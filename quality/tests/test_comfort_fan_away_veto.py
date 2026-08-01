"""D5 tests for the comfort-fan house-AWAY veto (mmwave-corroboration Tier-3 D3).

Covers the plan's D5 test set scoped to D3 only (D2 is parked):

  T1  helper: constants importable / defaults sane
  T2  helper: house_state gating (HOME_* / SLEEP → no veto; AWAY/VACATION → veto)
  T3  helper: kill-switch (CONF_COMFORT_FAN_AWAY_VETO_ENABLED=False → identical no-op)
  T4  helper: trusted-presence legs — motion (recent + currently ON) both defeat veto
  T5  helper: trusted-presence legs — BLE-in-room defeats veto
  T6  helper: trusted-presence legs — camera-person defeats veto ONLY when covered
  T7  helper: mmWave-only room with mmWave firing does NOT defeat veto (invariant V)
  T8  helper: fail-OPEN on all internal error paths (no missing coord manager, etc.)
  T9  observability: veto counter increments per veto, per room
  T10 per-site routing (source-anchored): each of the three actuation sites
      contains the exact import + call of the shared helper. Bug-Class-#53
      mitigation — if any site's routing gets removed, the anchor fails.

Humidity path / sleep-home / house=HOME baseline regressions are covered
via T2 (no veto outside AWAY/VACATION) + the routing anchor in T10 (the
humidity path is asserted NOT to call the helper — sole-owner contract).

Tests drive the PRODUCTION helper directly (Bug Class #62: no
reimplementation of the veto arithmetic in test code).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import _provenance_harness  # noqa: F401
from _provenance_harness import make_hass

from custom_components.universal_room_automation import fan_veto

# _provenance_harness mocks homeassistant.const as a MagicMock, so STATE_ON
# is not "on". Patch the fan_veto module's imported STATE_ON to the
# production literal so state-comparison branches behave as they will in HA.
fan_veto.STATE_ON = "on"
from custom_components.universal_room_automation.const import (
    CAMERA_COVERED_ROOMS,
    CONF_CAMERA_PERSON_ENTITIES,
    CONF_COMFORT_FAN_AWAY_VETO_ENABLED,
    CONF_MOTION_SENSORS,
    CONF_OCCUPANCY_TIMEOUT,
    DEFAULT_COMFORT_FAN_AWAY_VETO_ENABLED,
    DOMAIN,
)
from custom_components.universal_room_automation.domain_coordinators.house_state import (
    HouseState,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _hass_with_house_state(state: str):
    hass = make_hass()
    presence = MagicMock()
    presence.house_state = state
    person_coord = MagicMock()
    person_coord.get_persons_in_room = MagicMock(return_value=[])
    manager = MagicMock()
    manager.coordinators = {"presence": presence}
    hass.data = {
        DOMAIN: {
            "coordinator_manager": manager,
            "person_coordinator": person_coord,
        },
    }
    return hass, presence, person_coord


def _state(state_str, last_changed=None):
    st = MagicMock()
    st.state = state_str
    # tz-AWARE: production subtracts against dt_util.utcnow() (aware); a
    # naive fixture datetime makes the age calc raise and fail-open — the
    # test would then assert against the exception path, not the logic.
    # Clock-derive from fan_veto's own dt_util binding so the fixture is
    # agnostic to whether the harness stub clock is naive or aware.
    st.last_changed = last_changed or fan_veto.dt_util.utcnow()
    return st


# ---------------------------------------------------------------------------
# T1 — constants importable
# ---------------------------------------------------------------------------

def test_t1_constants_present_and_sane() -> None:
    assert CONF_COMFORT_FAN_AWAY_VETO_ENABLED == "comfort_fan_away_veto_enabled"
    assert DEFAULT_COMFORT_FAN_AWAY_VETO_ENABLED is True
    # Camera map is a frozenset (rung-1 module constant, per Amendment 1).
    assert isinstance(CAMERA_COVERED_ROOMS, frozenset)
    assert "Study A" in CAMERA_COVERED_ROOMS


# ---------------------------------------------------------------------------
# T2 — house_state gating
# ---------------------------------------------------------------------------

def test_t2_no_veto_when_house_home_day() -> None:
    hass, _p, _pc = _hass_with_house_state(HouseState.HOME_DAY)
    assert not fan_veto.should_veto_comfort_fan(hass, "Bedroom", {})


def test_t2_no_veto_when_house_sleep() -> None:
    # SLEEP is explicitly NOT covered (per D-AUT reasoning preserved).
    hass, _p, _pc = _hass_with_house_state(HouseState.SLEEP)
    assert not fan_veto.should_veto_comfort_fan(hass, "Bedroom", {})


def test_t2_veto_when_house_away_no_presence() -> None:
    hass, _p, _pc = _hass_with_house_state(HouseState.AWAY)
    assert fan_veto.should_veto_comfort_fan(hass, "Bedroom", {})


def test_t2_veto_when_house_vacation_no_presence() -> None:
    hass, _p, _pc = _hass_with_house_state(HouseState.VACATION)
    assert fan_veto.should_veto_comfort_fan(hass, "Bedroom", {})


# ---------------------------------------------------------------------------
# T3 — kill switch
# ---------------------------------------------------------------------------

def test_t3_killswitch_disabled_never_vetoes() -> None:
    hass, _p, _pc = _hass_with_house_state(HouseState.AWAY)
    cfg = {CONF_COMFORT_FAN_AWAY_VETO_ENABLED: False}
    assert not fan_veto.should_veto_comfort_fan(hass, "Bedroom", cfg)


# ---------------------------------------------------------------------------
# T4 — motion trusted-presence leg
# ---------------------------------------------------------------------------

def test_t4_motion_currently_on_defeats_veto() -> None:
    hass, _p, _pc = _hass_with_house_state(HouseState.AWAY)
    hass.states.get = MagicMock(return_value=_state("on"))
    cfg = {CONF_MOTION_SENSORS: ["binary_sensor.pir1"]}
    assert not fan_veto.should_veto_comfort_fan(hass, "Bedroom", cfg)


def test_t4_motion_recent_within_timeout_defeats_veto() -> None:
    hass, _p, _pc = _hass_with_house_state(HouseState.AWAY)
    # Sensor OFF but flipped 60s ago; timeout=300 → recent.
    recent = fan_veto.dt_util.utcnow() - timedelta(seconds=60)
    hass.states.get = MagicMock(return_value=_state("off", last_changed=recent))
    cfg = {
        CONF_MOTION_SENSORS: ["binary_sensor.pir1"],
        CONF_OCCUPANCY_TIMEOUT: 300,
    }
    assert not fan_veto.should_veto_comfort_fan(hass, "Bedroom", cfg)


def test_t4_motion_stale_beyond_timeout_does_not_defeat_veto() -> None:
    hass, _p, _pc = _hass_with_house_state(HouseState.AWAY)
    stale = fan_veto.dt_util.utcnow() - timedelta(seconds=900)
    hass.states.get = MagicMock(return_value=_state("off", last_changed=stale))
    cfg = {
        CONF_MOTION_SENSORS: ["binary_sensor.pir1"],
        CONF_OCCUPANCY_TIMEOUT: 300,
    }
    assert fan_veto.should_veto_comfort_fan(hass, "Bedroom", cfg)


# ---------------------------------------------------------------------------
# T5 — BLE trusted-presence leg
# ---------------------------------------------------------------------------

def test_t5_ble_person_in_room_defeats_veto() -> None:
    hass, _p, person_coord = _hass_with_house_state(HouseState.AWAY)
    person_coord.get_persons_in_room = MagicMock(return_value=["person.alice"])
    assert not fan_veto.should_veto_comfort_fan(hass, "Bedroom", {})


# ---------------------------------------------------------------------------
# T6 — camera trusted-presence leg (only for covered rooms)
# ---------------------------------------------------------------------------

def test_t6_camera_person_in_covered_room_defeats_veto() -> None:
    hass, _p, _pc = _hass_with_house_state(HouseState.AWAY)
    hass.states.get = MagicMock(return_value=_state("on"))
    cfg = {CONF_CAMERA_PERSON_ENTITIES: ["binary_sensor.studya_person"]}
    # "Study A" is in CAMERA_COVERED_ROOMS.
    assert not fan_veto.should_veto_comfort_fan(hass, "Study A", cfg)


def test_t6_camera_person_in_uncovered_room_does_not_defeat_veto() -> None:
    hass, _p, _pc = _hass_with_house_state(HouseState.AWAY)
    hass.states.get = MagicMock(return_value=_state("on"))
    cfg = {CONF_CAMERA_PERSON_ENTITIES: ["binary_sensor.rogue"]}
    # "Bedroom" is not in CAMERA_COVERED_ROOMS — camera leg is ABSENT.
    # Motion sensors are also absent, so nothing defeats the veto.
    assert fan_veto.should_veto_comfort_fan(hass, "Bedroom", cfg)


# ---------------------------------------------------------------------------
# T7 — Invariant V: mmWave firing does NOT defeat the veto
# ---------------------------------------------------------------------------

def test_t7_mmwave_only_does_not_defeat_veto() -> None:
    """The whole point: mmWave is EXCLUDED from trusted presence."""
    hass, _p, person_coord = _hass_with_house_state(HouseState.AWAY)
    # No motion sensors configured (mmwave-only room). BLE empty. No cameras.
    # A hypothetical mmwave binary_sensor being ON is irrelevant — the
    # helper never reads CONF_MMWAVE_SENSORS.
    hass.states.get = MagicMock(return_value=_state("on"))  # everything on
    cfg = {}  # no motion, no camera entities
    assert fan_veto.should_veto_comfort_fan(hass, "Study A", cfg)


# ---------------------------------------------------------------------------
# T8 — fail-OPEN on error paths
# ---------------------------------------------------------------------------

def test_t8_no_coordinator_manager_fails_open() -> None:
    hass = make_hass()
    hass.data = {}
    assert not fan_veto.should_veto_comfort_fan(hass, "Bedroom", {})


def test_t8_broken_person_coordinator_fails_open_on_ble_leg() -> None:
    hass, _p, person_coord = _hass_with_house_state(HouseState.AWAY)
    person_coord.get_persons_in_room = MagicMock(side_effect=RuntimeError("kaboom"))
    # BLE leg fails open (returns False → no defeat), but nothing else
    # defeats the veto, so veto still fires.
    assert fan_veto.should_veto_comfort_fan(hass, "Bedroom", {})


# ---------------------------------------------------------------------------
# T9 — observability counter
# ---------------------------------------------------------------------------

def test_t9_counter_increments_per_veto() -> None:
    hass, _p, _pc = _hass_with_house_state(HouseState.AWAY)
    assert fan_veto.get_veto_count(hass, "Bedroom") == 0
    assert fan_veto.should_veto_comfort_fan(hass, "Bedroom", {})
    assert fan_veto.should_veto_comfort_fan(hass, "Bedroom", {})
    assert fan_veto.should_veto_comfort_fan(hass, "Living Room", {})
    assert fan_veto.get_veto_count(hass, "Bedroom") == 2
    assert fan_veto.get_veto_count(hass, "Living Room") == 1


def test_t9_counter_not_incremented_when_no_veto() -> None:
    hass, _p, _pc = _hass_with_house_state(HouseState.HOME_DAY)
    fan_veto.should_veto_comfort_fan(hass, "Bedroom", {})
    assert fan_veto.get_veto_count(hass, "Bedroom") == 0


# ---------------------------------------------------------------------------
# T10 — per-site routing (Bug-Class-#53 mitigation, source-anchored)
# ---------------------------------------------------------------------------

_URA_ROOT = (
    Path(__file__).resolve().parent.parent.parent
    / "custom_components" / "universal_room_automation"
)


def _read(rel: str) -> str:
    return (_URA_ROOT / rel).read_text()


def test_t10_room_tier_site_routes_through_helper() -> None:
    """automation.py::handle_temperature_based_fan_control turn-on branch."""
    src = _read("automation.py")
    assert "from .fan_veto import should_veto_comfort_fan" in src
    # Guard placed inside the turn-on branch (speed_pct > 0), not turn-off.
    turn_on_slice = src.split("if speed_pct > 0:", 1)[1].split("try:", 1)[0]
    assert "should_veto_comfort_fan(" in turn_on_slice


def test_t10_hvac_tier_site_routes_through_helper() -> None:
    """hvac_fans.py before _set_fan_state, only on ON transitions."""
    src = _read("domain_coordinators/hvac_fans.py")
    assert "from ..fan_veto import should_veto_comfort_fan" in src
    # Guard placed inside `if should_on and not room_fan.is_on:` — verify.
    assert "if should_on and not room_fan.is_on:" in src
    guard_slice = src.split("if should_on and not room_fan.is_on:", 1)[1]
    guard_slice = guard_slice.split("await self._set_fan_state", 1)[0]
    assert "should_veto_comfort_fan(" in guard_slice


def test_t10_reconciler_site_routes_through_helper() -> None:
    """actuator_reconciler.py::_resolve_fan before returning ON DesiredState."""
    src = _read("actuator_reconciler.py")
    assert "from .fan_veto import should_veto_comfort_fan" in src
    # Guard sits between the "off" return and the final "on" DesiredState.
    fan_slice = src.split("def _resolve_fan(", 1)[1].split("def ", 1)[0]
    assert "should_veto_comfort_fan(" in fan_slice
    # Ensure the reconciler returns None on veto (not an "on" DesiredState).
    veto_slice = fan_slice.split("should_veto_comfort_fan(", 1)[1]
    assert "return None" in veto_slice.split("\n\n", 1)[0]


def test_t10_humidity_path_does_not_route_through_helper() -> None:
    """Humidity fans are sole-owner (hvac_fans.py:291-296) — must NOT be vetoed.

    Regression guard: if a future edit accidentally adds the veto to
    handle_humidity_based_fan_control, this test fails.
    """
    src = _read("automation.py")
    # C-HIGH-1 fix (fix-up pass): hard-assert the humidity handler exists;
    # a silent skip on rename would hide a real regression.
    assert "def handle_humidity_based_fan_control" in src, (
        "handle_humidity_based_fan_control must exist — humidity path is "
        "the sole-owner for humidity fans"
    )
    humidity_slice = src.split(
        "def handle_humidity_based_fan_control", 1,
    )[1].split("\n    def ", 1)[0]
    assert "should_veto_comfort_fan(" not in humidity_slice


# ---------------------------------------------------------------------------
# Orchestrator addition 2026-08-01 (camera-resolver cycle, post-fix-up drill
# gap): the E-HIGH-1 divergence gate on the fused camera path must be
# load-bearing — neutering `agreement == "unanimous_on" or confidence ==
# "high"` in fan_veto._has_camera_person must turn these red.
# ---------------------------------------------------------------------------

def _fused_cam_hass(state_str, agreement, confidence):
    hass = MagicMock()
    st = MagicMock()
    st.state = state_str
    st.attributes = {}
    if agreement is not None:
        st.attributes["agreement"] = agreement
    if confidence is not None:
        st.attributes["confidence"] = confidence
    hass.states.get = MagicMock(return_value=st)
    return hass


def test_veto_camera_leg_denies_on_split_agreement():
    """Fused sensor ON but divergent (split/medium) must NOT count as
    trusted camera presence (E-HIGH-1 divergence-aware gate)."""
    cfg = {"room_cameras": ["camera.study_a"]}
    hass = _fused_cam_hass("on", "split", "medium")
    assert fan_veto._has_camera_person(hass, "Study A", cfg) is False


def test_veto_camera_leg_grants_on_unanimous():
    """Unanimous-ON agreement satisfies the leg — single-platform rooms
    reach this via unanimous_on with one source (leg not disabled for
    single-integration homes)."""
    cfg = {"room_cameras": ["camera.study_a"]}
    hass = _fused_cam_hass("on", "unanimous_on", "medium")
    assert fan_veto._has_camera_person(hass, "Study A", cfg) is True


def test_veto_camera_leg_denies_when_attributes_missing():
    """Fail direction: ON with missing agreement/confidence attrs = unknown,
    not corroborated — must deny."""
    cfg = {"room_cameras": ["camera.study_a"]}
    hass = _fused_cam_hass("on", None, None)
    assert fan_veto._has_camera_person(hass, "Study A", cfg) is False


def test_veto_camera_leg_grants_on_single_source():
    """D'-HIGH-2 adjudication: single_source ON (uncontested — no second
    camera dissenting) satisfies the leg, matching v5.43.0's census
    single-source precedent. Split (contested) still denies."""
    cfg = {"room_cameras": ["camera.study_a"]}
    hass = _fused_cam_hass("on", "single_source", "medium")
    assert fan_veto._has_camera_person(hass, "Study A", cfg) is True
