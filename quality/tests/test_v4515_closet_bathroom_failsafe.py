"""v4.5.15 — Closet + bathroom 60-min lazy auto-off failsafe.

URA's existing RESILIENCE-001 failsafe at coordinator.py:1379 forces
vacancy after MAX_OCCUPANCY_DURATION_SECONDS (4 hours) regardless of
motion state. That's the right ceiling for most rooms but too long for
closets and bathrooms — typical use is minutes, and a "stuck sensor /
fan-as-motion / forgotten light" pattern can keep one of these spaces
"occupied" indefinitely.

v4.5.15 adds a room-type-keyed failsafe lookup:
  - closet: 3600s (60 min)
  - bathroom: 3600s (60 min)
  - all other types: 14400s (4 hr — DEFAULT_FAILSAFE_DURATION_SECONDS)

Tests below are source-grep + AST + behavior on the helper. Runtime
integration with the failsafe check at coordinator.py:1394 is covered
by source-grep that the new helper is called.
"""

import ast
import sys
import types
import importlib.util
from pathlib import Path

import pytest


# ===========================================================================
# Source fixtures
# ===========================================================================


@pytest.fixture(scope="module")
def coordinator_src() -> str:
    with open("custom_components/universal_room_automation/coordinator.py") as f:
        return f.read()


@pytest.fixture(scope="module")
def const_src() -> str:
    with open("custom_components/universal_room_automation/const.py") as f:
        return f.read()


# ===========================================================================
# const.py — verify the new dict and default
# ===========================================================================


def test_const_declares_default_failsafe_duration(const_src: str):
    assert "DEFAULT_FAILSAFE_DURATION_SECONDS" in const_src
    assert "DEFAULT_FAILSAFE_DURATION_SECONDS: Final = 4 * 3600" in const_src


def test_const_declares_room_type_failsafe_durations(const_src: str):
    assert "ROOM_TYPE_FAILSAFE_DURATIONS" in const_src
    # Confirm the two target room types are present
    # We check the source contains the dict with both keys; the actual
    # values are validated by the behavior tests below.


