"""ONBOARDING-SIMPLIFY-1 Tier-3 fix-up — mutation-anchored tests.

Each production fix (P1..P8, T1..T7) has an anchor test that goes RED
when the load-bearing production site is neutered. Tests drive the flow
methods (or their voluptuous schemas) — no source greps for behavior.
"""
from __future__ import annotations

import asyncio
import importlib
import sys
import types
from types import SimpleNamespace
from unittest.mock import MagicMock, AsyncMock

import pytest

_cbcf = importlib.import_module("test_cycle_b_config_flow")
_cf = _cbcf._cf
_make_config_flow = _cbcf._make_config_flow

CONF_ROOM_NAME = _cf.CONF_ROOM_NAME
CONF_ROOM_TYPE = _cf.CONF_ROOM_TYPE
CONF_AREA_ID = _cf.CONF_AREA_ID
CONF_WET_ROOM = _cf.CONF_WET_ROOM
CONF_ROOM_IS_GUEST_ROOM = _cf.CONF_ROOM_IS_GUEST_ROOM
CONF_MOTION_SENSORS = _cf.CONF_MOTION_SENSORS
CONF_OCCUPANCY_SENSORS = _cf.CONF_OCCUPANCY_SENSORS
CONF_MMWAVE_SENSORS = _cf.CONF_MMWAVE_SENSORS
CONF_TEMPERATURE_SENSOR = _cf.CONF_TEMPERATURE_SENSOR
CONF_HUMIDITY_SENSOR = _cf.CONF_HUMIDITY_SENSOR
CONF_ILLUMINANCE_SENSOR = _cf.CONF_ILLUMINANCE_SENSOR
CONF_DOOR_SENSORS = _cf.CONF_DOOR_SENSORS
CONF_WATER_LEAK_SENSOR = _cf.CONF_WATER_LEAK_SENSOR
CONF_LIGHTS = _cf.CONF_LIGHTS
CONF_AUTO_SWITCHES = _cf.CONF_AUTO_SWITCHES
CONF_FANS = _cf.CONF_FANS
CONF_COVERS = _cf.CONF_COVERS
CONF_HUMIDITY_FANS = _cf.CONF_HUMIDITY_FANS
CONF_LIGHT_CAPABILITIES = _cf.CONF_LIGHT_CAPABILITIES
CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_ENABLED = _cf.CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_ENABLED
CONF_HUMIDITY_FAN_SPIKE_ENABLED = _cf.CONF_HUMIDITY_FAN_SPIKE_ENABLED
CONF_ENTRY_TYPE = _cf.CONF_ENTRY_TYPE
CONF_INTEGRATION_ENTRY_ID = _cf.CONF_INTEGRATION_ENTRY_ID
ENTRY_TYPE_INTEGRATION = _cf.ENTRY_TYPE_INTEGRATION
ENTRY_TYPE_ROOM = _cf.ENTRY_TYPE_ROOM
ROOM_TYPE_BATHROOM = _cf.ROOM_TYPE_BATHROOM
ROOM_TYPE_BEDROOM = _cf.ROOM_TYPE_BEDROOM
ROOM_TYPE_GENERIC = _cf.ROOM_TYPE_GENERIC


# ---------------------------------------------------------------------------
# Registry / hass fakes
# ---------------------------------------------------------------------------

def _reg_entry(entity_id, domain, *, device_id=None, area_id=None,
               disabled_by=None, hidden_by=None, entity_category=None,
               platform="mqtt", original_device_class=None, device_class=None):
    return SimpleNamespace(
        entity_id=entity_id, domain=domain, device_id=device_id,
        area_id=area_id, disabled_by=disabled_by, hidden_by=hidden_by,
        entity_category=entity_category, platform=platform,
        original_device_class=original_device_class, device_class=device_class,
    )


class _FakeEntReg:
    def __init__(self, entries):
        self.entities = {e.entity_id: e for e in entries}

    def async_get(self, eid):
        return self.entities.get(eid)


class _FakeDevReg:
    def __init__(self, devices=None):
        self._d = devices or {}

    def async_get(self, dev_id):
        return self._d.get(dev_id)


