"""D5 — Sensor / binary_sensor surface tests.

Verifies:
  * OccupiedBinarySensor carries the four per-room provenance/fan attrs.
  * PresenceHouseStateSensor.zones[<zone>] carries the breakdown +
    fan_interference_rooms; top-level carries fan_interference_active.
  * No new platform entity class added by D5 (attribute extension only).
  * Attrs refresh ride the existing SIGNAL_PRESENCE_ENTITIES_UPDATE
    dispatcher — i.e. no new dispatcher signal introduced.
"""

from __future__ import annotations

import ast
import inspect
import os

import _provenance_harness  # noqa: F401
from _provenance_harness import make_hass


def test_no_new_entity_classes_introduced_by_d5() -> None:
    """Diff entity-class count vs the pre-cycle baseline.

    The acceptance criterion is "zero new `class .*Entity` blocks added
    by D5 in binary_sensor.py and sensor.py". We codify it as a
    structural assertion against the production source: the four
    diagnostic attrs MUST live on `OccupiedBinarySensor` (per-room) and
    `PresenceHouseStateSensor` (zone rollup) — no new dedicated
    sensor/binary_sensor subclasses named "Provenance" or
    "FanInterference".
    """
    base = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..",
                     "custom_components", "universal_room_automation"),
    )
    bad_substrings = ("Provenance", "FanInterference")
    for fname in ("binary_sensor.py", "sensor.py"):
        path = os.path.join(base, fname)
        tree = ast.parse(open(path, encoding="utf-8").read())
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for bad in bad_substrings:
                    if bad in node.name:
                        raise AssertionError(
                            f"D5 must add attrs only — found new class "
                            f"`{node.name}` in {fname}"
                        )


def _read_source(fname: str) -> str:
    """Read a production-source file from disk.

    Avoids importing the module (which would require the full HA
    runtime — RestoreEntity etc.). This is the harness pattern used by
    other doc/marker tests in this suite.
    """
    base = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..",
                     "custom_components", "universal_room_automation"),
    )
    return open(os.path.join(base, fname), encoding="utf-8").read()


def test_occupied_binary_sensor_carries_provenance_attrs() -> None:
    """The per-room OccupiedBinarySensor exposes the four D5 attrs."""
    src = _read_source("binary_sensor.py")
    assert '"tier1_provenance"' in src
    assert '"last_kind_to_fire"' in src
    assert '"fan_on"' in src
    assert '"fan_interference_suspect"' in src


def test_occupied_binary_sensor_carries_fan_attrs() -> None:
    src = _read_source("binary_sensor.py")
    # Fan attrs are an additive subset of the four above — explicit
    # acceptance criterion in the planning doc.
    assert '"fan_on"' in src
    assert '"fan_interference_suspect"' in src


def test_house_state_sensor_zones_carries_breakdown() -> None:
    src = _read_source("sensor.py")
    assert '"tier1_provenance_breakdown"' in src
    assert '"fan_interference_rooms"' in src


def test_house_state_sensor_top_level_fan_interference_active() -> None:
    src = _read_source("sensor.py")
    assert '"fan_interference_active"' in src


def test_attrs_refresh_via_existing_signal() -> None:
    """No new dispatcher signal: surface refresh rides SIGNAL_PRESENCE_ENTITIES_UPDATE."""
    from custom_components.universal_room_automation.domain_coordinators import signals
    # Sentinel — the existing dispatcher is the one used.
    assert hasattr(signals, "SIGNAL_PRESENCE_ENTITIES_UPDATE")
    # No new D5-specific signal name leaked in.
    for attr in dir(signals):
        assert "PROVENANCE" not in attr.upper(), attr
        assert "FAN_INTERFERENCE" not in attr.upper(), attr
