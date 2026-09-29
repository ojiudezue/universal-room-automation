"""HVAC Batch D (v5.103.24) — room comfort-fan OWNERSHIP, HVAC-tier FanController.

The incident: Guest Bedroom 2 had "Comfort Fan Control" OFF and "Enable
HVAC-Managed Fans" OFF, yet the HVAC-tier fan controller switched the guest's
fan on at sleep onset (23:43, 03:09) and off on its temp path — it never read
either toggle.

The rule (``const.fan_owner``, ONE helper for every fan writer):

    hvac_coordination | fan_control | owner
    on                | on          | "hvac"
    on                | off         | None  (person-owned)
    off               | on          | "room"
    off               | off         | None  (person-owned)

This file drives the REAL ``hvac_fans.FanController`` for three rooms shaped
like the live house (2026-09-29 ``.storage``):

* Study-A-like   — hvac on  / comfort on  -> "hvac"
* Jaya-like      — hvac off / comfort on  -> "room" (recheck still works)
* Guest-2-like   — hvac off / comfort off -> None   (zero fan writes)

plus the seam row (hvac on / comfort off -> None).

Loader: the REAL sources are loaded under a PRIVATE package name so the file
behaves the same standalone (``suite_namediff --isolate``) and in suite
order, whatever stubs earlier test files left under ``custom_components``.
"""

from __future__ import annotations

import asyncio
import importlib
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

_URA_ROOT = (
    Path(__file__).resolve().parents[2]
    / "custom_components" / "universal_room_automation"
)
_PKG = "ura_batch_d_fans_pkg"


def _load():
    if f"{_PKG}.domain_coordinators.hvac_fans" in sys.modules:
        return (
            sys.modules[f"{_PKG}.const"],
            sys.modules[f"{_PKG}.domain_coordinators.hvac_fans"],
        )
    pkg = types.ModuleType(_PKG)
    pkg.__path__ = [str(_URA_ROOT)]
    sys.modules[_PKG] = pkg
    dc = types.ModuleType(f"{_PKG}.domain_coordinators")
    dc.__path__ = [str(_URA_ROOT / "domain_coordinators")]
    sys.modules[f"{_PKG}.domain_coordinators"] = dc
    const = importlib.import_module(f"{_PKG}.const")
    hf = importlib.import_module(f"{_PKG}.domain_coordinators.hvac_fans")
    return const, hf


CONST, HF = _load()
fan_owner = CONST.fan_owner

ROOMS = {
    # name: (hvac_coordination_enabled, fan_control_enabled, fan entity)
    "Study A": (True, True, "fan.study_a"),
    "Jaya Bedroom": (False, True, "fan.jaya"),
    "Guest Bedroom 2": (False, False, "fan.guest2"),
    "Seam Room": (True, False, "fan.seam"),
}


class _Entry:
    def __init__(self, name, hvac, fce, fans, room_type="bedroom"):
        self.entry_id = f"entry_{name}"
        self.data = {
            "entry_type": "room",
            "room_name": name,
            "fans": list(fans),
            "room_type": room_type,
            "hvac_coordination_enabled": hvac,
            "fan_control_enabled": fce,
        }
        self.options: dict = {}


class _State:
    def __init__(self, state, attrs=None):
        self.state = state
        self.attributes = dict(attrs or {})


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _world(fan_on: dict | None = None, rooms=ROOMS):
    """A real FanController over `rooms`, every room in zone z1, hot and
    occupied. Returns (fc, entries, states, log)."""
    fan_on = fan_on or {}
    hass = MagicMock()
    hass.data = {}
    states: dict = {}
    entries = []
    for name, (hvac, fce, fan) in rooms.items():
        entries.append(_Entry(name, hvac, fce, [fan]))
        states[fan] = _State(
            "on" if fan_on.get(name) else "off", {"percentage": 33},
        )
    hass.states.get = lambda eid: states.get(eid)
    hass.config_entries.async_entries = lambda domain: list(entries)
    log: list = []

    async def _svc(domain, service, data=None, blocking=False, **kw):
        log.append((domain, service, dict(data or {})))

    hass.services.async_call = _svc
    hass.async_create_task = lambda c: c.close() if hasattr(c, "close") else None

    zone = MagicMock()
    zone.rooms = list(rooms)
    zone.target_temp_high = 74.0
    conds = []
    for name in rooms:
        rc = MagicMock()
        rc.room_name = name
        rc.temperature = 82.0
        rc.occupied = True
        conds.append(rc)
    zone.room_conditions = conds
    zm = MagicMock()
    zm.zones = {"z1": zone}

    fc = HF.FanController(hass=hass, zone_manager=zm)
    fc.discover_fans()
    return fc, entries, states, log


