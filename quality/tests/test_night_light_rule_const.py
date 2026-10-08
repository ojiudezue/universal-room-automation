"""NIGHT-LIGHT-ACTION-SELECTOR-1 (REV 3) — D1 default.

Pure-import unit test for the single new boolean knob
``CONF_NIGHT_LIGHTS_BY_DAY``.
"""
from __future__ import annotations

from custom_components.universal_room_automation.const import (
    CONF_NIGHT_LIGHTS_BY_DAY,
    DEFAULT_NIGHT_LIGHTS_BY_DAY,
)


def test_conf_night_lights_by_day_key_is_stable_string():
    # The key is persisted in entry.options; must not drift.
    assert CONF_NIGHT_LIGHTS_BY_DAY == "night_lights_by_day"


def test_default_night_lights_by_day_is_false():
    # Default off preserves today's "night lights ride dusk/sleep only"
    # behaviour for every room until the operator opts in.
    assert DEFAULT_NIGHT_LIGHTS_BY_DAY is False
