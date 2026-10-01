"""Room lighting Slice C (v5.103.28) — D2 light manual hold, URA write mark,
D3 Room lights switch, and the deferred Slice B' reconciler leave-on harness.

Invariant: no URA write ever opens a manual hold; a person's change to a
room light during occupancy is never undone by URA until the room empties.

The module imports the REAL homeassistant + URA package inside a scoped
fixture: sys.modules entries under ``homeassistant`` / ``custom_components``
are set aside for the module and restored afterwards (sibling files install
stubs there at collection time). Every test drives production methods and
asserts on the service calls they emit.
"""

from __future__ import annotations

import asyncio
import importlib
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

_PREFIXES = ("homeassistant", "custom_components")
M: dict = {}


@pytest.fixture(scope="module", autouse=True)
def _real_modules():
    saved = {k: v for k, v in sys.modules.items() if k.startswith(_PREFIXES)}
    for k in saved:
        sys.modules.pop(k, None)
    try:
        base = "custom_components.universal_room_automation"
        for name in (
            "const", "ura_context", "automation", "actuator_reconciler",
            "switch", "aggregation", "coordinator",
            "domain_coordinators.light_policy_oracle",
            "domain_coordinators.notification_manager",
            "domain_coordinators.manager", "domain_coordinators.base",
            "lighting.resolver",
        ):
            M[name] = importlib.import_module(f"{base}.{name}")
        from homeassistant.core import Context
        M["Context"] = Context
        yield
    finally:
        for k in [k for k in sys.modules if k.startswith(_PREFIXES)]:
            sys.modules.pop(k, None)
        sys.modules.update(saved)
        M.clear()


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeServices:
    def __init__(self, hass):
        self.calls: list = []
        self._hass = hass

    async def async_call(self, domain, service, data=None, blocking=False, **kw):
        data = dict(data or {})
        self.calls.append(SimpleNamespace(
            domain=domain, service=service, data=data, context=kw.get("context"),
        ))
        # Echo the write onto the state machine like a real entity would
        # (same context object — helpers/entity.py:1248).
        eids = data.get("entity_id")
        eids = [eids] if isinstance(eids, str) else list(eids or [])
        if service in ("turn_on", "turn_off"):
            for e in eids:
                self._hass.set_state(e, "on" if service == "turn_on" else "off",
                                     context=kw.get("context"))


class FakeHass:
    def __init__(self):
        self.data: dict = {"universal_room_automation": {}}
        self._states: dict = {}
        self.states = SimpleNamespace(get=lambda e: self._states.get(e))
        self.services = FakeServices(self)
        self.listeners: list = []

    def set_state(self, entity_id, state, context=None):
        old = self._states.get(entity_id)
        new = SimpleNamespace(entity_id=entity_id, state=state, attributes={})
        self._states[entity_id] = new
        ev = SimpleNamespace(
            data={"entity_id": entity_id, "old_state": old, "new_state": new},
            context=context,
        )
        for cb in list(self.listeners):
            cb(ev)

    async def async_add_executor_job(self, fn, *a):
        return None

    def async_create_task(self, coro):
        coro.close()


def _ctx_is_ura(ctx):
    return M["ura_context"].is_ura_context(ctx)


def _light_calls(hass, service=None):
    return [c for c in hass.services.calls
            if c.domain in ("light", "switch")
            and (service is None or c.service == service)]


def _ids(call):
    e = call.data.get("entity_id")
    return [e] if isinstance(e, str) else list(e or [])


def _targets(hass, service):
    out = []
    for c in _light_calls(hass, service):
        out.extend(_ids(c))
    return out


# ---------------------------------------------------------------------------
# Room builder: real RoomAutomation + real ActuatorReconciler wired to a
# minimal coordinator. The reconciler's listener is the D2 detector.
# ---------------------------------------------------------------------------

C = SimpleNamespace()


def _c():
    const = M["const"]
    return const


