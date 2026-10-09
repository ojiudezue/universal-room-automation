"""B-MED (2026-10-09): round-trip test for the ``clear_grid_fields``
multi-select on the options-flow coordinator_energy step.

Three cases:
  1. Normal save (no clear choices) preserves stored grid import/export.
  2. ``clear_grid_fields=["grid_import"]`` pops the stored import key.
  3. "Clear + fresh pick in SAME submit" — new entity wins (A-LOW).

Piggybacks the BAEC harness (used elsewhere in-tree) for HA mocks.
"""

from __future__ import annotations

import asyncio
import importlib


_baec = importlib.import_module("test_baec_config_flow_round_trip")
_cbcf = importlib.import_module("test_cycle_b_config_flow")

_ha_mocks_injected = _baec._ha_mocks_injected
_make_options_flow = _cbcf._make_options_flow


CONF_IMPORT = "energy_grid_import_entity"
CONF_EXPORT = "energy_grid_export_entity"


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_normal_save_preserves_stored_grid_entities():
    """Submitting without touching clear_grid_fields must preserve both
    stored grid entity keys (merge behaviour)."""
    stored = {
        CONF_IMPORT: "sensor.mains_import_counter",
        CONF_EXPORT: "sensor.mains_export_counter",
    }
    flow = _make_options_flow(options=stored)
    with _ha_mocks_injected():
        result = _run(flow.async_step_coordinator_energy(user_input={}))
    assert result["type"] == "create_entry", result
    saved = result["data"]
    assert saved.get(CONF_IMPORT) == "sensor.mains_import_counter"
    assert saved.get(CONF_EXPORT) == "sensor.mains_export_counter"


def test_clear_grid_import_removes_stored_key():
    """``clear_grid_fields=["grid_import"]`` must pop the import key from
    saved options so the runtime no longer sees it."""
    stored = {
        CONF_IMPORT: "sensor.mains_import_counter",
        CONF_EXPORT: "sensor.mains_export_counter",
    }
    flow = _make_options_flow(options=stored)
    with _ha_mocks_injected():
        result = _run(flow.async_step_coordinator_energy(user_input={
            "clear_grid_fields": ["grid_import"],
        }))
    assert result["type"] == "create_entry", result
    saved = result["data"]
    assert CONF_IMPORT not in saved, (
        "clear_grid_fields=['grid_import'] must drop the stored import key"
    )
    # Export is untouched.
    assert saved.get(CONF_EXPORT) == "sensor.mains_export_counter"


def test_clear_plus_new_entity_in_same_submit_new_wins():
    """A-LOW: a fresh entity picked in the SAME submit as its clear
    checkbox wins — the new pick is a stronger operator signal."""
    stored = {CONF_IMPORT: "sensor.old_import"}
    flow = _make_options_flow(options=stored)
    with _ha_mocks_injected():
        result = _run(flow.async_step_coordinator_energy(user_input={
            CONF_IMPORT: "sensor.new_import",
            "clear_grid_fields": ["grid_import"],
        }))
    assert result["type"] == "create_entry", result
    saved = result["data"]
    assert saved.get(CONF_IMPORT) == "sensor.new_import", (
        "fresh entity pick must win over clear in the same submit"
    )
