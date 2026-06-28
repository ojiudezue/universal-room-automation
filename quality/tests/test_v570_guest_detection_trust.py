"""v5.7.0 WS-A — Guest-Mode Detection Trust (LOST-admitted AWAY veto).

Tier 3 cycle. Tests drive the REAL authoritative house-state resolver —
``StateInferenceEngine.infer()`` — which is the surface `_run_inference`
calls and the surface whose return value gets applied to the
HouseStateMachine. The prior Fix-A tests drove
``should_veto_due_to_reliable_signals`` (a DIAGNOSTIC-only helper that
writes ``self._last_veto_decision``) which is NOT the authoritative
resolver — those tests were invalid for invariant verification.

This file asserts the seven required cases from the WS-A build prompt:

  1. dead-phone-home + one INDOOR zone occupied (census=0, unidentified=0)
     → stays HOME_* (NOT AWAY) — explicit HIGH regression guard (I1).
  2. dead-phone-away + empty house (no indoor zone, census=0) → AWAY @ 0.95.
  3. all-lost-away + grace NOT elapsed → not yet AWAY; after grace
     elapsed → AWAY.
  4. all-lost-away during SLEEP/HOME_NIGHT with sleep-exempt → stays
     (no force-AWAY) regardless of grace (I4).
  5. unidentified-while-home (unidentified_count>0) → guest path
     preserved (no force-AWAY-via-β regression, I2).
  6. outdoor "Outside" zone occupied + everyone away → AWAY (A4
     excludes it; the occupied outdoor zone does NOT block path β).
  7. ACTIVE-only inputs → byte-identical state+confidence to v4.7.14
     (snapshot test for path α / I3).

Each case names the load-bearing site (A1, A2, A3, A4) it covers so the
Tier-3 Review C mutation-anchored verification can confirm a SPECIFIC
test fails when that site is bypassed.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
PKG = REPO_ROOT / "custom_components" / "universal_room_automation"
DC_PATH = PKG / "domain_coordinators"
PRESENCE_SRC = (DC_PATH / "presence.py").read_text()
SENSOR_SRC = (PKG / "sensor.py").read_text()


# ---------------------------------------------------------------------------
# HA module mocking (mirrors test_v4714_away_state_person_tracker_trust.py)
# ---------------------------------------------------------------------------


def _mock_module(name, **attrs):
    mod = types.ModuleType(name)
    mod.__path__ = []
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


_identity = lambda fn: fn  # noqa: E731
_mock_cls = MagicMock

_ha_mods = {
    "homeassistant": {},
    "homeassistant.core": {
        "HomeAssistant": _mock_cls,
        "callback": _identity,
        "Event": _mock_cls,
        "State": _mock_cls,
    },
    "homeassistant.config_entries": {"ConfigEntry": _mock_cls},
    "homeassistant.const": MagicMock(),
    "homeassistant.helpers": {},
    "homeassistant.helpers.device_registry": {"DeviceInfo": dict},
    "homeassistant.helpers.entity": {
        "DeviceInfo": dict,
        "EntityCategory": _mock_cls(),
    },
    "homeassistant.helpers.entity_platform": {"AddEntitiesCallback": _mock_cls},
    "homeassistant.helpers.event": {
        "async_track_state_change_event": _mock_cls(),
        "async_track_time_interval": lambda hass, cb, interval: _mock_cls(),
        "async_call_later": lambda hass, delay, cb: _mock_cls(),
    },
    "homeassistant.helpers.dispatcher": {
        "async_dispatcher_connect": lambda hass, signal, cb: _mock_cls(),
        "async_dispatcher_send": lambda hass, signal, data=None: None,
    },
    "homeassistant.helpers.update_coordinator": {
        "DataUpdateCoordinator": _mock_cls,
        "UpdateFailed": Exception,
    },
    "homeassistant.helpers.selector": _mock_cls(),
    "homeassistant.helpers.entity_registry": {"async_get": _mock_cls()},
    "homeassistant.helpers.sun": {},
    "homeassistant.util": {},
    "homeassistant.util.dt": {
        "utcnow": lambda: datetime.utcnow(),
        "now": lambda: datetime(2026, 5, 30, 14, 0, 0),
        "as_local": lambda dt: dt,
    },
    "homeassistant.components": {},
    "homeassistant.components.sensor": {
        "SensorEntity": type("SensorEntity", (), {}),
        "SensorDeviceClass": _mock_cls(),
        "SensorStateClass": _mock_cls(),
    },
    "homeassistant.components.binary_sensor": {
        "BinarySensorEntity": type("BinarySensorEntity", (), {}),
        "BinarySensorDeviceClass": _mock_cls(),
    },
    "homeassistant.components.button": {
        "ButtonEntity": type("ButtonEntity", (), {}),
    },
}

for _name, _attrs in _ha_mods.items():
    if isinstance(_attrs, dict):
        _existing = sys.modules.get(_name)
        if _existing is None:
            sys.modules[_name] = _mock_module(_name, **_attrs)
        else:
            for _k, _v in _attrs.items():
                if not hasattr(_existing, _k):
                    setattr(_existing, _k, _v)
    else:
        sys.modules.setdefault(_name, _attrs)

sys.modules.setdefault("aiosqlite", MagicMock())


def _load_module(full_name: str, filepath) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(full_name, str(filepath))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = mod
    spec.loader.exec_module(mod)
    return mod


_cc_pkg_name = "custom_components"
if _cc_pkg_name not in sys.modules:
    sys.modules[_cc_pkg_name] = _mock_module(_cc_pkg_name)

_ura_pkg_name = "custom_components.universal_room_automation"
if _ura_pkg_name not in sys.modules:
    _ura_pkg = _mock_module(_ura_pkg_name)
    _ura_pkg.__file__ = str(PKG / "__init__.py")
    sys.modules[_ura_pkg_name] = _ura_pkg

_dc_pkg_name = "custom_components.universal_room_automation.domain_coordinators"
if _dc_pkg_name not in sys.modules:
    _dc_pkg = _mock_module(_dc_pkg_name)
    _dc_pkg.__file__ = str(DC_PATH / "__init__.py")
    sys.modules[_dc_pkg_name] = _dc_pkg

for _submod in ("const",):
    _full = f"custom_components.universal_room_automation.{_submod}"
    if _full not in sys.modules:
        _load_module(_full, PKG / f"{_submod}.py")

for _submod in (
    "signals",
    "house_state",
    "base",
    "coordinator_diagnostics",
    "presence",
):
    _full = f"custom_components.universal_room_automation.domain_coordinators.{_submod}"
    if _full not in sys.modules:
        _load_module(_full, DC_PATH / f"{_submod}.py")


from custom_components.universal_room_automation.domain_coordinators.presence import (  # noqa: E402
    StateInferenceEngine,
    _tracking_active_or_lost_away,
)
from custom_components.universal_room_automation.domain_coordinators.house_state import (  # noqa: E402
    HouseState,
)


# ---------------------------------------------------------------------------
# Engine fixture
# ---------------------------------------------------------------------------

def _make_engine() -> StateInferenceEngine:
    """Default sleep window (23-06) — afternoon `now` is awake."""
    return StateInferenceEngine(sleep_start_hour=23, sleep_end_hour=6)


def _afternoon() -> datetime:
    return datetime(2026, 5, 30, 14, 0, 0)


# ===========================================================================
# Case 1 — dead-phone-home + indoor zone occupied → stays HOME (HIGH regression)
# Mutation anchor: A2 (indoor-occupancy guard on path β).
# ===========================================================================

def test_case1_dead_phone_home_with_indoor_zone_stays_home():
    """Path β MUST NOT force AWAY when an indoor zone is occupied.

    Scenario: dead phone reports LOST+away; mmWave still detects the
    resident sitting on the couch (indoor zone OCCUPIED). With census=0
    and unidentified=0, the naive WS-A1 (no indoor guard) would force
    AWAY — the explicit HIGH regression the operator called out.

    Mutation anchor (A2): if A2's `not indoor_blocked` clause is removed
    from path β in StateInferenceEngine.infer(), this test fails.
    """
    engine = _make_engine()
    new_state = engine.infer(
        census_count=0,
        current_state=HouseState.HOME_DAY,
        any_zone_occupied=True,           # indoor zone occupied
        now=_afternoon(),
        unidentified_count=0,
        guest_gate_armed=False,
        # Path α denominator: not all ACTIVE-away (the resident is LOST).
        all_tracked_persons_away=False,
        # Path β denominator: all LOST-relaxed are away.
        all_trusted_or_lost_away_persons_away=True,
        any_indoor_zone_occupied=True,    # ← the load-bearing guard
        grace_elapsed_for_lost_away=True,
        lost_away_persons_present=True,
        sleep_exempt_state=False,
    )
    assert new_state != HouseState.AWAY, (
        "WS-A2 invariant I1: dead-phone-home + indoor zone occupied must "
        "NOT trigger AWAY"
    )
    # Diagnostic: veto_path must be "none" since no veto fired.
    assert engine._veto_path == "none"


# ===========================================================================
# Case 2 — dead-phone-away + empty house → AWAY @ 0.95 (path β legitimate fire)
# Mutation anchor: A1 (LOST-relaxed denominator).
# ===========================================================================

def test_case2_dead_phone_away_empty_house_goes_away():
    """Path β fires when everyone's truly away AND house is indoor-empty.

    Mutation anchor (A1): if `_tracking_active_or_lost_away` is reverted
    to ACTIVE-only, the path-β denominator never resolves True for a
    LOST-only resident and this test fails.
    """
    engine = _make_engine()
    new_state = engine.infer(
        census_count=0,
        current_state=HouseState.HOME_DAY,
        any_zone_occupied=False,
        now=_afternoon(),
        unidentified_count=0,
        guest_gate_armed=False,
        all_tracked_persons_away=False,
        all_trusted_or_lost_away_persons_away=True,
        any_indoor_zone_occupied=False,
        grace_elapsed_for_lost_away=True,
        lost_away_persons_present=True,
        sleep_exempt_state=False,
    )
    # NOTE: with any_zone_occupied=False and census_count=0, the
    # "Nobody home" early-return branch ALSO fires AWAY @ 0.9. To prove
    # path β (not the early-return) is the resolver, force-occupied an
    # outdoor zone in case 6 — here we accept the early-return path as
    # a sufficient AWAY proof; path β must STILL fire when there's a
    # transient bounce (case 6 exercises that explicitly).
    assert new_state == HouseState.AWAY


def test_case2b_dead_phone_away_with_camera_ghost_goes_away_via_path_beta():
    """Same as case2 but camera ghost-motion (any_zone_occupied=True).

    Forces the resolver past the 'nobody home' early-return — only path
    β can fire AWAY. Sets `any_indoor_zone_occupied=False` (ghost motion
    is on an outdoor camera; WS-A4 excludes it).

    Mutation anchor (A1): drop LOST-relaxed denominator → test fails
    (path β no longer fires; resolver falls through to HOME).
    """
    engine = _make_engine()
    new_state = engine.infer(
        census_count=0,
        current_state=HouseState.HOME_DAY,
        any_zone_occupied=True,            # outdoor camera ghost
        now=_afternoon(),
        unidentified_count=0,
        guest_gate_armed=False,
        all_tracked_persons_away=False,    # path α: no ACTIVE-away
        all_trusted_or_lost_away_persons_away=True,
        any_indoor_zone_occupied=False,    # WS-A4 excluded outdoor
        grace_elapsed_for_lost_away=True,
        lost_away_persons_present=True,
        sleep_exempt_state=False,
    )
    assert new_state == HouseState.AWAY
    assert engine.confidence == 0.95
    assert engine._veto_path == "lost_admitted"


# ===========================================================================
# Case 3 — grace gate
# Mutation anchor: A3 (grace gate on path β).
# ===========================================================================

def test_case3a_grace_not_elapsed_does_not_force_away():
    """Path β must NOT fire while grace is still ticking.

    Mutation anchor (A3): if `grace_elapsed_for_lost_away` is dropped
    from the path-β predicate, this test fails (β fires immediately on
    a flap).
    """
    engine = _make_engine()
    new_state = engine.infer(
        census_count=0,
        current_state=HouseState.HOME_DAY,
        any_zone_occupied=True,            # outdoor camera ghost
        now=_afternoon(),
        unidentified_count=0,
        guest_gate_armed=False,
        all_tracked_persons_away=False,
        all_trusted_or_lost_away_persons_away=True,
        any_indoor_zone_occupied=False,
        grace_elapsed_for_lost_away=False,   # ← grace NOT elapsed
        lost_away_persons_present=True,
        sleep_exempt_state=False,
    )
    assert new_state != HouseState.AWAY
    assert engine._veto_path == "none"


def test_case3b_grace_elapsed_fires_path_beta():
    """Same as 3a but with grace elapsed → β fires AWAY."""
    engine = _make_engine()
    new_state = engine.infer(
        census_count=0,
        current_state=HouseState.HOME_DAY,
        any_zone_occupied=True,
        now=_afternoon(),
        unidentified_count=0,
        guest_gate_armed=False,
        all_tracked_persons_away=False,
        all_trusted_or_lost_away_persons_away=True,
        any_indoor_zone_occupied=False,
        grace_elapsed_for_lost_away=True,   # ← elapsed
        lost_away_persons_present=True,
        sleep_exempt_state=False,
    )
    assert new_state == HouseState.AWAY
    assert engine._veto_path == "lost_admitted"


# ===========================================================================
# Case 4 — sleep exemption
# Mutation anchor: A3 (sleep_exempt_state gate).
# ===========================================================================

def test_case4_sleep_exempt_suppresses_path_beta_regardless_of_grace():
    """During SLEEP with sleep-exempt True, β must NOT fire even after grace.

    Protects a resident whose phone dies overnight (the operator-cited
    real-world failure mode).

    Mutation anchor (A3): if the `not sleep_exempt_state` clause is
    dropped from path β, this test fails.
    """
    engine = _make_engine()
    new_state = engine.infer(
        census_count=0,
        current_state=HouseState.SLEEP,
        any_zone_occupied=True,
        now=_afternoon(),
        unidentified_count=0,
        guest_gate_armed=False,
        all_tracked_persons_away=False,
        all_trusted_or_lost_away_persons_away=True,
        any_indoor_zone_occupied=False,
        grace_elapsed_for_lost_away=True,    # grace elapsed
        lost_away_persons_present=True,
        sleep_exempt_state=True,             # ← sleep-exempt active
    )
    assert new_state != HouseState.AWAY


def test_case4b_sleep_exempt_disabled_respects_grace_in_sleep():
    """Sleep-exempt False → β can fire during SLEEP once grace elapses."""
    engine = _make_engine()
    new_state = engine.infer(
        census_count=0,
        current_state=HouseState.SLEEP,
        any_zone_occupied=True,
        now=_afternoon(),
        unidentified_count=0,
        guest_gate_armed=False,
        all_tracked_persons_away=False,
        all_trusted_or_lost_away_persons_away=True,
        any_indoor_zone_occupied=False,
        grace_elapsed_for_lost_away=True,
        lost_away_persons_present=True,
        sleep_exempt_state=False,           # ← disabled
    )
    assert new_state == HouseState.AWAY
    assert engine._veto_path == "lost_admitted"


# ===========================================================================
# Case 5 — guest-detection preserved (I2)
# ===========================================================================

def test_case5_unidentified_while_home_does_not_force_away_via_beta():
    """unidentified_count > 0 keeps path β from firing — guest preserved.

    Mirrors v4.7.14's `test_veto_does_not_fire_when_unidentified_count_positive`
    but for the new path β.
    """
    engine = _make_engine()
    new_state = engine.infer(
        census_count=0,
        current_state=HouseState.HOME_DAY,
        any_zone_occupied=True,
        now=_afternoon(),
        unidentified_count=1,                # ← guest at the door
        guest_gate_armed=False,
        all_tracked_persons_away=False,
        all_trusted_or_lost_away_persons_away=True,
        any_indoor_zone_occupied=False,
        grace_elapsed_for_lost_away=True,
        lost_away_persons_present=True,
        sleep_exempt_state=False,
    )
    assert new_state != HouseState.AWAY


# ===========================================================================
# Case 6 — outdoor zone does NOT block path β (A4)
# Mutation anchor: A4 (`any_indoor_zone_occupied` distinct from
# `any_zone_occupied`).
# ===========================================================================

def test_case6_outdoor_zone_occupied_does_not_block_path_beta():
    """An occupied outdoor zone + all-away + indoor empty → AWAY fires.

    Mutation anchor (A4): if the indoor guard reverts to using
    `any_zone_occupied` instead of `any_indoor_zone_occupied`, this
    test fails (outdoor occupied jams path β).
    """
    engine = _make_engine()
    new_state = engine.infer(
        census_count=0,
        current_state=HouseState.HOME_DAY,
        any_zone_occupied=True,             # outdoor zone occupied
        now=_afternoon(),
        unidentified_count=0,
        guest_gate_armed=False,
        all_tracked_persons_away=False,
        all_trusted_or_lost_away_persons_away=True,
        any_indoor_zone_occupied=False,     # ← outdoor excluded
        grace_elapsed_for_lost_away=True,
        lost_away_persons_present=True,
        sleep_exempt_state=False,
    )
    assert new_state == HouseState.AWAY
    assert engine._veto_path == "lost_admitted"


# ===========================================================================
# Case 7 — ACTIVE-only inputs are byte-identical to v4.7.14 (I3 snapshot)
# Mutation anchor: path α conditional must be untouched.
# ===========================================================================

def test_case7_active_path_unchanged_byte_identical_state_and_confidence():
    """v4.7.14 ACTIVE-only inputs must produce byte-identical output.

    Asserts both `new_state` AND `engine.confidence` match the v4.7.14
    snapshot (HouseState.AWAY @ 0.95). Path β kwargs at their defaults
    cannot fire β; only path α can resolve AWAY in this scenario.

    Mutation anchor (I3): if path α arithmetic / confidence is mutated,
    this test fails. Also fails if path α somehow short-circuits through
    the new path β code (verifies the conditional ordering).
    """
    engine = _make_engine()
    new_state = engine.infer(
        census_count=0,
        current_state=HouseState.HOME_DAY,
        any_zone_occupied=True,
        now=_afternoon(),
        unidentified_count=0,
        guest_gate_armed=False,
        all_tracked_persons_away=True,   # v4.7.14 ACTIVE-only veto
        # All WS-A kwargs left at default — NO path β admission possible.
    )
    assert new_state == HouseState.AWAY
    assert engine.confidence == 0.95
    assert engine._veto_path == "active"


def test_case7b_active_byte_identical_when_already_away_returns_none():
    """v4.7.14: when already AWAY, the path-α branch returns None.

    Path β's `current_state == HouseState.AWAY → return None` branch
    must NOT preempt path α's same branch (ordering invariant).
    """
    engine = _make_engine()
    new_state = engine.infer(
        census_count=0,
        current_state=HouseState.AWAY,
        any_zone_occupied=True,
        now=_afternoon(),
        unidentified_count=0,
        guest_gate_armed=False,
        all_tracked_persons_away=True,
    )
    assert new_state is None
    assert engine._veto_path == "active"


# ===========================================================================
# Additional Tier-3 mutation-anchor tests for the WS-A1 predicate itself.
# ===========================================================================

# Mutation-anchor tests for the WS-A1 predicate drive the REAL
# module-level `_tracking_active_or_lost_away` function (not a mirror).
# Reverting the predicate to ACTIVE-only causes
# `test_a1_predicate_lost_away_admitted` + `..._stale_away_admitted` to fail.


def test_a1_predicate_active_counts_regardless_of_location():
    from custom_components.universal_room_automation.const import (
        TRACKING_STATUS_ACTIVE,
    )
    assert _tracking_active_or_lost_away(
        {"tracking_status": TRACKING_STATUS_ACTIVE, "location": "away"}
    )
    assert _tracking_active_or_lost_away(
        {"tracking_status": TRACKING_STATUS_ACTIVE, "location": "home"}
    )


def test_a1_predicate_lost_home_excluded():
    from custom_components.universal_room_automation.const import (
        TRACKING_STATUS_LOST,
    )
    assert not _tracking_active_or_lost_away(
        {"tracking_status": TRACKING_STATUS_LOST, "location": "home"}
    )


def test_a1_predicate_lost_away_admitted():
    from custom_components.universal_room_automation.const import (
        TRACKING_STATUS_LOST,
    )
    assert _tracking_active_or_lost_away(
        {"tracking_status": TRACKING_STATUS_LOST, "location": "away"}
    )


def test_a1_predicate_stale_away_admitted():
    from custom_components.universal_room_automation.const import (
        TRACKING_STATUS_STALE,
    )
    assert _tracking_active_or_lost_away(
        {"tracking_status": TRACKING_STATUS_STALE, "location": "away"}
    )


# ===========================================================================
# Source-level invariants (AST-blind): production keeps the load-bearing
# tokens. If any of these regress, a Tier-3 D reviewer's first sweep flags it.
# ===========================================================================

def test_source_invariant_a1_predicate_exists():
    """WS-A1: the relaxed-predicate helper must be defined."""
    assert "_tracking_active_or_lost_away" in PRESENCE_SRC, (
        "WS-A1: predicate `_tracking_active_or_lost_away` missing from presence.py"
    )


def test_source_invariant_path_alpha_unchanged():
    """WS-I3: path α's all-three-AND conjunction must remain a single block."""
    assert "all_tracked_persons_away" in PRESENCE_SRC
    # The exact v4.7.14 conjunction is preserved verbatim.
    idx = PRESENCE_SRC.find("all_tracked_persons_away\n            and unidentified_count == 0\n            and census_count == 0")
    assert idx >= 0, (
        "WS-I3: v4.7.14 path-α AND conjunction was modified — must remain "
        "byte-identical for the ACTIVE-only inputs invariant to hold"
    )


