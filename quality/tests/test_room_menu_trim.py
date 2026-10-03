"""ROOM-TYPE-TRIMMED-MENU-1 — room options menu trim (D1-D3, D5, D6).

Invariant I1: a step hidden for the room type appears in the Simple-mode
menu whenever any key it owns holds a non-default value (factory default
from a shim render, NOT the live schema default — plan R1).
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from _room_menu_helpers import (
    make_flow,
    menu,
    nondefault,
    owned_keys,
    run,
)
from custom_components.universal_room_automation import config_flow as cf
from custom_components.universal_room_automation.const import (
    CONF_AUTO_SWITCHES,
    CONF_AUTOMATION_CHAINS,
    CONF_COVER_TYPE,
    CONF_COVERS,
    CONF_ENERGY_SENSOR,
    CONF_ENTRY_LIGHT_ACTION,
    CONF_FLAP_SENSITIVITY,
    CONF_MANUAL_SWITCHES,
    CONF_POWER_SENSORS,
    CONF_ROOM_FAN_MODE,
    CONF_ROOM_TYPE,
    CONF_SLEEP_PROTECTION_ENABLED,
    CONF_WET_ROOM,
    CONF_ZONE,
    FAN_MODE_OFF,
    FAN_MODE_ROOM_TEMPERATURE,
    ROOM_MENU_STEPS_ALL,
    ROOM_MENU_STEPS_BY_TYPE,
    ROOM_TYPE_BEDROOM,
    ROOM_TYPE_CLOSET,
    ROOM_TYPE_UTILITY,
    ROOM_TYPE_GARAGE,
)

ALL_TYPES = sorted(ROOM_MENU_STEPS_BY_TYPE)
_COMP = Path(__file__).resolve().parents[2] / "custom_components" / "universal_room_automation"


def _expected(room_type):
    exp = list(ROOM_MENU_STEPS_BY_TYPE[room_type])
    if len(exp) != len(ROOM_MENU_STEPS_ALL):
        exp.append("show_all_settings")
    return exp


# --- D1 -------------------------------------------------------------------

def test_map_covers_all_ten_types_and_keeps_order():
    assert len(ROOM_MENU_STEPS_BY_TYPE) == 10
    for steps in ROOM_MENU_STEPS_BY_TYPE.values():
        assert set(steps) <= set(ROOM_MENU_STEPS_ALL)
        assert "options_lighting_behaviour" in steps
    assert "options_lighting" not in ROOM_MENU_STEPS_ALL
    for steps in ROOM_MENU_STEPS_BY_TYPE.values():
        assert "options_lighting" not in steps
    for t in ("garage", "utility", "infrastructure"):
        assert "options_covers" not in ROOM_MENU_STEPS_BY_TYPE[t]


# --- D2 snapshot (Simple) ------------------------------------------------

@pytest.mark.parametrize("room_type", ALL_TYPES)
def test_simple_menu_snapshot_per_type(room_type):
    flow = make_flow(room_type)
    result = run(flow.async_step_init())
    assert result["menu_options"] == _expected(room_type)
    assert "Advanced mode" in result["description_placeholders"]["menu_hint"]


@pytest.mark.parametrize("room_type", ALL_TYPES)
def test_advanced_mode_full_menu(room_type):
    flow = make_flow(room_type, adv=True)
    result = run(flow.async_step_init())
    assert result["menu_options"] == list(ROOM_MENU_STEPS_ALL)
    assert "show_all_settings" not in result["menu_options"]
    assert result["description_placeholders"]["menu_hint"] == "Advanced settings shown."


def test_trimmed_hint_names_room_type():
    hint = run(make_flow(ROOM_TYPE_CLOSET).async_step_init())[
        "description_placeholders"]["menu_hint"]
    assert "a closet usually needs" in hint
    assert "More settings" in hint


# --- I1 in-use reveal ------------------------------------------------------

def _hidden_cases():
    cases = []
    for t in ALL_TYPES:
        for step in ROOM_MENU_STEPS_ALL:
            if step not in ROOM_MENU_STEPS_BY_TYPE[t]:
                cases.append((t, step))
    return cases


@pytest.mark.parametrize("room_type,step", _hidden_cases())
def test_in_use_reveal_every_owned_key(room_type, step):
    probe = make_flow(room_type)
    owned, defaults = owned_keys(probe, step)
    assert owned, f"{step} owns no keys"
    for key in sorted(owned):
        val = nondefault(defaults.get(key))
        flow = make_flow(room_type, options={key: val})
        assert step in menu(flow), (room_type, step, key, val)


def test_live_default_is_not_the_baseline_r1():
    """R1 discriminator: a stored non-default value equals the LIVE schema
    default (handlers default to the stored value) yet must still reveal."""
    flow = make_flow(ROOM_TYPE_CLOSET, options={CONF_SLEEP_PROTECTION_ENABLED: True})
    live = run(flow.async_step_sleep_protection(None))["data_schema"]
    live_defaults = cf._collect_schema_defaults(live)
    assert live_defaults[CONF_SLEEP_PROTECTION_ENABLED] is True
    assert "sleep_protection" in menu(flow)


def test_legacy_data_only_values():
    flow = make_flow(ROOM_TYPE_CLOSET, data={CONF_POWER_SENSORS: ["sensor.p"]})
    assert "energy" in menu(flow)
    flow = make_flow(ROOM_TYPE_CLOSET, data={CONF_ENERGY_SENSOR: "sensor.e"})
    assert "energy" in menu(flow)
    # room type in data only -> correct trim
    assert menu(make_flow(ROOM_TYPE_GARAGE)) == _expected(ROOM_TYPE_GARAGE)


def test_options_room_type_wins_over_data():
    flow = make_flow(ROOM_TYPE_BEDROOM, options={CONF_ROOM_TYPE: ROOM_TYPE_CLOSET})
    assert menu(flow) == _expected(ROOM_TYPE_CLOSET)


@pytest.mark.parametrize("mode", [FAN_MODE_OFF, FAN_MODE_ROOM_TEMPERATURE])
def test_fan_mode_only_room_keeps_climate_hidden(mode):
    # Both a default and a NON-default Fan Mode (operator ruling: Fan Mode
    # is written by migration/Select and must never reveal Climate alone).
    flow = make_flow(ROOM_TYPE_CLOSET, options={CONF_ROOM_FAN_MODE: mode})
    assert "climate" not in menu(flow)


def test_menu_only_steps_reveal_on_non_empty():
    flow = make_flow(ROOM_TYPE_CLOSET, options={CONF_AUTOMATION_CHAINS: {}})
    assert "automation_chaining" not in menu(flow)
    flow = make_flow(ROOM_TYPE_CLOSET, options={CONF_AUTOMATION_CHAINS: {"enter": "automation.x"}})
    assert "automation_chaining" in menu(flow)


def test_render_failure_fails_open(monkeypatch):
    flow = make_flow(ROOM_TYPE_CLOSET)

    async def _boom(self, user_input=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(cf.UniversalRoomAutomationOptionsFlow, "async_step_energy", _boom)
    assert "energy" in menu(flow)


# --- More settings ---------------------------------------------------------

def test_more_settings_full_then_trimmed_again():
    flow = make_flow(ROOM_TYPE_CLOSET)
    assert "show_all_settings" in menu(flow)
    full = run(flow.async_step_show_all_settings())
    assert full["step_id"] == "init"
    assert full["menu_options"] == list(ROOM_MENU_STEPS_ALL)
    assert "Advanced mode" in full["description_placeholders"]["menu_hint"]
    assert menu(flow) == _expected(ROOM_TYPE_CLOSET)


# --- owner / schema consistency -------------------------------------------

def test_owner_schema_consistency():
    flow = make_flow(ROOM_TYPE_BEDROOM)
    owners: dict = {}
    for step in ROOM_MENU_STEPS_ALL:
        owned, defaults = owned_keys(flow, step)
        extras = set(cf._STEP_EXTRA_OWNED_KEYS.get(step, ()))
        assert owned - extras <= set(defaults), step
        for k in owned:
            owners.setdefault(k, set()).add(step)
    assert all(len(v) == 1 for v in owners.values()), {
        k: v for k, v in owners.items() if len(v) > 1}
    assert CONF_ROOM_FAN_MODE not in owners
    assert owners[CONF_ROOM_TYPE] == {"basic_setup"}
    assert owners[CONF_ZONE] == {"basic_setup"}
    assert owners[CONF_COVERS] == {"devices"}
    assert owners[CONF_COVER_TYPE] == {"options_covers"}
    assert owners[CONF_WET_ROOM] == {"climate"}
    for k in (CONF_ENTRY_LIGHT_ACTION, CONF_FLAP_SENSITIVITY,
              CONF_AUTO_SWITCHES, CONF_MANUAL_SWITCHES):
        assert owners[k] == {"options_lighting_behaviour"}, k


def test_factory_render_uses_fallbacks_not_stored_values():
    flow = make_flow(ROOM_TYPE_BEDROOM, options={CONF_SLEEP_PROTECTION_ENABLED: True})
    _, defaults = owned_keys(flow, "sleep_protection")
    assert defaults[CONF_SLEEP_PROTECTION_ENABLED] is False


# --- handler purity --------------------------------------------------------

def test_factory_render_is_side_effect_free():
    flow = make_flow(ROOM_TYPE_BEDROOM, options={CONF_SLEEP_PROTECTION_ENABLED: True},
                     data={CONF_POWER_SENSORS: ["sensor.p"]})
    before = (copy.deepcopy(flow._config_entry.data), copy.deepcopy(flow._config_entry.options))
    ctx_before = dict(flow.context)
    for step in ROOM_MENU_STEPS_ALL:
        if step not in cf._MENU_ONLY_ROOM_STEPS:
            assert run(flow._render_step_schema(step)) is not None, step
    run(flow.async_step_init())
    assert (flow._config_entry.data, flow._config_entry.options) == before
    assert dict(flow.context) == ctx_before
    flow.hass.config_entries.async_update_entry.assert_not_called()
    flow.hass.async_create_task.assert_not_called()


# --- D5 type change --------------------------------------------------------

def test_type_change_redraws():
    flow = make_flow(ROOM_TYPE_BEDROOM)
    assert menu(flow) == list(ROOM_MENU_STEPS_ALL)
    flow._config_entry.options = {CONF_ROOM_TYPE: ROOM_TYPE_CLOSET}
    assert menu(flow) == _expected(ROOM_TYPE_CLOSET)
    flow._config_entry.options = {CONF_ROOM_TYPE: ROOM_TYPE_CLOSET,
                                  CONF_SLEEP_PROTECTION_ENABLED: True}
    assert "sleep_protection" in menu(flow)


# --- D6 translations -------------------------------------------------------

@pytest.mark.parametrize("rel", ["strings.json", "translations/en.json"])
def test_translations(rel):
    blob = json.loads((_COMP / rel).read_text())
    steps = blob["options"]["step"]
    assert steps["init"]["menu_options"]["show_all_settings"] == "More settings…"
    assert "{menu_hint}" in steps["init"]["description"]
    for s in ROOM_MENU_STEPS_ALL:
        assert steps["init"]["menu_options"].get(s), s
    assert "{advanced_hint}" in steps["options_covers"]["description"]
    assert "{advanced_hint}" in steps["climate"]["description"]


def test_non_room_menus_pass_empty_menu_hint():
    from custom_components.universal_room_automation.const import (
        CONF_ENTRY_TYPE, ENTRY_TYPE_COORDINATOR_MANAGER, ENTRY_TYPE_INTEGRATION,
    )
    for et in (ENTRY_TYPE_INTEGRATION, ENTRY_TYPE_COORDINATOR_MANAGER):
        flow = make_flow(data={CONF_ENTRY_TYPE: et})
        res = run(flow.async_step_init())
        assert res["description_placeholders"] == {"menu_hint": ""}


# --- B-MEDIUM: hand-written Advanced-only keys (independent oracle) ---------
# Hand-authored (NOT derived from the shim render): these keys are Advanced-
# only on their step. If the factory render ever ran with Advanced OFF they
# would be filtered out of the owned-key set and the step would stay hidden.
_HAND_ADVANCED_CASES = [
    (ROOM_TYPE_UTILITY, "options_covers", "sunrise_offset", 15),
    (ROOM_TYPE_UTILITY, "options_covers", "sunset_offset", -20),
    (ROOM_TYPE_CLOSET, "climate", "fan_speed_low_temp", 91),
    (ROOM_TYPE_CLOSET, "climate", "fan_speed_high_temp", 99),
]


@pytest.mark.parametrize("room_type,step,key,value", _HAND_ADVANCED_CASES)
def test_advanced_only_key_reveals_owning_step(room_type, step, key, value):
    assert step not in menu(make_flow(room_type))  # hidden by type
    flow = make_flow(room_type, options={key: value}, adv=False)
    assert step in menu(flow), (room_type, step, key)


def test_render_failure_warns_once_per_step(monkeypatch, caplog):
    import logging

    async def _boom(self, user_input=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(cf.UniversalRoomAutomationOptionsFlow, "async_step_energy", _boom)
    monkeypatch.setattr(cf, "_RENDER_FAIL_WARNED", set())
    caplog.set_level(logging.DEBUG)
    menu(make_flow(ROOM_TYPE_CLOSET))
    menu(make_flow(ROOM_TYPE_CLOSET))
    warns = [r for r in caplog.records if r.levelno == logging.WARNING
             and "factory render of energy failed" in r.getMessage()]
    assert len(warns) == 1


def test_factory_render_emits_no_timing_logs(caplog):
    import logging
    caplog.set_level(logging.WARNING)
    flow = make_flow(ROOM_TYPE_CLOSET)
    run(flow._render_step_schema("climate"))
    assert not [r for r in caplog.records if "CFLOW-TIMING" in r.getMessage()]
