"""LIGHT-TRANSITION-COVERAGE-1 — every ambient ``light.*`` write URA issues
carries the room's configured fade; alert / warning lights stay instant;
``switch.*`` relays never get a ``transition`` key.

Sites anchored (each neuter -> a named test below goes RED):
- switch.py RoomLightsSwitch.async_turn_on regular-light call
- switch.py RoomLightsSwitch.async_turn_on night-light call
- switch.py RoomLightsSwitch.async_turn_off light call
- automation.py handle_away_leave_on_sweep light turn_off
- automation.py _shared_space_turn_off_all light turn_off
- actuator_reconciler.py _reconcile_one dispatch (on + off)
- lighting/resolver.py light_transition (ON / OFF knob pick)

Oracles are hardcoded literals (7 / 9 configured; 1 / 3 defaults), not the
imported constants. Reuses the scoped real-module harness from
test_lighting_slice_c_manual_hold (its module fixture restores sys.modules).
"""

from __future__ import annotations

from test_lighting_slice_c_manual_hold import (  # noqa: F401 — fixture import
    M,
    _real_modules,
    _run,
    make_room,
)

ON_S = 7
OFF_S = 9


def _c():
    return M["const"]


def _cfg_fade():
    c = _c()
    return {c.CONF_LIGHT_TRANSITION_ON: ON_S, c.CONF_LIGHT_TRANSITION_OFF: OFF_S}


def _switch(room):
    S = M["switch"].RoomLightsSwitch
    sw = S.__new__(S)
    sw.coordinator = room.coord
    sw.hass = room.hass
    sw.async_write_ha_state = lambda: None
    return sw


def _calls(room, domain, service):
    return [c for c in room.hass.services.calls
            if c.domain == domain and c.service == service]


def _by_entity(room, domain, service, eid):
    out = []
    for c in _calls(room, domain, service):
        ids = c.data.get("entity_id")
        ids = [ids] if isinstance(ids, str) else list(ids or [])
        if eid in ids:
            out.append(c)
    assert out, f"no {domain}.{service} for {eid}: {room.hass.services.calls}"
    return out


# ---------------------------------------------------------------------------
# resolver helper
# ---------------------------------------------------------------------------


def test_helper_picks_on_and_off_knobs_and_defaults():
    lt = M["lighting.resolver"].light_transition
    assert lt(_cfg_fade(), on=True) == 7
    assert lt(_cfg_fade(), on=False) == 9
    assert lt({}, on=True) == 1
    assert lt({}, on=False) == 3


# ---------------------------------------------------------------------------
# Room lights switch (manual)
# ---------------------------------------------------------------------------


def test_switch_on_regular_lights_fade_and_relay_does_not():
    c = _c()
    room = make_room({**_cfg_fade(), c.CONF_LIGHTS: ["light.a", "switch.r"]})
    room.auto.is_dark = lambda _lux: True
    _run(_switch(room).async_turn_on())
    (call,) = _by_entity(room, "light", "turn_on", "light.a")
    assert call.data.get("transition") == 7
    for sc in _calls(room, "switch", "turn_on"):
        assert "transition" not in sc.data


def test_switch_on_night_lights_fade():
    c = _c()
    room = make_room(
        {**_cfg_fade(), c.CONF_LIGHTS: ["light.a"], c.CONF_NIGHT_LIGHTS: ["light.n"]},
        sleep=True,
    )
    room.auto.is_dark = lambda _lux: True
    _run(_switch(room).async_turn_on())
    (call,) = _by_entity(room, "light", "turn_on", "light.n")
    assert call.data.get("transition") == 7


def test_switch_off_fades_and_relay_does_not():
    c = _c()
    room = make_room({**_cfg_fade(), c.CONF_LIGHTS: ["light.a", "switch.r"]})
    _run(_switch(room).async_turn_off())
    (call,) = _by_entity(room, "light", "turn_off", "light.a")
    assert call.data.get("transition") == 9
    for sc in _calls(room, "switch", "turn_off"):
        assert "transition" not in sc.data


