"""Tests for v3.6.0 C0-diag: Coordinator Diagnostics Framework.

Tests cover:
- DecisionLogger: log_decision, get_decisions, get_decisions_count
- ComplianceTracker: schedule_check, _compare_states, compliance rate
- AnomalyDetector: record_observation, z-score classification, baselines
- MetricBaseline: Welford's online algorithm, z_score
- AnomalyRecord and AnomalySeverity
- OutcomeMeasurer: store_outcome
- CoordinatorManager diagnostics injection and enable/disable
- BaseCoordinator diagnostics summary
- New constants (enable/disable keys, retention, scope)
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
import sys
import os
import types

# ---------------------------------------------------------------------------
# Mock homeassistant and its submodules before importing URA code.
# ---------------------------------------------------------------------------

def _mock_module(name, **attrs):
    """Create a mock module with given attributes."""
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


_identity = lambda fn: fn  # noqa: E731
_mock_cls = MagicMock

_mods = {
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
        "async_call_later": lambda hass, delay, cb: _mock_cls(),
    },
    "homeassistant.helpers.dispatcher": {},
    "homeassistant.helpers.update_coordinator": {
        "DataUpdateCoordinator": _mock_cls,
        "UpdateFailed": Exception,
    },
    "homeassistant.helpers.selector": _mock_cls(),
    "homeassistant.helpers.entity_registry": {"async_get": _mock_cls()},
    "homeassistant.helpers.sun": {},
    "homeassistant.util": {},
    "homeassistant.util.dt": {
        "utcnow": datetime.utcnow,
        "now": datetime.now,
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

for name, attrs in _mods.items():
    if isinstance(attrs, dict):
        sys.modules.setdefault(name, _mock_module(name, **attrs))
    else:
        sys.modules.setdefault(name, attrs)

# Mock aiosqlite
sys.modules.setdefault("aiosqlite", MagicMock())

# Add project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import importlib

_cc = types.ModuleType("custom_components")
_cc.__path__ = [os.path.join(os.path.dirname(__file__), "..", "..", "custom_components")]
sys.modules.setdefault("custom_components", _cc)

_ura = types.ModuleType("custom_components.universal_room_automation")
_ura_path = os.path.join(_cc.__path__[0], "universal_room_automation")
_ura.__path__ = [_ura_path]
_ura.__package__ = "custom_components.universal_room_automation"
sys.modules["custom_components.universal_room_automation"] = _ura

# Import const.py
_const_spec = importlib.util.spec_from_file_location(
    "custom_components.universal_room_automation.const",
    os.path.join(_ura_path, "const.py"),
)
_const_mod = importlib.util.module_from_spec(_const_spec)
sys.modules["custom_components.universal_room_automation.const"] = _const_mod
_const_spec.loader.exec_module(_const_mod)
_ura.const = _const_mod

# Import domain_coordinators subpackage
_dc_path = os.path.join(_ura_path, "domain_coordinators")
_dc = types.ModuleType("custom_components.universal_room_automation.domain_coordinators")
_dc.__path__ = [_dc_path]
_dc.__package__ = "custom_components.universal_room_automation.domain_coordinators"
sys.modules["custom_components.universal_room_automation.domain_coordinators"] = _dc
_ura.domain_coordinators = _dc

for _submod_name in ("signals", "house_state", "base", "coordinator_diagnostics", "manager"):
    _full_name = f"custom_components.universal_room_automation.domain_coordinators.{_submod_name}"
    _spec = importlib.util.spec_from_file_location(
        _full_name, os.path.join(_dc_path, f"{_submod_name}.py"),
    )
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules[_full_name] = _mod
    _spec.loader.exec_module(_mod)
    setattr(_dc, _submod_name, _mod)


# ---------------------------------------------------------------------------
# Imports under test
# ---------------------------------------------------------------------------

from custom_components.universal_room_automation.domain_coordinators.coordinator_diagnostics import (
    AnomalyDetector,
    AnomalyRecord,
    AnomalySeverity,
    ComplianceRecord,
    ComplianceState,
    ComplianceTracker,
    DecisionLog,
    DecisionLogger,
    LearningStatus,
    MetricBaseline,
    OutcomeMeasurement,
    OutcomeMeasurer,
)
from custom_components.universal_room_automation.domain_coordinators.base import (
    BaseCoordinator,
    CoordinatorAction,
    Intent,
    Severity,
    ActionType,
)
from custom_components.universal_room_automation.domain_coordinators.manager import (
    CoordinatorManager,
)
from custom_components.universal_room_automation.const import (
    CONF_PRESENCE_ENABLED,
    CONF_SAFETY_ENABLED,
    CONF_SECURITY_ENABLED,
    CONF_ENERGY_ENABLED,
    CONF_HVAC_ENABLED,
    CONF_COMFORT_ENABLED,
    COORDINATOR_ENABLED_KEYS,
    DIAGNOSTICS_SCOPE_HOUSE,
    RETENTION_ANOMALY_LOG,
    RETENTION_OUTCOME_LOG,
    RETENTION_PARAMETER_HISTORY,
)


# ============================================================================
# Helpers
# ============================================================================

def make_hass():
    """Create a mock HomeAssistant instance."""
    hass = MagicMock()
    hass.data = {}
    return hass


class StubCoordinator(BaseCoordinator):
    """Concrete coordinator for testing."""

    async def async_setup(self):
        pass

    async def evaluate(self, intents, context):
        return []

    async def async_teardown(self):
        pass


# ============================================================================
# MetricBaseline Tests
# ============================================================================

class TestMetricBaseline:
    """Tests for MetricBaseline Welford's online algorithm."""

    def test_initial_state(self):
        b = MetricBaseline("test", "energy", "house")
        assert b.mean == 0.0
        assert b.variance == 1.0
        assert b.sample_count == 0
        assert b.std > 0

    def test_single_update(self):
        b = MetricBaseline("test", "energy", "house")
        b.update(10.0)
        assert b.sample_count == 1
        assert b.mean == 10.0
        assert b.variance == 0.0

    def test_multiple_updates(self):
        b = MetricBaseline("test", "energy", "house")
        values = [10.0, 12.0, 14.0, 16.0, 18.0]
        for v in values:
            b.update(v)
        assert b.sample_count == 5
        assert abs(b.mean - 14.0) < 0.01
        # Variance should be population variance of [10,12,14,16,18]
        # = mean of squared deviations = (16+4+0+4+16)/5 = 8.0
        assert abs(b.variance - 8.0) < 0.01

    def test_z_score_normal(self):
        b = MetricBaseline("test", "energy", "house")
        # Manually set known stats
        b.mean = 10.0
        b.variance = 4.0  # std = 2.0
        b.sample_count = 100
        assert abs(b.z_score(14.0) - 2.0) < 0.01

    def test_z_score_zero_variance_uses_floor(self):
        """When variance is 0 (constant data), min floor prevents extreme z-scores."""
        b = MetricBaseline("test", "energy", "house")
        b.mean = 5.0
        b.variance = 0.0
        # std floor is sqrt(0.01) = 0.1, so z-score = |10-5|/0.1 = 50
        # Still high but bounded, not infinite
        z = b.z_score(10.0)
        assert z == pytest.approx(50.0, rel=0.01)

    def test_last_updated_set(self):
        b = MetricBaseline("test", "energy", "house")
        assert b.last_updated is None
        b.update(5.0)
        assert b.last_updated is not None


