"""ACTIVITY-LOG-BARE-SLUG-ENTITY-ID-1 — the ura_action bus event must only
carry a well-formed entity_id.

WHY THIS MATTERS BEYOND TIDINESS. Home Assistant's recorder subscribes to EVERY
event and calls `split_entity_id()` on any `entity_id` it finds. A bare slug
raises `ValueError: Invalid entity ID <x>` *inside the recorder's listener job*,
so a URA-internal naming slip surfaces as an ERROR in someone else's code path.
Observed live on 2026-09-16 from the EVSE charge-onset telemetry passing a BAY
slug ("garage_a"): 24 such rows in the URA DB.

These tests DISCRIMINATE rather than merely assert success: a well-formed id must
still ride the event, and a malformed one must not — a guard that dropped
everything, or kept everything, fails exactly one of them.
"""
from __future__ import annotations

import sys
import types

import pytest


def _load_guard():
    """Import the shape guard without dragging in the HA runtime.

    The helper is a pure function, so we read it out of the module source rather
    than importing the package (which would need a live hass).
    """
    import ast
    import pathlib

    src = pathlib.Path(__file__).resolve().parents[2].joinpath(
        "custom_components", "universal_room_automation", "activity_logger.py"
    ).read_text()
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "_is_entity_id_shaped":
            mod = types.ModuleType("_guard")
            exec(compile(ast.Module(body=[node], type_ignores=[]), "<guard>", "exec"), mod.__dict__)
            return mod._is_entity_id_shaped
    raise AssertionError(
        "_is_entity_id_shaped not found in activity_logger.py — the guard this "
        "test protects has been removed or renamed"
    )


GUARD = _load_guard()


@pytest.mark.parametrize(
    "value",
    [
        "switch.garage_a_charger",
        "sensor.ura_appliance_census",
        "binary_sensor.x_y_2",
    ],
)
def test_well_formed_entity_ids_are_admitted(value):
    """A real entity_id must still ride the event — the guard must not be a
    blanket drop (that would silently break every logbook link)."""
    assert GUARD(value) is True


@pytest.mark.parametrize(
    "value",
    [
        "garage_a",          # THE live offender (EVSE onset bay slug)
        "garage_b",          # its sibling, also observed in the DB
        "",                  # empty
        "no_dot_at_all",
        ".leading",          # empty domain
        "trailing.",         # empty object_id
        "too.many.dots",     # split_entity_id would also reject this
    ],
)
def test_malformed_values_are_rejected(value):
    """Anything HA's split_entity_id would raise on must be rejected here."""
    assert GUARD(value) is False


def test_guard_agrees_with_home_assistants_own_split():
    """Cross-check against an INDEPENDENT oracle rather than our own reasoning.

    We re-implement nothing: we assert that for every sample, our guard returns
    True exactly when HA's real `split_entity_id` does NOT raise. If HA ever
    changes that contract this test fails, which is the correct outcome — the
    guard exists only to predict HA's behaviour.
    """
    try:
        from homeassistant.core import split_entity_id
    except Exception:  # pragma: no cover - HA not installed in this env
        pytest.skip("homeassistant not importable in this environment")

    samples = [
        "switch.garage_a_charger",
        "sensor.x",
        "garage_a",
        "",
        "no_dot_at_all",
        ".leading",
        "trailing.",
    ]
    for value in samples:
        try:
            split_entity_id(value)
            ha_accepts = True
        except Exception:
            ha_accepts = False
        assert GUARD(value) is ha_accepts, (
            f"guard disagrees with HA's split_entity_id for {value!r}: "
            f"guard={GUARD(value)} ha_accepts={ha_accepts}"
        )


def test_the_live_offender_is_specifically_covered():
    """Regression anchor for the exact value seen on the running system."""
    assert GUARD("garage_a") is False, (
        "garage_a must be rejected — this is the value that produced "
        "'ValueError: Invalid entity ID garage_a' inside HA's recorder on "
        "2026-09-16"
    )
