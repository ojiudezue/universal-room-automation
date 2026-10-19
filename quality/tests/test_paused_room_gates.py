"""ROOM-OVERRIDE-SWITCH-FORGOTTEN-1 — paused rooms stop occupancy-driven
lights and fans in the HVAC tier and the fan recheck.

Plan: ``docs/planning/PLANNING_paused_room_occupancy_lights_fans.md``.
Operator 2026-10-18: "Paused rooms should stop with lights and fans
automation based on occupancy ... I just didn't want it turning off lights
when paused."

"Paused" = the room coordinator's REAL ``_is_automation_enabled`` returns
False (Automation switch off, or Manual Mode on). Every fake room coordinator
below carries the production method itself (bound from
``UniversalRoomCoordinator``) over a switch-state table, so a per-site
mutation of any ``room_automation_paused`` call is observable.

Loader: the REAL sources are loaded under a PRIVATE package name (same
pattern as ``test_hvac_batch_d_fan_ownership.py``) so the file behaves the
same standalone and in suite order, whatever stubs earlier test files left
under ``custom_components``.

Recheck tests (F2) reuse the ``test_fan_recheck_mode2_cycle`` world (same as
``test_fan_recheck_d2_deadlock``). The D2-backstop pin lives in
``test_mmwave_fan_demotion.py`` next to its D2-block harness.
"""

from __future__ import annotations

import asyncio
import importlib
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

_URA_ROOT = (
    Path(__file__).resolve().parents[2]
    / "custom_components" / "universal_room_automation"
)
_PKG = "ura_paused_gates_pkg"


def _load():
    if _PKG not in sys.modules:
        pkg = types.ModuleType(_PKG)
        pkg.__path__ = [str(_URA_ROOT)]
        sys.modules[_PKG] = pkg
        dc = types.ModuleType(f"{_PKG}.domain_coordinators")
        dc.__path__ = [str(_URA_ROOT / "domain_coordinators")]
        sys.modules[f"{_PKG}.domain_coordinators"] = dc
    names = (
        "const", "coordinator",
        "domain_coordinators.hvac_zones", "domain_coordinators.hvac_fans",
        "domain_coordinators.hvac_predict", "domain_coordinators.hvac",
    )
    return [importlib.import_module(f"{_PKG}.{n}") for n in names]


CONST, COORD, HZ, HF, HP, HVAC = _load()
DOMAIN = CONST.DOMAIN
FOLLOW = CONST.FAN_MODE_FOLLOW_THERMOSTAT

from runtime_harness import StubHass  # noqa: E402


@pytest.fixture(autouse=True)
def _aware_clock(monkeypatch):
    """Pin a tz-aware clock on the dt_util objects these private modules
    read (a sibling file may have left a naive stub in place)."""
    seen = []
    for mod in (HF, HP, HVAC, HZ, COORD):
        d = getattr(mod, "dt_util", None)
        if d is None or any(d is s for s in seen):
            continue
        seen.append(d)
        monkeypatch.setattr(d, "now", lambda: datetime.now(timezone.utc), raising=False)
        monkeypatch.setattr(d, "utcnow", lambda: datetime.now(timezone.utc), raising=False)


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class _Entry:
    def __init__(self, name, *, fans=(), lights=(), mode=FOLLOW,
                 room_type="generic"):
        self.entry_id = f"entry_{name}"
        self.data = {
            CONST.CONF_ENTRY_TYPE: CONST.ENTRY_TYPE_ROOM,
            CONST.CONF_ROOM_NAME: name,
            CONST.CONF_FANS: list(fans),
            CONST.CONF_LIGHTS: list(lights),
            CONST.CONF_ROOM_TYPE: room_type,
        }
        self.options = {CONST.CONF_ROOM_FAN_MODE: mode}


class _RoomCoord:
    """Minimal room coordinator: the PRODUCTION ``_is_automation_enabled``
    over a switch-state table (None = switch not found)."""

    _is_automation_enabled = COORD.UniversalRoomCoordinator._is_automation_enabled

    def __init__(self, entry, *, automation=True, manual=False):
        self.entry = entry
        self.config_entry = entry
        self.switches = {"automation": automation, "manual_mode": manual}
        self.automation = None
        self.data = {"occupied": False}

    def _get_room_switch_state(self, suffix):
        return self.switches.get(suffix)

    def pause(self):
        self.switches["automation"] = False

    def unpause(self):
        self.switches["automation"] = True


