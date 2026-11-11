"""NIGHT-LIGHT-ACTION-SELECTOR-1 (REV 3) — D4 config-flow surfaces.

Covers:
- The new ``CONF_NIGHT_LIGHTS_BY_DAY`` BooleanSelector lives in
  ``options_lighting_behaviour`` and the field is visible in Simple mode
  with default False.
- Round-trip through the options flow — saving True preserves True on
  re-open; saving unchecked persists False (not dropped / reset).
- The five night-light colour/brightness fields in the ``devices`` step
  sit in its collapsed ``advanced`` section (FORM-CONDITIONAL-FIELDS-1).
"""
from __future__ import annotations

import pytest

from _room_menu_helpers import (
    make_flow,
    render,
    run,
    schema_keys,
)
from custom_components.universal_room_automation.const import (
    CONF_NIGHT_LIGHT_DAY_BRIGHTNESS,
    CONF_NIGHT_LIGHT_DAY_COLOR,
    CONF_NIGHT_LIGHT_SLEEP_BRIGHTNESS,
    CONF_NIGHT_LIGHT_SLEEP_COLOR,
    CONF_NIGHT_LIGHT_SLEEP_HUE,
    CONF_NIGHT_LIGHTS_BY_DAY,
    DEFAULT_NIGHT_LIGHT_SLEEP_BRIGHTNESS,
    DEFAULT_NIGHT_LIGHTS_BY_DAY,
    ROOM_TYPE_BEDROOM,
)


# ---------------------------------------------------------------------------
# D4a — new boolean field is visible in Simple mode on the behaviour step
# ---------------------------------------------------------------------------


def test_night_lights_by_day_visible_in_simple_mode():
    flow = make_flow(ROOM_TYPE_BEDROOM)
    keys = schema_keys(render(flow, "options_lighting_behaviour"))
    assert CONF_NIGHT_LIGHTS_BY_DAY in keys


def test_night_lights_by_day_default_false():
    assert DEFAULT_NIGHT_LIGHTS_BY_DAY is False


# ---------------------------------------------------------------------------
# D4a — round-trip save: True preserved, unchecked persists False
# ---------------------------------------------------------------------------


def _submit(flow, step, user_input):
    return run(getattr(flow, f"async_step_{step}")(dict(user_input)))


def test_night_lights_by_day_roundtrip_true_preserved():
    flow = make_flow(ROOM_TYPE_BEDROOM)
    res = _submit(flow, "options_lighting_behaviour",
                  {CONF_NIGHT_LIGHTS_BY_DAY: True})
    assert res["data"].get(CONF_NIGHT_LIGHTS_BY_DAY) is True

    # Re-open with the stored True — the field renders True.
    flow2 = make_flow(ROOM_TYPE_BEDROOM,
                      options={CONF_NIGHT_LIGHTS_BY_DAY: True})
    rendered = render(flow2, "options_lighting_behaviour")
    assert CONF_NIGHT_LIGHTS_BY_DAY in schema_keys(rendered)


def test_night_lights_by_day_roundtrip_unchecked_persists_false():
    # Operator unchecks the box — HA sends False (BooleanSelector).
    flow = make_flow(ROOM_TYPE_BEDROOM,
                     options={CONF_NIGHT_LIGHTS_BY_DAY: True})
    res = _submit(flow, "options_lighting_behaviour",
                  {CONF_NIGHT_LIGHTS_BY_DAY: False})
    assert res["data"].get(CONF_NIGHT_LIGHTS_BY_DAY) is False


# ---------------------------------------------------------------------------
# D4b — the 5 night-light colour/brightness fields retreat to Advanced
# ---------------------------------------------------------------------------


_ADVANCED_COLOUR_KEYS = (
    CONF_NIGHT_LIGHT_SLEEP_BRIGHTNESS,
    CONF_NIGHT_LIGHT_SLEEP_HUE,
    CONF_NIGHT_LIGHT_SLEEP_COLOR,
    CONF_NIGHT_LIGHT_DAY_BRIGHTNESS,
    CONF_NIGHT_LIGHT_DAY_COLOR,
)


def _advanced_section_keys(result) -> set:
    from custom_components.universal_room_automation import config_flow as cf
    for marker, val in result["data_schema"].schema.items():
        if str(getattr(marker, "schema", marker)) == "advanced":
            return set(cf._collect_schema_defaults(val.schema))
    return set()


@pytest.mark.parametrize("key", _ADVANCED_COLOUR_KEYS)
def test_night_colour_field_in_collapsed_section(key):
    """FORM-CONDITIONAL-FIELDS-1: the five fields sit in the Devices
    step's collapsed ``advanced`` section (not top level), whatever the
    retired profile flag says."""
    for adv in (False, True):
        res = render(make_flow(ROOM_TYPE_BEDROOM, adv=adv), "devices")
        assert key not in schema_keys(res, top_level_only=True), key
        assert key in _advanced_section_keys(res), key


def test_night_colour_stored_value_prefilled():
    stored = {CONF_NIGHT_LIGHT_SLEEP_BRIGHTNESS: 50}
    assert stored[CONF_NIGHT_LIGHT_SLEEP_BRIGHTNESS] != DEFAULT_NIGHT_LIGHT_SLEEP_BRIGHTNESS
    res = render(make_flow(ROOM_TYPE_BEDROOM, options=stored), "devices")
    from custom_components.universal_room_automation import config_flow as cf
    for marker, val in res["data_schema"].schema.items():
        if str(getattr(marker, "schema", marker)) == "advanced":
            assert cf._collect_schema_defaults(val.schema)[
                CONF_NIGHT_LIGHT_SLEEP_BRIGHTNESS] == 50


def test_night_colour_unsent_section_keeps_stored_values():
    """I3: a save whose section was not sent keeps the stored colours."""
    stored = {
        CONF_NIGHT_LIGHT_DAY_BRIGHTNESS: 42,
        CONF_NIGHT_LIGHT_SLEEP_BRIGHTNESS: DEFAULT_NIGHT_LIGHT_SLEEP_BRIGHTNESS,
    }
    flow = make_flow(ROOM_TYPE_BEDROOM, options=stored)
    res = _submit(flow, "devices", {})
    assert res["data"][CONF_NIGHT_LIGHT_DAY_BRIGHTNESS] == 42
    assert res["data"][CONF_NIGHT_LIGHT_SLEEP_BRIGHTNESS] == \
        DEFAULT_NIGHT_LIGHT_SLEEP_BRIGHTNESS


def test_night_colour_section_edit_lands_flat():
    flow = make_flow(ROOM_TYPE_BEDROOM, options={CONF_NIGHT_LIGHT_DAY_BRIGHTNESS: 42})
    res = _submit(flow, "devices", {"advanced": {CONF_NIGHT_LIGHT_DAY_BRIGHTNESS: 60}})
    assert res["data"][CONF_NIGHT_LIGHT_DAY_BRIGHTNESS] == 60
    assert "advanced" not in res["data"]
