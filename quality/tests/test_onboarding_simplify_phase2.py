"""ONBOARDING-SIMPLIFY-1 phase 2 — S1 Simple House form, S2 rooms from
areas (bulk), S3 Simple single-room chain, S4 dead ends.

Plan: docs/planning/PLANNING_onboarding_simplify_phase2.md (incl. the
plan-review findings 1-6). Tests drive the production flow methods through
the shared mocked-HA harness (test_cycle_b_config_flow). Advanced-field
hiding is asserted on the RENDERED schema (finding 1): the harness binds a
replica of HA's ``FlowHandler.add_suggested_values_to_schema`` advanced
drop (homeassistant/data_entry_flow.py:660-667), which the production
``_filter_advanced`` routes through.
"""
from __future__ import annotations

import ast
import asyncio
import importlib
import json
import logging
import pathlib
import sys
import time
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import voluptuous as vol

_cbcf = importlib.import_module("test_cycle_b_config_flow")
_cf = _cbcf._cf
_make_config_flow = _cbcf._make_config_flow
_const = importlib.import_module("const")

_COMPONENT = (
    pathlib.Path(__file__).resolve().parents[2]
    / "custom_components" / "universal_room_automation"
)

C = _cf  # constants re-exported through the config_flow module namespace


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------

def _reg(entity_id, *, area_id="a1", device_id=None, dc=None, platform="mqtt"):
    return SimpleNamespace(
        entity_id=entity_id, domain=entity_id.split(".")[0], device_id=device_id,
        area_id=area_id, disabled_by=None, hidden_by=None, entity_category=None,
        platform=platform, original_device_class=dc, device_class=None,
    )


class _EntReg:
    def __init__(self, entries):
        self.entities = {e.entity_id: e for e in entries}

    def async_get(self, eid):
        return self.entities.get(eid)


class _DevReg:
    def async_get(self, _dev_id):
        return None


class _AreaReg:
    def __init__(self, areas):
        self._areas = [SimpleNamespace(id=k, name=v) for k, v in areas.items()]

    def async_list_areas(self):
        return list(self._areas)


@pytest.fixture
def install(monkeypatch):
    """Install fake entity / device / area registries (restored after)."""

    def _install(entries, areas=None):
        ha = types.ModuleType("homeassistant")
        helpers = types.ModuleType("homeassistant.helpers")
        ha.helpers = helpers
        regs = {
            "entity_registry": _EntReg(entries),
            "device_registry": _DevReg(),
            "area_registry": _AreaReg(areas or {}),
        }
        monkeypatch.setitem(sys.modules, "homeassistant", ha)
        monkeypatch.setitem(sys.modules, "homeassistant.helpers", helpers)
        for name, obj in regs.items():
            mod = types.ModuleType(f"homeassistant.helpers.{name}")
            mod.async_get = lambda hass, _o=obj: _o
            setattr(helpers, name, mod)
            monkeypatch.setitem(sys.modules, f"homeassistant.helpers.{name}", mod)

    return _install


def _ha_filter(flow):
    """Replica of HA FlowHandler.add_suggested_values_to_schema's advanced
    drop (data_entry_flow.py:660-667), bound to the flow."""

    def add_suggested_values_to_schema(schema, _suggested):
        return vol.Schema({
            k: v for k, v in schema.schema.items()
            if not (
                isinstance(k, vol.Marker)
                and isinstance(k.description, dict)
                and k.description.get("advanced")
                and not flow.show_advanced_options
            )
        })

    return add_suggested_values_to_schema


