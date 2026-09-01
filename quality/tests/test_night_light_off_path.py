"""NIGHT-LIGHT-NO-OFF-PATH-1 (Rev 3) — behavioral tests for the
UNCONDITIONAL union off_set widening across all four turn-off emission
sites + D3b consumer widen + A2-gate flash filter + D6 conflict-detector
surface.

Rev 3 premise (operator correction 2026-09-01): night lights behave like
any occupancy light — OFF on vacancy ALWAYS, including during sleep. The
reconciler sleep branch is occupancy-aware (D2b) so both sides agree
OFF-when-vacant.

Sites under test:
- D1: automation.py::_control_lights_exit
- D2a/D2b: actuator_reconciler.py::_resolve_light (see test_reconcile_on_return.py)
- D3a: automation.py::_shared_space_turn_off_all
- D3b: automation.py::check_auto_off_warning + _warning_flash (+ A2-gate)
- D5: hvac.py::_execute_vacancy_sweep (see test_hvac_vacancy_sweep_manual_on_guard.py)
- D6: coordinator.py::_get_builtin_target_entities(TRIGGER_EXIT)

Each test is a behavioral service_call / state-return assertion, NOT a
source grep (hollow-anchor guard).

D4 tests are DROPPED — Rev 3 removes the hoisted-sleep-block deliverable.
"""

from __future__ import annotations

from datetime import datetime, time
from unittest.mock import MagicMock

import asyncio

import _provenance_harness  # noqa: F401 — installs HA mocks on import

from custom_components.universal_room_automation.const import (
    CONF_ENTRY_LIGHT_ACTION,
    CONF_EXIT_LIGHT_ACTION,
    CONF_LIGHTS,
    CONF_NIGHT_LIGHTS,
    DOMAIN,
    LIGHT_ACTION_NONE,
    LIGHT_ACTION_TURN_OFF,
    LIGHT_ACTION_TURN_ON,
)


# ---------------------------------------------------------------------------
# Fixture: RoomAutomation stub via __new__ (mirrors test_fan_oracle_delegation).
# ---------------------------------------------------------------------------


def _make_room(config: dict, sleep: bool = False):
    """Build a RoomAutomation stub + service-call log.

    Only the surface each _control_* / warning / flash / shared-off helper
    touches is injected. Service calls captured as (domain, service, ids).
    """
    from custom_components.universal_room_automation.automation import (
        RoomAutomation,
    )

    room = RoomAutomation.__new__(RoomAutomation)
    hass = MagicMock()
    hass.data = {DOMAIN: {}}
    calls: list[tuple[str, str, tuple]] = []
    states: dict = {}

    async def _svc_call(domain, service, data=None, blocking=False, **_):
        eid = (data or {}).get("entity_id", "")
        if isinstance(eid, list):
            ids = tuple(sorted(eid))
        else:
            ids = (eid,)
        svc = str(service) if not isinstance(service, str) else service
        if "TURN_OFF" in svc or svc == "turn_off":
            svc = "turn_off"
        elif "TURN_ON" in svc or svc == "turn_on":
            svc = "turn_on"
        calls.append((domain, svc, ids))
        return True

    hass.services = MagicMock()
    hass.services.async_call = _svc_call
    hass.states = MagicMock()
    hass.states.get = lambda eid: states.get(eid)

    room.hass = hass
    room.config = {"room_name": "TestRoom", **config}
    room._config_entry = MagicMock()
    room._config_entry.entry_id = "test_entry"

    # _safe_service_call counters
    room._service_calls_today = 0
    room._service_failures_today = 0
    room._service_call_reset_date = ""

    # is_sleep_mode_active is a method — patch on the INSTANCE.
    room.is_sleep_mode_active = lambda: sleep

    coord = MagicMock()
    coord.set_last_action = MagicMock()
    coord._is_cover_automation_enabled = MagicMock(return_value=False)
    room.coordinator = coord

    # Expose the states dict so tests can prime entity states.
    room._test_states = states

    return room, calls


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _turn_offs_for(calls, entity_id):
    return [
        (dom, svc, ids)
        for dom, svc, ids in calls
        if svc == "turn_off" and entity_id in ids
    ]


