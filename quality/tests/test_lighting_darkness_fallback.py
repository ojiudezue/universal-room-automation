"""Slice B tests for the darkness fallback (ROOM-LIGHTING-SETUP-REDESIGN-1).

Covers the fallback order per the plan §D1 (:191-196):
  1. Borrowed lux (CONF_LIGHT_DARK_LUX_SOURCE)
  2. Sun fallback (CONF_LIGHT_DARK_USE_SUN_FALLBACK, default TRUE)
  3. False
Plus the R2-3 availability-only freshness rule, the operator's per-room
kill-switch semantics (default TRUE, False preserves today), and the
fail-safe posture (bad/missing state ⇒ False, never auto-light).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.universal_room_automation.const import (
    CONF_ILLUMINANCE_THRESHOLD,
    CONF_LIGHT_DARK_LUX_SOURCE,
    CONF_LIGHT_DARK_USE_SUN_FALLBACK,
    SUN_DARK_ELEVATION_DEG,
)
from custom_components.universal_room_automation.lighting.darkness import (
    is_dark_fallback,
)


class _FakeStates:
    def __init__(self, states: dict) -> None:
        self._states = states

    def get(self, entity_id: str):
        return self._states.get(entity_id)


class _FakeState:
    def __init__(self, state, attributes=None) -> None:
        self.state = state
        self.attributes = attributes or {}


def _hass(states: dict | None = None):
    return SimpleNamespace(states=_FakeStates(states or {}))


# ---------------------------------------------------------------------------
# Path 3: nothing configured, no hass → False.
# ---------------------------------------------------------------------------

def test_no_config_no_hass_returns_false():
    assert is_dark_fallback({}, None) is False


def test_no_config_with_hass_but_no_sun_state_returns_false():
    assert is_dark_fallback({}, _hass()) is False


# ---------------------------------------------------------------------------
# Path 2: sun fallback.
# ---------------------------------------------------------------------------

def test_sun_below_civil_dusk_is_dark():
    hass = _hass({"sun.sun": _FakeState("below_horizon", {"elevation": -10.0})})
    assert is_dark_fallback({}, hass) is True


def test_sun_above_civil_dusk_not_dark():
    hass = _hass({"sun.sun": _FakeState("above_horizon", {"elevation": 5.0})})
    assert is_dark_fallback({}, hass) is False


def test_sun_exactly_at_threshold_is_not_dark():
    """Strict less-than: elevation == threshold is NOT dark."""
    hass = _hass({"sun.sun": _FakeState("below_horizon",
                                        {"elevation": SUN_DARK_ELEVATION_DEG})})
    assert is_dark_fallback({}, hass) is False


def test_kill_switch_off_disables_sun_fallback():
    """Per-room CONF_LIGHT_DARK_USE_SUN_FALLBACK=False preserves today's False."""
    hass = _hass({"sun.sun": _FakeState("below_horizon", {"elevation": -10.0})})
    assert is_dark_fallback({CONF_LIGHT_DARK_USE_SUN_FALLBACK: False}, hass) is False


def test_kill_switch_default_true():
    hass = _hass({"sun.sun": _FakeState("below_horizon", {"elevation": -10.0})})
    # No key set at all → default TRUE → fallback engages.
    assert is_dark_fallback({}, hass) is True


def test_sun_missing_elevation_attribute_returns_false():
    hass = _hass({"sun.sun": _FakeState("below_horizon", {})})
    assert is_dark_fallback({}, hass) is False


def test_sun_unavailable_returns_false():
    hass = _hass({"sun.sun": _FakeState("unavailable")})
    assert is_dark_fallback({}, hass) is False


def test_sun_bad_elevation_type_returns_false():
    hass = _hass({"sun.sun": _FakeState("below_horizon", {"elevation": "nope"})})
    assert is_dark_fallback({}, hass) is False


# ---------------------------------------------------------------------------
# Path 1: borrowed lux.
# ---------------------------------------------------------------------------

def test_borrow_lux_available_below_threshold_is_dark():
    cfg = {
        CONF_LIGHT_DARK_LUX_SOURCE: "sensor.other_room_lux",
        CONF_ILLUMINANCE_THRESHOLD: 50,
    }
    hass = _hass({"sensor.other_room_lux": _FakeState("5")})
    assert is_dark_fallback(cfg, hass) is True


def test_borrow_lux_available_above_threshold_not_dark():
    cfg = {
        CONF_LIGHT_DARK_LUX_SOURCE: "sensor.other_room_lux",
        CONF_ILLUMINANCE_THRESHOLD: 50,
    }
    hass = _hass({"sensor.other_room_lux": _FakeState("500")})
    assert is_dark_fallback(cfg, hass) is False


def test_borrow_lux_unavailable_falls_through_to_sun():
    """R2-3: availability-only. Unavailable borrow → skip → try sun."""
    cfg = {
        CONF_LIGHT_DARK_LUX_SOURCE: "sensor.other_room_lux",
        CONF_ILLUMINANCE_THRESHOLD: 50,
    }
    hass = _hass({
        "sensor.other_room_lux": _FakeState("unavailable"),
        "sun.sun": _FakeState("below_horizon", {"elevation": -10.0}),
    })
    assert is_dark_fallback(cfg, hass) is True


def test_borrow_lux_unknown_falls_through_to_sun():
    cfg = {CONF_LIGHT_DARK_LUX_SOURCE: "sensor.other_room_lux"}
    hass = _hass({
        "sensor.other_room_lux": _FakeState("unknown"),
        "sun.sun": _FakeState("below_horizon", {"elevation": -10.0}),
    })
    assert is_dark_fallback(cfg, hass) is True


def test_borrow_lux_missing_entity_falls_through_to_sun():
    cfg = {CONF_LIGHT_DARK_LUX_SOURCE: "sensor.nonexistent"}
    hass = _hass({
        "sun.sun": _FakeState("below_horizon", {"elevation": -10.0}),
    })
    assert is_dark_fallback(cfg, hass) is True


def test_borrow_lux_bad_value_falls_through_to_sun():
    cfg = {CONF_LIGHT_DARK_LUX_SOURCE: "sensor.other_room_lux"}
    hass = _hass({
        "sensor.other_room_lux": _FakeState("banana"),
        "sun.sun": _FakeState("below_horizon", {"elevation": -10.0}),
    })
    assert is_dark_fallback(cfg, hass) is True


# ---------------------------------------------------------------------------
# Interaction discriminator — the D0 AFFECTED cases.
# ---------------------------------------------------------------------------

def test_affected_no_sensor_room_after_dusk_becomes_dark():
    """D0 case 2: no lux sensor + turn_on_if_dark + after dusk → NEW dark=True."""
    hass = _hass({"sun.sun": _FakeState("below_horizon", {"elevation": -10.0})})
    # No CONF_ILLUMINANCE_SENSOR, no borrow, kill switch default TRUE.
    assert is_dark_fallback({}, hass) is True


def test_affected_no_sensor_room_before_dusk_stays_not_dark():
    hass = _hass({"sun.sun": _FakeState("above_horizon", {"elevation": 10.0})})
    assert is_dark_fallback({}, hass) is False
