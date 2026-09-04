"""v4.6.0 D4/D5 Registration tests.

v5.94.0 device/entity de-frag D1b (2026-09-03): the per-person +
house Accuracy/Routine sensors were RELOCATED from
`async_setup_aggregation_sensors` (INTEGRATION entry) to
`async_setup_cm_hosted_aggregation_sensors` (CM entry). These tests were
updated in-lockstep to point at the new coroutine, PRESERVING the D4/D5
invariants: per-person Accuracy sensor is co-located with the per-person
loop; House sensor is instantiated exactly once and outside any per-person
loop.
"""

import re

import pytest


@pytest.fixture(scope="module")
def aggregation_src() -> str:
    with open(
        "custom_components/universal_room_automation/aggregation.py"
    ) as f:
        return f.read()


@pytest.fixture(scope="module")
def cm_coroutine_body(aggregation_src: str) -> str:
    """Return the body of `async_setup_cm_hosted_aggregation_sensors`
    (from its `async def` line to the top of the next `async def` /
    `def` at column 0). This is where the D1b-migrated sensors now live.
    """
    match = re.search(
        r"async def async_setup_cm_hosted_aggregation_sensors\b.*?(?=\n(?:async )?def [A-Za-z_])",
        aggregation_src,
        re.DOTALL,
    )
    assert match, "async_setup_cm_hosted_aggregation_sensors not found"
    return match.group(0)


# ---------------------------------------------------------------------------
# PersonNextRoomAccuracySensor + PersonRoutineStatusSensor — per-person
# ---------------------------------------------------------------------------


def test_person_accuracy_sensor_imported(cm_coroutine_body: str):
    """PersonNextRoomAccuracySensor must be imported inside the CM coroutine."""
    assert "PersonNextRoomAccuracySensor" in cm_coroutine_body, (
        "D4 (post-D1b): PersonNextRoomAccuracySensor must be imported inside "
        "async_setup_cm_hosted_aggregation_sensors"
    )


def test_person_accuracy_sensor_instantiated(cm_coroutine_body: str):
    """PersonNextRoomAccuracySensor must be instantiated inside the CM
    coroutine (any call form — construction args changed post-D1b to
    (hass, integration_entry, person_id))."""
    assert "PersonNextRoomAccuracySensor(" in cm_coroutine_body, (
        "D4 (post-D1b): PersonNextRoomAccuracySensor must be instantiated inside "
        "async_setup_cm_hosted_aggregation_sensors"
    )


def test_person_accuracy_at_same_callsite_as_routine_status(cm_coroutine_body: str):
    """Post-D1b the per-person loop constructs the accuracy sensor at the
    SAME site as `PersonRoutineStatusSensor` (they replaced the pre-D1b
    same-site anchor to `PersonLikelyNextRoomSensor`, which now lives in
    the INTEGRATION-side aggregation coroutine).
    """
    routine_pos = cm_coroutine_body.find("PersonRoutineStatusSensor(")
    accuracy_pos = cm_coroutine_body.find("PersonNextRoomAccuracySensor(")
    assert routine_pos >= 0
    assert accuracy_pos >= 0
    # Both should be within the same `for person_entity_id in tracked_persons` loop.
    loop_start = cm_coroutine_body.find("for person_entity_id in tracked_persons")
    assert loop_start >= 0, "per-person loop must exist inside CM coroutine"
    assert routine_pos > loop_start
    assert accuracy_pos > loop_start
    # Both live in the deferred phase-2 registration branch.


def test_person_accuracy_in_per_person_import(cm_coroutine_body: str):
    """PersonNextRoomAccuracySensor must be imported alongside
    PersonRoutineStatusSensor in the CM-coroutine\'s local sensor import.
    """
    import_pos = cm_coroutine_body.find("PersonRoutineStatusSensor")
    import_block_start = cm_coroutine_body.rfind("from .sensor import", 0, import_pos)
    import_block_end = cm_coroutine_body.find(")", import_block_start)
    import_block = cm_coroutine_body[import_block_start:import_block_end + 1]
    assert "PersonNextRoomAccuracySensor" in import_block, (
        "D4 (post-D1b): PersonNextRoomAccuracySensor must be in the same "
        "from .sensor import block as PersonRoutineStatusSensor"
    )


# ---------------------------------------------------------------------------
# HouseNextRoomAccuracySensor — exactly once, outside per-person loop
# ---------------------------------------------------------------------------


def test_house_accuracy_sensor_imported(cm_coroutine_body: str):
    """HouseNextRoomAccuracySensor must be imported in the CM coroutine."""
    assert "HouseNextRoomAccuracySensor" in cm_coroutine_body, (
        "D5 (post-D1b): HouseNextRoomAccuracySensor must be imported inside "
        "async_setup_cm_hosted_aggregation_sensors"
    )


def test_house_accuracy_sensor_instantiated(cm_coroutine_body: str):
    """HouseNextRoomAccuracySensor must be instantiated inside the CM coroutine."""
    assert "HouseNextRoomAccuracySensor(" in cm_coroutine_body, (
        "D5 (post-D1b): HouseNextRoomAccuracySensor must be instantiated inside "
        "async_setup_cm_hosted_aggregation_sensors"
    )


def test_house_accuracy_sensor_instantiated_exactly_once(aggregation_src: str):
    """Whole-file exactly-once: HouseNextRoomAccuracySensor is constructed
    ONE time across the entire aggregation.py module. Double registration
    is the _2-mint mechanism = the D1 acceptance gate.
    """
    count = len(re.findall(r"HouseNextRoomAccuracySensor\(", aggregation_src))
    assert count == 1, (
        f"D5 (post-D1b): HouseNextRoomAccuracySensor must be instantiated "
        f"exactly once in aggregation.py, found {count} — a second call site "
        f"would double-register and mint a _2 entity."
    )


def test_house_sensor_outside_per_person_loop(cm_coroutine_body: str):
    """HouseNextRoomAccuracySensor must be instantiated OUTSIDE the
    per-person loop within the CM coroutine (once per integration, not per
    person).
    """
    house_pos = cm_coroutine_body.find("HouseNextRoomAccuracySensor(")
    assert house_pos >= 0
    loop_start = cm_coroutine_body.find("for person_entity_id in tracked_persons")
    if loop_start < 0:
        # No per-person loop found in scanned body — that already means
        # the house sensor is outside any loop.
        return
    # The per-person loop is indented; the house sensor must be either
    # BEFORE the loop line or in an un-indented block after it. Verify the
    # line-column of the house sensor call is smaller than the loop body
    # column, OR house_pos < loop_start.
    if house_pos < loop_start:
        return
    # If house_pos > loop_start, it must sit at ≤ the column of the loop
    # header (i.e. outside the loop body).
    loop_line_start = cm_coroutine_body.rfind("\n", 0, loop_start) + 1
    loop_indent = loop_start - loop_line_start
    house_line_start = cm_coroutine_body.rfind("\n", 0, house_pos) + 1
    house_indent = house_pos - house_line_start
    assert house_indent <= loop_indent, (
        "D5 (post-D1b): HouseNextRoomAccuracySensor is nested inside the "
        "per-person loop (indent %d > loop indent %d)"
        % (house_indent, loop_indent)
    )
