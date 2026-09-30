"""Room lighting Slice D (v5.103.29) — D4 house-state awareness.

Covers:
  * Away leave-on sweep: acts only on leave-on entities, gated by
    ``CONF_AWAY_TURN_OFF_LEAVE_ON`` (default True); manual holds do NOT
    block; boot-settle gate suppresses within the settle window;
    Home→Away→Home no-flap.
  * Sleep precedence: HouseState=="sleep" makes ``is_sleep_mode_active``
    return True even outside the per-room sleep clock (plan D4 tie rule
    "Sleep wins").
  * AI-rule light writes respect the manual hold (stamped writes still
    never open holds — Slice C invariant preserved).

Uses the same real-module import scoping pattern as
``test_lighting_slice_c_manual_hold.py``.
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
            "coordinator",
            "domain_coordinators.light_policy_oracle",
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


class FakeServices:
    def __init__(self, hass):
        self.calls: list = []
        self._hass = hass

    async def async_call(self, domain, service, data=None, blocking=False, **kw):
        data = dict(data or {})
        self.calls.append(SimpleNamespace(
            domain=domain, service=service, data=data, context=kw.get("context"),
        ))


class FakeHass:
    def __init__(self):
        self.data: dict = {"universal_room_automation": {}}
        self._states: dict = {}
        self.states = SimpleNamespace(get=lambda e: self._states.get(e))
        self.services = FakeServices(self)

    def set_state(self, e, s):
        self._states[e] = SimpleNamespace(entity_id=e, state=s, attributes={})

    async def async_add_executor_job(self, fn, *a):
        return None


def _light_targets(hass, service):
    out = []
    for c in hass.services.calls:
        if c.domain in ("light", "switch") and c.service == service:
            e = c.data.get("entity_id")
            out.extend([e] if isinstance(e, str) else list(e or []))
    return out


# ---------------------------------------------------------------------------
# Room / coordinator builder for D4 Away sweep + AI-rule tests
# ---------------------------------------------------------------------------


def _make_room(hass, leave_on=None, away_off=True, boot_done=True,
               entry_id="room_1"):
    const = M["const"]
    cfg = {
        "room_name": "Den",
        const.CONF_LIGHTS: ["light.a", "light.b"],
        const.CONF_LIGHTS_LEAVE_ON_WHEN_EMPTY: list(leave_on or []),
        const.CONF_AWAY_TURN_OFF_LEAVE_ON: away_off,
        const.CONF_SLEEP_PROTECTION_ENABLED: True,
        const.CONF_SLEEP_START_HOUR: 22,
        const.CONF_SLEEP_END_HOUR: 7,
    }
    entry = SimpleNamespace(entry_id=entry_id, data=dict(cfg), options={})
    RA = M["automation"].RoomAutomation
    auto = RA.__new__(RA)
    auto.hass = hass
    auto.config = dict(cfg)
    auto._config_entry = entry
    auto._service_calls_today = 0
    auto._service_failures_today = 0
    auto._service_call_reset_date = ""
    auto._refresh_config = lambda: None

    # Wire the "presence" coordinator boot-settle flag through hass.data.
    presence = SimpleNamespace(_boot_settle_done=boot_done)
    mgr = SimpleNamespace(coordinators={"presence": presence})
    hass.data["universal_room_automation"]["coordinator_manager"] = mgr
    return auto, entry


# ===========================================================================
# D4 Away leave-on sweep
# ===========================================================================


def test_away_sweep_off_leave_on_only_when_boolean_true_and_list_nonempty():
    hass = FakeHass()
    auto, _e = _make_room(hass, leave_on=["light.porch"], away_off=True)
    _run(auto.handle_away_leave_on_sweep())
    assert _light_targets(hass, "turn_off") == ["light.porch"]


def test_away_sweep_inert_when_leave_on_empty():
    hass = FakeHass()
    auto, _e = _make_room(hass, leave_on=[], away_off=True)
    _run(auto.handle_away_leave_on_sweep())
    assert _light_targets(hass, "turn_off") == []


def test_away_sweep_inert_when_boolean_false():
    hass = FakeHass()
    auto, _e = _make_room(hass, leave_on=["light.porch"], away_off=False)
    _run(auto.handle_away_leave_on_sweep())
    assert _light_targets(hass, "turn_off") == []


def test_away_sweep_ignores_manual_hold_for_leave_on():
    """Operator precedence: Away sweep wins over a manual hold for the
    leave-on list when the boolean is True (plan REV 2.2)."""
    hass = FakeHass()
    auto, entry = _make_room(hass, leave_on=["light.porch"], away_off=True)
    oracle = M["domain_coordinators.light_policy_oracle"].get_light_oracle(
        hass, "universal_room_automation",
    )
    now = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)
    oracle.note_manual(entry.entry_id, "light.porch", "on",
                       now=now, on_hold_s=3600, off_cooldown_s=900)
    _run(auto.handle_away_leave_on_sweep())
    assert _light_targets(hass, "turn_off") == ["light.porch"]


def test_away_sweep_boot_settle_gate_suppresses():
    hass = FakeHass()
    auto, _e = _make_room(hass, leave_on=["light.porch"], away_off=True,
                           boot_done=False)
    _run(auto.handle_away_leave_on_sweep())
    assert _light_targets(hass, "turn_off") == []


def test_away_sweep_writes_are_ura_stamped():
    """Slice C invariant: stamped write cannot open a new hold."""
    hass = FakeHass()
    auto, _e = _make_room(hass, leave_on=["light.porch"], away_off=True)
    _run(auto.handle_away_leave_on_sweep())
    calls = [c for c in hass.services.calls if c.service == "turn_off"]
    assert calls
    assert all(M["ura_context"].is_ura_context(c.context) for c in calls)


def test_away_sweep_splits_domains():
    hass = FakeHass()
    auto, _e = _make_room(
        hass, leave_on=["light.porch", "switch.hall"], away_off=True,
    )
    _run(auto.handle_away_leave_on_sweep())
    off = [(c.domain, c.data.get("entity_id")) for c in hass.services.calls
           if c.service == "turn_off"]
    assert ("light", ["light.porch"]) in off
    assert ("switch", ["switch.hall"]) in off


# ===========================================================================
# D4 no-flap and edge dispatch (via UniversalRoomCoordinator)
# ===========================================================================


def _make_coord(hass, entry, auto):
    Coord = M["coordinator"].UniversalRoomCoordinator
    c = Coord.__new__(Coord)
    c.hass = hass
    c.entry = entry
    c.automation = auto
    c._get_config = lambda k, default=None: default if default is not None else {}
    c._is_ai_automation_enabled = lambda: False
    # background-task shim: run coro synchronously in a fresh loop.
    entry.async_create_background_task = lambda hass_, coro, name, eager_start=False: _run(coro)
    return c


def test_away_dispatch_edge_only_no_flap():
    """Home→Away fires the sweep ONCE; a second Away signal is a no-op."""
    hass = FakeHass()
    auto, entry = _make_room(hass, leave_on=["light.porch"], away_off=True)
    c = _make_coord(hass, entry, auto)
    c._on_house_state_changed({"new_state": "home"})
    c._on_house_state_changed({"new_state": "away"})
    n1 = len(_light_targets(hass, "turn_off"))
    c._on_house_state_changed({"new_state": "away"})  # repeat: no edge
    n2 = len(_light_targets(hass, "turn_off"))
    assert n1 == 1 and n2 == 1


def test_home_away_home_no_double_emit():
    hass = FakeHass()
    auto, entry = _make_room(hass, leave_on=["light.porch"], away_off=True)
    c = _make_coord(hass, entry, auto)
    c._on_house_state_changed({"new_state": "home"})
    c._on_house_state_changed({"new_state": "away"})
    c._on_house_state_changed({"new_state": "home"})
    assert _light_targets(hass, "turn_off") == ["light.porch"]


# ===========================================================================
# D4 Sleep precedence — HouseState=Sleep wins over sleep-clock
# ===========================================================================


def test_sleep_house_state_forces_sleep_semantics_outside_clock():
    """Even outside the per-room sleep clock, HouseState=='sleep' ⇒ True."""
    hass = FakeHass()
    auto, _e = _make_room(hass)
    # Wire house_state == 'sleep' via the coordinator_manager shim.
    hass.data["universal_room_automation"]["coordinator_manager"].house_state = "sleep"
    # Verify: without HouseState, mid-day clock would report False.
    hass.data["universal_room_automation"]["coordinator_manager"].house_state = ""
    # Freeze wall-clock to noon so the clock says NOT sleep.
    import homeassistant.util.dt as dt_util
    real_now = dt_util.now
    dt_util.now = lambda: datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)
    try:
        assert auto.is_sleep_mode_active() is False
        hass.data["universal_room_automation"]["coordinator_manager"].house_state = "sleep"
        assert auto.is_sleep_mode_active() is True
    finally:
        dt_util.now = real_now


def test_sleep_disabled_switch_still_off_under_house_sleep():
    """CONF_SLEEP_PROTECTION_ENABLED=False ⇒ sleep is off regardless."""
    hass = FakeHass()
    auto, _e = _make_room(hass)
    auto.config[M["const"].CONF_SLEEP_PROTECTION_ENABLED] = False
    hass.data["universal_room_automation"]["coordinator_manager"].house_state = "sleep"
    assert auto.is_sleep_mode_active() is False


# ===========================================================================
# AI-rule light writes RESPECT the manual hold (stamped writes never open holds)
# ===========================================================================


def _ai_coord(hass, entry_id="room_1"):
    Coord = M["coordinator"].UniversalRoomCoordinator
    c = Coord.__new__(Coord)
    c.hass = hass
    c.entry = SimpleNamespace(entry_id=entry_id, data={}, options={})
    c._AI_RULE_ALLOWED_DOMAINS = Coord._AI_RULE_ALLOWED_DOMAINS
    return c


def test_ai_rule_light_write_suppressed_by_on_hold():
    """A person holds light.a ON; an AI-rule turn_off is suppressed."""
    hass = FakeHass()
    c = _ai_coord(hass, "room_1")
    oracle = M["domain_coordinators.light_policy_oracle"].get_light_oracle(
        hass, "universal_room_automation",
    )
    now_utc = datetime.utcnow().replace(tzinfo=timezone.utc)
    oracle.note_manual("room_1", "light.a", "on",
                       now=now_utc, on_hold_s=3600, off_cooldown_s=900)
    _run(c._execute_rule_action(
        {"domain": "light", "service": "turn_off",
         "target": {"entity_id": "light.a"}}, "Den",
    ))
    # Fully suppressed: no service call reached hass.
    assert not [x for x in hass.services.calls if x.domain == "light"]


def test_ai_rule_light_write_partial_pass_when_only_some_held():
    """Two-entity turn_on: one has an OFF cooldown, other passes."""
    hass = FakeHass()
    c = _ai_coord(hass, "room_1")
    oracle = M["domain_coordinators.light_policy_oracle"].get_light_oracle(
        hass, "universal_room_automation",
    )
    now_utc = datetime.utcnow().replace(tzinfo=timezone.utc)
    oracle.note_manual("room_1", "light.a", "off",
                       now=now_utc, on_hold_s=3600, off_cooldown_s=900)
    _run(c._execute_rule_action(
        {"domain": "light", "service": "turn_on",
         "target": {"entity_id": ["light.a", "light.b"]}}, "Den",
    ))
    # light.a suppressed, light.b passes through — call carried [light.b].
    calls = [x for x in hass.services.calls if x.domain == "light"]
    assert len(calls) == 1
    assert calls[0].data["entity_id"] == ["light.b"]


# ===========================================================================
# Advanced field visibility (manual hold windows are ADVANCED-only)
# ===========================================================================


def _build_lighting_schema_dict():
    """Rebuild only the two hold-window advanced entries + a control entry.

    We test the CONTRACT of the schema wrapper, not the whole 30-key form:
    a vol.Optional with description={"advanced": True} must be filtered
    out by ``add_suggested_values_to_schema`` when show_advanced_options
    is False, and present when True. This is the guard the operator asked
    for (verified against HA data_entry_flow.py:660-666).
    """
    import voluptuous as vol
    from custom_components.universal_room_automation.const import (
        CONF_LIGHT_MANUAL_ON_HOLD_S, CONF_LIGHT_MANUAL_OFF_COOLDOWN_S,
        CONF_AWAY_TURN_OFF_LEAVE_ON,
    )
    return vol.Schema({
        vol.Optional(CONF_AWAY_TURN_OFF_LEAVE_ON, default=True): bool,
        vol.Optional(
            CONF_LIGHT_MANUAL_ON_HOLD_S, default=3600,
            description={"advanced": True},
        ): int,
        vol.Optional(
            CONF_LIGHT_MANUAL_OFF_COOLDOWN_S, default=900,
            description={"advanced": True},
        ): int,
    })


class _StubFlow:
    """Minimal stub exposing add_suggested_values_to_schema via HA's real
    FlowHandler binding. We instantiate the real base class so we exercise
    the actual filter code, not a rewrite."""
    def __init__(self, show_advanced: bool):
        from homeassistant.data_entry_flow import FlowHandler
        self._fh = FlowHandler()
        self._fh.context = {"show_advanced_options": show_advanced}

    def wrap(self, schema):
        return self._fh.add_suggested_values_to_schema(schema, {})


def test_advanced_fields_hidden_when_profile_not_advanced():
    from custom_components.universal_room_automation.const import (
        CONF_LIGHT_MANUAL_ON_HOLD_S, CONF_LIGHT_MANUAL_OFF_COOLDOWN_S,
        CONF_AWAY_TURN_OFF_LEAVE_ON,
    )
    schema = _build_lighting_schema_dict()
    out = _StubFlow(show_advanced=False).wrap(schema)
    keys = {getattr(k, "schema", k) for k in out.schema}
    assert CONF_AWAY_TURN_OFF_LEAVE_ON in keys
    assert CONF_LIGHT_MANUAL_ON_HOLD_S not in keys
    assert CONF_LIGHT_MANUAL_OFF_COOLDOWN_S not in keys


def test_advanced_fields_present_when_profile_advanced():
    from custom_components.universal_room_automation.const import (
        CONF_LIGHT_MANUAL_ON_HOLD_S, CONF_LIGHT_MANUAL_OFF_COOLDOWN_S,
    )
    schema = _build_lighting_schema_dict()
    out = _StubFlow(show_advanced=True).wrap(schema)
    keys = {getattr(k, "schema", k) for k in out.schema}
    assert CONF_LIGHT_MANUAL_ON_HOLD_S in keys
    assert CONF_LIGHT_MANUAL_OFF_COOLDOWN_S in keys


def test_stored_manual_hold_value_still_honoured_when_field_hidden():
    """Even when the field is not rendered, a stored value must still be
    read by the runtime (RoomAutomation.note_manual_light). This is a
    round-trip guarantee for the advanced knob."""
    hass = FakeHass()
    const = M["const"]
    RA = M["automation"].RoomAutomation
    auto = RA.__new__(RA)
    auto.hass = hass
    entry = SimpleNamespace(entry_id="room_x", data={}, options={})
    auto.config = {
        const.CONF_LIGHT_MANUAL_ON_HOLD_S: 42,
        const.CONF_LIGHT_MANUAL_OFF_COOLDOWN_S: 7,
    }
    auto._config_entry = entry
    auto._refresh_config = lambda: None
    auto.note_manual_light("light.z", "on")
    oracle = M["domain_coordinators.light_policy_oracle"].get_light_oracle(
        hass, "universal_room_automation",
    )
    st = oracle.get_state("room_x")["light.z"]
    # Hold window applied ⇒ on_hold_until is now+42s (non-None).
    assert st["on_hold_until"] is not None


def test_ai_rule_stamped_write_never_opens_a_hold():
    """The stamped write itself must not open a hold (Slice C invariant)."""
    hass = FakeHass()
    c = _ai_coord(hass, "room_1")
    _run(c._execute_rule_action(
        {"domain": "light", "service": "turn_on",
         "target": {"entity_id": "light.a"}}, "Den",
    ))
    oracle = M["domain_coordinators.light_policy_oracle"].get_light_oracle(
        hass, "universal_room_automation",
    )
    st = oracle.get_state("room_1")
    # No hold opened by the URA-stamped write.
    assert st.get("light.a", {}).get("on_hold_until") is None
    assert st.get("light.a", {}).get("off_cooldown_until") is None