def make_room(config=None, occupied=True, sleep=False, entry_id="room_1"):
    const = _c()
    hass = FakeHass()
    base_cfg = {
        "room_name": "Den",
        const.CONF_LIGHTS: ["light.a", "light.b"],
        const.CONF_NIGHT_LIGHTS: [],
        const.CONF_ENTRY_LIGHT_ACTION: const.LIGHT_ACTION_TURN_ON,
        const.CONF_EXIT_LIGHT_ACTION: const.LIGHT_ACTION_TURN_OFF,
    }
    base_cfg.update(config or {})
    entry = SimpleNamespace(entry_id=entry_id, data=dict(base_cfg), options={})

    coord = SimpleNamespace()
    coord.hass = hass
    coord.entry = entry
    coord.config_entry = entry
    coord.data = {const.STATE_OCCUPIED: occupied}
    coord._skip_first_automation = False
    coord._switch = {}
    coord._is_automation_enabled = lambda: coord._switch.get("manual_mode") is not True
    coord._is_cover_automation_enabled = lambda: False
    coord.set_last_action = lambda *a, **k: None

    RA = M["automation"].RoomAutomation
    auto = RA.__new__(RA)
    auto.hass = hass
    auto.config = dict(base_cfg)
    auto._config_entry = entry
    auto.coordinator = coord
    auto._service_calls_today = 0
    auto._service_failures_today = 0
    auto._service_call_reset_date = ""
    auto._sleep_motion_count = 0
    auto._refresh_config = lambda: None
    auto.is_sleep_mode_active = lambda: sleep
    coord.automation = auto

    rec = M["actuator_reconciler"].ActuatorReconciler(coord)
    rec._created_monotonic = rec._now() - 1_000_000.0
    hass.listeners.append(rec._handle_state_change)
    return SimpleNamespace(hass=hass, coord=coord, auto=auto, rec=rec, entry=entry)


def person(room, entity_id, state):
    """A person's change: plain HA Context (no URA mark)."""
    room.hass.set_state(entity_id, state, context=M["Context"](user_id="u1"))


def holds(room):
    return M["domain_coordinators.light_policy_oracle"].get_light_oracle(
        room.hass, "universal_room_automation",
    ).get_state(room.entry.entry_id)


# ===========================================================================
# Writer stamps (inventory rows 1-10 + surfaced writers)
# ===========================================================================


def test_w1_room_tier_write_is_ura_stamped():
    room = make_room()
    room.hass.set_state("light.a", "on")
    _run(room.auto._control_lights_exit({}))
    calls = _light_calls(room.hass, "turn_off")
    assert calls and all(_ctx_is_ura(c.context) for c in calls)


def test_w1_room_tier_non_light_write_unstamped():
    """Byte-identical for non-light domains (cover/fan/climate...)."""
    room = make_room()
    _run(room.auto._safe_service_call("cover", "open_cover", {"entity_id": "cover.x"}))
    assert room.hass.services.calls[-1].context is None


def test_w2_reconciler_fallback_write_is_ura_stamped():
    room = make_room()
    room.coord.automation = None
    _run(room.rec._safe_service_call("light", "turn_on", {"entity_id": ["light.a"]}))
    assert _ctx_is_ura(room.hass.services.calls[-1].context)


def _nm(hass):
    NM = M["domain_coordinators.notification_manager"].NotificationManager
    nm = NM.__new__(NM)
    nm.hass = hass
    nm._light_original_states = {}
    nm._dry_run_active = False
    return nm


def test_w3_nm_alert_flash_and_restore_are_ura_stamped():
    hass = FakeHass()
    nm = _nm(hass)
    _run(nm._run_light_pattern(["light.a"], {"effect": "solid", "brightness": 200}))
    nm._light_original_states = {"light.a": {"state": "off"},
                                 "light.b": {"state": "on", "brightness": 10}}
    _run(nm._restore_alert_lights())
    calls = _light_calls(hass)
    assert len(calls) == 3
    assert all(_ctx_is_ura(c.context) for c in calls)


def test_w4_aggregation_alert_flash_is_ura_stamped():
    hass = FakeHass()
    hass.set_state("light.a", "on")
    cls = M["aggregation"].SafetyAlertBinarySensor
    ent = cls.__new__(cls)
    ent.hass = hass
    _run(cls._flash_light(ent, "light.a", [255, 0, 0], flashes=1))
    calls = _light_calls(hass)
    assert len(calls) == 3  # on, off, restore-on
    assert all(_ctx_is_ura(c.context) for c in calls)


def _mgr(hass):
    CM = M["domain_coordinators.manager"].CoordinatorManager
    mgr = CM.__new__(CM)
    mgr.hass = hass
    mgr._notification_manager = None
    return mgr


def test_w5_safety_security_light_actions_are_ura_stamped():
    base = M["domain_coordinators.base"]
    hass = FakeHass()
    mgr = _mgr(hass)
    coord = SimpleNamespace(coordinator_id="security")
    act = base.ServiceCallAction(
        coordinator_id="security", severity=base.Severity.HIGH,
        service="light.turn_on", service_data={"entity_id": "light.porch", "flash": "long"},
    )
    _run(mgr._execute_action(coord, act))
    assert _ctx_is_ura(hass.services.calls[-1].context)
    clim = base.ServiceCallAction(
        coordinator_id="safety", service="climate.set_hvac_mode",
        service_data={"entity_id": "climate.z", "hvac_mode": "off"},
    )
    _run(mgr._execute_action(SimpleNamespace(coordinator_id="safety"), clim))
    assert hass.services.calls[-1].context is None  # non-light untouched