class _Hass:
    """Hass fake: entries, notify services, persons, and a flow manager
    that runs internal child flows through the production steps."""

    def __init__(self, *, notify=None, persons=None, fail_names=()):
        self._states = {}
        self.states = MagicMock()
        self.states.get = lambda eid: self._states.get(eid)
        self.states.async_entity_ids = MagicMock(
            side_effect=lambda domain=None: list(persons or []) if domain == "person" else []
        )
        self.services = MagicMock()
        self.services.async_services = MagicMock(
            return_value={"notify": {n: None for n in (notify or [])}} if notify else {}
        )
        self.services.async_call = AsyncMock(return_value=None)
        self.data = {}
        self._entries: list = []
        self.fail_names = set(fail_names)
        self.flow_init_calls: list = []
        self.config_entries = MagicMock()
        self.config_entries.async_entries = MagicMock(
            side_effect=lambda *_a, **_k: list(self._entries)
        )
        self.config_entries.flow = MagicMock()
        self.config_entries.flow.async_init = self._async_init

    async def _async_init(self, domain, *, context=None, data=None):
        self.flow_init_calls.append({"context": context, "data": data})
        source = (context or {}).get("source")
        if source == "integration_create":
            self._entries.append(SimpleNamespace(
                entry_id="house_1", data=dict(data), options={}, title="Home",
            ))
            return {"type": "create_entry"}
        if source == "room_bulk_create":
            if data.get(C.CONF_ROOM_NAME) in self.fail_names:
                raise RuntimeError("setup blew up")
            child = _make_config_flow(hass=self)
            result = await child.async_step_room_bulk_create(dict(data))
            if result["type"] == "create_entry":
                self._entries.append(SimpleNamespace(
                    entry_id=f"room_{len(self._entries)}",
                    data=dict(result["data"]), options={}, title=result["title"],
                ))
            return result
        raise AssertionError(f"unexpected source {source}")

    def rooms(self):
        return [e for e in self._entries
                if e.data.get(C.CONF_ENTRY_TYPE) == C.ENTRY_TYPE_ROOM]


def _flow(hass, advanced=False):
    flow = _make_config_flow(hass=hass)
    flow.show_advanced_options = advanced
    flow.add_suggested_values_to_schema = _ha_filter(flow)
    return flow


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _keys(result):
    return {str(k) for k in result["data_schema"].schema}


def _untouched(result) -> dict:
    """What the HA frontend submits for a form the operator does not edit:
    defaults, plus suggested values for fields that have one."""
    out = {}
    for marker in result["data_schema"].schema:
        default = getattr(marker, "default", vol.UNDEFINED)
        if default is not vol.UNDEFINED:
            out[str(marker)] = default() if callable(default) else default
            continue
        desc = marker.description if isinstance(marker.description, dict) else {}
        if desc.get("suggested_value"):
            out[str(marker)] = desc["suggested_value"]
    return out


# Area fixture used by S2 / S3 tests.
_AREAS = {"a1": "Guest Bath", "a2": "Office", "a3": "Storage"}


def _area_entities():
    return [
        _reg("binary_sensor.bath_motion", dc="motion", device_id="d1"),
        _reg("sensor.bath_temp", dc="temperature", device_id="d1"),
        _reg("binary_sensor.bath_door", dc="door", device_id="d2"),
        _reg("light.bath_ceiling", device_id="d3"),
        _reg("switch.bath_relay", device_id="d4"),
        _reg("binary_sensor.office_occ", area_id="a2", dc="occupancy", device_id="d5"),
        _reg("light.office_lamp", area_id="a2", device_id="d6"),
        # a3 "Storage" has a light but no motion / occupancy sensor
        _reg("light.storage", area_id="a3", device_id="d7"),
    ]


# ===========================================================================
# S1 — Simple House form
# ===========================================================================

_S1_SHOWN = {C.CONF_WEATHER_ENTITY, C.CONF_TRACKED_PERSONS, C.CONF_NOTIFY_TARGET}


def test_house_simple_shows_three_fields(install):
    install([])
    hass = _Hass(notify=["mobile_app_pixel"])
    simple = _run(_flow(hass).async_step_integration_config())
    assert _keys(simple) == _S1_SHOWN
    full = _run(_flow(hass, advanced=True).async_step_integration_config())
    assert len(_keys(full)) == 11
    assert _S1_SHOWN < _keys(full)