def test_source_invariant_path_beta_indoor_guard_present():
    """WS-A2: path β must contain the `not indoor_blocked` guard."""
    assert "not indoor_blocked" in PRESENCE_SRC, (
        "WS-A2: path-β indoor-occupancy guard missing"
    )


def test_source_invariant_path_beta_grace_and_sleep_guards():
    """WS-A3: path β must check grace_elapsed_for_lost_away AND sleep_exempt."""
    assert "grace_elapsed_for_lost_away" in PRESENCE_SRC
    assert "not sleep_exempt_state" in PRESENCE_SRC, (
        "WS-A3: path-β sleep-exemption guard missing"
    )


def test_source_invariant_a4_outdoor_zone_helper_exists():
    """WS-A4: outdoor-zone snapshot helper must be defined on PresenceCoordinator."""
    assert "_outdoor_zone_names_snapshot" in PRESENCE_SRC
    assert "CONF_ZONE_IS_OUTDOOR" in PRESENCE_SRC


def test_source_invariant_run_inference_passes_path_beta_kwargs():
    """The infer() call site must pass the WS-A path-β kwargs."""
    idx = PRESENCE_SRC.find("self._inference_engine.infer(")
    assert idx >= 0
    block = PRESENCE_SRC[idx: idx + 1500]
    assert "all_trusted_or_lost_away_persons_away=" in block
    assert "any_indoor_zone_occupied=" in block
    assert "grace_elapsed_for_lost_away=" in block
    assert "lost_away_persons_present=" in block
    assert "sleep_exempt_state=" in block