class _MetaEntry:
    def __init__(self, eid, entry_type, options=None):
        self.entry_id = eid
        self.data = {CONST.CONF_ENTRY_TYPE: entry_type}
        self.options = options or {}


def _calls(hass, service, entity=None):
    return [
        c for c in hass.services.calls
        if c[1] == service and (entity is None or c[2].get("entity_id") == entity)
    ]


def _hvac_world(rooms, *, fan_state="on", light_state="on"):
    """Real HVACCoordinator over ONE zone (zone_1) holding ``rooms``.

    ``rooms`` = {name: {"automation": bool, "manual": bool}}. Each room has
    one light ``light.<n>`` and one HVAC-owned fan ``fan.<n>``.
    Returns (coord, hass, zone, room_coords).
    """
    hass = StubHass()
    entries = [
        _MetaEntry("cm", CONST.ENTRY_TYPE_COORDINATOR_MANAGER),
        _MetaEntry("zm", CONST.ENTRY_TYPE_ZONE_MANAGER, {"zones": {}}),
    ]
    rcs = {}
    hass.data[DOMAIN] = {}
    for name, sw in rooms.items():
        n = name.lower()
        e = _Entry(name, fans=[f"fan.{n}"], lights=[f"light.{n}"])
        entries.append(e)
        rc = _RoomCoord(e, automation=sw.get("automation", True),
                        manual=sw.get("manual", False))
        rcs[name] = rc
        hass.data[DOMAIN][e.entry_id] = rc
        hass.states.async_set(f"fan.{n}", fan_state, {"percentage": 33})
        hass.states.async_set(f"light.{n}", light_state)
    hass.config_entries._entries = entries
    coord = HVAC.HVACCoordinator(hass)
    zone = HZ.ZoneState(
        zone_id="zone_1", zone_name="Z1",
        climate_entity="climate.z1", rooms=list(rooms),
    )
    coord.zone_manager._zones["zone_1"] = zone
    coord._fan_controller.discover_fans()
    return coord, hass, zone, rcs


# ---------------------------------------------------------------------------
# D1 — predicate
# ---------------------------------------------------------------------------

def test_predicate_truth_table():
    pred = CONST.room_automation_paused
    e = _Entry("A")
    assert pred(None) is False                                     # no coord
    assert pred(object()) is False                                 # no method
    assert pred(_RoomCoord(e, automation=False)) is True           # switch off
    assert pred(_RoomCoord(e, automation=True, manual=True)) is True  # manual on
    assert pred(_RoomCoord(e, automation=False, manual=True)) is True  # both
    assert pred(_RoomCoord(e, automation=True)) is False           # enabled
    assert pred(_RoomCoord(e, automation=None)) is False           # switch missing

    class _Raises:
        def _is_automation_enabled(self):
            raise RuntimeError("boom")
    assert pred(_Raises()) is False                                # raises

    class _NotBool:
        def _is_automation_enabled(self):
            return 0                                               # falsy, not False
    assert pred(_NotBool()) is False


# ---------------------------------------------------------------------------
# D2 — L1 zone vacancy sweep
# ---------------------------------------------------------------------------

def test_sweep_skips_paused_room_lights_and_fans():
    coord, hass, zone, _rcs = _hvac_world({
        "A": {"automation": False}, "B": {"automation": True},
    })
    _run(coord._execute_vacancy_sweep(zone))
    assert _calls(hass, "turn_off", "light.a") == []
    assert _calls(hass, "turn_off", "fan.a") == []
    assert len(_calls(hass, "turn_off", "light.b")) == 1
    assert len(_calls(hass, "turn_off", "fan.b")) == 1


def test_sweep_manual_mode_counts_as_paused():
    coord, hass, zone, _rcs = _hvac_world({
        "A": {"automation": True, "manual": True}, "B": {},
    })
    _run(coord._execute_vacancy_sweep(zone))
    assert _calls(hass, "turn_off", "light.a") == []
    assert _calls(hass, "turn_off", "fan.a") == []
    assert len(_calls(hass, "turn_off", "light.b")) == 1


