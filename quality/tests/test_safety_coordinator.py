"""Tests for v3.6.0 C2: Safety Coordinator.

Tests cover:
- HazardType: enum values, all 12 types
- RateOfChangeDetector: temp drop/rise detection, extreme rise, humidity spike,
  bathroom exclusion, season detection, shoulder season both-directions
- AlertDeduplicator: suppression windows, different severities, window expiry
- SafetyCoordinator: initialization, binary hazard (smoke), binary hazard (leak),
  numeric hazard (CO thresholds), flooding escalation (multi-sensor), flooding
  escalation (sustained), temperature freeze, temperature overheat, humidity
  normal room thresholds, humidity bathroom thresholds, humidity low, TVOC
  detection, light patterns, test hazard service, diagnostics summary,
  hazard clearing
- TestRoomTypeHumidityThresholds: normal room, bathroom, basement thresholds
- TestSeasonDetection: heating season, cooling season, shoulder season
"""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import sys
import os
import types

# ---------------------------------------------------------------------------
# Mock homeassistant and its submodules before importing URA code.
# ---------------------------------------------------------------------------

def _mock_module(name, **attrs):
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
        existing = sys.modules.get(name)
        if existing is None:
            sys.modules[name] = _mock_module(name, **attrs)
        else:
            for k, v in attrs.items():
                if not hasattr(existing, k):
                    setattr(existing, k, v)
    else:
        sys.modules.setdefault(name, attrs)

sys.modules.setdefault("aiosqlite", MagicMock())
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

_const_spec = importlib.util.spec_from_file_location(
    "custom_components.universal_room_automation.const",
    os.path.join(_ura_path, "const.py"),
)
_const_mod = importlib.util.module_from_spec(_const_spec)
sys.modules["custom_components.universal_room_automation.const"] = _const_mod
_const_spec.loader.exec_module(_const_mod)
_ura.const = _const_mod

_dc_path = os.path.join(_ura_path, "domain_coordinators")
_dc = types.ModuleType("custom_components.universal_room_automation.domain_coordinators")
_dc.__path__ = [_dc_path]
_dc.__package__ = "custom_components.universal_room_automation.domain_coordinators"
sys.modules["custom_components.universal_room_automation.domain_coordinators"] = _dc
_ura.domain_coordinators = _dc

for _submod_name in ("signals", "house_state", "base", "coordinator_diagnostics", "manager", "presence", "safety"):
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

from custom_components.universal_room_automation.domain_coordinators.safety import (
    AlertDeduplicator,
    FLOODING_SUSTAINED_MINUTES,
    Hazard,
    HazardType,
    HUMIDITY_THRESHOLDS,
    LIGHT_PATTERNS,
    LOW_HUMIDITY_THRESHOLDS,
    NUMERIC_THRESHOLDS,
    RateOfChangeDetector,
    SafetyCoordinator,
    _UNAVAILABLE_STATES,
)
from custom_components.universal_room_automation.domain_coordinators.base import (
    CoordinatorAction,
    Intent,
    Severity,
)
from custom_components.universal_room_automation.domain_coordinators.manager import (
    CoordinatorManager,
)


# ============================================================================
# Helpers
# ============================================================================

def make_hass():
    hass = MagicMock()
    hass.data = {}
    hass.states = MagicMock()
    hass.states.async_all.return_value = []
    hass.states.get.return_value = None
    hass.config_entries = MagicMock()
    hass.config_entries.async_entries.return_value = []
    return hass


def make_now(month=6, day=15, hour=12):
    """Create a datetime for testing, defaulting to June (cooling season)."""
    return datetime(2026, month, day, hour, 0, 0)


# ============================================================================
# HazardType Tests
# ============================================================================


class TestHazardType:
    """Tests for the HazardType enum."""

    def test_all_12_types_exist(self):
        """All 12 hazard types should be defined."""
        expected = [
            "smoke", "fire", "water_leak", "flooding",
            "carbon_monoxide", "high_co2", "high_tvoc",
            "freeze_risk", "overheat", "hvac_failure",
            "high_humidity", "low_humidity",
        ]
        actual = [ht.value for ht in HazardType]
        assert sorted(actual) == sorted(expected)

    def test_hazard_type_is_str_enum(self):
        """HazardType values should be strings."""
        assert isinstance(HazardType.SMOKE.value, str)
        assert HazardType.SMOKE == "smoke"

    def test_hazard_type_values(self):
        """Verify specific enum values."""
        assert HazardType.SMOKE.value == "smoke"
        assert HazardType.FIRE.value == "fire"
        assert HazardType.WATER_LEAK.value == "water_leak"
        assert HazardType.FLOODING.value == "flooding"
        assert HazardType.CARBON_MONOXIDE.value == "carbon_monoxide"
        assert HazardType.HIGH_CO2.value == "high_co2"
        assert HazardType.HIGH_TVOC.value == "high_tvoc"
        assert HazardType.FREEZE_RISK.value == "freeze_risk"
        assert HazardType.OVERHEAT.value == "overheat"
        assert HazardType.HVAC_FAILURE.value == "hvac_failure"
        assert HazardType.HIGH_HUMIDITY.value == "high_humidity"
        assert HazardType.LOW_HUMIDITY.value == "low_humidity"


# ============================================================================
# RateOfChangeDetector Tests
# ============================================================================


