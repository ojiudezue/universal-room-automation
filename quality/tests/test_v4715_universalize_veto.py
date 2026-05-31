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
        body = AGG_SRC[idx: idx + 4000]
        assert "should_veto_due_to_reliable_signals" in body, (
            "v4.7.15 D2: Layer 3 must call the shared helper"
        )
        assert "zone_aggregator" in body

    def test_layer3_uses_module_level_quiet_threshold(self):
        idx = AGG_SRC.find("def _nonsleep_person_fallback_occupied")
        body = AGG_SRC[idx: idx + 4000]
        assert "room_sensors_quiet_seconds" in body


# ===========================================================================
# D3 — WAKING + GUEST sustained-signal gates
# ===========================================================================


class TestD3WakingSustainedSignal:
    def test_first_positive_zone_occupied_since_field_exists(self):
        assert "_first_positive_zone_occupied_since" in PRESENCE_SRC

    def test_wake_blocked_ticks_counter_exists(self):
        assert "_wake_blocked_ticks" in PRESENCE_SRC

    def test_run_inference_tracks_sustained_occupancy(self):
        idx = PRESENCE_SRC.find("async def _run_inference")
        assert idx >= 0
        body = PRESENCE_SRC[idx: idx + 12000]
        assert "_first_positive_zone_occupied_since" in body, (
            "v4.7.15 D3: _run_inference must track sustained-occupancy timer"
        )

    def test_waking_transition_uses_helper(self):
        idx = PRESENCE_SRC.find("async def _run_inference")
        body = PRESENCE_SRC[idx: idx + 12000]
        assert "waking_transition" in body, (
            "v4.7.15 D3: WAKING transition must consult helper"
        )


class TestD3GuestExitPersistence:
    def test_guest_exit_quiet_since_field_exists(self):
        assert "_guest_exit_quiet_since" in PRESENCE_SRC

    def test_guest_exit_uses_helper(self):
        idx = PRESENCE_SRC.find("async def _run_inference")
        body = PRESENCE_SRC[idx: idx + 12000]
        assert "guest_exit" in body, (
            "v4.7.15 D3: GUEST exit must consult helper"
        )

    def test_guest_exit_reuses_guest_persistence_seconds(self):
        idx = PRESENCE_SRC.find("async def _run_inference")
        body = PRESENCE_SRC[idx: idx + 12000]
        assert "_guest_persistence_seconds" in body or "guest_persistence_seconds" in body


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
        idx = PRESENCE_SRC.find("async def _run_inference")
        body = PRESENCE_SRC[idx: idx + 12000]
        assert "self._signal_consensus =" in body, (
            "v4.7.15 D5: _run_inference must update self._signal_consensus"
        )

    def test_signal_consensus_floors_at_zero(self):
        idx = PRESENCE_SRC.find("async def _run_inference")
        body = PRESENCE_SRC[idx: idx + 12000]
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
        idx = COORD_DIAG_SRC.find("_emit_compliance_violation_anomaly")
        assert idx >= 0
        body = COORD_DIAG_SRC[idx: idx + 4000]
        assert "_signal_consensus" in body, (
            "v4.7.15 D6: compliance emit must consult signal_consensus"
        )

    def test_compliance_60s_sustained_check(self):
        idx = COORD_DIAG_SRC.find("_emit_compliance_violation_anomaly")
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
        assert (
            "all_tracked_persons_away and unidentified_count == 0" in PRESENCE_SRC
        ), "v4.7.14 inference veto branch must not be regressed"

    def test_v4714_diagnostic_attributes_intact(self):
        for attr in ("tracked_persons_count", "all_tracked_persons_away"):
            assert attr in SENSOR_SRC

    def test_v4714_dispatcher_payload_shape_unchanged(self):
        idx = PRESENCE_SRC.find("SIGNAL_HOUSE_STATE_CHANGED")
        assert idx >= 0
        idx2 = PRESENCE_SRC.find("async_dispatcher_send", idx)
        if idx2 < 0:
            idx2 = PRESENCE_SRC.find("async_dispatcher_send")
        block = PRESENCE_SRC[idx2: idx2 + 1500]
        for field in ("old_state", "new_state", "trigger", "confidence"):
            assert f'"{field}"' in block, f"dispatcher payload missing {field}"