def test_house_simple_hidden_fields_store_defaults(install):
    """INV-C incl. the Required electricity rate."""
    install([])
    hass = _Hass()
    flow = _flow(hass)
    _run(flow.async_step_integration_config(user_input={}))
    house = [e for e in hass._entries
             if e.data.get(C.CONF_ENTRY_TYPE) == C.ENTRY_TYPE_INTEGRATION]
    assert len(house) == 1
    data = house[0].data
    assert data[C.CONF_ELECTRICITY_RATE] == _const.DEFAULT_ELECTRICITY_RATE
    assert data[C.CONF_PERSON_DATA_RETENTION] == _const.DEFAULT_PERSON_DATA_RETENTION
    assert data[C.CONF_TRANSITION_DETECTION_WINDOW] == _const.DEFAULT_TRANSITION_WINDOW
    assert data[C.CONF_NOTIFY_LEVEL] == _const.NOTIFY_LEVEL_ERRORS
    for absent in (C.CONF_OUTSIDE_TEMP_SENSOR, C.CONF_OUTSIDE_HUMIDITY_SENSOR,
                   C.CONF_SOLAR_PRODUCTION_SENSOR, C.CONF_NOTIFY_SERVICE):
        assert absent not in data, absent


def test_house_people_prefill_all_persons(install):
    install([])
    hass = _Hass(persons=["person.b", "person.a"])
    result = _run(_flow(hass).async_step_integration_config())
    marker = next(m for m in result["data_schema"].schema
                  if str(m) == C.CONF_TRACKED_PERSONS)
    assert marker.default() == ["person.a", "person.b"]


def test_house_phone_prefilled_when_one_mobile_app(install):
    install([])
    hass = _Hass(notify=["mobile_app_pixel", "persistent_notification"])
    result = _run(_flow(hass).async_step_integration_config())
    marker = next(m for m in result["data_schema"].schema
                  if str(m) == C.CONF_NOTIFY_TARGET)
    assert marker.description["suggested_value"] == "notify.mobile_app_pixel"


def test_energy_setup_skipped_in_simple(install):
    install([])
    hass = _Hass()
    simple = _run(_flow(hass).async_step_integration_config(user_input={}))
    assert simple["type"] == "menu" and simple["step_id"] == "add_first_room"
    assert len(hass.flow_init_calls) == 1  # House minted
    hass2 = _Hass()
    adv = _run(_flow(hass2, advanced=True).async_step_integration_config(
        user_input={C.CONF_ELECTRICITY_RATE: 0.2}))
    assert adv["type"] == "form" and adv["step_id"] == "energy_setup"
    assert hass2.flow_init_calls == []


def _load_process_alerts():
    """Extract the PRODUCTION legacy alert sender (aggregation.py
    ``_process_alerts``) and compile it against the real constants."""
    src = (_COMPONENT / "aggregation.py").read_text()
    tree = ast.parse(src)
    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "_process_alerts"
    )
    ns = dict(vars(_const))
    ns.update({
        "dt_util": SimpleNamespace(now=lambda: __import__("datetime").datetime.now()),
        "_LOGGER": logging.getLogger("test_alert"),
        "_get_room_coordinators": lambda hass: [],
    })
    module = ast.Module(body=[fn], type_ignores=[])
    exec(compile(module, "aggregation.py", "exec"), ns)
    return ns["_process_alerts"]


def test_simple_house_phone_sends_alert(install):
    """Plan-review finding 2: a Simple-mode House with only a phone picked
    must make the real alert sender call that phone's notify service."""
    install([])
    hass = _Hass(notify=["mobile_app_pixel"])
    _run(_flow(hass).async_step_integration_config(user_input={
        C.CONF_NOTIFY_TARGET: "notify.mobile_app_pixel",
    }))
    house = next(e for e in hass._entries
                 if e.data.get(C.CONF_ENTRY_TYPE) == C.ENTRY_TYPE_INTEGRATION)
    assert house.data[C.CONF_NOTIFY_SERVICE] == "notify.mobile_app_pixel"

    process_alerts = _load_process_alerts()
    sender = SimpleNamespace(
        hass=hass, entry=house, _last_alert_time=None,
        _get_config=lambda key, default=None: house.data.get(key, default),
    )
    _run(process_alerts(sender, [{"room": "Kitchen", "type": "smoke"}]))
    hass.services.async_call.assert_awaited_once()
    args = hass.services.async_call.await_args.args
    assert args[0] == "notify" and args[1] == "mobile_app_pixel"