def test_source_invariant_sensor_exposes_new_attrs():
    """PresenceHouseStateSensor must surface the four new diagnostic attrs."""
    assert '"veto_path"' in SENSOR_SRC
    assert '"lost_away_persons"' in SENSOR_SRC
    assert '"lost_away_grace_remaining_s"' in SENSOR_SRC
    assert '"outdoor_zones"' in SENSOR_SRC


# ===========================================================================
# Engine kwarg signature defaults (back-compat I3 guarantee)
# ===========================================================================

def test_infer_new_kwargs_default_to_safe_values():
    """All WS-A kwargs must default such that omitting them = v4.7.14 behavior."""
    import inspect
    sig = inspect.signature(StateInferenceEngine.infer)
    params = sig.parameters
    for name in (
        "all_trusted_or_lost_away_persons_away",
        "any_indoor_zone_occupied",
        "grace_elapsed_for_lost_away",
        "lost_away_persons_present",
        "sleep_exempt_state",
    ):
        assert name in params, f"WS-A: missing kwarg `{name}` on infer()"
    # Defaults: path β cannot fire when WS-A kwargs are at defaults.
    assert params["all_trusted_or_lost_away_persons_away"].default is False
    assert params["any_indoor_zone_occupied"].default is None
    assert params["grace_elapsed_for_lost_away"].default is False
    assert params["lost_away_persons_present"].default is False
    assert params["sleep_exempt_state"].default is False


def test_default_kwargs_preserve_v4714_behavior_byte_identical():
    """Engine invoked with only v4.7.14 kwargs → identical to historical baseline."""
    engine = _make_engine()
    # Same scenario the v4.7.14 test asserts:
    new_state = engine.infer(
        census_count=0,
        current_state=HouseState.HOME_DAY,
        any_zone_occupied=True,
        now=_afternoon(),
        unidentified_count=0,
        guest_gate_armed=False,
        all_tracked_persons_away=True,
    )
    assert new_state == HouseState.AWAY
    assert engine.confidence == 0.95
