"""SHARED-SPACE-AUTO-OFF-FAILSAFE-1 option A — failsafe runs in PAUSED rooms.

Drives the REAL ``UniversalRoomCoordinator._async_update_data`` (same
construction as test_room_menu_adv_trim_and_room_rate._room_coordinator_tick)
with the room switches stubbed per test:

- master ``automation`` OFF (paused) + vacant  -> failsafe called, vacant
- master OFF + override_occupied               -> failsafe called, occupied
  (and with the REAL body: no turn-off)
- master ON                                    -> exactly ONE call per tick
- skip-first tick / ManualMode ON              -> no call
- paused + vacant + in window, REAL body       -> lights swept
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from _room_menu_helpers import run
from custom_components.universal_room_automation.const import DOMAIN


def _coordinator(switches: dict):
    import homeassistant.helpers.frame as _frame
    from custom_components.universal_room_automation import coordinator as co

    db = AsyncMock()  # every DAO coroutine awaitable
    db.get_energy_for_period = AsyncMock(return_value=0.0)
    db.get_next_occupancy_prediction = AsyncMock(return_value=None)
    db.get_occupancy_percentage = AsyncMock(return_value=None)
    db.get_peak_occupancy_hour = AsyncMock(return_value=None)
    db.log_environmental_data = AsyncMock(return_value=None)
    db.log_occupancy_event = AsyncMock(return_value=None)
    hass = MagicMock()
    hass.data = {DOMAIN: {"database": db}}
    hass.states.get = lambda eid: None
    entry = MagicMock()
    entry.data = {"room_name": "Kitchen", "room_type": "kitchen",
                  "entry_type": "room", "shared_space": True,
                  "lights": ["light.kitchen_overhead"]}
    entry.options = {}
    entry.entry_id = "K1"
    with patch.object(_frame, "report_usage", lambda *a, **k: None):
        c = co.UniversalRoomCoordinator(hass, entry)
    c._skip_first_automation = False
    c._get_room_switch_state = lambda key: switches.get(key)
    return c, co


def _spy(c):
    spy = AsyncMock(return_value=None)
    c.automation.check_scheduled_auto_off = spy
    return spy


def test_paused_room_vacant_failsafe_called_once_with_vacant():
    c, _ = _coordinator({"automation": False})
    spy = _spy(c)
    run(c._async_update_data())
    assert spy.await_count == 1
    assert spy.await_args.args == (False,)


def test_paused_room_occupied_failsafe_called_with_occupied():
    c, _ = _coordinator({"automation": False, "override_occupied": True})
    spy = _spy(c)
    run(c._async_update_data())
    assert spy.await_count == 1
    assert spy.await_args.args == (True,)


def test_unpaused_room_exactly_one_call_per_tick():
    c, _ = _coordinator({"automation": True})
    spy = _spy(c)
    run(c._async_update_data())
    assert spy.await_count == 1
    run(c._async_update_data())
    assert spy.await_count == 2


def test_skip_first_tick_does_not_call_failsafe():
    c, _ = _coordinator({"automation": False})
    c._skip_first_automation = True
    spy = _spy(c)
    run(c._async_update_data())
    assert spy.await_count == 0
    run(c._async_update_data())  # next real tick does run it
    assert spy.await_count == 1


@pytest.mark.parametrize("master", [True, False])
def test_manual_mode_on_blocks_failsafe(master):
    c, _ = _coordinator({"automation": master, "manual_mode": True})
    spy = _spy(c)
    run(c._async_update_data())
    assert spy.await_count == 0


def _real_body(c, monkeypatch, when):
    from custom_components.universal_room_automation import automation as A
    monkeypatch.setattr(A.dt_util, "now", lambda: when)
    a = c.automation
    monkeypatch.setattr(a, "_failsafe_boot_settle_done", lambda: True)
    sweep = AsyncMock(return_value=None)
    monkeypatch.setattr(a, "_shared_space_turn_off_all", sweep)
    return sweep


def test_paused_room_vacant_in_window_real_body_sweeps(monkeypatch):
    c, _ = _coordinator({"automation": False})
    sweep = _real_body(c, monkeypatch, datetime(2026, 11, 12, 1, 30, tzinfo=timezone.utc))
    run(c._async_update_data())
    assert sweep.await_count == 1


def test_paused_room_occupied_in_window_real_body_no_sweep(monkeypatch):
    c, _ = _coordinator({"automation": False, "override_occupied": True})
    sweep = _real_body(c, monkeypatch, datetime(2026, 11, 12, 1, 30, tzinfo=timezone.utc))
    run(c._async_update_data())
    assert sweep.await_count == 0
