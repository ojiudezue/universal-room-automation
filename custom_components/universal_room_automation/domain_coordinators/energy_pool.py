"""Pool optimizer, EV charger controller, and smart plug manager for Energy Coordinator.

Sub-Cycle E2: Pool VSF speed reduction during peak, EV charging pause/resume,
additional controllable loads.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant

import time as _time

from .energy_const import (
    EVSE_CHARGING_POWER_THRESHOLD,
    EVSE_ESTIMATED_POWER_W,
    EV_BATTERY_DRAIN_COOLDOWN_SECONDS,
    EV_PAUSE_DISPATCH_GRACE_SECONDS,
    DEFAULT_FILL_PRIORITY_SAFETY_MARGIN_KWH,
    L1_ESTIMATED_POWER_W,
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
        # v4.5.0 D4: compound-load protection — pause EVSEs while arbitrage
        # is grid-charging. Solo battery 20 kW (~83A) is within main breaker;
        # battery + EV (7.4 kW) + house base (~5 kW) ≈ 134A is the panel-
        # stress scenario. This pattern (`_paused_by_<reason>` set with
        # precedence rules) is what v4.7.x B5 will extend to appliances.
        self._paused_by_arbitrage: set[str] = set()
        self._battery_drain_cooldown: dict[str, float] = {}  # evse_id → monotonic expiry
        # v4.2.19: Track power sensor unavailability for alerting
        self._power_sensor_unavail_count: dict[str, int] = {}  # evse_id → consecutive misses
        self._power_sensor_alerted: set[str] = set()  # evse_ids already alerted
        self._power_sensor_unavail_since: dict[str, str] = {}  # evse_id → ISO timestamp
        # v4.7.x D3: URA-side admin override — open 30-min force-charge window.
        # Non-None when override is active; UTC-aware datetime at which it expires.
        # Only settable via EVSEForceChargeButton; never from HA UI directly.
        self._force_charge_until: datetime | None = None

        # v4.7.6 D1: Hybrid manual-override detection state.
        # _pause_dispatch_ts[evse_id] = monotonic() at the moment URA dispatched
        # switch.turn_off. _observed_off_since_pause[evse_id] flips False → True
        # the first decision tick after dispatch where URA reads is_on=False.
        # Both reset on EVPool init (no DB persistence — Bug Class #7 mitigation
        # explicitly documented; monotonic resets on HA restart anyway).
        self._pause_dispatch_ts: dict[str, float] = {}
        self._observed_off_since_pause: dict[str, bool] = {}

        # v4.7.6 D2: Fill-priority pause set — symmetric to drain.
        # When SOC < fill_priority_soc AND solar forecast healthy, URA pauses
        # EVSEs so the home battery fills first. Resume on SOC recovery or
        # forecast decay below safety margin.
        self._paused_by_fill_priority: set[str] = set()

        # v4.7.6 D4: Cache last computed fill-priority forecast-health flag,
        # surfaced as `fill_priority_solar_ok` on the EV status sensor.
        self._fill_priority_solar_ok: bool = False

        # v4.7.6 D1 #9: Prune stale entries on init (idempotent on cold boot).
        self._prune_removed_evses()

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
                # v4.5.0 unit-consistency: EVSE_CHARGING_POWER_THRESHOLD is
                # in watts (100). Emporia reports W; Tesla Wall Connector
                # via some integrations reports kW. Normalize via the
                # entity's unit_of_measurement attribute. Same bug class
                # as v4.3.4 battery_power_w fix (Bug Class #30).
                uom = power_state.attributes.get("unit_of_measurement", "")
                if uom in ("kW", "kw"):
                    power *= 1000.0
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

    # ------------------------------------------------------------------
    # v4.7.6 D1 — Per-EVSE config + lifecycle helpers
    # ------------------------------------------------------------------

    def _self_modulates_for(self, evse_id: str) -> bool:
        """Return True when this EVSE is marked self-modulating (Option A).

        When True, URA is the sole authority — manual-override detection is
        skipped and URA re-pauses every decision tick that conditions hold.
        Default False (Option B / smart manual-override detection).
        """
        cfg = self._evse.get(evse_id, {})
        try:
            return bool(cfg.get("self_modulates", False))
        except Exception:  # pragma: no cover — defensive
            return False

    def _clear_pause_dispatch_state(self, evse_id: str) -> None:
        """Drop the per-EVSE dispatch-tracking entries on resume/cooldown.

        Called whenever the EVSE leaves _paused_by_battery_drain or
        _paused_by_fill_priority. Idempotent.
        """
        self._pause_dispatch_ts.pop(evse_id, None)
        self._observed_off_since_pause.pop(evse_id, None)

    def _prune_removed_evses(self) -> None:
        """Purge per-EVSE state for entries no longer configured.

        Without this, config-flow edits that remove an EVSE leak entries in
        _paused_by_*, _battery_drain_cooldown, _pause_dispatch_ts, etc.
        Called from __init__ and update_evse_config().
        """
        known = set(self._evse.keys())
        for tracking_set in (
            self._paused_by_us,
            self._excess_solar_active,
            self._paused_by_grid_cap,
            self._paused_by_battery_drain,
            self._paused_by_arbitrage,
            self._paused_by_fill_priority,
        ):
            for evse_id in list(tracking_set):
                if evse_id not in known:
                    tracking_set.discard(evse_id)
        for tracking_dict in (
            self._battery_drain_cooldown,
            self._pause_dispatch_ts,
            self._observed_off_since_pause,
            self._power_sensor_unavail_count,
            self._power_sensor_unavail_since,
        ):
            for evse_id in list(tracking_dict.keys()):
                if evse_id not in known:
                    tracking_dict.pop(evse_id, None)
        for evse_id in list(self._power_sensor_alerted):
            if evse_id not in known:
                self._power_sensor_alerted.discard(evse_id)

    def update_evse_config(self, evse_config: dict[str, dict[str, Any]]) -> None:
        """Replace the EVSE config dict and prune stale per-EVSE state.

        Called from EnergyCoordinator when config flow rewrites entries
        (or, in v4.7.6, when per-EVSE self_modulates flips). Caller is
        responsible for triggering the next decision tick.
        """
        self._evse = evse_config or {}
        self._prune_removed_evses()

    def determine_actions(self, tou_period: str) -> list[dict[str, Any]]:
        """Determine EV charger actions based on TOU period.

        v4.7.x D1: Strict TOU enforcement — the `_paused_by_us` short-circuit
        is removed so URA re-pauses idempotently each decision tick even if
        the user manually re-enabled the EVSE in HA.  Manual HA-side overrides
        are reversed within ≤5 min (one decision interval).  The excess-solar
        exception (already handled above this path) is unchanged.

        v4.7.x D3: `_force_charge_until` opens a timed admin-bypass window set
        exclusively via `EVSEForceChargeButton`.  When the window is active and
        unexpired, TOU pause is skipped for all EVSEs.  Auto-expires: once the
        current UTC time passes the stored timestamp, normal pausing resumes on
        the next tick.
        """
        from homeassistant.util import dt as dt_util

        actions: list[dict[str, Any]] = []

        # v4.7.x D3: check force-charge override (UTC-safe, Bug Class #11/#21)
        force_charge_active = False
        if self._force_charge_until is not None:
            now_utc = dt_util.utcnow()
            if now_utc < self._force_charge_until:
                force_charge_active = True
            else:
                _LOGGER.info("EV: force-charge override expired — resuming strict TOU")
                self._force_charge_until = None

        for evse_id, config in self._evse.items():
            switch_entity = config.get("switch", "")
            if not switch_entity:
                continue

            state = self._get_evse_state(evse_id)

            if tou_period in ("peak", "mid_peak"):
                # Skip if excess solar is actively charging this EVSE
                if evse_id in self._excess_solar_active:
                    continue
                # v4.7.x D3: Skip pause if admin force-charge override is active
                if force_charge_active:
                    _LOGGER.debug(
                        "EV: %s TOU pause bypassed — admin force-charge override active",
                        evse_id,
                    )
                    continue
                # v4.7.x D1: Re-pause idempotently — no `_paused_by_us` guard.
                # URA turns the switch off on every tick while peak/mid_peak is
                # active.  This defeats manual HA-side re-enables within one
                # decision cycle.
                if state["is_on"]:
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

    # -------------------------------------------------------------------------
    # v4.7.x D3: Admin force-charge override API
    # -------------------------------------------------------------------------

    @property
    def force_charge_until(self) -> datetime | None:
        """Return the UTC expiry of the current force-charge window, or None."""
        return self._force_charge_until

    def set_force_charge_override(self, until: datetime) -> None:
        """Open (or extend) the force-charge window to `until` (UTC-aware).

        Idempotent: re-pressing the button replaces (not stacks) the window.
        The caller is responsible for supplying a UTC-aware datetime.
        """
        self._force_charge_until = until
        _LOGGER.info(
            "EV: force-charge override set until %s", until.isoformat()
        )

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
        reserve_soc: int | None = None,
    ) -> list[dict[str, Any]]:
        """Pause EVSEs draining the home battery. Resume on recovery.

        Pauses when: EVSE is charging AND battery is discharging AND SOC < threshold.

        v4.7.6 D1: Refined resume gate.
          - `battery_out_of_capacity = battery_ok AND soc <= reserve_soc + 2`
            (we're at the reserve floor; capacity is exhausted — resume).
          - `soc_recovered = soc >= soc_threshold + 5` (solar recharge clear).
          - Replaces the old `battery_ok OR soc_recovered` which let a
            transient equilibrium (caused by URA's own pause) wrongly resume.
          - When `reserve_soc is None` (test paths, missing Enpower), only
            `soc_recovered` permits resume — safer than the legacy behavior.

        v4.7.6 D1: Hybrid `self_modulates` manual-override detection.
          - When `self_modulates=True` (Option A — smart EVSE with native
            solar/schedule mode): URA is sole authority. Re-pause every tick
            conditions hold. Cooldown branch skipped entirely.
          - When `self_modulates=False` (default / Option B): the manual-
            override branch fires ONLY when ALL hold:
              * evse_id in _paused_by_battery_drain
              * state.is_on=True
              * _observed_off_since_pause[evse_id] is True (we saw it off)
              * monotonic() - _pause_dispatch_ts[evse_id] > 30s grace
            Otherwise it's a stale state-cache read or an instant auto-resume
            and URA re-pauses idempotently.

        v4.7.6 D1: Idempotent re-pause — the `if not in _paused_by_battery_drain`
        short-circuit is dropped; URA re-dispatches `switch.turn_off` every
        tick the conditions are met. Mirrors the TOU pattern at lines 319-323.
        """
        actions: list[dict[str, Any]] = []
        now = _time.monotonic()

        for evse_id, config in self._evse.items():
            switch_entity = config.get("switch", "")
            if not switch_entity:
                continue
            state = self._get_evse_state(evse_id)

            # State-update on every tick: once we read is_on=False after
            # dispatch, mark observed_off so the manual-override branch can
            # legitimately fire later (Option B / self_modulates=False).
            if (
                evse_id in self._paused_by_battery_drain
                and state["is_on"] is False
                and self._observed_off_since_pause.get(evse_id) is False
            ):
                self._observed_off_since_pause[evse_id] = True

            self_modulates = self._self_modulates_for(evse_id)

            # Check cooldown (manual override protection) — Option B only.
            # Smart-EVSE (Option A) never engages cooldown because we never
            # interpret an external state change as a manual override.
            cooldown_expiry = self._battery_drain_cooldown.get(evse_id)
            if cooldown_expiry is not None:
                if now < cooldown_expiry:
                    continue  # In cooldown — don't re-pause
                self._battery_drain_cooldown.pop(evse_id, None)

            # v4.7.6 D1 hybrid manual-override branch (Option B only).
            # ALL of: paused-by-us, is_on=True, observed_off=True, grace expired.
            if not self_modulates and evse_id in self._paused_by_battery_drain and state["is_on"]:
                dispatch_ts = self._pause_dispatch_ts.get(evse_id)
                observed_off = self._observed_off_since_pause.get(evse_id, False)
                grace_expired = (
                    dispatch_ts is not None
                    and (now - dispatch_ts) > EV_PAUSE_DISPATCH_GRACE_SECONDS
                )
                if observed_off and grace_expired:
                    self._paused_by_battery_drain.discard(evse_id)
                    self._battery_drain_cooldown[evse_id] = now + EV_BATTERY_DRAIN_COOLDOWN_SECONDS
                    self._clear_pause_dispatch_state(evse_id)
                    _LOGGER.info(
                        "EV battery drain: %s turned on manually — cooldown %ds",
                        evse_id, EV_BATTERY_DRAIN_COOLDOWN_SECONDS,
                    )
                    continue
                # Else: dispatch lag OR instant auto-resume — fall through
                # to the pause-conditions check; URA may re-pause this tick.
                _LOGGER.debug(
                    "EV battery drain: %s is_on=True while paused — "
                    "observed_off=%s grace_expired=%s — falling through to re-pause check",
                    evse_id, observed_off, grace_expired,
                )

            battery_discharging = (
                battery_power_w is not None and battery_power_w < -100  # >100W discharge
            )
            soc_low = (
                battery_soc is not None and battery_soc < soc_threshold
            )

            if state["charging"] and battery_discharging and soc_low:
                # v4.7.6 D1: Idempotent re-pause — re-dispatch every tick.
                # Mirrors the TOU pattern at lines 319-323.
                actions.append({
                    "service": "switch.turn_off",
                    "target": switch_entity,
                    "data": {},
                })
                self._paused_by_battery_drain.add(evse_id)
                # Re-stamp dispatch ts and reset observed_off on every
                # dispatch so the grace window is honored cycle-to-cycle.
                self._pause_dispatch_ts[evse_id] = now
                self._observed_off_since_pause[evse_id] = False
                _LOGGER.info(
                    "EV battery drain: pausing %s (battery=%.0fW, SOC=%.0f%% < %d%%)",
                    evse_id, battery_power_w, battery_soc, soc_threshold,
                )
            elif evse_id in self._paused_by_battery_drain:
                # v4.7.6 D1: Refined resume conditions.
                # 1. battery_out_of_capacity: battery_ok AND SOC <= reserve_soc + 2
                #    — we're at the reserve floor; can't reasonably wait longer.
                # 2. soc_recovered: SOC >= soc_threshold + 5% (solar recharge).
                # The legacy OR clause (`battery_ok or soc_recovered`) let a
                # transient equilibrium caused by URA's own pause resume the EV
                # mid-day; the refined gate prevents that flap.
                battery_ok = not battery_discharging
                battery_out_of_capacity = (
                    battery_ok
                    and battery_soc is not None
                    and reserve_soc is not None
                    and battery_soc <= reserve_soc + 2
                )
                soc_recovered = (
                    battery_soc is not None
                    and battery_soc >= soc_threshold + 5
                )

                if battery_out_of_capacity or soc_recovered:
                    if not state["is_on"]:
                        # Don't resume if another pause reason is active
                        if (
                            evse_id in self._paused_by_grid_cap
                            or evse_id in self._paused_by_us
                            or evse_id in self._paused_by_arbitrage
                            or evse_id in self._paused_by_fill_priority
                        ):
                            self._paused_by_battery_drain.discard(evse_id)
                            self._clear_pause_dispatch_state(evse_id)
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
                        reason = (
                            "battery out of capacity"
                            if battery_out_of_capacity else "SOC recovered"
                        )
                        _LOGGER.info(
                            "EV battery drain: resuming %s (%s)", evse_id, reason,
                        )
                    self._paused_by_battery_drain.discard(evse_id)
                    self._clear_pause_dispatch_state(evse_id)

        return actions

    # ------------------------------------------------------------------
    # v4.7.6 D2 — Fill-priority pause (primary rule)
    # ------------------------------------------------------------------

    def determine_fill_priority_actions(
        self,
        soc: float | None,
        remaining_forecast_kwh: float | None,
        tou_period: str,
        soc_threshold: int,
        excess_solar_kwh_threshold: float,
        safety_margin_kwh: float = DEFAULT_FILL_PRIORITY_SAFETY_MARGIN_KWH,
    ) -> list[dict[str, Any]]:
        """Pause EVSEs so the home battery fills first when solar is healthy.

        Symmetric to drain-protection but BEFORE the battery actually drains:
        when SOC is below `soc_threshold` (default 80%) and the day's remaining
        solar forecast >= `excess_solar_kwh_threshold`, pause EV charging so
        the battery climbs to the fill threshold first.

        Resume when EITHER:
          - SOC >= soc_threshold (battery filled to target), OR
          - remaining_forecast_kwh < (excess_solar_kwh_threshold - safety_margin)
            (forecast no longer healthy enough to keep EV paused).

        Never overrides peak — the existing TOU pause is canonical there.

        Mirrors D1's hybrid `self_modulates` and idempotent re-pause patterns.
        Shares `_pause_dispatch_ts` / `_observed_off_since_pause` with drain —
        only one URA dispatch is pending at a time per EVSE.
        """
        actions: list[dict[str, Any]] = []
        now = _time.monotonic()

        # Compute forecast-health flag and cache it for the EV charging sensor.
        forecast_healthy = (
            remaining_forecast_kwh is not None
            and remaining_forecast_kwh >= excess_solar_kwh_threshold
        )
        forecast_decayed = (
            remaining_forecast_kwh is not None
            and remaining_forecast_kwh < (
                excess_solar_kwh_threshold - safety_margin_kwh
            )
        )
        self._fill_priority_solar_ok = bool(forecast_healthy)

        # Never run during peak — TOU pause is the canonical rule there.
        if tou_period == "peak":
            # Don't dispatch resumes either; let TOU/drain control. Discard
            # set membership silently so we don't auto-resume out of peak.
            for evse_id in list(self._paused_by_fill_priority):
                self._paused_by_fill_priority.discard(evse_id)
            return actions

        pause_conditions_global = (
            soc is not None
            and soc < soc_threshold
            and forecast_healthy
        )
        resume_soc_met = soc is not None and soc >= soc_threshold

        for evse_id, config in self._evse.items():
            switch_entity = config.get("switch", "")
            if not switch_entity:
                continue
            state = self._get_evse_state(evse_id)

            # Mirror D1 state-update for shared dispatch tracking.
            if (
                evse_id in self._paused_by_fill_priority
                and state["is_on"] is False
                and self._observed_off_since_pause.get(evse_id) is False
            ):
                self._observed_off_since_pause[evse_id] = True

            self_modulates = self._self_modulates_for(evse_id)

            # v4.7.6 D2 hybrid manual-override branch (Option B only).
            # No cooldown engagement here — fill-priority is informational/
            # opportunistic; drain protection retains the 1-h cooldown for
            # safety. We simply release the EVSE from the set on a real
            # manual override so it can re-charge if user insists.
            if not self_modulates and evse_id in self._paused_by_fill_priority and state["is_on"]:
                dispatch_ts = self._pause_dispatch_ts.get(evse_id)
                observed_off = self._observed_off_since_pause.get(evse_id, False)
                grace_expired = (
                    dispatch_ts is not None
                    and (now - dispatch_ts) > EV_PAUSE_DISPATCH_GRACE_SECONDS
                )
                if observed_off and grace_expired:
                    self._paused_by_fill_priority.discard(evse_id)
                    self._clear_pause_dispatch_state(evse_id)
                    _LOGGER.info(
                        "EV fill-priority: %s turned on manually — releasing",
                        evse_id,
                    )
                    continue
                _LOGGER.debug(
                    "EV fill-priority: %s is_on=True while paused — "
                    "observed_off=%s grace_expired=%s — falling through",
                    evse_id, observed_off, grace_expired,
                )

            # Excess-solar-active interaction: belt-and-suspenders deferral.
            # If excess solar is firing (SOC≥excess_solar_soc≥95), pause_
            # conditions_global is already False (soc not < 80), but log it.
            if evse_id in self._excess_solar_active and pause_conditions_global:
                _LOGGER.debug(
                    "EV fill-priority: %s in excess_solar_active — deferring",
                    evse_id,
                )
                continue

            if pause_conditions_global and state["is_on"]:
                # v4.7.6 D2: idempotent re-pause every tick.
                actions.append({
                    "service": "switch.turn_off",
                    "target": switch_entity,
                    "data": {},
                })
                self._paused_by_fill_priority.add(evse_id)
                self._pause_dispatch_ts[evse_id] = now
                self._observed_off_since_pause[evse_id] = False
                _LOGGER.info(
                    "EV fill-priority: pausing %s "
                    "(SOC=%.0f%% < %d%%, remaining=%.1f kWh >= %.1f)",
                    evse_id,
                    soc if soc is not None else -1,
                    soc_threshold,
                    remaining_forecast_kwh if remaining_forecast_kwh is not None else -1,
                    excess_solar_kwh_threshold,
                )
            elif evse_id in self._paused_by_fill_priority:
                if resume_soc_met or forecast_decayed:
                    # Don't resume if a stronger pause reason holds (mirrors
                    # the existing pattern at lines 595-600 in drain rule).
                    if (
                        evse_id in self._paused_by_grid_cap
                        or evse_id in self._paused_by_battery_drain
                        or evse_id in self._paused_by_us
                        or evse_id in self._paused_by_arbitrage
                    ):
                        self._paused_by_fill_priority.discard(evse_id)
                        self._clear_pause_dispatch_state(evse_id)
                        _LOGGER.info(
                            "EV fill-priority: clearing for %s (other pause active)",
                            evse_id,
                        )
                        continue
                    if not state["is_on"]:
                        actions.append({
                            "service": "switch.turn_on",
                            "target": switch_entity,
                            "data": {},
                        })
                        reason = (
                            "SOC reached fill target"
                            if resume_soc_met else "forecast decayed"
                        )
                        _LOGGER.info(
                            "EV fill-priority: resuming %s (%s)", evse_id, reason,
                        )
                    self._paused_by_fill_priority.discard(evse_id)
                    self._clear_pause_dispatch_state(evse_id)

        return actions

    def determine_arbitrage_actions(
        self,
        arbitrage_charging: bool,
        tou_period: str,
    ) -> list[dict[str, Any]]:
        """v4.5.0 D4: pause/resume EVSEs based on arbitrage CHARGE phase.

        When arbitrage is grid-charging the battery (20 kW), running an
        EVSE concurrently can take a normal residential panel to ~134A
        on the main breaker (battery 20 kW + EV 7.4 kW + base ~5 kW).
        Solo battery is well within breaker capacity (~83A).

        Pause logic:
            arbitrage_charging=True →
                - For every EVSE that is ON and not already in
                  _paused_by_arbitrage: turn off + add to set.

        Resume logic (arbitrage_charging=False, i.e., phase exits CHARGE
        — typically into HOLD or DISCHARGE):
            - For every EVSE in _paused_by_arbitrage:
                * Remove from set.
                * Resume only if:
                  - TOU still allows EV charging (off_peak), AND
                  - No other pause reason holds (grid_cap / battery_drain /
                    paused_by_us / excess_solar isn't claiming).

        Mirrors the pattern that v4.7.x B5 will copy onto appliance controllers.
        """
        actions: list[dict[str, Any]] = []

        if arbitrage_charging:
            for evse_id, config in self._evse.items():
                switch_entity = config.get("switch", "")
                if not switch_entity:
                    continue
                if evse_id in self._paused_by_arbitrage:
                    continue  # already paused
                state = self._get_evse_state(evse_id)
                if state["is_on"]:
                    actions.append({
                        "service": "switch.turn_off",
                        "target": switch_entity,
                        "data": {},
                    })
                    self._paused_by_arbitrage.add(evse_id)
                    _LOGGER.info(
                        "EV %s paused for arbitrage compound-load protection",
                        evse_id,
                    )
                else:
                    # Proactive claim: EVSE is currently off but gets
                    # added to the set so it can't auto-resume mid-cycle.
                    self._paused_by_arbitrage.add(evse_id)
                    _LOGGER.debug(
                        "EV %s claimed by arbitrage pause (was already off)",
                        evse_id,
                    )
            return actions

        # arbitrage_charging=False — release any we held
        for evse_id in list(self._paused_by_arbitrage):
            self._paused_by_arbitrage.discard(evse_id)
            config = self._evse.get(evse_id, {})
            switch_entity = config.get("switch", "")
            if not switch_entity:
                continue
            # Resume only if TOU + other pause-reasons permit
            if tou_period != "off_peak":
                _LOGGER.info(
                    "EV %s arbitrage release: TOU=%s — leaving paused",
                    evse_id, tou_period,
                )
                continue
            if (
                evse_id in self._paused_by_grid_cap
                or evse_id in self._paused_by_battery_drain
                or evse_id in self._paused_by_us
            ):
                _LOGGER.info(
                    "EV %s arbitrage release: another pause reason holds — leaving paused",
                    evse_id,
                )
                continue
            state = self._get_evse_state(evse_id)
            if not state["is_on"]:
                actions.append({
                    "service": "switch.turn_on",
                    "target": switch_entity,
                    "data": {},
                })
                _LOGGER.info("EV %s resumed (arbitrage released)", evse_id)
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

    def get_status(
        self,
        fill_priority_target_soc: int | None = None,
        plug_status: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return EV charging status for sensor.

        v4.7.6 D4: surfaces 7 new attrs — `paused_by_fill_priority`,
        `pause_reason_human`, `cooldowns`, `fill_priority_target_soc`,
        `fill_priority_solar_ok`, `evse_config`, `pause_dispatch_state`.

        v4.7.6 D6.3: when `plug_status` is passed (from EnergyCoordinator
        bridging SmartPlugController), L1 plug entries are merged as
        peer keys alongside EVSEs and included in ALL D4 attrs.
        """
        from homeassistant.util import dt as dt_util
        force_until_iso: str | None = None
        if self._force_charge_until is not None:
            now_utc = dt_util.utcnow()
            if now_utc < self._force_charge_until:
                force_until_iso = self._force_charge_until.isoformat()

        # Combined sets including L1 plug peers (D6.3). When plug_status is
        # provided, its `paused_by_*` lists are merged into the surfaced
        # totals so dashboards see a single keyspace.
        plug_status = plug_status or {}
        plug_paused_drain: list[str] = list(plug_status.get("paused_by_battery_drain", []))
        plug_paused_fp: list[str] = list(plug_status.get("paused_by_fill_priority", []))
        plug_paused_tou: list[str] = list(plug_status.get("paused_by_energy", []))

        status: dict[str, Any] = {
            "paused_by_energy": list(self._paused_by_us) + plug_paused_tou,
            "paused_by_grid_cap": list(self._paused_by_grid_cap),
            "paused_by_battery_drain": list(self._paused_by_battery_drain) + plug_paused_drain,
            # v4.5.0 D4: arbitrage compound-load mutual-exclusion set
            "paused_by_arbitrage": list(self._paused_by_arbitrage),
            # v4.7.6 D4.1
            "paused_by_fill_priority": list(self._paused_by_fill_priority) + plug_paused_fp,
            "excess_solar_active": bool(self._excess_solar_active),
            "excess_solar_evses": list(self._excess_solar_active),
            # v4.7.x D3: admin override window (None = not active)
            "force_charge_until_iso": force_until_iso,
            # v4.7.6 D4.4 / D4.5
            "fill_priority_target_soc": (
                int(fill_priority_target_soc)
                if fill_priority_target_soc is not None else None
            ),
            "fill_priority_solar_ok": bool(self._fill_priority_solar_ok),
        }

        # v4.7.6 D4.3: cooldowns — surface _battery_drain_cooldown with
        # local-timezone formatted expiry (Bug Class #11). monotonic ts is
        # converted to wall-clock via now() + (expiry - monotonic_now).
        cooldowns: dict[str, dict[str, str]] = {}
        now_mono = _time.monotonic()
        now_local = dt_util.now()
        for evse_id, expiry_mono in self._battery_drain_cooldown.items():
            if expiry_mono > now_mono:
                delta = expiry_mono - now_mono
                expires_local = now_local + timedelta(seconds=delta)
                cooldowns[evse_id] = {
                    "expires": expires_local.strftime("%H:%M %Z").strip(),
                    "reason": "manual_override_detected",
                }
        status["cooldowns"] = cooldowns

        # v4.7.6 D4.6: evse_config — surface configured self_modulates flag
        # plus the source (explicit vs default) so a user can see why URA
        # is or isn't honoring a manual switch flip.
        evse_config: dict[str, dict[str, Any]] = {}
        for evse_id, cfg in self._evse.items():
            explicit = "self_modulates" in (cfg or {})
            evse_config[evse_id] = {
                "self_modulates": self._self_modulates_for(evse_id),
                "source": "explicit" if explicit else "default",
            }
        # Merge L1 plug entries (D6.3 / D3.4 per-plug semantics).
        for plug_id, plug_cfg in plug_status.get("evse_config", {}).items():
            evse_config[plug_id] = plug_cfg
        status["evse_config"] = evse_config

        # v4.7.6 D4.7: pause_dispatch_state — last_dispatch + observed_off
        # + grace_expires. Only present for EVSEs with a recorded dispatch.
        pause_dispatch_state: dict[str, dict[str, Any]] = {}
        for evse_id, ts_mono in self._pause_dispatch_ts.items():
            delta = ts_mono - now_mono  # negative; dispatch in past
            last_dispatch_local = now_local + timedelta(seconds=delta)
            grace_expiry_local = (
                last_dispatch_local
                + timedelta(seconds=EV_PAUSE_DISPATCH_GRACE_SECONDS)
            )
            pause_dispatch_state[evse_id] = {
                "last_dispatch": last_dispatch_local.strftime("%H:%M:%S"),
                "observed_off": bool(self._observed_off_since_pause.get(evse_id, False)),
                "grace_expires": grace_expiry_local.strftime("%H:%M:%S"),
            }
        # Merge plug dispatch state if provided.
        for plug_id, dispatch_info in plug_status.get("pause_dispatch_state", {}).items():
            pause_dispatch_state[plug_id] = dispatch_info
        status["pause_dispatch_state"] = pause_dispatch_state

        # Per-EVSE entries
        for evse_id in self._evse:
            evse_state = self._get_evse_state(evse_id)
            if evse_id in self._paused_by_battery_drain:
                evse_state["energy_status"] = "battery_drain_paused"
            elif evse_id in self._paused_by_fill_priority:
                evse_state["energy_status"] = "fill_priority_paused"
            elif evse_id in self._paused_by_arbitrage:
                evse_state["energy_status"] = "arbitrage_paused"
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

        # Merge L1 plug peer entries (D6.3)
        for plug_id, plug_entry in plug_status.get("plug_entries", {}).items():
            status[plug_id] = plug_entry

        # v4.7.6 D4.2: pause_reason_human — plain-English per device.
        # Computed after per-EVSE/plug entries are populated so we can read
        # back is_on/charging for the idle/charging/off fallback.
        pause_reason_human: dict[str, str] = {}
        # EVSE precedence: fill_priority > drain > grid_cap > arbitrage > TOU > excess_solar > activity
        for evse_id in self._evse:
            ent = status.get(evse_id, {})
            soc_for_msg = ent.get("soc")  # may be None
            if evse_id in self._paused_by_fill_priority:
                pause_reason_human[evse_id] = (
                    f"holding for battery fill "
                    f"(target {status['fill_priority_target_soc']}%, solar healthy)"
                )
            elif evse_id in self._paused_by_battery_drain:
                pause_reason_human[evse_id] = "battery drain protection (paused)"
            elif evse_id in self._paused_by_grid_cap:
                pause_reason_human[evse_id] = "grid import cap"
            elif evse_id in self._paused_by_arbitrage:
                pause_reason_human[evse_id] = "arbitrage compound-load protection"
            elif evse_id in self._paused_by_us:
                pause_reason_human[evse_id] = "TOU peak/mid-peak pause"
            elif evse_id in self._excess_solar_active:
                pause_reason_human[evse_id] = "excess solar (charging)"
            elif ent.get("charging"):
                pause_reason_human[evse_id] = "charging"
            elif ent.get("is_on"):
                pause_reason_human[evse_id] = "idle"
            else:
                pause_reason_human[evse_id] = "off"
        # Merge plug pause reasons if provided
        for plug_id, reason in plug_status.get("pause_reason_human", {}).items():
            pause_reason_human[plug_id] = reason
        status["pause_reason_human"] = pause_reason_human

        return status


# ============================================================================
# Smart Plug Controller
# ============================================================================


class SmartPlugController:
    """Controls additional smart plug loads (L1 chargers) based on TOU and battery state.

    Configured via options flow as a list of entity IDs.
    v4.2.21: Pauses during peak AND mid_peak. Battery drain protection.

    v4.7.6 D6: L1 plugs are treated as peer "small EVSE" devices —
    EVSE TOU gate (D6.1), per-plug self_modulates flag (D3.4), drain
    hardening (D1 mirror), and fill-priority pause (D2 mirror).
    """

    def __init__(
        self,
        hass: HomeAssistant,
        plug_entities: list[str] | None = None,
        plug_config: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        """Initialize smart plug controller.

        v4.7.6: `plug_config` carries per-plug settings (currently just
        `self_modulates`). Falls back to defaults when missing.
        """
        self.hass = hass
        self._plugs = plug_entities or []
        self._plug_config: dict[str, dict[str, Any]] = plug_config or {}
        self._paused_by_us: set[str] = set()
        self._paused_by_battery_drain: set[str] = set()

        # v4.7.6 D1 mirror: hybrid manual-override detection state.
        self._pause_dispatch_ts: dict[str, float] = {}
        self._observed_off_since_pause: dict[str, bool] = {}
        # v4.7.6 D2 mirror
        self._paused_by_fill_priority: set[str] = set()
        # v4.7.6 D1 mirror: cooldown after detected manual override
        self._battery_drain_cooldown: dict[str, float] = {}
        # v4.7.6 D4 cache
        self._fill_priority_solar_ok: bool = False

    # ------------------------------------------------------------------
    # v4.7.6 helpers
    # ------------------------------------------------------------------

    def _self_modulates_for(self, plug_id: str) -> bool:
        """Return True when this plug is marked self-modulating (Option A)."""
        cfg = self._plug_config.get(plug_id, {})
        try:
            return bool(cfg.get("self_modulates", False))
        except Exception:  # pragma: no cover
            return False

    def _clear_pause_dispatch_state(self, plug_id: str) -> None:
        self._pause_dispatch_ts.pop(plug_id, None)
        self._observed_off_since_pause.pop(plug_id, None)

    def update_plug_config(
        self,
        plug_entities: list[str],
        plug_config: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        """Replace plug list and prune stale per-plug state."""
        self._plugs = plug_entities or []
        self._plug_config = plug_config or {}
        known = set(self._plugs)
        for tracking_set in (
            self._paused_by_us,
            self._paused_by_battery_drain,
            self._paused_by_fill_priority,
        ):
            for plug_id in list(tracking_set):
                if plug_id not in known:
                    tracking_set.discard(plug_id)
        for tracking_dict in (
            self._pause_dispatch_ts,
            self._observed_off_since_pause,
            self._battery_drain_cooldown,
        ):
            for plug_id in list(tracking_dict.keys()):
                if plug_id not in known:
                    tracking_dict.pop(plug_id, None)

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
        reserve_soc: int | None = None,
    ) -> list[dict[str, Any]]:
        """Pause smart plugs draining the home battery. Resume on recovery.

        v4.7.6 D1 mirror: hybrid self_modulates, idempotent re-pause, refined
        battery_out_of_capacity gate, observed-off / grace-window state.
        """
        actions: list[dict[str, Any]] = []
        now = _time.monotonic()

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
            is_on = state.state == "on"

            # State-update: mark observed_off once we read off after dispatch
            if (
                entity_id in self._paused_by_battery_drain
                and not is_on
                and self._observed_off_since_pause.get(entity_id) is False
            ):
                self._observed_off_since_pause[entity_id] = True

            self_modulates = self._self_modulates_for(entity_id)

            # Cooldown check (Option B only)
            cooldown_expiry = self._battery_drain_cooldown.get(entity_id)
            if cooldown_expiry is not None:
                if now < cooldown_expiry:
                    continue
                self._battery_drain_cooldown.pop(entity_id, None)

            # Hybrid manual-override branch
            if not self_modulates and entity_id in self._paused_by_battery_drain and is_on:
                dispatch_ts = self._pause_dispatch_ts.get(entity_id)
                observed_off = self._observed_off_since_pause.get(entity_id, False)
                grace_expired = (
                    dispatch_ts is not None
                    and (now - dispatch_ts) > EV_PAUSE_DISPATCH_GRACE_SECONDS
                )
                if observed_off and grace_expired:
                    self._paused_by_battery_drain.discard(entity_id)
                    self._battery_drain_cooldown[entity_id] = now + EV_BATTERY_DRAIN_COOLDOWN_SECONDS
                    self._clear_pause_dispatch_state(entity_id)
                    _LOGGER.info(
                        "Smart plug battery drain: %s manually turned on — cooldown %ds",
                        entity_id, EV_BATTERY_DRAIN_COOLDOWN_SECONDS,
                    )
                    continue
                _LOGGER.debug(
                    "Smart plug battery drain: %s is_on while paused — "
                    "observed_off=%s grace_expired=%s — falling through",
                    entity_id, observed_off, grace_expired,
                )

            if is_on and battery_discharging and soc_low:
                # v4.7.6 D1: idempotent re-pause every tick
                actions.append({
                    "service": "switch.turn_off",
                    "target": entity_id,
                    "data": {},
                })
                self._paused_by_battery_drain.add(entity_id)
                self._pause_dispatch_ts[entity_id] = now
                self._observed_off_since_pause[entity_id] = False
                _LOGGER.info(
                    "Smart plug battery drain: pausing %s (SOC=%.0f%% < %d%%)",
                    entity_id, battery_soc, soc_threshold,
                )
            elif entity_id in self._paused_by_battery_drain:
                battery_ok = not battery_discharging
                battery_out_of_capacity = (
                    battery_ok
                    and battery_soc is not None
                    and reserve_soc is not None
                    and battery_soc <= reserve_soc + 2
                )
                soc_recovered = (
                    battery_soc is not None and battery_soc >= soc_threshold + 5
                )

                if battery_out_of_capacity or soc_recovered:
                    # Don't resume if TOU pause or fill-priority is active
                    if (
                        entity_id in self._paused_by_us
                        or entity_id in self._paused_by_fill_priority
                    ):
                        self._paused_by_battery_drain.discard(entity_id)
                        self._clear_pause_dispatch_state(entity_id)
                        _LOGGER.info(
                            "Smart plug battery drain: clearing for %s (other pause active)",
                            entity_id,
                        )
                        continue
                    if not is_on:
                        actions.append({
                            "service": "switch.turn_on",
                            "target": entity_id,
                            "data": {},
                        })
                        reason = (
                            "battery out of capacity"
                            if battery_out_of_capacity else "SOC recovered"
                        )
                        _LOGGER.info("Smart plug battery drain: resuming %s (%s)", entity_id, reason)
                    self._paused_by_battery_drain.discard(entity_id)
                    self._clear_pause_dispatch_state(entity_id)

        return actions

    def determine_fill_priority_actions(
        self,
        soc: float | None,
        remaining_forecast_kwh: float | None,
        tou_period: str,
        soc_threshold: int,
        excess_solar_kwh_threshold: float,
        safety_margin_kwh: float = DEFAULT_FILL_PRIORITY_SAFETY_MARGIN_KWH,
    ) -> list[dict[str, Any]]:
        """Mirror of EVPool.determine_fill_priority_actions for L1 plugs (D2)."""
        actions: list[dict[str, Any]] = []
        now = _time.monotonic()

        forecast_healthy = (
            remaining_forecast_kwh is not None
            and remaining_forecast_kwh >= excess_solar_kwh_threshold
        )
        forecast_decayed = (
            remaining_forecast_kwh is not None
            and remaining_forecast_kwh < (
                excess_solar_kwh_threshold - safety_margin_kwh
            )
        )
        self._fill_priority_solar_ok = bool(forecast_healthy)

        if tou_period == "peak":
            for plug_id in list(self._paused_by_fill_priority):
                self._paused_by_fill_priority.discard(plug_id)
            return actions

        pause_conditions = (
            soc is not None and soc < soc_threshold and forecast_healthy
        )
        resume_soc_met = soc is not None and soc >= soc_threshold

        for entity_id in self._plugs:
            state = self.hass.states.get(entity_id)
            if state is None:
                continue
            is_on = state.state == "on"

            if (
                entity_id in self._paused_by_fill_priority
                and not is_on
                and self._observed_off_since_pause.get(entity_id) is False
            ):
                self._observed_off_since_pause[entity_id] = True

            self_modulates = self._self_modulates_for(entity_id)

            if not self_modulates and entity_id in self._paused_by_fill_priority and is_on:
                dispatch_ts = self._pause_dispatch_ts.get(entity_id)
                observed_off = self._observed_off_since_pause.get(entity_id, False)
                grace_expired = (
                    dispatch_ts is not None
                    and (now - dispatch_ts) > EV_PAUSE_DISPATCH_GRACE_SECONDS
                )
                if observed_off and grace_expired:
                    self._paused_by_fill_priority.discard(entity_id)
                    self._clear_pause_dispatch_state(entity_id)
                    _LOGGER.info(
                        "Smart plug fill-priority: %s turned on manually — releasing",
                        entity_id,
                    )
                    continue

            if pause_conditions and is_on:
                actions.append({
                    "service": "switch.turn_off",
                    "target": entity_id,
                    "data": {},
                })
                self._paused_by_fill_priority.add(entity_id)
                self._pause_dispatch_ts[entity_id] = now
                self._observed_off_since_pause[entity_id] = False
                _LOGGER.info(
                    "Smart plug fill-priority: pausing %s "
                    "(SOC=%.0f%% < %d%%, remaining=%.1f kWh >= %.1f)",
                    entity_id,
                    soc if soc is not None else -1,
                    soc_threshold,
                    remaining_forecast_kwh if remaining_forecast_kwh is not None else -1,
                    excess_solar_kwh_threshold,
                )
            elif entity_id in self._paused_by_fill_priority:
                if resume_soc_met or forecast_decayed:
                    if (
                        entity_id in self._paused_by_us
                        or entity_id in self._paused_by_battery_drain
                    ):
                        self._paused_by_fill_priority.discard(entity_id)
                        self._clear_pause_dispatch_state(entity_id)
                        continue
                    if not is_on:
                        actions.append({
                            "service": "switch.turn_on",
                            "target": entity_id,
                            "data": {},
                        })
                        reason = (
                            "SOC reached fill target"
                            if resume_soc_met else "forecast decayed"
                        )
                        _LOGGER.info(
                            "Smart plug fill-priority: resuming %s (%s)", entity_id, reason,
                        )
                    self._paused_by_fill_priority.discard(entity_id)
                    self._clear_pause_dispatch_state(entity_id)

        return actions

    def get_status(self) -> dict[str, Any]:
        """Return smart plug status with v4.7.6 D6.3 peer-shape entries.

        Returns a base dict plus per-plug `plug_entries` keyed by entity_id
        (the EVPool.get_status() merge consumer uses these as peer keys).
        """
        from homeassistant.util import dt as dt_util
        now_mono = _time.monotonic()
        now_local = dt_util.now()

        plug_entries: dict[str, dict[str, Any]] = {}
        pause_reason_human: dict[str, str] = {}
        evse_config: dict[str, dict[str, Any]] = {}
        pause_dispatch_state: dict[str, dict[str, Any]] = {}

        for entity_id in self._plugs:
            state = self.hass.states.get(entity_id)
            is_on = state is not None and state.state == "on"
            # Per D6.3: power falls back to L1_ESTIMATED_POWER_W
            estimated_power = L1_ESTIMATED_POWER_W if is_on else 0
            paused = (
                entity_id in self._paused_by_battery_drain
                or entity_id in self._paused_by_fill_priority
                or entity_id in self._paused_by_us
            )
            charging = is_on and not paused
            if entity_id in self._paused_by_battery_drain:
                energy_status = "battery_drain_paused"
                pause_reason_human[entity_id] = "battery drain protection (paused)"
            elif entity_id in self._paused_by_fill_priority:
                energy_status = "fill_priority_paused"
                pause_reason_human[entity_id] = "holding for battery fill"
            elif entity_id in self._paused_by_us:
                energy_status = "paused"
                pause_reason_human[entity_id] = "TOU peak/mid-peak pause"
            elif charging:
                energy_status = "charging"
                pause_reason_human[entity_id] = "charging"
            elif is_on:
                energy_status = "idle"
                pause_reason_human[entity_id] = "idle"
            else:
                energy_status = "off"
                pause_reason_human[entity_id] = "off"

            plug_entries[entity_id] = {
                "is_on": is_on,
                "power": estimated_power,
                "status": "on" if is_on else "off",
                "charging": bool(charging),
                "power_source": "switch_status",
                "energy_status": energy_status,
            }
            explicit = "self_modulates" in self._plug_config.get(entity_id, {})
            evse_config[entity_id] = {
                "self_modulates": self._self_modulates_for(entity_id),
                "source": "explicit" if explicit else "default",
            }
            ts_mono = self._pause_dispatch_ts.get(entity_id)
            if ts_mono is not None:
                delta = ts_mono - now_mono
                last_dispatch_local = now_local + timedelta(seconds=delta)
                grace_expiry_local = (
                    last_dispatch_local + timedelta(seconds=EV_PAUSE_DISPATCH_GRACE_SECONDS)
                )
                pause_dispatch_state[entity_id] = {
                    "last_dispatch": last_dispatch_local.strftime("%H:%M:%S"),
                    "observed_off": bool(self._observed_off_since_pause.get(entity_id, False)),
                    "grace_expires": grace_expiry_local.strftime("%H:%M:%S"),
                }

        return {
            "configured_plugs": len(self._plugs),
            "paused_by_energy": list(self._paused_by_us),
            "paused_by_battery_drain": list(self._paused_by_battery_drain),
            "paused_by_fill_priority": list(self._paused_by_fill_priority),
            "fill_priority_solar_ok": bool(self._fill_priority_solar_ok),
            "plug_entries": plug_entries,
            "pause_reason_human": pause_reason_human,
            "evse_config": evse_config,
            "pause_dispatch_state": pause_dispatch_state,
        }