# ============================================================================
# AnomalySeverity Tests
# ============================================================================

class TestAnomalySeverity:
    """Tests for AnomalySeverity enum values."""

    def test_severity_values(self):
        assert AnomalySeverity.NOMINAL.value == "nominal"
        assert AnomalySeverity.ADVISORY.value == "advisory"
        assert AnomalySeverity.ALERT.value == "alert"
        assert AnomalySeverity.CRITICAL.value == "critical"

    def test_learning_status_values(self):
        assert LearningStatus.INSUFFICIENT_DATA.value == "insufficient_data"
        assert LearningStatus.LEARNING.value == "learning"
        assert LearningStatus.ACTIVE.value == "active"
        assert LearningStatus.PAUSED.value == "paused"


# ============================================================================
# AnomalyDetector Tests
# ============================================================================

class TestAnomalyDetector:
    """Tests for the AnomalyDetector base class."""

    def test_initialization(self):
        hass = make_hass()
        detector = AnomalyDetector(
            hass=hass,
            coordinator_id="energy",
            metric_names=["grid_import_kwh", "solar_production"],
            minimum_samples=48,
        )
        assert detector.coordinator_id == "energy"
        assert len(detector.metric_names) == 2
        assert detector.minimum_samples == 48

    def test_no_anomaly_below_minimum_samples(self):
        """Should not detect anomalies before minimum samples reached."""
        hass = make_hass()
        detector = AnomalyDetector(
            hass=hass,
            coordinator_id="presence",
            metric_names=["transitions"],
            minimum_samples=10,
        )
        # Record 5 observations — below minimum
        for i in range(5):
            result = detector.record_observation("transitions", "house", 5.0)
            assert result is None

    def test_no_anomaly_for_normal_values(self):
        """After sufficient samples, normal values should not trigger."""
        hass = make_hass()
        detector = AnomalyDetector(
            hass=hass,
            coordinator_id="presence",
            metric_names=["transitions"],
            minimum_samples=10,
        )
        # Build baseline with some natural variation
        import random
        random.seed(42)
        for _ in range(20):
            detector.record_observation("transitions", "house", 5.0 + random.uniform(-0.5, 0.5))

        # Value within normal range should not trigger
        result = detector.record_observation("transitions", "house", 5.1)
        assert result is None

    def test_anomaly_for_extreme_value(self):
        """Extreme deviation should trigger anomaly."""
        hass = make_hass()
        detector = AnomalyDetector(
            hass=hass,
            coordinator_id="energy",
            metric_names=["grid_import"],
            minimum_samples=10,
        )
        # Build stable baseline around 2.0
        for _ in range(20):
            detector.record_observation("grid_import", "house", 2.0 + 0.1 * (_ % 3))

        # Extreme value
        result = detector.record_observation("grid_import", "house", 100.0)
        assert result is not None
        assert isinstance(result, AnomalyRecord)
        assert result.coordinator_id == "energy"
        assert result.metric_name == "grid_import"
        assert result.severity in (
            AnomalySeverity.ADVISORY,
            AnomalySeverity.ALERT,
            AnomalySeverity.CRITICAL,
        )
        assert result.z_score > 2.0

    def test_severity_classification(self):
        hass = make_hass()
        detector = AnomalyDetector(
            hass=hass,
            coordinator_id="test",
            metric_names=["m1"],
        )
        assert detector._classify_severity(1.5) == AnomalySeverity.NOMINAL
        assert detector._classify_severity(2.5) == AnomalySeverity.ADVISORY
        assert detector._classify_severity(3.5) == AnomalySeverity.ALERT
        assert detector._classify_severity(5.0) == AnomalySeverity.CRITICAL

    def test_learning_status_insufficient(self):
        hass = make_hass()
        detector = AnomalyDetector(
            hass=hass,
            coordinator_id="test",
            metric_names=["m1", "m2"],
            minimum_samples=10,
        )
        assert detector.get_learning_status() == "insufficient_data"

    def test_learning_status_learning(self):
        hass = make_hass()
        detector = AnomalyDetector(
            hass=hass,
            coordinator_id="test",
            metric_names=["m1", "m2"],
            minimum_samples=10,
        )
        # Add some samples to m1 but not enough
        for _ in range(5):
            detector.record_observation("m1", "house", 1.0)
        assert detector.get_learning_status() == "learning"

    def test_learning_status_active(self):
        hass = make_hass()
        detector = AnomalyDetector(
            hass=hass,
            coordinator_id="test",
            metric_names=["m1"],
            minimum_samples=5,
        )
        for _ in range(10):
            detector.record_observation("m1", "house", 1.0)
        assert detector.get_learning_status() == "active"

    def test_get_status_summary(self):
        hass = make_hass()
        detector = AnomalyDetector(
            hass=hass,
            coordinator_id="energy",
            metric_names=["grid_import"],
            minimum_samples=5,
        )
        for _ in range(10):
            detector.record_observation("grid_import", "house", 2.0)

        summary = detector.get_status_summary()
        assert summary["coordinator_id"] == "energy"
        assert summary["learning_status"] == "active"
        assert "grid_import" in summary["metrics"]
        assert summary["metrics"]["grid_import"]["active"] is True
        assert summary["metrics"]["grid_import"]["sample_count"] == 10

    def test_worst_severity_nominal_when_empty(self):
        hass = make_hass()
        detector = AnomalyDetector(
            hass=hass,
            coordinator_id="test",
            metric_names=["m1"],
        )
        assert detector.get_worst_severity() == AnomalySeverity.NOMINAL

    def test_worst_metric_empty_when_no_anomalies(self):
        hass = make_hass()
        detector = AnomalyDetector(
            hass=hass,
            coordinator_id="test",
            metric_names=["m1"],
        )
        name, z = detector.get_worst_metric()
        assert name == ""
        assert z == 0.0

    def test_clear_active_anomalies(self):
        hass = make_hass()
        detector = AnomalyDetector(
            hass=hass,
            coordinator_id="test",
            metric_names=["m1"],
            minimum_samples=5,
        )
        # Build baseline and trigger anomaly
        for _ in range(10):
            detector.record_observation("m1", "house", 1.0)
        detector.record_observation("m1", "house", 100.0)
        assert len(detector._active_anomalies) > 0
        detector.clear_active_anomalies()
        assert len(detector._active_anomalies) == 0

    def test_scope_isolation(self):
        """Baselines should be isolated per scope."""
        hass = make_hass()
        detector = AnomalyDetector(
            hass=hass,
            coordinator_id="presence",
            metric_names=["transitions"],
            minimum_samples=5,
        )
        # Different scopes build independent baselines
        for _ in range(10):
            detector.record_observation("transitions", "room:kitchen", 3.0)
            detector.record_observation("transitions", "room:bedroom", 1.0)

        kitchen = detector._get_baseline("transitions", "room:kitchen")
        bedroom = detector._get_baseline("transitions", "room:bedroom")
        assert abs(kitchen.mean - 3.0) < 0.01
        assert abs(bedroom.mean - 1.0) < 0.01