def _install_registries(entries, devices=None):
    ent_reg = _FakeEntReg(entries)
    dev_reg = _FakeDevReg(devices)
    for parent in ("homeassistant", "homeassistant.helpers"):
        if parent not in sys.modules:
            sys.modules[parent] = types.ModuleType(parent)
    for name, obj in (
        ("homeassistant.helpers.entity_registry", ent_reg),
        ("homeassistant.helpers.device_registry", dev_reg),
    ):
        mod = sys.modules.get(name) or types.ModuleType(name)
        mod.async_get = lambda hass, _o=obj: _o
        sys.modules[name] = mod
        parent = sys.modules["homeassistant.helpers"]
        setattr(parent, name.rsplit(".", 1)[-1], mod)
    return ent_reg, dev_reg


class _FakeIntegrationHass:
    """Records flow.async_init calls; synthesizes a House entry so the
    caller's `async_entries` lookup finds it."""
    def __init__(self):
        self._states = {}
        self.states = MagicMock()
        self.states.get = lambda eid: self._states.get(eid)
        self.states.async_entity_ids = MagicMock(return_value=[])
        self.services = MagicMock()
        self.services.async_services = MagicMock(return_value={})
        self.services.async_call = AsyncMock(return_value=None)
        self.config_entries = MagicMock()
        self._entries: list = []
        self.config_entries.async_entries = MagicMock(
            side_effect=lambda *_a, **_k: list(self._entries)
        )
        self.flow_init_calls: list = []

        async def _async_init(domain, *, context=None, data=None):
            self.flow_init_calls.append({
                "domain": domain, "context": context, "data": data,
            })
            if (data or {}).get(CONF_ENTRY_TYPE) == ENTRY_TYPE_INTEGRATION:
                self._entries.append(SimpleNamespace(
                    entry_id=f"house_{len(self._entries)}",
                    data=dict(data), options={}, title="🏠 Home",
                ))
            return {"type": "create_entry", "title": "🏠 Home"}

        self.config_entries.flow = MagicMock()
        self.config_entries.flow.async_init = _async_init


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _schema_map(result):
    return {str(k): (k, v) for k, v in result["data_schema"].schema.items()}


# ===========================================================================
# P1 — D-CRIT-1 zero-House dead path
# ===========================================================================

def test_first_run_house_exists_before_room_committed():
    """P1: after energy_setup submits, the House entry EXISTS in the
    registry BEFORE any room is committed. Neutering the eager
    `_mint_house_now` call in async_step_energy_setup makes this RED.
    """
    _install_registries([])
    hass = _FakeIntegrationHass()
    flow = _make_config_flow(hass=hass)
    flow._integration_data = {"electricity_rate": 0.12}
    r = _run(flow.async_step_energy_setup(user_input={}))
    # The step routes to add_first_room (menu); the salient invariant is:
    assert len(hass.flow_init_calls) == 1, (
        "P1: House must be minted eagerly after energy_setup, before any room."
    )
    assert hass.flow_init_calls[0]["context"] == {"source": "integration_create"}
    assert any(
        e.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_INTEGRATION
        for e in hass._entries
    ), "House entry not present in registry after energy_setup"


def test_first_run_no_occupancy_sensor_still_installs():
    """P1 D-CRIT-1 repro: the operator submits energy_setup then never
    provides an occupancy sensor. Old behavior: dead path — no config
    entries created. Fixed behavior: House exists regardless."""
    _install_registries([])
    hass = _FakeIntegrationHass()
    flow = _make_config_flow(hass=hass)
    flow._integration_data = {"electricity_rate": 0.12}
    _run(flow.async_step_energy_setup(user_input={}))
    # Even if the operator now enters sensors_confirm and cannot satisfy
    # the occupancy guard, House already exists.
    house_present = [
        e for e in hass._entries
        if e.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_INTEGRATION
    ]
    assert len(house_present) == 1, (
        "D-CRIT-1: first run must leave a House entry even with no rooms."
    )


def test_first_run_skip_rooms_reachable_via_route():
    """P1: 'Skip — add rooms later' is a REACHABLE menu option off
    add_first_room. Driving the route: energy_setup -> add_first_room
    menu -> skip_rooms_later -> abort (House already minted eagerly)."""
    _install_registries([])
    hass = _FakeIntegrationHass()
    flow = _make_config_flow(hass=hass)
    flow._integration_data = {"electricity_rate": 0.12}
    _run(flow.async_step_energy_setup(user_input={}))
    menu = _run(flow.async_step_add_first_room())
    assert menu["type"] == "menu"
    assert "skip_rooms_later" in menu["menu_options"], (
        "P1: 'skip_rooms_later' must be a reachable menu option."
    )
    abort = _run(flow.async_step_skip_rooms_later())
    assert abort["type"] == "abort"
    # And the House exists (was minted eagerly), so total = 1.
    house_present = [
        e for e in hass._entries
        if e.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_INTEGRATION
    ]
    assert len(house_present) == 1