# ---------------------------------------------------------------------------
# automation.py sweeps
# ---------------------------------------------------------------------------


def test_away_leave_on_sweep_fades_lights_not_relays():
    c = _c()
    cfg = {**_cfg_fade(), c.CONF_LIGHTS_LEAVE_ON_WHEN_EMPTY: ["light.a", "switch.r"]}
    room = make_room(cfg, occupied=False)
    room.auto._away_boot_settle_done = lambda: True
    _run(room.auto.handle_away_leave_on_sweep())
    (call,) = _by_entity(room, "light", "turn_off", "light.a")
    assert call.data.get("transition") == 9
    (sc,) = _by_entity(room, "switch", "turn_off", "switch.r")
    assert "transition" not in sc.data


def test_shared_space_turn_off_all_fades_lights_not_relays():
    c = _c()
    room = make_room({**_cfg_fade(), c.CONF_LIGHTS: ["light.a", "switch.r"]},
                     occupied=False)
    _run(room.auto._shared_space_turn_off_all())
    (call,) = _by_entity(room, "light", "turn_off", "light.a")
    assert call.data.get("transition") == 9
    (sc,) = _by_entity(room, "switch", "turn_off", "switch.r")
    assert "transition" not in sc.data


def test_shared_space_off_default_fade_when_knob_unset():
    room = make_room(occupied=False)
    _run(room.auto._shared_space_turn_off_all())
    (call,) = _by_entity(room, "light", "turn_off", "light.a")
    assert call.data.get("transition") == 3


# ---------------------------------------------------------------------------
# Reconciler dispatch
# ---------------------------------------------------------------------------


def test_reconciler_on_dispatch_fades():
    c = _c()
    room = make_room({**_cfg_fade(), c.CONF_LIGHTS: ["light.a", "switch.r"]},
                     occupied=True)
    room.auto.is_dark = lambda _lux: True
    room.hass.set_state("light.a", "off")
    room.hass.set_state("switch.r", "off")
    room.hass.services.calls.clear()
    _run(room.rec._reconcile_one("light.a"))
    _run(room.rec._reconcile_one("switch.r"))
    (call,) = _by_entity(room, "light", "turn_on", "light.a")
    assert call.data.get("transition") == 7
    (sc,) = _by_entity(room, "switch", "turn_on", "switch.r")
    assert "transition" not in sc.data


def test_reconciler_off_dispatch_fades():
    c = _c()
    room = make_room({**_cfg_fade(), c.CONF_LIGHTS: ["light.a"]}, occupied=False)
    room.hass.set_state("light.a", "on")
    room.hass.services.calls.clear()
    _run(room.rec._reconcile_one("light.a"))
    (call,) = _by_entity(room, "light", "turn_off", "light.a")
    assert call.data.get("transition") == 9


def test_reconciler_already_on_night_light_still_noop():
    """No-op gate unchanged: transition is added at dispatch, not into
    params, so a BASIC night light already ON at sleep is not re-sent."""
    c = _c()
    room = make_room({**_cfg_fade(), c.CONF_LIGHTS: [], c.CONF_NIGHT_LIGHTS: ["light.n"]},
                     occupied=True, sleep=True)
    room.hass.set_state("light.n", "on")
    room.hass.services.calls.clear()
    _run(room.rec._reconcile_one("light.n"))
    assert room.hass.services.calls == []


# ---------------------------------------------------------------------------
# Intentionally instant
# ---------------------------------------------------------------------------


def test_alert_lights_stay_instant():
    c = _c()
    room = make_room({**_cfg_fade(), c.CONF_ALERT_LIGHTS: ["light.x"]})
    room.auto._alert_lights_active = False
    room.auto._alert_light_original_states = {}
    _run(room.auto.trigger_alert_lights("warning"))
    (call,) = _by_entity(room, "light", "turn_on", "light.x")
    assert "transition" not in call.data
