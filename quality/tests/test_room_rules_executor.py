"""AI-ROOM-RULES-TRUST-REPAIR-1 D2 / D4 / D5 / D8: the ONE room-rule executor.

Every test drives the REAL ``UniversalRoomCoordinator`` (``_run_room_rules``,
the signal handlers, the person room-change listener, the occupancy-edge path
in ``_async_update_data``) against a recording services fake. No source greps.
Oracles are hand-written (expected service calls / skip names), never re-run
production code.
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

import pytest

from _room_rules_rig import Rig, automation_rule, light_rule, run, st
from custom_components.universal_room_automation import const as C
from custom_components.universal_room_automation.const import DOMAIN


def _m(name):
    """The module the production code resolves NOW (another file may have
    re-imported the package after this file was collected)."""
    import importlib
    return importlib.import_module(f"custom_components.universal_room_automation.{name}")


def _calls(rig):
    return [(c.domain, c.service, c.target) for c in rig.services.rule_calls()]


def _outcomes(rig):
    return [e["attrs"]["outcome"] for e in rig.episodes()]


def _lamp_states():
    return {"light.exercise_lamp": st("off", friendly_name="Exercise Lamp"),
            "automation.exercise_music": st("on", friendly_name="Exercise music")}


# ---------------------------------------------------------------------------
# D4: one record, one executor, explicit gates
# ---------------------------------------------------------------------------


def test_rules_kill_switch_default_is_unified():
    assert C.ROOM_RULES_UNIFIED_EXECUTOR is True


def test_rules_automation_goes_through_gate():
    """A legacy chain AND an automation rule both reach HA through
    _execute_rule_action (URA context, skip_condition carried)."""
    rig = Rig(rules=[automation_rule()], chains={"exit": "automation.exercise_music"},
              states=_lamp_states())
    seen = []
    real = rig.c._execute_rule_action

    async def _spy(action, room, context=None):
        seen.append((action["domain"], action["service"]))
        return await real(action, room, context=context)

    rig.c._execute_rule_action = _spy
    run(rig.c._run_room_rules(["enter"]))
    run(rig.c._run_room_rules(["exit"]))
    assert seen == [("automation", "trigger"), ("automation", "trigger")]
    calls = rig.services.rule_calls()
    assert [c.data for c in calls] == [
        {"entity_id": "automation.exercise_music", "skip_condition": False},
        {"entity_id": "automation.exercise_music", "skip_condition": False},
    ]


def test_legacy_chain_dict_becomes_automation_rules():
    from custom_components.universal_room_automation.rule_compiler import adapt_rules
    recs = adapt_rules([light_rule()], {"enter": "automation.x", "exit": ""})
    assert [r["rule_id"] for r in recs] == ["chain_enter", "r1"]
    chain = recs[0]
    assert chain["source"] == "automation" and chain["trigger_type"] == "enter"
    assert chain["actions"] == [{"domain": "automation", "service": "trigger",
                                 "target": {"entity_id": "automation.x"},
                                 "data": {"skip_condition": False}}]
    assert chain["needs_parse"] is False


def test_rules_automation_off_skipped():
    states = _lamp_states()
    states["automation.exercise_music"] = st("off")
    rig = Rig(rules=[automation_rule()], states=states)
    run(rig.c._run_room_rules(["enter"]))
    run(rig.drain())
    assert _calls(rig) == []
    assert _outcomes(rig) == ["automation_off"]


def test_rules_automation_run_first():
    rig = Rig(rules=[light_rule(), automation_rule()], states=_lamp_states())
    run(rig.c._run_room_rules(["enter"]))
    assert [c[0] for c in _calls(rig)] == ["automation", "light"]


def test_rules_enter_skipped_with_switch_off():
    rig = Rig(rules=[light_rule()], states=_lamp_states(), switches={"ai_automation": False})
    run(rig.c._run_room_rules(["enter"]))
    run(rig.drain())
    assert _calls(rig) == []
    assert _outcomes(rig) == ["switch_off"]


def test_rules_enter_skipped_with_manual_mode():
    rig = Rig(rules=[light_rule()], states=_lamp_states(), switches={"manual_mode": True})
    run(rig.c._run_room_rules(["enter"]))
    run(rig.drain())
    assert _calls(rig) == []
    assert _outcomes(rig) == ["manual_mode"]


def test_rules_enter_fires_with_switch_on():
    rig = Rig(rules=[light_rule(data={"brightness_pct": 40})], states=_lamp_states())
    run(rig.c._run_room_rules(["enter"]))
    run(rig.drain())
    assert _calls(rig) == [("light", "turn_on", "light.exercise_lamp")]
    assert rig.services.rule_calls()[0].data == {"brightness_pct": 40, "entity_id": ["light.exercise_lamp"]}
    assert _outcomes(rig) == ["fired"]


def test_rules_safety_fires_with_switch_off():
    rig = Rig(rules=[light_rule(trigger="safety_hazard")], states=_lamp_states(),
              switches={"ai_automation": False, "automation": False})
    rig.c._on_safety_hazard("smoke")
    run(rig.drain())
    assert _calls(rig) == [("light", "turn_on", "light.exercise_lamp")]


def test_rules_security_fires_with_manual_mode():
    rig = Rig(rules=[light_rule(trigger="security_event")], states=_lamp_states(),
              switches={"manual_mode": True})
    rig.c._on_security_event("intrusion")
    run(rig.drain())
    assert _calls(rig) == [("light", "turn_on", "light.exercise_lamp")]


def test_house_state_rule_switch_off():
    rig = Rig(rules=[light_rule(trigger="house_state_sleep", service="turn_off")],
              states=_lamp_states(), switches={"ai_automation": False})
    rig.c._on_house_state_changed({"new_state": "sleep"})
    run(rig.drain())
    assert _calls(rig) == []
    assert _outcomes(rig) == ["switch_off"]


def test_house_state_rule_fires_with_master_automation_off():
    """System-level triggers keep their old matrix: the master automation
    switch does not gate them; only Room Rules + Manual Mode do."""
    rig = Rig(rules=[light_rule(trigger="house_state_sleep", service="turn_off")],
              states=_lamp_states(), switches={"automation": False})
    rig.c._on_house_state_changed({"new_state": "sleep"})
    run(rig.drain())
    assert _calls(rig) == [("light", "turn_off", "light.exercise_lamp")]


def test_energy_rule_fires_and_respects_switch():
    rig = Rig(rules=[light_rule(trigger="energy_constraint", service="turn_off")],
              states=_lamp_states())
    rig.c._on_energy_constraint("shed")
    run(rig.drain())
    assert _calls(rig) == [("light", "turn_off", "light.exercise_lamp")]
    rig.switches["ai_automation"] = False
    rig.c._on_energy_constraint("shed")
    run(rig.drain())
    assert len(_calls(rig)) == 1
    assert _outcomes(rig) == ["fired", "switch_off"]


def test_rules_light_respects_manual_hold():
    from custom_components.universal_room_automation.domain_coordinators.light_policy_oracle import (
        get_light_oracle,
    )
    rig = Rig(rules=[light_rule(trigger="exit", service="turn_off")], states=_lamp_states())
    oracle = get_light_oracle(rig.hass, DOMAIN)
    oracle.note_manual("EX1", "light.exercise_lamp", "on", now=datetime.now().astimezone(),
                       on_hold_s=3600, off_cooldown_s=0)
    run(rig.c._run_room_rules(["exit"]))
    run(rig.drain())
    assert _calls(rig) == []
    assert _outcomes(rig) == ["gate_blocked:manual_hold"]


def test_rules_cover_security_owned_blocked():
    rule = light_rule(service="open_cover", entity="cover.garage_door")
    states = {"cover.garage_door": st("closed", device_class="garage")}
    rig = Rig(rules=[rule], states=states)
    run(rig.c._run_room_rules(["enter"]))
    run(rig.drain())
    assert _calls(rig) == []
    assert _outcomes(rig) == ["gate_blocked:security_cover"]


def test_rules_climate_blocked():
    rule = light_rule(service="set_temperature", entity="climate.zone_1")
    rig = Rig(rules=[rule], states={"climate.zone_1": st("cool")})
    run(rig.c._run_room_rules(["enter"]))
    run(rig.drain())
    assert _calls(rig) == []
    assert _outcomes(rig) == ["gate_blocked:climate"]


def test_rules_allowlist_blocked():
    rule = light_rule(service="restart", entity="homeassistant.x")
    rig = Rig(rules=[rule], states={})
    run(rig.c._run_room_rules(["enter"]))
    run(rig.drain())
    assert _calls(rig) == []
    assert _outcomes(rig) == ["gate_blocked:allowlist"]


def test_rules_conflict_sensor_clears_on_clean_evaluation():
    from custom_components.universal_room_automation.binary_sensor import (
        AutomationConflictBinarySensor,
    )
    rig = Rig(rules=[light_rule(), light_rule(rule_id="r2", trigger="lux_dark",
                                              entity="light.other")],
              states={**_lamp_states(), "light.other": st("off")})
    sensor = AutomationConflictBinarySensor.__new__(AutomationConflictBinarySensor)
    sensor.coordinator = rig.c
    run(rig.c._run_room_rules(["enter"]))          # lamp is a built-in enter target
    assert sensor.is_on is True
    run(rig.c._run_room_rules(["lux_dark"]))       # light.other: no conflict
    assert sensor.is_on is False


def test_unmatched_trigger_writes_no_decision():
    rig = Rig(rules=[light_rule(trigger="exit")], states=_lamp_states())
    run(rig.c._run_room_rules(["enter"]))
    run(rig.drain())
    assert _calls(rig) == [] and rig.episodes() == []


def test_disabled_rule_not_matched():
    rig = Rig(rules=[light_rule(enabled=False)], states=_lamp_states())
    run(rig.c._run_room_rules(["enter"]))
    run(rig.drain())
    assert _calls(rig) == [] and rig.episodes() == []


def test_kill_switch_false_runs_legacy_paths_through_gate():
    rig = Rig(rules=[light_rule()], chains={"enter": "automation.exercise_music"},
              states=_lamp_states())
    with patch.object(_m("const"), "ROOM_RULES_UNIFIED_EXECUTOR", False):
        run(rig.c._run_room_rules(["enter"]))
    assert _calls(rig) == [("automation", "trigger", "automation.exercise_music"),
                           ("light", "turn_on", "light.exercise_lamp")]
    # the legacy chain went through the gate: skip_condition False carried
    assert rig.services.rule_calls()[0].data == {
        "entity_id": "automation.exercise_music", "skip_condition": False}
    rig2 = Rig(rules=[light_rule()], states=_lamp_states(), switches={"ai_automation": False})
    with patch.object(_m("const"), "ROOM_RULES_UNIFIED_EXECUTOR", False):
        run(rig2.c._run_room_rules(["enter"]))
    assert _calls(rig2) == []


def test_occupancy_edge_path_calls_run_room_rules():
    """Wire-in anchor: the room-trigger site in _async_update_data reaches
    _run_room_rules on an enter edge."""
    rig = Rig(rules=[light_rule()], states=_lamp_states(),
              extra_options={"override_occupied": True})
    rig.switches["override_occupied"] = True
    rig.c._last_occupied_state = False
    seen = []

    async def _spy(triggers, event=None):
        seen.append(list(triggers))

    rig.c._run_room_rules = _spy
    run(rig.c._async_update_data())
    assert ["enter"] in seen


# ---------------------------------------------------------------------------
# D2: conditions
# ---------------------------------------------------------------------------


def test_rule_condition_after_dark_false_skips():
    rig = Rig(rules=[light_rule(conditions=[{"type": "after_dark"}])], states=_lamp_states())
    rig.c.data = {C.STATE_ILLUMINANCE: 180}
    run(rig.c._run_room_rules(["enter"]))
    run(rig.drain())
    assert _calls(rig) == []
    ep = rig.episodes()[0]["attrs"]
    assert ep["outcome"] == "condition_false"
    assert ep["conditions"] == {"after_dark": False}
    rig.c.data = {C.STATE_ILLUMINANCE: 5}
    run(rig.c._run_room_rules(["enter"]))
    assert _calls(rig) == [("light", "turn_on", "light.exercise_lamp")]


def test_rule_condition_time_window_crosses_midnight():
    from custom_components.universal_room_automation.rule_compiler import in_time_window
    from datetime import time as t
    assert in_time_window(t(22, 0), t(6, 0), t(23, 30)) is True
    assert in_time_window(t(22, 0), t(6, 0), t(5, 59)) is True
    assert in_time_window(t(22, 0), t(6, 0), t(6, 0)) is False
    assert in_time_window(t(22, 0), t(6, 0), t(12, 0)) is False
    assert in_time_window(t(7, 0), t(9, 0), t(8, 0)) is True
    rule = light_rule(conditions=[{"type": "time_window", "start": "22:00", "end": "06:00"}])
    rig = Rig(rules=[rule], states=_lamp_states())
    dt_util = rig.co.dt_util     # the module object the coordinator reads
    noon = datetime(2026, 11, 20, 12, 0).astimezone()
    with patch.object(dt_util, "now", lambda *a, **k: noon):
        run(rig.c._run_room_rules(["enter"]))
    assert _calls(rig) == []
    night = datetime(2026, 11, 20, 23, 30).astimezone()
    with patch.object(dt_util, "now", lambda *a, **k: night):
        run(rig.c._run_room_rules(["enter"]))
    assert len(_calls(rig)) == 1


class _Presence:
    def __init__(self, hs):
        self.house_state = hs


class _Mgr:
    def __init__(self, hs):
        self.coordinators = {"presence": _Presence(hs)}


def test_rule_condition_house_state():
    rule = light_rule(conditions=[{"type": "house_state_in", "states": ["sleep", "home_night"]}])
    rig = Rig(rules=[rule], states=_lamp_states())
    rig.hass.data[DOMAIN]["coordinator_manager"] = _Mgr("home_day")
    run(rig.c._run_room_rules(["enter"]))
    assert _calls(rig) == []
    rig.hass.data[DOMAIN]["coordinator_manager"] = _Mgr("sleep")
    run(rig.c._run_room_rules(["enter"]))
    assert len(_calls(rig)) == 1


# ---------------------------------------------------------------------------
# D5: person rules fire on the person
# ---------------------------------------------------------------------------


class _Evt:
    def __init__(self, **data):
        self.data = data


def _person_rig(trigger="enter", person="person.oji_udezue"):
    rig = Rig(rules=[light_rule(trigger=trigger, person=person)], states=_lamp_states())
    rig.c._update_signal_subscriptions()
    return rig


def _fire_person(rig, person_id, prev, cur):
    for name, cb in list(rig.bus_listeners):
        if name == "ura_person_location_change":
            cb(_Evt(person_id=person_id, previous_location=prev, current_location=cur))
    run(rig.drain())


def test_rule_person_enter_fires_on_person_event():
    rig = _person_rig()
    assert [n for n, _ in rig.bus_listeners] == ["ura_person_location_change"]
    _fire_person(rig, "Oji Udezue", "Kitchen", "Exercise Room")
    assert _calls(rig) == [("light", "turn_on", "light.exercise_lamp")]
    assert rig.episodes()[0]["attrs"]["person"] == "Oji Udezue"


def test_rule_person_exit_fires_on_person_event():
    rig = _person_rig(trigger="exit")
    _fire_person(rig, "Oji Udezue", "Exercise Room", "Kitchen")
    assert _calls(rig) == [("light", "turn_on", "light.exercise_lamp")]


def test_rule_person_other_person_no_fire():
    rig = _person_rig()
    for name, cb in list(rig.bus_listeners):
        cb(_Evt(person_id="Jaya Udezue", previous_location="Kitchen",
                current_location="Exercise Room"))
    assert rig.tasks == []          # the listener schedules nothing for Jaya
    run(rig.drain())
    assert _calls(rig) == [] and rig.episodes() == []


def test_run_room_rules_person_event_other_person_not_matched():
    """The executor's own person match (second layer, behind the listener)."""
    rig = Rig(rules=[light_rule(person="person.oji_udezue")], states=_lamp_states())
    run(rig.c._run_room_rules(["enter"], event={"kind": "person", "person_id": "Jaya Udezue"}))
    run(rig.drain())
    assert _calls(rig) == [] and rig.episodes() == []
    run(rig.c._run_room_rules(["enter"], event={"kind": "person", "person_id": "Oji Udezue"}))
    assert _calls(rig) == [("light", "turn_on", "light.exercise_lamp")]


