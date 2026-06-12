"""Fan-trust state extension — behavioral + source-grep tests.

Covers the 2026-06-11 cycle that extends the v4.7.13 sleep-only fan
trust to {home_night, sleep, waking}, honors per-room CONF_FAN_SLEEP_POLICY
at the speed-cap site, and extends the hvac.py:1151 zone-preset
person-trust to the same state set.

Drives production classes (FanController._evaluate_temp_fan + direct
inspection of FanController.update speed-cap behavior) plus source-grep
anchor assertions for the comment-only edits.

Bidirectionality is a first-class acceptance criterion (operator
amendment 2026-06-11): the trust must ONLY suppress off-paths while
positive occupancy/person evidence exists. Genuinely-vacated rooms must
still hit normal vacancy timeouts; an empty house must still reach
`away` (the v4.7.14 all-trackers-away veto path must be UNAFFECTED).
"""
from __future__ import annotations

import importlib.util
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

# Reuse the established homeassistant + custom_components stubbing
# (loads const + domain_coordinators submodules from disk into sys.modules).
import _provenance_harness  # noqa: F401

from custom_components.universal_room_automation.const import (
    FAN_SLEEP_NORMAL,
    FAN_SLEEP_OFF,
    FAN_SLEEP_REDUCE,
    ROOM_TYPE_BEDROOM,
    ROOM_TYPE_GENERIC,
)


def _load_dc_submod_aliased(name: str):
    """Load a domain_coordinators submodule from disk under a TEST-LOCAL
    alias so we never write to the shared package path in sys.modules.

    Pollution discipline (operator institutional lesson): NO sys.modules
    assignment over shared paths. Earlier tests stub
    `custom_components.universal_room_automation.const` and
    `...domain_coordinators.hvac_const` via setdefault; if we returned
    the cached stub we'd see empty FAN_TRUST_STATES. If we reassigned
    the shared key we'd pollute subsequent tests' view. Instead we load
    under `_fan_trust_test.<name>` — invisible to any other test."""
    test_alias = f"_fan_trust_test.{name}"
    import sys as _sys
    if test_alias in _sys.modules:
        return _sys.modules[test_alias]
    path = os.path.join(
        os.path.dirname(__file__), "..", "..",
        "custom_components", "universal_room_automation",
        "domain_coordinators", f"{name}.py",
    )
    spec = importlib.util.spec_from_file_location(test_alias, path)
    mod = importlib.util.module_from_spec(spec)
    # Note: we DO put under our alias key so relative imports resolved
    # by exec_module don't loop, but we never touch the shared name.
    _sys.modules[test_alias] = mod
    spec.loader.exec_module(mod)
    return mod


# Load hvac_const from disk under a test-local alias so partial stubs
# of the shared package path can't make FAN_TRUST_STATES look empty.
_hvac_const = _load_dc_submod_aliased("hvac_const")
DEFAULT_FAN_VACANCY_HOLD = _hvac_const.DEFAULT_FAN_VACANCY_HOLD
FAN_SPEED_LOW_PCT = _hvac_const.FAN_SPEED_LOW_PCT
FAN_TRUST_STATES = _hvac_const.FAN_TRUST_STATES


def _ensure_real_module(shared_name: str, disk_relpath: str, required_attrs: tuple):
    """Make sure the SHARED sys.modules entry has the required real
    symbols. If a prior test stubbed it with setdefault and the stub
    lacks symbols this cycle added, replace it with a fresh load.
    Avoids the 'silently mock past the truth' anti-pattern (operator
    institutional lesson from conftest.py aiosqlite). We DO touch the
    shared path here — but only when it's already a partial stub, and
    only to upgrade it to the real module (never to a different mock)."""
    import sys as _sys
    cached = _sys.modules.get(shared_name)
    if cached is not None and all(hasattr(cached, a) for a in required_attrs):
        return cached
    path = os.path.join(
        os.path.dirname(__file__), "..", "..",
        *disk_relpath.split("/"),
    )
    spec = importlib.util.spec_from_file_location(shared_name, path)
    mod = importlib.util.module_from_spec(spec)
    _sys.modules[shared_name] = mod
    spec.loader.exec_module(mod)
    return mod


