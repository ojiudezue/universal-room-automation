"""v4.6.0 D4/D5 Registration tests.

Source-grep tests verify:
- PersonNextRoomAccuracySensor is instantiated at the same call-site as PersonLikelyNextRoomSensor
- HouseNextRoomAccuracySensor is instantiated exactly once
- Both classes are imported from sensor.py at the registration site
"""

import pytest


@pytest.fixture(scope="module")
def aggregation_src() -> str:
    with open(
        "custom_components/universal_room_automation/aggregation.py"
    ) as f:
        return f.read()


# ---------------------------------------------------------------------------
# PersonNextRoomAccuracySensor — per-person, same call-site as prediction sensor
# ---------------------------------------------------------------------------


def test_person_accuracy_sensor_imported(aggregation_src: str):
    """PersonNextRoomAccuracySensor must be imported in aggregation.py."""
    assert "PersonNextRoomAccuracySensor" in aggregation_src, (
        "D4: PersonNextRoomAccuracySensor must be imported in aggregation.py"
    )


def test_person_accuracy_sensor_instantiated(aggregation_src: str):
    """PersonNextRoomAccuracySensor must be instantiated with (hass, entry, person_id)."""
    assert "PersonNextRoomAccuracySensor(hass, entry, person_id)" in aggregation_src, (
        "D4: PersonNextRoomAccuracySensor must be instantiated per person"
    )


def test_person_accuracy_at_same_callsite_as_likely_next_room(aggregation_src: str):
    """PersonNextRoomAccuracySensor must be registered at the same call-site
    as PersonLikelyNextRoomSensor (same loop, same entities.extend block).
    """
    likely_pos = aggregation_src.find("PersonLikelyNextRoomSensor(hass, entry, person_id)")
    accuracy_pos = aggregation_src.find("PersonNextRoomAccuracySensor(hass, entry, person_id)")
    assert likely_pos >= 0, "PersonLikelyNextRoomSensor must be present"
    assert accuracy_pos >= 0, "PersonNextRoomAccuracySensor must be present"
    # Both should be within the same `entities.extend([...])` block.
    # Find the enclosing extend call for each.
    extend_before_likely = aggregation_src.rfind("entities.extend", 0, likely_pos)
    extend_before_accuracy = aggregation_src.rfind("entities.extend", 0, accuracy_pos)
    assert extend_before_likely == extend_before_accuracy, (
        "D4: PersonNextRoomAccuracySensor must be in the same entities.extend() "
        "block as PersonLikelyNextRoomSensor"
    )


def test_person_accuracy_in_per_person_import(aggregation_src: str):
    """PersonNextRoomAccuracySensor must be imported alongside PersonLikelyNextRoomSensor."""
    # Find the import block that has PersonLikelyNextRoomSensor
    import_pos = aggregation_src.find("PersonLikelyNextRoomSensor")
    import_block_start = aggregation_src.rfind("from .sensor import", 0, import_pos)
    import_block_end = aggregation_src.find("\n)", import_block_start)
    import_block = aggregation_src[import_block_start:import_block_end + 2]
    assert "PersonNextRoomAccuracySensor" in import_block, (
        "D4: PersonNextRoomAccuracySensor must be in the same from .sensor import "
        "block as PersonLikelyNextRoomSensor"
    )


# ---------------------------------------------------------------------------
# HouseNextRoomAccuracySensor — exactly once, outside per-person loop
# ---------------------------------------------------------------------------


def test_house_accuracy_sensor_imported(aggregation_src: str):
    """HouseNextRoomAccuracySensor must be imported in aggregation.py."""
    assert "HouseNextRoomAccuracySensor" in aggregation_src, (
        "D5: HouseNextRoomAccuracySensor must be imported in aggregation.py"
    )


def test_house_accuracy_sensor_instantiated(aggregation_src: str):
    """HouseNextRoomAccuracySensor must be instantiated with (hass, entry)."""
    assert "HouseNextRoomAccuracySensor(hass, entry)" in aggregation_src, (
        "D5: HouseNextRoomAccuracySensor must be instantiated once"
    )


def test_house_accuracy_sensor_instantiated_exactly_once(aggregation_src: str):
    """HouseNextRoomAccuracySensor must appear exactly once as an instantiation
    to ensure only one house sensor is registered per integration entry.
    """
    count = aggregation_src.count("HouseNextRoomAccuracySensor(hass, entry)")
    assert count == 1, (
        f"D5: HouseNextRoomAccuracySensor must be instantiated exactly once, "
        f"found {count} times"
    )


def test_house_sensor_outside_per_person_loop(aggregation_src: str):
    """HouseNextRoomAccuracySensor must be instantiated OUTSIDE the per-person loop.

    Per-person loop instantiates PersonNextRoomAccuracySensor. House sensor is
    once per integration, so it must be outside the loop.
    """
    # The per-person loop starts at 'for person_entity_id in tracked_persons'
    loop_start = aggregation_src.find("for person_entity_id in tracked_persons")
    assert loop_start >= 0, "per-person loop must exist"
    # Find the loop end by finding 'async_add_entities(entities)' (which is after the loop)
    add_entities_pos = aggregation_src.find("async_add_entities(entities)", loop_start)
    assert add_entities_pos > loop_start

    house_pos = aggregation_src.find("HouseNextRoomAccuracySensor(hass, entry)")
    assert house_pos >= 0

    # House sensor instantiation must be between the loop block end and async_add_entities
    # The loop body is indented; house sensor is at module/function level after the loop.
    # Simpler: verify house_pos > loop_start and within 200 chars of async_add_entities
    assert house_pos > loop_start, (
        "D5: HouseNextRoomAccuracySensor must come after the per-person loop"
    )
    # Should be close to async_add_entities (not buried inside loop iterations)
    # The distance from house_pos to add_entities must be short (within the same block)
    gap = add_entities_pos - house_pos
    assert gap < 300, (
        f"D5: HouseNextRoomAccuracySensor instantiation is too far from "
        f"async_add_entities — it may be inside the per-person loop (gap={gap})"
    )