def test_rule_person_other_room_no_fire():
    rig = _person_rig()
    _fire_person(rig, "Oji Udezue", "Kitchen", "Study A")
    assert _calls(rig) == []


def test_rule_person_enter_not_fired_by_occupancy_edge():
    """The occupancy instant with BLE not yet in the room: the person rule is
    NOT matched by the edge (old code skipped it as person_absent)."""
    rig = Rig(rules=[light_rule(person="person.oji_udezue")], states=_lamp_states())
    run(rig.c._run_room_rules(["enter"]))
    run(rig.drain())
    assert _calls(rig) == [] and rig.episodes() == []


def test_rule_person_event_respects_switch_off():
    rig = _person_rig()
    rig.switches["ai_automation"] = False
    _fire_person(rig, "Oji Udezue", "Kitchen", "Exercise Room")
    assert _calls(rig) == []
    assert _outcomes(rig) == ["switch_off"]


def test_rule_person_event_paused_room_schedules_nothing():
    """Master Automation switch off (paused room): same as the occupancy-edge
    path, the person listener runs no rule."""
    rig = _person_rig()
    rig.switches["automation"] = False
    _fire_person(rig, "Oji Udezue", "Kitchen", "Exercise Room")
    assert _calls(rig) == [] and rig.episodes() == []