def _fan_writes(log, entity):
    return [(d, s) for (d, s, data) in log if data.get("entity_id") == entity]


# ---------------------------------------------------------------------------
# The shared helper — one assertion per table row (+ missing keys).
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "hvac,fce,owner",
    [
        (True, True, "hvac"),
        (True, False, None),     # the seam row: person-owned
        (False, True, "room"),
        (False, False, None),
    ],
)
def test_fan_owner_table(hvac, fce, owner):
    cfg = {"hvac_coordination_enabled": hvac, "fan_control_enabled": fce}
    assert fan_owner(cfg) == owner


def test_fan_owner_missing_keys_are_off():
    assert fan_owner({}) is None
    assert fan_owner(None) is None
    assert fan_owner({"fan_control_enabled": True}) == "room"
    assert fan_owner({"hvac_coordination_enabled": True}) is None


# ---------------------------------------------------------------------------
# G0 — discovery keeps EVERY zone fan room registered (the recheck's write
# registry) and snapshots whether the HVAC tier manages it.
# ---------------------------------------------------------------------------

def test_discovery_registers_all_rooms_and_marks_hvac_managed():
    fc, *_ = _world()
    assert set(fc._room_fans) == set(ROOMS)
    managed = {n for n, rf in fc._room_fans.items() if rf.hvac_managed}
    assert managed == {"Study A"}


# ---------------------------------------------------------------------------
# G1 — the `_set_fan_state` chokepoint.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("room,allowed", [
    ("Study A", True), ("Jaya Bedroom", False),
    ("Guest Bedroom 2", False), ("Seam Room", False),
])
def test_chokepoint_hvac_own_write_needs_hvac_owner(room, allowed):
    fc, _e, _s, log = _world()
    fan = ROOMS[room][2]
    ok = _run(fc._set_fan_state(
        [fan], True, 66, room_name=room,
        trigger_path=CONST.FAN_TRIGGER_TEMP_HVAC,
    ))
    assert ok is allowed
    assert bool(_fan_writes(log, fan)) is allowed


@pytest.mark.parametrize("room,allowed", [
    ("Study A", True), ("Jaya Bedroom", True),
    ("Guest Bedroom 2", False), ("Seam Room", False),
])
def test_chokepoint_recheck_write_follows_owner(room, allowed):
    fc, _e, _s, log = _world()
    fan = ROOMS[room][2]
    ok = _run(fc._set_fan_state(
        [fan], True, 66, room_name=room,
        trigger_path=CONST.FAN_TRIGGER_RECHECK_RESTORE,
    ))
    assert ok is allowed
    assert bool(_fan_writes(log, fan)) is allowed


def test_turn_off_all_managed_leaves_unmanaged_fans_on():
    """HVAC-level fan-control OFF sweeps only fans the HVAC tier owns."""
    on = {n: True for n in ROOMS}
    fc, _e, _s, log = _world(fan_on=on)
    for rf in fc._room_fans.values():
        rf.is_on = True
    _run(fc.turn_off_all_managed())
    assert _fan_writes(log, "fan.study_a") == [("fan", "turn_off")]
    for room in ("Jaya Bedroom", "Guest Bedroom 2", "Seam Room"):
        assert _fan_writes(log, ROOMS[room][2]) == [], room


# ---------------------------------------------------------------------------
# G2 — update() temp path + external sync / adoption.
# ---------------------------------------------------------------------------

def test_update_temp_path_only_for_hvac_owner():
    fc, *_ = _world()
    fc._set_fan_state = AsyncMock(return_value=True)
    _run(fc.update(None, "home_day"))
    rooms_called = {c.kwargs["room_name"] for c in fc._set_fan_state.await_args_list}
    assert rooms_called == {"Study A"}


def test_update_does_not_adopt_person_owned_running_fan():
    """Guest-2-like: the guest's fan is on. The HVAC tier neither adopts it
    (no manual-ON hold, no tracked `is_on`) nor writes to it."""
    fc, _e, _s, log = _world(fan_on={"Guest Bedroom 2": True})
    _run(fc.update(None, "home_day"))
    rf = fc._room_fans["Guest Bedroom 2"]
    assert rf.is_on is False and rf.trigger == ""
    assert rf.manual_on_hold_until == ""
    assert _fan_writes(log, "fan.guest2") == []