def _prep_tick(coord, hass, zone):
    """A home_day zone; a readable heat_cool thermostat on home."""
    coord._house_state = "home_day"
    coord._defer_gate_enabled = False
    hass.states.async_set(
        "climate.z1", "heat_cool",
        {"preset_mode": "home", "preset_modes": ["home", "away", "sleep"],
         "target_temp_high": 76, "target_temp_low": 70},
    )
    zone.hvac_mode = "heat_cool"
    zone.preset_mode = "home"
    zone.vacancy_sweep_enabled = True
    zone.vacancy_sweep_done = False


def test_sweep_paused_room_d6_branch():
    """D6 stale-occupancy caller (`hvac.py` D6 block): HVAC-fused occupied
    for > max hours, lighting-empty, no corroboration -> the sweep runs and
    must still skip the paused room."""
    coord, hass, zone, _rcs = _hvac_world({
        "A": {"automation": False}, "B": {},
    })
    _prep_tick(coord, hass, zone)
    now = datetime.now(timezone.utc)
    # HVAC-fused occupied (a stuck sensor), lighting-empty.
    zone.room_conditions = [
        HZ.RoomCondition(room_name=n, occupied=False, hvac_occupied=True)
        for n in ("A", "B")
    ]
    zone.continuous_occupied_since = now - timedelta(hours=48)
    zone.last_occupied_time = now
    _run(coord._apply_house_state_presets())
    assert zone.vacancy_sweep_done is True          # the D6 caller swept
    assert len(_calls(hass, "turn_off", "light.b")) == 1
    assert _calls(hass, "turn_off", "light.a") == []
    assert _calls(hass, "turn_off", "fan.a") == []


def _row1_tick(paused: bool):
    coord, hass, zone, _rcs = _hvac_world({
        "A": {"automation": not paused}, "B": {},
    })
    _prep_tick(coord, hass, zone)
    coord._zone_conditioning_retreat_ok = lambda _z: True
    zone.room_conditions = [
        HZ.RoomCondition(room_name=n, occupied=False, hvac_occupied=False)
        for n in ("A", "B")
    ]
    zone.last_occupied_time = datetime.now(timezone.utc) - timedelta(hours=2)
    _run(coord._apply_house_state_presets())
    presets = [
        (c[2].get("entity_id"), c[2].get("preset_mode"))
        for c in hass.services.calls if c[1] == "set_preset_mode"
    ]
    offs = {c[2].get("entity_id") for c in _calls(hass, "turn_off")}
    return presets, zone.vacancy_sweep_done, coord._vacancy_sweeps_today.value, offs


def test_zone_retreat_unchanged_with_paused_room():
    """INV-Z (occupancy held fixed): pausing A changes ONLY the turn_off set."""
    p_presets, p_done, p_count, p_offs = _row1_tick(paused=True)
    e_presets, e_done, e_count, e_offs = _row1_tick(paused=False)
    assert ("climate.z1", "away") in e_presets      # the row-1 retreat happened
    assert p_presets == e_presets
    assert (p_done, p_count) == (e_done, e_count) == (True, 1)
    assert e_offs - p_offs == {"light.a", "fan.a"}
    assert p_offs == {"light.b", "fan.b"}


# ---------------------------------------------------------------------------
# D3 — F1 HVAC comfort fans (FanController.update)
# ---------------------------------------------------------------------------

def _fan_world(rooms, *, fan_on=None, temp=82.0, occupied=True):
    """Real FanController over ``rooms`` (all Follow thermostat) in zone z1.
    Returns (fc, hass, states, room_coords)."""
    hass = StubHass()
    hass.data[DOMAIN] = {}
    entries = []
    rcs = {}
    fan_on = fan_on or {}
    for name, sw in rooms.items():
        n = name.lower()
        e = _Entry(name, fans=[f"fan.{n}"], room_type=sw.get("room_type", "generic"))
        entries.append(e)
        rc = _RoomCoord(e, automation=sw.get("automation", True),
                        manual=sw.get("manual", False))
        rcs[name] = rc
        hass.data[DOMAIN][e.entry_id] = rc
        hass.states.async_set(
            f"fan.{n}", "on" if fan_on.get(name) else "off", {"percentage": 33},
        )
    hass.config_entries._entries = entries

    class _Zone:
        pass
    zone = _Zone()
    zone.rooms = list(rooms)
    zone.target_temp_high = 74.0
    conds = []
    for name in rooms:
        rc = types.SimpleNamespace(
            room_name=name, temperature=temp, occupied=occupied,
        )
        conds.append(rc)
    zone.room_conditions = conds

    class _ZM:
        zones = {"z1": zone}
    fc = HF.FanController(hass=hass, zone_manager=_ZM())
    fc.discover_fans()
    return fc, hass, hass.states, rcs


