"""AI-ROOM-RULES-TRUST-REPAIR-1 D2 / D3 / D8 / §7: the "Room rules" options flow.

Drives the REAL ``UniversalRoomAutomationOptionsFlow`` steps with a stubbed
``ai_task.generate_data`` (recording services fake) and asserts what is
written to ``entry.options`` (``async_create_entry`` data).
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from _room_menu_helpers import make_flow
from _room_rules_rig import FakeServices, light_rule, run, st
from custom_components.universal_room_automation.const import (
    CONF_AI_RULE_DESCRIPTION,
    CONF_AI_RULE_PERSON,
    CONF_AI_RULE_TRIGGER,
    CONF_AI_RULES,
    CONF_AUTOMATION_CHAINS,
    DOMAIN,
)

LAMP_ON = {"domain": "light", "service": "turn_on",
           "target": {"entity_id": "light.exercise_lamp"}, "data": {"brightness_pct": 40}}


def _resp(actions, conditions=None, unsupported=""):
    return {"data": {"actions_json": json.dumps(actions),
                     "conditions_json": json.dumps(conditions or []),
                     "unsupported": unsupported, "summary": "turns on the lamp after dark"}}


class _Reg:
    def __init__(self, switch_eid="switch.exercise_room_ai_automation"):
        self.switch_eid = switch_eid
        self.entities = {}

    def async_get_entity_id(self, domain, platform, unique_id):
        if (domain, platform, unique_id) == ("switch", DOMAIN, "EX1_ai_automation"):
            return self.switch_eid
        return None


def _flow(options=None, data=None, response=None, switch_state="on", cm_options=None):
    base = {"room_name": "Exercise Room", "lights": ["light.exercise_lamp"]}
    base.update(data or {})
    flow = make_flow(data=base, options=options)
    flow._config_entry.entry_id = "EX1"
    services = FakeServices()
    services.response = response
    flow.hass.services = services
    states = {
        "light.exercise_lamp": st("off", friendly_name="Exercise Lamp"),
        "ai_task.claude_ai_task": st("unknown"),
        "automation.party": st("on", friendly_name="Party"),
        "person.oji_udezue": st("home", friendly_name="Oji"),
        "switch.exercise_room_ai_automation": st(switch_state),
    }
    flow.hass.states.get = lambda eid: states.get(eid)
    flow.hass.data = {DOMAIN: {}}
    if cm_options is not None:
        cm = MagicMock()
        cm.data = {"entry_type": "coordinator_manager"}
        cm.options = cm_options
        flow.hass.config_entries.async_entries = lambda domain=None: [cm]
    return flow, services, states


def _run_step(flow, step, user_input=None):
    from homeassistant.helpers import entity_registry as er
    with patch.object(er, "async_get", lambda h: _Reg()):
        return run(getattr(flow, f"async_step_{step}")(user_input))


DESCRIBE = {CONF_AI_RULE_DESCRIPTION: "After dark turn on the lamp at 40%",
            CONF_AI_RULE_TRIGGER: "enter", CONF_AI_RULE_PERSON: "person.oji_udezue"}


def test_room_rules_menu_has_three_plain_actions():
    flow, _s, _st = _flow()
    res = _run_step(flow, "room_rules")
    assert res["menu_options"] == ["room_rule_describe", "room_rule_automation", "room_rule_list"]


def test_rule_describe_preview_then_save_writes_options():
    flow, services, _ = _flow(response=_resp([LAMP_ON], [{"type": "after_dark"}]))
    res = _run_step(flow, "room_rule_describe", DESCRIBE)
    assert res["step_id"] == "room_rule_confirm"
    assert res["description_placeholders"]["preview"] == (
        "When Oji enters Exercise Room, after dark: turn on Exercise Lamp at 40 percent."
    )
    saved = _run_step(flow, "room_rule_confirm", {"change_wording": False})
    assert saved["type"] == "create_entry"
    rules = saved["data"][CONF_AI_RULES]
    assert len(rules) == 1
    r = rules[0]
    assert r["source"] == "described" and r["trigger_type"] == "enter"
    assert r["person"] == "person.oji_udezue"
    assert r["actions"] == [LAMP_ON] and r["conditions"] == [{"type": "after_dark"}]
    assert r["summary"] == "turns on the lamp after dark"
    assert saved["data"][CONF_AUTOMATION_CHAINS] == {}
    # the model call named the configured entity
    assert services.calls[0].data["entity_id"] == "ai_task.claude_ai_task"


def test_rule_form_refuses_unparsed():
    flow, _s, _ = _flow(response={"data": {"actions_json": "garbage"}})
    res = _run_step(flow, "room_rule_describe", DESCRIBE)
    assert res["type"] == "form" and res["step_id"] == "room_rule_describe"
    assert res["errors"] == {"base": "rule_not_understood"}


def test_rule_form_refuses_zero_actions():
    flow, _s, _ = _flow(response=_resp([]))
    res = _run_step(flow, "room_rule_describe", DESCRIBE)
    assert res["errors"] == {"base": "rule_not_understood"}


def test_rule_form_refuses_unsupported_and_names_it():
    flow, _s, _ = _flow(response=_resp([LAMP_ON], unsupported="only when it is raining"))
    res = _run_step(flow, "room_rule_describe", DESCRIBE)
    assert res["errors"] == {"base": "rule_unsupported"}
    assert "only when it is raining" in res["description_placeholders"]["problem"]


def test_rule_compiler_ai_task_error_is_model_unavailable_in_form():
    from homeassistant.exceptions import HomeAssistantError
    flow, services, _ = _flow()
    services.raise_on[("ai_task", "generate_data")] = HomeAssistantError("usage limit")
    res = _run_step(flow, "room_rule_describe", DESCRIBE)
    assert res["errors"] == {"base": "rule_model_unavailable"}
    assert res["description_placeholders"]["model"] == "ai_task.claude_ai_task"
    assert "ai_task.claude_ai_task" in res["description_placeholders"]["problem"]
    # typed text kept in the re-shown form
    keys = {str(k): k for k in res["data_schema"].schema}
    assert keys[CONF_AI_RULE_DESCRIPTION].default() == DESCRIBE[CONF_AI_RULE_DESCRIPTION]
    # no rule written
    assert getattr(flow, "_rule_pending", None) is None


def test_rule_model_knob_selects_entity():
    flow, services, _ = _flow(response=_resp([LAMP_ON]),
                              cm_options={"room_rules_ai_task_entity": "ai_task.sonnet_rules"})
    flow.hass.states.get = (lambda base: (lambda eid: {**base, "ai_task.sonnet_rules": st("unknown")}.get(eid)))(
        {"light.exercise_lamp": st("off", friendly_name="Exercise Lamp")})
    res = _run_step(flow, "room_rule_describe", DESCRIBE)
    assert res["step_id"] == "room_rule_confirm"
    assert services.calls[0].data["entity_id"] == "ai_task.sonnet_rules"


def test_rule_save_turns_switch_on_when_checked():
    flow, services, _ = _flow(response=_resp([LAMP_ON]), switch_state="off")
    res = _run_step(flow, "room_rule_describe", DESCRIBE)
    keys = [str(k) for k in res["data_schema"].schema]
    assert keys == ["turn_on_room_rules", "change_wording"]
    assert res["description_placeholders"]["switch_note"] == "Room rules are off in this room."
    saved = _run_step(flow, "room_rule_confirm", {"turn_on_room_rules": True, "change_wording": False})
    assert saved["type"] == "create_entry"
    on = [c for c in services.calls if (c.domain, c.service) == ("switch", "turn_on")]
    assert [c.data for c in on] == [{"entity_id": "switch.exercise_room_ai_automation"}]


def test_rule_save_leaves_switch_off_when_unchecked():
    flow, services, _ = _flow(response=_resp([LAMP_ON]), switch_state="off")
    _run_step(flow, "room_rule_describe", DESCRIBE)
    _run_step(flow, "room_rule_confirm", {"turn_on_room_rules": False, "change_wording": False})
    assert not [c for c in services.calls if c.domain == "switch"]


def test_rule_confirm_switch_on_has_no_checkbox():
    flow, _s, _ = _flow(response=_resp([LAMP_ON]), switch_state="on")
    res = _run_step(flow, "room_rule_describe", DESCRIBE)
    assert [str(k) for k in res["data_schema"].schema] == ["change_wording"]


def test_change_wording_returns_to_form_with_text():
    flow, _s, _ = _flow(response=_resp([LAMP_ON]))
    _run_step(flow, "room_rule_describe", DESCRIBE)
    res = _run_step(flow, "room_rule_confirm", {"change_wording": True})
    assert res["step_id"] == "room_rule_describe"
    keys = {str(k): k for k in res["data_schema"].schema}
    assert keys[CONF_AI_RULE_DESCRIPTION].default() == DESCRIBE[CONF_AI_RULE_DESCRIPTION]


def test_run_an_automation_rule_saved_without_model():
    flow, services, _ = _flow()
    res = _run_step(flow, "room_rule_automation", {
        CONF_AI_RULE_TRIGGER: "exit", "rule_automation": "automation.party",
        "rule_use_conditions": True,
    })
    assert res["step_id"] == "room_rule_confirm"
    assert res["description_placeholders"]["preview"] == (
        "When someone leaves Exercise Room: run automation Party if its own conditions pass."
    )
    saved = _run_step(flow, "room_rule_confirm", {"change_wording": False})
    r = saved["data"][CONF_AI_RULES][0]
    assert r["source"] == "automation" and r["skip_condition"] is False
    assert r["actions"][0]["data"] == {"skip_condition": False}
    assert services.calls == []          # no model call


def test_reparse_writes_options_not_data():
    old = light_rule(rule_id="6a932dd2")
    old.update({"actions": [], "needs_parsing": True,
                "description": "After dark turn on the lamp at 40%"})
    flow, _s, _ = _flow(data={CONF_AI_RULES: [old]}, response=_resp([LAMP_ON]))
    flow._rule_selected = "6a932dd2"
    res = _run_step(flow, "room_rule_recheck")
    assert res["step_id"] == "room_rule_confirm"
    saved = _run_step(flow, "room_rule_confirm", {"change_wording": False})
    rules = saved["data"][CONF_AI_RULES]
    assert [r["rule_id"] for r in rules] == ["6a932dd2"]
    assert rules[0]["actions"] == [LAMP_ON] and "needs_parsing" not in rules[0]
    # entry.data untouched (create_entry writes options only)
    assert flow._config_entry.data[CONF_AI_RULES][0]["actions"] == []


def test_first_edit_copies_data_rules_to_options_still_flagged():
    a = light_rule(rule_id="d1")
    b = light_rule(rule_id="d2")
    flow, _s, _ = _flow(data={CONF_AI_RULES: [a, b]})
    flow._rule_selected = "d2"
    saved = _run_step(flow, "room_rule_toggle")
    rules = saved["data"][CONF_AI_RULES]
    assert [r["rule_id"] for r in rules] == ["d1", "d2"]
    assert all(r.get("needs_parsing") is True for r in rules)
    assert rules[1]["enabled"] is False


def test_delete_and_legacy_chain_fold():
    flow, _s, _ = _flow(options={CONF_AUTOMATION_CHAINS: {"enter": "automation.party"},
                                 CONF_AI_RULES: [light_rule(rule_id="r1")]})
    flow._rule_selected = "r1"
    saved = _run_step(flow, "room_rule_delete", {"confirm_delete": True})
    rules = saved["data"][CONF_AI_RULES]
    assert [r["rule_id"] for r in rules] == ["chain_enter"]
    assert rules[0]["source"] == "automation"
    assert saved["data"][CONF_AUTOMATION_CHAINS] == {}


def test_rule_list_labels_use_preview_and_status():
    flow, _s, _ = _flow(options={CONF_AI_RULES: [light_rule(rule_id="r1"),
                                                light_rule(rule_id="r2", enabled=False)]})
    res = _run_step(flow, "room_rule_list")
    labels = [o["label"] for o in res["data_schema"].schema[next(iter(res["data_schema"].schema))].config["options"]]
    assert labels == [
        "When someone enters Exercise Room: turn on Exercise Lamp. - Active",
        "When someone enters Exercise Room: turn on Exercise Lamp. - Off",
    ]


def test_init_menu_has_room_rules_not_old_entries():
    flow, _s, _ = _flow()
    menu = run(flow.async_step_init())["menu_options"]
    assert "room_rules" in menu
    assert "automation_chaining" not in menu and "ai_rules" not in menu


def test_cm_rule_writing_model_field_present():
    from custom_components.universal_room_automation import config_flow as cf
    from _room_menu_helpers import StubEntry, make_hass
    entry = StubEntry(data={"entry_type": "coordinator_manager"})
    flow = cf.UniversalRoomAutomationOptionsFlow(entry)
    flow.hass = make_hass()
    flow.hass.states.async_all = lambda: [MagicMock(entity_id="ai_task.claude_ai_task")]
    res = run(flow.async_step_coordinator_optimization(None))
    found = False
    for key, val in res["data_schema"].schema.items():
        if str(key) == "optimizer_llm":
            inner = val.schema.schema
            for k in inner:
                if str(k) == "room_rules_ai_task_entity":
                    found = True
                    assert k.default() == "ai_task.claude_ai_task"
    assert found
