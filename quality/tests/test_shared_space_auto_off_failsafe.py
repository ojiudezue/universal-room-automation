"""SHARED-SPACE-AUTO-OFF-FAILSAFE-1 — vacancy-gated night failsafe.

Plan: docs/planning/PLANNING_shared_space_auto_off_failsafe.md (rev 2).

Invariant: for a shared-space room, if any tick between the auto-off hour
and the cutoff sees the room vacant, every light / night light / leave-on
light not held by ``light_hold_allowed`` is turned off exactly once that
night. No sweep on an occupied tick, outside the window, or during boot
settle. The T-5 warning flash is gone (D4).

Drives the REAL ``RoomAutomation.check_scheduled_auto_off`` loaded under a
private package alias (order-independent, same loader as
test_hvac_batch_d_shared_space_fans). Wall clock is patched per test via
``monkeypatch`` on the module's ``dt_util`` binding. Oracles are hand-written
literals.
"""

from __future__ import annotations

import asyncio
import importlib
import sys
import types
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

_URA = (
    Path(__file__).resolve().parents[2]
    / "custom_components" / "universal_room_automation"
)
_PKG = "ura_shared_space_failsafe_pkg"


def _load():
    if f"{_PKG}.automation" not in sys.modules:
        pkg = types.ModuleType(_PKG)
        pkg.__path__ = [str(_URA)]
        sys.modules[_PKG] = pkg
        dc = types.ModuleType(f"{_PKG}.domain_coordinators")
        dc.__path__ = [str(_URA / "domain_coordinators")]
        sys.modules[f"{_PKG}.domain_coordinators"] = dc
    return (
        importlib.import_module(f"{_PKG}.const"),
        importlib.import_module(f"{_PKG}.automation"),
    )


C, A = _load()
DOMAIN = C.DOMAIN

OVERHEAD = "light.kitchen_overhead"   # leave-on light (the 11-02 incident)
PENDANT = "light.kitchen_pendant"
NIGHT = "light.kitchen_night"
FAN = "fan.kitchen"
SWITCH = "switch.kitchen_relay"


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _Logger:
    def __init__(self):
        self.rows: list = []

    def log(self, **kw):
        self.rows.append(kw)
        return None


def _room(*, start=23, cutoff=5, shared=True, settle_done=True,
          extra=None, fan_mode=None):
    hass = MagicMock()
    presence = SimpleNamespace(_boot_settle_done=settle_done)
    mgr = SimpleNamespace(coordinators={"presence": presence})
    logger = _Logger()
    hass.data = {DOMAIN: {"coordinator_manager": mgr, "activity_logger": logger}}
    hass.async_create_task = lambda _x: None
    hass.config_entries.async_entries = lambda domain=None: []
    config = {
        C.CONF_ROOM_NAME: "Kitchen",
        C.CONF_SHARED_SPACE: shared,
        C.CONF_SHARED_SPACE_AUTO_OFF_HOUR: start,
        C.CONF_SHARED_SPACE_AUTO_OFF_CUTOFF_HOUR: cutoff,
        C.CONF_LIGHTS: [OVERHEAD, PENDANT],
        C.CONF_NIGHT_LIGHTS: [NIGHT],
        C.CONF_LIGHTS_LEAVE_ON_WHEN_EMPTY: [OVERHEAD],
        C.CONF_FANS: [FAN],
        C.CONF_ROOM_FAN_MODE: fan_mode or C.FAN_MODE_ROOM_TEMPERATURE,
        C.CONF_AUTO_SWITCHES: [SWITCH],
    }
    config.update(extra or {})
    auto = A.RoomAutomation(hass=hass, config=config, coordinator=MagicMock())
    log: list = []

    async def _svc(domain, service, data=None, **kw):
        log.append((domain, service, dict(data or {})))
        return True

    auto._safe_service_call = _svc
    return SimpleNamespace(auto=auto, log=log, logger=logger, presence=presence)