def test_fan_controller_skips_paused_room():
    fc, hass, _s, _rcs = _fan_world({"A": {"automation": False}, "B": {}})
    _run(fc.update(None, "home_day"))
    assert _calls(hass, "turn_on", "fan.a") == []
    assert _calls(hass, "turn_off", "fan.a") == []
    assert len(_calls(hass, "turn_on", "fan.b")) == 1   # enabled twin runs


def test_fan_controller_paused_release_level_no_write():
    """R4: the paused release is LEVEL (every paused tick)."""
    fc, hass, states, rcs = _fan_world({"A": {}}, fan_on={"A": True})
    rf = fc._room_fans["A"]
    rf.is_on = True
    rf.trigger = "temperature"
    rf.speed_pct = 33
    rf.last_on_time = datetime.now(timezone.utc).isoformat()
    # A recheck snapshots the tracked-ON fan before the operator pauses.
    snap = fc.snapshot_room_fan("A")
    assert snap["is_on"] is True

    rcs["A"].pause()
    _run(fc.update(None, "home_day"))
    assert (rf.is_on, rf.trigger, rf.speed_pct, rf.last_on_time) == (False, "", 0, "")
    assert hass.services.calls == []                      # release writes nothing

    # Whitelisted mid-flight recheck restore re-sets is_on=True.
    _run(fc.restore_after_recheck("A", snap))
    assert rf.is_on is True
    _run(fc.update(None, "home_day"))                     # next paused tick
    assert rf.is_on is False and rf.trigger == ""

    # A person turns the fan OFF, then the room is unpaused.
    states.async_set("fan.a", "off", {"percentage": 0})
    rcs["A"].unpause()
    _run(fc.update(None, "home_day"))
    assert rf.manual_off_cooldown_until in ("", None)     # no fake 1 h cooldown


def test_release_helper_single_copy(monkeypatch):
    """Fan-Mode hand-back and the paused release both go through
    ``_release_room_tracking`` and leave identical tracking state."""
    fc, hass, states, rcs = _fan_world(
        {"A": {}, "B": {}}, fan_on={"A": True, "B": True},
    )
    seen = []
    real = HF.FanController._release_room_tracking

    def _spy(room_name, room_fan, *, reason):
        seen.append((room_name, reason))
        return real(room_name, room_fan, reason=reason)
    monkeypatch.setattr(fc, "_release_room_tracking", _spy)
    for n in ("A", "B"):
        rf = fc._room_fans[n]
        rf.is_on, rf.trigger, rf.speed_pct = True, "temperature", 33
        rf.last_on_time = "2026-10-19T00:00:00+00:00"
        rf.vacancy_detected_time = "2026-10-19T00:00:00+00:00"
    # A: Fan Mode leaves Follow thermostat; B: paused.
    next(e for e in hass.config_entries._entries
         if e.data[CONST.CONF_ROOM_NAME] == "A").options = {
        CONST.CONF_ROOM_FAN_MODE: CONST.FAN_MODE_OFF,
    }
    rcs["B"].pause()
    _run(fc.update(None, "home_day"))
    assert ("A", "fan_mode") in seen and ("B", "room_paused") in seen

    def _track(rf):
        return (rf.is_on, rf.trigger, rf.speed_pct, rf.last_on_time,
                rf.vacancy_detected_time)
    assert _track(fc._room_fans["A"]) == _track(fc._room_fans["B"]) == (
        False, "", 0, "", "",
    )
    assert hass.services.calls == []


# ---------------------------------------------------------------------------
# D4 — F3 sleep-onset fan ON
# ---------------------------------------------------------------------------

def test_sleep_onset_skips_paused_room(monkeypatch):
    monkeypatch.setattr(HF, "SLEEP_FAN_ON_STAGGER_S", 0)
    fc, hass, _s, _rcs = _fan_world({
        "A": {"automation": False, "room_type": "bedroom"},
        "B": {"room_type": "bedroom"},
    }, temp=80.0)
    _run(fc._sleep_onset_activation(datetime.now(timezone.utc)))
    assert _calls(hass, "turn_on", "fan.a") == []
    assert len(_calls(hass, "turn_on", "fan.b")) == 1
    assert fc._room_fans["B"].trigger == "sleep_onset"


