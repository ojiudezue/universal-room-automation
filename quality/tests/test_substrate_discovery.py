"""Occupancy substrate — discovery tests (D1 acceptance).

Confirms that for synthetic CONF lists the substrate produces the
expected (entity_id, room, kind) classification triples — no area-sweep
contamination, no substring fallback, kind is determined solely by the
CONF list slot.
"""

from __future__ import annotations

import _provenance_harness  # noqa: F401
from _provenance_harness import make_hass, fake_room_entry

from custom_components.universal_room_automation.const import (
    CONF_MMWAVE_SENSORS,
    CONF_MOTION_SENSORS,
    CONF_OCCUPANCY_SENSORS,
    TIER1_KINDS,
)
from custom_components.universal_room_automation.domain_coordinators.occupancy_substrate import (  # noqa: E501
    OccupancySubstrate,
)


def _run_setup(hass, sub):
    """Synchronously drive ``async_setup`` for the substrate."""
    import asyncio
    asyncio.get_event_loop().run_until_complete(sub.async_setup())


def test_substrate_discovers_only_conf_listed_entities() -> None:
    """A room with CONF lists registers exactly those (room, kind) slots."""
    hass = make_hass()
    entry = fake_room_entry(
        "Jaya Bedroom",
        **{
            CONF_MOTION_SENSORS: ["binary_sensor.jaya_motion"],
            CONF_MMWAVE_SENSORS: ["binary_sensor.jaya_mmwave"],
            CONF_OCCUPANCY_SENSORS: [],
        },
    )
    hass.config_entries.async_entries.return_value = [entry]

    sub = OccupancySubstrate(hass)
    _run_setup(hass, sub)

    # Discovery should classify each curated entity into its CONF slot.
    assert sub._entity_to_room_kind["binary_sensor.jaya_motion"] == (
        "Jaya Bedroom",
        "motion",
    )
    assert sub._entity_to_room_kind["binary_sensor.jaya_mmwave"] == (
        "Jaya Bedroom",
        "mmwave",
    )
    # Non-CONF entities are NOT in the substrate (no area-sweep).
    assert (
        "binary_sensor.jaya_other_presence" not in sub._entity_to_room_kind
    )
    # Every TIER1_KINDS slot is present (defaulting False) in the view.
    view = sub.get_room_kinds("Jaya Bedroom")
    assert set(view.keys()) == set(TIER1_KINDS)
    for k in TIER1_KINDS:
        assert view[k] is False


def test_substrate_multi_room_isolated() -> None:
    """Each room sees only its own CONF-listed entities."""
    hass = make_hass()
    room_a = fake_room_entry(
        "Office A",
        **{CONF_MOTION_SENSORS: ["binary_sensor.office_a_motion"]},
    )
    room_b = fake_room_entry(
        "Office B",
        **{CONF_OCCUPANCY_SENSORS: ["binary_sensor.office_b_occ"]},
    )
    hass.config_entries.async_entries.return_value = [room_a, room_b]
    sub = OccupancySubstrate(hass)
    _run_setup(hass, sub)

    assert sub._entity_to_room_kind == {
        "binary_sensor.office_a_motion": ("Office A", "motion"),
        "binary_sensor.office_b_occ": ("Office B", "occupancy"),
    }
    all_view = sub.get_all_room_kinds()
    assert set(all_view.keys()) == {"Office A", "Office B"}


def test_substrate_no_area_sweep() -> None:
    """A non-CONF-listed entity matching the substring heuristic is NOT picked up."""
    hass = make_hass()
    entry = fake_room_entry(
        "Bedroom",
        **{CONF_MOTION_SENSORS: ["binary_sensor.curated_motion"]},
    )
    hass.config_entries.async_entries.return_value = [entry]
    sub = OccupancySubstrate(hass)
    _run_setup(hass, sub)

    # No substring heuristic should pull this in.
    assert (
        "binary_sensor.uncurated_mmwave_presence"
        not in sub._entity_to_room_kind
    )
    assert (
        "binary_sensor.unrelated_garden_motion"
        not in sub._entity_to_room_kind
    )
