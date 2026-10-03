"""ROOM-TYPE-TRIMMED-MENU-1 — Advanced-only room fields (D7-D8).

I2: no stored non-default value is unreachable in Simple mode.
I3: a Simple-mode save never drops a value that was not on the form.
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
    DEFAULT_FAN_SPEED_LOW,
    DEFAULT_HUMIDITY_FAN_MAX_RUNTIME,
    DEFAULT_SUNRISE_OFFSET,
    ROOM_MENU_STEPS_ALL,
    ROOM_MENU_STEPS_BY_TYPE,
    ROOM_TYPE_BEDROOM,
)

_COMP = Path(__file__).resolve().parents[2] / "custom_components" / "universal_room_automation"

# D7 Advanced column (NEW) + Lighting's pre-existing advanced keys.
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


@pytest.mark.parametrize("step,key", ADVANCED)
def test_classification_advanced_on_present_simple_absent(step, key):
    on = render(make_flow(ROOM_TYPE_BEDROOM, adv=True), step)
    assert key in schema_keys(on, top_level_only=True), "plan defect: key not top-level"
    off = render(make_flow(ROOM_TYPE_BEDROOM, adv=False), step)
    assert key not in schema_keys(off), key


@pytest.mark.parametrize("step,key", ADVANCED)
def test_i2_forced_render_when_non_default(step, key):
    _, defaults = owned_keys(make_flow(ROOM_TYPE_BEDROOM), step)
    val = nondefault(defaults.get(key))
    off = render(make_flow(ROOM_TYPE_BEDROOM, options={key: val}), step)
    assert key in schema_keys(off), (key, val)


def test_i2_explicit_default_stays_hidden():
    off = render(make_flow(ROOM_TYPE_BEDROOM,
                           options={CONF_SUNRISE_OFFSET: DEFAULT_SUNRISE_OFFSET}),
                 "options_covers")
    assert CONF_SUNRISE_OFFSET not in schema_keys(off)


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
    # Menu-only steps store their values via sub-steps; the legacy singular
    # energy key is shown through energy_sensors.
    not_form_keys = {k for v in cf._STEP_EXTRA_OWNED_KEYS.values() for k in v}
    missing = set(seeded) - not_form_keys - rendered
    assert not missing, (room_type, sorted(missing))


# --- I3 save guard ---------------------------------------------------------

def _submit(flow, step, user_input):
    return run(getattr(flow, f"async_step_{step}")(dict(user_input)))


def test_i3_covers_simple_save_keeps_hidden_value():
    flow = make_flow(ROOM_TYPE_BEDROOM, options={CONF_SUNRISE_OFFSET: DEFAULT_SUNRISE_OFFSET})
    assert CONF_SUNRISE_OFFSET not in schema_keys(render(flow, "options_covers"))
    res = _submit(flow, "options_covers", {})
    assert res["data"][CONF_SUNRISE_OFFSET] == DEFAULT_SUNRISE_OFFSET


def test_i3_climate_simple_save_keeps_hidden_values():
    stored = {CONF_FAN_SPEED_LOW_TEMP: DEFAULT_FAN_SPEED_LOW,
              CONF_HUMIDITY_FAN_MAX_RUNTIME: DEFAULT_HUMIDITY_FAN_MAX_RUNTIME}
    flow = make_flow(ROOM_TYPE_BEDROOM, options=stored)
    keys = schema_keys(render(flow, "climate"))
    assert not (set(stored) & keys)
    res = _submit(flow, "climate", {})
    for k, v in stored.items():
        assert res["data"][k] == v


@pytest.mark.parametrize("key", [
    CONF_LIGHT_SCENE_DAY, CONF_LIGHT_EVENING_BRIGHTNESS_PCT, CONF_NIGHT_LIGHT_EVENING_COLOR,
])
def test_i3_lighting_simple_save_keeps_hidden_value(key):
    """Stored explicitly at its default (empty) => hidden in Simple mode;
    a Simple-mode save must not clear it (show_advanced_options gate)."""
    flow = make_flow(ROOM_TYPE_BEDROOM, options={key: ""})
    assert key not in schema_keys(render(flow, "options_lighting_behaviour"))
    res = _submit(flow, "options_lighting_behaviour", {})
    assert key in res["data"] and res["data"][key] == ""


def test_lighting_advanced_save_still_clears_omitted():
    flow = make_flow(ROOM_TYPE_BEDROOM, options={CONF_LIGHT_SCENE_DAY: "scene.a"}, adv=True)
    res = _submit(flow, "options_lighting_behaviour", {})
    assert CONF_LIGHT_SCENE_DAY not in res["data"]


def test_lighting_forced_field_clearable_in_simple_mode():
    flow = make_flow(ROOM_TYPE_BEDROOM, options={CONF_LIGHT_SCENE_DAY: "scene.a"})
    assert CONF_LIGHT_SCENE_DAY in schema_keys(render(flow, "options_lighting_behaviour"))
    res = _submit(flow, "options_lighting_behaviour", {})
    assert CONF_LIGHT_SCENE_DAY not in res["data"]


# --- hint ------------------------------------------------------------------

@pytest.mark.parametrize("step", ["options_covers", "climate", "options_lighting_behaviour"])
def test_hint_per_step(step):
    off = render(make_flow(ROOM_TYPE_BEDROOM), step)
    on = render(make_flow(ROOM_TYPE_BEDROOM, adv=True), step)
    assert off["description_placeholders"]["advanced_hint"] == cf.ADVANCED_HINT_HIDDEN
    assert on["description_placeholders"]["advanced_hint"] == "Advanced settings shown."


def test_meta_every_step_with_advanced_fields_passes_hint():
    blobs = [json.loads((_COMP / r).read_text()) for r in ("strings.json", "translations/en.json")]
    with_adv = []
    for step in ROOM_MENU_STEPS_ALL:
        on = render(make_flow(ROOM_TYPE_BEDROOM, adv=True), step)
        if on.get("data_schema") is None:
            continue
        off = render(make_flow(ROOM_TYPE_BEDROOM), step)
        if schema_keys(on) - schema_keys(off):
            with_adv.append(step)
            assert "advanced_hint" in (off.get("description_placeholders") or {}), step
            for blob in blobs:
                assert "{advanced_hint}" in blob["options"]["step"][step]["description"], step
    assert set(with_adv) == {"options_covers", "climate", "options_lighting_behaviour"}


def test_room_menu_hint_variants():
    assert cf.room_menu_hint("closet", True, True) == "Advanced settings shown."
    assert cf.room_menu_hint("closet", False, False) == cf.ADVANCED_HINT_HIDDEN
    t = cf.room_menu_hint("closet", True, False)
    assert t.startswith("Showing the settings closet rooms usually need.")
    assert t.endswith(cf.ADVANCED_HINT_HIDDEN)