def test_person_listener_only_with_person_rule():
    rig = Rig(rules=[light_rule()], states=_lamp_states())
    rig.c._update_signal_subscriptions()
    assert [n for n, _ in rig.bus_listeners] == []


def test_person_scoped_signal_rule_checks_presence():
    """A person-scoped rule on a non-person trigger keeps the
    get_persons_in_room check (slug match)."""
    rule = light_rule(trigger="house_state_sleep", person="person.oji_udezue", service="turn_off")
    rig = Rig(rules=[rule], states=_lamp_states(), persons_in_room=["Jaya Udezue"])
    run(rig.c._run_room_rules(["house_state_sleep"]))
    run(rig.drain())
    assert _calls(rig) == [] and _outcomes(rig) == ["person_absent"]
    rig.persons_in_room = ["Oji Udezue"]
    run(rig.c._run_room_rules(["house_state_sleep"]))
    assert _calls(rig) == [("light", "turn_off", "light.exercise_lamp")]


# ---------------------------------------------------------------------------
# D3: saved rules run without the model
# ---------------------------------------------------------------------------


def test_rules_run_with_model_unavailable():
    from custom_components.universal_room_automation.sensor import AIAutomationStatusSensor
    rig = Rig(rules=[light_rule()], states=_lamp_states())
    rig.services.registered.discard(("ai_task", "generate_data"))
    rig.services.raise_on[("ai_task", "generate_data")] = RuntimeError("locked")
    run(rig.c._run_room_rules(["enter"]))
    assert _calls(rig) == [("light", "turn_on", "light.exercise_lamp")]
    assert not [c for c in rig.services.calls if c.domain == "ai_task"]
    sensor = AIAutomationStatusSensor.__new__(AIAutomationStatusSensor)
    sensor.coordinator = rig.c
    sensor.hass = rig.hass
    assert sensor.native_value == "active"