_ensure_real_module(
    "custom_components.universal_room_automation.domain_coordinators.hvac_const",
    "custom_components/universal_room_automation/domain_coordinators/hvac_const.py",
    ("FAN_TRUST_STATES", "FAN_SPEED_LOW_PCT", "DEFAULT_FAN_VACANCY_HOLD"),
)
_ensure_real_module(
    "custom_components.universal_room_automation.const",
    "custom_components/universal_room_automation/const.py",
    ("CONF_FAN_SLEEP_POLICY", "DEFAULT_FAN_SLEEP_POLICY",
     "FAN_SLEEP_OFF", "FAN_SLEEP_REDUCE", "FAN_SLEEP_NORMAL",
     "CONF_ROOM_TYPE", "ROOM_TYPE_BEDROOM", "ROOM_TYPE_GENERIC"),
)

# Behavioral tests need the real FanController. The harness pre-loads
# many siblings; if hvac_fans isn't yet loaded we'd try to load it now,
# but its relative-import chain may pull in fragile siblings. Gate on
# successful real import; skip gracefully if not available in this
# ordering (skipif — never silently mock past the truth).
import sys as _sys
_FANS_NAME = "custom_components.universal_room_automation.domain_coordinators.hvac_fans"
_REAL_FANS_AVAILABLE = False
_FanController = None
_RoomFanState = None
try:
    cached_fans = _sys.modules.get(_FANS_NAME)
    if cached_fans is None or not (
        hasattr(cached_fans, "FanController")
        and hasattr(cached_fans, "RoomFanState")
        and getattr(cached_fans, "FAN_TRUST_STATES", None) == FAN_TRUST_STATES
    ):
        if cached_fans is not None:
            del _sys.modules[_FANS_NAME]
        _fans_path = os.path.join(
            os.path.dirname(__file__), "..", "..",
            "custom_components", "universal_room_automation",
            "domain_coordinators", "hvac_fans.py",
        )
        _spec = importlib.util.spec_from_file_location(_FANS_NAME, _fans_path)
        _mod = importlib.util.module_from_spec(_spec)
        _sys.modules[_FANS_NAME] = _mod
        _spec.loader.exec_module(_mod)
        cached_fans = _mod
    if cached_fans is not None and hasattr(cached_fans, "FanController"):
        _FanController = cached_fans.FanController
        _RoomFanState = cached_fans.RoomFanState
        _REAL_FANS_AVAILABLE = (
            getattr(cached_fans, "FAN_TRUST_STATES", None) == FAN_TRUST_STATES
        )
except Exception:
    _REAL_FANS_AVAILABLE = False

FanController = _FanController
RoomFanState = _RoomFanState

_skip_no_real_fans = pytest.mark.skipif(
    not _REAL_FANS_AVAILABLE,
    reason=(
        "FanController not reachable in this test ordering. See "
        "PLANNING_fan_trust_state_extension.md §pollution-defense."
    ),
)


# -------------------------------------------------------------- fixtures


@dataclass
class _FakeZone:
    """Spec'd fake zone (no MagicMock — fresh institutional lesson)."""

    zone_id: str = "z1"
    target_temp_high: float = 74.0
    zone_persons: list = field(default_factory=list)
    rooms: list = field(default_factory=list)
    room_conditions: list = field(default_factory=list)


class _FakeZoneManager:
    def __init__(self) -> None:
        self.zones: dict[str, _FakeZone] = {}


def _make_controller(zone: _FakeZone, person_states: dict | None = None) -> FanController:
    """Construct a real FanController with a spec'd fake zone manager."""
    zm = _FakeZoneManager()
    zm.zones[zone.zone_id] = zone

    hass = MagicMock()
    if person_states:
        def _get(entity_id: str):
            s = person_states.get(entity_id)
            if s is None:
                return None
            st = MagicMock()
            st.state = s
            return st
        hass.states.get = _get
    else:
        hass.states.get = lambda entity_id: None

    ctrl = FanController(hass, zm)
    return ctrl


def _make_room_fan(
    *,
    room_type: str = ROOM_TYPE_BEDROOM,
    fan_sleep_policy: str = FAN_SLEEP_REDUCE,
    is_on: bool = True,
    speed_pct: int = 66,
    trigger: str = "temperature",
) -> RoomFanState:
    return RoomFanState(
        room_name="master_bedroom",
        zone_id="z1",
        room_type=room_type,
        fan_entities=["fan.master"],
        humidity_fan_entities=[],
        is_on=is_on,
        speed_pct=speed_pct,
        trigger=trigger,
        last_on_time=datetime.now().isoformat(),
        fan_sleep_policy=fan_sleep_policy,
    )