def test_w8_ai_rule_light_action_is_ura_stamped():
    Coord = M["coordinator"].UniversalRoomCoordinator
    c = Coord.__new__(Coord)
    hass = FakeHass()
    c.hass = hass
    _run(c._execute_rule_action(
        {"domain": "light", "service": "turn_on", "target": {"entity_id": "light.a"}},
        "Den",
    ))
    assert hass.services.calls and _ctx_is_ura(hass.services.calls[-1].context)


# ===========================================================================
# Listener filter (D2 detector in ActuatorReconciler._handle_state_change)
# ===========================================================================


def test_listener_person_on_while_occupied_opens_hold():
    room = make_room()
    room.hass.set_state("light.a", "off")
    person(room, "light.a", "on")
    assert holds(room)["light.a"]["on_hold_until"] is not None


def test_listener_ura_write_opens_no_hold():
    room = make_room()
    room.hass.set_state("light.a", "off")
    _run(room.auto._turn_on_regular_lights())
    assert room.hass._states["light.a"].state == "on"
    assert holds(room) == {}


def test_listener_alert_flash_opens_no_hold_R2_1():
    """R2-1 discriminator: NM alert flash + restore on a CONF_LIGHTS entity
    opens NO hold; the next exit sweeps normally."""
    room = make_room()
    room.hass.set_state("light.a", "off")
    nm = _nm(room.hass)
    _run(nm._run_light_pattern(["light.a"], {"effect": "solid"}))
    nm._light_original_states = {"light.a": {"state": "off"}}
    _run(nm._restore_alert_lights())
    assert holds(room) == {}
    room.hass.set_state("light.a", "on", context=M["ura_context"].ura_write_context())
    _run(room.auto.handle_occupancy_change(False, {}))
    assert "light.a" in _targets(room.hass, "turn_off")


def test_listener_vacant_room_opens_no_hold():
    room = make_room(occupied=False)
    room.hass.set_state("light.a", "off")
    person(room, "light.a", "on")
    assert holds(room) == {}


def test_listener_availability_edge_opens_no_hold():
    room = make_room()
    room.hass.set_state("light.a", "unavailable")
    person(room, "light.a", "on")
    assert holds(room) == {}


def test_listener_foreign_entity_ignored():
    room = make_room()
    room.hass.set_state("light.other", "off")
    person(room, "light.other", "on")
    assert holds(room) == {}


def test_listener_person_off_opens_cooldown():
    room = make_room()
    room.hass.set_state("light.a", "on")
    person(room, "light.a", "off")
    assert holds(room)["light.a"]["off_cooldown_until"] is not None


# ===========================================================================
# Hold-respect sites
# ===========================================================================


def test_h1_on_entry_branch_skips_cooldown_light():
    const = _c()
    room = make_room({const.CONF_LIGHTS_ON_ENTRY: ["light.a", "light.b"]})
    room.hass.set_state("light.a", "on")
    person(room, "light.a", "off")
    room.hass.services.calls.clear()
    _run(room.auto._control_lights_entry({}))
    on = _targets(room.hass, "turn_on")
    assert "light.b" in on and "light.a" not in on


def test_h2_regular_lights_skip_cooldown_light():
    room = make_room()
    room.hass.set_state("light.a", "on")
    person(room, "light.a", "off")
    room.hass.services.calls.clear()
    _run(room.auto._control_lights_entry({}))
    on = _targets(room.hass, "turn_on")
    assert "light.b" in on and "light.a" not in on


def test_h3_night_lights_skip_cooldown_light():
    const = _c()
    room = make_room({const.CONF_NIGHT_LIGHTS: ["light.n", "light.m"]}, sleep=True)
    room.hass.set_state("light.n", "on")
    person(room, "light.n", "off")
    room.hass.services.calls.clear()
    _run(room.auto._turn_on_night_lights(mode="sleep"))
    on = _targets(room.hass, "turn_on")
    assert "light.m" in on and "light.n" not in on


