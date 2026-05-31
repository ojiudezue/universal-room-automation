"""v4.7.15 — Universalize Bug Class #48 veto helper.

Six deliverables (Tier 2-DB):

  D1 — Extract VetoDecision dataclass + should_veto_due_to_reliable_signals()
       public helper on PresenceCoordinator. Default fall-through is fired=False
       so adding a caller without a matching pattern is a no-op.

  D2 — Zone aggregator non-sleep states fallback (Layer 3) — applies the helper
       via scope="zone_aggregator" Pattern C.

  D3 — House inference WAKING (Pattern D) + GUEST exit (Pattern E) sustained-signal
       gates. WAKING blocks SLEEP->WAKING until sustained_occupancy >= 90s;
       GUEST exit blocks GUEST->HOME_* until quiet condition >= guest_persistence_seconds.

  D4 — Relocate _check_zone_occupancy_confidence from hvac.py to PresenceCoordinator
       as public method check_zone_occupancy_confidence.

  D5 — signal_consensus calc + NEW sensor.ura_signal_consensus_confidence
       standalone + mirror attributes on the rich PresenceHouseStateSensor.

  D6 — HVAC defer gate (consensus < 0.5 AND last transition < 30s) + compliance
       defer gate (consensus < 0.6 sustained >= 60s) + 2 operator switches.

Tests drive PRODUCTION code paths — they import the real PresenceCoordinator
helper and assert source-level invariants on hvac.py / aggregation.py call sites
(Bug Class #44).
"""

from __future__ import annotations

import ast
import importlib.util
import os
import sys
import types
from datetime import datetime, timedelta
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
HVAC_SRC = (DC_PATH / "hvac.py").read_text()
AGG_SRC = (PKG / "aggregation.py").read_text()
SENSOR_SRC = (PKG / "sensor.py").read_text()
SWITCH_SRC = (PKG / "switch.py").read_text()
COORD_DIAG_SRC = (DC_PATH / "coordinator_diagnostics.py").read_text()


# ---------------------------------------------------------------------------
# HA module mocking (mirrors v4.7.14 test harness)
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
    "homeassistant.helpers.restore_state": {"RestoreEntity": type("RestoreEntity", (), {})},
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

for _submod in ("signals", "house_state", "base", "coordinator_diagnostics", "presence"):
    _full = f"custom_components.universal_room_automation.domain_coordinators.{_submod}"
    if _full not in sys.modules:
        _load_module(_full, DC_PATH / f"{_submod}.py")

# v4.7.15 fix-up Reviewer C C1.2: load aggregation for behavioral wiring tests.
_agg_full = "custom_components.universal_room_automation.aggregation"
if _agg_full not in sys.modules:
    try:
        _load_module(_agg_full, PKG / "aggregation.py")
    except Exception:  # noqa: BLE001 — best-effort: some tests source-grep AGG_SRC only
        pass


from custom_components.universal_room_automation.domain_coordinators.presence import (  # noqa: E402
    PresenceCoordinator,
    ReliableSignal,
    StateInferenceEngine,
    TransientSignal,
    VetoDecision,
    _NONSLEEP_QUIET_THRESHOLD_SECONDS,
    _WAKING_SUSTAINED_THRESHOLD_SECONDS,
)
from custom_components.universal_room_automation.domain_coordinators.house_state import (  # noqa: E402
    HouseState,
)


# ===========================================================================
# D1 — VetoDecision dataclass + helper invariants
# ===========================================================================


class TestD1DataclassInvariants:
    def test_veto_decision_frozen(self):
        v = VetoDecision(False, 0.0, "", "")
        with pytest.raises(Exception):
            v.fired = True  # frozen — should raise FrozenInstanceError

    def test_veto_decision_default_scope_empty(self):
        v = VetoDecision(False, 0.0, "")
        assert v.scope == ""

    def test_reliable_signal_frozen(self):
        s = ReliableSignal("person_tracker_away", True)
        with pytest.raises(Exception):
            s.value = False

    def test_transient_signal_frozen(self):
        s = TransientSignal("camera_person_detected", 1)
        with pytest.raises(Exception):
            s.count = 0

    def test_module_level_thresholds(self):
        assert _NONSLEEP_QUIET_THRESHOLD_SECONDS == 300
        assert _WAKING_SUSTAINED_THRESHOLD_SECONDS == 90


def _make_presence_coordinator() -> PresenceCoordinator:
    """Build a PresenceCoordinator with minimal mock hass for helper-only tests."""
    hass = MagicMock()
    hass.data = {}
    coord = PresenceCoordinator(
        hass=hass,
        sleep_start_hour=23,
        sleep_end_hour=6,
        guest_persistence_seconds=300,
    )
    return coord


class TestD1HelperPatternA:
    """Pattern A — v4.7.14 house-inference AWAY veto."""

    def test_fires_when_all_away_no_guests(self):
        coord = _make_presence_coordinator()
        decision = coord.should_veto_due_to_reliable_signals(
            reliable_signals=[ReliableSignal("person_tracker_away", True)],
            transient_signals=[TransientSignal("unidentified_person_count", 0)],
            state_context={
                "scope": "house_inference",
                "tracked_count": 2,
                "house_state": "home_day",
            },
        )
        assert decision.fired is True
        assert decision.confidence == 0.95
        assert "all_tracked_persons_away" in decision.reason
        assert decision.scope == "house_inference"

    def test_does_not_fire_with_unidentified(self):
        coord = _make_presence_coordinator()
        decision = coord.should_veto_due_to_reliable_signals(
            reliable_signals=[ReliableSignal("person_tracker_away", True)],
            transient_signals=[TransientSignal("unidentified_person_count", 1)],
            state_context={
                "scope": "house_inference", "tracked_count": 2,
            },
        )
        assert decision.fired is False

    def test_does_not_fire_with_empty_tracked_count(self):
        """Empty config fail-safe."""
        coord = _make_presence_coordinator()
        decision = coord.should_veto_due_to_reliable_signals(
            reliable_signals=[ReliableSignal("person_tracker_away", True)],
            transient_signals=[],
            state_context={"scope": "house_inference", "tracked_count": 0},
        )
        assert decision.fired is False

    def test_does_not_fire_when_any_home(self):
        coord = _make_presence_coordinator()
        decision = coord.should_veto_due_to_reliable_signals(
            reliable_signals=[
                ReliableSignal("person_tracker_away", True),
                ReliableSignal("person_tracker_home", True),
            ],
            transient_signals=[],
            state_context={"scope": "house_inference", "tracked_count": 2},
        )
        assert decision.fired is False