class TestRateOfChangeDetector:
    """Tests for rate-of-change detection."""

    def test_no_history_returns_none(self):
        """With no readings, rate should be None."""
        detector = RateOfChangeDetector()
        assert detector.get_rate("sensor.test") is None

    def test_single_reading_returns_none(self):
        """With only one reading, rate should be None."""
        detector = RateOfChangeDetector()
        now = make_now()
        detector.record("sensor.test", now, 72.0)
        assert detector.get_rate("sensor.test", now) is None

    def test_temperature_drop_detection(self):
        """Rapid temperature drop should be detected in heating season."""
        detector = RateOfChangeDetector()
        now = make_now(month=1, day=15)  # January = heating season
        # Record a 6-degree drop over 20 minutes
        detector.record("sensor.temp", now - timedelta(minutes=20), 72.0)
        detector.record("sensor.temp", now, 63.0)  # Dropped 9 degrees in 20min

        results = detector.check_thresholds("sensor.temp", "temperature", "normal", now)
        hazard_types = [r[1] for r in results]
        assert HazardType.HVAC_FAILURE in hazard_types

    def test_temperature_rise_detection(self):
        """Rapid temperature rise should be detected in cooling season."""
        detector = RateOfChangeDetector()
        now = make_now(month=7, day=15)  # July = cooling season
        # Record a 6-degree rise over 20 minutes
        detector.record("sensor.temp", now - timedelta(minutes=20), 72.0)
        detector.record("sensor.temp", now, 81.0)  # Rose 9 degrees in 20min

        results = detector.check_thresholds("sensor.temp", "temperature", "normal", now)
        hazard_types = [r[1] for r in results]
        assert HazardType.HVAC_FAILURE in hazard_types

    def test_extreme_temperature_rise(self):
        """Extreme temperature rise (>10F/30min) should trigger OVERHEAT in any season."""
        detector = RateOfChangeDetector()
        now = make_now(month=1, day=15)  # January — heating season
        # Record a 12-degree rise over 20 minutes (= 18/30min rate)
        detector.record("sensor.temp", now - timedelta(minutes=20), 72.0)
        detector.record("sensor.temp", now, 84.0)

        results = detector.check_thresholds("sensor.temp", "temperature", "normal", now)
        hazard_types = [r[1] for r in results]
        assert HazardType.OVERHEAT in hazard_types

    def test_humidity_spike_detection(self):
        """Rapid humidity rise should be detected in non-bathroom rooms."""
        detector = RateOfChangeDetector()
        now = make_now()
        # Record a 25% humidity rise over 20 minutes (= 37.5/30min rate)
        detector.record("sensor.hum", now - timedelta(minutes=20), 45.0)
        detector.record("sensor.hum", now, 70.0)

        results = detector.check_thresholds("sensor.hum", "humidity", "normal", now)
        hazard_types = [r[1] for r in results]
        assert HazardType.WATER_LEAK in hazard_types

    def test_bathroom_exclusion_from_humidity_spike(self):
        """Humidity spike in bathroom should be excluded (shower pattern)."""
        detector = RateOfChangeDetector()
        now = make_now()
        # Same readings as above but in bathroom
        detector.record("sensor.hum", now - timedelta(minutes=20), 45.0)
        detector.record("sensor.hum", now, 70.0)

        results = detector.check_thresholds("sensor.hum", "humidity", "bathroom", now)
        hazard_types = [r[1] for r in results]
        assert HazardType.WATER_LEAK not in hazard_types

    def test_season_detection_heating(self):
        """November through March should be 'heating' season."""
        for month in (11, 12, 1, 2, 3):
            now = make_now(month=month)
            assert RateOfChangeDetector._get_current_season(now) == "heating"

    def test_season_detection_cooling(self):
        """May through September should be 'cooling' season."""
        for month in (5, 6, 7, 8, 9):
            now = make_now(month=month)
            assert RateOfChangeDetector._get_current_season(now) == "cooling"

    def test_season_detection_shoulder(self):
        """April and October should be 'shoulder' season."""
        for month in (4, 10):
            now = make_now(month=month)
            assert RateOfChangeDetector._get_current_season(now) == "shoulder"

    def test_shoulder_season_both_directions(self):
        """In shoulder season, both heating and cooling rate checks should be active."""
        detector = RateOfChangeDetector()
        now = make_now(month=4, day=15)  # April = shoulder

        # Temperature drop
        detector.record("sensor.temp_a", now - timedelta(minutes=20), 72.0)
        detector.record("sensor.temp_a", now, 63.0)  # 9-degree drop
        results = detector.check_thresholds("sensor.temp_a", "temperature", "normal", now)
        hazard_types = [r[1] for r in results]
        assert HazardType.HVAC_FAILURE in hazard_types

        # Temperature rise
        detector.record("sensor.temp_b", now - timedelta(minutes=20), 72.0)
        detector.record("sensor.temp_b", now, 81.0)  # 9-degree rise
        results = detector.check_thresholds("sensor.temp_b", "temperature", "normal", now)
        hazard_types = [r[1] for r in results]
        assert HazardType.HVAC_FAILURE in hazard_types

    def test_rate_calculation(self):
        """Rate should be calculated per 30 minutes."""
        detector = RateOfChangeDetector()
        now = make_now()
        detector.record("sensor.test", now - timedelta(minutes=30), 50.0)
        detector.record("sensor.test", now, 55.0)
        rate = detector.get_rate("sensor.test", now)
        assert rate is not None
        assert abs(rate - 5.0) < 0.1

    def test_clear_history(self):
        """Clearing history should remove readings."""
        detector = RateOfChangeDetector()
        now = make_now()
        detector.record("sensor.test", now, 72.0)
        detector.clear("sensor.test")
        assert detector.get_rate("sensor.test") is None

    def test_clear_all_history(self):
        """Clearing all history should remove all readings."""
        detector = RateOfChangeDetector()
        now = make_now()
        detector.record("sensor.a", now, 72.0)
        detector.record("sensor.b", now, 50.0)
        detector.clear()
        assert detector.get_rate("sensor.a") is None
        assert detector.get_rate("sensor.b") is None


# ============================================================================
# AlertDeduplicator Tests
# ============================================================================


class TestAlertDeduplicator:
    """Tests for alert deduplication."""

    def _make_hazard(self, hazard_type=HazardType.SMOKE, severity=Severity.CRITICAL, location="kitchen"):
        return Hazard(
            type=hazard_type,
            severity=severity,
            confidence=0.95,
            location=location,
            sensor_id="test",
            value="on",
            threshold="on",
            detected_at=datetime.utcnow(),
            message="test hazard",
        )

    def test_first_alert_always_passes(self):
        """First alert for a hazard should always pass."""
        dedup = AlertDeduplicator()
        hazard = self._make_hazard()
        now = datetime.utcnow()
        assert dedup.should_alert(hazard, now) is True

    def test_critical_suppression_window_1min(self):
        """CRITICAL alerts should be suppressed for 1 minute."""
        dedup = AlertDeduplicator()
        hazard = self._make_hazard(severity=Severity.CRITICAL)
        now = datetime.utcnow()
        assert dedup.should_alert(hazard, now) is True
        # 30 seconds later — suppressed
        assert dedup.should_alert(hazard, now + timedelta(seconds=30)) is False
        # 61 seconds later — allowed
        assert dedup.should_alert(hazard, now + timedelta(seconds=61)) is True

    def test_high_suppression_window_5min(self):
        """HIGH alerts should be suppressed for 5 minutes."""
        dedup = AlertDeduplicator()
        hazard = self._make_hazard(severity=Severity.HIGH)
        now = datetime.utcnow()
        assert dedup.should_alert(hazard, now) is True
        assert dedup.should_alert(hazard, now + timedelta(minutes=3)) is False
        assert dedup.should_alert(hazard, now + timedelta(minutes=6)) is True

    def test_medium_suppression_window_15min(self):
        """MEDIUM alerts should be suppressed for 15 minutes."""
        dedup = AlertDeduplicator()
        hazard = self._make_hazard(severity=Severity.MEDIUM)
        now = datetime.utcnow()
        assert dedup.should_alert(hazard, now) is True
        assert dedup.should_alert(hazard, now + timedelta(minutes=10)) is False
        assert dedup.should_alert(hazard, now + timedelta(minutes=16)) is True

    def test_low_suppression_window_1hr(self):
        """LOW alerts should be suppressed for 1 hour."""
        dedup = AlertDeduplicator()
        hazard = self._make_hazard(severity=Severity.LOW)
        now = datetime.utcnow()
        assert dedup.should_alert(hazard, now) is True
        assert dedup.should_alert(hazard, now + timedelta(minutes=30)) is False
        assert dedup.should_alert(hazard, now + timedelta(minutes=61)) is True

    def test_different_locations_not_suppressed(self):
        """Alerts for different locations should not suppress each other."""
        dedup = AlertDeduplicator()
        now = datetime.utcnow()
        h1 = self._make_hazard(location="kitchen")
        h2 = self._make_hazard(location="basement")
        assert dedup.should_alert(h1, now) is True
        assert dedup.should_alert(h2, now) is True

    def test_clear(self):
        """Clearing deduplicator should allow all alerts."""
        dedup = AlertDeduplicator()
        now = datetime.utcnow()
        hazard = self._make_hazard()
        dedup.should_alert(hazard, now)
        dedup.clear()
        assert dedup.should_alert(hazard, now) is True