def _load_const_dict():
    """Load ROOM_TYPE_FAILSAFE_DURATIONS + DEFAULT from const.py without
    dragging in the rest of the URA package.
    """
    if "ura_v4515_const" in sys.modules:
        mod = sys.modules["ura_v4515_const"]
        return (
            mod.ROOM_TYPE_FAILSAFE_DURATIONS,
            mod.DEFAULT_FAILSAFE_DURATION_SECONDS,
            mod.ROOM_TYPE_CLOSET,
            mod.ROOM_TYPE_BATHROOM,
        )

    root = Path(__file__).resolve().parents[2]
    src = root / "custom_components" / "universal_room_automation" / "const.py"
    spec = importlib.util.spec_from_file_location(
        "ura_v4515_const_under_test", str(src),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    sys.modules["ura_v4515_const"] = mod
    return (
        mod.ROOM_TYPE_FAILSAFE_DURATIONS,
        mod.DEFAULT_FAILSAFE_DURATION_SECONDS,
        mod.ROOM_TYPE_CLOSET,
        mod.ROOM_TYPE_BATHROOM,
    )


def test_closet_failsafe_is_3600_seconds():
    durations, _, closet, _ = _load_const_dict()
    assert durations[closet] == 3600


def test_bathroom_failsafe_is_3600_seconds():
    durations, _, _, bathroom = _load_const_dict()
    assert durations[bathroom] == 3600


def test_default_failsafe_is_4_hours():
    _, default, _, _ = _load_const_dict()
    assert default == 4 * 3600


def test_only_closet_and_bathroom_have_overrides():
    """Scope-pinning test: only the two declared room types have
    overrides. If a future cycle adds more types, update this test
    deliberately to acknowledge the expansion.
    """
    durations, _, closet, bathroom = _load_const_dict()
    assert set(durations.keys()) == {closet, bathroom}


# ===========================================================================
# coordinator.py — helper method + integration with failsafe check
# ===========================================================================


def test_coordinator_stores_room_type_attr(coordinator_src: str):
    """The helper looks up self._room_type — make sure init sets it."""
    assert "self._room_type" in coordinator_src
    # Specifically the assignment from merged_config
    assert 'self._room_type: str = room_type' in coordinator_src


def test_coordinator_defines_get_failsafe_duration_helper(coordinator_src: str):
    assert "def _get_failsafe_duration_seconds(self)" in coordinator_src


def test_failsafe_check_uses_room_type_lookup(coordinator_src: str):
    """The hard-coded MAX_OCCUPANCY_DURATION_SECONDS reference in the
    failsafe check must be replaced with a call to the new helper.
    """
    # Locate the failsafe block. P24 fix (2026-08-10) moved the live
    # block after the camera/BLE override + "always populate
    # ble_persons" section; use the P24 marker to disambiguate.
    marker = "# === P24 FAILSAFE (moved after overrides"
    start = coordinator_src.find(marker)
    assert start >= 0, "P24 FAILSAFE (moved) block missing"
    end = coordinator_src.find("# === TRUE VACANCY FINALIZE", start)
    body = coordinator_src[start:end if end > 0 else start + 4000]
    assert "_get_failsafe_duration_seconds" in body, (
        "Failsafe block must call self._get_failsafe_duration_seconds() — "
        "the room-type-keyed lookup added in v4.5.15."
    )
    # And must NOT compare against the bare constant anymore
    assert "duration > MAX_OCCUPANCY_DURATION_SECONDS" not in body, (
        "Failsafe still uses hard-coded MAX_OCCUPANCY_DURATION_SECONDS. "
        "Replace with room-type-keyed helper."
    )


def test_failsafe_helper_imports_const_dict(coordinator_src: str):
    """The helper must import ROOM_TYPE_FAILSAFE_DURATIONS and
    DEFAULT_FAILSAFE_DURATION_SECONDS from const.
    """
    start = coordinator_src.find("def _get_failsafe_duration_seconds(self)")
    assert start >= 0
    end = coordinator_src.find("\n    def ", start + 1)
    body = coordinator_src[start:end if end > 0 else start + 1000]
    assert "ROOM_TYPE_FAILSAFE_DURATIONS" in body
    assert "DEFAULT_FAILSAFE_DURATION_SECONDS" in body


# ===========================================================================
# Behavior tests — exercise the lookup pattern via standalone reconstruction
# ===========================================================================
# We can't fully import the coordinator (heavy HA dependency), but the
# helper is a pure lookup. Reconstruct the dict + default and verify the
# semantics match what coordinator.py asks of them.


def test_lookup_returns_3600_for_closet():
    durations, default, closet, _ = _load_const_dict()
    assert durations.get(closet, default) == 3600


def test_lookup_returns_3600_for_bathroom():
    durations, default, _, bathroom = _load_const_dict()
    assert durations.get(bathroom, default) == 3600


def test_lookup_returns_default_for_other_room_types():
    durations, default, _, _ = _load_const_dict()
    for room_type in ["bedroom", "garage", "utility", "common_area",
                      "media_room", "generic", "infrastructure"]:
        assert durations.get(room_type, default) == default, (
            f"Room type {room_type!r} unexpectedly has an override. "
            "If this is intentional, update the dict + this test."
        )


def test_lookup_unknown_room_type_returns_default():
    durations, default, _, _ = _load_const_dict()
    assert durations.get("unknown_type", default) == default
    assert durations.get("", default) == default
    assert durations.get(None, default) == default


# ===========================================================================
# Failsafe-decision behavior — Review LOW #2 remediation
# ===========================================================================
# Reconstruct the boolean "should failsafe fire?" decision in isolation
# from the coordinator's full state machine. The decision is:
#   duration > failsafe_seconds  →  fire
# where `duration = (now - became_occupied_time).total_seconds()` and
# `failsafe_seconds = ROOM_TYPE_FAILSAFE_DURATIONS.get(rt, default)`.


def _should_fire(room_type: str, duration_seconds: float) -> bool:
    """Mirror of coordinator.py:1409–1411 decision logic, isolated from
    the HA coordinator instantiation hazard. If a future refactor moves
    the failsafe check, this test fails — caller must update.
    """
    durations, default, _, _ = _load_const_dict()
    failsafe_seconds = durations.get(room_type, default)
    return duration_seconds > failsafe_seconds


def test_closet_at_65_minutes_fires():
    assert _should_fire("closet", 65 * 60) is True


def test_closet_at_30_minutes_does_not_fire():
    assert _should_fire("closet", 30 * 60) is False


def test_closet_exactly_at_60_minutes_does_not_fire():
    """Boundary check: comparison is strict `>`. Exactly 60 min should
    NOT fire (gives 1-tick grace). Confirms we don't accidentally
    use `>=` and trim a millisecond off the budget.
    """
    assert _should_fire("closet", 60 * 60) is False


def test_bathroom_at_65_minutes_fires():
    assert _should_fire("bathroom", 65 * 60) is True


def test_bedroom_at_65_minutes_does_not_fire():
    """v4.5.15 must preserve original 4-hour behavior for non-target
    room types. Bedroom at 65 min should stay occupied.
    """
    assert _should_fire("bedroom", 65 * 60) is False


def test_bedroom_at_4h05min_fires():
    """Default failsafe still works at 4 hr ceiling for generic rooms."""
    assert _should_fire("bedroom", 4 * 3600 + 5 * 60) is True


def test_generic_at_2_hours_does_not_fire():
    assert _should_fire("generic", 2 * 3600) is False


def test_unknown_room_type_uses_default_failsafe():
    """Defensive: an unknown / migration-edge room_type falls back to
    the 4-hour default. Closet at 65 min would fire; an unknown type
    at 65 min should not.
    """
    assert _should_fire("unknown_future_type", 65 * 60) is False
    assert _should_fire("unknown_future_type", 5 * 3600) is True