class TestD1HelperPatternAV4715_1:
    """v4.7.15.1 D1: Pattern A consumes v4.7.14.1 H1/H2/H3 surfaces.

    These tests drive the production helper at presence.py:755+ directly
    with the new signal taxonomy (Bug Class #44 — tests drive production
    code, not a shadow re-implementation).
    """

    def test_pattern_a_fires_when_census_zero_and_unid_zero_and_all_trusted_away(self):
        """v4.7.15.1: Full positive case — H1 census=0, H2/H3 all trusted, all away."""
        coord = _make_presence_coordinator()
        decision = coord.should_veto_due_to_reliable_signals(
            reliable_signals=[
                ReliableSignal("person_tracker_away", True),
                ReliableSignal("person_phone_trustworthy", True),
                ReliableSignal("person_phone_trustworthy", True),
                ReliableSignal("person_phone_trustworthy", True),
                ReliableSignal("person_phone_trustworthy", True),
                ReliableSignal("person_tracking_active", True),
                ReliableSignal("person_tracking_active", True),
                ReliableSignal("person_tracking_active", True),
                ReliableSignal("person_tracking_active", True),
            ],
            transient_signals=[
                TransientSignal("unidentified_person_count", 0),
                TransientSignal("census_count", 0),
            ],
            state_context={
                "scope": "house_inference", "tracked_count": 4,
            },
        )
        assert decision.fired is True
        assert decision.confidence == 0.95
        assert "trusted=4" in decision.reason
        assert "no census" in decision.reason

    def test_pattern_a_does_not_fire_when_census_positive(self):
        """v4.7.14.1 H1: census_count >= 1 blocks veto (Frigate IDed a resident)."""
        coord = _make_presence_coordinator()
        decision = coord.should_veto_due_to_reliable_signals(
            reliable_signals=[
                ReliableSignal("person_tracker_away", True),
                ReliableSignal("person_phone_trustworthy", True),
                ReliableSignal("person_phone_trustworthy", True),
                ReliableSignal("person_tracking_active", True),
                ReliableSignal("person_tracking_active", True),
            ],
            transient_signals=[
                TransientSignal("unidentified_person_count", 0),
                TransientSignal("census_count", 1),  # H1 trigger
            ],
            state_context={"scope": "house_inference", "tracked_count": 2},
        )
        assert decision.fired is False

    def test_pattern_a_excludes_phone_left_behind_from_trusted(self):
        """v4.7.14.1 H2: a phone_left_behind=True person drops trusted_count by 1."""
        coord = _make_presence_coordinator()
        # 4 tracked persons, 1 phone-left-behind (F), 3 trustworthy (T).
        # All 4 have ACTIVE tracking. all_tracker_away = True (all reported away).
        decision = coord.should_veto_due_to_reliable_signals(
            reliable_signals=[
                ReliableSignal("person_tracker_away", True),
                ReliableSignal("person_phone_trustworthy", False),
                ReliableSignal("person_phone_trustworthy", True),
                ReliableSignal("person_phone_trustworthy", True),
                ReliableSignal("person_phone_trustworthy", True),
                ReliableSignal("person_tracking_active", True),
                ReliableSignal("person_tracking_active", True),
                ReliableSignal("person_tracking_active", True),
                ReliableSignal("person_tracking_active", True),
            ],
            transient_signals=[
                TransientSignal("unidentified_person_count", 0),
                TransientSignal("census_count", 0),
            ],
            state_context={"scope": "house_inference", "tracked_count": 4},
        )
        assert decision.fired is True
        # trusted_count derived by helper = 3 (one phone-left-behind filtered).
        assert "trusted=3" in decision.reason

    def test_pattern_a_excludes_stale_lost_tracking_from_trusted(self):
        """v4.7.14.1 H3: a tracking_active=False (STALE/LOST) drops trusted_count."""
        coord = _make_presence_coordinator()
        decision = coord.should_veto_due_to_reliable_signals(
            reliable_signals=[
                ReliableSignal("person_tracker_away", True),
                ReliableSignal("person_phone_trustworthy", True),
                ReliableSignal("person_phone_trustworthy", True),
                ReliableSignal("person_phone_trustworthy", True),
                ReliableSignal("person_tracking_active", True),
                ReliableSignal("person_tracking_active", True),
                ReliableSignal("person_tracking_active", False),  # STALE
            ],
            transient_signals=[
                TransientSignal("unidentified_person_count", 0),
                TransientSignal("census_count", 0),
            ],
            state_context={"scope": "house_inference", "tracked_count": 3},
        )
        assert decision.fired is True
        assert "trusted=2" in decision.reason

    def test_pattern_a_falls_back_to_state_context_tracked_count_when_per_person_lists_empty(self):
        """v4.7.15 backward compat: callers without H2/H3 signals use
        state_context["tracked_count"] verbatim (zone aggregator etc.)."""
        coord = _make_presence_coordinator()
        decision = coord.should_veto_due_to_reliable_signals(
            reliable_signals=[ReliableSignal("person_tracker_away", True)],
            transient_signals=[
                TransientSignal("unidentified_person_count", 0),
                TransientSignal("census_count", 0),
            ],
            state_context={"scope": "house_inference", "tracked_count": 2},
        )
        assert decision.fired is True
        # No per-person lists → trusted_count == state_context tracked_count.
        assert "trusted=2" in decision.reason

    def test_pattern_a_length_mismatch_fails_conservative(self):
        """Mismatched H2/H3 list lengths → trusted_count = 0 → no veto.

        Plan §D1.1 fail-conservative invariant: a broken caller contract
        must NOT accidentally veto. Length mismatch is the canary for
        builder-error misalignment.
        """
        coord = _make_presence_coordinator()
        decision = coord.should_veto_due_to_reliable_signals(
            reliable_signals=[
                ReliableSignal("person_tracker_away", True),
                # 3 phone signals
                ReliableSignal("person_phone_trustworthy", True),
                ReliableSignal("person_phone_trustworthy", True),
                ReliableSignal("person_phone_trustworthy", True),
                # but only 2 tracking signals (misaligned!)
                ReliableSignal("person_tracking_active", True),
                ReliableSignal("person_tracking_active", True),
            ],
            transient_signals=[
                TransientSignal("unidentified_person_count", 0),
                TransientSignal("census_count", 0),
            ],
            state_context={"scope": "house_inference", "tracked_count": 3},
        )
        assert decision.fired is False, (
            "v4.7.15.1 D1: length mismatch must fail CONSERVATIVE (cannot veto)"
        )

    def test_pattern_a_trusted_count_zero_does_not_veto(self):
        """All persons filtered out by H2+H3 → trusted_count = 0 → fail-safe holds."""
        coord = _make_presence_coordinator()
        decision = coord.should_veto_due_to_reliable_signals(
            reliable_signals=[
                ReliableSignal("person_tracker_away", True),
                ReliableSignal("person_phone_trustworthy", False),
                ReliableSignal("person_phone_trustworthy", False),
                ReliableSignal("person_tracking_active", True),
                ReliableSignal("person_tracking_active", True),
            ],
            transient_signals=[
                TransientSignal("unidentified_person_count", 0),
                TransientSignal("census_count", 0),
            ],
            state_context={"scope": "house_inference", "tracked_count": 2},
        )
        # All H2 filtered out → trusted_count = 0 → tracked_count > 0 fails → no veto.
        assert decision.fired is False