def test_house_minted_exactly_once_on_full_first_run():
    """P1 single-mint: House is minted eagerly at energy_setup; the
    subsequent room_summary must NOT re-mint (idempotent guard)."""
    _install_registries([
        _reg_entry("binary_sensor.mo", "binary_sensor", area_id="a1",
                   original_device_class="motion"),
    ])
    hass = _FakeIntegrationHass()
    flow = _make_config_flow(hass=hass)
    flow._integration_data = {"electricity_rate": 0.12}
    _run(flow.async_step_energy_setup(user_input={}))
    _run(flow.async_step_room_setup(user_input={
        CONF_ROOM_NAME: "R1", CONF_ROOM_TYPE: ROOM_TYPE_BEDROOM,
        CONF_AREA_ID: "a1",
    }))
    _run(flow.async_step_room_class(user_input={
        CONF_WET_ROOM: False, CONF_ROOM_IS_GUEST_ROOM: False,
    }))
    _run(flow.async_step_sensors_confirm(user_input={
        CONF_MOTION_SENSORS: ["binary_sensor.mo"],
    }))
    _run(flow.async_step_devices_confirm(user_input={}))
    result = _run(flow.async_step_room_summary(user_input={}))
    assert result["type"] == "create_entry"
    house_entries = [
        e for e in hass._entries
        if e.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_INTEGRATION
    ]
    assert len(house_entries) == 1, (
        f"P1 single-mint violated: {len(house_entries)} House entries created."
    )


# ===========================================================================
# P2 — CONF_LIGHT_CAPABILITIES restored on create path
# ===========================================================================

def test_create_persists_light_capabilities():
    """P2: a color light on the create path -> data[CONF_LIGHT_CAPABILITIES]=='full'.
    Neutering the `_detect_light_capabilities` call in devices_confirm makes
    this RED (the key never lands in _data)."""
    _install_registries([
        _reg_entry("light.color_bulb", "light", area_id="a1"),
    ])
    hass = _cbcf._FakeHass()
    hass._states["light.color_bulb"] = SimpleNamespace(
        attributes={"supported_features": 16}
    )
    flow = _make_config_flow(hass=hass)
    flow._data.update({
        CONF_ROOM_NAME: "R", CONF_ROOM_TYPE: ROOM_TYPE_BEDROOM,
        CONF_AREA_ID: "a1",
    })
    _run(flow.async_step_devices_confirm(user_input={
        CONF_LIGHTS: ["light.color_bulb"],
    }))
    result = _run(flow.async_step_room_summary(user_input={}))
    assert result["data"].get(CONF_LIGHT_CAPABILITIES) == "full", (
        "P2: light capabilities should be auto-detected as 'full' for a color bulb."
    )


# ===========================================================================
# P3 — bathroom seeds CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_ENABLED
# ===========================================================================

def test_bathroom_seeds_humidity_fan_presence_runtime():
    """P3: bathroom room-type seed writes
    CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_ENABLED=True. Removing the
    ROOM_TYPE_FEATURE_DEFAULTS[BATHROOM] row entry makes this RED."""
    _install_registries([
        _reg_entry("binary_sensor.mo", "binary_sensor", area_id="a1",
                   original_device_class="motion"),
    ])
    flow = _make_config_flow()
    flow._data.update({
        CONF_ROOM_NAME: "Bath", CONF_ROOM_TYPE: ROOM_TYPE_BATHROOM,
        CONF_AREA_ID: "a1",
    })
    result = _run(flow.async_step_room_summary(user_input={}))
    assert result["data"].get(CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_ENABLED) is True, (
        "P3: bathroom must seed CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_ENABLED=True."
    )


# ===========================================================================
# P4 — INV-2: cleared single-entity selector persists EMPTY (voluptuous route)
# ===========================================================================