# ---------------------------------------------------------------------------
# D5 — F4 pre-arrival fans
# ---------------------------------------------------------------------------

def test_prearrival_activate_skips_paused_room():
    coord, hass, zone, _rcs = _hvac_world(
        {"A": {"automation": False}, "B": {}}, fan_state="off",
    )
    zone.target_temp_high = 74.0
    zone.room_conditions = [
        HZ.RoomCondition(room_name=n, temperature=80.0) for n in ("A", "B")
    ]
    _run(coord._predictor._activate_zone_fans(zone))
    assert _calls(hass, "turn_on", "fan.a") == []
    assert len(_calls(hass, "turn_on", "fan.b")) == 1
    assert {"room": "A", "temp": None, "setpoint": 74.0,
            "reason": "room_paused"} in coord._predictor._last_fan_skipped_rooms


def test_prearrival_deactivate_skips_paused_room():
    coord, hass, zone, _rcs = _hvac_world(
        {"A": {"automation": False}, "B": {}}, fan_state="on",
    )
    # Both rooms are in the predictor's activation list (worst case: A was
    # activated before the pause; a person runs its fan now).
    coord._predictor._last_fan_activation_rooms = ["A", "B"]
    _run(coord._deactivate_zone_fans(zone))
    assert _calls(hass, "turn_off", "fan.a") == []
    assert len(_calls(hass, "turn_off", "fan.b")) == 1


# ---------------------------------------------------------------------------
# F2 — fan recheck arm / still-armed
# ---------------------------------------------------------------------------

def _recheck_world():
    from test_fan_recheck_mode2_cycle import _FakeConfigEntries, _build_world
    mod, hass, mgr, rc, fc, pc, db = _build_world()
    hass.config_entries = _FakeConfigEntries([hass._fan_recheck_cm_entry, rc.entry])
    hass.data["universal_room_automation"][rc.entry.entry_id] = rc
    # The PRODUCTION predicate over a switch table.
    rc.switches = {"automation": True, "manual_mode": False}
    rc._get_room_switch_state = lambda suffix: rc.switches.get(suffix)
    rc._is_automation_enabled = types.MethodType(
        COORD.UniversalRoomCoordinator._is_automation_enabled, rc,
    )
    return mod, hass, mgr, rc, fc


@pytest.mark.asyncio
async def test_fan_recheck_vetoes_paused_room():
    mod, hass, mgr, rc, fc = _recheck_world()
    await mgr.async_setup()
    ctx = mod._RoomCtx(room_name="exercise", entry_id=rc.entry.entry_id)
    # Control: enabled room is eligible on all three surfaces.
    assert mgr.is_recheck_eligible("exercise") is True
    assert mgr._still_armed_eligible(ctx, rc) is True
    assert mgr._is_eligible(ctx, rc) is True

    rc.switches["automation"] = False
    assert mgr.is_recheck_eligible("exercise") is False
    assert mgr._still_armed_eligible(ctx, rc) is False
    assert mgr._is_eligible(ctx, rc) is False
    assert mgr._veto_counts["exercise"].get("room_paused") == 1


@pytest.mark.asyncio
async def test_fan_recheck_paused_mid_flight_restores():
    """A recheck already PAUSED when the room is paused completes, and its
    restore (a discharge) still runs."""
    mod, hass, mgr, rc, fc = _recheck_world()
    await mgr.async_setup()
    from test_fan_recheck_mode2_cycle import _drain_tasks, dt_now_aware
    mgr.on_room_tick(rc)
    await _drain_tasks(hass)
    ctx = mgr._rooms["exercise"]
    await mgr._enter_paused(ctx, rc)
    assert len(fc.pause_calls) == 1
    rc.switches["automation"] = False                     # operator pauses
    await mgr._on_pause_window_done(ctx, dt_now_aware())
    await _drain_tasks(hass)
    assert len(fc.restore_calls) == 1
    assert fc.restore_calls[0][1]["is_on"] is True        # snapshot restored


# ---------------------------------------------------------------------------
# Ambiguity #1 — room-tier `_delayed_exit_verify` retry re-reads the switch
# ---------------------------------------------------------------------------