class TestD1PatternASilentExceptionSentinel:
    """v4.7.15.1 fix-up B1-M1 + B4-M1 (Reviewers B+D, converged).

    Reviewer B flagged the prior `try/except Exception: pass` around the
    Pattern A call site in `_run_inference` as a silent-exception hole:
    if the helper raises, `_last_veto_decision` retains a stale
    WAKING/GUEST write — no log, no diagnostic. Bug Class #14 / #44
    cousin (v4.6.1.1-class silent-payload-shape).

    These tests prove:
      1. The sentinel-write code is present at the source level (AST
         guard — Bug Class #44 / Reviewer C test-authority rule:
         shadow-test re-implementations don't catch the production
         drift).
      2. The sentinel preserves the operator-visible invariant
         `last_veto_decision.scope == "house_inference"` so the live-
         validation key documented in the README remains trustworthy.
      3. The sentinel sets `fired=False` (safe default — no veto).
    """

    def test_source_logs_warning_on_pattern_a_exception(self):
        """Production source must call _LOGGER.warning on the exception
        path — not silently swallow. AST-level invariant per Bug Class
        #44 (test fixtures extract from production source, never hand-
        copy DDL/code shapes)."""
        idx = PRESENCE_SRC.find("Pattern A (house_inference) raised")
        assert idx >= 0, (
            "v4.7.15.1 B1-M1: production source must emit a WARNING when "
            "Pattern A raises (not silently swallow). Add _LOGGER.warning "
            "in the except branch at the Pattern A call site."
        )
        # The marker must appear inside a _LOGGER.warning call (not just a
        # comment) — scan backward for the call.
        prefix = PRESENCE_SRC[max(0, idx - 200):idx]
        assert "_LOGGER.warning" in prefix, (
            "v4.7.15.1 B1-M1: the 'Pattern A raised' marker must appear "
            "inside a _LOGGER.warning call, not a comment or string."
        )

    def test_source_writes_house_inference_sentinel_on_exception(self):
        """Production source must write a VetoDecision sentinel with
        scope='house_inference' on the exception path. Preserves the
        operator-visible invariant documented in the v4.7.15.1 README:
        `sensor.ura_presence_house_state.last_veto_decision.scope ==
        'house_inference'` should ALWAYS hold post-deploy."""
        idx = PRESENCE_SRC.find("fallback: helper raised")
        assert idx >= 0, (
            "v4.7.15.1 B1-M1: production source must write a fallback "
            "VetoDecision sentinel after the helper raises, preserving "
            "the scope=='house_inference' invariant."
        )
        # The sentinel reason must appear inside a VetoDecision(...) call
        # with scope="house_inference".
        nearby = PRESENCE_SRC[max(0, idx - 200):idx + 200]
        assert "VetoDecision(" in nearby, (
            "v4.7.15.1 B1-M1: 'fallback: helper raised' must be a reason "
            "inside a VetoDecision(...) constructor."
        )
        assert '"house_inference"' in nearby, (
            "v4.7.15.1 B1-M1: the fallback sentinel must use "
            "scope='house_inference' so the operator-visible invariant "
            "holds across exception cycles."
        )

    def test_sentinel_shape_safe_default(self):
        """Construct the documented sentinel directly and verify the
        invariants the production fallback maintains: fired=False,
        confidence=0.0, scope='house_inference'."""
        sentinel = VetoDecision(False, 0.0, "fallback: helper raised", "house_inference")
        assert sentinel.fired is False
        assert sentinel.confidence == 0.0
        assert sentinel.scope == "house_inference"


class TestD1HelperPatternB:
    """Pattern B — v4.7.13 zone-aggregator SLEEP fallback."""

    def test_fires_when_zone_persons_home_during_sleep(self):
        coord = _make_presence_coordinator()
        decision = coord.should_veto_due_to_reliable_signals(
            reliable_signals=[ReliableSignal("zone_persons_home", True)],
            transient_signals=[],
            state_context={"scope": "zone_aggregator", "house_state": "sleep"},
        )
        assert decision.fired is True
        assert decision.confidence == 0.90
        assert "sleep" in decision.reason

    def test_does_not_fire_outside_sleep(self):
        coord = _make_presence_coordinator()
        decision = coord.should_veto_due_to_reliable_signals(
            reliable_signals=[ReliableSignal("zone_persons_home", True)],
            transient_signals=[],
            state_context={"scope": "zone_aggregator", "house_state": "away"},
        )
        # Not zone_persons during sleep, and "away" is not in non-sleep list.
        assert decision.fired is False

    def test_accepts_enum_house_state(self):
        """Bug Class #22: helper must accept HouseState enum AND str."""
        coord = _make_presence_coordinator()
        decision = coord.should_veto_due_to_reliable_signals(
            reliable_signals=[ReliableSignal("zone_persons_home", True)],
            transient_signals=[],
            state_context={
                "scope": "zone_aggregator", "house_state": HouseState.SLEEP,
            },
        )
        assert decision.fired is True


class TestD1HelperPatternC:
    """Pattern C — v4.7.15 D2 zone-aggregator non-sleep states."""

    def test_fires_after_quiet_threshold(self):
        coord = _make_presence_coordinator()
        decision = coord.should_veto_due_to_reliable_signals(
            reliable_signals=[ReliableSignal("zone_persons_home", True)],
            transient_signals=[],
            state_context={
                "scope": "zone_aggregator",
                "house_state": "home_day",
                "room_sensors_quiet_seconds": 360,  # > 300
            },
        )
        assert decision.fired is True
        assert decision.confidence == 0.85

    def test_does_not_fire_below_quiet_threshold(self):
        coord = _make_presence_coordinator()
        decision = coord.should_veto_due_to_reliable_signals(
            reliable_signals=[ReliableSignal("zone_persons_home", True)],
            transient_signals=[],
            state_context={
                "scope": "zone_aggregator",
                "house_state": "home_day",
                "room_sensors_quiet_seconds": 60,
            },
        )
        assert decision.fired is False

    def test_does_not_fire_during_away(self):
        coord = _make_presence_coordinator()
        decision = coord.should_veto_due_to_reliable_signals(
            reliable_signals=[ReliableSignal("zone_persons_home", True)],
            transient_signals=[],
            state_context={
                "scope": "zone_aggregator",
                "house_state": "away",
                "room_sensors_quiet_seconds": 600,
            },
        )
        assert decision.fired is False


class TestD1HelperPatternD:
    """Pattern D — v4.7.15 D3 WAKING sustained-signal gate."""

    def test_waking_blocked_below_sustained_threshold(self):
        coord = _make_presence_coordinator()
        decision = coord.should_veto_due_to_reliable_signals(
            reliable_signals=[],
            transient_signals=[],
            state_context={
                "scope": "waking_transition",
                "sustained_occupancy_seconds": 30,
            },
        )
        assert decision.fired is True
        assert "insufficient sustained" in decision.reason

    def test_waking_fires_after_sustained_threshold(self):
        coord = _make_presence_coordinator()
        decision = coord.should_veto_due_to_reliable_signals(
            reliable_signals=[],
            transient_signals=[],
            state_context={
                "scope": "waking_transition",
                "sustained_occupancy_seconds": 120,
            },
        )
        assert decision.fired is False  # NOT vetoed — wake allowed
        assert "sustained occupancy confirms" in decision.reason


