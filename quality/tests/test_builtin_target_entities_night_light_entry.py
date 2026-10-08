"""NIGHT-LIGHT-ACTION-SELECTOR-1 (REV 3) — D5: AI-rule conflict surface.

``RoomAutomationCoordinator._get_builtin_target_entities(TRIGGER_ENTER)``
must include CONF_NIGHT_LIGHTS whenever non-empty (deduped against
CONF_LIGHTS). Simplified from REV 2's ``nl_action != NONE`` gate: under
the new rule, night lights are a potential entry target in all three
regimes (sleep, dark, daytime opt-in).
"""
from __future__ import annotations

from types import SimpleNamespace

from custom_components.universal_room_automation.const import (
    CONF_LIGHTS,
    CONF_NIGHT_LIGHTS,
)
from custom_components.universal_room_automation.coordinator import (
    UniversalRoomCoordinator,
)
from custom_components.universal_room_automation.const import TRIGGER_ENTER


def _coord_with_config(cfg):
    coord = UniversalRoomCoordinator.__new__(UniversalRoomCoordinator)
    coord.entry = SimpleNamespace(data=dict(cfg), options={})
    # _get_config reads data/options via self.entry — keep it simple.
    coord._get_config = lambda key, default=None: cfg.get(key, default)
    return coord


def test_trigger_enter_no_night_lights_omits_them():
    coord = _coord_with_config({CONF_LIGHTS: ["light.a"], CONF_NIGHT_LIGHTS: []})
    out = coord._get_builtin_target_entities(TRIGGER_ENTER)
    assert "light.a" in out
    # No night-light entities to include.
    assert all(not e.startswith("light.night") for e in out)


def test_trigger_enter_includes_night_lights_dedup():
    coord = _coord_with_config({
        CONF_LIGHTS: ["light.a", "light.n"],
        CONF_NIGHT_LIGHTS: ["light.n", "light.m"],
    })
    out = coord._get_builtin_target_entities(TRIGGER_ENTER)
    # light.a and light.n from CONF_LIGHTS, light.m from night lights.
    # light.n must appear exactly once (deduped).
    assert out.count("light.n") == 1
    assert "light.m" in out
    assert "light.a" in out


def test_trigger_enter_night_only_room_is_included():
    """Main=NONE / no CONF_LIGHTS room still exposes its night light to
    the AI-rule conflict surface."""
    coord = _coord_with_config({CONF_LIGHTS: [], CONF_NIGHT_LIGHTS: ["light.n"]})
    out = coord._get_builtin_target_entities(TRIGGER_ENTER)
    assert "light.n" in out