# ============================================================================
# ComplianceTracker Tests
# ============================================================================

class TestComplianceTracker:
    """Tests for compliance state comparison logic."""

    def test_climate_compliant(self):
        hass = make_hass()
        tracker = ComplianceTracker(hass)
        compliant, deviation = tracker._compare_states(
            {"target_temp_high": 75.0},
            {"target_temp_high": 75.0},
            "climate",
        )
        assert compliant is True
        assert deviation is None

    def test_climate_non_compliant_temp(self):
        hass = make_hass()
        tracker = ComplianceTracker(hass)
        compliant, deviation = tracker._compare_states(
            {"target_temp_high": 75.0},
            {"target_temp_high": 78.0},
            "climate",
        )
        assert compliant is False
        assert deviation["field"] == "target_temp_high"
        assert deviation["delta"] == 3.0

    def test_climate_non_compliant_preset(self):
        hass = make_hass()
        tracker = ComplianceTracker(hass)
        compliant, deviation = tracker._compare_states(
            {"preset_mode": "home"},
            {"preset_mode": "manual"},
            "climate",
        )
        assert compliant is False
        assert deviation["field"] == "preset_mode"

    def test_light_compliant(self):
        hass = make_hass()
        tracker = ComplianceTracker(hass)
        compliant, _ = tracker._compare_states(
            {"state": "on"},
            {"state": "on"},
            "light",
        )
        assert compliant is True

    def test_light_non_compliant(self):
        hass = make_hass()
        tracker = ComplianceTracker(hass)
        compliant, deviation = tracker._compare_states(
            {"state": "on"},
            {"state": "off"},
            "light",
        )
        assert compliant is False
        assert deviation["field"] == "state"

    def test_cover_compliant_within_tolerance(self):
        hass = make_hass()
        tracker = ComplianceTracker(hass)
        compliant, _ = tracker._compare_states(
            {"position": 50},
            {"position": 53},
            "cover",
        )
        assert compliant is True  # Within 5 tolerance

    def test_cover_non_compliant(self):
        hass = make_hass()
        tracker = ComplianceTracker(hass)
        compliant, deviation = tracker._compare_states(
            {"position": 50},
            {"position": 100},
            "cover",
        )
        assert compliant is False
        assert deviation["field"] == "position"

    def test_extract_state_climate(self):
        hass = make_hass()
        tracker = ComplianceTracker(hass)
        state = MagicMock()
        state.state = "heat"
        state.attributes = {
            "preset_mode": "home",
            "target_temp_high": 78,
            "target_temp_low": 68,
        }
        result = tracker._extract_state(state, "climate")
        assert result["hvac_mode"] == "heat"
        assert result["preset_mode"] == "home"
        assert result["target_temp_high"] == 78

    def test_extract_state_none(self):
        hass = make_hass()
        tracker = ComplianceTracker(hass)
        assert tracker._extract_state(None, "light") == {}

    def test_extract_state_light(self):
        hass = make_hass()
        tracker = ComplianceTracker(hass)
        state = MagicMock()
        state.state = "on"
        result = tracker._extract_state(state, "light")
        assert result["state"] == "on"


