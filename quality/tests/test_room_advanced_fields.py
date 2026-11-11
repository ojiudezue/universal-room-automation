"""Rarely-changed room fields live in a collapsed ``advanced`` section.

ROOM-TYPE-TRIMMED-MENU-1 (D7-D8) put these fields behind HA's profile
"Advanced mode"; FORM-CONDITIONAL-FIELDS-1 release 1 (D3) moved them into
each step's collapsed section keyed ``advanced`` (HA deprecated the flag).

I2: every stored value is reachable (one click away, inside the section).
I3: a save whose section was not sent never drops a stored value.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import voluptuous as vol

from _room_menu_helpers import (
    make_flow,
    menu,
    nondefault,
    owned_keys,
    render,
    run,
    schema_keys,
)
from custom_components.universal_room_automation import config_flow as cf
from custom_components.universal_room_automation.const import (
    CONF_FAN_SPEED_HIGH_TEMP,
    CONF_FAN_SPEED_LOW_TEMP,
    CONF_FAN_SPEED_MED_TEMP,
    CONF_HUMIDITY_FAN_MAX_RUNTIME,
    CONF_LIGHT_EVENING_BRIGHTNESS_PCT,
    CONF_LIGHT_EVENING_COLOR_KELVIN,
    CONF_LIGHT_MANUAL_OFF_COOLDOWN_S,
    CONF_LIGHT_MANUAL_ON_HOLD_S,
    CONF_LIGHT_SCENE_DAY,
    CONF_LIGHT_SCENE_EVENING,
    CONF_LIGHT_SCENE_SLEEP,
    CONF_LIGHTS_ON_ENTRY_DARK_ONLY,
    CONF_NIGHT_LIGHT_EVENING_BRIGHTNESS,
    CONF_NIGHT_LIGHT_EVENING_COLOR,
    CONF_ROOM_NAME,
    CONF_ROOM_TYPE,
    CONF_SUNRISE_OFFSET,
    CONF_SUNSET_OFFSET,
    ROOM_MENU_STEPS_ALL,
    ROOM_MENU_STEPS_BY_TYPE,
    ROOM_TYPE_BEDROOM,
)

_COMP = Path(__file__).resolve().parents[2] / "custom_components" / "universal_room_automation"

# Hand-written oracle (plan §13.1 rows 52-67), not derived from the schema.
ADVANCED = [
    ("options_covers", CONF_SUNRISE_OFFSET),
    ("options_covers", CONF_SUNSET_OFFSET),
    ("climate", CONF_FAN_SPEED_LOW_TEMP),
    ("climate", CONF_FAN_SPEED_MED_TEMP),
    ("climate", CONF_FAN_SPEED_HIGH_TEMP),
    ("climate", CONF_HUMIDITY_FAN_MAX_RUNTIME),
    ("options_lighting_behaviour", CONF_LIGHTS_ON_ENTRY_DARK_ONLY),
    ("options_lighting_behaviour", CONF_LIGHT_MANUAL_ON_HOLD_S),
    ("options_lighting_behaviour", CONF_LIGHT_MANUAL_OFF_COOLDOWN_S),
    ("options_lighting_behaviour", CONF_LIGHT_EVENING_BRIGHTNESS_PCT),
    ("options_lighting_behaviour", CONF_LIGHT_EVENING_COLOR_KELVIN),
    ("options_lighting_behaviour", CONF_NIGHT_LIGHT_EVENING_BRIGHTNESS),
    ("options_lighting_behaviour", CONF_NIGHT_LIGHT_EVENING_COLOR),
    ("options_lighting_behaviour", CONF_LIGHT_SCENE_DAY),
    ("options_lighting_behaviour", CONF_LIGHT_SCENE_EVENING),
    ("options_lighting_behaviour", CONF_LIGHT_SCENE_SLEEP),
]


def _section_keys(result, name="advanced") -> set:
    for marker, val in result["data_schema"].schema.items():
        if str(getattr(marker, "schema", marker)) == name:
            return set(cf._collect_schema_defaults(val.schema))
    return set()


@pytest.mark.parametrize("step,key", ADVANCED)
def test_key_lives_in_advanced_section(step, key):
    res = render(make_flow(ROOM_TYPE_BEDROOM), step)
    assert key not in schema_keys(res, top_level_only=True), key
    assert key in _section_keys(res), key


@pytest.mark.parametrize("step,key", ADVANCED)
def test_i2_stored_value_rendered_as_section_default(step, key):
    _, defaults = owned_keys(make_flow(ROOM_TYPE_BEDROOM), step)
    val = nondefault(defaults.get(key))
    res = render(make_flow(ROOM_TYPE_BEDROOM, options={key: val}), step)
    assert key in schema_keys(res), (key, val)


@pytest.mark.parametrize("room_type", sorted(ROOM_MENU_STEPS_BY_TYPE))
def test_i2_global_every_seeded_key_reachable(room_type):
    probe = make_flow(room_type)
    seeded: dict = {}
    for step in ROOM_MENU_STEPS_ALL:
        owned, defaults = owned_keys(probe, step)
        for key in owned:
            if key in (CONF_ROOM_TYPE, CONF_ROOM_NAME):
                continue
            seeded[key] = nondefault(defaults.get(key, vol.UNDEFINED))
    flow = make_flow(room_type, options=seeded)
    rendered: set = set()
    for step in menu(flow):
        if step == "show_all_settings":
            continue
        res = render(flow, step)
        if res.get("data_schema") is not None:
            rendered |= schema_keys(res)
    not_form_keys = {k for v in cf._STEP_EXTRA_OWNED_KEYS.values() for k in v}
    missing = set(seeded) - not_form_keys - rendered
    assert not missing, (room_type, sorted(missing))


# --- I3 save guard ---------------------------------------------------------

def _submit(flow, step, user_input):
    return run(getattr(flow, f"async_step_{step}")(dict(user_input)))


def test_i3_covers_unsent_section_keeps_stored_value():
    flow = make_flow(ROOM_TYPE_BEDROOM, options={CONF_SUNRISE_OFFSET: 45})
    res = _submit(flow, "options_covers", {})
    assert res["data"][CONF_SUNRISE_OFFSET] == 45
    assert "advanced" not in res["data"]


def test_covers_section_edit_lands_flat():
    flow = make_flow(ROOM_TYPE_BEDROOM, options={CONF_SUNRISE_OFFSET: 45})
    res = _submit(flow, "options_covers", {"advanced": {CONF_SUNRISE_OFFSET: 90}})
    assert res["data"][CONF_SUNRISE_OFFSET] == 90
    assert "advanced" not in res["data"]


def test_i3_climate_unsent_section_keeps_stored_values():
    stored = {CONF_FAN_SPEED_LOW_TEMP: 71, CONF_HUMIDITY_FAN_MAX_RUNTIME: 1800}
    flow = make_flow(ROOM_TYPE_BEDROOM, options=stored)
    res = _submit(flow, "climate", {})
    for k, v in stored.items():
        assert res["data"][k] == v
    assert "advanced" not in res["data"]


@pytest.mark.parametrize("key", [
    CONF_LIGHT_SCENE_DAY, CONF_LIGHT_EVENING_BRIGHTNESS_PCT, CONF_NIGHT_LIGHT_EVENING_COLOR,
])
def test_i3_lighting_unsent_section_keeps_clearable(key):
    """A clearable evening/scene key survives a save whose section was not
    sent (plan §3 rev 4, H2)."""
    flow = make_flow(ROOM_TYPE_BEDROOM, options={key: "scene.a"})
    res = _submit(flow, "options_lighting_behaviour", {})
    assert res["data"][key] == "scene.a"


def test_lighting_sent_section_still_clears_omitted():
    flow = make_flow(ROOM_TYPE_BEDROOM, options={CONF_LIGHT_SCENE_DAY: "scene.a"})
    res = _submit(flow, "options_lighting_behaviour", {"advanced": {}})
    assert CONF_LIGHT_SCENE_DAY not in res["data"]


# --- hint retired ------------------------------------------------------------

@pytest.mark.parametrize("step", [s for s in ROOM_MENU_STEPS_ALL])
def test_no_step_passes_advanced_hint(step):
    res = render(make_flow(ROOM_TYPE_BEDROOM), step)
    assert "advanced_hint" not in (res.get("description_placeholders") or {}), step


@pytest.mark.parametrize("rel", ["strings.json", "translations/en.json"])
def test_no_advanced_hint_placeholder_in_strings(rel):
    blob = json.loads((_COMP / rel).read_text())
    for flow in ("config", "options"):
        for step_id, step in blob[flow]["step"].items():
            assert "{advanced_hint}" not in (step.get("description") or ""), (flow, step_id)


def test_room_menu_hint_variants():
    assert cf.room_menu_hint("closet", True) == (
        "Showing the settings a closet usually needs. "
        "Pick More settings for the rest."
    )
    assert cf.room_menu_hint("bedroom", False) == ""
    assert cf.room_menu_hint("utility", True).startswith(
        "Showing the settings a utility room usually needs.")
    assert cf.room_menu_hint("media room", True).startswith(
        "Showing the settings a media room usually needs.")
    assert cf.room_menu_hint("infrastructure", True).startswith(
        "Showing the settings an equipment room usually needs.")
