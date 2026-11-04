"""SECURITY-LOCK-SWEEP-RETRY-CAP-1: periodic lock check stops retrying a device
that will not lock/close after N commands in one episode, notifies once, and
re-arms when the device changes state.

Drives the real SecurityCoordinator._evaluate_lock_check with a real-ish
state store (SimpleNamespace states carrying ``state`` + ``last_changed``).
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


LOCK = "lock.front"
GARAGE = "cover.garage"
T0 = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)


class _States:
    def __init__(self):
        self._d: dict[str, SimpleNamespace] = {}

    def set(self, eid, state, changed):
        self._d[eid] = SimpleNamespace(state=state, last_changed=changed)

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


def _run(coord):
    with patch.object(security_mod, "async_dispatcher_send", lambda *a, **k: None):
        return asyncio.run(coord._evaluate_lock_check())


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
    states.set(LOCK, "unlocked", T0)
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
    states.set(LOCK, "unlocked", T0)
    for _ in range(4):
        _run(coord)
    assert _cmds(_run(coord), LOCK) == []  # capped
    # Locks, observed locked at a check (counter reset) ...
    states.set(LOCK, "locked", T0 + timedelta(hours=1))
    _run(coord)
    # ... then unlocked again with the SAME last_changed as the original
    # episode would be impossible live, so isolate the reset: reuse T0.
    states.set(LOCK, "unlocked", T0)
    total = sum(len(_cmds(_run(coord), LOCK)) for _ in range(6))
    assert total == 3


def test_state_change_between_checks_rearms_episode():
    coord, states = _make()
    states.set(LOCK, "unlocked", T0)
    for _ in range(5):
        _run(coord)
    # manual lock + unlock between checks: last_changed advances
    states.set(LOCK, "unlocked", T0 + timedelta(hours=2))
    total = sum(len(_cmds(_run(coord), LOCK)) for _ in range(6))
    assert total == 3


def test_garage_cover_capped_same_way():
    coord, states = _make(locks=(), garages=(GARAGE,))
    states.set(GARAGE, "open", T0)
    cmds, notes = 0, 0
    for _ in range(7):
        acts = _run(coord)
        c = _cmds(acts, GARAGE)
        assert all(a.service == "cover.close_cover" for a in c)
        cmds += len(c)
        notes += len(_cap_notes(acts))
    assert cmds == 3
    assert notes == 1
    states.set(GARAGE, "closed", T0 + timedelta(minutes=5))
    _run(coord)
    states.set(GARAGE, "open", T0)
    assert sum(len(_cmds(_run(coord), GARAGE)) for _ in range(5)) == 3


def test_cap_zero_is_unlimited(monkeypatch):
    monkeypatch.setattr(security_mod, "SECURITY_LOCK_RETRY_CAP", 0)
    coord, states = _make()
    states.set(LOCK, "unlocked", T0)
    acts_all = [_run(coord) for _ in range(10)]
    assert sum(len(_cmds(a, LOCK)) for a in acts_all) == 10
    assert sum(len(_cap_notes(a)) for a in acts_all) == 0


def test_unavailable_not_counted_as_failure():
    coord, states = _make()
    states.set(LOCK, "unavailable", T0)
    for _ in range(6):
        acts = _run(coord)
        assert _cmds(acts, LOCK) == []
        assert _cap_notes(acts) == []
    states.set(LOCK, "unlocked", T0)
    total = sum(len(_cmds(_run(coord), LOCK)) for _ in range(6))
    assert total == 3
