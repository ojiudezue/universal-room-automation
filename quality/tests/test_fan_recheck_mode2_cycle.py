"""Fan-noise Mode-2 mitigation cycle tests.

Covers the planning doc's D10 acceptance criteria:
  - trigger eligibility (D1 1-9)
  - BLE ladder + tier-flip (D1.5 + D2)
  - state machine + cancellation (D3)
  - HVAC handshake (D4)
  - cross-rule precedence (D5)
  - restart resilience (D6)
  - mmwave-history precondition (D1 #2)
  - cold-boot gate (D9)
  - room-tier release method (apply_fan_recheck_release)

HA modules are stubbed (mirrors test_v478_egress_window.py's loader shape) so
this file can run without a real Home Assistant install.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys
import types
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional
from unittest.mock import MagicMock

import pytest


ROOT_DIR = Path(__file__).resolve().parents[2]
ROOT_REL = "custom_components/universal_room_automation"
COORD_PKG_REL = os.path.join(ROOT_REL, "domain_coordinators")


def _now_utc():
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Module loader — stubs HA + ura package siblings.
# ---------------------------------------------------------------------------


def _load_fan_recheck_module():
    if "ura_fan_recheck_under_test" in sys.modules:
        return sys.modules["ura_fan_recheck_under_test"]

    if "homeassistant" not in sys.modules:
        sys.modules["homeassistant"] = types.ModuleType("homeassistant")
        sys.modules["homeassistant"].__path__ = []
    if "homeassistant.core" not in sys.modules:
        ha_core = types.ModuleType("homeassistant.core")
        ha_core.HomeAssistant = type("HomeAssistant", (), {})
        ha_core.callback = lambda f: f
        sys.modules["homeassistant.core"] = ha_core
    if "homeassistant.helpers" not in sys.modules:
        ha_helpers = types.ModuleType("homeassistant.helpers")
        ha_helpers.__path__ = []
        sys.modules["homeassistant.helpers"] = ha_helpers
    if "homeassistant.helpers.dispatcher" not in sys.modules:
        ha_disp = types.ModuleType("homeassistant.helpers.dispatcher")
        ha_disp.async_dispatcher_send = lambda *a, **kw: None
        sys.modules["homeassistant.helpers.dispatcher"] = ha_disp
    if "homeassistant.helpers.event" not in sys.modules:
        ha_event = types.ModuleType("homeassistant.helpers.event")
        ha_event.async_call_later = lambda hass, delay, cb: (lambda: None)
        sys.modules["homeassistant.helpers.event"] = ha_event
    if "homeassistant.helpers.entity_registry" not in sys.modules:
        ha_er = types.ModuleType("homeassistant.helpers.entity_registry")
        ha_er.async_get = lambda hass: None
        sys.modules["homeassistant.helpers.entity_registry"] = ha_er
    if "homeassistant.util" not in sys.modules:
        ha_util = types.ModuleType("homeassistant.util")
        ha_util.__path__ = []
        sys.modules["homeassistant.util"] = ha_util
    if "homeassistant.util.dt" not in sys.modules:
        ha_util_dt = types.ModuleType("homeassistant.util.dt")
        ha_util_dt.now = lambda: datetime.now(timezone.utc)
        ha_util_dt.utcnow = lambda: datetime.now(timezone.utc)
        ha_util_dt.parse_datetime = lambda s: (
            datetime.fromisoformat(s) if s else None
        )
        sys.modules["homeassistant.util.dt"] = ha_util_dt

    # ura stub package — only needed so the relative imports inside
    # presence_fan_recheck and _ble_corroboration resolve.
    pkg_name = "ura_fanrecheck_pkg"
    pkg = types.ModuleType(pkg_name)
    pkg.__path__ = []
    sys.modules[pkg_name] = pkg

    # Load REAL const.py (no stub — we want the real CONF_* defaults).
    const_src = ROOT_DIR / ROOT_REL / "const.py"
    const_spec = importlib.util.spec_from_file_location(
        f"{pkg_name}.const", str(const_src),
    )
    const_mod = importlib.util.module_from_spec(const_spec)
    sys.modules[f"{pkg_name}.const"] = const_mod
    const_spec.loader.exec_module(const_mod)

    # domain_coordinators subpackage.
    coord_pkg = types.ModuleType(f"{pkg_name}.domain_coordinators")
    coord_pkg.__path__ = []
    sys.modules[f"{pkg_name}.domain_coordinators"] = coord_pkg

    # Load REAL signals.py for SIGNAL_FAN_RECHECK_*.
    signals_src = ROOT_DIR / ROOT_REL / "domain_coordinators" / "signals.py"
    signals_spec = importlib.util.spec_from_file_location(
        f"{pkg_name}.domain_coordinators.signals", str(signals_src),
    )
    signals_mod = importlib.util.module_from_spec(signals_spec)
    sys.modules[f"{pkg_name}.domain_coordinators.signals"] = signals_mod
    signals_spec.loader.exec_module(signals_mod)

    # Load REAL _ble_corroboration.py.
    ble_src = ROOT_DIR / ROOT_REL / "domain_coordinators" / "_ble_corroboration.py"
    ble_spec = importlib.util.spec_from_file_location(
        f"{pkg_name}.domain_coordinators._ble_corroboration", str(ble_src),
    )
    ble_mod = importlib.util.module_from_spec(ble_spec)
    sys.modules[f"{pkg_name}.domain_coordinators._ble_corroboration"] = ble_mod
    ble_spec.loader.exec_module(ble_mod)

    # Load REAL presence_fan_recheck.py.
    src_path = ROOT_DIR / ROOT_REL / "domain_coordinators" / "presence_fan_recheck.py"
    spec = importlib.util.spec_from_file_location(
        f"{pkg_name}.domain_coordinators.presence_fan_recheck", str(src_path),
    )
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = f"{pkg_name}.domain_coordinators"
    sys.modules[f"{pkg_name}.domain_coordinators.presence_fan_recheck"] = mod
    spec.loader.exec_module(mod)

    sys.modules["ura_fan_recheck_under_test"] = mod
    return mod


def _load_ble_corroboration_module():
    _load_fan_recheck_module()
    return sys.modules["ura_fanrecheck_pkg.domain_coordinators._ble_corroboration"]


def _const():
    _load_fan_recheck_module()
    return sys.modules["ura_fanrecheck_pkg.const"]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _FakeStates:
    def __init__(self):
        self.mapping = {}

    def get(self, entity_id):
        return self.mapping.get(entity_id)

    def set(self, entity_id, state, attrs=None):
        s = MagicMock()
        s.state = state
        s.attributes = attrs or {}
        self.mapping[entity_id] = s


class _FakeServices:
    def __init__(self):
        self.calls = []

    async def async_call(self, domain, service, data, blocking=False):
        self.calls.append({"domain": domain, "service": service, "data": dict(data)})


class _FakeConfigEntry:
    def __init__(self, entry_id, room_name, fans, extras=None):
        self.entry_id = entry_id
        self.data = {
            "entry_type": "room",
            "room_name": room_name,
            "fans": fans,
            **(extras or {}),
        }
        self.options = {}


class _FakeConfigEntries:
    def __init__(self, entries):
        self._entries = entries

    def async_entries(self, domain):
        return list(self._entries)


class _FakeDB:
    def __init__(self):
        self.rows = {}

    async def get_all_fan_recheck_state(self):
        return list(self.rows.values())

    async def save_fan_recheck_state(self, state):
        self.rows[state["room_id"]] = dict(state)

    async def clear_fan_recheck_state(self, room_id):
        self.rows.pop(room_id, None)


class _FakeRoomCoord:
    def __init__(self, room_name, entry_id, fans, recent_sources=None, **opts):
        extras = {"fan_control_enabled": opts.get("fan_control_enabled", True)}
        # opts pass-through for CONF_ROOM_FAN_RECHECK_ENABLED etc.
        for k, v in opts.items():
            if k != "fan_control_enabled":
                extras[k] = v
        self.entry = _FakeConfigEntry(entry_id, room_name, fans, extras=extras)
        self._recent = list(recent_sources or [])
        self.data = {
            "occupied": True,
            "occupancy_source": "mmwave",
            "motion_detected": False,
            "presence_detected": True,
        }
        self.updated_with = None

    def recent_occupancy_sources(self):
        return list(self._recent)

    def apply_fan_recheck_release(self):
        self.data["occupied"] = False
        self.data["occupancy_source"] = "fan_recheck_release"
        self.data["timeout_remaining"] = 0

    def async_set_updated_data(self, data):
        self.updated_with = dict(data)


class _FakeFanController:
    def __init__(self):
        self._room_fans = {}
        self.pause_calls = []
        self.restore_calls = []
        self.suppress_calls = []

    def is_room_fan_on(self, room_name):
        return True

    def snapshot_room_fan(self, room_name):
        rf = self._room_fans.get(room_name)
        if rf is None:
            return None
        return {"entities": list(rf.fan_entities), "is_on": True, "speed_pct": 50,
                "trigger": "temperature", "last_on_time": "", "entity_attrs": {}}

    async def pause_for_recheck(self, room_name, until_iso):
        self.pause_calls.append((room_name, until_iso))
        rf = self._room_fans.get(room_name)
        if rf is None:
            return None
        rf.fan_recheck_suppress_until = until_iso
        rf.is_on = False
        return {"entities": list(rf.fan_entities), "is_on": True, "speed_pct": 50,
                "trigger": "temperature", "last_on_time": "", "entity_attrs": {}}

    async def restore_after_recheck(self, room_name, snapshot):
        self.restore_calls.append((room_name, snapshot))
        rf = self._room_fans.get(room_name)
        if rf is not None:
            rf.fan_recheck_suppress_until = ""
            if snapshot and snapshot.get("is_on"):
                rf.is_on = True

    def suppress_room_until(self, room_name, until_iso):
        self.suppress_calls.append((room_name, until_iso))
        rf = self._room_fans.get(room_name)
        if rf is not None:
            rf.fan_recheck_suppress_until = until_iso


class _FakeHVAC:
    def __init__(self, fan_controller):
        self.fan_controller = fan_controller


class _FakeCM:
    def __init__(self, hvac):
        self.coordinators = {"hvac": hvac}


class _FakePersonCoord:
    def __init__(self):
        self.room_persons = {}
        self.zone_persons = {}
        self.ble_tier = 1
        self.room_direct_ble = True

    def get_persons_in_room(self, room_name):
        return list(self.room_persons.get(room_name, []))

    def get_persons_in_zone(self, zone_rooms):
        out = set()
        for r in zone_rooms:
            out.update(self.room_persons.get(r, []))
        return sorted(out)

    def get_ble_tier(self, room_name):
        return self.ble_tier

    def is_room_direct_ble(self, room_name):
        return self.room_direct_ble


class _FakeZoneTracker:
    def __init__(self, room_names):
        self.room_names = list(room_names)


class _FakePresence:
    def __init__(self):
        self._boot_settle_done = True
        self.zone_trackers = {}
        self.adjacency = {}

    def get_adjacent_rooms(self, room_name):
        return list(self.adjacency.get(room_name, []))


class _FakeHass:
    def __init__(self):
        self.states = _FakeStates()
        self.services = _FakeServices()
        self.data = {"universal_room_automation": {}}
        self.config_entries = _FakeConfigEntries([])
        self._tasks = []

    def async_create_task(self, coro):
        self._tasks.append(coro)
        return coro


# ---------------------------------------------------------------------------
# Helpers to assemble a working manager + run scheduled tasks.
# ---------------------------------------------------------------------------


async def _drain_tasks(hass):
    """Run any tasks scheduled via async_create_task."""
    while hass._tasks:
        coro = hass._tasks.pop(0)
        await coro


def _build_world(*, recent_sources=None, with_fan_on=True, person_in_room=False,
                 ble_tier=1, l2_adjacent_present=False,
                 master_enabled=True, room_opt_in=True,
                 room_type="generic", l2_allowed=False, trust_sensors_ok=False,
                 fan_control_enabled=True):
    mod = _load_fan_recheck_module()
    hass = _FakeHass()
    fc = _FakeFanController()
    fc._room_fans["exercise"] = _FakeRoomFan(
        room_name="exercise",
        fan_entities=["fan.exercise"],
    )
    hvac = _FakeHVAC(fc)
    cm = _FakeCM(hvac)
    hass.data["universal_room_automation"]["coordinator_manager"] = cm

    pc = _FakePersonCoord()
    pc.ble_tier = ble_tier
    pc.room_direct_ble = (ble_tier == 1)
    if person_in_room:
        pc.room_persons["exercise"] = ["operator"]
    if l2_adjacent_present:
        pc.room_persons["jaya_bedroom"] = ["jaya"]
    hass.data["universal_room_automation"]["person_coordinator"] = pc

    presence = _FakePresence()
    presence.adjacency["exercise"] = ["jaya_bedroom"]
    presence.zone_trackers["upstairs"] = _FakeZoneTracker(
        ["exercise", "jaya_bedroom"],
    )
    hass.data["universal_room_automation"]["fan_recheck_master_enabled"] = master_enabled

    room_extras = {
        "room_fan_recheck_enabled": room_opt_in,
        "fan_recheck_l2_allowed": l2_allowed,
        "fan_recheck_trust_sensors_ok": trust_sensors_ok,
        "room_type": room_type,
        "fan_control_enabled": fan_control_enabled,
        "fan_recheck_arm_delay_s": 60,
        "fan_recheck_spindown_s": 30,
        "fan_recheck_window_s": 60,
        "fan_recheck_cooldown_s": 1800,
        "fan_recheck_max_per_hour": 2,
        "fan_recheck_hvac_suppress_s": 600,
        "fan_recheck_mmwave_history_ticks": 3,
    }
    rc = _FakeRoomCoord(
        "exercise", "entry_exercise", ["fan.exercise"],
        recent_sources=recent_sources or ["mmwave", "mmwave", "mmwave"],
        **room_extras,
    )

    if with_fan_on:
        hass.states.set("fan.exercise", "on")
    else:
        hass.states.set("fan.exercise", "off")

    db = _FakeDB()
    hass.data["universal_room_automation"]["database"] = db

    mgr = mod.FanRecheckManager(hass, presence)
    return mod, hass, mgr, rc, fc, pc, db


@dataclass
class _FakeRoomFan:
    room_name: str
    fan_entities: list = field(default_factory=list)
    is_on: bool = True
    speed_pct: int = 50
    trigger: str = "temperature"
    last_on_time: str = ""
    manual_off_cooldown_until: str = ""
    fan_recheck_suppress_until: str = ""


# =============================================================================
# D1 trigger eligibility tests
# =============================================================================


@pytest.mark.asyncio
async def test_eligible_with_three_consecutive_mmwave_ticks_tier1_zone_absent():
    mod, hass, mgr, rc, fc, pc, db = _build_world()
    await mgr.async_setup()
    mgr.on_room_tick(rc)
    await _drain_tasks(hass)
    assert mgr.get_room_state("exercise") == mod.STATE_ARMED


@pytest.mark.asyncio
async def test_master_kill_blocks_trigger():
    mod, hass, mgr, rc, fc, pc, db = _build_world(master_enabled=False)
    await mgr.async_setup()
    mgr.on_room_tick(rc)
    await _drain_tasks(hass)
    assert mgr.get_room_state("exercise") == mod.STATE_IDLE


@pytest.mark.asyncio
async def test_room_opt_out_blocks_trigger():
    mod, hass, mgr, rc, fc, pc, db = _build_world(room_opt_in=False)
    await mgr.async_setup()
    mgr.on_room_tick(rc)
    await _drain_tasks(hass)
    assert mgr.get_room_state("exercise") == mod.STATE_IDLE


@pytest.mark.asyncio
async def test_fan_control_disabled_blocks_trigger():
    mod, hass, mgr, rc, fc, pc, db = _build_world(fan_control_enabled=False)
    await mgr.async_setup()
    mgr.on_room_tick(rc)
    await _drain_tasks(hass)
    assert mgr.get_room_state("exercise") == mod.STATE_IDLE


@pytest.mark.asyncio
async def test_no_fan_on_blocks_trigger():
    mod, hass, mgr, rc, fc, pc, db = _build_world(with_fan_on=False)
    await mgr.async_setup()
    mgr.on_room_tick(rc)
    await _drain_tasks(hass)
    assert mgr.get_room_state("exercise") == mod.STATE_IDLE


@pytest.mark.asyncio
async def test_mmwave_history_too_short_blocks_trigger():
    mod, hass, mgr, rc, fc, pc, db = _build_world(
        recent_sources=["mmwave", "mmwave"],  # only 2 ticks, need 3
    )
    await mgr.async_setup()
    mgr.on_room_tick(rc)
    await _drain_tasks(hass)
    assert mgr.get_room_state("exercise") == mod.STATE_IDLE


@pytest.mark.asyncio
async def test_motion_blip_in_history_blocks_trigger():
    mod, hass, mgr, rc, fc, pc, db = _build_world(
        recent_sources=["mmwave", "motion", "mmwave"],
    )
    await mgr.async_setup()
    mgr.on_room_tick(rc)
    await _drain_tasks(hass)
    assert mgr.get_room_state("exercise") == mod.STATE_IDLE


@pytest.mark.asyncio
async def test_l1_room_person_vetoes_trigger():
    mod, hass, mgr, rc, fc, pc, db = _build_world(person_in_room=True)
    await mgr.async_setup()
    mgr.on_room_tick(rc)
    await _drain_tasks(hass)
    assert mgr.get_room_state("exercise") == mod.STATE_IDLE


@pytest.mark.asyncio
async def test_boot_settle_blocks_trigger():
    mod, hass, mgr, rc, fc, pc, db = _build_world()
    mgr._presence._boot_settle_done = False
    await mgr.async_setup()
    mgr.on_room_tick(rc)
    await _drain_tasks(hass)
    assert mgr.get_room_state("exercise") == mod.STATE_IDLE


# =============================================================================
# D1.5 / D2 BLE tier-flip tests
# =============================================================================


@pytest.mark.asyncio
async def test_tier2_with_l2_adjacent_present_unconditional_veto():
    """In Tier-2, an adjacent trustworthy phone is an unconditional VETO,
    regardless of CONF_FAN_RECHECK_L2_ALLOWED."""
    mod, hass, mgr, rc, fc, pc, db = _build_world(
        ble_tier=2,
        l2_adjacent_present=True,
        l2_allowed=True,  # even with the Tier-1 opt-in True, Tier-2 vetoes
        trust_sensors_ok=True,
    )
    await mgr.async_setup()
    mgr.on_room_tick(rc)
    await _drain_tasks(hass)
    assert mgr.get_room_state("exercise") == mod.STATE_IDLE


@pytest.mark.asyncio
async def test_tier2_without_trust_sensors_ok_blocks_drop():
    mod, hass, mgr, rc, fc, pc, db = _build_world(
        ble_tier=2,
        l2_adjacent_present=False,
        trust_sensors_ok=False,  # gates Tier-2 / Tier-0 authorization
    )
    await mgr.async_setup()
    mgr.on_room_tick(rc)
    await _drain_tasks(hass)
    assert mgr.get_room_state("exercise") == mod.STATE_IDLE


@pytest.mark.asyncio
async def test_tier2_with_trust_sensors_ok_authorizes():
    mod, hass, mgr, rc, fc, pc, db = _build_world(
        ble_tier=2,
        l2_adjacent_present=False,
        trust_sensors_ok=True,
    )
    await mgr.async_setup()
    mgr.on_room_tick(rc)
    await _drain_tasks(hass)
    assert mgr.get_room_state("exercise") == mod.STATE_ARMED


@pytest.mark.asyncio
async def test_tier1_bedroom_l2_allowed_still_rejects_l2():
    """D1.5 dial: bedrooms force L3-only even when L2_ALLOWED is True."""
    mod, hass, mgr, rc, fc, pc, db = _build_world(
        ble_tier=1,
        l2_adjacent_present=True,
        l2_allowed=True,
        room_type="bedroom",
    )
    await mgr.async_setup()
    mgr.on_room_tick(rc)
    await _drain_tasks(hass)
    assert mgr.get_room_state("exercise") == mod.STATE_IDLE


# =============================================================================
# D3 state machine + cancellation
# =============================================================================


@pytest.mark.asyncio
async def test_motion_during_armed_cancels_to_cooldown():
    mod, hass, mgr, rc, fc, pc, db = _build_world()
    await mgr.async_setup()
    mgr.on_room_tick(rc)
    await _drain_tasks(hass)
    assert mgr.get_room_state("exercise") == mod.STATE_ARMED
    # Simulate motion appearing.
    rc.data["motion_detected"] = True
    mgr.on_room_tick(rc)
    await _drain_tasks(hass)
    # After cancellation it transitions to cooldown.
    assert mgr.get_room_state("exercise") == mod.STATE_COOLDOWN


# =============================================================================
# D4 HVAC handshake (verified via the FanController fake)
# =============================================================================


@pytest.mark.asyncio
async def test_pause_calls_fan_controller_with_suppress_window():
    mod, hass, mgr, rc, fc, pc, db = _build_world()
    await mgr.async_setup()
    mgr.on_room_tick(rc)
    await _drain_tasks(hass)
    ctx = mgr._rooms["exercise"]
    # Force transition to paused.
    await mgr._enter_paused(ctx, rc)
    assert len(fc.pause_calls) == 1
    room_name, until_iso = fc.pause_calls[0]
    assert room_name == "exercise"
    assert until_iso  # ISO timestamp present


@pytest.mark.asyncio
async def test_restore_calls_fan_controller_and_releases_room_when_vacated():
    mod, hass, mgr, rc, fc, pc, db = _build_world()
    # Wire the room coord into hass.data + config_entries so _room_coord_for
    # can find it during the verdict step.
    hass.config_entries = _FakeConfigEntries([rc.entry])
    hass.data["universal_room_automation"][rc.entry.entry_id] = rc
    await mgr.async_setup()
    mgr.on_room_tick(rc)
    await _drain_tasks(hass)
    ctx = mgr._rooms["exercise"]
    await mgr._enter_paused(ctx, rc)
    # Simulate mmwave dropping during the observation window.
    rc.data["presence_detected"] = False
    rc.data["occupancy_source"] = "none"
    await mgr._on_pause_window_done(ctx, dt_now_aware())
    assert ctx.last_outcome == mod.OUTCOME_VACATED
    # apply_fan_recheck_release was called on the room coord.
    assert rc.data["occupancy_source"] == "fan_recheck_release"
    assert rc.data["occupied"] is False


@pytest.mark.asyncio
async def test_restore_does_not_release_when_mmwave_persists():
    mod, hass, mgr, rc, fc, pc, db = _build_world()
    hass.config_entries = _FakeConfigEntries([rc.entry])
    hass.data["universal_room_automation"][rc.entry.entry_id] = rc
    await mgr.async_setup()
    mgr.on_room_tick(rc)
    await _drain_tasks(hass)
    ctx = mgr._rooms["exercise"]
    await mgr._enter_paused(ctx, rc)
    # mmwave persists -> real presence
    await mgr._on_pause_window_done(ctx, dt_now_aware())
    assert ctx.last_outcome == mod.OUTCOME_OCCUPIED_CONFIRMED
    # Room state untouched.
    assert rc.data["occupied"] is True


# =============================================================================
# D5 cross-rule precedence
# =============================================================================


@pytest.mark.asyncio
async def test_force_restore_service_path():
    mod, hass, mgr, rc, fc, pc, db = _build_world()
    await mgr.async_setup()
    mgr.on_room_tick(rc)
    await _drain_tasks(hass)
    ctx = mgr._rooms["exercise"]
    await mgr._enter_paused(ctx, rc)
    await mgr.force_restore("exercise")
    assert ctx.last_outcome == mod.OUTCOME_OCCUPIED_CONFIRMED
    assert ctx.state == mod.STATE_COOLDOWN


@pytest.mark.asyncio
async def test_manual_off_cooldown_blocks_trigger():
    mod, hass, mgr, rc, fc, pc, db = _build_world()
    # Set manual_off_cooldown_until in the future. Use the same dt_util the
    # code under test imported (cross-test stubs may swap naive vs aware).
    base_now = mod.dt_util.now()
    fc._room_fans["exercise"].manual_off_cooldown_until = (
        (base_now + timedelta(hours=1)).isoformat()
    )
    await mgr.async_setup()
    mgr.on_room_tick(rc)
    await _drain_tasks(hass)
    assert mgr.get_room_state("exercise") == mod.STATE_IDLE


# =============================================================================
# D6 restart resilience
# =============================================================================


@pytest.mark.asyncio
async def test_rehydrate_armed_drops_to_idle_bug_class_14():
    mod, hass, mgr, rc, fc, pc, db = _build_world()
    db.rows["entry_exercise"] = {
        "room_id": "entry_exercise",
        "state": "armed",
        "state_entered_at": mod.dt_util.now().isoformat(),
        "snapshot_json": None,
        "attempts_in_hour": 0,
        "last_outcome": None,
        "last_attempt_at": None,
        "ble_ladder_layer": "L3",
        "last_update_ts": mod.dt_util.now().isoformat(),
    }
    hass.config_entries = _FakeConfigEntries([rc.entry])
    await mgr.async_setup()
    assert mgr.get_room_state("exercise") == mod.STATE_IDLE


@pytest.mark.asyncio
async def test_rehydrate_paused_too_old_idle():
    mod, hass, mgr, rc, fc, pc, db = _build_world()
    old = mod.dt_util.now() - timedelta(seconds=600)
    db.rows["entry_exercise"] = {
        "room_id": "entry_exercise",
        "state": "paused",
        "state_entered_at": old.isoformat(),
        "snapshot_json": None,
        "attempts_in_hour": 1,
        "last_outcome": None,
        "last_attempt_at": old.isoformat(),
        "ble_ladder_layer": "L3",
        "last_update_ts": old.isoformat(),
    }
    hass.config_entries = _FakeConfigEntries([rc.entry])
    await mgr.async_setup()
    assert mgr.get_room_state("exercise") == mod.STATE_IDLE


@pytest.mark.asyncio
async def test_rehydrate_cooldown_honors_remaining():
    mod, hass, mgr, rc, fc, pc, db = _build_world()
    entered = mod.dt_util.now() - timedelta(seconds=300)
    db.rows["entry_exercise"] = {
        "room_id": "entry_exercise",
        "state": "cooldown",
        "state_entered_at": entered.isoformat(),
        "snapshot_json": None,
        "attempts_in_hour": 1,
        "last_outcome": "vacated",
        "last_attempt_at": entered.isoformat(),
        "ble_ladder_layer": "L3",
        "last_update_ts": entered.isoformat(),
    }
    hass.config_entries = _FakeConfigEntries([rc.entry])
    await mgr.async_setup()
    # Still in cooldown (default 1800s, only 300 elapsed).
    assert mgr.get_room_state("exercise") == mod.STATE_COOLDOWN


@pytest.mark.asyncio
async def test_rehydrate_corrupt_row_drops_to_idle():
    mod, hass, mgr, rc, fc, pc, db = _build_world()
    db.rows["entry_exercise"] = {
        "room_id": "entry_exercise",
        "state": "garbage",
        "state_entered_at": "not_a_datetime",
        "snapshot_json": "{not json",
        "attempts_in_hour": "not_int",
        "last_outcome": None,
        "last_attempt_at": None,
        "ble_ladder_layer": None,
        "last_update_ts": mod.dt_util.now().isoformat(),
    }
    hass.config_entries = _FakeConfigEntries([rc.entry])
    await mgr.async_setup()
    # Implementation falls through unknown state -> idle.
    assert mgr.get_room_state("exercise") == mod.STATE_IDLE


# =============================================================================
# const / signal / occupancy_source contract — fixed surface contracts
# =============================================================================


def test_new_const_names_exist():
    const = _const()
    for name in (
        "CONF_FAN_RECHECK_ENABLED",
        "CONF_ROOM_FAN_RECHECK_ENABLED",
        "CONF_FAN_RECHECK_L2_ALLOWED",
        "CONF_FAN_RECHECK_TRUST_SENSORS_OK",
        "CONF_FAN_RECHECK_ARM_DELAY_S",
        "CONF_FAN_RECHECK_SPINDOWN_S",
        "CONF_FAN_RECHECK_WINDOW_S",
        "CONF_FAN_RECHECK_COOLDOWN_S",
        "CONF_FAN_RECHECK_MAX_PER_HOUR",
        "CONF_FAN_RECHECK_HVAC_SUPPRESS_S",
        "CONF_FAN_RECHECK_MMWAVE_HISTORY_TICKS",
        "ROOM_TYPE_RECHECK_FACTOR",
        "OCCUPANCY_SOURCE_FAN_RECHECK_RELEASE",
    ):
        assert hasattr(const, name), f"const.{name} missing"


def test_new_signal_names_exist():
    sig_mod = sys.modules["ura_fanrecheck_pkg.domain_coordinators.signals"]
    assert hasattr(sig_mod, "SIGNAL_FAN_RECHECK_STARTED")
    assert hasattr(sig_mod, "SIGNAL_FAN_RECHECK_FINISHED")


def test_room_type_recheck_factor_only_bedrooms_and_media():
    const = _const()
    factor = const.ROOM_TYPE_RECHECK_FACTOR
    assert factor.get("bedroom") and factor["bedroom"] > 1.0
    assert factor.get("media_room") and factor["media_room"] > 1.0
    # Other types fall back to default 1.0 via DEFAULT_RECHECK_FACTOR.
    assert "generic" not in factor


def test_occupancy_source_release_value():
    const = _const()
    assert const.OCCUPANCY_SOURCE_FAN_RECHECK_RELEASE == "fan_recheck_release"


# =============================================================================
# BLE corroboration H2 carve-out tests
# =============================================================================


def test_ble_phone_trustworthy_fail_open_when_no_entity_registry():
    ble = _load_ble_corroboration_module()
    hass = _FakeHass()
    # H2 carve-out: missing sensor -> fail OPEN
    assert ble.phone_trustworthy(hass, "operator") is True


def test_ble_trustworthy_persons_in_room_filters_left_behind():
    ble = _load_ble_corroboration_module()
    hass = _FakeHass()
    pc = _FakePersonCoord()
    pc.room_persons["exercise"] = ["operator", "guest"]
    # No phone sensors registered -> all persons pass through (fail OPEN).
    persons = ble.trustworthy_persons_in_room(hass, pc, "exercise")
    assert persons == ["operator", "guest"]


def test_ble_trustworthy_persons_in_zone_aggregates():
    ble = _load_ble_corroboration_module()
    hass = _FakeHass()
    pc = _FakePersonCoord()
    pc.room_persons["a"] = ["x"]
    pc.room_persons["b"] = ["y"]
    persons = ble.trustworthy_persons_in_zone(hass, pc, ["a", "b"])
    assert set(persons) == {"x", "y"}


# =============================================================================
# Source-grep regression invariants
# =============================================================================


def test_state_machine_module_uses_module_top_dispatcher_import():
    """Bug Class #34 / v4.7.20.1 recurrence: NO function-local
    async_dispatcher_send imports."""
    src_path = ROOT_DIR / ROOT_REL / "domain_coordinators" / "presence_fan_recheck.py"
    src = src_path.read_text(encoding="utf-8")
    # Module-level import present.
    assert "from homeassistant.helpers.dispatcher import async_dispatcher_send" in src
    # No function-local re-import.
    bad = src.count("from homeassistant.helpers.dispatcher import")
    assert bad == 1, "expected exactly ONE top-level dispatcher import"


def test_state_machine_does_not_use_legacy_terminology():
    """Layered lattice rule: no 'legacy' label on the room tier."""
    src_path = ROOT_DIR / ROOT_REL / "domain_coordinators" / "presence_fan_recheck.py"
    src = src_path.read_text(encoding="utf-8").lower()
    assert "legacy" not in src


def test_fan_controller_has_pause_restore_suppress_methods():
    src_path = ROOT_DIR / ROOT_REL / "domain_coordinators" / "hvac_fans.py"
    src = src_path.read_text(encoding="utf-8")
    for method in (
        "def suppress_room_until",
        "def snapshot_room_fan",
        "async def pause_for_recheck",
        "async def restore_after_recheck",
        "fan_recheck_suppress_until",
    ):
        assert method in src, f"missing {method}"


def test_hvac_fans_update_honors_suppression_window():
    src_path = ROOT_DIR / ROOT_REL / "domain_coordinators" / "hvac_fans.py"
    src = src_path.read_text(encoding="utf-8")
    # Suppression check appears INSIDE the update for-loop.
    update_idx = src.find("async def update(")
    set_state_idx = src.find("    def get_fan_status(")
    body = src[update_idx:set_state_idx]
    assert "fan_recheck_suppress_until" in body
    assert "continue" in body  # skip past the room


def test_room_coordinator_has_apply_fan_recheck_release():
    src_path = ROOT_DIR / ROOT_REL / "coordinator.py"
    src = src_path.read_text(encoding="utf-8")
    assert "def apply_fan_recheck_release" in src
    assert "OCCUPANCY_SOURCE_FAN_RECHECK_RELEASE" in src
    # Ring buffer added.
    assert "_recent_occupancy_sources" in src
    assert "recent_occupancy_sources" in src


def test_presence_has_get_adjacent_rooms_public_method():
    src_path = ROOT_DIR / ROOT_REL / "domain_coordinators" / "presence.py"
    src = src_path.read_text(encoding="utf-8")
    assert "def get_adjacent_rooms(" in src
    # Reads cache, not rebuild on every call.
    assert "_adjacency_cache" in src


def test_database_module_has_fan_recheck_daos():
    src_path = ROOT_DIR / ROOT_REL / "database.py"
    src = src_path.read_text(encoding="utf-8")
    for dao in (
        "async def get_fan_recheck_state",
        "async def save_fan_recheck_state",
        "async def get_all_fan_recheck_state",
        "async def clear_fan_recheck_state",
        "async def prune_stale_fan_recheck_state",
    ):
        assert dao in src, f"missing DAO {dao}"


# helper
def dt_now_aware():
    return datetime.now(timezone.utc)