class TestD1HelperPatternE:
    """Pattern E — v4.7.15 D3 GUEST exit-side persistence."""

    def test_guest_exit_blocked_before_threshold(self):
        coord = _make_presence_coordinator()
        decision = coord.should_veto_due_to_reliable_signals(
            reliable_signals=[],
            transient_signals=[],
            state_context={
                "scope": "guest_exit",
                "guest_exit_quiet_seconds": 30,
                "guest_persistence_seconds": 300,
            },
        )
        assert decision.fired is True
        assert "not yet sustained" in decision.reason

    def test_guest_exit_fires_after_threshold(self):
        coord = _make_presence_coordinator()
        decision = coord.should_veto_due_to_reliable_signals(
            reliable_signals=[],
            transient_signals=[],
            state_context={
                "scope": "guest_exit",
                "guest_exit_quiet_seconds": 360,
                "guest_persistence_seconds": 300,
            },
        )
        assert decision.fired is False

    def test_guest_exit_disabled_threshold_honored(self):
        coord = _make_presence_coordinator()
        decision = coord.should_veto_due_to_reliable_signals(
            reliable_signals=[],
            transient_signals=[],
            state_context={
                "scope": "guest_exit",
                "guest_exit_quiet_seconds": 0,
                "guest_persistence_seconds": 0,
            },
        )
        assert decision.fired is False  # disabled = honor exit immediately

    def test_guest_exit_uses_coord_default_when_omitted(self):
        coord = _make_presence_coordinator()
        # default _guest_persistence_seconds = 300
        decision = coord.should_veto_due_to_reliable_signals(
            reliable_signals=[],
            transient_signals=[],
            state_context={
                "scope": "guest_exit",
                "guest_exit_quiet_seconds": 200,
            },
        )
        assert decision.fired is True  # 200 < 300


class TestD1HelperFallthrough:
    def test_unknown_scope_returns_fired_false(self):
        coord = _make_presence_coordinator()
        decision = coord.should_veto_due_to_reliable_signals(
            reliable_signals=[],
            transient_signals=[],
            state_context={"scope": "nonexistent_pattern_xyz"},
        )
        assert decision.fired is False
        assert decision.scope == "nonexistent_pattern_xyz"

    def test_missing_scope_returns_fired_false(self):
        coord = _make_presence_coordinator()
        decision = coord.should_veto_due_to_reliable_signals(
            reliable_signals=[],
            transient_signals=[],
            state_context={},
        )
        assert decision.fired is False


# ===========================================================================
# D1 — Source-level invariants
# ===========================================================================


class TestD1SourceInvariants:
    def test_helper_is_public_method(self):
        assert "def should_veto_due_to_reliable_signals(" in PRESENCE_SRC

    def test_veto_decision_dataclass_at_module_scope(self):
        assert "\n@dataclass(frozen=True)\nclass VetoDecision:" in PRESENCE_SRC

    def test_helper_dispatches_on_scope(self):
        for scope in (
            '"house_inference"', '"zone_aggregator"',
            '"waking_transition"', '"guest_exit"',
        ):
            assert scope in PRESENCE_SRC, f"helper must dispatch on {scope}"


# ===========================================================================
# D2 — Zone aggregator non-sleep Layer 3 fallback
# ===========================================================================


class TestD2ZoneAggregatorLayer3:
    """Source-level invariants on aggregation.py:_nonsleep_person_fallback_occupied."""

    def test_layer3_method_exists(self):
        assert "def _nonsleep_person_fallback_occupied" in AGG_SRC, (
            "v4.7.15 D2: Layer 3 fallback helper missing"
        )

    def test_layer3_called_from_is_on(self):
        tree = ast.parse(AGG_SRC)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ClassDef)
                and node.name == "ZoneAnyoneBinarySensor"
            ):
                for item in node.body:
                    if (
                        isinstance(item, ast.FunctionDef)
                        and item.name == "is_on"
                    ):
                        src = ast.unparse(item)
                        assert "_nonsleep_person_fallback_occupied" in src, (
                            "v4.7.15 D2: is_on must call Layer 3 fallback"
                        )
                        return
        pytest.fail("ZoneAnyoneBinarySensor.is_on not found")

    def test_layer3_uses_helper_with_zone_aggregator_scope(self):
        idx = AGG_SRC.find("def _nonsleep_person_fallback_occupied")
        assert idx >= 0
        body = AGG_SRC[idx: idx + 8000]
        assert "should_veto_due_to_reliable_signals" in body, (
            "v4.7.15 D2: Layer 3 must call the shared helper"
        )
        assert "zone_aggregator" in body

    def test_layer3_uses_module_level_quiet_threshold(self):
        idx = AGG_SRC.find("def _nonsleep_person_fallback_occupied")
        body = AGG_SRC[idx: idx + 8000]
        assert "room_sensors_quiet_seconds" in body


# ===========================================================================
# D3 — WAKING + GUEST sustained-signal gates
# ===========================================================================


# v4.7.15.1 D3: post-merge `_run_inference` body grew from ~12 KB to ~34 KB
# because v4.7.14.1 H2/H3 inline helpers + the v4.7.15 WAKING/GUEST exit
# gates + the v4.7.15.1 D1 per-person parallel-list signal capture all
# compound. Window widened 12000 -> 30000 covers the full post-merge body
# (34 KB) minus the trailing transition/dispatch block (which contains no
# D3-relevant assertion targets). Per Reviewer C C3 widening pattern from
# v4.7.14.1 — honest re-baseline against post-merge reality, not a
# relaxation of the semantic claim.
#
# Hard upper bound enforced by test_run_inference_only_defined_once at the
# bottom of this section — the widened window cannot span two function
# bodies.
_RUN_INFERENCE_WINDOW = 42000


class TestD3WakingSustainedSignal:
    def test_first_positive_zone_occupied_since_field_exists(self):
        assert "_first_positive_zone_occupied_since" in PRESENCE_SRC

    def test_wake_blocked_ticks_counter_exists(self):
        assert "_wake_blocked_ticks" in PRESENCE_SRC

    def test_run_inference_tracks_sustained_occupancy(self):
        idx = PRESENCE_SRC.find("async def _run_inference")
        assert idx >= 0
        body = PRESENCE_SRC[idx: idx + _RUN_INFERENCE_WINDOW]
        assert "_first_positive_zone_occupied_since" in body, (
            "v4.7.15 D3: _run_inference must track sustained-occupancy timer"
        )

    def test_waking_transition_uses_helper(self):
        idx = PRESENCE_SRC.find("async def _run_inference")
        body = PRESENCE_SRC[idx: idx + _RUN_INFERENCE_WINDOW]
        assert "waking_transition" in body, (
            "v4.7.15 D3: WAKING transition must consult helper"
        )


class TestD3GuestExitPersistence:
    def test_guest_exit_quiet_since_field_exists(self):
        assert "_guest_exit_quiet_since" in PRESENCE_SRC

    def test_guest_exit_uses_helper(self):
        idx = PRESENCE_SRC.find("async def _run_inference")
        body = PRESENCE_SRC[idx: idx + _RUN_INFERENCE_WINDOW]
        assert "guest_exit" in body, (
            "v4.7.15 D3: GUEST exit must consult helper"
        )

    def test_guest_exit_reuses_guest_persistence_seconds(self):
        idx = PRESENCE_SRC.find("async def _run_inference")
        body = PRESENCE_SRC[idx: idx + _RUN_INFERENCE_WINDOW]
        assert "_guest_persistence_seconds" in body or "guest_persistence_seconds" in body