# ============================================================================
# SafetyCoordinator Tests
# ============================================================================


class TestSafetyCoordinator:
    """Tests for the SafetyCoordinator."""

    def _make_coordinator(self):
        hass = make_hass()
        coord = SafetyCoordinator(hass)
        return coord, hass

    def test_initialization(self):
        """SafetyCoordinator should initialize with correct properties."""
        coord, _ = self._make_coordinator()
        assert coord.coordinator_id == "safety"
        assert coord.priority == 100
        assert coord.name == "Safety Coordinator"
        assert len(coord.active_hazards) == 0
        assert coord.sensors_monitored == 0

    def test_binary_hazard_smoke_on(self):
        """Smoke detector 'on' should create CRITICAL hazard."""
        coord, _ = self._make_coordinator()
        coord._sensor_locations["binary_sensor.kitchen_smoke"] = "Kitchen"
        coord._binary_sensors["binary_sensor.kitchen_smoke"] = HazardType.SMOKE

        hazard = coord._handle_binary_hazard(
            "binary_sensor.kitchen_smoke", "on", HazardType.SMOKE
        )
        assert hazard is not None
        assert hazard.type == HazardType.SMOKE
        assert hazard.severity == Severity.CRITICAL
        assert hazard.location == "Kitchen"
        assert "SMOKE DETECTED" in hazard.message

    def test_binary_hazard_smoke_off_clears(self):
        """Smoke detector 'off' should clear the hazard."""
        coord, _ = self._make_coordinator()
        coord._sensor_locations["binary_sensor.kitchen_smoke"] = "Kitchen"

        # First trigger the hazard
        coord._active_hazards["smoke:Kitchen"] = Hazard(
            type=HazardType.SMOKE, severity=Severity.CRITICAL,
            confidence=0.95, location="Kitchen",
            sensor_id="binary_sensor.kitchen_smoke",
            value="on", threshold="on",
            detected_at=datetime.utcnow(), message="test",
        )

        hazard = coord._handle_binary_hazard(
            "binary_sensor.kitchen_smoke", "off", HazardType.SMOKE
        )
        assert hazard is None
        assert "smoke:Kitchen" not in coord._active_hazards

    def test_binary_hazard_leak(self):
        """Water leak sensor 'on' should create HIGH hazard."""
        coord, _ = self._make_coordinator()
        coord._sensor_locations["binary_sensor.basement_leak"] = "Basement"
        coord._binary_sensors["binary_sensor.basement_leak"] = HazardType.WATER_LEAK

        hazard = coord._handle_binary_hazard(
            "binary_sensor.basement_leak", "on", HazardType.WATER_LEAK
        )
        assert hazard is not None
        assert hazard.type == HazardType.WATER_LEAK
        assert hazard.severity == Severity.HIGH
        assert "Water leak" in hazard.message

    def test_numeric_hazard_co_critical(self):
        """CO above 100ppm should be CRITICAL."""
        coord, _ = self._make_coordinator()
        coord._sensor_locations["sensor.co"] = "Kitchen"

        hazard = coord._handle_numeric_hazard(
            "sensor.co", 120.0, HazardType.CARBON_MONOXIDE
        )
        assert hazard is not None
        assert hazard.severity == Severity.CRITICAL

    def test_numeric_hazard_co_high(self):
        """CO 50-100ppm should be HIGH."""
        coord, _ = self._make_coordinator()
        coord._sensor_locations["sensor.co"] = "Kitchen"

        hazard = coord._handle_numeric_hazard(
            "sensor.co", 60.0, HazardType.CARBON_MONOXIDE
        )
        assert hazard is not None
        assert hazard.severity == Severity.HIGH

    def test_numeric_hazard_co_medium(self):
        """CO 35-50ppm should be MEDIUM."""
        coord, _ = self._make_coordinator()
        coord._sensor_locations["sensor.co"] = "Kitchen"

        hazard = coord._handle_numeric_hazard(
            "sensor.co", 40.0, HazardType.CARBON_MONOXIDE
        )
        assert hazard is not None
        assert hazard.severity == Severity.MEDIUM

    def test_numeric_hazard_co_low(self):
        """CO 10-35ppm should be LOW."""
        coord, _ = self._make_coordinator()
        coord._sensor_locations["sensor.co"] = "Kitchen"

        hazard = coord._handle_numeric_hazard(
            "sensor.co", 15.0, HazardType.CARBON_MONOXIDE
        )
        assert hazard is not None
        assert hazard.severity == Severity.LOW

    def test_numeric_hazard_co_below_threshold(self):
        """CO below 10ppm should return None."""
        coord, _ = self._make_coordinator()
        coord._sensor_locations["sensor.co"] = "Kitchen"

        hazard = coord._handle_numeric_hazard(
            "sensor.co", 5.0, HazardType.CARBON_MONOXIDE
        )
        assert hazard is None

    def test_flooding_escalation_multi_sensor(self):
        """Multiple active leak sensors should escalate to FLOODING."""
        coord, _ = self._make_coordinator()
        now = datetime.utcnow()
        coord._sensor_locations["binary_sensor.leak_1"] = "Kitchen"
        coord._sensor_locations["binary_sensor.leak_2"] = "Basement"
        coord._active_leak_sensors = {"binary_sensor.leak_1", "binary_sensor.leak_2"}
        coord._leak_start_times = {
            "binary_sensor.leak_1": now,
            "binary_sensor.leak_2": now,
        }

        result = coord._check_flooding_escalation(now)
        assert result is not None
        assert result.type == HazardType.FLOODING
        assert result.severity == Severity.CRITICAL

    def test_flooding_escalation_sustained(self):
        """Single leak sensor active for >15min should escalate to FLOODING."""
        coord, _ = self._make_coordinator()
        now = datetime.utcnow()
        start = now - timedelta(minutes=16)
        coord._sensor_locations["binary_sensor.leak_1"] = "Kitchen"
        coord._active_leak_sensors = {"binary_sensor.leak_1"}
        coord._leak_start_times = {"binary_sensor.leak_1": start}

        result = coord._check_flooding_escalation(now)
        assert result is not None
        assert result.type == HazardType.FLOODING
        assert result.severity == Severity.CRITICAL

    def test_flooding_not_escalated_before_15min(self):
        """Single leak sensor active for <15min should NOT escalate."""
        coord, _ = self._make_coordinator()
        now = datetime.utcnow()
        start = now - timedelta(minutes=10)
        coord._sensor_locations["binary_sensor.leak_1"] = "Kitchen"
        coord._active_leak_sensors = {"binary_sensor.leak_1"}
        coord._leak_start_times = {"binary_sensor.leak_1": start}

        result = coord._check_flooding_escalation(now)
        assert result is None

    def test_temperature_freeze_risk(self):
        """Temperature below 35F should trigger FREEZE_RISK HIGH."""
        coord, _ = self._make_coordinator()
        coord._sensor_locations["sensor.temp"] = "Garage"
        now = datetime.utcnow()

        hazards = coord._handle_temperature("sensor.temp", 32.0, now)
        freeze_hazards = [h for h in hazards if h.type == HazardType.FREEZE_RISK]
        assert len(freeze_hazards) >= 1
        assert freeze_hazards[0].severity == Severity.HIGH

    def test_temperature_freeze_risk_medium(self):
        """Temperature between 35-40F should trigger FREEZE_RISK MEDIUM."""
        coord, _ = self._make_coordinator()
        coord._sensor_locations["sensor.temp"] = "Garage"
        now = datetime.utcnow()

        hazards = coord._handle_temperature("sensor.temp", 38.0, now)
        freeze_hazards = [h for h in hazards if h.type == HazardType.FREEZE_RISK]
        assert len(freeze_hazards) >= 1
        assert freeze_hazards[0].severity == Severity.MEDIUM

    def test_temperature_overheat(self):
        """Temperature above 110F should trigger OVERHEAT HIGH."""
        coord, _ = self._make_coordinator()
        coord._sensor_locations["sensor.temp"] = "Attic"
        now = datetime.utcnow()

        hazards = coord._handle_temperature("sensor.temp", 115.0, now)
        overheat_hazards = [h for h in hazards if h.type == HazardType.OVERHEAT]
        assert len(overheat_hazards) >= 1
        assert overheat_hazards[0].severity == Severity.HIGH

    def test_humidity_normal_room_thresholds(self):
        """Normal room humidity thresholds should fire after sustained window (2hr)."""
        coord, _ = self._make_coordinator()
        coord._sensor_locations["sensor.hum"] = "Bedroom"
        coord._sensor_room_types["sensor.hum"] = "normal"
        now = datetime.utcnow()

        # Pre-set sustained tracking to 3 hours ago (past the 2hr window)
        coord._humidity_above_since["sensor.hum"] = now - timedelta(hours=3)

        # Above 80% = HIGH severity
        hazards = coord._handle_humidity("sensor.hum", 82.0, now)
        high_hum = [h for h in hazards if h.type == HazardType.HIGH_HUMIDITY]
        assert len(high_hum) >= 1
        assert high_hum[0].severity == Severity.HIGH

        # 70-80% = MEDIUM
        hazards = coord._handle_humidity("sensor.hum", 72.0, now)
        med_hum = [h for h in hazards if h.type == HazardType.HIGH_HUMIDITY]
        assert len(med_hum) >= 1
        assert med_hum[0].severity == Severity.MEDIUM

    def test_humidity_bathroom_thresholds(self):
        """Bathroom humidity thresholds should use higher ranges after 4hr sustained window."""
        coord, _ = self._make_coordinator()
        coord._sensor_locations["sensor.hum"] = "Bathroom"
        coord._sensor_room_types["sensor.hum"] = "bathroom"
        now = datetime.utcnow()

        # 75% in bathroom is BELOW the LOW threshold (80) — no alarm
        hazards = coord._handle_humidity("sensor.hum", 75.0, now)
        high_hum = [h for h in hazards if h.type == HazardType.HIGH_HUMIDITY]
        assert len(high_hum) == 0

        # Pre-set sustained tracking to 5 hours ago (past the 4hr bathroom window)
        coord._humidity_above_since["sensor.hum"] = now - timedelta(hours=5)

        # 82% in bathroom = LOW severity (80-85 range)
        hazards = coord._handle_humidity("sensor.hum", 82.0, now)
        high_hum = [h for h in hazards if h.type == HazardType.HIGH_HUMIDITY]
        assert len(high_hum) >= 1
        assert high_hum[0].severity == Severity.LOW

        # 87% in bathroom = MEDIUM severity (85-90 range)
        hazards = coord._handle_humidity("sensor.hum", 87.0, now)
        high_hum = [h for h in hazards if h.type == HazardType.HIGH_HUMIDITY]
        assert len(high_hum) >= 1
        assert high_hum[0].severity == Severity.MEDIUM

        # 92% in bathroom = HIGH severity (>90)
        hazards = coord._handle_humidity("sensor.hum", 92.0, now)
        high_hum = [h for h in hazards if h.type == HazardType.HIGH_HUMIDITY]
        assert len(high_hum) >= 1
        assert high_hum[0].severity == Severity.HIGH

    def test_humidity_low(self):
        """Low humidity below 25% should trigger LOW_HUMIDITY MEDIUM."""
        coord, _ = self._make_coordinator()
        coord._sensor_locations["sensor.hum"] = "Living Room"
        coord._sensor_room_types["sensor.hum"] = "normal"
        now = datetime.utcnow()

        hazards = coord._handle_humidity("sensor.hum", 22.0, now)
        low_hum = [h for h in hazards if h.type == HazardType.LOW_HUMIDITY]
        assert len(low_hum) >= 1
        assert low_hum[0].severity == Severity.MEDIUM

    def test_humidity_low_advisory(self):
        """Low humidity 25-30% should trigger LOW_HUMIDITY LOW."""
        coord, _ = self._make_coordinator()
        coord._sensor_locations["sensor.hum"] = "Living Room"
        coord._sensor_room_types["sensor.hum"] = "normal"
        now = datetime.utcnow()

        hazards = coord._handle_humidity("sensor.hum", 28.0, now)
        low_hum = [h for h in hazards if h.type == HazardType.LOW_HUMIDITY]
        assert len(low_hum) >= 1
        assert low_hum[0].severity == Severity.LOW

    def test_tvoc_detection(self):
        """High TVOC should trigger hazard."""
        coord, _ = self._make_coordinator()
        coord._sensor_locations["sensor.tvoc"] = "Office"

        hazard = coord._handle_numeric_hazard(
            "sensor.tvoc", 600.0, HazardType.HIGH_TVOC
        )
        assert hazard is not None
        assert hazard.type == HazardType.HIGH_TVOC
        assert hazard.severity == Severity.MEDIUM

    def test_tvoc_high(self):
        """Very high TVOC should trigger HIGH severity."""
        coord, _ = self._make_coordinator()
        coord._sensor_locations["sensor.tvoc"] = "Office"

        hazard = coord._handle_numeric_hazard(
            "sensor.tvoc", 1200.0, HazardType.HIGH_TVOC
        )
        assert hazard is not None
        assert hazard.severity == Severity.HIGH

    def test_light_patterns_exist(self):
        """All expected light patterns should be defined."""
        assert "fire" in LIGHT_PATTERNS
        assert "water_leak" in LIGHT_PATTERNS
        assert "co" in LIGHT_PATTERNS
        assert "freeze" in LIGHT_PATTERNS
        assert "warning" in LIGHT_PATTERNS

    def test_light_pattern_fire_color(self):
        """Fire pattern should be orange flash."""
        assert LIGHT_PATTERNS["fire"]["color"] == (255, 100, 0)
        assert LIGHT_PATTERNS["fire"]["effect"] == "flash"

    def test_light_pattern_water_color(self):
        """Water leak pattern should be blue pulse."""
        assert LIGHT_PATTERNS["water_leak"]["color"] == (0, 0, 255)
        assert LIGHT_PATTERNS["water_leak"]["effect"] == "pulse"

    def test_light_pattern_key_mapping(self):
        """Hazard type to light pattern key mapping should be correct."""
        coord, _ = self._make_coordinator()
        assert coord._get_light_pattern_key(HazardType.SMOKE) == "fire"
        assert coord._get_light_pattern_key(HazardType.FIRE) == "fire"
        assert coord._get_light_pattern_key(HazardType.WATER_LEAK) == "water_leak"
        assert coord._get_light_pattern_key(HazardType.FLOODING) == "water_leak"
        assert coord._get_light_pattern_key(HazardType.CARBON_MONOXIDE) == "co"
        assert coord._get_light_pattern_key(HazardType.FREEZE_RISK) == "freeze"
        assert coord._get_light_pattern_key(HazardType.HIGH_CO2) == "warning"

    @pytest.mark.asyncio
    async def test_test_hazard_service(self):
        """Test hazard service should log without triggering real responses."""
        coord, _ = self._make_coordinator()
        # Should not raise
        await coord.handle_test_hazard("smoke", "Kitchen", "critical")
        await coord.handle_test_hazard("water_leak", "Basement", "high")

    @pytest.mark.asyncio
    async def test_test_hazard_service_invalid_type(self):
        """Test hazard service with invalid type should log warning."""
        coord, _ = self._make_coordinator()
        # Should not raise
        await coord.handle_test_hazard("invalid_type", "Kitchen", "critical")

    def test_diagnostics_summary(self):
        """Diagnostics summary should include key metrics."""
        coord, _ = self._make_coordinator()
        summary = coord.get_diagnostics_summary()
        assert "active_hazards" in summary
        assert "sensors_monitored" in summary
        assert "hazards_detected_24h" in summary
        assert "alerts_sent_24h" in summary
        assert "false_alarm_rate" in summary
        assert "response_times" in summary

    def test_diagnostics_summary_with_hazards(self):
        """Diagnostics should show active hazard details."""
        coord, _ = self._make_coordinator()
        coord._active_hazards["smoke:Kitchen"] = Hazard(
            type=HazardType.SMOKE, severity=Severity.CRITICAL,
            confidence=0.95, location="Kitchen",
            sensor_id="test", value="on", threshold="on",
            detected_at=datetime.utcnow(), message="test",
        )
        summary = coord.get_diagnostics_summary()
        assert summary["active_hazards"] == 1
        assert "smoke:Kitchen" in summary["active_hazard_details"]

    def test_hazard_clearing(self):
        """Clearing a hazard should remove it from active hazards."""
        coord, _ = self._make_coordinator()
        coord._active_hazards["smoke:Kitchen"] = Hazard(
            type=HazardType.SMOKE, severity=Severity.CRITICAL,
            confidence=0.95, location="Kitchen",
            sensor_id="test", value="on", threshold="on",
            detected_at=datetime.utcnow(), message="test",
        )
        coord.clear_hazard(HazardType.SMOKE, "Kitchen")
        assert len(coord.active_hazards) == 0

    def test_clear_all_hazards(self):
        """Clearing all hazards should empty the active set."""
        coord, _ = self._make_coordinator()
        coord._active_hazards["smoke:Kitchen"] = Hazard(
            type=HazardType.SMOKE, severity=Severity.CRITICAL,
            confidence=0.95, location="Kitchen",
            sensor_id="test", value="on", threshold="on",
            detected_at=datetime.utcnow(), message="test",
        )
        coord._active_hazards["leak:Basement"] = Hazard(
            type=HazardType.WATER_LEAK, severity=Severity.HIGH,
            confidence=0.95, location="Basement",
            sensor_id="test", value="on", threshold="on",
            detected_at=datetime.utcnow(), message="test",
        )
        coord.clear_all_hazards()
        assert len(coord.active_hazards) == 0

    def test_safety_status_normal(self):
        """Status should be 'normal' when no hazards active."""
        coord, _ = self._make_coordinator()
        assert coord.get_safety_status() == "normal"

    def test_safety_status_critical(self):
        """Status should be 'critical' when CRITICAL hazard active."""
        coord, _ = self._make_coordinator()
        coord._active_hazards["smoke:Kitchen"] = Hazard(
            type=HazardType.SMOKE, severity=Severity.CRITICAL,
            confidence=0.95, location="Kitchen",
            sensor_id="test", value="on", threshold="on",
            detected_at=datetime.utcnow(), message="test",
        )
        assert coord.get_safety_status() == "critical"

    def test_safety_status_alert(self):
        """Status should be 'alert' when HIGH hazard active."""
        coord, _ = self._make_coordinator()
        coord._active_hazards["leak:Basement"] = Hazard(
            type=HazardType.WATER_LEAK, severity=Severity.HIGH,
            confidence=0.95, location="Basement",
            sensor_id="test", value="on", threshold="on",
            detected_at=datetime.utcnow(), message="test",
        )
        assert coord.get_safety_status() == "alert"

    def test_safety_status_warning(self):
        """Status should be 'warning' when MEDIUM hazard active."""
        coord, _ = self._make_coordinator()
        coord._active_hazards["co2:Office"] = Hazard(
            type=HazardType.HIGH_CO2, severity=Severity.MEDIUM,
            confidence=0.85, location="Office",
            sensor_id="test", value=1800, threshold=1500,
            detected_at=datetime.utcnow(), message="test",
        )
        assert coord.get_safety_status() == "warning"

    @pytest.mark.asyncio
    async def test_critical_response_has_lights(self):
        """CRITICAL response should include emergency lights action."""
        coord, _ = self._make_coordinator()
        hazard = Hazard(
            type=HazardType.SMOKE, severity=Severity.CRITICAL,
            confidence=0.95, location="Kitchen",
            sensor_id="test", value="on", threshold="on",
            detected_at=datetime.utcnow(), message="test",
        )
        actions = coord._critical_response(hazard)
        service_actions = [a for a in actions if hasattr(a, 'service') and a.service == "light.turn_on"]
        assert len(service_actions) >= 1

    @pytest.mark.asyncio
    async def test_critical_co_response_has_ventilation(self):
        """CRITICAL CO response should include fan ventilation."""
        coord, _ = self._make_coordinator()
        hazard = Hazard(
            type=HazardType.CARBON_MONOXIDE, severity=Severity.CRITICAL,
            confidence=0.95, location="Kitchen",
            sensor_id="test", value=120, threshold=100,
            detected_at=datetime.utcnow(), message="test",
        )
        actions = coord._critical_response(hazard)
        fan_actions = [a for a in actions if hasattr(a, 'service') and a.service == "fan.turn_on"]
        assert len(fan_actions) >= 1

    @pytest.mark.asyncio
    async def test_high_freeze_response_has_hvac_constraint(self):
        """HIGH freeze risk should include HVAC heat constraint."""
        coord, _ = self._make_coordinator()
        hazard = Hazard(
            type=HazardType.FREEZE_RISK, severity=Severity.HIGH,
            confidence=0.90, location="Garage",
            sensor_id="test", value=32, threshold=35,
            detected_at=datetime.utcnow(), message="test",
        )
        actions = coord._high_response(hazard)
        constraint_actions = [a for a in actions if hasattr(a, 'constraint_type')]
        assert len(constraint_actions) >= 1
        assert constraint_actions[0].constraint_data["mode"] == "heat"

    @pytest.mark.asyncio
    async def test_evaluate_returns_actions_for_smoke(self):
        """evaluate() should return actions for a smoke hazard intent."""
        coord, hass = self._make_coordinator()
        coord._binary_sensors["binary_sensor.smoke"] = HazardType.SMOKE
        coord._sensor_locations["binary_sensor.smoke"] = "Kitchen"

        intents = [
            Intent(
                source="state_change",
                entity_id="binary_sensor.smoke",
                data={"state": "on"},
                coordinator_id="safety",
            )
        ]
        actions = await coord.evaluate(intents, {})
        assert len(actions) > 0

    @pytest.mark.asyncio
    async def test_evaluate_no_actions_when_disabled(self):
        """evaluate() should return no actions when coordinator is disabled."""
        coord, _ = self._make_coordinator()
        coord._enabled = False
        intents = [Intent(source="test", entity_id="test", data={"state": "on"})]
        actions = await coord.evaluate(intents, {})
        assert len(actions) == 0

    @pytest.mark.asyncio
    async def test_teardown(self):
        """Teardown should clean up all state."""
        coord, _ = self._make_coordinator()
        coord._active_hazards["test:Test"] = Hazard(
            type=HazardType.SMOKE, severity=Severity.CRITICAL,
            confidence=0.95, location="Test",
            sensor_id="test", value="on", threshold="on",
            detected_at=datetime.utcnow(), message="test",
        )
        await coord.async_teardown()
        assert len(coord._active_hazards) == 0

    def test_notification_channels_by_severity(self):
        """Notification channels should vary by severity."""
        assert SafetyCoordinator._get_notification_channels(Severity.CRITICAL) == ["imessage", "speaker", "lights"]
        assert SafetyCoordinator._get_notification_channels(Severity.HIGH) == ["imessage", "speaker"]
        assert SafetyCoordinator._get_notification_channels(Severity.MEDIUM) == ["imessage"]
        assert SafetyCoordinator._get_notification_channels(Severity.LOW) == []

    def test_location_from_entity_id(self):
        """Location extraction from entity_id should work."""
        assert SafetyCoordinator._location_from_entity_id("binary_sensor.kitchen_smoke") == "Kitchen"
        assert SafetyCoordinator._location_from_entity_id("sensor.basement_humidity") == "Basement"