# ============================================================================
# DecisionLog and ComplianceRecord Data Class Tests
# ============================================================================

class TestDataClasses:
    """Tests for diagnostic data classes."""

    def test_decision_log_creation(self):
        dl = DecisionLog(
            timestamp=datetime.utcnow(),
            coordinator_id="energy",
            decision_type="tou_transition",
            scope="house",
            situation_classified="EXPENSIVE",
            urgency=80,
            confidence=0.95,
        )
        assert dl.coordinator_id == "energy"
        assert dl.scope == "house"
        assert dl.urgency == 80
        assert dl.constraints_published == []
        assert dl.devices_commanded == []

    def test_compliance_record_defaults(self):
        cr = ComplianceRecord(
            timestamp=datetime.utcnow(),
            decision_id=1,
            scope="room:kitchen",
            device_type="light",
            device_id="light.kitchen",
        )
        assert cr.compliant is True
        assert cr.override_detected is False
        assert cr.override_source is None

    def test_anomaly_record_creation(self):
        ar = AnomalyRecord(
            timestamp=datetime.utcnow(),
            coordinator_id="presence",
            scope="room:kitchen",
            metric_name="room_transitions",
            observed_value=15.0,
            expected_mean=3.0,
            expected_std=1.5,
            z_score=8.0,
            severity=AnomalySeverity.CRITICAL,
            sample_size=200,
        )
        assert ar.severity == AnomalySeverity.CRITICAL
        assert ar.resolved is False

    def test_outcome_measurement_defaults(self):
        om = OutcomeMeasurement(
            timestamp=datetime.utcnow(),
            coordinator_id="energy",
            period_start=datetime.utcnow() - timedelta(hours=1),
            period_end=datetime.utcnow(),
            scope="house",
        )
        assert om.decisions_in_period == 0
        assert om.compliance_rate == 1.0
        assert om.metrics == {}


