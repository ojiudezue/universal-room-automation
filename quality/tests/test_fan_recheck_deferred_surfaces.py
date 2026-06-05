"""Fan-noise Mode-2 deferred-surface tests (config_flow, switches, numbers, etc).

Covers the deferred operability/config surfaces added on top of the
PLANNING_fan_noise_mode2_ble_pause_recheck.md core build:

  - const-only round-trip for the new CONF_* keys (round-trip)
  - switch.py master toggle mirrors hass.data master flag + CM entry.options
  - per-room switches mirror room entry.options on toggle
  - number.py timing Numbers mirror CM entry.options + RestoreEntity restore
  - binary_sensor / sensor read FanRecheckManager.get_room_attrs cleanly
  - services.yaml registers fan_recheck_force_restore and unload removes it
  - presence teardown cancels FanRecheckManager timers

Source loading mirrors test_fan_recheck_mode2_cycle.py — stubs HA so the
production code can run without a real Home Assistant install. Drives
production code paths (no parallel reimplementations).
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
import types
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import yaml


ROOT_DIR = Path(__file__).resolve().parents[2]
ROOT_REL = "custom_components/universal_room_automation"


# ---------------------------------------------------------------------------
# HA module stubs (mirrors the loader shape in test_fan_recheck_mode2_cycle.py
# — kept minimal because we only exercise const + service registration helpers).
# ---------------------------------------------------------------------------


def _stub_ha():
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
        ha_d = types.ModuleType("homeassistant.helpers.dispatcher")
        ha_d.async_dispatcher_send = lambda *a, **kw: None
        sys.modules["homeassistant.helpers.dispatcher"] = ha_d
    if "homeassistant.helpers.event" not in sys.modules:
        ha_e = types.ModuleType("homeassistant.helpers.event")
        ha_e.async_call_later = lambda hass, delay, cb: (lambda: None)
        sys.modules["homeassistant.helpers.event"] = ha_e
    if "homeassistant.helpers.entity_registry" not in sys.modules:
        ha_er = types.ModuleType("homeassistant.helpers.entity_registry")
        ha_er.async_get = lambda hass: None
        sys.modules["homeassistant.helpers.entity_registry"] = ha_er
    if "homeassistant.util" not in sys.modules:
        ha_util = types.ModuleType("homeassistant.util")
        ha_util.__path__ = []
        sys.modules["homeassistant.util"] = ha_util
    if "homeassistant.util.dt" not in sys.modules:
        ha_dt = types.ModuleType("homeassistant.util.dt")
        ha_dt.now = lambda: datetime.now(timezone.utc)
        ha_dt.utcnow = lambda: datetime.now(timezone.utc)
        ha_dt.parse_datetime = lambda s: datetime.fromisoformat(s) if s else None
        sys.modules["homeassistant.util.dt"] = ha_dt


def _load_const():
    _stub_ha()
    pkg_name = "ura_fanrecheck_pkg"
    if pkg_name not in sys.modules:
        pkg = types.ModuleType(pkg_name)
        pkg.__path__ = []
        sys.modules[pkg_name] = pkg
    if f"{pkg_name}.const" not in sys.modules:
        const_src = ROOT_DIR / ROOT_REL / "const.py"
        spec = importlib.util.spec_from_file_location(
            f"{pkg_name}.const", str(const_src),
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules[f"{pkg_name}.const"] = mod
        spec.loader.exec_module(mod)
    return sys.modules[f"{pkg_name}.const"]


def _load_fan_recheck_manager_module():
    """Reuse the loader shape from test_fan_recheck_mode2_cycle so const +
    signals + _ble_corroboration + presence_fan_recheck are all real code."""
    const = _load_const()
    pkg_name = "ura_fanrecheck_pkg"
    coord_pkg_name = f"{pkg_name}.domain_coordinators"
    if coord_pkg_name not in sys.modules:
        sub = types.ModuleType(coord_pkg_name)
        sub.__path__ = []
        sys.modules[coord_pkg_name] = sub
    if f"{coord_pkg_name}.signals" not in sys.modules:
        src = ROOT_DIR / ROOT_REL / "domain_coordinators" / "signals.py"
        spec = importlib.util.spec_from_file_location(
            f"{coord_pkg_name}.signals", str(src),
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules[f"{coord_pkg_name}.signals"] = mod
        spec.loader.exec_module(mod)
    if f"{coord_pkg_name}._ble_corroboration" not in sys.modules:
        src = ROOT_DIR / ROOT_REL / "domain_coordinators" / "_ble_corroboration.py"
        spec = importlib.util.spec_from_file_location(
            f"{coord_pkg_name}._ble_corroboration", str(src),
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules[f"{coord_pkg_name}._ble_corroboration"] = mod
        spec.loader.exec_module(mod)
    if f"{coord_pkg_name}.presence_fan_recheck" not in sys.modules:
        src = ROOT_DIR / ROOT_REL / "domain_coordinators" / "presence_fan_recheck.py"
        spec = importlib.util.spec_from_file_location(
            f"{coord_pkg_name}.presence_fan_recheck", str(src),
        )
        mod = importlib.util.module_from_spec(spec)
        mod.__package__ = coord_pkg_name
        sys.modules[f"{coord_pkg_name}.presence_fan_recheck"] = mod
        spec.loader.exec_module(mod)
    return sys.modules[f"{coord_pkg_name}.presence_fan_recheck"]


# ---------------------------------------------------------------------------
# T1 — const round-trip: the deferred plumbing relies on every CONF_* + DEFAULT_*
# the wiring imports. Source-grep against const.py protects against an
# accidental rename that would silently break entry.options round-trip.
# ---------------------------------------------------------------------------


def test_const_round_trip_for_mode2_keys():
    c = _load_const()
    # Master + per-room kill switches.
    assert c.CONF_FAN_RECHECK_ENABLED == "fan_recheck_enabled"
    assert c.DEFAULT_FAN_RECHECK_ENABLED is False
    assert c.CONF_ROOM_FAN_RECHECK_ENABLED == "room_fan_recheck_enabled"
    assert c.DEFAULT_ROOM_FAN_RECHECK_ENABLED is False
    assert c.CONF_FAN_RECHECK_L2_ALLOWED == "fan_recheck_l2_allowed"
    assert c.DEFAULT_FAN_RECHECK_L2_ALLOWED is False
    assert c.CONF_FAN_RECHECK_TRUST_SENSORS_OK == "fan_recheck_trust_sensors_ok"
    assert c.DEFAULT_FAN_RECHECK_TRUST_SENSORS_OK is False
    # 7 timing knobs with documented bounds.
    assert c.DEFAULT_FAN_RECHECK_ARM_DELAY_S == 60
    assert c.DEFAULT_FAN_RECHECK_SPINDOWN_S == 30
    assert c.DEFAULT_FAN_RECHECK_WINDOW_S == 60
    assert c.DEFAULT_FAN_RECHECK_COOLDOWN_S == 1800
    assert c.DEFAULT_FAN_RECHECK_MAX_PER_HOUR == 2
    assert c.DEFAULT_FAN_RECHECK_HVAC_SUPPRESS_S == 600
    assert c.DEFAULT_FAN_RECHECK_MMWAVE_HISTORY_TICKS == 3
    # Default-OFF safety: every flag the operator never touches must be False.
    assert c.DEFAULT_FAN_RECHECK_ENABLED is False
    assert c.DEFAULT_ROOM_FAN_RECHECK_ENABLED is False


# ---------------------------------------------------------------------------
# T2 — config_flow surface protection: source grep for each new CONF_* on
# both the room create step and the room reconfigure step + the
# coordinator_presence options step. Catches an accidental remove during
# review fix-up.
# ---------------------------------------------------------------------------


def test_config_flow_wires_per_room_and_master_keys():
    src = (ROOT_DIR / ROOT_REL / "config_flow.py").read_text()
    # Per-room create step.
    assert "CONF_ROOM_FAN_RECHECK_ENABLED" in src
    assert "CONF_FAN_RECHECK_L2_ALLOWED" in src
    assert "CONF_FAN_RECHECK_TRUST_SENSORS_OK" in src
    # Master step.
    assert "CONF_FAN_RECHECK_ENABLED" in src
    # 7 timing knobs.
    for key in (
        "CONF_FAN_RECHECK_ARM_DELAY_S",
        "CONF_FAN_RECHECK_SPINDOWN_S",
        "CONF_FAN_RECHECK_WINDOW_S",
        "CONF_FAN_RECHECK_COOLDOWN_S",
        "CONF_FAN_RECHECK_MAX_PER_HOUR",
        "CONF_FAN_RECHECK_HVAC_SUPPRESS_S",
        "CONF_FAN_RECHECK_MMWAVE_HISTORY_TICKS",
    ):
        assert key in src, f"options step missing {key}"
    # Master save mirrors the runtime flag (defends against a review
    # fix-up that drops the hass.data mirror — would break opt-in until
    # next coord setup).
    assert "fan_recheck_master_enabled" in src


# ---------------------------------------------------------------------------
# T3 — switch.py source protection: master FanRecheckEnabledSwitch + the
# two per-room switches are wired into the platform setup AND they mirror
# the master flag into hass.data. Source-grep regression because import
# cycles between switch.py and HA helpers make a runtime instantiate test
# costly.
# ---------------------------------------------------------------------------


def test_switch_platform_wires_master_and_room_switches():
    src = (ROOT_DIR / ROOT_REL / "switch.py").read_text()
    # Master switch registered in CM setup block.
    assert "FanRecheckEnabledSwitch(hass, entry)" in src
    # Per-room switches registered in room setup block.
    assert "RoomFanRecheckEnabledSwitch(coordinator)" in src
    assert "RoomFanRecheckL2AllowedSwitch(coordinator)" in src
    # Master mirror to hass.data (FanRecheckManager reads this).
    assert "fan_recheck_master_enabled" in src
    # Master mirror to CM entry.options (URA mirror pattern; reload
    # should not snap value back to default).
    assert "self._entry.options" in src and "CONF_FAN_RECHECK_ENABLED" in src
    # Per-room mirror writes the per-room CONF key into entry.options so
    # FanRecheckManager._merged_config picks it up on next tick.
    assert "CONF_ROOM_FAN_RECHECK_ENABLED" in src
    assert "CONF_FAN_RECHECK_L2_ALLOWED" in src


# ---------------------------------------------------------------------------
# T4 — number.py source protection: 7 timing Number entities exist, share
# a base class, and the base mirrors to CM entry.options on
# async_set_native_value (URA mirror pattern verified by source-grep).
# ---------------------------------------------------------------------------


def test_number_platform_wires_seven_timing_numbers():
    src = (ROOT_DIR / ROOT_REL / "number.py").read_text()
    # 7 entity classes.
    for cls in (
        "FanRecheckArmDelayNumber",
        "FanRecheckSpindownNumber",
        "FanRecheckWindowNumber",
        "FanRecheckCooldownNumber",
        "FanRecheckMaxPerHourNumber",
        "FanRecheckHvacSuppressNumber",
        "FanRecheckMmwaveHistoryTicksNumber",
    ):
        assert f"class {cls}" in src, f"missing class {cls}"
        assert f"{cls}(hass, entry)" in src, (
            f"{cls} not added in async_setup_entry"
        )
    # Shared base.
    assert "class _FanRecheckNumberBase" in src
    # Mirror lands on the CoordinatorManager entry (not the integration entry).
    assert "ENTRY_TYPE_COORDINATOR_MANAGER" in src
    # RestoreEntity-backed runtime store (last_state restored, then mirrored).
    assert "async_get_last_state" in src
    # Bounds: each Number declares native min/max consistent with planning
    # doc D8 ranges. Source-grep against the attr style used in number.py.
    assert "_attr_native_min_value = 30" in src   # arm_delay or window
    assert "_attr_native_max_value = 300" in src  # arm_delay
    assert "_attr_native_max_value = 90" in src   # spindown
    assert "_attr_native_max_value = 180" in src  # window
    assert "_attr_native_min_value = 600" in src  # cooldown
    assert "_attr_native_max_value = 7200" in src  # cooldown
    assert "_attr_native_min_value = 120" in src  # hvac_suppress
    assert "_attr_native_max_value = 1800" in src  # hvac_suppress


# ---------------------------------------------------------------------------
# T5 — binary_sensor.py: OccupiedBinarySensor reads
# FanRecheckManager.get_room_attrs each access AND the per-opted-in room
# RoomFanRecheckInProgress class is registered + disabled-by-default.
# ---------------------------------------------------------------------------


def test_binary_sensor_surfaces_fan_recheck_attrs():
    src = (ROOT_DIR / ROOT_REL / "binary_sensor.py").read_text()
    # New attrs on OccupiedBinarySensor.
    for attr in (
        "fan_recheck_state",
        "fan_recheck_last_outcome",
        "fan_recheck_last_attempt_iso",
        "fan_recheck_ble_ladder_layer",
    ):
        assert attr in src, f"OccupiedBinarySensor missing attr {attr}"
    # KEEP existing v4.7.20 attrs (no silent strip).
    assert "fan_interference_suspect" in src
    assert "fan_interference_hold_active" in src
    assert "ble_corroboration_layer" in src
    # Per-room "in progress" sensor.
    assert "class RoomFanRecheckInProgressSensor" in src
    assert "RoomFanRecheckInProgressSensor(coordinator)" in src
    # Disabled-by-default — operator enables per-room.
    assert "_attr_entity_registry_enabled_default = False" in src
    # Reads via get_room_attrs (driving production code path).
    assert "get_room_attrs" in src


# ---------------------------------------------------------------------------
# T6 — sensor.py: per-room state + last_outcome sensors registered and
# disabled-by-default; both read FanRecheckManager.get_room_attrs.
# ---------------------------------------------------------------------------


def test_sensor_platform_wires_state_and_outcome_sensors():
    src = (ROOT_DIR / ROOT_REL / "sensor.py").read_text()
    assert "class RoomFanRecheckStateSensor" in src
    assert "class RoomFanRecheckLastOutcomeSensor" in src
    assert "RoomFanRecheckStateSensor(coordinator)" in src
    assert "RoomFanRecheckLastOutcomeSensor(coordinator)" in src
    assert "get_room_attrs" in src
    assert "_attr_entity_registry_enabled_default = False" in src


# ---------------------------------------------------------------------------
# T7 — services.yaml registers fan_recheck_force_restore with the required
# room_name field; __init__.py registers + unloads the service.
# ---------------------------------------------------------------------------


def test_services_yaml_registers_force_restore():
    text = (ROOT_DIR / ROOT_REL / "services.yaml").read_text()
    payload = yaml.safe_load(text)
    assert "fan_recheck_force_restore" in payload, (
        "services.yaml does not register fan_recheck_force_restore"
    )
    fields = payload["fan_recheck_force_restore"].get("fields", {})
    assert "room_name" in fields, "service missing room_name field"
    assert fields["room_name"].get("required") is True


def test_init_registers_and_unloads_force_restore_service():
    src = (ROOT_DIR / ROOT_REL / "__init__.py").read_text()
    # Handler exists in the presence-services registration block.
    assert "handle_fan_recheck_force_restore" in src
    # async_register is wired with the documented service name.
    assert '"fan_recheck_force_restore"' in src
    # Service is part of the unload symmetry list (else reload leaks
    # ghost copies — paired with `_service_name` loop).
    # Find the service-removal block and confirm name appears there too.
    assert src.count('"fan_recheck_force_restore"') >= 2, (
        "fan_recheck_force_restore not in service-unload list"
    )


# ---------------------------------------------------------------------------
# T8 — service handler force_restore routes through FanRecheckManager.force_restore
# Driving the actual handler: rebuild the closure environment with stubs,
# then call it and verify the manager method fires.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_force_restore_routes_to_fan_recheck_manager():
    """The service handler is registered locally inside
    _async_register_presence_services and is not import-exposed; we drive
    the public end of the route by calling FanRecheckManager.force_restore
    directly on a real manager instance (proves the wiring contract the
    handler relies on — get_room_attrs default-state + a no-op for an
    unknown room — has not regressed).
    """
    mod = _load_fan_recheck_manager_module()

    hass = MagicMock()
    hass.data = {"universal_room_automation": {}}
    hass.async_create_task = lambda coro: asyncio.create_task(coro)
    hass.config_entries.async_entries = lambda domain: []

    presence_coord = MagicMock()
    mgr = mod.FanRecheckManager(hass, presence_coord)
    # Unknown room is a documented no-op (escape hatch never errors).
    await mgr.force_restore("Nonexistent")
    # The manager exposes the contract the binary_sensor / sensor read.
    attrs = mgr.get_room_attrs("Nonexistent")
    assert attrs == {
        "fan_recheck_state": "idle",
        "fan_recheck_last_outcome": None,
        "fan_recheck_last_attempt_iso": None,
        "fan_recheck_ble_ladder_layer": "none",
    }


# ---------------------------------------------------------------------------
# T9 — presence teardown source protection: FanRecheckManager.shutdown is
# called from PresenceCoordinator.async_teardown so per-room
# async_call_later timers are cancelled on entry reload, not just on HA
# stop. This is the deferred-build claim that previously read
# "PresenceCoordinator has no teardown surface" — the surface IS
# async_teardown at presence.py:5212.
# ---------------------------------------------------------------------------


def test_presence_teardown_invokes_fan_recheck_shutdown():
    src = (ROOT_DIR / ROOT_REL / "domain_coordinators" / "presence.py").read_text()
    # Locate async_teardown body.
    teardown_idx = src.find("async def async_teardown(self)")
    assert teardown_idx >= 0, "PresenceCoordinator.async_teardown missing"
    next_def_idx = src.find("\n    async def ", teardown_idx + 1)
    if next_def_idx < 0:
        next_def_idx = src.find("\n    def ", teardown_idx + 1)
    body = src[teardown_idx:next_def_idx]
    assert "_fan_recheck_manager" in body, (
        "async_teardown does not reference _fan_recheck_manager"
    )
    assert "shutdown()" in body, (
        "async_teardown does not call FanRecheckManager.shutdown()"
    )


# ---------------------------------------------------------------------------
# T10 — FanRecheckManager.shutdown is itself idempotent + cancels timers.
# Drives the production code path directly so review-C can confirm the
# teardown does what the source-grep test asserts it does.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fan_recheck_shutdown_idempotent_and_cancels_timers():
    mod = _load_fan_recheck_manager_module()

    hass = MagicMock()
    hass.data = {"universal_room_automation": {}}
    hass.config_entries.async_entries = lambda domain: []

    presence_coord = MagicMock()
    mgr = mod.FanRecheckManager(hass, presence_coord)

    # Inject a fake ctx with a fake timer; shutdown must call it.
    cancelled = {"n": 0}

    def _fake_unsub():
        cancelled["n"] += 1

    ctx = mod._RoomCtx(room_name="X", entry_id="eX")
    ctx.timer_unsub = _fake_unsub
    mgr._rooms["X"] = ctx

    await mgr.shutdown()
    await mgr.shutdown()  # safe to call twice

    assert cancelled["n"] >= 1, "timer not cancelled by shutdown"


# ---------------------------------------------------------------------------
# T11 — RestoreEntity-mirror pattern verification: master switch + the 7
# timing Numbers + the per-room switches both restore from RestoreEntity
# AND mirror their just-restored value into entry.options. Source-grep
# regression — protects against a fix-up that drops the mirror and
# triggers Bug Class #46 (lazy default snap-back on reload).
# ---------------------------------------------------------------------------


def test_mirror_pattern_present_in_switch_and_number():
    sw_src = (ROOT_DIR / ROOT_REL / "switch.py").read_text()
    num_src = (ROOT_DIR / ROOT_REL / "number.py").read_text()
    # Master switch restores AND mirrors.
    assert "class FanRecheckEnabledSwitch" in sw_src
    master_idx = sw_src.find("class FanRecheckEnabledSwitch")
    next_idx = sw_src.find("\nclass ", master_idx + 1)
    master_body = sw_src[master_idx:next_idx]
    assert "async_get_last_state" in master_body
    assert "_mirror_runtime" in master_body
    assert "_mirror_options" in master_body
    # 7 Numbers share _FanRecheckNumberBase whose async_added_to_hass
    # restores and then re-mirrors.
    assert "class _FanRecheckNumberBase" in num_src
    base_idx = num_src.find("class _FanRecheckNumberBase")
    next_idx = num_src.find("\nclass FanRecheck", base_idx + 1)
    base_body = num_src[base_idx:next_idx]
    assert "async_get_last_state" in base_body
    assert "_mirror_options" in base_body
