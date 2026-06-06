"""Occupancy substrate — lifecycle tests (Bug Class #38).

Re-discovery must cleanly tear down stale listeners and subscribe new
ones. ``async_teardown`` must release every captured unsub.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import _provenance_harness  # noqa: F401
from _provenance_harness import make_hass, fake_room_entry

from custom_components.universal_room_automation.const import (
    CONF_MOTION_SENSORS,
)
from custom_components.universal_room_automation.domain_coordinators import (
    occupancy_substrate as substrate_mod,
)
from custom_components.universal_room_automation.domain_coordinators.occupancy_substrate import (  # noqa: E501
    OccupancySubstrate,
)


def _run(coro):
    import asyncio
    return asyncio.get_event_loop().run_until_complete(coro)


def test_rediscovery_tears_down_stale_listeners(monkeypatch) -> None:
    """A second async_setup unsubs the prior listener registration."""
    hass = make_hass()
    entry = fake_room_entry(
        "Office",
        **{CONF_MOTION_SENSORS: ["binary_sensor.office_motion"]},
    )
    hass.config_entries.async_entries.return_value = [entry]

    unsubs = []

    def _fake_track(_hass, _entities, _cb):
        m = MagicMock()
        unsubs.append(m)
        return m

    monkeypatch.setattr(
        substrate_mod, "async_track_state_change_event", _fake_track,
    )
    sub = OccupancySubstrate(hass)
    _run(sub.async_setup())
    assert len(unsubs) == 1
    first_unsub = unsubs[0]

    # Re-discovery — should unsub the prior listener and create a new one.
    _run(sub.async_setup())
    assert first_unsub.called
    assert len(unsubs) == 2


def test_teardown_unsubs_listeners(monkeypatch) -> None:
    hass = make_hass()
    entry = fake_room_entry(
        "Office",
        **{CONF_MOTION_SENSORS: ["binary_sensor.office_motion"]},
    )
    hass.config_entries.async_entries.return_value = [entry]

    unsubs = []

    def _fake_track(_hass, _entities, _cb):
        m = MagicMock()
        unsubs.append(m)
        return m

    monkeypatch.setattr(
        substrate_mod, "async_track_state_change_event", _fake_track,
    )
    sub = OccupancySubstrate(hass)
    _run(sub.async_setup())
    _run(sub.async_teardown())
    assert unsubs[0].called


def test_empty_conf_lists_subscribes_zero_listeners(monkeypatch) -> None:
    hass = make_hass()
    entry = fake_room_entry("CameraOnly")  # no CONF lists
    hass.config_entries.async_entries.return_value = [entry]

    unsubs = []

    def _fake_track(_hass, _entities, _cb):
        m = MagicMock()
        unsubs.append(m)
        return m

    monkeypatch.setattr(
        substrate_mod, "async_track_state_change_event", _fake_track,
    )
    sub = OccupancySubstrate(hass)
    _run(sub.async_setup())
    assert unsubs == []
