"""Occupancy substrate — startup seeding tests (v4.7.18.1 B-HIGH-1 parity).

The substrate must read current ``hass.states`` at ``async_setup`` and
seed ``_raw_state`` so the first post-settle tick agrees with reality.
The seed and live-edge paths must use the SAME predicate (state == "on";
unavailable/unknown → False) so they cannot diverge.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import _provenance_harness  # noqa: F401
from _provenance_harness import make_hass, fake_room_entry

from custom_components.universal_room_automation.const import (
    CONF_MMWAVE_SENSORS,
    CONF_MOTION_SENSORS,
)
from custom_components.universal_room_automation.domain_coordinators.occupancy_substrate import (  # noqa: E501
    OccupancySubstrate,
)


def _state(value: str):
    s = MagicMock()
    s.state = value
    return s


def _run_setup(sub):
    import asyncio
    asyncio.get_event_loop().run_until_complete(sub.async_setup())


def test_seed_picks_up_on_state() -> None:
    hass = make_hass()
    entry = fake_room_entry(
        "Kitchen",
        **{CONF_MMWAVE_SENSORS: ["binary_sensor.kitchen_mmwave"]},
    )
    hass.config_entries.async_entries.return_value = [entry]

    def _states_get(entity_id):
        if entity_id == "binary_sensor.kitchen_mmwave":
            return _state("on")
        return None

    hass.states.get = MagicMock(side_effect=_states_get)
    sub = OccupancySubstrate(hass)
    _run_setup(sub)
    assert sub.is_kind_active("Kitchen", "mmwave") is True


def test_seed_treats_unavailable_as_false() -> None:
    hass = make_hass()
    entry = fake_room_entry(
        "Kitchen",
        **{CONF_MMWAVE_SENSORS: ["binary_sensor.kitchen_mmwave"]},
    )
    hass.config_entries.async_entries.return_value = [entry]
    hass.states.get = MagicMock(return_value=_state("unavailable"))
    sub = OccupancySubstrate(hass)
    _run_setup(sub)
    assert sub.is_kind_active("Kitchen", "mmwave") is False


def test_seed_off_state_yields_false() -> None:
    hass = make_hass()
    entry = fake_room_entry(
        "Kitchen",
        **{CONF_MOTION_SENSORS: ["binary_sensor.kitchen_motion"]},
    )
    hass.config_entries.async_entries.return_value = [entry]
    hass.states.get = MagicMock(return_value=_state("off"))
    sub = OccupancySubstrate(hass)
    _run_setup(sub)
    assert sub.is_kind_active("Kitchen", "motion") is False
