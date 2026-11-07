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
import logging
from datetime import datetime, timedelta
from typing import Any, Callable

_LOGGER = logging.getLogger(__name__)

POLICY_NAME = "security.lock_regime.garage_lockout"

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
    from homeassistant.exceptions import HomeAssistantError  # noqa: PLC0415
    from homeassistant.util.unit_conversion import DistanceConverter  # noqa: PLC0415

    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    try:
        return float(DistanceConverter.convert(number, unit, "m"))
    except (HomeAssistantError, ValueError, TypeError):
        return None


def lockout_overlap(lock_entities: Any, lockout_entities: Any) -> list[str]:
    """Entities listed both as sweep/lockdown locks and as remote lockouts.

    Options-flow validator (plan §3.3): a lockout must never be in
    ``security_lock_entities``, or the sweep and lockdown would lock it.
    """
    def _as_set(raw: Any) -> set[str]:
        if isinstance(raw, str):
            return {raw}
        if isinstance(raw, (list, tuple, set, frozenset)):
            return {str(x) for x in raw}
        return set()

    return sorted(_as_set(lock_entities) & _as_set(lockout_entities))


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

    def _backstop_delay_s(self, cfg: dict[str, Any]) -> float:
        """Seconds until the morning backstop; 0 = release now (daytime, past it)."""
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
        today_deadline = now.replace(hour=end, minute=0, second=0, microsecond=0) + (
            timedelta(minutes=backstop_min)
        )
        if now < today_deadline:
            return (today_deadline - now).total_seconds()
        if now.hour >= start:
            return (today_deadline + timedelta(days=1) - now).total_seconds()
        return 0.0

    def _seconds_until_hour(self, hour: int) -> float:
        now = self._now()
        target = now.replace(hour=hour, minute=0, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return (target - now).total_seconds()

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
                if isinstance(data, dict):
                    persisted = {str(p) for p in data.get("residents", [])}
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
        excluded = self._excluded(cfg)
        for pid in sorted((live | persisted) - excluded):
            self._subscribe_person(pid)
        self._residents = (live | persisted) - excluded
        self._save_residents()

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
        """Boot never engages. Recent arrival releases; else rebuild reason (H1)."""
        from ..const import GARAGE_LOCKOUT_BOOT_ARRIVAL_WINDOW_S  # noqa: PLC0415

        if not self.kill_switch_on():
            return
        locked = [
            e for e in self.lockout_entities(cfg)
            if _state_value(self._hass.states.get(e)) == "locked"
        ]
        if not locked:
            return
        now_ts = self._ts()
        for pid in sorted(self._residents):
            st = self._hass.states.get(pid)
            if _state_value(st) != "home":
                continue
            changed = getattr(st, "last_changed", None)
            try:
                changed_ts = changed.timestamp()
            except Exception:  # noqa: BLE001
                continue
            if now_ts - changed_ts <= GARAGE_LOCKOUT_BOOT_ARRIVAL_WINDOW_S:
                self._release("boot_recent_arrival", person=pid)
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
            self._schedule_backstop(cfg)

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
        ):
            _safe_unsub(getattr(self, attr))
            setattr(self, attr, None)
        for unsub in self._readback_unsubs.values():
            _safe_unsub(unsub)
        self._readback_unsubs.clear()
        for task in list(self._tasks):
            if not task.done():
                task.cancel()
        self._tasks.clear()

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
        if not person or not self._is_resident(person, self._cfg()):
            return
        self._release("arriving_signal", person=person)

    def on_hazard(self) -> None:
        """Critical smoke/fire/CO with egress unlock configured."""
        if self._torn_down:
            return
        self._cancel_reengage()
        self._release("hazard")
        self.reason = REASON_NONE

    def on_kill_switch_changed(self, enabled: bool) -> None:
        """ON -> OFF releases once. OFF -> ON never catches up (INV-5)."""
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

    def _on_person_added(self, event: Any) -> None:
        pid = event.data.get("entity_id", "")
        if not pid or self._torn_down:
            return
        if not self._is_resident(pid, self._cfg()):
            return
        self._subscribe_person(pid)
        self._residents.add(pid)
        if pid in self.releasing_set:
            self.releasing_set[pid]["removed"] = False
        self._save_residents()

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
        self._save_residents()

    def _on_person_event(self, event: Any) -> None:
        if self._torn_down:
            return
        pid = event.data.get("entity_id", "")
        new = event.data.get("new_state")
        old = event.data.get("old_state")
        cfg = self._cfg()
        if new is None or not self._is_resident(pid, cfg):
            return
        new_val = _state_value(new)
        now_ts = self._ts()
        if old is None:
            # Entity (re)added, e.g. HA person restore: not an arrival edge;
            # stamp last_real as restored (M-2).
            if new_val not in _UNREAL_STATES:
                self._last_real[pid] = (new_val, now_ts, True)
            return
        old_val = _state_value(old)
        if new_val == "home" and old_val != "home":
            if self._arrival_counts(pid, old_val, now_ts):
                self._release(f"person:{pid}", person=pid)
        elif new_val not in _UNREAL_STATES and new_val != old_val:
            if self._is_approach_zone(new_val, cfg):
                self._release(f"approach_zone:{pid}", person=pid)
        if new_val not in _UNREAL_STATES:
            prev = self._last_real.get(pid)
            if prev is None or prev[0] != new_val or prev[2]:
                self._last_real[pid] = (new_val, now_ts, False)

    def _arrival_counts(self, pid: str, old_val: str | None, now_ts: float) -> bool:
        from ..const import GARAGE_LOCKOUT_BLIP_MIN_AWAY_MIN  # noqa: PLC0415

        if old_val not in _UNREAL_STATES:
            return True  # not_home / named zone -> home
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
        """Proximity sensors are named <proximity>_<person>_distance."""
        for pid in self._residents:
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
            pending_lock = ent in self._engage_inflight
            if val != "locked" and not pending_lock:
                continue
            if ent in self._release_inflight:
                continue  # H3b: one release in flight per entity
            self._release_inflight.add(ent)
            self._engage_inflight.pop(ent, None)
            written.append(ent)
            self._spawn(self._async_unlock(ent, trigger, GARAGE_RETRIES()))
        self._after_release(trigger, person, cfg)
        self._record("release", trigger=trigger, written=written)

    def _after_release(self, trigger: str, person: str | None, cfg: dict[str, Any]) -> None:
        is_arrival = person is not None or trigger.startswith("proximity:")
        if trigger.startswith("house_state:") or trigger in (
            "backstop", "boot_recent_arrival",
        ):
            self._cancel_reengage()
            self._cancel_backstop()
            self.reason = REASON_NONE
            if trigger != "boot_recent_arrival":
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

    async def _async_unlock(self, ent: str, trigger: str, retries_left: int) -> None:
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
        self._readback_unsubs[ent] = self._call_later(
            self._hass,
            float(GARAGE_LOCKOUT_READBACK_S),
            lambda _now=None, e=ent, t=trigger, r=retries_left: self._on_readback(e, t, r),
        )

    def _on_readback(self, ent: str, trigger: str, retries_left: int) -> None:
        self._readback_unsubs.pop(ent, None)
        if self._torn_down:
            self._release_inflight.discard(ent)
            return
        if _state_value(self._hass.states.get(ent)) != "locked":
            self._release_inflight.discard(ent)
            return
        if retries_left > 0:
            self._spawn(self._async_unlock(ent, trigger, retries_left - 1))
            return
        self._release_inflight.discard(ent)
        self._spawn(self._notify_failure(ent, trigger))

    async def _notify_failure(self, ent: str, trigger: str, *, timeout: bool = False) -> None:
        from ..const import DOMAIN  # noqa: PLC0415
        from .base import Severity  # noqa: PLC0415

        nm = self._hass.data.get(DOMAIN, {}).get("notification_manager")
        if nm is None:
            return
        coro = nm.async_notify(
            coordinator_id="security",
            severity=Severity.HIGH,
            title="Garage lockout release failed",
            message=(
                f"{ent} is still locked after a release ({trigger}). The car "
                "remotes and keypad may not open this garage. Unlock it from "
                "the HA app or the opener's own app."
            ),
            hazard_type="lockout_release_failed",
            location="garage",
        )
        try:
            if timeout:
                from ..const import GARAGE_LOCKOUT_TEARDOWN_RELEASE_TIMEOUT_S  # noqa: PLC0415

                await asyncio.wait_for(coro, timeout=GARAGE_LOCKOUT_TEARDOWN_RELEASE_TIMEOUT_S)
            else:
                await coro
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Lock regime: NM notify failed", exc_info=True)

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

    def _schedule_backstop(self, cfg: dict[str, Any]) -> None:
        self._cancel_backstop()
        self._backstop_unsub = self._call_later(
            self._hass, self._backstop_delay_s(cfg), self._on_backstop
        )

    def _cancel_backstop(self) -> None:
        _safe_unsub(self._backstop_unsub)
        self._backstop_unsub = None

    def _on_backstop(self, _now: Any = None) -> None:
        self._backstop_unsub = None
        if self._torn_down:
            return
        if self.reason in SLEEP_LIKE_REASONS:
            self._release("backstop")

    # ------------------------------------------------------------------
    # Bookkeeping
    # ------------------------------------------------------------------

    def _spawn(self, coro: Any) -> None:
        task = self._hass.async_create_task(coro)
        if isinstance(task, asyncio.Task):
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    def _save_residents(self) -> None:
        if self._store is None:
            return
        try:
            self._store.async_delay_save(
                lambda: {"residents": sorted(self._residents)}, 1.0
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Lock regime: resident store save failed", exc_info=True)

    def _record(
        self,
        action: str,
        *,
        trigger: str,
        written: list[str],
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Log AFTER any write was issued (never between check and call)."""
        from ..const import DOMAIN  # noqa: PLC0415

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
        self.last_action = record
        decision_logger = getattr(self._sc, "decision_logger", None)
        if decision_logger is not None:
            try:
                from .coordinator_diagnostics import DecisionLog  # noqa: PLC0415

                decision_logger.log_decision(
                    DecisionLog(
                        coordinator_id="security",
                        decision_type=f"lock_regime_{action}",
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
                            action=f"lock_regime_{action}",
                            description=f"Garage lockout {action}: {', '.join(written)} ({trigger})",
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