def test_advanced_house_keeps_explicit_empty_service(install):
    """In Advanced mode both fields are visible: no service is derived."""
    install([])
    hass = _Hass()
    flow = _flow(hass, advanced=True)
    _run(flow.async_step_integration_config(user_input={
        C.CONF_NOTIFY_TARGET: "notify.mobile_app_pixel",
    }))
    assert C.CONF_NOTIFY_SERVICE not in flow._integration_data


# ===========================================================================
# S2 — rooms from areas, in bulk
# ===========================================================================

def _bulk(flow, area_ids):
    review = _run(flow.async_step_rooms_from_areas(
        user_input={_cf.BULK_AREAS_FIELD: area_ids}))
    assert review["type"] == "form" and review["step_id"] == "rooms_review"
    done = _run(flow.async_step_rooms_review(user_input={}))
    return review, done


def _house_flow(hass, advanced=False):
    hass._entries.append(SimpleNamespace(
        entry_id="house_1", options={}, title="Home",
        data={C.CONF_ENTRY_TYPE: C.ENTRY_TYPE_INTEGRATION},
    ))
    flow = _flow(hass, advanced=advanced)
    flow._integration_entry_id = "house_1"
    return flow


def test_menus_offer_rooms_from_areas(install):
    install([])
    flow = _flow(_Hass())
    assert "rooms_from_areas" in _run(flow.async_step_add_first_room())["menu_options"]
    assert "skip_to_room" in _run(flow.async_step_add_first_room())["menu_options"]
    assert "rooms_from_areas" in _run(flow.async_step_entry_type_select())["menu_options"]


def test_bulk_pre_ticks_areas_with_motion(install):
    install(_area_entities(), _AREAS)
    result = _run(_flow(_Hass()).async_step_rooms_from_areas())
    marker = next(iter(result["data_schema"].schema))
    assert sorted(marker.default()) == ["a1", "a2"]


def test_bulk_rooms_creates_one_entry_per_ticked_area(install):
    install(_area_entities(), _AREAS)
    hass = _Hass()
    _review, done = _bulk(_house_flow(hass), ["a1", "a2"])
    assert done["type"] == "abort" and done["reason"] == "rooms_created"
    assert sorted(e.title for e in hass.rooms()) == ["Guest Bath", "Office"]
    for room in hass.rooms():
        assert room.data[C.CONF_INTEGRATION_ENTRY_ID] == "house_1"
    assert done["description_placeholders"]["created"] == "2"
    # Occupancy / motion prefill lands in the stored entry (review C #1).
    office = next(e for e in hass.rooms() if e.title == "Office")
    assert office.data[C.CONF_OCCUPANCY_SENSORS] == ["binary_sensor.office_occ"]
    assert office.data[C.CONF_MOTION_SENSORS] == []
    bath = next(e for e in hass.rooms() if e.title == "Guest Bath")
    assert bath.data[C.CONF_MOTION_SENSORS] == ["binary_sensor.bath_motion"]


def test_bulk_rooms_office_entry_hand_written_expected(install):
    """Bulk parity against a HAND-WRITTEN expected entry (not built by the
    shared default builders), so a regression in those builders cannot
    also move the oracle."""
    install(_area_entities(), _AREAS)
    hass = _Hass()
    _bulk(_house_flow(hass), ["a2"])
    assert hass.rooms()[0].data == {
        "entry_type": "room",
        "integration_entry_id": "house_1",
        "room_name": "Office",
        "room_type": "generic",
        "area_id": "a2",
        "occupancy_timeout": 300,
        "wet_room": False,
        "room_is_guest_room": False,
        "motion_sensors": [],
        "presence_sensors": [],
        "occupancy_sensors": ["binary_sensor.office_occ"],
        "lights": ["light.office_lamp"],
        "auto_switches": [],
        "fans": [],
        "humidity_fans": [],
        "covers": [],
        "light_capabilities": "basic",
    }


