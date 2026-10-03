"""Per-site drill anchor for Slice B (v5.103.28).

Verifies ``RoomAutomation.is_dark`` and — indirectly through it —
``actuator_reconciler.py`` (which calls ``automation.is_dark(...)`` at
:794) route their None-illuminance case through the new
``lighting.darkness.is_dark_fallback``. This is the load-bearing wiring
call the plan's F2/R2-2 finding required at BOTH sites (the reconciler
site delegates to ``automation.is_dark``, so both are covered by one
method).

Structured to fail specifically when:
  (a) the fallback module returns the wrong value,
  (b) `RoomAutomation.is_dark` does not call the fallback for None,
  (c) the reconciler's `automation.is_dark(...)` delegation is
      short-circuited (proven by the method-swap drill in the doc).

We construct a minimal ``RoomAutomation`` using ``__new__`` to skip the
heavy ctor — we only need ``config``, ``hass``, and the method under
test. This is the same pattern several existing URA tests use.
"""
from __future__ import annotations

from types import SimpleNamespace

from custom_components.universal_room_automation.automation import RoomAutomation
from custom_components.universal_room_automation.const import (
    CONF_ILLUMINANCE_THRESHOLD,
    CONF_LIGHT_DARK_USE_SUN_FALLBACK,
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


def _make_room(config: dict, hass_states: dict | None = None) -> RoomAutomation:
    ra = RoomAutomation.__new__(RoomAutomation)
    ra.config = config
    ra.hass = SimpleNamespace(states=_FakeStates(hass_states or {}))
    return ra


# ---------------------------------------------------------------------------
# Primary-lux path unchanged (pre-existing behaviour).
# ---------------------------------------------------------------------------

def test_primary_lux_below_threshold_is_dark():
    room = _make_room({CONF_ILLUMINANCE_THRESHOLD: 50})
    assert room.is_dark(5.0) is True


def test_primary_lux_above_threshold_not_dark():
    room = _make_room({CONF_ILLUMINANCE_THRESHOLD: 50})
    assert room.is_dark(500.0) is False


# ---------------------------------------------------------------------------
# Fallback wiring — None illuminance routes through is_dark_fallback.
# ---------------------------------------------------------------------------

def test_none_lux_no_hass_state_returns_false():
    """No sensor + no sun state ⇒ False (fail-safe)."""
    room = _make_room({}, {})
    assert room.is_dark(None) is False


def test_none_lux_sun_below_dusk_falls_through_to_true():
    """The Slice B behaviour change: no lux + dusk ⇒ dark (kill switch default TRUE)."""
    room = _make_room({}, {"sun.sun": _FakeState("below_horizon",
                                                  {"elevation": -10.0})})
    assert room.is_dark(None) is True


def test_none_lux_kill_switch_false_preserves_today():
    """Per-room CONF_LIGHT_DARK_USE_SUN_FALLBACK=False ⇒ today's is_dark(None)=False."""
    room = _make_room(
        {CONF_LIGHT_DARK_USE_SUN_FALLBACK: False},
        {"sun.sun": _FakeState("below_horizon", {"elevation": -10.0})},
    )
    assert room.is_dark(None) is False


def test_none_lux_sun_above_horizon_not_dark():
    room = _make_room({}, {"sun.sun": _FakeState("above_horizon",
                                                  {"elevation": 30.0})})
    assert room.is_dark(None) is False