def _turn_ons_for(calls, entity_id):
    return [
        (dom, svc, ids)
        for dom, svc, ids in calls
        if svc == "turn_on" and entity_id in ids
    ]


# ===========================================================================
# D1 — _control_lights_exit unconditional union
# ===========================================================================


def test_D1_exit_nonsleep_night_only_entity_gets_turn_off():
    """D1: non-sleep vacancy on a night-only entity emits turn_off."""
    room, calls = _make_room(
        {
            CONF_LIGHTS: [],
            CONF_NIGHT_LIGHTS: ["switch.foo"],
            CONF_EXIT_LIGHT_ACTION: LIGHT_ACTION_TURN_OFF,
        },
        sleep=False,
    )
    _run(room._control_lights_exit({}))
    assert _turn_offs_for(calls, "switch.foo"), (
        f"D1 non-sleep night-only entity MUST receive turn_off. calls={calls}"
    )


def test_D1_exit_SLEEP_night_only_entity_ALSO_gets_turn_off():
    """Rev 3 DISCRIMINATING: sleep + vacancy → night-only entity STILL
    receives turn_off (the operator correction — night lights behave like
    any occupancy light, OFF on vacancy always).

    Rev 2's sleep-gated design would have emitted ZERO turn_offs here —
    this test discriminates Rev 3 from Rev 2. Mutation drill: neutering
    the union (revert to CONF_LIGHTS only) turns this RED.
    """
    room, calls = _make_room(
        {
            CONF_LIGHTS: [],
            CONF_NIGHT_LIGHTS: ["switch.foo"],
            CONF_EXIT_LIGHT_ACTION: LIGHT_ACTION_TURN_OFF,
        },
        sleep=True,
    )
    _run(room._control_lights_exit({}))
    assert _turn_offs_for(calls, "switch.foo"), (
        f"Rev 3 D1 SLEEP-LEG: night-only switch.foo MUST be turned off "
        f"even during sleep (unconditional union). calls={calls}"
    )


def test_D1_exit_nonsleep_dedup_single_emission_per_dual_listed_entity():
    """Dual-listed entity → turn_off exactly once (order-preserving dedup)."""
    room, calls = _make_room(
        {
            CONF_LIGHTS: ["light.a"],
            CONF_NIGHT_LIGHTS: ["light.b", "light.a"],
            CONF_EXIT_LIGHT_ACTION: LIGHT_ACTION_TURN_OFF,
        },
        sleep=False,
    )
    _run(room._control_lights_exit({}))
    a_offs = _turn_offs_for(calls, "light.a")
    b_offs = _turn_offs_for(calls, "light.b")
    assert len(a_offs) == 1, f"light.a dedup regression: {a_offs}"
    assert len(b_offs) == 1, f"light.b turn_off missing: {calls}"


def test_D1_no_night_light_room_byte_identical():
    """~20 no-night-light rooms unchanged (invariant #6): with
    night_lights=[] the widened off_set == CONF_LIGHTS, so emission
    shape is byte-identical to pre-cycle. Hand-authored baseline:
    exactly one light.turn_off with entity_id=[light.a] and a transition
    key (whatever CONF_LIGHT_TRANSITION_OFF defaults to)."""
    room, calls = _make_room(
        {
            CONF_LIGHTS: ["light.a"],
            CONF_NIGHT_LIGHTS: [],
            CONF_EXIT_LIGHT_ACTION: LIGHT_ACTION_TURN_OFF,
        },
        sleep=False,
    )
    _run(room._control_lights_exit({}))
    off_calls = [c for c in calls if c[1] == "turn_off"]
    assert len(off_calls) == 1, f"expected 1 turn_off, got {off_calls}"
    dom, _svc, ids = off_calls[0]
    assert dom == "light"
    assert ids == ("light.a",), f"expected only light.a, got {ids}"


# ===========================================================================
# D3a — _shared_space_turn_off_all (unconditional union)
# ===========================================================================