def test_room_bulk_create_aborts_on_existing_name(install):
    install([])
    hass = _Hass()
    hass._entries.append(SimpleNamespace(
        entry_id="old", options={}, title="Office",
        data={C.CONF_ENTRY_TYPE: C.ENTRY_TYPE_ROOM, C.CONF_ROOM_NAME: "Office"},
    ))
    result = _run(_flow(hass).async_step_room_bulk_create(user_input={
        C.CONF_ENTRY_TYPE: C.ENTRY_TYPE_ROOM, C.CONF_ROOM_NAME: " office ",
    }))
    assert result["type"] == "abort" and result["reason"] == "room_name_exists"


def test_bulk_rooms_skips_area_without_occupancy(install):
    install(_area_entities(), _AREAS)
    hass = _Hass()
    review, done = _bulk(_house_flow(hass), ["a1", "a3"])
    assert "Storage**: Not added: no motion sensor in this area." in (
        review["description_placeholders"]["name"])
    assert [e.title for e in hass.rooms()] == ["Guest Bath"]


def test_bulk_rooms_name_collision_skipped(install):
    install(_area_entities(), _AREAS)
    hass = _Hass()
    hass._entries.append(SimpleNamespace(
        entry_id="old", options={}, title="Office",
        data={C.CONF_ENTRY_TYPE: C.ENTRY_TYPE_ROOM, C.CONF_ROOM_NAME: "office"},
    ))
    review, done = _bulk(_house_flow(hass), ["a1", "a2"])
    assert "**Office**: Already set up." in review["description_placeholders"]["name"]
    assert sorted(e.title for e in hass.rooms()) == ["Guest Bath", "Office"]
    assert len(hass.rooms()) == 2  # no second "Office"


def test_bulk_rooms_review_lists_every_written_entity(install):
    """INV-A: every entity_id stored in a created room is on the review."""
    install(_area_entities(), _AREAS)
    hass = _Hass()
    review, _done = _bulk(_house_flow(hass), ["a1", "a2"])
    text = review["description_placeholders"]["name"]
    written = set()
    for room in hass.rooms():
        for value in room.data.values():
            for v in (value if isinstance(value, list) else [value]):
                if isinstance(v, str) and "." in v and " " not in v:
                    written.add(v)
    assert written, "fixture should write entities"
    assert {"switch.bath_relay", "binary_sensor.bath_door", "light.office_lamp"} <= written
    missing = [e for e in written if e not in text]
    assert not missing, f"INV-A: written but not shown: {missing}"


@pytest.mark.parametrize("advanced", [False, True])
def test_bulk_rooms_entry_equals_single_flow_entry(install, advanced):
    """Same area through bulk and through the single chain with no edits
    -> identical entry data (plan-review finding 4)."""
    install(_area_entities(), _AREAS)

    hass_bulk = _Hass()
    hass_bulk._states["light.bath_ceiling"] = SimpleNamespace(
        attributes={"supported_features": 16})
    _bulk(_house_flow(hass_bulk, advanced), ["a1"])
    bulk_data = hass_bulk.rooms()[0].data

    hass_one = _Hass()
    hass_one._states["light.bath_ceiling"] = SimpleNamespace(
        attributes={"supported_features": 16})
    flow = _house_flow(hass_one, advanced)
    step = _run(flow.async_step_room_setup(user_input={
        C.CONF_AREA_ID: "a1", C.CONF_ROOM_TYPE: C.ROOM_TYPE_BATHROOM,
    }))
    for _ in range(10):
        if step["type"] != "form":
            break
        assert not step.get("errors"), (step["step_id"], step.get("errors"))
        handler = getattr(flow, f"async_step_{step['step_id']}")
        step = _run(handler(user_input=_untouched(step)))
    assert step["type"] == "create_entry"
    assert step["data"] == bulk_data
    assert bulk_data[C.CONF_LIGHT_CAPABILITIES] == "full"
    assert bulk_data[C.CONF_WET_ROOM] is True