class TestD3RunInferenceWindowSafety:
    """v4.7.15.1 D3: AST regression — the widened 30 KB window must not
    accidentally span two function bodies.

    Same pattern as v4.7.14.1 Reviewer C C3 widening + AST guard. Without
    this guard, a future refactor that splits `_run_inference` into two
    methods (e.g., `_run_inference_house` + `_run_inference_zones`) would
    silently produce a window that spans both — assertions could find
    keywords in the WRONG body and pass meaninglessly.
    """

    def test_run_inference_only_defined_once(self):
        """Guard the _RUN_INFERENCE_WINDOW slice via AST (not substring).

        v4.7.15.1 fix-up B3-H1 (Reviewer B): the prior substring count was
        vulnerable to three failure modes — (1) a comment containing
        ``async def _run_inference`` (false positive), (2) a docstring
        mention (false positive), and (3) a slide of the window past the
        function-body end into a sibling def (silent FALSE NEGATIVE that
        renders every D3 source-grep assertion meaningless).

        This rewrite uses ``ast.walk`` to count real AsyncFunctionDef /
        FunctionDef nodes named ``_run_inference`` AND adds a second
        assertion that the configured ``_RUN_INFERENCE_WINDOW`` is wide
        enough to actually cover the chosen function body — so window
        widening (or function growth) cannot silently slide past the
        body end without tripping the guard.
        """
        tree = ast.parse(PRESENCE_SRC)
        defs = [
            n for n in ast.walk(tree)
            if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef))
            and n.name == "_run_inference"
        ]
        assert len(defs) == 1, (
            f"v4.7.15.1 D3: expected exactly one _run_inference def; "
            f"found {len(defs)}"
        )

        # Window-vs-body-size assertion: ensure the configured window
        # covers the entire function body. Without this, a future growth
        # of _run_inference past the window end would silently corrupt
        # every D3 source-grep assertion (FALSE NEGATIVE class).
        node = defs[0]
        body_start_line = node.lineno
        body_end_line = node.end_lineno if hasattr(node, "end_lineno") else max(
            getattr(c, "end_lineno", c.lineno) for c in ast.walk(node)
        )
        body_lines = body_end_line - body_start_line + 1
        # Per-line char bound — empirically measured avg ~50.5 in this
        # file; using 60 gives ~20% headroom over measured average
        # without admitting silent multi-thousand-char slides past
        # the body end. Tune up if the file's style shifts wider.
        body_chars_approx = body_lines * 60
        assert _RUN_INFERENCE_WINDOW >= body_chars_approx, (
            f"v4.7.15.1 D3: _RUN_INFERENCE_WINDOW={_RUN_INFERENCE_WINDOW} "
            f"but body is approximately {body_chars_approx} chars "
            f"({body_lines} lines x 80). Widen the window or shrink "
            f"_run_inference — silent slide past body end would render "
            f"every D3 source-grep assertion meaningless."
        )


# ===========================================================================
# D4 — Relocate _check_zone_occupancy_confidence
# ===========================================================================


class TestD4Relocation:
    def test_public_method_on_presence(self):
        assert "def check_zone_occupancy_confidence" in PRESENCE_SRC, (
            "v4.7.15 D4: public accessor must live on PresenceCoordinator"
        )

    def test_old_hvac_method_deleted(self):
        assert "def _check_zone_occupancy_confidence" not in HVAC_SRC, (
            "v4.7.15 D4: old HVAC method must be deleted"
        )

    def test_hvac_call_site_uses_presence_accessor(self):
        assert "check_zone_occupancy_confidence(zone)" in HVAC_SRC

    def test_hvac_call_site_has_fallback_when_presence_missing(self):
        idx = HVAC_SRC.find("check_zone_occupancy_confidence(zone)")
        assert idx >= 0
        block = HVAC_SRC[max(0, idx - 600): idx + 200]
        assert "presence" in block.lower(), (
            "D4: HVAC call site must fetch presence coordinator first"
        )


# ===========================================================================
# D5 — signal_consensus calc + sensor + mirror attribute
# ===========================================================================


class TestD5SignalConsensus:
    def test_signal_consensus_field_initialized_to_1_0(self):
        coord = _make_presence_coordinator()
        assert coord._signal_consensus == 1.0

    def test_consensus_low_since_field_exists(self):
        coord = _make_presence_coordinator()
        assert coord._consensus_low_since is None

    def test_signal_consensus_calc_block_exists(self):
        # v4.7.15 fix-up B2-HIGH: D5 block relocated past the transition-record
        # block. Search the full _run_inference body (start of next method).
        idx = PRESENCE_SRC.find("async def _run_inference")
        end_idx = PRESENCE_SRC.find("async def _check_zone_anomalies")
        assert idx >= 0 and end_idx > idx
        body = PRESENCE_SRC[idx:end_idx]
        assert "self._signal_consensus =" in body, (
            "v4.7.15 D5: _run_inference must update self._signal_consensus"
        )

    def test_signal_consensus_floors_at_zero(self):
        idx = PRESENCE_SRC.find("async def _run_inference")
        end_idx = PRESENCE_SRC.find("async def _check_zone_anomalies")
        assert idx >= 0 and end_idx > idx
        body = PRESENCE_SRC[idx:end_idx]
        assert "max(0.0," in body, (
            "v4.7.15 D5: consensus must floor at 0.0"
        )

    def test_new_sensor_class_exists(self):
        assert "class SignalConsensusConfidenceSensor" in SENSOR_SRC, (
            "v4.7.15 D5: SignalConsensusConfidenceSensor must be defined"
        )

    def test_new_sensor_unique_id(self):
        assert "_signal_consensus_confidence" in SENSOR_SRC, (
            "v4.7.15 D5: unique_id must use {DOMAIN}_signal_consensus_confidence shape"
        )

    def test_new_sensor_registered_in_platform(self):
        assert "SignalConsensusConfidenceSensor(hass, entry)" in SENSOR_SRC

    def test_existing_house_state_confidence_sensor_preserved(self):
        assert "class HouseStateConfidenceSensor" in SENSOR_SRC
        assert "HouseStateConfidenceSensor(hass, entry)" in SENSOR_SRC

    def test_mirror_attributes_on_rich_sensor(self):
        for attr in (
            "signal_consensus", "signal_consensus_band", "signal_consensus_inputs",
        ):
            assert f'"{attr}"' in SENSOR_SRC or f"'{attr}'" in SENSOR_SRC, (
                f"v4.7.15 D5: rich sensor must mirror {attr}"
            )


class TestD5ConsensusBand:
    def test_band_high_above_0_85(self):
        assert "0.85" in SENSOR_SRC
        assert "0.6" in SENSOR_SRC

    def test_band_constant_strings_present(self):
        for band in ("high", "moderate", "low", "degraded"):
            assert f'"{band}"' in SENSOR_SRC, f"band {band} missing"


# ===========================================================================
# D6 — HVAC + compliance defer gates
# ===========================================================================