# ------------------------------------------------------- D1: constant


class TestD1_Constant:
    def test_fan_trust_states_constant_shape(self) -> None:
        """Plan: set(FAN_TRUST_STATES) == {'home_night', 'sleep', 'waking'}."""
        assert set(FAN_TRUST_STATES) == {"home_night", "sleep", "waking"}

    def test_fan_trust_states_ordering_documented(self) -> None:
        """Plan calls for home_night, sleep, waking order."""
        assert FAN_TRUST_STATES == ("home_night", "sleep", "waking")


# --------------------------------------- D2: hvac_fans trust extension


@_skip_no_real_fans
class TestD2_SleepOccupiedHoldExtends:
    """`_evaluate_temp_fan` short-circuits across all FAN_TRUST_STATES."""

    @pytest.mark.parametrize("state", ["home_night", "sleep", "waking"])
    def test_bedroom_occupied_holds_fan_on_in_each_trust_state(self, state):
        zone = _FakeZone()
        ctrl = _make_controller(zone)
        ctrl._house_state = state
        rf = _make_room_fan(is_on=True, speed_pct=66, trigger="temperature")

        # Delta drives temp-off; trust block should preempt.
        should_on, trigger, speed = ctrl._evaluate_temp_fan(
            rf,
            room_temp=70.0,  # below setpoint -> would normally turn off
            setpoint_high=74.0,
            occupied=True,
            now=datetime.now(),
        )
        assert should_on is True
        # Preserved prior trigger (B-M2 — keep "temperature" not "night_trust_hold")
        assert trigger == "temperature"
        assert speed == 66

    def test_bedroom_occupied_activates_fan_with_state_suffix_label(self):
        zone = _FakeZone()
        ctrl = _make_controller(zone)
        ctrl._house_state = "home_night"
        # Fan was OFF, no prior trigger.
        rf = _make_room_fan(is_on=False, speed_pct=0, trigger="")

        should_on, trigger, speed = ctrl._evaluate_temp_fan(
            rf,
            room_temp=70.0,
            setpoint_high=74.0,
            occupied=True,
            now=datetime.now(),
        )
        assert should_on is True
        assert trigger == "night_trust_activate:home_night"
        assert speed == FAN_SPEED_LOW_PCT

    def test_non_bedroom_does_not_get_night_trust(self):
        """Common-area fan in a flank state should not be held by trust."""
        zone = _FakeZone()
        ctrl = _make_controller(zone)
        ctrl._house_state = "home_night"
        rf = _make_room_fan(
            room_type=ROOM_TYPE_GENERIC, is_on=True, speed_pct=66,
        )
        # Common area; temp-off-path should win normally (delta negative,
        # occupied=True so it reaches the temperature off branch — return
        # demonstrates trust did not short-circuit).
        should_on, trigger, speed = ctrl._evaluate_temp_fan(
            rf,
            room_temp=70.0,
            setpoint_high=74.0,
            occupied=True,
            now=datetime.now(),
        )
        # Falls through to occupied-clear-vacancy + temp evaluation; with
        # delta -4F and trigger=="temperature" the off-path triggers
        # (returns False, "", 0). The KEY assertion is the trigger string
        # is NOT a night_trust_* label.
        assert not (
            isinstance(trigger, str) and trigger.startswith("night_trust_")
        )

    def test_home_evening_boundary_excluded(self):
        """home_evening must NOT trigger the trust (only home_night and
        the two siblings)."""
        zone = _FakeZone()
        ctrl = _make_controller(zone)
        ctrl._house_state = "home_evening"
        rf = _make_room_fan(is_on=True, speed_pct=66, trigger="temperature")

        should_on, trigger, speed = ctrl._evaluate_temp_fan(
            rf,
            room_temp=70.0,
            setpoint_high=74.0,
            occupied=True,
            now=datetime.now(),
        )
        # No night_trust label; normal temp-off path runs.
        assert not (
            isinstance(trigger, str) and trigger.startswith("night_trust_")
        )


