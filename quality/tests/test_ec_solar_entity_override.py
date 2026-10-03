"""EC-SOLAR-ENTITY-OVERRIDE-1 — options-flow solar power sensor override.

D1: `async_step_coordinator_energy` exposes CONF_ENERGY_SOLAR_ENTITY; a
    cleared / empty submission REMOVES the key (never persists "" and never
    resurrects the stored value through the {**options, **user_input} merge).
D2: the override reaches BatteryStrategy through the PRODUCTION setup merge
    (source-extracted from __init__.py, not hand-copied) and the PRODUCTION
    `EnergyCoordinator._build_entity_map` (source-extracted from energy.py).

Drills (run by the builder, see README draft):
  * setdefault -> overwrite in the __init__.py merge  => override tests RED.
  * neuter the key-removal pop in config_flow.py      => clear tests RED.
"""
from __future__ import annotations

import asyncio
import importlib
import os
import sys
import textwrap
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

# Staleness harness: installs HA stubs + loads real energy_const /
# energy_battery modules under the URA package path.
_stale = importlib.import_module("test_shared_power_read_staleness")
_eb_mod = _stale._eb_mod
_force_utc_aware_utcnow = _stale._force_utc_aware_utcnow  # autouse fixture

_baec = importlib.import_module("test_baec_config_flow_round_trip")
_cbcf = importlib.import_module("test_cycle_b_config_flow")
_ha_mocks_injected = _baec._ha_mocks_injected
_make_options_flow = _cbcf._make_options_flow

from conftest import MockHass, MockState  # noqa: E402

_PKG = "custom_components.universal_room_automation"
_EC_NAME = f"{_PKG}.domain_coordinators.energy_const"
_ec = sys.modules[_EC_NAME]

CONF_SOLAR = "energy_solar_entity"
CONF_ENVOY = "energy_envoy_entity"
SERIAL = "482543015950"
ENVOY = f"sensor.envoy_{SERIAL}_current_power_production"
DERIVED_SOLAR = f"sensor.envoy_{SERIAL}_current_power_production"
CT_SOLAR = f"sensor.envoy_{SERIAL}_production_ct_power"

_ROOT = os.path.join(os.path.dirname(__file__), "..", "..",
                     "custom_components", "universal_room_automation")


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Production-source extraction
# ---------------------------------------------------------------------------

def _setup_merge(cm_config: dict) -> dict:
    """Run the REAL __init__.py energy_entity_config build + Envoy derive
    merge (the block from `energy_entity_config: dict[str, str] = {}`
    through the setdefault loop)."""
    with open(os.path.join(_ROOT, "__init__.py")) as fh:
        src = fh.read()
    start = src.index("energy_entity_config: dict[str, str] = {}")
    end = src.index("# EC Envoy boot-decoupling cycle", start)
    block = textwrap.dedent(" " * 16 + src[start:end])
    ns = {
        "cm_config": dict(cm_config),
        "CONF_ENERGY_ENVOY_ENTITY": _ec.CONF_ENERGY_ENVOY_ENTITY,
        "extract_envoy_serial": _ec.extract_envoy_serial,
        "derive_envoy_config": _ec.derive_envoy_config,
    }
    exec(compile(block, "__init__.py<energy_merge>", "exec"), ns)
    return ns["energy_entity_config"]


def _build_entity_map(config: dict) -> dict:
    """REAL EnergyCoordinator._build_entity_map, source-extracted."""
    with open(os.path.join(_ROOT, "domain_coordinators", "energy.py")) as fh:
        src = fh.read()
    start = src.index("    def _build_entity_map(")
    end = src.index("\n    async def async_setup(", start)
    fn_src = textwrap.dedent(src[start:end])
    ns = dict(vars(_ec))
    ns["__package__"] = f"{_PKG}.domain_coordinators"
    ns["__name__"] = f"{_PKG}.domain_coordinators.energy"
    exec(compile(fn_src, "energy.py<_build_entity_map>", "exec"), ns)
    return ns["_build_entity_map"](None, config)


def _fresh(eid, value, uom):
    now = datetime.now(timezone.utc) - timedelta(seconds=1)
    st = MockState(eid, value, attributes={"unit_of_measurement": uom},
                   last_changed=now)
    st.last_reported = now
    st.last_updated = now
    return st


def _strategy_for(cm_options: dict):
    hass = MockHass()
    hass._states[DERIVED_SOLAR] = _fresh(DERIVED_SOLAR, "0.0", "kW")
    hass._states[CT_SOLAR] = _fresh(CT_SOLAR, "4.2", "kW")
    cfg = _setup_merge(cm_options)
    strategy = _eb_mod.BatteryStrategy(
        hass, entity_config=_build_entity_map(cfg),
    )
    return cfg, strategy


# ---------------------------------------------------------------------------
# D2 — wiring
# ---------------------------------------------------------------------------

