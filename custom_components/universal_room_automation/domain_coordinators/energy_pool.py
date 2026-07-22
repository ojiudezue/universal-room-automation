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
        # EVSE drain-precedence (Session B2b-i): dedicated pause-owner set,
        # peer of `_paused_by_battery_drain` / `_paused_by_arbitrage` /
        # `_paused_by_load_shed`. Mirrors the v5.3.9 pattern of one set per
        # owner (Bug Class #46 — collision-by-set-overload). Populated by
        # `EnergyCoordinator._apply_dp_transition` when the drain-precedence
        # state machine enters TRANSITIONED and requires an EVSE pause; the
        # carry-over guard in `determine_actions` (~:558) treats it as a
        # peer of the existing battery-protection owners (never pre-empted
        # by TOU ensure-on). Owner tag "dp" is claimed via
        # `_claim_pause_dispatch_owner` at the actuation entry-point. Pruned
        # in `_prune_removed_evses` alongside sibling sets.
        self._paused_by_dp: set[str] = set()
        # v4.5.0 D4: compound-load protection — pause EVSEs while arbitrage
        # is grid-charging. Solo battery 20 kW (~83A) is within main breaker;
        # battery + EV (7.4 kW) + house base (~5 kW) ≈ 134A is the panel-
        # stress scenario. This pattern (`_paused_by_<reason>` set with
        # precedence rules) is what v4.7.x B5 will extend to appliances.
        self._paused_by_arbitrage: set[str] = set()
        # load-shedding-correctness D1: dedicated pause-owner for the load-
        # shed EV tier (Bug Class #46 — collision-by-set-overload, see
        # `project_load_shedding_audit_backlog.md`). Previously the load-
        # shed cascade mutated `_paused_by_us` (shared with TOU), so during
        # peak/mid_peak the activate guard was a no-op (TOU already claimed
        # it) and de-escalation could spuriously discard TOU's pause →
        # blast-on into mid_peak. Mirrors the v5.3.9 arbitrage pattern of
        # giving each owner its own set. No side-map (only one shed intent).
        self._paused_by_load_shed: set[str] = set()
        # load-shedding-correctness fix-up C-HIGH-1: per-EVSE "was on at
        # shed-claim time" map. Release only turns the EVSE back on when
        # `was_on_at_shed=True` AND no other owner claims. A device that
        # was already off when load-shed proactively claimed it (operator
        # had it off, or manual-off during shed) must NOT be turned on
        # at release. Persisted in the bundle so it survives restart.
        self._load_shed_was_on_at_shed: dict[str, bool] = {}
        # arbitrage_solar_attainability_ladder D2: rung-label side-map.
        # Keyed by evse_id, values ∈ {"redirect", "breaker"}. Single source
        # of truth for pause membership remains `_paused_by_arbitrage`; this
        # map is *resume-policy metadata*. "redirect" = rung-1 (solar-redirect
        # pause, no grid charge commanded, fast resume when rung-0 recovers).
        # "breaker" = rung-2 (grid charge commanded, mandatory pause for
        # compound-load protection, sticky until phase exits CHARGE).
        self._arbitrage_pause_reason: dict[str, str] = {}
        self._battery_drain_cooldown: dict[str, float] = {}  # evse_id → monotonic expiry
        # v4.2.19: Track power sensor unavailability for alerting
        self._power_sensor_unavail_count: dict[str, int] = {}  # evse_id → consecutive misses
        self._power_sensor_alerted: set[str] = set()  # evse_ids already alerted
        self._power_sensor_unavail_since: dict[str, str] = {}  # evse_id → ISO timestamp
        # v4.7.x D3: URA-side admin override — open 30-min force-charge window.
        # Non-None when override is active; UTC-aware datetime at which it expires.
        # Only settable via EVSEForceChargeButton; never from HA UI directly.
        self._force_charge_until: datetime | None = None

        # v<next> WS2 D1.3: proactive off-peak hold set.
        # When the off-peak branch of determine_actions decides to ensure-on
        # an EVSE, the EVSE ID is added here. This is intent-state: it does
        # NOT re-derive on restart (unlike grid_cap / drain which re-evaluate
        # from their inputs every tick), so it MUST be persisted (D1.3 KV
        # save in `_save_evse_state`, restore in `_restore_evse_state`).
        # The set is pruned in `_prune_removed_evses` alongside the other
        # six tracking sets, and discarded on transition out of off-peak
        # (peak branch + excess-solar peak-clear).
        self._proactive_offpeak_holds: set[str] = set()

        # v4.7.6 D1: Hybrid manual-override detection state.
        # _pause_dispatch_ts[evse_id] = monotonic() at the moment URA dispatched
        # switch.turn_off. _observed_off_since_pause[evse_id] flips False → True
        # the first decision tick after dispatch where URA reads is_on=False.
        # Both reset on EVPool init (no DB persistence — Bug Class #7 mitigation
        # explicitly documented; monotonic resets on HA restart anyway).
        self._pause_dispatch_ts: dict[str, float] = {}
        self._observed_off_since_pause: dict[str, bool] = {}
        # v4.7.6 fix-up A-H2 / A-H3: reference-counted dispatch ownership.
        # When drain pauses, "battery_drain" is added; when fill-priority
        # pauses, "fill_priority" is added. Both rules share the same
        # _pause_dispatch_ts / _observed_off_since_pause entry — only when
        # ALL owners release do we wipe the tracking. Prevents handoff
        # clobber that broke manual-override detection on cross-rule
        # transitions (Review A findings A-H2 / A-H3).
        self._dispatch_owners: dict[str, set[str]] = {}

        # v4.7.6 D2: Fill-priority pause set — symmetric to drain.
        # When SOC < fill_priority_soc AND solar forecast healthy, URA pauses
        # EVSEs so the home battery fills first. Resume on SOC recovery or
        # forecast decay below safety margin.
        self._paused_by_fill_priority: set[str] = set()

        # v4.7.6 D4: Cache last computed fill-priority forecast-health flag,
        # surfaced as `fill_priority_solar_ok` on the EV status sensor.
        self._fill_priority_solar_ok: bool = False

        # ==============================================================
        # Blind-window EVSE guard (see PLANNING_ec_blind_window_evse_guard.md)
        # --------------------------------------------------------------
        # Pause-owner set for EVSEs held OFF while the reserve write path
        # is unverifiable (Envoy blind + WV inconclusive). Peer of the
        # other battery-protection owners; participates in
        # `_stronger_peer_holds`, `_prune_removed_evses`, and the
        # `_save_evse_state` persistence blob.
        #
        # `_blind_window_entry_first_at`: monotonic() timestamp of the
        # first tick the entry predicate held; consumed by the debounce
        # (CONF_BLIND_WINDOW_ENTRY_DEBOUNCE_S). None when the predicate
        # is currently false.
        #
        # `_blind_window_epoch_started_at`: wall-clock of the current
        # epoch (a single epoch spans one contiguous outage). Reset to
        # None when the guard clears. Consumed by the max-defer bound
        # (CONF_BLIND_WINDOW_MAX_DEFER_MIN) so we hand off to
        # must-start-by when an outage exceeds the cap.
        #
        # `_blind_window_defers_this_epoch`: integer count for the
        # `blind_window_defers_this_epoch` observability attribute.
        # ==============================================================
        self._paused_by_blind_window: set[str] = set()
        self._blind_window_entry_first_at: float | None = None
        self._blind_window_epoch_started_at: datetime | None = None
        self._blind_window_defers_this_epoch: int = 0
        # Fix-up D-CRIT-2 (Batch 1) — pre-engaged restore flag. Set by
        # `mark_pre_engaged_from_restore()` when the restart handler
        # rehydrates a non-empty `_paused_by_blind_window` set with a
        # non-None restored epoch. Consumed by `_blind_window_guard_engaged`
        # to bypass the debounce on the first post-restart tick: the
        # outage was already debounced pre-restart (the set only got
        # persisted BECAUSE the guard had engaged), and re-arming the
        # debounce would cause the else-branch to drain membership,
        # producing a blind ensure-on flap.
        self._blind_window_pre_engaged: bool = False

        # v4.7.6 D1 #9: Prune stale entries on init (idempotent on cold boot).
        self._prune_removed_evses()

    def _stronger_peer_holds(self, evse_id: str) -> bool:
        """C-b8 (fix-up): shared strong-peer guard.

        Returns True iff `evse_id` is currently held by ANY of the five
        battery-protection / safety / arbitrage peer owners:
        `_paused_by_battery_drain`, `_paused_by_fill_priority`,
        `_paused_by_grid_cap`, `_paused_by_arbitrage`,
        `_paused_by_load_shed`. These outrank BOTH the TOU ensure-on
        proactive-turn-on path AND the excess-solar claim path (safer
        long-term than dual mutation tests — one helper, one truth).

        NOTE: `_paused_by_dp` is INTENTIONALLY excluded here. The two
        callers have different DP semantics:
          - TOU ensure-on adds `or evse_id in self._paused_by_dp` inline
            (DP always outranks proactive off-peak turn-on).
          - Excess-solar treats `_paused_by_dp` as *conditionally*
            yieldable (INV-YIELD-1 HOLD_ONLY-only claim); the DP check
            lives at that site.
        """
        return (
            evse_id in self._paused_by_battery_drain
            or evse_id in self._paused_by_fill_priority
            or evse_id in self._paused_by_grid_cap
            or evse_id in self._paused_by_arbitrage
            or evse_id in self._paused_by_load_shed
            # Blind-window guard is a peer battery-protection owner: while
            # SOC is unresolved AND reserve write path is unverifiable, no
            # TOU / excess-solar path may claim this EVSE. Only row 2
            # force-charge preempts (see PLANNING_ec_blind_window_evse_guard.md
            # INV-BW1 escape hatch — force-charge is handled inline at each
            # site, not via this helper).
            or evse_id in self._paused_by_blind_window
        )

    # ------------------------------------------------------------------
    # Blind-window EVSE guard predicate + debounce + max-defer bound
    # (see PLANNING_ec_blind_window_evse_guard.md D1 + PROBE gates)
    # ------------------------------------------------------------------
    def _blind_window_entry_predicate(self, coord: Any) -> bool:
        """Raw entry predicate BEFORE debounce.

        Q3 ruling: use BOTH `envoy_available` (fast local) AND write-verify
        staleness on the reserve surface. False means the guard SHOULD NOT
        engage this tick (either Envoy is live OR the reserve write path is
        proveably verifiable).
        """
        try:
            if not coord.blind_hold_active:
                return False
        except Exception:  # noqa: BLE001
            return False
        try:
            return not coord.reserve_write_verifiable()
        except Exception:  # noqa: BLE001
            # Fail-safe: verifier failure is not proof of a good write.
            return True

    def _blind_window_guard_engaged(self, coord: Any) -> bool:
        """Debounced entry predicate.

        Returns True only after `CONF_BLIND_WINDOW_ENTRY_DEBOUNCE_S`
        seconds of continuous raw-predicate truth (per D3 probe: 66% of
        Envoy outages are <2min; without a debounce the fail-safe pause
        leg would flap on 90-second blips). Also stamps the epoch
        start-time on first engagement so the max-defer bound is anchored
        to the outage's actual start.
        """
        from .energy_const import CONF_BLIND_WINDOW_ENTRY_DEBOUNCE_S
        import time
        raw = self._blind_window_entry_predicate(coord)
        if not raw:
            # Clear debounce + epoch. Any pre-existing pause set membership
            # is drained by caller (release path in determine_actions) —
            # the caller consults `_blind_window_entry_predicate` directly
            # to distinguish "raw=False (envoy back)" from "raw=True but
            # debounce pending" (fix-up D-CRIT-2 else-branch narrowing).
            self._blind_window_entry_first_at = None
            if self._blind_window_epoch_started_at is not None:
                _LOGGER.info(
                    "blind-window guard: cleared (defers this epoch=%d)",
                    self._blind_window_defers_this_epoch,
                )
            self._blind_window_epoch_started_at = None
            self._blind_window_defers_this_epoch = 0
            # Fix-up D-CRIT-2: clear pre-engaged so the next real outage
            # debounces normally (only a restart-restored non-empty set
            # gets the debounce bypass).
            self._blind_window_pre_engaged = False
            return False
        # Fix-up D-CRIT-2 (Batch 1) — pre-engaged restore bypass. When the
        # restart handler rehydrated a non-empty pause set with a non-None
        # epoch, the outage was already debounced BEFORE the restart. The
        # persisted set is our proof; skip the fresh debounce so the very
        # first post-restart tick sees the guard as engaged and the
        # else-branch does NOT drain membership.
        if self._blind_window_pre_engaged:
            # One-shot: consume the flag. Subsequent ticks fall through to
            # the normal debounce-satisfied branch (epoch is already
            # populated from restore, so no re-stamp).
            self._blind_window_pre_engaged = False
            # Seed entry_first_at so subsequent ticks satisfy the debounce
            # elapsed check without another wait.
            if self._blind_window_entry_first_at is None:
                self._blind_window_entry_first_at = (
                    time.monotonic()
                    - float(CONF_BLIND_WINDOW_ENTRY_DEBOUNCE_S)
                    - 1.0
                )
            _LOGGER.info(
                "blind-window guard: engaged from restart-restore "
                "(pause set carried over, debounce bypassed)",
            )
            return True
        now_mono = time.monotonic()
        if self._blind_window_entry_first_at is None:
            self._blind_window_entry_first_at = now_mono
        elapsed = now_mono - self._blind_window_entry_first_at
        if elapsed < float(CONF_BLIND_WINDOW_ENTRY_DEBOUNCE_S):
            # Debounce still counting; do not engage.
            return False
        # Debounce satisfied — stamp epoch start-time if unset.
        if self._blind_window_epoch_started_at is None:
            try:
                from homeassistant.util import dt as dt_util
                self._blind_window_epoch_started_at = dt_util.utcnow()
            except Exception:  # noqa: BLE001
                self._blind_window_epoch_started_at = None
            _LOGGER.info(
                "blind-window guard: engaged (Envoy blind, reserve write "
                "unverifiable, debounce %ds satisfied)",
                int(CONF_BLIND_WINDOW_ENTRY_DEBOUNCE_S),
            )
        return True

    def mark_pre_engaged_from_restore(
        self, epoch_started_at: "datetime | None" = None,
    ) -> None:
        """Fix-up D-CRIT-2 (Batch 1) — mark the guard pre-engaged.

        Called from `EnergyCoordinator._restore_evse_state` immediately
        after rehydrating a non-empty `_paused_by_blind_window` set. Wires
        the persisted `_blind_window_epoch_started_at` (so the max-defer
        bound remains anchored to the outage's ACTUAL start, not the
        post-restart wall-clock — this also closes D-LOW-1) and flips the
        one-shot bypass flag consumed by `_blind_window_guard_engaged`.

        Idempotent: subsequent invocations without a fresh epoch will
        overwrite with None (defensive; caller should never do this).
        """
        self._blind_window_epoch_started_at = epoch_started_at
        self._blind_window_pre_engaged = True

    def _blind_window_max_defer_exceeded(self) -> bool:
        """True when the current epoch has exceeded the max-defer bound.

        Per D3 probe: ~2-3 outages >30min per day; an unbounded defer would
        strand overnight EVSE charging. When exceeded, the guard yields to
        the DP must-start-by machinery (ensure-on paths proceed normally;
        the fail-safe pause leg still holds mid-charge unless the envelope
        proves SOC is safe).
        """
        from .energy_const import CONF_BLIND_WINDOW_MAX_DEFER_MIN
        cap = int(CONF_BLIND_WINDOW_MAX_DEFER_MIN)
        if cap <= 0:
            # Kill-switch: value 0 disables the defer (guard is a no-op).
            return True
        if self._blind_window_epoch_started_at is None:
            return False
        try:
            from homeassistant.util import dt as dt_util
            elapsed_min = (
                dt_util.utcnow() - self._blind_window_epoch_started_at
            ).total_seconds() / 60.0
        except Exception:  # noqa: BLE001
            return False
        return elapsed_min >= cap

    def _blind_window_envelope_permits_ride(
        self, coord: Any, drain_target_soc: int | None,
    ) -> bool:
        """Q1/Q4: mid-charge ride permission via the LKG envelope.

        Returns True iff the envelope's lower bound is >= the drain
        threshold — a bounded-uncertainty proof that SOC has not fallen
        below the guard's protection floor, so an already-on EVSE may
        legitimately ride. Also permits ride if D4 mains-export shows
        active grid export (battery-not-discharging from a non-Envoy
        source). Returns False when neither proof is available
        (default fail-safe: pause).
        """
        # D4 non-Envoy witness (Q1 branch a).
        try:
            exp = coord.mains_export_active()
        except Exception:  # noqa: BLE001
            exp = None
        if exp is True:
            return True
        # LKG envelope lower bound >= threshold (Q1 branch b / Q4).
        if drain_target_soc is None:
            return False
        try:
            env = coord.soc_envelope()
        except Exception:  # noqa: BLE001
            env = None
        if env is None:
            return False
        lower, _upper = env
        return lower >= float(drain_target_soc)

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

        v4.7.6 fix-up A-H2 / A-H3: this unconditional wipe is the legacy
        callsite — kept for cooldown engagement and terminal-resume paths
        where the rule definitively no longer needs the tracking AND no
        other rule owns it. Use `_release_pause_dispatch_owner()` instead
        on cross-rule handoff branches to preserve the OTHER rule's
        dispatch state.
        """
        self._pause_dispatch_ts.pop(evse_id, None)
        self._observed_off_since_pause.pop(evse_id, None)
        self._dispatch_owners.pop(evse_id, None)

    def _claim_pause_dispatch_owner(self, evse_id: str, owner: str) -> None:
        """Mark `owner` as holding the dispatch tracking for `evse_id`.

        Idempotent: re-claims don't duplicate. Use at every pause-dispatch
        site so the owner-set accurately reflects which rules still need
        the shared `_pause_dispatch_ts` / `_observed_off_since_pause`.
        """
        owners = self._dispatch_owners.setdefault(evse_id, set())
        owners.add(owner)

    def _release_pause_dispatch_owner(self, evse_id: str, owner: str) -> None:
        """Release `owner`'s claim. Wipe tracking only when no owners remain.

        v4.7.6 fix-up A-H2 / A-H3 + A-M4 (peak-clear leak): if other rules
        still own the dispatch tracking, leave `_pause_dispatch_ts` and
        `_observed_off_since_pause` intact so their manual-override
        detection keeps working.
        """
        owners = self._dispatch_owners.get(evse_id)
        if owners is None:
            # Legacy / never-claimed path — fall back to full wipe.
            self._pause_dispatch_ts.pop(evse_id, None)
            self._observed_off_since_pause.pop(evse_id, None)
            return
        owners.discard(owner)
        if not owners:
            self._dispatch_owners.pop(evse_id, None)
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
            # v<next> WS2 D1.3: prune proactive off-peak holds for removed EVSEs.
            self._proactive_offpeak_holds,
            # EVSE drain-precedence (B2b-i): mirror sibling owners.
            self._paused_by_dp,
            # Blind-window guard (D1): peer battery-protection owner.
            self._paused_by_blind_window,
        ):
            for evse_id in list(tracking_set):
                if evse_id not in known:
                    tracking_set.discard(evse_id)
        for tracking_dict in (
            self._battery_drain_cooldown,
            self._pause_dispatch_ts,
            self._observed_off_since_pause,
            self._dispatch_owners,
            self._power_sensor_unavail_count,
            self._power_sensor_unavail_since,
            self._arbitrage_pause_reason,
        ):
            for evse_id in list(tracking_dict.keys()):
                if evse_id not in known:
                    tracking_dict.pop(evse_id, None)
        for evse_id in list(self._power_sensor_alerted):
            if evse_id not in known:
                self._power_sensor_alerted.discard(evse_id)

    # v4.7.6 fix-up B-H1 / C-M1: `update_evse_config` was dead code — no
    # production caller. The canonical config-update path is HA's options-flow
    # reload (`hass.config_entries.async_reload`) which rebuilds EVPool from
    # scratch via `async_setup_entry`. Removed in v4.7.6 review fix-up to
    # avoid a footgun for future contributors. `_prune_removed_evses()` runs
    # in `__init__` and handles the equivalent state cleanup.

    def attach_coord(self, coord: Any) -> None:
        """Wire the owning EnergyCoordinator so the blind-window guard
        may consult its blind_hold_active / reserve_write_verifiable /
        soc_envelope / mains_export_active predicates without
        altering the `determine_actions(...)` public signature (which
        many production sibling controllers + test spies rely on).
        """
        self._energy_coord = coord

    def determine_actions(
        self,
        tou_period: str,
        grid_charge_on: bool = False,
        coord: Any = None,
    ) -> list[dict[str, Any]]:
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

        Fix-up B-CRIT-1 / B-HIGH-1 (breaker-safety resume-side guard):
        ``grid_charge_on`` — True when EITHER this tick's battery decision
        commands ``charge_from_grid=True`` OR the live grid switch is ON
        (hardware-derived, e.g. mid-charge reboot). When True, the off-peak
        ensure-on branch SKIPS the `switch.turn_on` AND claims the EVSE
        for ``_paused_by_arbitrage`` with the "breaker" label so the next
        breaker-pause chokepoint tick already finds the EV correctly
        owned. This is the second leg of the bidirectional breaker
        invariant: NO EV may be commanded ON while ``charge_from_grid``
        is commanded or ON.
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
                # B-MED-2 fix-up: clear stale proactive-hold bookkeeping FIRST,
                # before any `continue` short-circuit, so the hold-set can't
                # leak when excess_solar or force_charge wins the iteration.
                # Safe because no peak-period path wants the EVSE in the
                # hold set — the set is off-peak-intent only.
                self._proactive_offpeak_holds.discard(evse_id)
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
            elif tou_period == "off_peak":
                # =====================================================
                # Row 2.5 — Blind-Window EVSE Guard
                # (see PLANNING_ec_blind_window_evse_guard.md D1 + INV-BW1)
                # -----------------------------------------------------
                # BEFORE any of the existing row-2..N chains: while SOC is
                # unresolved AND the reserve write path is unverifiable,
                # DEFER turn-on and PAUSE any already-on EVSE (fail-safe
                # leg — Q1). Row 2 force-charge preempts (INV-BW1 escape).
                # Debounce prevents flapping on sub-2-min Envoy blips
                # (66% of outages per D3 probe). Max-defer bound hands
                # off to must-start-by on long outages (~2-3/day > 30min).
                # =====================================================
                _bw_coord = coord if coord is not None else getattr(
                    self, "_energy_coord", None,
                )
                if _bw_coord is not None and not force_charge_active:
                    coord = _bw_coord  # for the block below
                    engaged = self._blind_window_guard_engaged(coord)
                    max_defer_exceeded = self._blind_window_max_defer_exceeded()
                    if engaged and not max_defer_exceeded:
                        # Fail-safe pause leg (Q1): pause mid-charge UNLESS
                        # the LKG envelope lower bound >= drain threshold
                        # OR mains-export active (battery not discharging).
                        drain_target = None
                        try:
                            drain_target = int(
                                getattr(coord, "_ev_battery_drain_soc", None) or 0
                            ) or None
                        except Exception:  # noqa: BLE001
                            drain_target = None
                        ride_ok = self._blind_window_envelope_permits_ride(
                            coord, drain_target,
                        )
                        # Newly engage or re-affirm the pause set.
                        if evse_id not in self._paused_by_blind_window:
                            self._paused_by_blind_window.add(evse_id)
                            self._proactive_offpeak_holds.discard(evse_id)
                        if state["is_on"] and not ride_ok:
                            actions.append({
                                "service": "switch.turn_off",
                                "target": switch_entity,
                                "data": {},
                            })
                            _LOGGER.info(
                                "blind-window guard: pausing %s "
                                "(Envoy blind, reserve write unverifiable)",
                                evse_id,
                            )
                        elif not state["is_on"]:
                            _LOGGER.info(
                                "blind-window guard: deferring ensure-on for %s",
                                evse_id,
                            )
                        self._blind_window_defers_this_epoch += 1
                        continue
                    elif engaged and max_defer_exceeded:
                        # Max defer exceeded — yield to must-start-by
                        # (fall through into normal off-peak ensure-on
                        # semantics). Release the pause claim; the
                        # normal row-2 force-charge / must-start-by
                        # timer path is the authority now.
                        if evse_id in self._paused_by_blind_window:
                            self._paused_by_blind_window.discard(evse_id)
                            _LOGGER.info(
                                "blind-window guard: max-defer bound "
                                "exceeded for %s — yielding to must-start-by",
                                evse_id,
                            )
                    else:
                        # Fix-up D-CRIT-2 (Batch 1) — narrow drain gate.
                        # `_blind_window_guard_engaged` returning False has
                        # TWO causes:
                        #   (i) raw entry predicate is False (envoy back /
                        #       reserve write verifiable — the real "outage
                        #       ended" case), OR
                        #   (ii) raw is True but the debounce is still
                        #        counting (transient blip that may extend
                        #        into a real outage), OR the pre-engaged
                        #        one-shot was consumed on a prior tick and
                        #        state is briefly ambiguous.
                        # Only case (i) permits draining `_paused_by_blind_window`.
                        # Draining under (ii) would produce the blind
                        # ensure-on flap D-CRIT-2 called out: on the very
                        # next tick the guard re-engages (or force-charge
                        # gate reaches ensure-on) with a car we already
                        # explicitly paused.
                        raw_false = not self._blind_window_entry_predicate(coord)
                        if raw_false and evse_id in self._paused_by_blind_window:
                            self._paused_by_blind_window.discard(evse_id)

                # v<next> WS2 D2.1: off-peak ensure-on with guard precedence.
                #
                # Replaces the legacy resume-only rule (which only un-paused
                # URA's own _paused_by_us entries) with an *ensure-on with
                # precedence pre-check*. Why: a fresh plug-in overnight, or
                # the post-sunset hand-off from excess-solar, both leave the
                # EVSE in NO pause-set — and the legacy branch silently
                # no-op'd, so the car never charged by morning.
                #
                # Carry-over guards always win — battery protections must
                # not be pre-empted by TOU intent. If a guard fires NEWLY
                # this tick (so we turn ON here, then it fires AFTER us and
                # turns OFF), the user sees a single-tick on→off flap. This
                # is acceptable; the analogous excess-solar path
                # (`determine_excess_solar_actions` + downstream guards)
                # already permits the same flap shape today. Documenting
                # this here so a future reviewer doesn't mistake it for a
                # bug — actual no-flap protection on this tick comes from
                # the prior-tick carry-over check below.
                #
                # Force-charge is its own escape hatch (D2.3): when active
                # we skip the proactive-on claim so `_proactive_offpeak_holds`
                # doesn't gain membership for a charge that was authorized
                # for a different reason.

                # Fix-up B3 (Batch 2) — force-charge preempt drain.
                # `_stronger_peer_holds` now INCLUDES `_paused_by_blind_window`,
                # which means an EVSE the guard paused pre-force-charge
                # would still trigger the 2a peer-guard `continue` below
                # and force-charge could not preempt. Per INV-BW1 escape
                # hatch (row 2 force-charge is the sole authoritative
                # override), drain blind-window membership FIRST so row 2
                # authority actually reaches the ensure-on dispatch.
                # Force-charge does NOT drain other peer sets (drain /
                # fill-priority / grid-cap / arbitrage / load-shed) —
                # those retain their existing precedence. This is the
                # narrowest possible mutation to close the deadlock.
                if force_charge_active and evse_id in self._paused_by_blind_window:
                    self._paused_by_blind_window.discard(evse_id)
                    _LOGGER.info(
                        "blind-window guard: releasing %s to force-charge "
                        "(INV-BW1 escape hatch)",
                        evse_id,
                    )

                # 2a: carry-over guards (battery protections) win — don't
                # pre-empt the downstream rules; drop legacy _paused_by_us
                # bookkeeping and clear any stale proactive-hold claim so
                # the guard rule keeps the EVSE off.
                if (
                    # C-b8 (fix-up): shared five-peer guard extracted to
                    # `_stronger_peer_holds`; the DP check stays inline
                    # (proactive TOU turn-on ALWAYS defers to DP).
                    self._stronger_peer_holds(evse_id)
                    # EVSE drain-precedence (B2b-i): peer battery-protection
                    # owner. Force-charge is the sole authoritative override
                    # per plan §127 (interaction matrix row 1); TOU ensure-on
                    # must NEVER release a DP pause.
                    or evse_id in self._paused_by_dp
                ):
                    # load-shedding-correctness D1: load-shed is now a
                    # peer pause-owner — its carry-over wins over TOU
                    # ensure-on, exactly like arbitrage/drain/fill-priority.
                    self._paused_by_us.discard(evse_id)
                    self._proactive_offpeak_holds.discard(evse_id)
                    continue

                # Fix-up B-CRIT-1 / B-HIGH-1 (breaker-safety resume-side
                # guard). When the battery is currently commanding (or
                # the live switch shows) ``charge_from_grid=True``, do
                # NOT ensure-on. Force-claim the EVSE for arbitrage
                # under the "breaker" label so the resume-policy
                # (carry-over guard above on subsequent ticks) keeps it
                # off until grid charge ends. This is the post-restart
                # mid-charge recovery path: even with an empty
                # ``_paused_by_arbitrage`` set, ensure-on cannot turn
                # the EV on while hardware shows grid charging.
                if grid_charge_on:
                    self._paused_by_arbitrage.add(evse_id)
                    self._arbitrage_pause_reason[evse_id] = "breaker"
                    self._paused_by_us.discard(evse_id)
                    self._proactive_offpeak_holds.discard(evse_id)
                    # If the switch is currently ON (e.g. user manually
                    # enabled OR pre-restart state), command it OFF —
                    # the grid is already pulling 20 kW; an EV ON now
                    # is the compound-load breaker condition.
                    if state["is_on"]:
                        actions.append({
                            "service": "switch.turn_off",
                            "target": switch_entity,
                            "data": {},
                        })
                        _LOGGER.info(
                            "EV %s paused (breaker-safety: grid charge active)",
                            evse_id,
                        )
                    continue

                # 2b: force-charge already authorizes turn-on via its own
                # path (D3). Skip the proactive-on claim so the hold-set
                # cleanly reflects only TOU-driven holds.
                # B-LOW-4 fix-up: also clear any prior-tick hold (mirrors
                # the 2a carry-over-guard cleanup) so a stale hold doesn't
                # survive the force-charge window.
                if force_charge_active:
                    self._proactive_offpeak_holds.discard(evse_id)
                    continue

                # 2c: ensure-on. Re-issue turn_on idempotently each tick
                # (Bug Class #43 — intent-state, not a "we already did
                # this" short-circuit). If the user manually disables the
                # switch mid-off-peak, the next tick re-enforces.
                if not state["is_on"]:
                    actions.append({
                        "service": "switch.turn_on",
                        "target": switch_entity,
                        "data": {},
                    })
                    _LOGGER.info(
                        "EV: proactive off-peak turn-on for %s", evse_id
                    )

                # 2d: claim the hold; drop legacy TOU bookkeeping (matches
                # the v4.7.x semantics where _paused_by_us tracks "we paused
                # it", and an off-peak proactive-on is the inverse intent).
                # B-LOW-3 fix-up: dual membership with `_excess_solar_active`
                # is intentional — both can be true off-peak. `_classify_evse`
                # resolves the human reason: excess_solar wins ("excess solar
                # (charging)") over proactive-on ("off-peak proactive
                # turn-on"); see precedence ordering in `_classify_evse`.
                self._proactive_offpeak_holds.add(evse_id)
                self._paused_by_us.discard(evse_id)
            else:
                # B-LOW-2 fix-up: unknown/empty TOU period — explicit safe
                # no-op (do not proactively turn-on or pause). The legacy
                # bare-`else` would have triggered proactive turn-on for
                # any unexpected period string. The supported values are
                # enforced by `EnergyTOUEngine._VALID_PERIODS` in
                # `energy_tou.py:37` ({"peak", "mid_peak", "off_peak"}),
                # so reaching this branch means upstream contract drift.
                continue

        return actions

    # -------------------------------------------------------------------------
    # v4.7.x D3: Admin force-charge override API
    # -------------------------------------------------------------------------

    @property
    def force_charge_until(self) -> datetime | None:
        """Return the UTC expiry of the current force-charge window, or None."""
        return self._force_charge_until

    def _is_force_charge_active(self) -> bool:
        """Return True when the admin force-charge window is currently active.

        v4.7.6 fix-up A-H1: precedence rule — Force-Charge > all URA pause
        rules (drain, fill-priority, grid-cap, arbitrage, TOU). When this is
        True, every pause method early-returns AND releases any current set
        membership so the EVSE can charge.

        Auto-expires: clears `_force_charge_until` on first expired check.
        """
        if self._force_charge_until is None:
            return False
        try:
            from homeassistant.util import dt as dt_util
            now_utc = dt_util.utcnow()
        except Exception:  # pragma: no cover — defensive
            return False
        if now_utc < self._force_charge_until:
            return True
        # Expired — clear so subsequent calls don't re-check.
        self._force_charge_until = None
        return False

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
        dp_carrier_state: str | None = None,
        coord: Any = None,
    ) -> list[dict[str, Any]]:
        """Determine whether to turn on EVSEs for excess solar charging.

        Only during off-peak or mid-peak (never peak — battery needed).
        Conditions to activate: SOC >= threshold AND remaining forecast >= kwh threshold.

        `dp_carrier_state` is the value of `EnergyCoordinator._dp_carrier.state`
        (a `DPState` StrEnum value, so its `.value` matches the strings
        "hold_only" / "transitioned" / "must_start_forced" / etc.). The
        caller passes it as a plain string to keep this module free of a
        DP-module import (mirrors how `tou_period` / `soc` / `remaining`
        are already threaded in from the energy coordinator, NOT read
        via cross-module attribute).

        Sticky-DP yield (INV-YIELD-1 / INV-YIELD-2 — see
        docs/planning/PLANNING_dp_sticky_yields_to_excess_solar.md):
        an EVSE in `_paused_by_dp` is claimable by excess-solar IFF
        `dp_carrier_state == "hold_only"` (deferred-reversion orphan,
        no active BAEC transition). TRANSITIONED / MUST_START_FORCED /
        HOLD_PRE_EVAL / EVAL_TRANSITION never yield: an active drain
        transition MUST NOT be short-circuited by a mid-drain solar
        spike (would collapse the reserve the drain was engineered to
        build). When `dp_carrier_state is None` we conservatively refuse
        the yield (treat as not-HOLD_ONLY).
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
                # v<next> WS2 D2.2: also clear any proactive off-peak hold
                # claim — excess-solar peak-clear is a transition out of
                # off-peak intent.
                self._proactive_offpeak_holds.discard(evse_id)
            return actions

        # Blind-window guard for the excess-solar path (row 2.5 sibling).
        # When Envoy is blind + reserve write unverifiable, the caller
        # cannot trust `soc`. D4 fallback: if operator wired
        # `CONF_ENERGY_MAINS_EXPORT_ENTITY`, use export>threshold as the
        # Envoy-independent excess-solar signal; else defer.
        if coord is None:
            coord = getattr(self, "_energy_coord", None)
        if coord is not None:
            engaged = self._blind_window_guard_engaged(coord)
            max_defer_exceeded = self._blind_window_max_defer_exceeded()
            # Fix-up B4 (Batch 2) — guard-not-engaged drain (symmetric to
            # the off_peak else-branch narrowing D-CRIT-2 (c)). When the
            # RAW predicate is confirmed False (envoy back, reserve write
            # verifiable), drain any stale membership so a daytime recovery
            # allows the excess-solar claim path to proceed. Draining only
            # on raw-false (not on `not engaged`) preserves the debounce-
            # pending semantics: a transient blip must not drop membership.
            if not self._blind_window_entry_predicate(coord):
                # raw False => outage has ended (or never engaged).
                for _eid in list(self._paused_by_blind_window):
                    self._paused_by_blind_window.discard(_eid)
            if engaged and not max_defer_exceeded:
                # Fix-up C-HIGH-2 + D-MED-1 (Batch 3) — CONTINUE-permission
                # semantics for D4 witness.
                #
                # Previously the witness-True branch fell through to the
                # normal claim path. That leg was LIVE-UNREACHABLE (SOC is
                # None while blind → `conditions_met` False → no new
                # claims), and a test could only exercise it by feeding
                # impossible state (SOC + blind at once). The correct
                # semantic is narrower and testable:
                #
                #   * Guard engaged AND witness True AND envelope permits
                #     ride → an ALREADY-ACTIVE excess-solar EVSE may
                #     CONTINUE (we do NOT turn it off, we do NOT drain the
                #     claim, and we do NOT gain `_paused_by_blind_window`
                #     membership). New claims (EVSE not already in
                #     `_excess_solar_active`) remain refused — we return
                #     early so the normal claim path below cannot fire.
                #
                #   * Any other combination (witness None/False OR
                #     envelope denies) → fail-safe DROP leg: turn off any
                #     active excess-solar EVSE, drain the claim set, and
                #     add to `_paused_by_blind_window` so the guard's
                #     other precedence gates keep it off.
                try:
                    exp = coord.mains_export_active()
                except Exception:  # noqa: BLE001
                    exp = None
                # Envelope check for CONTINUE-permission — INDEPENDENT of
                # the witness (both conditions required per C-HIGH-2
                # ruling). We do NOT reuse `_blind_window_envelope_permits_ride`
                # here because that helper short-circuits True on witness
                # alone (a legitimate optimization for the off_peak
                # fail-safe ride leg where either signal suffices, but
                # wrong for CONTINUE-permission which requires BOTH).
                drain_target_for_ride = None
                try:
                    drain_target_for_ride = int(
                        getattr(coord, "_ev_battery_drain_soc", None) or 0
                    ) or None
                except Exception:  # noqa: BLE001
                    drain_target_for_ride = None
                envelope_ride_ok = False
                if drain_target_for_ride is not None:
                    try:
                        env_bounds = coord.soc_envelope()
                    except Exception:  # noqa: BLE001
                        env_bounds = None
                    if env_bounds is not None:
                        _lower, _upper = env_bounds
                        envelope_ride_ok = (
                            _lower >= float(drain_target_for_ride)
                        )
                continue_permission = (exp is True) and envelope_ride_ok
                if continue_permission:
                    # Active EVSEs continue; NEW claims still refused.
                    # Log once per epoch-defer for observability.
                    self._blind_window_defers_this_epoch += 1
                    for _active in self._excess_solar_active:
                        _LOGGER.debug(
                            "blind-window guard: permitting excess-solar "
                            "CONTINUE for %s (witness + envelope both ok)",
                            _active,
                        )
                    return actions
                # DROP leg — fail-safe pause.
                for evse_id in list(self._excess_solar_active):
                    config = self._evse.get(evse_id, {})
                    switch_entity = config.get("switch", "")
                    if switch_entity:
                        st = self._get_evse_state(evse_id)
                        if st["is_on"]:
                            actions.append({
                                "service": "switch.turn_off",
                                "target": switch_entity,
                                "data": {},
                            })
                            _LOGGER.info(
                                "blind-window guard: dropping excess-solar "
                                "claim on %s (Envoy blind, witness=%r, "
                                "envelope_ok=%s)",
                                evse_id, exp, envelope_ride_ok,
                            )
                    self._excess_solar_active.discard(evse_id)
                    self._paused_by_blind_window.add(evse_id)
                self._blind_window_defers_this_epoch += 1
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
                # v4.7.6 fix-up A-M1: defense-in-depth — excess-solar turn-on
                # must NOT re-enable an EVSE held by a stronger pause reason
                # (drain, fill-priority, grid-cap, arbitrage). TOU/`_paused_by_us`
                # is the only pause set that excess-solar legitimately claims
                # against (battery-full + solar-surplus is the design override).
                if self._stronger_peer_holds(evse_id):
                    # C-b8 (fix-up): shared five-peer guard. The DP
                    # sticky-yield check (INV-YIELD-1/2) lives BELOW —
                    # it is not a "stronger peer", it is a conditional
                    # yield target.
                    _LOGGER.debug(
                        "Excess solar: %s held by stronger pause reason — skipping",
                        evse_id,
                    )
                    continue
                # Session B2b-ii peer-skip, refined by the sticky-DP
                # yield (INV-YIELD-1/2). `_paused_by_dp` retains membership
                # under the sticky-defer branch of `_apply_dp_reversion`
                # even after the DP carrier collapses to HOLD_ONLY (no
                # active transition, waiting on non-off_peak TOU). In
                # that deferred-orphan case, excess-solar legitimately
                # claims the EVSE. TRANSITIONED / MUST_START_FORCED (and
                # the transitional HOLD_PRE_EVAL / EVAL_TRANSITION) remain
                # strictly protected — draining the house battery to the
                # drain target so night charging runs off-peak MUST NOT
                # be short-circuited by a mid-drain solar spike. See
                # docs/planning/PLANNING_dp_sticky_yields_to_excess_solar.md.
                _dp_yield_ok = (
                    evse_id in self._paused_by_dp
                    and dp_carrier_state == "hold_only"
                )
                if evse_id in self._paused_by_dp and not _dp_yield_ok:
                    _LOGGER.debug(
                        "Excess solar: %s held by stronger pause reason — skipping "
                        "(dp_carrier=%s)",
                        evse_id, dp_carrier_state,
                    )
                    continue
                # Claim EVSE from TOU pause if needed
                was_tou_paused = evse_id in self._paused_by_us
                if was_tou_paused:
                    self._paused_by_us.discard(evse_id)
                # INV-YIELD-1 atomic ownership handoff: mirror the
                # `_paused_by_us` claim above but drop the "dp" owner
                # instead. Runs BEFORE the dispatch append so there is
                # no ownerless gap — the four mutations (discard set,
                # release "dp" owner, add to _excess_solar_active,
                # append turn_on) happen synchronously (no await) so
                # no concurrent tick observes the EVSE with neither
                # owner nor claim. Persists on the next _save_evse_state
                # tick alongside the rest of the ownership blob.
                _yielded_from_dp = _dp_yield_ok
                if _yielded_from_dp:
                    self._paused_by_dp.discard(evse_id)
                    self._release_pause_dispatch_owner(evse_id, "dp")
                state = self._get_evse_state(evse_id)
                if not state["is_on"]:
                    actions.append({
                        "service": "switch.turn_on",
                        "target": switch_entity,
                        "data": {},
                    })
                    self._excess_solar_active.add(evse_id)
                    if _yielded_from_dp:
                        _LOGGER.info(
                            "excess solar: claimed %s from deferred DP hold "
                            "(dp_carrier=HOLD_ONLY, SOC=%.0f, remaining=%.1f kWh)",
                            evse_id, soc, remaining_forecast_kwh,
                        )
                    else:
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
                elif _yielded_from_dp:
                    # EVSE already on but we just took ownership from DP —
                    # complete the handoff by claiming into excess_solar
                    # so the ownership blob isn't left owner-less.
                    self._excess_solar_active.add(evse_id)
                    _LOGGER.info(
                        "excess solar: claimed %s from deferred DP hold "
                        "(already on, dp_carrier=HOLD_ONLY)",
                        evse_id,
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
                    # load-shedding-correctness fix-up A-HIGH-2:
                    # also defer to load_shed / fill_priority / arbitrage /
                    # us so grid-cap resume can't blast an EVSE on that
                    # any other owner still claims.
                    if (
                        evse_id in self._paused_by_battery_drain
                        or evse_id in self._paused_by_load_shed
                        or evse_id in self._paused_by_fill_priority
                        or evse_id in self._paused_by_arbitrage
                        or evse_id in self._paused_by_us
                        # D-HIGH-1 (Batch 2): blind-window guard is a peer
                        # battery-protection owner; grid-cap resume must
                        # NOT turn the EVSE on while the guard still
                        # claims it (blind ensure-on = D-CRIT-2 flap).
                        or evse_id in self._paused_by_blind_window
                    ):
                        self._paused_by_grid_cap.discard(evse_id)
                        _LOGGER.info(
                            "EV grid cap: clearing for %s (other pause owner active)",
                            evse_id,
                        )
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
        solar_replenishing: bool = False,
        is_offpeak: bool = False,
    ) -> list[dict[str, Any]]:
        """Pause EVSEs draining the home battery. Resume on recovery.

        Pauses when: EVSE is charging AND battery is discharging AND SOC < threshold.

        EV dead-band fix-up (Fix 2): `is_offpeak` gates the F substitution
        and the release-side sticky. When False (peak/mid_peak) the release
        semantics are pre-fix (release at static reserve+2) and the sticky
        is disabled — the drain pause must remain a hard backstop against
        deep discharge during expensive-grid windows.

        EV charge-start dead-band fix: the `reserve_soc` kwarg is repurposed
        as the **effective release floor** F = max(static reserve_soc,
        current_offpeak_drain_target()). Threaded by the caller from
        `BatteryStrategy` so the release gate reconciles with the
        drain-target the battery emitter is actually parking at. Before
        this fix, the release used the static reserve (10) while the
        battery parked at the higher drain target (e.g. 40 for
        `tomorrow=unknown`) → SOC never dropped low enough to trigger
        `battery_out_of_capacity` → EV silently starved overnight.
        Excellent solar (drain_target=10=reserve) is byte-identical.

        Release-side sticky (Operator D4 Option 1): once SOC is at/below the
        effective release floor F (within ±2% hysteresis), the pause gate
        does NOT re-engage even if the EV briefly discharges the battery
        (Enphase hold has ~5-15min lag). Prevents 1-tick oscillation at
        the floor where the drain rule has nothing left to protect.

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

        # v4.7.6 fix-up A-H1: Force-Charge precedence. When the admin override
        # is active, drain MUST skip pause AND release any current ownership
        # so the EVSE can charge. Per Force-Charge contract: this is the
        # single authoritative override across all URA pause rules.
        force_charge_active = self._is_force_charge_active()

        for evse_id, config in self._evse.items():
            switch_entity = config.get("switch", "")
            if not switch_entity:
                continue
            # v4.7.6 fix-up A-H1: Force-Charge bypasses drain entirely.
            if force_charge_active:
                if evse_id in self._paused_by_battery_drain:
                    self._paused_by_battery_drain.discard(evse_id)
                    self._release_pause_dispatch_owner(evse_id, "battery_drain")
                    _LOGGER.info(
                        "EV battery drain: %s cleared — force-charge override active",
                        evse_id,
                    )
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
                    # v4.7.6 fix-up A-H2: release drain's claim only — if
                    # fill_priority still owns the dispatch tracking it stays.
                    self._release_pause_dispatch_owner(evse_id, "battery_drain")
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
            # EV dead-band fix-up (Fix 3): BAND the sticky as F−2 ≤ SOC ≤ F+2
            # (the plan's ±2 hysteresis, not one-sided). Below F−2 the pause
            # MUST re-arm — if Enphase reserve-hold ever fails to catch, the
            # EV could otherwise drain the battery to 0. Fix 2: sticky only
            # active during off_peak (elsewhere the drain pause is a
            # hard backstop and must not be suppressed).
            in_sticky_band = (
                is_offpeak
                and battery_soc is not None
                and reserve_soc is not None
                and (reserve_soc - 2) <= battery_soc <= (reserve_soc + 2)
            )
            if (
                in_sticky_band
                and state["charging"]
                and battery_discharging
                and soc_low
                and not getattr(self, "_deadband_sticky_logged", False)
            ):
                # Fix 4: once-per-process INFO for band collapse observability.
                _LOGGER.info(
                    "EV drain sticky: suppressing re-pause of %s at floor "
                    "(SOC=%.0f%%, F=%d%%, band=F±2, is_offpeak=True) — "
                    "reserve hold will land within 5-15 min",
                    evse_id, battery_soc, reserve_soc,
                )
                self._deadband_sticky_logged = True

            if (
                state["charging"]
                and battery_discharging
                and soc_low
                and not in_sticky_band
            ):
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
                # v4.7.6 fix-up A-H2: claim drain ownership of the shared
                # dispatch tracking. Released only via the handoff branches
                # below or `_release_pause_dispatch_owner` on terminal resume.
                self._claim_pause_dispatch_owner(evse_id, "battery_drain")
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
                # evse-offpeak-fill-release D2: solar-gate the high-SOC release.
                # `soc_recovered = SOC >= soc_threshold+5` is a DAYTIME-solar
                # assumption ("solar refilled the battery, the EV can share").
                # At night (no solar) it wrongly lets the EV drain a high-SOC
                # battery (~85→79) — high L2-rate battery wear and NOT
                # guaranteed-grid. Gate it on solar ACTIVELY replenishing
                # (TIME-windowed `_expected_solar_surplus_pct` and/or live
                # `battery_power > +100W`, computed by the caller — NEVER raw
                # `solcast_remaining`, which is high all night and is the
                # original bug). At night the ONLY release is
                # `battery_out_of_capacity` (reserve) → overnight EV charge is
                # reserve-gated → guaranteed grid, sparing battery wear.
                soc_recovered = (
                    solar_replenishing
                    and battery_soc is not None
                    and battery_soc >= soc_threshold + 5
                )

                if battery_out_of_capacity or soc_recovered:
                    if not state["is_on"]:
                        # Don't resume if another pause reason is active.
                        # v4.7.6 fix-up A-H2: release drain's claim only —
                        # the receiving rule (fill_priority/us/...) may still
                        # own the dispatch tracking.
                        if (
                            evse_id in self._paused_by_grid_cap
                            or evse_id in self._paused_by_us
                            or evse_id in self._paused_by_arbitrage
                            or evse_id in self._paused_by_fill_priority
                            # D-HIGH-1 (Batch 2): blind-window guard peer.
                            or evse_id in self._paused_by_blind_window
                        ):
                            self._paused_by_battery_drain.discard(evse_id)
                            self._release_pause_dispatch_owner(
                                evse_id, "battery_drain",
                            )
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
                    # Terminal resume — drain is done. Release its claim;
                    # if no other owner remains, dispatch tracking is wiped.
                    self._release_pause_dispatch_owner(evse_id, "battery_drain")

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
        peak_ahead: bool | None = None,
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

        evse-offpeak-fill-release D1: day/night-aware release (mirrors the
        battery strategy at energy_battery.py:2240/2883). Fill-priority is a
        DAYTIME-pre-peak battery-fill protection only; it must go inert in the
        cheap-grid night window so the EVs actually charge. The PHASE is
        TIME-anchored, never inferred from instantaneous PV:
          - `peak`    → release (TOU pause is canonical there). Unchanged.
          - `off_peak`→ release (NEW): the fixed cheap-grid window. Clear the
            hold and do NOT re-hold; the off_peak ensure-on then charges. This
            is cloud-proof (off_peak is a fixed TOU window, not a solar read).
          - `mid_peak`→ hold ONLY IF `peak_ahead` (a real peak is still ahead
            before the next off_peak — the pre-peak fill window). Post-peak
            mid_peak (no peak ahead) → release. `peak_ahead` is computed by the
            caller via `EnergyTOU.peak_ahead_before_offpeak(now)` — TIME only.
            When `peak_ahead is None` (no TOU engine wired / legacy harness),
            preserve the prior always-hold behavior so non-arbitrage setups
            are unaffected.

        Mirrors D1's hybrid `self_modulates` and idempotent re-pause patterns.
        Shares `_pause_dispatch_ts` / `_observed_off_since_pause` with drain —
        only one URA dispatch is pending at a time per EVSE.
        """
        actions: list[dict[str, Any]] = []
        now = _time.monotonic()

        # v4.7.6 fix-up A-H1: Force-Charge precedence.
        force_charge_active = self._is_force_charge_active()

        # Compute forecast-health flag and cache it for the EV charging sensor.
        forecast_healthy = (
            remaining_forecast_kwh is not None
            and remaining_forecast_kwh >= excess_solar_kwh_threshold
        )
        # v4.7.6 fix-up A-L4: include the boundary (`<=`) so the SOC-between-
        # threshold and forecast-at-exactly-margin edge does not strand the
        # EVSE in `_paused_by_fill_priority` for an extra tick.
        forecast_decayed = (
            remaining_forecast_kwh is not None
            and remaining_forecast_kwh <= (
                excess_solar_kwh_threshold - safety_margin_kwh
            )
        )
        self._fill_priority_solar_ok = bool(forecast_healthy)

        # evse-offpeak-fill-release D1: determine whether fill-priority is
        # inert this tick. Inert = release-and-don't-rehold. TIME-anchored:
        #   - peak / off_peak: always inert (release).
        #   - mid_peak: inert when no peak is ahead before off_peak (post-peak).
        #     `peak_ahead is None` (legacy / no TOU engine) → NOT inert (hold).
        fill_priority_inert = (
            tou_period in ("peak", "off_peak")
            or (tou_period == "mid_peak" and peak_ahead is False)
        )
        if fill_priority_inert:
            # Release every held EVSE and do NOT dispatch a re-hold. Let the
            # off_peak ensure-on / TOU / drain rules control the charger.
            # v4.7.6 fix-up A-M4: also release fill_priority's dispatch
            # ownership so a stale dispatch entry doesn't linger on the sensor
            # surface for an EVSE no rule still owns.
            for evse_id in list(self._paused_by_fill_priority):
                self._paused_by_fill_priority.discard(evse_id)
                self._release_pause_dispatch_owner(evse_id, "fill_priority")
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
            # v4.7.6 fix-up A-H1: Force-Charge bypasses fill-priority entirely.
            if force_charge_active:
                if evse_id in self._paused_by_fill_priority:
                    self._paused_by_fill_priority.discard(evse_id)
                    self._release_pause_dispatch_owner(evse_id, "fill_priority")
                    _LOGGER.info(
                        "EV fill-priority: %s cleared — force-charge override active",
                        evse_id,
                    )
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
                    # v4.7.6 fix-up A-H3: release FP's claim only — if drain
                    # still owns the dispatch tracking it stays intact.
                    self._release_pause_dispatch_owner(evse_id, "fill_priority")
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
                # v4.7.6 fix-up A-H3: claim FP ownership of shared tracking.
                self._claim_pause_dispatch_owner(evse_id, "fill_priority")
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
                    # v4.7.6 fix-up A-H3: release FP's claim only — drain's
                    # dispatch tracking remains intact.
                    if (
                        evse_id in self._paused_by_grid_cap
                        or evse_id in self._paused_by_battery_drain
                        or evse_id in self._paused_by_us
                        or evse_id in self._paused_by_arbitrage
                        or evse_id in self._paused_by_load_shed
                        # D-HIGH-1 (Batch 2): blind-window guard peer.
                        or evse_id in self._paused_by_blind_window
                    ):
                        self._paused_by_fill_priority.discard(evse_id)
                        self._release_pause_dispatch_owner(
                            evse_id, "fill_priority",
                        )
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
                    # Terminal resume — release FP's claim. If no other owner
                    # remains, dispatch tracking is wiped.
                    self._release_pause_dispatch_owner(evse_id, "fill_priority")

        return actions

    def current_charging_load_w(self) -> float:
        """Sum the live `power` reads across all EVSEs currently `charging=True`.

        arbitrage_solar_attainability_ladder D1: used by BatteryStrategy's
        rung classifier to (a) decide whether rung-1 (solar redirect) is
        meaningful (no EV load → skip to rung-2), and (b) compute the
        counterfactual rate when an EV pause is contemplated/active.

        Returns watts. None per-EVSE reads degrade gracefully through the
        existing `_get_evse_state` fallback (sensor unavailable → estimated
        power if switch reports charging, else 0). A purely unavailable
        rail therefore reads 0, which causes rung-1 to be skipped — the
        SAFE behavior (we can't subtract a load we can't measure).
        """
        total_w = 0.0
        for evse_id in self._evse:
            try:
                state = self._get_evse_state(evse_id)
            except Exception:  # noqa: BLE001 — defensive: per-EVSE blip
                continue
            if state.get("charging"):
                p = state.get("power") or 0.0
                try:
                    total_w += float(p)
                except (TypeError, ValueError):
                    continue
        return total_w

    def determine_arbitrage_actions(
        self,
        arbitrage_charging: bool,
        tou_period: str,
        pause_reason: str | None = None,
        grid_charge_on: bool = False,
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
            # arbitrage_solar_attainability_ladder D2 breaker-safety invariant:
            # whenever ANY arbitrage pause is requested (rung-1 redirect OR
            # rung-2 breaker), an explicit rung label MUST end up on the
            # side-map so the resume policy reads the correct semantics each
            # tick. Back-compat: legacy callers that pass arbitrage_charging
            # without a pause_reason are presumed to be on the rung-2 (CHARGE
            # phase) path — fail CLOSED to "breaker" so the EVs are paused
            # for compound-load protection, and so the breaker-safety
            # invariant is upheld even when the caller hasn't migrated to
            # the rung-aware API.
            if pause_reason is None:
                pause_reason = "breaker"
                _LOGGER.warning(
                    "determine_arbitrage_actions: pause_reason omitted; "
                    "defaulting to 'breaker' (fail-closed). Caller should "
                    "thread BatteryStrategy._arbitrage_intent.",
                )
            elif pause_reason not in ("redirect", "breaker"):
                raise AssertionError(
                    "determine_arbitrage_actions: pause_reason must be one "
                    f"of ('redirect', 'breaker'); got {pause_reason!r}"
                )
            for evse_id, config in self._evse.items():
                switch_entity = config.get("switch", "")
                if not switch_entity:
                    continue
                # Label is recorded each tick from the CURRENT rung intent.
                # Mid-CHARGE redirect→breaker flips are a silent label
                # update — no churn dispatch (already in the set short-
                # circuits below).
                self._arbitrage_pause_reason[evse_id] = pause_reason
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
                        "EV %s paused for arbitrage (%s)",
                        evse_id, pause_reason,
                    )
                else:
                    # Proactive claim: EVSE is currently off but gets
                    # added to the set so it can't auto-resume mid-cycle.
                    self._paused_by_arbitrage.add(evse_id)
                    _LOGGER.debug(
                        "EV %s claimed by arbitrage pause (%s, was already off)",
                        evse_id, pause_reason,
                    )
            return actions

        # arbitrage_charging=False — release any we held. The release fires
        # uniformly for both rung labels: at this point the caller has
        # decided NO arbitrage pause is wanted on this tick (rung-0 fired,
        # OR rung-2 phase exited CHARGE). The label is dropped together with
        # set membership.
        for evse_id in list(self._paused_by_arbitrage):
            # Fix-up B-CRIT-1 (resume-side guard). If hardware still
            # shows charge_from_grid ON, REFUSE to release / resume —
            # re-claim the EVSE under "breaker" and keep it paused.
            # Without this, a stale decision (e.g. mid-tick latch
            # release while the grid switch hasn't responded yet) could
            # turn the EV on under an active grid pull.
            if grid_charge_on:
                self._arbitrage_pause_reason[evse_id] = "breaker"
                _LOGGER.info(
                    "EV %s arbitrage release refused: grid charge still ON "
                    "(re-claimed as 'breaker')",
                    evse_id,
                )
                continue
            prior_label = self._arbitrage_pause_reason.pop(evse_id, None)
            self._paused_by_arbitrage.discard(evse_id)
            config = self._evse.get(evse_id, {})
            switch_entity = config.get("switch", "")
            if not switch_entity:
                continue
            # Resume only if TOU + other pause-reasons permit
            if tou_period != "off_peak":
                _LOGGER.info(
                    "EV %s arbitrage release (%s): TOU=%s — leaving paused",
                    evse_id, prior_label or "unknown", tou_period,
                )
                continue
            if (
                evse_id in self._paused_by_grid_cap
                or evse_id in self._paused_by_battery_drain
                or evse_id in self._paused_by_us
                or evse_id in self._paused_by_load_shed
                # D-HIGH-1 (Batch 2): blind-window guard peer.
                or evse_id in self._paused_by_blind_window
            ):
                _LOGGER.info(
                    "EV %s arbitrage release (%s): another pause reason holds — leaving paused",
                    evse_id, prior_label or "unknown",
                )
                continue
            state = self._get_evse_state(evse_id)
            if not state["is_on"]:
                actions.append({
                    "service": "switch.turn_on",
                    "target": switch_entity,
                    "data": {},
                })
                _LOGGER.info(
                    "EV %s resumed (arbitrage released, prior=%s)",
                    evse_id, prior_label or "unknown",
                )
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
            # arbitrage_solar_attainability_ladder D2: per-EVSE rung-label
            # discriminator. {"<evse_id>": "redirect"|"breaker"}. Diagnostic
            # only — set membership above remains the canonical "is this
            # EVSE arbitrage-paused?" check.
            "paused_by_arbitrage_reasons": {
                evse_id: self._arbitrage_pause_reason.get(evse_id)
                for evse_id in self._paused_by_arbitrage
            },
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
            # v<next> WS2 D3: proactive off-peak hold set — surfaces which
            # EVSEs URA is currently keeping on during off-peak. MUST be a
            # JSON-serializable list (HA serializes attrs to JSON over the
            # WebSocket; a `set` would raise TypeError).
            "proactive_offpeak_holds": list(self._proactive_offpeak_holds),
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
                # v4.7.6 fix-up B-M2: use `%z` (numeric offset) instead of
                # `%Z` (timezone name) — `%Z` may render empty on HAOS where
                # tzdata abbreviations aren't populated. `%z` is always
                # populated for tz-aware datetimes.
                cooldowns[evse_id] = {
                    "expires": expires_local.strftime("%H:%M %z").strip(),
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

        # v4.7.6 fix-up A-M2: unified precedence helper for both
        # `energy_status` and `pause_reason_human`. The canonical order is
        # fill_priority > drain > grid_cap > arbitrage > TOU > excess_solar
        # > charging > idle > off. Returns a (status_token, human_message)
        # tuple so both sensor attrs are derived from one source of truth.
        target_pct = (
            int(fill_priority_target_soc)
            if fill_priority_target_soc is not None else None
        )
        # v4.7.6 fix-up C-H1: fall back to "configured" when target SOC kwarg
        # was not supplied, instead of rendering "target None%".
        target_str = f"{target_pct}%" if target_pct is not None else "configured target"
        fp_msg = f"holding for battery fill (target {target_str}, solar healthy)"

        def _classify_evse(evse_id: str, ent: dict[str, Any]) -> tuple[str, str]:
            if evse_id in self._paused_by_fill_priority:
                return ("fill_priority_paused", fp_msg)
            if evse_id in self._paused_by_battery_drain:
                return ("battery_drain_paused", "battery drain protection (paused)")
            if evse_id in self._paused_by_grid_cap:
                return ("grid_capped", "grid import cap")
            if evse_id in self._paused_by_arbitrage:
                return ("arbitrage_paused", "arbitrage compound-load protection")
            # EVSE drain-precedence (B2b-i): peer classification, positioned
            # above the TOU/charging/idle fallbacks and below the higher-
            # authority owners already listed. Force-charge is not a set
            # (window state); when active it PREVENTS DP from claiming here.
            if evse_id in self._paused_by_dp:
                return (
                    "dp_paused",
                    "drain-precedence transition (paused)",
                )
            if evse_id in self._paused_by_us:
                return ("paused", "TOU peak/mid-peak pause")
            if evse_id in self._excess_solar_active:
                return ("excess_solar", "excess solar (charging)")
            # B-MED-1 fix-up: surface URA's off-peak proactive turn-on intent
            # so the EV charging-status sensor doesn't hide it behind
            # "charging"/"idle". Positioned AFTER excess_solar so the
            # human reason resolves to "excess solar (charging)" on dual
            # membership (excess_solar_active + proactive_offpeak_holds),
            # which is the operator-preferred precedence. Outranks the
            # bare charging/idle fallbacks so the sensor reflects URA's
            # ensure-on claim (operator decision 1 — documented widened
            # `_ev_tou_enabled` semantics at the read side).
            if evse_id in self._proactive_offpeak_holds:
                return ("offpeak_proactive_on", "off-peak proactive turn-on")
            if ent.get("charging"):
                return ("charging", "charging")
            if ent.get("is_on"):
                return ("idle", "idle")
            return ("off", "off")

        # Per-EVSE entries
        pause_reason_human: dict[str, str] = {}
        for evse_id in self._evse:
            evse_state = self._get_evse_state(evse_id)
            status_token, human_msg = _classify_evse(evse_id, evse_state)
            evse_state["energy_status"] = status_token
            pause_reason_human[evse_id] = human_msg
            # v4.2.19: Surface unavailability timestamp
            unavail_since = self._power_sensor_unavail_since.get(evse_id)
            if unavail_since:
                evse_state["power_sensor_unavail_since"] = unavail_since
            status[evse_id] = evse_state

        # Merge L1 plug peer entries (D6.3)
        for plug_id, plug_entry in plug_status.get("plug_entries", {}).items():
            status[plug_id] = plug_entry

        # Merge plug pause reasons if provided (plug uses same precedence
        # in its own classifier — see SmartPlugController.get_status).
        for plug_id, reason in plug_status.get("pause_reason_human", {}).items():
            pause_reason_human[plug_id] = reason
        status["pause_reason_human"] = pause_reason_human

        return status

    # ------------------------------------------------------------------
    # D1 — release-only paths (run unconditionally each tick when the
    # owning feature toggle is OFF, so no device gets stranded in a
    # pause-owner set after its toggle flips off). Mirror of the
    # release-side logic inside the main decision paths, but with the
    # "should still be paused?" predicate inverted to "toggle is off,
    # always drain the set". See PLANNING_energy_pause_release_hygiene.md
    # D1 (INV-D1-RELEASE).
    # ------------------------------------------------------------------

    def release_all_tou(self) -> list[dict[str, Any]]:
        """Drain `_paused_by_us` when the EV TOU toggle is OFF.

        For each EVSE currently in `_paused_by_us`: drop membership,
        clear proactive-offpeak-hold intent bookkeeping, and issue
        `switch.turn_on` if no other stronger pause-owner (drain,
        fill-priority, grid-cap, arbitrage, load-shed) holds the device.
        Cross-owner deferral matches `determine_actions` off-peak branch
        (energy_pool.py carry-over guards).
        """
        actions: list[dict[str, Any]] = []
        for evse_id in list(self._paused_by_us):
            self._paused_by_us.discard(evse_id)
            self._proactive_offpeak_holds.discard(evse_id)
            # Cross-owner deferral — a stronger pause holds it.
            if (
                evse_id in self._paused_by_battery_drain
                or evse_id in self._paused_by_fill_priority
                or evse_id in self._paused_by_grid_cap
                or evse_id in self._paused_by_arbitrage
                or evse_id in self._paused_by_load_shed
                # D-HIGH-1 (Batch 2): blind-window guard peer.
                or evse_id in self._paused_by_blind_window
            ):
                _LOGGER.debug(
                    "EV release_all_tou: %s dropped TOU membership; "
                    "another owner still holds device",
                    evse_id,
                )
                continue
            config = self._evse.get(evse_id, {})
            switch_entity = config.get("switch", "")
            if not switch_entity:
                continue
            state = self._get_evse_state(evse_id)
            if not state["is_on"]:
                actions.append({
                    "service": "switch.turn_on",
                    "target": switch_entity,
                    "data": {},
                })
                _LOGGER.info(
                    "EV release_all_tou: releasing %s (TOU toggle OFF)",
                    evse_id,
                )
        # Fix 6e (A-LOW-2): with TOU toggle OFF, no proactive off-peak
        # claim is valid — drop membership for ALL current holds, not
        # just those that also lived in `_paused_by_us`. Idempotent.
        self._proactive_offpeak_holds.clear()
        return actions

    def release_all_fill_priority(self) -> list[dict[str, Any]]:
        """Drain `_paused_by_fill_priority` when the excess-solar toggle is OFF."""
        actions: list[dict[str, Any]] = []
        for evse_id in list(self._paused_by_fill_priority):
            self._paused_by_fill_priority.discard(evse_id)
            if (
                evse_id in self._paused_by_battery_drain
                or evse_id in self._paused_by_grid_cap
                or evse_id in self._paused_by_arbitrage
                or evse_id in self._paused_by_load_shed
                # Fix 4 (A-MED-1): a TOU-paused device must NOT be
                # turned_on when fill-priority toggle flips OFF during
                # peak — `_paused_by_us` still legitimately holds it.
                or evse_id in self._paused_by_us
                # D-HIGH-1 (Batch 2): blind-window guard peer.
                or evse_id in self._paused_by_blind_window
            ):
                _LOGGER.debug(
                    "EV release_all_fill_priority: %s dropped fill-priority "
                    "membership; another owner still holds device",
                    evse_id,
                )
                continue
            config = self._evse.get(evse_id, {})
            switch_entity = config.get("switch", "")
            if not switch_entity:
                continue
            state = self._get_evse_state(evse_id)
            if not state["is_on"]:
                actions.append({
                    "service": "switch.turn_on",
                    "target": switch_entity,
                    "data": {},
                })
                _LOGGER.info(
                    "EV release_all_fill_priority: releasing %s "
                    "(excess-solar toggle OFF)",
                    evse_id,
                )
        return actions

    def release_all_grid_cap(self) -> list[dict[str, Any]]:
        """Drain `_paused_by_grid_cap` when the grid-import-cap toggle is OFF."""
        actions: list[dict[str, Any]] = []
        for evse_id in list(self._paused_by_grid_cap):
            self._paused_by_grid_cap.discard(evse_id)
            if (
                evse_id in self._paused_by_battery_drain
                or evse_id in self._paused_by_fill_priority
                or evse_id in self._paused_by_arbitrage
                or evse_id in self._paused_by_load_shed
                # Fix 4 (A-MED-1): TOU-owner defers grid-cap release too.
                or evse_id in self._paused_by_us
                # D-HIGH-1 (Batch 2): blind-window guard peer.
                or evse_id in self._paused_by_blind_window
            ):
                _LOGGER.debug(
                    "EV release_all_grid_cap: %s dropped grid-cap "
                    "membership; another owner still holds device",
                    evse_id,
                )
                continue
            config = self._evse.get(evse_id, {})
            switch_entity = config.get("switch", "")
            if not switch_entity:
                continue
            state = self._get_evse_state(evse_id)
            if not state["is_on"]:
                actions.append({
                    "service": "switch.turn_on",
                    "target": switch_entity,
                    "data": {},
                })
                _LOGGER.info(
                    "EV release_all_grid_cap: releasing %s "
                    "(grid-cap toggle OFF)",
                    evse_id,
                )
        return actions


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
        # v4.7.6 fix-up A-H2 / A-H3 mirror: reference-counted dispatch ownership.
        self._dispatch_owners: dict[str, set[str]] = {}
        # v4.7.6 D2 mirror
        self._paused_by_fill_priority: set[str] = set()
        # load-shedding-correctness D1 mirror: dedicated pause-owner for the
        # load-shed smart-plug tier. Same collision shape as the EV side —
        # the load-shed cascade previously mutated `_paused_by_us` (shared
        # with TOU). Mirrors v5.3.9 arbitrage pattern.
        self._paused_by_load_shed: set[str] = set()
        # load-shedding-correctness fix-up C-HIGH-1: per-plug "was on at
        # shed-claim time" map. Mirrors EV side; controls whether release
        # restores the plug.
        self._load_shed_was_on_at_shed: dict[str, bool] = {}
        # v4.7.6 D1 mirror: cooldown after detected manual override
        self._battery_drain_cooldown: dict[str, float] = {}
        # v4.7.6 D4 cache
        self._fill_priority_solar_ok: bool = False
        # D4 (post-plan operator addition, 2026-07-13): proactive off-peak
        # hold intent-state for L1 plugs. Mirrors EVPool's
        # `_proactive_offpeak_holds` (see energy_pool.py:249). L1 plugs are
        # peer "small EVSE" devices per v4.7.6 D6 — same TOU treatment.
        # Enables `determine_actions` to ensure-on during off_peak so a
        # plug that was off at boot / manually turned off / plugged in
        # late does not sit idle through the cheap window (2026-07-13
        # live incident: socket_2 flipped manually at 01:04).
        self._proactive_offpeak_holds: set[str] = set()

        # Fix 5 (A-MED-3 / C-LOW-1): mirror EVPool.__init__ pattern which
        # calls `_prune_removed_evses()` here (energy_pool.py:279). Without
        # this call, `prune_removed_plugs` was dead code and the plug
        # owner-sets could carry membership for entity_ids no longer in
        # `_plugs` after an options-flow reload. Options-reload rebuilds
        # SmartPlugController from scratch via `async_setup_entry`, so
        # this is defense-in-depth for any future in-place reconfig path.
        self.prune_removed_plugs()

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
        """v4.7.6 fix-up A-H2 / A-H3: unconditional wipe (cooldown / terminal)."""
        self._pause_dispatch_ts.pop(plug_id, None)
        self._observed_off_since_pause.pop(plug_id, None)
        self._dispatch_owners.pop(plug_id, None)

    def _claim_pause_dispatch_owner(self, plug_id: str, owner: str) -> None:
        owners = self._dispatch_owners.setdefault(plug_id, set())
        owners.add(owner)

    def _release_pause_dispatch_owner(self, plug_id: str, owner: str) -> None:
        """v4.7.6 fix-up A-H2 / A-H3 mirror: release `owner`; wipe only if empty."""
        owners = self._dispatch_owners.get(plug_id)
        if owners is None:
            self._pause_dispatch_ts.pop(plug_id, None)
            self._observed_off_since_pause.pop(plug_id, None)
            return
        owners.discard(owner)
        if not owners:
            self._dispatch_owners.pop(plug_id, None)
            self._pause_dispatch_ts.pop(plug_id, None)
            self._observed_off_since_pause.pop(plug_id, None)

    # v4.7.6 fix-up B-H1 / C-M1: `update_plug_config` was dead code — no
    # production caller. The canonical config-update path is HA's options-flow
    # reload which rebuilds SmartPlugController from scratch.

    def determine_actions(
        self,
        tou_period: str,
        force_charge_active: bool = False,
        grid_charge_on: bool = False,
    ) -> list[dict[str, Any]]:
        """Determine smart plug actions based on TOU period.

        v4.2.21: Pauses on peak AND mid_peak (was peak only).

        D4 (post-plan operator addition, 2026-07-13): off_peak branch is
        now an **ensure-on with precedence pre-check**, mirroring EVPool
        `determine_actions` (energy_pool.py:528-636). Prior behavior only
        resumed plugs in `_paused_by_us`; a plug that was off at boot,
        manually turned off, or plugged in late never got started. Live
        incident 2026-07-13: operator manually flipped socket_2 at 01:04
        because URA would not re-enable it. Same guard precedence as
        EVSE: carry-over guards (drain/fill/load-shed/TOU-us) win;
        force-charge is its own escape hatch; if no guard fires, ensure
        the plug is ON and claim the proactive-offpeak hold.

        Args:
            tou_period: current TOU period ("peak", "mid_peak",
                "off_peak", or unknown).
            force_charge_active: True when EVPool's admin force-charge
                override is currently open. When True, plug proactive-on
                is skipped (force-charge is authorized by its own path).
        """
        actions: list[dict[str, Any]] = []

        for entity_id in self._plugs:
            state = self.hass.states.get(entity_id)
            if state is None:
                continue

            if tou_period in ("peak", "mid_peak"):
                # Clear any stale proactive-offpeak hold — set is
                # off-peak-intent only. Mirrors EVSE cleanup at line ~505.
                self._proactive_offpeak_holds.discard(entity_id)
                # B-LOW-1 fix-up: don't issue a cosmetic re-pause when
                # load-shed already claims the plug (device is already off).
                if (
                    state.state == "on"
                    and entity_id not in self._paused_by_us
                    and entity_id not in self._paused_by_load_shed
                ):
                    actions.append({
                        "service": "switch.turn_off",
                        "target": entity_id,
                        "data": {},
                    })
                    self._paused_by_us.add(entity_id)
                    _LOGGER.info("Smart plug: pausing %s (%s)", entity_id, tou_period)
            elif tou_period == "off_peak":
                # D4: ensure-on with precedence pre-check.
                # (a) Carry-over guards (battery protections) win — drop
                # TOU bookkeeping and clear any stale proactive-offpeak
                # hold, but do NOT turn the plug back on. Mirrors EVSE
                # off_peak branch at energy_pool.py:558-570.
                if (
                    entity_id in self._paused_by_battery_drain
                    or entity_id in self._paused_by_fill_priority
                    or entity_id in self._paused_by_load_shed
                ):
                    self._paused_by_us.discard(entity_id)
                    self._proactive_offpeak_holds.discard(entity_id)
                    _LOGGER.debug(
                        "Smart plug: %s carry-over guard holds off_peak — "
                        "no ensure-on",
                        entity_id,
                    )
                    continue
                # Fix 6d (A-LOW-1): breaker-safety cede for L1 parity
                # with EVSE (energy_pool.py:572-601). When the battery is
                # commanding (or the live grid switch shows)
                # `charge_from_grid=True`, do NOT ensure-on the plug —
                # the grid is already pulling significant load; adding a
                # plug now is the compound-load breaker condition. If
                # the plug is currently ON, command it OFF.
                # Operator principle: L1 behaves like L2.
                if grid_charge_on:
                    self._proactive_offpeak_holds.discard(entity_id)
                    if state.state == "on":
                        actions.append({
                            "service": "switch.turn_off",
                            "target": entity_id,
                            "data": {},
                        })
                        _LOGGER.info(
                            "Smart plug %s paused (breaker-safety: "
                            "grid charge active)",
                            entity_id,
                        )
                    continue

                # (b) Force-charge is its own escape hatch — skip the
                # proactive-on claim so hold-set cleanly reflects only
                # TOU-driven holds.
                if force_charge_active:
                    self._proactive_offpeak_holds.discard(entity_id)
                    continue
                # (c) Ensure-on — re-issue turn_on idempotently each tick
                # (Bug Class #43 — intent-state). If user manually
                # disables the plug mid-off-peak, next tick re-enforces.
                if state.state != "on":
                    actions.append({
                        "service": "switch.turn_on",
                        "target": entity_id,
                        "data": {},
                    })
                    _LOGGER.info(
                        "Smart plug: proactive off-peak turn-on for %s",
                        entity_id,
                    )
                # (d) Claim the hold; drop legacy TOU bookkeeping.
                self._proactive_offpeak_holds.add(entity_id)
                self._paused_by_us.discard(entity_id)
            else:
                # Unknown/empty TOU period — safe no-op (do not
                # proactively turn-on or pause). Mirrors EVSE B-LOW-2.
                if entity_id in self._paused_by_us:
                    # Preserve prior legacy behavior for the unknown-period
                    # case: if we had paused it, drop bookkeeping (no
                    # turn-on issued, matches EVSE guarded no-op).
                    self._paused_by_us.discard(entity_id)

        return actions

    # ------------------------------------------------------------------
    # D1 mirror — release-only paths for the smart-plug tier.
    # ------------------------------------------------------------------

    def release_all_tou(self) -> list[dict[str, Any]]:
        """Drain `_paused_by_us` when the EV TOU toggle is OFF (plug tier).

        Mirrors `EVPool.release_all_tou`. Cross-owner deferral matches
        the plug off_peak branch above.
        """
        actions: list[dict[str, Any]] = []
        for entity_id in list(self._paused_by_us):
            self._paused_by_us.discard(entity_id)
            self._proactive_offpeak_holds.discard(entity_id)
            if (
                entity_id in self._paused_by_battery_drain
                or entity_id in self._paused_by_fill_priority
                or entity_id in self._paused_by_load_shed
            ):
                _LOGGER.debug(
                    "Plug release_all_tou: %s dropped TOU membership; "
                    "another owner still holds device",
                    entity_id,
                )
                continue
            state = self.hass.states.get(entity_id)
            if state is None:
                continue
            if state.state != "on":
                actions.append({
                    "service": "switch.turn_on",
                    "target": entity_id,
                    "data": {},
                })
                _LOGGER.info(
                    "Plug release_all_tou: releasing %s (TOU toggle OFF)",
                    entity_id,
                )
        # Fix 6e (A-LOW-2) mirror: plug tier — drop all proactive holds.
        self._proactive_offpeak_holds.clear()
        return actions

    def release_all_fill_priority(self) -> list[dict[str, Any]]:
        """Drain `_paused_by_fill_priority` when excess-solar toggle is OFF."""
        actions: list[dict[str, Any]] = []
        for entity_id in list(self._paused_by_fill_priority):
            self._paused_by_fill_priority.discard(entity_id)
            if (
                entity_id in self._paused_by_battery_drain
                or entity_id in self._paused_by_load_shed
                # Fix 4 (A-MED-1) mirror: plug tier — TOU-owner defers.
                or entity_id in self._paused_by_us
            ):
                _LOGGER.debug(
                    "Plug release_all_fill_priority: %s dropped fill-priority "
                    "membership; another owner still holds device",
                    entity_id,
                )
                continue
            state = self.hass.states.get(entity_id)
            if state is None:
                continue
            if state.state != "on":
                actions.append({
                    "service": "switch.turn_on",
                    "target": entity_id,
                    "data": {},
                })
                _LOGGER.info(
                    "Plug release_all_fill_priority: releasing %s "
                    "(excess-solar toggle OFF)",
                    entity_id,
                )
        return actions

    def prune_removed_plugs(self) -> None:
        """Drop hold-set membership for plug entity_ids no longer
        configured. Mirrors EVPool prune (see `_prune_removed_evses`).

        Fix 5 (A-MED-3 / C-LOW-1): called from `__init__` (mirrors
        EVPool.__init__:279) so options-flow reload paths that rebuild
        SmartPlugController from scratch get clean owner-sets. The prior
        docstring claimed a caller in EnergyCoordinator that did not
        exist — the method was dead code. Idempotent.
        """
        current = set(self._plugs)
        for owner_set in (
            self._paused_by_us,
            self._paused_by_battery_drain,
            self._paused_by_fill_priority,
            self._paused_by_load_shed,
            self._proactive_offpeak_holds,
        ):
            for eid in list(owner_set):
                if eid not in current:
                    owner_set.discard(eid)

    def determine_battery_drain_actions(
        self,
        battery_power_w: float | None,
        battery_soc: float | None,
        soc_threshold: int,
        reserve_soc: int | None = None,
        force_charge_active: bool = False,
        solar_replenishing: bool = False,
        is_offpeak: bool = False,
    ) -> list[dict[str, Any]]:
        """Pause smart plugs draining the home battery. Resume on recovery.

        EV charge-start dead-band fix (parity with EV path): `reserve_soc` is
        the **effective release floor** F = max(static reserve_soc,
        current_offpeak_drain_target()); `solar_replenishing` gates the
        high-SOC `soc_recovered` release (pre-existing L1/L2 gap from
        `energy.py:2941-2947` where the kwarg defaulted to False). Release-side
        sticky at floor prevents 1-tick oscillation. See the EV docstring
        for the full rationale.

        v4.7.6 D1 mirror: hybrid self_modulates, idempotent re-pause, refined
        battery_out_of_capacity gate, observed-off / grace-window state.

        v4.7.6 fix-up A-H1: when `force_charge_active` is True (admin override
        on EVPool), drain is bypassed for all plugs and any current
        `_paused_by_battery_drain` membership is released. Precedence:
        Force-Charge > all URA pause rules.
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
            # v4.7.6 fix-up A-H1: Force-Charge bypasses plug drain entirely.
            if force_charge_active:
                if entity_id in self._paused_by_battery_drain:
                    self._paused_by_battery_drain.discard(entity_id)
                    self._release_pause_dispatch_owner(entity_id, "battery_drain")
                    _LOGGER.info(
                        "Smart plug battery drain: %s cleared — force-charge override active",
                        entity_id,
                    )
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
                    # v4.7.6 fix-up A-H2 mirror: release drain claim only.
                    self._release_pause_dispatch_owner(entity_id, "battery_drain")
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

            # EV dead-band fix-up (Fix 3): BAND the sticky F−2 ≤ SOC ≤ F+2,
            # and (Fix 2) only during off_peak. Mirrors the EV path above.
            in_sticky_band = (
                is_offpeak
                and battery_soc is not None
                and reserve_soc is not None
                and (reserve_soc - 2) <= battery_soc <= (reserve_soc + 2)
            )
            if (
                in_sticky_band
                and is_on
                and battery_discharging
                and soc_low
                and not getattr(self, "_deadband_sticky_logged", False)
            ):
                _LOGGER.info(
                    "Smart plug drain sticky: suppressing re-pause of %s at "
                    "floor (SOC=%.0f%%, F=%d%%, band=F±2, is_offpeak=True)",
                    entity_id, battery_soc, reserve_soc,
                )
                self._deadband_sticky_logged = True

            if is_on and battery_discharging and soc_low and not in_sticky_band:
                # v4.7.6 D1: idempotent re-pause every tick
                actions.append({
                    "service": "switch.turn_off",
                    "target": entity_id,
                    "data": {},
                })
                self._paused_by_battery_drain.add(entity_id)
                self._pause_dispatch_ts[entity_id] = now
                self._observed_off_since_pause[entity_id] = False
                # v4.7.6 fix-up A-H2 mirror: claim drain ownership.
                self._claim_pause_dispatch_owner(entity_id, "battery_drain")
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
                # evse-offpeak-fill-release D2 (parity with EV path): solar-gate
                # the high-SOC release so an overnight no-solar high-SOC battery
                # is NOT drained into the plug load — reserve-only release at
                # night (see the EV docstring for the full rationale).
                soc_recovered = (
                    solar_replenishing
                    and battery_soc is not None
                    and battery_soc >= soc_threshold + 5
                )

                if battery_out_of_capacity or soc_recovered:
                    # Don't resume if TOU pause or fill-priority is active.
                    # v4.7.6 fix-up A-H2 mirror: release drain claim only.
                    # load-shedding-correctness D1: also defer to load_shed.
                    if (
                        entity_id in self._paused_by_us
                        or entity_id in self._paused_by_fill_priority
                        or entity_id in self._paused_by_load_shed
                    ):
                        self._paused_by_battery_drain.discard(entity_id)
                        self._release_pause_dispatch_owner(
                            entity_id, "battery_drain",
                        )
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
                    self._release_pause_dispatch_owner(entity_id, "battery_drain")

        return actions

    def determine_fill_priority_actions(
        self,
        soc: float | None,
        remaining_forecast_kwh: float | None,
        tou_period: str,
        soc_threshold: int,
        excess_solar_kwh_threshold: float,
        safety_margin_kwh: float = DEFAULT_FILL_PRIORITY_SAFETY_MARGIN_KWH,
        force_charge_active: bool = False,
        peak_ahead: bool | None = None,
    ) -> list[dict[str, Any]]:
        """Mirror of EVPool.determine_fill_priority_actions for L1 plugs (D2).

        v4.7.6 fix-up A-H1: when `force_charge_active` is True, fill-priority
        is bypassed for all plugs and any current membership is released.
        v4.7.6 fix-up A-L4: forecast_decayed boundary is `<=` (close edge).

        evse-offpeak-fill-release D1 (parity with the EV path): day/night-aware
        release. `peak`/`off_peak` → inert (release). `mid_peak` → hold only if
        `peak_ahead`; release post-peak. TIME-anchored — see the EV docstring.
        """
        actions: list[dict[str, Any]] = []
        now = _time.monotonic()

        forecast_healthy = (
            remaining_forecast_kwh is not None
            and remaining_forecast_kwh >= excess_solar_kwh_threshold
        )
        # v4.7.6 fix-up A-L4: include boundary so the edge doesn't strand.
        forecast_decayed = (
            remaining_forecast_kwh is not None
            and remaining_forecast_kwh <= (
                excess_solar_kwh_threshold - safety_margin_kwh
            )
        )
        self._fill_priority_solar_ok = bool(forecast_healthy)

        # evse-offpeak-fill-release D1: fill-priority inert outside the
        # daytime-pre-peak window (mirror of the EV path).
        fill_priority_inert = (
            tou_period in ("peak", "off_peak")
            or (tou_period == "mid_peak" and peak_ahead is False)
        )
        if fill_priority_inert:
            # v4.7.6 fix-up A-M4 mirror: release ownership too.
            for plug_id in list(self._paused_by_fill_priority):
                self._paused_by_fill_priority.discard(plug_id)
                self._release_pause_dispatch_owner(plug_id, "fill_priority")
            return actions

        pause_conditions = (
            soc is not None and soc < soc_threshold and forecast_healthy
        )
        resume_soc_met = soc is not None and soc >= soc_threshold

        for entity_id in self._plugs:
            state = self.hass.states.get(entity_id)
            if state is None:
                continue
            # v4.7.6 fix-up A-H1: Force-Charge bypasses plug fill-priority.
            if force_charge_active:
                if entity_id in self._paused_by_fill_priority:
                    self._paused_by_fill_priority.discard(entity_id)
                    self._release_pause_dispatch_owner(entity_id, "fill_priority")
                    _LOGGER.info(
                        "Smart plug fill-priority: %s cleared — force-charge override active",
                        entity_id,
                    )
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
                    # v4.7.6 fix-up A-H3 mirror: release FP claim only.
                    self._release_pause_dispatch_owner(entity_id, "fill_priority")
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
                # v4.7.6 fix-up A-H3 mirror: claim FP ownership.
                self._claim_pause_dispatch_owner(entity_id, "fill_priority")
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
                    # load-shedding-correctness D1: defer to load_shed too.
                    if (
                        entity_id in self._paused_by_us
                        or entity_id in self._paused_by_battery_drain
                        or entity_id in self._paused_by_load_shed
                    ):
                        self._paused_by_fill_priority.discard(entity_id)
                        # v4.7.6 fix-up A-H3 mirror: release FP claim only.
                        self._release_pause_dispatch_owner(
                            entity_id, "fill_priority",
                        )
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
                    self._release_pause_dispatch_owner(entity_id, "fill_priority")

        return actions

    def get_status(
        self,
        fill_priority_target_soc: int | None = None,
    ) -> dict[str, Any]:
        """Return smart plug status with v4.7.6 D6.3 peer-shape entries.

        Returns a base dict plus per-plug `plug_entries` keyed by entity_id
        (the EVPool.get_status() merge consumer uses these as peer keys).

        v4.7.6 fix-up A-M2 / A-L3: precedence order matches EVPool —
        fill_priority > drain > TOU > activity. Target SOC is included in
        the fill-priority human message when supplied (peer format with EV).
        """
        from homeassistant.util import dt as dt_util
        now_mono = _time.monotonic()
        now_local = dt_util.now()

        # v4.7.6 fix-up C-H1 / A-L3 mirror.
        target_pct = (
            int(fill_priority_target_soc)
            if fill_priority_target_soc is not None else None
        )
        target_str = f"{target_pct}%" if target_pct is not None else "configured target"
        fp_msg = f"holding for battery fill (target {target_str}, solar healthy)"

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
            # v4.7.6 fix-up C-M5: `charging` heuristic for L1 plugs.
            # Default (legacy): `is_on AND not paused`. This wrongly reports
            # `charging: True` for an always-on plug serving a non-charging
            # load (lamp, fridge). Per-plug opt-out via `assume_charging_when_on`
            # in plug_config — when set to False, the plug never renders
            # `charging: True` from switch state alone (no power sensor is
            # configured per L1 plug today, so power-based derivation isn't
            # available). When set to False and is_on, `energy_status` becomes
            # "idle" instead of "charging" — communicates the limitation
            # without surfacing a false-charging claim.
            plug_cfg = self._plug_config.get(entity_id, {})
            assume_charging_when_on = bool(
                plug_cfg.get("assume_charging_when_on", True)
            )
            charging = is_on and not paused and assume_charging_when_on
            # v4.7.6 fix-up A-M2: precedence aligned with EVPool —
            # fill_priority > drain > TOU > activity.
            if entity_id in self._paused_by_fill_priority:
                energy_status = "fill_priority_paused"
                pause_reason_human[entity_id] = fp_msg
            elif entity_id in self._paused_by_battery_drain:
                energy_status = "battery_drain_paused"
                pause_reason_human[entity_id] = "battery drain protection (paused)"
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