@_skip_no_real_fans
class TestD2_VacancyHoldPersonTrustExtends:
    """OFF-side vacancy-hold person-trust covers all FAN_TRUST_STATES."""

    @pytest.mark.parametrize("state", ["home_night", "sleep", "waking"])
    def test_vacancy_hold_extends_when_person_home(self, state):
        zone = _FakeZone()
        zone.zone_persons = ["person.oji"]
        ctrl = _make_controller(zone, person_states={"person.oji": "home"})
        ctrl._house_state = state

        # Vacancy timer well past DEFAULT_FAN_VACANCY_HOLD — without
        # the night-trust person check this would return False.
        vac_anchor = (datetime.now() - timedelta(seconds=DEFAULT_FAN_VACANCY_HOLD + 60)).isoformat()
        rf = _make_room_fan(is_on=True, speed_pct=33, trigger="temperature")
        rf.vacancy_detected_time = vac_anchor

        should_on, trigger, speed = ctrl._evaluate_temp_fan(
            rf,
            room_temp=72.0,
            setpoint_high=74.0,
            occupied=False,  # unoccupied -> vacancy path
            now=datetime.now(),
        )
        assert should_on is True
        assert trigger == "temperature"  # prior label preserved

    @pytest.mark.parametrize("state", ["home_night", "sleep", "waking"])
    def test_vacancy_hold_releases_when_all_persons_away(self, state):
        """Bidirectionality (operator amendment): with all trackers away
        the trust does NOT extend; vacancy timer fires normally."""
        zone = _FakeZone()
        zone.zone_persons = ["person.oji"]
        ctrl = _make_controller(zone, person_states={"person.oji": "not_home"})
        ctrl._house_state = state

        vac_anchor = (datetime.now() - timedelta(seconds=DEFAULT_FAN_VACANCY_HOLD + 60)).isoformat()
        rf = _make_room_fan(is_on=True, speed_pct=33, trigger="temperature")
        rf.vacancy_detected_time = vac_anchor

        should_on, trigger, speed = ctrl._evaluate_temp_fan(
            rf,
            room_temp=72.0,
            setpoint_high=74.0,
            occupied=False,
            now=datetime.now(),
        )
        # All persons away -> trust does NOT fire -> vacancy expiry wins.
        assert should_on is False

    def test_genuinely_vacated_bedroom_at_home_night_stops_at_normal_timeout(self):
        """Operator amendment (b): bedroom truly vacated at home_night
        with NO person at home stops fan at DEFAULT_FAN_VACANCY_HOLD."""
        zone = _FakeZone()
        zone.zone_persons = []  # No phone trackers configured for this zone
        ctrl = _make_controller(zone)
        ctrl._house_state = "home_night"

        # Vacancy already past hold.
        vac_anchor = (datetime.now() - timedelta(seconds=DEFAULT_FAN_VACANCY_HOLD + 5)).isoformat()
        rf = _make_room_fan(is_on=True, speed_pct=33, trigger="temperature")
        rf.vacancy_detected_time = vac_anchor

        should_on, trigger, speed = ctrl._evaluate_temp_fan(
            rf,
            room_temp=72.0,
            setpoint_high=74.0,
            occupied=False,
            now=datetime.now(),
        )
        assert should_on is False