# ============================================================================
# Room-Type Humidity Threshold Tests
# ============================================================================


class TestRoomTypeHumidityThresholds:
    """Tests for room-type-aware humidity thresholds."""

    def test_normal_room_thresholds(self):
        """Normal room thresholds should be 60/70/80."""
        thresholds = HUMIDITY_THRESHOLDS["normal"]
        assert thresholds["low"] == 60.0
        assert thresholds["medium"] == 70.0
        assert thresholds["high"] == 80.0
        assert thresholds["window_hours"] == 2.0

    def test_bathroom_thresholds(self):
        """Bathroom thresholds should be 80/85/90 with 4hr window."""
        thresholds = HUMIDITY_THRESHOLDS["bathroom"]
        assert thresholds["low"] == 80.0
        assert thresholds["medium"] == 85.0
        assert thresholds["high"] == 90.0
        assert thresholds["window_hours"] == 4.0

    def test_basement_thresholds(self):
        """Basement thresholds should be 55/65/75."""
        thresholds = HUMIDITY_THRESHOLDS["basement"]
        assert thresholds["low"] == 55.0
        assert thresholds["medium"] == 65.0
        assert thresholds["high"] == 75.0
        assert thresholds["window_hours"] == 2.0

    def test_low_humidity_thresholds(self):
        """Low humidity thresholds should be universal."""
        assert LOW_HUMIDITY_THRESHOLDS[Severity.MEDIUM] == 25.0
        assert LOW_HUMIDITY_THRESHOLDS[Severity.LOW] == 30.0