def test_bulk_rooms_partial_failure_and_rerun(install):
    """Finding 3(a): a failing room does not stop the others; a re-run
    only creates what is missing (existing rooms skipped)."""
    install(_area_entities(), _AREAS)
    hass = _Hass(fail_names={"Guest Bath"})
    flow = _house_flow(hass)
    _review, done = _bulk(flow, ["a1", "a2"])
    assert [e.title for e in hass.rooms()] == ["Office"]
    assert done["description_placeholders"]["failed"] == "Guest Bath"

    hass.fail_names.clear()
    # Re-submit the SAME (now stale) review: the skip-existing guard must
    # stop a duplicate Office.
    again = _run(flow.async_step_rooms_review(user_input={}))
    assert sorted(e.title for e in hass.rooms()) == ["Guest Bath", "Office"]
    assert flow._bulk_result == {
        "created": ["Guest Bath"], "skipped": ["Office"], "failed": [],
    }
    assert again["description_placeholders"]["created"] == "1"


# Finding 3(b) pass/fail gate: URA's own work for N=15 rooms (area scan,
# ranking, data build, finalise, dispatch) must stay under this bound.
# Live, HA's per-room setup time adds on top; the live gate is in the
# README draft.
BULK_N15_MAX_SECONDS = 1.0


def test_bulk_rooms_n15_timing(install):
    entries, areas = [], {}
    for i in range(15):
        aid = f"z{i}"
        areas[aid] = f"Room {i}"
        entries += [
            _reg(f"binary_sensor.m{i}", area_id=aid, dc="motion", device_id=f"m{i}"),
            _reg(f"light.l{i}", area_id=aid, device_id=f"l{i}"),
            _reg(f"sensor.t{i}", area_id=aid, dc="temperature", device_id=f"m{i}"),
        ]
    # background registry noise
    entries += [_reg(f"sensor.noise{i}", area_id=None) for i in range(2000)]
    install(entries, areas)
    hass = _Hass()
    flow = _house_flow(hass)
    t0 = time.monotonic()
    _run(flow.async_step_rooms_from_areas())
    _bulk(flow, list(areas))
    elapsed = time.monotonic() - t0
    assert len(hass.rooms()) == 15
    assert elapsed < BULK_N15_MAX_SECONDS, f"N=15 bulk took {elapsed:.2f}s"


@pytest.mark.parametrize("name,expected", [
    ("Guest Bath", "bathroom"),
    ("Office", "generic"),
    ("Master Bedroom", "bedroom"),
    ("Bedroom Closet", "closet"),
    ("Garage", "garage"),
    ("Upstairs Hallway", "hallway"),
    ("Laundry", "utility"),
    ("", "generic"),
])
def test_area_keyword_type_guess(name, expected):
    assert _cf.guess_room_type_from_area(name) == expected


def test_room_bulk_create_rejects_non_room(install):
    install([])
    flow = _flow(_Hass())
    result = _run(flow.async_step_room_bulk_create(
        user_input={C.CONF_ENTRY_TYPE: C.ENTRY_TYPE_INTEGRATION}))
    assert result["type"] == "abort"


# ===========================================================================
# S3 — Simple single-room chain
# ===========================================================================

def test_room_simple_four_screens(install):
    install(_area_entities(), _AREAS)
    hass = _Hass()
    flow = _house_flow(hass)
    seen = ["room_setup"]
    step = _run(flow.async_step_room_setup(user_input={
        C.CONF_AREA_ID: "a1", C.CONF_ROOM_TYPE: C.ROOM_TYPE_BATHROOM,
    }))
    for _ in range(10):
        if step["type"] != "form":
            break
        assert not step.get("errors"), (step["step_id"], step.get("errors"))
        seen.append(step["step_id"])
        step = _run(getattr(flow, f"async_step_{step['step_id']}")(
            user_input=_untouched(step)))
    assert step["type"] == "create_entry"
    assert seen == ["room_setup", "sensors_confirm", "devices_confirm", "room_summary"]


@pytest.mark.parametrize("room_type,wet", [
    ("bathroom", True), ("bedroom", False),
])
def test_room_hidden_class_matches_type_default(install, room_type, wet):
    install([])
    flow = _flow(_Hass())
    flow._data = {C.CONF_ROOM_NAME: "R", C.CONF_ROOM_TYPE: room_type}
    nxt = _run(flow.async_step_room_class())
    assert nxt["step_id"] == "sensors_confirm"
    assert flow._data[C.CONF_WET_ROOM] is wet
    assert flow._data[C.CONF_ROOM_IS_GUEST_ROOM] is False