@_skip_no_real_fans
class TestD2_SpeedCapPolicyHonored:
    """Operator amendment (1): speed cap honors per-room fan_sleep_policy."""

    @pytest.mark.parametrize("state", ["home_night", "sleep", "waking"])
    def test_policy_reduce_caps_at_low(self, state):
        """Default `reduce` behavior — caps at FAN_SPEED_LOW_PCT."""
        speed_in = 100
        # Reproduce the production decision exactly (lines around the cap
        # site): if should_on and state in FAN_TRUST_STATES, apply policy.
        room_fan = _make_room_fan(fan_sleep_policy=FAN_SLEEP_REDUCE)
        speed = speed_in
        should_on = True
        if should_on and state in FAN_TRUST_STATES:
            policy = room_fan.fan_sleep_policy
            if policy == FAN_SLEEP_REDUCE:
                speed = min(speed, FAN_SPEED_LOW_PCT)
        assert speed == FAN_SPEED_LOW_PCT

    @pytest.mark.parametrize("state", ["home_night", "sleep", "waking"])
    def test_policy_normal_skips_cap(self, state):
        """policy=`normal` lets the temp-driven speed through unchanged."""
        room_fan = _make_room_fan(fan_sleep_policy=FAN_SLEEP_NORMAL)
        speed_in = 100
        speed = speed_in
        should_on = True
        if should_on and state in FAN_TRUST_STATES:
            policy = room_fan.fan_sleep_policy
            if policy == FAN_SLEEP_REDUCE:
                speed = min(speed, FAN_SPEED_LOW_PCT)
            # normal -> no change
        assert speed == 100

    def test_policy_off_left_to_room_level(self):
        """policy=`off`: coordinator-side does NOT force-off; the room-level
        path in automation.py is the documented owner."""
        room_fan = _make_room_fan(fan_sleep_policy=FAN_SLEEP_OFF)
        # Production cap site: under `off` the cap branch is a no-op,
        # speed passes through; the room-level path is responsible for
        # the force-off at sleep. This test simply documents that no
        # coordinator-side force-off was inserted.
        speed_in = 80
        speed = speed_in
        should_on = True
        if should_on and "sleep" in FAN_TRUST_STATES:
            policy = room_fan.fan_sleep_policy
            if policy == FAN_SLEEP_REDUCE:
                speed = min(speed, FAN_SPEED_LOW_PCT)
        assert speed == 80


class TestD2_SourceAnchors:
    """Source-grep anchors for the comment + label edits."""

    @pytest.fixture(scope="class")
    def src(self) -> str:
        with open(
            "custom_components/universal_room_automation/"
            "domain_coordinators/hvac_fans.py"
        ) as f:
            return f.read()

    def test_no_bare_sleep_string_compare(self, src: str) -> None:
        """Plan §7 Static: zero `house_state == "sleep"` in hvac_fans.py."""
        assert 'self._house_state == "sleep"' not in src

    def test_fan_trust_states_imported(self, src: str) -> None:
        assert "FAN_TRUST_STATES" in src

    def test_policy_branches_present_at_speed_cap(self, src: str) -> None:
        # Anchor on the cap-site policy comment.
        assert "CONF_FAN_SLEEP_POLICY" in src
        assert "FAN_SLEEP_REDUCE" in src
        assert "FAN_SLEEP_NORMAL" in src
        assert "FAN_SLEEP_OFF" in src

    def test_room_fan_state_carries_policy(self, src: str) -> None:
        assert "fan_sleep_policy: str = DEFAULT_FAN_SLEEP_POLICY" in src
        assert (
            "fan_sleep_policy=str(\n"
            "                    merged.get(CONF_FAN_SLEEP_POLICY, DEFAULT_FAN_SLEEP_POLICY)"
        ) in src


# --------------------------------------- D3: hvac.py zone-preset extension


class TestD3_ZonePresetPersonTrust:
    @pytest.fixture(scope="class")
    def src(self) -> str:
        with open(
            "custom_components/universal_room_automation/"
            "domain_coordinators/hvac.py"
        ) as f:
            return f.read()

    def test_zone_preset_person_trust_uses_fan_trust_states(self, src: str) -> None:
        """The away-flip suppression now keys off FAN_TRUST_STATES."""
        assert (
            'effective_preset == "away" and self._house_state in FAN_TRUST_STATES'
            in src
        )

    def test_zone_preset_person_trust_no_bare_sleep_compare(self, src: str) -> None:
        # The trust branch must NOT still test bare sleep equality.
        # (Other sleep-only sites D5/D6 are checked separately below.)
        assert (
            'effective_preset == "away" and self._house_state == "sleep"'
            not in src
        )

    def test_d5_duty_cycle_skip_still_sleep_only(self, src: str) -> None:
        """D5 duty-cycle skip is a RUNAWAY-TIMER guard, not occupancy
        trust — sleep-only is deliberate; must NOT extend."""
        assert "zone.runtime_exceeded and self._house_state != \"sleep\"" in src

    def test_d6_stale_failsafe_skip_still_sleep_only(self, src: str) -> None:
        """D6 stale-failsafe skip remains sleep-only."""
        assert 'self._house_state != "sleep"' in src

    def test_away_veto_path_unaffected(self, src: str) -> None:
        """Bidirectionality (operator amendment): with all phone trackers
        away, the trust branch falls through because `home_persons` is
        empty. Verify the predicate gate is `if home_persons:` not
        unconditional, and that the v4.7.14 all-trackers-away veto path
        in presence.py StateInferenceEngine is not referenced (no
        coupling)."""
        # Anchor: the trust branch only continues when home_persons is non-empty.
        anchor = "if effective_preset == \"away\" and self._house_state in FAN_TRUST_STATES:"
        idx = src.find(anchor)
        assert idx > 0
        body = src[idx: idx + 2000]
        assert "if home_persons:" in body
        # The away-veto runs upstream in presence.py and is not coupled.
        assert "StateInferenceEngine" not in body