def _offs(log):
    out = []
    for _dom, svc, data in log:
        if svc != "turn_off":
            continue
        ids = data.get("entity_id")
        out += ids if isinstance(ids, list) else [ids]
    return sorted(out)


def _tick(monkeypatch, room, when: datetime, occupied: bool):
    monkeypatch.setattr(A, "dt_util", SimpleNamespace(now=lambda: when))
    _run(room.auto.check_scheduled_auto_off(occupied))


ALL_OFF = sorted([OVERHEAD, PENDANT, NIGHT, FAN, SWITCH])


# ---------------------------------------------------------------------------
# D1 + D2 — vacancy gate, retry, leave-on included, once per night
# ---------------------------------------------------------------------------


def test_occupied_2300_no_sweep_first_vacant_0130_sweeps_once(monkeypatch):
    r = _room()
    _tick(monkeypatch, r, datetime(2026, 11, 2, 23, 0), occupied=True)
    assert r.log == []
    _tick(monkeypatch, r, datetime(2026, 11, 3, 1, 30), occupied=False)
    assert _offs(r.log) == ALL_OFF          # leave-on overhead INCLUDED
    assert OVERHEAD in _offs(r.log)
    n = len(r.log)
    _tick(monkeypatch, r, datetime(2026, 11, 3, 3, 0), occupied=False)
    assert len(r.log) == n                  # same night: no second sweep


def test_occupied_all_window_never_sweeps_and_closes_at_cutoff(monkeypatch):
    r = _room()
    for when in (datetime(2026, 11, 2, 23, 0), datetime(2026, 11, 3, 0, 59),
                 datetime(2026, 11, 3, 4, 59)):
        _tick(monkeypatch, r, when, occupied=True)
    _tick(monkeypatch, r, datetime(2026, 11, 3, 5, 0), occupied=False)
    _tick(monkeypatch, r, datetime(2026, 11, 3, 12, 0), occupied=False)
    _tick(monkeypatch, r, datetime(2026, 11, 3, 22, 59), occupied=False)
    assert r.log == []


def test_vacant_at_0459_still_sweeps(monkeypatch):
    r = _room()
    _tick(monkeypatch, r, datetime(2026, 11, 3, 4, 59), occupied=False)
    assert _offs(r.log) == ALL_OFF


def test_no_double_fire_across_midnight_keyed_by_window_start(monkeypatch):
    r = _room()
    _tick(monkeypatch, r, datetime(2026, 11, 2, 23, 10), occupied=False)
    assert _offs(r.log) == ALL_OFF
    n = len(r.log)
    _tick(monkeypatch, r, datetime(2026, 11, 3, 0, 10), occupied=False)
    assert len(r.log) == n
    # The NEXT night opens a new key and sweeps again.
    _tick(monkeypatch, r, datetime(2026, 11, 3, 23, 5), occupied=False)
    assert len(r.log) == 2 * n


def test_not_shared_space_never_sweeps(monkeypatch):
    r = _room(shared=False)
    _tick(monkeypatch, r, datetime(2026, 11, 2, 23, 30), occupied=False)
    assert r.log == []


def test_boot_settle_blocks_then_retries(monkeypatch):
    r = _room(settle_done=False)
    _tick(monkeypatch, r, datetime(2026, 11, 2, 23, 30), occupied=False)
    assert r.log == []
    r.presence._boot_settle_done = True
    _tick(monkeypatch, r, datetime(2026, 11, 2, 23, 31), occupied=False)
    assert _offs(r.log) == ALL_OFF


def test_activity_row_names_actual_fire_time(monkeypatch):
    r = _room()
    _tick(monkeypatch, r, datetime(2026, 11, 3, 1, 37), occupied=False)
    assert len(r.logger.rows) == 1
    row = r.logger.rows[0]
    assert row["action"] == "shared_space_auto_off"
    assert row["room"] == "Kitchen"
    assert "01:37" in row["description"]
    assert "23:00" not in row["description"]


