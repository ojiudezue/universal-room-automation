"""Pool optimizer, EV charger controller, and smart plug manager for Energy Coordinator.

Sub-Cycle E2: Pool VSF speed reduction during peak, EV charging pause/resume,
additional controllable loads.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant

import time as _time

from .energy_const import (
    EVSE_CHARGING_POWER_THRESHOLD,
    EVSE_ESTIMATED_POWER_W,
    EV_BATTERY_DRAIN_COOLDOWN_SECONDS,
)

_LOGGER = logging.getLogger(__name__)

# ============================================================================
# Pool Optimizer
# ============================================================================

# Default Pentair entities (confirmed via HA)
DEFAULT_POOL_VSF_SPEED_ENTITY = "number.pentair_pool_variable_speed_pump_1_speed"
DEFAULT_SPA_VSF_SPEED_ENTITY = "number.pentair_spa_variable_speed_pump_1_speed"
DEFAULT_POOL_PUMP_POWER_ENTITY = "sensor.pentair_pool_variable_speed_pump_1_power"

# Pentair circuit switches for load shedding (stubbed)
DEFAULT_POOL_INFINITY_EDGE_ENTITY = "switch.pentair_feature_7"
DEFAULT_POOL_HEATER_ENTITY = "switch.pentair_heater_solar_preferred"

# Pool speed settings (GPM)
POOL_NORMAL_SPEED = 75
POOL_REDUCED_SPEED = 30
POOL_MIN_SPEED = 15

# Pool optimization states
POOL_STATE_NORMAL = "normal"
POOL_STATE_REDUCED = "reduced"
POOL_STATE_SHED = "shed"
POOL_STATE_OFF = "off"


class PoolOptimizer:
    """Manages pool pump VSF speed based on TOU period.

    Tier 1: Reduce VSF speed during peak (75→30 GPM, ~94% power savings)
    Tier 2: Shed infinity edge during peak (stubbed, off by default)
    Tier 3: Full shutdown (stubbed, off by default)
    """

    def __init__(
        self,
        hass: HomeAssistant,
        pool_speed_entity: str | None = None,
        pool_power_entity: str | None = None,
        load_shedding_enabled: bool = False,
    ) -> None:
        """Initialize pool optimizer."""
        self.hass = hass
        self._speed_entity = pool_speed_entity or DEFAULT_POOL_VSF_SPEED_ENTITY
        self._power_entity = pool_power_entity or DEFAULT_POOL_PUMP_POWER_ENTITY
        self._load_shedding_enabled = load_shedding_enabled
        self._state = POOL_STATE_NORMAL
        self._original_speed: float | None = None

    @property
    def state(self) -> str:
        """Current pool optimization state."""
        return self._state

    @property
    def current_speed(self) -> float | None:
        """Current VSF pump speed."""
        state = self.hass.states.get(self._speed_entity)
        if state is None or state.state in ("unknown", "unavailable"):
            return None
        try:
            return float(state.state)
        except (ValueError, TypeError):
            return None

    @property
    def current_power(self) -> float | None:
        """Current pump power consumption in watts."""
        state = self.hass.states.get(self._power_entity)
        if state is None or state.state in ("unknown", "unavailable"):
            return None
        try:
            return float(state.state)
        except (ValueError, TypeError):
            return None

    def determine_actions(self, tou_period: str) -> list[dict[str, Any]]:
        """Determine pool actions based on TOU period.

        Returns list of service call specs.
        """
        actions: list[dict[str, Any]] = []
        current = self.current_speed

        if tou_period == "peak":
            # Tier 1: Reduce speed
            if current is not None and current > POOL_REDUCED_SPEED:
                if self._original_speed is None:
                    self._original_speed = current
                actions.append({
                    "service": "number.set_value",
                    "target": self._speed_entity,
                    "data": {"value": POOL_REDUCED_SPEED},
                })
                self._state = POOL_STATE_REDUCED
                _LOGGER.info(
                    "Pool: reducing speed %d → %d GPM (peak TOU)",
                    int(current), POOL_REDUCED_SPEED,
                )
        else:
            # Restore normal speed on off-peak/mid-peak
            if self._state != POOL_STATE_NORMAL and self._original_speed is not None:
                restore_speed = self._original_speed
                if current is None:
                    # Entity temporarily unavailable — keep state, retry next cycle
                    _LOGGER.debug("Pool: speed entity unavailable, deferring restore")
                else:
                    actions.append({
                        "service": "number.set_value",
                        "target": self._speed_entity,
                        "data": {"value": restore_speed},
                    })
                    _LOGGER.info(
                        "Pool: restoring speed %d → %d GPM (off-peak)",
                        int(current), int(restore_speed),
                    )
                    self._original_speed = None
                    self._state = POOL_STATE_NORMAL

        return actions

    def get_status(self) -> dict[str, Any]:
        """Return pool optimizer status for sensor."""
        return {
            "state": self._state,
            "current_speed": self.current_speed,
            "current_power": self.current_power,
            "original_speed": self._original_speed,
        }


# ============================================================================
# EV Charger Controller
# ============================================================================

# Default Emporia EVSE entities (confirmed via HA)
DEFAULT_EVSE_ENTITIES = {
    "garage_a": {
        "switch": "switch.garage_a",
        "power": "sensor.garage_a_power_minute_average",
        "energy_today": "sensor.garage_a_energy_today",
        "energy_month": "sensor.garage_a_energy_this_month",
        "span_breaker": "switch.span_panel_car_charger_breaker",
    },
    "garage_b": {
        "switch": "switch.garage_b",
        "power": "sensor.garage_b_power_minute_average",
        "energy_today": "sensor.garage_b_energy_today",
        "energy_month": "sensor.garage_b_energy_this_month",
        "span_breaker": "switch.span_panel_garage_b_evse_breaker",
    },
}


class EVChargerController:
    """Controls EV chargers based on TOU period.

    Pauses charging during peak/mid-peak, resumes on off-peak.
    Tracks which chargers we paused so we only resume our own pauses.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        evse_config: dict[str, dict[str, str]] | None = None,
    ) -> None:
        """Initialize EV charger controller."""
        self.hass = hass
        self._evse = evse_config or DEFAULT_EVSE_ENTITIES
        self._paused_by_us: set[str] = set()
        self._excess_solar_active: set[str] = set()
        self._paused_by_grid_cap: set[str] = set()
        self._paused_by_battery_drain: set[str] = set()
        self._battery_drain_cooldown: dict[str, float] = {}  # evse_id → monotonic expiry
        # v4.2.19: Track power sensor unavailability for alerting
        self._power_sensor_unavail_count: dict[str, int] = {}  # evse_id → consecutive misses
        self._power_sensor_alerted: set[str] = set()  # evse_ids already alerted
        self._power_sensor_unavail_since: dict[str, str] = {}  # evse_id → ISO timestamp

    def _get_evse_state(self, evse_id: str) -> dict[str, Any]:
        """Get current state of an EVSE.

        v4.2.19: Falls back to switch status attribute when power sensor
        is unavailable, so EV control remains functional.
        """
        config = self._evse.get(evse_id, {})
        switch_entity = config.get("switch", "")
        power_entity = config.get("power", "")

        switch_state = self.hass.states.get(switch_entity)
        power_state = self.hass.states.get(power_entity)

        is_on = switch_state.state == "on" if switch_state else False
        power = 0.0
        power_source = "unavailable"
        power_sensor_ok = (
            power_state is not None
            and power_state.state not in ("unknown", "unavailable")
        )
        if power_sensor_ok:
            power_source = "sensor"  # sensor responsive, even if non-numeric
            try:
                power = float(power_state.state)
            except (ValueError, TypeError):
                pass

        # Check charging status from switch attributes
        status = "unknown"
        if switch_state and switch_state.attributes:
            status = switch_state.attributes.get("status", "unknown")

        # Determine charging: prefer power sensor, fall back to switch status
        if power_source == "sensor":
            charging = power > EVSE_CHARGING_POWER_THRESHOLD
        elif is_on and status.lower() in ("charging",):
            # v4.2.19: Power sensor unavailable — use switch status as fallback
            charging = True
            power = float(EVSE_ESTIMATED_POWER_W)  # estimated draw for accounting
            power_source = "switch_status"
        else:
            charging = False

        return {
            "is_on": is_on,
            "power": power,
            "status": status,
            "charging": charging,
            "power_source": power_source,
        }

    def determine_actions(self, tou_period: str) -> list[dict[str, Any]]:
        """Determine EV charger actions based on TOU period."""
        actions: list[dict[str, Any]] = []

        for evse_id, config in self._evse.items():
            switch_entity = config.get("switch", "")
            if not switch_entity:
                continue

            state = self._get_evse_state(evse_id)

            if tou_period in ("peak", "mid_peak"):
                # Skip if excess solar is actively charging this EVSE
                if evse_id in self._excess_solar_active:
                    continue
                # Pause charging during peak/mid-peak
                if state["is_on"] and evse_id not in self._paused_by_us:
                    actions.append({
                        "service": "switch.turn_off",
                        "target": switch_entity,
                        "data": {},
                    })
                    self._paused_by_us.add(evse_id)
                    _LOGGER.info("EV: pausing %s (%s TOU)", evse_id, tou_period)
            else:
                # Resume on off-peak (only if we paused it)
                if evse_id in self._paused_by_us:
                    # v4.0.18: Grid cap takes priority — don't resume if grid capped
                    if evse_id in self._paused_by_grid_cap:
                        self._paused_by_us.discard(evse_id)
                        _LOGGER.info("EV: clearing TOU pause for %s (grid cap active)", evse_id)
                        continue
                    # v4.2.17: Battery drain takes priority — don't resume if draining
                    if evse_id in self._paused_by_battery_drain:
                        self._paused_by_us.discard(evse_id)
                        _LOGGER.info("EV: clearing TOU pause for %s (battery drain active)", evse_id)
                        continue
                    if not state["is_on"]:
                        actions.append({
                            "service": "switch.turn_on",
                            "target": switch_entity,
                            "data": {},
                        })
                        _LOGGER.info("EV: resuming %s (off-peak)", evse_id)
                    self._paused_by_us.discard(evse_id)

        return actions

    def determine_excess_solar_actions(
        self,
        soc: float | None,
        remaining_forecast_kwh: float | None,
        tou_period: str,
        soc_threshold: int = 95,
        kwh_threshold: float = 5.0,
    ) -> list[dict[str, Any]]:
        """Determine whether to turn on EVSEs for excess solar charging.

        Only during off-peak or mid-peak (never peak — battery needed).
        Conditions to activate: SOC >= threshold AND remaining forecast >= kwh threshold.
        """
        actions: list[dict[str, Any]] = []

        # Never during peak
        if tou_period == "peak":
            # Turn off any we activated
            for evse_id in list(self._excess_solar_active):
                config = self._evse.get(evse_id, {})
                switch_entity = config.get("switch", "")
                if switch_entity:
                    state = self._get_evse_state(evse_id)
                    if state["is_on"]:
                        actions.append({
                            "service": "switch.turn_off",
                            "target": switch_entity,
                            "data": {},
                        })
                        _LOGGER.info("Excess solar: turning off %s (peak period)", evse_id)
                self._excess_solar_active.discard(evse_id)
            return actions

        conditions_met = (
            soc is not None
            and soc >= soc_threshold
            and remaining_forecast_kwh is not None
            and remaining_forecast_kwh >= kwh_threshold
        )

        if conditions_met:
            _LOGGER.debug(
                "Excess solar conditions met: SOC=%.0f%% >= %d, remaining=%.1f kWh >= %.1f",
                soc or 0, soc_threshold,
                remaining_forecast_kwh or 0, kwh_threshold,
            )
            # Turn on EVSEs — override TOU pause when battery is full + solar surplus
            for evse_id, config in self._evse.items():
                switch_entity = config.get("switch", "")
                if not switch_entity:
                    continue
                if evse_id in self._excess_solar_active:
                    continue  # Already on by us
                # Claim EVSE from TOU pause if needed
                was_tou_paused = evse_id in self._paused_by_us
                if was_tou_paused:
                    self._paused_by_us.discard(evse_id)
                state = self._get_evse_state(evse_id)
                if not state["is_on"]:
                    actions.append({
                        "service": "switch.turn_on",
                        "target": switch_entity,
                        "data": {},
                    })
                    self._excess_solar_active.add(evse_id)
                    _LOGGER.info(
                        "Excess solar: turning on %s (SOC=%.0f%%, remaining=%.1f kWh%s)",
                        evse_id, soc, remaining_forecast_kwh,
                        ", overriding TOU pause" if was_tou_paused else "",
                    )
                elif was_tou_paused:
                    # EVSE already on — just claim it
                    self._excess_solar_active.add(evse_id)
                    _LOGGER.info(
                        "Excess solar: claiming %s from TOU pause (already on)", evse_id,
                    )
        else:
            # Conditions no longer met — turn off only what we turned on
            for evse_id in list(self._excess_solar_active):
                config = self._evse.get(evse_id, {})
                switch_entity = config.get("switch", "")
                if switch_entity:
                    state = self._get_evse_state(evse_id)
                    if state["is_on"]:
                        actions.append({
                            "service": "switch.turn_off",
                            "target": switch_entity,
                            "data": {},
                        })
                        _LOGGER.info("Excess solar: turning off %s (conditions no longer met)", evse_id)
                self._excess_solar_active.discard(evse_id)

        return actions

    def determine_grid_cap_actions(
        self,
        net_power_kw: float,
        grid_cap_kw: float,
        hysteresis_kw: float = 1.0,
    ) -> list[dict[str, Any]]:
        """Pause/resume EVSEs based on grid import cap.

        Pauses charging EVSEs when net_power > grid_cap.
        Resumes when net_power < (grid_cap - hysteresis).
        Separate from TOU pausing — tracked independently.
        """
        actions: list[dict[str, Any]] = []

        for evse_id, config in self._evse.items():
            switch_entity = config.get("switch", "")
            if not switch_entity:
                continue
            state = self._get_evse_state(evse_id)

            if net_power_kw > grid_cap_kw:
                # Over cap — pause any charging EVSE not already capped
                if state["charging"] and evse_id not in self._paused_by_grid_cap:
                    actions.append({
                        "service": "switch.turn_off",
                        "target": switch_entity,
                        "data": {},
                    })
                    self._paused_by_grid_cap.add(evse_id)
                    _LOGGER.info(
                        "EV grid cap: pausing %s (grid=%.1f kW > cap=%.1f kW)",
                        evse_id, net_power_kw, grid_cap_kw,
                    )
            elif evse_id in self._paused_by_grid_cap:
                # Below cap minus hysteresis — resume
                if net_power_kw < (grid_cap_kw - hysteresis_kw):
                    # v4.2.17: Battery drain takes priority
                    if evse_id in self._paused_by_battery_drain:
                        self._paused_by_grid_cap.discard(evse_id)
                        _LOGGER.info("EV grid cap: clearing for %s (battery drain active)", evse_id)
                        continue
                    if not state["is_on"]:
                        actions.append({
                            "service": "switch.turn_on",
                            "target": switch_entity,
                            "data": {},
                        })
                        _LOGGER.info(
                            "EV grid cap: resuming %s (grid=%.1f kW < %.1f kW)",
                            evse_id, net_power_kw, grid_cap_kw - hysteresis_kw,
                        )
                    self._paused_by_grid_cap.discard(evse_id)

        return actions

    def determine_battery_drain_actions(
        self,
        battery_power_w: float | None,
        battery_soc: float | None,
        soc_threshold: int,
    ) -> list[dict[str, Any]]:
        """Pause EVSEs draining the home battery. Resume on recovery.

        Pauses when: EVSE is charging AND battery is discharging AND SOC < threshold.
        Resumes when: battery stops discharging (reserve holds, grid takes over)
                  OR SOC >= threshold + 5% hysteresis (solar recharge).
        Manual override: if user turns charger back on during pause, set 1h cooldown.
        """
        actions: list[dict[str, Any]] = []
        now = _time.monotonic()

        for evse_id, config in self._evse.items():
            switch_entity = config.get("switch", "")
            if not switch_entity:
                continue
            state = self._get_evse_state(evse_id)

            # Check cooldown (manual override protection)
            cooldown_expiry = self._battery_drain_cooldown.get(evse_id)
            if cooldown_expiry is not None:
                if now < cooldown_expiry:
                    continue  # In cooldown — don't re-pause
                self._battery_drain_cooldown.pop(evse_id, None)

            # Detect manual override: charger on while we have it paused
            if evse_id in self._paused_by_battery_drain and state["is_on"]:
                self._paused_by_battery_drain.discard(evse_id)
                self._battery_drain_cooldown[evse_id] = now + EV_BATTERY_DRAIN_COOLDOWN_SECONDS
                _LOGGER.info(
                    "EV battery drain: %s turned on manually — cooldown %ds",
                    evse_id, EV_BATTERY_DRAIN_COOLDOWN_SECONDS,
                )
                continue

            battery_discharging = (
                battery_power_w is not None and battery_power_w < -100  # >100W discharge
            )
            soc_low = (
                battery_soc is not None and battery_soc < soc_threshold
            )

            if state["charging"] and battery_discharging and soc_low:
                # Pause: EV is draining the battery
                if evse_id not in self._paused_by_battery_drain:
                    actions.append({
                        "service": "switch.turn_off",
                        "target": switch_entity,
                        "data": {},
                    })
                    self._paused_by_battery_drain.add(evse_id)
                    _LOGGER.info(
                        "EV battery drain: pausing %s (battery=%.0fW, SOC=%.0f%% < %d%%)",
                        evse_id, battery_power_w, battery_soc, soc_threshold,
                    )
            elif evse_id in self._paused_by_battery_drain:
                # Resume conditions:
                # 1. Battery stopped discharging (reserve holds, grid takes over)
                # 2. SOC recovered above threshold + 5% hysteresis (solar recharge)
                soc_recovered = (
                    battery_soc is not None and battery_soc >= soc_threshold + 5
                )
                battery_ok = not battery_discharging

                if battery_ok or soc_recovered:
                    if not state["is_on"]:
                        # Don't resume if another pause reason is active
                        if evse_id in self._paused_by_grid_cap or evse_id in self._paused_by_us:
                            self._paused_by_battery_drain.discard(evse_id)
                            _LOGGER.info(
                                "EV battery drain: clearing for %s (other pause active)",
                                evse_id,
                            )
                            continue
                        actions.append({
                            "service": "switch.turn_on",
                            "target": switch_entity,
                            "data": {},
                        })
                        reason = "battery ok" if battery_ok else "SOC recovered"
                        _LOGGER.info(
                            "EV battery drain: resuming %s (%s)", evse_id, reason,
                        )
                    self._paused_by_battery_drain.discard(evse_id)

        return actions

    def check_power_sensor_health(self) -> list[dict[str, str]]:
        """Check EVSE power sensor availability. Returns alerts to send.

        Called each decision cycle (~5 min). After 3 consecutive unavailable
        readings (~15 min), returns an alert dict for the coordinator to send
        via NM. Clears alert when sensor recovers.
        """
        from homeassistant.util import dt as dt_util
        alerts: list[dict[str, str]] = []
        for evse_id, config in self._evse.items():
            state = self._get_evse_state(evse_id)
            if state["power_source"] == "unavailable":
                count = self._power_sensor_unavail_count.get(evse_id, 0) + 1
                self._power_sensor_unavail_count[evse_id] = count
                # Record when unavailability started
                if evse_id not in self._power_sensor_unavail_since:
                    self._power_sensor_unavail_since[evse_id] = dt_util.utcnow().isoformat()
                if count == 3 and evse_id not in self._power_sensor_alerted:
                    power_entity = config.get("power", "unknown")
                    since = self._power_sensor_unavail_since.get(evse_id, "unknown")
                    alerts.append({
                        "evse_id": evse_id,
                        "power_entity": power_entity,
                        "message": (
                            f"EVSE {evse_id} power sensor ({power_entity}) has been "
                            f"unavailable since {since}. EV control using switch status "
                            f"fallback — charging detection is degraded."
                        ),
                    })
                    self._power_sensor_alerted.add(evse_id)
                    _LOGGER.warning(
                        "EVSE %s power sensor unavailable since %s (%d cycles) — using fallback",
                        evse_id, since, count,
                    )
            else:
                if evse_id in self._power_sensor_alerted:
                    since = self._power_sensor_unavail_since.get(evse_id, "unknown")
                    _LOGGER.info("EVSE %s power sensor recovered (was down since %s)", evse_id, since)
                    self._power_sensor_alerted.discard(evse_id)
                self._power_sensor_unavail_count[evse_id] = 0
                self._power_sensor_unavail_since.pop(evse_id, None)
        return alerts

    def get_status(self) -> dict[str, Any]:
        """Return EV charging status for sensor."""
        status: dict[str, Any] = {
            "paused_by_energy": list(self._paused_by_us),
            "paused_by_grid_cap": list(self._paused_by_grid_cap),
            "paused_by_battery_drain": list(self._paused_by_battery_drain),
            "excess_solar_active": bool(self._excess_solar_active),
            "excess_solar_evses": list(self._excess_solar_active),
        }
        for evse_id in self._evse:
            evse_state = self._get_evse_state(evse_id)
            if evse_id in self._paused_by_battery_drain:
                evse_state["energy_status"] = "battery_drain_paused"
            elif evse_id in self._paused_by_grid_cap:
                evse_state["energy_status"] = "grid_capped"
            elif evse_id in self._paused_by_us:
                evse_state["energy_status"] = "paused"
            elif evse_id in self._excess_solar_active:
                evse_state["energy_status"] = "excess_solar"
            elif evse_state["charging"]:
                evse_state["energy_status"] = "charging"
            elif evse_state["is_on"]:
                evse_state["energy_status"] = "idle"
            else:
                evse_state["energy_status"] = "off"
            # v4.2.19: Surface unavailability timestamp
            unavail_since = self._power_sensor_unavail_since.get(evse_id)
            if unavail_since:
                evse_state["power_sensor_unavail_since"] = unavail_since
            status[evse_id] = evse_state
        return status