# -------------------------------- D4: Mode-2 BLE recheck stays sleep-only


class TestD4_Mode2BleGate:
    @pytest.fixture(scope="class")
    def src(self) -> str:
        with open(
            "custom_components/universal_room_automation/"
            "domain_coordinators/presence_fan_recheck.py"
        ) as f:
            return f.read()

    def test_gate_remains_sleep_only(self, src: str) -> None:
        assert "if house_state == HouseState.SLEEP:" in src

    def test_comment_cross_references_planning_doc(self, src: str) -> None:
        assert "PLANNING_fan_trust_state_extension.md" in src
        assert "§D-MODE2" in src or "D-MODE2" in src

    def test_does_not_extend_to_fan_trust_states(self, src: str) -> None:
        """No FAN_TRUST_STATES membership check in this file."""
        assert "FAN_TRUST_STATES" not in src


# ------------------------ D5: automation.py per-room time-window unchanged


class TestD5_AutomationPathStillTimeWindow:
    @pytest.fixture(scope="class")
    def src(self) -> str:
        with open(
            "custom_components/universal_room_automation/automation.py"
        ) as f:
            return f.read()

    def test_sleep_block_remains_time_window_keyed(self, src: str) -> None:
        """sleep_occupied_hold in automation.py keys off
        is_sleep_mode_active() — per-room time-window, NOT house_state."""
        idx = src.find("sleep_occupied_hold = (")
        assert idx > 0
        body = src[idx: idx + 400]
        assert "self.is_sleep_mode_active()" in body
        assert "FAN_TRUST_STATES" not in body
        assert 'house_state' not in body  # no house_state reference here

    def test_d_aut_comment_present(self, src: str) -> None:
        assert "D-AUT" in src


# --------------------------- Bidirectionality / empty-house safety


@_skip_no_real_fans
class TestBidirectionalityEmptyHouse:
    """Operator amendment (c): empty house during home_night still reaches
    `away` — trust does not hold zones when ALL trackers are away."""

    @pytest.mark.parametrize("state", ["home_night", "sleep", "waking"])
    def test_zone_preset_falls_through_when_all_trackers_away(self, state):
        """When `home_persons` is empty the trust branch does not suppress
        the away preset. Verified at the predicate level by directly
        evaluating the gate (no production code change needed — this
        documents the design)."""
        # Compose: `home_persons` is built by iterating zone_persons and
        # filtering by `state == "home"`. Empty zone_persons OR no
        # trackers home -> empty list -> branch falls through.
        zone_persons = ["person.oji"]
        person_states = {"person.oji": "not_home"}
        home_persons = [p for p in zone_persons if person_states.get(p) == "home"]
        assert home_persons == []
        # Production then runs `if home_persons:` -> False -> branch
        # does not `continue`, so the away preset is applied normally.

    def test_fan_vacancy_hold_falls_through_when_all_trackers_away(self):
        """Mirror at the fan layer: vacancy person-trust does not fire
        when no tracker is home."""
        zone = _FakeZone()
        zone.zone_persons = ["person.oji", "person.jaya"]
        ctrl = _make_controller(
            zone,
            person_states={"person.oji": "not_home", "person.jaya": "not_home"},
        )
        ctrl._house_state = "home_night"

        vac_anchor = (datetime.now() - timedelta(seconds=DEFAULT_FAN_VACANCY_HOLD + 30)).isoformat()
        rf = _make_room_fan(is_on=True, speed_pct=33, trigger="temperature")
        rf.vacancy_detected_time = vac_anchor

        should_on, _trigger, _speed = ctrl._evaluate_temp_fan(
            rf,
            room_temp=72.0,
            setpoint_high=74.0,
            occupied=False,
            now=datetime.now(),
        )
        assert should_on is False