# ---------------------------------------------------------------------------
# D8: migration and lifecycle
# ---------------------------------------------------------------------------


def test_migration_data_only_rule_is_inert_and_flagged():
    from custom_components.universal_room_automation.sensor import AIAutomationStatusSensor
    rule = light_rule(rule_id="6a932dd2")
    rule.update({"actions": [], "needs_parsing": True})
    rig = Rig(data_rules=[rule], states=_lamp_states())
    run(rig.c._run_room_rules(["enter"]))
    run(rig.drain())
    assert _calls(rig) == [] and rig.episodes() == []
    sensor = AIAutomationStatusSensor.__new__(AIAutomationStatusSensor)
    sensor.coordinator = rig.c
    sensor.hass = rig.hass
    assert sensor.native_value == "needs_parse"
    assert sensor.extra_state_attributes["rules"][0]["status"] == "needs_parse"
    # Even with well-formed actions, a data-only rule never runs.
    rig2 = Rig(data_rules=[light_rule()], states=_lamp_states())
    run(rig2.c._run_room_rules(["enter"]))
    assert _calls(rig2) == []


def test_new_energy_rule_subscribed_after_options_save():
    from custom_components.universal_room_automation.domain_coordinators.signals import (
        SIGNAL_ENERGY_CONSTRAINT,
    )
    rig = Rig(rules=[], states=_lamp_states())
    connected = []

    def _connect(hass, signal, handler):
        connected.append(signal)
        return lambda: None

    with patch.object(rig.co, "async_dispatcher_connect", _connect):
        rig.c._update_signal_subscriptions()
        assert SIGNAL_ENERGY_CONSTRAINT not in connected
        rig.entry.options = {"ai_rules": [light_rule(trigger="energy_constraint")]}
        rig.c._update_signal_subscriptions()   # the options-update listener body
    assert SIGNAL_ENERGY_CONSTRAINT in connected
