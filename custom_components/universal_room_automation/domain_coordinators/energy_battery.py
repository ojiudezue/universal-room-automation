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
    BATTERY_MODE_SELF_CONSUMPTION,
    DEFAULT_ARBITRAGE_SOC_TARGET,
    DEFAULT_ARBITRAGE_SOC_TRIGGER,
    DEFAULT_CHARGE_FROM_GRID_ENTITY,
    DEFAULT_GRID_ENABLED_ENTITY,
    DEFAULT_OFFPEAK_DRAIN_EXCELLENT,
    DEFAULT_OFFPEAK_DRAIN_GOOD,
    DEFAULT_OFFPEAK_DRAIN_MODERATE,
    DEFAULT_OFFPEAK_DRAIN_POOR,
    DEFAULT_OFFPEAK_DRAIN_UNKNOWN,
    DEFAULT_RESERVE_SOC,
    DEFAULT_RESERVE_SOC_ENTITY,
    DEFAULT_SOLCAST_REMAINING_ENTITY,
    DEFAULT_SOLCAST_TODAY_ENTITY,
    DEFAULT_SOLCAST_TOMORROW_ENTITY,
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
        offpeak_drain_targets: dict[str, int] | None = None,
        arbitrage_enabled: bool = False,
        arbitrage_soc_trigger: int = DEFAULT_ARBITRAGE_SOC_TRIGGER,
        arbitrage_soc_target: int = DEFAULT_ARBITRAGE_SOC_TARGET,
    ) -> None:
        """Initialize battery strategy."""
        self.hass = hass
        self.reserve_soc = reserve_soc
        self._entities = entity_config or {}
        self._last_mode: str | None = None
        self._last_reason: str = ""
        self._solar_classification_mode = solar_classification_mode
        self._custom_solar_thresholds = custom_solar_thresholds

        # Phase A: Off-peak drain targets by tomorrow's solar class
        dt = offpeak_drain_targets or {}
        self._drain_targets: dict[str, int] = {
            "excellent": dt.get("excellent", DEFAULT_OFFPEAK_DRAIN_EXCELLENT),
            "good": dt.get("good", DEFAULT_OFFPEAK_DRAIN_GOOD),
            "moderate": dt.get("moderate", DEFAULT_OFFPEAK_DRAIN_MODERATE),
            "poor": dt.get("poor", DEFAULT_OFFPEAK_DRAIN_POOR),
            "very_poor": dt.get("very_poor", dt.get("poor", DEFAULT_OFFPEAK_DRAIN_POOR)),
            "unknown": dt.get("unknown", DEFAULT_OFFPEAK_DRAIN_UNKNOWN),
        }

        # Phase B: Grid charge arbitrage
        self._arbitrage_enabled = arbitrage_enabled
        self._arbitrage_trigger = arbitrage_soc_trigger
        self._arbitrage_target = arbitrage_soc_target
        self._arbitrage_active = False

    def _get_entity(self, key: str, default: str | None = None) -> str | None:
        """Get entity ID from config or default.

        v4.3.1: default is now optional (None). Envoy-derived entities have
        no production default — they MUST come via config (auto-derive seeds
        them in __init__.py). Non-envoy entities (Solcast, Enpower, Weather)
        still pass their hardcoded defaults explicitly.
        """
        return self._entities.get(key, default)

    def _get_state_float(self, entity_id: str | None) -> float | None:
        """Get numeric state from an entity. None entity_id → None."""
        if entity_id is None:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unknown", "unavailable"):
            return None
        try:
            return float(state.state)
        except (ValueError, TypeError):
            return None

    def _get_state_str(self, entity_id: str | None) -> str | None:
        """Get string state from an entity. None entity_id → None."""
        if entity_id is None:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unknown", "unavailable"):
            return None
        return state.state

    def _get_state_bool(self, entity_id: str | None) -> bool | None:
        """Get boolean state from a switch entity. None entity_id → None."""
        if entity_id is None:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unknown", "unavailable"):
            return None
        return state.state == "on"

    @property
    def battery_soc(self) -> float | None:
        """Current battery state of charge (%). None if envoy not configured."""
        return self._get_state_float(self._get_entity("battery_soc"))

    @property
    def solar_production(self) -> float | None:
        """Current solar production in watts. None if envoy not configured."""
        return self._get_state_float(self._get_entity("solar_production"))

    @property
    def net_power(self) -> float | None:
        """Net power consumption (positive=importing, negative=exporting).

        None if envoy not configured.
        """
        return self._get_state_float(self._get_entity("net_power"))

    @property
    def battery_power(self) -> float | None:
        """Battery power (positive=charging, negative=discharging).

        The new Envoy ``current_battery_discharge`` sensor uses the opposite
        sign convention (positive=discharging), so we negate it here to keep
        the rest of the codebase consistent.

        UNITS: returned as-is from the underlying entity (some Envoy installs
        report W, newer ones report kW). For unit-correct math, use
        :py:attr:`battery_power_w` instead. This raw value is what's shown on
        the strategy sensor display for backward compatibility.
        """
        raw = self._get_state_float(self._get_entity("battery_power"))
        return -raw if raw is not None else None

    @property
    def battery_power_w(self) -> float | None:
        """Battery power normalized to W (positive=charging, negative=discharging).

        v4.3.4 fix: reads the underlying entity's ``unit_of_measurement``
        attribute and multiplies by 1000 if the entity reports in kW.
        Use this for any threshold math (e.g., "is the battery discharging
        more than 100W?") so behavior is correct regardless of Envoy
        firmware/integration version.

        Returns None if entity is missing/unavailable.
        """
        eid = self._get_entity("battery_power")
        if eid is None:
            return None
        state = self.hass.states.get(eid)
        if state is None or state.state in ("unknown", "unavailable"):
            return None
        try:
            value = -float(state.state)  # flip sign per battery_power convention
        except (ValueError, TypeError):
            return None
        uom = state.attributes.get("unit_of_measurement", "")
        if uom in ("kW", "kw"):
            value *= 1000.0
        return value

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

    @property
    def solcast_tomorrow(self) -> float | None:
        """Solcast forecast for tomorrow in kWh."""
        return self._get_state_float(
            self._get_entity("solcast_tomorrow", DEFAULT_SOLCAST_TOMORROW_ENTITY)
        )

    def classify_tomorrow_solar(self) -> str:
        """Classify tomorrow's solar forecast using per-month thresholds.

        Same logic as classify_solar_day() but reads the tomorrow entity
        and uses tomorrow's month for threshold lookup.
        """
        forecast = self.solcast_tomorrow
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

        from homeassistant.util import dt as dt_util
        from datetime import timedelta
        tomorrow = (dt_util.now() + timedelta(days=1)).month
        p25, p50, p75 = SOLAR_MONTHLY_THRESHOLDS.get(tomorrow, (50.0, 80.0, 100.0))
        if forecast >= p75:
            return "excellent"
        if forecast >= p50:
            return "good"
        if forecast >= p25:
            return "moderate"
        return "poor"

    def _get_offpeak_drain_target(self, tomorrow_class: str) -> int:
        """Get the SOC drain target for off-peak based on tomorrow's solar class."""
        return self._drain_targets.get(tomorrow_class, DEFAULT_OFFPEAK_DRAIN_UNKNOWN)

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
            # v4.3.0 D1 cosmetic fix: keep in-memory _arbitrage_active in sync
            # with the returned dict so the sensor doesn't show "arbitrage_active=False"
            # while the in-memory state still says True. When envoy comes back the
            # next decision cycle will re-evaluate and re-set as needed.
            self._arbitrage_active = False
            return {
                "mode": current_mode or "unknown",
                "reason": "Envoy unavailable — holding (no commands issued)",
                "actions": [],
                "soc": soc,
                "solar_production": self.solar_production,
                "net_power": self.net_power,
                "battery_power": self.battery_power,
                "solar_day_class": self.classify_solar_day(),
                "tomorrow_solar_class": "unknown",
                "envoy_available": False,
                "season": season,
                "arbitrage_active": False,
                "arbitrage_enabled": self._arbitrage_enabled,
                "reserve_soc": self.reserve_soc,
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

        # Off-peak — SOC-conditional drain with optional arbitrage
        # Guard: only run off-peak logic for recognized off_peak period
        if tou_period != "off_peak":
            # Unrecognized period — treat as off-peak with conservative behavior
            _LOGGER.warning("Unexpected TOU period '%s' — treating as off-peak", tou_period)
        tomorrow_class = self.classify_tomorrow_solar()

        # Phase B: Grid charge arbitrage check (before drain logic)
        # If tomorrow is poor and SOC is low, charge from grid at off-peak rate
        if (
            self._arbitrage_enabled
            and soc is not None
            and soc < self._arbitrage_trigger
            and tomorrow_class in ("poor", "very_poor")
        ):
            self._arbitrage_active = True
            return self._result(
                BATTERY_MODE_SELF_CONSUMPTION,
                f"Off-peak arbitrage — grid charging (SOC {soc}%, tomorrow {tomorrow_class})",
                current_mode,
                charge_from_grid=True,
                # v4.3.0 D1 CRITICAL fix: was self.reserve_soc (the user's safety
                # floor, e.g. 10%) which made Enphase see "SOC=floor, reserve=floor,
                # hold" → never imported. Setting reserve to the arbitrage target
                # tells Enphase "pull from grid up to this level, then hold" —
                # which is what self_consumption + charge_from_grid actually requires.
                # Latent since v3.11.0; battery has never charged via arbitrage.
                reserve_level=self._arbitrage_target,
                season=season,
                tomorrow_solar_class=tomorrow_class,
                arbitrage_active=True,
            )

        # Stop arbitrage when SOC reaches target
        if self._arbitrage_active:
            if soc is not None and soc >= self._arbitrage_target:
                self._arbitrage_active = False
            else:
                # Still in arbitrage range — keep charging
                return self._result(
                    BATTERY_MODE_SELF_CONSUMPTION,
                    f"Off-peak arbitrage — continuing (SOC {soc}%, target {self._arbitrage_target}%)",
                    current_mode,
                    charge_from_grid=True,
                    # v4.3.0 D1 CRITICAL fix (continuation path): see comment above.
                    reserve_level=self._arbitrage_target,
                    season=season,
                    tomorrow_solar_class=tomorrow_class,
                    arbitrage_active=True,
                )

        # Phase A: SOC-conditional drain
        drain_target = self._get_offpeak_drain_target(tomorrow_class)

        if soc is not None and soc > drain_target:
            # Above target — drain stored solar (free energy)
            return self._result(
                BATTERY_MODE_SELF_CONSUMPTION,
                f"Off-peak drain — SOC {soc}% > target {drain_target}% (tomorrow {tomorrow_class})",
                current_mode,
                reserve_level=drain_target,
                season=season,
                tomorrow_solar_class=tomorrow_class,
            )

        # At/below target — hold and import cheap grid
        hold_reserve = int(soc) if soc is not None else drain_target
        return self._result(
            BATTERY_MODE_SELF_CONSUMPTION,
            f"Off-peak hold — SOC {soc}% <= target {drain_target}% (tomorrow {tomorrow_class})",
            current_mode,
            reserve_level=hold_reserve,
            season=season,
            tomorrow_solar_class=tomorrow_class,
        )

    def _result(
        self,
        mode: str,
        reason: str,
        current_mode: str | None,
        charge_from_grid: bool = False,
        reserve_level: int | None = None,
        season: str | None = None,
        tomorrow_solar_class: str | None = None,
        arbitrage_active: bool = False,
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
            "tomorrow_solar_class": tomorrow_solar_class,
            "envoy_available": True,
            "season": season,
            "arbitrage_active": arbitrage_active,
            "arbitrage_enabled": self._arbitrage_enabled,
        }

    def _threshold_position(self, soc: float | None, tomorrow_class: str) -> str:
        """v4.3.0 D5: human-readable narration of where current SOC sits
        relative to all thresholds.
        """
        if soc is None:
            return "SOC unknown — Envoy not reporting"
        s = float(soc)
        if s <= self.reserve_soc:
            return (
                f"SOC={s:.0f}% at/below reserve_soc ({self.reserve_soc}%) — "
                f"safety floor reached, no further discharge"
            )
        if s < self._arbitrage_trigger:
            return (
                f"SOC={s:.0f}% below arbitrage_trigger ({self._arbitrage_trigger}%) — "
                f"arbitrage will activate next off-peak cycle if tomorrow=poor"
            )
        drain = self._drain_targets.get(tomorrow_class, self._drain_targets.get("unknown", 40))
        if s <= drain:
            return (
                f"SOC={s:.0f}% at/below drain_target ({drain}%, tomorrow={tomorrow_class}) — "
                f"will hold at SOC during off-peak"
            )
        return (
            f"SOC={s:.0f}% above drain_target ({drain}%, tomorrow={tomorrow_class}) — "
            f"will drain to target during off-peak"
        )

    def _next_action_estimate(self, soc: float | None, tomorrow_class: str) -> str:
        """v4.3.0 D5: short narration of expected next-cycle action."""
        if soc is None:
            return "no estimate — Envoy unavailable"
        if self._arbitrage_active:
            return (
                f"continue arbitrage charging until SOC reaches "
                f"target ({self._arbitrage_target}%)"
            )
        if (
            self._arbitrage_enabled
            and float(soc) < self._arbitrage_trigger
            and tomorrow_class in ("poor", "very_poor")
        ):
            return (
                f"activate arbitrage at next off-peak tick "
                f"(charge to {self._arbitrage_target}%)"
            )
        drain = self._drain_targets.get(tomorrow_class, self._drain_targets.get("unknown", 40))
        if float(soc) > drain:
            return f"drain to {drain}% during off-peak (tomorrow={tomorrow_class})"
        return "hold at current SOC"

    def get_status(self) -> dict[str, Any]:
        """Return current battery strategy status for sensor.

        v4.3.0 D3: includes threshold_warning when ladder is violated, plus
        the raw threshold values (arbitrage_trigger/target, drain_targets).
        v4.3.0 D5: includes threshold_position + next_action_estimate strings.
        """
        from .energy_const import validate_threshold_ladder
        warning = validate_threshold_ladder(
            self.reserve_soc,
            self._drain_targets,
            self._arbitrage_trigger,
            self._arbitrage_target,
        )
        soc = self.battery_soc
        tomorrow_class = self.classify_tomorrow_solar()
        return {
            "mode": self._last_mode or self.current_storage_mode or "unknown",
            "reason": self._last_reason or "initializing",
            "soc": soc,
            "solar_production": self.solar_production,
            "net_power": self.net_power,
            "battery_power": self.battery_power,
            "grid_connected": self.grid_connected,
            "envoy_available": self.envoy_available,
            "solar_day_class": self.classify_solar_day(),
            "tomorrow_solar_class": tomorrow_class,
            "storm_forecast": self.has_storm_forecast(),
            "reserve_soc": self.reserve_soc,
            "arbitrage_active": self._arbitrage_active,
            "arbitrage_enabled": self._arbitrage_enabled,
            "arbitrage_trigger": self._arbitrage_trigger,
            "arbitrage_target": self._arbitrage_target,
            "drain_targets": dict(self._drain_targets),
            "threshold_warning": warning,
            "threshold_position": self._threshold_position(soc, tomorrow_class),
            "next_action_estimate": self._next_action_estimate(soc, tomorrow_class),
        }
