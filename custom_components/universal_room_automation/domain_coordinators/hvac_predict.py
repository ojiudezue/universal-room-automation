"""Predictive sensors and weather pre-conditioning for HVAC Coordinator.

Generates pre-cool/pre-heat likelihood, comfort violation risk,
per-zone demand, and daily outcome measurements.

v3.8.5-H4: Initial implementation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .hvac_const import (
    SEASON_SHOULDER,
    SEASON_SUMMER,
    SEASON_WINTER,
    SEASONAL_DEFAULTS,
)
from .hvac_override import OverrideArrester
from .hvac_preset import PresetManager
from .hvac_zones import ZoneManager
from .signals import EnergyConstraint

_LOGGER = logging.getLogger(__name__)

# Pre-conditioning thresholds
PRECOOL_FORECAST_HIGH: float = 90.0  # F — trigger pre-cool above this
PREHEAT_FORECAST_LOW: float = 35.0  # F — trigger pre-heat below this
PRECOOL_SOC_MIN: int = 30  # % — minimum battery SOC to allow pre-cool
PEAK_HOUR_START: int = 14  # 2PM — peak window start
PEAK_HOUR_END: int = 19  # 7PM — peak window end
PRECOOL_LEAD_HOURS: int = 2  # hours before peak to start pre-cooling
PREHEAT_LEAD_HOURS: int = 1  # hours before off-peak ends to start pre-heating
OFF_PEAK_END_HOUR: int = 6  # 6AM — typical off-peak end


@dataclass
class HVACOutcome:
    """Daily outcome measurement for HVAC performance."""

    date: str
    zone_satisfaction_pct: float  # % of cycle checks where zones were in-band
    total_overrides: int
    total_ac_resets: int
    energy_mode_minutes: dict[str, int]  # mode -> minutes spent in that mode
    pre_cool_triggered: bool
    pre_heat_triggered: bool


class HVACPredictor:
    """Generates predictive HVAC data and triggers pre-conditioning.

    Called from the HVAC decision cycle every 5 minutes.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        zone_manager: ZoneManager,
        preset_manager: PresetManager,
        override_arrester: OverrideArrester | None = None,
    ) -> None:
        """Initialize predictor."""
        self.hass = hass
        self._zone_manager = zone_manager
        self._preset_manager = preset_manager
        self._override_arrester = override_arrester

        # Current predictions
        self._pre_cool_likelihood: int = 0
        self._comfort_violation_risk: str = "low"
        self._zone_demand: dict[str, str] = {}  # zone_id -> "low"|"medium"|"high"

        # Pre-conditioning state
        self._pre_cool_active: bool = False
        self._pre_heat_active: bool = False
        self._pre_cool_triggered_today: bool = False
        self._pre_heat_triggered_today: bool = False

        # Daily outcome tracking
        self._in_band_checks: int = 0
        self._total_checks: int = 0
        self._energy_mode_start: str = ""
        self._energy_mode_minutes: dict[str, int] = {}
        self._last_outcome_date: str = ""
        self._last_outcome: HVACOutcome | None = None

        # Outdoor temp sensor
        self._outdoor_temp_entity: str = ""

    def set_outdoor_temp_entity(self, entity_id: str) -> None:
        """Set outdoor temperature sensor entity."""
        self._outdoor_temp_entity = entity_id

    def flush_daily_outcome(self) -> None:
        """Store yesterday's outcome before zone counters are reset.

        Called from hvac.py's daily reset block so zone override/reset
        counts are captured before ZoneManager.reset_daily_counters() zeros them.
        """
        if self._last_outcome_date:
            self._store_daily_outcome()

    async def update(
        self,
        energy_constraint: EnergyConstraint | None,
        house_state: str,
    ) -> None:
        """Run prediction cycle.

        Called from the HVAC decision cycle every 5 minutes.
        """
        now = dt_util.now()

        # Daily reset (outcome storage is done via flush_daily_outcome()
        # called from hvac.py before zone counters are zeroed)
        today = now.date().isoformat()
        if today != self._last_outcome_date:
            self._last_outcome_date = today
            self._in_band_checks = 0
            self._total_checks = 0
            self._energy_mode_minutes.clear()
            self._pre_cool_triggered_today = False
            self._pre_heat_triggered_today = False
            self._pre_cool_active = False
            self._pre_heat_active = False

        # Track energy mode time
        if energy_constraint:
            mode = energy_constraint.mode
            self._energy_mode_minutes[mode] = (
                self._energy_mode_minutes.get(mode, 0) + 5
            )

        # Update predictions
        self._update_pre_cool_likelihood(energy_constraint, now)
        self._update_comfort_violation_risk(energy_constraint)
        self._update_zone_demand(now)
        self._track_zone_satisfaction()

        # Check pre-conditioning triggers
        await self._check_pre_conditioning(energy_constraint, house_state, now)

    def _update_pre_cool_likelihood(
        self,
        constraint: EnergyConstraint | None,
        now,
    ) -> None:
        """Compute pre-cool likelihood percentage.

        Combines: forecast high temp, TOU peak proximity, battery SOC.
        """
        likelihood = 0
        forecast_high = constraint.forecast_high_temp if constraint else None

        # Forecast temperature component (0-40%)
        if forecast_high is not None:
            if forecast_high >= PRECOOL_FORECAST_HIGH + 10:
                likelihood += 40
            elif forecast_high >= PRECOOL_FORECAST_HIGH:
                pct = (forecast_high - PRECOOL_FORECAST_HIGH) / 10
                likelihood += int(pct * 40)

        # Time proximity to peak (0-30%)
        hour = now.hour
        hours_to_peak = PEAK_HOUR_START - hour
        if 0 < hours_to_peak <= PRECOOL_LEAD_HOURS:
            likelihood += 30
        elif hours_to_peak == 0 or (PEAK_HOUR_START <= hour < PEAK_HOUR_END):
            likelihood += 15  # Already in peak

        # Battery SOC component (0-20%)
        soc = constraint.soc if constraint else None
        if soc is not None:
            if soc < PRECOOL_SOC_MIN:
                likelihood += 20  # Low battery = more reason to pre-cool
            elif soc < 50:
                likelihood += 10

        # Season bonus (0-10%)
        season = self._preset_manager.current_season
        if season == SEASON_SUMMER:
            likelihood += 10

        self._pre_cool_likelihood = min(likelihood, 100)

    def _update_comfort_violation_risk(
        self, constraint: EnergyConstraint | None,
    ) -> None:
        """Compute comfort violation risk level.

        Based on current energy constraint mode and zone conditions.
        """
        if constraint is None or constraint.mode == "normal":
            self._comfort_violation_risk = "low"
            return

        # Check zone temperatures against setpoints
        violation_count = 0
        for zone in self._zone_manager.zones.values():
            if zone.current_temperature is None or zone.target_temp_high is None:
                continue
            delta = zone.current_temperature - zone.target_temp_high
            if delta > 2.0:
                violation_count += 1

        if violation_count >= 2 or constraint.mode == "shed":
            self._comfort_violation_risk = "high"
        elif violation_count >= 1 or constraint.mode == "coast":
            self._comfort_violation_risk = "medium"
        else:
            self._comfort_violation_risk = "low"

    def _update_zone_demand(self, now) -> None:
        """Compute per-zone demand based on outdoor trend and indoor delta."""
        outdoor_temp = self._get_outdoor_temp()
        self._zone_demand.clear()

        for zone_id, zone in self._zone_manager.zones.items():
            if zone.current_temperature is None or zone.target_temp_high is None:
                self._zone_demand[zone_id] = "unknown"
                continue

            indoor_delta = zone.current_temperature - zone.target_temp_high

            # Factor outdoor temperature
            outdoor_factor = 0
            if outdoor_temp is not None:
                if outdoor_temp > 95:
                    outdoor_factor = 2
                elif outdoor_temp > 85:
                    outdoor_factor = 1

            # Demand level
            total = indoor_delta + outdoor_factor
            if total >= 4:
                self._zone_demand[zone_id] = "high"
            elif total >= 2:
                self._zone_demand[zone_id] = "medium"
            else:
                self._zone_demand[zone_id] = "low"

    def _track_zone_satisfaction(self) -> None:
        """Track how many zones are within comfortable range."""
        self._total_checks += 1
        all_in_band = True

        for zone in self._zone_manager.zones.values():
            if zone.current_temperature is None:
                continue
            if zone.target_temp_high is not None:
                if zone.current_temperature > zone.target_temp_high + 2:
                    all_in_band = False
            if zone.target_temp_low is not None:
                if zone.current_temperature < zone.target_temp_low - 2:
                    all_in_band = False

        if all_in_band:
            self._in_band_checks += 1

    async def _check_pre_conditioning(
        self,
        constraint: EnergyConstraint | None,
        house_state: str,
        now,
    ) -> None:
        """Trigger pre-cooling or pre-heating based on forecast.

        Pre-cool: forecast high > threshold AND peak approaching AND energy allows.
        Pre-heat: forecast low < threshold AND off-peak ending.
        """
        hour = now.hour
        season = self._preset_manager.current_season

        # Skip if away/vacation
        if house_state in ("away", "vacation"):
            return

        forecast_high = constraint.forecast_high_temp if constraint else None
        soc = constraint.soc if constraint else None

        # Pre-cool check (summer/shoulder, before peak)
        if (
            not self._pre_cool_active
            and not self._pre_cool_triggered_today
            and season in (SEASON_SUMMER, SEASON_SHOULDER)
            and forecast_high is not None
            and forecast_high >= PRECOOL_FORECAST_HIGH
            and PEAK_HOUR_START - PRECOOL_LEAD_HOURS <= hour < PEAK_HOUR_START
            and (soc is None or soc >= PRECOOL_SOC_MIN)
        ):
            self._pre_cool_active = True
            self._pre_cool_triggered_today = True
            _LOGGER.info(
                "HVAC Pre-cool triggered: forecast_high=%.0fF, hour=%d, soc=%s",
                forecast_high, hour, soc,
            )
            await self._execute_pre_cool()

        # End pre-cool when peak starts
        if self._pre_cool_active and hour >= PEAK_HOUR_START:
            self._pre_cool_active = False
            _LOGGER.info("HVAC Pre-cool ended: peak period started")

        # Pre-heat check (winter, before off-peak ends)
        outdoor_temp = self._get_outdoor_temp()
        if (
            not self._pre_heat_active
            and not self._pre_heat_triggered_today
            and season == SEASON_WINTER
            and outdoor_temp is not None
            and outdoor_temp <= PREHEAT_FORECAST_LOW
            and OFF_PEAK_END_HOUR - PREHEAT_LEAD_HOURS <= hour < OFF_PEAK_END_HOUR
        ):
            self._pre_heat_active = True
            self._pre_heat_triggered_today = True
            _LOGGER.info(
                "HVAC Pre-heat triggered: outdoor=%.0fF, hour=%d",
                outdoor_temp, hour,
            )
            await self._execute_pre_heat()

        # End pre-heat when off-peak ends
        if self._pre_heat_active and hour >= OFF_PEAK_END_HOUR:
            self._pre_heat_active = False
            _LOGGER.info("HVAC Pre-heat ended: off-peak period ended")

    async def _execute_pre_cool(self) -> None:
        """Lower cooling setpoints to pre-cool before peak."""
        for zone in self._zone_manager.zones.values():
            if not zone.any_room_occupied:
                continue
            if zone.target_temp_high is None or zone.target_temp_low is None:
                continue

            pre_cool_temp = zone.target_temp_high - 2  # Lower by 2F from current

            # Suppress override arrester for this change
            if self._override_arrester:
                self._override_arrester.suppress(zone.climate_entity)

            try:
                await self.hass.services.async_call(
                    "climate", "set_temperature",
                    {
                        "entity_id": zone.climate_entity,
                        "target_temp_high": pre_cool_temp,
                        "target_temp_low": zone.target_temp_low,
                    },
                    blocking=False,
                )
                _LOGGER.info(
                    "HVAC Pre-cool: %s set to %.0fF (was %.0fF)",
                    zone.zone_name, pre_cool_temp, zone.target_temp_high,
                )
            except Exception as e:
                _LOGGER.error("HVAC Pre-cool failed on %s: %s",
                              zone.climate_entity, e)

    async def _execute_pre_heat(self) -> None:
        """Raise heating setpoints to pre-heat before on-peak."""
        for zone in self._zone_manager.zones.values():
            if not zone.any_room_occupied:
                continue
            if zone.target_temp_high is None or zone.target_temp_low is None:
                continue

            pre_heat_temp = zone.target_temp_low + 2  # Raise by 2F from current

            # Suppress override arrester for this change
            if self._override_arrester:
                self._override_arrester.suppress(zone.climate_entity)

            try:
                await self.hass.services.async_call(
                    "climate", "set_temperature",
                    {
                        "entity_id": zone.climate_entity,
                        "target_temp_high": zone.target_temp_high,
                        "target_temp_low": pre_heat_temp,
                    },
                    blocking=False,
                )
                _LOGGER.info(
                    "HVAC Pre-heat: %s set to %.0fF (was %.0fF)",
                    zone.zone_name, pre_heat_temp, zone.target_temp_low,
                )
            except Exception as e:
                _LOGGER.error("HVAC Pre-heat failed on %s: %s",
                              zone.climate_entity, e)

    def _store_daily_outcome(self) -> None:
        """Store daily outcome measurement."""
        satisfaction = (
            (self._in_band_checks / self._total_checks * 100)
            if self._total_checks > 0
            else 100.0
        )
        total_overrides = sum(
            z.override_count_today for z in self._zone_manager.zones.values()
        )
        total_resets = sum(
            z.ac_reset_count_today for z in self._zone_manager.zones.values()
        )
        self._last_outcome = HVACOutcome(
            date=self._last_outcome_date,
            zone_satisfaction_pct=round(satisfaction, 1),
            total_overrides=total_overrides,
            total_ac_resets=total_resets,
            energy_mode_minutes=dict(self._energy_mode_minutes),
            pre_cool_triggered=self._pre_cool_triggered_today,
            pre_heat_triggered=self._pre_heat_triggered_today,
        )
        _LOGGER.info(
            "HVAC Daily Outcome: satisfaction=%.1f%%, overrides=%d, resets=%d",
            satisfaction, total_overrides, total_resets,
        )

    def _get_outdoor_temp(self) -> float | None:
        """Read outdoor temperature."""
        if not self._outdoor_temp_entity:
            return None
        state = self.hass.states.get(self._outdoor_temp_entity)
        if state is None or state.state in ("unavailable", "unknown"):
            return None
        try:
            return float(state.state)
        except (ValueError, TypeError):
            return None

    # =========================================================================
    # Public accessors for sensors
    # =========================================================================

    @property
    def pre_cool_likelihood(self) -> int:
        """Return pre-cool likelihood percentage."""
        return self._pre_cool_likelihood

    @property
    def comfort_violation_risk(self) -> str:
        """Return comfort violation risk level."""
        return self._comfort_violation_risk

    @property
    def pre_cool_active(self) -> bool:
        """Return whether pre-cooling is active."""
        return self._pre_cool_active

    @property
    def pre_heat_active(self) -> bool:
        """Return whether pre-heating is active."""
        return self._pre_heat_active

    def get_zone_demand(self, zone_id: str) -> str:
        """Return demand level for a zone."""
        return self._zone_demand.get(zone_id, "unknown")

    def get_prediction_attrs(self) -> dict[str, Any]:
        """Return prediction attributes for sensor."""
        return {
            "pre_cool_likelihood": self._pre_cool_likelihood,
            "comfort_violation_risk": self._comfort_violation_risk,
            "pre_cool_active": self._pre_cool_active,
            "pre_heat_active": self._pre_heat_active,
            "pre_cool_triggered_today": self._pre_cool_triggered_today,
            "pre_heat_triggered_today": self._pre_heat_triggered_today,
            "zone_demand": dict(self._zone_demand),
        }

    def get_outcome_attrs(self) -> dict[str, Any]:
        """Return daily outcome for sensor."""
        if self._last_outcome is None:
            satisfaction = (
                (self._in_band_checks / self._total_checks * 100)
                if self._total_checks > 0
                else 100.0
            )
            return {
                "zone_satisfaction_pct": round(satisfaction, 1),
                "total_checks_today": self._total_checks,
                "in_band_checks_today": self._in_band_checks,
                "energy_mode_minutes": dict(self._energy_mode_minutes),
            }
        return {
            "date": self._last_outcome.date,
            "zone_satisfaction_pct": self._last_outcome.zone_satisfaction_pct,
            "total_overrides": self._last_outcome.total_overrides,
            "total_ac_resets": self._last_outcome.total_ac_resets,
            "energy_mode_minutes": self._last_outcome.energy_mode_minutes,
            "pre_cool_triggered": self._last_outcome.pre_cool_triggered,
            "pre_heat_triggered": self._last_outcome.pre_heat_triggered,
        }