def test_D3a_shared_space_nonsleep_night_only_gets_turn_off():
    room, calls = _make_room(
        {CONF_LIGHTS: [], CONF_NIGHT_LIGHTS: ["switch.foo"]},
        sleep=False,
    )
    _run(room._shared_space_turn_off_all())
    assert _turn_offs_for(calls, "switch.foo"), (
        f"D3a non-sleep night-only entity MUST be turned off. calls={calls}"
    )


def test_D3a_shared_space_SLEEP_night_only_ALSO_gets_turn_off():
    """Rev 3: sleep does NOT gate the shared-space off — unconditional union."""
    room, calls = _make_room(
        {CONF_LIGHTS: [], CONF_NIGHT_LIGHTS: ["switch.foo"]},
        sleep=True,
    )
    _run(room._shared_space_turn_off_all())
    assert _turn_offs_for(calls, "switch.foo"), (
        f"Rev 3 D3a SLEEP: night-only entity MUST be turned off during "
        f"sleep too. calls={calls}"
    )


# ===========================================================================
# D3b — check_auto_off_warning + _warning_flash (unconditional union + A2-gate)
# Review-C C1 fix: these were hollow anchors — now proper behavioral coverage.
# ===========================================================================


def _prime_warning_time(room):
    """Configure the room so check_auto_off_warning enters the T-5 branch.

    Sets last_warning_date_hour to a different value, get_auto_off_hour
    to return a value that when combined with `dt_util.now()` triggers
    the "warning_hour minute >= 55" branch. Simplest: monkey-patch
    check_auto_off_warning's now source to a fixed time and set
    auto_off_hour so warning_hour == now.hour with minute=55.
    """
    import custom_components.universal_room_automation.automation as _auto_mod

    fixed = datetime(2026, 9, 1, 22, 55, 0)
    # dt_util.now is imported at module top as `dt_util`; monkey-patch its
    # `now` attribute for the duration of the call.
    room.get_auto_off_hour = lambda: 23  # warning_hour = 22
    room._last_warning_date_hour = None
    orig_now = _auto_mod.dt_util.now
    _auto_mod.dt_util.now = lambda: fixed
    return orig_now, _auto_mod


def _restore_dt(orig_now, mod):
    mod.dt_util.now = orig_now


def test_D3b_check_auto_off_warning_fires_for_night_only_on_light():
    """D3b: shared-space warning fires when the ONLY on-light is a night-only
    entity (previously silently missed because lights_on scanned CONF_LIGHTS
    only). Neutering the widen back to CONF_LIGHTS turns this RED.
    """
    room, calls = _make_room(
        {
            CONF_LIGHTS: [],
            CONF_NIGHT_LIGHTS: ["light.night_a"],
        },
        sleep=False,
    )
    # Prime the night entity as ON.
    st = MagicMock()
    st.state = "on"
    room._test_states["light.night_a"] = st

    # Stub _warning_flash so we OBSERVE it fires without needing the full
    # dt_util-driven flash body.
    flash_calls: list = []

    async def _flash():
        flash_calls.append(1)

    room._warning_flash = _flash
    room.is_shared_space = lambda: True
    room.should_warn_before_auto_off = lambda: True

    orig_now, mod = _prime_warning_time(room)
    try:
        _run(room.check_auto_off_warning())
    finally:
        _restore_dt(orig_now, mod)

    assert flash_calls, (
        "D3b: check_auto_off_warning MUST detect the night-only ON entity "
        "and fire the warning flash. Neuter the widen (revert to "
        "CONF_LIGHTS) and this test goes RED."
    )


def test_D3b_A2_gate_warning_flash_EXCLUDES_light_domain_night_only():
    """B-M1 fix: A2-gate exclusion is DOMAIN-SYMMETRIC. A LIGHT.* night-only
    entity is also excluded from the flash ON-cycle — otherwise it would be
    blasted from sleep brightness (e.g. 15) to hard-coded brightness=255
    for the pre-auto-off warning (same UX bug as the switch-domain
    mains-blast). The entity is still turned OFF by D3a at auto-off time.

    Mutation drill: revert the A2 exclusion (include night-only in flash
    target) → this test AND the switch-domain sibling test both go RED.
    """
    room, calls = _make_room(
        {
            CONF_LIGHTS: [],
            CONF_NIGHT_LIGHTS: ["light.night_dim"],
        },
        sleep=False,
    )
    try:
        _run(asyncio.wait_for(room._warning_flash(), timeout=5))
    except asyncio.TimeoutError:
        pass
    # A2-gate: light.night_dim (night-only, light domain) is EXCLUDED
    # from the flash ON cycle.
    on_for_light_night = _turn_ons_for(calls, "light.night_dim")
    assert not on_for_light_night, (
        f"A2-gate (B-M1): light-domain night-only entity light.night_dim "
        f"MUST NOT receive a turn_on from the warning flash (would blast "
        f"from sleep brightness to 255). calls={calls}"
    )
    # And no turn_off from flash either (flash only cycles).
    # (D3a auto-off handles the OFF separately.)