def test_cleared_temperature_persists_empty_through_voluptuous_route():
    """P4 INV-2: build the sensors_confirm data_schema (renders the
    `suggested_value` idiom), submit user_input WITHOUT
    CONF_TEMPERATURE_SENSOR, then push through voluptuous — the resulting
    dict must NOT re-inject the guessed default. Mutation: change the
    single-entity Optional back to `default=guess` -> RED (voluptuous
    re-fills on submit)."""
    _install_registries([
        _reg_entry("binary_sensor.mo", "binary_sensor", area_id="a1",
                   original_device_class="motion"),
        _reg_entry("sensor.pref_temp", "sensor", area_id="a1",
                   original_device_class="temperature"),
    ])
    flow = _make_config_flow()
    flow._data.update({
        CONF_ROOM_NAME: "T", CONF_ROOM_TYPE: ROOM_TYPE_GENERIC,
        CONF_AREA_ID: "a1",
    })
    # First call renders the schema.
    form = _run(flow.async_step_sensors_confirm())
    schema = form["data_schema"]
    # Simulate a submit that CLEARED the temperature: user_input has
    # motion only. Run through voluptuous.
    submit = {CONF_MOTION_SENSORS: ["binary_sensor.mo"]}
    processed = schema(submit)
    assert CONF_TEMPERATURE_SENSOR not in processed or not processed.get(CONF_TEMPERATURE_SENSOR), (
        f"P4 INV-2: voluptuous re-injected default guess: {processed.get(CONF_TEMPERATURE_SENSOR)!r}"
    )


# ===========================================================================
# P5 — multi-select ranker keeps all same-device entities
# ===========================================================================

def test_ranker_multiselect_keeps_all_same_device_entities():
    """P5: 4-zone FP2 (all device_class=occupancy on ONE device_id) —
    multi-select bucket must return all 4. Mutation: route the multi-select
    bucket through the dedup path -> RED (only 1 winner returned)."""
    entries = [
        _reg_entry(f"binary_sensor.fp2_z{i}", "binary_sensor",
                   device_id="dev_fp2", area_id="a1",
                   original_device_class="occupancy")
        for i in range(4)
    ]
    _install_registries(entries)
    flow = _make_config_flow()
    eids = [e.entity_id for e in entries]
    out = flow._rank_area_candidates(eids, dedup=False)
    assert len(out) == 4, (
        f"P5: multi-select rank-only path must keep all 4 FP2 zones; got {out}"
    )
    # And the dedup path collapses to 1 (guard against accidental unification).
    dedupped = flow._rank_area_candidates(eids, dedup=True)
    assert len(dedupped) == 1, (
        f"P5 (control): dedup path must collapse same (device, class) group; got {dedupped}"
    )


# ===========================================================================
# P7 — switch-only room pre-fills AUTO_SWITCHES; water-leak on schema
# ===========================================================================

def test_switch_only_room_prefills_auto_switches():
    """P7: AV-Closet-style room (only actuator is a switch relay).
    devices_confirm must offer CONF_AUTO_SWITCHES pre-filled with area
    switches. Neutering the area_switches pre-fill -> RED (default=[])."""
    _install_registries([
        _reg_entry("switch.shelly_av", "switch", device_id="d_av",
                   area_id="a1"),
    ])
    flow = _make_config_flow()
    flow._data.update({
        CONF_ROOM_NAME: "AV", CONF_ROOM_TYPE: ROOM_TYPE_GENERIC,
        CONF_AREA_ID: "a1",
    })
    form = _run(flow.async_step_devices_confirm())
    schema = form["data_schema"]
    keys = {str(k): k for k in schema.schema}
    assert CONF_AUTO_SWITCHES in keys, (
        "P7: CONF_AUTO_SWITCHES must be on the devices_confirm schema."
    )
    default = keys[CONF_AUTO_SWITCHES].default()
    assert "switch.shelly_av" in (default or []), (
        f"P7: area switch not pre-filled; default={default!r}"
    )


