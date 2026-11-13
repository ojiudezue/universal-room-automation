"""Lock regime — garage remote lockouts (GARAGE-REMOTE-LOCKOUT-SCHEDULE-1, Phase 1).

Plan: docs/planning/PLANNING_sc_garage_remote_lockout.md rev 5 (+ operator
answer Q-G1). Arming (alarm posture) and the lock regime (what is locked)
are separate concerns: this controller never reads or changes ArmedState
and never goes through ``SecurityCoordinator.evaluate()``.

Policy owned this cycle: the two opener "remote lockout" locks.
  * Engage on a SLEEP / VACATION house-state edge, and on GUEST inside the
    CM sleep window (toggle, Q-G1 option (a)). Boot edges and the kill
    switch OFF -> ON never engage (INV-5); the one boot recheck
    (LOCK-BOOT-RECHECK-ENGAGE-1) re-asks for SLEEP / GUEST night / VACATION.
    A manual unlock during the current episode is remembered in the Store
    (``garage_manual_unlock``) and the recheck never re-locks it (INV-5);
    the mark clears at the house-state edge that ends the episode.
  * Release on wake / HOME_* / morning backstop / any resident
    arrival (P1 person -> home, P2 SIGNAL_PERSON_ARRIVING, P5 proximity
    crossing, optional approach zone) / critical hazard / kill switch OFF /
    SC disabled (teardown on the real disable path). LOCK-RELEASE-ON-ARRIVING
    (plan PLANNING_lock_release_on_arriving.md rev 3): a house-state ARRIVING
    edge never releases an engaged episode, and once an episode has seen
    ARRIVING (the "taint") no HOME_* edge or boot recheck releases it either;
    an operator ``override_set`` edge still does.

Write paths (rev 5 §6.1b H-1):
  * Release = direct ``lock.unlock`` in a tracked task (observation mode
    never suppresses it) + read-back + one retry + HIGH NM.
  * Engage = direct ``lock.lock`` issued by ``_async_engage``. For EACH
    lockout the whole engage predicate is evaluated synchronously and the
    service call is awaited immediately after it, with no other ``await``
    in between. HA's ``ServiceRegistry.async_call(blocking=False)`` schedules
    the handler without yielding, so a release that runs after the check
    always runs after the lock command was committed; the release then
    unlocks the entity because it is in ``_engage_inflight`` even if its
    state still reads ``unlocked``.

Lockout entities are their own CONF list and must never be in
``security_lock_entities`` (the sweep / lockdown lists).

HA helper functions are resolved at construction time and can be injected
(tests pass fakes), so this module does not depend on which HA stubs other
test files installed.
"""

from __future__ import annotations

import asyncio
import collections
import functools
import logging
from datetime import datetime, timedelta
from typing import Any, Callable

_LOGGER = logging.getLogger(__name__)

# Bound at import, not per call: a later sys.modules swap of
# homeassistant.util.unit_conversion (test stubs do this) must not change
# the converter this module uses.
from homeassistant.core import callback as _ha_callback  # noqa: E402
from homeassistant.exceptions import HomeAssistantError  # noqa: E402
from homeassistant.util.unit_conversion import DistanceConverter  # noqa: E402

from ..arrival_edges import (  # noqa: E402
    area_slug_of_entity,
    arrival_source_needs_corroboration,
    door_entry_areas,
    live_arrival_slug,
    nonface_arrival_source,
    record_bermuda_moves,
    stale_source_arrival,
)


def callback(func):  # noqa: D401 — review B-C1
    """HA ``@callback``: run on the event loop, never in the executor.

    Every method this module hands to ``async_call_later`` /
    ``async_track_*`` MUST carry it, or HA types it as an Executor job
    (core.py ``get_hassjob_callable_job_type``) and runs it on a worker
    thread, where ``hass.async_create_task`` raises. Applies HA's decorator
    and then sets HA's marker (``_hass_callback``, core.py:210-218)
    explicitly, so a test file that swapped ``homeassistant.core.callback``
    for a no-op cannot strip it.
    """
    func = _ha_callback(func)
    setattr(func, "_hass_callback", True)
    return func

POLICY_NAME = "security.lock_regime.garage_lockout"
POLICY_GARAGE_LOCKOUT = "garage_lockout"
POLICY_AWAY_LOCK = "away_lock"

REASON_NONE = "none"
REASON_SLEEP = "sleep"
REASON_VACATION = "vacation"
REASON_GUEST_NIGHT = "guest_night"
REASON_BOOT_UNKNOWN = "boot_unknown"

# Reasons released like SLEEP (wake, HOME_*, backstop, arrival).
SLEEP_LIKE_REASONS = frozenset({REASON_SLEEP, REASON_GUEST_NIGHT, REASON_BOOT_UNKNOWN})

_UNREAL_STATES = frozenset({"unknown", "unavailable"})
_HOME_STATES = frozenset({"home_day", "home_evening", "home_night"})


def _state_value(state: Any) -> str | None:
    if state is None:
        return None
    return getattr(state, "state", None)


class _Val:
    """A bare ``.state`` holder, so a (possibly replayed) person edge given
    as values goes through the shared ``live_arrival_slug`` rule."""

    __slots__ = ("state",)

    def __init__(self, state: str | None) -> None:
        self.state = state


