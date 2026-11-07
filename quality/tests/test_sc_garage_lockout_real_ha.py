"""GARAGE-REMOTE-LOCKOUT-SCHEDULE-1 review B-C1 — REAL Home Assistant core.

The behavioural suite injects fake timers/trackers. This file drives the
regime through REAL ``async_track_state_change_event`` / ``async_call_later``
on a real HA core (phcc factory), so HA's own job-type dispatch decides
where each callback runs. An arrival must release on the event loop thread.

HA helpers are bound at import (collection), so a later sys.modules swap by
another test file cannot change what this test exercises.
"""

from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest
import pytest_asyncio
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_added_domain,
    async_track_state_change_event,
    async_track_state_removed_domain,
)
from homeassistant.util import dt as dt_util

from _lockout_harness import load

const = load("const")
R = load("domain_coordinators.security_lock_regime")

LOCK_A = "lock.konnected_f0f5bd523b00_lock"
LOCK_B = "lock.ratgdov25i_dbfe2a_lock_remotes"
EZ = "person.ezinne"

_REAL_NOW = dt_util.now


@pytest_asyncio.fixture
async def hass():
    from pytest_homeassistant_custom_component.common import (
        async_test_home_assistant,
    )

    async with async_test_home_assistant(load_registries=False) as real_hass:
        yield real_hass
        await real_hass.async_block_till_done()
        await real_hass.async_stop(force=True)


@pytest.mark.asyncio
async def test_real_ha_arrival_release_runs_on_loop_and_unlocks(hass):
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    MockConfigEntry(
        domain=const.DOMAIN,
        entry_id="cm",
        title="CM",
        data={const.CONF_ENTRY_TYPE: const.ENTRY_TYPE_COORDINATOR_MANAGER},
        options={
            "security_garage_lockout_enabled": True,
            "security_lockout_entities": [LOCK_A, LOCK_B],
            "security_coordinator_enabled": True,
        },
    ).add_to_hass(hass)
    hass.data[const.DOMAIN] = {
        "coordinator_manager": SimpleNamespace(house_state="sleep")
    }

    loop_thread = threading.get_ident()
    calls: list[tuple[str, str, int]] = []

    async def _handler(call):
        calls.append((call.service, call.data["entity_id"], threading.get_ident()))
        hass.states.async_set(
            call.data["entity_id"], "unlocked" if call.service == "unlock" else "locked"
        )

    hass.services.async_register("lock", "unlock", _handler)
    hass.services.async_register("lock", "lock", _handler)
    hass.states.async_set(LOCK_A, "locked")
    hass.states.async_set(LOCK_B, "locked")
    hass.states.async_set(EZ, "not_home")
    await hass.async_block_till_done()

    sc = SimpleNamespace(
        enabled=True, _shutting_down=False, observation_mode=False,
        _garage_entities=[], decision_logger=None,
    )
    regime = R.LockRegimeController(
        hass, sc,
        now=_REAL_NOW,
        call_later=async_call_later,
        track_state=async_track_state_change_event,
        track_added_domain=async_track_state_added_domain,
        track_removed_domain=async_track_state_removed_domain,
        store=None,
    )
    await regime.async_setup()
    try:
        hass.states.async_set(EZ, "home")  # P1 arrival via the REAL tracker
        await hass.async_block_till_done()
        assert sorted(c[1] for c in calls if c[0] == "unlock") == [LOCK_A, LOCK_B]
        assert {c[2] for c in calls} == {loop_thread}
        assert hass.states.get(LOCK_A).state == "unlocked"
        assert regime._release_inflight == {LOCK_A, LOCK_B}  # read-back pending
    finally:
        await regime.async_teardown()
        await hass.async_block_till_done()
