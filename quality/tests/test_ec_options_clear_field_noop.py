"""EC-OPTIONS-CLEAR-FIELD-NOOP-1 — clearing an optional single-entity
selector on the Energy Coordinator options step must REMOVE the stored
options key.

Prior art reused: `clear_grid_fields` multi-select pattern in the SAME
step (config_flow.py ~6229 apply; ~7100 selector).

Problem being pinned by these tests:
    An optional EntitySelector field with `description={"suggested_value":
    <current>}` and no `default=` is rendered pre-filled by HA but, when
    the operator CLEARS it, HA omits the key from `user_input`. The step
    then persists `{**options, **user_input}`, which resurrects the old
    value — the operator cannot un-configure the field via the options
    flow.

The newly-added role-keyed single-entity selectors from
EC-HOUSE-ENTITY-DEFAULTS-1 (commit 99b6f4327) are the surface the
operator was pointed at by the Repairs issue text — so they are the
primary coverage below. One cloud_verification field is also exercised
to prove the flatten → clear → pop path works through the pop'd section.
"""

from __future__ import annotations

import asyncio
import importlib

_baec = importlib.import_module("test_baec_config_flow_round_trip")
_cbcf = importlib.import_module("test_cycle_b_config_flow")

_ha_mocks_injected = _baec._ha_mocks_injected
_make_options_flow = _cbcf._make_options_flow


# Role-keyed fields introduced by EC-HOUSE-ENTITY-DEFAULTS-1 fix-up
# (99b6f4327). All optional, all single-entity selectors.
EVSE_A_SWITCH = "energy_evse_a_switch_entity"
STORAGE_MODE = "energy_storage_mode_entity"
RESERVE_SOC = "energy_reserve_soc_entity"
POOL_POWER = "energy_pool_power_entity"
# Cloud-verification single-entity field (flattened from the collapsed
# `cloud_verification` section in the same step).
CLOUD_RESERVE_ORACLE = "energy_cloud_reserve_oracle_entity"


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_clear_role_entity_removes_stored_key():
    """Clearing a role-keyed entity field (operator ticks `Clear ...`
    checkbox in the step's clear widget) must POP the key from saved
    options, so the field falls back exactly as a never-set field does."""
    stored = {
        EVSE_A_SWITCH: "switch.evse_a_relay_old",
        STORAGE_MODE: "select.span_storage_mode",
    }
    flow = _make_options_flow(options=stored)
    with _ha_mocks_injected():
        result = _run(flow.async_step_coordinator_energy(user_input={
            "clear_grid_fields": ["evse_a_switch"],
        }))
    assert result["type"] == "create_entry", result
    saved = result["data"]
    assert EVSE_A_SWITCH not in saved, (
        "clearing evse_a_switch must drop the stored key, not preserve "
        "it via the merge"
    )
    # Untouched key is preserved.
    assert saved.get(STORAGE_MODE) == "select.span_storage_mode"


def test_clear_cloud_verification_entity_removes_stored_key():
    """Cloud-verification single-entity fields live inside the
    collapsed `cloud_verification` section — the step flattens them to
    top-level keys before the merge. A clear-tick must still pop the
    stored top-level key."""
    stored = {
        CLOUD_RESERVE_ORACLE: "number.cloud_reserve_floor",
    }
    flow = _make_options_flow(options=stored)
    with _ha_mocks_injected():
        result = _run(flow.async_step_coordinator_energy(user_input={
            "clear_grid_fields": ["cloud_reserve_oracle"],
        }))
    assert result["type"] == "create_entry", result
    saved = result["data"]
    assert CLOUD_RESERVE_ORACLE not in saved, (
        "clearing cloud_reserve_oracle must drop the stored top-level "
        "key (the flatten runs before the clear-apply)"
    )


def test_unchanged_save_preserves_all_role_fields():
    """Submitting with NO clear-ticks and NO user_input keys for the
    role fields must preserve every stored role field unchanged — this
    is the "operator opened the step and clicked save" path."""
    stored = {
        EVSE_A_SWITCH: "switch.evse_a_relay_old",
        STORAGE_MODE: "select.span_storage_mode",
        RESERVE_SOC: "number.span_reserve",
        POOL_POWER: "sensor.pool_power",
    }
    flow = _make_options_flow(options=dict(stored))
    with _ha_mocks_injected():
        result = _run(flow.async_step_coordinator_energy(user_input={}))
    assert result["type"] == "create_entry", result
    saved = result["data"]
    for k, v in stored.items():
        assert saved.get(k) == v, f"{k} must be preserved on unchanged save"


def test_clear_plus_new_pick_for_role_field_new_wins():
    """Precedence (mirrors A-LOW on clear_grid_fields): if the operator
    ticks `Clear X` AND picks a fresh entity for X in the SAME submit,
    the fresh pick wins — the clear is for the "I set this once and now
    want it empty" case; a fresh pick is a stronger signal."""
    stored = {EVSE_A_SWITCH: "switch.evse_a_relay_old"}
    flow = _make_options_flow(options=stored)
    with _ha_mocks_injected():
        result = _run(flow.async_step_coordinator_energy(user_input={
            EVSE_A_SWITCH: "switch.evse_a_relay_new",
            "clear_grid_fields": ["evse_a_switch"],
        }))
    assert result["type"] == "create_entry", result
    saved = result["data"]
    assert saved.get(EVSE_A_SWITCH) == "switch.evse_a_relay_new", (
        "fresh entity pick must win over clear in the same submit"
    )


def test_cleared_key_is_a_change_under_normalised_diff():
    """A cleared role key (popped from saved options so .get(k) is None)
    MUST be seen as a change by the EC-HOUSE-ENTITY-DEFAULTS-1 review-D I3
    value-normalised listener diff — otherwise the EnergyCoordinator will
    not pick it up at runtime (it reads these keys only at construction).
    Mirror case: an unchanged save is NOT a change."""
    from custom_components.universal_room_automation import (
        _norm_cm_opt,
    )
    old = {EVSE_A_SWITCH: "switch.evse_a_relay_old"}
    # After clear-apply, the key is popped from saved options.
    new_cleared: dict = {}
    changed = _norm_cm_opt(old.get(EVSE_A_SWITCH)) != _norm_cm_opt(
        new_cleared.get(EVSE_A_SWITCH)
    )
    assert changed, (
        "popping a role key must register as a change against the "
        "normalised diff (so the parent entry reload fires)"
    )
    # Negative: unchanged save -> no change.
    new_same = {EVSE_A_SWITCH: "switch.evse_a_relay_old"}
    assert not (
        _norm_cm_opt(old.get(EVSE_A_SWITCH))
        != _norm_cm_opt(new_same.get(EVSE_A_SWITCH))
    ), "an identical save must NOT register as a change"
