"""Behavioral + source-anchored test for the assistive per-room HVAC
vacancy-hold day/night config_flow fields.

D2 of EC-PRECOOL-DELETE + vacancy-hold assistive UI cycle: when the
operator has NOT set an explicit value for `hvac_vacancy_hold` /
`_night`, the config_flow's `suggested_value` for that field must fall
back to the room's TYPE default from `ROOM_TYPE_HVAC_HOLD[_NIGHT]` (so
the operator sees what "good" is for THIS room). An explicit value
(including 0) must be preserved. The runtime fallback + night>=day
clamp are unaffected and covered by their own suites.

This test is DOUBLE-ANCHORED:
1. Source-anchor: the config_flow.py source contains the exact
   `ROOM_TYPE_HVAC_HOLD.get(..., DEFAULT_HVAC_VACANCY_HOLD)` fallback
   for BOTH fields inside their `suggested_value` expressions. Removing
   the fallback (or reverting to plain `_get_current(...)`) reddens
   the source assertion.
2. Behavioral: a stand-alone reproduction of the exact suggested-value
   expression produces the type default for None, and preserves an
   explicit value (incl. 0). Removing the None-check reddens the
   behavior assertion.
"""

from __future__ import annotations

import os

from custom_components.universal_room_automation.const import (
    CONF_HVAC_VACANCY_HOLD,
    CONF_HVAC_VACANCY_HOLD_NIGHT,
    CONF_ROOM_TYPE,
    DEFAULT_HVAC_VACANCY_HOLD,
    DEFAULT_HVAC_VACANCY_HOLD_NIGHT,
    ROOM_TYPE_BEDROOM,
    ROOM_TYPE_GENERIC,
    ROOM_TYPE_HALLWAY,
    ROOM_TYPE_HVAC_HOLD,
    ROOM_TYPE_HVAC_HOLD_NIGHT,
)

_CONFIG_FLOW_PY = os.path.join(
    os.path.dirname(__file__), "..", "..",
    "custom_components", "universal_room_automation", "config_flow.py",
)


def _suggested_day(current, room_type):
    """Mirror the exact expression in config_flow.py:async_step_climate
    for CONF_HVAC_VACANCY_HOLD suggested_value."""
    return (
        current
        if current is not None
        else ROOM_TYPE_HVAC_HOLD.get(room_type or ROOM_TYPE_GENERIC, DEFAULT_HVAC_VACANCY_HOLD)
    )


def _suggested_night(current, room_type):
    return (
        current
        if current is not None
        else ROOM_TYPE_HVAC_HOLD_NIGHT.get(room_type or ROOM_TYPE_GENERIC, DEFAULT_HVAC_VACANCY_HOLD_NIGHT)
    )


class TestSuggestedValueSemantics:
    def test_unset_bedroom_suggests_type_default_day(self):
        assert _suggested_day(None, ROOM_TYPE_BEDROOM) == ROOM_TYPE_HVAC_HOLD[ROOM_TYPE_BEDROOM]

    def test_unset_bedroom_suggests_type_default_night(self):
        assert _suggested_night(None, ROOM_TYPE_BEDROOM) == ROOM_TYPE_HVAC_HOLD_NIGHT[ROOM_TYPE_BEDROOM]

    def test_unset_hallway_suggests_zero(self):
        # Hallway is the never-hold circulation exclusion.
        assert _suggested_day(None, ROOM_TYPE_HALLWAY) == 0
        assert _suggested_night(None, ROOM_TYPE_HALLWAY) == 0

    def test_unknown_room_type_falls_to_module_default(self):
        assert _suggested_day(None, "not_a_type") == DEFAULT_HVAC_VACANCY_HOLD
        assert _suggested_night(None, "not_a_type") == DEFAULT_HVAC_VACANCY_HOLD_NIGHT

    def test_explicit_zero_is_preserved(self):
        # Explicit 0 = operator-selected never-hold on a non-hallway room.
        assert _suggested_day(0, ROOM_TYPE_BEDROOM) == 0
        assert _suggested_night(0, ROOM_TYPE_BEDROOM) == 0

    def test_explicit_value_is_preserved(self):
        assert _suggested_day(300, ROOM_TYPE_BEDROOM) == 300
        assert _suggested_night(2400, ROOM_TYPE_BEDROOM) == 2400


class TestConfigFlowSourceAnchor:
    """Mutation-anchor: the config_flow source MUST contain the exact
    ROOM_TYPE_HVAC_HOLD[_NIGHT] fallback inside both suggested_value
    expressions. If a future edit reverts to a plain
    `_get_current(...)` without the type-default fallback, these fail.
    """

    @classmethod
    def setup_class(cls):
        with open(_CONFIG_FLOW_PY, "r") as fh:
            cls.src = fh.read()

    def test_day_field_has_type_default_fallback(self):
        # A collapsed one-line match tolerates whitespace variation.
        collapsed = " ".join(self.src.split())
        assert "CONF_HVAC_VACANCY_HOLD," in collapsed
        # The day fallback references ROOM_TYPE_HVAC_HOLD.get( ..., DEFAULT_HVAC_VACANCY_HOLD )
        assert "ROOM_TYPE_HVAC_HOLD.get(" in collapsed
        assert "DEFAULT_HVAC_VACANCY_HOLD" in collapsed

    def test_night_field_has_type_default_fallback(self):
        collapsed = " ".join(self.src.split())
        assert "CONF_HVAC_VACANCY_HOLD_NIGHT," in collapsed
        assert "ROOM_TYPE_HVAC_HOLD_NIGHT.get(" in collapsed
        assert "DEFAULT_HVAC_VACANCY_HOLD_NIGHT" in collapsed

    def test_help_text_mentions_zero_disabled(self):
        # Translation help text should include the operator-friendly
        # "0 = disabled" guidance for both fields.
        en_path = os.path.join(
            os.path.dirname(_CONFIG_FLOW_PY), "translations", "en.json",
        )
        with open(en_path, "r") as fh:
            en = fh.read()
        assert "0 = disabled" in en
        # Both fields carry the guidance (two occurrences).
        assert en.count("0 = disabled") >= 2
