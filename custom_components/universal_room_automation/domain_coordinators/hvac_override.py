"""Override Arrester + AC Reset for HVAC Coordinator.

Detects manual thermostat overrides, applies two-tier severity response
(severe: immediate revert after grace; normal: compromise then revert),
and resets stuck AC cycles.

v3.8.3-H2: Initial implementation.
"""

from __future__ import annotations

import asyncio
import logging
import math
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.recorder import get_instance as recorder_get_instance
from homeassistant.components.recorder.history import get_significant_states
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
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
    AC_NUDGE_RESTORE_SETTLE_DELAY_S,
    AC_NUDGE_RESTORE_SETTLED_UNMEASURABLE_REASON,
    AC_NUDGE_KWH_RATE_BEFORE_FLOOR,
    AC_NUDGE_OVERSHOOT_GAP,
    ARRESTER_IMMUNE_HOLD_MAX_S,
    ARRESTER_IMMUNITY_VOICE_CONTEXTS,
    ARRESTER_OVERRIDE_EXPIRY_WARN_S,
    ARRESTER_OVERRIDE_MIN_LIFE_S,
    COMFORT_DELTA_MIN_F,
    COMFORT_GRACE_MIN,
    COMFORT_OVERRIDE_MAX_S,
    COMFORT_SOC_FLOOR_PCT,
    COMFORT_TEMP_MAX_AGE_S,
    DURABLE_HOUSE_STATES,  # legacy, kept for import graph; do NOT read here
    house_state_invalidates_arrester_hold,
    SIGNAL_HVAC_TEMP_ARRESTER_OVERRIDE_UPDATE,
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
    # AC-RAMP-PIPELINE-HARDENING-1
    AC_ACTIVELY_COOLING_BLOWER_RPM_MIN,
    AC_ACTIVELY_COOLING_KW_MIN,
    AC_KWH_SENSOR_STALENESS_S,
    AC_RAMP_EVENT_GATE4_DIVERGENCE_SHADOW,
    AC_RAMP_EVENT_HARD_RESET_DECLINED,
    AC_RESET_DECLINED_COMFORT_DEFERRED,
    AC_RESET_DECLINED_DAY_BUDGET,
    AC_RESET_DECLINED_FEATURE_DISABLED,
    AC_RESET_DECLINED_GLOBAL_MIN_INTERVAL,
    AC_RESET_DECLINED_MASTER_OFF,
    AC_RESET_DECLINED_MIN_INTERVAL_S,
    AC_RESET_DECLINED_NIGHT_BUDGET,
    AC_RESET_DECLINED_TRUE_CAP_EXHAUSTED,
    AC_RESET_OUTCOME_FLOOR_SURVIVED,
    AC_RESET_OUTCOME_INCONCLUSIVE,
    AC_RESET_OUTCOME_JUSTIFIED_RAMP,
    AC_RESET_OUTCOME_SETTLE_S,
    AC_RESET_OUTCOME_KWH_SETTLE_S,
    DEFAULT_HVAC_AC_DURABILITY_WINDOW,
    DEFAULT_HVAC_AC_GATE4_PREDICATE_MODE,
    DEFAULT_HVAC_AC_NIGHT_END_HHMM,
    DEFAULT_HVAC_AC_NIGHT_START_HHMM,
    DEFAULT_HVAC_AC_RESET_DAY_BUDGET,
    DEFAULT_HVAC_AC_RESET_NIGHT_BUDGET,
    DEFAULT_HVAC_AC_SOFT_NUDGE_DAILY_LIMIT,
    HVAC_AC_GATE4_MODE_LEGACY,
    HVAC_AC_GATE4_MODE_LIVE,
    HVAC_AC_GATE4_MODE_SHADOW,
    HVAC_AC_GATE4_MODES,
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
from .energy_billing import _get_effective_rate_kwh
from .hvac_setpoint import emit_set_preset_mode, emit_set_temperature
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
        # ARREST-COMFORT-1 Cycle A: SOC snapshot + shed pushed via
        # update_energy_state(); D1 (grant) + D3 (coast guard) share
        # HVACCoordinator accessors (planning §8).
        self._battery_soc: float | None = None
        self._battery_blind: bool = False
        self._shed_active: bool = False
        # Per-zone comfort-delay grants (RAM-only §3.5). Grant key =
        # zone_id (audit §metric 4: zero multi-thermostat zones).
        self._comfort_delay_timers: dict[str, CALLBACK_TYPE] = {}
        self._comfort_delay_meta: dict[str, dict[str, Any]] = {}
        # ARREST-COMFORT-1 fix-up A-HIGH-1: rung-3 live knobs. `None` =
        # fall back to module-constant default (preserves pre-cycle
        # monkeypatch semantics for tests that patch the module constant).
        # Number entities call `set_comfort_grace_min` / `set_comfort_soc_
        # floor_pct` at setup — from that point the instance attr wins.
        self._comfort_grace_min: int | None = None
        self._comfort_soc_floor_pct: int | None = None

        # Suppression: entity_id -> wall-clock expiry for ignoring overrides
        # during URA-initiated changes. v4.7.33 A-F5: replaced the prior
        # `set[str]` (popped on first state event) with a TTL window so a
        # single URA action that produces multiple settle events (e.g.
        # set_hvac_mode + set_preset_mode in _revert_override) stays
        # suppressed across all of them. Window self-clears on TTL expiry.
        self._suppressed_until: dict[str, datetime] = {}
        # FIX B1: tag each active suppression with a KIND so the
        # manual-passthrough (~:660) can distinguish induced-manual from
        # a URA temp-write ("temp") vs a URA preset-write ("preset") vs
        # an untagged external suppression (None, legacy). An induced
        # preset_mode sleep->manual event that lands inside a "temp"
        # suppression window must NOT self-count as a user override
        # (85 auto ac_ramp_events/night on empty house with
        # current_temp==target).
        self._suppress_kind: dict[str, str | None] = {}
        # FIX B2: pre-nudge preset capture. On preset-based Carrier/Bryant
        # thermostats, a `set_temperature` write flips `preset_mode` from
        # e.g. `sleep`->`manual` as a side effect and it PERSISTS —
        # `_restore_after_nudge` only writes target back, never preset, so
        # the thermostat sits in `manual` for the rest of the night, and
        # the user's sleep-preset schedule is defeated across 20+ nudges
        # per night. We snapshot the preset BEFORE the nudge write; if
        # the restore path sees preset == "manual" and the snapshot was a
        # non-manual preset, we also emit a `set_preset_mode` to restore
        # it. Empty snapshot (unknown/unavailable at nudge time) = skip
        # restore = fail-safe (no worse than pre-fix behavior).
        self._nudge_pre_preset: dict[str, str] = {}
        # HVAC-GOVERNED-EXCURSION-1 D3: per-zone ExcursionToken issued at
        # nudge start; consumed by restore/cancel/audit paths to call
        # return_excursion (which clears the persisted lease row).
        self._nudge_excursion_tokens: dict = {}
        # Same for compromise (rows 4/5).
        self._compromise_excursion_tokens: dict = {}

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
        # AC-RAMP-PIPELINE-HARDENING-1: new live-tunable state.
        # D-GATE4: predicate mode Select — legacy | shadow (default) | live.
        # Kill-switch = "legacy" (restores pre-cycle Gate 4 body verbatim).
        self._gate4_predicate_mode: str = DEFAULT_HVAC_AC_GATE4_PREDICATE_MODE
        # LATCHED per-zone divergence writer state (REBUILD across restart).
        # Values: None (never seen) | "agree" | "diverge". Prevents
        # per-tick write flood — one row on agree→diverge, one on
        # diverge→agree.
        self._gate4_divergence_state: dict[str, str] = {}
        # D-SCORE: durability classifier window (options rung 2 mins).
        self._durability_window_min: int = DEFAULT_HVAC_AC_DURABILITY_WINDOW
        # Per-zone cancel handles for the delayed `_write_durable` callback.
        # Registry shape mirrors `_nudge_settled_timers`. Cancelled on
        # teardown; fired-early with truncated=True on re-nudge.
        self._durable_timers: dict[str, CALLBACK_TYPE] = {}
        # Per-zone {event_id, started_ts, kwh_rate_before, restore_dt}
        # closure state so the callback can UPDATE the correct row.
        self._durable_pending: dict[str, dict] = {}
        # D3: runaway guard on the auto soft-nudge path only. Manual
        # force_nudge bypasses (operator intent beats runaway guard).
        self._soft_nudge_daily_limit: int = DEFAULT_HVAC_AC_SOFT_NUDGE_DAILY_LIMIT
        # D2 / D-PARTITION: partitioned reset budgets (operator 2/2).
        self._reset_day_budget: int = DEFAULT_HVAC_AC_RESET_DAY_BUDGET
        self._reset_night_budget: int = DEFAULT_HVAC_AC_RESET_NIGHT_BUDGET
        self._night_start_hhmm: str = DEFAULT_HVAC_AC_NIGHT_START_HHMM
        self._night_end_hhmm: str = DEFAULT_HVAC_AC_NIGHT_END_HHMM
        # D7: promote AC_RESET_OFF_DURATION_SECONDS to a live knob.
        # Seeded from the module const for first-boot behaviour.
        self._ac_reset_off_duration_s: int = int(
            AC_RESET_OFF_DURATION_SECONDS
        )
        # D6: per-zone reset-outcome delayed-callback registry (60s).
        # Short-lived timer — REBUILD on restart is acceptable per plan.
        self._reset_outcome_timers: dict[str, CALLBACK_TYPE] = {}
        self._reset_outcome_pending: dict[str, dict] = {}
        # F6 fix-up: second delayed-callback registry for the kW capture
        # at AC_RESET_OUTCOME_KWH_SETTLE_S (150s vs the temp's 60s).
        # See `_schedule_reset_outcome`.
        self._reset_outcome_kw_timers: dict[str, CALLBACK_TYPE] = {}
        # D8: edge-triggered declined-row latch. Key = zone_id,
        # value = (reason, wall_clock_ts). Same reason cannot re-log
        # within AC_RESET_DECLINED_MIN_INTERVAL_S. REBUILD across restart.
        self._last_declined: dict[str, tuple[str, datetime]] = {}
        # Per-zone timers — separate from _reset_timers (existing hard-reset
        # restore timers) so a soft nudge in flight doesn't get cancelled
        # by an unrelated hard-reset path on the same zone.
        self._nudge_restore_timers: dict[str, CALLBACK_TYPE] = {}
        self._nudge_eval_timers: dict[str, CALLBACK_TYPE] = {}
        # HVAC-GOVERNED-EXCURSION-1 D1: per-zone timers for the
        # delayed SETTLED-verdict re-read. Fires
        # AC_NUDGE_RESTORE_SETTLE_DELAY_S after each _restore_after_nudge
        # completes; passive read + UPDATE only, no thermostat writes.
        self._nudge_settled_timers: dict[str, CALLBACK_TYPE] = {}
        # v4.7.17.1: track restore wall-clock ISO timestamp per zone so the
        # evaluator can query recorder history over [restore_ts, eval_ts]
        # for the trailing-window minimum kW (the new effectiveness rule).
        # Pre-existing behavior: lost on HA restart (mid-eval-window nudges
        # are silently dropped from FP statistics — known gap, Tier 1 scope
        # preserves rather than fixes, per the v4.7.17.x design review).
        self._nudge_post_restore_ts: dict[str, str] = {}
        # Track which zones are currently mid-nudge for sensor exposure.
        self._nudge_in_flight: set[str] = set()
        # F5 fix-up (2026-08-22, revised): per-zone running MAX kW
        # observed since the current durability window started. Updated
        # on the existing 5-min decision tick (`check_ac_reset`, which
        # already reads kW). The truncated durability verdict reads
        # THIS INTERVAL check rather than an instantaneous fire-time
        # read — a truncation happens because Gate 7 detected high kW,
        # so an instantaneous read at that moment is above threshold
        # by construction and would score every truncated row as
        # durable=0. Set to `None` when no durability window is armed.
        # 5-minute sampling granularity is stated on the `durable`
        # column so nobody later mistakes it for continuous.
        self._nudge_running_max_kw: dict[str, float] = {}
        # A1 fix-up (2026-08-22): per-zone diagnostic cache for the
        # five A1 sensors. Refreshed by _refresh_a1_cache once per
        # decision cycle (5 min). Sensors read this dict sync. Keys
        # per zone: gate4_blind_fraction_7d, gate4_diverge_count_7d,
        # ac_reset_day_count, ac_reset_night_count,
        # ac_reset_last_outcome, durability_rate_full,
        # durability_rate_trunc, durability_sample_count.
        self._a1_zone_cache: dict[str, dict] = {}
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
            "kwh_avoided_cycle": 0.0,
            "kwh_avoided_total": 0.0,
            "false_positive_rate": None,  # None until sample_size >= 5
            "fp_sample_size": 0,
            # PLANNING_hvac_kwh_avoided_savings D2: standalone AC-ramp $ family
            # (rough estimate; NOT summed into EC energy_savings_total_*).
            # Each nudge_evaluated event's kWh_avoided valued at the TOU rate
            # captured into notes at nudge-eval time. Forward-only: pre-deploy
            # events without a captured rate contribute kWh but $0.
            "savings_today": 0.0,
            "savings_cycle": 0.0,
            "savings_lifetime": 0.0,
            "last_refresh_ts": None,
        }

        # =====================================================================
        # Arrester Operator-Immunity (2026-08-06)
        # =====================================================================
        # Person entity_ids (e.g. "person.oji_udezue") whose manual holds are
        # immune to compromise/severe/revert/AC-ramp shaving. Seeded via
        # set_immune_persons() from the HVACCoordinator on init and on
        # options-flow update. Empty list = feature dormant (fail-safe: nobody
        # is immune; original governance behavior byte-identical).
        self._immune_persons: list[str] = []

        # Per-zone active immune-hold ledger:
        #   zone_id -> {
        #       "user_id": HA user id (from event.context.user_id),
        #       "user_name": friendly, resolved from person entity attrs,
        #       "person_entity": "person.<slug>",
        #       "started_ts": datetime (when the immune hold was stamped),
        #       "next_activity_ts": Optional[datetime] (thermostat schedule
        #           boundary at stamping time; used by sunset first-of).
        #   }
        # Presence of a zone key = arrester will SKIP shave paths on that zone.
        # Sunset (durable-state / boundary / max-age) removes the key and lets
        # arrester regain jurisdiction on the next state event (governance
        # resumes; the operator's hold is NOT force-cleared — the manual
        # preset & elevated setpoint stay live until arrester re-evaluates
        # them in the normal way).
        self._immune_holds: dict[str, dict[str, Any]] = {}

        # Temp Arrester Override — house-wide suspension of ALL corrective
        # writes. Owned here (single point of truth) even though the
        # operator-facing entity is a Switch on the HVAC Coordinator device.
        # Default OFF. Deliberately NOT restored across restart (default-OFF
        # is the safe state — an accidental "leave it on" through an outage
        # should not persistently disable governance). Documented as
        # intentional inversion of the restore-off-only pattern used by the
        # other HVAC switches (which default ON and restore OFF).
        #
        # (2026-08-06 rename per operator ruling: former "Comfort Override"
        # naming; renamed to "Temp Arrester Override" because it is an
        # arrester primitive, not a comfort dial. Internal attrs / methods
        # / logs / get_stats keys use ``temp_arrester_override_*``.)
        self._temp_arrester_override_active: bool = False
        self._temp_arrester_override_started_ts: datetime | None = None
        # ARREST-SUNSET-1 MIN_LIFE deferred-sunset obligation (2026-08-07):
        # When an invalidating house-state transition arrives during the
        # MIN_LIFE grace window we DEFER (not discard) the sunset —
        # otherwise the event is lost and the override rides to max-age.
        # Pending is STICKY: a later transition into a preserving state
        # does NOT clear it (an invalidating transition already occurred).
        # Discharge happens via (a) one-shot async_call_later scheduled at
        # deferral time, OR (b) the periodic sweep at the top of
        # sunset_temp_arrester_override as a backstop for lost timers /
        # HA restart. RESTART GAP: pending flag is in-memory only; if HA
        # restarts mid-grace after a deferred invalidating transition,
        # the obligation is lost and the override survives to max-age
        # (6h). Documented, not persisted — see planning ARREST-SUNSET-1.
        self._temp_arrester_override_pending_sunset: str | None = None
        self._temp_arrester_override_pending_sunset_unsub: Any = None
        # F8 (2026-08-07 fix-up cycle-4): sunset-notify callback so the
        # timer-precise discharge path (`_pending_sunset_timer_cb`) can
        # fire the operator-facing "override ended (auto)" NM note
        # WITHOUT reaching into HVACCoordinator internals. HVACCoordinator
        # registers this at construction; sunset invokes it exactly once
        # per fire (guarded by the release branch's own idempotency, so
        # sweep + timer cannot double-notify for one engagement).
        self._on_sunset_notify: Any = None
        # OVERRIDE-NOTIFY-1 (2026-08-08): pre-warn + deferral callbacks
        # + async_call_later unsub for the pre-warn timer. Both callbacks
        # are optional (HVACCoordinator registers them at construction);
        # unregistered callbacks are silently skipped.
        self._on_expiry_warn_notify: Any = None
        self._on_defer_notify: Any = None
        self._temp_arrester_override_expiry_warn_unsub: Any = None
        # Dedup per engagement — an engagement_id ticks on every OFF→ON
        # so a stale scheduled notification cannot cross-fire against a
        # subsequent engagement.
        self._temp_arrester_override_engagement_id: int = 0
        self._last_notified_engagement_id: int = -1
        # OVERRIDE-NOTIFY-1: per-engagement dedup for the pre-warn note
        # so a re-scheduled or duplicate fire cannot double-notify.
        self._last_expiry_warned_engagement_id: int = -1

    # -------------------------------------------------------------------------
    # Arrester Operator-Immunity — public wiring (called by HVACCoordinator)
    # -------------------------------------------------------------------------

    def set_immune_persons(self, persons: list[str] | None) -> None:
        """Wire the operator-immunity person list (from options-flow).

        ``persons`` is a list of person entity ids ("person.<slug>"). Empty
        list / None disables the feature entirely (no user's holds are
        immune; original governance behavior). Called from HVACCoordinator
        init AND from options-flow update handler so live edits take effect
        without restart.
        """
        self._immune_persons = list(persons or [])
        _LOGGER.info(
            "Arrester immunity: %d person(s) configured (%s)",
            len(self._immune_persons),
            ", ".join(self._immune_persons) if self._immune_persons else "none",
        )

    def _is_immunity_context_eligible(self, ctx: Any) -> bool:
        """Voice-channel discriminator (ARRESTER_IMMUNITY_VOICE_CONTEXTS).

        When the const is True (documented escape hatch) all contexts
        pass — voice pipelines under the operator's user inherit immunity.

        When False (operator-ruled default 2026-08-06 — voice must NOT
        inherit immunity), the context is eligible only if
        ``context.parent_id is None``. Frontend/UI direct calls and
        physical thermostat dial state changes typically arrive with
        ``parent_id == None``; automation-triggered, script-triggered,
        and Assist/voice-pipeline-mediated calls carry a non-None
        ``parent_id`` (the id of the originating event/context) and are
        therefore excluded. This is a best-effort discriminator — see
        the HC manual §3.4b.4 for the operational caveat (dedicated
        HA user for voice agents is the fully-reliable enforcement).
        """
        if ARRESTER_IMMUNITY_VOICE_CONTEXTS:
            return True
        if ctx is None:
            return True
        parent_id = getattr(ctx, "parent_id", None)
        return parent_id is None

    def _parse_next_activity(self, raw: str) -> datetime | None:
        """Parse a Bryant/Carrier ``next_activity_time`` attribute.

        Accepts either:
          * ISO-8601 timestamp (e.g. "2026-08-06T18:00:00-05:00")
          * Bare "HH:MM" wall-clock in house-local time (verified live).

        For "HH:MM": construct today's local datetime; if the boundary
        has already passed (now >= boundary), roll to tomorrow — the
        thermostat's next boundary is at the next occurrence of that
        wall-clock. Garbage inputs return None (no boundary sunset).
        """
        try:
            return datetime.fromisoformat(raw)
        except (ValueError, TypeError):
            pass
        try:
            hh, mm = raw.split(":", 1)
            h = int(hh)
            m = int(mm)
            if not (0 <= h <= 23 and 0 <= m <= 59):
                return None
            now_local = dt_util.now()
            candidate = now_local.replace(
                hour=h, minute=m, second=0, microsecond=0,
            )
            if candidate <= now_local:
                candidate = candidate + timedelta(days=1)
            return candidate
        except (ValueError, TypeError, AttributeError):
            return None

    def _resolve_context_user_to_person(
        self, user_id: str | None,
    ) -> tuple[str | None, str | None]:
        """Return (person_entity_id, friendly_name) for an HA context user_id.

        Walks person.* states and matches attributes.user_id. Returns
        (None, None) if the user cannot be resolved (physical thermostat
        dial with no context user, unresolvable id, or exception).
        Fail-open direction: unresolvable → NOT immune (governance is the
        safe default). Guarded so a state-registry hiccup can never crash
        the arrester's detection path.
        """
        if not user_id:
            return None, None
        try:
            all_states = self.hass.states.async_all("person")
        except Exception as e:  # noqa: BLE001 — defensive; never crash detection
            _LOGGER.debug("Arrester immunity: person lookup failed: %s", e)
            return None, None
        for st in all_states:
            try:
                attrs = st.attributes or {}
                if attrs.get("user_id") == user_id:
                    friendly = attrs.get("friendly_name") or st.entity_id
                    return st.entity_id, friendly
            except Exception:  # noqa: BLE001
                continue
        return None, None

    def _is_hold_immune(self, zone_id: str) -> bool:
        """True iff this zone has an active immune-hold record."""
        return zone_id in self._immune_holds

    def _corrective_writes_suppressed(self, zone_id: str) -> bool:
        """Master gate consulted by EVERY corrective-write site.

        Returns True (SUPPRESS the write) when EITHER:
          * Temp Arrester Override is currently active (house-wide), OR
          * this zone has an active immune-hold record (person-scoped).

        Wire-once helper so no site can silently forget one axis. All
        shave paths (severe / normal / compromise / revert / startup
        audit / startup_ramp_audit / AC-ramp soft-nudge / AC-reset
        escalation / DPM preset-override apply) route through this gate.
        Each caller must also emit a ledger row on skip so the operator
        can see why nothing happened.

        Deliberate runtime exception: ``_restore_after_nudge`` is the
        UN-shaving path (it puts the operator's original target BACK on
        the wire after a bounded soft-nudge). It intentionally does NOT
        consult this gate — un-shaving is allowed even under
        immunity / Temp Arrester Override; the whole point of both
        features is to keep the operator's setpoint honoured, and
        _restore_after_nudge is what MAKES that true when a nudge was
        already in flight. (Documented at method site.)
        """
        return (
            self._temp_arrester_override_active
            or self._is_hold_immune(zone_id)
        )

    def _log_shave_skipped(
        self, zone_name: str, zone_id: str, path: str,
    ) -> None:
        """Structured ledger row for a suppressed shave (INFO)."""
        reason_parts: list[str] = []
        if self._temp_arrester_override_active:
            reason_parts.append("temp_arrester_override_active")
        rec = self._immune_holds.get(zone_id)
        if rec is not None:
            reason_parts.append(
                f"immune_hold user={rec.get('user_name') or 'unknown'}"
            )
        _LOGGER.info(
            "Arrester shave_skipped: zone=%s path=%s reason=%s",
            zone_name, path, "|".join(reason_parts) or "unknown",
        )

    def _stamp_immune_hold(
        self,
        zone_id: str,
        user_id: str,
        user_name: str,
        person_entity: str,
        next_activity_ts: datetime | None = None,
    ) -> None:
        """Record an active immune hold on a zone."""
        self._immune_holds[zone_id] = {
            "user_id": user_id,
            "user_name": user_name,
            "person_entity": person_entity,
            "started_ts": dt_util.now(),
            "next_activity_ts": next_activity_ts,
        }
        _LOGGER.info(
            "Arrester immunity: stamped immune hold on zone=%s by user=%s "
            "(%s); shave paths will skip until sunset",
            zone_id, user_name, person_entity,
        )

    def sunset_immune_holds(
        self, reason: str, house_state: str | None = None,
    ) -> int:
        """Expire immune-hold records whose sunset condition has fired.

        Called from HVACCoordinator on:
          * SIGNAL_HOUSE_STATE_CHANGED transitions (reason="durable_state")
          * periodic decision cycle sweep (reason="max_age_or_boundary")

        Sunset first-of (per hold):
          1. Transition INTO any house_state for which
             ``house_state_invalidates_arrester_hold`` returns True — the
             denylist source of truth (ARRESTER_HOLD_PRESERVING_STATES;
             only ``arriving``/``guest``/``waking`` preserve). Sibling
             ``sunset_temp_arrester_override`` routes through the SAME
             predicate; the previous split (this method: DURABLE_HOUSE_
             STATES set; sibling: hardcoded "sleep") was the original
             ARREST-SUNSET-1 bug — F9(a) docstring correction 2026-08-07.
          2. Thermostat next_activity_ts boundary reached.
          3. ARRESTER_IMMUNE_HOLD_MAX_S elapsed since started_ts.

        Sunset does NOT force-clear the operator's manual — it just
        removes the immunity record so the arrester regains jurisdiction
        (governance resumes normally on the next state event).

        Returns the count of records sunset this call.
        """
        if not self._immune_holds:
            return 0
        now = dt_util.now()
        expired: list[tuple[str, str]] = []  # (zone_id, sunset_reason)
        # ARREST-SUNSET-1 (2026-08-07): single source of truth — denylist
        # via house_state_invalidates_arrester_hold (only ``arriving`` and
        # ``guest`` preserve the hold). Sibling sunset_temp_arrester_override
        # routes through the same predicate; do NOT re-inline the check.
        durable_transition = (
            reason == "durable_state"
            and house_state_invalidates_arrester_hold(house_state)
        )
        for zone_id, rec in list(self._immune_holds.items()):
            # ARREST-SUNSET-1 DISCHARGE BACKSTOP (2026-08-07): on EVERY
            # invocation, first check if this record has a previously-
            # deferred pending sunset that has now aged past MIN_LIFE →
            # expire it. This is the sweep-driven discharge; no per-
            # record timer is scheduled for immune-holds (unlike the
            # single-instance Temp Arrester Override which uses
            # async_call_later). Discharge latency = sweep cadence
            # (5 min), acceptable because the max-age cap is 6 h — the
            # invariant "min-life < max-age" holds even including the
            # sweep-latency headroom.
            pending_hold = rec.get("pending_sunset_state")
            started_pending = rec.get("started_ts")
            if (
                pending_hold
                and isinstance(started_pending, datetime)
                and (now - started_pending).total_seconds()
                >= ARRESTER_OVERRIDE_MIN_LIFE_S
            ):
                expired.append(
                    (zone_id, f"durable_state->{pending_hold}(deferred)")
                )
                continue
            if durable_transition:
                # ARREST-SUNSET-1 MIN_LIFE grace (2026-08-07): the
                # transition-driven sunset is blocked while the hold is
                # younger than ARRESTER_OVERRIDE_MIN_LIFE_S. Each immune
                # record already carries started_ts (populated by
                # _stamp_immune_hold), so the grace applies uniformly
                # across arrester-family holds. On grace-block we DEFER
                # (not discard): the pending_sunset_state key is set on
                # the record (sticky — first invalidating transition
                # wins), and discharge happens via the top-of-method
                # backstop above once age >= MIN_LIFE. The independent
                # ARRESTER_IMMUNE_HOLD_MAX_S / next_activity_boundary
                # paths below remain unaffected (their branches are only
                # reached when durable_transition did NOT expire the
                # record via the grace check + continue).
                started_hold = rec.get("started_ts")
                if (
                    ARRESTER_OVERRIDE_MIN_LIFE_S > 0
                    and isinstance(started_hold, datetime)
                    and (now - started_hold).total_seconds()
                    < ARRESTER_OVERRIDE_MIN_LIFE_S
                ):
                    if rec.get("pending_sunset_state") is None:
                        rec["pending_sunset_state"] = house_state
                        _LOGGER.debug(
                            "Arrester immunity: transition into %s DEFERRED "
                            "for zone=%s — under MIN_LIFE grace (age=%.0fs, "
                            "grace=%ds); sweep will discharge",
                            house_state, zone_id,
                            (now - started_hold).total_seconds(),
                            ARRESTER_OVERRIDE_MIN_LIFE_S,
                        )
                else:
                    expired.append((zone_id, f"durable_state->{house_state}"))
                    continue
            started = rec.get("started_ts")
            if isinstance(started, datetime):
                age_s = (now - started).total_seconds()
                if (
                    ARRESTER_IMMUNE_HOLD_MAX_S > 0
                    and age_s >= ARRESTER_IMMUNE_HOLD_MAX_S
                ):
                    expired.append((zone_id, "max_age"))
                    continue
            nxt = rec.get("next_activity_ts")
            if isinstance(nxt, datetime) and now >= nxt:
                expired.append((zone_id, "next_activity_boundary"))
                continue
        for zone_id, sunset_reason in expired:
            rec = self._immune_holds.pop(zone_id, None)
            user_name = (rec or {}).get("user_name", "unknown")
            _LOGGER.info(
                "Arrester immunity: sunset zone=%s reason=%s user=%s "
                "(governance resumes; hold not force-cleared)",
                zone_id, sunset_reason, user_name,
            )
        return len(expired)

    # -------------------------------------------------------------------------
    # Temp Arrester Override — public wiring
    # -------------------------------------------------------------------------
    #
    # Attribute / method naming (2026-08-06 operator ruling): the primitive
    # is an ARRESTER override, not a comfort dial. Public method + attr +
    # log strings all read ``temp_arrester_override_*``. get_stats keys
    # match. No back-compat aliases retained — the pre-rename name never
    # shipped outside this feature branch (grep-verified).

    @property
    def temp_arrester_override_active(self) -> bool:
        """Return whether Temp Arrester Override is currently suppressing writes."""
        return self._temp_arrester_override_active

    @property
    def temp_arrester_override_started_ts(self) -> datetime | None:
        """Public accessor for the switch entity's UI attribute.

        Renamed from ``_comfort_override_started_ts`` per B-M3. Kept as a
        property so the switch can read without reaching into a private
        attr.
        """
        return self._temp_arrester_override_started_ts

    def _fire_temp_arrester_override_update(self) -> None:
        """Dispatch the dedicated switch-UI update signal (B-H2 fix).

        The HVACTempArresterOverrideSwitch subscribes at
        async_added_to_hass and calls async_write_ha_state so the switch
        card reflects engage/release/sunset within one event-loop tick
        rather than waiting for the next SIGNAL_HVAC_ENTITIES_UPDATE
        broadcast (~5 min).
        """
        try:
            async_dispatcher_send(
                self.hass, SIGNAL_HVAC_TEMP_ARRESTER_OVERRIDE_UPDATE,
            )
        except Exception as e:  # noqa: BLE001
            _LOGGER.debug(
                "Temp Arrester Override dispatcher send failed: %s", e,
            )

    def set_on_expiry_warn_notify(self, cb) -> None:
        """Register the pre-warn NM-note callback (OVERRIDE-NOTIFY-1).

        Fired once per engagement, ~ARRESTER_OVERRIDE_EXPIRY_WARN_S seconds
        before the COMFORT_OVERRIDE_MAX_S auto-release. Callback signature:
        ``cb(remaining_minutes: int) -> None`` (may be sync or return a
        coroutine — HVACCoordinator wraps it as a task).
        """
        self._on_expiry_warn_notify = cb

    def set_on_defer_notify(self, cb) -> None:
        """Register the deferral NM-note callback (OVERRIDE-NOTIFY-1).

        Fired at the moment a state-transition sunset is DEFERRED by the
        MIN_LIFE grace: transitions are not schedulable so an immediate
        "ends in ~N minutes" note is the correct analogue of a 5-min pre-
        warn. Signature: ``cb(remaining_minutes: int) -> None``.
        """
        self._on_defer_notify = cb

    def _cancel_expiry_warn_timer(self) -> None:
        """Cancel the pre-warn async_call_later, if any."""
        unsub = self._temp_arrester_override_expiry_warn_unsub
        self._temp_arrester_override_expiry_warn_unsub = None
        if unsub is None:
            return
        try:
            unsub()
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "Temp Arrester Override: expiry-warn timer unsub raised",
                exc_info=True,
            )

    @callback
    def _expiry_warn_timer_cb(self, _now: Any) -> None:
        """One-shot pre-warn callback — fires the NM note if still armed."""
        self._temp_arrester_override_expiry_warn_unsub = None
        if not self._temp_arrester_override_active:
            return
        eng_id = self._temp_arrester_override_engagement_id
        if eng_id == self._last_expiry_warned_engagement_id:
            return
        cb = self._on_expiry_warn_notify
        if cb is None:
            # F5 fix-up (2026-08-08): do NOT stamp dedup before we've
            # actually notified — otherwise an unregistered callback
            # would silently mark this engagement "warned" and no retry
            # is possible. Dedup means "warned iff notified".
            return
        self._last_expiry_warned_engagement_id = eng_id
        try:
            remaining_min = max(
                1, int(round(ARRESTER_OVERRIDE_EXPIRY_WARN_S / 60))
            )
            cb(remaining_min)
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "Temp Arrester Override: expiry-warn callback raised",
                exc_info=True,
            )

    def set_on_sunset_notify(self, cb) -> None:
        """Register a callback fired once per sunset with the reason string.

        F8 (2026-08-07 fix-up cycle-4): consolidates NM-note dispatch so
        BOTH the periodic sweep AND the timer-precise discharge path
        produce exactly one operator-facing note per engagement.
        """
        self._on_sunset_notify = cb

    def set_temp_arrester_override(self, value: bool) -> None:
        """Set Temp Arrester Override state (called by the switch).

        Turning ON stamps ``_temp_arrester_override_started_ts`` so the
        max-age sunset can fire later; turning OFF clears it. Idempotent.
        Fires the dedicated dispatcher signal so the switch UI updates
        without waiting for the coarse coordinator entities tick.
        """
        value = bool(value)
        if value == self._temp_arrester_override_active:
            return
        self._temp_arrester_override_active = value
        if value:
            # ARREST-COMFORT-1 §3.6: switch flipped ON mid-grace evicts
            # every active comfort-delay grant with expiry_reason=
            # switch_flipped_on. Subsequent OFF does NOT revive.
            self._evict_comfort_delays_for_switch_on()
            # F6 (2026-08-07 fix-up cycle-4): defensive clear on engage.
            # If a stale pending-sunset flag or timer survives (e.g. a
            # partial teardown left one dangling), we DO NOT want a
            # fresh engagement to be sunset early by a leftover discharge
            # scheduled against the previous engagement's started_ts.
            self._temp_arrester_override_pending_sunset = None
            self._cancel_pending_sunset_timer()
            # OVERRIDE-NOTIFY-1: any prior pre-warn timer from a stale
            # engagement must not carry forward into this fresh one.
            self._cancel_expiry_warn_timer()
            self._temp_arrester_override_started_ts = dt_util.now()
            self._temp_arrester_override_engagement_id += 1
            _LOGGER.info(
                "Temp Arrester Override ENGAGED — arrester corrective writes "
                "suppressed house-wide until sunset (sleep transition or "
                "%ds max-age)",
                COMFORT_OVERRIDE_MAX_S,
            )
            # OVERRIDE-NOTIFY-1: schedule the pre-warn one-shot at
            # (max_age - warn_lead). Kill-switch: warn_s == 0 disables.
            # Also skipped when warn_s >= max_age (misconfigured pair —
            # the warn would fire immediately or never, both useless).
            if (
                ARRESTER_OVERRIDE_EXPIRY_WARN_S > 0
                and COMFORT_OVERRIDE_MAX_S > ARRESTER_OVERRIDE_EXPIRY_WARN_S
            ):
                delay = (
                    COMFORT_OVERRIDE_MAX_S - ARRESTER_OVERRIDE_EXPIRY_WARN_S
                )
                try:
                    self._temp_arrester_override_expiry_warn_unsub = (
                        async_call_later(
                            self.hass, delay, self._expiry_warn_timer_cb,
                        )
                    )
                except Exception:  # noqa: BLE001
                    _LOGGER.debug(
                        "Temp Arrester Override: expiry-warn timer "
                        "schedule failed", exc_info=True,
                    )
        else:
            self._temp_arrester_override_started_ts = None
            # Clear any pending deferred-sunset obligation + timer so a
            # stale grace-window timer cannot fire against a fresh
            # engagement of the override later.
            self._temp_arrester_override_pending_sunset = None
            self._cancel_pending_sunset_timer()
            # OVERRIDE-NOTIFY-1: manual OFF must cancel the pending
            # pre-warn timer so it cannot fire against a released override.
            self._cancel_expiry_warn_timer()
            _LOGGER.info("Temp Arrester Override RELEASED")
        self._fire_temp_arrester_override_update()

    def sunset_temp_arrester_override(
        self, reason: str, house_state: str | None = None,
    ) -> bool:
        """Auto-release Temp Arrester Override on the sunset first-of.

        First-of:
          * Transition INTO any house_state for which
            ``house_state_invalidates_arrester_hold`` returns True — the
            toggle must always match reality (ARREST-SUNSET-1, 2026-08-07).
            Denylist: only ``arriving`` and ``guest`` preserve the hold;
            every other transition (including sleep/away/vacation/
            home_day/home_evening/home_night/waking) sunsets it. Sibling
            ``sunset_immune_holds`` routes through the SAME predicate —
            the previous split (this method: hardcoded "sleep"; sibling:
            DURABLE_HOUSE_STATES set) was the original bug.
          * COMFORT_OVERRIDE_MAX_S elapsed since engagement.

        Returns True iff the sunset fired this call. Caller (HVAC coord)
        is responsible for firing the LOW NM note ("Temp Arrester
        Override ended (auto)"). The switch UI update dispatcher signal
        is fired here so the card flips OFF immediately.
        """
        if not self._temp_arrester_override_active:
            return False
        now = dt_util.now()
        fire = False
        sunset_reason = ""
        # ARREST-SUNSET-1 (2026-08-07) DISCHARGE BACKSTOP: every
        # invocation (any reason) first discharges a previously-deferred
        # invalidating transition once its grace has elapsed. This
        # backstops a lost async_call_later (HA restart, timer cancel
        # race) via the periodic sweep (called every decision cycle).
        pending = self._temp_arrester_override_pending_sunset
        started_for_pending = self._temp_arrester_override_started_ts
        if (
            pending
            and isinstance(started_for_pending, datetime)
            and (now - started_for_pending).total_seconds()
            >= ARRESTER_OVERRIDE_MIN_LIFE_S
        ):
            fire = True
            # F9(b): make the deferred sunset reason explicit. The
            # PENDING state is the one that triggered the sunset (the
            # invalidating transition that arrived during MIN_LIFE
            # grace); we discharge NOW at (or after) grace expiry.
            # Suffix (deferred@discharge) distinguishes from an
            # instantaneous durable_state->X sunset in NM/logs.
            sunset_reason = f"durable_state->{pending}(deferred@discharge)"
        if not fire and (
            reason == "durable_state"
            and house_state_invalidates_arrester_hold(house_state)
        ):
            # ARREST-SUNSET-1 MIN_LIFE grace (2026-08-07): a state-
            # transition sunset cannot fire while the override is younger
            # than ARRESTER_OVERRIDE_MIN_LIFE_S. Grace does NOT block
            # the independent max-age path below (see next branch); the
            # constants are set so min-life < max-age today, but the
            # branches are ordered so max-age wins regardless.
            #
            # If grace blocks, DEFER (don't discard) — record the pending
            # sunset + schedule a one-shot timer for the remainder of the
            # grace window. Pending is STICKY: a later transition into a
            # preserving state does NOT clear it (an invalidating
            # transition already occurred).
            started = self._temp_arrester_override_started_ts
            if (
                ARRESTER_OVERRIDE_MIN_LIFE_S > 0
                and isinstance(started, datetime)
                and (now - started).total_seconds() < ARRESTER_OVERRIDE_MIN_LIFE_S
            ):
                if self._temp_arrester_override_pending_sunset is None:
                    self._temp_arrester_override_pending_sunset = house_state
                    remaining = max(
                        1.0,
                        ARRESTER_OVERRIDE_MIN_LIFE_S
                        - (now - started).total_seconds(),
                    )
                    _LOGGER.debug(
                        "Temp Arrester Override: transition into %s DEFERRED — "
                        "under MIN_LIFE grace (age=%.0fs, grace=%ds); "
                        "sunset will fire in %.0fs",
                        house_state,
                        (now - started).total_seconds(),
                        ARRESTER_OVERRIDE_MIN_LIFE_S,
                        remaining,
                    )
                    try:
                        self._cancel_pending_sunset_timer()
                        self._temp_arrester_override_pending_sunset_unsub = (
                            async_call_later(
                                self.hass,
                                remaining,
                                self._pending_sunset_timer_cb,
                            )
                        )
                    except Exception:  # noqa: BLE001 — timer best-effort; sweep backstops
                        _LOGGER.debug(
                            "Temp Arrester Override: pending-sunset timer "
                            "schedule failed — sweep will backstop",
                            exc_info=True,
                        )
                    # OVERRIDE-NOTIFY-1: immediate NM note on deferral.
                    # Transitions are NOT schedulable so the analogue of
                    # the pre-warn is an immediate "ends in ~N min" note
                    # computed from the remaining grace. Cancel the
                    # pre-warn timer — the deferral discharges BEFORE
                    # max-age so a subsequent pre-warn fire would be
                    # confusing (override already released by then).
                    self._cancel_expiry_warn_timer()
                    cb_defer = self._on_defer_notify
                    if cb_defer is not None:
                        try:
                            remaining_min = max(1, int(round(remaining / 60)))
                            cb_defer(remaining_min)
                        except Exception:  # noqa: BLE001
                            _LOGGER.debug(
                                "Temp Arrester Override: defer callback raised",
                                exc_info=True,
                            )
                else:
                    _LOGGER.debug(
                        "Temp Arrester Override: transition into %s ignored "
                        "(pending sunset already recorded for %s)",
                        house_state,
                        self._temp_arrester_override_pending_sunset,
                    )
            else:
                fire = True
                sunset_reason = f"durable_state->{house_state}"
        if not fire:
            started = self._temp_arrester_override_started_ts
            if (
                isinstance(started, datetime)
                and COMFORT_OVERRIDE_MAX_S > 0
                and (now - started).total_seconds() >= COMFORT_OVERRIDE_MAX_S
            ):
                fire = True
                sunset_reason = "max_age"
        if fire:
            _LOGGER.info(
                "Temp Arrester Override: auto-sunset (reason=%s); releasing",
                sunset_reason,
            )
            self._temp_arrester_override_active = False
            self._temp_arrester_override_started_ts = None
            # Clear any pending deferred-sunset obligation + timer.
            self._temp_arrester_override_pending_sunset = None
            self._cancel_pending_sunset_timer()
            # OVERRIDE-NOTIFY-1: cancel the pending pre-warn so it
            # cannot fire after release (all sunset paths, including
            # sweep + timer-precise discharge + max-age, converge here).
            self._cancel_expiry_warn_timer()
            self._fire_temp_arrester_override_update()
            # F8 (2026-08-07 fix-up cycle-4): notify the operator via NM
            # regardless of which path (sweep / state-change / timer)
            # discharged the override. Engagement-id dedup guarantees at
            # most one notify per engagement even if multiple sunset
            # paths race — sweep-return-value + timer-path used to be
            # able to double-fire on paper (sweep observes True, timer
            # calls sunset which observes True from a different reason).
            try:
                cb = self._on_sunset_notify
                eng_id = self._temp_arrester_override_engagement_id
                if cb is not None and eng_id != self._last_notified_engagement_id:
                    self._last_notified_engagement_id = eng_id
                    # Strip the deferred/backstop suffix for the operator
                    # message so both timer-path and sweep-path produce a
                    # comparable reason string.
                    _reason_out = sunset_reason
                    cb(_reason_out)
            except Exception:  # noqa: BLE001 — best-effort notify
                _LOGGER.debug(
                    "Temp Arrester Override: on_sunset_notify callback "
                    "raised", exc_info=True,
                )
            return True
        return False

    def _cancel_pending_sunset_timer(self) -> None:
        """Cancel the deferred-sunset async_call_later, if any."""
        unsub = self._temp_arrester_override_pending_sunset_unsub
        self._temp_arrester_override_pending_sunset_unsub = None
        if unsub is None:
            return
        try:
            unsub()
        except Exception:  # noqa: BLE001 — best-effort teardown
            _LOGGER.debug(
                "Temp Arrester Override: pending-sunset timer unsub raised",
                exc_info=True,
            )

    @callback
    def _pending_sunset_timer_cb(self, _now: Any) -> None:
        """One-shot timer callback: discharge the deferred sunset.

        Delegates to sunset_temp_arrester_override with a synthetic
        reason so the discharge-backstop branch at the top of the method
        picks it up (no duplication of the release code path). Guards
        against firing after a manual OFF cleared the pending flag.
        """
        self._temp_arrester_override_pending_sunset_unsub = None
        if not self._temp_arrester_override_active:
            return
        if self._temp_arrester_override_pending_sunset is None:
            return
        try:
            # Discharge via the sunset method's own backstop branch
            # (pending flag set + age >= MIN_LIFE → fire). The switch
            # dispatcher signal fires from the release path so the card
            # flips OFF immediately. NM "override ended (auto)" note is
            # NOT dispatched from this timer path — it rides the HVAC
            # coord's periodic sweep discharge instead. That means a
            # timer-precise discharge fires the release silently and the
            # subsequent sweep sees the already-released override. This
            # is a known small NM-quiet edge; acceptable given the
            # switch card and log INFO line both fire.
            self.sunset_temp_arrester_override(reason="min_life_discharge")
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "Temp Arrester Override: deferred-sunset discharge raised",
                exc_info=True,
            )

    async def _refresh_a1_cache(self) -> None:
        """A1 fix-up: refresh the per-zone diagnostic cache read by
        the five A1 sensors. Runs once per decision cycle.

        Bounded work per call:
          - 3 SQL queries per zone (gate4 divergence rows, last
            outcome, durability rate).
          - Each query is per-zone + windowed to 7 days.
          - No thermostat / no service call reads.

        Values written per zone into `_a1_zone_cache`:
          - gate4_blind_fraction_7d, gate4_diverge_count_7d
          - ac_reset_day_count, ac_reset_night_count
          - ac_reset_last_outcome
          - durability_rate_full, durability_rate_trunc, sample counts.
        """
        if self._db is None:
            return
        now = dt_util.now()
        _7d_ago = (now - timedelta(days=7)).isoformat()
        _window_s = 7 * 24 * 3600.0
        today = now.date().isoformat()
        session_date = self._night_session_date(now)
        for zone_id in list(self._zone_manager.zones.keys()):
            _entry: dict = {}
            # 1. Gate 4 divergence — pair edge-triggered rows to sum
            #    time in diverge state, divide by 7-day window.
            try:
                rows = await self._db.get_gate4_divergence_rows_7d(
                    zone_id, _7d_ago,
                )
            except Exception:  # noqa: BLE001
                rows = []
            diverge_time_s = 0.0
            diverge_count = 0
            _cur_diverge_start: datetime | None = None
            for ts_iso, notes in rows:
                _is_diverge = "direction=legacy" in (notes or "") and "diverge" not in (
                    notes or ""
                ) or "direction=legacy_" in (notes or "")
                # A "diverge" transition row has notes containing
                # `direction=legacy_veto_new_proceed` or
                # `direction=legacy_proceed_new_veto`; the "agree"
                # transition has `direction=agree`. Parse honestly.
                _is_diverge = (
                    "direction=legacy_veto_new_proceed" in (notes or "")
                    or "direction=legacy_proceed_new_veto" in (notes or "")
                )
                try:
                    _ts = datetime.fromisoformat(ts_iso)
                except (ValueError, TypeError):
                    continue
                if _is_diverge:
                    if _cur_diverge_start is None:
                        _cur_diverge_start = _ts
                        diverge_count += 1
                else:
                    # agree transition — closes an open diverge span
                    if _cur_diverge_start is not None:
                        diverge_time_s += (_ts - _cur_diverge_start).total_seconds()
                        _cur_diverge_start = None
            # If we ended in a diverge state, count time up to now.
            if _cur_diverge_start is not None:
                diverge_time_s += (now - _cur_diverge_start).total_seconds()
            _entry["gate4_blind_fraction_7d"] = (
                round(diverge_time_s / _window_s, 6)
                if _window_s > 0 else 0.0
            )
            _entry["gate4_diverge_count_7d"] = diverge_count

            # 2. Reset counts — read persistent state (today + session).
            try:
                _st_today = await self._db.get_ac_reset_state(zone_id, today)
                _entry["ac_reset_day_count"] = int(
                    _st_today.get("day_reset_count", 0) or 0
                )
                if session_date == today:
                    _entry["ac_reset_night_count"] = int(
                        _st_today.get("night_reset_count", 0) or 0
                    )
                else:
                    _st_sess = await self._db.get_ac_reset_state(
                        zone_id, session_date,
                    )
                    _entry["ac_reset_night_count"] = int(
                        _st_sess.get("night_reset_count", 0) or 0
                    )
            except Exception:  # noqa: BLE001
                _entry["ac_reset_day_count"] = 0
                _entry["ac_reset_night_count"] = 0

            # 3. Last outcome.
            try:
                _entry["ac_reset_last_outcome"] = (
                    await self._db.get_last_reset_outcome_for_zone(zone_id)
                )
            except Exception:  # noqa: BLE001
                _entry["ac_reset_last_outcome"] = None

            # 4. Durability rate — full and truncated kept SEPARATE
            #    per operator directive (do not re-flatten F5's
            #    truncated-vs-full distinction).
            try:
                _fo, _ft, _to, _tt = (
                    await self._db.get_durability_rate_for_zone(
                        zone_id, _7d_ago,
                    )
                )
            except Exception:  # noqa: BLE001
                _fo = _ft = _to = _tt = 0
            _entry["durability_rate_full"] = (
                round(_fo / _ft, 4) if _ft > 0 else None
            )
            _entry["durability_rate_trunc"] = (
                round(_to / _tt, 4) if _tt > 0 else None
            )
            _entry["durability_full_sample_size"] = _ft
            _entry["durability_trunc_sample_size"] = _tt

            self._a1_zone_cache[zone_id] = _entry

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
            # Anchor "today" to LOCAL MIDNIGHT (not now-24h rolling) so the
            # sensor is a true daily accumulator: monotonic non-decreasing
            # across the day, resets cleanly at 00:00 local. state_class
            # total_increasing depends on this — a rolling 24h sum would
            # decrease as events age out and corrupt HA long-term stats.
            # Restart behavior: not persisted in RAM; re-derived from DB rows
            # (same pattern as sibling `nudges_today`/`resets_today` which
            # read per-date rows). ac_ramp_events survives restart.
            local_midnight = dt_util.start_of_local_day()
            (
                kwh_avoided_today,
                evals_today,
                fp_today,
            ) = await self._db.get_ac_ramp_kwh_avoided(since=local_midnight)
            (
                kwh_avoided_total,
                evals_total,
                fp_total,
            ) = await self._db.get_ac_ramp_kwh_avoided(days=None)

            # PLANNING_hvac_kwh_avoided_savings D1: billing-cycle kWh scope.
            # Route through EC's PUBLIC accessor `get_billing_cycle_start`
            # (Review B M1: no more private `_billing._get_cycle_start` reach —
            # Bug Class #55). Fallback to local midnight so the sensor still
            # populates (cycle >= today invariant preserved as equality)
            # rather than sitting at 0 forever.
            cycle_start_dt = None
            cycle_start_source = "fallback"
            try:
                mgr = self.hass.data.get("universal_room_automation", {}).get(
                    "coordinator_manager"
                )
                ec = None
                if mgr is not None and hasattr(mgr, "coordinators"):
                    ec = mgr.coordinators.get("energy")
                if ec is not None and hasattr(ec, "get_billing_cycle_start"):
                    cycle_start_date = ec.get_billing_cycle_start(dt_util.now())
                    if cycle_start_date is not None:
                        # DAO expects a datetime; anchor at local midnight of
                        # the cycle-start date (DST-safe via dt_util idiom —
                        # Review B L2 / Bug Class #7).
                        cycle_start_dt = dt_util.start_of_local_day(
                            cycle_start_date
                        )
                        cycle_start_source = "ec"
            except Exception as e:
                _LOGGER.debug(
                    "AC ramp cycle-start resolution failed (falling back to "
                    "local midnight for cycle scope): %s", e,
                )
            if cycle_start_dt is None:
                cycle_start_dt = local_midnight
                # Once-per-refresh INFO so a degraded EC-lookup is visible in
                # logs, not silently masked (Review B L1: observability).
                _LOGGER.info(
                    "AC ramp cycle-start using local-midnight fallback "
                    "(EC billing cycle not resolvable this refresh)"
                )
            self._cycle_start_source = cycle_start_source
            (
                kwh_avoided_cycle,
                _evals_cycle,
                _fp_cycle,
            ) = await self._db.get_ac_ramp_kwh_avoided(since=cycle_start_dt)

            # PLANNING_hvac_kwh_avoided_savings D2: $ savings family (rough
            # estimate; NOT summed into EC energy_savings_total_*).
            savings_today, _n_t = await self._db.get_ac_ramp_savings(
                since=local_midnight,
            )
            savings_cycle, _n_c = await self._db.get_ac_ramp_savings(
                since=cycle_start_dt,
            )
            savings_lifetime, _n_l = await self._db.get_ac_ramp_savings(
                days=None,
            )

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
                "kwh_avoided_cycle": round(kwh_avoided_cycle, 3),
                "kwh_avoided_total": round(kwh_avoided_total, 3),
                "false_positive_rate": fp_rate,
                "fp_sample_size": evals_total,
                "savings_today": round(savings_today, 4),
                "savings_cycle": round(savings_cycle, 4),
                "savings_lifetime": round(savings_lifetime, 4),
                "cycle_start_source": cycle_start_source,
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

    # =========================================================================
    # AC-RAMP-PIPELINE-HARDENING-1 — new live-tunable setters
    # Called by Number/Select entities on operator change AND by the CM
    # options-flow listener on options-flow save (form-path). All are
    # write-through-only — no side effects on in-flight nudges.
    # =========================================================================

    def set_gate4_predicate_mode(self, value: str) -> None:
        """Select values: legacy | shadow | live. Kill-switch = legacy."""
        v = str(value).lower()
        if v not in HVAC_AC_GATE4_MODES:
            _LOGGER.warning("Rejecting invalid gate4_predicate_mode: %r", v)
            return
        self._gate4_predicate_mode = v
        _LOGGER.info("Gate4 predicate mode -> %s", v)

    def set_durability_window(self, value: int) -> None:
        self._durability_window_min = max(1, int(value))

    def set_soft_nudge_daily_limit(self, value: int) -> None:
        self._soft_nudge_daily_limit = max(0, int(value))

    def set_reset_day_budget(self, value: int) -> None:
        self._reset_day_budget = max(0, int(value))

    def set_reset_night_budget(self, value: int) -> None:
        self._reset_night_budget = max(0, int(value))

    def set_night_start_hhmm(self, value: str) -> None:
        self._night_start_hhmm = str(value)

    def set_night_end_hhmm(self, value: str) -> None:
        self._night_end_hhmm = str(value)

    def set_ac_reset_off_duration(self, value: int) -> None:
        # Range guard mirrors the Number entity (30-300).
        v = int(value)
        if v < 30 or v > 300:
            _LOGGER.warning("Rejecting out-of-range ac_reset_off_duration=%s", v)
            return
        self._ac_reset_off_duration_s = v

    # -------------------------------------------------------------------------
    # D-GATE4 — draw-based Gate 4 predicate + shadow divergence latch
    # -------------------------------------------------------------------------

    def _zone_is_actively_cooling(self, zone, now: datetime) -> bool:
        """Return True iff the zone is *actually* cooling right now.

        Trust ladder (see plan §3-D-GATE4):
          1. CONFIG guard on `zone.hvac_mode` — must be a cooling-capable
             config. Frozen `""` (pre-first-poll) and stale `unavailable`
             are fail-closed. Basis: `hvac_mode` is the same-poll sibling
             of `hvac_action` but its underlying value only changes on
             seasonal operator action, so a frozen last-known value is
             overwhelmingly likely to be correct; `hvac_action` changes
             tick-to-tick and its frozen value is a lie about now.
          2. SPAN draw via `_read_kwh_rate` — inherits its 10-min
             staleness gate and W→kW unit-normalisation. Fail-closed on
             None (stale, unknown, unavailable, unparseable).
          3. Optional blower_rpm CORROBORATION (not a veto). If step 2
             passes, corroboration is not required. If step 2 fails,
             blower cannot rescue.

        NOTE (safety): safe under `heat_cool` in this deployment because
        heating is gas-fired; the AC circuit draw cannot rise during a
        heating cycle (measured 2026-01-10 → 2026-01-25: zero
        simultaneous furnace-draw + AC-draw hours across 360 h). A
        future change to heat-pump heating REOPENS this concern.
        """
        # Step 1: hvac_mode config guard (frozen-tolerant, fail-closed).
        mode = (
            (zone.hvac_mode or "") if isinstance(zone.hvac_mode, str)
            else ""
        )
        if mode not in ("cool", "heat_cool", "auto"):
            return False

        # Step 2: SPAN draw (fail-closed on None — stale = not trusted).
        # F10 fix-up (2026-08-22): pass warn=False so the shadow-mode
        # per-tick predicate does not consume the 6-hour stale-warning
        # rate-limit token on ticks the legacy Gate 4 would have
        # skipped (legacy uses cloud hvac_action, never touches the
        # SPAN sensor). Without this, shadow suppresses the real
        # Gate-7 stale-SPAN warning for 6h whenever the SPAN sensor
        # goes stale.
        try:
            kw = self._read_kwh_rate(zone, now, warn=False)
        except Exception:  # noqa: BLE001 — defensive
            return False
        if kw is None:
            return False
        if kw < AC_ACTIVELY_COOLING_KW_MIN:
            return False
        return True

    def _gate4_legacy_predicate(self, zone) -> bool:
        """Original cloud-reported Gate 4 body (kept live under legacy /
        shadow modes)."""
        return zone.hvac_action == "cooling"

    def _maybe_write_gate4_divergence(
        self, zone_id: str, legacy_ok: bool, new_ok: bool,
    ) -> None:
        """LATCHED writer: one row per agree↔diverge transition per
        zone. See plan B-H7 — a per-tick writer would burn 50-100
        rows/day of blind-episode noise into ac_ramp_events.
        """
        prev = self._gate4_divergence_state.get(zone_id)
        current = "agree" if legacy_ok == new_ok else "diverge"
        if prev == current:
            return
        # First observation (None -> agree|diverge) establishes the
        # latch WITHOUT writing — otherwise every boot burns a row per
        # zone. Transitions AFTER establishment write one row.
        self._gate4_divergence_state[zone_id] = current
        if prev is None:
            return
        if self._db is None:
            return
        if current == "diverge":
            direction = (
                "legacy_veto_new_proceed" if (not legacy_ok and new_ok)
                else "legacy_proceed_new_veto"
            )
            notes = f"direction={direction};legacy={int(legacy_ok)};new={int(new_ok)}"
        else:
            notes = "direction=agree"
        # F20 fix-up (2026-08-22): track this background task so it
        # doesn't dangle if teardown fires before it completes, and so
        # a runaway can be observed rather than silently swallowed.
        _task = self.hass.async_create_task(
            self._db.log_ac_ramp_event(
                zone_id=zone_id,
                event_type=AC_RAMP_EVENT_GATE4_DIVERGENCE_SHADOW,
                notes=notes,
            )
        )
        if not hasattr(self, "_gate4_divergence_tasks"):
            self._gate4_divergence_tasks = set()
        self._gate4_divergence_tasks.add(_task)
        _task.add_done_callback(self._gate4_divergence_tasks.discard)

    def _gate4_is_ok(self, zone, now: datetime) -> bool:
        """Return the Gate-4 verdict per the currently-selected mode.

        - legacy: cloud-reported hvac_action ONLY.
        - shadow: cloud-reported decides; new predicate computed and
          logged on transition (byte-identical decision to legacy).
        - live: new predicate decides.
        """
        mode = self._gate4_predicate_mode
        legacy_ok = self._gate4_legacy_predicate(zone)
        if mode == HVAC_AC_GATE4_MODE_LEGACY:
            return legacy_ok
        # Compute new predicate for both shadow and live.
        new_ok = self._zone_is_actively_cooling(zone, now)
        if mode == HVAC_AC_GATE4_MODE_SHADOW:
            self._maybe_write_gate4_divergence(
                zone.zone_id, legacy_ok, new_ok,
            )
            return legacy_ok
        # live
        return new_ok

    # -------------------------------------------------------------------------
    # D-PARTITION — day/night helpers + partition check + declined writer
    # -------------------------------------------------------------------------

    def _parse_hhmm(self, raw: str) -> tuple[int, int] | None:
        try:
            hh, mm = str(raw).split(":", 1)
            h, m = int(hh), int(mm)
            if not (0 <= h <= 23 and 0 <= m <= 59):
                return None
            return h, m
        except Exception:  # noqa: BLE001
            return None

    def _is_night_now(self, now: datetime) -> bool:
        """Wrap-around wall-clock helper. Fail-CLOSED to day on garbage
        (day is the smaller budget in the operator's ruling)."""
        start = self._parse_hhmm(self._night_start_hhmm)
        end = self._parse_hhmm(self._night_end_hhmm)
        if start is None or end is None:
            return False
        start_min = start[0] * 60 + start[1]
        end_min = end[0] * 60 + end[1]
        now_min = now.hour * 60 + now.minute
        if start_min == end_min:
            return False
        if start_min > end_min:
            # Wrap-around (e.g. 22:00 -> 06:00)
            return now_min >= start_min or now_min < end_min
        return start_min <= now_min < end_min

    def _night_session_date(self, now: datetime) -> str:
        """The night bucket key. A reset at 23:30 (D) and 00:30 (D+1)
        must charge the SAME night row — otherwise `night_budget=1`
        fires twice around midnight because the second reset reads a
        fresh row. Rule: night session = `now.date()` if
        `now.time() >= night_end` else `now.date() - 1`.
        """
        end = self._parse_hhmm(self._night_end_hhmm)
        if end is None:
            return now.date().isoformat()
        end_min = end[0] * 60 + end[1]
        now_min = now.hour * 60 + now.minute
        if now_min >= end_min:
            return now.date().isoformat()
        return (now.date() - timedelta(days=1)).isoformat()

    async def _maybe_write_declined(
        self, zone_id: str, reason: str, now: datetime,
    ) -> None:
        """D8: edge-triggered `hard_reset_declined` row writer. Same
        (zone_id, reason) cannot re-log within
        AC_RESET_DECLINED_MIN_INTERVAL_S — the v4.7.33 write-flood
        incident forbids level-triggered ledger writes."""
        if self._db is None:
            return
        prev = self._last_declined.get(zone_id)
        if prev is not None:
            prev_reason, prev_ts = prev
            if prev_reason == reason:
                try:
                    age = (now - prev_ts).total_seconds()
                except Exception:  # noqa: BLE001
                    age = AC_RESET_DECLINED_MIN_INTERVAL_S + 1
                if age < AC_RESET_DECLINED_MIN_INTERVAL_S:
                    return
        self._last_declined[zone_id] = (reason, now)
        try:
            await self._db.log_ac_ramp_event(
                zone_id=zone_id,
                event_type=AC_RAMP_EVENT_HARD_RESET_DECLINED,
                notes=f"reason={reason}",
            )
        except Exception as _e:  # noqa: BLE001 — defensive
            _LOGGER.debug("declined-row write failed for %s: %s",
                          zone_id, _e)

    def _gate_partition_check(
        self, zone_id: str, now: datetime, state: dict,
        night_state: dict | None = None,
    ) -> tuple[bool, str, str]:
        """A-C2 fix. Runs BEFORE Gate A inside
        `_perform_hard_reset_escalation`. Returns
        `(ok, partition_name, reason)`. On denial the caller writes a
        `hard_reset_declined` row and returns WITHOUT engaging lockout —
        lockout is reserved for the ineffective-nudge classifier verdict
        AND the true-cap fallback, never for a partition-only denial.

        F1 (fix-up 2026-08-22): night counters live in a row keyed by
        SESSION-DATE, not calendar date. `state` is the row keyed by
        today; `night_state` is the row keyed by the current night's
        session_date (which equals today for the pre-midnight leg of a
        session). When `night_state` is None (legacy caller / day-only
        decision) we fall back to reading night columns from `state` —
        which yields the pre-fix behaviour but only during the
        pre-midnight leg. Post-midnight, the correct night counter now
        addresses the prior-day's session row via `night_state`, so a
        reset at 22:10 and again at 00:35 charge the SAME night bucket.
        """
        is_night = self._is_night_now(now)
        partition = "night" if is_night else "day"
        if partition == "night":
            session_date = self._night_session_date(now)
            night_row = night_state if night_state is not None else state
            # Auto-reconcile the persisted `night_session_date` on the
            # night row (guards a fresh row that just came back with 0).
            if night_row.get("night_session_date") != session_date:
                night_row["night_session_date"] = session_date
                night_row["night_reset_count"] = 0
            budget = int(self._reset_night_budget)
            used = int(night_row.get("night_reset_count", 0) or 0)
            reason = AC_RESET_DECLINED_NIGHT_BUDGET
        else:
            # Day bucket keys on `state["date"]` (today). If the row is
            # from a prior day, the day counter should read 0 (the
            # today-only read guarantees that).
            budget = int(self._reset_day_budget)
            used = int(state.get("day_reset_count", 0) or 0)
            reason = AC_RESET_DECLINED_DAY_BUDGET
        if used >= budget:
            return False, partition, reason
        return True, partition, ""

    def _increment_partition_counter(
        self, state: dict, now: datetime,
        night_state: dict | None = None,
    ) -> str:
        """Increment the partition counter matching `now` and return the
        partition name. Called BEFORE `_perform_ac_reset` so a failed
        off-call still charges budget (fail-closed compressor
        protection).

        F1 (fix-up): if `night_state` is provided, the night counter is
        incremented on that (session-keyed) row rather than `state`.
        Caller is responsible for persisting whichever row(s) it
        actually modified (see `_perform_hard_reset_escalation`).
        """
        is_night = self._is_night_now(now)
        if is_night:
            session_date = self._night_session_date(now)
            night_row = night_state if night_state is not None else state
            night_row["night_session_date"] = session_date
            night_row["night_reset_count"] = (
                int(night_row.get("night_reset_count", 0) or 0) + 1
            )
            return "night"
        state["day_reset_count"] = int(state.get("day_reset_count", 0) or 0) + 1
        return "day"

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
            # Arrester Operator-Immunity: an active immune hold survives
            # restart in the sense that the manual preset survives (it is
            # persisted on the thermostat itself). The in-memory immune
            # record does NOT survive restart. Startup audit intentionally
            # falls through to governance for those holds — the operator
            # can re-establish immunity on their next manual touch. Comfort
            # Override never survives restart by design (default-OFF).
            if self._corrective_writes_suppressed(zone.zone_id):
                self._log_shave_skipped(
                    zone.zone_name, zone.zone_id, "startup_audit",
                )
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
        # HVAC-GOVERNED-EXCURSION-1 D1: cancel-safe teardown of
        # delayed settled-verdict timers.
        for cancel in self._nudge_settled_timers.values():
            cancel()
        self._nudge_settled_timers.clear()
        # AC-RAMP-PIPELINE-HARDENING-1: cancel-safe teardown for the
        # D-SCORE durability timers and the D6 reset-outcome timers.
        # In-flight callbacks are DROPPED (no write) — the row lives on
        # disk with the column NULL, correctly attributed as "measurement
        # lost across restart" per plan §9.
        for cancel in self._durable_timers.values():
            try:
                cancel()
            except Exception:  # noqa: BLE001
                pass
        self._durable_timers.clear()
        self._durable_pending.clear()
        # F5 (revised): clear the running-max tracker on teardown so a
        # torn-down arrester doesn't leak stale window state on next
        # setup.
        if hasattr(self, "_nudge_running_max_kw"):
            self._nudge_running_max_kw.clear()
        for cancel in self._reset_outcome_timers.values():
            try:
                cancel()
            except Exception:  # noqa: BLE001
                pass
        self._reset_outcome_timers.clear()
        # F6 fix-up: teardown for the second (kW) settle timer registry.
        if hasattr(self, "_reset_outcome_kw_timers"):
            for cancel in self._reset_outcome_kw_timers.values():
                try:
                    cancel()
                except Exception:  # noqa: BLE001
                    pass
            self._reset_outcome_kw_timers.clear()
        self._reset_outcome_pending.clear()
        self._nudge_in_flight.clear()

        # F12 fix-up (2026-08-22): clear the hard-reset completed event
        # id stash — every other new dict is cleared on teardown, this
        # one was missed.
        if hasattr(self, "_hard_reset_completed_event_ids"):
            self._hard_reset_completed_event_ids.clear()
        # F20 fix-up: cancel any in-flight background divergence-log
        # tasks so a torn-down arrester doesn't leak them.
        if hasattr(self, "_gate4_divergence_tasks"):
            for _t in list(self._gate4_divergence_tasks):
                try:
                    _t.cancel()
                except Exception:  # noqa: BLE001
                    pass
            self._gate4_divergence_tasks.clear()

        # F5 (2026-08-07 fix-up cycle-4): cancel any pending deferred-
        # sunset async_call_later so a late-fire cannot land on a torn-
        # down arrester. Also clear the pending flag and force-release
        # the override so a racing callback that beats the unsub is a
        # no-op (its `_temp_arrester_override_active` guard trips).
        try:
            self._cancel_pending_sunset_timer()
        except Exception:  # noqa: BLE001
            pass
        # OVERRIDE-NOTIFY-1: same discipline for the pre-warn timer.
        try:
            self._cancel_expiry_warn_timer()
        except Exception:  # noqa: BLE001
            pass
        self._temp_arrester_override_pending_sunset = None
        self._temp_arrester_override_active = False

    def update_energy_state(
        self,
        offset: float,
        coast: bool,
        *,
        battery_soc: float | None = None,
        battery_blind: bool = False,
        shed_active: bool = False,
    ) -> None:
        """Update energy constraint state for tolerance adjustment.

        ARREST-COMFORT-1 Cycle A (2026-08-10): also feeds the comfort-delay
        grant-time SOC contract (§3.3). SOC + blind + shed_active are the
        SAME values that HVACCoordinator exposes for the D3 coast-precedence
        guard at hvac.py:1445 — a single accessor discipline (planning §8).
        """
        self._energy_offset = offset
        self._energy_coast = coast
        self._battery_soc = battery_soc
        self._battery_blind = bool(battery_blind)
        self._shed_active = bool(shed_active)

    # ------------------------------------------------------------------
    # ARREST-COMFORT-1 Cycle A — comfort-delay grace (2026-08-10)
    # ------------------------------------------------------------------
    def comfort_delay_active(self, zone_id: str) -> bool:
        """Pure boolean — is a comfort-delay grant currently in force for
        the given zone?

        Definition (§3.3): grant timer is alive AND the zone is still
        occupied AND the Temp Arrester Override switch is not engaged.
        SOC is NOT re-read here — it was evaluated exactly ONCE at grant
        (H2 contract). This method is the single consultation site used
        by BOTH the D3 coast-precedence guard (hvac.py:1445) AND every
        S1-S9 write-site gate (§3.7). One mutation to this method must
        redden BOTH the D1 grant test AND the D3 defer test — that is
        the C-mutation invariant enforced by the test suite.
        """
        if zone_id not in self._comfort_delay_timers:
            return False
        if self._temp_arrester_override_active:
            return False
        # Occupancy re-check via LIVE any_room_occupied (fix-up A-CRIT-1):
        # zone_persons is the STATIC CONFIG list of person entities — it is
        # non-empty on any zone that has residents configured, so the
        # pre-fix predicate never observed "zone became unoccupied". The
        # authoritative live-occupancy signal is `zone.any_room_occupied`,
        # which reflects the rooms-in-the-zone occupied booleans in
        # real-time. Fail-closed: missing / None / accessor error → False.
        # This revives §3.6 exit-ii: a zone that emptied mid-grace makes
        # comfort_delay_active False on the very next evaluation.
        # Fix-up A-LOW-1: when we detect zone-unoccupied here, evict the
        # timer + log expiry_reason="zone_unoccupied" so the ledger row
        # fires (previously unreachable because the check used
        # zone_persons which never emptied).
        zone = self._zone_manager.zones.get(zone_id) if self._zone_manager else None
        try:
            occupied = bool(getattr(zone, "any_room_occupied", False)) if zone is not None else False
        except Exception:  # noqa: BLE001 — defensive
            occupied = False
        if not occupied:
            try:
                self._expire_comfort_delay(zone_id, reason="zone_unoccupied")
            except Exception:  # noqa: BLE001 — never let logging block the read
                _LOGGER.debug(
                    "comfort_delay_active zone-unoccupied eviction failed",
                    exc_info=True,
                )
            return False
        return True

    # ------------------------------------------------------------------
    # ARREST-COMFORT-1 fix-up A-HIGH-1 — rung-3 live knobs (2026-08-10).
    # ------------------------------------------------------------------
    def _get_grace_min(self) -> int:
        """Live-knob accessor. Falls back to module constant when the
        Number entity has not yet pushed a value (pre-CM-init boot, or
        bare-arrester test constructions)."""
        return int(
            self._comfort_grace_min
            if self._comfort_grace_min is not None
            else COMFORT_GRACE_MIN
        )

    def _get_soc_floor(self) -> int:
        """Live-knob accessor for the SOC-floor gate."""
        return int(
            self._comfort_soc_floor_pct
            if self._comfort_soc_floor_pct is not None
            else COMFORT_SOC_FLOOR_PCT
        )

    def set_comfort_grace_min(self, value: int) -> None:
        """Number-entity setter for the comfort-delay grace duration.
        `0` = feature disabled (predicate falls through to standard arrest).
        """
        try:
            v = int(value)
        except (TypeError, ValueError):
            _LOGGER.warning(
                "set_comfort_grace_min: ignoring non-int value %r", value,
            )
            return
        self._comfort_grace_min = v
        _LOGGER.info("Comfort-delay grace set to %d min (rung-3 knob)", v)

    def set_comfort_soc_floor_pct(self, value: int) -> None:
        """Number-entity setter for the comfort-delay SOC floor. `0` =
        SOC gate disabled (grants regardless of battery — deliberate
        blackout-risk acceptance). Fix-up C-H2 boot-WARN: evaluate the
        live value here so ANY change into the 0<v<20 danger band fires
        the WARN, and CM setup fires it once at boot when seeding.
        """
        try:
            v = int(value)
        except (TypeError, ValueError):
            _LOGGER.warning(
                "set_comfort_soc_floor_pct: ignoring non-int value %r", value,
            )
            return
        self._comfort_soc_floor_pct = v
        if 0 < v < 20:
            _LOGGER.warning(
                "ARREST-COMFORT-1: SOC floor set to %d%% (below 20%%) — "
                "comfort-delay grants risk battery drain to blackout during "
                "extended manuals. Deliberate operator override; audit if "
                "unintended.", v,
            )
        else:
            _LOGGER.info(
                "Comfort-delay SOC floor set to %d%% (rung-3 knob)", v,
            )

    def _is_genuine_manual(self, event: Any, entity_id: str) -> bool:
        """Return True iff the state-change event should be treated as a
        genuine user manual override — i.e. it survives the
        SUPPRESS_TTL_SECONDS induced-manual filter.

        Extracted from `_handle_climate_change` (rev-2 L1) as the single
        testable predicate. The extraction is BEHAVIOR-PRESERVING; the
        original inline block still consumes the same suppress dicts +
        early-return conditions, now via this helper. Note: this helper
        also PERFORMS the suppression cleanup (dict.pop) as a side effect
        when a genuine-manual passthrough occurs mid-window — preserving
        the pre-extraction sequence exactly.
        """
        try:
            new_state = event.data.get("new_state")
            old_state = event.data.get("old_state")
        except Exception:  # noqa: BLE001
            return False
        if new_state is None or old_state is None:
            return False

        until = self._suppressed_until.get(entity_id)
        if until is None:
            return True
        try:
            now = dt_util.now()
        except Exception:  # noqa: BLE001
            return True
        if now >= until:
            # TTL window expired — clean up + treat as genuine.
            self._suppressed_until.pop(entity_id, None)
            self._suppress_kind.pop(entity_id, None)
            return True

        # In-window: only a fresh preset transition INTO "manual" is a
        # genuine mid-window candidate (URA never writes manual).
        new_preset_mid = new_state.attributes.get("preset_mode", "") if hasattr(new_state, "attributes") else ""
        old_preset_mid = old_state.attributes.get("preset_mode", "") if hasattr(old_state, "attributes") else ""
        if not (new_preset_mid == "manual" and old_preset_mid != "manual"):
            return False
        # FIX B1 preserved: "temp" suppression classifies the induced
        # manual as a side effect of a URA temp write — NOT genuine.
        if self._suppress_kind.get(entity_id) == "temp":
            return False
        # Genuine mid-window override — clear suppression and let the
        # caller fall through to normal detection.
        self._suppressed_until.pop(entity_id, None)
        self._suppress_kind.pop(entity_id, None)
        return True

    def _comfort_request_qualifies(
        self, entity_id: str, event: Any, zone: ZoneState,
    ) -> tuple[bool, dict[str, Any] | None]:
        """Evaluate the D1 predicate (§3.2). Fail-closed on every None.

        Returns (True, meta) if the change is a comfort-qualified manual
        (per-hvac_mode leg analysis + freshness + delta threshold +
        occupancy). ``meta`` carries fields for ledger + eviction.
        Returns (False, None) otherwise. Reads current_temperature from
        the specific entity's new_state.
        """
        try:
            new_state = event.data.get("new_state")
            old_state = event.data.get("old_state")
        except Exception:  # noqa: BLE001
            return False, None
        if new_state is None or old_state is None:
            return False, None

        # (c) occupied at the instant of the change. Fix-up A-CRIT-1:
        # use LIVE any_room_occupied (rooms actually occupied right now),
        # NOT zone_persons (static config list of configured residents,
        # which is non-empty for any zone that has residents at all).
        # Fail-closed on missing / None.
        try:
            occupied = bool(getattr(zone, "any_room_occupied", False))
        except Exception:  # noqa: BLE001
            return False, None
        if not occupied:
            return False, None

        # hvac_mode = the new state's `state` (climate entity's mode).
        hvac_mode = getattr(new_state, "state", "") or ""
        if hvac_mode not in ("cool", "heat", "heat_cool"):
            return False, None  # off / unavailable / unknown → fail closed

        na = getattr(new_state, "attributes", {}) or {}
        oa = getattr(old_state, "attributes", {}) or {}

        # Freshness of current_temperature.
        current_temp = na.get("current_temperature")
        if current_temp is None:
            return False, None
        try:
            current_temp = float(current_temp)
        except (TypeError, ValueError):
            return False, None
        # Age bound — if COMFORT_TEMP_MAX_AGE_S == 0, kill switch: fail
        # closed always. Fix-up A-LOW-2: `last_updated is None` MUST fail
        # closed (we cannot prove freshness without a timestamp). Fix-up
        # A-LOW-3: dt_util always exposes utcnow() in HA — the historical
        # hasattr guard is dead code, removed.
        try:
            last_updated = getattr(new_state, "last_updated", None)
            if COMFORT_TEMP_MAX_AGE_S == 0:
                return False, None
            if last_updated is None:
                return False, None
            now_utc = dt_util.utcnow()
            age_s = (now_utc - last_updated).total_seconds()
            if age_s > COMFORT_TEMP_MAX_AGE_S:
                return False, None
        except Exception:  # noqa: BLE001
            return False, None

        qualifies = False
        delta_f = 0.0
        direction = ""
        granted_setpoint: float | tuple[float, float] | None = None
        if hvac_mode == "cool":
            new_sp = na.get("temperature")
            old_sp = oa.get("temperature")
            if new_sp is None or old_sp is None:
                return False, None
            try:
                new_sp = float(new_sp); old_sp = float(old_sp)
            except (TypeError, ValueError):
                return False, None
            qualifies = (new_sp < old_sp) and (current_temp > new_sp)
            delta_f = abs(new_sp - old_sp)
            direction = "cooler"
            granted_setpoint = new_sp
        elif hvac_mode == "heat":
            new_sp = na.get("temperature")
            old_sp = oa.get("temperature")
            if new_sp is None or old_sp is None:
                return False, None
            try:
                new_sp = float(new_sp); old_sp = float(old_sp)
            except (TypeError, ValueError):
                return False, None
            qualifies = (new_sp > old_sp) and (current_temp < new_sp)
            delta_f = abs(new_sp - old_sp)
            direction = "warmer"
            granted_setpoint = new_sp
        else:  # heat_cool
            new_high = na.get("target_temp_high")
            new_low = na.get("target_temp_low")
            old_high = oa.get("target_temp_high")
            old_low = oa.get("target_temp_low")
            if None in (new_high, new_low, old_high, old_low):
                return False, None
            try:
                new_high = float(new_high); new_low = float(new_low)
                old_high = float(old_high); old_low = float(old_low)
            except (TypeError, ValueError):
                return False, None
            # Relevant leg per current_temp position vs new range.
            if current_temp > new_high:
                # cool leg is relevant
                qualifies = (new_high < old_high) and (new_high < current_temp)
                delta_f = abs(new_high - old_high)
                direction = "cooler"
                granted_setpoint = (new_low, new_high)
            elif current_temp < new_low:
                # heat leg is relevant
                qualifies = (new_low > old_low) and (new_low > current_temp)
                delta_f = abs(new_low - old_low)
                direction = "warmer"
                granted_setpoint = (new_low, new_high)
            else:
                # inside the new deadband — no comfort-relevant leg
                return False, None

        if not qualifies:
            return False, None
        if delta_f < COMFORT_DELTA_MIN_F:
            return False, None

        return True, {
            "zone_id": zone.zone_id,
            "climate_entity_id": entity_id,
            "hvac_mode": hvac_mode,
            "current_temp": current_temp,
            "delta_f": delta_f,
            "direction": direction,
            "granted_setpoint": granted_setpoint,
        }

    def _seed_comfort_delay(
        self, zone: ZoneState, meta: dict[str, Any],
    ) -> None:
        """Attach a grace timer + record ledger `comfort_delay_started`.

        Grant key is zone_id alone (audit §metric 4 simplification).
        Kill-switch: if COMFORT_GRACE_MIN <= 0 the caller has already
        filtered — no timer scheduled.
        """
        zone_id = zone.zone_id
        # Cancel any existing timer for this zone (fresh manual overrides
        # a stale grace — the operator just spoke).
        existing = self._comfort_delay_timers.pop(zone_id, None)
        if existing is not None:
            try:
                existing()
            except Exception:  # noqa: BLE001
                pass
        grace_s = int(self._get_grace_min()) * 60
        soc_at_grant = self._battery_soc
        meta = dict(meta)
        meta["soc_at_grant"] = soc_at_grant
        meta["grace_s"] = grace_s
        try:
            meta["started_ts"] = dt_util.now()
        except Exception:  # noqa: BLE001
            meta["started_ts"] = None
        self._comfort_delay_meta[zone_id] = meta

        @callback
        def _on_grace_expiry(_now):
            self._expire_comfort_delay(zone_id, reason="timer")

        self._comfort_delay_timers[zone_id] = async_call_later(
            self.hass, grace_s, _on_grace_expiry,
        )

        _LOGGER.info(
            "ARREST-COMFORT-1: comfort_delay_started zone=%s entity=%s "
            "delta=%.1fF direction=%s current=%.1f grace=%ds soc=%s",
            zone_id, meta.get("climate_entity_id"), meta.get("delta_f", 0.0),
            meta.get("direction"), meta.get("current_temp", 0.0), grace_s,
            soc_at_grant,
        )
        self._log_comfort_ledger("comfort_delay_started", zone.climate_entity, {
            "zone_id": zone_id,
            "climate_entity_id": meta.get("climate_entity_id"),
            "delta_f": meta.get("delta_f"),
            "direction": meta.get("direction"),
            "current_temp": meta.get("current_temp"),
            "soc_at_grant": soc_at_grant,
            "requested_setpoint": meta.get("granted_setpoint"),
            "granted_setpoint": meta.get("granted_setpoint"),
            "grace_s": grace_s,
            "hvac_mode": meta.get("hvac_mode"),
        })
        # Count in the daily override tally so the sensor visibility is
        # preserved (comfort delay IS a detected override, just handled).
        try:
            zone.override_count_today += 1
        except Exception:  # noqa: BLE001
            pass

    def _expire_comfort_delay(
        self, zone_id: str, *, reason: str,
    ) -> None:
        """Discharge a comfort-delay grant. reason ∈ {timer, zone_unoccupied,
        switch_flipped_on}. Enum documented as OPEN (extensible for Cycle B).
        """
        meta = self._comfort_delay_meta.pop(zone_id, None)
        cancel = self._comfort_delay_timers.pop(zone_id, None)
        if cancel is not None and reason != "timer":
            try:
                cancel()
            except Exception:  # noqa: BLE001
                pass
        if meta is None:
            return
        try:
            started_ts = meta.get("started_ts")
            elapsed_s = (
                (dt_util.now() - started_ts).total_seconds()
                if started_ts is not None else None
            )
        except Exception:  # noqa: BLE001
            elapsed_s = None
        _LOGGER.info(
            "ARREST-COMFORT-1: comfort_delay_expired zone=%s reason=%s elapsed_s=%s",
            zone_id, reason, elapsed_s,
        )
        climate_entity = meta.get("climate_entity_id", "")
        self._log_comfort_ledger("comfort_delay_expired", climate_entity, {
            "zone_id": zone_id,
            "climate_entity_id": climate_entity,
            "elapsed_s": elapsed_s,
            "expiry_reason": reason,
        })

    def _evict_comfort_delays_for_switch_on(self) -> None:
        """Called when the temp_arrester_override switch flips ON — every
        active comfort-delay is evicted with expiry_reason=switch_flipped_on.
        Subsequent switch-OFF does NOT revive.
        """
        for zone_id in list(self._comfort_delay_timers.keys()):
            self._expire_comfort_delay(zone_id, reason="switch_flipped_on")

    def _log_comfort_ledger(
        self, action: str, entity_id: str, details: dict[str, Any],
    ) -> None:
        """Fire-and-forget activity-logger ledger row. Guarded so a logger
        stall never blocks the grant / expiry paths.
        """
        try:
            from ..const import DOMAIN  # local: avoid cycle
            activity_logger = (
                self.hass.data.get(DOMAIN, {}).get("activity_logger")
                if hasattr(self.hass, "data") else None
            )
        except Exception:  # noqa: BLE001
            activity_logger = None
        if activity_logger is None:
            return
        try:
            zone_id = details.get("zone_id", "")
            self.hass.async_create_task(
                activity_logger.log(
                    coordinator="hvac",
                    action=action,
                    description=(
                        f"{action} zone={zone_id} "
                        f"reason={details.get('expiry_reason', '')}"
                    ).strip(),
                    zone=zone_id,
                    importance="notable",
                    entity_id=entity_id or "",
                    details=details,
                )
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug("comfort ledger emit failed", exc_info=True)

    def suppress(self, entity_id: str, kind: str | None = None) -> None:
        """Suppress override detection for an entity (URA-initiated change).

        v4.7.33 A-F5: opens a TTL window (`SUPPRESS_TTL_SECONDS`) rather
        than adding to a set that gets popped on the first state event.
        Covers multi-event settles from a single URA service call.

        FIX B1: ``kind`` tags the suppression origin so the mid-window
        manual-passthrough (~:660) can distinguish an induced
        ``preset_mode`` transition caused by URA's own temp-write
        (``kind="temp"``) from a genuine user manual flip. Preset-writes
        pass ``kind="preset"``. External callers that leave ``kind=None``
        retain legacy behavior (manual passthrough fires as before).
        """
        self._suppressed_until[entity_id] = (
            dt_util.now() + timedelta(seconds=SUPPRESS_TTL_SECONDS)
        )
        self._suppress_kind[entity_id] = kind

    def unsuppress(self, entity_id: str) -> None:
        """Re-enable override detection for an entity immediately.

        Used on error paths where the caller knows the URA-initiated write
        did not happen (or failed) and the TTL window must close now.
        """
        self._suppressed_until.pop(entity_id, None)
        self._suppress_kind.pop(entity_id, None)

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
            self._suppress_kind.clear()
        _LOGGER.info("Override Arrester %s", "enabled" if value else "disabled (passive mode)")

    @callback
    def _handle_climate_change(self, event: Event) -> None:
        """Handle climate entity state change — detect overrides."""
        entity_id = event.data.get("entity_id", "")
        new_state = event.data.get("new_state")
        old_state = event.data.get("old_state")

        if new_state is None or old_state is None:
            return

        # ARREST-COMFORT-1 Cycle A rev-2 L1: suppression-TTL filter is now
        # the single predicate _is_genuine_manual. Behavior-preserving
        # extraction — the helper still performs the same dict.pop side
        # effects (expired-window cleanup, mid-window genuine-manual
        # passthrough) as the pre-extraction inline block. See §3.2 step 1.
        if not self._is_genuine_manual(event, entity_id):
            return

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

        # ================================================================
        # Arrester Operator-Immunity — DETECTION-TIME STAMP.
        # Resolve the state-change's context.user_id to a person entity;
        # if that person is on the operator-immune list, stamp the hold
        # record and RETURN. No _override_active flag is set, no grace
        # timer is scheduled, no NM alert fires. Every subsequent shave
        # path additionally consults `_corrective_writes_suppressed` as
        # defense-in-depth, but the detection-time skip is the primary
        # short-circuit. Fail-open direction: user resolution errors,
        # missing context (physical dial), and non-listed users all fall
        # through to the normal (governed) path.
        # ================================================================
        ctx = getattr(event, "context", None)
        ctx_user_id = getattr(ctx, "user_id", None) if ctx is not None else None
        person_entity, user_name = self._resolve_context_user_to_person(
            ctx_user_id,
        )
        if (
            person_entity is not None
            and person_entity in self._immune_persons
            and self._is_immunity_context_eligible(ctx)
        ):
            # Capture thermostat's next_activity_time attribute (if the
            # integration exposes it) for boundary-based sunset. Bryant/
            # Carrier climate entities expose ``next_activity_time`` as
            # either an ISO-8601 timestamp or a bare "HH:MM" string
            # (verified live 2026-08-06 on the operator's Bryant, e.g.
            # value "18:00"). MED-A3: try fromisoformat first; on failure
            # parse as HH:MM in house-local time (roll forward to tomorrow
            # if the boundary has already passed today). Any parse
            # failure → no boundary sunset (durable-state + max-age
            # still active).
            nxt_dt: datetime | None = None
            try:
                nxt_raw = new_state.attributes.get("next_activity_time")
                if isinstance(nxt_raw, str) and nxt_raw:
                    nxt_dt = self._parse_next_activity(nxt_raw)
            except Exception:  # noqa: BLE001
                nxt_dt = None
            self._stamp_immune_hold(
                zone_id=zone.zone_id,
                user_id=ctx_user_id or "",
                user_name=user_name or "operator",
                person_entity=person_entity,
                next_activity_ts=nxt_dt,
            )
            zone.override_count_today += 1
            _LOGGER.info(
                "Arrester shave_skipped: zone=%s path=detection reason="
                "immune_hold user=%s (stamped; governance suspended for "
                "this hold until sunset)",
                zone.zone_name, user_name,
            )
            return

        # Temp Arrester Override — if the operator has flipped the
        # house-wide switch ON, no arrester write should fire for anyone
        # (guest, kid, physical dial, or listed operator). Skip with
        # ledger row and count the override for diagnostics.
        if self._temp_arrester_override_active:
            zone.override_count_today += 1
            self._log_shave_skipped(
                zone.zone_name, zone.zone_id,
                "detection_temp_arrester_override",
            )
            return

        # ================================================================
        # ARREST-COMFORT-1 Cycle A rev-2 §3.2 step 5 (2026-08-10).
        # NEW comfort_request evaluation. If the change is a genuine,
        # non-immune, occupied, toward-comfort manual with |delta| ≥
        # COMFORT_DELTA_MIN_F AND grant-time SOC ≥ COMFORT_SOC_FLOOR_PCT
        # AND not shed_active AND kill-switch not tripped: seed a comfort-
        # delay grant + emit `comfort_delay_started` ledger row + RETURN
        # (no severity dispatch). Otherwise fall through to the standard
        # severe/normal branches with ZERO behavior change (fail-closed
        # direction — planning §3.3). SOC evaluated EXACTLY ONCE here
        # (H2 contract); subsequent `comfort_delay_active` reads never
        # re-read SOC.
        # ================================================================
        if self._get_grace_min() > 0:
            qualifies, meta = self._comfort_request_qualifies(
                entity_id, event, zone,
            )
            if qualifies:
                # SOC gate: inclusive `>=` per rev-2 L2. Blind = below floor.
                # Fix-up A-HIGH-1: read the LIVE rung-3 knob (not the module
                # constant) so operator changes take effect without restart.
                soc = self._battery_soc
                soc_ok = (
                    (not self._battery_blind)
                    and soc is not None
                    and float(soc) >= float(self._get_soc_floor())
                )
                shed_gate = not self._shed_active
                if soc_ok and shed_gate:
                    # Seed grant, count override, RETURN (no dispatch).
                    self._seed_comfort_delay(zone, meta)
                    return
                # SOC below floor / blind / shed active → fall through to
                # standard arrest with byte-identical pre-cycle behavior.
                _LOGGER.debug(
                    "ARREST-COMFORT-1: comfort request qualified but "
                    "collapsed to standard timing (soc=%s blind=%s shed=%s)",
                    soc, self._battery_blind, self._shed_active,
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
        # Arrester Operator-Immunity: defense-in-depth. Detection-time
        # short-circuit above SHOULD have handled this case, but any
        # future caller into this method (e.g. a test harness, an out-of-
        # band trigger, an audit path) must still respect immunity/comfort.
        if self._corrective_writes_suppressed(zone_id):
            self._log_shave_skipped(
                zone.zone_name, zone_id, "severe_override",
            )
            return
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
        # Arrester Operator-Immunity: defense-in-depth (see _handle_severe_override).
        if self._corrective_writes_suppressed(zone_id):
            self._log_shave_skipped(
                zone.zone_name, zone_id, "normal_override",
            )
            return
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
        # Arrester Operator-Immunity: defense-in-depth. This runs from a
        # timer scheduled several minutes ago; immunity or Comfort Override
        # may have engaged in the interim (e.g. operator flipped the
        # Comfort Override switch after the grace timer started).
        if self._corrective_writes_suppressed(zone_id):
            self._log_shave_skipped(
                zone.zone_name, zone_id, "compromise",
            )
            self._grace_timers.pop(zone_id, None)
            return
        self._compromise_active[zone_id] = True

        # Remove grace timer reference
        self._grace_timers.pop(zone_id, None)

        # HVAC-GOVERNED-EXCURSION-1 D3 (row 4, S3 compromise START):
        # open the governed excursion. Item-2 retrofit (2026-08-21):
        # wire write MUST run inside auto_release_on_incomplete so an
        # emit exception or comfort-grace defer cannot leak the row.
        from . import hvac_excursion as _ex_mod  # noqa: PLC0415
        try:
            _cmp_token = await _ex_mod.begin_excursion(
                self.hass,
                zone_id=zone_id,
                entity_id=zone.climate_entity,
                kind=_ex_mod.EXCURSION_KIND.COMPROMISE,
                excursion_low=compromise_heat,
                excursion_high=compromise_cool,
                duration_s=self._compromise_minutes * 60,
                site="S3_compromise",
                intended_mode="heat_cool",
            )
        except Exception as _cmp_exc:  # noqa: BLE001
            _LOGGER.debug(
                "compromise: begin_excursion failed for %s: %s",
                zone_id, _cmp_exc,
            )
            _cmp_token = None
        if not hasattr(self, "_compromise_excursion_tokens"):
            self._compromise_excursion_tokens = {}

        _LOGGER.info(
            "Override compromise on %s: setting cool=%.0f heat=%.0f for %dmin",
            zone.zone_name, compromise_cool, compromise_heat,
            self._compromise_minutes,
        )

        # ARREST-COMFORT-1 §3.7 S3: DEFER while comfort_delay_active.
        async with _ex_mod.auto_release_on_incomplete(
            _cmp_token, trigger="s3_compromise_wire_failed",
        ) as _s3_guard:
            try:
                _s3_written = await emit_set_temperature(
                    self.hass,
                    zone.climate_entity,
                    target_temp_low=compromise_heat,
                    target_temp_high=compromise_cool,
                    freeze_active=self._freeze_active(),
                    blocking=False,
                    gate=lambda z=zone_id: self.comfort_delay_active(z),
                    site="S3_compromise",
                    zone_id=zone_id,
                    reason="normal_override_compromise",
                )
                if _s3_written:
                    self.suppress(zone.climate_entity, kind="temp")
                    # Commit — future _revert_override owns the return.
                    _s3_guard.mark_committed()
                    if _cmp_token is not None:
                        self._compromise_excursion_tokens[zone_id] = _cmp_token
            except Exception as e:
                _LOGGER.error("Override: failed to set compromise on %s: %s",
                              zone.climate_entity, e)
                # CM auto-releases; legacy did not return early here.

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

        # Arrester Operator-Immunity: defense-in-depth. Revert is the
        # LAST-CHANCE gate before we forcibly write preset back — if
        # immunity or Comfort Override engaged between grace/compromise
        # scheduling and this callback firing, we must not clobber the
        # operator's setpoint.
        if self._corrective_writes_suppressed(zone_id):
            self._log_shave_skipped(
                zone.zone_name, zone_id, "revert",
            )
            # Item-1 (2026-08-21): policy DECIDED not to restore
            # (immunity engaged). Nothing was attempted on the wire;
            # analytics counting restore_ok=False as failures should
            # NOT see these. restore_ok=None ("we deliberately did not
            # try") vs False ("we tried and the wire is wrong").
            await self._compromise_release_lease(
                zone_id, trigger="immunity_skip",
                restore_ok=None,
                trigger_detail="revert_skipped_immunity",
            )
            return

        # Fix-up D-MED-1: short-circuit the ENTIRE revert while a comfort-
        # delay is active. The raw `set_hvac_mode` re-assert below is
        # ungated (the D6 chokepoint only covers set_preset_mode) — bailing
        # here covers the mode + preset pair coherently and mirrors the
        # immunity short-circuit above.
        try:
            if self.comfort_delay_active(zone_id):
                _LOGGER.debug(
                    "Override revert on %s SKIPPED — comfort_delay_active",
                    zone.zone_name,
                )
                # Item-1 (2026-08-21): policy skip — see immunity block above.
                await self._compromise_release_lease(
                    zone_id, trigger="comfort_delay_skip",
                    restore_ok=None,
                    trigger_detail="revert_skipped_comfort_delay",
                )
                return
        except Exception:  # noqa: BLE001 — never let this deny safety
            pass

        _LOGGER.info(
            "Override revert on %s: restoring preset %s",
            zone.zone_name, original_preset,
        )

        # Fix-up A-MED-2: suppress AFTER the emit(s) and only for the
        # calls that actually landed. The set_hvac_mode + set_preset_mode
        # pair each produce a settle event; a preset-defer must not leave
        # a stale suppression around the (still-emitted) hvac_mode write.
        # FIX B1: kind="preset" so genuine mid-window user manual is
        # still caught (only "temp" suppression blocks manual passthrough).

        try:
            # v4.7.32: re-assert heat_cool whenever the mode has drifted from it
            # (off OR a single mode like cool/heat) — not just "off". The operator
            # runs zones in ranges/presets; a stuck single-mode defeats that. Only
            # force it on thermostats that support heat_cool.
            _mode_wrote = False
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
                _mode_wrote = True
                _LOGGER.info(
                    "Override revert: restored %s to heat_cool (was %s)",
                    zone.zone_name, zone.hvac_mode,
                )

            # F2 fix (plan §3 row 5): the preset value MUST come from the
            # token snapshot, not the caller's `original_preset` argument.
            # The two can disagree — the token is taken at compromise
            # begin_excursion time (what the wire held); `original_preset`
            # is the caller's intended value which may have drifted.
            _cmp_token = self._compromise_excursion_tokens.get(zone_id)
            _revert_preset = (
                _cmp_token.pre_preset if _cmp_token is not None
                and _cmp_token.pre_preset
                else original_preset
            )

            # ARREST-COMFORT-1 §3.7 S4: DEFER while comfort_delay_active.
            _s4_written = await emit_set_preset_mode(
                self.hass,
                zone.climate_entity,
                _revert_preset,
                blocking=False,
                gate=lambda z=zone_id: self.comfort_delay_active(z),
                site="S4_revert",
                zone_id=zone_id,
                reason="severe_override_revert",
            )
            if _s4_written or _mode_wrote:
                self.suppress(zone.climate_entity, kind="preset")
        except Exception as e:
            _LOGGER.error(
                "Override: failed to revert %s to preset %s: %s",
                zone.climate_entity, original_preset, e,
            )
            _s4_written = False

        # HVAC-GOVERNED-EXCURSION-1 D3 (row 5, S4 compromise RETURN):
        # F2 fix — pass restore_ok=_s4_written so a comfort-delay defer
        # (or an exception) records a divergence in the outcome event
        # row rather than silently closing "OK". Without this, an event
        # row shows the compromise ended cleanly while the wire is still
        # at the compromise setpoint.
        await self._compromise_release_lease(
            zone_id,
            trigger="timer",
            restore_ok=bool(_s4_written),
            preset_after=_revert_preset if _s4_written else None,
            trigger_detail=(
                None if _s4_written else "s4_preset_write_deferred_or_failed"
            ),
        )

    async def _compromise_release_lease(
        self, zone_id: str, *, trigger: str,
        restore_ok: bool | None = None,
        preset_after: str | None = None,
        trigger_detail: str | None = None,
    ) -> None:
        """Release the compromise excursion row for zone_id.

        Called from every _revert_override exit path. Bookkeeping only
        post-gate-removal — a leaked row is a false signal and a boot-
        audit input, but no longer suppresses decision writes.

        F2 fix: accepts restore_ok / preset_after / trigger_detail so an
        S4 preset-write deferral (or exception) records a divergence in
        the outcome event row rather than silently closing "OK".
        """
        _cmp_token = self._compromise_excursion_tokens.pop(zone_id, None)
        if _cmp_token is None:
            return
        try:
            from . import hvac_excursion as _ex_mod  # noqa: PLC0415
            await _ex_mod.return_excursion(
                _cmp_token, trigger=trigger,
                restore_ok=restore_ok,
                preset_after=preset_after,
                trigger_detail=trigger_detail,
            )
        except Exception as _ret_exc:  # noqa: BLE001
            _LOGGER.debug(
                "compromise: return_excursion (trigger=%s) failed for %s: %s",
                trigger, zone_id, _ret_exc,
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

            # Gate 4 (AC-RAMP-PIPELINE-HARDENING-1 D-GATE4): draw-based
            # predicate replaces the cloud-reported hvac_action veto.
            # Under `legacy` the pre-cycle body is restored verbatim;
            # under `shadow` (default on first boot) the legacy verdict
            # decides but divergence is LATCHED-logged; under `live` the
            # new predicate decides. The three state-clearing statements
            # MUST stay in the False branch — removing them collapses
            # Gate 7's consecutive-sample counter and Gate 8's
            # sustained-time guard on the next cooling cycle (B-H1).
            if not self._gate4_is_ok(zone, now):
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

                # Gate 5b (AC-RAMP-PIPELINE-HARDENING-1 D3): soft-nudge
                # daily cap runaway guard. Applies to the AUTO path only
                # (this is the AUTO entry); the manual `force_nudge`
                # button bypasses by design. Kill-switch semantics:
                # limit=0 disables the check.
                if (
                    self._soft_nudge_daily_limit > 0
                    and int(state.get("soft_nudge_count", 0) or 0)
                    >= self._soft_nudge_daily_limit
                ):
                    # F11 fix-up (2026-08-22): a partition/budget denial
                    # is NOT a lockout; report IDLE and write a
                    # declined-row entry (edge-triggered). Also guard
                    # with the sibling in-flight check every other Gate
                    # carries — otherwise this branch would stomp
                    # in-flight nudge sensor state.
                    if zone_id not in self._nudge_in_flight:
                        zone.ramp_state = AC_RAMP_STATE_IDLE
                    _LOGGER.info(
                        "soft_nudge_daily_limit_reached zone=%s count=%d",
                        zone_id, int(state.get("soft_nudge_count", 0) or 0),
                    )
                    await self._maybe_write_declined(
                        zone_id, "soft_nudge_daily_limit", now,
                    )
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

            # F5 (revised): if a durability window is armed for this
            # zone, grow the running max. Sampled at the 5-min tick
            # cadence — the truncated verdict is an INTERVAL check
            # (did it hold across the elapsed period), not an
            # instantaneous point. Full-window fire still uses the
            # instantaneous read at fire time.
            if zone_id in self._durable_pending:
                _prev_max = self._nudge_running_max_kw.get(zone_id, 0.0) or 0.0
                if kwh_rate > _prev_max:
                    self._nudge_running_max_kw[zone_id] = float(kwh_rate)

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
        # A1 fix-up (2026-08-22): per-zone diagnostic refresh alongside
        # the house-wide impact refresh. Same cadence (5 min), same
        # Bug Class #26 compliance (sensors read the cache sync).
        await self._refresh_a1_cache()

    async def _perform_ac_reset(self, zone: ZoneState) -> None:
        """Perform AC reset: off -> wait -> restore mode."""
        original_mode = zone.hvac_mode
        original_action = zone.hvac_action
        zone_id = zone.zone_id
        # 2026-08-22: snapshot the pre-reset preset so the SUCCESS branch
        # of _verify_restore can put it back. A raw setpoint/mode write on
        # Carrier/Bryant leaves preset_mode=manual, which then locks the
        # zone out of governed preset changes (should_change_preset in
        # hvac_preset.py refuses to act on 'manual'). Same defect the
        # v5.88.0 borrow cycle eliminated everywhere else; explicitly
        # excluded here per PLANNING_hvac_governed_excursion.md
        # (hard_reset_preset_assert is NOT a primitive-managed kind).
        try:
            _pre_state = self.hass.states.get(zone.climate_entity)
            original_preset = (
                _pre_state.attributes.get("preset_mode", "") or ""
                if _pre_state is not None
                else ""
            )
        except Exception:  # noqa: BLE001
            original_preset = ""
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
                self._restore_after_reset(zone, original_mode, original_preset)
            )

        # D7: use the runtime knob instead of the module constant so
        # operator-tuned off-durations take effect without redeploy.
        _off_duration_s = int(self._ac_reset_off_duration_s)
        self._reset_timers[zone_id] = async_call_later(
            self.hass,
            _off_duration_s,
            _on_reset_fire,
        )

        # D8 NM alert repair: partition-aware wording. The old string
        # said "#N/2 today" — misleading under partitioned budgets
        # because it hid the day/night split. New shape names the
        # partition and the partition budget, plus the day+night total
        # + total budget.
        _now_local = dt_util.now()
        _partition = "night" if self._is_night_now(_now_local) else "day"
        if _partition == "night":
            _used = 0
            _budget = int(self._reset_night_budget)
        else:
            _used = 0
            _budget = int(self._reset_day_budget)
        if self._db is not None:
            try:
                _state_for_msg = await self._db.get_ac_reset_state(zone_id)
                # F1 fix-up: night count lives in the session-keyed row
                # when the night session crossed midnight; fetch it
                # explicitly rather than reading whatever happens to be
                # on today's row.
                _sess = self._night_session_date(_now_local)
                _today = _state_for_msg.get("date") or _now_local.date().isoformat()
                if _sess != _today:
                    _night_for_msg = await self._db.get_ac_reset_state(
                        zone_id, _sess,
                    )
                    _night = int(
                        _night_for_msg.get("night_reset_count", 0) or 0
                    )
                else:
                    _night = int(
                        _state_for_msg.get("night_reset_count", 0) or 0
                    )
                _day = int(_state_for_msg.get("day_reset_count", 0) or 0)
                if _partition == "night":
                    _used = _night
                else:
                    _used = _day
            except Exception:  # noqa: BLE001 — defensive
                _day = 0
                _night = 0
        else:
            _day = 0
            _night = 0
        _total_budget = (
            int(self._reset_day_budget) + int(self._reset_night_budget)
        )
        await self._send_nm_alert(
            title=f"AC Reset: {zone.zone_name}",
            message=(
                f"Stuck {original_action} cycle detected — "
                f"cycling off for {_off_duration_s}s then restoring "
                f"{restore_target}. Reset #{_used}/{_budget} ({_partition}). "
                f"Total today: {_day + _night} across {_total_budget} "
                f"({_day}/day + {_night}/night)."
            ),
            severity="high",
        )

    async def _restore_after_reset(
        self, zone: ZoneState, original_mode: str, original_preset: str = "",
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
                    # F12 fix-up (2026-08-22): pop the stashed event_id
                    # here too. Without this, a LATER reset would
                    # inherit the previous reset's completed event_id
                    # and its restore_ok back-fill would land on the
                    # wrong row.
                    if hasattr(self, "_hard_reset_completed_event_ids"):
                        self._hard_reset_completed_event_ids.pop(zone_id, None)
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
                # D5-B: back-fill restore_ok=0 on the completed row.
                await self._backfill_restore_ok(zone_id, False)
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
                # 2026-08-22: SUCCESS branch — restore the pre-reset preset.
                # A raw set_hvac_mode/set_temperature write on Carrier/Bryant
                # leaves preset_mode=manual, and hvac_preset.should_change_preset
                # refuses to act on 'manual' — so a hard-reset zone is locked
                # out of preset governance until this is put back. Mirror the
                # cancel_nudge preset-restore pattern (blocking=True, suppress
                # kind="preset" so the induced settle doesn't self-count).
                # Unopinionated: restore what was FOUND, including 'manual'.
                # Fail-soft: a failure here MUST NOT break the mode/setpoint
                # restore that already succeeded.
                #
                # F9 fix-up (2026-08-22): track preset-restore success
                # SEPARATELY from mode-restore. Pre-fix, a swallowed
                # preset failure fell through to unconditional
                # `_backfill_restore_ok(True)` — misreporting a lockout-
                # condition failure (the v5.88.1 defect this cycle
                # exists to fix) as a full success. combined restore_ok
                # is now mode_ok AND preset_ok.
                _mode_ok = True  # branch is the success branch of mode verify
                _preset_ok: bool = True
                if original_preset:
                    self.suppress(climate_entity, kind="preset")
                    try:
                        await emit_set_preset_mode(
                            self.hass,
                            climate_entity,
                            original_preset,
                            blocking=True,
                            gate=None,
                            site="ac_reset_verify_preset_restore",
                            zone_id=zone_id,
                            reason="ac_reset_preset_restore",
                        )
                        _LOGGER.info(
                            "HVAC AC Reset: Zone %s preset restored -> %s",
                            zone_name, original_preset,
                        )
                    except Exception as _pexc:  # noqa: BLE001
                        _LOGGER.error(
                            "HVAC AC Reset: preset restore failed for "
                            "zone %s (preset=%s): %s — mode/setpoint "
                            "restore succeeded, preset left as-is",
                            zone_name, original_preset, _pexc,
                        )
                        _preset_ok = False
                # D5-B: back-fill restore_ok on the completed row.
                # F9: combined restore_ok reflects the AND of mode-ok
                # AND preset-ok. Also record preset_restore_ok as its
                # own signal so downstream analytics can discriminate.
                _combined_ok = bool(_mode_ok and _preset_ok)
                await self._backfill_restore_ok(
                    zone_id, _combined_ok, preset_ok=_preset_ok,
                )

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
            # D5-B: enrich `hard_reset_completed` telemetry with post-
            # restore preset/mode + current temp. `restore_ok` starts
            # NULL — the delayed `_verify_restore` back-fills it via
            # `update_ac_ramp_event_fields` on its terminal branches.
            _post_preset: str | None = None
            _post_mode: str | None = None
            try:
                _cs_post = self.hass.states.get(climate_entity)
                if _cs_post is not None:
                    _post_preset = _cs_post.attributes.get(
                        "preset_mode", "",
                    ) or ""
                    _post_mode = _cs_post.state
            except Exception:  # noqa: BLE001
                pass
            completed_event_id = await self._db.log_ac_ramp_event(
                zone_id=zone_id,
                event_type=AC_RAMP_EVENT_HARD_RESET_COMPLETED,
                target_high=zone.target_temp_high,
                current_temp=zone.current_temperature,
                preset_after=_post_preset,
                mode_after=_post_mode,
                restore_ok=None,
                action_taken=f"restored_mode={target_mode}",
            )
            # Bridge `_verify_restore` -> completed row: stash the
            # event_id on the coordinator so its terminal branches can
            # back-fill `restore_ok` via update_ac_ramp_event_fields.
            if not hasattr(self, "_hard_reset_completed_event_ids"):
                self._hard_reset_completed_event_ids = {}
            if completed_event_id is not None:
                self._hard_reset_completed_event_ids[zone_id] = completed_event_id
            # D6: schedule the reset-outcome delayed callback.
            self._schedule_reset_outcome(zone, completed_event_id)
        zone.ramp_state = AC_RAMP_STATE_IDLE

    # =========================================================================
    # v4.5.11 — AC Energy-Aware Ramp-Down: action paths
    # =========================================================================

    def _read_kwh_rate(
        self, zone: ZoneState, now: datetime, *, warn: bool = True,
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
                # F10 fix-up: warn=False callers (shadow Gate 4) skip
                # the rate-limit token consumption so the real Gate-7
                # stale warning is not suppressed for 6h.
                if warn:
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
        # F7 fix-up (2026-08-22): reject cumulative kWh sensors. config_flow
        # advertises the field as "kW or kWh", so a monotonic counter
        # is a legal configuration; without this check the counter would
        # cross the 0.5 kW floor exactly once and never return, making
        # Gate 4 a permanent no-op under LIVE mode. Plan §3-D-GATE4
        # step 3 requires fail-CLOSED (return None) so the predicate
        # denies rather than misdecides.
        if unit in ("kwh", "kw h", "kw-h", "kw·h", "wh", "watt-hour", "watt hour"):
            return None
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
        # Arrester Operator-Immunity gate: Comfort Override + per-zone
        # immune-hold suppress the soft-nudge dispatch (last chance before
        # the +°F setpoint write). The manual entry point `force_nudge`
        # bypasses this gate by design.
        if self._corrective_writes_suppressed(zone_id):
            zone.ramp_state = AC_RAMP_STATE_IDLE
            self._log_shave_skipped(zone.zone_name, zone_id, "soft_nudge")
            return
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
        # F21 fix-up (2026-08-22): the D-SCORE re-nudge early-fire was
        # previously invoked here at method ENTRY, before the wire
        # write could abort. A failed emit_set_temperature that early-
        # exits would then have truncated the PREVIOUS nudge's
        # durability record even though no re-nudge actually happened.
        # Moved past the wire-write success point below (search for
        # "F21: fire truncated durable HERE").
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

        # FIX B2: snapshot preset BEFORE the temp write so
        # _restore_after_nudge can restore it (the temp write flips
        # preset->manual as a side effect on Carrier/Bryant and the
        # restore path never wrote preset back — leaving the sleep
        # schedule defeated for the rest of the night).
        try:
            _cs = self.hass.states.get(zone.climate_entity)
            _pre_preset = (
                _cs.attributes.get("preset_mode", "") if _cs is not None else ""
            )
            # HVAC-GOVERNED-EXCURSION-1 D1: observability-only snapshot of
            # the raw pre-write preset+mode. Reads HA's cached state dict
            # (no I/O, no await) so it cannot perturb the setpoint-vs-preset
            # race the telemetry is measuring. Unlike _pre_preset (which is
            # filtered to non-manual/non-empty for restore intent), these
            # capture the RAW state so a "manual" preset_before is visible
            # in the DB — that is the SELF-DISARM signal (defect #2).
            _pre_mode = _cs.state if _cs is not None else None
        except Exception:  # noqa: BLE001 — defensive
            _pre_preset = ""
            _pre_mode = None
        # None (not empty string) means "state unreadable, do not guess".
        _tele_preset_before: str | None = _pre_preset if _cs is not None else None
        _tele_mode_before: str | None = _pre_mode
        # HVAC-GOVERNED-EXCURSION-1 D3 (§13.5 CLOSED, snapshot-restore):
        # UNFILTERED snapshot. Rev-4 deleted the pre-existing filter
        # that excluded manual/empty preset values. The excursion
        # snapshots exactly what it finds and restores exactly that.
        # If pre_preset is "manual", restore writes "manual" (equality
        # no-op); if empty, restore skips the preset step. Fighting an
        # operator-set manual is the arrester's job (per operator's
        # ruling), not the excursion's.
        if _pre_preset:
            self._nudge_pre_preset[zone_id] = _pre_preset
        else:
            self._nudge_pre_preset.pop(zone_id, None)

        # HVAC-GOVERNED-EXCURSION-1 D3 (row 6, S5 start): open the
        # governed excursion. Every begin_excursion caller MUST wrap
        # the wire-write attempt in auto_release_on_incomplete so an
        # early-exit (defer, exception, fall-through) cannot leak a
        # row. Item-2 retrofit (2026-08-21).
        from . import hvac_excursion as _ex_mod  # noqa: PLC0415
        try:
            _ex_token = await _ex_mod.begin_excursion(
                self.hass,
                zone_id=zone_id,
                entity_id=zone.climate_entity,
                kind=_ex_mod.EXCURSION_KIND.NUDGE,
                excursion_low=zone.target_temp_low,
                excursion_high=new_target,
                duration_s=duration_s,
                site="S5_nudge_start",
                intended_mode="heat_cool",
            )
        except Exception as _ex_exc:  # noqa: BLE001
            _LOGGER.debug(
                "nudge: begin_excursion failed for %s (non-fatal): %s",
                zone_id, _ex_exc,
            )
            _ex_token = None
        if not hasattr(self, "_nudge_excursion_tokens"):
            self._nudge_excursion_tokens = {}

        # ARREST-COMFORT-1 §3.7 S5: DEFER while comfort_delay_active.
        # Fix-up A-MED-2: suppress AFTER the emit; only stamp when it
        # actually fires. FIX B1: kind="temp".
        async with _ex_mod.auto_release_on_incomplete(
            _ex_token, trigger="s5_nudge_wire_failed",
        ) as _s5_guard:
            try:
                _s5_written = await emit_set_temperature(
                    self.hass,
                    zone.climate_entity,
                    target_temp_low=zone.target_temp_low,
                    target_temp_high=new_target,
                    freeze_active=self._freeze_active(),
                    blocking=False,
                    gate=lambda z=zone_id: self.comfort_delay_active(z),
                    site="S5_nudge_start",
                    zone_id=zone_id,
                    reason="soft_nudge_start",
                )
                if _s5_written:
                    self.suppress(zone.climate_entity, kind="temp")
                    # Commit the excursion — CM will be a no-op; the
                    # timer-scheduled _restore_after_nudge below owns
                    # the future return_excursion call.
                    _s5_guard.mark_committed()
                    if _ex_token is not None:
                        self._nudge_excursion_tokens[zone_id] = _ex_token
            except Exception as e:
                _LOGGER.error(
                    "Soft nudge: set_temperature failed on %s: %s",
                    zone.climate_entity, e,
                )
                if self._db is not None:
                    await self._db.clear_ac_in_flight_nudge(zone_id)
                # FIX B2: nudge never took effect, don't try to restore
                # preset later.
                self._nudge_pre_preset.pop(zone_id, None)
                # CM auto-releases the excursion on scope exit (no
                # mark_committed). Re-raise cleanup path: we return
                # early below to skip in-flight bookkeeping.
                # (No re-raise: legacy behaviour swallowed the exception.)
                return
            # Legacy behaviour on comfort-grace defer: DO NOT return
            # early — flow continues to in-flight bookkeeping below
            # (daily counter etc.). Legacy assumed the write would
            # eventually land via re-emit. Preserving that; CM will
            # auto-release the excursion since mark_committed was
            # skipped, so the row does not linger.

        # F21: fire truncated durable HERE — the wire write above has
        # either landed OR set legacy behaviour (comfort-grace defer
        # is expected to eventually land via re-emit, so we still
        # legitimately count this as a re-nudge for the prior cycle).
        # A hard emit failure returned early above, so we won't reach
        # this point in that case.
        try:
            self._maybe_fire_durable_early(zone_id)
        except Exception as _e:  # noqa: BLE001 — defensive
            _LOGGER.debug(
                "_maybe_fire_durable_early failed for %s: %s", zone_id, _e,
            )

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
            # #53 fix: populate ac_ramp_events.excursion_id from the
            # NUDGE token opened by begin_excursion above. Without this,
            # the column added in D2 was DEAD — plumbed through the DAO
            # but never given a value. The join key that lets
            # ac_ramp_events UNION-analyse against hvac_excursion_events
            # is only useful if it has a value.
            _tele_excursion_id = (
                self._nudge_excursion_tokens[zone_id].excursion_id
                if zone_id in self._nudge_excursion_tokens
                else None
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
                # HVAC-GOVERNED-EXCURSION-1 D1: pre-write telemetry.
                preset_before=_tele_preset_before,
                mode_before=_tele_mode_before,
                excursion_id=_tele_excursion_id,
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
        """Restore target after nudge_duration; schedule outcome evaluation.

        DELIBERATE runtime exception to ``_corrective_writes_suppressed``:
        this method UN-SHAVES (puts the operator's original target back on
        the wire). It runs unconditionally even when Temp Arrester
        Override is engaged OR the zone has an active immune hold — the
        whole point of immunity / Temp Arrester Override is to honour the
        operator's setpoint, and this method is what makes that true when
        a soft-nudge was already in flight when the guard engaged. If we
        gated it, an operator engaging Temp Arrester Override mid-nudge
        would leave the +°F bump stuck on the thermostat until the next
        boundary. Documented per the operator's fix-up instructions.
        """
        zone_id = zone.zone_id
        self._nudge_restore_timers.pop(zone_id, None)
        self._nudge_in_flight.discard(zone_id)

        # Risk R11: re-suppress before our own write so an in-flight user
        # override doesn't get mis-classified.
        # FIX B1: kind="temp" (see suppress() docstring).
        self.suppress(zone.climate_entity, kind="temp")

        try:
            # ARREST-COMFORT-1 §3.7 S6: ALLOW (restoration path).
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

        # FIX B2: preset-preserving restore. If we snapshotted a
        # non-manual preset before the nudge AND the thermostat is now
        # in "manual" (i.e. our temp write flipped it as a side effect),
        # write the preset back to what it was. Suppression is already
        # open (kind="temp" set above); we re-open with kind="preset"
        # so the induced settle events from set_preset_mode stay
        # suppressed and don't self-count as a user override.
        pre_preset = self._nudge_pre_preset.pop(zone_id, "")
        # HVAC-GOVERNED-EXCURSION-1 D3 (§13.5 CLOSED, row 7):
        # UNCONDITIONAL preset write from the snapshot. Rev-4 deleted
        # the pre-existing `if _cur_preset == "manual"` gate — the
        # excursion restores exactly what it snapshotted. If pre_preset
        # equals the current thermostat preset, the write is idempotent;
        # if it differs, we restore. The old "only rewrite when we see
        # manual" gate was the self-disarm latch (defect #2 in §1.1).
        if pre_preset:
            self.suppress(zone.climate_entity, kind="preset")
            try:
                # ARREST-COMFORT-1 §3.7 S7: ALLOW (restoration).
                # HVAC-GOVERNED-EXCURSION-1: return path uses
                # blocking=True (EXCURSION_RETURN_BLOCKING) so the D1
                # immediate-read below sees the settled write, not a
                # racing cloud poll.
                await emit_set_preset_mode(
                    self.hass,
                    zone.climate_entity,
                    pre_preset,
                    blocking=True,
                )
                _LOGGER.info(
                    "Soft nudge restore on %s: preset -> %s "
                    "(snapshot-restore, unconditional)",
                    zone.zone_name, pre_preset,
                )
            except Exception as e:  # noqa: BLE001 — defensive
                _LOGGER.error(
                    "Soft nudge preset restore failed on %s: %s",
                    zone.climate_entity, e,
                )

        self._track_zone_action(
            zone, AC_RAMP_EVENT_NUDGE_RESTORED, "auto",
            kwh_before=zone.nudge_kwh_rate_before,
        )
        if self._db is not None:
            await self._db.clear_ac_in_flight_nudge(zone_id)
            # HVAC-GOVERNED-EXCURSION-1 D1: paired IMMEDIATE / SETTLED
            # telemetry. The immediate verdict is computed here from
            # hass.states.get (cached dict, no await) — it captures what
            # HA sees the moment the restore sequence completes. The
            # SETTLED verdict is written by a scheduled callback
            # AC_NUDGE_RESTORE_SETTLE_DELAY_S later, so a late-landing
            # cloud-poll setpoint that clobbers preset back to "manual"
            # (the observed ~509 ms defect this cycle exists to measure)
            # is captured in restore_ok. The pair (immediate=1, settled=0)
            # is the load-bearing signature of the clobber; reading only
            # at t=0 would systematically record success in the failure
            # case, which is worse than no metric.
            _tele_preset_after: str | None = None
            _tele_mode_after: str | None = None
            _tele_restore_ok_immediate: bool | None
            try:
                _cs_final = self.hass.states.get(zone.climate_entity)
            except Exception:  # noqa: BLE001 — defensive
                _cs_final = None
            if _cs_final is not None:
                _tele_preset_after = _cs_final.attributes.get("preset_mode", "") or ""
                _tele_mode_after = _cs_final.state
            # Verdict semantics (identical for immediate + settled):
            #   pre_preset (intent) empty  -> no intent (self-disarm or
            #     nothing to restore) -> NULL, never guess.
            #   pre_preset set + preset_after unreadable -> NULL.
            #   pre_preset set + preset_after == pre_preset -> True.
            #   pre_preset set + preset_after != pre_preset -> False.
            if not pre_preset:
                _tele_restore_ok_immediate = None
            elif _tele_preset_after is None:
                _tele_restore_ok_immediate = None
            else:
                _tele_restore_ok_immediate = (_tele_preset_after == pre_preset)
            # #53 fix: same excursion_id from the token so nudge_started
            # and nudge_restored can be JOINed.
            _tele_excursion_id_r = (
                self._nudge_excursion_tokens[zone_id].excursion_id
                if zone_id in self._nudge_excursion_tokens
                else None
            )
            await self._db.log_ac_ramp_event(
                zone_id=zone_id,
                event_type=AC_RAMP_EVENT_NUDGE_RESTORED,
                target_high=original_target,
                kwh_rate_before=zone.nudge_kwh_rate_before,
                preset_after=_tele_preset_after,
                mode_after=_tele_mode_after,
                # restore_ok is left NULL here; the delayed settled
                # callback below fills it in AC_NUDGE_RESTORE_SETTLE_DELAY_S
                # from now. Any read that sees restore_ok IS NULL is a
                # "measurement in flight OR settled row lost to
                # retention/kill" case — both are valid NULL.
                restore_ok=None,
                restore_ok_immediate=_tele_restore_ok_immediate,
                excursion_id=_tele_excursion_id_r,
            )

            # ---- SETTLED sample: delayed passive re-read ------------------
            # Cancel any prior in-flight settled timer for this zone (a
            # rapid re-nudge cycle would otherwise leak the previous
            # callback). Store the new handle so teardown can cancel it.
            _prev_settled = self._nudge_settled_timers.pop(zone_id, None)
            if _prev_settled is not None:
                try:
                    _prev_settled()
                except Exception:  # noqa: BLE001 — defensive
                    pass

            _intent_preset = pre_preset  # closure capture (already popped)

            async def _write_settled(_now, _zid=zone_id,
                                     _entity=zone.climate_entity,
                                     _intent=_intent_preset) -> None:
                # F8 fix-up (2026-08-22, revised): the settled verdict
                # is structurally unmeasurable through hass.states on
                # this deployment. ha_carrier does not write the
                # entity state on `async_set_preset_mode`; the state
                # only refreshes on its 30-min coordinator poll.
                # Median inter-nudge cadence is 25 min, so any settle
                # sample either lands INSIDE the poll interval
                # (reading stale state) or AFTER the next nudge starts
                # (reading a subsequent nudge's state). Neither is
                # honest evidence.
                #
                # This callback therefore fires but does NOT read the
                # state object. It writes restore_ok=NULL with a
                # reason string so consumers of `nudge_restored` rows
                # know the sample was intentionally skipped. The
                # IMMEDIATE sample (restore_ok_immediate, written
                # outside this callback) is preserved as an honest
                # read of possibly-stale state.
                #
                # See CARRIER-STALE-POLL-REFRESH-1 for the out-of-
                # scope path to a working instrument.
                self._nudge_settled_timers.pop(_zid, None)
                if self._db is not None:
                    try:
                        await self._db.update_ac_ramp_restore_settled(
                            zone_id=_zid,
                            preset_settled=None,
                            mode_settled=None,
                            restore_ok=None,
                            settled_reason=(
                                AC_NUDGE_RESTORE_SETTLED_UNMEASURABLE_REASON
                            ),
                        )
                    except Exception as _e:  # noqa: BLE001 — defensive
                        _LOGGER.debug(
                            "settled restore verdict update failed "
                            "on %s: %s", _zid, _e,
                        )

            @callback
            def _on_settled_fire(_now):
                self.hass.async_create_task(_write_settled(_now))

            self._nudge_settled_timers[zone_id] = async_call_later(
                self.hass,
                AC_NUDGE_RESTORE_SETTLE_DELAY_S,
                _on_settled_fire,
            )

        zone.ramp_state = AC_RAMP_STATE_AWAITING_EVAL
        # v4.7.17.1: capture restore wall-clock for recorder query in
        # _evaluate_nudge_outcome (trailing-window min kW rule).
        self._nudge_post_restore_ts[zone_id] = dt_util.now().isoformat()

        # HVAC-GOVERNED-EXCURSION-1 D3 (row 7, S5/S6 nudge RETURN):
        # release the excursion lease. Clears the in-memory lease
        # entry AND deletes the persisted hvac_excursion_state row.
        # Callers of subsequent decision ticks stop deferring; a
        # follow-up preset write from S1 is again allowed. The nudge
        # continues to write its outcome to ac_ramp_events via the
        # existing D1 path above (with the D2 excursion_id column
        # populated by the token so cross-table analytics can JOIN).
        _ex_token = self._nudge_excursion_tokens.pop(zone_id, None)
        if _ex_token is not None:
            try:
                from . import hvac_excursion as _ex_mod  # noqa: PLC0415
                await _ex_mod.return_excursion(
                    _ex_token, trigger="timer",
                )
            except Exception as _ret_exc:  # noqa: BLE001
                _LOGGER.debug(
                    "nudge: return_excursion failed for %s: %s",
                    zone_id, _ret_exc,
                )

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
    ) -> tuple[float | None, float | None, int]:
        """Query HA recorder for kW samples on `zone.ac_load_sensor` over
        `[restore_dt, eval_dt]` and return (min_kw, mean_kw, sample_count).

        v5.24+ hotfix: also return the arithmetic MEAN of the same samples.
        Classification/escalation still key off `min_kw`; only the
        `kwh_avoided` magnitude compute uses `mean_kw` (the min hits ~0
        during natural compressor cycling and wildly over-credits each
        nudge as if it eliminated the full AC load).

        Returns (None, None, 0) if:
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
            return None, None, 0
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
            return None, None, 0

        states = states_dict.get(zone.ac_load_sensor) if states_dict else None
        if not states:
            return None, None, 0

        min_kw: float | None = None
        sum_kw: float = 0.0
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
            sum_kw += value
            if min_kw is None or value < min_kw:
                min_kw = value
        mean_kw = (sum_kw / sample_count) if sample_count > 0 else None
        return min_kw, mean_kw, sample_count

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

        # Compute trailing-window minimum kW over [restore_ts, now].
        # v5.24+ hotfix: also collect the arithmetic MEAN over the same
        # window — classification/escalation still key off post_min
        # (byte-identical decision), but the kwh_avoided magnitude uses
        # post_mean so we don't credit a nudge with the compressor's
        # natural OFF-cycle valley (~0 kW) as if it eliminated full AC load.
        post_min: float | None = None
        post_mean: float | None = None
        sample_count = 0
        if restore_iso is not None:
            try:
                restore_dt = datetime.fromisoformat(restore_iso)
            except (ValueError, TypeError):
                restore_dt = None
            if restore_dt is not None:
                post_min, post_mean, sample_count = (
                    await self._compute_post_restore_min_kw(
                        zone, restore_dt, now,
                    )
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
        # v5.24+ hotfix: magnitude uses post_mean (AVERAGE reduction across
        # the post-window), not post_min. Classification above still keys
        # off post_min so escalation logic is byte-identical. When there
        # are no samples, post_mean is None → kwh_avoided stays 0.0
        # (same fallback path as before).
        kwh_avoided = 0.0
        if effective and post_mean is not None and kwh_rate_before is not None:
            delta = kwh_rate_before - post_mean
            if delta > 0:
                kwh_avoided = delta * (AC_KWH_AVOIDED_PROJECTION_CAP_MIN / 60.0)

        self._track_zone_action(
            zone, AC_RAMP_EVENT_NUDGE_EVALUATED, "auto",
            kwh_before=kwh_rate_before,
            kwh_after=post_min,
        )
        if self._db is not None:
            # Structured notes — semicolon-separated key=value pairs,
            # parser at database.py splits on `;` then `=`. Format MUST
            # stay key=value;key=value for back-compat. New keys are
            # APPENDED (parser is tolerant of unknown keys + missing keys).
            #
            # PLANNING_hvac_kwh_avoided_savings D2: capture the TOU-effective
            # rate at nudge-eval time so the $ savings family can value each
            # event at the rate it happened at (not a later look-up). Forward-
            # only: pre-deploy rows lacking `rate` contribute $0.
            try:
                _rate_val, _rate_src = _get_effective_rate_kwh(self.hass)
                _rate_f = float(_rate_val)
                # FIX (Review A L1): only persist a `rate=` key when finite
                # AND positive. A `rate=nan` (or negative) would poison the
                # cached lifetime savings total — omitting the key is
                # forward-only-safe (row contributes $0 to savings math but
                # still counts in kWh-avoided).
                if math.isfinite(_rate_f) and _rate_f > 0:
                    rate_field = f";rate={_rate_f:.5f}"
                else:
                    _LOGGER.debug(
                        "ac_ramp savings: dropping non-finite/non-positive "
                        "rate=%r (row will contribute $0)", _rate_val,
                    )
                    rate_field = ""
            except Exception as _rerr:  # noqa: BLE001
                _LOGGER.debug("rate capture for ac_ramp savings failed: %s", _rerr)
                rate_field = ""
            notes = (
                f"kwh_avoided={kwh_avoided:.3f};"
                f"post_min={'NA' if post_min is None else f'{post_min:.2f}'};"
                f"sample_count={sample_count};"
                f"classification={classification};"
                f"post_mean={'NA' if post_mean is None else f'{post_mean:.2f}'}"
                f"{rate_field}"
            )
            eval_event_id = await self._db.log_ac_ramp_event(
                zone_id=zone_id,
                event_type=AC_RAMP_EVENT_NUDGE_EVALUATED,
                current_temp=zone.current_temperature,
                target_high=zone.target_temp_high,
                kwh_rate_before=kwh_rate_before,
                kwh_rate_after=post_min,
                effective=effective,
                notes=notes,
            )
            # D-SCORE: schedule the delayed durability classifier.
            # Fires `_durability_window_min` minutes from now and
            # UPDATEs `durable` / `durable_minutes` onto THIS event_id
            # (no "UPDATE latest row" race). Truncated early on re-
            # nudge of the same zone.
            try:
                self._schedule_write_durable(
                    zone=zone,
                    event_id=eval_event_id,
                    kwh_rate_before=kwh_rate_before,
                    restore_dt=now,
                )
            except Exception as _e:  # noqa: BLE001
                _LOGGER.debug(
                    "_schedule_write_durable failed for %s: %s",
                    zone_id, _e,
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
                triggered_by="auto",
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

    # -------------------------------------------------------------------------
    # AC-RAMP-PIPELINE-HARDENING-1 D5-B / D6 back-fill helpers
    # -------------------------------------------------------------------------

    async def _backfill_restore_ok(
        self, zone_id: str, ok: bool, *, preset_ok: bool | None = None,
    ) -> None:
        """D5-B: back-fill `restore_ok` onto the hard_reset_completed
        row identified by its stashed event_id.

        F9 fix-up (2026-08-22): optional `preset_ok` records the
        preset-restore verdict as a distinct column so a swallowed
        preset failure is not conflated with a full success. `ok`
        remains the combined (mode AND preset) verdict for backward-
        compatible readers.
        """
        event_id = None
        if hasattr(self, "_hard_reset_completed_event_ids"):
            event_id = self._hard_reset_completed_event_ids.pop(zone_id, None)
        if event_id is None or self._db is None:
            return
        _fields: dict = {"restore_ok": ok}
        if preset_ok is not None:
            _fields["preset_restore_ok"] = preset_ok
        try:
            await self._db.update_ac_ramp_event_fields(
                event_id, **_fields,
            )
        except Exception as _e:  # noqa: BLE001
            _LOGGER.debug(
                "backfill_restore_ok failed for zone=%s event_id=%s: %s",
                zone_id, event_id, _e,
            )

    def _schedule_reset_outcome(
        self, zone: ZoneState, completed_event_id: int | None,
    ) -> None:
        """D6: schedule the reset-outcome passive re-read
        `AC_RESET_OUTCOME_SETTLE_S` seconds after
        `_restore_after_reset` returns. Silent no-op if there is no
        pending started-row context (aborts / setter-driven restore)."""
        zone_id = zone.zone_id
        pending = self._reset_outcome_pending.pop(zone_id, None)
        if pending is None or completed_event_id is None:
            return

        # Cancel any prior in-flight outcome timer for this zone.
        prev = self._reset_outcome_timers.pop(zone_id, None)
        if prev is not None:
            try:
                prev()
            except Exception:  # noqa: BLE001
                pass

        _target_high = pending.get("target_high")
        # F22 fix-up: `temp_start` was stored on the pending payload
        # but never read here — removed. If a future use-case needs
        # start-vs-settle delta it can be re-added deliberately.

        # F6 fix-up (2026-08-22): split the D6 delayed callback into
        # TWO timers so the temp LEVEL classification stays at 60s
        # (defensible per the plan) while the kW capture waits for the
        # measured p50 72-101s command-to-physical-response lag to
        # elapse before sampling. A 60s kW read sampled INSIDE the
        # actuation lag and systematically returned ~0.0, which reads
        # as evidence the reset worked even when it didn't.
        async def _write_outcome_temp(_now, _zid=zone_id,
                                 _entity=zone.climate_entity,
                                 _target=_target_high,
                                 _completed_id=completed_event_id) -> None:
            self._reset_outcome_timers.pop(_zid, None)
            _settle_temp: float | None = None
            try:
                _cs = self.hass.states.get(_entity)
                if _cs is not None:
                    _raw = _cs.attributes.get("current_temperature")
                    if _raw is not None:
                        try:
                            _settle_temp = float(_raw)
                        except (ValueError, TypeError):
                            _settle_temp = None
            except Exception:  # noqa: BLE001
                _settle_temp = None
            if _settle_temp is None or _target is None:
                _outcome = AC_RESET_OUTCOME_INCONCLUSIVE
            elif _settle_temp > float(_target):
                _outcome = AC_RESET_OUTCOME_JUSTIFIED_RAMP
            else:
                _outcome = AC_RESET_OUTCOME_FLOOR_SURVIVED
            if self._db is not None:
                try:
                    # F13: write settle temp to `current_temp_settle`.
                    await self._db.update_ac_ramp_event_fields(
                        _completed_id,
                        reset_outcome=_outcome,
                        current_temp_settle=_settle_temp,
                    )
                except Exception as _e:  # noqa: BLE001
                    _LOGGER.debug(
                        "write_reset_outcome failed zone=%s event_id=%s: %s",
                        _zid, _completed_id, _e,
                    )

        async def _write_outcome_kw(_now, _zid=zone_id,
                                    _completed_id=completed_event_id) -> None:
            # Fires at AC_RESET_OUTCOME_KWH_SETTLE_S. Reads the kW
            # sensor AFTER the actuation-lag envelope and updates only
            # kwh_rate_settle on the same completed row.
            self._reset_outcome_kw_timers.pop(_zid, None)
            _settle_kw: float | None = None
            try:
                _z = self._zone_manager.zones.get(_zid)
                if _z is not None:
                    _settle_kw = self._read_kwh_rate(_z, dt_util.now())
            except Exception:  # noqa: BLE001
                _settle_kw = None
            if self._db is not None:
                try:
                    await self._db.update_ac_ramp_event_fields(
                        _completed_id, kwh_rate_settle=_settle_kw,
                    )
                except Exception as _e:  # noqa: BLE001
                    _LOGGER.debug(
                        "write_reset_kw_settle failed zone=%s event_id=%s: %s",
                        _zid, _completed_id, _e,
                    )

        @callback
        def _on_outcome_fire(_now):
            self.hass.async_create_task(_write_outcome_temp(_now))

        @callback
        def _on_kw_fire(_now):
            self.hass.async_create_task(_write_outcome_kw(_now))

        self._reset_outcome_timers[zone_id] = async_call_later(
            self.hass, AC_RESET_OUTCOME_SETTLE_S, _on_outcome_fire,
        )
        # Second timer for the kW capture at the longer settle. Live in
        # its own registry so teardown can cancel independently and a
        # rapid re-reset cancels both.
        if not hasattr(self, "_reset_outcome_kw_timers"):
            self._reset_outcome_kw_timers = {}
        _prev_kw = self._reset_outcome_kw_timers.pop(zone_id, None)
        if _prev_kw is not None:
            try:
                _prev_kw()
            except Exception:  # noqa: BLE001
                pass
        self._reset_outcome_kw_timers[zone_id] = async_call_later(
            self.hass, AC_RESET_OUTCOME_KWH_SETTLE_S, _on_kw_fire,
        )

    # -------------------------------------------------------------------------
    # D-SCORE — delayed durability classifier
    # -------------------------------------------------------------------------

    def _schedule_write_durable(
        self,
        zone: ZoneState,
        event_id: int | None,
        kwh_rate_before: float | None,
        restore_dt: datetime,
    ) -> None:
        """Register a `_write_durable` callback to fire
        `_durability_window_min` minutes after the nudge_evaluated
        row is written. Cancelled + fired-early on re-nudge (see
        `_maybe_fire_durable_early`).
        """
        if event_id is None:
            return
        zone_id = zone.zone_id
        # Cancel any prior pending timer for this zone (defensive; the
        # re-nudge early-fire path should have already cleared it).
        prev = self._durable_timers.pop(zone_id, None)
        if prev is not None:
            try:
                prev()
            except Exception:  # noqa: BLE001
                pass
        # F22 fix-up: `kwh_rate_before` + `restore_dt` were stored on
        # the pending payload but never read by `_write_durable` —
        # removed. The kW verdict is computed from a live re-read at
        # fire time (see `_write_durable`), and elapsed is measured
        # from `started_ts`.
        _started_now = dt_util.now()
        self._durable_pending[zone_id] = {
            "event_id": int(event_id),
            "started_ts": _started_now,
        }
        # F5 (revised): reset the per-zone running-max kW so this new
        # window starts from a clean slate. `check_ac_reset` ticks (or
        # any other kW observer) will grow this monotonically until the
        # window fires and consumes it.
        self._nudge_running_max_kw[zone_id] = 0.0
        # A3 fix-up (2026-08-22): arm the persistent marker so a boot
        # inside this window can resume. Fire-and-forget — the
        # in-memory pending state above is authoritative for the
        # normal (no-crash) path; the persistent marker exists solely
        # for restart resumption.
        if self._db is not None:
            self.hass.async_create_task(
                self._db.set_in_flight_durable(
                    zone_id, int(event_id), _started_now.isoformat(),
                )
            )
        window_s = int(self._durability_window_min) * 60

        @callback
        def _on_durable_fire(_now, _zid=zone_id):
            self.hass.async_create_task(
                self._write_durable(_zid, truncated=False)
            )

        self._durable_timers[zone_id] = async_call_later(
            self.hass, window_s, _on_durable_fire,
        )

    def _maybe_fire_durable_early(self, zone_id: str) -> None:
        """Called from `_perform_soft_nudge` on entry. If a prior
        durability timer is pending on this zone, cancel it AND fire
        immediately with truncated=True — captures whatever the
        compressor was doing at re-nudge time."""
        cancel = self._durable_timers.pop(zone_id, None)
        if cancel is None:
            return
        try:
            cancel()
        except Exception:  # noqa: BLE001
            pass
        self.hass.async_create_task(
            self._write_durable(zone_id, truncated=True)
        )

    async def _write_durable(
        self, zone_id: str, *, truncated: bool,
    ) -> None:
        """UPDATE the `durable` + `durable_minutes` columns onto the
        specific nudge_evaluated row this callback closed over.

        F5 fix-up (2026-08-22, revised after operator ruling):
        the two branches DO differ semantically. Uncollapsed.

        - TRUNCATED (re-nudge before D):
              Interval check. `durable = 1` iff the running MAX kW
              observed over the elapsed window (sampled at the 5-min
              decision-tick cadence) stayed below the Gate-7 zone
              threshold. Instantaneous read at truncation time is
              guaranteed above threshold (a truncation happens BECAUSE
              Gate 7 fired a re-nudge), so an instantaneous rule
              scores every truncated row 0.
        - FULL-WINDOW (D reached, no re-nudge):
              Instantaneous read at fire time. `durable = 1` iff kW
              below Gate-7 threshold.

        Both branches use Gate-7 `zone.kwh_rate_threshold` (Invariant
        S) — NOT `AC_ACTIVELY_COOLING_KW_MIN` (0.5) — per plan
        Rev-2 B-M4.

        F15 fix-up: `durable_minutes` records the interval ACTUALLY
        measured (elapsed since restore) for both branches. A knob
        change between arm and fire would otherwise mis-record.

        On unreadable kW at fire time (full-window) OR no running-max
        samples (truncated): `durable` stays NULL.
        """
        pending = self._durable_pending.pop(zone_id, None)
        # F5: pop running_max regardless of DB availability so a NULL
        # DB doesn't leak the tracker dict.
        _running_max = self._nudge_running_max_kw.pop(zone_id, None)
        if pending is None or self._db is None:
            return
        now = dt_util.now()
        elapsed_min = int(
            (now - pending["started_ts"]).total_seconds() / 60
        )
        # F15: elapsed_min for both branches.
        durable_minutes = elapsed_min
        zone = self._zone_manager.zones.get(zone_id)
        _thresh = getattr(
            zone, "kwh_rate_threshold", AC_ACTIVELY_COOLING_KW_MIN,
        ) if zone is not None else AC_ACTIVELY_COOLING_KW_MIN
        durable_val: int | None
        if truncated:
            # INTERVAL check via running max. A tracker of 0.0 means
            # we never saw a kW sample in this window (rare — no tick
            # fired). Treat as NULL so we don't score a hold we can't
            # attest to.
            if _running_max is None or _running_max <= 0.0:
                durable_val = None
            else:
                durable_val = 0 if _running_max >= float(_thresh) else 1
        else:
            # INSTANTANEOUS read at fire time.
            kw_now: float | None = None
            try:
                if zone is not None:
                    kw_now = self._read_kwh_rate(zone, now)
            except Exception:  # noqa: BLE001
                kw_now = None
            if kw_now is None:
                durable_val = None
            else:
                durable_val = 0 if kw_now >= float(_thresh) else 1
        try:
            await self._db.update_ac_ramp_event_fields(
                pending["event_id"],
                durable=durable_val,
                durable_minutes=durable_minutes,
            )
        except Exception as _e:  # noqa: BLE001
            _LOGGER.debug(
                "_write_durable UPDATE failed for zone=%s event_id=%s: %s",
                zone_id, pending.get("event_id"), _e,
            )
        # A3 fix-up (2026-08-22): clear the persistent marker AFTER
        # the durable UPDATE lands. Ordering: a crash between the
        # UPDATE and this clear leaves the marker armed; next boot
        # sees started_ts > window_min ago and writes NULL over the
        # already-written value — idempotent no-op (byte-identical
        # for the durable row; the marker just gets cleared then).
        try:
            await self._db.clear_in_flight_durable_for_zone(zone_id)
        except Exception as _e:  # noqa: BLE001
            _LOGGER.debug(
                "clear_in_flight_durable failed for zone=%s: %s",
                zone_id, _e,
            )

    async def _perform_hard_reset_escalation(
        self,
        zone: ZoneState,
        kwh_rate_now: float,
        *,
        triggered_by: str = "auto",
        engage_lockout_on_cap: bool = True,
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
            await self._maybe_write_declined(
                zone_id, AC_RESET_DECLINED_FEATURE_DISABLED, now,
            )
            return

        # Arrester Operator-Immunity: hard reset is a corrective write
        # (cycles compressor off/on). Comfort Override + per-zone
        # immune-hold both must suppress. Escalation deferred until
        # governance resumes.
        if self._corrective_writes_suppressed(zone_id):
            zone.ramp_state = AC_RAMP_STATE_IDLE
            self._log_shave_skipped(
                zone.zone_name, zone_id, "hard_reset_escalation",
            )
            await self._maybe_write_declined(
                zone_id, AC_RESET_DECLINED_COMFORT_DEFERRED, now,
            )
            return

        if self._db is None:
            zone.ramp_state = AC_RAMP_STATE_IDLE
            return

        state = await self._db.get_ac_reset_state(zone_id)
        # F1 fix-up: night counter lives in the row keyed by the
        # current night's session_date. When session_date == today,
        # the night row IS the day row (single fetch). Post-midnight
        # they differ and the night row is fetched separately so the
        # 23:30/00:35 pair charge the SAME night bucket.
        session_date = self._night_session_date(now)
        today_date = state.get("date") or now.date().isoformat()
        if session_date != today_date:
            night_state = await self._db.get_ac_reset_state(
                zone_id, session_date,
            )
        else:
            night_state = state  # same row aliased

        # F4 fix-up: reorder — Gate A (true total-cap exhaustion) runs
        # BEFORE the partition check. In the pre-fix ordering the
        # partition check denied first whenever ANY partition was full,
        # and `total_used >= total_cap` (which requires BOTH partitions
        # full) could never be reached — `_engage_lockout` was dead
        # code and Gate 5's `lockout_flag` read (:3167) was unreachable.
        # Running Gate A first restores the semantic contract: partition
        # denial when only one bucket is full (no lockout), lockout only
        # when the compressor has truly exhausted every budget.
        #
        # F3 fix-up: apply `_hard_reset_daily_limit` as a ceiling on the
        # total cap (`=0` remains an explicit kill-switch that denies
        # every reset). This is the load-bearing dashboard knob that
        # was previously dead — no decision path read it.
        total_cap = int(self._reset_day_budget) + int(self._reset_night_budget)
        _limit = int(self._hard_reset_daily_limit)
        if _limit == 0:
            # Kill-switch semantics preserved verbatim: reset feature
            # disabled entirely via this knob. Report as decline (no
            # lockout latch — the operator can just re-arm the knob).
            await self._maybe_write_declined(
                zone_id, AC_RESET_DECLINED_FEATURE_DISABLED, now,
            )
            zone.ramp_state = AC_RAMP_STATE_IDLE
            return
        if _limit > 0:
            total_cap = min(total_cap, _limit)
        # Total-used counts BOTH partition rows (state["day_reset_count"]
        # on today + night_state["night_reset_count"] on the session row).
        # `hard_reset_count` is preserved as a legacy per-day tally on
        # today's row for backward-compatible sensor exposure.
        total_used = (
            int(state.get("day_reset_count", 0) or 0)
            + int(night_state.get("night_reset_count", 0) or 0)
        )
        if total_used >= total_cap:
            if engage_lockout_on_cap:
                await self._engage_lockout(zone, state)
            else:
                await self._maybe_write_declined(
                    zone_id, AC_RESET_DECLINED_TRUE_CAP_EXHAUSTED, now,
                )
                zone.ramp_state = AC_RAMP_STATE_IDLE
            return

        # D-PARTITION (A-C2 fix): partition-aware check runs AFTER
        # Gate A. On partition-only denial we write a `hard_reset_declined`
        # row and RETURN — `_engage_lockout` is NOT called. The night
        # reserve stays reachable when the day is exhausted.
        partition_ok, partition, part_reason = self._gate_partition_check(
            zone_id, now, state, night_state=night_state,
        )
        if not partition_ok:
            await self._maybe_write_declined(zone_id, part_reason, now)
            zone.ramp_state = AC_RAMP_STATE_IDLE
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
                await self._maybe_write_declined(
                    zone_id, AC_RESET_DECLINED_GLOBAL_MIN_INTERVAL, now,
                )
                zone.ramp_state = AC_RAMP_STATE_IDLE
                return

        # Both gates passed
        # D-PARTITION: charge the correct partition counter BEFORE
        # actuation (fail-closed compressor protection — a failed
        # off-call still consumes budget).
        # F1 fix-up: pass night_state so a night reset charges the
        # session-keyed row rather than today's row. When state and
        # night_state are the same object, one save covers both.
        partition_charged = self._increment_partition_counter(
            state, now, night_state=night_state,
        )
        state["hard_reset_count"] = int(state.get("hard_reset_count", 0)) + 1
        state["last_hard_reset_ts"] = now.isoformat()
        await self._db.save_ac_reset_state(state)
        # F1 fix-up: if the night row is a DIFFERENT row than today's
        # (post-midnight leg of a night session), persist ONLY the night
        # counter fields on that row via the targeted DAO. This avoids
        # clobbering any other state on the session-date row and works
        # even if that row does not yet exist (INSERT ... ON CONFLICT).
        if night_state is not state and partition_charged == "night":
            await self._db.update_ac_night_counter(
                zone_id,
                session_date,
                int(night_state.get("night_reset_count", 0) or 0),
            )
        self._track_zone_action(
            zone, AC_RAMP_EVENT_HARD_RESET_STARTED, triggered_by,
            kwh_before=kwh_rate_now,
        )
        # D5-A: enriched hard_reset_started row (telemetry only). Read
        # HA state ONCE and extract preset/mode. Silent on read failure.
        _hr_preset_before: str | None = None
        _hr_mode_before: str | None = None
        try:
            _cs = self.hass.states.get(zone.climate_entity)
            if _cs is not None:
                _hr_preset_before = _cs.attributes.get("preset_mode", "") or ""
                _hr_mode_before = _cs.state
        except Exception:  # noqa: BLE001 — defensive
            pass
        started_event_id = await self._db.log_ac_ramp_event(
            zone_id=zone_id,
            event_type=AC_RAMP_EVENT_HARD_RESET_STARTED,
            triggered_by=triggered_by,
            kwh_rate_before=kwh_rate_now,
            hard_reset_count_today=int(state["hard_reset_count"]),
            current_temp=zone.current_temperature,
            target_high=zone.target_temp_high,
            preset_before=_hr_preset_before,
            mode_before=_hr_mode_before,
            notes=(
                f"partition={partition_charged};"
                f"day={int(state.get('day_reset_count', 0) or 0)};"
                f"night={int(state.get('night_reset_count', 0) or 0)}"
            ),
        )
        # Keep ZoneState counter in sync for legacy sensor exposure
        zone.ac_reset_count_today = int(state["hard_reset_count"])

        # Stash the started event_id for D6 outcome back-fill (60s
        # settle callback UPDATEs onto this row).
        # F22 fix-up: `temp_start` removed — never read on the settle
        # side. If start-vs-settle delta is added later, re-add
        # deliberately and wire the reader.
        self._reset_outcome_pending[zone_id] = {
            "event_id": started_event_id,
            "target_high": zone.target_temp_high,
        }

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
        # F3 fix (2026-08-21, plan §3 row 8): capture the snapshot BEFORE
        # popping so the cancel restore path can also write the preset
        # back. Pre-cycle behaviour discarded the snapshot then emitted
        # setpoint only, which left preset_mode=manual on preset-based
        # thermostats (Bryant/Carrier) — a cancel that was supposed to
        # UN-do the nudge but only undid half of it. The excursion
        # snapshot on the token is the authoritative source (matches the
        # normal restore path); the legacy _nudge_pre_preset dict entry
        # is popped for cleanup symmetry.
        _cancel_snapshot_preset = self._nudge_pre_preset.pop(zone_id, "") or ""
        _cancel_token = self._nudge_excursion_tokens.get(zone_id)
        if _cancel_token is not None and _cancel_token.pre_preset:
            _cancel_snapshot_preset = _cancel_token.pre_preset

        original_target = None
        if self._db is not None:
            state = await self._db.get_ac_reset_state(zone_id)
            original_target = state.get("in_flight_nudge_original_target")

        if original_target is not None:
            # FIX B1: kind="temp" — cancel_nudge restore is a set_temperature.
            self.suppress(zone.climate_entity, kind="temp")
            try:
                # ARREST-COMFORT-1 §3.7 S8 (cancel_nudge restore): the
                # plan's rev-2 table labels this "AI-rules R2 residual"
                # and prescribes DEFER, but re-enumeration at build time
                # (2026-08-10) finds NO AI-rules R2 site in this file at
                # this or any line. The actual site here is the
                # cancel_nudge RESTORATION path — structurally identical
                # to S6 (nudge restore). Restoration moves BACK toward the
                # operator's original target; comfort-grace exists to
                # prevent yanking the operator, not to strand them at a
                # nudged +°F. Classified ALLOW to match S6's rationale;
                # discrepancy surfaced in the build report for review.
                await emit_set_temperature(
                    self.hass,
                    zone.climate_entity,
                    target_temp_low=zone.target_temp_low,
                    target_temp_high=float(original_target),
                    freeze_active=self._freeze_active(),
                    blocking=False,
                    site="S8_cancel_nudge_restore",
                    zone_id=zone_id,
                    reason="cancel_nudge_restore",
                )
            except Exception as e:
                _LOGGER.error(
                    "cancel_nudge restore failed for %s: %s",
                    zone.climate_entity, e,
                )

            # F3 fix (2026-08-21, plan §3 row 8): also restore the
            # snapshotted preset — cancel must be the full undo of the
            # nudge, not just the setpoint half. Unconditional per §13.5
            # (equality no-op when snapshot matches current). Suppression
            # re-opened with kind="preset" so the induced settle event
            # from set_preset_mode doesn't self-count as a user override.
            if _cancel_snapshot_preset:
                self.suppress(zone.climate_entity, kind="preset")
                try:
                    await emit_set_preset_mode(
                        self.hass,
                        zone.climate_entity,
                        _cancel_snapshot_preset,
                        blocking=True,
                        gate=None,
                        site="S8_cancel_nudge_preset_restore",
                        zone_id=zone_id,
                        reason="cancel_nudge_preset_restore",
                    )
                    _LOGGER.info(
                        "cancel_nudge preset restore on %s -> %s "
                        "(F3 fix — snapshot-restore, unconditional)",
                        zone.zone_name, _cancel_snapshot_preset,
                    )
                except Exception as e:  # noqa: BLE001
                    _LOGGER.error(
                        "cancel_nudge preset restore failed on %s: %s",
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
            # F18 fix-up (2026-08-22): also emit a `nudge_restored` row
            # so cancel-ended nudges show up in the restore-verdict
            # family (settled reader looks for the most recent
            # nudge_restored with restore_ok IS NULL). Pre-fix, a
            # cancel-ended nudge was invisible to the entire family
            # — analytics could not distinguish "no restore verdict
            # because cancel" from "no restore verdict because clobber
            # measurement lost".
            _cancel_preset_after: str | None = None
            _cancel_mode_after: str | None = None
            try:
                _cs_cancel = self.hass.states.get(zone.climate_entity)
            except Exception:  # noqa: BLE001
                _cs_cancel = None
            if _cs_cancel is not None:
                _cancel_preset_after = (
                    _cs_cancel.attributes.get("preset_mode", "") or ""
                )
                _cancel_mode_after = _cs_cancel.state
            if _cancel_snapshot_preset:
                if _cancel_preset_after is None:
                    _cancel_ok: bool | None = None
                else:
                    _cancel_ok = (_cancel_preset_after == _cancel_snapshot_preset)
            else:
                _cancel_ok = None
            await self._db.log_ac_ramp_event(
                zone_id=zone_id,
                event_type=AC_RAMP_EVENT_NUDGE_RESTORED,
                triggered_by=triggered_by,
                target_high=(
                    float(original_target)
                    if original_target is not None else None
                ),
                preset_after=_cancel_preset_after,
                mode_after=_cancel_mode_after,
                restore_ok=None,
                restore_ok_immediate=_cancel_ok,
                notes="triggered_by_cancel",
            )

        zone.ramp_state = AC_RAMP_STATE_IDLE
        _LOGGER.info(
            "Nudge cancelled on %s (triggered_by=%s)",
            zone.zone_name, triggered_by,
        )

        # HVAC-GOVERNED-EXCURSION-1 D3 (row 8, S8 cancel_nudge RETURN):
        # release the excursion lease on cancel. Same clearing semantics
        # as the timer-driven restore path.
        _ex_token = self._nudge_excursion_tokens.pop(zone_id, None)
        if _ex_token is not None:
            try:
                from . import hvac_excursion as _ex_mod  # noqa: PLC0415
                await _ex_mod.return_excursion(
                    _ex_token, trigger="cancel",
                )
            except Exception as _ret_exc:  # noqa: BLE001
                _LOGGER.debug(
                    "nudge cancel: return_excursion failed for %s: %s",
                    zone_id, _ret_exc,
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

            # HIGH-A2: NINTH-SITE GATE. Startup-ramp audit's direct
            # set_temperature write AND the _restore_after_nudge scheduling
            # both must consult _corrective_writes_suppressed. If Temp
            # Arrester Override is engaged at boot OR the zone has an
            # active immune-hold record (rare at boot since the in-memory
            # dict starts empty, but possible after a rapid reload where
            # the option-persisted marker gets restamped), the audit must
            # not re-write the pre-outage `original_target` over what the
            # operator asked us to leave alone.
            if self._corrective_writes_suppressed(zone_id):
                self._log_shave_skipped(
                    zone.zone_name, zone_id, "startup_ramp_audit",
                )
                await self._db.clear_ac_in_flight_nudge(zone_id)
                continue

            # HIGH-A2 second guard: if the operator re-set the thermostat
            # DURING the outage, the current setpoint will match neither
            # the nudged value nor `original_target`. In that case do NOT
            # clobber the operator's re-set — drop the stale row + log.
            try:
                current_st = self.hass.states.get(zone.climate_entity)
                current_high: float | None = None
                if current_st is not None:
                    raw = current_st.attributes.get("target_temp_high")
                    if raw is not None:
                        current_high = float(raw)
                nudged_high = row.get("nudged_target")
                orig_f = float(original_target)
                if (
                    current_high is not None
                    and nudged_high is not None
                    and abs(current_high - float(nudged_high)) > 0.4
                    and abs(current_high - orig_f) > 0.4
                ):
                    _LOGGER.info(
                        "Startup ramp audit: zone=%s current setpoint "
                        "%.1f differs from BOTH nudged %.1f and "
                        "original %.1f — operator re-set during outage; "
                        "dropping stale in-flight row without restore",
                        zone.zone_name, current_high,
                        float(nudged_high), orig_f,
                    )
                    await self._db.clear_ac_in_flight_nudge(zone_id)
                    continue
            except (TypeError, ValueError, AttributeError) as e:
                _LOGGER.debug(
                    "Startup ramp audit: state-read guard failed on %s: %s",
                    zone.climate_entity, e,
                )

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
                # FIX B1: kind="temp" — startup nudge restore is a set_temperature.
                self.suppress(zone.climate_entity, kind="temp")
                try:
                    # ARREST-COMFORT-1 §3.7 S9 (startup_ramp_audit restore):
                    # same reconciliation as S8 — plan's rev-2 table labels
                    # this "AI-rules downstream write" and prescribes DEFER,
                    # but the actual site is a boot-time RESTORATION path
                    # that puts the operator's pre-outage target back on
                    # the wire. Classified ALLOW to match S6 rationale.
                    await emit_set_temperature(
                        self.hass,
                        zone.climate_entity,
                        target_temp_low=zone.target_temp_low,
                        target_temp_high=float(original_target),
                        freeze_active=self._freeze_active(),
                        blocking=False,
                        site="S9_startup_ramp_audit_restore",
                        zone_id=zone_id,
                        reason="startup_ramp_audit_restore",
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
    # A3 — bounded restart resumption of in-flight durability windows
    # =========================================================================
    # Staleness cutoff: 6h. Rationale — the durability window is capped
    # at 180 min (F17.a Number entity max), so 6h is 2x the maximum
    # legitimate window. A marker older than that came from a crash long
    # enough ago that any reading would not represent the compressor's
    # behaviour during the intended window. Anything within 6h either
    # (a) already elapsed the window during downtime → immediate write
    # with a restart note, or (b) has a genuine remainder → re-arm.
    A3_STALENESS_CUTOFF_S: int = 6 * 3600

    async def async_startup_durable_audit(self) -> None:
        """Resume in-flight durability windows across HA restart.

        Bounds (per operator A3):
          - <=1 row per zone (DAO enforces; arming clears any prior).
          - No table scan (DAO WHERE-filters on the marker).
          - Immediate write from persisted data when window already
            elapsed; durable = NULL with restart note (we cannot
            retroactively sample kW; a NULL that says why is honest).
          - Re-arm only for a genuine remainder (elapsed < window).
          - Staleness cutoff at A3_STALENESS_CUTOFF_S.
          - Idempotent across rapid reboots (marker cleared same
            audit; re-boot before clear writes NULL over NULL = no-op).
          - Marker cleared last, AFTER the durable UPDATE lands (same
            ordering as `_write_durable` normal path).

        Called from HVAC coordinator first-decision-cycle after the
        zone manager is populated (sibling of async_startup_ramp_audit).
        """
        if self._db is None:
            return
        rows = await self._db.get_in_flight_durable_rows()
        if not rows:
            return
        now = dt_util.now()
        window_min = int(self._durability_window_min)
        for row in rows:
            zone_id = row["zone_id"]
            event_id = row.get("event_id")
            started_iso = row.get("started_ts")
            if event_id is None or started_iso is None:
                # Corrupted marker — clear defensively.
                await self._db.clear_in_flight_durable_for_zone(zone_id)
                continue
            try:
                started_dt = datetime.fromisoformat(started_iso)
            except (ValueError, TypeError):
                _LOGGER.warning(
                    "A3 audit: unparseable started_ts=%r for %s; clearing",
                    started_iso, zone_id,
                )
                await self._db.clear_in_flight_durable_for_zone(zone_id)
                continue
            elapsed_s = (now - started_dt).total_seconds()
            elapsed_min = int(elapsed_s / 60)
            # Staleness gate.
            if elapsed_s > self.A3_STALENESS_CUTOFF_S:
                _LOGGER.info(
                    "A3 audit: stale marker for %s (elapsed=%dmin > cutoff);"
                    " writing NULL and clearing",
                    zone_id, elapsed_min,
                )
                try:
                    await self._db.update_ac_ramp_event_fields(
                        int(event_id),
                        durable=None,
                        durable_minutes=elapsed_min,
                    )
                except Exception as _e:  # noqa: BLE001
                    _LOGGER.debug(
                        "A3 stale write failed zone=%s event_id=%s: %s",
                        zone_id, event_id, _e,
                    )
                await self._db.clear_in_flight_durable_for_zone(zone_id)
                continue
            # Elapsed >= window → immediate write, no re-arm.
            if elapsed_min >= window_min:
                try:
                    await self._db.update_ac_ramp_event_fields(
                        int(event_id),
                        durable=None,
                        durable_minutes=elapsed_min,
                    )
                except Exception as _e:  # noqa: BLE001
                    _LOGGER.debug(
                        "A3 elapsed write failed zone=%s event_id=%s: %s",
                        zone_id, event_id, _e,
                    )
                await self._db.clear_in_flight_durable_for_zone(zone_id)
                _LOGGER.info(
                    "A3 audit: window elapsed during downtime for %s "
                    "(elapsed=%dmin, window=%dmin); durable=NULL written",
                    zone_id, elapsed_min, window_min,
                )
                continue
            # Genuine remainder → re-arm the in-memory pending state
            # and schedule a callback for (window - elapsed). Do NOT
            # clear the persistent marker yet; `_write_durable` clears
            # it when the callback fires (same normal-path ordering).
            zone = self._zone_manager.zones.get(zone_id)
            if zone is None:
                # No live ZoneState for this zone (config changed
                # during downtime). Best-effort: clear the marker and
                # write NULL for the elapsed portion.
                try:
                    await self._db.update_ac_ramp_event_fields(
                        int(event_id),
                        durable=None,
                        durable_minutes=elapsed_min,
                    )
                except Exception:  # noqa: BLE001
                    pass
                await self._db.clear_in_flight_durable_for_zone(zone_id)
                continue
            self._durable_pending[zone_id] = {
                "event_id": int(event_id),
                "started_ts": started_dt,
            }
            # No historical running_max — start fresh from here. The
            # verdict at fire time will reflect the remainder-of-window
            # behaviour only, which is the best we can honestly claim.
            self._nudge_running_max_kw[zone_id] = 0.0
            remaining_s = int(max(1, (window_min * 60) - elapsed_s))

            @callback
            def _on_durable_fire(_now, _zid=zone_id):
                self.hass.async_create_task(
                    self._write_durable(_zid, truncated=False)
                )

            self._durable_timers[zone_id] = async_call_later(
                self.hass, remaining_s, _on_durable_fire,
            )
            _LOGGER.info(
                "A3 audit: re-armed durability window for %s "
                "(elapsed=%dmin, remaining=%ds, window=%dmin)",
                zone_id, elapsed_min, remaining_s, window_min,
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
        # Arrester Operator-Immunity — surface state for the operator
        # dashboard (per-zone immune-hold user + started_ts + Comfort
        # Override state + started_ts). Cheap: two dict reads.
        immune_holds = {
            zid: {
                "user": rec.get("user_name"),
                "person_entity": rec.get("person_entity"),
                "started_ts": (
                    rec.get("started_ts").isoformat()
                    if isinstance(rec.get("started_ts"), datetime) else None
                ),
            }
            for zid, rec in self._immune_holds.items()
        }
        return {
            "state": self.get_arrester_state(),
            "enabled": self._enabled,
            "ac_reset_enabled": self._ac_reset_enabled,
            "zones": zones_detail,
            "energy_coast": self._energy_coast,
            "energy_offset": self._energy_offset,
            "immune_persons_configured": list(self._immune_persons),
            "immune_holds_active": immune_holds,
            "temp_arrester_override_active": (
                self._temp_arrester_override_active
            ),
            "temp_arrester_override_suppressed_since": (
                self._temp_arrester_override_started_ts.isoformat()
                if isinstance(
                    self._temp_arrester_override_started_ts, datetime,
                )
                else None
            ),
        }