# ============================================================================
# Season Detection Tests
# ============================================================================


class TestSeasonDetection:
    """Tests for date-based season detection."""

    def test_heating_season_months(self):
        """November through March should be heating season."""
        for month in (11, 12, 1, 2, 3):
            now = datetime(2026, month, 15)
            assert RateOfChangeDetector._get_current_season(now) == "heating"

    def test_cooling_season_months(self):
        """May through September should be cooling season."""
        for month in (5, 6, 7, 8, 9):
            now = datetime(2026, month, 15)
            assert RateOfChangeDetector._get_current_season(now) == "cooling"

    def test_shoulder_season_months(self):
        """April and October should be shoulder season."""
        for month in (4, 10):
            now = datetime(2026, month, 15)
            assert RateOfChangeDetector._get_current_season(now) == "shoulder"

    def test_season_matches_same(self):
        """Same season should match."""
        assert RateOfChangeDetector._season_matches("heating", "heating") is True
        assert RateOfChangeDetector._season_matches("cooling", "cooling") is True

    def test_season_matches_any(self):
        """'any' active season should always match."""
        assert RateOfChangeDetector._season_matches("heating", "any") is True
        assert RateOfChangeDetector._season_matches("cooling", "any") is True
        assert RateOfChangeDetector._season_matches("shoulder", "any") is True

    def test_shoulder_matches_both(self):
        """Shoulder season should match both heating and cooling."""
        assert RateOfChangeDetector._season_matches("shoulder", "heating") is True
        assert RateOfChangeDetector._season_matches("shoulder", "cooling") is True

    def test_season_mismatch(self):
        """Different specific seasons should not match."""
        assert RateOfChangeDetector._season_matches("heating", "cooling") is False
        assert RateOfChangeDetector._season_matches("cooling", "heating") is False