# ============================================================================
# BaseCoordinator Diagnostics Integration Tests
# ============================================================================

class TestBaseCoordinatorDiagnostics:
    """Tests for BaseCoordinator diagnostics attributes and summary."""

    def test_diagnostics_attributes_initialized_none(self):
        hass = make_hass()
        coord = StubCoordinator(hass, "presence", "Presence", 60)
        assert coord.decision_logger is None
        assert coord.compliance_tracker is None
        assert coord.anomaly_detector is None

    def test_diagnostics_summary_without_detector(self):
        hass = make_hass()
        coord = StubCoordinator(hass, "presence", "Presence", 60)
        summary = coord.get_diagnostics_summary()
        assert summary["coordinator_id"] == "presence"
        assert summary["enabled"] is True
        assert summary["anomaly"]["learning_status"] == "not_configured"

    def test_diagnostics_summary_with_detector(self):
        hass = make_hass()
        coord = StubCoordinator(hass, "presence", "Presence", 60)
        detector = AnomalyDetector(
            hass=hass,
            coordinator_id="presence",
            metric_names=["transitions"],
            minimum_samples=5,
        )
        coord.anomaly_detector = detector

        summary = coord.get_diagnostics_summary()
        assert summary["anomaly"]["learning_status"] == "insufficient_data"
        assert summary["anomaly"]["worst_severity"] == "nominal"


# ============================================================================
# CoordinatorManager Diagnostics Tests
# ============================================================================

