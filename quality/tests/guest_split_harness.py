"""Shared harness for GUEST-MODE-SPLIT-VISITORS-1 tests (not a test module).

Plan: docs/planning/PLANNING_guest_mode_split_2026_11.md rev 4.

Loads the URA package under a private alias (``ura_guestsplit_pkg``) against a
fresh copy of ``homeassistant`` / ``aiosqlite`` and restores every original
``sys.modules`` entry afterwards (same pattern as
test_house_state_sleep_mask_ble_memory._load; DoD 8: no permanent surgery).

``World`` drives the REAL ``PresenceCoordinator._run_inference`` with the REAL
guest gates (``_guest_room_gate_armed`` over ``_guest_room_state``,
``_guest_gate_armed`` over unidentified count / confidence / persistence) and a
REAL ``HouseStateMachine``. ``infer()`` is wrapped (call-through) only to record
the ``guest_gate_armed`` kwarg and the returned proposal.

``run_tuple`` is also the golden generator: the golden file
``fixtures/guest_split_golden_base.json`` was produced by running it against
the base tree (develop @ f8cbcba4 == code of 4b52c262) BEFORE any change.
"""
from __future__ import annotations

import asyncio
import importlib
import itertools
import random
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

_URA_ROOT = (
    Path(__file__).resolve().parents[2]
    / "custom_components" / "universal_room_automation"
)
_PKG = "ura_guestsplit_pkg"
_POLLUTABLE = ("homeassistant", "aiosqlite")


def load():
    """Return (CONST, HSM, PR, DB) from the alias package."""
    if f"{_PKG}.domain_coordinators.presence" in sys.modules:
        return _import_names()
    saved = {
        k: v for k, v in sys.modules.items() if k.split(".")[0] in _POLLUTABLE
    }
    for k in saved:
        del sys.modules[k]
    try:
        return _import_names()
    finally:
        for k in [k for k in sys.modules if k.split(".")[0] in _POLLUTABLE]:
            del sys.modules[k]
        sys.modules.update(saved)


def _import_names():
    if f"{_PKG}.domain_coordinators.presence" not in sys.modules:
        pkg = types.ModuleType(_PKG)
        pkg.__path__ = [str(_URA_ROOT)]
        sys.modules[_PKG] = pkg
        dc = types.ModuleType(f"{_PKG}.domain_coordinators")
        dc.__path__ = [str(_URA_ROOT / "domain_coordinators")]
        sys.modules[f"{_PKG}.domain_coordinators"] = dc
    for lazy in (
        "domain_coordinators.notification_manager",
        "domain_coordinators._stuck_signal_nm",
        "domain_coordinators.occupancy_substrate",
        "domain_coordinators.signals",
        "memory_writers",
        "aggregation",
        "binary_sensor",
        "sensor",
    ):
        importlib.import_module(f"{_PKG}.{lazy}")
    names = (
        "const", "domain_coordinators.house_state",
        "domain_coordinators.presence", "database",
    )
    mods = [importlib.import_module(f"{_PKG}.{n}") for n in names]
    # binary_sensor imports DeviceInfo lazily (inside __init__): keep the
    # clean module so entity tests can scope it in (monkeypatch.setitem).
    mods.append(importlib.import_module("homeassistant.helpers.device_registry"))
    return mods


CONST, HSM, PR, DB, REAL_DEVICE_REGISTRY = load()
HS = HSM.HouseState
DOMAIN = CONST.DOMAIN
DT = PR.dt_util

GB1 = "Guest Bedroom 1"


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _close(coro, *a, **k):
    try:
        coro.close()
    except Exception:  # noqa: BLE001
        pass
    return MagicMock()


class Clock:
    def __init__(self, t):
        self.t = t

    def advance(self, seconds):
        self.t = self.t + timedelta(seconds=seconds)


def install_clock(monkeypatch, t0, tz=timezone.utc):
    """Patch dt_util.now/utcnow; local zone = ``tz``."""
    c = Clock(t0)
    monkeypatch.setattr(DT, "now", lambda *a, **k: c.t.astimezone(tz))
    monkeypatch.setattr(DT, "utcnow", lambda: c.t.astimezone(timezone.utc))
    monkeypatch.setattr(DT, "DEFAULT_TIME_ZONE", tz)
    return c