# ============================================================================
# Numeric Thresholds Tests
# ============================================================================


class TestNumericThresholds:
    """Tests for numeric threshold constants."""

    def test_co_thresholds_exist(self):
        """CO thresholds should cover CRITICAL/HIGH/MEDIUM/LOW."""
        co = NUMERIC_THRESHOLDS[HazardType.CARBON_MONOXIDE]
        assert co[Severity.CRITICAL] == 100.0
        assert co[Severity.HIGH] == 50.0
        assert co[Severity.MEDIUM] == 35.0
        assert co[Severity.LOW] == 10.0

    def test_co2_thresholds_exist(self):
        """CO2 thresholds should cover HIGH/MEDIUM/LOW."""
        co2 = NUMERIC_THRESHOLDS[HazardType.HIGH_CO2]
        assert co2[Severity.HIGH] == 2500.0
        assert co2[Severity.MEDIUM] == 1500.0
        assert co2[Severity.LOW] == 1000.0

    def test_freeze_risk_thresholds_exist(self):
        """Freeze risk thresholds should cover HIGH/MEDIUM/LOW."""
        freeze = NUMERIC_THRESHOLDS[HazardType.FREEZE_RISK]
        assert freeze[Severity.HIGH] == 35.0
        assert freeze[Severity.MEDIUM] == 40.0
        assert freeze[Severity.LOW] == 45.0

    def test_classify_severity_co(self):
        """CO severity classification should be correct."""
        classify = SafetyCoordinator._classify_severity
        assert classify(HazardType.CARBON_MONOXIDE, 120.0) == Severity.CRITICAL
        assert classify(HazardType.CARBON_MONOXIDE, 60.0) == Severity.HIGH
        assert classify(HazardType.CARBON_MONOXIDE, 40.0) == Severity.MEDIUM
        assert classify(HazardType.CARBON_MONOXIDE, 15.0) == Severity.LOW
        assert classify(HazardType.CARBON_MONOXIDE, 5.0) is None

    def test_classify_severity_freeze(self):
        """Freeze severity classification should use <= (lower is worse)."""
        classify = SafetyCoordinator._classify_severity
        assert classify(HazardType.FREEZE_RISK, 30.0) == Severity.HIGH
        assert classify(HazardType.FREEZE_RISK, 38.0) == Severity.MEDIUM
        assert classify(HazardType.FREEZE_RISK, 42.0) == Severity.LOW
        assert classify(HazardType.FREEZE_RISK, 50.0) is None


