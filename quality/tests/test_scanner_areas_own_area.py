"""SCANNER-AREAS-OWN-AREA: a room's own area in CONF_SCANNER_AREAS is ignored.

Operator 2026-10-26: "scanner_areas" means "borrow another area's Bluetooth
scanner". Listing the room's OWN area is meaningless and, because any
non-empty list removed the room from ``_direct_ble_rooms``, it demoted the
room to the shared-scanner BLE rules. HA's AreaSelectorConfig has no exclude
option, so the flows strip the own area on save, and person_coordinator
ignores it at runtime (a stale config cannot demote a room).

Drives the real flow handlers and the real ``_build_scanner_room_map``.
"""

from __future__ import annotations

import asyncio
import importlib
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

_cbcf = importlib.import_module("test_cycle_b_config_flow")
_baec = importlib.import_module("test_baec_config_flow_round_trip")

PKG = "custom_components.universal_room_automation"
DOMAIN = "universal_room_automation"

OWN = "study_a"
OTHER = "entry_nook"
PIR = "binary_sensor.study_a_motion"


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------- options flow

def _options_submit(scanner_areas):
    captured = {}
    with _baec._ha_mocks_injected():
        flow = _cbcf._make_options_flow(
            data={"room_name": "Study A", "area_id": OWN},
            options={"motion_sensors": [PIR]},
        )
        flow.async_create_entry = lambda title="", data=None: captured.setdefault(
            "data", data
        ) or {"type": "create_entry", "data": data}
        _run(flow.async_step_sensors({
            "motion_sensors": [PIR],
            "occupancy_sensors": [],
            "sensor_capabilities_json": "",
            "scanner_areas": scanner_areas,
        }))
    return captured.get("data")


def test_options_flow_strips_own_area_on_save():
    data = _options_submit([OWN, OTHER])
    assert data is not None, "options sensors step did not save"
    assert data["scanner_areas"] == [OTHER]


def test_options_flow_own_area_only_saves_empty():
    data = _options_submit([OWN])
    assert data["scanner_areas"] == []


def test_options_flow_keeps_other_areas_untouched():
    data = _options_submit([OTHER])
    assert data["scanner_areas"] == [OTHER]


def test_options_form_default_excludes_own_area():
    with _baec._ha_mocks_injected():
        flow = _cbcf._make_options_flow(
            data={"room_name": "Study A", "area_id": OWN},
            options={"motion_sensors": [PIR], "scanner_areas": [OWN, OTHER]},
        )
        result = _run(flow.async_step_sensors(None))
    for key in result["data_schema"].schema:
        if str(key) == "scanner_areas":
            assert key.default() == [OTHER]
            return
    pytest.fail("scanner_areas field missing from options sensors form")


# ---------------------------------------------------------------- initial flow

def test_initial_flow_strips_own_area_on_save():
    with _baec._ha_mocks_injected():
        flow = _cbcf._make_config_flow()
        flow._data = {"room_name": "Study A", "area_id": OWN}

        async def _devices(user_input=None):
            return {"type": "form", "step_id": "devices"}

        flow.async_step_devices = _devices
        _run(flow.async_step_sensors({
            "motion_sensors": [PIR],
            "scanner_areas": [OWN, OTHER],
        }))
    assert flow._data["scanner_areas"] == [OTHER]


# ---------------------------------------------------------- person_coordinator

@pytest.fixture
def pc_mod():
    """Real person_coordinator module, restoring sys.modules afterwards."""
    names = (PKG, f"{PKG}.const", f"{PKG}.person_coordinator")
    saved = {n: sys.modules.get(n) for n in names}
    for n in names:
        mod = saved[n]
        if mod is None or isinstance(mod, MagicMock) or not getattr(mod, "__file__", None):
            sys.modules.pop(n, None)
    try:
        yield importlib.import_module(f"{PKG}.person_coordinator")
    finally:
        for n, mod in saved.items():
            if mod is None:
                sys.modules.pop(n, None)
            else:
                sys.modules[n] = mod


def _room_entry(eid, room, area_id, scanner_areas):
    return SimpleNamespace(
        entry_id=eid,
        data={"entry_type": "room", "room_name": room, "area_id": area_id},
        options={"scanner_areas": scanner_areas},
    )


def _build(pc, entries):
    coord = pc.PersonTrackingCoordinator.__new__(pc.PersonTrackingCoordinator)
    hass = MagicMock()
    hass.config_entries.async_entries = MagicMock(return_value=entries)
    hass.data = {}
    coord.hass = hass
    coord._scanner_map_entry_ids = set()
    coord._scanner_to_rooms = {}
    coord._area_id_to_room = {}
    coord._room_coordinators = {}
    coord._direct_ble_rooms = set()
    area_reg = MagicMock()
    area_reg.async_get_area = lambda aid: SimpleNamespace(name=aid.replace("_", " ").title())
    with patch.object(pc.ar, "async_get", return_value=area_reg):
        _run(coord._build_scanner_room_map())
    return coord


def test_room_listing_only_own_area_stays_direct(pc_mod):
    assert pc_mod.CONF_SCANNER_AREAS == "scanner_areas"
    coord = _build(pc_mod, [_room_entry("e1", "Study A", OWN, [OWN])])
    assert coord._direct_ble_rooms == {"study_a"}
    assert coord._scanner_to_rooms == {OWN: ["Study A"]}


def test_own_area_ignored_with_real_borrow(pc_mod):
    coord = _build(pc_mod, [_room_entry("e1", "Study A", OWN, [OWN, OTHER])])
    # Still borrowing -> not direct; own area does not enter the Tier-2 map.
    assert coord._direct_ble_rooms == set()
    assert coord._scanner_to_rooms == {OTHER: ["Study A"]}


def test_borrow_only_room_unchanged(pc_mod):
    coord = _build(pc_mod, [_room_entry("e1", "Study A", OWN, [OTHER])])
    assert coord._direct_ble_rooms == set()
    assert coord._scanner_to_rooms == {OTHER: ["Study A"]}


def test_config_flow_class_keeps_timing_instrumentation():
    """Review A/B/C 2026-10-26: strip_own_area must not sit between
    @instrument_flow and the ConfigFlow class."""
    from custom_components.universal_room_automation import config_flow as cf

    assert getattr(
        cf.UniversalRoomAutomationConfigFlow, "_cflow_timing_instrumented", False
    )


def test_strip_own_area_without_area_id_keeps_list():
    from custom_components.universal_room_automation.config_flow import (
        strip_own_area,
    )

    assert strip_own_area(["a", "b"], None) == ["a", "b"]
    assert strip_own_area(None, "a") == []
