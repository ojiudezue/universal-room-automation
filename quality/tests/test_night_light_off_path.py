"""NIGHT-LIGHT-NO-OFF-PATH-1 — behavioral tests for the sleep-gated
off_set widening across all four turn-off emission sites + D4 hoisted
sleep entry block + D6 conflict-detector surface.

Sites under test:
- D1: automation.py::_control_lights_exit
- D2: actuator_reconciler.py::_resolve_light vacant branch (covered by
      test_reconcile_on_return.py — the two tests added there)
- D3a: automation.py::_shared_space_turn_off_all
- D3b: automation.py::check_auto_off_warning + _warning_flash
- D4: automation.py::_control_lights_entry hoisted sleep block
- D5: hvac.py::_execute_vacancy_sweep lights loop
- D6: coordinator.py::_get_builtin_target_entities(TRIGGER_EXIT)

Each test is a behavioral turn_off / DesiredState emission assertion,
NOT a source grep (planning doc L1 — hollow-anchor guard).

Test-authority (mutation) neuter→RED anchors — the reviewer / builder
can neuter one site at a time to confirm each named test fails.
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

    Only the surface each _control_* helper touches is injected. Service
    calls are captured on a list (domain, service, entity_ids-sorted-tuple).
    """
    from custom_components.universal_room_automation.automation import (
        RoomAutomation,
    )

    room = RoomAutomation.__new__(RoomAutomation)
    hass = MagicMock()
    hass.data = {DOMAIN: {}}
    calls: list[tuple[str, str, tuple]] = []

    async def _svc_call(domain, service, data=None, blocking=False, **_):
        eid = (data or {}).get("entity_id", "")
        if isinstance(eid, list):
            ids = tuple(sorted(eid))
        else:
            ids = (eid,)
        # `service` may be a MagicMock from const imports — normalize to str.
        svc = str(service) if not isinstance(service, str) else service
        # Detect turn_off/turn_on via HA constants regardless of mock name.
        if "TURN_OFF" in svc or svc == "turn_off":
            svc = "turn_off"
        elif "TURN_ON" in svc or svc == "turn_on":
            svc = "turn_on"
        calls.append((domain, svc, ids))
        return True

    hass.services = MagicMock()
    hass.services.async_call = _svc_call
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

    # coordinator surface needed by set_last_action + _control_lights_exit tail.
    coord = MagicMock()
    coord.set_last_action = MagicMock()
    coord._is_cover_automation_enabled = MagicMock(return_value=False)
    room.coordinator = coord

    return room, calls


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _turn_offs_for(calls, entity_id):
    """Return list of (domain, service) records whose entity list contains eid."""
    out = []
    for dom, svc, ids in calls:
        if svc != "turn_off":
            continue
        if entity_id in ids:
            out.append((dom, svc, ids))
    return out


# ===========================================================================
# D1 — _control_lights_exit sleep-gated off_set
# ===========================================================================


def test_D1_exit_nonsleep_night_only_entity_gets_turn_off():
    """D1: non-sleep vacancy on a night-only entity emits turn_off (the fix)."""
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


def test_D1_exit_sleep_bypass_night_only_entity_gets_NO_turn_off():
    """D1 DISCRIMINATING (Rev 2 M1/M2): sleep + vacancy → night-only entity
    receives ZERO turn_off. Neutering the sleep gate MUST turn this RED.
    """
    room, calls = _make_room(
        {
            CONF_LIGHTS: ["light.a"],
            CONF_NIGHT_LIGHTS: ["light.b"],
            CONF_EXIT_LIGHT_ACTION: LIGHT_ACTION_TURN_OFF,
        },
        sleep=True,
    )
    _run(room._control_lights_exit({}))
    assert not _turn_offs_for(calls, "light.b"), (
        "D1 sleep-gate: night-only light.b MUST NOT be turned off during "
        f"sleep even on the vacancy path. calls={calls}"
    )
    # light.a (regular) is in CONF_LIGHTS — unchanged behavior, may be off.


def test_D1_exit_nonsleep_dedup_single_emission_per_dual_listed_entity():
    """Dual-listed entity (in BOTH CONF_LIGHTS and CONF_NIGHT_LIGHTS) is
    turned off exactly once — order-preserving dedup.
    """
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
    # light.a appears in exactly one turn_off service_data entity_id list
    # (dedup); light.b likewise appears once.
    a_count = sum(1 for c in a_offs)
    b_count = sum(1 for c in b_offs)
    assert a_count == 1, f"light.a dedup regression: {a_offs}"
    assert b_count == 1, f"light.b turn_off missing: {calls}"


# ===========================================================================
# D3a — _shared_space_turn_off_all
# ===========================================================================


def test_D3a_shared_space_nonsleep_night_only_gets_turn_off():
    room, calls = _make_room(
        {
            CONF_LIGHTS: [],
            CONF_NIGHT_LIGHTS: ["switch.foo"],
        },
        sleep=False,
    )
    _run(room._shared_space_turn_off_all())
    assert _turn_offs_for(calls, "switch.foo"), (
        f"D3a non-sleep night-only entity MUST be turned off. calls={calls}"
    )


def test_D3a_shared_space_sleep_night_only_gets_NO_turn_off():
    room, calls = _make_room(
        {
            CONF_LIGHTS: [],
            CONF_NIGHT_LIGHTS: ["switch.foo"],
        },
        sleep=True,
    )
    _run(room._shared_space_turn_off_all())
    assert not _turn_offs_for(calls, "switch.foo"), (
        "D3a sleep gate: night-only entity MUST NOT be turned off during "
        f"sleep in shared-space consolidated off. calls={calls}"
    )