def test_D3b_A2_gate_regular_light_STILL_flashes():
    """Positive control: regular-list light.* entities STILL flash — the
    A2 gate only excludes NIGHT-ONLY entities. Mutation drill: broadening
    the exclusion to all lights would break this test."""
    room, calls = _make_room(
        {
            CONF_LIGHTS: ["light.regular"],
            CONF_NIGHT_LIGHTS: [],
        },
        sleep=False,
    )
    try:
        _run(asyncio.wait_for(room._warning_flash(), timeout=5))
    except asyncio.TimeoutError:
        pass
    assert _turn_ons_for(calls, "light.regular"), (
        f"regular light.* MUST still flash. calls={calls}"
    )


def test_D3b_A2_gate_warning_flash_EXCLUDES_switch_domain_night_only():
    """A2-gate: switch.* night-only entities are EXCLUDED from the flash
    ON-cycle (potentially jarring at mains-brightness during low-light
    hours). They ARE still turned OFF at auto-off (that's D3a's job — a
    separate site). Mutation drill: revert the A2-gate (include
    switch-domain night-only in flash_targets) → this test turns RED.
    """
    room, calls = _make_room(
        {
            CONF_LIGHTS: [],
            CONF_NIGHT_LIGHTS: ["switch.night_relay", "light.night_dim"],
        },
        sleep=False,
    )
    try:
        _run(asyncio.wait_for(room._warning_flash(), timeout=5))
    except asyncio.TimeoutError:
        pass
    # A2-gate (B-M1): BOTH switch.* AND light.* night-only entities are
    # excluded from the flash ON cycle (domain-symmetric).
    assert not _turn_ons_for(calls, "switch.night_relay"), (
        f"A2-gate: switch-domain night-only MUST NOT flash. calls={calls}"
    )
    assert not _turn_ons_for(calls, "light.night_dim"), (
        f"A2-gate (B-M1): light-domain night-only MUST NOT flash either "
        f"(would blast dim night light to 255). calls={calls}"
    )


# ===========================================================================
# D6 — coordinator.py::_get_builtin_target_entities(TRIGGER_EXIT)
# (unconditional union — no sleep gate on the conflict-detection surface)
# ===========================================================================


def test_D6_exit_target_entities_include_night_only():
    from custom_components.universal_room_automation.coordinator import (
        UniversalRoomCoordinator,
    )
    from custom_components.universal_room_automation.const import (
        TRIGGER_ENTER,
        TRIGGER_EXIT,
    )

    import types as _types
    stub = _types.SimpleNamespace()
    stub._get_config = lambda key, default=None: {
        CONF_LIGHTS: ["light.a"],
        CONF_NIGHT_LIGHTS: ["light.b", "light.a"],
    }.get(key, default)

    fn = UniversalRoomCoordinator._get_builtin_target_entities
    exit_targets = fn(stub, TRIGGER_EXIT)
    assert "light.a" in exit_targets
    assert "light.b" in exit_targets
    assert exit_targets.count("light.a") == 1, (
        f"D6 dedup: light.a should appear exactly once, got {exit_targets}"
    )

    # D6 non-change: enter trigger target set unchanged (CONF_LIGHTS only).
    enter_targets = fn(stub, TRIGGER_ENTER)
    assert "light.a" in enter_targets
    assert "light.b" not in enter_targets, (
        f"D6 non-change: enter trigger MUST NOT include night-only. got {enter_targets}"
    )
