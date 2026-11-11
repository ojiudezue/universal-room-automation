"""PRESENCE-GEOFENCE-FIELD-DEAD-1 — late person.* pickup.

``PresenceCoordinator._subscribe_geofence`` listened only to the person
entities present at setup, so a person added later (Settings → People, or
a person entity that loads after URA) never produced a geofence signal.
These tests drive the REAL method on a REAL hass (state machine + event
bus) and check the arrival path end to end.
"""
from __future__ import annotations

import pytest
import pytest_asyncio

from homeassistant.helpers.dispatcher import async_dispatcher_connect

from custom_components.universal_room_automation.domain_coordinators.presence import (
    PresenceCoordinator,
)
from custom_components.universal_room_automation.domain_coordinators.signals import (
    SIGNAL_PERSON_ARRIVING,
)


@pytest_asyncio.fixture
async def hass():
    """REAL Home Assistant core (phcc factory); the suite runs asyncio
    strict, so wrap the factory (pattern: test_census_device_switches)."""
    from pytest_homeassistant_custom_component.common import (
        async_test_home_assistant,
    )

    async with async_test_home_assistant(load_registries=False) as real_hass:
        yield real_hass
        await real_hass.async_block_till_done()
        await real_hass.async_stop(force=True)


def _coord(hass):
    coord = PresenceCoordinator(hass)
    seen: list = []
    coord.handle_geofence_event = lambda pid, zone: seen.append((pid, zone))
    return coord, seen


async def _teardown(coord):
    for unsub in list(coord._unsub_listeners):
        try:
            unsub()
        except Exception:  # noqa: BLE001
            pass


@pytest.mark.asyncio
async def test_person_added_after_setup_is_tracked(hass):
    coord, seen = _coord(hass)
    arrivals: list = []
    unsub_sig = async_dispatcher_connect(
        hass, SIGNAL_PERSON_ARRIVING, lambda payload: arrivals.append(payload))
    try:
        coord._subscribe_geofence()          # no person.* exists yet
        await hass.async_block_till_done()

        hass.states.async_set("person.late", "not_home")   # added later
        await hass.async_block_till_done()
        assert seen == []                    # the add itself is no transition
        hass.states.async_set("person.late", "home")
        await hass.async_block_till_done()
        assert seen == [("person.late", "home")]
        assert arrivals == [{"person_entity": "person.late", "source": "geofence"}]
        hass.states.async_set("person.late", "not_home")
        await hass.async_block_till_done()
        assert seen[-1] == ("person.late", "not_home")
    finally:
        unsub_sig()
        await _teardown(coord)


@pytest.mark.asyncio
async def test_person_present_at_setup_still_tracked_once(hass):
    """Startup persons keep working and are not double-subscribed when the
    added-domain listener also sees them."""
    hass.states.async_set("person.early", "not_home")
    await hass.async_block_till_done()
    coord, seen = _coord(hass)
    try:
        coord._subscribe_geofence()
        assert coord._geofence_tracked == {"person.early"}
        hass.states.async_set("person.early", "home")
        await hass.async_block_till_done()
        assert seen == [("person.early", "home")]
    finally:
        await _teardown(coord)


@pytest.mark.asyncio
async def test_teardown_releases_late_listener(hass):
    """Both listeners live in ``_unsub_listeners``: after teardown a new
    person is not tracked."""
    coord, seen = _coord(hass)
    coord._subscribe_geofence()
    await _teardown(coord)
    hass.states.async_set("person.after", "not_home")
    hass.states.async_set("person.after", "home")
    await hass.async_block_till_done()
    assert seen == []
    assert "person.after" not in coord._geofence_tracked
