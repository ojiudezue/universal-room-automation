"""HVAC-NIGHT-TAIL-STARTS-TOO-EARLY-1 (B) — night holds follow house Sleep.

Plan: docs/planning/PLANNING_hvac_night_tail_follows_sleep.md, deliverable B.

INV-NT: for every non-hallway room and every falling edge handled while the
house state is H, the armed tail is the room's NIGHT value iff
H in HVAC_NIGHT_HOLD_STATES == ("sleep", "waking"); otherwise the DAY value.
FAN_TRUST_STATES (fans, D7) is unchanged.

Mutation anchor: put `FAN_TRUST_STATES` back in the selector at
`hvac_zones.ZoneManager._effective_hvac_hold_seconds` and
`test_home_night_uses_day_hold` + `test_producer_home_night_arms_day_tail`
go RED.

Imports the REAL package path (no HA stubs, no sys.modules mutation), the same
pattern as test_hvac_live_room_establishment.py.
"""
from __future__ import annotations

import inspect
import os
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from custom_components.universal_room_automation.const import (  # noqa: E402
    ROOM_TYPE_BEDROOM,
    ROOM_TYPE_COMMON_AREA,
    ROOM_TYPE_HVAC_HOLD,
    ROOM_TYPE_HVAC_HOLD_NIGHT,
    ROOM_TYPE_MEDIA_ROOM,
)
from custom_components.universal_room_automation.domain_coordinators import (  # noqa: E402
    hvac_const as _hvac_const,
    hvac_zones as _hvac_zones,
)

ZoneManager = _hvac_zones.ZoneManager

# 2026-09-27 21:30 CDT (house in home_night, before the 22:00 Sleep hour).
NOW = datetime(2026, 9, 28, 2, 30, 0, tzinfo=timezone.utc)

_ROOM_TYPES = (ROOM_TYPE_BEDROOM, ROOM_TYPE_COMMON_AREA, ROOM_TYPE_MEDIA_ROOM)
_NON_NIGHT_STATES = (
    "home_night", "home_evening", "home_day", "guest", "arriving", "away",
)


def _zm() -> ZoneManager:
    return ZoneManager(MagicMock())


# ---------------------------------------------------------------------------
# Selector (helper) behaviour
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("room_type", _ROOM_TYPES)
def test_home_night_uses_day_hold(room_type):
    """home_night (21:00-22:00) arms the DAY hold for bedroom, common room
    and media room — not the 30/15/30-min night hold."""
    zm = _zm()
    got = zm._effective_hvac_hold_seconds(room_type, "home_night")
    assert got == ROOM_TYPE_HVAC_HOLD[room_type], (
        f"{room_type} in home_night must use the day hold "
        f"{ROOM_TYPE_HVAC_HOLD[room_type]}s; got {got}s"
    )
    assert got != ROOM_TYPE_HVAC_HOLD_NIGHT[room_type]


def test_home_night_day_values_are_the_expected_literals():
    """Independent oracle (not read from the tables): bedroom 60, common 60,
    media 120 in home_night."""
    zm = _zm()
    assert zm._effective_hvac_hold_seconds(ROOM_TYPE_BEDROOM, "home_night") == 60
    assert zm._effective_hvac_hold_seconds(ROOM_TYPE_COMMON_AREA, "home_night") == 60
    assert zm._effective_hvac_hold_seconds(ROOM_TYPE_MEDIA_ROOM, "home_night") == 120


def test_night_states_use_night_hold():
    """sleep and waking give the night hold (bedroom 1800); every other
    house state gives the day hold (bedroom 60)."""
    zm = _zm()
    for hs in ("sleep", "waking"):
        assert zm._effective_hvac_hold_seconds(ROOM_TYPE_BEDROOM, hs) == 1800, hs
    assert zm._effective_hvac_hold_seconds(ROOM_TYPE_MEDIA_ROOM, "sleep") == 1800
    assert zm._effective_hvac_hold_seconds(ROOM_TYPE_COMMON_AREA, "waking") == 900
    for hs in _NON_NIGHT_STATES + (None,):
        assert zm._effective_hvac_hold_seconds(ROOM_TYPE_BEDROOM, hs) == 60, hs


