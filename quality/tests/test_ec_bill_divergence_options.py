"""EC-BILL-UTILITY-DIVERGENCE-FROM-STATS-1 D4 — options-flow statistic ids.

Drives the REAL ``async_step_coordinator_energy`` with the same harness as
test_ec_solar_entity_override.py.
"""
from __future__ import annotations

import asyncio
import importlib
import sys

_stale = importlib.import_module("test_shared_power_read_staleness")
_force_utc_aware_utcnow = _stale._force_utc_aware_utcnow  # autouse fixture
_baec = importlib.import_module("test_baec_config_flow_round_trip")
_cbcf = importlib.import_module("test_cycle_b_config_flow")
_ha_mocks_injected = _baec._ha_mocks_injected
_make_options_flow = _cbcf._make_options_flow

_PKG = "custom_components.universal_room_automation"
_ec = sys.modules[f"{_PKG}.domain_coordinators.energy_const"]

IMP_KEY = "energy_utility_import_statistic_id"
EXP_KEY = "energy_utility_export_statistic_id"
IMP = "smarthub:smarthub_energy_sensor_1_2"
EXP = "smarthub:smarthub_energy_return_sensor_1_2"


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _flow(options):
    flow = _make_options_flow(options=options)
    flow.hass._states = {}
    flow.hass.data = {}
    return flow


def _save(options, user_input):
    flow = _flow(options)
    with _ha_mocks_injected():
        return _run(flow.async_step_coordinator_energy(user_input=user_input))


def test_options_utility_statistic_ids_roundtrip():
    # Set both.
    r = _save({}, {IMP_KEY: IMP, EXP_KEY: EXP})
    assert r["type"] == "create_entry", r
    assert r["data"][IMP_KEY] == IMP
    assert r["data"][EXP_KEY] == EXP
    # Re-submitting the stored values keeps them.
    r = _save({IMP_KEY: IMP, EXP_KEY: EXP}, {IMP_KEY: IMP, EXP_KEY: EXP})
    assert r["data"][IMP_KEY] == IMP and r["data"][EXP_KEY] == EXP
    # Blank clears (never persists "").
    r = _save({IMP_KEY: IMP, EXP_KEY: EXP}, {IMP_KEY: "", EXP_KEY: "  "})
    assert r["type"] == "create_entry", r
    assert IMP_KEY not in r["data"] and EXP_KEY not in r["data"]
    # Omitted field (frontend cleared the text box) clears too.
    r = _save({IMP_KEY: IMP, EXP_KEY: EXP}, {"energy_bill_cycle_day": 23})
    assert IMP_KEY not in r["data"] and EXP_KEY not in r["data"]
    # Import set, export blank is allowed.
    r = _save({}, {IMP_KEY: IMP, EXP_KEY: ""})
    assert r["type"] == "create_entry", r
    assert r["data"][IMP_KEY] == IMP and EXP_KEY not in r["data"]


def test_options_utility_statistic_id_requires_colon():
    r = _save({}, {IMP_KEY: "sensor.smarthub_energy"})
    assert r["type"] == "form", r
    assert r["errors"][IMP_KEY] == "utility_statistic_id_invalid"
    r = _save({}, {IMP_KEY: IMP, EXP_KEY: "nocolon"})
    assert r["type"] == "form", r
    assert r["errors"][EXP_KEY] == "utility_statistic_id_invalid"
    assert IMP_KEY not in r["errors"]


def test_options_schema_exposes_statistic_fields():
    flow = _flow({})
    with _ha_mocks_injected():
        r = _run(flow.async_step_coordinator_energy(user_input=None))
    keys = {str(k) for k in r["data_schema"].schema.keys()}
    assert IMP_KEY in keys and EXP_KEY in keys


def test_statistic_ids_are_construction_keys():
    """Read at EC construction -> a change must trigger the parent reload."""
    assert _ec.CONF_ENERGY_UTILITY_IMPORT_STATISTIC_ID == IMP_KEY
    assert _ec.CONF_ENERGY_UTILITY_EXPORT_STATISTIC_ID == EXP_KEY
    assert IMP_KEY in _ec.EC_CONSTRUCTION_ENTITY_KEYS
    assert EXP_KEY in _ec.EC_CONSTRUCTION_ENTITY_KEYS
