"""v4.6.2 — sensor classes registered exactly once.

Source-grep regression guard for the double-registration bug caught
during Phase 2 review: PersonNextRoomAccuracySensor, HouseNextRoomAccuracySensor,
PersonRoutineStatusSensor, HouseRoutineStatusSensor must each be instantiated
in EXACTLY ONE call-site across sensor.py + aggregation.py.

A class instantiated in two setup paths would either collide on unique_id
(HA logs warnings, second instance discarded) or — worse — register both
under different entry types and produce orphan duplicates.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
PKG = REPO_ROOT / "custom_components" / "universal_room_automation"


def _instantiation_call_sites(src: str, class_name: str) -> list[int]:
    """Return line numbers where `ClassName(` appears as a call (not class
    definition / type hint / log message)."""
    sites = []
    for i, line in enumerate(src.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("class "):
            continue
        if stripped.startswith("#"):
            continue
        if f'"{class_name}' in stripped or f"'{class_name}" in stripped:
            # log-string mention, not a call
            continue
        if re.search(rf"\b{class_name}\(", line):
            sites.append(i)
    return sites


SENSOR_SRC = (PKG / "sensor.py").read_text()
AGGREGATION_SRC = (PKG / "aggregation.py").read_text()
COMBINED = SENSOR_SRC + "\n" + AGGREGATION_SRC


@pytest.mark.parametrize(
    "class_name",
    [
        "PersonNextRoomAccuracySensor",
        "HouseNextRoomAccuracySensor",
        "PersonRoutineStatusSensor",
        "HouseRoutineStatusSensor",
    ],
)
def test_class_instantiated_exactly_once_across_sensor_and_aggregation(class_name: str):
    """Each accuracy/routine sensor class is instantiated in exactly ONE
    call-site across sensor.py + aggregation.py. Two registration sites
    cause unique_id collisions on restart and waste DB queries.
    """
    sensor_sites = _instantiation_call_sites(SENSOR_SRC, class_name)
    agg_sites = _instantiation_call_sites(AGGREGATION_SRC, class_name)
    total = len(sensor_sites) + len(agg_sites)
    assert total == 1, (
        f"{class_name} instantiated {total} times "
        f"(sensor.py lines {sensor_sites}, aggregation.py lines {agg_sites}). "
        "Must be exactly 1 to avoid unique_id collision on restart."
    )


def test_aggregation_is_the_single_registration_site():
    """Convention: v4.6.0 + v4.6.2 CM-device-bound aggregate sensors
    register via aggregation.async_setup_aggregation_sensors (Integration
    entry path). The CM-entry path in sensor.async_setup_entry MUST NOT
    re-register them — that was the Phase 2 build bug.
    """
    for class_name in (
        "PersonNextRoomAccuracySensor",
        "HouseNextRoomAccuracySensor",
        "PersonRoutineStatusSensor",
        "HouseRoutineStatusSensor",
    ):
        agg_sites = _instantiation_call_sites(AGGREGATION_SRC, class_name)
        sensor_sites = _instantiation_call_sites(SENSOR_SRC, class_name)
        assert len(agg_sites) == 1, (
            f"{class_name}: expected exactly 1 instantiation in aggregation.py, "
            f"got {len(agg_sites)} at lines {agg_sites}"
        )
        assert len(sensor_sites) == 0, (
            f"{class_name}: must NOT be instantiated in sensor.py "
            f"(got call-sites at {sensor_sites}). All CM-device-bound "
            f"aggregate sensors register via aggregation.py."
        )
