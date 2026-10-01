"""Slice E tests — time-of-day slots (D5) + scenes (D6) + advanced hint.

Covers:
- ``resolve_slot(is_sleep_hours, is_dark)`` returns day/evening/sleep with
  no wall-clock reads (clock injected via the two bool args).
- ``slot_scene`` / ``slot_regular_light_overrides`` / ``slot_night_light_overrides``
  return correct values or empty on absent keys.
- Absent Slice E keys ⇒ resolver-equivalence still holds (no visible change).
- The has_on_entry inline entry path applies evening brightness / colour.
- ``_turn_on_regular_lights`` applies evening overrides for regular lights.
- ``_turn_on_night_lights(mode="evening")`` reuses day defaults when
  evening keys are absent and applies overrides when they are present.
- ``_maybe_activate_slot_scene`` returns False when no scene is set,
  False when the scene entity is unavailable, True on happy path, and
  the dispatched call goes to ``scene.turn_on`` with the URA context
  (``ura_context.URA_LIGHT_WRITE_DOMAINS`` includes ``"scene"``).
- The Lighting behaviour step's Advanced hint has two variants and the
  helper picks the correct one per ``show_advanced_options``.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.universal_room_automation.const import (
    CONF_LIGHT_CAPABILITIES,
    CONF_LIGHT_EVENING_BRIGHTNESS_PCT,
    CONF_LIGHT_EVENING_COLOR_KELVIN,
    CONF_LIGHT_SCENE_DAY,
    CONF_LIGHT_SCENE_EVENING,
    CONF_LIGHT_SCENE_SLEEP,
    CONF_LIGHTS,
    CONF_LIGHTS_ON_ENTRY,
    CONF_NIGHT_LIGHTS,
    CONF_NIGHT_LIGHT_DAY_BRIGHTNESS,
    CONF_NIGHT_LIGHT_DAY_COLOR,
    CONF_NIGHT_LIGHT_EVENING_BRIGHTNESS,
    CONF_NIGHT_LIGHT_EVENING_COLOR,
    DEFAULT_NIGHT_LIGHT_DAY_BRIGHTNESS,
    DEFAULT_NIGHT_LIGHT_DAY_COLOR,
    LIGHT_CAPABILITY_FULL,
    LIGHT_SLOT_DAY,
    LIGHT_SLOT_EVENING,
    LIGHT_SLOT_SLEEP,
)
from custom_components.universal_room_automation.lighting.resolver import (
    effective_entry_set,
    effective_exit_set,
    resolve_slot,
    slot_night_light_overrides,
    slot_regular_light_overrides,
    slot_scene,
)
from custom_components.universal_room_automation.ura_context import (
    URA_LIGHT_WRITE_DOMAINS,
    URA_WRITE_CONTEXT_PARENT_ID,
    ura_ctx_kwargs,
)


# ---------------------------------------------------------------------------
# resolve_slot — pure function, clock injected via booleans
# ---------------------------------------------------------------------------


def test_resolve_slot_sleep_wins_over_dark():
    assert resolve_slot(True, True) == LIGHT_SLOT_SLEEP
    assert resolve_slot(True, False) == LIGHT_SLOT_SLEEP
    assert resolve_slot(True, None) == LIGHT_SLOT_SLEEP


def test_resolve_slot_evening_when_dark_and_not_sleep():
    assert resolve_slot(False, True) == LIGHT_SLOT_EVENING


def test_resolve_slot_day_when_not_dark_and_not_sleep():
    assert resolve_slot(False, False) == LIGHT_SLOT_DAY
    assert resolve_slot(False, None) == LIGHT_SLOT_DAY


# ---------------------------------------------------------------------------
# Slot getters — absent-keys equivalence + overrides
# ---------------------------------------------------------------------------


def test_slot_scene_absent_returns_none():
    cfg: dict = {}
    assert slot_scene(cfg, LIGHT_SLOT_DAY) is None
    assert slot_scene(cfg, LIGHT_SLOT_EVENING) is None
    assert slot_scene(cfg, LIGHT_SLOT_SLEEP) is None


def test_slot_scene_present_returns_entity_id():
    cfg = {
        CONF_LIGHT_SCENE_DAY: "scene.morning",
        CONF_LIGHT_SCENE_EVENING: "scene.sunset",
        CONF_LIGHT_SCENE_SLEEP: "scene.night",
    }
    assert slot_scene(cfg, LIGHT_SLOT_DAY) == "scene.morning"
    assert slot_scene(cfg, LIGHT_SLOT_EVENING) == "scene.sunset"
    assert slot_scene(cfg, LIGHT_SLOT_SLEEP) == "scene.night"


def test_slot_scene_empty_string_returns_none():
    cfg = {CONF_LIGHT_SCENE_EVENING: ""}
    assert slot_scene(cfg, LIGHT_SLOT_EVENING) is None


def test_slot_scene_bad_slot_returns_none():
    assert slot_scene({}, "midnight") is None


def test_slot_regular_light_overrides_evening_only():
    cfg = {
        CONF_LIGHT_EVENING_BRIGHTNESS_PCT: 40,
        CONF_LIGHT_EVENING_COLOR_KELVIN: 2500,
    }
    assert slot_regular_light_overrides(cfg, LIGHT_SLOT_DAY) == {}
    assert slot_regular_light_overrides(cfg, LIGHT_SLOT_SLEEP) == {}
    assert slot_regular_light_overrides(cfg, LIGHT_SLOT_EVENING) == {
        "brightness_pct": 40, "color_kelvin": 2500,
    }


def test_slot_regular_light_overrides_partial_and_absent():
    assert slot_regular_light_overrides({}, LIGHT_SLOT_EVENING) == {}
    assert slot_regular_light_overrides(
        {CONF_LIGHT_EVENING_BRIGHTNESS_PCT: 60}, LIGHT_SLOT_EVENING,
    ) == {"brightness_pct": 60}


def test_slot_night_light_overrides_evening_only():
    cfg = {
        CONF_NIGHT_LIGHT_EVENING_BRIGHTNESS: 25,
        CONF_NIGHT_LIGHT_EVENING_COLOR: 2200,
    }
    assert slot_night_light_overrides(cfg, LIGHT_SLOT_DAY) == {}
    assert slot_night_light_overrides(cfg, LIGHT_SLOT_SLEEP) == {}
    assert slot_night_light_overrides(cfg, LIGHT_SLOT_EVENING) == {
        "brightness": 25, "color": 2200,
    }


def test_slot_night_light_overrides_absent_evening_is_empty():
    assert slot_night_light_overrides({}, LIGHT_SLOT_EVENING) == {}


# ---------------------------------------------------------------------------
# Absent-keys equivalence — resolver-equivalence still holds under Slice E
# ---------------------------------------------------------------------------


def test_absent_slice_e_keys_keep_entry_and_exit_sets():
    """Adding no Slice E keys must not change effective_entry/exit_set."""
    cfg = {
        CONF_LIGHTS: ["light.a", "light.b"],
        CONF_NIGHT_LIGHTS: ["light.n"],
    }
    assert effective_entry_set(cfg, False) == ["light.a", "light.b", "light.n"]
    assert effective_entry_set(cfg, True) == ["light.n"]
    assert effective_exit_set(cfg) == ["light.a", "light.b", "light.n"]


# ---------------------------------------------------------------------------
# URA context includes "scene" so propagation carries the parent_id
# ---------------------------------------------------------------------------


def test_ura_context_domains_include_scene():
    assert "scene" in URA_LIGHT_WRITE_DOMAINS
    kw = ura_ctx_kwargs("scene")
    assert "context" in kw
    assert kw["context"].parent_id == URA_WRITE_CONTEXT_PARENT_ID


# ---------------------------------------------------------------------------
# Wire-in tests — _turn_on_regular_lights + _turn_on_night_lights slot use.
# We drive the real method with an AsyncMock ``_safe_service_call`` on a
# minimally-stubbed RoomAutomation. Import the class under a light package
# stub so we don't need the full HA harness.
# ---------------------------------------------------------------------------


@pytest.fixture
def ra_module():
    """Import the automation module against the installed HA harness."""
    from custom_components.universal_room_automation import automation as m
    return m


def _make_ra(ra_module, cfg: dict, *, capability=LIGHT_CAPABILITY_FULL):
    """Build a bare RoomAutomation instance for method-level tests.

    We bypass __init__ to avoid the full coordinator boot; only the fields
    the method under test reads are set. ``light_hold_allowed`` is stubbed
    to identity (no hold interference).
    """
    ra = ra_module.RoomAutomation.__new__(ra_module.RoomAutomation)
    ra.config = {**cfg}
    if CONF_LIGHT_CAPABILITIES not in ra.config:
        ra.config[CONF_LIGHT_CAPABILITIES] = capability
    ra.hass = MagicMock()
    ra._safe_service_call = AsyncMock(return_value=True)
    ra.light_hold_allowed = lambda ents, direction: list(ents)
    ra.coordinator = MagicMock()
    return ra


@pytest.mark.asyncio
async def test_turn_on_regular_lights_evening_overrides_brightness_and_color(ra_module):
    ra = _make_ra(ra_module, {
        CONF_LIGHTS: ["light.a"],
        CONF_LIGHT_EVENING_BRIGHTNESS_PCT: 30,
        CONF_LIGHT_EVENING_COLOR_KELVIN: 2400,
    })
    await ra._turn_on_regular_lights(slot=LIGHT_SLOT_EVENING)
    ra._safe_service_call.assert_awaited()
    domain, service, data = ra._safe_service_call.await_args.args[:3]
    assert (domain, service) == ("light", "turn_on")
    assert data["brightness_pct"] == 30
    # HA light.turn_on key is color_temp_kelvin (review A HIGH: color_kelvin is rejected by the schema).
    assert data["color_temp_kelvin"] == 2400
    assert "color_kelvin" not in data


@pytest.mark.asyncio
async def test_turn_on_regular_lights_day_absent_keys_is_todays_path(ra_module):
    ra = _make_ra(ra_module, {CONF_LIGHTS: ["light.a"]})
    await ra._turn_on_regular_lights(slot=LIGHT_SLOT_DAY)
    _, _, data = ra._safe_service_call.await_args.args[:3]
    # Absent evening keys ⇒ CONF_LIGHT_BRIGHTNESS_PCT default (100), no color.
    assert data["brightness_pct"] == 100
    assert "color_kelvin" not in data and "color_temp_kelvin" not in data


@pytest.mark.asyncio
async def test_turn_on_night_lights_evening_falls_back_to_day_defaults(ra_module):
    ra = _make_ra(ra_module, {
        CONF_NIGHT_LIGHTS: ["light.n"],
        CONF_NIGHT_LIGHT_DAY_BRIGHTNESS: 80,
        CONF_NIGHT_LIGHT_DAY_COLOR: 4500,
    })
    await ra._turn_on_night_lights(mode="evening")
    _, _, data = ra._safe_service_call.await_args.args[:3]
    assert data["brightness_pct"] == 80
    assert data["color_temp_kelvin"] == 4500


@pytest.mark.asyncio
async def test_turn_on_night_lights_evening_uses_overrides_when_set(ra_module):
    ra = _make_ra(ra_module, {
        CONF_NIGHT_LIGHTS: ["light.n"],
        CONF_NIGHT_LIGHT_DAY_BRIGHTNESS: 80,
        CONF_NIGHT_LIGHT_DAY_COLOR: 4500,
        CONF_NIGHT_LIGHT_EVENING_BRIGHTNESS: 20,
        CONF_NIGHT_LIGHT_EVENING_COLOR: 2100,
    })
    await ra._turn_on_night_lights(mode="evening")
    _, _, data = ra._safe_service_call.await_args.args[:3]
    assert data["brightness_pct"] == 20
    assert data["color_temp_kelvin"] == 2100


# ---------------------------------------------------------------------------
# _maybe_activate_slot_scene — happy path + skip cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_maybe_activate_slot_scene_returns_false_when_no_scene(ra_module):
    ra = _make_ra(ra_module, {})
    got = await ra._maybe_activate_slot_scene(LIGHT_SLOT_EVENING, ["light.a"])
    assert got is False
    ra._safe_service_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_maybe_activate_slot_scene_returns_false_when_scene_unavailable(ra_module):
    ra = _make_ra(ra_module, {CONF_LIGHT_SCENE_EVENING: "scene.sunset"})
    ra.hass.states.get.return_value = SimpleNamespace(state="unavailable")
    got = await ra._maybe_activate_slot_scene(LIGHT_SLOT_EVENING, ["light.a"])
    assert got is False
    ra._safe_service_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_maybe_activate_slot_scene_dispatches_scene_turn_on(ra_module):
    ra = _make_ra(ra_module, {CONF_LIGHT_SCENE_EVENING: "scene.sunset"})
    ra.hass.states.get.return_value = SimpleNamespace(state="scening")
    got = await ra._maybe_activate_slot_scene(LIGHT_SLOT_EVENING, ["light.a"])
    assert got is True
    ra._safe_service_call.assert_awaited_once()
    domain, service, data = ra._safe_service_call.await_args.args[:3]
    assert (domain, service) == ("scene", "turn_on")
    assert data == {"entity_id": "scene.sunset"}


# ---------------------------------------------------------------------------
# Advanced-mode hint — two variants + helper
# ---------------------------------------------------------------------------


def test_lighting_advanced_hint_variants_exist():
    from custom_components.universal_room_automation import config_flow as cf

    hidden = cf.LIGHTING_ADVANCED_HINT_HIDDEN
    shown = cf.LIGHTING_ADVANCED_HINT_SHOWN
    assert "Advanced mode" in hidden
    assert "bottom left" in hidden.lower()
    assert "profile" in hidden.lower()
    assert "hidden" in hidden.lower()
    assert "Advanced" in shown
    assert hidden != shown


def test_lighting_advanced_hint_helper_picks_variant():
    from custom_components.universal_room_automation.config_flow import (
        LIGHTING_ADVANCED_HINT_HIDDEN,
        LIGHTING_ADVANCED_HINT_SHOWN,
        lighting_advanced_hint,
    )

    assert lighting_advanced_hint(False) == LIGHTING_ADVANCED_HINT_HIDDEN
    assert lighting_advanced_hint(True) == LIGHTING_ADVANCED_HINT_SHOWN


def test_lighting_behaviour_description_carries_advanced_hint_placeholder():
    """strings.json + en.json descriptions must interpolate {advanced_hint}."""
    import json
    from pathlib import Path

    comp = Path(__file__).resolve().parents[2] / "custom_components" / "universal_room_automation"
    for path in (comp / "strings.json", comp / "translations" / "en.json"):
        blob = json.loads(path.read_text())
        step = blob["options"]["step"]["options_lighting_behaviour"]
        assert "{advanced_hint}" in step["description"], f"missing in {path}"