class _ExitSelf:
    _is_automation_enabled = COORD.UniversalRoomCoordinator._is_automation_enabled
    _delayed_exit_verify = COORD.UniversalRoomCoordinator._delayed_exit_verify

    def __init__(self):
        self.switches = {"automation": True, "manual_mode": False}
        self.data = {CONST.STATE_OCCUPIED: False}
        self.automation = types.SimpleNamespace(
            handle_occupancy_change=AsyncMock(),
        )
        self._last_exit_verify_time = None
        self._last_exit_verify_result = None

    def _get_room_switch_state(self, suffix):
        return self.switches.get(suffix)

    def _get_config(self, key, default=None):
        return "area_a" if key == CONST.CONF_AREA_ID else default

    def _calculate_device_counts(self, area_id):
        return {"lights_on": 1, "switches_on": 0}


@pytest.mark.parametrize("paused_during_delay", [True, False])
def test_delayed_exit_verify_skips_retry_when_paused(monkeypatch, paused_during_delay):
    s = _ExitSelf()

    async def _fake_sleep(_secs):
        if paused_during_delay:
            s.switches["automation"] = False
    monkeypatch.setattr(COORD.asyncio, "sleep", _fake_sleep)
    _run(s._delayed_exit_verify("A", {}))
    if paused_during_delay:
        s.automation.handle_occupancy_change.assert_not_awaited()
        assert s._last_exit_verify_result == "skipped_paused"
    else:
        s.automation.handle_occupancy_change.assert_awaited_once()
        assert s._last_exit_verify_result == "retried"


# ---------------------------------------------------------------------------
# Review C fix-up — release preserves person / recheck state; the kill-switch
# discharge (turn_off_all_managed) is NOT gated by a pause.
# ---------------------------------------------------------------------------

def test_release_preserves_suppress_cooldown_and_hold():
    """`_release_room_tracking` (both callers: Fan Mode hand-back and the
    paused release) clears URA's tracking ONLY. The recheck suppress-until,
    the manual-off cooldown and the manual-ON hold fields are a person's /
    the recheck's state and must survive (else an unpause books a person's
    OFF as a fake cooldown, or drops their hold)."""
    fc, hass, _states, rcs = _fan_world(
        {"A": {}, "B": {}}, fan_on={"A": True, "B": True},
    )
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    paused_at = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    for n in ("A", "B"):
        rf = fc._room_fans[n]
        rf.is_on, rf.trigger, rf.speed_pct = True, "temperature", 33
        rf.last_on_time = "2026-10-19T00:00:00+00:00"
        rf.fan_recheck_suppress_until = future
        rf.manual_off_cooldown_until = future
        rf.manual_on_hold_until = future
        rf.manual_on_hold_paused_at = paused_at
    # A: Fan Mode leaves Follow thermostat (reason fan_mode); B: paused.
    next(e for e in hass.config_entries._entries
         if e.data[CONST.CONF_ROOM_NAME] == "A").options = {
        CONST.CONF_ROOM_FAN_MODE: CONST.FAN_MODE_OFF,
    }
    rcs["B"].pause()
    _run(fc.update(None, "home_day"))
    for n in ("A", "B"):
        rf = fc._room_fans[n]
        assert rf.is_on is False and rf.trigger == ""        # released
        assert rf.fan_recheck_suppress_until == future, n
        assert rf.manual_off_cooldown_until == future, n
        assert rf.manual_on_hold_until == future, n
        assert rf.manual_on_hold_paused_at == paused_at, n
    assert hass.services.calls == []


def test_turn_off_all_managed_still_turns_off_paused_room_fan():
    """The HVAC kill-switch discharge is whitelisted (INV-P'): a paused
    room's tracked fan is still turned off."""
    fc, hass, _states, rcs = _fan_world(
        {"A": {"automation": False}, "B": {}}, fan_on={"A": True, "B": True},
    )
    for n in ("A", "B"):
        rf = fc._room_fans[n]
        rf.is_on, rf.trigger, rf.speed_pct = True, "temperature", 33
    _run(fc.turn_off_all_managed())
    assert len(_calls(hass, "turn_off", "fan.a")) == 1
    assert len(_calls(hass, "turn_off", "fan.b")) == 1
    assert fc._room_fans["A"].is_on is False