@pytest.mark.parametrize("house_state,expected", [
    ("sleep", 5400),
    ("waking", 5400),
    ("home_night", 60),
    ("home_evening", 60),
    ("home_day", 60),
])
def test_per_room_night_override_applies_only_in_sleep_or_waking(
    house_state, expected,
):
    """Jaya-style per-room hvac_vacancy_hold_night=5400 applies only in
    sleep / waking; in home_night the (table) day value applies."""
    zm = _zm()
    got = zm._effective_hvac_hold_seconds(
        ROOM_TYPE_BEDROOM, house_state,
        override_day=None, override_night=5400,
        room_name="Jaya Bedroom",
    )
    assert got == expected, (house_state, got)


def test_common_room_night_override_90_only_in_sleep():
    """Deliverable A's 90 s common-room override: 90 in sleep, 60 (day) in
    home_night."""
    zm = _zm()
    assert zm._effective_hvac_hold_seconds(
        ROOM_TYPE_COMMON_AREA, "sleep", override_night=90,
    ) == 90
    assert zm._effective_hvac_hold_seconds(
        ROOM_TYPE_COMMON_AREA, "home_night", override_night=90,
    ) == 60


# ---------------------------------------------------------------------------
# FAN_TRUST_STATES guard (plan §3)
# ---------------------------------------------------------------------------

def test_fan_trust_states_unchanged_and_not_read_by_selector():
    assert _hvac_const.FAN_TRUST_STATES == ("home_night", "sleep", "waking")
    assert _hvac_const.HVAC_NIGHT_HOLD_STATES == ("sleep", "waking")
    src = inspect.getsource(ZoneManager._effective_hvac_hold_seconds)
    assert "FAN_TRUST_STATES" not in src
    assert "HVAC_NIGHT_HOLD_STATES" in src


# ---------------------------------------------------------------------------
# Wire-in anchors: drive the real caller `_compute_hvac_occupied`
# ---------------------------------------------------------------------------

def _falling_edge(zm, *, room_type, house_state, override_night=None,
                  room_name="r1"):
    zm._compute_hvac_occupied(
        room_name=room_name, room_type=room_type, state_occupied=True,
        now=NOW - timedelta(minutes=5), house_state=house_state,
        override_night=override_night,
    )
    out = zm._compute_hvac_occupied(
        room_name=room_name, room_type=room_type, state_occupied=False,
        now=NOW, house_state=house_state, override_night=override_night,
    )
    return out


@pytest.mark.parametrize("room_type,day_s", [
    (ROOM_TYPE_BEDROOM, 60),
    (ROOM_TYPE_COMMON_AREA, 60),
    (ROOM_TYPE_MEDIA_ROOM, 120),
])
def test_producer_home_night_arms_day_tail(room_type, day_s):
    """Falling edge in home_night through the real producer arms a DAY tail
    and releases once it expires (not 30 min later)."""
    zm = _zm()
    assert _falling_edge(zm, room_type=room_type, house_state="home_night") is True
    assert zm._hvac_tail_until["r1"] == NOW + timedelta(seconds=day_s)
    assert zm._hvac_arm_source["r1"] == "tail"
    # One tick past the day tail -> released.
    out = zm._compute_hvac_occupied(
        room_name="r1", room_type=room_type, state_occupied=False,
        now=NOW + timedelta(seconds=day_s + 1), house_state="home_night",
    )
    assert out is False
    assert zm._hvac_arm_source["r1"] == "released_tail_expired"


@pytest.mark.parametrize("house_state", ["sleep", "waking"])
def test_producer_sleep_arms_night_tail(house_state):
    zm = _zm()
    assert _falling_edge(zm, room_type=ROOM_TYPE_BEDROOM,
                         house_state=house_state) is True
    assert zm._hvac_tail_until["r1"] == NOW + timedelta(seconds=1800)


def test_producer_per_room_night_override_only_in_sleep():
    """Jaya's 5400 s override through the real producer: 5400 in sleep,
    day 60 in home_night."""
    zm = _zm()
    _falling_edge(zm, room_type=ROOM_TYPE_BEDROOM, house_state="sleep",
                  override_night=5400, room_name="jaya")
    assert zm._hvac_tail_until["jaya"] == NOW + timedelta(seconds=5400)

    zm2 = _zm()
    _falling_edge(zm2, room_type=ROOM_TYPE_BEDROOM, house_state="home_night",
                  override_night=5400, room_name="jaya")
    assert zm2._hvac_tail_until["jaya"] == NOW + timedelta(seconds=60)
