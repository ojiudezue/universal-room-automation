"""Occupancy substrate — classification tests.

Kind is ALWAYS the CONF list slot — never the substring heuristic — for
CONF-listed sensors. Defensive multi-list membership uses precedence
motion → mmwave → occupancy with a WARN log.
"""

from __future__ import annotations

import logging

import _provenance_harness  # noqa: F401
from _provenance_harness import make_hass, fake_room_entry

from custom_components.universal_room_automation.const import (
    CONF_MMWAVE_SENSORS,
    CONF_MOTION_SENSORS,
    CONF_OCCUPANCY_SENSORS,
)
from custom_components.universal_room_automation.domain_coordinators.occupancy_substrate import (  # noqa: E501
    OccupancySubstrate,
)


def _run_setup(sub):
    import asyncio
    asyncio.get_event_loop().run_until_complete(sub.async_setup())


def test_classification_uses_conf_slot_not_substring() -> None:
    """A naming-mismatched entity uses its CONF slot, not its name."""
    hass = make_hass()
    # A "_motion"-named entity placed in CONF_MMWAVE_SENSORS must be
    # classified as mmwave (CONF wins).
    entry = fake_room_entry(
        "Exercise",
        **{
            CONF_MOTION_SENSORS: [],
            CONF_MMWAVE_SENSORS: ["binary_sensor.misnamed_motion"],
            CONF_OCCUPANCY_SENSORS: [],
        },
    )
    hass.config_entries.async_entries.return_value = [entry]
    sub = OccupancySubstrate(hass)
    _run_setup(sub)
    assert sub._entity_to_room_kind["binary_sensor.misnamed_motion"] == (
        "Exercise",
        "mmwave",
    )


def test_classification_precedence_motion_over_mmwave_over_occupancy(
    caplog,
) -> None:
    """Multi-list membership: motion > mmwave > occupancy, WARN logged."""
    caplog.set_level(logging.WARNING)
    hass = make_hass()
    entry = fake_room_entry(
        "Living Room",
        **{
            CONF_MOTION_SENSORS: ["binary_sensor.dup"],
            CONF_MMWAVE_SENSORS: ["binary_sensor.dup"],
            CONF_OCCUPANCY_SENSORS: ["binary_sensor.dup"],
        },
    )
    hass.config_entries.async_entries.return_value = [entry]
    sub = OccupancySubstrate(hass)
    _run_setup(sub)
    # Motion wins (declared first in precedence).
    assert sub._entity_to_room_kind["binary_sensor.dup"] == (
        "Living Room",
        "motion",
    )
    # A WARN should have been emitted at least once for the duplicates.
    assert any(
        "multiple CONF lists" in record.message for record in caplog.records
    )
