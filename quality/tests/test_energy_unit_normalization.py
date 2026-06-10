"""Tests for D1: energy_state_to_kwh shared helper + coordinator integration.

Drives the production helper in
custom_components/universal_room_automation/domain_coordinators/_units.py
and verifies it is plumbed into coordinator._update_energy_tracking at
line 1876 (per PLANNING_energy_unit_normalization_and_attribution.md D1).

Bug Class #30 (Unit-of-Measurement Drift) recurrence on the energy
device class. Pre-fix: a Wh-reporting sensor inflated STATE_ENERGY_TODAY
1000× (master_suite zone observed at ~1,671 kWh on v5.3.0 live).
"""
import importlib.util
import os
import sys
import types

import pytest


# Make custom_components importable as a flat package so the helper
# import path matches production.
_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_CC_PARENT = os.path.join(_REPO, "custom_components")
if _CC_PARENT not in sys.path:
    sys.path.insert(0, _CC_PARENT)


# Direct import of the helper module via file path — avoids needing
# the full custom_components.universal_room_automation init graph.
def _load_units_module():
    """Load _units.py directly so the test exercises production source."""
    path = os.path.join(
        _REPO,
        "custom_components",
        "universal_room_automation",
        "domain_coordinators",
        "_units.py",
    )
    spec = importlib.util.spec_from_file_location("_ura_units_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_units = _load_units_module()


class _FakeState:
    """Minimal stand-in for an HA State object."""
    def __init__(self, state, attributes=None):
        self.state = state
        self.attributes = attributes or {}


# ---------------------------------------------------------------------------
# Helper behavior
# ---------------------------------------------------------------------------

def test_kwh_passthrough():
    s = _FakeState("1.0", {"unit_of_measurement": "kWh"})
    assert _units.energy_state_to_kwh(s) == 1.0


def test_kwh_case_insensitive():
    s = _FakeState("2.5", {"unit_of_measurement": "kwh"})
    assert _units.energy_state_to_kwh(s) == 2.5


def test_wh_converts_to_kwh():
    s = _FakeState("1000.0", {"unit_of_measurement": "Wh"})
    assert _units.energy_state_to_kwh(s) == 1.0


def test_wh_lowercase():
    s = _FakeState("2500", {"unit_of_measurement": "wh"})
    assert _units.energy_state_to_kwh(s) == 2.5


def test_mwh_converts_to_kwh():
    s = _FakeState("0.5", {"unit_of_measurement": "MWh"})
    assert _units.energy_state_to_kwh(s) == 500.0


def test_one_kwh_equals_one_thousand_wh():
    a = _FakeState("1.0", {"unit_of_measurement": "kWh"})
    b = _FakeState("1000.0", {"unit_of_measurement": "Wh"})
    assert _units.energy_state_to_kwh(a) == _units.energy_state_to_kwh(b)


def test_missing_uom_taken_as_kwh():
    # Sources that omit uom are taken at face value (HA default semantics);
    # this matches pre-fix behavior for already-correct sources.
    s = _FakeState("3.0", {})
    assert _units.energy_state_to_kwh(s) == 3.0


def test_string_unavailable_returns_none():
    s = _FakeState("unavailable", {"unit_of_measurement": "kWh"})
    assert _units.energy_state_to_kwh(s) is None


def test_string_unknown_returns_none():
    s = _FakeState("unknown", {"unit_of_measurement": "kWh"})
    assert _units.energy_state_to_kwh(s) is None


def test_empty_state_returns_none():
    s = _FakeState("", {"unit_of_measurement": "kWh"})
    assert _units.energy_state_to_kwh(s) is None


def test_none_state_object_returns_none():
    assert _units.energy_state_to_kwh(None) is None


def test_state_state_is_none_returns_none():
    s = _FakeState(None, {"unit_of_measurement": "kWh"})
    assert _units.energy_state_to_kwh(s) is None


def test_unparseable_returns_none():
    s = _FakeState("not_a_number", {"unit_of_measurement": "kWh"})
    assert _units.energy_state_to_kwh(s) is None


def test_unrecognized_uom_returns_none():
    # Refuse silently misattributing — return None.
    s = _FakeState("1.0", {"unit_of_measurement": "joules"})
    assert _units.energy_state_to_kwh(s) is None


def test_attributes_missing_returns_value_anyway():
    """Attributes object absent → treat as missing uom (pass through)."""
    class _NoAttrs:
        state = "5.0"
        attributes = None
    assert _units.energy_state_to_kwh(_NoAttrs()) == 5.0


# ---------------------------------------------------------------------------
# Coordinator wire-up smoke test
# ---------------------------------------------------------------------------

def test_helper_imported_in_coordinator():
    """coordinator.py imports energy_state_to_kwh from the new module."""
    path = os.path.join(
        _REPO,
        "custom_components",
        "universal_room_automation",
        "coordinator.py",
    )
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    assert "from .domain_coordinators._units import energy_state_to_kwh" in src, (
        "coordinator.py must import the unit-normalization helper"
    )
    # The energy-tracking read site uses the helper, not raw float(state.state).
    assert "energy_state_to_kwh(state)" in src, (
        "coordinator._update_energy_tracking must route the read through the helper"
    )


def test_helper_imported_in_aggregation():
    """aggregation.py imports energy_state_to_kwh for tier reads."""
    path = os.path.join(
        _REPO,
        "custom_components",
        "universal_room_automation",
        "aggregation.py",
    )
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    assert "energy_state_to_kwh" in src, (
        "aggregation must import the energy unit-normalization helper"
    )
    assert "energy_state_to_kwh(state)" in src, (
        "aggregation._sum_sensors / whole-house tier must use the helper"
    )


# ---------------------------------------------------------------------------
# Power surface — Bug Class #30 sibling (whole-house power cycle)
# ---------------------------------------------------------------------------

def test_power_w_passthrough():
    s = _FakeState("100.0", {"unit_of_measurement": "W"})
    assert _units.power_state_to_w(s) == 100.0


def test_power_w_case_insensitive():
    s = _FakeState("250", {"unit_of_measurement": "w"})
    assert _units.power_state_to_w(s) == 250.0


def test_power_kw_converts_to_w():
    # Live trigger: Envoy current_power_consumption reports kW. 2.7 kW
    # configured raw → 0.29 W observed pre-fix (different sensor + magnitude
    # but same kW-vs-W root cause). 1 kW must become 1000 W.
    s = _FakeState("2.7", {"unit_of_measurement": "kW"})
    assert _units.power_state_to_w(s) == 2700.0


def test_power_kw_lowercase():
    s = _FakeState("1.5", {"unit_of_measurement": "kw"})
    assert _units.power_state_to_w(s) == 1500.0


def test_power_mw_converts_to_w():
    s = _FakeState("0.001", {"unit_of_measurement": "MW"})
    assert _units.power_state_to_w(s) == 1000.0


def test_power_one_kw_equals_one_thousand_w():
    a = _FakeState("1.0", {"unit_of_measurement": "kW"})
    b = _FakeState("1000.0", {"unit_of_measurement": "W"})
    assert _units.power_state_to_w(a) == _units.power_state_to_w(b)


def test_power_missing_uom_taken_as_w():
    # Sources omitting uom are taken at face value as Watts — matches the
    # pre-fix behavior at WholeHousePowerSensor._sum_sensors and the room
    # coordinator power-sum (Shelly / SPAN native Watts).
    s = _FakeState("42.0", {})
    assert _units.power_state_to_w(s) == 42.0


def test_power_unavailable_returns_none():
    s = _FakeState("unavailable", {"unit_of_measurement": "W"})
    assert _units.power_state_to_w(s) is None


def test_power_unknown_returns_none():
    s = _FakeState("unknown", {"unit_of_measurement": "kW"})
    assert _units.power_state_to_w(s) is None


def test_power_empty_state_returns_none():
    s = _FakeState("", {"unit_of_measurement": "W"})
    assert _units.power_state_to_w(s) is None


def test_power_none_state_object_returns_none():
    assert _units.power_state_to_w(None) is None


def test_power_state_state_is_none_returns_none():
    s = _FakeState(None, {"unit_of_measurement": "W"})
    assert _units.power_state_to_w(s) is None


def test_power_garbage_returns_none():
    s = _FakeState("not_a_number", {"unit_of_measurement": "W"})
    assert _units.power_state_to_w(s) is None


def test_power_unrecognized_uom_returns_none():
    # Refuse silently misattributing — return None.
    s = _FakeState("100", {"unit_of_measurement": "BTU/h"})
    assert _units.power_state_to_w(s) is None


def test_power_attributes_missing_returns_value_anyway():
    """Attributes object absent → treat as missing uom (W pass-through)."""
    class _NoAttrs:
        state = "12.5"
        attributes = None
    assert _units.power_state_to_w(_NoAttrs()) == 12.5


def test_power_whole_house_sum_mixed_w_and_kw():
    """A whole-house list mixing a native-W and a kW source must sum in W.

    Simulates the live bug: an Envoy kW source + a SPAN W source
    configured together. Pre-fix sum was 2.71 (W + raw kW number);
    post-fix sum must be 2700 + 100 = 2800 W.
    """
    span = _FakeState("100.0", {"unit_of_measurement": "W"})
    envoy = _FakeState("2.7", {"unit_of_measurement": "kW"})
    total = _units.power_state_to_w(span) + _units.power_state_to_w(envoy)
    assert total == 2800.0


def test_power_helpers_used_in_aggregation_and_coordinator():
    """The whole-house cycle plumbs power_state_to_w into both surfaces."""
    for filename in ("aggregation.py", "coordinator.py"):
        path = os.path.join(
            _REPO,
            "custom_components",
            "universal_room_automation",
            filename,
        )
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        assert "power_state_to_w" in src, (
            f"{filename} must import + use the power unit-normalization helper"
        )
