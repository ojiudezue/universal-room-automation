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
    if f"{coord_pkg_name}.house_state" not in sys.modules:
        src = ROOT_DIR / ROOT_REL / "domain_coordinators" / "house_state.py"
        spec = importlib.util.spec_from_file_location(
            f"{coord_pkg_name}.house_state", str(src),
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules[f"{coord_pkg_name}.house_state"] = mod
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
    # Default-ON per-room (find-and-disable). Master switch + sleep gate bound it.
    assert c.DEFAULT_ROOM_FAN_RECHECK_ENABLED is True
    assert c.CONF_FAN_RECHECK_L2_ALLOWED == "fan_recheck_l2_allowed"
    assert c.DEFAULT_FAN_RECHECK_L2_ALLOWED is True
    assert c.CONF_FAN_RECHECK_TRUST_SENSORS_OK == "fan_recheck_trust_sensors_ok"
    assert c.DEFAULT_FAN_RECHECK_TRUST_SENSORS_OK is True
    # 7 timing knobs with documented bounds.
    assert c.DEFAULT_FAN_RECHECK_ARM_DELAY_S == 60
    assert c.DEFAULT_FAN_RECHECK_SPINDOWN_S == 30
    assert c.DEFAULT_FAN_RECHECK_WINDOW_S == 60
    assert c.DEFAULT_FAN_RECHECK_COOLDOWN_S == 1800
    assert c.DEFAULT_FAN_RECHECK_MAX_PER_HOUR == 2
    assert c.DEFAULT_FAN_RECHECK_HVAC_SUPPRESS_S == 600
    assert c.DEFAULT_FAN_RECHECK_MMWAVE_HISTORY_TICKS == 3
    # Master switch stays default-OFF: the whole feature is opt-in at the
    # coordinator. Per-room flags default-ON so they're not inert once the
    # master is enabled (find-and-disable, not find-and-enable).
    assert c.DEFAULT_FAN_RECHECK_ENABLED is False
    assert c.DEFAULT_ROOM_FAN_RECHECK_ENABLED is True


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
# T4 — number.py source protection: the 7 timing Number entities have been
# DELETED. They now live as options-flow form fields inside a collapsed
# "Advanced" section on the coordinator_presence step. CONF_/DEFAULT_ names
# still exist in const.py (options flow + _timing_config() still use them).
# ---------------------------------------------------------------------------


def test_number_platform_no_longer_registers_seven_timing_numbers():
    src = (ROOT_DIR / ROOT_REL / "number.py").read_text()
    # 7 entity classes must NOT exist anywhere in number.py.
    for cls in (
        "FanRecheckArmDelayNumber",
        "FanRecheckSpindownNumber",
        "FanRecheckWindowNumber",
        "FanRecheckCooldownNumber",
        "FanRecheckMaxPerHourNumber",
        "FanRecheckHvacSuppressNumber",
        "FanRecheckMmwaveHistoryTicksNumber",
    ):
        assert f"class {cls}" not in src, f"deleted class {cls} still present"
        assert f"{cls}(hass, entry)" not in src, (
            f"{cls} still registered in async_setup_entry"
        )
    # Shared base also gone.
    assert "class _FanRecheckNumberBase" not in src


def test_init_cleans_up_orphan_fan_recheck_number_registry_entries():
    """The 7 deleted FanRecheck*Number unique_ids must be removed from
    the entity registry once per integration entry (run-once flag
    `fan_recheck_number_cleanup_done`). Precedent: safety_alert dedup
    block at __init__.py:740."""
    src = (ROOT_DIR / ROOT_REL / "__init__.py").read_text()
    assert "fan_recheck_number_cleanup_done" in src
    for uid_suffix in (
        "fan_recheck_arm_delay_s",
        "fan_recheck_spindown_s",
        "fan_recheck_window_s",
        "fan_recheck_cooldown_s",
        "fan_recheck_max_per_hour",
        "fan_recheck_hvac_suppress_s",
        "fan_recheck_mmwave_history_ticks",
    ):
        assert uid_suffix in src, (
            f"cleanup migration missing unique_id suffix {uid_suffix}"
        )
    # Routed through entity_registry.async_remove (the precedent pattern).
    assert "ent_reg.async_remove(eid)" in src


def test_const_still_exposes_seven_timing_conf_keys():
    """Options-flow + _timing_config still consume the 7 CONF_/DEFAULT_
    names — they MUST remain in const.py even though the Number entities
    were deleted."""
    c = _load_const()
    for pair in (
        ("CONF_FAN_RECHECK_ARM_DELAY_S", "DEFAULT_FAN_RECHECK_ARM_DELAY_S"),
        ("CONF_FAN_RECHECK_SPINDOWN_S", "DEFAULT_FAN_RECHECK_SPINDOWN_S"),
        ("CONF_FAN_RECHECK_WINDOW_S", "DEFAULT_FAN_RECHECK_WINDOW_S"),
        ("CONF_FAN_RECHECK_COOLDOWN_S", "DEFAULT_FAN_RECHECK_COOLDOWN_S"),
        ("CONF_FAN_RECHECK_MAX_PER_HOUR", "DEFAULT_FAN_RECHECK_MAX_PER_HOUR"),
        ("CONF_FAN_RECHECK_HVAC_SUPPRESS_S", "DEFAULT_FAN_RECHECK_HVAC_SUPPRESS_S"),
        ("CONF_FAN_RECHECK_MMWAVE_HISTORY_TICKS",
         "DEFAULT_FAN_RECHECK_MMWAVE_HISTORY_TICKS"),
    ):
        for name in pair:
            assert hasattr(c, name), f"const.{name} missing"


def test_config_flow_collapses_timing_knobs_into_advanced_section():
    """The 7 timing knobs are wrapped in a collapsed section on the
    coordinator_presence options step."""
    src = (ROOT_DIR / ROOT_REL / "config_flow.py").read_text()
    # section helper imported on this step.
    assert "from homeassistant.data_entry_flow import section" in src
    # Collapsed section key + collapsed flag wired on the coordinator step.
    assert '"fan_recheck_advanced"' in src
    assert '{"collapsed": True}' in src
    # Master enable still visible at top-level (outside the section).
    assert "CONF_FAN_RECHECK_ENABLED" in src
    # Flatten path persists the section keys at top-level entry.options
    # (verifies submit-handler integrity — Change 2 depends on this).
    assert 'user_input.pop("fan_recheck_advanced"' in src


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
        # Observability counters (RAM-only, since-boot) added by the
        # fan-recheck-observability cycle. Empty for an unknown room.
        "fan_recheck_eval_count": 0,
        "fan_recheck_veto_counts": {},
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
    # Master switch restores AND mirrors. Per-room switches and the master
    # toggle still own the RestoreEntity/mirror discipline — only the 7
    # timing Number entities were removed (now options-flow form fields).
    assert "class FanRecheckEnabledSwitch" in sw_src
    master_idx = sw_src.find("class FanRecheckEnabledSwitch")
    next_idx = sw_src.find("\nclass ", master_idx + 1)
    master_body = sw_src[master_idx:next_idx]
    assert "async_get_last_state" in master_body
    assert "_mirror_runtime" in master_body
    assert "_mirror_options" in master_body
    # The shared _FanRecheckNumberBase + 7 subclasses were intentionally
    # removed. Confirm the absence (sister to
    # test_number_platform_no_longer_registers_seven_timing_numbers).
    assert "class _FanRecheckNumberBase" not in num_src