# ============================================================================
# Smart Plug Controller
# ============================================================================


class SmartPlugController:
    """Controls additional smart plug loads (L1 chargers) based on TOU and battery state.

    Configured via options flow as a list of entity IDs.
    v4.2.21: Pauses during peak AND mid_peak. Battery drain protection.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        plug_entities: list[str] | None = None,
    ) -> None:
        """Initialize smart plug controller."""
        self.hass = hass
        self._plugs = plug_entities or []
        self._paused_by_us: set[str] = set()
        self._paused_by_battery_drain: set[str] = set()

    def determine_actions(self, tou_period: str) -> list[dict[str, Any]]:
        """Determine smart plug actions based on TOU period.

        v4.2.21: Pauses on peak AND mid_peak (was peak only).
        """
        actions: list[dict[str, Any]] = []

        for entity_id in self._plugs:
            state = self.hass.states.get(entity_id)
            if state is None:
                continue

            if tou_period in ("peak", "mid_peak"):
                if state.state == "on" and entity_id not in self._paused_by_us:
                    actions.append({
                        "service": "switch.turn_off",
                        "target": entity_id,
                        "data": {},
                    })
                    self._paused_by_us.add(entity_id)
                    _LOGGER.info("Smart plug: pausing %s (%s)", entity_id, tou_period)
            else:
                if entity_id in self._paused_by_us:
                    # Don't resume if battery drain is active
                    if entity_id in self._paused_by_battery_drain:
                        self._paused_by_us.discard(entity_id)
                        _LOGGER.info("Smart plug: clearing TOU pause for %s (battery drain active)", entity_id)
                        continue
                    if state.state != "on":
                        actions.append({
                            "service": "switch.turn_on",
                            "target": entity_id,
                            "data": {},
                        })
                        _LOGGER.info("Smart plug: resuming %s (off-peak)", entity_id)
                    self._paused_by_us.discard(entity_id)

        return actions

    def determine_battery_drain_actions(
        self,
        battery_power_w: float | None,
        battery_soc: float | None,
        soc_threshold: int,
    ) -> list[dict[str, Any]]:
        """Pause smart plugs draining the home battery. Resume on recovery.

        Simpler than EVSE version — no charging detection (no power sensors
        on dumb plugs). Pauses any ON plug when battery is draining below
        threshold. No manual override cooldown (plugs are L1 chargers, not
        user-interactive).
        """
        actions: list[dict[str, Any]] = []

        battery_discharging = (
            battery_power_w is not None and battery_power_w < -100
        )
        soc_low = (
            battery_soc is not None and battery_soc < soc_threshold
        )

        for entity_id in self._plugs:
            state = self.hass.states.get(entity_id)
            if state is None:
                continue

            if state.state == "on" and battery_discharging and soc_low:
                if entity_id not in self._paused_by_battery_drain:
                    actions.append({
                        "service": "switch.turn_off",
                        "target": entity_id,
                        "data": {},
                    })
                    self._paused_by_battery_drain.add(entity_id)
                    _LOGGER.info(
                        "Smart plug battery drain: pausing %s (SOC=%.0f%% < %d%%)",
                        entity_id, battery_soc, soc_threshold,
                    )
            elif entity_id in self._paused_by_battery_drain:
                soc_recovered = (
                    battery_soc is not None and battery_soc >= soc_threshold + 5
                )
                battery_ok = not battery_discharging

                if battery_ok or soc_recovered:
                    # Don't resume if TOU pause is active
                    if entity_id in self._paused_by_us:
                        self._paused_by_battery_drain.discard(entity_id)
                        _LOGGER.info("Smart plug battery drain: clearing for %s (TOU active)", entity_id)
                        continue
                    if state.state != "on":
                        actions.append({
                            "service": "switch.turn_on",
                            "target": entity_id,
                            "data": {},
                        })
                        reason = "battery ok" if battery_ok else "SOC recovered"
                        _LOGGER.info("Smart plug battery drain: resuming %s (%s)", entity_id, reason)
                    self._paused_by_battery_drain.discard(entity_id)

        return actions

    def get_status(self) -> dict[str, Any]:
        """Return smart plug status."""
        return {
            "configured_plugs": len(self._plugs),
            "paused_by_energy": list(self._paused_by_us),
            "paused_by_battery_drain": list(self._paused_by_battery_drain),
        }