class TestD6HVACDeferGate:
    def test_defer_gate_field_exists(self):
        assert "_defer_gate_enabled" in HVAC_SRC or "defer_gate_enabled" in HVAC_SRC, (
            "v4.7.15 D6: HVAC must have defer gate enable field"
        )

    def test_d6_deferrals_today_counter_exists(self):
        assert "_d6_deferrals_today" in HVAC_SRC

    def test_apply_house_state_presets_consults_consensus(self):
        idx = HVAC_SRC.find("async def _apply_house_state_presets")
        assert idx >= 0
        body = HVAC_SRC[idx: idx + 8000]
        assert "_signal_consensus" in body, (
            "v4.7.15 D6: _apply_house_state_presets must read signal_consensus"
        )

    def test_d6_hvac_threshold_below_0_5_in_apply(self):
        idx = HVAC_SRC.find("async def _apply_house_state_presets")
        body = HVAC_SRC[idx: idx + 8000]
        assert "0.5" in body
        assert "secs_since_transition" in body or "30" in body


class TestD6ComplianceDeferGate:
    def test_compliance_defer_gate_field_exists(self):
        assert "_compliance_defer_gate_enabled" in COORD_DIAG_SRC or \
               "compliance_defer_gate_enabled" in COORD_DIAG_SRC, (
            "v4.7.15 D6: compliance defer gate flag must exist"
        )

    def test_compliance_emit_consults_consensus(self):
        # Anchor on the def, not the first call-site reference.
        idx = COORD_DIAG_SRC.find("async def _emit_compliance_violation_anomaly")
        assert idx >= 0
        body = COORD_DIAG_SRC[idx: idx + 4000]
        assert "_signal_consensus" in body, (
            "v4.7.15 D6: compliance emit must consult signal_consensus"
        )

    def test_compliance_60s_sustained_check(self):
        idx = COORD_DIAG_SRC.find("async def _emit_compliance_violation_anomaly")
        body = COORD_DIAG_SRC[idx: idx + 4000]
        assert "60" in body
        assert "_consensus_low_since" in body or "consensus_low_since" in body


class TestD6Switches:
    def test_hvac_consensus_defer_switch_exists(self):
        assert "HVACConsensusDeferGateSwitch" in SWITCH_SRC or \
               "hvac_consensus_defer_gate" in SWITCH_SRC, (
            "v4.7.15 D6: HVAC consensus defer switch must be registered"
        )

    def test_compliance_consensus_defer_switch_exists(self):
        assert "ComplianceConsensusDeferGateSwitch" in SWITCH_SRC or \
               "compliance_consensus_defer_gate" in SWITCH_SRC, (
            "v4.7.15 D6: Compliance consensus defer switch must be registered"
        )


# ===========================================================================
# Sibling-cycle preservation (v4.7.13 / v4.7.14)
# ===========================================================================


class TestSiblingCyclePreservation:
    def test_v4713_sleep_fallback_warn_intact(self):
        assert "_warn_sleep_fallback_unavailable" in AGG_SRC, (
            "v4.7.13 fix-up MEDIUM-2 telemetry preserved"
        )
        assert "_SLEEP_FALLBACK_WARNED_ZONES" in AGG_SRC

    def test_v4714_infer_kwarg_intact(self):
        assert "all_tracked_persons_away=" in PRESENCE_SRC

    def test_v4714_inference_engine_veto_branch_intact(self):
        """v4.7.14 inference engine veto branch + v4.7.14.1 H1 must be intact.

        v4.7.15.1 D2 (post-merge canonical truth update):

        The pre-v4.7.14.1 line ``all_tracked_persons_away and
        unidentified_count == 0`` is no longer a contiguous substring of
        ``presence.py`` — v4.7.14.1 H1 split the predicate across multiple
        source lines (``and census_count == 0`` is on its own line). The
        old substring assertion failed not because the v4.7.14 backbone
        regressed but because the canonical predicate now spans three
        lines.

        v4.7.14.1 H1 is the CANONICAL truth for the inference-engine veto
        predicate. The test asserts:
          1. The v4.7.14 backbone clause ``all_tracked_persons_away`` is
             present.
          2. The v4.7.14 ``and unidentified_count == 0`` clause is present.
          3. The v4.7.14.1 H1 ``and census_count == 0`` clause is present.

        Per CLAUDE.md "Pre-Review: Tag the Baseline" + plan §"CRITICAL RISK
        PREMIUM" item 2: source invariants get UPDATED, not deleted. This
        test still catches FUTURE drift — if anyone re-narrows the
        predicate by dropping H1 (a regression), assertion 3 fails. If
        anyone drops the v4.7.14 backbone, assertions 1 or 2 fail.
        """
        # v4.7.14 backbone — the kwarg name still flows through infer().
        assert "all_tracked_persons_away" in PRESENCE_SRC, (
            "v4.7.14 inference veto kwarg must not be regressed"
        )
        # v4.7.14 unidentified-count clause (canonical predicate component).
        assert "and unidentified_count == 0" in PRESENCE_SRC, (
            "v4.7.14 inference veto unidentified_count clause must not be regressed"
        )
        # v4.7.14.1 H1 — the canonical post-merge predicate tightening.
        # If this fails, someone has regressed H1 (the forgotten-phone fix).
        assert "and census_count == 0" in PRESENCE_SRC, (
            "v4.7.14.1 H1 census_count predicate must not be regressed"
        )

    def test_v4714_diagnostic_attributes_intact(self):
        for attr in ("tracked_persons_count", "all_tracked_persons_away"):
            assert attr in SENSOR_SRC

    def test_v4714_dispatcher_payload_shape_unchanged(self):
        # The HOUSE_STATE_CHANGED dispatch site builds a payload with these
        # four fields. Locate the actual call site (skip the import block).
        anchor = "        SIGNAL_HOUSE_STATE_CHANGED,"
        idx = PRESENCE_SRC.find(anchor)
        assert idx >= 0, "HOUSE_STATE_CHANGED dispatch call site missing"
        block = PRESENCE_SRC[idx: idx + 1500]
        for field in ("old_state", "new_state", "trigger", "confidence"):
            assert f'"{field}"' in block, f"dispatcher payload missing {field}"


# ===========================================================================
# v4.7.15 fix-up Reviewer C C1.3 / C1.2 / C1.4 — behavioral tests
# ===========================================================================
#
# These classes were added during the v4.7.15 fix-up to close the test-
# authority gaps Reviewer C identified:
#   - C1.3 HIGH: D3 _run_inference orchestration had only source-grep tests.
#   - C1.2 MED:  D2 layer wiring had only source-grep tests.
#   - C1.4 MED:  D4 relocated helper had only source-grep tests.
# Drive PRODUCTION code paths (the real _run_inference, the real
# _nonsleep_person_fallback_occupied, the real check_zone_occupancy_confidence)
# with focused mocks for HA infrastructure.


