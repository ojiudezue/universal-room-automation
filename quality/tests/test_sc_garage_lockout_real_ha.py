"""GARAGE-REMOTE-LOCKOUT-SCHEDULE-1 review B-C1 — REAL Home Assistant core.

The behavioural suite injects fake timers/trackers. This file drives the
regime through REAL ``async_track_state_change_event`` / ``async_call_later``
on a real HA core (phcc factory), so HA's own job-type dispatch decides
where each callback runs. An arrival must release on the event loop thread.

HA helpers are bound at import (collection), so a later sys.modules swap by
another test file cannot change what this test exercises.
"""

from __future__ import annotations

import importlib.util
import sys
import threading
from types import SimpleNamespace

import pytest
import pytest_asyncio
import homeassistant.helpers as _ha_helpers
from homeassistant.util import dt as dt_util

from _lockout_harness import load


def _pristine_event_module():
    """A fresh copy of HA's helpers/event.py loaded from the installed source.

    test_house_state_rung2a.py (pre-existing) overwrites async_call_later /
    async_track_state_change_event / async_track_time_interval ON the real
    homeassistant.helpers.event module at collection time, so importing them
    by name can return its fakes. A private copy re-executes the real source
    (its relative imports resolve to the real homeassistant.helpers package);
    its tracker keys are its own, which is fine for this test.
    """
    name = "homeassistant.helpers._ura_lockout_pristine_event"
    if name in sys.modules:
        return sys.modules[name]
    import homeassistant.core as ha_core

    def _real_callback(func):  # HA core.py:210-213, verbatim behaviour
        setattr(func, "_hass_callback", True)
        return func

    path = _ha_helpers.__path__[0] + "/event.py"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    # Several files also replace homeassistant.core.callback with a no-op;
    # give the copy HA's real decorator for the duration of its import only.
    saved = ha_core.callback
    ha_core.callback = _real_callback
    try:
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    finally:
        ha_core.callback = saved
    return mod


_EV = _pristine_event_module()
async_call_later = _EV.async_call_later
async_track_state_change_event = _EV.async_track_state_change_event
async_track_state_added_domain = _EV.async_track_state_added_domain
async_track_state_removed_domain = _EV.async_track_state_removed_domain

const = load("const")
R = load("domain_coordinators.security_lock_regime")

LOCK_A = "lock.konnected_f0f5bd523b00_lock"
LOCK_B = "lock.ratgdov25i_dbfe2a_lock_remotes"
EZ = "person.ezinne"

_REAL_NOW = dt_util.now


# Names other test files overwrite ON the real homeassistant.core module at
# import (e.g. test_fan_incident_2026_08_01_replay.py sets State / Event /
# HomeAssistant to MagicMock and callback to an identity lambda). The real
# core looks these up in its own globals, so a real hass would mint Mock
# states. Repair them for this test only, then restore what was there.
_CORE_NAMES = ("State", "Event", "HomeAssistant", "callback", "HassJob",
               "Context", "ServiceCall", "CALLBACK_TYPE")


def _is_genuine(name, obj):
    return (getattr(obj, "__module__", None) == "homeassistant.core"
            and getattr(obj, "__qualname__", getattr(obj, "__name__", None)) == name)


def _genuine_core_attr(name):
    """The real homeassistant.core object for ``name``, found in any module
    that imported it before the overwrite (their own references survive)."""
    for mod in list(sys.modules.values()):
        obj = getattr(mod, name, None) if mod is not None else None
        try:
            if _is_genuine(name, obj):
                return obj
        except Exception:  # noqa: BLE001 — exotic module attrs
            continue
    return None


@pytest.fixture
def _real_core_globals():
    import homeassistant.core as ha_core

    saved = {}
    for name in _CORE_NAMES:
        cur = getattr(ha_core, name, None)
        if cur is None or _is_genuine(name, cur):
            continue
        real = _genuine_core_attr(name)
        if real is not None:
            saved[name] = cur
            setattr(ha_core, name, real)
    try:
        yield
    finally:
        for name, cur in saved.items():
            setattr(ha_core, name, cur)


@pytest_asyncio.fixture
async def hass(_real_core_globals):
    from pytest_homeassistant_custom_component.common import (
        async_test_home_assistant,
    )

    # Review C F17: HA's loader registers phcc's own top-level
    # ``custom_components`` namespace when this file is the first to start a
    # real core (it imports the integration under a private package name),
    # which later broke ``from custom_components.universal_room_automation
    # import ...`` in test_low_cleanup. Restore those entries afterwards.
    before = {k: v for k, v in sys.modules.items() if k.split(".")[0] == "custom_components"}
    try:
        async with async_test_home_assistant(load_registries=False) as real_hass:
            yield real_hass
            await real_hass.async_block_till_done()
            await real_hass.async_stop(force=True)
    finally:
        for k in [k for k in sys.modules if k.split(".")[0] == "custom_components"]:
            if k not in before:
                del sys.modules[k]
        sys.modules.update(before)


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


async def _real_rig(hass):
    """LOCK-RELEASE-ON-ARRIVING: the regime on a real HA core, lockouts locked
    in a SLEEP episode (rebuilt at setup from house=sleep)."""
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
    mgr = SimpleNamespace(house_state="sleep")
    hass.data[const.DOMAIN] = {"coordinator_manager": mgr}
    calls: list[tuple[str, str]] = []

    async def _handler(call):
        calls.append((call.service, call.data["entity_id"]))
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
    assert regime.reason == "sleep"

    def edge(new):
        old = mgr.house_state
        mgr.house_state = new
        regime.on_house_state_changed(
            {"old_state": old, "new_state": new, "trigger": "census_update",
             "confidence": 0.8}
        )

    return regime, calls, edge


@pytest.mark.asyncio
async def test_real_ha_body_only_arriving_holds(hass):
    regime, calls, edge = await _real_rig(hass)
    try:
        edge("away")
        edge("arriving")
        edge("home_day")
        await hass.async_block_till_done()
        assert [c for c in calls if c[0] == "unlock"] == []
        assert regime.reason == "sleep"
        assert regime.last_action["action"] == "arriving_hold"
        assert hass.states.get(LOCK_A).state == "locked"
    finally:
        await regime.async_teardown()
        await hass.async_block_till_done()


@pytest.mark.asyncio
async def test_real_ha_8632_shape_person_edge_after_arriving_releases(hass):
    regime, calls, edge = await _real_rig(hass)
    try:
        edge("away")
        edge("arriving")
        await hass.async_block_till_done()
        assert [c for c in calls if c[0] == "unlock"] == []
        hass.states.async_set(EZ, "home")  # the resident's edge, after ARRIVING
        await hass.async_block_till_done()
        assert sorted(c[1] for c in calls if c[0] == "unlock") == [LOCK_A, LOCK_B]
        assert regime.last_action["trigger"] == "person:person.ezinne"
    finally:
        await regime.async_teardown()
        await hass.async_block_till_done()
