"""Battery strategy for Energy Coordinator.

Reads battery SOC, solar production, and grid state from Enphase entities.
Determines optimal battery storage mode based on TOU period and conditions.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant

from .energy_const import (
    BATTERY_MODE_BACKUP,
    BATTERY_MODE_SAVINGS,
    BATTERY_MODE_SELF_CONSUMPTION,
    DEFAULT_BATTERY_POWER_ENTITY,
    DEFAULT_BATTERY_SOC_ENTITY,
    DEFAULT_CHARGE_FROM_GRID_ENTITY,
    DEFAULT_GRID_ENABLED_ENTITY,
    DEFAULT_NET_POWER_ENTITY,
    DEFAULT_RESERVE_SOC,
    DEFAULT_RESERVE_SOC_ENTITY,
    DEFAULT_SOLAR_PRODUCTION_ENTITY,
    DEFAULT_SOLCAST_REMAINING_ENTITY,
    DEFAULT_SOLCAST_TODAY_ENTITY,
    DEFAULT_STORAGE_MODE_ENTITY,
    DEFAULT_STORM_CHARGE_THRESHOLD,
    DEFAULT_WEATHER_ENTITY,
    SOLAR_DAY_THRESHOLDS,
    SOLAR_MONTHLY_THRESHOLDS,
)

_LOGGER = logging.getLogger(__name__)


class BatteryStrategy:
    """Determines battery mode and actions based on TOU period and system state."""

    def __init__(
        self,
        hass: HomeAssistant,
        reserve_soc: int = DEFAULT_RESERVE_SOC,
        entity_config: dict[str, str] | None = None,
        solar_classification_mode: str = "automatic",
        custom_solar_thresholds: dict[str, float] | None = None,
    ) -> None:
        """Initialize battery strategy."""
        self.hass = hass
        self.reserve_soc = reserve_soc
        self._entities = entity_config or {}
        self._last_mode: str | None = None
        self._last_reason: str = ""
        self._solar_classification_mode = solar_classification_mode
        self._custom_solar_thresholds = custom_solar_thresholds

    def _get_entity(self, key: str, default: str) -> str:
        """Get entity ID from config or default."""
        return self._entities.get(key, default)

    def _get_state_float(self, entity_id: str) -> float | None:
        """Get numeric state from an entity."""
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unknown", "unavailable"):
            return None
        try:
            return float(state.state)
        except (ValueError, TypeError):
            return None

    def _get_state_str(self, entity_id: str) -> str | None:
        """Get string state from an entity."""
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unknown", "unavailable"):
            return None
        return state.state

    def _get_state_bool(self, entity_id: str) -> bool | None:
        """Get boolean state from a switch entity."""
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unknown", "unavailable"):
            return None
        return state.state == "on"

    @property
    def battery_soc(self) -> float | None:
        """Current battery state of charge (%)."""
        return self._get_state_float(
            self._get_entity("battery_soc", DEFAULT_BATTERY_SOC_ENTITY)
        )

    @property
    def solar_production(self) -> float | None:
        """Current solar production in watts."""
        return self._get_state_float(
            self._get_entity("solar_production", DEFAULT_SOLAR_PRODUCTION_ENTITY)
        )

    @property
    def net_power(self) -> float | None:
        """Net power consumption (positive=importing, negative=exporting)."""
        return self._get_state_float(
            self._get_entity("net_power", DEFAULT_NET_POWER_ENTITY)
        )

    @property
    def battery_power(self) -> float | None:
        """Battery power (positive=charging, negative=discharging)."""
        return self._get_state_float(
            self._get_entity("battery_power", DEFAULT_BATTERY_POWER_ENTITY)
        )

    @property
    def current_storage_mode(self) -> str | None:
        """Current Enpower storage mode."""
        return self._get_state_str(
            self._get_entity("storage_mode", DEFAULT_STORAGE_MODE_ENTITY)
        )

    @property
    def grid_connected(self) -> bool:
        """Whether grid is connected."""
        result = self._get_state_bool(
            self._get_entity("grid_enabled", DEFAULT_GRID_ENABLED_ENTITY)
        )
        return result if result is not None else True

    @property
    def solcast_today(self) -> float | None:
        """Solcast forecast for today in kWh."""
        return self._get_state_float(
            self._get_entity("solcast_today", DEFAULT_SOLCAST_TODAY_ENTITY)
        )

    @property
    def solcast_remaining(self) -> float | None:
        """Solcast remaining forecast for today in kWh."""
        return self._get_state_float(
            self._get_entity("solcast_remaining", DEFAULT_SOLCAST_REMAINING_ENTITY)
        )

    def classify_solar_day(self) -> str:
        """Classify today's solar forecast: excellent/good/moderate/poor/very_poor.

        Uses per-month percentile thresholds by default, or custom absolute
        thresholds if configured.
        """
        forecast = self.solcast_today
        if forecast is None:
            return "unknown"

        if self._solar_classification_mode == "custom" and self._custom_solar_thresholds:
            for classification, threshold in sorted(
                self._custom_solar_thresholds.items(),
                key=lambda x: x[1],
                reverse=True,
            ):
                if forecast >= threshold:
                    return classification
            return "very_poor"

        # Automatic (monthly) mode — use per-month P25/P50/P75
        from homeassistant.util import dt as dt_util
        month = dt_util.now().month
        p25, p50, p75 = SOLAR_MONTHLY_THRESHOLDS.get(month, (50.0, 80.0, 100.0))
        if forecast >= p75:
            return "excellent"
        if forecast >= p50:
            return "good"
        if forecast >= p25:
            return "moderate"
        return "poor"

    def has_storm_forecast(self) -> bool:
        """Check weather entity for storm/severe weather conditions."""
        weather_entity = self._get_entity("weather", DEFAULT_WEATHER_ENTITY)
        state = self.hass.states.get(weather_entity)
        if state is None:
            return False
        condition = state.state.lower()
        storm_conditions = {
            "lightning", "lightning-rainy", "hail",
            "tornado", "hurricane", "exceptional",
        }
        return condition in storm_conditions

    @property
    def envoy_available(self) -> bool:
        """Whether the Envoy is responding (SOC and storage mode both readable)."""
        return self.battery_soc is not None and self.current_storage_mode is not None

    def determine_mode(
        self, tou_period: str, season: str = "summer"
    ) -> dict[str, Any]:
        """Determine optimal battery mode based on TOU period and conditions.

        Uses self_consumption mode exclusively with reserve level as primary control.
        See ENPHASE_CONTROL_CODICIL.md for rationale — Enphase does not support
        direct battery-to-grid export; savings mode gives up HA control.

        Season matters: shoulder/winter have no peak period, so mid-peak IS the
        highest-rate window.  Battery should discharge during mid-peak in those
        seasons rather than holding for a peak that never comes.

        Returns dict with: mode, reason, actions (list of service calls to make)
        """
        soc = self.battery_soc
        current_mode = self.current_storage_mode

        # Envoy offline — do NOT issue commands when blind.
        # Hold whatever state the system is in until we can read it again.
        if not self.envoy_available:
            _LOGGER.warning(
                "Envoy unavailable (SOC=%s, mode=%s) — holding current state",
                soc, current_mode,
            )
            return {
                "mode": current_mode or "unknown",
                "reason": "Envoy unavailable — holding (no commands issued)",
                "actions": [],
                "soc": soc,
                "solar_production": self.solar_production,
                "net_power": self.net_power,
                "solar_day_class": self.classify_solar_day(),
                "envoy_available": False,
                "season": season,
            }

        # Grid disconnected — emergency backup
        if not self.grid_connected:
            return self._result(
                BATTERY_MODE_BACKUP,
                "Grid disconnected — backup mode",
                current_mode,
                season=season,
            )

        # Storm forecast — pre-charge and prepare for outage
        if self.has_storm_forecast():
            if soc is not None and soc < DEFAULT_STORM_CHARGE_THRESHOLD:
                return self._result(
                    BATTERY_MODE_SELF_CONSUMPTION,
                    f"Storm forecast — pre-charging (SOC {soc}%)",
                    current_mode,
                    charge_from_grid=True,
                    reserve_level=self.reserve_soc,
                    season=season,
                )
            # Already charged enough — switch to backup to hold charge
            return self._result(
                BATTERY_MODE_BACKUP,
                f"Storm forecast — holding charge (SOC {soc}%)",
                current_mode,
                season=season,
            )

        # Peak period — battery covers home load, solar exports
        # Strategy 3 from codicil: self_consumption + low reserve
        if tou_period == "peak":
            if soc is not None and soc > self.reserve_soc:
                return self._result(
                    BATTERY_MODE_SELF_CONSUMPTION,
                    "Peak — battery covers load, solar exports",
                    current_mode,
                    reserve_level=self.reserve_soc,
                    season=season,
                )
            return self._result(
                BATTERY_MODE_SELF_CONSUMPTION,
                f"Peak but SOC low ({soc}%) — minimal discharge",
                current_mode,
                reserve_level=max(int(soc or 0) - 5, self.reserve_soc),
                season=season,
            )

        # Mid-peak strategy depends on season:
        # - Summer: hold battery for upcoming peak (mid-peak is a bridge)
        # - Shoulder/Winter: mid-peak IS the highest-rate period (no peak exists).
        #   Discharge battery to cover load; solar exports at $0.086/kWh.
        if tou_period == "mid_peak":
            if season == "summer":
                # Summer mid-peak: hold charge for upcoming peak
                hold_reserve = int(soc) if soc is not None else 100
                return self._result(
                    BATTERY_MODE_SELF_CONSUMPTION,
                    "Mid-peak (summer) — holding charge for peak",
                    current_mode,
                    reserve_level=hold_reserve,
                    season=season,
                )
            # Shoulder/Winter mid-peak: discharge — this is the best rate window
            if soc is not None and soc > self.reserve_soc:
                return self._result(
                    BATTERY_MODE_SELF_CONSUMPTION,
                    f"Mid-peak ({season}) — discharging, best rate window",
                    current_mode,
                    reserve_level=self.reserve_soc,
                    season=season,
                )
            return self._result(
                BATTERY_MODE_SELF_CONSUMPTION,
                f"Mid-peak ({season}) but SOC low ({soc}%) — minimal discharge",
                current_mode,
                reserve_level=max(int(soc or 0) - 5, self.reserve_soc),
                season=season,
            )

        # Off-peak — charge from solar, low reserve allows full charging
        return self._result(
            BATTERY_MODE_SELF_CONSUMPTION,
            "Off-peak — charging from solar",
            current_mode,
            reserve_level=self.reserve_soc,
            season=season,
        )

    def _result(
        self,
        mode: str,
        reason: str,
        current_mode: str | None,
        charge_from_grid: bool = False,
        reserve_level: int | None = None,
        season: str | None = None,
    ) -> dict[str, Any]:
        """Build battery decision result with actions.

        Uses reserve level as the primary control lever per Enphase codicil.
        Mode changes happen first, then reserve adjustment, then charge_from_grid.
        60-90s buffer built into decision cycle (5min interval) accommodates Enphase latency.
        """
        actions: list[dict[str, Any]] = []

        # 1. Storage mode — only change if different from current
        if current_mode is not None and mode != current_mode:
            actions.append({
                "service": "select.select_option",
                "target": self._get_entity("storage_mode", DEFAULT_STORAGE_MODE_ENTITY),
                "data": {"option": mode},
            })

        # 2. Reserve level — primary control lever
        if reserve_level is not None:
            current_reserve = self._get_state_float(
                self._get_entity("reserve_soc_number", DEFAULT_RESERVE_SOC_ENTITY)
            )
            target_reserve = max(0, min(100, reserve_level))
            if current_reserve is None or abs(current_reserve - target_reserve) >= 2:
                actions.append({
                    "service": "number.set_value",
                    "target": self._get_entity(
                        "reserve_soc_number", DEFAULT_RESERVE_SOC_ENTITY
                    ),
                    "data": {"value": target_reserve},
                })

        # 3. Charge from grid control
        if charge_from_grid:
            current_cfg = self._get_state_bool(
                self._get_entity("charge_from_grid", DEFAULT_CHARGE_FROM_GRID_ENTITY)
            )
            if current_cfg is not True:
                actions.append({
                    "service": "switch.turn_on",
                    "target": self._get_entity(
                        "charge_from_grid", DEFAULT_CHARGE_FROM_GRID_ENTITY
                    ),
                    "data": {},
                })
        else:
            current_cfg = self._get_state_bool(
                self._get_entity("charge_from_grid", DEFAULT_CHARGE_FROM_GRID_ENTITY)
            )
            if current_cfg is True:
                actions.append({
                    "service": "switch.turn_off",
                    "target": self._get_entity(
                        "charge_from_grid", DEFAULT_CHARGE_FROM_GRID_ENTITY
                    ),
                    "data": {},
                })

        self._last_mode = mode
        self._last_reason = reason

        return {
            "mode": mode,
            "reason": reason,
            "actions": actions,
            "soc": self.battery_soc,
            "solar_production": self.solar_production,
            "net_power": self.net_power,
            "solar_day_class": self.classify_solar_day(),
            "envoy_available": True,
            "season": season,
        }

    def get_status(self) -> dict[str, Any]:
        """Return current battery strategy status for sensor."""
        return {
            "mode": self._last_mode or self.current_storage_mode or "unknown",
            "reason": self._last_reason or "initializing",
            "soc": self.battery_soc,
            "solar_production": self.solar_production,
            "net_power": self.net_power,
            "battery_power": self.battery_power,
            "grid_connected": self.grid_connected,
            "envoy_available": self.envoy_available,
            "solar_day_class": self.classify_solar_day(),
            "storm_forecast": self.has_storm_forecast(),
            "reserve_soc": self.reserve_soc,
        }
