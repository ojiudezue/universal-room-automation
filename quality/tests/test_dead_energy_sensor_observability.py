"""Tests for D4: dead-energy-sensor observability.

When ALL of a room's configured energy sensors are unavailable in a
cycle, the coordinator must:
- set data[STATE_ENERGY_TODAY] = None (not 0.0)
- log a WARNING rate-limited at most once per hour per room
- expose `energy_sensors_dead: True` attribute on EnergyTodaySensor

Downstream consumers of STATE_ENERGY_TODAY use
`coord.data.get(STATE_ENERGY_TODAY, 0)` followed by `if energy:` which
treats None as falsy → the dead room cleanly skips the sum.
"""
import importlib.util
import os
import sys

import pytest


_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# Source-level verification (cheap, no HA import needed)
# ---------------------------------------------------------------------------

def _coordinator_source():
    path = os.path.join(
        _REPO, "custom_components", "universal_room_automation", "coordinator.py",
    )
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _sensor_source():
    path = os.path.join(
        _REPO, "custom_components", "universal_room_automation", "sensor.py",
    )
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def test_coordinator_tracks_dead_count():
    """Coordinator counts unavailable sensors per cycle."""
    src = _coordinator_source()
    assert "dead_count" in src
    assert "dead_count += 1" in src


def test_coordinator_sets_none_when_all_dead():
    """When all sensors dead, STATE_ENERGY_TODAY is set to None."""
    src = _coordinator_source()
    # The all-dead branch must assign None, not 0.0.
    assert "all_dead" in src
    assert "data[STATE_ENERGY_TODAY] = None" in src


def test_coordinator_rate_limits_warning():
    """WARNING is gated on monotonic clock with 1-hour window."""
    src = _coordinator_source()
    assert "_energy_sensors_dead_last_warn" in src
    # Rate limit window: 3600 seconds.
    assert "3600.0" in src or "3600" in src
    assert "time.monotonic()" in src


def test_coordinator_exposes_state_flag():
    """Instance attribute _energy_sensors_dead is set per cycle."""
    src = _coordinator_source()
    assert "self._energy_sensors_dead = all_dead" in src


def test_sensor_exposes_energy_sensors_dead_attribute():
    """EnergyTodaySensor surfaces energy_sensors_dead in extra_state_attributes."""
    src = _sensor_source()
    # Find the EnergyTodaySensor class.
    cls_idx = src.find("class EnergyTodaySensor(")
    assert cls_idx > 0
    # Find next class definition to bound the slice.
    next_cls = src.find("\nclass ", cls_idx + 1)
    body = src[cls_idx:next_cls if next_cls > 0 else len(src)]
    assert "extra_state_attributes" in body
    assert "energy_sensors_dead" in body
    assert "_energy_sensors_dead" in body  # reads from coordinator instance


# ---------------------------------------------------------------------------
# Behavioral test: EnergyTodaySensor attribute reflects coordinator flag
# ---------------------------------------------------------------------------

def test_energy_today_sensor_attribute_reads_coordinator_flag():
    """Drive EnergyTodaySensor.extra_state_attributes against a stubbed coord."""
    try:
        sys.path.insert(0, os.path.join(_REPO, "custom_components"))
        from universal_room_automation import sensor as _sensor_mod
    except Exception as e:
        pytest.skip(f"sensor module not importable: {e}")

    class _Coord:
        def __init__(self, dead):
            self._energy_sensors_dead = dead
            self.data = {}

    # Bypass UniversalRoomEntity init (needs registry etc).
    ets = _sensor_mod.EnergyTodaySensor.__new__(_sensor_mod.EnergyTodaySensor)
    ets.coordinator = _Coord(True)
    attrs = ets.extra_state_attributes
    assert attrs.get("energy_sensors_dead") is True

    ets.coordinator = _Coord(False)
    attrs = ets.extra_state_attributes
    assert attrs.get("energy_sensors_dead") is False


def test_energy_today_sensor_attribute_defaults_false_when_attr_missing():
    """If coordinator hasn't yet run a cycle, attribute must default safely to False."""
    try:
        sys.path.insert(0, os.path.join(_REPO, "custom_components"))
        from universal_room_automation import sensor as _sensor_mod
    except Exception as e:
        pytest.skip(f"sensor module not importable: {e}")

    class _Coord:
        data = {}
        # no _energy_sensors_dead attr

    ets = _sensor_mod.EnergyTodaySensor.__new__(_sensor_mod.EnergyTodaySensor)
    ets.coordinator = _Coord()
    attrs = ets.extra_state_attributes
    assert attrs.get("energy_sensors_dead") is False


# ---------------------------------------------------------------------------
# Downstream consumer None-safety audit
# ---------------------------------------------------------------------------

def test_downstream_consumers_handle_none_via_truthiness():
    """The 7 STATE_ENERGY_TODAY consumers all use the `if energy:` pattern OR `or 0`."""
    agg_path = os.path.join(
        _REPO, "custom_components", "universal_room_automation", "aggregation.py",
    )
    with open(agg_path, encoding="utf-8") as fh:
        agg = fh.read()
    # Every STATE_ENERGY_TODAY read in aggregation.py must be followed by
    # either an `if energy:` truthiness gate or an `or 0` coalesce.
    lines = agg.splitlines()
    # Skip lines inside import blocks (the const is imported by name).
    in_import_block = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("from ") or stripped.startswith("import "):
            in_import_block = "(" in stripped and ")" not in stripped
            continue
        if in_import_block:
            if ")" in stripped:
                in_import_block = False
            continue
        if "STATE_ENERGY_TODAY" not in line:
            continue
        # Look at this line + next two for the None-handling idiom.
        context = "\n".join(lines[i:i + 3])
        assert ("if energy:" in context) or ("or 0" in context) or (
            "any_valid = True" in context
        ), (
            f"aggregation.py:{i+1} consumes STATE_ENERGY_TODAY without "
            f"a None-safe truthiness gate or 'or 0' coalesce. Context:\n{context}"
        )