class World:
    """PresenceCoordinator + real HouseStateMachine, census 2 (people home)."""

    def __init__(self, monkeypatch, *, state=HS.HOME_DAY, census=2,
                 sleep_start=22, sleep_end=6):
        self.dispatched = []
        hass = MagicMock()
        hass.states.get = lambda eid: None
        hass.config_entries.async_entries = lambda domain=None: []
        hass.async_create_task = _close
        hass.async_create_background_task = _close
        hass.is_running = True
        sm = HSM.HouseStateMachine(initial_state=state)
        sm._state_since = DT.utcnow() - timedelta(hours=6)
        manager = MagicMock()
        manager.house_state_machine = sm
        hass.data = {DOMAIN: {"coordinator_manager": manager}}
        coord = PR.PresenceCoordinator(
            hass, sleep_start_hour=sleep_start, sleep_end_hour=sleep_end,
        )
        coord._enabled = True
        coord._boot_settle_done = True
        coord._census_count = census
        coord._unidentified_count = 0
        coord._census_camera_input_dark = False
        coord._zone_trackers = {}
        coord._schedule_guest_persistence_recheck = lambda *_a, **_k: None
        manager.presence = coord
        manager.coordinators = {"presence": coord}
        self.hass, self.sm, self.manager, self.coord = hass, sm, manager, coord
        self.infer_calls = []
        self.gate_calls = {"room": 0, "unid": 0}
        world = self
        engine = coord._inference_engine
        real_infer = engine.infer

        def _infer(**kw):
            res = real_infer(**kw)
            world.infer_calls.append((kw.get("guest_gate_armed"), res))
            return res

        engine.infer = _infer
        real_room = coord._guest_room_gate_armed
        real_unid = coord._guest_gate_armed

        def _room(*a, **k):
            world.gate_calls["room"] += 1
            return real_room(*a, **k)

        def _unid(*a, **k):
            world.gate_calls["unid"] += 1
            return real_unid(*a, **k)

        coord._guest_room_gate_armed = _room
        coord._guest_gate_armed = _unid

        def _send(_hass, signal, *args):
            world.dispatched.append((signal, args))

        monkeypatch.setattr(PR, "async_dispatcher_send", _send)

    # -- inputs ------------------------------------------------------------
    def guest_room(self, elapsed_min, room=GB1, threshold=30):
        """Unknown occupant in ``room`` for ``elapsed_min`` (None = empty)."""
        first = None
        if elapsed_min is not None:
            first = DT.utcnow() - timedelta(minutes=elapsed_min)
        self.coord._guest_room_state[room] = {
            "first_seen": first,
            "current_occupancy_known": False,
            "threshold_min": threshold,
        }
        return self

    def unidentified(self, count, confidence="high", persisted_s=None):
        self.coord._unidentified_count = count
        self.coord._census_confidence = confidence
        self.coord._unidentified_first_seen = (
            None if persisted_s is None
            else DT.now() - timedelta(seconds=persisted_s)
        )
        return self

    def tick(self):
        run(self.coord._run_inference("test"))
        return self.sm.state


def drive_once(*, state, rule_on, room_min=None, unid=(0, "high", None),
               stay=False, hour=14, advance_s=None):
    """One (or two, with ``advance_s``) real ``_run_inference`` ticks in a
    scoped MonkeyPatch; returns (final_state, guest_armed kwargs seen).

    Used by the behavioural replacements of the pre-cycle source-grep anchors
    (test_guest_census_correctness / test_v472_feature_b_guest_signal)."""
    import pytest

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(CONST, "GUEST_NIGHT_STAY_RULE_ENABLED", rule_on)
        clock = install_clock(
            mp, datetime(2026, 11, 10, hour, 0, tzinfo=timezone.utc))
        w = World(mp, state=state)
        w.coord._guest_stay_active = stay
        w.guest_room(room_min)
        w.unidentified(*unid)
        final = w.tick()
        if advance_s is not None:
            clock.advance(advance_s)
            final = w.tick()
        return final, [a for a, _p in w.infer_calls]


# ---------------------------------------------------------------------------
# Golden tuples (INV-VIS-1 / INV-STAY-3)
# ---------------------------------------------------------------------------

STATES = ("home_day", "home_evening", "home_night", "guest", "sleep", "away")
ROOM_MIN = (None, 10, 45)
UNID = (0, 2)
CONF = ("low", "high")
PERSIST = (None, 100, 400)
OVERRIDE = (False, True)
SWITCH = (True, False)
HOURS = (14, 23)


def golden_tuples(n=200, seed=20261109):
    allt = list(itertools.product(
        STATES, ROOM_MIN, UNID, CONF, PERSIST, OVERRIDE, SWITCH, HOURS,
    ))
    rnd = random.Random(seed)
    return rnd.sample(allt, n)


def run_tuple(monkeypatch, tup):
    state, room_min, unid, conf, persist, override, switch, hour = tup
    install_clock(
        monkeypatch, datetime(2026, 11, 10, hour, 30, tzinfo=timezone.utc),
    )
    w = World(monkeypatch, state=HS(state))
    if override:
        w.sm.set_override(HS.GUEST)
    w.coord._guest_detection_enabled = switch
    w.guest_room(room_min)
    w.unidentified(unid, conf, persist)
    final = w.tick()
    armed, proposal = w.infer_calls[-1] if w.infer_calls else (None, None)
    return {
        "tuple": list(tup),
        "guest_armed": armed,
        "proposal": proposal.value if proposal is not None else None,
        "final": final.value,
        "guest_reason": w.coord._guest_reason,
        "confidence": round(float(w.coord._inference_engine._confidence), 4),
        "gate_calls": dict(w.gate_calls),
    }
