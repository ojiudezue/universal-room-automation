"""ROOM-TYPE-TRIMMED-MENU-1 follow-up (2026-11-05).

D1: the room-type menu trim applies in HA Advanced mode too.
D2: the per-room electricity rate is gone: not rendered in the room energy
    step, does not reveal the energy step, and is not read by the rate
    helper (EC TOU -> house-wide rate -> DEFAULT).

All tests drive production code (options-flow handlers, the real rate
helper, the real room cost sensor). Oracles are hand-written literals.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from _room_menu_helpers import make_flow, menu, render, run, schema_keys
from custom_components.universal_room_automation import config_flow as cf
from custom_components.universal_room_automation.domain_coordinators.energy_billing import (
    _get_effective_rate_kwh,
)

DOMAIN = "universal_room_automation"

CLOSET_TRIMMED = [
    "basic_setup", "sensors", "devices", "options_lighting_behaviour",
    "options_covers", "show_all_settings",
]
FULL_12 = [
    "basic_setup", "sensors", "devices",
    "options_lighting_behaviour", "options_covers",
    "automation_chaining", "ai_rules",
    "climate", "sleep_protection", "music_following",
    "energy", "notifications",
]


# --- D1 --------------------------------------------------------------------

def test_closet_advanced_mode_gets_trimmed_menu_and_more_settings():
    res = run(make_flow("closet", adv=True).async_step_init())
    assert res["menu_options"] == CLOSET_TRIMMED
    hint = res["description_placeholders"]["menu_hint"]
    assert "a closet usually needs" in hint
    assert hint.endswith("Advanced settings shown.")


def test_closet_simple_mode_hint_still_explains_advanced():
    hint = run(make_flow("closet", adv=False).async_step_init())[
        "description_placeholders"]["menu_hint"]
    assert "a closet usually needs" in hint
    assert "turn on Advanced mode" in hint


@pytest.mark.parametrize("adv", [False, True])
def test_bedroom_shows_all_twelve_without_more_settings(adv):
    res = run(make_flow("bedroom", adv=adv).async_step_init())
    assert res["menu_options"] == FULL_12
    assert len(res["menu_options"]) == 12


def test_advanced_closet_still_reveals_step_holding_a_value():
    flow = make_flow("closet", adv=True, options={"power_sensors": ["sensor.p"]})
    assert "energy" in menu(flow)


def test_more_settings_in_advanced_mode_shows_all_twelve():
    res = run(make_flow("closet", adv=True).async_step_show_all_settings())
    assert res["menu_options"] == FULL_12


# --- D2 menu reveal / schema ----------------------------------------------

@pytest.mark.parametrize("adv", [False, True])
def test_closet_with_only_stored_room_rate_does_not_reveal_energy(adv):
    flow = make_flow("closet", adv=adv, options={"electricity_rate": 0.11})
    assert "energy" not in menu(flow)


def test_closet_with_power_sensors_reveals_energy():
    flow = make_flow("closet", options={
        "electricity_rate": 0.11, "power_sensors": ["sensor.closet_power"],
    })
    assert "energy" in menu(flow)


def test_room_options_energy_step_has_no_rate_field():
    flow = make_flow("closet", adv=True, options={"electricity_rate": 0.11})
    keys = schema_keys(render(flow, "energy"))
    assert "electricity_rate" not in keys
    assert "power_sensors" in keys


def test_room_options_energy_save_keeps_stored_rate_untouched():
    flow = make_flow("closet", options={"electricity_rate": 0.11})
    res = run(flow.async_step_energy({"power_sensors": []}))
    assert res["data"]["electricity_rate"] == 0.11  # no migration


def test_room_create_energy_step_has_no_rate_field():
    flow = cf.UniversalRoomAutomationConfigFlow()
    flow.hass = make_flow("closet").hass
    flow._data = {}
    flow.context = {}
    keys = schema_keys(run(flow.async_step_energy(None)))
    assert "electricity_rate" not in keys
    assert "power_sensors" in keys


# --- D2 rate helper --------------------------------------------------------

def _hass(ec_rate=None, house_rate=None):
    data = {}
    if ec_rate is not None:
        ec = SimpleNamespace(current_effective_rate=ec_rate)
        data["coordinator_manager"] = SimpleNamespace(coordinators={"energy": ec})
    if house_rate is not None:
        data["integration"] = SimpleNamespace(
            data={}, options={"electricity_rate": house_rate})
    return SimpleNamespace(data={DOMAIN: data})


def test_rate_helper_ec_first():
    assert _get_effective_rate_kwh(_hass(ec_rate=0.27, house_rate=0.13)) == (0.27, "ec_tou")


def test_rate_helper_global_when_ec_absent():
    assert _get_effective_rate_kwh(_hass(house_rate=0.13)) == (0.13, "static_config")


def test_rate_helper_default_when_nothing():
    assert _get_effective_rate_kwh(_hass()) == (0.15, "static_config")


def _cost_sensor(room_rate, hass):
    from custom_components.universal_room_automation import sensor as s
    from custom_components.universal_room_automation.const import STATE_ENERGY_TODAY
    entry = SimpleNamespace(entry_id="r1", data={}, options={"electricity_rate": room_rate})
    coord = SimpleNamespace(hass=hass, entry=entry, data={STATE_ENERGY_TODAY: 10.0})
    sensor = object.__new__(s.EnergyCostTodaySensor)
    sensor.coordinator = coord
    return sensor


def test_room_cost_today_uses_house_rate_not_stored_room_rate():
    # Room stores 0.11, house rate 0.13, EC absent -> 10 kWh * 0.13 = 1.30.
    assert _cost_sensor(0.11, _hass(house_rate=0.13)).native_value == 1.3


def test_room_cost_today_uses_ec_rate():
    assert _cost_sensor(0.11, _hass(ec_rate=0.2, house_rate=0.13)).native_value == 2.0