def test_switch_off_releases_without_forcing_the_fan_off():
    """Comfort Fan Control goes OFF while URA holds the fan ON: URA stops
    managing it and does NOT turn it off; the person later turning it off
    opens no URA cooldown."""
    fc, entries, states, log = _world(fan_on={"Study A": True})
    rf = fc._room_fans["Study A"]
    rf.is_on, rf.trigger, rf.speed_pct = True, "temperature", 66
    study = next(e for e in entries if e.data["room_name"] == "Study A")
    study.options = {"fan_control_enabled": False}
    _run(fc.update(None, "home_day"))
    assert _fan_writes(log, "fan.study_a") == []
    assert rf.is_on is False and rf.hvac_managed is False
    states["fan.study_a"] = _State("off")
    _run(fc.update(None, "home_day"))
    assert rf.manual_off_cooldown_until == ""
    assert _fan_writes(log, "fan.study_a") == []


# ---------------------------------------------------------------------------
# G3 — sleep-onset burst.
# ---------------------------------------------------------------------------

def test_sleep_onset_only_for_hvac_owner():
    fc, *_ = _world()
    fc._set_fan_state = AsyncMock(return_value=True)
    _run(fc._sleep_onset_activation(HF.dt_util.now()))
    rooms_called = {c.kwargs["room_name"] for c in fc._set_fan_state.await_args_list}
    assert rooms_called == {"Study A"}


def test_sleep_onset_suppressed_on_is_not_booked():
    """A chokepoint-suppressed ON sent nothing: the fan must not be booked on
    (`dispatched` honoured)."""
    fc, *_ = _world()
    fc._set_fan_state = AsyncMock(return_value=False)
    _run(fc._sleep_onset_activation(HF.dt_util.now()))
    assert fc._room_fans["Study A"].is_on is False


# ---------------------------------------------------------------------------
# G4 + recheck pause / restore through the real controller, per row.
# ---------------------------------------------------------------------------

def test_recheck_jaya_like_pause_and_restore_work():
    """Room-tier-owned fan: the HVAC tier never tracked it, yet the recheck
    pauses the RUNNING fan and restores it; tracking stays untouched."""
    fc, _e, states, log = _world(fan_on={"Jaya Bedroom": True})
    snap = _run(fc.pause_for_recheck("Jaya Bedroom", "2099-01-01T00:00:00+00:00"))
    assert snap is not None and snap["is_on"] is True
    assert _fan_writes(log, "fan.jaya") == [("fan", "turn_off")]
    states["fan.jaya"] = _State("off")
    _run(fc.restore_after_recheck("Jaya Bedroom", snap))
    assert _fan_writes(log, "fan.jaya")[-1] == ("fan", "turn_on")
    assert fc._room_fans["Jaya Bedroom"].is_on is False


def test_recheck_study_a_like_unchanged():
    fc, _e, states, log = _world(fan_on={"Study A": True})
    rf = fc._room_fans["Study A"]
    rf.is_on, rf.speed_pct, rf.trigger = True, 66, "temperature"
    snap = _run(fc.pause_for_recheck("Study A", "2099-01-01T00:00:00+00:00"))
    assert snap["is_on"] is True and snap["speed_pct"] == 66
    states["fan.study_a"] = _State("off")
    _run(fc.restore_after_recheck("Study A", snap))
    assert _fan_writes(log, "fan.study_a") == [("fan", "turn_off"), ("fan", "turn_on")]
    assert rf.is_on is True


def test_recheck_guest2_like_zero_writes():
    fc, _e, _s, log = _world(fan_on={"Guest Bedroom 2": True})
    snap = _run(fc.pause_for_recheck("Guest Bedroom 2", "2099-01-01T00:00:00+00:00"))
    _run(fc.restore_after_recheck("Guest Bedroom 2", snap))
    assert _fan_writes(log, "fan.guest2") == []


def test_restore_skipped_when_fan_becomes_person_owned_mid_recheck():
    """G4: Comfort Fan Control OFF during the recheck -> restore NOTHING,
    including the attribute writes that bypass the chokepoint."""
    fc, entries, states, log = _world(fan_on={"Study A": True})
    states["fan.study_a"] = _State("on", {"percentage": 66, "preset_mode": "breeze"})
    rf = fc._room_fans["Study A"]
    rf.is_on, rf.speed_pct = True, 66
    snap = _run(fc.pause_for_recheck("Study A", "2099-01-01T00:00:00+00:00"))
    study = next(e for e in entries if e.data["room_name"] == "Study A")
    study.options = {"fan_control_enabled": False}
    n_before = len(log)
    _run(fc.restore_after_recheck("Study A", snap))
    assert log[n_before:] == []
