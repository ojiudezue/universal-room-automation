"""Lock regime — garage remote lockouts (GARAGE-REMOTE-LOCKOUT-SCHEDULE-1, Phase 1).

Plan: docs/planning/PLANNING_sc_garage_remote_lockout.md rev 5 (+ operator
answer Q-G1). Arming (alarm posture) and the lock regime (what is locked)
are separate concerns: this controller never reads or changes ArmedState
and never goes through ``SecurityCoordinator.evaluate()``.

Policy owned this cycle: the two opener "remote lockout" locks.
  * Engage on a SLEEP / VACATION house-state edge, and on GUEST inside the
    CM sleep window (toggle, Q-G1 option (a)). Edge-only: boot edges and
    the kill switch OFF -> ON never engage (INV-5).
  * Release on wake / HOME_* / ARRIVING / morning backstop / any resident
    arrival (P1 person -> home, P2 SIGNAL_PERSON_ARRIVING, P5 proximity
    crossing, optional approach zone) / critical hazard / kill switch OFF /
    SC disabled (teardown on the real disable path).

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
        self._residents: set[str] = set()
        self._unavailable_warned: set[str] = set()

        # SC-LOCK-REGIME-DOOR-LOCKS-1 (plan rev 3 D3a): the away-lock policy.
        # Its own state; it never touches reason / release_gen / backstop /
        # re-engage (garage policy).
        # Entities this policy locked (read-back saw `locked`). Persisted.
        self.away_lock_owned: set[str] = set()
        # entity -> ts a lock.lock was issued, until its read-back ran.
        self._away_engage_inflight: dict[str, float] = {}
        self._away_readback_unsubs: dict[str, Callable[[], None]] = {}
        self._away_dwell_unsub: Callable[[], None] | None = None
        self._away_pending_at: float | None = None
        # One engage attempt per all-away formation (M6). Cleared when any
        # listed person reads a real non-not_home state.
        self._away_attempted: bool = False
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
            return
        house = self._house_state()
        if house == "sleep":
            self.reason = REASON_SLEEP
        elif house == "vacation":
            self.reason = REASON_VACATION
        else:
            self.reason = REASON_BOOT_UNKNOWN
        self._record("boot_rebuild", trigger=f"boot:{house}", written=[])
        if self.reason in SLEEP_LIKE_REASONS:
            self._schedule_backstop(cfg, allow_immediate=True)

    @callback
    def _on_boot_recheck(self, _now: Any = None) -> None:
        self._boot_recheck_unsub = None
        if self._torn_down:
            return
        if self.reason == REASON_BOOT_UNKNOWN:
            house = self._house_state()
            if house == "sleep":
                self.reason = REASON_SLEEP
            elif house == "vacation":
                self.reason = REASON_VACATION
                self._cancel_backstop()
        # D3e (H1): arm the away-lock dwell for the remainder, from the
        # persisted not_home stamps. Replayed boot edges never armed it.
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
        ):
            _safe_unsub(getattr(self, attr))
            setattr(self, attr, None)
        self._away_pending_at = None
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
        self.reason = REASON_NONE

    # ------------------------------------------------------------------
    # Inputs
    # ------------------------------------------------------------------

    def on_house_state_changed(self, payload: Any) -> None:
        """Fed from SC's house-state bridge BEFORE its auto-follow return."""
        if self._torn_down:
            return
        if isinstance(payload, dict):
            new = str(payload.get("new_state", "") or "")
        else:
            new = str(getattr(payload, "new_state", "") or "")
        if not new:
            return
        cfg = self._cfg()
        if new == "waking":
            if self.reason in SLEEP_LIKE_REASONS:
                self._release("house_state:waking")
            return
        if new in _HOME_STATES:
            if self.reason != REASON_NONE:
                self._release(f"house_state:{new}")
            return
        if new == "arriving":
            self._release("house_state:arriving")
            return
        engage_reason: str | None = None
        if new == "sleep":
            engage_reason = REASON_SLEEP
        elif new == "vacation":
            engage_reason = REASON_VACATION
        elif new == "guest":
            if self._guest_toggle_on(cfg) and self._in_sleep_window(cfg):
                engage_reason = REASON_GUEST_NIGHT
        if engage_reason is None:
            return  # AWAY, GUEST outside the window or toggle OFF: inert
        if not self.kill_switch_on():
            return
        self.reason = engage_reason
        if engage_reason in SLEEP_LIKE_REASONS:
            self._schedule_backstop(cfg)
        else:
            self._cancel_backstop()
        if self._in_boot_window():
            # M1: boot replays (incl. boot_settle_override) rebuild only.
            self._record("boot_edge_rebuild", trigger=f"house_state:{new}", written=[])
            return
        self._request_engage(engage_reason, f"house_state:{new}")

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
            self.reason = REASON_GUEST_NIGHT
            self._schedule_backstop(cfg)
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
        cfg = self._cfg()
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
        self._cancel_reengage()
        self._release("hazard")
        self.reason = REASON_NONE
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
        self._cancel_reengage()
        self._cancel_backstop()
        self._release("kill_switch_off", force=True)
        self.reason = REASON_NONE

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
        resident = self._is_resident(pid, cfg)
        new_val = _state_value(new)
        now_ts = self._ts()
        if old is None:
            # Entity (re)added, e.g. HA person restore: not an arrival edge;
            # stamp last_real as restored (M-2).
            if new_val not in _UNREAL_STATES:
                self._last_real[pid] = (new_val, now_ts, True)
            self._away_on_person(pid, None, new_val, now_ts, cfg)
            return
        old_val = _state_value(old)
        if resident:
            if new_val == "home" and old_val != "home":
                if self._arrival_counts(pid, old_val, now_ts):
                    self._release(f"person:{pid}", person=pid)
            elif new_val not in _UNREAL_STATES and new_val != old_val:
                if self._is_approach_zone(new_val, cfg):
                    self._release(f"approach_zone:{pid}", person=pid)
        # Away lock: before _last_real moves, so P1 sees the pre-edge state.
        self._away_on_person(pid, old_val, new_val, now_ts, cfg)
        if new_val not in _UNREAL_STATES:
            prev = self._last_real.get(pid)
            if prev is None or prev[0] != new_val or prev[2]:
                self._last_real[pid] = (new_val, now_ts, False)

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
            self._release(f"proximity:{sid}", person=person)

    # ------------------------------------------------------------------
    # Release
    # ------------------------------------------------------------------

    def _release(self, trigger: str, *, person: str | None = None, force: bool = False) -> None:
        """Bump the generation, then unlock every locked / lock-pending lockout."""
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

    @callback
    def _on_lockout_event(self, event: Any) -> None:
        if _state_value(event.data.get("new_state")) == "locked":
            self._engage_inflight.pop(event.data.get("entity_id", ""), None)

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
        ):
            self._cancel_reengage()
            self._cancel_backstop()
            self.reason = REASON_NONE
            self.releasing_set.clear()
            return
        if is_arrival:
            if self.reason == REASON_VACATION:
                self.reason = REASON_NONE
                self._cancel_reengage()
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
        restored = old_val is None
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
            if (
                new_val == "home"
                and not restored
                and old_val != "home"
                and self._arrival_counts(pid, old_val, now_ts)
            ):
                self._away_release(f"person:{pid}")
            # After the release (which latches it): this person is not away,
            # so the next all-away formation may attempt again (M6).
            self._away_attempted = False
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
        self._spawn(self._async_away_engage("all_away"))

    async def _async_away_engage(self, trigger: str) -> None:
        if self._away_attempted:
            return
        self._away_attempted = True
        self._away_advisory_sent = False
        cfg = self._cfg()
        for ent in self.away_lock_entities(cfg):
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
        self._cancel_away_dwell()
        self._away_attempted = True
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
                continue  # stays owned; a later release retries
            self.away_lock_owned.discard(ent)
            if val != "locked" and not inflight:
                continue  # already unlocked
            if ent in self._release_inflight:
                continue
            if self._spawn_unlock(ent, trigger, GARAGE_RETRIES(), POLICY_AWAY_LOCK):
                written.append(ent)
        self._save_store()
        self._record("release", trigger=trigger, written=written, policy=POLICY_AWAY_LOCK)

    async def _away_release_on_disable(self) -> None:
        """SC disable (M4): unlock owned / in-flight away locks before teardown."""
        from ..const import GARAGE_LOCKOUT_TEARDOWN_RELEASE_TIMEOUT_S  # noqa: PLC0415

        self._cancel_away_dwell()
        targets = self._away_targets()
        if not targets:
            return
        for ent in targets:
            inflight = self._away_engage_inflight.pop(ent, None) is not None
            _safe_unsub(self._away_readback_unsubs.pop(ent, None))
            self.away_lock_owned.discard(ent)
            val = _state_value(self._hass.states.get(ent))
            if val != "locked" and not inflight:
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
