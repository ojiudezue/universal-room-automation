"""SECURITY-LOCK-SWEEP-RETRY-CAP-1: periodic lock check stops retrying a device
that will not lock/close after N commands in one episode, notifies once, and
re-arms only when the device is seen locked/closed (or after the re-arm
window).

Drives the real SecurityCoordinator (evaluate / _evaluate_lock_check) with a
SimpleNamespace state store. dt_util.utcnow is patched, never slept on.
Cap values are hardcoded literals in assertions (not the imported constant).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import sys

# Scoped import: other files (e.g. test_house_state_rung2a) install their own
# stubbed copies of the URA package via sys.modules.setdefault. Import the real
# modules for this file only, then restore sys.modules at module teardown so
# file order does not matter (DoD #8 / #10).
_SAVED = {k: v for k, v in sys.modules.items() if k.startswith("custom_components")}
from custom_components.universal_room_automation.domain_coordinators import (  # noqa: E402
    security as security_mod,
)
for _k in [k for k in sys.modules if k.startswith("custom_components")]:
    del sys.modules[_k]
sys.modules.update(_SAVED)
# Take the action classes from the security module itself: another file may
# have re-imported base.py, and isinstance against a different copy is False.
NotificationAction = security_mod.NotificationAction
ServiceCallAction = security_mod.ServiceCallAction
Intent = security_mod.Intent


LOCK = "lock.front"
GARAGE = "cover.garage"
T0 = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)


class _States:
    def __init__(self):
        self._d: dict[str, SimpleNamespace] = {}

    def set(self, eid, state):
        self._d[eid] = SimpleNamespace(state=state)

    def get(self, eid):
        return self._d.get(eid)


def _make(locks=(LOCK,), garages=()):
    hass = MagicMock()
    hass.data = {"universal_room_automation": {}}
    hass.config_entries.async_entries = lambda *_a, **_k: []
    states = _States()
    hass.states = states
    coord = security_mod.SecurityCoordinator(
        hass, lock_entities=list(locks), garage_entities=list(garages)
    )
    coord.compliance_tracker = None
    return coord, states


def _run(coord, now=T0):
    with patch.object(security_mod, "async_dispatcher_send", lambda *a, **k: None), \
            patch.object(security_mod.dt_util, "utcnow", lambda: now):
        return asyncio.run(coord._evaluate_lock_check())


def _run_evaluate(coord, now=T0):
    """Drive the full evaluate() path (incl. the observation-mode drop)."""
    intent = Intent(source="periodic_lock_check", entity_id="", data={},
                    coordinator_id="security")
    with patch.object(security_mod, "async_dispatcher_send", lambda *a, **k: None), \
            patch.object(security_mod.dt_util, "utcnow", lambda: now):
        return asyncio.run(coord.evaluate([intent], {}))


def _cmds(actions, eid):
    return [
        a for a in actions
        if isinstance(a, ServiceCallAction) and a.target_device == eid
    ]


def _cap_notes(actions):
    return [
        a for a in actions
        if isinstance(a, NotificationAction)
        and a.description == "Lock check retry cap notification"
    ]


def test_lock_stays_unlocked_exactly_cap_commands_then_one_notify():
    coord, states = _make()
    states.set(LOCK, "unlocked")
    cmd_count = 0
    notes = []
    for _ in range(8):
        acts = _run(coord)
        cmd_count += len(_cmds(acts, LOCK))
        notes.extend(_cap_notes(acts))
    assert cmd_count == 3
    assert len(notes) == 1
    msg = notes[0].message
    assert LOCK in msg and "3 tries" in msg and "stopped retrying" in msg


def test_lock_becomes_locked_resets_counter_fresh_cap():
    coord, states = _make()
    states.set(LOCK, "unlocked")
    for _ in range(4):
        _run(coord)
    assert _cmds(_run(coord), LOCK) == []  # capped
    states.set(LOCK, "locked")
    _run(coord)
    states.set(LOCK, "unlocked")
    acts = [_run(coord) for _ in range(6)]
    assert sum(len(_cmds(a, LOCK)) for a in acts) == 3
    assert sum(len(_cap_notes(a)) for a in acts) == 1


def test_bounce_through_locking_still_caps():
    coord, states = _make()
    total = 0
    for i in range(10):
        states.set(LOCK, "locking" if i % 2 else "unlocked")
        total += len(_cmds(_run(coord), LOCK))
    assert total == 3


def test_jammed_not_commanded_and_continues_episode():
    coord, states = _make()
    states.set(LOCK, "unlocked")
    for _ in range(2):
        _run(coord)
    states.set(LOCK, "jammed")
    for _ in range(3):
        assert _cmds(_run(coord), LOCK) == []
    states.set(LOCK, "unlocked")
    total = sum(len(_cmds(_run(coord), LOCK)) for _ in range(5))
    assert total == 1  # 2 already spent before the jam


def test_garage_cover_capped_and_bounce_through_closing():
    coord, states = _make(locks=(), garages=(GARAGE,))
    cmds, notes = 0, 0
    for i in range(9):
        states.set(GARAGE, "closing" if i % 3 == 2 else "open")
        acts = _run(coord)
        c = _cmds(acts, GARAGE)
        assert all(a.service == "cover.close_cover" for a in c)
        cmds += len(c)
        notes += len(_cap_notes(acts))
    assert cmds == 3
    assert notes == 1
    states.set(GARAGE, "closed")
    _run(coord)
    states.set(GARAGE, "open")
    assert sum(len(_cmds(_run(coord), GARAGE)) for _ in range(5)) == 3


def test_cap_zero_is_unlimited(monkeypatch):
    monkeypatch.setattr(security_mod, "SECURITY_LOCK_RETRY_CAP", 0)
    coord, states = _make()
    states.set(LOCK, "unlocked")
    acts_all = [_run(coord) for _ in range(10)]
    assert sum(len(_cmds(a, LOCK)) for a in acts_all) == 10
    assert sum(len(_cap_notes(a)) for a in acts_all) == 0


def test_unavailable_not_counted_as_failure():
    coord, states = _make()
    states.set(LOCK, "unavailable")
    for _ in range(6):
        acts = _run(coord)
        assert _cmds(acts, LOCK) == []
        assert _cap_notes(acts) == []
    states.set(LOCK, "unlocked")
    total = sum(len(_cmds(_run(coord), LOCK)) for _ in range(6))
    assert total == 3


def test_observation_mode_does_not_spend_retries():
    coord, states = _make()
    states.set(LOCK, "unlocked")
    coord.observation_mode = True
    for _ in range(5):
        assert _run_evaluate(coord) == []
    coord.observation_mode = False
    acts = [_run_evaluate(coord) for _ in range(5)]
    assert len(_cmds(acts[0], LOCK)) == 1
    assert acts[0][[isinstance(a, ServiceCallAction) for a in acts[0]].index(True)].service == "lock.lock"
    assert sum(len(_cmds(a, LOCK)) for a in acts) == 3
    assert sum(len(_cap_notes(a)) for a in acts) == 1


def test_capped_device_still_in_found_unlocked():
    coord, states = _make()
    states.set(LOCK, "unlocked")
    for _ in range(4):
        _run(coord)
    sweep = coord._last_lock_sweep
    assert sweep["found_unlocked"] == [LOCK]
    assert sweep["lock_actions_sent"] == []
    assert sweep["retry_capped"] == [LOCK]


def test_rearm_after_24h():
    coord, states = _make()
    states.set(LOCK, "unlocked")
    for i in range(4):
        _run(coord, T0 + timedelta(minutes=60 * i))
    capped_at = T0 + timedelta(hours=3)
    # 1 s before the window: still capped
    assert _cmds(_run(coord, capped_at + timedelta(seconds=86399)), LOCK) == []
    acts = [_run(coord, capped_at + timedelta(seconds=86400 + 60 * i)) for i in range(5)]
    assert len(_cmds(acts[0], LOCK)) == 1  # exactly at the window boundary
    assert sum(len(_cmds(a, LOCK)) for a in acts) == 3
    assert sum(len(_cap_notes(a)) for a in acts) == 1


def test_rearm_zero_never_rearms(monkeypatch):
    monkeypatch.setattr(security_mod, "SECURITY_LOCK_RETRY_REARM_S", 0)
    coord, states = _make()
    states.set(LOCK, "unlocked")
    for _ in range(4):
        _run(coord)
    assert _cmds(_run(coord, T0 + timedelta(days=30)), LOCK) == []


def test_cap_notice_not_lost_to_observation_mode():
    coord, states = _make()
    states.set(LOCK, "unlocked")
    for _ in range(3):
        _run_evaluate(coord)  # 3 real commands, obs off
    coord.observation_mode = True
    assert _run_evaluate(coord) == []  # cap sweep while observing: dropped
    coord.observation_mode = False
    notes = sum(len(_cap_notes(_run_evaluate(coord))) for _ in range(3))
    assert notes == 1