class TestCoordinatorManagerDiagnostics:
    """Tests for CoordinatorManager diagnostics features."""

    def test_register_injects_diagnostics(self):
        hass = make_hass()
        manager = CoordinatorManager(hass)
        coord = StubCoordinator(hass, "presence", "Presence", 60)
        assert coord.decision_logger is None

        manager.register_coordinator(coord)
        assert coord.decision_logger is not None
        assert coord.compliance_tracker is not None

    def test_enable_disable_coordinator(self):
        hass = make_hass()
        manager = CoordinatorManager(hass)
        coord = StubCoordinator(hass, "presence", "Presence", 60)
        manager.register_coordinator(coord)

        assert coord.enabled is True
        # Disable returns a coroutine, but for sync test we check the method exists
        status = manager.get_coordinator_status("presence")
        assert status["status"] == "enabled"

    def test_get_coordinator_status_not_registered(self):
        hass = make_hass()
        manager = CoordinatorManager(hass)
        status = manager.get_coordinator_status("unknown")
        assert status["status"] == "not_registered"

    def test_system_anomaly_status_no_detectors(self):
        hass = make_hass()
        manager = CoordinatorManager(hass)
        coord = StubCoordinator(hass, "presence", "Presence", 60)
        manager.register_coordinator(coord)

        status = manager.get_system_anomaly_status()
        assert status["state"] == "nominal"
        assert status["active_anomalies"] == 0
        assert status["learning_status"]["presence"] == "not_configured"

    def test_system_anomaly_status_with_detector(self):
        hass = make_hass()
        manager = CoordinatorManager(hass)
        coord = StubCoordinator(hass, "energy", "Energy", 40)
        detector = AnomalyDetector(
            hass=hass,
            coordinator_id="energy",
            metric_names=["grid_import"],
            minimum_samples=5,
        )
        coord.anomaly_detector = detector
        manager.register_coordinator(coord)

        # Build baseline
        for _ in range(10):
            detector.record_observation("grid_import", "house", 2.0)

        status = manager.get_system_anomaly_status()
        assert status["state"] == "nominal"
        assert status["learning_status"]["energy"] == "active"

    def test_diagnostics_summary(self):
        hass = make_hass()
        manager = CoordinatorManager(hass)
        coord = StubCoordinator(hass, "presence", "Presence", 60)
        manager.register_coordinator(coord)

        summary = manager.get_diagnostics_summary()
        assert "system_anomaly" in summary
        assert "coordinators" in summary
        assert "presence" in summary["coordinators"]

    def test_decision_logger_property(self):
        hass = make_hass()
        manager = CoordinatorManager(hass)
        assert isinstance(manager.decision_logger, DecisionLogger)

    def test_compliance_tracker_property(self):
        hass = make_hass()
        manager = CoordinatorManager(hass)
        assert isinstance(manager.compliance_tracker, ComplianceTracker)


# ============================================================================
# Constants Tests
# ============================================================================

class TestDiagnosticsConstants:
    """Tests for new C0-diag constants."""

    def test_enable_config_keys_exist(self):
        assert CONF_PRESENCE_ENABLED == "presence_coordinator_enabled"
        assert CONF_SAFETY_ENABLED == "safety_coordinator_enabled"
        assert CONF_SECURITY_ENABLED == "security_coordinator_enabled"
        assert CONF_ENERGY_ENABLED == "energy_coordinator_enabled"
        assert CONF_HVAC_ENABLED == "hvac_coordinator_enabled"
        assert CONF_COMFORT_ENABLED == "comfort_coordinator_enabled"

    def test_coordinator_enabled_keys_mapping(self):
        assert COORDINATOR_ENABLED_KEYS["presence"] == "presence_coordinator_enabled"
        assert COORDINATOR_ENABLED_KEYS["energy"] == "energy_coordinator_enabled"
        assert COORDINATOR_ENABLED_KEYS["music_following"] == "music_following_coordinator_enabled"
        assert len(COORDINATOR_ENABLED_KEYS) == 8

    def test_retention_constants(self):
        assert RETENTION_ANOMALY_LOG == 90
        assert RETENTION_OUTCOME_LOG == 365
        assert RETENTION_PARAMETER_HISTORY == 365

    def test_scope_constant(self):
        assert DIAGNOSTICS_SCOPE_HOUSE == "house"


# ============================================================================
# ComplianceState Tests
# ============================================================================

class TestComplianceState:
    """Tests for ComplianceState enum."""

    def test_values(self):
        assert ComplianceState.FULL.value == "full"
        assert ComplianceState.PARTIAL.value == "partial"
        assert ComplianceState.OVERRIDDEN.value == "overridden"
