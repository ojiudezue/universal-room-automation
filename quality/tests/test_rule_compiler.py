"""AI-ROOM-RULES-TRUST-REPAIR-1 D1 / D3: the one rule compiler + preview.

Drives ``rule_compiler.compile_rule`` / ``parse_and_validate`` /
``render_rule_preview`` with a stubbed ``ai_task.generate_data`` (the account
is API-limit locked until 2026-12-01). Expected values are hand-written.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from _room_rules_rig import FakeServices, run, st
from custom_components.universal_room_automation import rule_compiler as R
from custom_components.universal_room_automation.const import (
    ROOM_RULE_DATA_KEYS,
    ROOM_RULE_STRUCTURE,
)
from unittest.mock import MagicMock


ROOM_IDS = ["light.exercise_lamp", "fan.exercise_fan", "media_player.exercise_speaker",
            "cover.exercise_blind", "input_number.exercise_level", "select.exercise_mode"]


def _hass(response=None, states=None):
    hass = MagicMock()
    services = FakeServices()
    services.response = response
    hass.services = services
    base = {
        "ai_task.claude_ai_task": st("unknown"),
        "light.exercise_lamp": st("off", friendly_name="Exercise Lamp"),
        "fan.exercise_fan": st("off", friendly_name="Exercise Fan"),
        "automation.party": st("on", friendly_name="Party"),
        "scene.relax": st("scening", friendly_name="Relax"),
        "person.oji_udezue": st("home", friendly_name="Oji"),
    }
    base.update(states or {})
    hass.states.get = lambda eid: base.get(eid)
    return hass


def _resp(actions, conditions=None, unsupported="", summary="", nested=True):
    body = {
        "actions_json": json.dumps(actions),
        "conditions_json": json.dumps(conditions or []),
        "unsupported": unsupported,
        "summary": summary,
    }
    return {"data": body} if nested else body


LAMP_ON = {"domain": "light", "service": "turn_on",
           "target": {"entity_id": "light.exercise_lamp"}, "data": {"brightness_pct": 40}}


def _compile(hass, entity="ai_task.claude_ai_task", **kw):
    ents = [{"entity_id": e, "name": e, "domain": e.split(".")[0]} for e in ROOM_IDS]
    return run(R.compile_rule(
        hass, description=kw.get("description", "turn on the lamp"),
        trigger_type=kw.get("trigger", "enter"), person=kw.get("person", ""),
        room_name="Exercise Room", entities=ents, ai_task_entity=entity,
        timeout_s=kw.get("timeout_s"),
    ))


# --- D1 structure ---------------------------------------------------------


def test_rule_compiler_structure_has_only_text_fields():
    assert set(ROOM_RULE_STRUCTURE) == {"actions_json", "conditions_json", "unsupported", "summary"}
    for spec in ROOM_RULE_STRUCTURE.values():
        assert set(spec["selector"]) == {"text"}, spec
    hass = _hass(_resp([LAMP_ON]))
    res = _compile(hass)
    call = hass.services.calls[0]
    assert (call.domain, call.service) == ("ai_task", "generate_data")
    assert call.data["structure"] == ROOM_RULE_STRUCTURE
    assert call.data["entity_id"] == "ai_task.claude_ai_task"
    assert res.ok


def test_rule_compiler_parses_nested_and_flat():
    for nested in (True, False):
        res = R.parse_and_validate(_hass(), _resp([LAMP_ON], nested=nested), ROOM_IDS)
        assert res.kind == "ok" and res.actions == [LAMP_ON]
    # Strict precedence: a dict under "data" wins; a flat key beside it is ignored.
    raw = {"data": {"actions_json": "not json"}, "actions_json": json.dumps([LAMP_ON])}
    assert R.parse_and_validate(_hass(), raw, ROOM_IDS).kind == "parse_failed"


def test_rule_compiler_rejects_entity_outside_room_set():
    other = {**LAMP_ON, "target": {"entity_id": "light.kitchen"}}
    res = R.parse_and_validate(_hass(states={"light.kitchen": st("off")}), _resp([other]), ROOM_IDS)
    assert res.kind == "parse_failed"
    assert any("light.kitchen" in e and "not in this room" in e for e in res.errors)


def test_rule_compiler_allows_any_automation_target():
    acts = [{"domain": "automation", "service": "trigger", "target": {"entity_id": "automation.party"},
             "data": {"skip_condition": False}},
            {"domain": "scene", "service": "turn_on", "target": {"entity_id": "scene.relax"}, "data": {}}]
    assert R.parse_and_validate(_hass(), _resp(acts), ROOM_IDS).kind == "ok"
    missing = [{"domain": "automation", "service": "trigger",
                "target": {"entity_id": "automation.gone"}, "data": {}}]
    assert R.parse_and_validate(_hass(), _resp(missing), ROOM_IDS).kind == "parse_failed"


@pytest.mark.parametrize("domain,eid,data", [
    ("light", "light.exercise_lamp", {"brightness_pct": 40, "color_temp_kelvin": 2700,
                                       "rgb_color": [255, 0, 0], "color_name": "red", "transition": 2}),
    ("fan", "fan.exercise_fan", {"percentage": 50, "preset_mode": "breeze",
                                  "oscillating": True, "direction": "forward"}),
    ("media_player", "media_player.exercise_speaker", {"volume_level": 0.3, "media_content_id": "x",
                                                        "media_content_type": "music", "source": "Spotify"}),
    ("cover", "cover.exercise_blind", {"position": 30, "tilt_position": 10}),
    ("input_number", "input_number.exercise_level", {"value": 3}),
    ("select", "select.exercise_mode", {"option": "a"}),
])
def test_rule_compiler_volume_level_and_fan_percentage_kept(domain, eid, data):
    act = {"domain": domain, "service": "turn_on", "target": {"entity_id": eid}, "data": data}
    res = R.parse_and_validate(_hass(), _resp([act]), ROOM_IDS)
    assert res.kind == "ok", res.errors
    assert res.actions[0]["data"] == data
    assert set(data) <= ROOM_RULE_DATA_KEYS[domain]


def test_rule_compiler_rejects_unknown_key_by_name():
    act = {**LAMP_ON, "data": {"brightness": 200}}
    res = R.parse_and_validate(_hass(), _resp([act]), ROOM_IDS)
    assert res.kind == "parse_failed"
    assert any("'brightness'" in e for e in res.errors)


def test_rule_compiler_rejects_light_toggle():
    act = {**LAMP_ON, "service": "toggle", "data": {}}
    res = R.parse_and_validate(_hass(), _resp([act]), ROOM_IDS)
    assert res.kind == "parse_failed" and any("toggle" in e for e in res.errors)


def test_rule_compiler_rejects_climate_and_zero_actions():
    clim = {"domain": "climate", "service": "set_temperature",
            "target": {"entity_id": "climate.zone_1"}, "data": {}}
    assert R.parse_and_validate(_hass(), _resp([clim]), ROOM_IDS + ["climate.zone_1"]).kind == "parse_failed"
    assert R.parse_and_validate(_hass(), _resp([]), ROOM_IDS).kind == "parse_failed"


def test_rule_compiler_rejects_entity_of_other_domain():
    act = {**LAMP_ON, "domain": "switch", "data": {}}
    res = R.parse_and_validate(_hass(), _resp([act]), ROOM_IDS)
    assert res.kind == "parse_failed" and any("is not a switch" in e for e in res.errors)


def test_rule_compiler_timeout_is_model_unavailable():
    hass = _hass()

    async def _slow(*a, **k):
        await asyncio.sleep(5)

    hass.services.async_call = _slow
    res = _compile(hass, timeout_s=0.05)
    assert res.kind == "model_unavailable"
    assert res.model_entity == "ai_task.claude_ai_task"
    assert any("timed out" in e for e in res.errors)


def test_rule_compiler_ai_task_error_is_model_unavailable():
    from homeassistant.exceptions import HomeAssistantError
    hass = _hass()
    hass.services.raise_on[("ai_task", "generate_data")] = HomeAssistantError("usage limit")
    res = _compile(hass)
    assert res.kind == "model_unavailable"
    # entity unavailable -> no call at all
    hass2 = _hass(states={"ai_task.claude_ai_task": st("unavailable")})
    res2 = _compile(hass2)
    assert res2.kind == "model_unavailable" and hass2.services.calls == []
    # service not registered -> model_unavailable
    hass3 = _hass()
    hass3.services.registered.clear()
    assert _compile(hass3).kind == "model_unavailable" and hass3.services.calls == []


def test_rule_compiler_bad_response_is_parse_failed_not_model():
    hass = _hass({"data": {"actions_json": "[{\"domain\": "}})
    assert _compile(hass).kind == "parse_failed"


def test_rule_compiler_unsupported_named():
    res = R.parse_and_validate(_hass(), _resp([LAMP_ON], unsupported="only when it rains"), ROOM_IDS)
    assert res.kind == "unsupported" and res.unsupported == "only when it rains"


def test_rule_compiler_empty_entity_uses_ha_default():
    hass = _hass(_resp([LAMP_ON]))
    res = _compile(hass, entity="")
    assert res.ok and "entity_id" not in hass.services.calls[0].data


def test_rule_compiler_conditions_validated():
    good = [{"type": "after_dark"}, {"type": "time_window", "start": "22:00", "end": "06:00"},
            {"type": "house_state_in", "states": ["sleep"]}]
    assert R.parse_and_validate(_hass(), _resp([LAMP_ON], good), ROOM_IDS).kind == "ok"
    for bad in ([{"type": "weather_is", "value": "rain"}],
                [{"type": "time_window", "start": "7", "end": "9"}],
                [{"type": "house_state_in", "states": ["party"]}]):
        assert R.parse_and_validate(_hass(), _resp([LAMP_ON], bad), ROOM_IDS).kind == "parse_failed"


# --- D3 preview -------------------------------------------------------------


def test_rule_preview_renders_from_actions_not_summary():
    hass = _hass()
    rule = {"trigger_type": "enter", "person": "person.oji_udezue", "conditions": [],
            "actions": [LAMP_ON], "summary": "turns on the lamp when you enter after dark",
            "description": "after dark turn on the lamp"}
    text = R.render_rule_preview(rule, hass, "Exercise Room")
    assert text == "When Oji enters Exercise Room: turn on Exercise Lamp at 40 percent."
    assert "after dark" not in text
    rule["conditions"] = [{"type": "after_dark"}]
    assert R.render_rule_preview(rule, hass, "Exercise Room") == (
        "When Oji enters Exercise Room, after dark: turn on Exercise Lamp at 40 percent."
    )


def test_rule_preview_automation_rule():
    hass = _hass()
    rule = {"trigger_type": "house_state_sleep", "person": "", "conditions": [],
            "actions": [{"domain": "automation", "service": "trigger",
                         "target": {"entity_id": "automation.party"},
                         "data": {"skip_condition": False}}]}
    assert R.render_rule_preview(rule, hass, "Exercise Room") == (
        "When the house switches to Sleep: run automation Party if its own conditions pass."
    )


def test_room_entity_set_is_config_plus_area():
    hass = _hass()
    reg = MagicMock()
    reg.entities = {
        "fan.exercise_fan": MagicMock(entity_id="fan.exercise_fan", area_id="exercise_room", disabled=False),
        "light.kitchen": MagicMock(entity_id="light.kitchen", area_id="kitchen", disabled=False),
    }
    from unittest.mock import patch
    from homeassistant.helpers import entity_registry as er
    with patch.object(er, "async_get", lambda h: reg):
        ents = R.room_entity_set(hass, {"lights": ["light.exercise_lamp"], "area_id": "exercise_room"})
    assert [e["entity_id"] for e in ents] == ["light.exercise_lamp", "fan.exercise_fan"]


def test_room_entity_set_leaves_out_climate():
    """Review A LOW: every climate action is rejected, so the room's climate
    entity is not offered to the model."""
    from custom_components.universal_room_automation.const import CONF_CLIMATE_ENTITY
    hass = _hass(states={"climate.exercise": st("cool"), "climate.area_unit": st("cool")})
    reg = MagicMock()
    reg.entities = {"climate.area_unit": MagicMock(
        entity_id="climate.area_unit", area_id="exercise_room", disabled=False)}
    from unittest.mock import patch
    from homeassistant.helpers import entity_registry as er
    with patch.object(er, "async_get", lambda h: reg):
        ents = R.room_entity_set(hass, {"lights": ["light.exercise_lamp"],
                                        CONF_CLIMATE_ENTITY: "climate.exercise",
                                        "area_id": "exercise_room"})
    assert [e["entity_id"] for e in ents] == ["light.exercise_lamp"]