def test_h4_sleep_entry_does_not_turn_off_held_light():
    const = _c()
    room = make_room({const.CONF_NIGHT_LIGHTS: ["light.n"]}, sleep=True)
    room.hass.set_state("light.a", "off")
    person(room, "light.a", "on")
    room.hass.services.calls.clear()
    _run(room.auto._control_lights_entry({}))
    off = _targets(room.hass, "turn_off")
    assert "light.b" in off and "light.a" not in off


def test_h5_shared_space_auto_off_spares_held_light():
    room = make_room()
    room.hass.set_state("light.a", "off")
    person(room, "light.a", "on")
    room.hass.services.calls.clear()
    _run(room.auto._shared_space_turn_off_all())
    off = _targets(room.hass, "turn_off")
    assert "light.b" in off and "light.a" not in off


def test_h6_reconciler_does_not_undo_person_on():
    """Sleep + non-night light: the reconciler would assert OFF — the hold
    keeps a person's ON."""
    const = _c()
    room = make_room({const.CONF_NIGHT_LIGHTS: ["light.n"]}, sleep=True)
    room.hass.set_state("light.a", "off")
    person(room, "light.a", "on")
    room.hass.services.calls.clear()
    _run(room.rec._reconcile_one("light.a"))
    assert _targets(room.hass, "turn_off") == []
    _run(room.rec._reconcile_one("light.b"))  # control: unheld light is fixed
    room.hass.set_state("light.b", "on")
    _run(room.rec._reconcile_one("light.b"))
    assert "light.b" in _targets(room.hass, "turn_off")


def test_h6_reconciler_respects_off_cooldown():
    room = make_room()
    room.hass.set_state("light.a", "on")
    person(room, "light.a", "off")
    room.hass.services.calls.clear()
    _run(room.rec._reconcile_one("light.a"))
    assert _targets(room.hass, "turn_on") == []


# ===========================================================================
# Hold clears when the room empties (REV 2.3.1 (a) (b) (c))
# ===========================================================================


def test_c_hold_cleared_on_vacancy_then_sleep_entry_turns_off():
    const = _c()
    room = make_room({const.CONF_NIGHT_LIGHTS: ["light.n"]})
    room.hass.set_state("light.a", "off")
    person(room, "light.a", "on")
    _run(room.auto.handle_occupancy_change(False, {}))
    assert holds(room)["light.a"]["on_hold_until"] is None
    room.auto.is_sleep_mode_active = lambda: True
    room.hass.services.calls.clear()
    _run(room.auto._control_lights_entry({}))
    assert "light.a" in _targets(room.hass, "turn_off")


def test_a_hand_on_non_entry_light_off_at_vacancy():
    const = _c()
    room = make_room({const.CONF_LIGHTS_ON_ENTRY: ["light.b"]})
    room.hass.set_state("light.a", "off")
    person(room, "light.a", "on")
    room.coord.data[const.STATE_OCCUPIED] = False
    _run(room.auto.handle_occupancy_change(False, {}))
    assert "light.a" in _targets(room.hass, "turn_off")


def test_b_leave_on_light_stays_on_at_vacancy():
    const = _c()
    room = make_room({const.CONF_LIGHTS_LEAVE_ON_WHEN_EMPTY: ["light.a"]})
    room.hass.set_state("light.a", "off")
    person(room, "light.a", "on")
    _run(room.auto.handle_occupancy_change(False, {}))
    off = _targets(room.hass, "turn_off")
    assert "light.a" not in off and "light.b" in off


def test_off_cooldown_survives_vacancy():
    room = make_room()
    room.hass.set_state("light.a", "on")
    person(room, "light.a", "off")
    _run(room.auto.handle_occupancy_change(False, {}))
    assert holds(room)["light.a"]["off_cooldown_until"] is not None


# ===========================================================================
# Manual Mode composition (disjunctive)
# ===========================================================================


def test_manual_mode_and_hold_are_disjunctive():
    const = _c()
    room = make_room({const.CONF_NIGHT_LIGHTS: ["light.n"]}, sleep=True)
    room.hass.set_state("light.a", "off")
    person(room, "light.a", "on")
    room.coord._switch["manual_mode"] = True
    assert room.rec._consider_reconcile("light.a", boot_edge=True) is None
    assert room.rec._last_skip_reason == "manual_mode"
    room.coord._switch["manual_mode"] = False  # hold alone still blocks
    room.hass.services.calls.clear()
    _run(room.rec._reconcile_one("light.a"))
    assert _targets(room.hass, "turn_off") == []
    assert room.rec._last_skip_reason == "light_manual_hold"


# ===========================================================================
# Knob extremes + boundaries (hardcoded literals)
# ===========================================================================