def test_water_leak_sensor_on_sensors_confirm_schema():
    """P7: CONF_WATER_LEAK_SENSOR is on the sensors_confirm schema
    (safety path — dropped in Slice 2 by mistake)."""
    _install_registries([
        _reg_entry("binary_sensor.leak_1", "binary_sensor", area_id="a1",
                   original_device_class="moisture"),
    ])
    flow = _make_config_flow()
    flow._data.update({
        CONF_ROOM_NAME: "R", CONF_ROOM_TYPE: ROOM_TYPE_GENERIC,
        CONF_AREA_ID: "a1",
    })
    form = _run(flow.async_step_sensors_confirm())
    keys = {str(k) for k in form["data_schema"].schema}
    assert CONF_WATER_LEAK_SENSOR in keys, (
        "P7: CONF_WATER_LEAK_SENSOR must be on the sensors_confirm schema."
    )


# ===========================================================================
# P8 — House title
# ===========================================================================

def test_house_integration_title_is_home_emoji():
    """P8: async_step_integration_create titles the House as '🏠 Home'
    (pre-cycle behavior). Reverting to 'Universal Room Automation' RED."""
    hass = _FakeIntegrationHass()
    flow = _make_config_flow(hass=hass)
    result = _run(flow.async_step_integration_create(user_input={
        CONF_ENTRY_TYPE: ENTRY_TYPE_INTEGRATION,
    }))
    assert result["type"] == "create_entry"
    assert result["title"] == "🏠 Home", (
        f"P8: House title should be '🏠 Home', got {result['title']!r}"
    )


# ===========================================================================
# T3 — occupancy guard still fires with empty submit
# ===========================================================================

def test_area_detect_empty_occupancy_still_errors():
    """T3: async_step_sensors_confirm with an empty submit must return the
    `no_occupancy_sensors` error. Neutering the guard -> RED."""
    _install_registries([])
    flow = _make_config_flow()
    flow._data.update({
        CONF_ROOM_NAME: "R", CONF_ROOM_TYPE: ROOM_TYPE_GENERIC,
    })
    result = _run(flow.async_step_sensors_confirm(user_input={}))
    assert result["type"] == "form"
    assert result.get("errors", {}).get("base") == "no_occupancy_sensors"


# ===========================================================================
# T1 — ranker wire-in anchors (behavioral, not source-grep)
# ===========================================================================

def test_sensors_confirm_calls_ranker_and_uses_ranked_winner():
    """T1: the sensors_confirm temperature default is the RANKED winner,
    not a bare alphabetical head. Fixture: a denylisted sensor that sorts
    FIRST alphabetically vs a real temperature sensor that sorts LATER.
    Winner must be the real one — proves the denylist rung is live.
    Neutering `_ranked` (identity passthrough) -> RED."""
    _install_registries([
        # denylisted (linkquality) sorts BEFORE by ascii
        _reg_entry("sensor.a_linkquality", "sensor", area_id="a1",
                   original_device_class="temperature"),
        _reg_entry("sensor.z_room_temp", "sensor", area_id="a1",
                   original_device_class="temperature"),
    ])
    flow = _make_config_flow()
    flow._data.update({
        CONF_ROOM_NAME: "R", CONF_ROOM_TYPE: ROOM_TYPE_GENERIC,
        CONF_AREA_ID: "a1",
    })
    form = _run(flow.async_step_sensors_confirm())
    keys = {str(k): k for k in form["data_schema"].schema}
    marker = keys[CONF_TEMPERATURE_SENSOR]
    # suggested_value lives in the key's description dict; default() may
    # not be set (P4 idiom). Read description.
    desc = getattr(marker, "description", None) or {}
    suggested = desc.get("suggested_value")
    assert suggested == "sensor.z_room_temp", (
        f"T1: ranker not consulted (denylist rung dead); suggested={suggested!r}"
    )


# ===========================================================================
# T5 — explicit-False-wins SOFT-seed guard at room_summary
# ===========================================================================

def test_room_summary_seed_is_soft_explicit_false_wins():
    """T5: bathroom room, operator submitted CONF_WET_ROOM=False on
    room_class step -> room_summary must NOT overwrite with the seed's
    True. Mutation: hard-overwrite (drop the `if _k not in self._data`
    guard) -> RED."""
    _install_registries([])
    flow = _make_config_flow()
    flow._data.update({
        CONF_ROOM_NAME: "Powder", CONF_ROOM_TYPE: ROOM_TYPE_BATHROOM,
        CONF_WET_ROOM: False,  # operator explicit-False
    })
    result = _run(flow.async_step_room_summary(user_input={}))
    assert result["data"][CONF_WET_ROOM] is False, (
        "T5: SOFT seed overrode explicit operator False."
    )