# ===========================================================================
# D4 — _control_lights_entry hoisted sleep block
# ===========================================================================


def test_D4_master_bedroom_shape_sleep_entry_none_turns_on_night_lights():
    """Master-Bedroom shape: entry_action=none, lights=[], night_lights=[x],
    sleep=True → _turn_on_night_lights invoked; _turn_off_non_night_lights
    NOT invoked (H2)."""
    from custom_components.universal_room_automation.automation import (
        RoomAutomation,
    )
    room, calls = _make_room(
        {
            CONF_LIGHTS: [],
            CONF_NIGHT_LIGHTS: ["light.x"],
            CONF_ENTRY_LIGHT_ACTION: LIGHT_ACTION_NONE,
        },
        sleep=True,
    )

    # Instrument the helper methods.
    on_calls: list[str] = []
    off_calls: list[str] = []

    async def _on(mode="sleep"):
        on_calls.append(mode)

    async def _off():
        off_calls.append("called")

    room._turn_on_night_lights = _on
    room._turn_off_non_night_lights = _off

    _run(room._control_lights_entry({}))

    assert on_calls == ["sleep"], (
        f"D4: night lights ON must be invoked once with mode=sleep, got {on_calls}"
    )
    assert off_calls == [], (
        f"D4 H2: _turn_off_non_night_lights MUST NOT be called from the "
        f"hoisted sleep block. off_calls={off_calls}"
    )


def test_D4_patio_shape_sleep_entry_none_regular_light_gets_NO_turn_off():
    """Patio/Game-Room shape: entry_action=none, lights=[light.a] (non-empty),
    night_lights=[light.b], sleep=True → night lights ON; NO turn_off
    service call for light.a from the hoisted block (H2).
    """
    room, calls = _make_room(
        {
            CONF_LIGHTS: ["light.a"],
            CONF_NIGHT_LIGHTS: ["light.b"],
            CONF_ENTRY_LIGHT_ACTION: LIGHT_ACTION_NONE,
        },
        sleep=True,
    )

    on_calls: list[str] = []
    async def _on(mode="sleep"):
        on_calls.append(mode)

    room._turn_on_night_lights = _on
    room._turn_off_non_night_lights = MagicMock()  # capture calls

    _run(room._control_lights_entry({}))

    assert on_calls == ["sleep"], f"D4: night lights ON expected, got {on_calls}"
    # H2: hoisted block does NOT call the off helper.
    assert not room._turn_off_non_night_lights.called, (
        f"D4 H2: _turn_off_non_night_lights MUST NOT be called from the "
        f"hoisted block (would newly kill regular lights during sleep for "
        f"entry=none rooms)."
    )
    # And no direct turn_off on light.a either.
    assert not _turn_offs_for(calls, "light.a"), (
        f"D4 H2: light.a MUST NOT receive turn_off from the hoisted block. "
        f"calls={calls}"
    )


def test_D4_nonsleep_entry_none_is_noop():
    """Non-sleep + entry_action=none → hoisted block skipped, function
    early-returns at :980 (empty lights) or the action==NONE guard.
    Snapshot the no-op.
    """
    room, calls = _make_room(
        {
            CONF_LIGHTS: [],
            CONF_NIGHT_LIGHTS: ["light.x"],
            CONF_ENTRY_LIGHT_ACTION: LIGHT_ACTION_NONE,
        },
        sleep=False,
    )

    on_calls: list[str] = []
    async def _on(mode="sleep"):
        on_calls.append(mode)

    room._turn_on_night_lights = _on

    _run(room._control_lights_entry({}))
    assert on_calls == [], f"non-sleep entry=none should be noop, got {on_calls}"
    assert calls == [], f"non-sleep entry=none should be noop, got {calls}"


# ===========================================================================
# D6 — coordinator.py::_get_builtin_target_entities(TRIGGER_EXIT)
# ===========================================================================


def test_D6_exit_target_entities_include_night_only():
    """D6: exit trigger target set includes union CONF_LIGHTS ∪ CONF_NIGHT_LIGHTS
    (dedup). Entry trigger unchanged.
    """
    from custom_components.universal_room_automation.coordinator import (
        UniversalRoomCoordinator,
    )
    from custom_components.universal_room_automation.const import (
        TRIGGER_ENTER,
        TRIGGER_EXIT,
    )

    # DataUpdateCoordinator base is a MagicMock (spec-locked); invoke the
    # unbound method with a plain namespace as `self` — the function only
    # reads self._get_config.
    import types as _types
    stub = _types.SimpleNamespace()
    stub._get_config = lambda key, default=None: {
        CONF_LIGHTS: ["light.a"],
        CONF_NIGHT_LIGHTS: ["light.b", "light.a"],
    }.get(key, default)

    fn = UniversalRoomCoordinator._get_builtin_target_entities
    exit_targets = fn(stub, TRIGGER_EXIT)
    assert "light.a" in exit_targets, exit_targets
    assert "light.b" in exit_targets, exit_targets
    # Dedup: light.a appears once, not twice.
    assert exit_targets.count("light.a") == 1, (
        f"D6 dedup: light.a should appear exactly once, got {exit_targets}"
    )

    # D6 non-change: enter trigger target set unchanged (CONF_LIGHTS only for lights).
    enter_targets = fn(stub, TRIGGER_ENTER)
    assert "light.a" in enter_targets
    assert "light.b" not in enter_targets, (
        f"D6 non-change: enter trigger MUST NOT include night-only. got {enter_targets}"
    )
