"""HVAC Batch D (v5.103.24) — per-room "Fan Mode" ownership, HVAC-tier side.

The incident: Guest Bedroom 2 had comfort fan control OFF and HVAC-managed
fans OFF, yet the HVAC-tier fan controller switched the guest's fan on at
sleep onset (23:43, 03:09) and off on its temp path — it read neither toggle.

Operator ruling (option C): ONE per-room Fan Mode feeds ``const.fan_owner``:

    follow_thermostat -> "hvac"   (HVAC tier: zone setpoint + fan assist)
    room_temperature  -> "room"   (room tier: the room's °F thresholds)
    off               -> None     (person-owned; URA never touches the fan,
                                   including the recheck)

This file drives the REAL ``hvac_fans.FanController`` for three rooms, one
per mode, shaped like the live house:

* Study-A-like  — Follow thermostat
* Jaya-like     — Room temperature (recheck still works through the
                  FanController write registry)
* Guest-2-like  — Off (zero fan writes)

plus the const helpers (mode -> owner, migration mapping, option lists).

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
AUTOMATION = importlib.import_module(f"{_PKG}.automation")
FOLLOW = CONST.FAN_MODE_FOLLOW_THERMOSTAT
ROOMT = CONST.FAN_MODE_ROOM_TEMPERATURE
OFF = CONST.FAN_MODE_OFF

ROOMS = {
    # name: (Fan Mode, fan entity)
    "Study A": (FOLLOW, "fan.study_a"),
    "Jaya Bedroom": (ROOMT, "fan.jaya"),
    "Guest Bedroom 2": (OFF, "fan.guest2"),
}


class _Entry:
    def __init__(self, name, mode, fans, room_type="bedroom"):
        self.entry_id = f"entry_{name}"
        self.data = {
            "entry_type": "room",
            "room_name": name,
            "fans": list(fans),
            "room_type": room_type,
        }
        self.options: dict = {CONST.CONF_ROOM_FAN_MODE: mode}


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
    for name, (mode, fan) in rooms.items():
        entries.append(_Entry(name, mode, [fan]))
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


def _entry_of(entries, name):
    return next(e for e in entries if e.data["room_name"] == name)


def _fan_writes(log, entity):
    return [(d, s) for (d, s, data) in log if data.get("entity_id") == entity]


# ---------------------------------------------------------------------------
# const helpers
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "mode,owner",
    [(FOLLOW, "hvac"), (ROOMT, "room"), (OFF, None), ("bogus", None)],
)
def test_fan_owner_follows_fan_mode(mode, owner):
    assert CONST.fan_owner({CONST.CONF_ROOM_FAN_MODE: mode}) == owner


def test_fan_mode_wins_over_legacy_toggles():
    cfg = {
        CONST.CONF_ROOM_FAN_MODE: OFF,
        "hvac_coordination_enabled": True,
        "fan_control_enabled": True,
    }
    assert CONST.fan_owner(cfg) is None


@pytest.mark.parametrize(
    "hvac,fce,in_zone,mode",
    [
        (True, True, True, FOLLOW),
        (True, False, True, FOLLOW),       # hvac on wins (operator rule)
        (True, True, False, ROOMT),        # not in a zone -> room temperature
        (False, True, True, ROOMT),
        (False, True, False, ROOMT),
        (False, False, True, OFF),
        (None, None, True, OFF),           # missing keys read as off
    ],
)
def test_migration_mapping(hvac, fce, in_zone, mode):
    cfg = {}
    if hvac is not None:
        cfg["hvac_coordination_enabled"] = hvac
    if fce is not None:
        cfg["fan_control_enabled"] = fce
    assert CONST.fan_mode_from_legacy(cfg, in_hvac_zone=in_zone) == mode


def test_unmigrated_room_reads_legacy_toggles():
    """Legacy keys stay readable for one release (no CONF_ROOM_FAN_MODE)."""
    assert CONST.room_fan_mode({"hvac_coordination_enabled": True}) == FOLLOW
    assert CONST.room_fan_mode({"fan_control_enabled": True}) == ROOMT
    assert CONST.room_fan_mode({}) == OFF


def test_fan_mode_options_depend_on_hvac_zone():
    assert CONST.fan_mode_options(True) == [FOLLOW, ROOMT, OFF]
    assert CONST.fan_mode_options(False) == [ROOMT, OFF]


def test_room_in_hvac_zone_needs_a_thermostat_zone():
    zm = MagicMock()
    zm.data = {"entry_type": "zone_manager"}
    zm.options = {"zones": {
        "Upstairs": {"zone_thermostat": "climate.up", "zone_rooms": ["r1"]},
        "Patio": {"zone_rooms": ["r2"]},                  # no thermostat
    }}
    hass = MagicMock()
    hass.config_entries.async_entries = lambda domain: [zm]
    assert CONST.room_in_hvac_zone(hass, "r1") is True
    assert CONST.room_in_hvac_zone(hass, "r2") is False
    assert CONST.room_in_hvac_zone(hass, "r3") is False


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
# G1 — the `_set_fan_state` chokepoint, per mode.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("room,allowed", [
    ("Study A", True), ("Jaya Bedroom", False), ("Guest Bedroom 2", False),
])
def test_chokepoint_hvac_own_write_needs_follow_thermostat(room, allowed):
    fc, _e, _s, log = _world()
    fan = ROOMS[room][1]
    ok = _run(fc._set_fan_state(
        [fan], True, 66, room_name=room,
        trigger_path=CONST.FAN_TRIGGER_TEMP_HVAC,
    ))
    assert ok is allowed
    assert bool(_fan_writes(log, fan)) is allowed


@pytest.mark.parametrize("room,allowed", [
    ("Study A", True), ("Jaya Bedroom", True), ("Guest Bedroom 2", False),
])
def test_chokepoint_recheck_write_follows_owner(room, allowed):
    fc, _e, _s, log = _world()
    fan = ROOMS[room][1]
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
    for room in ("Jaya Bedroom", "Guest Bedroom 2"):
        assert _fan_writes(log, ROOMS[room][1]) == [], room


# ---------------------------------------------------------------------------
# G2 — update() temp path + external sync / adoption.
# ---------------------------------------------------------------------------

def test_update_temp_path_only_for_follow_thermostat():
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


def test_mode_set_to_off_releases_without_forcing_the_fan_off():
    """Fan Mode goes to Off while URA holds the fan ON: URA stops managing
    it and does NOT turn it off; the person later turning it off opens no URA
    cooldown."""
    fc, entries, states, log = _world(fan_on={"Study A": True})
    rf = fc._room_fans["Study A"]
    rf.is_on, rf.trigger, rf.speed_pct = True, "temperature", 66
    _entry_of(entries, "Study A").options = {CONST.CONF_ROOM_FAN_MODE: OFF}
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

def test_sleep_onset_only_for_follow_thermostat():
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
# G4 + recheck pause / restore through the real controller, per mode.
# ---------------------------------------------------------------------------

def test_recheck_room_temperature_pause_and_restore_work():
    """Jaya-like (room tier owns): the HVAC tier never tracked the fan, yet
    the recheck pauses the RUNNING fan and restores it; the HVAC tier's own
    tracking stays untouched, and it makes no temp / sleep-onset writes."""
    fc, _e, states, log = _world(fan_on={"Jaya Bedroom": True})
    snap = _run(fc.pause_for_recheck("Jaya Bedroom", "2099-01-01T00:00:00+00:00"))
    assert snap is not None and snap["is_on"] is True
    assert _fan_writes(log, "fan.jaya") == [("fan", "turn_off")]
    states["fan.jaya"] = _State("off")
    _run(fc.restore_after_recheck("Jaya Bedroom", snap))
    assert _fan_writes(log, "fan.jaya")[-1] == ("fan", "turn_on")
    assert fc._room_fans["Jaya Bedroom"].is_on is False
    n = len(_fan_writes(log, "fan.jaya"))
    fc._room_fans["Jaya Bedroom"].fan_recheck_suppress_until = ""
    _run(fc.update(None, "home_day"))
    _run(fc._sleep_onset_activation(HF.dt_util.now()))
    assert len(_fan_writes(log, "fan.jaya")) == n


def test_recheck_follow_thermostat_unchanged():
    fc, _e, states, log = _world(fan_on={"Study A": True})
    rf = fc._room_fans["Study A"]
    rf.is_on, rf.speed_pct, rf.trigger = True, 66, "temperature"
    snap = _run(fc.pause_for_recheck("Study A", "2099-01-01T00:00:00+00:00"))
    assert snap["is_on"] is True and snap["speed_pct"] == 66
    states["fan.study_a"] = _State("off")
    _run(fc.restore_after_recheck("Study A", snap))
    assert _fan_writes(log, "fan.study_a") == [("fan", "turn_off"), ("fan", "turn_on")]
    assert rf.is_on is True


def test_recheck_off_zero_writes():
    fc, _e, _s, log = _world(fan_on={"Guest Bedroom 2": True})
    snap = _run(fc.pause_for_recheck("Guest Bedroom 2", "2099-01-01T00:00:00+00:00"))
    _run(fc.restore_after_recheck("Guest Bedroom 2", snap))
    _run(fc.update(None, "home_day"))
    _run(fc._sleep_onset_activation(HF.dt_util.now()))
    _run(fc.turn_off_all_managed())
    assert _fan_writes(log, "fan.guest2") == []


def test_restore_skipped_when_mode_set_to_off_mid_recheck():
    """G4: Fan Mode set to Off during the recheck -> restore NOTHING,
    including the attribute writes that bypass the chokepoint."""
    fc, entries, states, log = _world(fan_on={"Study A": True})
    states["fan.study_a"] = _State("on", {"percentage": 66, "preset_mode": "breeze"})
    rf = fc._room_fans["Study A"]
    rf.is_on, rf.speed_pct = True, 66
    snap = _run(fc.pause_for_recheck("Study A", "2099-01-01T00:00:00+00:00"))
    _entry_of(entries, "Study A").options = {CONST.CONF_ROOM_FAN_MODE: OFF}
    n_before = len(log)
    _run(fc.restore_after_recheck("Study A", snap))
    assert log[n_before:] == []


# ---------------------------------------------------------------------------
# Fix-up 1 — B-M1: the room tier across a recheck pause + restore
# ---------------------------------------------------------------------------

def _room_tier_for(fc, entries, name, fan):
    """A REAL RoomAutomation for `name`, registered where the FanController's
    handshake finds it (hass.data[DOMAIN][entry_id].automation)."""
    hass = fc.hass
    entry = _entry_of(entries, name)
    coord = MagicMock()
    coord.entry = entry
    config = {
        **entry.data, **entry.options,
        "fans": [fan], "fan_temp_threshold": 80,
        "sleep_protection_enabled": False,
    }
    auto = AUTOMATION.RoomAutomation(hass=hass, config=config, coordinator=coord)
    auto.is_sleep_mode_active = lambda: False
    auto._refresh_config = lambda: None
    room_log: list = []

    async def _svc(domain, service, data=None, **kw):
        room_log.append((domain, service, dict(data or {})))

    auto._safe_service_call = _svc
    coord.automation = auto
    hass.data = {CONST.DOMAIN: {entry.entry_id: coord}}
    return auto, room_log


def test_room_tier_does_not_book_the_recheck_as_a_person():
    """Jaya-like ("Room temperature"): the room tier owns the running fan.
    The presence recheck pauses it (OFF) and restores it (ON) through the
    FanController. The room tier must open NO 1 h off-cooldown and NO
    manual-ON hold, and must not re-drive the fan mid-pause."""
    fc, entries, states, log = _world(fan_on={"Jaya Bedroom": True})
    auto, room_log = _room_tier_for(fc, entries, "Jaya Bedroom", "fan.jaya")
    # The room tier already owns the running fan (URA-lit — the boot-edge
    # "fan seen on at tick 1" hold is covered by its own tests).
    auto._last_seen_any_fan_on = True
    _run(auto.handle_temperature_based_fan_control(85.0, True))   # baseline: on
    assert auto._last_seen_any_fan_on is True
    assert auto._fan_manual_on_until is None
    assert auto._fan_manual_off_until is None
    n_room = len(room_log)

    snap = _run(fc.pause_for_recheck("Jaya Bedroom", "2099-01-01T00:00:00+00:00"))
    states["fan.jaya"] = _State("off")
    _run(auto.handle_temperature_based_fan_control(85.0, True))   # mid-pause
    assert auto._fan_manual_off_until is None
    assert len(room_log) == n_room          # no room-tier write mid-pause

    _run(fc.restore_after_recheck("Jaya Bedroom", snap))
    states["fan.jaya"] = _State("on", {"percentage": 33})
    _run(auto.handle_temperature_based_fan_control(85.0, True))   # after restore
    assert auto._fan_manual_off_until is None
    assert auto._fan_manual_on_until is None
    assert auto._recheck_pause_until is None


def test_room_tier_pause_window_has_a_backstop():
    """The pause window discharges by itself at the recheck's suppress-until
    (a lost restore cannot freeze the room tier)."""
    fc, entries, states, log = _world(fan_on={"Jaya Bedroom": True})
    auto, _room_log = _room_tier_for(fc, entries, "Jaya Bedroom", "fan.jaya")
    _run(fc.pause_for_recheck("Jaya Bedroom", "2000-01-01T00:00:00+00:00"))
    assert auto._recheck_pause_until is not None
    _run(auto.handle_temperature_based_fan_control(85.0, True))
    assert auto._recheck_pause_until is None
    assert auto.is_recheck_paused() is False


# ---------------------------------------------------------------------------
# Fix-up 1 — B-M3: the HVAC Fan Control kill keeps room-tier holds
# ---------------------------------------------------------------------------

def test_hvac_kill_keeps_holds_of_rooms_it_does_not_own():
    fc, _e, _s, _log = _world()
    future = "2099-01-01T00:00:00+00:00"
    for name in ROOMS:
        rf = fc._room_fans[name]
        rf.manual_off_cooldown_until = future
        rf.manual_on_hold_until = future
    _run(fc.turn_off_all_managed())
    assert fc._room_fans["Study A"].manual_off_cooldown_until == ""
    assert fc._room_fans["Study A"].manual_on_hold_until == ""
    for name in ("Jaya Bedroom", "Guest Bedroom 2"):
        assert fc._room_fans[name].manual_off_cooldown_until == future, name
        assert fc._room_fans[name].manual_on_hold_until == future, name


# ---------------------------------------------------------------------------
# Fix-up 1 — A9: recheck speed from the first ON entity
# ---------------------------------------------------------------------------

def test_recheck_snapshot_speed_is_the_first_on_entity():
    rooms = {"Jaya Bedroom": (ROOMT, "fan.jaya_a")}
    fc, entries, states, log = _world(rooms=rooms)
    fc._room_fans["Jaya Bedroom"].fan_entities = ["fan.jaya_a", "fan.jaya_b"]
    states["fan.jaya_a"] = _State("off", {"percentage": 20})
    states["fan.jaya_b"] = _State("on", {"percentage": 66})
    snap = fc.snapshot_room_fan("Jaya Bedroom")
    assert snap["is_on"] is True and snap["speed_pct"] == 66
