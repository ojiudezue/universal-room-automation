"""Suspicious-arrival hold on a REAL Home Assistant core with the REAL
``person`` component (plan rev 2 D2b, review F2).

HA's person picks its state and ``source`` itself (any non-GPS home wins,
else the GPS tracker with the newest ``last_updated``; unavailable ignored),
so these tests exercise the real source selection and the real
``last_changed`` / ``last_updated`` split instead of synthesised states:

* two GPS trackers: the phone drops ``unavailable``, HA falls back to the
  stale second device (``home``) -> held, no unlock; the phone returning
  ``not_home`` drops the hold;
* the stale device gets an attribute-only refresh (bumps ``last_updated``
  only, so HA now picks it) -> still held (a predicate reading
  ``last_updated`` would release);
* a BLE-only person ``not_home -> home`` releases at once.

The regime runs with real ``async_track_state_change_event`` /
``async_call_later`` (pristine copy, see test_sc_garage_lockout_real_ha) and a
clock offset 700 s past setup, so the edges are outside the 600 s boot
arrival window (boot edges are never held, F4).
"""

from __future__ import annotations

import asyncio
import time
from datetime import timedelta
from types import SimpleNamespace

import pytest
import pytest_asyncio
from homeassistant.util import dt as dt_util

from _lockout_harness import load
from test_sc_garage_lockout_real_ha import (  # noqa: F401 — fixture reuse
    _real_core_globals,
    async_call_later,
    async_track_state_added_domain,
    async_track_state_change_event,
    async_track_state_removed_domain,
)

const = load("const")
R = load("domain_coordinators.security_lock_regime")

LOCK_A = "lock.konnected_f0f5bd523b00_lock"
LOCK_B = "lock.ratgdov25i_dbfe2a_lock_remotes"
PHONE = "device_tracker.oji_phone"
IPAD = "device_tracker.okosisipadmini6_2"
JAYA_BLE = "device_tracker.jaya_private_ble"
OJI = "person.oji"
JAYA = "person.jaya"

_REAL_NOW = dt_util.now


@pytest_asyncio.fixture
async def hass(_real_core_globals):
    import sys

    from pytest_homeassistant_custom_component.common import async_test_home_assistant

    before = {k: v for k, v in sys.modules.items() if k.split(".")[0] == "custom_components"}
    try:
        async with async_test_home_assistant() as real_hass:
            yield real_hass
            await real_hass.async_block_till_done()
            await real_hass.async_stop(force=True)
    finally:
        for k in [k for k in sys.modules if k.split(".")[0] == "custom_components"]:
            if k not in before:
                del sys.modules[k]
        sys.modules.update(before)


async def _flush(hass) -> None:
    """Tracker -> person -> regime is two keyed dispatches, each scheduled
    with call_soon (helpers/event.py _async_dispatch_entity_id_event_soon)."""
    for _ in range(3):
        await hass.async_block_till_done()
        await asyncio.sleep(0)


async def _setup(hass):
    from homeassistant.setup import async_setup_component
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    MockConfigEntry(
        domain=const.DOMAIN, entry_id="cm", title="CM",
        data={const.CONF_ENTRY_TYPE: const.ENTRY_TYPE_COORDINATOR_MANAGER},
        options={
            "security_garage_lockout_enabled": True,
            "security_lockout_entities": [LOCK_A, LOCK_B],
            "security_coordinator_enabled": True,
        },
    ).add_to_hass(hass)
    hass.data[const.DOMAIN] = {"coordinator_manager": SimpleNamespace(house_state="vacation")}
    calls: list[tuple[str, str]] = []

    async def _handler(call):
        calls.append((call.service, call.data["entity_id"]))
        hass.states.async_set(
            call.data["entity_id"], "unlocked" if call.service == "unlock" else "locked")

    hass.services.async_register("lock", "unlock", _handler)
    hass.services.async_register("lock", "lock", _handler)
    hass.states.async_set(LOCK_A, "locked")
    hass.states.async_set(LOCK_B, "locked")
    stale_ts = time.time() - 4119.0
    hass.states.async_set(PHONE, "not_home", {"source_type": "gps"})
    hass.states.async_set(IPAD, "home", {"source_type": "gps"}, timestamp=stale_ts)
    hass.states.async_set(JAYA_BLE, "not_home", {"source_type": "bluetooth_le"})
    assert await async_setup_component(hass, "person", {"person": [
        {"id": "oji", "name": "Oji", "device_trackers": [PHONE, IPAD]},
        {"id": "jaya", "name": "Jaya", "device_trackers": [JAYA_BLE]},
    ]})
    await hass.async_block_till_done()
    assert hass.states.get(OJI).state == "not_home"
    assert hass.states.get(OJI).attributes["source"] == PHONE

    clock = {"off": 0.0}
    sc = SimpleNamespace(enabled=True, _shutting_down=False, observation_mode=False,
                         _garage_entities=[], decision_logger=None)
    regime = R.LockRegimeController(
        hass, sc,
        now=lambda: _REAL_NOW() + timedelta(seconds=clock["off"]),
        call_later=async_call_later,
        track_state=async_track_state_change_event,
        track_added_domain=async_track_state_added_domain,
        track_removed_domain=async_track_state_removed_domain,
        store=None,
    )
    await regime.async_setup()
    clock["off"] = 700.0  # past the 600 s boot arrival window
    return regime, calls