def distance_to_metres(value: Any, unit: Any) -> float | None:
    """Convert a proximity distance reading to metres, or None = no signal.

    REUSE HA's DistanceConverter (rev 4 M4). An unknown unit raises
    ``HomeAssistantError`` (unit_conversion.py:145-150, pinned HA); a
    non-numeric state raises ValueError / TypeError. Each means no signal.
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    try:
        return float(DistanceConverter.convert(number, unit, "m"))
    except (HomeAssistantError, ValueError, TypeError):
        return None


def _as_set(raw: Any) -> set[str]:
    """Coerce an options value (str / list / None) to a set of entity ids."""
    if isinstance(raw, str):
        return {raw} if raw else set()
    if isinstance(raw, (list, tuple, set, frozenset)):
        return {str(x) for x in raw}
    return set()


def lockout_overlap(lock_entities: Any, lockout_entities: Any) -> list[str]:
    """Entities listed both as sweep/lockdown locks and as remote lockouts.

    Options-flow validator (plan §3.3): a lockout must never be in
    ``security_lock_entities``, or the sweep and lockdown would lock it.
    """
    return sorted(_as_set(lock_entities) & _as_set(lockout_entities))


def lock_exclude_not_subset(lock_entities: Any, exclude: Any) -> list[str]:
    """Entries of ``exclude`` that are not in ``lock_entities`` (SC-LOCK-SWEEP-EXCLUDE-1).

    Also used for "away-lock entities must be excluded" (the same subset
    rule with the exclude list as the superset).
    """
    return sorted(_as_set(exclude) - _as_set(lock_entities))


class LockRegimeController:
    """Garage remote-lockout policy, owned by SecurityCoordinator."""

    def __init__(
        self,
        hass: Any,
        security: Any,
        *,
        now: Callable[[], datetime] | None = None,
        call_later: Callable[..., Callable[[], None]] | None = None,
        track_state: Callable[..., Callable[[], None]] | None = None,
        track_added_domain: Callable[..., Callable[[], None]] | None = None,
        track_removed_domain: Callable[..., Callable[[], None]] | None = None,
        store: Any = None,
        to_metres: Callable[[Any, Any], float | None] | None = None,
    ) -> None:
        self._hass = hass
        self._sc = security
        if now is None:
            from homeassistant.util import dt as dt_util  # noqa: PLC0415

            now = dt_util.now
        if call_later is None or track_state is None:
            from homeassistant.helpers import event as ha_event  # noqa: PLC0415

            call_later = call_later or ha_event.async_call_later
            track_state = track_state or ha_event.async_track_state_change_event
            track_added_domain = (
                track_added_domain or ha_event.async_track_state_added_domain
            )
            track_removed_domain = (
                track_removed_domain or ha_event.async_track_state_removed_domain
            )
        self._now = now
        self._call_later = call_later
        self._track_state = track_state
        self._track_added_domain = track_added_domain
        self._track_removed_domain = track_removed_domain
        self._store = store
        self._to_metres = to_metres or distance_to_metres

        self.reason: str = REASON_NONE
        self.release_gen: int = 0
        self.last_action: dict[str, Any] = {}
        self.missing_residents: list[str] = []
        self.reengage_at: str | None = None
        # v5.108.3: engage reason of the episode in which a human unlocked a
        # lockout (sleep / vacation / guest_night), else None. Persisted
        # (Store key "garage_manual_unlock"); the boot recheck honours it.
        self.manual_unlock_reason: str | None = None

        self._setup_ts: float | None = None
        self._torn_down = False
        self._person_unsubs: dict[str, Callable[[], None]] = {}
        self._other_unsubs: list[Callable[[], None]] = []
        self._distance_unsub: Callable[[], None] | None = None
        self._backstop_unsub: Callable[[], None] | None = None
        self._boot_recheck_unsub: Callable[[], None] | None = None
        self._guest_clock_unsub: Callable[[], None] | None = None
        self._reengage_unsub: Callable[[], None] | None = None
        self._reengage_gen: int | None = None
        self._readback_unsubs: dict[str, Callable[[], None]] = {}
        self._tasks: set[asyncio.Task] = set()
        # Review B-M1: release unlocks awaited (bounded) at teardown.
        self._unlock_tasks: set[asyncio.Task] = set()
        # entity_id -> pending release (write or read-back in flight).
        self._release_inflight: set[str] = set()
        # entity_id -> ts a lock.lock was issued and not yet seen `locked`.
        self._engage_inflight: dict[str, float] = {}
        # person -> {"at": ts, "removed": bool}
        self.releasing_set: dict[str, dict[str, Any]] = {}
        # person -> (state, since_ts, restored)
        self._last_real: dict[str, tuple[str, float, bool]] = {}
        self._last_distance_m: dict[str, float | None] = {}
        # person slug -> ts of the last LIVE not_home -> home edge (face
        # corroboration; not persisted: a restart is inside the exclusion).
        self._arrival_edges: dict[str, float] = {}
        # Review A MED-1: Bermuda move stamps (fed by a PersonCoordinator
        # listener) and faces held for one re-check. Not persisted.
        self._bermuda_moves: dict[str, list[tuple[frozenset[str], float]]] = {}
        self._pending_faces: dict[str, float] = {}
        self._pc_listener_unsub: Callable[[], None] | None = None
        self._pc_listened: Any = None
        self._residents: set[str] = set()
        self._unavailable_warned: set[str] = set()
        # Suspicious-arrival hold (PLANNING_lock_suspicious_arrival_hold.md
        # rev 2): person -> held edge {old_val, new_val, edge_ts, due_ts,
        # unsub, proximity_sids, synthetic}. Not persisted (R5).
        self._held_edges: dict[str, dict[str, Any]] = {}
        self.arrival_holds: int = 0
        self.arrival_signal_held: int = 0
        self.arrival_hold_confirms: int = 0
        # LOCK-RELEASE-ON-ARRIVING D1 (plan rev 3 §2): this engage episode has
        # seen house-state ARRIVING (body evidence, no identity). While set,
        # no house-state / boot-recheck edge releases. Persisted (store keys
        # garage_arrival_taint / garage_episode_saw_arriving). Set and cleared
        # ONLY at the sites named in the plan; the saw flag is D3's own copy
        # (separate set statements, so the trip-wire survives a taint bug).
        self._arrival_taint: bool = False
        self._episode_saw_arriving: bool = False
        self.arriving_holds: int = 0
        # D3 trip-wire: count + the last house-state edges for its message
        # (new, old, trigger, ts), F20.
        self.uncorroborated_releases: int = 0
        self._last_house_edges: collections.deque = collections.deque(maxlen=4)
        # D4 still-locked trip-wire. engage_seq is bumped at every lock.lock
        # we issue (release_gen cannot serve: only releases bump it, F2/H3a).
        self.engage_seq: int = 0
        # entity -> ts a lockout_release_failed NM started (H3b dedup).
        self._failure_nm_at: dict[str, float] = {}
        # person -> pending still-locked check; entity -> engage_seq it was
        # paged in (one page per stuck lock per engage episode, R2-7). Neither
        # is persisted (a restart drops a pending check; named residual).
        self._still_locked_unsubs: dict[str, Callable[[], None]] = {}
        self._still_locked_paged: dict[str, int] = {}
        self.still_locked_pages: int = 0
        self.uncounted_returns: int = 0

        # SC-LOCK-REGIME-DOOR-LOCKS-1 (plan rev 3 D3a): the away-lock policy.
        # Its own state; it never touches reason / release_gen / backstop /
        # re-engage (garage policy).
        # Entities this policy locked (read-back saw `locked`). Persisted.
        self.away_lock_owned: set[str] = set()
        # entity -> ts a lock.lock was issued, until its read-back ran.
        self._away_engage_inflight: dict[str, float] = {}
        # True while the SC-disable release unlocks (not a manual unlock).
        self._disable_releasing: bool = False
        self._away_readback_unsubs: dict[str, Callable[[], None]] = {}
        self._away_dwell_unsub: Callable[[], None] | None = None
        self._away_pending_at: float | None = None
        # One engage attempt per all-away formation (M6). Cleared when any
        # listed person reads a real non-not_home state.
        self._away_attempted: bool = False
        # Fix-up B2: the formation the attempt belongs to (max listed
        # since-stamp at attempt time). Persisted, so a restart mid-outing
        # neither re-engages nor re-notifies.
        self._away_attempted_marker: float | None = None
        # Fix-up B1: bumped by every away release; an engage loop aborts
        # when it changed since the loop started.
        self._away_release_epoch: int = 0
        # Fix-up A5/B4: persisted in-flight engages, reconciled at setup.
        self._away_inflight_restored: set[str] = set()
        self._away_advisory_sent: bool = False
        # person -> ts the person was first seen not_home in this outing.
        # Persisted: the ONLY dwell source after a restart (H1).
        self._away_not_home_since: dict[str, float] = {}
        self.away_lock_last_action: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Live configuration (never a setup snapshot, Bug Class #14 / M-1)
    # ------------------------------------------------------------------

    def _cm_entry(self) -> Any:
        from ..const import (  # noqa: PLC0415
            CONF_ENTRY_TYPE,
            DOMAIN,
            ENTRY_TYPE_COORDINATOR_MANAGER,
        )

        try:
            for entry in self._hass.config_entries.async_entries(DOMAIN):
                if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_COORDINATOR_MANAGER:
                    return entry
        except Exception:  # noqa: BLE001
            return None
        return None

    def _cfg(self) -> dict[str, Any]:
        entry = self._cm_entry()
        if entry is None:
            return {}
        return {**(entry.data or {}), **(entry.options or {})}

    def kill_switch_on(self) -> bool:
        from ..const import (  # noqa: PLC0415
            CONF_SECURITY_GARAGE_LOCKOUT_ENABLED,
            DEFAULT_SECURITY_GARAGE_LOCKOUT_ENABLED,
        )

        return bool(
            self._cfg().get(
                CONF_SECURITY_GARAGE_LOCKOUT_ENABLED,
                DEFAULT_SECURITY_GARAGE_LOCKOUT_ENABLED,
            )
        )

    def _guest_toggle_on(self, cfg: dict[str, Any]) -> bool:
        from ..const import (  # noqa: PLC0415
            CONF_SECURITY_LOCKOUT_ENGAGE_ON_GUEST_SLEEP,
            DEFAULT_SECURITY_LOCKOUT_ENGAGE_ON_GUEST_SLEEP,
        )

        return bool(
            cfg.get(
                CONF_SECURITY_LOCKOUT_ENGAGE_ON_GUEST_SLEEP,
                DEFAULT_SECURITY_LOCKOUT_ENGAGE_ON_GUEST_SLEEP,
            )
        )

    def lockout_entities(self, cfg: dict[str, Any] | None = None) -> list[str]:
        from ..const import CONF_SECURITY_LOCKOUT_ENTITIES  # noqa: PLC0415

        cfg = self._cfg() if cfg is None else cfg
        raw = cfg.get(CONF_SECURITY_LOCKOUT_ENTITIES) or []
        if isinstance(raw, str):
            raw = [raw]
        return [str(e) for e in raw if isinstance(e, str) and e]

    def _excluded(self, cfg: dict[str, Any]) -> set[str]:
        from ..const import CONF_SECURITY_LOCKOUT_EXCLUDED_PERSONS  # noqa: PLC0415

        raw = cfg.get(CONF_SECURITY_LOCKOUT_EXCLUDED_PERSONS) or []
        if isinstance(raw, str):
            raw = [raw]
        return {str(p) for p in raw}

    def _distance_sensors(self, cfg: dict[str, Any]) -> list[str]:
        from ..const import CONF_SECURITY_LOCKOUT_DISTANCE_SENSORS  # noqa: PLC0415

        raw = cfg.get(CONF_SECURITY_LOCKOUT_DISTANCE_SENSORS) or []
        if isinstance(raw, str):
            raw = [raw]
        return [str(s) for s in raw if isinstance(s, str) and s]

    def sweep_exclude(self, cfg: dict[str, Any] | None = None) -> set[str]:
        """``security_lock_sweep_exclude`` as configured (live)."""
        from ..const import CONF_SECURITY_LOCK_SWEEP_EXCLUDE  # noqa: PLC0415

        cfg = self._cfg() if cfg is None else cfg
        return _as_set(cfg.get(CONF_SECURITY_LOCK_SWEEP_EXCLUDE))

    def away_lock_on(self, cfg: dict[str, Any] | None = None) -> bool:
        """Away-lock kill switch. Never the garage ``kill_switch_on`` (M4)."""
        from ..const import (  # noqa: PLC0415
            CONF_SECURITY_AWAY_LOCK_ENABLED,
            DEFAULT_SECURITY_AWAY_LOCK_ENABLED,
        )

        cfg = self._cfg() if cfg is None else cfg
        return bool(
            cfg.get(CONF_SECURITY_AWAY_LOCK_ENABLED, DEFAULT_SECURITY_AWAY_LOCK_ENABLED)
        )

    def away_lock_entities(self, cfg: dict[str, Any] | None = None) -> list[str]:
        from ..const import CONF_SECURITY_AWAY_LOCK_ENTITIES  # noqa: PLC0415

        cfg = self._cfg() if cfg is None else cfg
        return sorted(e for e in _as_set(cfg.get(CONF_SECURITY_AWAY_LOCK_ENTITIES)) if e)

    def away_lock_persons(self, cfg: dict[str, Any] | None = None) -> list[str]:
        from ..const import CONF_SECURITY_AWAY_LOCK_PERSONS  # noqa: PLC0415

        cfg = self._cfg() if cfg is None else cfg
        return sorted(
            p for p in _as_set(cfg.get(CONF_SECURITY_AWAY_LOCK_PERSONS))
            if p.startswith("person.")
        )

    def _num(self, cfg: dict[str, Any], key: str, default: float) -> float:
        try:
            return float(cfg.get(key, default))
        except (TypeError, ValueError):
            return float(default)

    def _sleep_hours(self, cfg: dict[str, Any]) -> tuple[int, int]:
        """Same CM keys Presence reads (__init__.py PresenceCoordinator ctor)."""
        from ..const import (  # noqa: PLC0415
            CONF_SLEEP_END_HOUR,
            CONF_SLEEP_START_HOUR,
            DEFAULT_SLEEP_END_HOUR,
            DEFAULT_SLEEP_START_HOUR,
        )

        start = int(self._num(cfg, CONF_SLEEP_START_HOUR, DEFAULT_SLEEP_START_HOUR))
        end = int(self._num(cfg, CONF_SLEEP_END_HOUR, DEFAULT_SLEEP_END_HOUR))
        return start, end

    # ------------------------------------------------------------------
    # Time helpers
    # ------------------------------------------------------------------

    def _ts(self) -> float:
        return self._now().timestamp()

    def _in_sleep_window(self, cfg: dict[str, Any], now: datetime | None = None) -> bool:
        start, end = self._sleep_hours(cfg)
        hour = (now or self._now()).hour
        if start == end:
            return False
        if start > end:
            return hour >= start or hour < end
        return start <= hour < end

    def _in_boot_window(self) -> bool:
        from ..const import GARAGE_LOCKOUT_BOOT_RECHECK_S  # noqa: PLC0415

        if self._setup_ts is None:
            return True
        return self._ts() < self._setup_ts + GARAGE_LOCKOUT_BOOT_RECHECK_S

    def _in_boot_arrival_window(self) -> bool:
        from ..const import GARAGE_LOCKOUT_BOOT_ARRIVAL_WINDOW_S  # noqa: PLC0415

        if self._setup_ts is None:
            return True
        return self._ts() < self._setup_ts + GARAGE_LOCKOUT_BOOT_ARRIVAL_WINDOW_S

    @staticmethod
    def _local_wall(day: Any, hour: int, minute: float, tzinfo: Any) -> datetime:
        """Local wall-clock datetime for ``day`` (DST-safe with a ZoneInfo tz:
        the offset is resolved for that date, not copied from ``now``)."""
        base = datetime(day.year, day.month, day.day, tzinfo=tzinfo)
        return datetime(
            base.year, base.month, base.day, hour, 0, tzinfo=tzinfo
        ) + timedelta(minutes=minute)

    def _backstop_delay_s(self, cfg: dict[str, Any], *, allow_immediate: bool = False) -> float:
        """Real seconds until the next morning backstop (review A M1 / L3).

        ``allow_immediate`` (boot rebuild only): a stale night lock found in
        the daytime, past today's deadline and before tonight's sleep start,
        releases now (deviation (d)). Every engage-time schedule uses the
        NEXT deadline, so an early SLEEP (e.g. override at 22:30 with
        sleep_start 23) holds until tomorrow morning.
        """
        from ..const import (  # noqa: PLC0415
            CONF_GARAGE_LOCKOUT_MORNING_BACKSTOP_MIN,
            GARAGE_LOCKOUT_MORNING_BACKSTOP_MIN,
        )

        start, end = self._sleep_hours(cfg)
        backstop_min = max(
            0.0,
            self._num(
                cfg,
                CONF_GARAGE_LOCKOUT_MORNING_BACKSTOP_MIN,
                GARAGE_LOCKOUT_MORNING_BACKSTOP_MIN,
            ),
        )
        now = self._now()
        today_deadline = self._local_wall(now.date(), end, backstop_min, now.tzinfo)
        if now.timestamp() < today_deadline.timestamp():
            return today_deadline.timestamp() - now.timestamp()
        if allow_immediate and now.hour < start:
            return 0.0
        tomorrow = self._local_wall(
            now.date() + timedelta(days=1), end, backstop_min, now.tzinfo
        )
        return tomorrow.timestamp() - now.timestamp()

    def _seconds_until_hour(self, hour: int) -> float:
        now = self._now()
        target = self._local_wall(now.date(), hour, 0, now.tzinfo)
        if target.timestamp() <= now.timestamp():
            target = self._local_wall(now.date() + timedelta(days=1), hour, 0, now.tzinfo)
        return target.timestamp() - now.timestamp()

    # ------------------------------------------------------------------
    # House state + gates
    # ------------------------------------------------------------------

    def _house_state(self) -> str | None:
        from ..const import DOMAIN  # noqa: PLC0415

        manager = self._hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        try:
            state = manager.house_state
        except Exception:  # noqa: BLE001
            return None
        if state is None:
            return None
        return str(getattr(state, "value", state))

    def _sc_alive(self) -> bool:
        return (
            not self._torn_down
            and bool(getattr(self._sc, "enabled", True))
            and not bool(getattr(self._sc, "_shutting_down", False))
        )

    def _is_resident(self, person: str, cfg: dict[str, Any]) -> bool:
        return person.startswith("person.") and person not in self._excluded(cfg)

    # ------------------------------------------------------------------
    # Setup / teardown
    # ------------------------------------------------------------------

    async def async_setup(self) -> None:
        self._setup_ts = self._ts()
        cfg = self._cfg()

        persisted: set[str] = set()
        if self._store is not None:
            try:
                data = await self._store.async_load()
                # D3g: each key is loaded independently; a missing or bad
                # away-lock key never affects the resident set.
                self._load_away_store(data)
                raw = data.get("residents") if isinstance(data, dict) else None
                if isinstance(raw, list) and all(isinstance(p, str) for p in raw):
                    persisted = {p for p in raw if p.startswith("person.")}
                elif data is not None:
                    # Review B-L3: a corrupt shape (e.g. a string) must not be
                    # iterated into bogus subscriptions.
                    _LOGGER.warning(
                        "Lock regime: resident store has an unexpected shape; ignoring it"
                    )
            except Exception:  # noqa: BLE001
                _LOGGER.warning(
                    "Lock regime: resident store load failed; using the live "
                    "person domain",
                    exc_info=True,
                )
        live: set[str] = set()
        try:
            live = {s.entity_id for s in self._hass.states.async_all("person")}
        except Exception:  # noqa: BLE001
            live = set()
        # Subscribe EVERY person (exclusions are filtered at event time), so
        # an options edit of the exclusion list is live without a reload.
        excluded = self._excluded(cfg)
        for pid in sorted(live | persisted):
            self._subscribe_person(pid)
        self._residents = (live | persisted) - excluded
        self._away_setup(cfg)
        self._save_store()

        if self._track_added_domain is not None:
            self._other_unsubs.append(
                self._track_added_domain(self._hass, "person", self._on_person_added)
            )
        if self._track_removed_domain is not None:
            self._other_unsubs.append(
                self._track_removed_domain(
                    self._hass, "person", self._on_person_removed
                )
            )

        # Review A L2: forget an issued lock.lock once the lockout reads locked.
        lockouts = self.lockout_entities(cfg)
        if lockouts:
            self._other_unsubs.append(
                self._track_state(self._hass, lockouts, self._on_lockout_event)
            )
        # D3d: away-lock ownership loss (a human unlocked it).
        away_ents = self.away_lock_entities(cfg)
        if away_ents:
            self._other_unsubs.append(
                self._track_state(self._hass, away_ents, self._on_away_lock_event)
            )

        sensors = self._distance_sensors(cfg)
        if sensors:
            self._distance_unsub = self._track_state(
                self._hass, sensors, self._on_distance_event
            )

        self._ensure_pc_listener()
        self._boot_rebuild(cfg)
        self._boot_recheck_unsub = self._call_later(
            self._hass, self._boot_recheck_delay(), self._on_boot_recheck
        )
        start, _end = self._sleep_hours(cfg)
        self._guest_clock_unsub = self._call_later(
            self._hass, self._seconds_until_hour(start), self._on_guest_clock
        )

    def _boot_recheck_delay(self) -> float:
        from ..const import GARAGE_LOCKOUT_BOOT_RECHECK_S  # noqa: PLC0415

        return float(GARAGE_LOCKOUT_BOOT_RECHECK_S)

    def _boot_rebuild(self, cfg: dict[str, Any]) -> None:
        """Boot never engages and never releases on a resident reading home;
        it only rebuilds ``reason`` (H1).

        Review A H1: there is NO setup-time "recent arrival" release. HA's
        person restore writes a fresh State (last_changed = boot time), so
        such a rule fired on every night restart with anyone home. Real
        arrivals during a restart are caught by the boot-arrival window in
        ``_arrival_counts`` (any -> home edge within 600 s of setup).
        """
        if not self.kill_switch_on():
            return
        locked = [
            e for e in self.lockout_entities(cfg)
            if _state_value(self._hass.states.get(e)) == "locked"
        ]
        if not locked:
            # R2-4: reason is not persisted, so a restored taint with nothing
            # locked is stale; nothing can be released with reason NONE.
            self._end_episode_arrival_flags()
            return
        house = self._house_state()
        if house == "sleep":
            self.reason = REASON_SLEEP
            self._end_episode_arrival_flags()
        elif house == "vacation":
            self.reason = REASON_VACATION
            self._end_episode_arrival_flags()
        else:
            # Deliberate no-clear write: a restart is inside the episode, so a
            # restored taint is kept (plan D1 item 3 allowlist).
            self.reason = REASON_BOOT_UNKNOWN
            if house in ("away", "arriving"):
                # H2 / F5: a lock found locked while the house reads empty or
                # arriving is an excursion the regime may never see an edge of.
                self._arrival_taint = True
                self._episode_saw_arriving = True
                self._save_store()
        self._record("boot_rebuild", trigger=f"boot:{house}", written=[])
        if self.reason in SLEEP_LIKE_REASONS:
            self._schedule_backstop(cfg, allow_immediate=True)

    @callback
    def _on_boot_recheck(self, _now: Any = None) -> None:
        self._boot_recheck_unsub = None
        if self._torn_down:
            return
        self._ensure_pc_listener()
        if self.reason == REASON_BOOT_UNKNOWN:
            house = self._house_state()
            if house == "sleep":
                self.reason = REASON_SLEEP
                self._end_episode_arrival_flags()
            elif house == "vacation":
                self.reason = REASON_VACATION
                self._end_episode_arrival_flags()
                self._cancel_backstop()
        # LOCK-BOOT-RECHECK-ENGAGE-1: engage or release to match the house.
        try:
            self._boot_recheck_regime()
        except Exception:  # noqa: BLE001 — never block the away-lock rearm
            _LOGGER.exception("Lock regime: boot recheck decision failed")
        # D3e (H1): arm the away-lock dwell for the remainder, from the
        # persisted not_home stamps. Replayed boot edges never armed it.
        self._away_boot_discharge(self._cfg())
        self._away_rearm(self._cfg())
        missing = sorted(
            pid for pid in self._residents if self._hass.states.get(pid) is None
        )
        if missing and missing != self.missing_residents:
            _LOGGER.warning(
                "Lock regime: resident person entities have no state after "
                "the boot recheck: %s",
                missing,
            )
        self.missing_residents = missing

    async def async_teardown(self) -> None:
        """Cancel every regime timer, tracker and task (H3d)."""
        self._torn_down = True
        for unsub in list(self._person_unsubs.values()) + list(self._other_unsubs):
            _safe_unsub(unsub)
        self._person_unsubs.clear()
        self._other_unsubs.clear()
        for attr in (
            "_distance_unsub",
            "_backstop_unsub",
            "_boot_recheck_unsub",
            "_guest_clock_unsub",
            "_reengage_unsub",
            "_away_dwell_unsub",
            "_pc_listener_unsub",
        ):
            _safe_unsub(getattr(self, attr))
            setattr(self, attr, None)
        self._away_pending_at = None
        self._pc_listened = None
        self._pending_faces.clear()
        for held in self._held_edges.values():
            _safe_unsub(held.get("unsub"))
        self._held_edges.clear()
        for unsub in self._still_locked_unsubs.values():
            _safe_unsub(unsub)
        self._still_locked_unsubs.clear()
        for unsub in self._readback_unsubs.values():
            _safe_unsub(unsub)
        self._readback_unsubs.clear()
        for unsub in self._away_readback_unsubs.values():
            _safe_unsub(unsub)
        self._away_readback_unsubs.clear()
        # Review B-M1: an unlock already in flight is a family-release
        # discharge; let it finish (bounded) instead of cancelling it, or a
        # reload mid-release strands the lockout (the new instance never
        # releases at boot, review A H1). Chosen over a persisted "release
        # pending" Store mark: the only teardown path is a reload in the same
        # process (HA stop does not run teardown), so awaiting discharges it
        # without a second persisted state machine to reconcile at boot.
        from ..const import GARAGE_LOCKOUT_TEARDOWN_RELEASE_TIMEOUT_S  # noqa: PLC0415

        pending = [t for t in self._unlock_tasks if not t.done()]
        if pending:
            try:
                await asyncio.wait(
                    pending, timeout=GARAGE_LOCKOUT_TEARDOWN_RELEASE_TIMEOUT_S
                )
            except Exception:  # noqa: BLE001
                _LOGGER.debug("Lock regime: awaiting unlocks raised", exc_info=True)
        for task in list(self._tasks):
            if not task.done():
                task.cancel()
        self._tasks.clear()
        self._unlock_tasks.clear()
        # Fix-up B5: flush the Store now; a delayed save could otherwise be
        # overwritten by the next instance's setup save after a reload.
        save_now = getattr(self._store, "async_save", None)
        if save_now is not None:
            try:
                await save_now(self._store_payload())
            except Exception:  # noqa: BLE001
                _LOGGER.debug("Lock regime: store flush at teardown failed", exc_info=True)

    async def async_release_if_disabled(self) -> None:
        """C1 + M-1: release on the real SC-disable path, before teardown.

        Reads the LIVE CM entry. The Enabled switch writes
        ``security_coordinator_enabled: False`` before it reloads the
        integration (switch.py CoordinatorEnabledSwitch.async_turn_off), so
        a disable reads False here; a restart or ordinary reload reads True
        and releases nothing. No CM entry = the deletion residual (L-6).
        """
        from ..const import GARAGE_LOCKOUT_TEARDOWN_RELEASE_TIMEOUT_S  # noqa: PLC0415
        from ..coordinator_gate import coordinator_should_run  # noqa: PLC0415

        entry = self._cm_entry()
        if entry is None:
            return
        cfg = {**(entry.data or {}), **(entry.options or {})}
        if coordinator_should_run(cfg, "security", hass=None):
            return
        await self._garage_release_on_disable(cfg)
        # M4: the away lock is released independently of the garage switch.
        await self._away_release_on_disable()

    async def _garage_release_on_disable(self, cfg: dict[str, Any]) -> None:
        """Garage branch of the SC-disable release (unchanged behaviour)."""
        from ..const import GARAGE_LOCKOUT_TEARDOWN_RELEASE_TIMEOUT_S  # noqa: PLC0415

        if not self.kill_switch_on():
            return
        self.release_gen += 1
        self._disable_releasing = True
        try:
            await self._garage_release_on_disable_loop(cfg)
        finally:
            self._disable_releasing = False
        self.reason = REASON_NONE
        self._end_episode_arrival_flags()
        self._clear_manual_unlock()

    async def _garage_release_on_disable_loop(self, cfg: dict[str, Any]) -> None:
        from ..const import GARAGE_LOCKOUT_TEARDOWN_RELEASE_TIMEOUT_S  # noqa: PLC0415

        for ent in self.lockout_entities(cfg):
            if _state_value(self._hass.states.get(ent)) != "locked":
                continue
            try:
                await asyncio.wait_for(
                    self._hass.services.async_call(
                        "lock", "unlock", {"entity_id": ent}, blocking=True,
                        **_ctx_kwargs(),
                    ),
                    timeout=GARAGE_LOCKOUT_TEARDOWN_RELEASE_TIMEOUT_S,
                )
                self._record("release", trigger="sc_disabled", written=[ent])
            except Exception:  # noqa: BLE001 — includes TimeoutError
                _LOGGER.warning(
                    "Lock regime: release of %s on SC disable failed", ent,
                    exc_info=True,
                )
                await self._notify_failure(ent, "sc_disabled", timeout=True)

    # ------------------------------------------------------------------
    # Inputs
    # ------------------------------------------------------------------

    def on_house_state_changed(self, payload: Any) -> None:
        """Fed from SC's house-state bridge BEFORE its auto-follow return."""
        if self._torn_down:
            return
        if isinstance(payload, dict):
            new = str(payload.get("new_state", "") or "")
            old = str(payload.get("old_state", "") or "")
            trig = str(payload.get("trigger", "") or "")
        else:
            new = str(getattr(payload, "new_state", "") or "")
            old = str(getattr(payload, "old_state", "") or "")
            trig = str(getattr(payload, "trigger", "") or "")
        override = trig == "override_set"
        self._last_house_edges.append((new, old, trig, self._ts()))
        # LOCK-RELEASE-ON-ARRIVING D1 item 2: taint BEFORE the decision and
        # before every later return. old_state == arriving closes H2 (a
        # boot-settle-suppressed ARRIVING first seen as arriving -> HOME_*).
        if (
            self.reason != REASON_NONE
            and not override
            and (new == "arriving" or old == "arriving")
        ):
            changed = not (self._arrival_taint and self._episode_saw_arriving)
            self._arrival_taint = True
            self._episode_saw_arriving = True
            if changed:
                self._save_store()
        if not new:
            return
        cfg = self._cfg()
        kind, engage_reason = self._edge_decision(new, cfg, override=override)
        if kind == "release":
            # _after_release clears a remembered manual unlock (episode over).
            self._release(f"house_state:{new}", override=override)
            return
        if kind == "arriving_hold":
            # Body evidence only: the episode stays open (reason, backstop,
            # re-engage and the manual-unlock memory are all kept).
            self.arriving_holds += 1
            self._record(
                "arriving_hold", trigger=f"house_state:{new}", written=[],
                extra={"reason": self.reason, "old_state": old},
            )
            return
        if kind == "none" and (new in _HOME_STATES or new == "waking"):
            # Review B-2: an awake edge ends any episode even when reason is
            # already NONE (hazard / kill switch / vacation arrival forced it):
            # drop a remembered mark so it cannot leak into the next episode.
            self._clear_manual_unlock()
            return
        if kind == "guest_yield_hold":
            # INV-LOCK-1 (GUEST-MODE-SPLIT rev 5, build review B-M1): see
            # _edge_decision.
            self._record("guest_yield_hold", trigger="house_state:home_night", written=[])
            return
        if engage_reason is None:
            return  # AWAY, GUEST outside the window or toggle OFF: inert
        if not self.kill_switch_on():
            return
        self._set_engage_reason(engage_reason, cfg)
        if self._in_boot_window():
            # M1: boot replays (incl. boot_settle_override) rebuild only.
            # LOCK-BOOT-RECHECK-ENGAGE-1: _on_boot_recheck re-asks.
            self._record("boot_edge_rebuild", trigger=f"house_state:{new}", written=[])
            return
        # A live engage edge starts a new episode.
        self._clear_manual_unlock()
        self._request_engage(engage_reason, f"house_state:{new}")

    def _edge_decision(
        self, new: str, cfg: dict[str, Any], *, override: bool = False
    ) -> tuple[str, str | None]:
        """What a house-state edge to ``new`` means for the lockouts.

        Shared by ``on_house_state_changed`` and the boot recheck
        (LOCK-BOOT-RECHECK-ENGAGE-1). Returns ``("release", None)``,
        ``("guest_yield_hold", None)``, ``("arriving_hold", None)``,
        ``("engage", reason)`` or ``("none", None)``. Pure: no command, no
        state change.

        LOCK-RELEASE-ON-ARRIVING D1 item 4: ARRIVING is body evidence with no
        identity, so it never releases an engaged episode (``arriving_hold``)
        and, with reason NONE, does nothing (it no longer unlocks a lockout
        locked by hand, F19). HOME_* in a tainted episode is held too. Only an
        operator ``override_set`` edge (``override``) keeps today's release.
        """
        if new == "waking":
            if self.reason in SLEEP_LIKE_REASONS:
                return "release", None
            return "none", None
        if (
            new == "home_night"
            and self.reason == REASON_GUEST_NIGHT
            and self._in_sleep_window(cfg)
        ):
            # INV-LOCK-1: the presence night yield takes GUEST -> HOME_NIGHT
            # ~5 min after the guest-night clock locked. Hold the lock (lock
            # once, at the guest-night clock); WAKING / HOME_DAY /
            # HOME_EVENING (untainted) / resident arrival / the backstop still
            # release (ARRIVING no longer does, LOCK-RELEASE-ON-ARRIVING). A manual override GUEST -> HOME_NIGHT in the window is
            # held too (the regime cannot tell the two apart; plan R26).
            return "guest_yield_hold", None
        if new in _HOME_STATES:
            if self.reason != REASON_NONE:
                if self._arrival_taint and not override:
                    return "arriving_hold", None
                return "release", None
            return "none", None
        if new == "arriving":
            if override:
                return "release", None
            if self.reason != REASON_NONE:
                return "arriving_hold", None
            return "none", None
        if new == "sleep":
            return "engage", REASON_SLEEP
        if new == "vacation":
            return "engage", REASON_VACATION
        if new == "guest" and self._guest_toggle_on(cfg) and self._in_sleep_window(cfg):
            return "engage", REASON_GUEST_NIGHT
        return "none", None

    def _set_engage_reason(self, engage_reason: str, cfg: dict[str, Any]) -> None:
        # Every engage (live, boot-window, boot-recheck, guest clock) is an
        # episode boundary (LOCK-RELEASE-ON-ARRIVING D1 item 3).
        self._end_episode_arrival_flags()
        self.reason = engage_reason
        if engage_reason in SLEEP_LIKE_REASONS:
            self._schedule_backstop(cfg)
        else:
            self._cancel_backstop()

    def _end_episode_arrival_flags(self) -> None:
        """Clear the ARRIVING taint and the D3 saw flag (episode boundary).

        The ONE clear site (plan D1 item 3): engages, the boot SLEEP /
        VACATION rebuilds, the nothing-locked boot return and every
        ``reason = NONE`` write. Never a person / approach / proximity /
        arriving-signal release (F1).
        """
        if self._arrival_taint or self._episode_saw_arriving:
            self._arrival_taint = False
            self._episode_saw_arriving = False
            self._save_store()

    def _boot_recheck_regime(self) -> None:
        """LOCK-BOOT-RECHECK-ENGAGE-1: "do I need to be locked now?".

        Boot edges only rebuild ``reason`` (M1), so a restart during SLEEP
        left unlocked lockouts unlocked, and a BOOT_UNKNOWN lock stayed on
        in an awake house. At the recheck, drive the same decision a real
        edge to the CURRENT house state would take (``_edge_decision``),
        through the same engage (``_request_engage``) and release
        (``_release``) paths. No command when the state is already correct.
        """
        if not self.kill_switch_on():
            return
        house = self._house_state()
        if not house or house in _UNREAL_STATES:
            _LOGGER.debug("Lock regime: boot recheck skipped, house state %s", house)
            return
        cfg = self._cfg()
        vals = {e: _state_value(self._hass.states.get(e)) for e in self.lockout_entities(cfg)}
        locked = sorted(e for e, v in vals.items() if v == "locked")
        unlocked = sorted(e for e, v in vals.items() if v == "unlocked")
        if (
            self.reason == REASON_BOOT_UNKNOWN
            and house == "home_night"
            and self._guest_toggle_on(cfg)
            and self._in_sleep_window(cfg)
        ):
            # INV-LOCK-1: a lock found at boot in a home_night sleep window
            # with the guest toggle on may be the guest-night lock after the
            # yield. Treat it as one: hold now; later edges / backstop release.
            # Deliberate no-clear write (R2-1): BOOT_UNKNOWN -> GUEST_NIGHT is
            # the same episode; a restored taint and saw flag are kept.
            self.reason = REASON_GUEST_NIGHT
        if house == "arriving" and self.reason != REASON_NONE:
            # H1 / F5: the house reads ARRIVING at the recheck (boot settle may
            # have swallowed the edge). Taint before the decision.
            self._arrival_taint = True
            self._episode_saw_arriving = True
            self._save_store()
        kind, engage_reason = self._edge_decision(house, cfg)
        remembered = self.manual_unlock_reason
        # F6 / M7: ARRIVING and a tainted HOME_* do not end the episode.
        ended = kind == "release" or (
            kind not in ("guest_yield_hold", "arriving_hold")
            and (house in _HOME_STATES or house == "waking")
        )
        if remembered is not None and (
            ended or (kind == "engage" and engage_reason != remembered)
        ):
            # The remembered episode ended across the restart.
            self._clear_manual_unlock()
            remembered = None
        decision = "no_change"
        act: Callable[[], None] | None = None
        if kind == "release":
            if self.reason == REASON_BOOT_UNKNOWN and locked:
                decision = "release"
                act = functools.partial(self._release, "boot_recheck")
        elif kind == "guest_yield_hold":
            decision = "guest_yield_hold"
        elif kind == "arriving_hold":
            # Never released at boot on body evidence, whatever a resident
            # reads (M2: the "resident reads home" rule is deleted).
            decision = "arriving_hold"
        elif kind == "engage" and engage_reason is not None:
            if not unlocked:
                decision = "already_locked"
                if self.reason in (REASON_NONE, REASON_BOOT_UNKNOWN):
                    self._set_engage_reason(engage_reason, cfg)
            elif engage_reason in (REASON_SLEEP, REASON_GUEST_NIGHT) and not (
                self._in_sleep_window(cfg)
                and self._backstop_delay_s(cfg, allow_immediate=True) > 0
            ):
                # Review A HIGH: a house still reading SLEEP after the
                # backstop deadline (no wake edge) must not re-lock and push
                # the backstop to tomorrow (locked all day).
                decision = "past_backstop_no_catchup"
            elif remembered == engage_reason:
                # INV-5 (operator 2026-11-10, option B): a manual unlock in
                # this episode was persisted; a restart never re-locks it.
                # The reason is rebuilt so later edges / backstop behave.
                decision = "manual_unlock_remembered"
                if self.reason in (REASON_NONE, REASON_BOOT_UNKNOWN):
                    self._set_engage_reason(engage_reason, cfg)
            elif self._arrival_since_setup():
                # An arrival inside the boot-arrival window released (or
                # would have); the re-engage machinery owns re-locking.
                decision = "arrival_suppressed"
            else:
                decision = "engage"
                self._set_engage_reason(engage_reason, cfg)
                act = functools.partial(
                    self._request_engage, engage_reason, "boot_recheck"
                )
        self._record(
            "boot_recheck", trigger=f"boot_recheck:{house}", written=[],
            extra={
                "decision": decision, "locked": locked, "unlocked": unlocked,
                "arrival_since_setup": self._arrival_since_setup(),
            },
        )
        if act is not None:
            act()

    def _arrival_since_setup(self) -> bool:
        """A resident arrival released (or tried to) since setup."""
        setup = self._setup_ts if self._setup_ts is not None else 0.0
        return any(
            float(info.get("at", 0.0)) >= setup for info in self.releasing_set.values()
        )

    @callback
    def _on_guest_clock(self, _now: Any = None) -> None:
        """Q-G1: house already reads GUEST at sleep_start_hour -> engage."""
        self._guest_clock_unsub = None
        if self._torn_down:
            return
        cfg = self._cfg()
        start, _end = self._sleep_hours(cfg)
        self._guest_clock_unsub = self._call_later(
            self._hass, max(60.0, self._seconds_until_hour(start)), self._on_guest_clock
        )
        if (
            self.kill_switch_on()
            and self._guest_toggle_on(cfg)
            and self._house_state() == "guest"
            and not self._in_boot_window()
        ):
            # Routed through the engage choke point (byte-identical: same
            # reason write + backstop; it also ends the ARRIVING taint, M3).
            self._set_engage_reason(REASON_GUEST_NIGHT, cfg)
            self._request_engage(REASON_GUEST_NIGHT, "guest_clock")

    def on_person_arriving(self, payload: Any) -> None:
        """P2, fed from SC above its enabled/observation returns."""
        if self._torn_down or payload is None:
            return
        if isinstance(payload, dict):
            person = str(payload.get("person_entity", "") or "")
        else:
            person = str(getattr(payload, "person_entity", "") or "")
        if not person:
            return
        if isinstance(payload, dict):
            source = payload.get("source")
        else:
            source = getattr(payload, "source", None)
        # LOCK-REGIME-FACE-ARRIVAL-CORROBORATION-1 (operator 2026-11-08): a
        # camera_face arrival can name a resident who IS away (10-24: Frigate
        # labelled Jaya as Oji while Oji was abroad), which passes the
        # really-away gate below. A face counts only with an independent
        # arrival edge for the SAME person (v5.107.0 D10.5 rule, shared
        # arrival_edges helper). Non-face sources are unchanged.
        # FACE-ARRIVAL-REBUILD-1 D3: membership in the ONE camera-derived set
        # (`const.CAMERA_DERIVED_ARRIVAL_SOURCES`) through the shared
        # classifier, not a literal; an unknown source fails closed, a missing
        # source (None) is develop behaviour (not camera-derived).
        self._ensure_pc_listener()
        if (
            arrival_source_needs_corroboration(source)
            and not self._face_arrival_corroborated(person)
        ):
            # Review A MED-1: a Bermuda entry move that lands AFTER the face
            # (inside the window) re-checks this face once (_on_pc_update).
            self._pending_faces[person] = self._ts()
            _LOGGER.info(
                "Lock regime: %s arrival for %s held "
                "(no independent arrival edge yet)", source, person,
            )
            return
        self._apply_arrival(person)

    def _apply_arrival(self, person: str) -> None:
        """P2 effects once an arrival counts (unchanged pre-v5.107.4 body)."""
        cfg = self._cfg()
        # Suspicious-arrival hold D3 (S6-S8: geofence / ble / camera_face and
        # the held-face recheck all land here): while this person's edge is
        # held, or the person reads home on a stale source, drop the signal.
        # Not queued: a confirmed edge replays P1, a superset of these effects
        # for the same person; a cancelled one is not replayed (F5, by design).
        if self._hold_s(cfg) > 0 and (
            person in self._held_edges
            or (not self._in_boot_arrival_window() and self._stale(person))
        ):
            self.arrival_signal_held += 1
            return
        # Away lock P2 (D3c): a listed person, same really-away gate.
        away_p2 = person in self.away_lock_persons(cfg)
        if self._is_resident(person, cfg):
            # Review A M2: Presence also dispatches this signal for any face
            # seen on ANY zone camera, interior included (source camera_face),
            # so "arriving" is not a physical arrival. Count it only when the
            # person was really away (same rule + boot exceptions as P1 blips).
            if self._really_away(person, self._ts()):
                self._release("arriving_signal", person=person)
        if away_p2 and self._really_away(person, self._ts()):
            self._away_release("arriving_signal")

    def on_hazard(self) -> None:
        """Critical smoke/fire/CO with egress unlock configured."""
        if self._torn_down:
            return
        # Review B-1: remember the episode so a restart in the same episode
        # (power loss during a fire is plausible) never re-locks via the
        # boot catch-up. Captured before reason is forced to NONE.
        episode = self._episode_reason()
        self._cancel_reengage()
        self._release("hazard")
        self.reason = REASON_NONE
        self._end_episode_arrival_flags()
        self._remember_episode_released(episode)
        self._away_release("hazard")

    def on_kill_switch_changed(self, enabled: bool, key: str | None = None) -> None:
        """ON -> OFF releases once. OFF -> ON never catches up (INV-5).

        ``key`` routes by the switch's conf key (D4): the away-lock switch
        releases only away-lock-owned locks; any other key (or None) is the
        garage kill switch, unchanged.
        """
        from ..const import CONF_SECURITY_AWAY_LOCK_ENABLED  # noqa: PLC0415

        if key == CONF_SECURITY_AWAY_LOCK_ENABLED:
            if self._torn_down or enabled:
                return
            self._away_release("kill_switch_off")
            return
        if self._torn_down or enabled:
            return
        # Review B-5: OFF -> ON never catches up (INV-5), including across a
        # restart in the same episode: remember the episode like a manual
        # unlock. A later new episode (a live engage edge) clears it.
        episode = self._episode_reason()
        self._cancel_reengage()
        self._cancel_backstop()
        self._release("kill_switch_off", force=True)
        self.reason = REASON_NONE
        self._end_episode_arrival_flags()
        self._remember_episode_released(episode)

    def _subscribe_person(self, pid: str) -> None:
        if pid in self._person_unsubs:
            return
        self._person_unsubs[pid] = self._track_state(
            self._hass, [pid], self._on_person_event
        )

    @callback
    def _on_person_added(self, event: Any) -> None:
        pid = event.data.get("entity_id", "")
        if not pid or self._torn_down or not pid.startswith("person."):
            return
        self._subscribe_person(pid)
        if not self._is_resident(pid, self._cfg()):
            return
        self._residents.add(pid)
        if pid in self.releasing_set:
            self.releasing_set[pid]["removed"] = False
        self._save_store()

    @callback
    def _on_person_removed(self, event: Any) -> None:
        pid = event.data.get("entity_id", "")
        if not pid or self._torn_down:
            return
        unsub = self._person_unsubs.pop(pid, None)
        _safe_unsub(unsub)
        self._residents.discard(pid)
        # Review B-L1: a removed person's pending hold is moot.
        self._drop_hold(pid)
        # L-5: keep an en-route member blocking re-engage until re-added
        # or the max wait passes.
        if pid in self.releasing_set:
            self.releasing_set[pid]["removed"] = True
        self._save_store()

    @callback
    def _on_person_event(self, event: Any) -> None:
        if self._torn_down:
            return
        pid = event.data.get("entity_id", "")
        new = event.data.get("new_state")
        old = event.data.get("old_state")
        cfg = self._cfg()
        if new is None:
            return
        # Plan rev 3 §2.2 / Build DO: _last_real is kept for EVERY person.*
        # (an away-lock person may be a lockout-excluded person); the garage
        # effects below stay resident-gated, byte-identical.
        new_val = _state_value(new)
        now_ts = self._ts()
        if old is None:
            # Entity (re)added, e.g. HA person restore: not an arrival edge;
            # stamp last_real as restored (M-2). A pending hold is moot.
            self._drop_hold(pid)
            if new_val not in _UNREAL_STATES:
                self._last_real[pid] = (new_val, now_ts, True)
            self._away_on_person(pid, None, new_val, now_ts, cfg)
            return
        old_val = _state_value(old)
        held = self._held_edges.get(pid)
        if held is not None:
            if new_val == held["new_val"]:
                # F1: a same-state event (attribute-only `home -> home`, a
                # source switch, a lat/lon refresh) keeps the hold and is
                # otherwise ignored; the held body runs once, at confirm. A
                # synthetic (proximity-made) hold adopts the real edge's
                # pre-edge value.
                if held.get("synthetic") and old_val != new_val:
                    held["old_val"] = old_val
                    held["synthetic"] = False
                return
            self._drop_hold(pid)
            if new_val == held["old_val"]:
                # The revert: the edge and its revert cancel as a pair, no
                # state change (INV-H3). Processing the revert would reset
                # the away-lock outing stamp (_away_on_person, a "real leave").
                self._record(
                    "arrival_hold_cancelled", trigger=f"person:{pid}", written=[],
                    extra={"held": held["new_val"], "edge_ts": held["edge_ts"]},
                )
                # Review B-M1: another listed person's edge inside the hold
                # may have delegated the away-lock re-arm to this person (its
                # _away_rearm saw the held `home` and dropped the dwell).
                # Re-arm here; _away_rearm changes no stamp (INV-H3 holds).
                if not self._in_boot_window():
                    self._away_rearm(cfg)
                return
            # Any other value: as if the held edge never happened.
            old_val = held["old_val"]
        if self._should_hold(pid, old_val, new_val, new, cfg):
            self._start_hold(pid, old_val, new_val, now_ts, cfg)
            return
        self._process_person_edge(pid, old_val, new_val, now_ts, cfg)

    def _process_person_edge(
        self,
        pid: str,
        old_val: str | None,
        new_val: str | None,
        edge_ts: float,
        cfg: dict[str, Any],
    ) -> None:
        """The person-edge body (S1-S5), unchanged; ``edge_ts`` is the edge's
        own time (now on the direct path, the held edge's ts on confirm)."""
        resident = self._is_resident(pid, cfg)
        # Face-arrival corroboration: record LIVE not_home -> home edges
        # (shared arrival_edges rule; old None returned by the listener).
        slug = live_arrival_slug({
            "entity_id": pid,
            "old_state": _Val(old_val),
            "new_state": _Val(new_val),
        })
        if slug:
            self._arrival_edges[slug] = edge_ts
        self._ensure_pc_listener()
        if resident:
            if new_val == "home" and old_val != "home":
                if self._arrival_counts(pid, old_val, edge_ts):
                    self._release(f"person:{pid}", person=pid)
                    # D4a: anchored AFTER the S1 call (post-hold, F3).
                    self._schedule_still_locked(pid, "arrival")
                elif self._uncounted_return_pages(pid, old_val):
                    # D4b (INV-REAL-B): a page, never a release (plan §11 Q4).
                    self.uncounted_returns += 1
                    self._record(
                        "arrival_uncounted", trigger=f"person:{pid}", written=[],
                        extra={"old_state": old_val},
                    )
                    self._schedule_still_locked(pid, "uncounted")
            elif new_val not in _UNREAL_STATES and new_val != old_val:
                if self._is_approach_zone(new_val, cfg):
                    self._release(f"approach_zone:{pid}", person=pid)
        # Away lock: before _last_real moves, so P1 sees the pre-edge state.
        self._away_on_person(pid, old_val, new_val, edge_ts, cfg)
        if new_val not in _UNREAL_STATES:
            prev = self._last_real.get(pid)
            if prev is None or prev[0] != new_val or prev[2]:
                self._last_real[pid] = (new_val, edge_ts, False)

    # ------------------------------------------------------------------
    # D4 still-locked trip-wire (LOCK-RELEASE-ON-ARRIVING plan rev 3)
    # ------------------------------------------------------------------

    def _uncounted_return_pages(self, pid: str, old_val: str | None) -> bool:
        """D4b: a resident ``unknown/unavailable -> home`` edge that
        ``_arrival_counts`` rejected, in an engaged episode that saw ARRIVING
        (persisted taint, R2-3) or while the house reads away / arriving."""
        from ..const import (  # noqa: PLC0415
            LOCK_RELEASE_ARRIVAL_STILL_LOCKED_S,
            LOCK_RELEASE_UNCOUNTED_RETURN_PAGE_ENABLED,
        )

        return (
            old_val in _UNREAL_STATES
            and LOCK_RELEASE_UNCOUNTED_RETURN_PAGE_ENABLED
            and float(LOCK_RELEASE_ARRIVAL_STILL_LOCKED_S) > 0
            and self.kill_switch_on()
            and self.reason != REASON_NONE
            and (self._arrival_taint or self._house_state() in ("away", "arriving"))
        )

    def _schedule_still_locked(self, pid: str, kind: str) -> None:
        from ..const import LOCK_RELEASE_ARRIVAL_STILL_LOCKED_S  # noqa: PLC0415

        window = float(LOCK_RELEASE_ARRIVAL_STILL_LOCKED_S)
        if window <= 0 or not self.kill_switch_on():
            return
        anchor = self._ts()
        # Wall clock for comparing HA State.last_changed (the injected clock
        # is dt_util.now in production; aware datetimes compare across tz).
        anchor_wall = self._now()
        seq = self.engage_seq
        _safe_unsub(self._still_locked_unsubs.pop(pid, None))
        self._still_locked_unsubs[pid] = self._call_later(
            self._hass,
            window,
            functools.partial(self._on_still_locked, pid, anchor, anchor_wall, seq, kind),
        )

    @callback
    def _on_still_locked(
        self,
        pid: str,
        anchor: float,
        anchor_wall: datetime,
        seq: int,
        kind: str,
        _now: Any = None,
    ) -> None:
        """INV-PAGE / INV-REAL-B: one NM HIGH per lockout still ``locked``."""
        self._still_locked_unsubs.pop(pid, None)
        if self._torn_down or not self.kill_switch_on():
            return
        if self.engage_seq != seq:
            return  # we locked again since the arrival (F2)
        for ent in self.lockout_entities():
            st = self._hass.states.get(ent)
            if _state_value(st) != "locked":
                continue
            if self._failure_nm_at.get(ent, 0.0) >= anchor:
                continue  # lockout_release_failed already told the operator (H3b)
            changed = getattr(st, "last_changed", None)
            if isinstance(changed, datetime) and changed > anchor_wall:
                continue  # re-locked after the arrival by someone else (R2-7)
            if self._still_locked_paged.get(ent) == seq:
                continue  # one page per stuck lock per engage episode (R2-7)
            self._still_locked_paged[ent] = seq
            self.still_locked_pages += 1
            self._record(
                "still_locked_page", trigger=f"person:{pid}", written=[],
                extra={"entity": ent, "kind": kind},
            )
            try:
                self._spawn(self._notify_still_locked(ent, pid, kind))
            except Exception:  # noqa: BLE001
                _LOGGER.warning("Lock regime: still-locked NM not sent", exc_info=True)

    async def _notify_still_locked(self, ent: str, pid: str, kind: str) -> None:
        from ..const import DOMAIN  # noqa: PLC0415
        from .base import Severity  # noqa: PLC0415

        nm = self._hass.data.get(DOMAIN, {}).get("notification_manager")
        if nm is None:
            return
        name = self._friendly(pid)
        lock_name = self._friendly(ent)
        if kind == "uncounted":
            title = f"{name} may be locked out of the garage"
            message = (
                f"{name}'s phone was offline when they left, so their return "
                f"did not count as an arrival and {lock_name} is still locked. "
                "Unlock it from the HA app or the opener's own app."
            )
            hazard = "lockout_locked_resident_uncounted_return"
        else:
            title = f"Garage still locked after {name} got home"
            message = (
                f"{lock_name} still reads locked after {name} arrived home. "
                "Unlock it from the HA app or the opener's own app."
            )
            hazard = "lockout_locked_after_arrival"
        try:
            await nm.async_notify(
                coordinator_id="security",
                severity=Severity.HIGH,
                title=title,
                message=message,
                hazard_type=hazard,
                location=f"garage_lockout:still_locked:{ent}",
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Lock regime: NM notify failed", exc_info=True)

    # ------------------------------------------------------------------
    # Suspicious-arrival hold (plan rev 2 §5.2-§5.4)
    # ------------------------------------------------------------------

    def _hold_s(self, cfg: dict[str, Any]) -> float:
        from ..const import (  # noqa: PLC0415
            CONF_GARAGE_LOCKOUT_ARRIVAL_HOLD_S,
            GARAGE_LOCKOUT_ARRIVAL_HOLD_S,
        )

        return max(
            0.0,
            self._num(cfg, CONF_GARAGE_LOCKOUT_ARRIVAL_HOLD_S, GARAGE_LOCKOUT_ARRIVAL_HOLD_S),
        )

    def _stale(self, pid: str, person_state: Any = None) -> bool:
        from ..const import LOCK_ARRIVAL_STALE_SOURCE_S  # noqa: PLC0415

        try:
            return stale_source_arrival(
                self._hass.states.get, pid, float(LOCK_ARRIVAL_STALE_SOURCE_S),
                person_state=person_state,
            )
        except Exception:  # noqa: BLE001 — never block a release on a read error
            _LOGGER.debug("Lock regime: stale-source read failed for %s", pid, exc_info=True)
            return False

    def _should_hold(
        self,
        pid: str,
        old_val: str | None,
        new_val: str | None,
        new_state: Any,
        cfg: dict[str, Any],
    ) -> bool:
        """Hold this person edge? H > 0, outside the boot arrival window
        (F4: boot/HA-start edges are never held), a real non-not_home edge,
        and the source tracker did not change at the edge (F2: reads the
        event's own new_state)."""
        if self._hold_s(cfg) <= 0:
            return False
        if self._in_boot_arrival_window():
            return False
        if new_val is None or new_val in _UNREAL_STATES or new_val == "not_home":
            return False
        if old_val == new_val:
            return False
        return self._stale(pid, new_state)

    def _start_hold(
        self,
        pid: str,
        old_val: str | None,
        new_val: str | None,
        edge_ts: float,
        cfg: dict[str, Any],
        *,
        synthetic: bool = False,
    ) -> dict[str, Any]:
        hold = self._hold_s(cfg)
        due = edge_ts + hold
        held: dict[str, Any] = {
            "old_val": old_val,
            "new_val": new_val,
            "edge_ts": edge_ts,
            "due_ts": due,
            "proximity_sids": set(),
            "synthetic": synthetic,
        }
        held["unsub"] = self._call_later(
            self._hass,
            max(0.0, due - self._ts()),
            functools.partial(self._on_hold_confirm, pid),
        )
        self._held_edges[pid] = held
        self.arrival_holds += 1
        self._record(
            "arrival_hold", trigger=f"person:{pid}", written=[],
            extra={"held": new_val, "edge_ts": edge_ts, "hold_s": hold},
        )
        return held

    def _drop_hold(self, pid: str) -> dict[str, Any] | None:
        held = self._held_edges.pop(pid, None)
        if held is not None:
            _safe_unsub(held.get("unsub"))
        return held

    @callback
    def _on_hold_confirm(self, pid: str, _now: Any = None) -> None:
        """At edge_ts + H: if the person still reads the held state, replay
        the ORIGINAL edge (stamps carry edge_ts, INV-H5) with the config
        re-read now (F7); else drop it."""
        held = self._held_edges.get(pid)
        if held is None:
            return
        # Clear the slot before replaying (re-entrancy).
        self._held_edges.pop(pid, None)
        if self._torn_down:
            return
        if _state_value(self._hass.states.get(pid)) != held["new_val"]:
            return
        cfg = self._cfg()
        self.arrival_hold_confirms += 1
        self._record(
            "arrival_hold_confirmed", trigger=f"person:{pid}", written=[],
            extra={"held": held["new_val"], "edge_ts": held["edge_ts"]},
        )
        self._process_person_edge(
            pid, held["old_val"], held["new_val"], held["edge_ts"], cfg
        )
        if held["proximity_sids"] and self._is_resident(pid, cfg):
            radius = self._radius_m(cfg)
            for sid in sorted(held["proximity_sids"]):
                dist = self._last_distance_m.get(sid)
                if radius > 0 and dist is not None and dist <= radius:
                    self._release(f"proximity:{sid}", person=pid)

    def _arrival_counts(self, pid: str, old_val: str | None, now_ts: float) -> bool:
        if old_val not in _UNREAL_STATES:
            return True  # not_home / named zone -> home
        return self._really_away(pid, now_ts)

    def _really_away(self, pid: str, now_ts: float) -> bool:
        """Was ``pid`` genuinely away (H3a) — with the M-2 boot exceptions."""
        from ..const import GARAGE_LOCKOUT_BLIP_MIN_AWAY_MIN  # noqa: PLC0415

        if self._in_boot_arrival_window():
            return True  # M-2 (i)
        prev = self._last_real.get(pid)
        if prev is None or prev[2]:
            return True  # M-2 (ii): no real transition seen since setup
        state, since, _restored = prev
        if state == "home":
            return False  # H3a: blip while home
        return (now_ts - since) >= GARAGE_LOCKOUT_BLIP_MIN_AWAY_MIN * 60

    def _area_of_entity(self, entity_id: str) -> str:
        return area_slug_of_entity(self._hass, entity_id)

    def _entry_areas(self) -> set[str]:
        """Areas a person arrives through: egress camera areas + configured
        door-interior neighbours (read live from the EgressDirectionTracker,
        which owns ``_egress_entities`` / ``_interior_neighbours_by_group``;
        the TransitValidator has neither -- LOCK-ENTRY-AREAS-WRONG-OBJECT-1)."""
        from ..const import DOMAIN  # noqa: PLC0415

        tracker = self._hass.data.get(DOMAIN, {}).get("egress_tracker")
        return door_entry_areas(tracker, self._area_of_entity)

    def face_input_corroborated(self, person: str, at_ts: float | None = None) -> bool:
        """FACE-ARRIVAL-REBUILD-1 D3 (plan rev 11 §3.4): the PUBLIC
        corroboration primitive every access-class consumer of a
        camera-derived input calls (today: the security expected-arrival gate).
        A wrapper over ``_face_arrival_corroborated`` (same stamps, same boot
        floor, same window); a torn-down regime is never corroborated (fail
        closed)."""
        if self._torn_down:
            return False
        return self._face_arrival_corroborated(person, at_ts)

    def _face_arrival_corroborated(self, person: str, at_ts: float | None = None) -> bool:
        """LOCK-REGIME-FACE-ARRIVAL-CORROBORATION-1: an independent arrival
        edge for ``person`` within the D10.5 window (either side of the face
        at ``at_ts``, default now), outside the post-boot exclusion. REUSED
        rung-1 constants PERIMETER_EGRESS_FACE_NONFACE_WINDOW_S /
        _ARRIVAL_BOOT_EXCLUDE_S; review A MED-2: the lock floors the boot
        exclusion at GARAGE_LOCKOUT_BOOT_ARRIVAL_WINDOW_S, so a perimeter
        retune can never shrink an unlock's boot guard. Window 0 = a face
        never releases (fail-safe: no unlock)."""
        from ..const import (  # noqa: PLC0415
            DOMAIN,
            GARAGE_LOCKOUT_BOOT_ARRIVAL_WINDOW_S,
            PERIMETER_EGRESS_ARRIVAL_BOOT_EXCLUDE_S,
            PERIMETER_EGRESS_FACE_NONFACE_WINDOW_S,
        )

        slug = person.split(".", 1)[-1].lower()
        if self._setup_ts is None:
            return False  # not set up: everything is inside the boot exclusion
        boot_end = self._setup_ts + max(
            float(PERIMETER_EGRESS_ARRIVAL_BOOT_EXCLUDE_S),
            float(GARAGE_LOCKOUT_BOOT_ARRIVAL_WINDOW_S),
        )
        src = nonface_arrival_source(
            slug=slug,
            at_ts=self._ts() if at_ts is None else at_ts,
            window_s=float(PERIMETER_EGRESS_FACE_NONFACE_WINDOW_S),
            boot_end=boot_end,
            tracker_arrivals=self._arrival_edges,
            pc_data_fn=lambda: getattr(
                self._hass.data.get(DOMAIN, {}).get("person_coordinator"), "data", None),
            areas_fn=self._entry_areas,
            bermuda_moves=self._bermuda_moves,
        )
        return src is not None

    def _ensure_pc_listener(self) -> None:
        """Subscribe to the CURRENT PersonCoordinator (it is created after
        the lock regime and replaced on reload). Idempotent; cheap."""
        from ..const import DOMAIN  # noqa: PLC0415

        if self._torn_down:
            return
        pc = self._hass.data.get(DOMAIN, {}).get("person_coordinator")
        if pc is self._pc_listened:
            return
        _safe_unsub(self._pc_listener_unsub)
        self._pc_listener_unsub = None
        self._pc_listened = None
        add = getattr(pc, "async_add_listener", None)
        if pc is None or add is None:
            return
        try:
            self._pc_listener_unsub = add(self._on_pc_update)
            self._pc_listened = pc
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Lock regime: person coordinator listener failed", exc_info=True)

    @callback
    def _on_pc_update(self) -> None:
        """Stamp Bermuda moves (review A MED-1) and re-check, ONCE, any face
        held within the window whose person just got a new stamp."""
        from ..const import DOMAIN, PERIMETER_EGRESS_FACE_NONFACE_WINDOW_S  # noqa: PLC0415

        if self._torn_down:
            return
        try:
            pc = self._hass.data.get(DOMAIN, {}).get("person_coordinator")
            fresh = record_bermuda_moves(getattr(pc, "data", None) or {}, self._bermuda_moves)
        except Exception:  # noqa: BLE001
            return
        now = self._ts()
        win = float(PERIMETER_EGRESS_FACE_NONFACE_WINDOW_S)
        for person, face_ts in list(self._pending_faces.items()):
            if now - face_ts > win:
                self._pending_faces.pop(person, None)
                continue
            if person.split(".", 1)[-1].lower() not in fresh:
                continue
            self._pending_faces.pop(person, None)
            # Review B LOW-B1: runs inside the person coordinator's listener
            # loop, which does not isolate listener exceptions.
            try:
                if self._face_arrival_corroborated(person, at_ts=face_ts):
                    _LOGGER.info(
                        "Lock regime: held camera_face arrival for %s "
                        "corroborated by a later Bermuda entry move", person,
                    )
                    self._apply_arrival(person)
            except Exception:  # noqa: BLE001
                _LOGGER.exception(
                    "Lock regime: held face re-check failed for %s", person,
                )

    def _is_approach_zone(self, person_state: str, cfg: dict[str, Any]) -> bool:
        from ..const import CONF_SECURITY_LOCKOUT_APPROACH_ZONE  # noqa: PLC0415

        zone_id = str(cfg.get(CONF_SECURITY_LOCKOUT_APPROACH_ZONE) or "")
        if not zone_id.startswith("zone."):
            return False
        names = {zone_id.split(".", 1)[1].lower()}
        zst = self._hass.states.get(zone_id)
        friendly = None
        if zst is not None:
            friendly = (getattr(zst, "attributes", {}) or {}).get("friendly_name")
        if friendly:
            names.add(str(friendly).lower())
        return person_state.lower() in names

    def _person_for_sensor(self, sensor_id: str) -> str | None:
        """Proximity sensors are named <proximity>_<person>_distance.

        Review A L1: map against ALL live person ids (not the setup resident
        snapshot); the caller applies the resident / exclusion filter.
        """
        candidates: set[str] = set(self._person_unsubs) | set(self._residents)
        try:
            candidates |= {s.entity_id for s in self._hass.states.async_all("person")}
        except Exception:  # noqa: BLE001
            pass
        for pid in sorted(candidates):
            obj = pid.split(".", 1)[1]
            if sensor_id.endswith(f"_{obj}_distance"):
                return pid
        return None

    def _radius_m(self, cfg: dict[str, Any]) -> float:
        from ..const import (  # noqa: PLC0415
            CONF_GARAGE_LOCKOUT_APPROACH_RADIUS_M,
            GARAGE_LOCKOUT_APPROACH_RADIUS_M,
        )

        return self._num(
            cfg, CONF_GARAGE_LOCKOUT_APPROACH_RADIUS_M, GARAGE_LOCKOUT_APPROACH_RADIUS_M
        )

    @callback
    def _on_distance_event(self, event: Any) -> None:
        if self._torn_down:
            return
        sid = event.data.get("entity_id", "")
        new = event.data.get("new_state")
        cur = None
        if new is not None:
            unit = (getattr(new, "attributes", {}) or {}).get("unit_of_measurement")
            cur = self._to_metres(_state_value(new), unit)
        prev = self._last_distance_m.get(sid)
        self._last_distance_m[sid] = cur
        cfg = self._cfg()
        radius = self._radius_m(cfg)
        if radius <= 0 or prev is None or cur is None:
            return
        if prev > radius and cur <= radius:
            person = self._person_for_sensor(sid)
            if person is not None and not self._is_resident(person, cfg):
                return
            # Suspicious-arrival hold D4 (S9): a crossing while the person
            # reads home on a stale source (the iPad blip jumps the distance
            # to 0) attaches to that person's held edge and is re-read at
            # confirm. A crossing with the person not_home (a real approach)
            # is never stale and releases now. An unresolved sensor bypasses
            # (R6, develop behaviour).
            if (
                person is not None
                and self._hold_s(cfg) > 0
                and not self._in_boot_arrival_window()
            ):
                held = self._held_edges.get(person)
                if held is None and self._stale(person):
                    held = self._start_synthetic_hold(person, cfg)
                if held is not None:
                    held["proximity_sids"].add(sid)
                    return
            self._release(f"proximity:{sid}", person=person)

    def _start_synthetic_hold(self, person: str, cfg: dict[str, Any]) -> dict[str, Any]:
        """D4 with no held person edge yet: hold keyed to the person's own
        ``last_changed``, pre-edge value from ``_last_real`` (F6: when that
        already reads the held state the confirm replay is a garage no-op)."""
        st = self._hass.states.get(person)
        lc = getattr(st, "last_changed", None)
        edge_ts = lc.timestamp() if isinstance(lc, datetime) else self._ts()
        prev = self._last_real.get(person)
        return self._start_hold(
            person, prev[0] if prev else None, _state_value(st), edge_ts, cfg,
            synthetic=True,
        )

    # ------------------------------------------------------------------
    # Release
    # ------------------------------------------------------------------

    def _release(
        self,
        trigger: str,
        *,
        person: str | None = None,
        force: bool = False,
        override: bool = False,
    ) -> None:
        """Bump the generation, then unlock every locked / lock-pending lockout.

        ``override`` (from ``on_house_state_changed`` only): the edge was an
        operator ``override_set``; the D3 trip-wire exempts it.
        """
        # D3: captured before _after_release can end the episode.
        saw_before = self._episode_saw_arriving
        reason_before = self.reason
        self.release_gen += 1
        if person is not None:
            self.releasing_set[person] = {"at": self._ts(), "removed": False}
        cfg = self._cfg()
        if not force and not self.kill_switch_on():
            return
        if not force and not self._sc_alive():
            return
        written: list[str] = []
        for ent in self.lockout_entities(cfg):
            state = self._hass.states.get(ent)
            val = _state_value(state)
            if val is None or val in _UNREAL_STATES:
                if ent not in self._unavailable_warned:
                    self._unavailable_warned.add(ent)
                    _LOGGER.warning(
                        "Lock regime: lockout %s is %s; release skipped", ent, val
                    )
                continue
            self._unavailable_warned.discard(ent)
            pending_lock = self._lock_in_flight(ent, val)
            if val != "locked" and not pending_lock:
                continue
            if ent in self._release_inflight:
                continue  # H3b: one release in flight per entity
            # Review B-M2: mark in flight only once the unlock task exists, so
            # a failing spawn can never leave the entity stuck in the latch.
            if not self._spawn_unlock(ent, trigger, GARAGE_RETRIES()):
                continue
            self._engage_inflight.pop(ent, None)
            written.append(ent)
        self._after_release(trigger, person, cfg)
        self._record("release", trigger=trigger, written=written)
        self._check_uncorroborated(trigger, written, saw_before, reason_before, override)

    def _check_uncorroborated(
        self,
        trigger: str,
        written: list[str],
        saw_before: bool,
        reason_before: str,
        override: bool,
    ) -> None:
        """LOCK-RELEASE-ON-ARRIVING D3: page when a house-state / boot-recheck
        release WROTE an unlock in an episode that had seen ARRIVING.

        Observes, never blocks (the D1 gate is the protection). Exempt:
        nothing written (F7), WAKING (only reachable after SLEEP), an operator
        ``override_set`` edge.
        """
        from ..const import LOCK_RELEASE_UNCORROBORATED_TRIPWIRE_ENABLED  # noqa: PLC0415

        violation = (
            bool(written)
            and (trigger.startswith("house_state:") or trigger == "boot_recheck")
            and saw_before
            and trigger != "house_state:waking"
            and not override
        )
        if not violation or not LOCK_RELEASE_UNCORROBORATED_TRIPWIRE_ENABLED:
            return
        self.uncorroborated_releases += 1
        edges = [list(e) for e in self._last_house_edges]
        self._record(
            "uncorroborated_release", trigger=trigger, written=list(written),
            extra={"reason_before": reason_before, "last_house_edges": edges},
        )
        try:
            self._spawn(self._notify_uncorroborated(trigger, reason_before, edges))
        except Exception:  # noqa: BLE001
            _LOGGER.warning("Lock regime: uncorroborated-release NM not sent", exc_info=True)

    async def _notify_uncorroborated(
        self, trigger: str, reason_before: str, edges: list[list[Any]]
    ) -> None:
        from ..const import DOMAIN  # noqa: PLC0415
        from .base import Severity  # noqa: PLC0415

        nm = self._hass.data.get(DOMAIN, {}).get("notification_manager")
        if nm is None:
            return
        shown = ", ".join(f"{e[1] or '?'} -> {e[0]} ({e[2] or '?'})" for e in edges)
        try:
            await nm.async_notify(
                coordinator_id="security",
                severity=Severity.HIGH,
                title="Garage lockout released without a resident arrival",
                message=(
                    f"The garage lockout was released by {trigger} (episode "
                    f"{reason_before}) after the house showed ARRIVING with no "
                    f"resident arrival. Last house-state edges: {shown}."
                ),
                hazard_type="lock_release_uncorroborated",
                location="garage_lockout:house_state",
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Lock regime: NM notify failed", exc_info=True)

    @callback
    def _on_lockout_event(self, event: Any) -> None:
        ent = event.data.get("entity_id", "")
        new_val = _state_value(event.data.get("new_state"))
        if new_val == "locked":
            self._engage_inflight.pop(ent, None)
            return
        if (
            new_val == "unlocked"
            and _state_value(event.data.get("old_state")) == "locked"
            and ent not in self._release_inflight
            and not self._disable_releasing
        ):
            self._note_manual_unlock(ent)

    def _episode_reason(self) -> str | None:
        """Engage reason of the current lock episode, or None."""
        if self.reason in (REASON_SLEEP, REASON_VACATION, REASON_GUEST_NIGHT):
            return self.reason
        if self.reason == REASON_BOOT_UNKNOWN:
            house = self._house_state()
            if house == "sleep":
                return REASON_SLEEP
            if house == "vacation":
                return REASON_VACATION
            if house in ("guest", "home_night"):
                return REASON_GUEST_NIGHT
        return None

    def _note_manual_unlock(self, ent: str) -> None:
        """A human unlocked a lockout (not our release): remember it for the
        episode so a restart's boot recheck does not re-lock it (INV-5)."""
        episode = self._episode_reason()
        if episode is None:
            return
        self._record("manual_unlock", trigger="manual_unlock", written=[],
                     extra={"entity": ent, "episode": episode})
        if self.manual_unlock_reason != episode:
            self.manual_unlock_reason = episode
            self._save_store()

    def _remember_episode_released(self, episode: str | None) -> None:
        """Hazard / kill-switch-off / vacation-arrival ended the lock for
        this episode: persist it like a manual unlock so the boot recheck
        does not re-lock in the same episode (review B-1/B-3/B-5)."""
        if episode is None:
            return
        if self.manual_unlock_reason != episode:
            self.manual_unlock_reason = episode
            self._save_store()

    def _clear_manual_unlock(self) -> None:
        if self.manual_unlock_reason is not None:
            self.manual_unlock_reason = None
            self._save_store()

    def _lock_in_flight(self, ent: str, val: str | None) -> bool:
        """True while a lock.lock we issued may still land (review A L2).

        Cleared once the lockout is seen ``locked`` (the command landed) or
        after the read-back window (the command was lost / refused).
        """
        from ..const import GARAGE_LOCKOUT_READBACK_S  # noqa: PLC0415

        issued = self._engage_inflight.get(ent)
        if issued is None:
            return False
        if val == "locked" or self._ts() - issued > GARAGE_LOCKOUT_READBACK_S:
            self._engage_inflight.pop(ent, None)
            return False
        return True

    def _after_release(self, trigger: str, person: str | None, cfg: dict[str, Any]) -> None:
        is_arrival = person is not None or trigger.startswith("proximity:")
        if trigger.startswith("house_state:") or trigger in (
            "backstop",
            "boot_recheck",
        ):
            self._cancel_reengage()
            self._cancel_backstop()
            self.reason = REASON_NONE
            self._end_episode_arrival_flags()
            self.releasing_set.clear()
            # Episode over (edge / morning backstop / boot recheck release).
            self._clear_manual_unlock()
            return
        if is_arrival:
            if self.reason == REASON_VACATION:
                self.reason = REASON_NONE
                self._end_episode_arrival_flags()
                self._cancel_reengage()
                # Review B-3: the house can still read VACATION (min dwell);
                # a restart must not re-lock with the resident home.
                self._remember_episode_released(REASON_VACATION)
            elif self.reason in (REASON_SLEEP, REASON_GUEST_NIGHT) and (
                self._in_sleep_window(cfg)
            ):
                self._schedule_reengage(cfg)

    async def _async_unlock(
        self, ent: str, trigger: str, retries_left: int, policy: str = "garage_lockout"
    ) -> None:
        try:
            await self._hass.services.async_call(
                "lock", "unlock", {"entity_id": ent}, blocking=True, **_ctx_kwargs()
            )
        except Exception:  # noqa: BLE001
            _LOGGER.warning("Lock regime: unlock of %s failed", ent, exc_info=True)
        if self._torn_down:
            self._release_inflight.discard(ent)
            return
        from ..const import GARAGE_LOCKOUT_READBACK_S  # noqa: PLC0415

        old = self._readback_unsubs.pop(ent, None)
        _safe_unsub(old)
        # Review B-C1: a @callback bound through partial (HA unwraps partials
        # when typing the job), never a lambda (which HA runs in the executor).
        self._readback_unsubs[ent] = self._call_later(
            self._hass,
            float(GARAGE_LOCKOUT_READBACK_S),
            functools.partial(
                self._on_readback, ent, trigger, retries_left, policy=policy
            ),
        )

    def _spawn_unlock(
        self, ent: str, trigger: str, retries_left: int, policy: str = "garage_lockout"
    ) -> bool:
        """Start an unlock task and mark ``ent`` in flight; False if it failed.

        ``policy`` ("garage_lockout" / "away_lock") only changes the
        failure-NM wording (D3c).
        """
        coro = self._async_unlock(ent, trigger, retries_left, policy)
        try:
            task = self._hass.async_create_task(coro)
        except Exception:  # noqa: BLE001
            coro.close()
            self._release_inflight.discard(ent)
            _LOGGER.warning("Lock regime: could not start unlock of %s", ent, exc_info=True)
            return False
        self._release_inflight.add(ent)
        if isinstance(task, asyncio.Task):
            self._tasks.add(task)
            self._unlock_tasks.add(task)
            task.add_done_callback(self._tasks.discard)
            task.add_done_callback(self._unlock_tasks.discard)
        return True

    @callback
    def _on_readback(
        self,
        ent: str,
        trigger: str,
        retries_left: int,
        _now: Any = None,
        policy: str = "garage_lockout",
    ) -> None:
        self._readback_unsubs.pop(ent, None)
        if self._torn_down:
            self._release_inflight.discard(ent)
            return
        if _state_value(self._hass.states.get(ent)) != "locked":
            self._release_inflight.discard(ent)
            return
        self._release_inflight.discard(ent)
        if retries_left > 0:
            self._spawn_unlock(ent, trigger, retries_left - 1, policy)
            return
        try:
            self._spawn(self._notify_failure(ent, trigger, policy=policy))
        except Exception:  # noqa: BLE001
            _LOGGER.warning("Lock regime: failure NM for %s not sent", ent, exc_info=True)

    async def _notify_failure(
        self,
        ent: str,
        trigger: str,
        *,
        timeout: bool = False,
        policy: str = "garage_lockout",
    ) -> None:
        from ..const import DOMAIN  # noqa: PLC0415
        from .base import Severity  # noqa: PLC0415

        if policy != POLICY_AWAY_LOCK:
            # D4 (H3b): a still-locked page defers to this failure NM.
            self._failure_nm_at[ent] = self._ts()
        nm = self._hass.data.get(DOMAIN, {}).get("notification_manager")
        if nm is None:
            return
        if policy == POLICY_AWAY_LOCK:
            name = self._friendly(ent)
            coro = nm.async_notify(
                coordinator_id="security",
                severity=Severity.HIGH,
                title="Away Lock release failed",
                message=(
                    f"{name} is still locked after a release ({trigger}). "
                    "Unlock it from the HA app or by hand."
                ),
                hazard_type="away_lock_release_failed",
                location=f"away_lock:{ent}",
            )
        else:
            coro = self._garage_failure_coro(nm, ent, trigger, Severity)
        try:
            if timeout:
                from ..const import GARAGE_LOCKOUT_TEARDOWN_RELEASE_TIMEOUT_S  # noqa: PLC0415

                await asyncio.wait_for(coro, timeout=GARAGE_LOCKOUT_TEARDOWN_RELEASE_TIMEOUT_S)
            else:
                await coro
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Lock regime: NM notify failed", exc_info=True)

    def _friendly(self, ent: str) -> str:
        st = self._hass.states.get(ent)
        name = (getattr(st, "attributes", {}) or {}).get("friendly_name") if st else None
        return str(name) if name else ent

    @staticmethod
    def _garage_failure_coro(nm: Any, ent: str, trigger: str, Severity: Any) -> Any:  # noqa: N803
        return nm.async_notify(
            coordinator_id="security",
            severity=Severity.HIGH,
            title="Garage lockout release failed",
            message=(
                f"{ent} is still locked after a release ({trigger}). The car "
                "remotes and keypad may not open this garage. Unlock it from "
                "the HA app or the opener's own app."
            ),
            hazard_type="lockout_release_failed",
            location=f"garage:{ent}",  # review B-L1: per-lock NM dedup key
        )

    # ------------------------------------------------------------------
    # Engage (write-time predicate, rev 5 H-1)
    # ------------------------------------------------------------------

    def _request_engage(self, reason: str, trigger: str, *, reengage: bool = False) -> None:
        intent = {
            "reason": reason,
            "trigger": trigger,
            "gen": self.release_gen,
            "reengage": reengage,
        }
        self._spawn(self._async_engage(intent))

    def engage_predicate(self, intent: dict[str, Any], ent: str) -> str | None:
        """Synchronous. Return None if lock.lock may be issued now, else why not."""
        cfg = self._cfg()
        if not self.kill_switch_on():
            return "kill_switch_off"
        if not self._sc_alive():
            return "sc_not_running"
        if ent in self.sweep_exclude(cfg):
            # D2c / INV-X1: an excluded lock is never locked by the garage
            # policy, even from an options state written before the
            # validators existed.
            return "excluded"
        if intent["gen"] != self.release_gen:
            return "release_since_intent"
        if ent in self._release_inflight:
            return "release_inflight"
        house = self._house_state()
        reason = intent["reason"]
        if reason == REASON_SLEEP and house != "sleep":
            return "house_left_sleep"
        if reason == REASON_VACATION and house != "vacation":
            return "house_left_vacation"
        if reason == REASON_GUEST_NIGHT and not (
            house == "guest" and self._guest_toggle_on(cfg) and self._in_sleep_window(cfg)
        ):
            return "guest_night_ended"
        if intent.get("reengage"):
            why = self._reengage_row_fails(cfg)
            if why is not None:
                return why
        val = _state_value(self._hass.states.get(ent))
        if val != "unlocked":
            return f"lockout_{val}"
        return None

    async def _async_engage(self, intent: dict[str, Any]) -> None:
        for ent in self.lockout_entities():
            why = self.engage_predicate(intent, ent)
            if why is None and getattr(self._sc, "observation_mode", False):
                self._record("would_engage", trigger=intent["trigger"], written=[ent])
                continue
            if why is not None:
                self._record(
                    "engage_dropped_stale", trigger=intent["trigger"],
                    written=[], extra={"entity": ent, "why": why},
                )
                continue
            # No await between the predicate above and this call (INV-2).
            self._engage_inflight[ent] = self._ts()
            self.engage_seq += 1  # D4: silences an older still-locked check
            try:
                await self._hass.services.async_call(
                    "lock", "lock", {"entity_id": ent}, blocking=False, **_ctx_kwargs()
                )
            except Exception:  # noqa: BLE001
                self._engage_inflight.pop(ent, None)
                _LOGGER.warning("Lock regime: lock of %s failed", ent, exc_info=True)
                continue
            self._record("engage", trigger=intent["trigger"], written=[ent])
        if intent.get("reengage"):
            self.releasing_set.clear()

    # ------------------------------------------------------------------
    # Re-engage (INV-3)
    # ------------------------------------------------------------------

    def _settled(self, pid: str, info: dict[str, Any], cfg: dict[str, Any]) -> bool:
        if info.get("removed"):
            return False
        if _state_value(self._hass.states.get(pid)) == "home":
            return True
        radius = self._radius_m(cfg)
        for sid in self._distance_sensors(cfg):
            if self._person_for_sensor(sid) != pid:
                continue
            st = self._hass.states.get(sid)
            if st is None:
                continue
            unit = (getattr(st, "attributes", {}) or {}).get("unit_of_measurement")
            metres = self._to_metres(_state_value(st), unit)
            if metres is not None and radius > 0 and metres > radius:
                return True
        return False

    def _reengage_row_fails(self, cfg: dict[str, Any]) -> str | None:
        from ..const import GARAGE_LOCKOUT_REENGAGE_MAX_WAIT_S  # noqa: PLC0415

        if not self._in_sleep_window(cfg):
            return "past_sleep_end"
        house = self._house_state()
        if self.reason == REASON_GUEST_NIGHT:
            if house != "guest":
                return "house_not_guest"
        elif house != "sleep":
            return "house_not_sleep"
        for cover in list(getattr(self._sc, "_garage_entities", []) or []):
            if _state_value(self._hass.states.get(cover)) != "closed":
                return f"door_not_closed:{cover}"
        now_ts = self._ts()
        for pid, info in self.releasing_set.items():
            if self._settled(pid, info, cfg):
                continue
            if now_ts - float(info.get("at", now_ts)) >= GARAGE_LOCKOUT_REENGAGE_MAX_WAIT_S:
                return "max_wait"
            return f"not_settled:{pid}"
        return None

    def _reengage_delay(self, cfg: dict[str, Any]) -> float:
        from ..const import (  # noqa: PLC0415
            CONF_GARAGE_LOCKOUT_REENGAGE_DELAY_S,
            GARAGE_LOCKOUT_REENGAGE_DELAY_S,
        )

        return self._num(
            cfg, CONF_GARAGE_LOCKOUT_REENGAGE_DELAY_S, GARAGE_LOCKOUT_REENGAGE_DELAY_S
        )

    def _schedule_reengage(self, cfg: dict[str, Any]) -> None:
        self._cancel_reengage()
        delay = self._reengage_delay(cfg)
        if delay <= 0:
            return
        self._reengage_gen = self.release_gen
        self._reengage_unsub = self._call_later(self._hass, delay, self._on_reengage_timer)
        self.reengage_at = (self._now() + timedelta(seconds=delay)).isoformat()

    def _cancel_reengage(self) -> None:
        _safe_unsub(self._reengage_unsub)
        self._reengage_unsub = None
        self._reengage_gen = None
        self.reengage_at = None

    @callback
    def _on_reengage_timer(self, _now: Any = None) -> None:
        self._reengage_unsub = None
        self.reengage_at = None
        if self._torn_down or self._reengage_gen != self.release_gen:
            return
        cfg = self._cfg()
        why = self._reengage_row_fails(cfg)
        if why is None:
            self._reengage_gen = None
            self._request_engage(self.reason, "reengage", reengage=True)
            return
        if why.startswith("not_settled") or why.startswith("door_not_closed"):
            # L-3: retry; the whole row is re-checked at the next fire.
            delay = self._reengage_delay(cfg)
            self._reengage_unsub = self._call_later(self._hass, delay, self._on_reengage_timer)
            self.reengage_at = (self._now() + timedelta(seconds=delay)).isoformat()
            return
        self._reengage_gen = None
        self._record("reengage_abandoned", trigger="reengage", written=[], extra={"why": why})

    # ------------------------------------------------------------------
    # Backstop (INV-4)
    # ------------------------------------------------------------------

    def _schedule_backstop(self, cfg: dict[str, Any], *, allow_immediate: bool = False) -> None:
        self._cancel_backstop()
        self._backstop_unsub = self._call_later(
            self._hass,
            self._backstop_delay_s(cfg, allow_immediate=allow_immediate),
            self._on_backstop,
        )

    def _cancel_backstop(self) -> None:
        _safe_unsub(self._backstop_unsub)
        self._backstop_unsub = None

    @callback
    def _on_backstop(self, _now: Any = None) -> None:
        self._backstop_unsub = None
        if self._torn_down:
            return
        if self.reason in SLEEP_LIKE_REASONS:
            self._release("backstop")

    # ------------------------------------------------------------------
    # Away lock (SC-LOCK-REGIME-DOOR-LOCKS-1, plan rev 3 D3 + amendments)
    # ------------------------------------------------------------------
    # Lock every away-lock entity once ALL listed persons read exactly
    # `not_home` for SECURITY_AWAY_LOCK_ENGAGE_DWELL_S; release when any one
    # of them arrives. Ownership (INV-X3) = read-back saw `locked`, or an
    # engage is in flight. Never routed through _release / _after_release.

    def _away_setup(self, cfg: dict[str, Any]) -> None:
        """Setup: validate the config (D3i), reconcile persisted state."""
        lockouts = set(self.lockout_entities(cfg))
        exclude = self.sweep_exclude(cfg)
        overlap = sorted(exclude & lockouts)
        if overlap:
            _LOGGER.warning(
                "Lock regime: %s are both remote lockouts and never-auto-lock "
                "locks; unsupported, fix the Security options", overlap,
            )
        away_ents = self.away_lock_entities(cfg)
        not_excluded = lock_exclude_not_subset(exclude, away_ents)
        if not_excluded:
            _LOGGER.warning(
                "Lock regime: away-lock locks %s are not in Never auto-lock; "
                "the away lock skips them", not_excluded,
            )
        both = sorted(set(away_ents) & lockouts)
        if both:
            _LOGGER.warning(
                "Lock regime: away-lock locks %s are also remote lockouts; "
                "the away lock skips them", both,
            )
        # A persisted owned lock a human unlocked while HA was down is no
        # longer ours.
        for ent in sorted(self.away_lock_owned):
            if _state_value(self._hass.states.get(ent)) == "unlocked":
                self.away_lock_owned.discard(ent)
        # A5/B4: an engage whose read-back was lost to a restart: if the lock
        # does not read unlocked now (locked, or undecided), treat it as ours.
        for ent in sorted(self._away_inflight_restored):
            if _state_value(self._hass.states.get(ent)) != "unlocked":
                self.away_lock_owned.add(ent)
        self._away_inflight_restored = set()
        # Persisted since-stamps: kept only while the person still reads
        # not_home (or unknown/unavailable, undecided). A listed person
        # reading not_home with no stamp counts from setup.
        now_ts = self._ts()
        listed = set(self.away_lock_persons(cfg))
        for pid in sorted(set(self._away_not_home_since) | listed):
            val = _state_value(self._hass.states.get(pid))
            if val == "not_home":
                if pid in listed:
                    self._away_not_home_since.setdefault(pid, now_ts)
            elif val is not None and val not in _UNREAL_STATES:
                self._away_not_home_since.pop(pid, None)
        # B2: the persisted attempt still holds only for the same formation.
        marker = self._away_attempted_marker
        if marker is not None and marker == self._formation_key(cfg):
            self._away_attempted = True
        else:
            self._away_attempted = False
            self._away_attempted_marker = None

    def _formation_key(self, cfg: dict[str, Any]) -> float | None:
        """Identity of the current all-away outing: the latest since-stamp
        across listed persons (None unless every listed person has one)."""
        persons = self.away_lock_persons(cfg)
        if not persons:
            return None
        stamps = [self._away_not_home_since.get(p) for p in persons]
        if any(t is None for t in stamps):
            return None
        return max(stamps)

    def _set_attempted(self) -> None:
        self._away_attempted = True
        self._away_attempted_marker = self._formation_key(self._cfg())
        self._save_store()

    def _clear_attempted(self) -> None:
        changed = self._away_attempted or self._away_attempted_marker is not None
        self._away_attempted = False
        self._away_attempted_marker = None
        if changed:
            self._save_store()

    def _away_boot_discharge(self, cfg: dict[str, Any]) -> None:
        """A1/B3: a listed person reading home at the boot recheck (got home
        while HA was down) releases owned / in-flight away locks."""
        if not self._away_targets():
            return
        for pid in self.away_lock_persons(cfg):
            if _state_value(self._hass.states.get(pid)) == "home":
                self._away_release(f"boot_recheck:{pid}")
                return

    def _away_on_person(
        self,
        pid: str,
        old_val: str | None,
        new_val: str | None,
        now_ts: float,
        cfg: dict[str, Any],
    ) -> None:
        """Person edge for the away lock. ``old_val`` None = restore/added."""
        if pid not in self.away_lock_persons(cfg):
            return
        changed = False
        if new_val == "not_home":
            if old_val is not None and old_val not in _UNREAL_STATES and old_val != "not_home":
                # A real leave: a fresh outing.
                self._away_not_home_since[pid] = now_ts
                changed = True
            elif pid not in self._away_not_home_since:
                self._away_not_home_since[pid] = now_ts
                changed = True
        elif new_val is None or new_val in _UNREAL_STATES:
            # Undecided: cannot engage now, but keep the outing's stamp.
            self._cancel_away_dwell()
            return
        else:
            # home or a named zone: not away (operator 2026-11-07).
            if self._away_not_home_since.pop(pid, None) is not None:
                changed = True
            self._cancel_away_dwell()
            # A1: ANY home reading of a listed person releases what the away
            # lock holds (restored / no-prior-state and blip-gated returns
            # included). No blip gate on this side: releasing is fail-safe.
            if new_val == "home" and self._away_targets():
                self._away_release(f"person:{pid}")
            # After the release (which latches it): this person is not away,
            # so the next all-away formation may attempt again (M6).
            self._clear_attempted()
        if changed:
            self._save_store()
        if self._in_boot_window():
            # D3e: replayed boot edges (HA person restore included) never
            # arm; the boot recheck does.
            return
        self._away_rearm(cfg)

    def _away_due_ts(self, cfg: dict[str, Any]) -> float | None:
        """When every listed person will have been not_home for the dwell.

        None if the list is empty, or any listed person does not read
        exactly `not_home` now, or has no since-stamp.
        """
        from ..const import SECURITY_AWAY_LOCK_ENGAGE_DWELL_S  # noqa: PLC0415

        persons = self.away_lock_persons(cfg)
        if not persons:
            return None
        due = 0.0
        for pid in persons:
            if _state_value(self._hass.states.get(pid)) != "not_home":
                return None
            since = self._away_not_home_since.get(pid)
            if since is None:
                return None
            due = max(due, since + float(SECURITY_AWAY_LOCK_ENGAGE_DWELL_S))
        return due

    def away_lock_predicate(self, ent: str, cfg: dict[str, Any]) -> str | None:
        """INV-X2, synchronous. None = lock.lock may be issued on ``ent`` now."""
        if not self.away_lock_on(cfg):
            return "kill_switch_off"
        if not self._sc_alive():
            return "sc_not_running"
        if ent not in self.away_lock_entities(cfg):
            return "not_away_lock_entity"
        if ent not in self.sweep_exclude(cfg):
            return "not_excluded"
        if ent in self.lockout_entities(cfg):
            return "is_lockout"
        due = self._away_due_ts(cfg)
        if due is None:
            return "not_all_away"
        if self._ts() < due:
            return "dwell"
        if ent in self._release_inflight:
            return "release_inflight"
        val = _state_value(self._hass.states.get(ent))
        if val != "unlocked":
            return f"lock_{val}"
        return None

    def _away_rearm(self, cfg: dict[str, Any]) -> None:
        """(Re)arm the one-shot dwell timer (M6): only while every listed
        person reads not_home and this formation has not been attempted."""
        self._cancel_away_dwell()
        if self._torn_down or self._away_attempted:
            return
        if not self.away_lock_on(cfg) or not self.away_lock_entities(cfg):
            return
        due = self._away_due_ts(cfg)
        if due is None:
            return
        delay = max(0.0, due - self._ts())
        self._away_pending_at = due
        self._away_dwell_unsub = self._call_later(self._hass, delay, self._on_away_dwell)

    def _cancel_away_dwell(self) -> None:
        _safe_unsub(self._away_dwell_unsub)
        self._away_dwell_unsub = None
        self._away_pending_at = None

    def _away_pending_iso(self) -> str | None:
        if self._away_pending_at is None:
            return None
        try:
            return datetime.fromtimestamp(
                self._away_pending_at, tz=self._now().tzinfo
            ).isoformat()
        except Exception:  # noqa: BLE001
            return None

    @callback
    def _on_away_dwell(self, _now: Any = None) -> None:
        self._away_dwell_unsub = None
        self._away_pending_at = None
        if self._torn_down:
            return
        # F3: while a listed person's edge is held, defer to the latest such
        # hold's expiry (+0.1 s) BEFORE _async_away_engage, so the one
        # attempt per formation (_set_attempted) is never consumed inside a
        # hold. Cancel -> fires at expiry and engages as it would have;
        # confirm -> the replayed home branch cancels this timer.
        persons = set(self.away_lock_persons(self._cfg()))
        dues = [h["due_ts"] for p, h in self._held_edges.items() if p in persons]
        if dues:
            from ..const import LOCK_ARRIVAL_DWELL_DEFER_PAD_S  # noqa: PLC0415

            due = max(dues) + float(LOCK_ARRIVAL_DWELL_DEFER_PAD_S)
            self._away_pending_at = due
            self._away_dwell_unsub = self._call_later(
                self._hass, max(0.0, due - self._ts()), self._on_away_dwell
            )
            return
        self._spawn(self._async_away_engage("all_away"))

    async def _async_away_engage(self, trigger: str) -> None:
        if self._away_attempted:
            return
        self._set_attempted()
        self._away_advisory_sent = False
        epoch = self._away_release_epoch
        for ent in self.away_lock_entities(self._cfg()):
            # B1/A4: a release since the loop started ends it; cfg is re-read
            # per lock (the switch may have flipped during the last await).
            if self._away_release_epoch != epoch:
                return
            cfg = self._cfg()
            why = self.away_lock_predicate(ent, cfg)
            if why is None and getattr(self._sc, "observation_mode", False):
                self._record(
                    "would_engage", trigger=trigger, written=[ent],
                    policy=POLICY_AWAY_LOCK,
                )
                continue
            if why is not None:
                self._record(
                    "engage_dropped", trigger=trigger, written=[],
                    extra={"entity": ent, "why": why}, policy=POLICY_AWAY_LOCK,
                )
                continue
            # No await between the predicate above and this call (INV-X2).
            self._away_engage_inflight[ent] = self._ts()
            self._save_store()  # A5: persist the in-flight engage (sync)
            try:
                await self._hass.services.async_call(
                    "lock", "lock", {"entity_id": ent}, blocking=False, **_ctx_kwargs()
                )
            except Exception:  # noqa: BLE001
                self._away_engage_inflight.pop(ent, None)
                _LOGGER.warning("Lock regime: away lock of %s failed", ent, exc_info=True)
                continue
            if ent not in self._away_engage_inflight:
                continue  # released while the call was being issued
            from ..const import GARAGE_LOCKOUT_READBACK_S  # noqa: PLC0415

            _safe_unsub(self._away_readback_unsubs.pop(ent, None))
            self._away_readback_unsubs[ent] = self._call_later(
                self._hass,
                float(GARAGE_LOCKOUT_READBACK_S),
                functools.partial(self._on_away_readback, ent),
            )

    @callback
    def _on_away_readback(self, ent: str, _now: Any = None) -> None:
        """D3b engage read-back: `locked` -> owned; else one LOW advisory."""
        self._away_readback_unsubs.pop(ent, None)
        if self._torn_down:
            return
        if self._away_engage_inflight.pop(ent, None) is None:
            return  # released meanwhile (H2)
        if _state_value(self._hass.states.get(ent)) == "locked":
            self.away_lock_owned.add(ent)
            self._save_store()
            self._record("engage", trigger="all_away", written=[ent], policy=POLICY_AWAY_LOCK)
            return
        self._record(
            "engage_not_taken", trigger="all_away", written=[],
            extra={"entity": ent}, policy=POLICY_AWAY_LOCK,
        )
        if self._away_advisory_sent:
            return
        self._away_advisory_sent = True
        try:
            self._spawn(self._notify_away_not_taken(ent))
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Lock regime: away advisory not sent", exc_info=True)

    async def _notify_away_not_taken(self, ent: str) -> None:
        from ..const import DOMAIN  # noqa: PLC0415
        from .base import Severity  # noqa: PLC0415

        nm = self._hass.data.get(DOMAIN, {}).get("notification_manager")
        if nm is None:
            return
        try:
            await nm.async_notify(
                coordinator_id="security",
                severity=Severity.LOW,
                title="Away Lock",
                message=(
                    f"Away Lock: {self._friendly(ent)} did not lock "
                    "(passage mode may be on)."
                ),
                hazard_type="away_lock_not_taken",
                location=f"away_lock:{ent}",
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Lock regime: away advisory failed", exc_info=True)

    @callback
    def _on_away_lock_event(self, event: Any) -> None:
        """D3d: unlocked with no engage in flight -> no longer ours.

        Deviation from plan D3d (H2 safety): a `locked` reading does NOT
        forget the in-flight entry; the read-back does, so a release inside
        the read-back window still targets the entity.
        """
        if self._torn_down:
            return
        ent = event.data.get("entity_id", "")
        if _state_value(event.data.get("new_state")) != "unlocked":
            return
        if ent in self._away_engage_inflight or ent not in self.away_lock_owned:
            return
        self.away_lock_owned.discard(ent)
        self._save_store()
        self._record("ownership_lost", trigger="manual_unlock", written=[],
                     extra={"entity": ent}, policy=POLICY_AWAY_LOCK)

    def _away_targets(self) -> list[str]:
        return sorted(self.away_lock_owned | set(self._away_engage_inflight))

    def _away_release(self, trigger: str) -> None:
        """Unlock owned + in-flight away locks (INV-X3). Direct write, never
        gated by observation mode or either kill switch (fail-safe)."""
        # No re-engage in this formation after any release.
        self._away_release_epoch += 1
        self._cancel_away_dwell()
        self._set_attempted()
        targets = self._away_targets()
        if not targets:
            return
        written: list[str] = []
        for ent in targets:
            inflight = self._away_engage_inflight.pop(ent, None) is not None
            _safe_unsub(self._away_readback_unsubs.pop(ent, None))
            val = _state_value(self._hass.states.get(ent))
            if val is None or val in _UNREAL_STATES:
                _LOGGER.warning("Lock regime: away lock %s is %s; release skipped", ent, val)
                # Stays (B4: or becomes) owned; a later release retries.
                self.away_lock_owned.add(ent)
                continue
            self.away_lock_owned.discard(ent)
            if val == "unlocked" and not inflight:
                continue  # already unlocked
            # A2: locked / jammed / locking / unlocking -> unlock attempt
            # (read-back + one retry + HIGH NM if it still reads locked).
            if ent in self._release_inflight:
                continue
            if self._spawn_unlock(ent, trigger, GARAGE_RETRIES(), POLICY_AWAY_LOCK):
                written.append(ent)
        self._save_store()
        self._record("release", trigger=trigger, written=written, policy=POLICY_AWAY_LOCK)

    async def _away_release_on_disable(self) -> None:
        """SC disable (M4): unlock owned / in-flight away locks before teardown."""
        from ..const import GARAGE_LOCKOUT_TEARDOWN_RELEASE_TIMEOUT_S  # noqa: PLC0415

        self._away_release_epoch += 1
        self._cancel_away_dwell()
        targets = self._away_targets()
        if not targets:
            return
        for ent in targets:
            inflight = self._away_engage_inflight.pop(ent, None) is not None
            _safe_unsub(self._away_readback_unsubs.pop(ent, None))
            val = _state_value(self._hass.states.get(ent))
            if val is None or val in _UNREAL_STATES:
                # A3: same as _away_release; keep ownership.
                self.away_lock_owned.add(ent)
                _LOGGER.warning(
                    "Lock regime: away lock %s is %s at SC disable; release skipped",
                    ent, val,
                )
                continue
            self.away_lock_owned.discard(ent)
            if val == "unlocked" and not inflight:
                continue
            try:
                await asyncio.wait_for(
                    self._hass.services.async_call(
                        "lock", "unlock", {"entity_id": ent}, blocking=True,
                        **_ctx_kwargs(),
                    ),
                    timeout=GARAGE_LOCKOUT_TEARDOWN_RELEASE_TIMEOUT_S,
                )
                self._record("release", trigger="sc_disabled", written=[ent],
                             policy=POLICY_AWAY_LOCK)
            except Exception:  # noqa: BLE001 — includes TimeoutError
                _LOGGER.warning(
                    "Lock regime: away-lock release of %s on SC disable failed", ent,
                    exc_info=True,
                )
                await self._notify_failure(
                    ent, "sc_disabled", timeout=True, policy=POLICY_AWAY_LOCK
                )
        self._save_store()

    # ------------------------------------------------------------------
    # Bookkeeping
    # ------------------------------------------------------------------

    def _spawn(self, coro: Any) -> None:
        task = self._hass.async_create_task(coro)
        if isinstance(task, asyncio.Task):
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    def _store_payload(self) -> dict[str, Any]:
        """D3g: the WHOLE payload, always from current in-memory state."""
        return {
            "residents": sorted(self._residents),
            "away_lock_owned": sorted(self.away_lock_owned),
            "away_not_home_since": dict(sorted(self._away_not_home_since.items())),
            "away_lock_inflight": sorted(self._away_engage_inflight),
            "away_attempted_marker": self._away_attempted_marker,
            "garage_manual_unlock": self.manual_unlock_reason,
            # LOCK-RELEASE-ON-ARRIVING D1 / D3.
            "garage_arrival_taint": self._arrival_taint,
            "garage_episode_saw_arriving": self._episode_saw_arriving,
        }

    def _save_store(self) -> None:
        if self._store is None:
            return
        try:
            self._store.async_delay_save(lambda: self._store_payload(), 1.0)
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Lock regime: store save failed", exc_info=True)

    def _load_away_store(self, data: Any) -> None:
        if not isinstance(data, dict):
            return
        owned = data.get("away_lock_owned")
        if isinstance(owned, list):
            self.away_lock_owned = {o for o in owned if isinstance(o, str) and o}
        since = data.get("away_not_home_since")
        if isinstance(since, dict):
            parsed: dict[str, float] = {}
            for pid, ts in since.items():
                if not isinstance(pid, str) or not pid.startswith("person."):
                    continue
                try:
                    parsed[pid] = float(ts)
                except (TypeError, ValueError):
                    continue
            self._away_not_home_since = parsed
        inflight = data.get("away_lock_inflight")
        if isinstance(inflight, list):
            self._away_inflight_restored = {o for o in inflight if isinstance(o, str) and o}
        manual = data.get("garage_manual_unlock")
        # Missing / corrupt -> None: fail secure (the recheck may re-lock).
        self.manual_unlock_reason = (
            manual
            if manual in (REASON_SLEEP, REASON_VACATION, REASON_GUEST_NIGHT)
            else None
        )
        # Missing / non-bool -> False (plan D1 item 1).
        self._arrival_taint = data.get("garage_arrival_taint") is True
        self._episode_saw_arriving = data.get("garage_episode_saw_arriving") is True
        marker = data.get("away_attempted_marker")
        if isinstance(marker, (int, float)) and not isinstance(marker, bool):
            self._away_attempted_marker = float(marker)

    def _record(
        self,
        action: str,
        *,
        trigger: str,
        written: list[str],
        extra: dict[str, Any] | None = None,
        policy: str = POLICY_GARAGE_LOCKOUT,
    ) -> None:
        """Log AFTER any write was issued (never between check and call).

        ``policy=away_lock`` records into ``away_lock_last_action`` with
        "Away Lock" wording; the garage record shape is unchanged.
        """
        from ..const import DOMAIN  # noqa: PLC0415

        away = policy == POLICY_AWAY_LOCK
        if away:
            record = {
                "action": action,
                "trigger": trigger,
                "entities": list(written),
                "policy": POLICY_AWAY_LOCK,
                "at": self._now().isoformat(),
            }
        else:
            record = {
                "action": action,
                "trigger": trigger,
                "entities": list(written),
                "reason": self.reason,
                "release_gen": self.release_gen,
                "at": self._now().isoformat(),
            }
        if extra:
            record.update(extra)
        if away:
            self.away_lock_last_action = record
            decision_type = f"lock_regime_away_lock_{action}"
            description = (
                f"Away Lock {action}: "
                f"{', '.join(self._friendly(e) for e in written)} ({trigger})"
            )
        else:
            self.last_action = record
            decision_type = f"lock_regime_{action}"
            description = f"Garage lockout {action}: {', '.join(written)} ({trigger})"
        decision_logger = getattr(self._sc, "decision_logger", None)
        if decision_logger is not None:
            try:
                from .coordinator_diagnostics import DecisionLog  # noqa: PLC0415

                decision_logger.log_decision(
                    DecisionLog(
                        coordinator_id="security",
                        decision_type=decision_type,
                        context=trigger,
                        action=",".join(written) or action,
                    )
                )
            except Exception:  # noqa: BLE001
                _LOGGER.debug("Lock regime: decision log failed", exc_info=True)
        if written:
            activity_logger = self._hass.data.get(DOMAIN, {}).get("activity_logger")
            if activity_logger is not None:
                try:
                    self._spawn(
                        activity_logger.log(
                            coordinator="security",
                            action=decision_type,
                            description=description,
                            importance="notable",
                            details=dict(record),
                        )
                    )
                except Exception:  # noqa: BLE001
                    _LOGGER.debug("Lock regime: activity log failed", exc_info=True)

    def snapshot(self) -> dict[str, Any]:
        return {
            "lock_regime_garage_lockout_enabled": self.kill_switch_on(),
            "lock_regime_garage_lockout_reason": self.reason,
            "lock_regime_garage_lockout_last_action": dict(self.last_action),
            "lock_regime_garage_lockout_reengage_at": self.reengage_at,
            "lock_regime_garage_lockout_missing_residents": list(self.missing_residents),
            # D3f: away lock (added keys only).
            "lock_regime_away_lock_enabled": self.away_lock_on(),
            "lock_regime_away_lock_owned": sorted(self.away_lock_owned),
            "lock_regime_away_lock_last_action": dict(self.away_lock_last_action),
            "lock_regime_away_lock_pending_engage_at": self._away_pending_iso(),
            # Suspicious-arrival hold (added keys only). Counts since setup.
            "lock_regime_arrival_holds": self.arrival_holds,
            "lock_regime_arrival_signal_held": self.arrival_signal_held,
            "lock_regime_arrival_hold_confirms": self.arrival_hold_confirms,
            "lock_regime_held_edges": sorted(self._held_edges),
            # LOCK-RELEASE-ON-ARRIVING (added keys only).
            "lock_regime_arriving_taint": self._arrival_taint,
            "lock_regime_episode_saw_arriving": self._episode_saw_arriving,
            "lock_regime_arriving_holds": self.arriving_holds,
            "lock_regime_uncorroborated_releases": self.uncorroborated_releases,
            "lock_regime_still_locked_pages": self.still_locked_pages,
            "lock_regime_uncounted_returns": self.uncounted_returns,
        }


def GARAGE_RETRIES() -> int:  # noqa: N802 — reads the rung-1 constant lazily
    from ..const import GARAGE_LOCKOUT_READBACK_RETRIES  # noqa: PLC0415

    return int(GARAGE_LOCKOUT_READBACK_RETRIES)


def _ctx_kwargs() -> dict[str, Any]:
    try:
        from ..ura_context import ura_ctx_kwargs  # noqa: PLC0415

        return ura_ctx_kwargs("lock")
    except Exception:  # noqa: BLE001
        return {}


def _safe_unsub(unsub: Any) -> None:
    if unsub is None:
        return
    try:
        unsub()
    except Exception:  # noqa: BLE001
        _LOGGER.debug("Lock regime: unsub raised", exc_info=True)