# ============================================================================
# Integration Tests
# ============================================================================


class TestSafetyCoordinatorIntegration:
    """Integration tests for SafetyCoordinator with CoordinatorManager."""

    def test_coordinator_priority_is_100(self):
        """Safety coordinator should have the highest priority (100)."""
        hass = make_hass()
        coord = SafetyCoordinator(hass)
        assert coord.priority == 100

    def test_coordinator_id(self):
        """Safety coordinator ID should be 'safety'."""
        hass = make_hass()
        coord = SafetyCoordinator(hass)
        assert coord.coordinator_id == "safety"

    @pytest.mark.asyncio
    async def test_respond_to_hazard_tracks_and_generates_actions(self):
        """_respond_to_hazard should track the hazard and generate actions."""
        hass = make_hass()
        coord = SafetyCoordinator(hass)
        hazard = Hazard(
            type=HazardType.SMOKE, severity=Severity.CRITICAL,
            confidence=0.95, location="Kitchen",
            sensor_id="test", value="on", threshold="on",
            detected_at=datetime.utcnow(), message="test smoke",
        )
        actions = await coord._respond_to_hazard(hazard)
        assert len(actions) > 0
        assert "smoke:Kitchen" in coord._active_hazards
        assert coord._hazards_detected_24h >= 1

    @pytest.mark.asyncio
    async def test_process_sensor_binary_smoke(self):
        """_process_sensor should detect smoke from binary sensor."""
        hass = make_hass()
        coord = SafetyCoordinator(hass)
        coord._binary_sensors["binary_sensor.smoke"] = HazardType.SMOKE
        coord._sensor_locations["binary_sensor.smoke"] = "Kitchen"

        hazards = await coord._process_sensor("binary_sensor.smoke", "on")
        assert len(hazards) >= 1
        assert hazards[0].type == HazardType.SMOKE

    @pytest.mark.asyncio
    async def test_process_sensor_numeric_co(self):
        """_process_sensor should detect CO from numeric sensor."""
        hass = make_hass()
        coord = SafetyCoordinator(hass)
        coord._numeric_sensors["sensor.co"] = "co"
        coord._sensor_locations["sensor.co"] = "Kitchen"
        coord._sensor_room_types["sensor.co"] = "normal"

        hazards = await coord._process_sensor("sensor.co", "55")
        co_hazards = [h for h in hazards if h.type == HazardType.CARBON_MONOXIDE]
        assert len(co_hazards) >= 1
        assert co_hazards[0].severity == Severity.HIGH


# ============================================================================
# Basement humidity thresholds
# ============================================================================