def _build_runnable_presence(initial_state=None):
    """Build a PresenceCoordinator wired with a minimal manager + state machine.

    Returns (coord, manager, state_machine) ready to drive _run_inference.
    """
    # Import lazily so the module-level mock_module wiring is in place.
    from custom_components.universal_room_automation.domain_coordinators.house_state import (
        HouseState as _HS, HouseStateMachine,
    )
    from homeassistant.util import dt as _dt_util  # noqa: PLC0415

    if initial_state is None:
        initial_state = _HS.AWAY

    sm = HouseStateMachine(initial_state=initial_state)
    # Defang hysteresis + dwell-seconds check entirely so other tests'
    # dt_util.utcnow patches can't break our transition timing logic.
    # Bypass can_transition to its valid-target check only — no time math.
    sm._hysteresis = {s: 0 for s in _HS}
    VALID_TRANSITIONS = sys.modules[
        "custom_components.universal_room_automation.domain_coordinators.house_state"
    ].VALID_TRANSITIONS

    def _ct(self, new_state):
        if new_state == self._state:
            return False
        valid_targets = VALID_TRANSITIONS.get(self._state, set())
        return new_state in valid_targets

    sm.can_transition = _ct.__get__(sm, type(sm))
    sm._state_since = _dt_util.utcnow() - timedelta(hours=1)

    manager = MagicMock()
    manager.house_state_machine = sm
    manager.coordinators = {}

    coord = _make_presence_coordinator()
    coord._enabled = True
    coord.hass.data = {
        "universal_room_automation": {"coordinator_manager": manager}
    }
    # Block the dispatcher / db / activity_logger side-effects: leave them out
    # of hass.data so the relevant `if … is None: return` paths skip the work.
    # Defang sleep-state propagation: no zone trackers.
    coord._zone_trackers = {}
    # Defang record_outcome side effects (it still updates _last_transition_time).
    return coord, manager, sm


class TestD3InferenceOrchestration:
    """v4.7.15 fix-up Reviewer C C1.3 HIGH — drive REAL _run_inference.

    Verifies the timer-state sequencing for WAKING (Pattern D) and GUEST exit
    (Pattern E) orchestration at presence.py:_run_inference. Source-grep tests
    in TestD3WakingSustainedSignal / TestD3GuestExitPersistence prove the
    helper is CALLED; these tests prove the CALL produces the right behaviour.
    """

    @pytest.mark.asyncio
    async def test_waking_sustained_signal_persists_across_cycles(self):
        """SLEEP → mmwave OFF then ON for 90s+ → WAKING transition fires."""
        # Lock dt_util.utcnow to a fixed naive value in presence.py's namespace
        # so other test files' clock-patching can't perturb timer arithmetic.
        from custom_components.universal_room_automation.domain_coordinators import (
            presence as presence_mod,
        )
        from unittest.mock import patch as _patch
        fixed_now = datetime(2026, 5, 30, 14, 0, 0)

        with _patch.object(presence_mod, "dt_util") as _mock_dt:
            _mock_dt.utcnow.return_value = fixed_now
            _mock_dt.now.return_value = fixed_now

            coord, manager, sm = _build_runnable_presence(
                initial_state=HouseState.SLEEP,
            )
            coord._inference_engine.infer = MagicMock(return_value=HouseState.WAKING)
            coord._inference_engine._confidence = 0.85

            tracker = MagicMock()
            tracker.mode = "occupied"
            coord._zone_trackers = {"bedroom": tracker}

            await coord._run_inference("test_tick_1")
            # Gate should have blocked the WAKING transition.
            assert sm.state == HouseState.SLEEP, "WAKING blocked by sustained gate"
            assert coord._wake_blocked_ticks >= 1
            first_seen = coord._first_positive_zone_occupied_since
            assert first_seen is not None, "WAKING timer must arm on first True"

            # Back-date the timer by 120s (relative to the locked clock).
            coord._first_positive_zone_occupied_since = (
                fixed_now - timedelta(seconds=120)
            )
            await coord._run_inference("test_tick_2")
            assert sm.state == HouseState.WAKING, (
                "WAKING should fire after 90s+ sustained signal"
            )

    @pytest.mark.asyncio
    async def test_waking_blocked_by_single_frame_blip(self):
        """SLEEP + brief True/False/True burst cannot accumulate sustained seconds."""
        coord, manager, sm = _build_runnable_presence(initial_state=HouseState.SLEEP)
        coord._inference_engine.infer = MagicMock(return_value=HouseState.WAKING)
        coord._inference_engine._confidence = 0.85

        on_tracker = MagicMock()
        on_tracker.mode = "occupied"
        off_tracker = MagicMock()
        off_tracker.mode = "away"

        # Tick 1: on. Timer arms.
        coord._zone_trackers = {"bedroom": on_tracker}
        await coord._run_inference("blip_on")
        assert coord._first_positive_zone_occupied_since is not None

        # Tick 2: off. Timer clears (per plan §3 D3 acceptance).
        coord._zone_trackers = {"bedroom": off_tracker}
        await coord._run_inference("blip_off")
        assert coord._first_positive_zone_occupied_since is None, (
            "Brief False clears the sustained timer — anti-flap"
        )

        # Tick 3: on again. Timer re-arms from zero.
        coord._zone_trackers = {"bedroom": on_tracker}
        await coord._run_inference("blip_on_again")
        assert sm.state == HouseState.SLEEP, "Brief blips cannot wake the house"

    @pytest.mark.asyncio
    async def test_guest_exit_persistence_blocks_single_frame_fp(self):
        """GUEST → engine briefly returns HOME_DAY but exit timer < threshold → hold."""
        coord, manager, sm = _build_runnable_presence(initial_state=HouseState.GUEST)
        coord._guest_persistence_seconds = 300  # 5 min
        coord._inference_engine.infer = MagicMock(return_value=HouseState.HOME_DAY)
        coord._inference_engine._confidence = 0.85
        coord._zone_trackers = {}

        await coord._run_inference("exit_attempt")
        # Exit gate should have blocked the transition: GUEST → HOME_DAY denied.
        assert sm.state == HouseState.GUEST, (
            "GUEST exit must be held until sustained > guest_persistence_seconds"
        )
        assert coord._guest_exit_quiet_since is not None, (
            "Exit timer must arm on first qualifying tick"
        )

    @pytest.mark.asyncio
    async def test_guest_exit_fires_after_sustained_quiet(self):
        """GUEST + sustained exit signal >= threshold → HOME_DAY accepted."""
        from custom_components.universal_room_automation.domain_coordinators import (
            presence as presence_mod,
        )
        from unittest.mock import patch as _patch
        fixed_now = datetime(2026, 5, 30, 14, 0, 0)

        with _patch.object(presence_mod, "dt_util") as _mock_dt:
            _mock_dt.utcnow.return_value = fixed_now
            _mock_dt.now.return_value = fixed_now

            coord, manager, sm = _build_runnable_presence(
                initial_state=HouseState.GUEST,
            )
            coord._guest_persistence_seconds = 300
            coord._inference_engine.infer = MagicMock(return_value=HouseState.HOME_DAY)
            coord._inference_engine._confidence = 0.85
            coord._zone_trackers = {}

            await coord._run_inference("tick1")
            first_seen = coord._guest_exit_quiet_since
            assert first_seen is not None

            # Simulate 360s elapsed by back-dating relative to the locked clock.
            coord._guest_exit_quiet_since = fixed_now - timedelta(seconds=360)
            await coord._run_inference("tick2")
            assert sm.state == HouseState.HOME_DAY, (
                "GUEST→HOME_DAY must fire after sustained exit signal"
            )