def test_ec_solar_override_reaches_battery_strategy():
    cfg, s = _strategy_for({CONF_ENVOY: ENVOY, CONF_SOLAR: CT_SOLAR})
    assert cfg[CONF_SOLAR] == CT_SOLAR
    assert s.solar_production == pytest.approx(4.2)
    assert s.solar_production_w == pytest.approx(4200.0)


def test_ec_solar_override_blank_uses_derived():
    cfg, s = _strategy_for({CONF_ENVOY: ENVOY})
    assert cfg[CONF_SOLAR] == DERIVED_SOLAR
    assert cfg == {CONF_ENVOY: ENVOY, **_ec.derive_envoy_config(SERIAL)}
    assert s.solar_production == pytest.approx(0.0)
    assert s.solar_production_w == pytest.approx(0.0)


def test_ec_solar_override_validation_resolves_override():
    hass = MagicMock()
    hass.states.get = lambda eid: MagicMock(state="1.0")
    cfg = {CONF_ENVOY: ENVOY, CONF_SOLAR: CT_SOLAR}
    result = _ec.validate_envoy_config(hass, cfg)
    assert result["resolved"][CONF_SOLAR] == CT_SOLAR


# ---------------------------------------------------------------------------
# D1 — options flow
# ---------------------------------------------------------------------------

class _State:
    def __init__(self, state="1.0"):
        self.state = state
        self.attributes = {}


def _flow(options, existing):
    flow = _make_options_flow(options=options)
    flow.hass._states = {eid: _State() for eid in existing}
    flow.hass.data = {}
    return flow


@pytest.fixture
def _state_only_registry(monkeypatch):
    """Registry = state machine (validator's own fallback contract)."""
    def _patch():
        mod = sys.modules[_EC_NAME]
        monkeypatch.setattr(
            mod, "_entity_in_registry",
            lambda hass, eid: hass.states.get(eid) is not None,
        )
    return _patch


def _all_derived():
    return [ENVOY, CT_SOLAR, *_ec.derive_envoy_config(SERIAL).values()]


def test_ec_solar_override_options_roundtrip_set_and_clear():
    # Set
    flow = _flow({}, [])
    with _ha_mocks_injected():
        r = _run(flow.async_step_coordinator_energy(
            user_input={CONF_SOLAR: CT_SOLAR}))
    assert r["type"] == "create_entry", r
    assert r["data"][CONF_SOLAR] == CT_SOLAR

    # Cleared field omitted -> key absent (not resurrected from options)
    flow = _flow({CONF_SOLAR: CT_SOLAR, "energy_bill_cycle_day": 23}, [])
    with _ha_mocks_injected():
        r = _run(flow.async_step_coordinator_energy(
            user_input={"energy_bill_cycle_day": 5}))
    assert r["type"] == "create_entry", r
    assert CONF_SOLAR not in r["data"]
    assert r["data"]["energy_bill_cycle_day"] == 5

    # Empty string -> key absent, "" never persisted
    flow = _flow({CONF_SOLAR: CT_SOLAR}, [])
    with _ha_mocks_injected():
        r = _run(flow.async_step_coordinator_energy(
            user_input={CONF_SOLAR: ""}))
    assert r["type"] == "create_entry", r
    assert CONF_SOLAR not in r["data"]


def test_ec_solar_override_schema_exposes_field():
    flow = _flow({}, [])
    with _ha_mocks_injected():
        r = _run(flow.async_step_coordinator_energy(user_input=None))
    assert r["type"] == "form", r
    assert CONF_SOLAR in {str(k) for k in r["data_schema"].schema.keys()}


def test_ec_solar_override_invalid_entity_rejected(_state_only_registry):
    existing = [e for e in _all_derived() if e != CT_SOLAR]
    flow = _flow({}, existing)
    with _ha_mocks_injected():
        _state_only_registry()
        r = _run(flow.async_step_coordinator_energy(user_input={
            CONF_ENVOY: ENVOY, CONF_SOLAR: CT_SOLAR,
        }))
    assert r["type"] == "form", r
    assert r["errors"].get(CONF_SOLAR) == _ec.ENVOY_ERR_DERIVED_MISSING


def test_ec_solar_override_valid_with_envoy_passes_validation(
    _state_only_registry,
):
    """Plan-review extra: Envoy set + valid override -> save passes and the
    validator resolves the override (not the derived name)."""
    flow = _flow({}, _all_derived())
    seen = {}
    with _ha_mocks_injected():
        _state_only_registry()
        mod = sys.modules[_EC_NAME]
        real = mod.validate_envoy_config

        def _spy(hass, cfg):
            res = real(hass, cfg)
            seen["resolved"] = res["resolved"]
            return res

        mod.validate_envoy_config = _spy
        try:
            r = _run(flow.async_step_coordinator_energy(user_input={
                CONF_ENVOY: ENVOY, CONF_SOLAR: CT_SOLAR,
            }))
        finally:
            mod.validate_envoy_config = real
    assert r["type"] == "create_entry", r
    assert r["data"][CONF_SOLAR] == CT_SOLAR
    assert seen["resolved"][CONF_SOLAR] == CT_SOLAR