def test_knob_zero_disables_hold_and_cooldown():
    const = _c()
    room = make_room({const.CONF_LIGHT_MANUAL_ON_HOLD_S: 0,
                      const.CONF_LIGHT_MANUAL_OFF_COOLDOWN_S: 0})
    room.hass.set_state("light.a", "off")
    person(room, "light.a", "on")
    assert holds(room)["light.a"] == {"on_hold_until": None, "off_cooldown_until": None}
    room.hass.services.calls.clear()
    _run(room.auto._shared_space_turn_off_all())
    assert "light.a" in _targets(room.hass, "turn_off")


def test_oracle_boundaries_literal():
    O = M["domain_coordinators.light_policy_oracle"].LightPolicyOracle()
    t0 = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)
    O.note_manual("r", "light.a", "on", now=t0, on_hold_s=60, off_cooldown_s=900)
    assert O.may_turn_off("r", "light.a", t0 + timedelta(seconds=59)) is False
    assert O.may_turn_off("r", "light.a", t0 + timedelta(seconds=60)) is True
    assert O.may_turn_off("r", "light.a", t0 + timedelta(seconds=61)) is True
    O.note_manual("r", "light.a", "off", now=t0, on_hold_s=60, off_cooldown_s=900)
    assert O.may_turn_off("r", "light.a", t0) is True  # newest instruction wins
    assert O.may_turn_on("r", "light.a", t0 + timedelta(seconds=899)) is False
    assert O.may_turn_on("r", "light.a", t0 + timedelta(seconds=900)) is True
    O.release("r")
    assert O.get_state("r") == {}


# ===========================================================================
# D3 — Room lights switch
# ===========================================================================


def _switch(room):
    S = M["switch"].RoomLightsSwitch
    sw = S.__new__(S)
    sw.coordinator = room.coord
    sw.hass = room.hass
    sw.async_write_ha_state = lambda: None
    return sw


@pytest.mark.parametrize("sleep", [False, True])
def test_d3_turn_on_equals_effective_entry_set(sleep):
    const = _c()
    cfg = {const.CONF_NIGHT_LIGHTS: ["light.n"], const.CONF_LIGHTS: ["light.a", "switch.r"]}
    room = make_room(cfg, sleep=sleep)
    room.auto.is_dark = lambda _lux: True
    _run(_switch(room).async_turn_on())
    expected = M["lighting.resolver"].effective_entry_set(
        {**room.entry.data}, is_sleep_hours=sleep, is_dark=True,
    )
    assert sorted(_targets(room.hass, "turn_on")) == sorted(expected)
    assert all(_ctx_is_ura(c.context) for c in _light_calls(room.hass))


def test_d3_turn_off_includes_leave_on_and_notes_manual():
    const = _c()
    room = make_room({const.CONF_LIGHTS_LEAVE_ON_WHEN_EMPTY: ["light.a"],
                      const.CONF_NIGHT_LIGHTS: ["light.n"]})
    for e in ("light.a", "light.b", "light.n"):
        room.hass.set_state(e, "on")
    sw = _switch(room)
    assert sw.is_on is True
    _run(sw.async_turn_off())
    assert sorted(_targets(room.hass, "turn_off")) == ["light.a", "light.b", "light.n"]
    h = holds(room)
    assert all(h[e]["off_cooldown_until"] is not None for e in ("light.a", "light.b", "light.n"))
    assert sw.is_on is False


def test_d3_turn_on_opens_hold_via_note_manual_only():
    room = make_room()
    _run(_switch(room).async_turn_on())
    h = holds(room)
    assert h["light.a"]["on_hold_until"] is not None
    assert h["light.b"]["on_hold_until"] is not None


def test_d3_unique_id_distinct_from_manual_mode():
    room = make_room()
    ids = {
        M["switch"].RoomLightsSwitch(room.coord).unique_id,
        M["switch"].ManualModeSwitch(room.coord).unique_id,
    }
    assert ids == {"room_1_room_lights", "room_1_manual_mode"}


# ===========================================================================
# Slice B' deferred gap — reconciler vacant-branch leave-on carve-out
# ===========================================================================


def test_reconciler_vacant_leave_on_carve_out():
    const = _c()
    room = make_room({const.CONF_LIGHTS_LEAVE_ON_WHEN_EMPTY: ["light.a"]}, occupied=False)
    room.hass.set_state("light.a", "on")
    room.hass.set_state("light.b", "on")
    _run(room.rec._reconcile_one("light.a"))
    _run(room.rec._reconcile_one("light.b"))
    off = _targets(room.hass, "turn_off")
    assert off == ["light.b"]