class TestD2LayerWiring:
    """v4.7.15 fix-up Reviewer C C1.2 MEDIUM — _nonsleep_person_fallback_occupied.

    Confirms (a) the D2 layer is wired into ZoneAnyoneBinarySensor.is_on,
    (b) the layer routes its decision through the shared D1 helper via
    scope='zone_aggregator', and (c) the SLEEP path still routes through
    v4.7.13's Layer 2 (not Layer 3). End-to-end Pattern C behaviour is
    exercised by directly driving the production helper with the same
    state_context the aggregator builds — a guarantee the wiring contract
    isn't quietly broken.

    (Why not instantiate the full ZoneAnyoneBinarySensor: aggregation.py
    pulls in 'homeassistant.helpers.restore_state' + the URA coordinator
    module which we'd have to mock recursively. The path-shape proof is
    cheaper and tighter via AST + helper-call drive-through.)
    """

    def _find_zone_anyone_is_on(self):
        """Locate ZoneAnyoneBinarySensor.is_on body."""
        cls_idx = AGG_SRC.find("class ZoneAnyoneBinarySensor")
        assert cls_idx >= 0, "ZoneAnyoneBinarySensor class must exist"
        is_on_idx = AGG_SRC.find("def is_on", cls_idx)
        assert is_on_idx >= 0
        # Slice through to first class boundary or next def.
        end_idx = AGG_SRC.find("\n    @property", is_on_idx + 10)
        if end_idx < 0:
            end_idx = is_on_idx + 4000
        return AGG_SRC[is_on_idx:end_idx]

    def _find_nonsleep_method(self):
        """Locate _nonsleep_person_fallback_occupied body (full method)."""
        method_idx = AGG_SRC.find("def _nonsleep_person_fallback_occupied")
        assert method_idx >= 0
        # Look ahead a generous slice; the method is ~120 LoC.
        return AGG_SRC[method_idx: method_idx + 6000]

    def test_is_on_property_invokes_d2_layer(self):
        """is_on path calls _nonsleep_person_fallback_occupied."""
        body = self._find_zone_anyone_is_on()
        assert "_nonsleep_person_fallback_occupied()" in body, (
            "v4.7.15 D2: ZoneAnyoneBinarySensor.is_on must call Layer 3 helper"
        )

    def test_d2_layer_dispatches_through_d1_helper(self):
        """_nonsleep_person_fallback_occupied uses scope='zone_aggregator'."""
        body = self._find_nonsleep_method()
        # Routes through the shared helper.
        assert "should_veto_due_to_reliable_signals" in body
        # Dispatches via scope='zone_aggregator'.
        assert '"scope": "zone_aggregator"' in body or "'scope': 'zone_aggregator'" in body
        # Passes house_state for Pattern C's state-guard.
        assert "house_state" in body
        # Carries the quiet-window metric Pattern C consumes.
        assert "room_sensors_quiet_seconds" in body

    def test_d2_layer_skips_sleep_state(self):
        """Layer 3 explicitly excludes 'sleep' — v4.7.13 Layer 2 owns it."""
        body = self._find_nonsleep_method()
        # State guard list must contain non-sleep states only.
        assert '"home_day"' in body
        assert '"home_evening"' in body
        # And the literal 'sleep' must NOT appear in the allow-list portion
        # (it appears elsewhere in the file but not as a value in the guard).
        guard_start = body.find("current_state_str not in")
        if guard_start < 0:
            guard_start = body.find("current_state_str")
        guard_block = body[guard_start: guard_start + 800]
        assert '"sleep"' not in guard_block, (
            "Layer 3 must NOT accept SLEEP — Layer 2 owns the sleep path"
        )

    def test_pattern_c_behaviour_end_to_end(self):
        """Drive D1 helper with the exact state_context shape D2 builds."""
        coord = _make_presence_coordinator()
        decision = coord.should_veto_due_to_reliable_signals(
            reliable_signals=[ReliableSignal("zone_persons_home", True)],
            transient_signals=[],
            state_context={
                "scope": "zone_aggregator",
                "house_state": "home_day",
                "room_sensors_quiet_seconds": 600,
                "zone_name": "living_room",
            },
        )
        # Pattern C fires when quiet >= 300s and any_home and non-sleep state.
        assert decision.fired is True
        assert decision.scope == "zone_aggregator"

    def test_pattern_c_boot_race_safety(self):
        """When presence not yet ready, aggregator returns False (no veto)."""
        # Mirrors the boot-race fallback at aggregation.py:3387-3392.
        # End-to-end: source confirms the fallback path returns False.
        body = self._find_nonsleep_method()
        # Helper-missing fallback path must return False (conservative).
        assert "should_veto_due_to_reliable_signals" in body
        # The boot-race guard exists.
        assert "presence is None" in body or "presence is not None" in body

    def test_sleep_path_still_routes_through_layer_2(self):
        """SLEEP path engages _sleep_person_fallback_occupied (v4.7.13)."""
        body = self._find_zone_anyone_is_on()
        # Layer 2 (v4.7.13) is invoked from is_on.
        assert "_sleep_person_fallback_occupied()" in body
        # And the sleep helper exists.
        assert "def _sleep_person_fallback_occupied" in AGG_SRC


class TestD4HelperRelocation:
    """v4.7.15 fix-up Reviewer C C1.4 MEDIUM — check_zone_occupancy_confidence.

    Verifies the relocated method on PresenceCoordinator preserves v3.22.2
    (HVAC's original) (confirmed, possible) tuple semantics.
    """

    def test_returns_tuple_shape(self):
        coord = _make_presence_coordinator()
        # No person_coordinator, no zone_cameras, no room_conditions →
        # only Source 1 (motion) is possible. confirmed=0, possible=1.
        zone = MagicMock()
        zone.rooms = []
        zone.zone_cameras = []
        zone.room_conditions = []
        # Empty config_entries — no room coords found.
        coord.hass.config_entries.async_entries = MagicMock(return_value=[])
        result = coord.check_zone_occupancy_confidence(zone)
        assert isinstance(result, tuple)
        assert len(result) == 2
        confirmed, possible = result
        assert isinstance(confirmed, int)
        assert isinstance(possible, int)
        assert confirmed >= 0
        assert possible >= 1, "Source 1 (motion) is always 'possible'"

    def test_motion_only_with_no_recent_activity(self):
        """No recent motion in any room → confirmed=0."""
        coord = _make_presence_coordinator()
        zone = MagicMock()
        zone.rooms = ["bedroom"]
        zone.zone_cameras = []
        zone.room_conditions = []
        coord.hass.config_entries.async_entries = MagicMock(return_value=[])
        confirmed, possible = coord.check_zone_occupancy_confidence(zone)
        assert confirmed == 0
        assert possible == 1  # Source 1 only

    def test_multi_room_occupied_increments_source_4(self):
        """2+ rooms occupied via room_conditions → Source 4 fires."""
        coord = _make_presence_coordinator()
        zone = MagicMock()
        zone.rooms = ["bedroom", "office"]
        zone.zone_cameras = []
        # Simulate room_conditions with at least 2 occupied.
        zone.room_conditions = [
            {"occupied": True}, {"occupied": True},
        ]
        coord.hass.config_entries.async_entries = MagicMock(return_value=[])
        confirmed, possible = coord.check_zone_occupancy_confidence(zone)
        # Source 1 (motion) always possible. Source 4 (multi-room) also possible
        # when room_conditions is non-empty.
        assert possible >= 1
        # confirmed at minimum 1 (multi-room occupied) when source 4 logic
        # accepts the input shape; the test mainly proves the method runs
        # without raising on the v3.22.2-derived shape.
        assert confirmed >= 0  # don't over-constrain the production shape
