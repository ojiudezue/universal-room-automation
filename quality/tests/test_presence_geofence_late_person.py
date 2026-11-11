"""PRESENCE-GEOFENCE-FIELD-DEAD-1 — late person.* pickup.

``PresenceCoordinator._subscribe_geofence`` listened only to the person
entities present at setup, so a person added later (Settings → People, or
a person entity that loads after URA) never produced a geofence signal.
These tests drive the REAL method on a REAL hass (state machine + event
bus) and check the arrival path end to end.

Order-proofing (FORMS-RELEASE-1 fix-up): this file used to import
``presence`` at collection time. Under ``-n 6 --dist loadfile`` a worker
collects every file first, and legacy donors leave stub ``custom_components``
/ ``homeassistant`` modules in ``sys.modules`` (AUDIT_test_suite_parallel_2026_11),
so the import could bind a stub-loaded copy (e.g. a ``helpers.event`` stub
without ``async_track_state_added_domain``, which the production code treats
as "unavailable" and silently skips). The module-scoped ``mods`` fixture
imports the REAL modules fresh inside ``_d7_isolation.import_scope`` after
dropping URA entries and non-real HA entries, and restores ``sys.modules``
(entries and attribute writes) when the file's tests end.
"""
from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

import pytest
import pytest_asyncio

import homeassistant as _real_ha_pkg

from _d7_isolation import import_scope

_HA_DIR = Path(_real_ha_pkg.__file__).resolve().parent
_PRESENCE = "custom_components.universal_room_automation.domain_coordinators.presence"
_SIGNALS = "custom_components.universal_room_automation.domain_coordinators.signals"
_FRESH_HELPERS = ("homeassistant.helpers.dispatcher", "homeassistant.helpers.event")


def _is_real_ha(mod) -> bool:
    """A real ``homeassistant`` module: a module object whose file lives in
    the installed HA package (stubs are bare ModuleType / MagicMock)."""
    if not isinstance(mod, types.ModuleType):
        return False
    f = getattr(mod, "__file__", None)
    if not f:
        return False
    try:
        return Path(f).resolve().is_relative_to(_HA_DIR)
    except (OSError, ValueError):
        return False