def test_room_class_shown_in_advanced(install):
    install([])
    flow = _flow(_Hass(), advanced=True)
    flow._data = {C.CONF_ROOM_NAME: "R", C.CONF_ROOM_TYPE: "bathroom"}
    assert _run(flow.async_step_room_class())["step_id"] == "room_class"


def test_room_name_prefilled_from_area(install):
    install([], _AREAS)
    flow = _flow(_Hass())
    _run(flow.async_step_room_setup(user_input={
        C.CONF_AREA_ID: "a2", C.CONF_ROOM_TYPE: C.ROOM_TYPE_GENERIC,
    }))
    assert flow._data[C.CONF_ROOM_NAME] == "Office"
    form = _run(_flow(_Hass()).async_step_room_setup())
    assert [str(k) for k in form["data_schema"].schema][0] == C.CONF_AREA_ID


def test_room_simple_hides_unused_fields(install):
    install(_area_entities(), _AREAS)
    flow = _flow(_Hass())
    flow._data = {C.CONF_ROOM_NAME: "Office", C.CONF_AREA_ID: "a2"}
    sensors = _keys(_run(flow.async_step_sensors_confirm()))
    assert C.CONF_MMWAVE_SENSORS not in sensors
    assert C.CONF_DOOR_SENSORS not in sensors
    assert C.CONF_WATER_LEAK_SENSOR not in sensors
    devices = _keys(_run(flow.async_step_devices_confirm()))
    assert C.CONF_HUMIDITY_FANS not in devices
    assert C.CONF_AUTO_SWITCHES not in devices
    # "Shown when in use": the bath area has a door and a switch.
    flow._data = {C.CONF_ROOM_NAME: "Bath", C.CONF_AREA_ID: "a1"}
    assert C.CONF_DOOR_SENSORS in _keys(_run(flow.async_step_sensors_confirm()))
    assert C.CONF_AUTO_SWITCHES in _keys(_run(flow.async_step_devices_confirm()))
    # Advanced shows everything.
    adv = _flow(_Hass(), advanced=True)
    adv._data = {C.CONF_ROOM_NAME: "Office", C.CONF_AREA_ID: "a2"}
    assert C.CONF_MMWAVE_SENSORS in _keys(_run(adv.async_step_sensors_confirm()))
    assert C.CONF_HUMIDITY_FANS in _keys(_run(adv.async_step_devices_confirm()))


def test_room_simple_hidden_fields_store_defaults(install):
    install(_area_entities(), _AREAS)
    flow = _flow(_Hass())
    flow._data = {C.CONF_ROOM_NAME: "Office", C.CONF_AREA_ID: "a2"}
    _run(flow.async_step_sensors_confirm(user_input={
        C.CONF_OCCUPANCY_SENSORS: ["binary_sensor.office_occ"],
    }))
    assert flow._data[C.CONF_MMWAVE_SENSORS] == []
    assert C.CONF_DOOR_SENSORS not in flow._data
    _run(flow.async_step_devices_confirm(user_input={
        C.CONF_LIGHTS: ["light.office_lamp"],
    }))
    assert flow._data[C.CONF_HUMIDITY_FANS] == []
    assert flow._data[C.CONF_AUTO_SWITCHES] == []


# ===========================================================================
# S4 — dead ends
# ===========================================================================

def test_add_coordinator_abort_reason(install):
    install([])
    result = _run(_flow(_Hass()).async_step_add_coordinator())
    assert result["type"] == "abort" and result["reason"] == "coordinator_use_options"
    for path in (_COMPONENT / "strings.json", _COMPONENT / "translations" / "en.json"):
        text = json.loads(path.read_text())["config"]["abort"]["coordinator_use_options"]
        assert "Domain Coordinators switch" in text


def test_no_route_to_deleted_steps():
    src = (_COMPONENT / "config_flow.py").read_text()
    for dead in ('"post_integration_setup"', '"setup_zone"', '"finish"'):
        assert dead not in src, dead
    for path in (_COMPONENT / "strings.json", _COMPONENT / "translations" / "en.json"):
        assert "post_integration_setup" not in json.loads(path.read_text())["config"]["step"]