class TestBasementHumidity:
    """Tests for basement-specific humidity handling."""

    def test_basement_55_triggers_low(self):
        """Humidity at 55% in basement should trigger LOW after sustained window."""
        hass = make_hass()
        coord = SafetyCoordinator(hass)
        coord._sensor_locations["sensor.hum"] = "Basement"
        coord._sensor_room_types["sensor.hum"] = "basement"
        now = datetime.utcnow()
        coord._humidity_above_since["sensor.hum"] = now - timedelta(hours=3)

        hazards = coord._handle_humidity("sensor.hum", 56.0, now)
        high_hum = [h for h in hazards if h.type == HazardType.HIGH_HUMIDITY]
        assert len(high_hum) >= 1
        assert high_hum[0].severity == Severity.LOW

    def test_basement_66_triggers_medium(self):
        """Humidity at 66% in basement should trigger MEDIUM after sustained window."""
        hass = make_hass()
        coord = SafetyCoordinator(hass)
        coord._sensor_locations["sensor.hum"] = "Basement"
        coord._sensor_room_types["sensor.hum"] = "basement"
        now = datetime.utcnow()
        coord._humidity_above_since["sensor.hum"] = now - timedelta(hours=3)

        hazards = coord._handle_humidity("sensor.hum", 66.0, now)
        high_hum = [h for h in hazards if h.type == HazardType.HIGH_HUMIDITY]
        assert len(high_hum) >= 1
        assert high_hum[0].severity == Severity.MEDIUM

    def test_basement_76_triggers_high(self):
        """Humidity at 76% in basement should trigger HIGH after sustained window."""
        hass = make_hass()
        coord = SafetyCoordinator(hass)
        coord._sensor_locations["sensor.hum"] = "Basement"
        coord._sensor_room_types["sensor.hum"] = "basement"
        now = datetime.utcnow()
        coord._humidity_above_since["sensor.hum"] = now - timedelta(hours=3)

        hazards = coord._handle_humidity("sensor.hum", 76.0, now)
        high_hum = [h for h in hazards if h.type == HazardType.HIGH_HUMIDITY]
        assert len(high_hum) >= 1
        assert high_hum[0].severity == Severity.HIGH


# ============================================================================
# Reviewer fix: additional tests for review issues
# ============================================================================


class TestReviewerFixes:
    """Tests added to address reviewer findings."""

    def test_high_overheat_response_has_hvac_cool_constraint(self):
        """HIGH overheat should include HVAC cool constraint."""
        hass = make_hass()
        coord = SafetyCoordinator(hass)
        hazard = Hazard(
            type=HazardType.OVERHEAT, severity=Severity.HIGH,
            confidence=0.90, location="Attic",
            sensor_id="test", value=115, threshold=110,
            detected_at=datetime.utcnow(), message="test",
        )
        actions = coord._high_response(hazard)
        constraint_actions = [a for a in actions if hasattr(a, 'constraint_type')]
        assert len(constraint_actions) >= 1
        assert constraint_actions[0].constraint_data["mode"] == "cool"

    @pytest.mark.asyncio
    async def test_test_hazard_does_not_create_real_actions(self):
        """Test hazard service should NOT populate active hazards or return actions."""
        hass = make_hass()
        coord = SafetyCoordinator(hass)
        await coord.handle_test_hazard("smoke", "Kitchen", "critical")
        # Should not create any active hazards
        assert len(coord.active_hazards) == 0

    def test_safety_status_advisory_for_low_severity(self):
        """LOW severity hazard should return 'advisory' status, not 'normal'."""
        hass = make_hass()
        coord = SafetyCoordinator(hass)
        coord._active_hazards["humidity:Bedroom"] = Hazard(
            type=HazardType.HIGH_HUMIDITY, severity=Severity.LOW,
            confidence=0.80, location="Bedroom",
            sensor_id="test", value=62, threshold=60,
            detected_at=datetime.utcnow(), message="test",
        )
        assert coord.get_safety_status() == "advisory"

    def test_humidity_not_fired_before_sustained_window(self):
        """Humidity above threshold should NOT fire before sustained window elapses."""
        hass = make_hass()
        coord = SafetyCoordinator(hass)
        coord._sensor_locations["sensor.hum"] = "Bedroom"
        coord._sensor_room_types["sensor.hum"] = "normal"
        now = datetime.utcnow()

        # First reading at 82% starts tracking but does NOT fire
        hazards = coord._handle_humidity("sensor.hum", 82.0, now)
        high_hum = [h for h in hazards if h.type == HazardType.HIGH_HUMIDITY]
        assert len(high_hum) == 0
        assert "sensor.hum" in coord._humidity_above_since

    def test_humidity_fires_after_sustained_window(self):
        """Humidity above threshold should fire AFTER sustained window elapses."""
        hass = make_hass()
        coord = SafetyCoordinator(hass)
        coord._sensor_locations["sensor.hum"] = "Bedroom"
        coord._sensor_room_types["sensor.hum"] = "normal"
        now = datetime.utcnow()

        # Start tracking
        coord._handle_humidity("sensor.hum", 82.0, now)
        # 2.5 hours later — past the 2hr window
        later = now + timedelta(hours=2, minutes=30)
        hazards = coord._handle_humidity("sensor.hum", 82.0, later)
        high_hum = [h for h in hazards if h.type == HazardType.HIGH_HUMIDITY]
        assert len(high_hum) >= 1
        assert high_hum[0].severity == Severity.HIGH

    def test_humidity_clears_tracking_when_below_threshold(self):
        """Humidity dropping below threshold should clear sustained tracking."""
        hass = make_hass()
        coord = SafetyCoordinator(hass)
        coord._sensor_locations["sensor.hum"] = "Bedroom"
        coord._sensor_room_types["sensor.hum"] = "normal"
        now = datetime.utcnow()

        # Start tracking
        coord._handle_humidity("sensor.hum", 82.0, now)
        assert "sensor.hum" in coord._humidity_above_since
        # Drop below all thresholds
        coord._handle_humidity("sensor.hum", 50.0, now + timedelta(minutes=30))
        assert "sensor.hum" not in coord._humidity_above_since

    def test_bathroom_humidity_not_fired_before_4hr_window(self):
        """Bathroom humidity should not fire before 4hr sustained window."""
        hass = make_hass()
        coord = SafetyCoordinator(hass)
        coord._sensor_locations["sensor.hum"] = "Bathroom"
        coord._sensor_room_types["sensor.hum"] = "bathroom"
        now = datetime.utcnow()

        # Pre-set to only 2 hours ago (bathroom needs 4hr)
        coord._humidity_above_since["sensor.hum"] = now - timedelta(hours=2)
        hazards = coord._handle_humidity("sensor.hum", 87.0, now)
        high_hum = [h for h in hazards if h.type == HazardType.HIGH_HUMIDITY]
        assert len(high_hum) == 0  # Not yet — needs 4hr

    def test_deduplicator_uses_severity_enum_keys(self):
        """Deduplicator should use Severity enum keys, not strings."""
        dedup = AlertDeduplicator()
        assert Severity.CRITICAL in dedup.SUPPRESSION_WINDOWS
        assert Severity.HIGH in dedup.SUPPRESSION_WINDOWS
        assert Severity.MEDIUM in dedup.SUPPRESSION_WINDOWS
        assert Severity.LOW in dedup.SUPPRESSION_WINDOWS
        # String keys should NOT be present
        assert "critical" not in dedup.SUPPRESSION_WINDOWS
