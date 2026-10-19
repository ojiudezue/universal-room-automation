"""Room-tier fan-recheck state machine (fan-noise Mode-2 mitigation).

When a fan running in a room could be falsely holding mmwave "occupied" in
an empty room, this mechanism pauses the fan, rechecks whether mmwave falls
with airflow stopped, and drops occupancy if the room is actually empty.

Trigger conditions (D1), BLE-tier drop-authorization gate (D1.5), BLE ladder
(D2), state machine (D3), HVAC handshake (D4), cross-rule precedence (D5),
and restart resilience (D6) are detailed in
``docs/planning/PLANNING_fan_noise_mode2_ble_pause_recheck.md``.

Ownership: presence-tier owns this one actuation because the trigger and
verdict consumer (room-tier ``binary_sensor.<room>_occupied``) are both
presence-adjacent. ALL fan writes still delegate through
``hvac_fans.FanController._set_fan_state`` — no new fan write callsite.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later
from homeassistant.util import dt as dt_util

from ..const import (
    CONF_ENTRY_TYPE,
    CONF_SCANNER_AREAS,
    FAN_RECHECK_MANUAL_FAN_ON_FOLLOWUP_MIN,
    CONF_FAN_CONTROL_ENABLED,
    CONF_FAN_RECHECK_ARM_DELAY_S,
    CONF_FAN_RECHECK_COOLDOWN_S,
    CONF_FAN_RECHECK_ENABLED,
    CONF_FAN_RECHECK_FAMILY_SCALING_ENABLED,
    CONF_FAN_RECHECK_HVAC_SUPPRESS_S,
    CONF_FAN_RECHECK_L2_ALLOWED,
    CONF_FAN_RECHECK_MAX_PER_HOUR,
    CONF_FAN_RECHECK_MMWAVE_HISTORY_TICKS,
    CONF_FAN_RECHECK_SPINDOWN_S,
    CONF_FAN_RECHECK_TRUST_SENSORS_OK,
    CONF_FAN_RECHECK_WINDOW_S,
    CONF_FANS,
    CONF_MMWAVE_SENSORS,
    CONF_MOTION_SENSORS,
    CONF_OCCUPANCY_SENSORS,
    CONF_ROOM_FAN_RECHECK_ENABLED,
    CONF_ROOM_NAME,
    CONF_ROOM_TYPE,
    DEFAULT_FAN_RECHECK_ARM_DELAY_S,
    DEFAULT_FAN_RECHECK_COOLDOWN_S,
    DEFAULT_FAN_RECHECK_ENABLED,
    DEFAULT_FAN_RECHECK_FAMILY_SCALING_ENABLED,
    DEFAULT_FAN_RECHECK_HVAC_SUPPRESS_S,
    DEFAULT_FAN_RECHECK_L2_ALLOWED,
    DEFAULT_FAN_RECHECK_MAX_PER_HOUR,
    DEFAULT_FAN_RECHECK_MMWAVE_HISTORY_TICKS,
    DEFAULT_FAN_RECHECK_SPINDOWN_S,
    DEFAULT_FAN_RECHECK_TRUST_SENSORS_OK,
    DEFAULT_FAN_RECHECK_WINDOW_S,
    DEFAULT_RECHECK_FACTOR,
    DEFAULT_ROOM_FAN_RECHECK_ENABLED,
    DOMAIN,
    FAN_RECHECK_SUPPRESS_MARGIN_S,
    ENTRY_TYPE_COORDINATOR_MANAGER,
    ENTRY_TYPE_ROOM,
    ROOM_TYPE_BEDROOM,
    ROOM_TYPE_MEDIA_ROOM,
    ROOM_TYPE_RECHECK_FACTOR,
    STATE_RADAR_SOLE_TICK,
)
from ..const import fan_owner, room_automation_paused
from ._ble_corroboration import trustworthy_persons_in_room
from .house_state import HouseState
from .hvac_const import FAN_TRUST_STATES
from .sensor_capability import (
    SENSOR_FAMILY_UNKNOWN,
    capability_routing_enabled,
    family_recheck_factor,
)
from .signals import (
    SIGNAL_FAN_RECHECK_FINISHED,
    SIGNAL_FAN_RECHECK_STARTED,
)

_LOGGER = logging.getLogger(__name__)

STATE_IDLE = "idle"
STATE_ARMED = "armed"
STATE_PAUSED = "paused"
STATE_RESTORING = "restoring"
STATE_COOLDOWN = "cooldown"

OUTCOME_VACATED = "vacated"
OUTCOME_OCCUPIED_CONFIRMED = "occupied_confirmed"
# MEMORY-WRITERS-SILENT-DROP-1 fix-up #4: a terminal cycle that aborted
# after real ARMING (no verdict reached). Emitted ONLY from ARMED-path
# cancel sites; PAUSED-path cancels still produce an occupied_confirmed
# verdict via `_restore` (so no double row).
OUTCOME_ABORTED = "aborted"

LAYER_L1 = "L1"
LAYER_L2 = "L2"
LAYER_L3 = "L3"
LAYER_NONE = "none"

# room_type values refused across FAN_TRUST_STATES (sleep_state veto; JAYA-FAN-STILL-PHANTOM-1
# 2026-10-18 replaced the D1.5 all-day high_still_risk veto with this sleep scope).
HIGH_STILL_RISK_ROOM_TYPES = frozenset({ROOM_TYPE_BEDROOM, ROOM_TYPE_MEDIA_ROOM})


@dataclass
class _RoomCtx:
    """Per-room runtime context."""

    room_name: str
    entry_id: str
    state: str = STATE_IDLE
    state_entered_at: Optional[datetime] = None
    snapshot: Optional[dict] = None
    attempts: deque = field(default_factory=lambda: deque(maxlen=10))
    last_outcome: Optional[str] = None
    last_attempt_at: Optional[datetime] = None
    ble_ladder_layer: str = LAYER_NONE
    timer_unsub: Optional[Any] = None


class _EligibilitySink:
    """Sink protocol for the shared 9-gate evaluator (Advisory-2).

    The live driver path (``on_room_tick`` -> ``_is_eligible``) passes
    ``_LiveSink`` so veto counters, ``ctx.ble_ladder_layer`` writes, and
    ``_prune_attempts`` mutations happen as before. The read-only probe
    path (``is_recheck_eligible``, called from the room coordinator's D2
    demotion block) passes ``_INERT_SINK`` so the evaluator can be
    called at high frequency without perturbing observability counters
    or corrupting the ctx's stored BLE ladder / attempts state.
    """

    def veto(self, room_name: str, reason: str) -> bool:  # noqa: D401
        return False

    def set_ladder_layer(self, ctx: "_RoomCtx", layer: str) -> None:
        return

    def prune_attempts(self, ctx: "_RoomCtx", now: datetime) -> None:
        return


class _LiveSink(_EligibilitySink):
    """Live sink — routes every mutation to the real manager state."""

    def __init__(self, manager: "FanRecheckManager") -> None:
        self._mgr = manager

    def veto(self, room_name: str, reason: str) -> bool:
        return self._mgr._veto(room_name, reason)

    def set_ladder_layer(self, ctx: "_RoomCtx", layer: str) -> None:
        ctx.ble_ladder_layer = layer

    def prune_attempts(self, ctx: "_RoomCtx", now: datetime) -> None:
        self._mgr._prune_attempts(ctx, now)


# Module-level inert sink singleton — no mutation of any kind. Safe to
# share across calls / rooms because it holds no state.
_INERT_SINK = _EligibilitySink()


class FanRecheckManager:
    """State machine for room-tier fan-pause + clean recheck.

    Construction wires the manager but does no IO. ``async_setup`` rehydrates
    persisted state. ``shutdown`` cancels per-room timers + persists final
    state to DB.
    """

    def __init__(self, hass: HomeAssistant, presence_coord: Any) -> None:
        self.hass = hass
        self._presence = presence_coord
        self._rooms: dict[str, _RoomCtx] = {}
        self._setup_done: bool = False
        # Observability: RAM-only counters. Durable event history lives in
        # ura_activity_log (fan_recheck_arm / fan_recheck_outcome /
        # fan_recheck_cancel rows). Counters reset at boot; that's the point
        # — they gauge live gate pressure since restart. Denominator is the
        # eval counter, numerators are per-veto-reason counters.
        self._eval_counts: dict[str, int] = defaultdict(int)
        self._veto_counts: dict[str, dict[str, int]] = defaultdict(
            lambda: defaultdict(int)
        )
        # C4 Rev 2: rooms already WARNed for an unresolved sensor family
        # (once per room per boot).
        self._family_warned: set[str] = set()
        # MEMORY-WRITERS-SILENT-DROP-1 fix-up #2: follow-up probe
        # async_call_later unsubs. Captured so `shutdown()` can cancel
        # them (the state-machine timer lives on ``ctx.timer_unsub``;
        # these are separate one-shot probes scheduled after a verdict).
        self._followup_timer_unsubs: list[Any] = []

    # ---- observability helpers --------------------------------------------

    def _veto(self, room_name: str, reason: str) -> bool:
        """Increment a per-room veto counter. Returns False for chaining."""
        self._veto_counts[room_name][reason] += 1
        return False

    async def _log_activity(
        self,
        action: str,
        room_name: str,
        description: str,
        details: dict[str, Any] | None = None,
        importance: str = "info",
    ) -> None:
        """Fire one durable ura_activity_log row. Never raises."""
        try:
            activity_logger = self.hass.data.get(DOMAIN, {}).get(
                "activity_logger"
            )
            if not activity_logger:
                return
            await activity_logger.log(
                coordinator="room",
                action=action,
                description=description,
                room=room_name,
                importance=importance,
                details=details,
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug("fan_recheck activity_log failed", exc_info=True)

    def _emit_aborted_mem(
        self, ctx: _RoomCtx, reason: str,
    ) -> None:
        """Fix-up #4: write one `fan_recheck_outcome` row with
        verdict=aborted at ARMED-path cancel sites (where no verdict is
        reached). Rate-bound BY CONSTRUCTION — only fires after a real
        arming, so it inherits the same max-per-hour + cooldown envelope
        as any live recheck. Never raises.
        """
        try:
            from ..memory_writers import (
                write_fan_recheck_outcome as _write_fan_recheck_outcome,
            )
            try:
                from ..const import FAN_RECHECK_OUTCOME_WRITER_ENABLED
            except Exception:  # noqa: BLE001
                FAN_RECHECK_OUTCOME_WRITER_ENABLED = True  # type: ignore
            if not FAN_RECHECK_OUTCOME_WRITER_ENABLED:
                return
            house_state_now = getattr(self._presence, "house_state", None)
            _write_fan_recheck_outcome(
                self.hass,
                room_name=ctx.room_name,
                verdict=OUTCOME_ABORTED,
                reason=reason,
                fan_restored=None,
                manual_fan_on_followup=None,
                house_state=house_state_now,
                at=dt_util.now(),
            )
        except Exception:  # noqa: BLE001 — observational
            _LOGGER.debug(
                "FanRecheck %s: aborted mem write skipped",
                ctx.room_name, exc_info=True,
            )

    def _schedule_activity(
        self,
        action: str,
        room_name: str,
        description: str,
        details: dict[str, Any] | None = None,
        importance: str = "info",
    ) -> None:
        self.hass.async_create_task(
            self._log_activity(
                action, room_name, description, details, importance,
            ),
        )

    # ---- public API --------------------------------------------------------

    async def async_setup(self) -> None:
        """Rehydrate state from DB. Safe to call once after PC setup."""
        db = self.hass.data.get(DOMAIN, {}).get("database")
        if db is None:
            _LOGGER.debug("FanRecheck: no DB available — starting cold")
            self._setup_done = True
            return
        try:
            rows = await db.get_all_fan_recheck_state()
        except Exception as exc:  # noqa: BLE001 — defensive
            _LOGGER.warning("FanRecheck: rehydrate read failed: %s", exc)
            rows = []
        for row in rows or []:
            self._restore_row(row)
        self._setup_done = True
        _LOGGER.info(
            "FanRecheck: setup complete (rehydrated %d rooms)",
            len(self._rooms),
        )

    async def shutdown(self) -> None:
        """Cancel per-room timers + persist final state.

        Emits a terminal ``fan_recheck_cancel`` row for any room still in
        an in-flight state (ARMED / PAUSED / RESTORING) so the activity
        log carries a definitive tail for every armed cycle. Bumps
        ``last_attempt_at`` on the state row too so post-restart readers
        see the shutdown as the last attempt.
        """
        for ctx in list(self._rooms.values()):
            self._cancel_timer(ctx)
            # M-1 (review): PAUSED is NOT terminal at shutdown — a fresh
            # PAUSED state rehydrates and RESUMES on reboot, so emitting a
            # cancel here would double-terminate the cycle and bumping
            # last_attempt_at would corrupt the resumed cycle's
            # paused_duration_s. Only ARMED/RESTORING (which rehydrate to
            # idle) get the terminal row. Stale-PAUSED gets its terminal
            # from the rehydrate path instead.
            if ctx.state in (STATE_ARMED, STATE_RESTORING):
                ctx.last_attempt_at = dt_util.now()
                self._schedule_activity(
                    action="fan_recheck_cancel",
                    room_name=ctx.room_name,
                    description=(
                        f"Fan-recheck cancelled (shutdown in {ctx.state})"
                    ),
                    details={
                        "room": ctx.room_name,
                        "reason": f"shutdown_in_{ctx.state}",
                        "state_at_cancel": ctx.state,
                        "ble_ladder_layer": ctx.ble_ladder_layer,
                    },
                )
                # Fix-up #4: durable aborted mem row for a cycle that
                # arrested at shutdown without a verdict.
                self._emit_aborted_mem(
                    ctx, reason=f"shutdown_in_{ctx.state}",
                )
            await self._persist(ctx)
        # Fix-up #2: cancel every outstanding follow-up probe. Untracked
        # probes would survive teardown and fire ~5 min later against a
        # stale hass -> orphan write / warn-once churn.
        for unsub in list(self._followup_timer_unsubs):
            try:
                unsub()
            except Exception:  # noqa: BLE001
                pass
        self._followup_timer_unsubs.clear()
        _LOGGER.info("FanRecheck: shutdown — %d rooms persisted", len(self._rooms))

    def on_room_tick(self, room_coord: Any) -> None:
        """Called by PresenceCoordinator inference loop for each room.

        Cheap eligibility check. If eligible AND state is idle, schedule
        the arm transition. The state machine only actuates from the
        timer callbacks — this method is fast and non-blocking.
        """
        if not self._setup_done:
            return
        room_name = self._room_name_of(room_coord)
        if not room_name:
            return
        ctx = self._rooms.get(room_name)
        if ctx is None:
            ctx = _RoomCtx(
                room_name=room_name,
                entry_id=room_coord.entry.entry_id,
            )
            self._rooms[room_name] = ctx

        # In-flight states evaluate their own cancellation conditions inside
        # the timer callbacks; the tick-level path only fires for idle rooms.
        if ctx.state != STATE_IDLE:
            self._evaluate_cancellation_during_tick(ctx, room_coord)
            return

        self._eval_counts[room_name] += 1
        if not self._is_eligible(ctx, room_coord):
            return

        self.hass.async_create_task(
            self._enter_armed(ctx),
        )

    async def force_restore(self, room_name: str) -> None:
        """Operator escape hatch: immediate restore + cooldown."""
        ctx = self._rooms.get(room_name)
        if ctx is None:
            _LOGGER.info(
                "FanRecheck: force_restore for unknown room %s — no-op",
                room_name,
            )
            return
        if ctx.state in (STATE_IDLE, STATE_COOLDOWN):
            return
        await self._restore(ctx, outcome=OUTCOME_OCCUPIED_CONFIRMED, forced=True)

    def get_room_state(self, room_name: str) -> str:
        ctx = self._rooms.get(room_name)
        return ctx.state if ctx else STATE_IDLE

    def get_room_attrs(self, room_name: str) -> dict[str, Any]:
        ctx = self._rooms.get(room_name)
        # RAM-only observability counters (since-boot). Durable event log
        # lives in ura_activity_log; these are for live gauging.
        vetoes = dict(self._veto_counts.get(room_name, {}))
        evals = int(self._eval_counts.get(room_name, 0))
        if ctx is None:
            return {
                "fan_recheck_state": STATE_IDLE,
                "fan_recheck_last_outcome": None,
                "fan_recheck_last_attempt_iso": None,
                "fan_recheck_ble_ladder_layer": LAYER_NONE,
                "fan_recheck_eval_count": evals,
                "fan_recheck_veto_counts": vetoes,
            }
        return {
            "fan_recheck_state": ctx.state,
            "fan_recheck_last_outcome": ctx.last_outcome,
            "fan_recheck_last_attempt_iso": (
                ctx.last_attempt_at.isoformat() if ctx.last_attempt_at else None
            ),
            "fan_recheck_ble_ladder_layer": ctx.ble_ladder_layer,
            "fan_recheck_eval_count": evals,
            "fan_recheck_veto_counts": vetoes,
        }

    def get_aggregate_counters(self) -> dict[str, Any]:
        """Cross-room totals for a presence-level diagnostics surface.

        Reserved for the follow-up presence-level diagnostics surface —
        the 2026-07-18 fan-recheck observability analysis memo (section 9)
        consumes this. Not wired to any live sensor yet by design;
        intentionally kept as a manager-level helper. (Review L2.)
        """
        total_evals = sum(self._eval_counts.values())
        agg: dict[str, int] = defaultdict(int)
        for room_map in self._veto_counts.values():
            for reason, n in room_map.items():
                agg[reason] += n
        return {
            "fan_recheck_eval_count_total": total_evals,
            "fan_recheck_veto_counts_total": dict(agg),
            "fan_recheck_rooms_tracked": len(
                set(self._eval_counts) | set(self._veto_counts)
            ),
        }

    # ---- public read-only eligibility probe (D2 defer gate) ---------------

    def is_recheck_eligible(self, room_name: str) -> bool:
        """Return True iff a periodic tick RIGHT NOW would arm this room.

        Side-effect-free variant of ``_is_eligible`` used by the room
        coordinator's D2 mmwave-fan demotion block (``coordinator.py``
        ~:3369-3402) to defer demotion when the recheck could plausibly
        arm this tick. Must NOT mutate ``self._veto_counts``,
        ``self._eval_counts``, ``ctx.ble_ladder_layer``, or
        ``ctx.attempts`` — those are reserved for the live ``on_room_tick``
        driver path so the observability signal reflects the real cadence.

        Room-coord resolution: mirrors the D2 call site
        (``coordinator.py:3354``). If the room-coord is not yet
        constructed OR the eligibility call raises, return False (D2
        fires as backstop). Symmetric with the existing
        ``recheck_in_flight`` guard's exception default.
        """
        if not self._setup_done:
            return False
        try:
            room_coord = self._room_coord_for(room_name)
            if room_coord is None:
                return False
            ctx = self._rooms.get(room_name)
            if ctx is None:
                # Ephemeral read-only ctx — never inserted into ``self._rooms``.
                ctx = _RoomCtx(
                    room_name=room_name,
                    entry_id=getattr(room_coord.entry, "entry_id", ""),
                )
            return self._evaluate_eligibility(
                ctx, room_coord, sink=_INERT_SINK,
            )
        except Exception:  # noqa: BLE001 — defensive: D2 fires as backstop
            _LOGGER.debug(
                "FanRecheck: is_recheck_eligible(%s) raised — defaulting False",
                room_name,
                exc_info=True,
            )
            return False

    # ---- internals: eligibility -------------------------------------------

    def _is_eligible(self, ctx: _RoomCtx, room_coord: Any) -> bool:
        """Evaluate all 9 trigger conditions (D1). Live driver path — mutates
        veto counters and ``ctx.ble_ladder_layer`` for observability. See
        ``is_recheck_eligible`` for the side-effect-free read-only variant.
        """
        return self._evaluate_eligibility(
            ctx, room_coord, sink=_LiveSink(self),
        )

    def _evaluate_eligibility(
        self,
        ctx: _RoomCtx,
        room_coord: Any,
        sink: "_EligibilitySink",
    ) -> bool:
        """Shared 9-gate evaluator. ALL mutations route through ``sink``.

        Callers:
        - ``_is_eligible`` (live, mutates ctx + veto counters).
        - ``is_recheck_eligible`` (inert, read-only for D2 defer gate).

        Advisory-2 contract: every ``sink.veto(...)``,
        ``sink.set_ladder_layer(...)``, and ``sink.prune_attempts(...)``
        MUST be routed through the sink. Any bare ``self._veto(...)`` /
        ``ctx.ble_ladder_layer = ...`` / ``self._prune_attempts(...)`` in
        this method silently corrupts the inert-path purity and is a bug.
        """
        room_name = ctx.room_name
        merged = self._merged_config(room_coord)
        # The 7 timing knobs live on the CM entry, not the room entry.
        # Read them from the coordinator-tier accessor — anything operator-
        # tuned via the coordinator_presence options step lands here.
        timing = self._timing_config()

        # Master + per-room kill switches.
        master_enabled = self._master_enabled()
        if not master_enabled:
            return sink.veto(room_name, "master_off")
        if not merged.get(
            CONF_ROOM_FAN_RECHECK_ENABLED, DEFAULT_ROOM_FAN_RECHECK_ENABLED,
        ):
            return sink.veto(room_name, "room_disabled")
        # D5 / HVAC Batch D (v5.103.24): the recheck follows the OWNER
        # (const.fan_owner). A person-owned fan (Fan Mode "Off")
        # is never paused — the same rule for HVAC- and room-owned rooms.
        if fan_owner(merged) is None:
            return sink.veto(room_name, "fan_control_off")
        # ROOM-OVERRIDE-SWITCH-FORGOTTEN-1 (F2): a paused room (Automation
        # switch off / Manual Mode on) never arms. A recheck already PAUSED
        # is not cut short — its restore is a discharge and must run.
        if room_automation_paused(room_coord):
            return sink.veto(room_name, "room_paused")

        # Sleep-scoped veto (FAN-RECHECK-SLEEP-VETO-SCOPE-1, folded in
        # 2026-08-19): previously an unconditional ``house_state ==
        # SLEEP`` veto suppressed the recheck house-wide, which also
        # suppressed the very non-bedroom rooms this feature was built for
        # (Study A, Living Room). Narrow the veto to the same predicate
        # ``hvac_fans.py:1205-1209`` uses to hold bedroom fans on across
        # ``FAN_TRUST_STATES = {home_night, sleep, waking}``: pausing a
        # fan the HVAC layer is deliberately keeping on would fight the
        # v4.7.13 keep-on contract. For non-bedroom rooms the recheck is
        # free to arm through sleep — no v4.7.13 obligation applies.
        # JAYA-FAN-STILL-PHANTOM-1 (2026-10-18): widened from bedroom-only
        # to HIGH_STILL_RISK_ROOM_TYPES (bedroom + media_room). Media is
        # included for still-sleeper protection, NOT the v4.7.13 HVAC
        # keep-on contract (bedroom-only in hvac_fans). This sleep-scoped
        # refusal REPLACES the old all-day ``high_still_risk`` veto.
        room_type_early = merged.get(CONF_ROOM_TYPE, "")
        house_state = getattr(self._presence, "house_state", "")
        if (
            house_state in FAN_TRUST_STATES
            and room_type_early in HIGH_STILL_RISK_ROOM_TYPES
        ):
            return sink.veto(room_name, "sleep_state")

        data = getattr(room_coord, "data", None) or {}
        if not data.get("occupied"):
            return sink.veto(room_name, "not_occupied")

        # Condition 2: mmwave-sole AND for N consecutive ticks.
        ticks_required = int(
            timing.get(
                CONF_FAN_RECHECK_MMWAVE_HISTORY_TICKS,
                DEFAULT_FAN_RECHECK_MMWAVE_HISTORY_TICKS,
            )
        )
        # Override Occupied veto (B-M1): the operator's Occupied-override is
        # intent, not a sensor fact — the capability radar-sole ring can't
        # see it (label-only state). Applies on BOTH routing branches, and
        # whether the master kill switch is on or off (operator intent wins).
        # The old label-ring N-tick gate rejected the "override" label as
        # `s != "mmwave"`; the capability ring doesn't, so re-add the veto
        # explicitly here against the label ring.
        try:
            label_ring = list(room_coord.recent_occupancy_sources()) \
                if hasattr(room_coord, "recent_occupancy_sources") else []
        except Exception:  # noqa: BLE001
            label_ring = []
        if any(s == "override" for s in label_ring[-ticks_required:]):
            return sink.veto(room_name, "override_occupied")
        if capability_routing_enabled():
            # OCCUPANCY-SOURCE-FOLLOWS-CAPABILITY-1 D4: N-tick history of
            # the capability radar-sole bool. Fail-closed: a coordinator
            # without the ring, or a ring shorter than N, vetoes
            # "capability_bootstrap" (no fallback to the LIST label).
            try:
                sole_ring = list(room_coord.recent_radar_sole_ring())
            except Exception:  # noqa: BLE001 — fail-closed
                sole_ring = []
            if len(sole_ring) < ticks_required:
                return sink.veto(room_name, "capability_bootstrap")
            if not all(sole_ring[-ticks_required:]):
                return sink.veto(room_name, "not_radar_sole")
        else:
            recent = []
            if hasattr(room_coord, "recent_occupancy_sources"):
                recent = list(room_coord.recent_occupancy_sources())
            if len(recent) < ticks_required:
                return sink.veto(room_name, "mmwave_history_short")
            if any(s != "mmwave" for s in recent[-ticks_required:]):
                return sink.veto(room_name, "not_mmwave_sole")

        # Condition 3: at least one fan entity AND one is ON.
        fans = merged.get(CONF_FANS) or []
        if isinstance(fans, str):
            fans = [fans]
        fans = [f for f in fans if f]
        if not fans:
            return sink.veto(room_name, "no_fan_configured")
        if not any(self._is_entity_on(f) for f in fans):
            return sink.veto(room_name, "no_fan_on")

        # Condition 7: boot-settle gate.
        if not getattr(self._presence, "_boot_settle_done", True):
            return sink.veto(room_name, "boot_settle")

        # Conditions 8 + 9: EgressManager pause + manual_off_cooldown_until
        # are evaluated by FanController itself; we mirror condition 9 here
        # so we don't even try to schedule a pause for a recently-killed fan.
        if self._fan_in_manual_cooldown(room_name):
            return sink.veto(room_name, "manual_off_cooldown")
        # Fan-noise Rev 2 C1a (Finding 2): never ARM a pause against a live
        # manual-ON hold — operator intent beats recheck inference. The
        # restore-time check in `hvac_fans.restore_after_recheck` is the
        # backstop for a hold that lands DURING the pause.
        if self._fan_in_manual_on_hold(room_name):
            return sink.veto(room_name, "manual_on_hold_live")
        # Fan-noise Rev 2 C3 Part B: never ARM against a fan the room's
        # ActuatorReconciler has quarantined as flapping (unreliable).
        if self._fan_in_actuator_quarantine(room_coord, fans):
            return sink.veto(room_name, "fan_quarantined")

        # Condition 5: rate limit.
        max_per_hour = int(
            timing.get(
                CONF_FAN_RECHECK_MAX_PER_HOUR,
                DEFAULT_FAN_RECHECK_MAX_PER_HOUR,
            )
        )
        if max_per_hour > 0:
            now = dt_util.now()
            sink.prune_attempts(ctx, now)
            if len(ctx.attempts) >= max_per_hour:
                return sink.veto(room_name, "rate_cap")

        # Condition 4: BLE-tier drop-authorization gate (D1.5).
        person_coord = self.hass.data.get(DOMAIN, {}).get("person_coordinator")
        if person_coord is None:
            return sink.veto(room_name, "no_person_coord")

        # L1 veto applies in EVERY tier.
        # Operator scope addition 2026-10-18: "in the room" also covers
        # persons resolved to a room whose area this room lists in its
        # CONF_SCANNER_AREAS (Jaya Bedroom -> jaya_bathroom).
        l1_persons = self._l1_persons(person_coord, room_name, merged)
        if l1_persons:
            sink.set_ladder_layer(ctx, LAYER_L1)
            return sink.veto(room_name, "ble_l1")

        # Tier classification.
        try:
            ble_tier = int(person_coord.get_ble_tier(room_name))
        except Exception:  # noqa: BLE001
            ble_tier = 0

        l2_hit_adj = self._has_trustworthy_phone_in_adjacent(person_coord, room_name)

        if ble_tier == 1:
            # Tier-1 path. L3 strongest; L2 weak-authorize requires opt-in.
            # (JAYA-FAN-STILL-PHANTOM-1: the all-day high_still_risk
            # rejection was removed; bedroom/media are refused only in
            # FAN_TRUST_STATES via the sleep_state predicate above.)
            try:
                zone_rooms = self._zone_rooms_for(room_name) or [room_name]
                zone_persons = self._trustworthy_persons_in_zone(
                    person_coord, zone_rooms,
                )
            except Exception:  # noqa: BLE001
                zone_persons = []
            if not zone_persons:
                sink.set_ladder_layer(ctx, LAYER_L3)
                return True
            if l2_hit_adj and merged.get(
                CONF_FAN_RECHECK_L2_ALLOWED, DEFAULT_FAN_RECHECK_L2_ALLOWED,
            ):
                sink.set_ladder_layer(ctx, LAYER_L2)
                return True
            sink.set_ladder_layer(ctx, LAYER_NONE)
            return sink.veto(room_name, "ble_l2")

        # Tier-2 / Tier-0: positive L2 in adjacent rooms is an UNCONDITIONAL veto.
        if l2_hit_adj:
            sink.set_ladder_layer(ctx, LAYER_L2)
            return sink.veto(room_name, "ble_l2")

        # Sensors-only authorize gate.
        if not merged.get(
            CONF_FAN_RECHECK_TRUST_SENSORS_OK,
            DEFAULT_FAN_RECHECK_TRUST_SENSORS_OK,
        ):
            sink.set_ladder_layer(ctx, LAYER_NONE)
            return sink.veto(room_name, "trust_sensors_off")

        sink.set_ladder_layer(ctx, LAYER_NONE)
        return True

    # ---- internals: state transitions -------------------------------------

    async def _enter_armed(self, ctx: _RoomCtx) -> None:
        timing = self._timing_config()
        arm_delay = int(
            timing.get(
                CONF_FAN_RECHECK_ARM_DELAY_S,
                DEFAULT_FAN_RECHECK_ARM_DELAY_S,
            )
        )
        ctx.state = STATE_ARMED
        ctx.state_entered_at = dt_util.now()
        await self._persist(ctx)
        async_dispatcher_send(
            self.hass,
            SIGNAL_FAN_RECHECK_STARTED,
            {"room": ctx.room_name, "ble_ladder_layer": ctx.ble_ladder_layer},
        )
        _LOGGER.info(
            "FanRecheck %s: armed (layer=%s, arm_delay=%ds)",
            ctx.room_name, ctx.ble_ladder_layer, arm_delay,
        )
        self._schedule_activity(
            action="fan_recheck_arm",
            room_name=ctx.room_name,
            description=f"Fan-recheck armed (layer={ctx.ble_ladder_layer})",
            details={
                "room": ctx.room_name,
                "ble_ladder_layer": ctx.ble_ladder_layer,
                "arm_delay_s": arm_delay,
            },
        )

        async def _on_arm_expiry(_now):
            ctx.timer_unsub = None
            await self._on_arm_expired(ctx)

        self._schedule_timer(ctx, arm_delay, _on_arm_expiry)

    async def _on_arm_expired(self, ctx: _RoomCtx) -> None:
        room_coord = self._room_coord_for(ctx.room_name)
        if room_coord is None:
            # Terminal for the armed cycle — stamp last_attempt_at so state
            # row + activity log agree on "this was the last attempt".
            ctx.last_attempt_at = dt_util.now()
            self._schedule_activity(
                action="fan_recheck_cancel",
                room_name=ctx.room_name,
                description="Fan-recheck arm expired (room coord missing)",
                details={
                    "room": ctx.room_name,
                    "reason": "arm_expired_no_room_coord",
                    "state_at_cancel": ctx.state,
                    "ble_ladder_layer": ctx.ble_ladder_layer,
                },
            )
            self._emit_aborted_mem(ctx, reason="arm_expired_no_room_coord")
            await self._enter_cooldown(ctx)
            return
        # Cancellation re-evaluation: if conditions no longer hold, abandon.
        if not self._still_armed_eligible(ctx, room_coord):
            ctx.last_attempt_at = dt_util.now()
            self._schedule_activity(
                action="fan_recheck_cancel",
                room_name=ctx.room_name,
                description="Fan-recheck arm expired (preconditions cleared)",
                details={
                    "room": ctx.room_name,
                    "reason": "arm_expired_ineligible",
                    "state_at_cancel": ctx.state,
                    "ble_ladder_layer": ctx.ble_ladder_layer,
                },
            )
            self._emit_aborted_mem(ctx, reason="arm_expired_ineligible")
            await self._enter_cooldown(ctx)
            return
        await self._enter_paused(ctx, room_coord)

    async def _enter_paused(self, ctx: _RoomCtx, room_coord: Any) -> None:
        merged = self._merged_config(room_coord)
        timing = self._timing_config()
        spindown = int(
            timing.get(
                CONF_FAN_RECHECK_SPINDOWN_S,
                DEFAULT_FAN_RECHECK_SPINDOWN_S,
            )
        )
        # _recheck_factor still reads CONF_ROOM_TYPE from the room entry
        # (per-room property — not coordinator-tier). C4 Rev 2: times the
        # room's dominant presence-sensor family factor.
        window = self._effective_window_s(merged, timing, ctx.room_name)
        hvac_suppress = int(
            timing.get(
                CONF_FAN_RECHECK_HVAC_SUPPRESS_S,
                DEFAULT_FAN_RECHECK_HVAC_SUPPRESS_S,
            )
        )

        # Review B-1: the suppress window (HVAC tier AND the room-tier
        # note_recheck_pause backstop, both fed this ISO) must cover the
        # whole pause, which C4 family scaling can stretch past the knob.
        hvac_suppress = max(
            hvac_suppress, spindown + window + FAN_RECHECK_SUPPRESS_MARGIN_S,
        )
        suppress_until = (
            dt_util.now() + timedelta(seconds=hvac_suppress)
        ).isoformat()

        snapshot = await self._fan_pause(ctx.room_name, suppress_until)
        if snapshot is None:
            _LOGGER.info(
                "FanRecheck %s: no managed fan in FanController — abandoning",
                ctx.room_name,
            )
            # A3 silent-exit fix: this was the terminal transition out of
            # ARMED for this cycle (arm-expired path reached _enter_paused
            # then bailed because FanController had no managed row). Emit a
            # terminal cancel row + bump last_attempt_at so the state row
            # + activity log both reflect the attempt.
            ctx.last_attempt_at = dt_util.now()
            self._schedule_activity(
                action="fan_recheck_cancel",
                room_name=ctx.room_name,
                description=(
                    "Fan-recheck cancelled (no managed fan in FanController)"
                ),
                details={
                    "room": ctx.room_name,
                    "reason": "no_managed_fan",
                    "state_at_cancel": ctx.state,
                    "ble_ladder_layer": ctx.ble_ladder_layer,
                },
            )
            self._emit_aborted_mem(ctx, reason="no_managed_fan")
            await self._enter_cooldown(ctx)
            return

        ctx.snapshot = snapshot
        ctx.state = STATE_PAUSED
        ctx.state_entered_at = dt_util.now()
        ctx.last_attempt_at = ctx.state_entered_at
        ctx.attempts.append(ctx.state_entered_at)
        await self._persist(ctx)
        _LOGGER.info(
            "FanRecheck %s: paused (spindown=%ds, window=%ds)",
            ctx.room_name, spindown, window,
        )

        total_observe = spindown + window
        observe_start = dt_util.now() + timedelta(seconds=spindown)

        async def _on_pause_window_done(_now):
            ctx.timer_unsub = None
            await self._on_pause_window_done(ctx, observe_start)

        self._schedule_timer(ctx, total_observe, _on_pause_window_done)

    async def _on_pause_window_done(
        self, ctx: _RoomCtx, observe_start: datetime,
    ) -> None:
        room_coord = self._room_coord_for(ctx.room_name)
        outcome = OUTCOME_OCCUPIED_CONFIRMED
        if room_coord is not None:
            data = getattr(room_coord, "data", None) or {}
            # If mmwave (the lone driver pre-pause) no longer drives occupancy
            # after airflow stopped, the fan was the culprit -> vacated.
            if capability_routing_enabled():
                # OCCUPANCY-SOURCE-FOLLOWS-CAPABILITY-1 D4: vacated iff
                # no radar-bearing entity (any CONF list) is on NOW —
                # live on-set, not the label, not presence_detected.
                try:
                    radar_on = bool(room_coord.any_radar_bearing_on_now())
                except Exception:  # noqa: BLE001 — fail-safe: not vacated
                    radar_on = True
                if not radar_on:
                    outcome = OUTCOME_VACATED
            else:
                current_source = str(data.get("occupancy_source", "none"))
                presence_now = bool(data.get("presence_detected", False))
                if not presence_now and current_source != "mmwave":
                    outcome = OUTCOME_VACATED
        await self._restore(ctx, outcome=outcome)

    async def _restore(
        self, ctx: _RoomCtx, outcome: str, forced: bool = False,
    ) -> None:
        ctx.state = STATE_RESTORING
        ctx.state_entered_at = dt_util.now()
        ctx.last_outcome = outcome
        await self._persist(ctx)

        # Fan-noise Rev 2 C1a: a VACATED verdict leaves the fan OFF (the
        # person it ran for has left) but still runs every restore
        # discharge duty in the HVAC FanController. All other exits
        # (occupied_confirmed, forced, cancel-driven) restore ON.
        leave_off = outcome == OUTCOME_VACATED and not forced
        await self._fan_restore(
            ctx.room_name, ctx.snapshot, leave_off=leave_off,
        )

        if outcome == OUTCOME_VACATED and not forced:
            room_coord = self._room_coord_for(ctx.room_name)
            if room_coord is not None and hasattr(
                room_coord, "apply_fan_recheck_release",
            ):
                try:
                    room_coord.apply_fan_recheck_release()
                    room_coord.async_set_updated_data(room_coord.data)
                except Exception as exc:  # noqa: BLE001
                    _LOGGER.warning(
                        "FanRecheck %s: apply_fan_recheck_release failed: %s",
                        ctx.room_name, exc,
                    )

        async_dispatcher_send(
            self.hass,
            SIGNAL_FAN_RECHECK_FINISHED,
            {"room": ctx.room_name, "outcome": outcome},
        )
        _LOGGER.info(
            "FanRecheck %s: outcome=%s (forced=%s)",
            ctx.room_name, outcome, forced,
        )
        # Durable observability event: one row per completed recheck.
        paused_duration_s: Optional[int] = None
        if ctx.last_attempt_at is not None and ctx.state_entered_at is not None:
            try:
                paused_duration_s = int(
                    (ctx.state_entered_at - ctx.last_attempt_at).total_seconds()
                )
            except Exception:  # noqa: BLE001
                paused_duration_s = None
        cancel_driven = bool(getattr(ctx, "_cancel_driven", False))
        self._schedule_activity(
            action="fan_recheck_outcome",
            room_name=ctx.room_name,
            description=f"Fan-recheck outcome: {outcome}",
            details={
                "room": ctx.room_name,
                "outcome": outcome,
                "forced": forced,
                "ble_ladder_layer": ctx.ble_ladder_layer,
                "paused_duration_s": paused_duration_s,
                # Review L1: true when this outcome row is the tail of a
                # PAUSED-path cancel (motion/L1 mid-flight). Analytics join
                # on this to dedupe the cancel+outcome pair as ONE terminal
                # event.
                "cancel_driven": cancel_driven,
            },
        )
        # MEMORY-WRITERS-SILENT-DROP-1 D2 — observational episode mirror of
        # the activity_log row. One row per completed recheck. Rate-bound
        # BY CONSTRUCTION via the recheck state machine's own cooldown +
        # max-per-hour cap. Memory-ineligible: never read on an actuation
        # path (arch §8). Follow-up manual_fan_on sampling is scheduled
        # FAN_RECHECK_MANUAL_FAN_ON_FOLLOWUP_MIN minutes after the verdict.
        try:
            merged_cfg = {}
            room_coord = self._room_coord_for(ctx.room_name)
            if room_coord is not None:
                merged_cfg = self._merged_config(room_coord)
            radar_factor = self._family_factor(
                merged_cfg, self._timing_config(), ctx.room_name,
            ) if merged_cfg else None
            house_state_now = getattr(self._presence, "house_state", None)
            # Verdict reason: cancel-driven vs max-out vs observed vacancy.
            if cancel_driven:
                _reason = "cancel_driven"
            elif forced:
                _reason = "forced"
            else:
                _reason = "pause_window_complete"
            _fan_restored = not leave_off
            _window = self._effective_window_s(
                merged_cfg, self._timing_config(), ctx.room_name,
            ) if merged_cfg else None

            # Lazy import — some test harnesses load this module under a
            # non-package alias ("ura_fanrecheck_pkg"), which breaks a
            # top-level relative import. Inline import is cheap, HA has
            # already paid the import cost for memory_writers elsewhere.
            from ..memory_writers import (
                write_fan_recheck_outcome as _write_fan_recheck_outcome,
            )

            # Fix-up #2 + #3: write the verdict row IMMEDIATELY at verdict
            # time (NOT 5 min later from the probe path) with
            # ``manual_fan_on_followup=None`` and ``at=verdict_at`` — the
            # row carries the verdict's own timestamp regardless of probe
            # scheduling or restart. The follow-up probe writes a SEPARATE
            # second row (distinct source_ref via ``:followup`` suffix)
            # with the sampled manual_fan_on_followup bool.
            verdict_at = dt_util.now()

            def _emit(
                manual_followup: Optional[bool],
                *, suffix: str = "",
            ) -> None:
                _write_fan_recheck_outcome(
                    self.hass,
                    room_name=ctx.room_name,
                    verdict=outcome,
                    reason=_reason,
                    pause_window_s=_window,
                    radar_family_factor=radar_factor,
                    fan_restored=_fan_restored,
                    manual_fan_on_followup=manual_followup,
                    house_state=house_state_now,
                    at=verdict_at,
                    source_ref_suffix=suffix,
                )

            # Verdict row — immediate.
            _emit(None)

            # If the writer is disabled upstream nothing lands; also skip
            # scheduling the follow-up probe in that case for parsimony.
            try:
                from ..const import FAN_RECHECK_OUTCOME_WRITER_ENABLED
            except Exception:  # noqa: BLE001
                FAN_RECHECK_OUTCOME_WRITER_ENABLED = True  # type: ignore
            if FAN_RECHECK_OUTCOME_WRITER_ENABLED:
                async def _followup_probe(_now):
                    try:
                        manual_hold = self._fan_in_manual_on_hold(
                            ctx.room_name,
                        )
                    except Exception:  # noqa: BLE001
                        manual_hold = None
                    _emit(manual_hold, suffix=":followup")

                unsub = async_call_later(
                    self.hass,
                    FAN_RECHECK_MANUAL_FAN_ON_FOLLOWUP_MIN * 60,
                    _followup_probe,
                )
                # Fix-up #2: track so shutdown() can cancel. Untracked
                # async_call_later survives shutdown and can fire after
                # the manager is torn down (orphan write).
                if unsub is not None:
                    self._followup_timer_unsubs.append(unsub)
        except Exception:  # noqa: BLE001 — observational, never raises
            _LOGGER.debug(
                "FanRecheck %s: fan_recheck_outcome memory write skipped",
                ctx.room_name, exc_info=True,
            )

        # Reset the marker so the next arm/outcome cycle doesn't inherit it.
        if cancel_driven:
            ctx._cancel_driven = False
        ctx.snapshot = None
        await self._enter_cooldown(ctx)

    async def _enter_cooldown(self, ctx: _RoomCtx) -> None:
        timing = self._timing_config()
        cooldown_s = int(
            timing.get(
                CONF_FAN_RECHECK_COOLDOWN_S,
                DEFAULT_FAN_RECHECK_COOLDOWN_S,
            )
        )
        ctx.state = STATE_COOLDOWN
        ctx.state_entered_at = dt_util.now()
        await self._persist(ctx)

        async def _on_cooldown_done(_now):
            ctx.timer_unsub = None
            ctx.state = STATE_IDLE
            ctx.state_entered_at = dt_util.now()
            await self._persist(ctx)
            _LOGGER.info("FanRecheck %s: cooldown done -> idle", ctx.room_name)

        self._schedule_timer(ctx, cooldown_s, _on_cooldown_done)

    # ---- cancellation during in-flight states -----------------------------

    def _evaluate_cancellation_during_tick(
        self, ctx: _RoomCtx, room_coord: Any,
    ) -> None:
        """Cancel armed/paused if L1 fires or motion/occupancy returns.

        Called from the per-tick path. Triggers async restore/abandon when
        the trigger preconditions no longer hold mid-flight.
        """
        if ctx.state not in (STATE_ARMED, STATE_PAUSED):
            return
        # Review B-1 (2026-10-18): a bedroom/media room armed or paused by
        # day must not keep its fan paused (or reach a VACATED verdict)
        # once the house enters FAN_TRUST_STATES. Cancel as
        # OCCUPIED_CONFIRMED so the existing restore path turns the fan
        # back ON. Same predicate as the sleep_state eligibility veto.
        merged_c = self._merged_config(room_coord)
        if (
            getattr(self._presence, "house_state", "") in FAN_TRUST_STATES
            and merged_c.get(CONF_ROOM_TYPE, "") in HIGH_STILL_RISK_ROOM_TYPES
        ):
            _LOGGER.info(
                "FanRecheck %s: sleep state entered mid-flight — cancelling",
                ctx.room_name,
            )
            self._schedule_activity(
                action="fan_recheck_cancel",
                room_name=ctx.room_name,
                description="Fan-recheck cancelled (sleep state mid-flight)",
                details={
                    "room": ctx.room_name,
                    "reason": "sleep_state",
                    "state_at_cancel": ctx.state,
                    "ble_ladder_layer": ctx.ble_ladder_layer,
                },
            )
            self._cancel_and_restore_async(
                ctx, OUTCOME_OCCUPIED_CONFIRMED, reason="sleep_state",
            )
            return
        data = getattr(room_coord, "data", None) or {}
        if data.get("motion_detected"):
            _LOGGER.info(
                "FanRecheck %s: motion detected mid-flight — cancelling",
                ctx.room_name,
            )
            self._schedule_activity(
                action="fan_recheck_cancel",
                room_name=ctx.room_name,
                description="Fan-recheck cancelled (motion mid-flight)",
                details={
                    "room": ctx.room_name,
                    "reason": "motion",
                    "state_at_cancel": ctx.state,
                    "ble_ladder_layer": ctx.ble_ladder_layer,
                },
            )
            self._cancel_and_restore_async(
                ctx, OUTCOME_OCCUPIED_CONFIRMED, reason="motion",
            )
            return
        person_coord = self.hass.data.get(DOMAIN, {}).get("person_coordinator")
        if person_coord is not None:
            l1 = self._l1_persons(person_coord, ctx.room_name, merged_c)
            if l1:
                ctx.ble_ladder_layer = LAYER_L1
                _LOGGER.info(
                    "FanRecheck %s: L1 fired mid-flight — cancelling",
                    ctx.room_name,
                )
                self._schedule_activity(
                    action="fan_recheck_cancel",
                    room_name=ctx.room_name,
                    description="Fan-recheck cancelled (L1 mid-flight)",
                    details={
                        "room": ctx.room_name,
                        "reason": "ble_l1",
                        "state_at_cancel": ctx.state,
                        "ble_ladder_layer": ctx.ble_ladder_layer,
                    },
                )
                self._cancel_and_restore_async(
                    ctx, OUTCOME_OCCUPIED_CONFIRMED, reason="ble_l1",
                )

    def _cancel_and_restore_async(
        self, ctx: _RoomCtx, outcome: str, *, reason: str = "cancel",
    ) -> None:
        # NOTE (review L1 2026-07-18): PAUSED-path cancellations produce TWO
        # ura_activity_log rows — a `fan_recheck_cancel` (fired at the cancel
        # site) followed by a `fan_recheck_outcome` from `_restore`. This is
        # intentional (the outcome row carries the real paused-duration and
        # fan-restore evidence). Analytics dedupe terminal events by joining
        # on `details_json.cancel_driven == True` in the outcome row — the
        # marker is set on ctx here and propagated by `_restore`. ARMED-path
        # cancels go straight to cooldown (no outcome row, one cancel row).
        self._cancel_timer(ctx)
        if ctx.state == STATE_ARMED:
            # ARMED-path cancels emit the cancel row at the call site (motion
            # / L1); bump last_attempt_at here so the state row's timestamp
            # reflects the terminal attempt (no PAUSED tail will bump it).
            ctx.last_attempt_at = dt_util.now()
            # Fix-up #4: durable aborted mem row — ARMED path never
            # reaches `_restore` so this is the only chance to persist a
            # terminal mem episode for the cycle.
            self._emit_aborted_mem(ctx, reason=reason)
            self.hass.async_create_task(self._enter_cooldown(ctx))
        else:
            ctx._cancel_driven = True  # consumed by _restore's outcome row
            self.hass.async_create_task(self._restore(ctx, outcome=outcome))

    def _still_armed_eligible(self, ctx: _RoomCtx, room_coord: Any) -> bool:
        """Re-check after ARM_DELAY: master kill, fan still on, mmwave still sole."""
        merged = self._merged_config(room_coord)
        if not self._master_enabled():
            return False
        if not merged.get(
            CONF_ROOM_FAN_RECHECK_ENABLED, DEFAULT_ROOM_FAN_RECHECK_ENABLED,
        ):
            return False
        # HVAC Batch D: same owner rule as `_evaluate_eligibility`.
        if fan_owner(merged) is None:
            return False
        # ROOM-OVERRIDE-SWITCH-FORGOTTEN-1 (F2): an ARMED room paused during
        # the arm delay disarms here (same rule as `_evaluate_eligibility`).
        if room_automation_paused(room_coord):
            return False
        # Sleep-scoped abort (FAN-RECHECK-SLEEP-VETO-SCOPE-1 fold-in,
        # 2026-08-19): mirrors ``_evaluate_eligibility`` — bedroom rooms
        # abort across FAN_TRUST_STATES to preserve the v4.7.13 keep-on
        # contract; non-bedroom rooms proceed through sleep since no
        # v4.7.13 obligation applies. Symmetric application here (not just
        # in ``_is_eligible``) so a bedroom that armed just before the
        # sleep edge is correctly aborted instead of pausing its fan
        # mid-sleep.
        house_state = getattr(self._presence, "house_state", "")
        # JAYA-FAN-STILL-PHANTOM-1: same widened predicate as
        # ``_evaluate_eligibility`` (bedroom + media_room; media for
        # still-sleeper protection, not the v4.7.13 keep-on contract).
        room_type = merged.get(CONF_ROOM_TYPE, "")
        if (
            house_state in FAN_TRUST_STATES
            and room_type in HIGH_STILL_RISK_ROOM_TYPES
        ):
            return False
        data = getattr(room_coord, "data", None) or {}
        if not data.get("occupied"):
            return False
        # Override Occupied veto (B-M1): operator intent, not a sensor
        # fact; applies on both routing branches and under either kill
        # switch state. Read the live label — override is a sustained
        # label state, so the current tick is authoritative.
        if str(data.get("occupancy_source", "none")) == "override":
            return False
        if capability_routing_enabled():
            # OCCUPANCY-SOURCE-FOLLOWS-CAPABILITY-1 D4: live tick must be
            # capability radar-sole.
            if not data.get(STATE_RADAR_SOLE_TICK, False):
                return False
        elif str(data.get("occupancy_source", "none")) != "mmwave":
            return False
        fans = merged.get(CONF_FANS) or []
        if isinstance(fans, str):
            fans = [fans]
        fans = [f for f in fans if f]
        if not any(self._is_entity_on(f) for f in fans):
            return False
        return True

    # ---- helpers -----------------------------------------------------------

    def _master_enabled(self) -> bool:
        # Master is per-PresenceCoordinator. We store it under hass.data so
        # the switch entity can flip it at runtime.
        return bool(
            self.hass.data.get(DOMAIN, {}).get(
                "fan_recheck_master_enabled",
                DEFAULT_FAN_RECHECK_ENABLED,
            )
        )

    def _merged_config(self, room_coord: Any) -> dict:
        if room_coord is None or not hasattr(room_coord, "entry"):
            return {}
        return {**room_coord.entry.data, **(room_coord.entry.options or {})}

    def _timing_config(self) -> dict:
        """Return the 7 fan-recheck timing values from the CM entry options.

        The 7 timing knobs live on the CoordinatorManager entry's options
        (same entry the master ``FanRecheckEnabledSwitch`` writes to via
        its ``_mirror_options``; same entry the ``coordinator_presence``
        options step persists). PresenceCoordinator itself does NOT carry
        an ``entry`` attribute, so we resolve the CM entry by entry-type
        sweep — identical pattern to ``FanRecheckEnabledSwitch._mirror_options``.

        Falls through to ``DEFAULT_*`` from const.py for any missing key.
        Best-effort: failures return defaults (the read is non-fatal — the
        state machine continues with default timings).
        """
        out = {
            CONF_FAN_RECHECK_ARM_DELAY_S: DEFAULT_FAN_RECHECK_ARM_DELAY_S,
            CONF_FAN_RECHECK_SPINDOWN_S: DEFAULT_FAN_RECHECK_SPINDOWN_S,
            CONF_FAN_RECHECK_WINDOW_S: DEFAULT_FAN_RECHECK_WINDOW_S,
            CONF_FAN_RECHECK_COOLDOWN_S: DEFAULT_FAN_RECHECK_COOLDOWN_S,
            CONF_FAN_RECHECK_MAX_PER_HOUR: DEFAULT_FAN_RECHECK_MAX_PER_HOUR,
            CONF_FAN_RECHECK_HVAC_SUPPRESS_S: DEFAULT_FAN_RECHECK_HVAC_SUPPRESS_S,
            CONF_FAN_RECHECK_MMWAVE_HISTORY_TICKS: (
                DEFAULT_FAN_RECHECK_MMWAVE_HISTORY_TICKS
            ),
            CONF_FAN_RECHECK_FAMILY_SCALING_ENABLED: (
                DEFAULT_FAN_RECHECK_FAMILY_SCALING_ENABLED
            ),
        }
        try:
            for ce in self.hass.config_entries.async_entries(DOMAIN):
                if ce.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_COORDINATOR_MANAGER:
                    continue
                opts = ce.options or {}
                for key in list(out.keys()):
                    if key in opts and opts[key] is not None:
                        out[key] = opts[key]
                break
        except Exception:  # noqa: BLE001 — best-effort read; defaults preserved
            _LOGGER.debug(
                "FanRecheck: timing-config read failed; using DEFAULT_* values",
                exc_info=True,
            )
        return out

    def _is_entity_on(self, entity_id: str) -> bool:
        try:
            state = self.hass.states.get(entity_id)
        except Exception:  # noqa: BLE001
            return False
        return state is not None and state.state == "on"

    def _room_name_of(self, room_coord: Any) -> str:
        try:
            return room_coord.entry.data.get(CONF_ROOM_NAME) or room_coord.entry.data.get("room_name", "")
        except Exception:  # noqa: BLE001
            return ""

    def _room_coord_for(self, room_name: str) -> Optional[Any]:
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_ROOM:
                continue
            if (entry.data.get(CONF_ROOM_NAME) or entry.data.get("room_name")) == room_name:
                return self.hass.data.get(DOMAIN, {}).get(entry.entry_id)
        return None

    def _l1_persons(
        self, person_coord: Any, room_name: str, merged: dict,
    ) -> list:
        """Trustworthy persons in this room OR in any URA room whose area_id
        is listed in this room's CONF_SCANNER_AREAS.

        Operator scope addition 2026-10-18 (JAYA-FAN-STILL-PHANTOM-1): a phone
        resolved by Tier-1 direct match to the bathroom room is still "in"
        the bedroom that borrows that bathroom's scanner. Reads person_coord's
        existing area->room map; does NOT change person positioning.
        """
        persons = list(trustworthy_persons_in_room(
            self.hass, person_coord, room_name,
        ))
        scanner_areas = merged.get(CONF_SCANNER_AREAS) or []
        if isinstance(scanner_areas, str):
            scanner_areas = [scanner_areas]
        area_map = getattr(person_coord, "_area_id_to_room", None)
        if not isinstance(area_map, dict):
            # Review A-LOW-4: a MagicMock/absent map must not yield false L1.
            area_map = {}
        seen = {room_name}
        for area in scanner_areas:
            if not area:
                continue
            other = area_map.get(area) or area_map.get(
                str(area).lower().replace(" ", "_"),
            )
            if not other or other in seen:
                continue
            seen.add(other)
            for p in trustworthy_persons_in_room(
                self.hass, person_coord, other,
            ):
                if p not in persons:
                    persons.append(p)
        return persons

    def _has_trustworthy_phone_in_adjacent(
        self, person_coord: Any, room_name: str,
    ) -> bool:
        try:
            adj = self._presence.get_adjacent_rooms(room_name)
        except Exception:  # noqa: BLE001
            adj = []
        for adj_room in adj:
            persons = trustworthy_persons_in_room(
                self.hass, person_coord, adj_room,
            )
            if persons:
                return True
        return False

    def _trustworthy_persons_in_zone(
        self, person_coord: Any, zone_rooms: list[str],
    ) -> list[str]:
        try:
            from ._ble_corroboration import trustworthy_persons_in_zone
            return trustworthy_persons_in_zone(
                self.hass, person_coord, zone_rooms,
            )
        except Exception:  # noqa: BLE001
            return []

    def _zone_rooms_for(self, room_name: str) -> list[str]:
        try:
            trackers = getattr(self._presence, "zone_trackers", {}) or {}
            for tracker in trackers.values():
                rooms = getattr(tracker, "room_names", []) or []
                if room_name in rooms:
                    return list(rooms)
        except Exception:  # noqa: BLE001
            return []
        return []

    def _recheck_factor(self, merged: dict) -> float:
        room_type = merged.get(CONF_ROOM_TYPE, "")
        return float(
            ROOM_TYPE_RECHECK_FACTOR.get(room_type, DEFAULT_RECHECK_FACTOR)
        )

    def _room_families(self, merged: dict) -> list[str]:
        """C4 Rev 2 (review A-M3): the RECOGNISED sensor families of the
        room's presence sensors (CONF_MMWAVE_SENSORS = "presence_sensors"),
        resolved from the device registry model. "unknown" is dropped."""
        try:
            from ..fan_veto import resolve_sensor_family  # noqa: PLC0415
        except ImportError:  # isolated-module test loaders: no fan_veto
            return []
        routed = capability_routing_enabled()
        if routed:
            # OCCUPANCY-SOURCE-FOLLOWS-CAPABILITY-1 D4: every radar-bearing
            # sensor across all three CONF lists (a radar filed under
            # occupancy/motion sets the window too).
            try:
                from ..fan_veto import is_radar_entity  # noqa: PLC0415
            except ImportError:
                return []
            keys = (
                CONF_MMWAVE_SENSORS, CONF_MOTION_SENSORS,
                CONF_OCCUPANCY_SENSORS,
            )
        else:
            keys = (CONF_MMWAVE_SENSORS,)
        sensors: list = []
        for key in keys:
            vals = merged.get(key) or []
            if isinstance(vals, str):
                vals = [vals]
            for v in vals:
                if v not in sensors:
                    sensors.append(v)
        out: list[str] = []
        for eid in sensors:
            if not isinstance(eid, str) or not eid:
                continue
            if routed and not is_radar_entity(self.hass, merged, eid):
                continue
            fam = resolve_sensor_family(self.hass, eid)
            if fam != SENSOR_FAMILY_UNKNOWN and fam not in out:
                out.append(fam)
        return out

    def _family_warned_set(self) -> set:
        warned = getattr(self, "_family_warned", None)
        if warned is None:
            warned = set()
            self._family_warned = warned
        return warned

    def _family_factor(
        self, merged: dict, timing: dict, room_name: str = "",
    ) -> float:
        """C4 Rev 2: window multiplier = the MAX factor over the room's
        recognised presence-sensor families (review A-M3). 1.0 when family
        scaling is off or no family is recognised (byte-identical pre-C4);
        the latter WARNs once per room per boot when the room has presence
        sensors."""
        if not timing.get(
            CONF_FAN_RECHECK_FAMILY_SCALING_ENABLED,
            DEFAULT_FAN_RECHECK_FAMILY_SCALING_ENABLED,
        ):
            return 1.0
        families = self._room_families(merged)
        if (
            not families
            and merged.get(CONF_MMWAVE_SENSORS)
            and room_name
            and room_name not in self._family_warned_set()
        ):
            self._family_warned_set().add(room_name)
            _LOGGER.warning(
                "FanRecheck %s: presence-sensor family not recognised from "
                "the device model — recheck window not scaled (factor 1.0)",
                room_name,
            )
        # Review A-M3: the slowest recognised family sets the window (a
        # room is only as quick to clear as its slowest radar).
        return max(
            (family_recheck_factor(f) for f in families), default=1.0,
        )

    def _effective_window_s(
        self, merged: dict, timing: dict, room_name: str = "",
    ) -> int:
        """Live recheck observe window: CM window knob x room-type factor x
        family factor (C4 Rev 2). Shared by the live pause path and the
        PAUSED rehydrate stale check."""
        window = int(
            timing.get(CONF_FAN_RECHECK_WINDOW_S, DEFAULT_FAN_RECHECK_WINDOW_S)
        )
        factor = self._recheck_factor(merged) * self._family_factor(
            merged, timing, room_name,
        )
        return int(window * factor)

    def _fan_in_manual_on_hold(self, room_name: str) -> bool:
        """Fan-noise Rev 2 C1a (Finding 2): True while the room's manual-ON
        hold is live. Mirrors `_fan_in_manual_cooldown` (oracle first, the
        FanController RAM state as fallback)."""
        try:
            oracle = self.hass.data.get(DOMAIN, {}).get("fan_oracle")
            if oracle is not None:
                try:
                    from .hvac_fans import _room_key
                    until = oracle.get_state(
                        _room_key(room_name),
                    ).manual_on_hold_until
                    if until is None:
                        return False
                    return dt_util.now() < until
                except Exception:  # noqa: BLE001 — fall through
                    pass
            fan_controller = self._fan_controller()
            if fan_controller is None:
                return False
            room_fan = fan_controller._room_fans.get(room_name)
            if room_fan is None or not room_fan.manual_on_hold_until:
                return False
            until = dt_util.parse_datetime(room_fan.manual_on_hold_until)
            if until is None:
                return False
            if until.tzinfo is None:
                until = dt_util.as_local(until)
            return dt_util.now() < until
        except Exception:  # noqa: BLE001
            return False

    def _fan_in_actuator_quarantine(
        self, room_coord: Any, fans: list,
    ) -> bool:
        """Fan-noise Rev 2 C3 Part B: True iff a configured fan that is ON
        right now is in its ActuatorReconciler flap quarantine (the
        reconciler owns fan availability-flap detection)."""
        try:
            reconciler = getattr(room_coord, "_actuator_reconciler", None)
            if reconciler is None:
                return False
            flapping = {
                row.get("entity_id") for row in reconciler.flapping_entities()
            }
            # Review B-4: only a quarantined fan that is RUNNING (the one
            # the pause would act on) vetoes; a flapping idle sibling does not.
            return any(f in flapping and self._is_entity_on(f) for f in fans)
        except Exception:  # noqa: BLE001
            return False

    def _fan_in_manual_cooldown(self, room_name: str) -> bool:
        """FAN-LAYER-2 D1 (PLAN §2.1 task item 2 + §5.2 dual-tier agreement).

        Reads the oracle ledger directly via the shared ``_room_key``
        keyer so this reader agrees with both the HVAC-tier writer and
        the room-tier writer for the same room. Prior-scheme reach-through
        (hass.data -> coordinator_manager -> hvac.fan_controller
        ._room_fans[room_name]) preserved as fallback when the oracle
        isn't yet attached (early boot / minimal-mock unit tests).
        """
        try:
            # Preferred path: oracle-first, keyed by _room_key(room_name).
            oracle = self.hass.data.get(DOMAIN, {}).get("fan_oracle")
            if oracle is not None:
                try:
                    from .hvac_fans import _room_key
                    key = _room_key(room_name)
                    until = oracle.get_state(key).manual_off_cooldown_until
                    if until is None:
                        return False
                    return dt_util.now() < until
                except Exception:  # noqa: BLE001 — fall through to prior-scheme
                    pass
            # Prior-scheme fallback: reach through the fan controller's RAM state.
            cm = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
            hvac = cm.coordinators.get("hvac") if cm else None
            fan_controller = getattr(hvac, "fan_controller", None) if hvac else None
            if fan_controller is None:
                return False
            room_fan = fan_controller._room_fans.get(room_name)
            if room_fan is None:
                return False
            if not room_fan.manual_off_cooldown_until:
                return False
            # M-A3: parse via dt_util so a tz-naive stored ISO doesn't blow up
            # the tz-aware comparison against dt_util.now(). hvac_fans stores
            # dt_util.now().isoformat() (tz-aware), but be permissive.
            until = dt_util.parse_datetime(room_fan.manual_off_cooldown_until)
            if until is None:
                return False
            if until.tzinfo is None:
                until = dt_util.as_local(until)
            return dt_util.now() < until
        except Exception:  # noqa: BLE001
            return False

    async def _fan_pause(
        self, room_name: str, suppress_until_iso: str,
    ) -> Optional[dict]:
        fan_controller = self._fan_controller()
        if fan_controller is None:
            return None
        try:
            return await fan_controller.pause_for_recheck(
                room_name, suppress_until_iso,
            )
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning(
                "FanRecheck %s: pause_for_recheck failed: %s",
                room_name, exc,
            )
            return None

    async def _fan_restore(
        self, room_name: str, snapshot: Optional[dict],
        leave_off: bool = False,
    ) -> None:
        fan_controller = self._fan_controller()
        if fan_controller is None:
            return
        try:
            await fan_controller.restore_after_recheck(
                room_name, snapshot, leave_off=leave_off,
            )
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning(
                "FanRecheck %s: restore_after_recheck failed: %s",
                room_name, exc,
            )

    def _fan_controller(self) -> Optional[Any]:
        cm = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if cm is None:
            return None
        hvac = getattr(cm, "coordinators", {}).get("hvac")
        return getattr(hvac, "fan_controller", None) if hvac else None

    def _prune_attempts(self, ctx: _RoomCtx, now: datetime) -> None:
        cutoff = now - timedelta(hours=1)
        while ctx.attempts and ctx.attempts[0] < cutoff:
            ctx.attempts.popleft()

    def _schedule_timer(self, ctx: _RoomCtx, seconds: int, callback) -> None:
        self._cancel_timer(ctx)
        ctx.timer_unsub = async_call_later(self.hass, seconds, callback)

    def _cancel_timer(self, ctx: _RoomCtx) -> None:
        if ctx.timer_unsub is not None:
            try:
                ctx.timer_unsub()
            except Exception:  # noqa: BLE001
                pass
            ctx.timer_unsub = None

    async def _persist(self, ctx: _RoomCtx) -> None:
        db = self.hass.data.get(DOMAIN, {}).get("database")
        if db is None:
            return
        snapshot_json = None
        if ctx.snapshot is not None:
            try:
                snapshot_json = json.dumps(ctx.snapshot, default=str)
            except Exception:  # noqa: BLE001
                snapshot_json = None
        try:
            await db.save_fan_recheck_state({
                "room_id": ctx.entry_id,
                "state": ctx.state,
                "state_entered_at": (
                    ctx.state_entered_at.isoformat()
                    if ctx.state_entered_at else None
                ),
                "snapshot_json": snapshot_json,
                "attempts_in_hour": len(ctx.attempts),
                "last_outcome": ctx.last_outcome,
                "last_attempt_at": (
                    ctx.last_attempt_at.isoformat()
                    if ctx.last_attempt_at else None
                ),
                "ble_ladder_layer": ctx.ble_ladder_layer,
                "last_update_ts": dt_util.now().isoformat(),
            })
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug(
                "FanRecheck %s: persist failed (non-fatal): %s",
                ctx.room_name, exc,
            )

    def _restore_row(self, row: dict) -> None:
        """Rehydrate a single DB row per D6 restart resilience table."""
        entry_id = row.get("room_id")
        if not entry_id:
            return
        # Resolve room_name from entry_id.
        room_name = ""
        merged: dict = {}
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.entry_id == entry_id:
                room_name = entry.data.get(CONF_ROOM_NAME) or entry.data.get(
                    "room_name", "",
                )
                merged = {**(entry.data or {}), **(entry.options or {})}
                break
        if not room_name:
            return
        try:
            state = row.get("state") or STATE_IDLE
        except Exception:  # noqa: BLE001
            state = STATE_IDLE
        # ISO-string -> datetime via stdlib fromisoformat; we own the encode
        # path (always isoformat in _persist), so no need for dt_util's
        # broader parser.
        try:
            entered = (
                datetime.fromisoformat(row["state_entered_at"])
                if row.get("state_entered_at") else None
            )
        except Exception:  # noqa: BLE001
            entered = None
        snapshot = None
        if row.get("snapshot_json"):
            try:
                snapshot = json.loads(row["snapshot_json"])
            except Exception:  # noqa: BLE001
                snapshot = None
        ctx = _RoomCtx(
            room_name=room_name,
            entry_id=entry_id,
            state=STATE_IDLE,
            state_entered_at=entered,
            snapshot=snapshot,
            last_outcome=row.get("last_outcome"),
            ble_ladder_layer=row.get("ble_ladder_layer") or LAYER_NONE,
        )
        try:
            last_attempt = row.get("last_attempt_at")
            ctx.last_attempt_at = (
                datetime.fromisoformat(last_attempt) if last_attempt else None
            )
        except Exception:  # noqa: BLE001
            ctx.last_attempt_at = None
        self._rooms[room_name] = ctx

        # D6 restart-resilience matrix.
        now = dt_util.now()
        if state == STATE_PAUSED and entered is not None:
            # C4 Rev 2 (Finding 9b): stale threshold scales with the room's
            # live effective window (room-type x family), not the default.
            # Review A-L1: never shorter than the pause itself
            # (spindown + effective window) plus the suppress margin.
            _timing = self._timing_config()
            _eff = self._effective_window_s(merged, _timing, room_name)
            _spin = int(_timing.get(
                CONF_FAN_RECHECK_SPINDOWN_S, DEFAULT_FAN_RECHECK_SPINDOWN_S,
            ))
            window = max(
                _eff * 2, _spin + _eff + FAN_RECHECK_SUPPRESS_MARGIN_S,
            )
            if (now - entered).total_seconds() < window:
                self.hass.async_create_task(
                    self._restore(ctx, outcome=OUTCOME_OCCUPIED_CONFIRMED),
                )
                return
            _LOGGER.warning(
                "FanRecheck %s: rehydrate paused state too old — idle",
                room_name,
            )
            ctx.last_attempt_at = now
            self._schedule_activity(
                action="fan_recheck_cancel",
                room_name=room_name,
                description=(
                    "Fan-recheck cancelled (rehydrate stale PAUSED)"
                ),
                details={
                    "room": room_name,
                    "reason": "rehydrate_stale_paused",
                    "state_at_cancel": STATE_PAUSED,
                    "ble_ladder_layer": ctx.ble_ladder_layer,
                },
            )
            ctx.state = STATE_IDLE
            ctx.snapshot = None
            return
        if state == STATE_RESTORING:
            _LOGGER.info(
                "FanRecheck %s: rehydrate restoring -> idle (restore skipped)",
                room_name,
            )
            ctx.last_attempt_at = now
            self._schedule_activity(
                action="fan_recheck_cancel",
                room_name=room_name,
                description=(
                    "Fan-recheck cancelled (rehydrate mid-RESTORING)"
                ),
                details={
                    "room": room_name,
                    "reason": "rehydrate_restoring",
                    "state_at_cancel": STATE_RESTORING,
                    "ble_ladder_layer": ctx.ble_ladder_layer,
                },
            )
            ctx.state = STATE_IDLE
            ctx.snapshot = None
            return
        if state == STATE_COOLDOWN and entered is not None:
            elapsed = (now - entered).total_seconds()
            # C4 Rev 2 (Finding 9c, Bug Class #53): the LIVE CM cooldown
            # knob, not the default.
            cooldown_s = int(
                self._timing_config().get(
                    CONF_FAN_RECHECK_COOLDOWN_S,
                    DEFAULT_FAN_RECHECK_COOLDOWN_S,
                )
            )
            remaining = max(0, cooldown_s - int(elapsed))
            ctx.state = STATE_COOLDOWN
            if remaining > 0:
                async def _on_cd_done(_n, _ctx=ctx):
                    _ctx.timer_unsub = None
                    _ctx.state = STATE_IDLE
                    _ctx.state_entered_at = dt_util.now()
                    await self._persist(_ctx)
                self._schedule_timer(ctx, remaining, _on_cd_done)
            else:
                ctx.state = STATE_IDLE
            return
        if state == STATE_ARMED:
            ctx.last_attempt_at = now
            self._schedule_activity(
                action="fan_recheck_cancel",
                room_name=room_name,
                description=(
                    "Fan-recheck cancelled (rehydrate ARMED)"
                ),
                details={
                    "room": room_name,
                    "reason": "rehydrate_armed",
                    "state_at_cancel": STATE_ARMED,
                    "ble_ladder_layer": ctx.ble_ladder_layer,
                },
            )
            ctx.state = STATE_IDLE
            return
        ctx.state = STATE_IDLE