def test_fans_follow_vacancy_gate_and_fan_mode(monkeypatch):
    """MEDIUM-4: through the new gate, Fan Mode "Off" still spares fans."""
    r = _room(fan_mode=C.FAN_MODE_OFF)
    _tick(monkeypatch, r, datetime(2026, 11, 2, 23, 30), occupied=True)
    assert r.log == []
    _tick(monkeypatch, r, datetime(2026, 11, 2, 23, 31), occupied=False)
    offs = _offs(r.log)
    assert FAN not in offs and OVERHEAD in offs


# ---------------------------------------------------------------------------
# D4 — the T-5 warning flash is removed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("occupied", [True, False])
def test_no_warning_flash_at_2255(monkeypatch, occupied):
    r = _room()
    r.auto.hass.states.get = lambda _e: SimpleNamespace(state="on")
    _tick(monkeypatch, r, datetime(2026, 11, 2, 22, 55), occupied=occupied)
    assert r.log == []
    assert not hasattr(r.auto, "check_auto_off_warning")


# ---------------------------------------------------------------------------
# Window predicate — exact S/C rule with hardcoded literals
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("start,cutoff,when,expected", [
    # S == C: the one-hour window (pre-failsafe behaviour).
    (23, 23, datetime(2026, 11, 2, 22, 59), None),
    (23, 23, datetime(2026, 11, 2, 23, 0), "2026-11-02"),
    (23, 23, datetime(2026, 11, 2, 23, 59), "2026-11-02"),
    (23, 23, datetime(2026, 11, 3, 0, 0), None),
    (1, 1, datetime(2026, 11, 3, 0, 59), None),
    (1, 1, datetime(2026, 11, 3, 1, 0), "2026-11-03"),
    (1, 1, datetime(2026, 11, 3, 2, 0), None),
    # S < C.
    (1, 5, datetime(2026, 11, 3, 0, 59), None),
    (1, 5, datetime(2026, 11, 3, 1, 0), "2026-11-03"),
    (1, 5, datetime(2026, 11, 3, 4, 59), "2026-11-03"),
    (1, 5, datetime(2026, 11, 3, 5, 0), None),
    (0, 5, datetime(2026, 11, 3, 0, 0), "2026-11-03"),
    (0, 5, datetime(2026, 11, 2, 23, 59), None),
    # S > C: wraps midnight; key = date the window opened.
    (23, 5, datetime(2026, 11, 2, 22, 59), None),
    (23, 5, datetime(2026, 11, 2, 23, 0), "2026-11-02"),
    (23, 5, datetime(2026, 11, 3, 0, 0), "2026-11-02"),
    (23, 5, datetime(2026, 11, 3, 4, 59), "2026-11-02"),
    (23, 5, datetime(2026, 11, 3, 5, 0), None),
    (23, 5, datetime(2026, 12, 1, 0, 30), "2026-11-30"),
    (23, 5, datetime(2027, 1, 1, 2, 0), "2026-12-31"),
])
def test_window_predicate_and_night_key(start, cutoff, when, expected):
    assert A.RoomAutomation._auto_off_night_key(when, start, cutoff) == expected


def test_cutoff_equal_start_reproduces_one_hour_rule(monkeypatch):
    r = _room(start=23, cutoff=23)
    _tick(monkeypatch, r, datetime(2026, 11, 3, 0, 30), occupied=False)
    assert r.log == []
    _tick(monkeypatch, r, datetime(2026, 11, 3, 23, 30), occupied=False)
    assert _offs(r.log) == ALL_OFF


def test_cutoff_default_is_five():
    r = _room()
    r.auto.config.pop(C.CONF_SHARED_SPACE_AUTO_OFF_CUTOFF_HOUR)
    assert r.auto.get_auto_off_cutoff_hour() == 5
