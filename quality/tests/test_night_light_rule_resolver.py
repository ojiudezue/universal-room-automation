"""NIGHT-LIGHT-ACTION-SELECTOR-1 (REV 3) — resolver + shared params helper.

Covers:
- ``effective_entry_set`` drops night-light members from the day/non-sleep
  union when ``is_dark is not True`` AND ``night_lights_by_day`` is False
  (R3-H1 fold).
- Night-light membership WINS over an explicit ``CONF_LIGHTS_ON_ENTRY``
  picker: a night light in the picker is still stripped by day with
  ``nl_by_day=False`` (R3-M1).
- ``night_lights_by_day=True`` admits night lights by day.
- ``is_dark is True`` admits night lights regardless of the by-day knob.
- Sleep behaviour is unchanged.
- ``night_light_turn_on_params(mode)`` returns identical brightness /
  color_temp for the day / evening / sleep modes (R3-M2).
"""
from __future__ import annotations

from custom_components.universal_room_automation.const import (
    CONF_LIGHT_CAPABILITIES,
    CONF_LIGHTS,
    CONF_LIGHTS_ON_ENTRY,
    CONF_NIGHT_LIGHT_DAY_BRIGHTNESS,
    CONF_NIGHT_LIGHT_DAY_COLOR,
    CONF_NIGHT_LIGHT_EVENING_BRIGHTNESS,
    CONF_NIGHT_LIGHT_EVENING_COLOR,
    CONF_NIGHT_LIGHT_SLEEP_BRIGHTNESS,
    CONF_NIGHT_LIGHT_SLEEP_COLOR,
    CONF_NIGHT_LIGHTS,
    DEFAULT_NIGHT_LIGHT_DAY_BRIGHTNESS,
    DEFAULT_NIGHT_LIGHT_DAY_COLOR,
    DEFAULT_NIGHT_LIGHT_SLEEP_BRIGHTNESS,
    DEFAULT_NIGHT_LIGHT_SLEEP_COLOR,
    LIGHT_CAPABILITY_BASIC,
    LIGHT_CAPABILITY_BRIGHTNESS,
    LIGHT_CAPABILITY_FULL,
)
from custom_components.universal_room_automation.lighting.resolver import (
    effective_entry_set,
    night_light_turn_on_params,
)


def _cfg(**extra):
    base = {
        CONF_LIGHTS: ["light.main"],
        CONF_NIGHT_LIGHTS: ["light.night"],
    }
    base.update(extra)
    return base


# ---------------------------------------------------------------------------
# effective_entry_set — by-day strip
# ---------------------------------------------------------------------------


def test_entry_set_bright_no_byday_strips_night():
    # is_dark=False, nl_by_day=False → night light NOT in main set.
    out = effective_entry_set(
        _cfg(), is_sleep_hours=False, is_dark=False,
        night_lights_by_day=False,
    )
    assert out == ["light.main"]


def test_entry_set_bright_byday_true_keeps_night():
    # is_dark=False, nl_by_day=True → night light IS in main set.
    out = effective_entry_set(
        _cfg(), is_sleep_hours=False, is_dark=False,
        night_lights_by_day=True,
    )
    assert "light.night" in out


def test_entry_set_dark_keeps_night_regardless_of_byday():
    for by_day in (False, True):
        out = effective_entry_set(
            _cfg(), is_sleep_hours=False, is_dark=True,
            night_lights_by_day=by_day,
        )
        assert "light.night" in out, f"by_day={by_day} should keep night when dark"


def test_entry_set_sleep_still_night_only():
    out = effective_entry_set(
        _cfg(), is_sleep_hours=True, is_dark=False,
        night_lights_by_day=False,
    )
    assert out == ["light.night"]


def test_entry_set_r3_m1_night_membership_wins_over_on_entry_picker():
    """R3-M1: a night light in CONF_LIGHTS_ON_ENTRY is still stripped by
    day with nl_by_day=False — membership in CONF_NIGHT_LIGHTS WINS over
    the explicit on-entry list.
    """
    cfg = _cfg(**{
        CONF_LIGHTS_ON_ENTRY: ["light.main", "light.night"],
    })
    out = effective_entry_set(
        cfg, is_sleep_hours=False, is_dark=False,
        night_lights_by_day=False,
    )
    assert out == ["light.main"], \
        "picker cannot force a night light on by day"
    # And when nl_by_day=True, the picker member is kept.
    out2 = effective_entry_set(
        cfg, is_sleep_hours=False, is_dark=False,
        night_lights_by_day=True,
    )
    assert "light.night" in out2


# ---------------------------------------------------------------------------
# night_light_turn_on_params — R3-M2 shared helper
# ---------------------------------------------------------------------------


def test_nl_params_basic_capability_no_brightness_or_color():
    cfg = {CONF_LIGHT_CAPABILITIES: LIGHT_CAPABILITY_BASIC}
    assert night_light_turn_on_params(cfg, "day") == {}
    assert night_light_turn_on_params(cfg, "sleep") == {}
    assert night_light_turn_on_params(cfg, "evening") == {}


def test_nl_params_brightness_only():
    cfg = {
        CONF_LIGHT_CAPABILITIES: LIGHT_CAPABILITY_BRIGHTNESS,
        CONF_NIGHT_LIGHT_DAY_BRIGHTNESS: 77,
        CONF_NIGHT_LIGHT_SLEEP_BRIGHTNESS: 11,
    }
    out_day = night_light_turn_on_params(cfg, "day")
    assert out_day == {"brightness_pct": 77}
    out_sleep = night_light_turn_on_params(cfg, "sleep")
    assert out_sleep == {"brightness_pct": 11}
    assert "color_temp_kelvin" not in out_day


def test_nl_params_full_capability_sleep():
    cfg = {CONF_LIGHT_CAPABILITIES: LIGHT_CAPABILITY_FULL}
    out = night_light_turn_on_params(cfg, "sleep")
    assert out["brightness_pct"] == DEFAULT_NIGHT_LIGHT_SLEEP_BRIGHTNESS
    assert out["color_temp_kelvin"] == DEFAULT_NIGHT_LIGHT_SLEEP_COLOR


def test_nl_params_full_capability_day():
    cfg = {CONF_LIGHT_CAPABILITIES: LIGHT_CAPABILITY_FULL}
    out = night_light_turn_on_params(cfg, "day")
    assert out["brightness_pct"] == DEFAULT_NIGHT_LIGHT_DAY_BRIGHTNESS
    assert out["color_temp_kelvin"] == DEFAULT_NIGHT_LIGHT_DAY_COLOR


def test_nl_params_evening_falls_back_to_day_defaults():
    cfg = {CONF_LIGHT_CAPABILITIES: LIGHT_CAPABILITY_FULL}
    out = night_light_turn_on_params(cfg, "evening")
    # Absent evening overrides → day values.
    assert out["brightness_pct"] == DEFAULT_NIGHT_LIGHT_DAY_BRIGHTNESS
    assert out["color_temp_kelvin"] == DEFAULT_NIGHT_LIGHT_DAY_COLOR


def test_nl_params_evening_uses_overrides_when_set():
    cfg = {
        CONF_LIGHT_CAPABILITIES: LIGHT_CAPABILITY_FULL,
        CONF_NIGHT_LIGHT_EVENING_BRIGHTNESS: 23,
        CONF_NIGHT_LIGHT_EVENING_COLOR: 2500,
    }
    out = night_light_turn_on_params(cfg, "evening")
    assert out["brightness_pct"] == 23
    assert out["color_temp_kelvin"] == 2500
