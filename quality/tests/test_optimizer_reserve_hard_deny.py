"""EC-RESERVE-WRITE-GOVERNOR-1 Review D D-2 — the Optimization Coordinator
never writes a battery-reserve role entity.

The optimizer's `async_call(domain, action_name, …)` is a variable-domain
writer the reserve lint (INV-G1) cannot see; the battery reserve has exactly
one writer (the energy governed slice). Both dispatch functions refuse any
reserve-role target, independent of `CONF_OPTIMIZER_SAFETY_DENY_ENTITIES`,
with a logged `reserve_role_hard_deny` activity row.
"""
from __future__ import annotations

import sys
from datetime import datetime

import pytest

# Reuse the optimizer suite's harness (its autouse stub-eviction fixture is
# module-scoped there; import the helpers only).
from test_optimization_coordinator import _make_hass, _evict_ura_stubs  # noqa: F401

RESERVE_CLOUD = "number.iq_battery_hacs_battery_reserve"
RESERVE_LOCAL = "number.enpower_482348004678_reserve_battery_level"


def _finding():
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationFinding, OptimizationDimension,
    )
    return OptimizationFinding(
        timestamp=datetime.utcnow().isoformat(),
        level="house", target_id="house",
        dimension=OptimizationDimension.COMFORT,
        severity="medium", confidence=0.95, score=50.0,
        description="raise reserve a bit", created_by="llm_tier2",
    )


def _cm(level="propose_config", **extra):
    opts = {
        "optimizer_autonomy_level": level,
        "optimizer_confidence_gate": 0.5,
        "energy_reserve_soc_entity": RESERVE_LOCAL,
        "energy_cloud_reserve_oracle_entity": RESERVE_CLOUD,
    }
    opts.update(extra)
    return opts


def _rows(hass, reason):
    db = hass.data["universal_room_automation"]["database"]
    out = []
    for call in db.log_activity.await_args_list:
        kw = call.kwargs
        import json
        det = kw.get("details_json")
        d = json.loads(det) if isinstance(det, str) else (det or {})
        if d.get("reason") == reason:
            out.append(d)
    return out


@pytest.mark.asyncio
@pytest.mark.parametrize("target", [RESERVE_CLOUD, RESERVE_LOCAL])
async def test_optimizer_config_write_to_reserve_is_refused_and_logged(target):
    """LLM proposal `number.set_value` to the reserve (write leg OR local
    witness) → DISALLOWED, no service call, `reserve_role_hard_deny` row.
    Mutation: delete the config-dispatch deny call → RED."""
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationCoordinator,
    )
    from custom_components.universal_room_automation.const import (
        OPTIMIZER_OUTCOME_DISALLOWED,
    )
    hass, _ = _make_hass(cm_options=_cm())
    coord = OptimizationCoordinator(hass)
    f = _finding()
    outcome = await coord._dispatch_config_action(
        f, "aid", target, "number.set_value", {"value": 24}, "propose_config",
    )
    assert outcome == OPTIMIZER_OUTCOME_DISALLOWED
    assert f.applied_outcome == OPTIMIZER_OUTCOME_DISALLOWED
    assert hass.services.calls == []
    rows = _rows(hass, "reserve_role_hard_deny")
    assert len(rows) == 1 and rows[0]["target_entity"] == target
    assert rows[0]["created_by"] == "llm_tier2"


@pytest.mark.asyncio
async def test_optimizer_device_dispatch_to_reserve_is_refused():
    """The device-class dispatch refuses too (belt for a future domain
    widening). Mutation: delete the device-dispatch deny call → RED."""
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationCoordinator,
    )
    from custom_components.universal_room_automation.const import (
        OPTIMIZER_OUTCOME_DISALLOWED,
    )
    hass, _ = _make_hass(cm_options=_cm())
    coord = OptimizationCoordinator(hass)
    outcome = await coord._dispatch_device_action(
        _finding(), "aid", RESERVE_CLOUD, "number.set_value", {"value": 24},
        "propose_config",
    )
    assert outcome == OPTIMIZER_OUTCOME_DISALLOWED
    assert hass.services.calls == []
    assert len(_rows(hass, "reserve_role_hard_deny")) == 1


@pytest.mark.asyncio
async def test_optimizer_reserve_deny_is_independent_of_operator_denylist():
    """Through the full chokepoint `_apply_action`, with the operator deny
    list EMPTY (the live default): still refused."""
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationCoordinator,
    )
    from custom_components.universal_room_automation.const import (
        OPTIMIZER_OUTCOME_DISALLOWED,
    )
    hass, _ = _make_hass(cm_options=_cm(optimizer_safety_deny_entities=[]))
    coord = OptimizationCoordinator(hass)
    outcome = await coord._apply_action(_finding(), {
        "service": "number.set_value", "service_data": {"value": 24},
        "target_entity": RESERVE_CLOUD, "action_class": "config_write",
    })
    assert outcome == OPTIMIZER_OUTCOME_DISALLOWED
    assert hass.services.calls == []
    assert len(_rows(hass, "reserve_role_hard_deny")) == 1
    assert _rows(hass, "safety_denylist") == []


@pytest.mark.asyncio
async def test_optimizer_non_reserve_number_still_dispatches():
    """Control: another number entity is NOT caught by the reserve deny
    (reaches the service bus at propose_config with a zero veto window)."""
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationCoordinator,
    )
    hass, _ = _make_hass(cm_options=_cm())
    coord = OptimizationCoordinator(hass)
    f = _finding()
    outcome = await coord._dispatch_config_action(
        f, "aid", "number.pool_pump_speed", "number.set_value", {"value": 2},
        "reversible_device",  # zero veto window
    )
    from custom_components.universal_room_automation.const import (
        OPTIMIZER_OUTCOME_DISALLOWED,
    )
    assert _rows(hass, "reserve_role_hard_deny") == []
    assert outcome != OPTIMIZER_OUTCOME_DISALLOWED


def test_reserve_role_entities_reads_both_roles_and_ignores_unset():
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationCoordinator,
    )
    hass, _ = _make_hass(cm_options=_cm())
    coord = OptimizationCoordinator(hass)
    assert coord._reserve_role_entities() == frozenset({RESERVE_CLOUD, RESERVE_LOCAL})
    assert coord._reserve_role_entities({"energy_reserve_soc_entity": None}) == frozenset()
    assert coord._reserve_role_entities({}) == frozenset()
