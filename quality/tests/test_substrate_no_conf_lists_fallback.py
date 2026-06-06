"""Occupancy substrate — D5 no-CONF-list fallback test.

When every CONF list is empty for every room, the substrate registers
zero listeners and logs the explicit INFO-once "no Tier-1 sensors
configured" message.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import _provenance_harness  # noqa: F401
from _provenance_harness import make_hass, fake_room_entry

from custom_components.universal_room_automation.domain_coordinators import (
    occupancy_substrate as substrate_mod,
)
from custom_components.universal_room_automation.domain_coordinators.occupancy_substrate import (  # noqa: E501
    OccupancySubstrate,
)


def _run(coro):
    import asyncio
    return asyncio.get_event_loop().run_until_complete(coro)


def test_empty_conf_lists_logs_once_and_zero_listeners(
    monkeypatch, caplog,
) -> None:
    caplog.set_level(logging.INFO)
    hass = make_hass()
    entry = fake_room_entry("CameraOnly")  # NO CONF lists at all
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
    info_msgs = [
        r.message for r in caplog.records
        if r.levelno == logging.INFO
        and "no Tier-1 occupancy sensors" in r.message
    ]
    assert len(info_msgs) == 1

    # Second setup should NOT re-emit the INFO (one-shot).
    caplog.clear()
    _run(sub.async_setup())
    info_msgs_second = [
        r.message for r in caplog.records
        if r.levelno == logging.INFO
        and "no Tier-1 occupancy sensors" in r.message
    ]
    assert info_msgs_second == []
