"""HOUSE-STATE step 1a D2 wire-in anchor on a REAL hass.

``PresenceCoordinator.async_setup`` (not the helper) builds the residency
tracker before the geofence subscription, and a real ``person.*`` state change
on the real bus reaches ``_handle_geofence_change`` and becomes a record.
Rig and real-module isolation: ``_sighting_rig`` (same as test_person_sighting).
"""

from __future__ import annotations

import pytest
import pytest_asyncio

import _sighting_rig as R


@pytest.fixture(scope="module")
def mods():
    with R.import_real_modules() as ns:
        yield ns


@pytest_asyncio.fixture
async def hass():
    from pytest_homeassistant_custom_component.common import async_test_home_assistant

    async with async_test_home_assistant(load_registries=False) as real_hass:
        yield real_hass
        await real_hass.async_block_till_done()
        await real_hass.async_stop(force=True)


@pytest.mark.asyncio
async def test_presence_async_setup_builds_residency(mods, hass, monkeypatch):
    rig = await R.build(mods, hass, monkeypatch, setup=False)
    try:
        assert rig.presence._residency is None
        await rig.presence.async_setup()
        tracker = rig.presence._residency
        assert tracker is not None
        hass.states.async_set("person.oji_udezue", "not_home")
        await hass.async_block_till_done()
        assert [r.kind for r in tracker.recent] in ([], ["departure"])
        tracker.recent.clear()
        hass.states.async_set("person.oji_udezue", "home")
        await hass.async_block_till_done()
        kinds = [(r.kind, r.person) for r in tracker.recent]
        assert kinds == [("arrival", "person.oji_udezue")]
        await rig.presence.async_teardown()
        assert rig.presence._residency_torn_down is True
    finally:
        await R.teardown(rig)
