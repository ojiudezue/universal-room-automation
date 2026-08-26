"""Round-2 fix-up (item #4): config-flow round-trip for the two
SolarFollowController grid-entity fields.

Two complementary tests:

  1. SUBMIT round-trip — user_input carrying the two keys lands in
     entry.options unchanged (the {**options, **user_input} merge path).

  2. SCHEMA round-trip (the schema-deletion detector) — the show-form
     path (user_input=None) emits a data_schema whose keys include both
     CONF_ENERGY_SOLAR_FOLLOW_GRID_ENTITY and _FALLBACK_ENTITY. Deleting
     either `vol.Optional(...)` block in async_step_coordinator_energy
     (config_flow.py:4557-4569) removes the corresponding key from the
     shown schema → RED.

Piggybacks on the BAEC harness for HA-mock injection.
"""

from __future__ import annotations

import asyncio
import importlib
from unittest.mock import MagicMock


_baec = importlib.import_module("test_baec_config_flow_round_trip")
_cbcf = importlib.import_module("test_cycle_b_config_flow")

_ha_mocks_injected = _baec._ha_mocks_injected
_make_options_flow = _cbcf._make_options_flow


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


CONF_GRID = "energy_solar_follow_grid_entity"
CONF_FALLBACK = "energy_solar_follow_grid_fallback_entity"


def test_solar_follow_submit_round_trip_lands_in_options():
    """Values submitted via the energy step land in entry.options."""
    flow = _make_options_flow(options={})
    user_input = {
        CONF_GRID: "sensor.mains_test_primary",
        CONF_FALLBACK: "sensor.envoy_test_fallback",
    }
    with _ha_mocks_injected():
        result = _run(flow.async_step_coordinator_energy(user_input=user_input))

    assert result["type"] == "create_entry", result
    saved = result["data"]
    assert saved[CONF_GRID] == "sensor.mains_test_primary"
    assert saved[CONF_FALLBACK] == "sensor.envoy_test_fallback"


def test_solar_follow_schema_exposes_both_grid_entity_fields():
    """Show-form path must publish both CONF_* keys in the data_schema.

    Neuter drill: delete either vol.Optional(CONF_ENERGY_SOLAR_FOLLOW_
    GRID_ENTITY, ...) or ..._FALLBACK_ENTITY block in the
    async_step_coordinator_energy schema (config_flow.py ~:4557-4569).
    """
    flow = _make_options_flow(options={})
    # `self.hass.data.get(DOMAIN, {}).get(...)` is used inside the
    # show-form path; the base _FakeHass omits `.data`, so attach an
    # empty mapping that behaves like hass.data.
    flow.hass.data = {}
    with _ha_mocks_injected():
        result = _run(flow.async_step_coordinator_energy(user_input=None))

    assert result["type"] == "form", result
    schema = result["data_schema"]
    keys = {str(k) for k in schema.schema.keys()}
    assert CONF_GRID in keys, (
        f"CONF_ENERGY_SOLAR_FOLLOW_GRID_ENTITY not in schema; got {keys!r}"
    )
    assert CONF_FALLBACK in keys, (
        f"CONF_ENERGY_SOLAR_FOLLOW_GRID_FALLBACK_ENTITY not in schema; got {keys!r}"
    )
