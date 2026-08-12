"""FAN-LAYER-1 — FanPolicyOracle (verdict + actuation-aware ledger).

Sessions 1-3 (2026-08-10..11). This module is the shared fan-actuation
oracle per ``docs/planning/PLANNING_fan_actuation_shared_layer_v2.md``
§7. Sessions 1 (D2 skeleton) + 2 (RoomAutomation delegation +
mark_fan_on_issued oracle edge) + 3 (W11 safety-stop consult, W12
pre-arrival ON consult) landed the writer-side wiring.

INV-FLA (Fan Layer Authority) — SCOPED CLAIM after FAN-LAYER-2 D2:

  Post FAN-LAYER-2 D2, NINE async-with ``oracle.actuate`` sites are wired:
    * W11 (`hvac.py::_safety_stop_one_fan`, safety=True) — PRE-EXISTING.
    * W12 (`hvac_predict.py::_activate_zone_fans`) — PRE-EXISTING.
    * W1 (`automation.py` temp/vacancy revert OFF) — D2 (FAN_TRIGGER_TEMP_ROOM).
    * W2 (`automation.py` FAN_SLEEP_OFF) — D2 (FAN_TRIGGER_SLEEP_OFF).
    * W3-temp (`automation.py` temp-branch ON) — D2 (FAN_TRIGGER_TEMP_ROOM_ON).
    * W3-onset (`automation.py` sleep-onset ON) — D2 (FAN_TRIGGER_SLEEP_ONSET_ON).
    * W4-chokepoint (`hvac_fans.py::_set_fan_state`) — D2 (trigger propagated
      via kw arg; W10-pause routes via FAN_TRIGGER_RECHECK_PAUSE and
      W10-restore via FAN_TRIGGER_RECHECK_RESTORE — no independent wraps).
    * W8 (`hvac.py::_execute_vacancy_sweep` per-room fan-emit) — D2
      INDEPENDENT (FAN_TRIGGER_HVAC_VACANCY).
    * W9 (`hvac.py::_deactivate_zone_fans` per-room fan-emit) — D2
      INDEPENDENT (FAN_TRIGGER_HVAC_PREARRIVAL).

  Together with D1's locked-setter fleet (`set_manual_*_locked` on the 9
  §5.4 sites) + `_room_key`-unified ledger keys (§5.2), INV-FLA-T is now
  ENFORCED at every URA-issued fan emission site classified in PLAN §2.2 —
  each holds the per-room ``asyncio.Lock`` across ``consult → emit → note``.

  The oracle remains the SINGLE source of truth for two ledger fields:
  ``manual_off_cooldown_until`` and ``manual_on_hold_until``, for the
  ROOM-tier surface (RoomAutomation fields ``_fan_manual_off_until`` /
  ``_fan_manual_on_until`` — Session 2 @property delegation). Every
  URA-issued fan turn_on at the room tier flows through
  ``mark_fan_on_issued()``, which emits ``oracle.note_actuation`` (also
  Session 2). W7 (actuator reconciler) consults via
  ``is_fan_in_manual_on_hold()`` — which now reads the delegated
  oracle-backed field.

  For the HVAC tier, W11 (`_stop_all_fans_safety`) and W12
  (`_activate_zone_fans`) route their emissions through
  ``oracle.actuate(...)`` (Session 3). W11 uses ``safety=True``
  (ALWAYS ALLOW, pre-safety verdict logged at WARNING). W12 DEFERs
  under a live manual-OFF cooldown and appends
  ``reason="manual_off_cooldown"`` to the skipped-rooms diagnostic.

  Not yet routed through ``oracle.actuate(...)`` (deferred to a
  follow-up cycle — the state-in-ONE-place property of the ledger
  holds for these via delegation, but the per-room lock TOCTOU
  protection of PLAN §7.9 INV-FLA-T is NOT yet in force for them):
  W1-W3 room-tier emissions in automation.py, W4-W6 HVAC-tier
  ``_set_fan_state`` chokepoint, W8 zone-vacancy sweep, W9 pre-arrival
  OFF, W10 recheck pause/restore. These sites' existing per-emit
  gates (``is_fan_in_manual_on_hold`` / ``manual_on_hold_until``)
  continue to work; the delegation shipped in Session 2 makes them
  transparently read oracle-backed state, so consistency is
  preserved. The remaining gap is the ATOMIC consult→emit critical
  section (per-room ``asyncio.Lock``), which follows in a
  dedicated cycle.

  Falsifying evidence for the Session-1..3 partial INV-FLA claim:
  (a) any RoomAutomation write to ``_fan_manual_off_until`` /
  ``_fan_manual_on_until`` that does NOT reach the oracle ledger →
  Session-2 tests `test_set_fan_manual_off_until_writes_to_oracle`
  and its sibling would fail; (b) a URA-issued fan_on that does NOT
  emit an oracle ``note_actuation`` edge →
  ``test_mark_fan_on_issued_records_oracle_edge`` fails;
  (c) a safety-stop emission that skips the oracle consult →
  Session-3 test `test_safety_stop_consults_oracle_with_safety_true`
  fails; (d) a pre-arrival ON that ignores an active manual-OFF
  cooldown → Session-3 test
  `test_prearrival_on_defers_under_manual_off_cooldown` fails.

Shape (b) — thin ``FanPolicyOracle`` per PLAN §6.5:
  * verdict predicates: ``may_turn_on`` / ``may_turn_off``
  * atomic actuation critical section: ``oracle.actuate(...)`` (async
    context manager, per-room ``asyncio.Lock``, consult on enter, note
    on exit) — mitigates INV-FLA-T TOCTOU race per PLAN §7.9.
  * ledger reader: ``get_state``
  * ``note_actuation`` — EDGES ONLY per PLAN §7.14 (see write-volume
    rationale citing ``project_optimizer_db_write_flood_incident_2026_06_09``).

Exception posture (PLAN §7.11) is fail-safe toward FAN-OFF: an
``may_turn_off`` failure ALLOWs (fan turns off), an ``may_turn_on``
failure VETOs (fan stays off), ``note_actuation`` is a no-op on error,
``get_state`` returns an empty ledger.

Note on ``slots=True``: PLAN §7.1 specifies frozen slots dataclasses.
``slots=True`` was introduced in Python 3.10; the URA test env still
runs 3.9 in some places, so the ``slots=True`` kwarg is omitted here.
The FROZEN invariant (which is the load-bearing one for the snapshot
contract) is preserved.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal

from ..const import (
    FAN_TRIGGER_HVAC_SLEEP_ONSET_ON,
    FAN_TRIGGER_KILL_SWITCH,
    FAN_TRIGGER_RECHECK_PAUSE,
    FAN_TRIGGER_RECHECK_RESTORE,
    FAN_TRIGGER_SAFETY_STOP,
    FAN_TRIGGER_SLEEP_OFF,
    FAN_TRIGGER_SLEEP_ONSET_ON,
)

# A-MED-1 / B-LOW-2 fix-up (2026-08-11): prefer HA's dt_util.now() (timezone-
# aware, mockable in tests via _dt_mock the parity anchors use). Fall back to
# naive datetime.now() only when the HA helper is unavailable (early boot /
# minimal-mock unit tests). datetime.now() alone silently produces
# tz-naive values that mis-compare against tz-aware ledger writes.
try:
    from homeassistant.util import dt as _ha_dt  # type: ignore
except Exception:  # noqa: BLE001 — HA optional at unit-test import time
    _ha_dt = None  # type: ignore

_LOGGER = logging.getLogger(__name__)

_ROOM_SLEEP_TRIGGERS = frozenset({FAN_TRIGGER_SLEEP_OFF, FAN_TRIGGER_SLEEP_ONSET_ON})
_HVAC_SLEEP_TRIGGERS = frozenset({FAN_TRIGGER_HVAC_SLEEP_ONSET_ON})


@dataclass(frozen=True)
class Verdict:
    """Oracle decision for a single consult."""

    kind: Literal["allow", "defer", "veto"]
    reason: str | None = None

    @property
    def is_allow(self) -> bool:
        return self.kind == "allow"

    @property
    def is_defer(self) -> bool:
        return self.kind == "defer"

    @property
    def is_veto(self) -> bool:
        return self.kind == "veto"


ALLOW: Verdict = Verdict("allow", None)


def DEFER(reason: str) -> Verdict:  # noqa: N802
    return Verdict("defer", reason)


def VETO(reason: str) -> Verdict:  # noqa: N802
    return Verdict("veto", reason)


@dataclass(frozen=True)
class FanDecisionSnapshot:
    """Caller's declaration of the world it decided against (PLAN §7.8).

    REQUIRED positional argument on every ``may_turn_*`` / ``actuate``
    call. Missing snapshot = TypeError.
    """

    now: datetime
    sleep_state: str
    sleep_axis: Literal["room_window", "house_state"] | None
    house_state: str
    is_hvac_managing: bool
    entities: tuple[str, ...]
    observed_any_on: bool


@dataclass(frozen=True)
class PauseContext:
    """Recheck-pause bookkeeping (PLAN §7.13)."""

    paused_at: datetime
    hold_remaining_at_pause: timedelta | None


@dataclass(frozen=True)
class RoomFanLedger:
    """Per-room fan policy ledger snapshot (PLAN §7.1)."""

    last_on_time: datetime | None = None
    last_off_time: datetime | None = None
    manual_off_cooldown_until: datetime | None = None
    manual_on_hold_until: datetime | None = None
    last_trigger_path: str | None = None
    last_actuation_source: Literal["ura", "external"] | None = None
    pause_context: PauseContext | None = None
    hold_id: int = 0


@dataclass
class _RoomRecord:
    """Mutable per-room state (internal)."""

    last_on_time: datetime | None = None
    last_off_time: datetime | None = None
    manual_off_cooldown_until: datetime | None = None
    manual_on_hold_until: datetime | None = None
    last_trigger_path: str | None = None
    last_actuation_source: Literal["ura", "external"] | None = None
    pause_context: PauseContext | None = None
    hold_id: int = 0
    _last_verdict: dict[tuple[str, int], str] = field(default_factory=dict)

    def snapshot(self) -> RoomFanLedger:
        return RoomFanLedger(
            last_on_time=self.last_on_time,
            last_off_time=self.last_off_time,
            manual_off_cooldown_until=self.manual_off_cooldown_until,
            manual_on_hold_until=self.manual_on_hold_until,
            last_trigger_path=self.last_trigger_path,
            last_actuation_source=self.last_actuation_source,
            pause_context=self.pause_context,
            hold_id=self.hold_id,
        )


class FanPolicyOracle:
    """Fan actuation policy oracle — verdict + actuation-aware ledger.

    Attached as a singleton to ``CoordinatorManager`` (PLAN §7.7). RAM-only
    (no persistence); adopt-external re-populates on boot.
    """

    def __init__(self, hass: Any | None = None) -> None:
        self._hass = hass
        self._rooms: dict[str, _RoomRecord] = {}
        self._room_locks: dict[str, asyncio.Lock] = {}
        # EDGE audit log — every VERDICT-CHANGE emit. Feeds activity_log
        # in a later session; here it lets the write-volume regression
        # test count edges.
        self.actuation_events: list[dict[str, Any]] = []
        _LOGGER.info(
            "FanPolicyOracle constructed — RoomAutomation delegation + "
            "W11 safety-stop + W12 pre-arrival-ON wired (Sessions 1..3)"
        )

    # ------------------------------------------------------------------
    # Public setter API (A-LOW-1 fix-up 2026-08-11).
    # Callers (RoomAutomation @property setters, mirror helpers) go through
    # these instead of reaching into ``_get_record(room).<field> = value``.
    # ------------------------------------------------------------------

    def set_manual_off_cooldown(self, room_key: str, value):
        """Set/clear the manual-OFF cooldown deadline for ``room_key``.

        ``value`` is a datetime | None. None clears the cooldown.
        Room key is the caller's stable identifier (config entry_id for
        the room-tier — see A-HIGH-1 fix-up: CONF_ROOM_NAME with an
        empty-string fallback collided when two rooms lacked a name).
        """
        try:
            rec = self._get_record(room_key)
            rec.manual_off_cooldown_until = value
        except Exception:  # noqa: BLE001
            _LOGGER.error(
                "FanPolicyOracle.set_manual_off_cooldown failed for room=%s",
                room_key, exc_info=True,
            )

    def set_manual_on_hold(self, room_key: str, value):
        """Set/clear the manual-ON hold deadline for ``room_key``.

        ``value`` is a datetime | None. None clears the hold.
        """
        try:
            rec = self._get_record(room_key)
            rec.manual_on_hold_until = value
        except Exception:  # noqa: BLE001
            _LOGGER.error(
                "FanPolicyOracle.set_manual_on_hold failed for room=%s",
                room_key, exc_info=True,
            )

    def clear_manual_on_hold(self, room_key: str) -> None:
        """Convenience: clear the ON-hold (kill-switch, safety-stop cleanup)."""
        self.set_manual_on_hold(room_key, None)

    # ------------------------------------------------------------------
    # FAN-LAYER-2 D1: async-locked setter fleet (PLAN §5.4).
    # Callers from async paths (hvac_fans.py external-adopt / kill-switch /
    # pause-restore sites) go through these to serialize under the per-room
    # asyncio.Lock, closing INV-FLA-T (PLAN §1 canonical repro at #3/#6).
    # asyncio.Lock is NON-REENTRANT — callers holding the lock manually
    # (e.g. §5.4a R-M-W wrap) MUST use the sync setters inside the block.
    # ------------------------------------------------------------------

    async def set_manual_on_hold_locked(self, room_key: str, value) -> None:
        async with self._get_lock(room_key):
            self.set_manual_on_hold(room_key, value)

    async def set_manual_off_cooldown_locked(self, room_key: str, value) -> None:
        async with self._get_lock(room_key):
            self.set_manual_off_cooldown(room_key, value)

    async def clear_manual_on_hold_locked(self, room_key: str) -> None:
        async with self._get_lock(room_key):
            self.set_manual_on_hold(room_key, None)

    async def clear_manual_off_cooldown_locked(self, room_key: str) -> None:
        async with self._get_lock(room_key):
            self.set_manual_off_cooldown(room_key, None)

    async def async_cleanup_expired_holds(self) -> None:
        """Cosmetic hygiene: drop expired hold/cooldown deadlines (PLAN §5.4 #14).

        NOT LOAD-BEARING. The authoritative expiry gate lives at
        ``hvac_fans.py::_is_manual_on_hold_live`` (read-time evaluation at
        ~:1076-1089) and ``_evaluate_temp_fan``'s cooldown compare at
        ~:842-844. This helper only tidies rows in the ledger dict whose
        read paths haven't fired in a while — behavior is IDENTICAL
        whether it runs or not. See PLANNING §5.4 row #14 rationale.
        """
        try:
            if _ha_dt is not None:
                now = _ha_dt.now()
            else:
                now = datetime.now()
            for room_key in list(self._rooms.keys()):
                async with self._get_lock(room_key):
                    rec = self._rooms.get(room_key)
                    if rec is None:
                        continue
                    if (rec.manual_on_hold_until is not None
                            and now >= rec.manual_on_hold_until):
                        rec.manual_on_hold_until = None
                    if (rec.manual_off_cooldown_until is not None
                            and now >= rec.manual_off_cooldown_until):
                        rec.manual_off_cooldown_until = None
        except Exception:  # noqa: BLE001 — cosmetic; never break caller
            _LOGGER.debug(
                "FanPolicyOracle.async_cleanup_expired_holds failed",
                exc_info=True,
            )

    def migrate_legacy_entry_keys(self, entry_to_room_key: dict[str, str]) -> int:
        """Fold ``entry:<eid>`` legacy rows into their target ``room:<name>`` keys.

        FAN-LAYER-2 D2 fix-up B-HIGH-1 + A-MED-1 (2026-08-11): called
        wired-in from ``FanController.discover_fans`` (natural site — the
        room-entry iteration builds the entry_id → room:{NFC(name)} map
        for free). Was previously defined but never called AND the docstring
        implied last-writer-wins, which would silently drop live holds on
        collision. Both fixed here.

        Behavior:
          * ``entry_to_room_key`` maps ``"entry:<entry_id>"`` → target
            ``"room:<NFC(name)>"``. Only legacy keys present in the map
            are migrated; unmapped legacy rows are LEFT IN PLACE (safer
            than dropping — a caller may resupply the map later).
          * COLLISION SEMANTICS (A-MED-1): if the target row already
            exists, take the FIELD-WISE MAX of the deadline fields
            (``manual_on_hold_until``, ``manual_off_cooldown_until``,
            ``last_on_time``, ``last_off_time``) so a fresh room:* row is
            never overwritten by a stale entry:* row. ``hold_id`` takes
            the max (edge-key dedup stays monotonic). Bookkeeping fields
            (``last_trigger_path``, ``last_actuation_source``,
            ``pause_context``) prefer the row with the later
            ``last_on_time`` / ``last_off_time``.
          * IDEMPOTENT: a second call with the same map is a no-op (the
            legacy rows are already gone; no target row is overwritten).

        Returns count of legacy rows folded (informational).
        """
        # B-LOW-1 (2026-08-11) — DEFERRED (follow-up card): this helper
        # folds legacy entry:<eid> rows into room:<NFC(name)> targets, but
        # does NOT sweep ORPHANED room:<old-name> rows when the operator
        # renames a room or deletes an entry. RAM-only ledger means a
        # restart clears them; the operator-observable impact of an orphan
        # row is a phantom hold on a now-nonexistent room name (does not
        # affect any live decision path — no wrap consults a room the
        # ledger knows about but the config doesn't). Tracked as a
        # follow-up card; do NOT extend this method.
        migrated = 0
        try:
            legacy_keys = [
                k for k in list(self._rooms.keys()) if k.startswith("entry:")
            ]
            for legacy_key in legacy_keys:
                target = entry_to_room_key.get(legacy_key)
                if target is None:
                    # No mapping for this legacy row — LEAVE IT (do not
                    # drop; a subsequent call with a richer map should
                    # still be able to fold it).
                    continue
                legacy_rec = self._rooms.pop(legacy_key, None)
                if legacy_rec is None:
                    continue
                existing = self._rooms.get(target)
                if existing is None:
                    self._rooms[target] = legacy_rec
                    migrated += 1
                    continue
                # A-MED-1 field-wise MAX merge. `None` loses to any
                # non-None value; two non-None values pick the LATER
                # datetime. This preserves the freshest deadline from
                # either row.
                def _max_dt(a, b):
                    if a is None:
                        return b
                    if b is None:
                        return a
                    return a if a >= b else b

                existing.manual_on_hold_until = _max_dt(
                    existing.manual_on_hold_until,
                    legacy_rec.manual_on_hold_until,
                )
                existing.manual_off_cooldown_until = _max_dt(
                    existing.manual_off_cooldown_until,
                    legacy_rec.manual_off_cooldown_until,
                )
                existing.last_on_time = _max_dt(
                    existing.last_on_time, legacy_rec.last_on_time,
                )
                existing.last_off_time = _max_dt(
                    existing.last_off_time, legacy_rec.last_off_time,
                )
                existing.hold_id = max(existing.hold_id, legacy_rec.hold_id)
                # Bookkeeping — prefer the fresher-activity row's metadata.
                existing_last = _max_dt(
                    existing.last_on_time, existing.last_off_time,
                )
                legacy_last = _max_dt(
                    legacy_rec.last_on_time, legacy_rec.last_off_time,
                )
                if legacy_last is not None and (
                    existing_last is None or legacy_last > existing_last
                ):
                    existing.last_trigger_path = legacy_rec.last_trigger_path
                    existing.last_actuation_source = legacy_rec.last_actuation_source
                    existing.pause_context = legacy_rec.pause_context
                migrated += 1
            if migrated:
                _LOGGER.info(
                    "FanPolicyOracle: migrated %d legacy entry:* rows to "
                    "room:* keys (field-wise MAX on collision)", migrated,
                )
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "FanPolicyOracle.migrate_legacy_entry_keys failed", exc_info=True,
            )
        return migrated

    def _get_lock(self, room: str) -> asyncio.Lock:
        lock = self._room_locks.get(room)
        if lock is None:
            lock = asyncio.Lock()
            self._room_locks[room] = lock
        return lock

    def _get_record(self, room: str) -> _RoomRecord:
        rec = self._rooms.get(room)
        if rec is None:
            rec = _RoomRecord()
            self._rooms[room] = rec
        return rec

    def may_turn_off(
        self,
        room: str,
        trigger_path: str,
        snapshot: FanDecisionSnapshot,
        *,
        safety: bool = False,
    ) -> Verdict:
        """Consult before emitting a fan OFF service call (PLAN §7.4)."""
        try:
            return self._may_turn_off_inner(
                room, trigger_path, snapshot, safety=safety,
            )
        except Exception:  # noqa: BLE001
            # §7.11 fail-safe: OFF error → ALLOW (fan turns off; no runaway).
            _LOGGER.error(
                "FanPolicyOracle.may_turn_off failed for room=%s trigger=%s — "
                "fail-safe ALLOW",
                room, trigger_path, exc_info=True,
            )
            return ALLOW

    def may_turn_on(
        self,
        room: str,
        trigger_path: str,
        snapshot: FanDecisionSnapshot,
        *,
        safety: bool = False,
    ) -> Verdict:
        """Consult before emitting a fan ON service call (PLAN §7.4)."""
        try:
            return self._may_turn_on_inner(
                room, trigger_path, snapshot, safety=safety,
            )
        except Exception:  # noqa: BLE001
            # §7.11 fail-safe: ON error → VETO (fan stays off; no phantom).
            _LOGGER.error(
                "FanPolicyOracle.may_turn_on failed for room=%s trigger=%s — "
                "fail-safe VETO",
                room, trigger_path, exc_info=True,
            )
            return VETO("oracle_error")

    def note_actuation(
        self,
        room: str,
        direction: Literal["on", "off"],
        trigger_path: str,
        *,
        source: Literal["ura", "external"] = "ura",
        now: datetime | None = None,
        verdict: Verdict | None = None,
    ) -> None:
        """Record an actuation edge (PLAN §7.14 — edges only).

        Appends to ``self.actuation_events`` ONLY when the verdict changes
        for the tuple ``(room, trigger_path, hold_id)``. See
        ``project_optimizer_db_write_flood_incident_2026_06_09.md`` —
        unconditional per-tick persistence on 40 rooms × 12 sites saturates
        the write queue; edges-only collapses steady-state to <200 rows/hr.
        """
        try:
            self._note_actuation_inner(
                room, direction, trigger_path,
                source=source, now=now, verdict=verdict,
            )
        except Exception:  # noqa: BLE001
            _LOGGER.error(
                "FanPolicyOracle.note_actuation failed for room=%s dir=%s trigger=%s",
                room, direction, trigger_path, exc_info=True,
            )

    def get_state(self, room: str) -> RoomFanLedger:
        """Return an immutable snapshot of the ledger (PLAN §7.5)."""
        try:
            rec = self._rooms.get(room)
            if rec is None:
                return RoomFanLedger()
            return rec.snapshot()
        except Exception:  # noqa: BLE001
            _LOGGER.error(
                "FanPolicyOracle.get_state failed for room=%s — empty ledger",
                room, exc_info=True,
            )
            return RoomFanLedger()

    @asynccontextmanager
    async def actuate(
        self,
        room: str,
        trigger_path: str,
        snapshot: FanDecisionSnapshot,
        direction: Literal["on", "off"],
        *,
        safety: bool = False,
    ):
        """Per-room lock across consult → emit → note (PLAN §7.9).

        Usage::

            async with oracle.actuate(room, trigger, snap, "off") as verdict:
                if verdict.is_allow:
                    await hass.services.async_call(...)

        No callers this session — later sessions plug in without shape churn.
        """
        lock = self._get_lock(room)
        async with lock:
            if direction == "off":
                verdict = self.may_turn_off(
                    room, trigger_path, snapshot, safety=safety,
                )
            elif direction == "on":
                verdict = self.may_turn_on(
                    room, trigger_path, snapshot, safety=safety,
                )
            else:  # pragma: no cover
                verdict = VETO("bad_direction")
            try:
                yield verdict
            finally:
                if verdict.is_allow:
                    self.note_actuation(
                        room, direction, trigger_path,
                        source="ura", now=snapshot.now, verdict=verdict,
                    )

    def _may_turn_off_inner(
        self,
        room: str,
        trigger_path: str,
        snapshot: FanDecisionSnapshot,
        *,
        safety: bool,
    ) -> Verdict:
        if safety:
            pre_verdict = self._compute_off_verdict(room, trigger_path, snapshot)
            if not pre_verdict.is_allow:
                _LOGGER.warning(
                    "fan safety OFF override room=%s trigger=%s "
                    "pre_safety_verdict=%s reason=%s",
                    room, trigger_path, pre_verdict.kind, pre_verdict.reason,
                )
            return ALLOW
        axis_veto = self._check_sleep_axis(trigger_path, snapshot)
        if axis_veto is not None:
            return axis_veto
        return self._compute_off_verdict(room, trigger_path, snapshot)

    def _compute_off_verdict(
        self,
        room: str,
        trigger_path: str,
        snapshot: FanDecisionSnapshot,
    ) -> Verdict:
        if trigger_path == FAN_TRIGGER_KILL_SWITCH:
            return ALLOW
        if trigger_path == FAN_TRIGGER_RECHECK_PAUSE:
            return ALLOW
        rec = self._rooms.get(room)
        if rec is None:
            return ALLOW
        hold_until = rec.manual_on_hold_until
        if hold_until is not None and snapshot.now < hold_until:
            return DEFER("manual_on_hold")
        return ALLOW

    def _may_turn_on_inner(
        self,
        room: str,
        trigger_path: str,
        snapshot: FanDecisionSnapshot,
        *,
        safety: bool,
    ) -> Verdict:
        if safety:
            return ALLOW
        axis_veto = self._check_sleep_axis(trigger_path, snapshot)
        if axis_veto is not None:
            return axis_veto
        rec = self._rooms.get(room)
        if rec is not None:
            cooldown_until = rec.manual_off_cooldown_until
            if cooldown_until is not None and snapshot.now < cooldown_until:
                return DEFER("manual_off_cooldown")
        return ALLOW

    @staticmethod
    def _check_sleep_axis(
        trigger_path: str,
        snapshot: FanDecisionSnapshot,
    ) -> Verdict | None:
        axis = snapshot.sleep_axis
        if trigger_path in _ROOM_SLEEP_TRIGGERS:
            if axis is not None and axis != "room_window":
                _LOGGER.error(
                    "fan sleep-axis mismatch: trigger=%s axis=%s (expected room_window)",
                    trigger_path, axis,
                )
                return VETO("sleep_axis_mismatch")
        elif trigger_path in _HVAC_SLEEP_TRIGGERS:
            if axis is not None and axis != "house_state":
                _LOGGER.error(
                    "fan sleep-axis mismatch: trigger=%s axis=%s (expected house_state)",
                    trigger_path, axis,
                )
                return VETO("sleep_axis_mismatch")
        return None

    def _note_actuation_inner(
        self,
        room: str,
        direction: Literal["on", "off"],
        trigger_path: str,
        *,
        source: Literal["ura", "external"],
        now: datetime | None,
        verdict: Verdict | None,
    ) -> None:
        rec = self._get_record(room)
        # A-MED-1 / B-LOW-2: prefer HA's tz-aware dt_util.now(); fall back to
        # naive datetime.now() only when HA is unavailable.
        if now is not None:
            ts = now
        elif _ha_dt is not None:
            ts = _ha_dt.now()
        else:
            ts = datetime.now()
        if direction == "off":
            rec.last_off_time = ts
            rec.last_actuation_source = source
            rec.last_trigger_path = trigger_path
            if source == "external":
                rec.manual_on_hold_until = None
            elif trigger_path in (FAN_TRIGGER_KILL_SWITCH, FAN_TRIGGER_SAFETY_STOP):
                # A-MED-2 fix-up (2026-08-11): safety-stop is a kill-switch-
                # class superset instruction. The manual-ON hold was honoring
                # the operator's most-recent intent (a fresh manual ON), but
                # a smoke/CO safety event supersedes all policy state incl.
                # that hold. Clearing here prevents a stale hold from
                # blocking the next legitimate URA re-arm after the safety
                # event resolves. Kill-switch parity by design.
                rec.manual_on_hold_until = None
            elif trigger_path == FAN_TRIGGER_RECHECK_PAUSE:
                remaining: timedelta | None = None
                if rec.manual_on_hold_until is not None:
                    remaining = rec.manual_on_hold_until - ts
                    if remaining.total_seconds() <= 0:
                        remaining = None
                rec.pause_context = PauseContext(
                    paused_at=ts, hold_remaining_at_pause=remaining,
                )
        else:
            rec.last_on_time = ts
            rec.last_actuation_source = source
            rec.last_trigger_path = trigger_path
            if source == "external":
                rec.hold_id += 1
            elif trigger_path == FAN_TRIGGER_RECHECK_RESTORE:
                pc = rec.pause_context
                if pc is not None and pc.hold_remaining_at_pause is not None:
                    rec.manual_on_hold_until = ts + pc.hold_remaining_at_pause
                rec.pause_context = None
        edge_key = (trigger_path, rec.hold_id)
        current_kind = verdict.kind if verdict is not None else "allow"
        prev_kind = rec._last_verdict.get(edge_key)
        if prev_kind != current_kind:
            rec._last_verdict[edge_key] = current_kind
            self.actuation_events.append({
                "room": room,
                "direction": direction,
                "trigger_path": trigger_path,
                "source": source,
                "verdict": current_kind,
                "hold_id": rec.hold_id,
                "ts": ts,
            })
