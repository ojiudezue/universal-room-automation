"""Override Arrester + AC Reset for HVAC Coordinator.

Detects manual thermostat overrides, applies two-tier severity response
(severe: immediate revert after grace; normal: compromise then revert),
and resets stuck AC cycles.

v3.8.3-H2: Initial implementation.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.recorder import get_instance as recorder_get_instance
from homeassistant.components.recorder.history import get_significant_states
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
)
from homeassistant.util import dt as dt_util

from .hvac_const import (
    AC_KWH_AVOIDED_PROJECTION_CAP_MIN,
    AC_KWH_SENSOR_STALENESS_S,
    AC_KWH_STALE_WARN_INTERVAL_S,
    AC_NUDGE_EVAL_MIN_DROP_FRAC,
    AC_NUDGE_EVALUATION_DELAY_S,
    AC_NUDGE_KWH_RATE_BEFORE_FLOOR,
    AC_NUDGE_OVERSHOOT_GAP,
    AC_RAMP_EVENT_CANCEL_INVOKED,
    AC_RAMP_EVENT_DETECTION_FIRED,
    AC_RAMP_EVENT_HARD_RESET_COMPLETED,
    AC_RAMP_EVENT_HARD_RESET_STARTED,
    AC_RAMP_EVENT_LOCKOUT_ENGAGED,
    AC_RAMP_EVENT_NUDGE_EVALUATED,
    AC_RAMP_EVENT_NUDGE_RESTORED,
    AC_RAMP_EVENT_NUDGE_STARTED,
    AC_RAMP_EVENT_STARTUP_RESTORE,
    AC_RAMP_STATE_AWAITING_EVAL,
    AC_RAMP_STATE_DETECTING,
    AC_RAMP_STATE_DISABLED,
    AC_RAMP_STATE_ESCALATING,
    AC_RAMP_STATE_IDLE,
    AC_RAMP_STATE_LOCKED_OUT,
    AC_RAMP_STATE_NUDGING,
    AC_RESET_MAX_PER_DAY,
    AC_RESET_OFF_DURATION_SECONDS,
    AC_RESET_STUCK_MINUTES,
    DEFAULT_COMPROMISE_MINUTES,
    DEFAULT_HVAC_AC_DETECTION_TIME_GATE,
    DEFAULT_HVAC_AC_HARD_RESET_DAILY_LIMIT,
    DEFAULT_HVAC_AC_HARD_RESET_MIN_INTERVAL,
    DEFAULT_HVAC_AC_KWH_RATE_THRESHOLD,
    DEFAULT_HVAC_AC_NUDGE_DURATION,
    DEFAULT_HVAC_AC_NUDGE_EVAL_DELAY,
    DEFAULT_HVAC_AC_NUDGE_SIZE,
    DEFAULT_HVAC_AC_RAMP_MASTER_ENABLED,
    DEFAULT_HVAC_AC_SUSTAINED_SAMPLES,
    OVERRIDE_COAST_TOLERANCE_BONUS,
    OVERRIDE_NORMAL_DELTA,
    OVERRIDE_NORMAL_GRACE_MINUTES,
    OVERRIDE_SEVERE_DELTA,
    OVERRIDE_SEVERE_GRACE_MINUTES,
)
from .hvac_setpoint import emit_set_temperature
from .hvac_zones import ZoneManager, ZoneState

_LOGGER = logging.getLogger(__name__)

# v4.7.33 A-F5: TTL window for suppressing override detection on URA-initiated
# climate writes. Previous mechanism was a `set` popped on the first state
# event, which silently broke when a single URA action emitted multiple
# events (e.g. _revert_override firing set_hvac_mode + set_preset_mode under
# one suppress()). The TTL window covers all settle events from a single
# logical write and self-clears so we don't grow unbounded.
SUPPRESS_TTL_SECONDS = 5


class OverrideArrester:
    """Detects and responds to manual thermostat overrides.

    Event-driven via async_track_state_change_event on climate entities.
    Two-tier severity:
      - Severe (>3F from expected): 2min grace -> immediate revert
      - Normal (>1F from expected): 5min grace -> 30min compromise -> revert

    Also handles AC reset for stuck cooling/heating cycles.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        zone_manager: ZoneManager,
        compromise_minutes: int = DEFAULT_COMPROMISE_MINUTES,
        ac_reset_timeout: int = AC_RESET_STUCK_MINUTES,
        enabled: bool = True,
    ) -> None:
        """Initialize override arrester."""
        self.hass = hass
        self._zone_manager = zone_manager
        self._compromise_minutes = compromise_minutes
        self._ac_reset_timeout = ac_reset_timeout
        self._enabled = enabled
        self._ac_reset_enabled = True
        # v4.7.7 A2: AC Nudge decouple — independent toggle for the soft-nudge
        # detection iteration. Default ON. Setter has NO cancel-in-flight
        # side-effect (rationale: a restore timer is part of completing the
        # in-flight action cleanly; flipping nudge OFF mid-cycle should NOT
        # strand zones at +nudge_size°F). See plan §A2 setter side-effect.
        self._ac_nudge_enabled = True

        # feature/freeze-floor: backref to the HVAC coordinator so restore /
        # compromise / nudge emissions can read `freeze_active` and route
        # through the setpoint chokepoint. Wired post-construction (mirrors the
        # predictor's `set_hvac_coord`); None-safe (freeze treated inactive).
        self._hvac_coord = None

        # Listener unsubscribes
        self._state_unsubs: list[CALLBACK_TYPE] = []

        # Per-zone timers: zone_id -> cancel callback
        self._grace_timers: dict[str, CALLBACK_TYPE] = {}
        self._compromise_timers: dict[str, CALLBACK_TYPE] = {}
        self._reset_timers: dict[str, CALLBACK_TYPE] = {}

        # Per-zone override state
        self._override_active: dict[str, bool] = {}
        self._compromise_active: dict[str, bool] = {}

        # Energy constraint awareness
        self._energy_offset: float = 0.0
        self._energy_coast: bool = False

        # Suppression: entity_id -> wall-clock expiry for ignoring overrides
        # during URA-initiated changes. v4.7.33 A-F5: replaced the prior
        # `set[str]` (popped on first state event) with a TTL window so a
        # single URA action that produces multiple settle events (e.g.
        # set_hvac_mode + set_preset_mode in _revert_override) stays
        # suppressed across all of them. Window self-clears on TTL expiry.
        self._suppressed_until: dict[str, datetime] = {}

        # v3.18.x review fix: Track verify/retry tasks for AC reset restore
        self._verify_tasks: dict[str, asyncio.Task] = {}

        # v4.7.8 D8: EgressManager reference — set after construction so
        # check_ac_reset can skip zones we paused via the egress feature.
        # None until HVACCoordinator.async_setup wires it.
        self._egress_manager = None

        # v4.5.11: AC ramp-down (energy-aware overshoot detection)
        # Master switch + house-wide tunables. Per-zone state lives on
        # ZoneState. Per-zone-per-day persistent counters live in SQLite.
        self._db = None  # set via set_database(); needed for persistent caps
        self._ramp_master_enabled: bool = DEFAULT_HVAC_AC_RAMP_MASTER_ENABLED
        self._nudge_size_f: float = DEFAULT_HVAC_AC_NUDGE_SIZE
        self._nudge_duration_min: int = DEFAULT_HVAC_AC_NUDGE_DURATION
        # v4.7.17.1: post-restore eval window (seconds). Runtime-tunable
        # via the "76 · AC Nudge Eval Delay" Number entity. Mid-flight
        # change does NOT reschedule an in-flight eval timer (one-shot
        # async_call_later); the next nudge picks up the new value.
        self._nudge_eval_delay_s: int = DEFAULT_HVAC_AC_NUDGE_EVAL_DELAY
        self._sustained_samples: int = DEFAULT_HVAC_AC_SUSTAINED_SAMPLES
        self._detection_time_gate_min: int = DEFAULT_HVAC_AC_DETECTION_TIME_GATE
        self._hard_reset_daily_limit: int = DEFAULT_HVAC_AC_HARD_RESET_DAILY_LIMIT
        self._hard_reset_min_interval_min: int = DEFAULT_HVAC_AC_HARD_RESET_MIN_INTERVAL
        # Per-zone timers — separate from _reset_timers (existing hard-reset
        # restore timers) so a soft nudge in flight doesn't get cancelled
        # by an unrelated hard-reset path on the same zone.
        self._nudge_restore_timers: dict[str, CALLBACK_TYPE] = {}
        self._nudge_eval_timers: dict[str, CALLBACK_TYPE] = {}
        # v4.7.17.1: track restore wall-clock ISO timestamp per zone so the
        # evaluator can query recorder history over [restore_ts, eval_ts]
        # for the trailing-window minimum kW (the new effectiveness rule).
        # Pre-existing behavior: lost on HA restart (mid-eval-window nudges
        # are silently dropped from FP statistics — known gap, Tier 1 scope
        # preserves rather than fixes, per the v4.7.17.x design review).
        self._nudge_post_restore_ts: dict[str, str] = {}
        # Track which zones are currently mid-nudge for sensor exposure.
        self._nudge_in_flight: set[str] = set()
        # Track today's date so we can detect day-rollover and prune events.
        self._last_rollover_date: str = ""

        # v4.5.12 D8: house-wide impact aggregates cached for sensor reads.
        # DB queries are async; sensor.native_value is sync — so we run the
        # aggregates once per decision cycle (5 min) and stash the result.
        # Sensors read this dict and return values synchronously.
        # Keys: nudges_today, resets_today, kwh_avoided_today,
        #       kwh_avoided_total, false_positive_rate, fp_sample_size.
        self._impact_cache: dict = {
            "nudges_today": 0,
            "resets_today": 0,
            "kwh_avoided_today": 0.0,
            "kwh_avoided_total": 0.0,
            "false_positive_rate": None,  # None until sample_size >= 5
            "fp_sample_size": 0,
            "last_refresh_ts": None,
        }

    async def _refresh_impact_cache(self) -> None:
        """v4.5.12 D8: pull house-wide aggregates from DB once per
        decision cycle. Sensors read the cache sync.

        Cheap — six small SQL queries against indexed tables. Runs at
        the end of `check_ac_reset` so it's bounded by the decision-cycle
        cadence (every 5 min, regardless of whether anything fired).
        """
        if self._db is None:
            return
        try:
            # Today's counts — sum across all zones for today's row
            today = dt_util.now().date().isoformat()
            zones = list(self._zone_manager.zones.keys())
            nudges_today = 0
            resets_today = 0
            for zone_id in zones:
                state = await self._db.get_ac_reset_state(zone_id, today)
                nudges_today += int(state.get("soft_nudge_count", 0))
                resets_today += int(state.get("hard_reset_count", 0))

            # kWh-avoided + false-positive math (excludes manual triggers
            # per the slice-1 R6 mitigation already in get_ac_ramp_kwh_avoided)
            (
                kwh_avoided_today,
                evals_today,
                fp_today,
            ) = await self._db.get_ac_ramp_kwh_avoided(days=1)
            (
                kwh_avoided_total,
                evals_total,
                fp_total,
            ) = await self._db.get_ac_ramp_kwh_avoided(days=None)

            # Risk R3: false-positive rate is meaningless until we have
            # a real sample. Hide it (None → "unavailable") until N >= 5.
            fp_rate: float | None
            if evals_total >= 5:
                fp_rate = round(100.0 * fp_total / evals_total, 1)
            else:
                fp_rate = None

            self._impact_cache.update({
                "nudges_today": nudges_today,
                "resets_today": resets_today,
                "kwh_avoided_today": round(kwh_avoided_today, 3),
                "kwh_avoided_total": round(kwh_avoided_total, 3),
                "false_positive_rate": fp_rate,
                "fp_sample_size": evals_total,
                "last_refresh_ts": dt_util.now().isoformat(),
            })
        except Exception as e:
            _LOGGER.warning(
                "AC ramp impact cache refresh failed: %s "
                "(sensors will show stale values until next cycle)", e,
            )

    def set_hvac_coord(self, hvac_coord) -> None:
        """Wire the HVAC coordinator backref (freeze-floor chokepoint).

        feature/freeze-floor: the arrester reads `hvac_coord.freeze_active`
        when emitting setpoints via the chokepoint so restore/compromise/nudge
        writes inherit the freeze floor.
        """
        self._hvac_coord = hvac_coord

    def _freeze_active(self) -> bool:
        """Current freeze-active state from HC; False when unwired."""
        coord = self._hvac_coord
        return bool(getattr(coord, "freeze_active", False)) if coord else False

    def set_database(self, db) -> None:
        """Wire UniversalRoomDatabase reference (v4.5.11).

        Called from HVAC coordinator setup. Without it, ramp-down feature
        is inert (graceful degrade — no caps to enforce, no events to log).
        """
        self._db = db

    def set_egress_manager(self, egress_manager) -> None:
        """v4.7.8 D8: Wire EgressManager so check_ac_reset can skip paused zones.

        Without this, AC Nudge / AC Reset would dispatch set_temperature /
        set_hvac_mode to a zone we deliberately paused — defeating egress.
        """
        self._egress_manager = egress_manager

    @property
    def ramp_master_enabled(self) -> bool:
        """House-wide ramp-down master switch."""
        return self._ramp_master_enabled

    @ramp_master_enabled.setter
    def ramp_master_enabled(self, value: bool) -> None:
        """Toggle ramp-down feature. OFF cancels in-flight nudges + restores
        original setpoints to avoid stranding zones at +1.5°F."""
        self._ramp_master_enabled = bool(value)
        if not self._ramp_master_enabled:
            # Cancel any in-flight nudges so we don't strand zones.
            for zone_id in list(self._nudge_in_flight):
                self.hass.async_create_task(
                    self.cancel_nudge(zone_id, triggered_by="master_off")
                )
        _LOGGER.info(
            "AC ramp-down master %s",
            "enabled" if self._ramp_master_enabled else "disabled",
        )

    def _track_zone_action(
        self,
        zone,
        event_type: str,
        triggered_by: str = "auto",
        kwh_before: float | None = None,
        kwh_after: float | None = None,
    ) -> None:
        """v4.5.12 D7: stamp last-action fields on ZoneState so the
        `sensor.ura_hvac_ac_ramp_last_action_<zone>` sensor can read
        in-memory state. Mirrors what we log to ac_ramp_events but
        in-memory only — no DB hit on the sensor read path.

        Call this alongside `db.log_ac_ramp_event(...)` at every action
        site. Cheap (sets 5 instance attrs).
        """
        zone.last_action_type = event_type
        zone.last_action_ts = dt_util.now().isoformat()
        zone.last_action_triggered_by = triggered_by
        zone.last_action_kwh_before = kwh_before
        zone.last_action_kwh_after = kwh_after

    # Slider write-throughs (called by Number entity factory on slider change)
    def set_nudge_size(self, value: float) -> None:
        self._nudge_size_f = float(value)

    def set_nudge_duration(self, value: int) -> None:
        self._nudge_duration_min = int(value)

    def set_sustained_samples(self, value: int) -> None:
        self._sustained_samples = int(value)

    def set_detection_time_gate(self, value: int) -> None:
        self._detection_time_gate_min = int(value)

    def set_hard_reset_daily_limit(self, value: int) -> None:
        self._hard_reset_daily_limit = int(value)

    def set_hard_reset_min_interval(self, value: int) -> None:
        self._hard_reset_min_interval_min = int(value)

    def has_active_ac_reset(self, zone_id: str) -> bool:
        """Check if a zone is mid-AC-reset (intentionally off)."""
        return zone_id in self._reset_timers

    def setup(self) -> None:
        """Subscribe to climate entity state changes."""
        entity_ids = [
            zone.climate_entity
            for zone in self._zone_manager.zones.values()
        ]
        if not entity_ids:
            _LOGGER.debug("Override Arrester: no climate entities to watch")
            return

        self._state_unsubs.append(
            async_track_state_change_event(
                self.hass, entity_ids, self._handle_climate_change
            )
        )
        _LOGGER.info(
            "Override Arrester: watching %d climate entities", len(entity_ids)
        )

    async def async_startup_audit(
        self, preset_manager, house_state: str = "home_day",
    ) -> None:
        """Scan zones for stale overrides that survived a restart.

        On HA restart, in-memory grace/compromise timers are lost.  If a zone
        is still in 'manual' preset, the event-driven detection won't fire
        again (no state *change*).  This audit catches those zones and
        schedules a revert using seasonal defaults as the expected setpoints.

        Called from the first decision cycle (not async_setup) so that climate
        entities have had time to report their initial state.
        """
        if not self._enabled:
            return

        season = preset_manager.current_season or preset_manager.determine_season()
        target_preset = preset_manager.get_preset_for_house_state(house_state) or "home"
        setpoints = preset_manager.get_seasonal_setpoints(target_preset, season)
        if setpoints is None:
            _LOGGER.debug("Startup audit: no seasonal setpoints for %s/%s", target_preset, season)
            return

        expected_cool, expected_heat = setpoints
        tolerance_bonus = OVERRIDE_COAST_TOLERANCE_BONUS if self._energy_coast else 0.0
        normal_threshold = OVERRIDE_NORMAL_DELTA + tolerance_bonus

        for zone in self._zone_manager.zones.values():
            # v4.7.8 fix-up A-H2 (Bug Class #33): startup audit must not
            # dispatch against an egress-paused zone (it would defeat the
            # pause). Sibling of the check_ac_reset guard at L944.
            if (
                self._egress_manager is not None
                and self._egress_manager.is_paused(zone.zone_id)
            ):
                continue
            state = self.hass.states.get(zone.climate_entity)
            if state is None:
                continue

            preset = state.attributes.get("preset_mode", "")
            if preset != "manual":
                continue

            # Zone is in manual — likely a stale override from before restart
            current_high = state.attributes.get("target_temp_high")
            current_low = state.attributes.get("target_temp_low")

            delta = self._compute_override_delta(
                current_high, current_low,
                expected_cool, expected_heat,
            )
            if delta is None:
                continue

            abs_delta = abs(delta)

            if abs_delta < normal_threshold:
                _LOGGER.debug(
                    "Startup audit: %s in manual but within tolerance (%.1fF)",
                    zone.zone_name, abs_delta,
                )
                continue

            # Stale override detected — revert to the appropriate preset
            zone.override_count_today += 1
            zone.last_override_direction = "cooler" if delta < 0 else "warmer"
            self._override_active[zone.zone_id] = True

            _LOGGER.warning(
                "Startup audit: stale override on %s (%.1fF %s, manual preset). "
                "Reverting to '%s' in %ds.",
                zone.zone_name, abs_delta, zone.last_override_direction,
                target_preset, OVERRIDE_SEVERE_GRACE_MINUTES * 60,
            )

            # Use severe grace (short) since this override already persisted
            # through a restart — user has already had their grace period
            self._cancel_zone_timers(zone.zone_id)
            grace_seconds = OVERRIDE_SEVERE_GRACE_MINUTES * 60

            _zone = zone
            _preset = target_preset

            @callback
            def _on_startup_grace_fire(_now, z=_zone, p=_preset):
                self.hass.async_create_task(
                    self._revert_override(z, p)
                )

            self._grace_timers[zone.zone_id] = async_call_later(
                self.hass,
                grace_seconds,
                _on_startup_grace_fire,
            )

            self.hass.async_create_task(
                self._send_nm_alert(
                    title=f"HVAC Startup Audit: {zone.zone_name}",
                    message=(
                        f"Stale override ({abs_delta:.0f}F {zone.last_override_direction}) "
                        f"detected after restart. Reverting to {target_preset} in "
                        f"{OVERRIDE_SEVERE_GRACE_MINUTES} minutes."
                    ),
                    severity="medium",
                )
            )

    def teardown(self) -> None:
        """Cancel all listeners and timers."""
        for unsub in self._state_unsubs:
            unsub()
        self._state_unsubs.clear()

        for cancel in self._grace_timers.values():
            cancel()
        self._grace_timers.clear()

        for cancel in self._compromise_timers.values():
            cancel()
        self._compromise_timers.clear()

        for cancel in self._reset_timers.values():
            cancel()
        self._reset_timers.clear()

        # v3.18.x review fix: Cancel all verify/retry tasks
        for task in self._verify_tasks.values():
            task.cancel()
        self._verify_tasks.clear()

        # v4.5.11: Cancel any in-flight nudge restore + evaluation timers
        for cancel in self._nudge_restore_timers.values():
            cancel()
        self._nudge_restore_timers.clear()
        for cancel in self._nudge_eval_timers.values():
            cancel()
        self._nudge_eval_timers.clear()
        self._nudge_in_flight.clear()

    def update_energy_state(self, offset: float, coast: bool) -> None:
        """Update energy constraint state for tolerance adjustment."""
        self._energy_offset = offset
        self._energy_coast = coast

    def suppress(self, entity_id: str) -> None:
        """Suppress override detection for an entity (URA-initiated change).

        v4.7.33 A-F5: opens a TTL window (`SUPPRESS_TTL_SECONDS`) rather
        than adding to a set that gets popped on the first state event.
        Covers multi-event settles from a single URA service call.
        """
        self._suppressed_until[entity_id] = (
            dt_util.now() + timedelta(seconds=SUPPRESS_TTL_SECONDS)
        )

    def unsuppress(self, entity_id: str) -> None:
        """Re-enable override detection for an entity immediately.

        Used on error paths where the caller knows the URA-initiated write
        did not happen (or failed) and the TTL window must close now.
        """
        self._suppressed_until.pop(entity_id, None)

    @property
    def enabled(self) -> bool:
        """Return whether the arrester is actively reverting overrides."""
        return self._enabled

    @property
    def ac_reset_enabled(self) -> bool:
        """Return whether AC reset is active."""
        return self._ac_reset_enabled

    @ac_reset_enabled.setter
    def ac_reset_enabled(self, value: bool) -> None:
        """Set AC reset enabled state. Cancels pending reset timers on disable.

        If a zone is mid-reset (intentionally off), cancelling the timer
        would leave it off. Restore those zones to heat_cool immediately.
        """
        self._ac_reset_enabled = value
        if not value:
            mid_reset_zones = []
            for zone_id in list(self._reset_timers):
                cancel = self._reset_timers.pop(zone_id, None)
                if cancel:
                    cancel()
                zone = self._zone_manager.zones.get(zone_id)
                if zone is not None:
                    mid_reset_zones.append(zone)
            # Restore any zones that were mid-AC-reset
            for zone in mid_reset_zones:
                self.hass.async_create_task(
                    self._restore_after_reset(zone, "heat_cool")
                )
        _LOGGER.info("AC Reset %s", "enabled" if value else "disabled")

    @property
    def ac_nudge_enabled(self) -> bool:
        """v4.7.7 A2: Return whether AC soft-nudge detection is active.

        Independent of `ac_reset_enabled`. Gates the soft-nudge detection
        iteration in `check_ac_reset`; does NOT gate the hard-reset
        escalation (that's `ac_reset_enabled`'s job in
        `_perform_hard_reset_escalation`).
        """
        return self._ac_nudge_enabled

    @ac_nudge_enabled.setter
    def ac_nudge_enabled(self, value: bool) -> None:
        """v4.7.7 A2: Set AC nudge enabled state.

        Deliberately NO side-effect on OFF — an in-flight nudge has a
        restore timer that must fire to return the zone to its original
        setpoint. Cancelling mid-flight would strand the zone at
        +nudge_size°F. Future ticks will simply skip new soft-nudge work
        via the Gate 0a/0b split in `check_ac_reset`.
        """
        self._ac_nudge_enabled = bool(value)
        _LOGGER.info(
            "AC Nudge %s",
            "enabled" if self._ac_nudge_enabled else "disabled",
        )

    @enabled.setter
    def enabled(self, value: bool) -> None:
        """Set arrester enabled state. Cancels in-flight timers on disable."""
        self._enabled = value
        if not value:
            # Cancel all pending timers to prevent stale reverts/compromises
            for cancel in self._grace_timers.values():
                cancel()
            self._grace_timers.clear()
            for cancel in self._compromise_timers.values():
                cancel()
            self._compromise_timers.clear()
            self._override_active.clear()
            self._compromise_active.clear()
            # A-F5 review HIGH FIX 2 — lifecycle: clear suppression on
            # disable so a stale TTL window doesn't survive an arrester
            # disable (which would silently swallow events for ≤5s).
            self._suppressed_until.clear()
        _LOGGER.info("Override Arrester %s", "enabled" if value else "disabled (passive mode)")

    @callback
    def _handle_climate_change(self, event: Event) -> None:
        """Handle climate entity state change — detect overrides."""
        entity_id = event.data.get("entity_id", "")
        new_state = event.data.get("new_state")
        old_state = event.data.get("old_state")

        if new_state is None or old_state is None:
            return

        # Skip if suppressed (URA-initiated temperature change).
        # v4.7.33 A-F5: TTL window — covers multi-event settles from a
        # single URA service call (e.g. set_hvac_mode + set_preset_mode in
        # _revert_override). Do NOT pop a still-valid entry; expired
        # entries are cleaned up here to bound dict growth.
        until = self._suppressed_until.get(entity_id)
        if until is not None:
            if dt_util.now() < until:
                # A-F5 review HIGH FIX 1 — mid-window manual passthrough.
                # A transition INTO "manual" can only be user-driven: URA
                # never writes preset_mode=manual. Let it through even
                # mid-window so a genuine user override landing inside the
                # 5s settle window is still caught (regression of the
                # arrester's core job otherwise). All other in-window
                # events are our own settle events — stay suppressed.
                # _revert_override emits (1) set_hvac_mode (preset
                # unchanged, never a fresh non-manual->manual transition)
                # and (2) set_preset_mode to a NON-manual original_preset,
                # so neither matches and both remain suppressed.
                new_preset_mid = new_state.attributes.get("preset_mode", "")
                old_preset_mid = old_state.attributes.get("preset_mode", "")
                if not (
                    new_preset_mid == "manual"
                    and old_preset_mid != "manual"
                ):
                    return
                # Genuine user override mid-window: drop suppression and
                # fall through to normal override detection below.
                self._suppressed_until.pop(entity_id, None)
            else:
                # Expired — clean up so the dict doesn't accumulate stale keys
                self._suppressed_until.pop(entity_id, None)

        # Find which zone this entity belongs to
        zone = self._find_zone_by_entity(entity_id)
        if zone is None:
            return

        # Check for preset change to "manual" — that's the override signal
        new_preset = new_state.attributes.get("preset_mode", "")
        old_preset = old_state.attributes.get("preset_mode", "")

        # Also check for direct temperature changes while on a preset
        new_high = new_state.attributes.get("target_temp_high")
        old_high = old_state.attributes.get("target_temp_high")
        new_low = new_state.attributes.get("target_temp_low")
        old_low = old_state.attributes.get("target_temp_low")

        # Detect override: preset changed to "manual" OR temp changed while on preset
        is_override = False
        if new_preset == "manual" and old_preset != "manual":
            is_override = True
        elif new_preset != "manual" and (new_high != old_high or new_low != old_low):
            # Temperature changed but preset didn't go to manual — this is
            # our own preset change or a preset range adjustment. Ignore.
            pass

        if not is_override:
            return

        _LOGGER.info(
            "Override detected on %s (%s): preset %s->%s, temp_high %s->%s",
            zone.zone_name, entity_id, old_preset, new_preset,
            old_high, new_high,
        )

        # Use the actual old setpoints from the event (what was active before override)
        # This is more accurate than seasonal defaults since presets may differ per thermostat
        if old_high is None and old_low is None:
            _LOGGER.debug("Override: no old setpoints available to compare")
            return

        try:
            expected_cool = float(old_high) if old_high is not None else None
            expected_heat = float(old_low) if old_low is not None else None
        except (ValueError, TypeError):
            _LOGGER.debug("Override: invalid old setpoint values")
            return

        if expected_cool is None and expected_heat is None:
            return

        # Passive mode: track override but don't revert
        if not self._enabled:
            zone.override_count_today += 1
            _LOGGER.info(
                "Override detected on %s (passive mode, no revert): delta from old setpoints",
                zone.zone_name,
            )
            return

        # Widen tolerance during energy coast
        tolerance_bonus = OVERRIDE_COAST_TOLERANCE_BONUS if self._energy_coast else 0.0

        # Determine override severity
        delta = self._compute_override_delta(
            new_high, new_low,
            expected_cool or 0.0,
            expected_heat or 0.0,
        )

        if delta is None:
            return

        abs_delta = abs(delta)
        direction = "cooler" if delta < 0 else "warmer"
        zone.last_override_direction = direction

        severe_threshold = OVERRIDE_SEVERE_DELTA + tolerance_bonus
        normal_threshold = OVERRIDE_NORMAL_DELTA + tolerance_bonus

        if abs_delta >= severe_threshold:
            self._handle_severe_override(
                zone, old_preset, expected_cool, expected_heat, delta
            )
        elif abs_delta >= normal_threshold:
            self._handle_normal_override(
                zone, old_preset, expected_cool, expected_heat, delta,
                new_high, new_low,
            )
        else:
            _LOGGER.debug(
                "Override on %s within tolerance (delta=%.1fF, threshold=%.1fF)",
                zone.zone_name, abs_delta, normal_threshold,
            )

    def _handle_severe_override(
        self,
        zone: ZoneState,
        original_preset: str,
        expected_cool: float,
        expected_heat: float,
        delta: float,
    ) -> None:
        """Handle severe override (>3F): short grace then revert."""
        zone_id = zone.zone_id
        zone.override_count_today += 1
        self._override_active[zone_id] = True

        # Cancel any existing timers for this zone
        self._cancel_zone_timers(zone_id)

        grace_seconds = OVERRIDE_SEVERE_GRACE_MINUTES * 60

        _LOGGER.warning(
            "SEVERE override on %s: delta=%.1fF %s, reverting in %ds",
            zone.zone_name, abs(delta),
            zone.last_override_direction, grace_seconds,
        )

        @callback
        def _on_severe_grace_fire(_now):
            self.hass.async_create_task(
                self._revert_override(zone, original_preset)
            )

        self._grace_timers[zone_id] = async_call_later(
            self.hass,
            grace_seconds,
            _on_severe_grace_fire,
        )

        # NM alert
        self.hass.async_create_task(
            self._send_nm_alert(
                title=f"HVAC Override: {zone.zone_name}",
                message=(
                    f"Severe override ({abs(delta):.0f}F {zone.last_override_direction}) "
                    f"detected. Reverting to {original_preset} in "
                    f"{OVERRIDE_SEVERE_GRACE_MINUTES} minutes."
                ),
                severity="high",
            )
        )

    def _handle_normal_override(
        self,
        zone: ZoneState,
        original_preset: str,
        expected_cool: float | None,
        expected_heat: float | None,
        delta: float,
        new_high: Any,
        new_low: Any,
    ) -> None:
        """Handle normal override (1-3F): grace then compromise then revert."""
        zone_id = zone.zone_id
        zone.override_count_today += 1
        self._override_active[zone_id] = True

        # Cancel any existing timers
        self._cancel_zone_timers(zone_id)

        grace_seconds = OVERRIDE_NORMAL_GRACE_MINUTES * 60

        # Compute compromise: move each setpoint halfway toward the override
        cool_delta = (float(new_high) - expected_cool) if (new_high is not None and expected_cool is not None) else 0
        heat_delta = (float(new_low) - expected_heat) if (new_low is not None and expected_heat is not None) else 0
        compromise_cool = (expected_cool + cool_delta / 2) if expected_cool is not None else expected_cool
        compromise_heat = (expected_heat + heat_delta / 2) if expected_heat is not None else expected_heat

        _LOGGER.info(
            "Normal override on %s: delta=%.1fF %s, compromise in %ds",
            zone.zone_name, abs(delta),
            zone.last_override_direction, grace_seconds,
        )

        @callback
        def _on_normal_grace_fire(_now):
            self.hass.async_create_task(
                self._apply_compromise(
                    zone, original_preset,
                    compromise_cool, compromise_heat,
                    expected_cool, expected_heat,
                )
            )

        self._grace_timers[zone_id] = async_call_later(
            self.hass,
            grace_seconds,
            _on_normal_grace_fire,
        )

        # NM alert
        self.hass.async_create_task(
            self._send_nm_alert(
                title=f"HVAC Override: {zone.zone_name}",
                message=(
                    f"Override ({abs(delta):.0f}F {zone.last_override_direction}) "
                    f"detected. Compromise in {OVERRIDE_NORMAL_GRACE_MINUTES}min, "
                    f"full revert after {self._compromise_minutes}min."
                ),
                severity="medium",
            )
        )

    async def _apply_compromise(
        self,
        zone: ZoneState,
        original_preset: str,
        compromise_cool: float,
        compromise_heat: float,
        expected_cool: float,
        expected_heat: float,
    ) -> None:
        """Apply compromise temperature, then schedule full revert."""
        zone_id = zone.zone_id
        self._compromise_active[zone_id] = True

        # Remove grace timer reference
        self._grace_timers.pop(zone_id, None)

        _LOGGER.info(
            "Override compromise on %s: setting cool=%.0f heat=%.0f for %dmin",
            zone.zone_name, compromise_cool, compromise_heat,
            self._compromise_minutes,
        )

        # Set compromise temperature
        try:
            await emit_set_temperature(
                self.hass,
                zone.climate_entity,
                target_temp_low=compromise_heat,
                target_temp_high=compromise_cool,
                freeze_active=self._freeze_active(),
                blocking=False,
            )
        except Exception as e:
            _LOGGER.error("Override: failed to set compromise on %s: %s",
                          zone.climate_entity, e)

        # Schedule full revert after compromise period
        compromise_seconds = self._compromise_minutes * 60

        @callback
        def _on_compromise_fire(_now):
            self.hass.async_create_task(
                self._revert_override(zone, original_preset)
            )

        self._compromise_timers[zone_id] = async_call_later(
            self.hass,
            compromise_seconds,
            _on_compromise_fire,
        )

    def _supports_heat_cool(self, climate_entity: str) -> bool:
        """True if the climate entity advertises heat_cool in its hvac_modes.

        v4.7.32: the operator runs zones in ranges/presets (heat_cool). Override
        revert and AC-reset restore re-assert heat_cool whenever the mode has
        drifted (off OR single-mode like cool/heat) — but only on thermostats
        that actually support it, so a genuinely heat-only / cool-only unit is
        never forced into an unsupported mode.
        """
        st = self.hass.states.get(climate_entity)
        modes = (st.attributes.get("hvac_modes") or []) if st else []
        return "heat_cool" in modes

    async def _revert_override(
        self, zone: ZoneState, original_preset: str,
    ) -> None:
        """Revert zone to its original preset."""
        zone_id = zone.zone_id

        # Clean up timer references
        self._grace_timers.pop(zone_id, None)
        self._compromise_timers.pop(zone_id, None)
        self._override_active[zone_id] = False
        self._compromise_active[zone_id] = False

        _LOGGER.info(
            "Override revert on %s: restoring preset %s",
            zone.zone_name, original_preset,
        )

        # Suppress arrester for our own revert (TTL window covers both
        # set_hvac_mode and set_preset_mode settle events — A-F5).
        self.suppress(zone.climate_entity)

        try:
            # v4.7.32: re-assert heat_cool whenever the mode has drifted from it
            # (off OR a single mode like cool/heat) — not just "off". The operator
            # runs zones in ranges/presets; a stuck single-mode defeats that. Only
            # force it on thermostats that support heat_cool.
            if zone.hvac_mode != "heat_cool" and self._supports_heat_cool(
                zone.climate_entity
            ):
                await self.hass.services.async_call(
                    "climate",
                    "set_hvac_mode",
                    {
                        "entity_id": zone.climate_entity,
                        "hvac_mode": "heat_cool",
                    },
                    blocking=False,
                )
                _LOGGER.info(
                    "Override revert: restored %s to heat_cool (was %s)",
                    zone.zone_name, zone.hvac_mode,
                )

            await self.hass.services.async_call(
                "climate",
                "set_preset_mode",
                {
                    "entity_id": zone.climate_entity,
                    "preset_mode": original_preset,
                },
                blocking=False,
            )
        except Exception as e:
            _LOGGER.error(
                "Override: failed to revert %s to preset %s: %s",
                zone.climate_entity, original_preset, e,
            )

    # =========================================================================
    # AC Reset — stuck cycle detection (polling, called from decision cycle)
    # =========================================================================

    async def check_ac_reset(self) -> None:
        """v4.5.11: Detect overshoot + sustained kWh-rate waste, then act.

        Replaces the v3.8.3 'still hot despite cooling' trigger which never
        fired for the dominant Texas-summer waste pattern (AC reaches setpoint,
        keeps burning kWh past the natural cycle-end).

        Called from the 5-minute HVAC decision cycle.

        Gating order (any failure -> skip zone, set ramp_state, continue):
          0a. _ac_nudge_enabled AND _ac_reset_enabled both False -> return
          0b. _ac_nudge_enabled False -> return (soft-nudge entry point
              has no work). NOTE (v4.7.7 A-M2 fix-up): with AC Nudge OFF +
              AC Reset ON, the hard-reset path is currently unreachable —
              soft-nudge auto-detection is skipped here, and no manual
              force_reset button exists today. The user can re-enable AC
              Nudge to allow escalation. Revisit in v4.7.8 if a manual
              force_reset button is wanted.
          1. _ramp_master_enabled (v4.5.11 master switch)
          2. zone.ramp_zone_enabled (per-zone opt-out)
          3. zone.ac_load_sensor configured (graceful degrade if not)
          4. hvac_action == cooling AND temps known
          5. lockout_flag not set (DB)
          6. current <= target_high  (at-or-below setpoint)
          7. kwh_rate > zone threshold for N consecutive samples (debounce)
          8. overshoot sustained for detection_time_gate minutes
          9. not already mid-nudge or mid-evaluation
        All gates passed -> _handle_overshoot_detected.

        v4.7.7 A2: Gate 0 split. Pre-v4.7.7 Gate 0 single-toggle
        `_ac_reset_enabled` gated BOTH the soft-nudge iteration AND the
        hard-reset escalation, which is why turning AC Reset OFF disabled
        nudges too. The escalation guard now lives at the top of
        `_perform_hard_reset_escalation` (A3), and Gate 0 here only governs
        the soft-nudge iteration entry.
        """
        # v4.7.7 A2 — Gate 0a: both features off -> arrester soft-nudge
        # work disabled entirely. Mirror behavior matches single-snapshot
        # Bug Class #20 (reload race): we read both flags once into local
        # vars to guarantee a stable view across this tick.
        _nudge_on = self._ac_nudge_enabled
        _reset_on = self._ac_reset_enabled
        if not _nudge_on and not _reset_on:
            return
        # v4.7.7 A2 — Gate 0b: nudge off, reset on. `check_ac_reset` is the
        # soft-nudge entry point; with nudges disabled it has no work.
        # v4.7.7 A-M2 fix-up: with AC Nudge OFF + AC Reset ON, the
        # hard-reset path is unreachable in v4.7.7 (no automatic trigger
        # since soft-nudge auto-detection is skipped here, and no manual
        # force_reset button exists today). User can re-enable AC Nudge to
        # allow escalation. v4.7.8 may add a manual force_reset button if
        # user feedback indicates this cell needs it.
        if not _nudge_on:
            _LOGGER.debug(
                "AC Nudge disabled — skipping soft-nudge detection "
                "(AC Reset state=%s)", "on" if _reset_on else "off",
            )
            return
        # Gate 1: v4.5.11 master switch (default OFF)
        if not self._ramp_master_enabled:
            return

        now = dt_util.now()
        today = now.date().isoformat()

        # Day-rollover hook: prune old events once per new day. Fire-and-forget.
        if self._last_rollover_date and self._last_rollover_date != today:
            if self._db is not None:
                self.hass.async_create_task(self._db.cleanup_ac_ramp_events())
        self._last_rollover_date = today

        # snapshot: zones dict may be pruned by _handle_zm_zones_updated mid-await
        for zone_id, zone in list(self._zone_manager.zones.items()):
            # v4.7.8 D8: Skip zones paused by EgressManager. Nudging a stopped
            # compressor is incoherent; AC Reset hard-cycling an already-off
            # zone is wasted work. State stays at idle so sensors don't lie.
            if self._egress_manager is not None and self._egress_manager.is_paused(zone_id):
                zone.ramp_state = AC_RAMP_STATE_IDLE
                continue
            # Skip zones with active overrides (let override path handle)
            if self._override_active.get(zone_id, False):
                zone.ramp_state = AC_RAMP_STATE_IDLE
                continue

            # Gate 2: per-zone enable
            if not zone.ramp_zone_enabled:
                zone.ramp_state = AC_RAMP_STATE_DISABLED
                continue

            # Gate 3: ac_load_sensor configured (else feature OFF for zone)
            if not zone.ac_load_sensor:
                zone.ramp_state = AC_RAMP_STATE_DISABLED
                continue

            # Gate 4: cooling action + valid temps
            if zone.hvac_action != "cooling":
                zone.last_overshoot_started = ""
                zone.kwh_samples_above_threshold = 0
                if zone_id not in self._nudge_in_flight:
                    zone.ramp_state = AC_RAMP_STATE_IDLE
                continue
            if zone.target_temp_high is None or zone.current_temperature is None:
                continue

            # Gate 5: lockout flag (DB)
            if self._db is not None:
                state = await self._db.get_ac_reset_state(zone_id)
                if state.get("lockout_flag"):
                    zone.ramp_state = AC_RAMP_STATE_LOCKED_OUT
                    continue

            # Gate 6: overshoot — current at-or-below target setpoint.
            # v4.7.16.2 hotfix: gap reduced 0.5°F → 0.0°F. Variable-speed
            # Bryant modulates AT setpoint and rarely undershoots 0.5°F,
            # so the previous gap suppressed auto-nudge for the exact
            # waste pattern this gate exists to catch (sustained kWh burn
            # while sitting at setpoint). Gates 7 (kwh_rate > zone
            # threshold), 7b (N consecutive samples), and 8 (time-
            # sustained for detection_time_gate min) provide three
            # independent false-positive guards downstream.
            overshoot = (
                zone.current_temperature
                <= zone.target_temp_high - AC_NUDGE_OVERSHOOT_GAP
            )
            if not overshoot:
                zone.last_overshoot_started = ""
                zone.kwh_samples_above_threshold = 0
                if zone_id not in self._nudge_in_flight:
                    zone.ramp_state = AC_RAMP_STATE_IDLE
                continue

            # Read kWh rate (with staleness check)
            kwh_rate = self._read_kwh_rate(zone, now)
            if kwh_rate is None:
                continue  # graceful degrade — sensor stale or unavailable

            # Update live attrs for D7 sensor exposure
            zone.last_kwh_rate = kwh_rate
            zone.last_kwh_rate_ts = now.isoformat()

            # Gate 7: debounce — N consecutive samples > zone-specific threshold
            if kwh_rate > zone.kwh_rate_threshold:
                zone.kwh_samples_above_threshold += 1
            else:
                zone.kwh_samples_above_threshold = 0
                if zone_id not in self._nudge_in_flight:
                    zone.ramp_state = AC_RAMP_STATE_IDLE
                continue

            if zone.kwh_samples_above_threshold < self._sustained_samples:
                if zone_id not in self._nudge_in_flight:
                    zone.ramp_state = AC_RAMP_STATE_DETECTING
                continue

            # Gate 8: time-sustained
            if not zone.last_overshoot_started:
                zone.last_overshoot_started = now.isoformat()
                if zone_id not in self._nudge_in_flight:
                    zone.ramp_state = AC_RAMP_STATE_DETECTING
                continue
            try:
                overshoot_started = datetime.fromisoformat(
                    zone.last_overshoot_started
                )
            except (ValueError, TypeError):
                zone.last_overshoot_started = now.isoformat()
                continue
            elapsed_min = (now - overshoot_started).total_seconds() / 60
            if elapsed_min < self._detection_time_gate_min:
                if zone_id not in self._nudge_in_flight:
                    zone.ramp_state = AC_RAMP_STATE_DETECTING
                continue

            # Gate 9: already in nudge/eval flow — let the in-flight cycle finish
            if zone_id in self._nudge_in_flight:
                continue
            if zone_id in self._nudge_eval_timers:
                continue

            # All gates passed — dispatch action
            await self._handle_overshoot_detected(zone, kwh_rate, now, elapsed_min)

        # v4.5.12 D8: refresh impact aggregates once per cycle. Runs after
        # the zone-iteration so any actions that fired this tick are
        # reflected in the next sensor read.
        await self._refresh_impact_cache()

    async def _perform_ac_reset(self, zone: ZoneState) -> None:
        """Perform AC reset: off -> wait -> restore mode."""
        original_mode = zone.hvac_mode
        original_action = zone.hvac_action
        zone_id = zone.zone_id
        # v4.7.32 (Review C MED-1): the restore now targets heat_cool when the
        # thermostat supports it (see _restore_after_reset). Report that in the
        # alert so the NM message doesn't claim it's restoring the pre-reset mode.
        restore_target = (
            "heat_cool" if self._supports_heat_cool(zone.climate_entity)
            else original_mode
        )

        # Turn off
        try:
            await self.hass.services.async_call(
                "climate",
                "set_hvac_mode",
                {"entity_id": zone.climate_entity, "hvac_mode": "off"},
                blocking=True,
            )
        except Exception as e:
            _LOGGER.error("AC Reset: failed to turn off %s: %s",
                          zone.climate_entity, e)
            return

        # Schedule restore after off duration
        @callback
        def _on_reset_fire(_now):
            self.hass.async_create_task(
                self._restore_after_reset(zone, original_mode)
            )

        self._reset_timers[zone_id] = async_call_later(
            self.hass,
            AC_RESET_OFF_DURATION_SECONDS,
            _on_reset_fire,
        )

        # NM alert
        await self._send_nm_alert(
            title=f"AC Reset: {zone.zone_name}",
            message=(
                f"Stuck {original_action} cycle detected — "
                f"cycling off for {AC_RESET_OFF_DURATION_SECONDS}s then restoring "
                f"{restore_target}. Reset #{zone.ac_reset_count_today}/{AC_RESET_MAX_PER_DAY} today."
            ),
            severity="high",
        )

    async def _restore_after_reset(
        self, zone: ZoneState, original_mode: str,
    ) -> None:
        """Restore HVAC mode after AC reset off period.

        v3.18.2: Added pre-restore telemetry logging and post-restore
        verification with retry (max 2 retries at 30s intervals).
        """
        zone_id = zone.zone_id
        zone_name = zone.zone_name
        climate_entity = zone.climate_entity
        # v4.7.32: restore to heat_cool (ranges/presets), not the pre-reset mode —
        # a zone that was in a single mode (cool/heat) before the reset would
        # otherwise come back single-mode and never reset ("nudges don't reset the
        # mode"). Guard on supported modes so a heat-only/cool-only unit keeps its
        # mode (falls back to the original).
        target_mode = (
            "heat_cool" if self._supports_heat_cool(climate_entity) else original_mode
        )

        self._reset_timers.pop(zone_id, None)

        # v3.18.2: Log pre-restore state for telemetry
        pre_state = self.hass.states.get(climate_entity)
        _LOGGER.info(
            "HVAC AC Reset: Restoring zone %s — pre-restore state=%s, target=%s",
            zone_name,
            pre_state.state if pre_state else "unknown",
            target_mode,
        )

        try:
            await self.hass.services.async_call(
                "climate",
                "set_hvac_mode",
                {"entity_id": climate_entity, "hvac_mode": target_mode},
                blocking=True,
            )
        except Exception as e:
            _LOGGER.error(
                "AC Reset: failed to restore %s to %s: %s",
                climate_entity, target_mode, e,
            )
            return

        # v3.18.2: Schedule verification after restore
        # v3.18.x review fix: Track verify tasks, cancel duplicates, return on retry failure
        async def _verify_restore(attempt: int = 1) -> None:
            # Bail out if task was cancelled/removed
            if zone_id not in self._verify_tasks:
                return

            await asyncio.sleep(30)
            state = self.hass.states.get(climate_entity)
            actual_mode = state.state if state else "unknown"

            # v4.7.32 (Review A-F3): verify the zone actually reached the INTENDED
            # mode (target_mode = heat_cool when supported), not merely "not off".
            # A thermostat that advertises heat_cool but silently downgrades to
            # cool/heat would otherwise pass verification falsely.
            if actual_mode != target_mode and attempt <= 2:
                _LOGGER.warning(
                    "HVAC AC Reset: Zone %s did not reach %s (still %s) after "
                    "restore (attempt %d/2) — retrying",
                    zone_name, target_mode, actual_mode, attempt,
                )
                try:
                    await self.hass.services.async_call(
                        "climate",
                        "set_hvac_mode",
                        {"entity_id": climate_entity, "hvac_mode": target_mode},
                        blocking=True,
                    )
                except Exception as exc:
                    _LOGGER.error(
                        "HVAC AC Reset: Retry failed for zone %s: %s",
                        zone_name, exc,
                    )
                    # Don't schedule next retry after a failed service call
                    self._verify_tasks.pop(zone_id, None)
                    return
                # Schedule next verification
                next_task = self.hass.async_create_task(_verify_restore(attempt + 1))
                self._verify_tasks[zone_id] = next_task
            elif actual_mode != target_mode:
                _LOGGER.error(
                    "HVAC AC Reset: Zone %s FAILED to restore to %s (still %s) "
                    "after 2 retries — manual intervention needed",
                    zone_name, target_mode, actual_mode,
                )
                self._verify_tasks.pop(zone_id, None)
                # Send NM critical alert for failed restore
                await self._send_nm_alert(
                    title=f"AC Reset FAILED: {zone_name}",
                    message=(
                        f"AC reset failed to restore Zone {zone_name} to "
                        f"{target_mode} — thermostat stuck on {actual_mode} after "
                        f"2 retries. Manual intervention needed."
                    ),
                    severity="critical",
                )
            else:
                _LOGGER.info(
                    "HVAC AC Reset: Zone %s verified — restored to %s",
                    zone_name, actual_mode,
                )
                self._verify_tasks.pop(zone_id, None)

        # Cancel any existing verify task for this zone before starting a new one
        existing_task = self._verify_tasks.get(zone_id)
        if existing_task is not None:
            existing_task.cancel()

        task = self.hass.async_create_task(_verify_restore())
        self._verify_tasks[zone_id] = task

        # v4.5.11: hard reset is also part of the ramp-down state machine when
        # invoked via _perform_hard_reset_escalation. Log completion event.
        if self._db is not None and zone_id in self._nudge_in_flight:
            # Defensive: shouldn't happen (hard reset is post-eval),
            # but if it did, clear in-flight to avoid stranded state.
            self._nudge_in_flight.discard(zone_id)
        # v4.5.12: track action for D7 last_action sensor
        zone_for_track = self._zone_manager.zones.get(zone_id)
        if zone_for_track is not None:
            self._track_zone_action(
                zone_for_track, AC_RAMP_EVENT_HARD_RESET_COMPLETED, "auto",
            )
        if self._db is not None:
            await self._db.log_ac_ramp_event(
                zone_id=zone_id,
                event_type=AC_RAMP_EVENT_HARD_RESET_COMPLETED,
                target_high=zone.target_temp_high,
                action_taken=f"restored_mode={target_mode}",
            )
        zone.ramp_state = AC_RAMP_STATE_IDLE

    # =========================================================================
    # v4.5.11 — AC Energy-Aware Ramp-Down: action paths
    # =========================================================================

    def _read_kwh_rate(
        self, zone: ZoneState, now: datetime,
    ) -> float | None:
        """Read kW from configured ac_load_sensor with staleness check.

        Returns:
          float — kW rate (converts W -> kW if unit_of_measurement is W)
          None — sensor missing, stale, or value unparseable

        Staleness threshold = AC_KWH_SENSOR_STALENESS_S (10 min). Stale
        readings are treated as missing rather than trusted, so a Span
        outage doesn't silently keep firing detection on the last good
        value (Risk R3).
        """
        if not zone.ac_load_sensor:
            return None
        state = self.hass.states.get(zone.ac_load_sensor)
        if state is None:
            return None
        last_updated = state.last_updated
        if last_updated is not None:
            try:
                age_s = (now - dt_util.as_local(last_updated)).total_seconds()
            except (TypeError, ValueError):
                age_s = 0.0
            if age_s > AC_KWH_SENSOR_STALENESS_S:
                self._maybe_warn_stale(zone, age_s, now)
                return None
        raw = state.state
        if raw in (None, "unknown", "unavailable", ""):
            return None
        try:
            value = float(raw)
        except (ValueError, TypeError):
            return None
        unit = (state.attributes.get("unit_of_measurement") or "").lower()
        if unit in ("w", "watt", "watts"):
            value = value / 1000.0
        return value

    def _maybe_warn_stale(
        self, zone: ZoneState, age_s: float, now: datetime,
    ) -> None:
        """Rate-limited stale-sensor warning (every 6h per zone)."""
        if zone.last_kwh_stale_warned_ts:
            try:
                last = datetime.fromisoformat(zone.last_kwh_stale_warned_ts)
            except (ValueError, TypeError):
                last = None
            if last is not None and (now - last).total_seconds() < AC_KWH_STALE_WARN_INTERVAL_S:
                return
        _LOGGER.warning(
            "AC ramp-down: %s ac_load_sensor (%s) stale (age=%.0fs > %ds) "
            "— feature inert for this zone until sensor recovers",
            zone.zone_name, zone.ac_load_sensor, age_s,
            AC_KWH_SENSOR_STALENESS_S,
        )
        zone.last_kwh_stale_warned_ts = now.isoformat()

    async def _handle_overshoot_detected(
        self,
        zone: ZoneState,
        kwh_rate: float,
        now: datetime,
        overshoot_minutes: float,
    ) -> None:
        """All detection gates passed — log + dispatch to soft nudge."""
        zone_id = zone.zone_id
        self._track_zone_action(
            zone, AC_RAMP_EVENT_DETECTION_FIRED, "auto",
            kwh_before=kwh_rate,
        )
        if self._db is not None:
            await self._db.log_ac_ramp_event(
                zone_id=zone_id,
                event_type=AC_RAMP_EVENT_DETECTION_FIRED,
                current_temp=zone.current_temperature,
                target_high=zone.target_temp_high,
                kwh_rate_before=kwh_rate,
                notes=f"overshoot_min={overshoot_minutes:.1f};threshold={zone.kwh_rate_threshold:.2f}",
            )
        _LOGGER.info(
            "AC overshoot detected on %s: current=%.1f, target=%.1f, "
            "kwh_rate=%.2f kW (threshold=%.2f), overshoot=%.0fmin",
            zone.zone_name, zone.current_temperature, zone.target_temp_high,
            kwh_rate, zone.kwh_rate_threshold, overshoot_minutes,
        )
        await self._perform_soft_nudge(zone, kwh_rate, triggered_by="auto")

    async def _perform_soft_nudge(
        self,
        zone: ZoneState,
        kwh_rate_before: float,
        triggered_by: str = "auto",
    ) -> None:
        """v4.5.11 D2: Bump target +nudge_size, restore after nudge_duration.

        Restart-safe: writes in_flight state to DB BEFORE issuing the climate
        service call. If we crash between the DB write and the service call,
        the next startup audit will "restore" to the original target — which
        equals the current target — i.e., a benign no-op. Risk R1.
        """
        zone_id = zone.zone_id
        if zone.target_temp_high is None:
            return
        original_target = float(zone.target_temp_high)
        new_target = original_target + self._nudge_size_f
        duration_s = self._nudge_duration_min * 60
        started_ts = dt_util.now().isoformat()

        # CRITICAL ORDER (R1): DB first, setpoint second.
        if self._db is not None:
            await self._db.set_ac_in_flight_nudge(
                zone_id=zone_id,
                original_target=original_target,
                started_ts=started_ts,
                duration_s=duration_s,
            )

        # Suppress override detection during URA-initiated change (R11)
        self.suppress(zone.climate_entity)

        try:
            await emit_set_temperature(
                self.hass,
                zone.climate_entity,
                target_temp_low=zone.target_temp_low,
                target_temp_high=new_target,
                freeze_active=self._freeze_active(),
                blocking=False,
            )
        except Exception as e:
            _LOGGER.error(
                "Soft nudge: set_temperature failed on %s: %s",
                zone.climate_entity, e,
            )
            if self._db is not None:
                await self._db.clear_ac_in_flight_nudge(zone_id)
            return

        self._nudge_in_flight.add(zone_id)
        zone.ramp_state = AC_RAMP_STATE_NUDGING
        zone.nudge_kwh_rate_before = kwh_rate_before
        zone.last_overshoot_started = ""  # window resets — outcome under eval
        zone.kwh_samples_above_threshold = 0

        if self._db is not None:
            state = await self._db.get_ac_reset_state(zone_id)
            state["soft_nudge_count"] = int(state.get("soft_nudge_count", 0)) + 1
            state["last_soft_nudge_ts"] = started_ts
            await self._db.save_ac_reset_state(state)
            self._track_zone_action(
                zone, AC_RAMP_EVENT_NUDGE_STARTED, triggered_by,
                kwh_before=kwh_rate_before,
            )
            await self._db.log_ac_ramp_event(
                zone_id=zone_id,
                event_type=AC_RAMP_EVENT_NUDGE_STARTED,
                triggered_by=triggered_by,
                current_temp=zone.current_temperature,
                target_high=original_target,
                kwh_rate_before=kwh_rate_before,
                action_taken=(
                    f"target {original_target:.1f}->{new_target:.1f} "
                    f"for {duration_s}s"
                ),
                soft_nudge_count_today=state["soft_nudge_count"],
            )

        _LOGGER.info(
            "Soft nudge fired on %s: target %.1f -> %.1f for %d min "
            "(kwh_rate_before=%.2f kW, by=%s)",
            zone.zone_name, original_target, new_target,
            self._nudge_duration_min, kwh_rate_before, triggered_by,
        )

        @callback
        def _on_nudge_restore_fire(_now):
            self.hass.async_create_task(
                self._restore_after_nudge(zone, original_target)
            )

        self._nudge_restore_timers[zone_id] = async_call_later(
            self.hass, duration_s, _on_nudge_restore_fire,
        )

    async def _restore_after_nudge(
        self, zone: ZoneState, original_target: float,
    ) -> None:
        """Restore target after nudge_duration; schedule outcome evaluation."""
        zone_id = zone.zone_id
        self._nudge_restore_timers.pop(zone_id, None)
        self._nudge_in_flight.discard(zone_id)

        # Risk R11: re-suppress before our own write so an in-flight user
        # override doesn't get mis-classified.
        self.suppress(zone.climate_entity)

        try:
            await emit_set_temperature(
                self.hass,
                zone.climate_entity,
                target_temp_low=zone.target_temp_low,
                target_temp_high=original_target,
                freeze_active=self._freeze_active(),
                blocking=False,
            )
        except Exception as e:
            _LOGGER.error(
                "Soft nudge restore: set_temperature failed on %s: %s",
                zone.climate_entity, e,
            )

        self._track_zone_action(
            zone, AC_RAMP_EVENT_NUDGE_RESTORED, "auto",
            kwh_before=zone.nudge_kwh_rate_before,
        )
        if self._db is not None:
            await self._db.clear_ac_in_flight_nudge(zone_id)
            await self._db.log_ac_ramp_event(
                zone_id=zone_id,
                event_type=AC_RAMP_EVENT_NUDGE_RESTORED,
                target_high=original_target,
                kwh_rate_before=zone.nudge_kwh_rate_before,
            )

        zone.ramp_state = AC_RAMP_STATE_AWAITING_EVAL
        # v4.7.17.1: capture restore wall-clock for recorder query in
        # _evaluate_nudge_outcome (trailing-window min kW rule).
        self._nudge_post_restore_ts[zone_id] = dt_util.now().isoformat()

        @callback
        def _on_eval_fire(_now):
            self.hass.async_create_task(self._evaluate_nudge_outcome(zone))

        # v4.7.17.1: runtime-tunable eval delay (was const
        # AC_NUDGE_EVALUATION_DELAY_S). One-shot async_call_later
        # — mid-flight change of self._nudge_eval_delay_s does NOT
        # reschedule this timer; next nudge picks up the new value.
        eval_delay_s = int(self._nudge_eval_delay_s)
        self._nudge_eval_timers[zone_id] = async_call_later(
            self.hass, eval_delay_s, _on_eval_fire,
        )
        _LOGGER.info(
            "Soft nudge restored on %s (target=%.1f); evaluating in %ds",
            zone.zone_name, original_target, eval_delay_s,
        )

    async def _compute_post_restore_min_kw(
        self,
        zone: ZoneState,
        restore_dt: datetime,
        eval_dt: datetime,
    ) -> tuple[float | None, int]:
        """Query HA recorder for kW samples on `zone.ac_load_sensor` over
        `[restore_dt, eval_dt]` and return (min_kw, sample_count).

        Returns (None, 0) if:
          - zone has no ac_load_sensor configured
          - recorder query errors out
          - no valid (parseable, non-stale, non-empty) samples in window

        Unit normalization matches `_read_kwh_rate`: W -> kW.

        v4.7.17.1: introduced for the new effectiveness rule. The trailing-
        window minimum captures the compressor's actual valley during the
        post-restore window, which is the signal we want — not the single-
        sample read at restore+eval_delay (which was likely sampling the
        rebound peak on variable-speed Bryant systems).
        """
        if not zone.ac_load_sensor:
            return None, 0
        try:
            instance = recorder_get_instance(self.hass)
            states_dict = await instance.async_add_executor_job(
                get_significant_states,
                self.hass,
                restore_dt,
                eval_dt,
                [zone.ac_load_sensor],
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug(
                "AC nudge eval: recorder query failed for %s: %s",
                zone.ac_load_sensor, err,
            )
            return None, 0

        states = states_dict.get(zone.ac_load_sensor) if states_dict else None
        if not states:
            return None, 0

        min_kw: float | None = None
        sample_count = 0
        for st in states:
            raw = getattr(st, "state", None)
            if raw in (None, "unknown", "unavailable", ""):
                continue
            try:
                value = float(raw)
            except (ValueError, TypeError):
                continue
            attrs = getattr(st, "attributes", None) or {}
            unit = (attrs.get("unit_of_measurement") or "").lower()
            if unit in ("w", "watt", "watts"):
                value = value / 1000.0
            sample_count += 1
            if min_kw is None or value < min_kw:
                min_kw = value
        return min_kw, sample_count

    async def _evaluate_nudge_outcome(self, zone: ZoneState) -> None:
        """Post-restore: did the compressor release? If not, escalate.

        v4.7.17.1 redesign — was a single-sample read at restore+600s,
        which on variable-speed Bryant systems sampled the rebound peak
        instead of the valley. Live recorder data (2026-06-01) showed
        5 of 6 nudges produced 71-89% kW reduction during the hold but
        then rebounded to full power during minutes 5-10 post-restore;
        the single-sample rule misclassified 3 of 10 as FP.

        New rule:
          1. Compute post_min = min kW over [restore_ts, eval_ts] via
             HA recorder query (NOT a per-tick listener; URA does not
             have one for the kW sensor).
          2. If kwh_rate_before is None / < AC_NUDGE_KWH_RATE_BEFORE_FLOOR
             (0.3 kW), classify as "inconclusive" — `effective = None`,
             EXCLUDE from FP statistics rather than treating as FP.
          3. If post_min is None (recorder gave us nothing), preserve
             pre-existing escalation behavior conservatively: classify
             as ineffective (operator would rather a spurious hard reset
             than a stranded compressor burning kWh).
          4. Else: effective iff `post_min < AC_NUDGE_EVAL_MIN_DROP_FRAC
             * kwh_rate_before` (default 0.50 — see hvac_const.py for
             calibration notes).

        DB write:
          - effective boolean column populated (v4.7.17.1 schema add).
          - notes: `kwh_avoided=X.XXX;post_min=Y.YY;sample_count=N` —
            semicolon-separated key=value, matches existing parser at
            database.py:5576.

        Mid-restart behavior preserved: if HA restarts during the eval
        window, `_nudge_post_restore_ts[zone_id]` is lost; this method
        is never called for that nudge; the row is never written; the
        event is silently excluded from FP statistics. Tier 1 scope
        does not add persistence — separate cycle.
        """
        zone_id = zone.zone_id
        self._nudge_eval_timers.pop(zone_id, None)

        now = dt_util.now()
        kwh_rate_before = zone.nudge_kwh_rate_before
        restore_iso = self._nudge_post_restore_ts.pop(zone_id, None)

        # Compute trailing-window minimum kW over [restore_ts, now]
        post_min: float | None = None
        sample_count = 0
        if restore_iso is not None:
            try:
                restore_dt = datetime.fromisoformat(restore_iso)
            except (ValueError, TypeError):
                restore_dt = None
            if restore_dt is not None:
                post_min, sample_count = await self._compute_post_restore_min_kw(
                    zone, restore_dt, now,
                )

        # Classify
        # 1) Floor on kwh_rate_before — signal-to-noise too low below 0.3 kW
        if (kwh_rate_before is None
                or kwh_rate_before < AC_NUDGE_KWH_RATE_BEFORE_FLOOR):
            classification = "inconclusive"
            effective: bool | None = None
            escalate = False
        # 2) Recorder gave us nothing — conservative ineffective (preserves
        #    pre-existing escalation behavior, see docstring rule 3).
        elif post_min is None:
            classification = "ineffective_no_samples"
            effective = False
            escalate = True
        # 3) New rule — trailing-window min vs before
        elif post_min < AC_NUDGE_EVAL_MIN_DROP_FRAC * kwh_rate_before:
            classification = "effective"
            effective = True
            escalate = False
        else:
            classification = "ineffective"
            effective = False
            escalate = True

        # Compute capped kWh-avoided estimate (uses post_min when present,
        # falls back to pre-existing rough estimate of zero when not).
        kwh_avoided = 0.0
        if effective and post_min is not None and kwh_rate_before is not None:
            delta = kwh_rate_before - post_min
            if delta > 0:
                kwh_avoided = delta * (AC_KWH_AVOIDED_PROJECTION_CAP_MIN / 60.0)

        self._track_zone_action(
            zone, AC_RAMP_EVENT_NUDGE_EVALUATED, "auto",
            kwh_before=kwh_rate_before,
            kwh_after=post_min,
        )
        if self._db is not None:
            # Structured notes — semicolon-separated key=value pairs,
            # parser at database.py:5576 splits on `;` then `=`. Format
            # MUST stay key=value;key=value for back-compat.
            notes = (
                f"kwh_avoided={kwh_avoided:.3f};"
                f"post_min={'NA' if post_min is None else f'{post_min:.2f}'};"
                f"sample_count={sample_count};"
                f"classification={classification}"
            )
            await self._db.log_ac_ramp_event(
                zone_id=zone_id,
                event_type=AC_RAMP_EVENT_NUDGE_EVALUATED,
                current_temp=zone.current_temperature,
                target_high=zone.target_temp_high,
                kwh_rate_before=kwh_rate_before,
                kwh_rate_after=post_min,
                effective=effective,
                notes=notes,
            )

        if escalate:
            zone.ramp_state = AC_RAMP_STATE_ESCALATING
            _LOGGER.warning(
                "Nudge ineffective on %s (kwh_rate_before=%.2f, post_min=%s, "
                "samples=%d, classification=%s) — escalating to hard reset",
                zone.zone_name,
                kwh_rate_before if kwh_rate_before is not None else 0.0,
                f"{post_min:.2f}" if post_min is not None else "None",
                sample_count, classification,
            )
            await self._perform_hard_reset_escalation(
                zone, post_min if post_min is not None else 0.0,
            )
        else:
            zone.ramp_state = AC_RAMP_STATE_IDLE
            zone.nudge_kwh_rate_before = None
            if effective:
                _LOGGER.info(
                    "Nudge effective on %s: kwh_rate %.2f -> post_min %.2f kW "
                    "(samples=%d, avoided ~%.2f kWh est.)",
                    zone.zone_name, kwh_rate_before, post_min,
                    sample_count, kwh_avoided,
                )
            else:
                # Inconclusive — excluded from FP stats. Log so operator can
                # see the reason without the row counting against the metric.
                _LOGGER.info(
                    "Nudge inconclusive on %s (kwh_rate_before=%s below floor"
                    " %.2f kW) — excluded from FP statistics",
                    zone.zone_name,
                    f"{kwh_rate_before:.2f}" if kwh_rate_before is not None else "None",
                    AC_NUDGE_KWH_RATE_BEFORE_FLOOR,
                )

    async def _perform_hard_reset_escalation(
        self, zone: ZoneState, kwh_rate_now: float,
    ) -> None:
        """Gated hard reset (compressor protection).

        Two gates AND together:
          - daily cap (hard_reset_count_today < limit)
          - global min-interval (no-date-filter MAX query — Risk R2)

        Cap hit -> _engage_lockout. Min-interval gate fail -> log + skip.
        Both pass -> increment counter, fire _perform_ac_reset (existing
        v3.18.x off->wait->restore logic with verify+retry).

        v4.7.7 A3: early-return guard. When `_ac_reset_enabled=False`
        (decoupled-off via v4.7.7), the escalation path is a no-op:
        set ramp_state IDLE and return WITHOUT engaging lockout, DB
        writes, or daily-cap math. Fixes the lockout side-effect bug
        where `_hard_reset_daily_limit=0` previously fired
        `_engage_lockout` on the FIRST failed nudge eval because
        `int(state.get("hard_reset_count", 0)) >= 0` was true
        immediately.
        """
        zone_id = zone.zone_id
        now = dt_util.now()

        # v4.7.7 A3: clean skip when reset feature is decoupled-disabled.
        # The soft-nudge already ran (Gate 0a/0b passed) but escalation
        # is the AC-Reset surface — without it enabled, there's no
        # legitimate work here. NO lockout, NO DB writes.
        #
        # v4.7.7 B-L1 fix-up: `self._ac_reset_enabled` is read LIVE here
        # (not snapshotted) by deliberate design — escalation respects the
        # CURRENT toggle, not the toggle at nudge-start time ~10 min ago.
        # The Gate 0 snapshot in `check_ac_reset` (L891-L892) protects
        # against intra-tick races on the soft-nudge entry point; this
        # live read is a different decision boundary (deferred escalation
        # 10 min after nudge start). See Tier 2 Reviewer B B-L1.
        if not self._ac_reset_enabled:
            zone.ramp_state = AC_RAMP_STATE_IDLE
            _LOGGER.debug(
                "Hard reset on %s skipped — AC Reset feature disabled "
                "(soft-nudge ran but escalation is decoupled-off)",
                zone.zone_name,
            )
            return

        if self._db is None:
            zone.ramp_state = AC_RAMP_STATE_IDLE
            return

        state = await self._db.get_ac_reset_state(zone_id)

        # Gate A: daily cap
        if int(state.get("hard_reset_count", 0)) >= self._hard_reset_daily_limit:
            await self._engage_lockout(zone, state)
            return

        # Gate B: global min-interval (R2 — across day-rollover)
        last_global_ts = await self._db.get_global_last_hard_reset_ts(zone_id)
        if last_global_ts:
            try:
                last = datetime.fromisoformat(last_global_ts)
                age_min = (now - last).total_seconds() / 60
            except (ValueError, TypeError):
                age_min = self._hard_reset_min_interval_min + 1  # treat as ok
            if age_min < self._hard_reset_min_interval_min:
                _LOGGER.warning(
                    "Hard reset on %s blocked by min-interval gate "
                    "(last=%.0fmin ago, gate=%dmin)",
                    zone.zone_name, age_min, self._hard_reset_min_interval_min,
                )
                zone.ramp_state = AC_RAMP_STATE_IDLE
                return

        # Both gates passed
        state["hard_reset_count"] = int(state.get("hard_reset_count", 0)) + 1
        state["last_hard_reset_ts"] = now.isoformat()
        await self._db.save_ac_reset_state(state)
        self._track_zone_action(
            zone, AC_RAMP_EVENT_HARD_RESET_STARTED, "auto",
            kwh_before=kwh_rate_now,
        )
        await self._db.log_ac_ramp_event(
            zone_id=zone_id,
            event_type=AC_RAMP_EVENT_HARD_RESET_STARTED,
            kwh_rate_before=kwh_rate_now,
            hard_reset_count_today=int(state["hard_reset_count"]),
        )
        # Keep ZoneState counter in sync for legacy sensor exposure
        zone.ac_reset_count_today = int(state["hard_reset_count"])

        # Reuse existing _perform_ac_reset (off -> wait -> restore w/ verify)
        await self._perform_ac_reset(zone)

    async def _engage_lockout(
        self, zone: ZoneState, state: dict,
    ) -> None:
        """Cap hit — set lockout_flag, fire persistent notification (D6)."""
        zone_id = zone.zone_id
        state["lockout_flag"] = 1
        await self._db.save_ac_reset_state(state)
        self._track_zone_action(
            zone, AC_RAMP_EVENT_LOCKOUT_ENGAGED, "auto",
        )
        await self._db.log_ac_ramp_event(
            zone_id=zone_id,
            event_type=AC_RAMP_EVENT_LOCKOUT_ENGAGED,
            hard_reset_count_today=int(state.get("hard_reset_count", 0)),
            lockout_triggered=True,
        )
        zone.ramp_state = AC_RAMP_STATE_LOCKED_OUT

        try:
            await self.hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": f"AC Ramp Lockout: {zone.zone_name}",
                    "message": (
                        f"AC {zone.zone_name} hit max hard resets today "
                        f"({state.get('hard_reset_count', 0)}). Controller may "
                        f"need manual investigation. Resets resume tomorrow. "
                        f"Use the Clear Lockout button if this was a false "
                        f"positive."
                    ),
                    "notification_id": f"ura_ac_ramp_lockout_{zone_id}",
                },
                blocking=False,
            )
        except Exception as e:
            _LOGGER.warning("Lockout notification failed for %s: %s",
                            zone.zone_name, e)
        _LOGGER.warning(
            "AC ramp lockout engaged on %s (hard_reset_count=%d)",
            zone.zone_name, state.get("hard_reset_count", 0),
        )

    def _resolve_zone(self, zone_id_or_entity: str):
        """Find a ZoneState by zone_id OR climate_entity.

        v4.5.11 review-2 fix: button + Number entities derive zone_id
        locally from climate.x_zone_3 -> 'x_zone_3', but ZoneManager
        derives zone_3 via _zone_id_from_thermostat. Accept either so
        callers from the platform side (which often only know the
        climate entity) and the coordinator side (which uses its own
        zone_id scheme) both work.

        Returns the ZoneState if found, else None.
        """
        zone = self._zone_manager.zones.get(zone_id_or_entity)
        if zone is not None:
            return zone
        for z in self._zone_manager.zones.values():
            if z.climate_entity == zone_id_or_entity:
                return z
        return None

    async def cancel_nudge(
        self, zone_id: str, triggered_by: str = "manual",
    ) -> None:
        """Abort an in-flight nudge, restore target immediately (D9 button)."""
        zone = self._resolve_zone(zone_id)
        if zone is None:
            return
        # Use the canonical zone_id from the resolved state for downstream
        # DB ops (the parameter could have been a climate entity).
        zone_id = zone.zone_id

        cancel = self._nudge_restore_timers.pop(zone_id, None)
        if cancel:
            cancel()
        cancel_eval = self._nudge_eval_timers.pop(zone_id, None)
        if cancel_eval:
            cancel_eval()
        # v4.7.17.1: clear the restore-ts anchor when cancelling — prevents
        # a future _evaluate_nudge_outcome from running a recorder query
        # against a stale window.
        self._nudge_post_restore_ts.pop(zone_id, None)
        self._nudge_in_flight.discard(zone_id)

        original_target = None
        if self._db is not None:
            state = await self._db.get_ac_reset_state(zone_id)
            original_target = state.get("in_flight_nudge_original_target")

        if original_target is not None:
            self.suppress(zone.climate_entity)
            try:
                await emit_set_temperature(
                    self.hass,
                    zone.climate_entity,
                    target_temp_low=zone.target_temp_low,
                    target_temp_high=float(original_target),
                    freeze_active=self._freeze_active(),
                    blocking=False,
                )
            except Exception as e:
                _LOGGER.error(
                    "cancel_nudge restore failed for %s: %s",
                    zone.climate_entity, e,
                )

        self._track_zone_action(
            zone, AC_RAMP_EVENT_CANCEL_INVOKED, triggered_by,
        )
        if self._db is not None:
            await self._db.clear_ac_in_flight_nudge(zone_id)
            await self._db.log_ac_ramp_event(
                zone_id=zone_id,
                event_type=AC_RAMP_EVENT_CANCEL_INVOKED,
                triggered_by=triggered_by,
                target_high=(
                    float(original_target)
                    if original_target is not None else None
                ),
            )

        zone.ramp_state = AC_RAMP_STATE_IDLE
        _LOGGER.info(
            "Nudge cancelled on %s (triggered_by=%s)",
            zone.zone_name, triggered_by,
        )

    async def force_nudge(self, zone_id: str) -> None:
        """User-triggered nudge (D9 button).

        Respects master switch (kill-switch contract) but ignores daily caps
        — counts toward day's budget so can't mask runaway loops via testing.
        """
        if not self._ramp_master_enabled:
            _LOGGER.warning(
                "force_nudge blocked: master switch is OFF (zone=%s)", zone_id,
            )
            return
        zone = self._resolve_zone(zone_id)
        if zone is None:
            return
        zone_id = zone.zone_id  # canonicalize
        if zone_id in self._nudge_in_flight:
            _LOGGER.warning(
                "force_nudge: %s already mid-nudge", zone.zone_name,
            )
            return

        now = dt_util.now()
        kwh_rate = self._read_kwh_rate(zone, now) or 0.0
        await self._perform_soft_nudge(zone, kwh_rate, triggered_by="manual")

    async def force_ac_reset(self, zone_id_or_entity: str) -> None:
        """User-triggered hard AC reset (v4.7.9 D1 button).

        Bridges the (Nudge=OFF, Reset=ON) cell of the v4.7.7 decouple matrix:
        soft-nudge auto-detection may be disabled, but the user still wants a
        manual entry point into the hard-reset escalation path. Mirrors the
        `force_nudge` precedent above.

        Gates applied (in order):
          - Master switch (kill-switch contract — same as force_nudge).
          - A3 guard inside _perform_hard_reset_escalation (no-op when
            _ac_reset_enabled is False; sets zone.ramp_state IDLE; no DB
            writes, no lockout engagement).
          - Daily cap + global min-interval gates inside the escalation.

        Note on triggered_by traceability: the existing
        `_perform_hard_reset_escalation` hard-codes `"auto"` at the
        `_track_zone_action` and `log_ac_ramp_event` call sites
        (hvac_override.py L1591). Adding a `triggered_by="manual"`
        parameter changes the signature for one caller — explicitly
        out-of-scope per planning §6 (D1 Spec correction). The resulting
        `ac_ramp_events` row will carry `auto` for force-reset presses;
        this is an accepted limitation for v4.7.9 hygiene-scale.

        kwh_rate_now=0.0 is passed because a manual button press is not
        reacting to a live overshoot reading — the user has decided the
        AC needs a reset and the gates inside the escalation make the
        actual decision. The kWh field on the resulting event row will
        be 0.0; downstream analytics that condition on kwh_rate_before
        treat the manual entry as a zero-rate event (acceptable; manual
        traceability is the deferred concern, not numeric accuracy).
        """
        if not self._ramp_master_enabled:
            _LOGGER.warning(
                "force_ac_reset blocked: master switch is OFF (zone=%s)",
                zone_id_or_entity,
            )
            return
        zone = self._resolve_zone(zone_id_or_entity)
        if zone is None:
            _LOGGER.warning(
                "force_ac_reset: zone %s not found in ZoneManager",
                zone_id_or_entity,
            )
            return
        zone_id = zone.zone_id  # canonicalize before timer/DB cleanup

        # v4.7.9 A-H1 fix-up: cancel any in-flight soft-nudge timers BEFORE
        # invoking the escalation. Without this, a still-active nudge's
        # restore/eval timers fire on top of the reset's off->wait->restore
        # cycle (race: nudge restore writes a setpoint while the reset's
        # off-state is in flight; nudge eval may schedule yet another
        # action). Mirrors the `cancel_nudge` cleanup pattern (L1680-1686)
        # and matches the in-flight guard at force_nudge (L1748).
        cancel_restore = self._nudge_restore_timers.pop(zone_id, None)
        if cancel_restore:
            cancel_restore()
        cancel_eval = self._nudge_eval_timers.pop(zone_id, None)
        if cancel_eval:
            cancel_eval()
        # v4.7.17.1: clear the restore-ts anchor on startup audit too.
        self._nudge_post_restore_ts.pop(zone_id, None)
        self._nudge_in_flight.discard(zone_id)
        if self._db is not None:
            try:
                await self._db.clear_ac_in_flight_nudge(zone_id)
            except Exception as e:
                _LOGGER.warning(
                    "force_ac_reset: failed to clear in-flight nudge row "
                    "for %s: %s (continuing into escalation)", zone_id, e,
                )

        _LOGGER.info(
            "force_ac_reset invoked on %s (zone_id=%s) — routing to "
            "_perform_hard_reset_escalation (A3 guard + daily cap + "
            "min-interval gates apply)",
            zone.zone_name, zone.zone_id,
        )
        # kwh_rate_now=0.0: manual presses don't react to a reading; the
        # signature requires a float; downstream code treats 0.0 cleanly.
        await self._perform_hard_reset_escalation(zone, 0.0)

    async def clear_zone_lockout(self, zone_id: str) -> None:
        """Reset today's counters + clear lockout for one zone (D9 button)."""
        if self._db is None:
            return
        zone = self._resolve_zone(zone_id)
        if zone is not None:
            zone_id = zone.zone_id  # canonicalize before DB write
            zone.ac_reset_count_today = 0
            zone.ramp_state = AC_RAMP_STATE_IDLE
        await self._db.clear_ac_zone_today(zone_id)
        try:
            await self.hass.services.async_call(
                "persistent_notification",
                "dismiss",
                {"notification_id": f"ura_ac_ramp_lockout_{zone_id}"},
                blocking=False,
            )
        except Exception:
            pass
        _LOGGER.info("Cleared lockout for zone %s", zone_id)

    async def async_startup_ramp_audit(self) -> None:
        """Restore in-flight nudges that survived an HA restart (R1).

        Scans ac_reset_state for non-NULL in_flight_nudge_original_target.
        For each:
          - elapsed >= duration  -> restore immediately + clear DB
          - elapsed <  duration  -> schedule restore for remaining time

        Called from HVAC coordinator first-decision-cycle (post-state-init)
        so climate entities have populated their initial state.
        """
        if self._db is None:
            return
        rows = await self._db.get_zones_with_in_flight_nudge()
        if not rows:
            return
        now = dt_util.now()
        for row in rows:
            zone_id = row["zone_id"]
            # v4.7.8 fix-up A-H2 (Bug Class #33): defer in-flight nudge
            # restoration on egress-paused zones. The dispatch would be a
            # no-op on the off thermostat but would still log + churn
            # internal state. Resume happens cleanly on next tick after
            # _engage_resume.
            if (
                self._egress_manager is not None
                and self._egress_manager.is_paused(zone_id)
            ):
                continue
            zone = self._zone_manager.zones.get(zone_id)
            if zone is None:
                # Stale row for a zone that no longer exists — clear it
                await self._db.clear_ac_in_flight_nudge(zone_id)
                continue

            original_target = row.get("original_target")
            if original_target is None:
                continue

            started_ts = row.get("started_ts")
            duration_s = int(row.get("duration_s") or 0)
            elapsed_s: float
            if started_ts:
                try:
                    started = datetime.fromisoformat(started_ts)
                    elapsed_s = (now - started).total_seconds()
                except (ValueError, TypeError):
                    elapsed_s = float(duration_s + 1)  # treat as expired
            else:
                elapsed_s = float(duration_s + 1)

            if elapsed_s >= duration_s:
                # Expired — restore now
                self.suppress(zone.climate_entity)
                try:
                    await emit_set_temperature(
                        self.hass,
                        zone.climate_entity,
                        target_temp_low=zone.target_temp_low,
                        target_temp_high=float(original_target),
                        freeze_active=self._freeze_active(),
                        blocking=False,
                    )
                except Exception as e:
                    _LOGGER.error(
                        "Startup nudge restore failed for %s: %s",
                        zone.climate_entity, e,
                    )
                await self._db.clear_ac_in_flight_nudge(zone_id)
                await self._db.log_ac_ramp_event(
                    zone_id=zone_id,
                    event_type=AC_RAMP_EVENT_STARTUP_RESTORE,
                    triggered_by="startup",
                    target_high=float(original_target),
                    notes=f"elapsed_s={elapsed_s:.0f};duration_s={duration_s};expired",
                )
                zone.ramp_state = AC_RAMP_STATE_IDLE
                _LOGGER.info(
                    "Startup audit: restored expired nudge on %s (target=%.1f)",
                    zone.zone_name, original_target,
                )
            else:
                # Still in-window — schedule restore for the remaining time
                remaining_s = duration_s - elapsed_s
                self._nudge_in_flight.add(zone_id)
                zone.ramp_state = AC_RAMP_STATE_NUDGING
                target = float(original_target)

                @callback
                def _on_resume_restore(_now, z=zone, t=target):
                    self.hass.async_create_task(
                        self._restore_after_nudge(z, t)
                    )

                self._nudge_restore_timers[zone_id] = async_call_later(
                    self.hass, remaining_s, _on_resume_restore,
                )
                await self._db.log_ac_ramp_event(
                    zone_id=zone_id,
                    event_type=AC_RAMP_EVENT_STARTUP_RESTORE,
                    triggered_by="startup",
                    target_high=target,
                    notes=f"resume_remaining_s={remaining_s:.0f}",
                )
                _LOGGER.info(
                    "Startup audit: resuming nudge on %s, %.0fs remaining",
                    zone.zone_name, remaining_s,
                )

    # =========================================================================
    # Helpers
    # =========================================================================

    def _find_zone_by_entity(self, entity_id: str) -> ZoneState | None:
        """Find zone by climate entity ID."""
        for zone in self._zone_manager.zones.values():
            if zone.climate_entity == entity_id:
                return zone
        return None

    def _compute_override_delta(
        self,
        new_high: Any,
        new_low: Any,
        expected_cool: float,
        expected_heat: float,
    ) -> float | None:
        """Compute the largest deviation from expected setpoints.

        Returns positive if warmer (cool setpoint raised), negative if cooler.
        """
        deltas = []
        if new_high is not None:
            try:
                deltas.append(float(new_high) - expected_cool)
            except (ValueError, TypeError):
                pass
        if new_low is not None:
            try:
                deltas.append(float(new_low) - expected_heat)
            except (ValueError, TypeError):
                pass

        if not deltas:
            return None

        # Return the delta with the largest absolute value
        return max(deltas, key=abs)

    def _cancel_zone_timers(self, zone_id: str) -> None:
        """Cancel all active timers for a zone."""
        for timer_dict in (
            self._grace_timers,
            self._compromise_timers,
            self._reset_timers,
        ):
            cancel = timer_dict.pop(zone_id, None)
            if cancel:
                cancel()

    async def _send_nm_alert(
        self,
        title: str,
        message: str,
        severity: str = "high",
    ) -> None:
        """Send alert through Notification Manager."""
        from ..const import DOMAIN

        nm = self.hass.data.get(DOMAIN, {}).get("notification_manager")
        if nm is None:
            _LOGGER.warning("HVAC Override NM (no NM): %s — %s", title, message)
            return
        try:
            from .base import Severity

            severity_map = {
                "low": Severity.LOW,
                "medium": Severity.MEDIUM,
                "high": Severity.HIGH,
                "critical": Severity.CRITICAL,
            }
            await nm.async_notify(
                coordinator_id="hvac",
                severity=severity_map.get(severity, Severity.HIGH),
                title=title,
                message=message,
                hazard_type="hvac_override",
            )
        except Exception:
            # v4.5.20: was debug. Soft-escalate matching the energy.py NM
            # alert pattern. Notification miss is non-critical; warning +
            # exc_info gives observability without alarming.
            _LOGGER.warning(
                "HVAC Override: NM alert failed (non-fatal): %s",
                title,
                exc_info=True,
            )

    # =========================================================================
    # Status for sensors
    # =========================================================================

    def get_override_status(self) -> dict[str, Any]:
        """Return override status for all zones."""
        total_overrides = sum(
            z.override_count_today for z in self._zone_manager.zones.values()
        )
        total_resets = sum(
            z.ac_reset_count_today for z in self._zone_manager.zones.values()
        )
        active_overrides = sum(1 for v in self._override_active.values() if v)
        active_compromises = sum(1 for v in self._compromise_active.values() if v)

        return {
            "enabled": self._enabled,
            "overrides_today": total_overrides,
            "ac_resets_today": total_resets,
            "active_overrides": active_overrides,
            "active_compromises": active_compromises,
        }

    def get_arrester_state(self) -> str:
        """Return current arrester state for diagnostic sensor."""
        if not self._enabled:
            return "disabled"
        if any(self._compromise_active.values()):
            return "compromise"
        if self._grace_timers:
            return "grace_period"
        if any(self._override_active.values()):
            return "active"
        return "idle"

    def get_arrester_detail(self) -> dict[str, Any]:
        """Return per-zone arrester detail for diagnostic sensor."""
        zones_detail = {}
        for zone_id, zone in self._zone_manager.zones.items():
            detail: dict[str, Any] = {
                "overrides_today": zone.override_count_today,
                "ac_resets_today": zone.ac_reset_count_today,
            }
            if self._override_active.get(zone_id, False):
                detail["state"] = "override_active"
            if self._compromise_active.get(zone_id, False):
                detail["state"] = "compromise"
            if zone_id in self._grace_timers:
                detail["state"] = "grace_period"
            if "state" not in detail:
                detail["state"] = "idle"
            if zone.last_override_direction:
                detail["last_direction"] = zone.last_override_direction
            zones_detail[zone.zone_name] = detail
        return {
            "state": self.get_arrester_state(),
            "enabled": self._enabled,
            "ac_reset_enabled": self._ac_reset_enabled,
            "zones": zones_detail,
            "energy_coast": self._energy_coast,
            "energy_offset": self._energy_offset,
        }