@pytest.mark.asyncio
async def test_two_gps_dropout_held_and_dropped(hass):
    regime, calls = await _setup(hass)
    try:
        hass.states.async_set(PHONE, "unavailable", {"source_type": "gps"})
        await _flush(hass)
        st = hass.states.get(OJI)
        assert (st.state, st.attributes["source"]) == ("home", IPAD)  # HA's own pick
        assert OJI in regime._held_edges
        assert calls == []
        hass.states.async_set(PHONE, "not_home", {"source_type": "gps"})
        await _flush(hass)
        assert hass.states.get(OJI).state == "not_home"
        assert regime._held_edges == {}
        assert calls == []
    finally:
        await regime.async_teardown()
        await hass.async_block_till_done()


@pytest.mark.asyncio
async def test_two_gps_attribute_refresh_stays_held(hass):
    regime, calls = await _setup(hass)
    try:
        lc_before = hass.states.get(IPAD).last_changed
        # Attribute-only refresh of the stale device: last_updated moves,
        # last_changed does not; HA now picks it (newest GPS).
        hass.states.async_set(IPAD, "home", {"source_type": "gps", "battery": 41})
        await _flush(hass)
        ipad = hass.states.get(IPAD)
        assert ipad.last_changed == lc_before and ipad.last_updated > lc_before
        st = hass.states.get(OJI)
        assert (st.state, st.attributes["source"]) == ("home", IPAD)
        assert OJI in regime._held_edges
        assert calls == []
    finally:
        await regime.async_teardown()
        await hass.async_block_till_done()


@pytest.mark.asyncio
async def test_ble_only_arrival_instant(hass):
    regime, calls = await _setup(hass)
    try:
        hass.states.async_set(JAYA_BLE, "home", {"source_type": "bluetooth_le"})
        await _flush(hass)
        assert hass.states.get(JAYA).attributes["source"] == JAYA_BLE
        assert regime._held_edges == {}
        assert regime.arrival_holds == 0
        assert sorted(c[1] for c in calls if c[0] == "unlock") == [LOCK_A, LOCK_B]
    finally:
        await regime.async_teardown()
        await hass.async_block_till_done()


def _fire(hass, seconds):
    from pytest_homeassistant_custom_component.common import async_fire_time_changed

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=seconds))


@pytest.mark.asyncio
async def test_two_gps_dropout_confirm_timer_fires(hass):
    """Review B-L3: the real async_call_later fires the @callback confirm
    partial on the loop; the still-held edge replays and both lockouts unlock."""
    regime, calls = await _setup(hass)
    try:
        hass.states.async_set(PHONE, "unavailable", {"source_type": "gps"})
        await _flush(hass)
        assert OJI in regime._held_edges
        assert calls == []
        _fire(hass, 6)
        await _flush(hass)
        assert regime.arrival_hold_confirms == 1
        assert regime._held_edges == {}
        assert sorted(c[1] for c in calls if c[0] == "unlock") == [LOCK_A, LOCK_B]
    finally:
        await regime.async_teardown()
        await hass.async_block_till_done()


@pytest.mark.asyncio
async def test_confirm_timer_does_not_fire_after_teardown(hass):
    regime, calls = await _setup(hass)
    hass.states.async_set(PHONE, "unavailable", {"source_type": "gps"})
    await _flush(hass)
    assert OJI in regime._held_edges
    await regime.async_teardown()
    await hass.async_block_till_done()
    _fire(hass, 6)
    await _flush(hass)
    assert regime.arrival_hold_confirms == 0
    assert calls == []