@pytest.fixture(scope="module")
def mods():
    with import_scope(("custom_components", "homeassistant"), attrs=True):
        for name in [k for k in sys.modules if k == "custom_components"
                     or k.startswith("custom_components.")]:
            sys.modules.pop(name, None)
        for name in [k for k in sys.modules if k.startswith("homeassistant")]:
            if not _is_real_ha(sys.modules[name]):
                sys.modules.pop(name, None)
        # A donor can also overwrite an ATTRIBUTE of the real module
        # (test_census_device_switches did, on helpers.dispatcher). Fresh
        # copies of the two helpers presence binds at import: their state
        # lives in hass.data under string keys, so a copy is equivalent.
        for name in _FRESH_HELPERS:
            sys.modules.pop(name, None)
        # Many legacy donors replace ``homeassistant.core.callback`` (and
        # ``is_callback``) on the REAL core module and never restore it; a
        # fresh helpers.event import would then decorate its filters with the
        # stub and the real bus rejects them ("is not a callback"). Put the
        # real definitions back for this block; attrs=True restores on exit.
        _core = sys.modules["homeassistant.core"]

        def _real_callback(func):
            setattr(func, "_hass_callback", True)
            return func

        def _real_is_callback(func):
            return getattr(func, "_hass_callback", False) is True

        _core.callback = _real_callback
        _core.is_callback = _real_is_callback
        # Collection-time donors also overwrite classes on the real core
        # module (test_fan_manual_on_hold_hvac_tier sets ``State`` /
        # ``Event`` / ``HomeAssistant`` to MagicMock), and the real state
        # machine then builds Mock states. The phcc plugin imported the real
        # objects before any test file was collected, so restore from it
        # (attrs=True restores the polluted values on exit).
        from pytest_homeassistant_custom_component import common as _phcc
        for _name in ("State", "Event", "HomeAssistant", "CoreState",
                      "ServiceCall", "SupportsResponse"):
            setattr(_core, _name, getattr(_phcc, _name))
        importlib.invalidate_caches()
        presence = importlib.import_module(_PRESENCE)
        signals = importlib.import_module(_SIGNALS)
        event = importlib.import_module("homeassistant.helpers.event")
        dispatcher = importlib.import_module("homeassistant.helpers.dispatcher")
        assert hasattr(event, "async_track_state_added_domain")
        yield types.SimpleNamespace(
            PresenceCoordinator=presence.PresenceCoordinator,
            SIGNAL_PERSON_ARRIVING=signals.SIGNAL_PERSON_ARRIVING,
            async_track_state_change_event=event.async_track_state_change_event,
            async_track_state_added_domain=event.async_track_state_added_domain,
            async_dispatcher_connect=dispatcher.async_dispatcher_connect,
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


def _coord(mods, hass):
    coord = mods.PresenceCoordinator(hass)
    seen: list = []
    coord.handle_geofence_event = lambda pid, zone: seen.append((pid, zone))
    return coord, seen


async def _teardown(coord):
    for unsub in list(coord._unsub_listeners):
        unsub()


@pytest.mark.asyncio
async def test_person_added_after_setup_is_tracked(mods, hass):
    coord, seen = _coord(mods, hass)
    arrivals: list = []
    unsub_sig = mods.async_dispatcher_connect(
        hass, mods.SIGNAL_PERSON_ARRIVING, lambda payload: arrivals.append(payload))
    try:
        coord._subscribe_geofence()          # no person.* exists yet
        await hass.async_block_till_done()

        hass.states.async_set("person.late", "not_home")   # added later
        await hass.async_block_till_done()
        assert seen == []                    # the add itself is no transition
        assert coord._geofence_tracked == {"person.late"}
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
async def test_person_added_home_with_prior_tracker_is_not_an_arrival(mods, hass):
    """B-L1: reproduce the live bus order. HA's ``zone`` registers an
    added-domain tracker during early bootstrap, so the keyed ADDED-DOMAIN
    bus listener sits BEFORE the keyed STATE-CHANGE one. On the add event the
    added-domain listener runs first and registers the per-person callback;
    the state-change listener's filter (evaluated at bus time,
    ``helpers/event.py`` ``_async_state_filter``) then sees it and schedules
    the add event itself (``old_state=None``) to the new callback. A person
    created already ``home`` must not be read as an arrival."""
    unsub_zone_like = mods.async_track_state_added_domain(
        hass, "zone", lambda ev: None)          # 1st bus listener: added-domain
    unsub_other = mods.async_track_state_change_event(
        hass, ["sensor.unrelated"], lambda ev: None)   # 2nd: state-change
    coord, seen = _coord(mods, hass)
    arrivals: list = []
    unsub_sig = mods.async_dispatcher_connect(
        hass, mods.SIGNAL_PERSON_ARRIVING, lambda payload: arrivals.append(payload))
    try:
        coord._subscribe_geofence()
        await hass.async_block_till_done()

        hass.states.async_set("person.new_home", "home")   # created at home
        await hass.async_block_till_done()
        assert coord._geofence_tracked == {"person.new_home"}
        assert seen == []
        assert arrivals == []
        # The next REAL edge still counts.
        hass.states.async_set("person.new_home", "not_home")
        await hass.async_block_till_done()
        hass.states.async_set("person.new_home", "home")
        await hass.async_block_till_done()
        assert seen == [("person.new_home", "not_home"), ("person.new_home", "home")]
        assert arrivals == [
            {"person_entity": "person.new_home", "source": "geofence"}]
    finally:
        unsub_sig()
        unsub_other()
        unsub_zone_like()
        await _teardown(coord)


@pytest.mark.asyncio
async def test_person_present_at_setup_still_tracked_once(mods, hass):
    """Startup persons keep working and are not double-subscribed when the
    added-domain listener also sees them."""
    hass.states.async_set("person.early", "not_home")
    await hass.async_block_till_done()
    coord, seen = _coord(mods, hass)
    try:
        coord._subscribe_geofence()
        assert coord._geofence_tracked == {"person.early"}
        hass.states.async_set("person.early", "home")
        await hass.async_block_till_done()
        assert seen == [("person.early", "home")]
    finally:
        await _teardown(coord)


@pytest.mark.asyncio
async def test_teardown_releases_late_listener(mods, hass):
    """Both listeners live in ``_unsub_listeners``: after teardown a new
    person is not tracked."""
    coord, seen = _coord(mods, hass)
    coord._subscribe_geofence()
    await _teardown(coord)
    hass.states.async_set("person.after", "not_home")
    hass.states.async_set("person.after", "home")
    await hass.async_block_till_done()
    assert seen == []
    assert "person.after" not in coord._geofence_tracked
