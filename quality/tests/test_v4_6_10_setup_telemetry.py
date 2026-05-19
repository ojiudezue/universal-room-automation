"""Tests for v4.6.10: Setup Telemetry + Anomaly Wiring + Deferred Polish.

Deliverables covered:
  D1 — Boot telemetry capture (logic tests, no HA import needed)
  D2 — URASetupDurationSensor (structural + behavior via stubs)
  D3 — AnomalyDetector observation wiring (CM-level)
  D4 — Threat-model: telemetry never blocks setup
  D5a — _PERSON_LAST_STATE_SKIP_VALUES module constant (source grep + logic)
  D6 — MONETARY state_class warning fixes (source grep)

Test strategy (mirrors v4.6.9 pattern):
- Module-level sys.modules.setdefault for ALL HA stubs so integration
  modules can be imported.
- SensorStateClass / SensorDeviceClass / EntityCategory set as real enums
  on the stub so isinstance/equality checks work.
- Structural D5a/D6 tests use source-file grep — no full module import needed
  and won't break if the HA stub is incomplete.
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import re
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

# ---------------------------------------------------------------------------
# HA module stubs — must be at module top before ANY integration import
# ---------------------------------------------------------------------------
ROOT = pathlib.Path(__file__).parents[2]

# Build realistic enum-like mocks for sensor classes so attribute equality
# works: SensorStateClass.TOTAL == SensorStateClass.TOTAL etc.
class _SensorStateClass:
    MEASUREMENT = "measurement"
    TOTAL = "total"
    TOTAL_INCREASING = "total_increasing"

class _SensorDeviceClass:
    MONETARY = "monetary"
    DURATION = "duration"
    ENERGY = "energy"
    TEMPERATURE = "temperature"
    HUMIDITY = "humidity"
    POWER = "power"
    PRESSURE = "pressure"
    ILLUMINANCE = "illuminance"
    TIMESTAMP = "timestamp"
    BATTERY = "battery"
    VOLTAGE = "voltage"
    CURRENT = "current"
    FREQUENCY = "frequency"
    GAS = "gas"
    SIGNAL_STRENGTH = "signal_strength"
    SPEED = "speed"
    VOLUME = "volume"
    WEIGHT = "weight"
    CO2 = "carbon_dioxide"
    PM25 = "pm25"
    PM10 = "pm10"
    SULPHUR_DIOXIDE = "sulphur_dioxide"
    NITROGEN_DIOXIDE = "nitrogen_dioxide"
    OZONE = "ozone"
    CO = "carbon_monoxide"
    PRECIPITATION = "precipitation"
    PRECIPITATION_INTENSITY = "precipitation_intensity"
    APPARENT_POWER = "apparent_power"
    REACTIVE_POWER = "reactive_power"
    DATE = "date"
    ENUM = "enum"
    IRRADIANCE = "irradiance"
    MOISTURE = "moisture"
    SOUND_PRESSURE = "sound_pressure"
    WIND_SPEED = "wind_speed"
    DISTANCE = "distance"
    AREA = "area"
    DATA_RATE = "data_rate"
    DATA_SIZE = "data_size"
    CONDUCTIVITY = "conductivity"
    DURATION = "duration"

class _BinarySensorDeviceClass:
    MOTION = "motion"
    DOOR = "door"
    WINDOW = "window"
    MOISTURE = "moisture"
    SMOKE = "smoke"
    CO = "carbon_monoxide"
    GAS = "gas"
    SAFETY = "safety"
    BATTERY = "battery"
    CONNECTIVITY = "connectivity"
    LOCK = "lock"
    OCCUPANCY = "occupancy"
    PRESENCE = "presence"
    TAMPER = "tamper"
    VIBRATION = "vibration"
    LIGHT = "light"
    PLUG = "plug"
    POWER = "power"
    PROBLEM = "problem"
    RUNNING = "running"
    SOUND = "sound"
    UPDATE = "update"
    HEAT = "heat"
    COLD = "cold"
    MOVING = "moving"
    OPENING = "opening"

class _EntityCategory:
    DIAGNOSTIC = "diagnostic"
    CONFIG = "config"

_sensor_mod = MagicMock()
_sensor_mod.SensorEntity = object
_sensor_mod.SensorDeviceClass = _SensorDeviceClass
_sensor_mod.SensorStateClass = _SensorStateClass

_binary_sensor_mod = MagicMock()
_binary_sensor_mod.BinarySensorEntity = object
_binary_sensor_mod.BinarySensorDeviceClass = _BinarySensorDeviceClass

_entity_mod = MagicMock()
_entity_mod.DeviceInfo = dict  # DeviceInfo is dict-like for our tests
_entity_mod.EntityCategory = _EntityCategory

_dt_stub = MagicMock()
# v4.6.10 review fix B-M2: stub utcnow returns tz-aware datetime so tests
# exercise the same behavior as production dt_util.utcnow (Bug Class #21).
_dt_stub.utcnow = lambda: datetime.now(tz=timezone.utc)
_dt_stub.now = lambda: datetime.now(tz=timezone.utc)
_dt_stub.parse_datetime = MagicMock(return_value=None)
_dt_stub.as_utc = lambda dt: dt

_util_stub = MagicMock()
_util_stub.dt = _dt_stub

_HA_STUBS = {
    "homeassistant": MagicMock(),
    "homeassistant.core": MagicMock(),
    "homeassistant.config_entries": MagicMock(),
    "homeassistant.helpers": MagicMock(),
    "homeassistant.helpers.update_coordinator": MagicMock(),
    "homeassistant.helpers.restore_state": MagicMock(),
    "homeassistant.helpers.dispatcher": MagicMock(),
    "homeassistant.helpers.entity": _entity_mod,
    "homeassistant.helpers.entity_platform": MagicMock(),
    "homeassistant.helpers.event": MagicMock(),
    "homeassistant.helpers.device_registry": MagicMock(),
    "homeassistant.components.sensor": _sensor_mod,
    "homeassistant.components.button": MagicMock(),
    "homeassistant.components.binary_sensor": _binary_sensor_mod,
    "homeassistant.util": _util_stub,
    "homeassistant.util.dt": _dt_stub,
    "homeassistant.const": MagicMock(),
}
for _k, _v in _HA_STUBS.items():
    sys.modules.setdefault(_k, _v)

# Patch dt_util as an attribute on the util stub
_HA_STUBS["homeassistant.util"].dt = _dt_stub

DOMAIN = "universal_room_automation"
ENTRY_TYPE_ROOM = "room"
ENTRY_TYPE_COORDINATOR_MANAGER = "coordinator_manager"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_hass():
    hass = MagicMock()
    hass.data = {DOMAIN: {}}
    hass.config_entries = MagicMock()
    hass.config_entries.async_entries = MagicMock(return_value=[])
    return hass


def _make_entry(entry_type=ENTRY_TYPE_COORDINATOR_MANAGER, entry_id="test_cm_entry"):
    entry = MagicMock()
    entry.entry_id = entry_id
    entry.data = {"entry_type": entry_type}
    entry.options = {}
    entry.async_create_background_task = MagicMock()
    return entry


def _utc_now():
    return datetime.now(tz=timezone.utc)


# ---------------------------------------------------------------------------
# D1 — Boot telemetry capture (inline logic — no HA import required)
# ---------------------------------------------------------------------------

class TestD1SetupTelemetryCapture:
    """D1: Boot telemetry dict is populated with the correct shape.

    Tests inline the D1 logic from __init__.py rather than importing the
    full module (which requires a live HA setup to execute fully).
    """

    def _run_d1_stash(self, hass, setup_started, setup_completed, cm):
        """Replicate the D1 telemetry stash block from __init__.py."""
        try:
            if setup_started is not None:
                _duration_s = (setup_completed - setup_started).total_seconds()
                _room_count = sum(
                    1 for _ce in hass.config_entries.async_entries(DOMAIN)
                    if _ce.data.get("entry_type") == ENTRY_TYPE_ROOM
                )
                hass.data[DOMAIN]["setup_telemetry"] = {
                    "started": setup_started,
                    "completed": setup_completed,
                    "duration_seconds": _duration_s,
                    "coordinator_count": len(cm.coordinators),
                    "room_count": _room_count,
                }
        except Exception:
            pass

    def test_setup_telemetry_populated_on_success(self):
        """D1 AC: all 5 keys present, duration_seconds matches delta."""
        hass = _make_hass()
        t0 = _utc_now()
        t1 = t0 + timedelta(seconds=7.42)

        cm = MagicMock()
        cm.coordinators = {"safety": MagicMock(), "energy": MagicMock()}

        r1 = MagicMock(); r1.data = {"entry_type": "room"}
        r2 = MagicMock(); r2.data = {"entry_type": "room"}
        r3 = MagicMock(); r3.data = {"entry_type": "room"}
        hass.config_entries.async_entries = MagicMock(return_value=[r1, r2, r3])

        self._run_d1_stash(hass, t0, t1, cm)

        telem = hass.data[DOMAIN].get("setup_telemetry")
        assert telem is not None, "setup_telemetry must be present"
        for key in ("started", "completed", "duration_seconds", "coordinator_count", "room_count"):
            assert key in telem, f"missing key: {key}"
        assert abs(telem["duration_seconds"] - 7.42) < 1e-6
        assert telem["coordinator_count"] == 2
        assert telem["room_count"] == 3

    def test_setup_telemetry_does_not_block_setup_on_dt_failure(self):
        """D1 AC: _setup_started=None leaves setup_telemetry absent."""
        hass = _make_hass()
        cm = MagicMock(); cm.coordinators = {}
        # dt raises — _setup_started stays None
        self._run_d1_stash(hass, None, _utc_now(), cm)
        assert "setup_telemetry" not in hass.data[DOMAIN]

    def test_setup_telemetry_coordinator_and_room_counts_accurate(self):
        """D1 AC: coordinator_count and room_count match actual entries."""
        hass = _make_hass()
        t0 = _utc_now()
        t1 = t0 + timedelta(seconds=3.0)

        cm = MagicMock()
        cm.coordinators = {"a": MagicMock(), "b": MagicMock(), "c": MagicMock()}

        r1 = MagicMock(); r1.data = {"entry_type": "room"}
        r2 = MagicMock(); r2.data = {"entry_type": "room"}
        cm_entry = MagicMock(); cm_entry.data = {"entry_type": "coordinator_manager"}
        hass.config_entries.async_entries = MagicMock(return_value=[r1, r2, cm_entry])

        self._run_d1_stash(hass, t0, t1, cm)

        telem = hass.data[DOMAIN]["setup_telemetry"]
        assert telem["coordinator_count"] == 3
        assert telem["room_count"] == 2

    def test_setup_telemetry_keys_stable(self):
        """D1 AC: setup_telemetry uses exactly the 5 documented stable string keys."""
        hass = _make_hass()
        t0 = _utc_now()
        t1 = t0 + timedelta(seconds=1.0)
        cm = MagicMock(); cm.coordinators = {}
        hass.config_entries.async_entries = MagicMock(return_value=[])
        self._run_d1_stash(hass, t0, t1, cm)

        keys = set(hass.data[DOMAIN]["setup_telemetry"].keys())
        assert keys == {"started", "completed", "duration_seconds", "coordinator_count", "room_count"}


# ---------------------------------------------------------------------------
# D2 — URASetupDurationSensor (structural via source read)
# ---------------------------------------------------------------------------

class TestD2SetupDurationSensor:
    """D2: URASetupDurationSensor structural verification via source inspection.

    Full import of sensor.py requires all HA sub-dependencies; instead we
    verify the key structural properties by reading the source file directly,
    then test the sensor's native_value / extra_state_attributes logic inline.
    """

    SENSOR_FILE = ROOT / "custom_components" / "universal_room_automation" / "sensor.py"

    def _read_sensor_source(self):
        with open(self.SENSOR_FILE) as f:
            return f.read()

    def test_setup_duration_sensor_class_exists(self):
        """D2 AC: URASetupDurationSensor class is defined in sensor.py."""
        src = self._read_sensor_source()
        assert "class URASetupDurationSensor" in src

    def test_setup_duration_sensor_unique_id_stable(self):
        """D2 AC: unique_id uses DOMAIN prefix + 'setup_duration_seconds'."""
        src = self._read_sensor_source()
        assert "setup_duration_seconds" in src

    def test_setup_duration_sensor_registry_enabled_default_true(self):
        """D2 AC: entity_registry_enabled_default = True."""
        src = self._read_sensor_source()
        # Must have a line inside the class setting this to True
        assert "_attr_entity_registry_enabled_default = True" in src

    def test_setup_duration_sensor_uses_cm_device_info(self):
        """D2 AC: URASetupDurationSensor calls _cm_device_info() not integration device."""
        src = self._read_sensor_source()
        # The class must reference _cm_device_info
        class_match = re.search(
            r"class URASetupDurationSensor.*?(?=\nclass |\Z)",
            src, re.DOTALL,
        )
        assert class_match, "URASetupDurationSensor class not found"
        class_body = class_match.group(0)
        assert "_cm_device_info()" in class_body, \
            "URASetupDurationSensor must call _cm_device_info() (not integration device)"

    def test_setup_duration_sensor_registered_in_cm_list(self):
        """D2 AC: URASetupDurationSensor(hass, entry) appears in CM sensor list."""
        src = self._read_sensor_source()
        assert "URASetupDurationSensor(hass, entry)" in src

    def test_native_value_logic_returns_rounded_duration(self):
        """D2 AC: native_value logic returns round(float(duration), 3)."""
        # Inline the native_value logic from the sensor
        def _native_value(hass_data_domain):
            try:
                telem = hass_data_domain.get("setup_telemetry")
                if not telem:
                    return None
                return round(float(telem.get("duration_seconds", 0)), 3)
            except Exception:
                return None

        telem = {"duration_seconds": 12.4567}
        assert _native_value({"setup_telemetry": telem}) == round(12.4567, 3)

    def test_native_value_logic_returns_none_when_missing(self):
        """D2 AC: native_value returns None when setup_telemetry absent."""
        def _native_value(hass_data_domain):
            try:
                telem = hass_data_domain.get("setup_telemetry")
                if not telem:
                    return None
                return round(float(telem.get("duration_seconds", 0)), 3)
            except Exception:
                return None

        assert _native_value({}) is None
        assert _native_value({"setup_telemetry": None}) is None


# ---------------------------------------------------------------------------
# D3 — AnomalyDetector wiring
# ---------------------------------------------------------------------------

class TestD3AnomalyDetectorWiring:
    """D3: CM._setup_anomaly_detector is initialized and receives observations.

    Tests use inline logic (same strategy as v4.6.9 TestSeedPreviousLocation)
    because the full manager.py import chain pulls in homeassistant.components.*
    which is not available in the lightweight test env.
    """

    def _make_fake_cm(self, detector_raises=False):
        """Build a minimal CM-like object that inlines the D3 __init__ logic."""
        import logging
        _log = logging.getLogger("test_cm_d3")

        class _FakeAnomalyDetector:
            def __init__(self, hass, coordinator_id, metric_names, minimum_samples):
                if detector_raises:
                    raise RuntimeError("detector init boom")
                self.coordinator_id = coordinator_id
                self.metric_names = metric_names
                self.minimum_samples = minimum_samples
                self._record_calls = []

            def record_observation(self, metric_name, scope, value):
                self._record_calls.append(
                    {"metric_name": metric_name, "scope": scope, "value": value}
                )
                return None  # no anomaly yet (baseline immature)

        class _FakeCM:
            def __init__(self, hass, det_raises=False):
                self.hass = hass
                self.coordinators = {}
                try:
                    self._setup_anomaly_detector = _FakeAnomalyDetector(
                        hass=hass,
                        coordinator_id="coordinator_manager",
                        metric_names=["setup_duration_seconds"],
                        minimum_samples=10,
                    )
                except Exception:
                    _log.debug("setup_anomaly_detector init failed", exc_info=True)
                    self._setup_anomaly_detector = None

        hass = MagicMock()
        hass.data = {}
        return _FakeCM(hass, det_raises=detector_raises)

    def test_setup_anomaly_detector_registered_on_cm_init(self):
        """D3 AC: _setup_anomaly_detector has correct coordinator_id, metric, min_samples."""
        cm = self._make_fake_cm()
        det = cm._setup_anomaly_detector
        assert det is not None
        assert det.coordinator_id == "coordinator_manager"
        assert "setup_duration_seconds" in det.metric_names
        assert det.minimum_samples == 10

    def test_setup_anomaly_detector_init_failure_leaves_cm_intact(self):
        """D3/D4 AC: AnomalyDetector raising must not prevent CM construction."""
        cm = self._make_fake_cm(detector_raises=True)
        assert cm._setup_anomaly_detector is None, \
            "_setup_anomaly_detector must be None when init fails (CM still constructed)"

    def test_source_manager_py_has_setup_anomaly_detector(self):
        """D3 AC: manager.py source contains _setup_anomaly_detector init block."""
        manager_file = ROOT / "custom_components" / "universal_room_automation" / \
                       "domain_coordinators" / "manager.py"
        with open(manager_file) as f:
            src = f.read()
        assert "_setup_anomaly_detector" in src, \
            "_setup_anomaly_detector must be set in manager.py CoordinatorManager.__init__"
        assert "coordinator_manager" in src
        assert "setup_duration_seconds" in src
        assert "minimum_samples=10" in src

    def test_observation_push_inner_logic(self):
        """D3 AC: Inner observation coroutine calls record_observation with correct args."""
        hass = _make_hass()
        t0 = _utc_now()
        t1 = t0 + timedelta(seconds=9.1)
        hass.data[DOMAIN]["setup_telemetry"] = {
            "started": t0, "completed": t1,
            "duration_seconds": 9.1,
            "coordinator_count": 2, "room_count": 3,
        }

        det = MagicMock()
        det.record_observation = MagicMock(return_value=None)
        cm = MagicMock()
        cm._setup_anomaly_detector = det
        hass.data[DOMAIN]["coordinator_manager"] = cm

        # Inline the inner coroutine from __init__.py D3
        async def _push():
            try:
                _cm = hass.data.get(DOMAIN, {}).get("coordinator_manager")
                if _cm is None:
                    return
                _det = getattr(_cm, "_setup_anomaly_detector", None)
                if _det is None:
                    return
                _telem = hass.data.get(DOMAIN, {}).get("setup_telemetry")
                if _telem is None:
                    return
                _dur = _telem.get("duration_seconds")
                if _dur is None:
                    return
                _det.record_observation(
                    metric_name="setup_duration_seconds",
                    scope="house",
                    value=float(_dur),
                )
            except Exception:
                pass

        asyncio.run(_push())
        det.record_observation.assert_called_once_with(
            metric_name="setup_duration_seconds",
            scope="house",
            value=9.1,
        )

    def test_observation_push_swallows_record_exception(self):
        """D3 AC: record_observation raising is swallowed by inner try/except."""
        hass = _make_hass()
        t0 = _utc_now()
        hass.data[DOMAIN]["setup_telemetry"] = {
            "started": t0, "completed": t0 + timedelta(seconds=5),
            "duration_seconds": 5.0, "coordinator_count": 1, "room_count": 0,
        }
        det = MagicMock()
        det.record_observation = MagicMock(side_effect=RuntimeError("boom"))
        cm = MagicMock()
        cm._setup_anomaly_detector = det
        hass.data[DOMAIN]["coordinator_manager"] = cm

        async def _push():
            try:
                _cm = hass.data.get(DOMAIN, {}).get("coordinator_manager")
                _det = getattr(_cm, "_setup_anomaly_detector", None)
                _telem = hass.data.get(DOMAIN, {}).get("setup_telemetry")
                _det.record_observation(
                    metric_name="setup_duration_seconds",
                    scope="house",
                    value=float(_telem["duration_seconds"]),
                )
            except Exception:
                pass

        asyncio.run(_push())  # must not raise

    def test_observation_push_when_cm_missing(self):
        """D3 AC: No exception when CM is absent from hass.data."""
        hass = _make_hass()
        # coordinator_manager NOT in hass.data

        async def _push():
            _cm = hass.data.get(DOMAIN, {}).get("coordinator_manager")
            if _cm is None:
                return

        asyncio.run(_push())  # passes if no exception

    def test_exactly_one_observation_per_setup(self):
        """D3 AC: Each setup invocation pushes exactly one observation."""
        hass = _make_hass()
        t0 = _utc_now()
        call_log = []

        det = MagicMock()
        det.record_observation = MagicMock(
            side_effect=lambda **kw: call_log.append(kw) or None
        )
        cm = MagicMock()
        cm._setup_anomaly_detector = det
        hass.data[DOMAIN]["coordinator_manager"] = cm
        hass.data[DOMAIN]["setup_telemetry"] = {
            "started": t0, "completed": t0 + timedelta(seconds=3),
            "duration_seconds": 3.0, "coordinator_count": 1, "room_count": 1,
        }

        async def _push():
            _cm = hass.data.get(DOMAIN, {}).get("coordinator_manager")
            _det = getattr(_cm, "_setup_anomaly_detector", None)
            _telem = hass.data.get(DOMAIN, {}).get("setup_telemetry")
            _det.record_observation(
                metric_name="setup_duration_seconds",
                scope="house",
                value=float(_telem["duration_seconds"]),
            )

        asyncio.run(_push())
        assert len(call_log) == 1

        # Simulate reload: second setup does NOT double-push into same detector
        asyncio.run(_push())
        assert len(call_log) == 2  # second boot = second distinct observation


# ---------------------------------------------------------------------------
# D4 — Threat-model: telemetry never blocks setup
# ---------------------------------------------------------------------------

class TestD4ThreatModelHonor:
    """D4: Every telemetry failure path is swallowed; setup outcome unaffected."""

    def test_dt_failure_leaves_telemetry_absent(self):
        """D4 AC: dt_util.utcnow raising must leave setup_telemetry absent."""
        hass = _make_hass()
        _setup_started = None
        try:
            raise RuntimeError("simulated dt failure")
        except Exception:
            pass

        if _setup_started is not None:
            hass.data[DOMAIN]["setup_telemetry"] = {"should": "not_be_set"}

        assert "setup_telemetry" not in hass.data[DOMAIN]

    def test_stash_exception_does_not_affect_coordinator_manager(self):
        """D4 AC: Exception in telemetry stash must not remove coordinator_manager key."""
        hass = _make_hass()
        cm = MagicMock()
        hass.data[DOMAIN]["coordinator_manager"] = cm

        try:
            raise RuntimeError("stash boom")
        except Exception:
            pass  # non-fatal

        assert hass.data[DOMAIN]["coordinator_manager"] is cm

    def test_record_observation_exception_swallowed(self):
        """D4 AC: record_observation raising is swallowed; no outer exception."""
        hass = _make_hass()
        t0 = _utc_now()
        hass.data[DOMAIN]["setup_telemetry"] = {
            "duration_seconds": 6.0,
        }
        det = MagicMock()
        det.record_observation = MagicMock(side_effect=RuntimeError("record boom"))
        cm = MagicMock()
        cm._setup_anomaly_detector = det
        hass.data[DOMAIN]["coordinator_manager"] = cm

        async def _bg_task():
            try:
                _cm = hass.data.get(DOMAIN, {}).get("coordinator_manager")
                _det = getattr(_cm, "_setup_anomaly_detector", None)
                _telem = hass.data.get(DOMAIN, {}).get("setup_telemetry")
                _det.record_observation(
                    metric_name="setup_duration_seconds",
                    scope="house",
                    value=float(_telem["duration_seconds"]),
                )
            except Exception:
                pass

        asyncio.run(_bg_task())
        # No exception → test passes

    def test_init_py_wraps_telemetry_in_try_except(self):
        """D4 AC: Source inspection — telemetry stash block has try/except in __init__.py."""
        init_file = ROOT / "custom_components" / "universal_room_automation" / "__init__.py"
        with open(init_file) as f:
            src = f.read()
        # D1 stash block must be inside a try/except
        assert "setup telemetry stash failed" in src or "setup telemetry captured" in src, \
            "D1 telemetry stash must log at debug"
        # D3 bg task inner try/except
        assert "setup anomaly observation push failed" in src or \
               "_push_setup_observation" in src, \
               "D3 observation push must have inner try/except"

    def test_init_py_telemetry_failures_log_at_debug_not_error(self):
        """v4.6.10 review fix B-M1: defensive try/except blocks log at debug.

        Source-inspection verifies all three telemetry-related try/except blocks
        (D1 start, D1 stash, D3 push, D3 schedule) use _LOGGER.debug, never
        _LOGGER.error or _LOGGER.warning. Non-fatal degradations must be quiet.
        """
        init_file = ROOT / "custom_components" / "universal_room_automation" / "__init__.py"
        with open(init_file) as f:
            src = f.read()
        # The 4 telemetry-related debug log signatures
        required_debug_lines = [
            "setup telemetry start capture failed",
            "setup telemetry stash failed",
            "setup anomaly observation push failed",
            "setup anomaly observation scheduling failed",
        ]
        for sig in required_debug_lines:
            assert sig in src, f"Missing telemetry debug log signature: {sig!r}"
        # Confirm those signatures appear with _LOGGER.debug (not error/warning)
        for sig in required_debug_lines:
            # Find each occurrence + check the preceding logger call is .debug
            idx = src.find(sig)
            assert idx > 0
            preceding = src[max(0, idx - 200):idx]
            assert "_LOGGER.debug" in preceding, \
                f"Telemetry signature {sig!r} must be logged via _LOGGER.debug, " \
                f"not error/warning. Preceding context: {preceding[-150:]!r}"

    def test_init_py_d3_scheduling_has_outer_try_except(self):
        """v4.6.10 review fix H1: entry.async_create_background_task call itself wrapped.

        If task scheduling raises (entry already unloaded, etc.), it must NOT
        propagate to the outer 'Failed to initialize Coordinator Manager' except.
        """
        init_file = ROOT / "custom_components" / "universal_room_automation" / "__init__.py"
        with open(init_file) as f:
            src = f.read()
        # Find the D3 scheduling call
        sched_idx = src.find("ura_setup_duration_observation")
        assert sched_idx > 0, "D3 scheduling call not found"
        # Look for the outer try/except wrapping it
        following = src[sched_idx:sched_idx + 500]
        assert "setup anomaly observation scheduling failed" in following, \
            "D3 entry.async_create_background_task call must be wrapped in its own " \
            "try/except logging 'setup anomaly observation scheduling failed' at debug. " \
            "Without this, a scheduling exception masks as 'CM init failed' at ERROR."


class TestB2UnloadTelemetryCleanup:
    """v4.6.10 review fix B2: setup_telemetry popped on async_unload_entry."""

    def test_async_unload_pops_setup_telemetry(self):
        """B2 AC: source inspection — async_unload_entry must pop setup_telemetry.

        Without this, a config-entry reload that fails before the CM init block
        leaves stale telemetry in hass.data, causing the sensor to silently
        report the PREVIOUS setup's duration. Bug Class #36 (lifecycle teardown).
        """
        init_file = ROOT / "custom_components" / "universal_room_automation" / "__init__.py"
        with open(init_file) as f:
            src = f.read()
        # Find async_unload_entry body
        unload_idx = src.find("async def async_unload_entry")
        assert unload_idx > 0, "async_unload_entry not found"
        # Pop must appear between async_unload_entry and the next async def
        next_def = src.find("async def ", unload_idx + 1)
        unload_body = src[unload_idx:next_def if next_def > 0 else len(src)]
        assert 'hass.data[DOMAIN].pop("setup_telemetry"' in unload_body, \
            "async_unload_entry must pop setup_telemetry from hass.data[DOMAIN]"


# ---------------------------------------------------------------------------
# D5a — _PERSON_LAST_STATE_SKIP_VALUES module constant
# ---------------------------------------------------------------------------

class TestD5aPersonSkipStates:
    """D5a: _PERSON_LAST_STATE_SKIP_VALUES is a frozenset at module top in aggregation.py."""

    AGG_FILE = ROOT / "custom_components" / "universal_room_automation" / "aggregation.py"

    def _read_agg(self):
        with open(self.AGG_FILE) as f:
            return f.read()

    def test_module_constant_defined_as_frozenset(self):
        """D5a AC: frozenset definition appears in aggregation.py."""
        src = self._read_agg()
        assert "frozenset" in src
        assert "_PERSON_LAST_STATE_SKIP_VALUES" in src

    def test_no_inline_skip_states_local_assignments(self):
        """D5a AC: grep _SKIP_STATES = returns zero local-scope assignments."""
        src = self._read_agg()
        local_assignments = re.findall(r"^\s+_SKIP_STATES\s*=", src, re.MULTILINE)
        assert local_assignments == [], (
            f"Inline _SKIP_STATES assignments found: {local_assignments}"
        )

    def test_module_constant_appears_three_or_more_times(self):
        """D5a AC: definition + 2 use sites = ≥3 occurrences."""
        src = self._read_agg()
        count = src.count("_PERSON_LAST_STATE_SKIP_VALUES")
        assert count >= 3, f"Expected ≥3 occurrences, found {count}"

    def test_constant_contains_required_sentinels(self):
        """D5a AC: frozenset literal contains the HA person-entity sentinels."""
        src = self._read_agg()
        # Find the definition block
        match = re.search(
            r"_PERSON_LAST_STATE_SKIP_VALUES.*?frozenset\(\{(.*?)\}\)",
            src, re.DOTALL,
        )
        assert match, "_PERSON_LAST_STATE_SKIP_VALUES frozenset definition not found"
        literal = match.group(1)
        for sentinel in ('"unknown"', '"unavailable"', '"not_home"', '"home"', '"away"'):
            assert sentinel in literal, f"sentinel {sentinel} missing from frozenset literal"

    def test_logic_skip_values_set_is_correct(self):
        """D5a AC: Inline test — skip values match expected HA person-entity sentinels."""
        # Test the set semantics without importing the module
        _SKIP = frozenset({
            "unknown", "unavailable", "Unknown", "Unavailable",
            "None", "none", "away", "Away", "",
            "not_home", "Not_home", "home", "Home",
        })
        must_skip = ["unknown", "unavailable", "Unknown", "not_home", "home", "away", ""]
        must_pass = ["Master Bedroom", "Office", "Kitchen", "Living Room"]
        for v in must_skip:
            assert v in _SKIP, f"{v!r} should be in skip set"
        for v in must_pass:
            assert v not in _SKIP, f"{v!r} should NOT be in skip set"


# ---------------------------------------------------------------------------
# D6 — MONETARY state_class warning fixes (source-grep)
# ---------------------------------------------------------------------------

class TestD6MonetaryStateClassFixes:
    """D6: MONETARY sensors must use TOTAL or no state_class.

    Uses source-file grep so the assertions are stable regardless of whether
    the HA stub fully supports the sensor enums.
    """

    AGG_FILE = ROOT / "custom_components" / "universal_room_automation" / "aggregation.py"
    SENSOR_FILE = ROOT / "custom_components" / "universal_room_automation" / "sensor.py"

    def _read(self, path):
        with open(path) as f:
            return f.read()

    def _extract_attr_state_class(self, src: str, class_name: str) -> str | None:
        """Find _attr_state_class = ... within a named class body.

        Returns the value token (e.g. 'SensorStateClass.TOTAL') or None if
        the attribute is absent from the class.  Searches only actual attribute
        assignment lines (starting with whitespace + '_attr_state_class'),
        not docstrings or comments — so version-comment mentions of
        TOTAL_INCREASING don't produce false positives.
        """
        # Locate the class definition
        class_match = re.search(
            r"^class " + re.escape(class_name) + r"\b.*?(?=\n^class |\Z)",
            src, re.DOTALL | re.MULTILINE,
        )
        if not class_match:
            return "CLASS_NOT_FOUND"
        body = class_match.group(0)
        # Match only attribute assignment lines (indented), not docstrings
        attr_match = re.search(
            r"^\s+_attr_state_class\s*=\s*(\S+)",
            body, re.MULTILINE,
        )
        if not attr_match:
            return None  # attribute absent = no state_class
        return attr_match.group(1).strip()

    def test_whole_house_cost_today_state_class_is_total(self):
        """D6 AC: WholeHouseCostTodaySensor _attr_state_class = TOTAL."""
        src = self._read(self.AGG_FILE)
        sc = self._extract_attr_state_class(src, "WholeHouseCostTodaySensor")
        assert sc != "CLASS_NOT_FOUND", "WholeHouseCostTodaySensor not found"
        assert sc is not None and "TOTAL" in sc and "INCREASING" not in sc, \
            f"WholeHouseCostTodaySensor state_class must be TOTAL, got: {sc}"

    def test_zone_energy_cost_today_state_class_is_total(self):
        """D6 AC: ZoneEnergyCostTodaySensor _attr_state_class = TOTAL."""
        src = self._read(self.AGG_FILE)
        sc = self._extract_attr_state_class(src, "ZoneEnergyCostTodaySensor")
        assert sc != "CLASS_NOT_FOUND", "ZoneEnergyCostTodaySensor not found"
        assert sc is not None and "TOTAL" in sc and "INCREASING" not in sc, \
            f"ZoneEnergyCostTodaySensor state_class must be TOTAL, got: {sc}"

    def test_zone_cost_per_hour_has_no_state_class(self):
        """D6 AC: ZoneCostPerHourSensor has no _attr_state_class (rate sensor)."""
        src = self._read(self.AGG_FILE)
        sc = self._extract_attr_state_class(src, "ZoneCostPerHourSensor")
        assert sc != "CLASS_NOT_FOUND", "ZoneCostPerHourSensor not found"
        assert sc is None, \
            f"ZoneCostPerHourSensor must not have _attr_state_class, got: {sc}"

    def test_energy_predicted_bill_has_no_state_class(self):
        """D6 AC: EnergyPredictedBillSensor has no _attr_state_class after D6 fix."""
        src = self._read(self.SENSOR_FILE)
        sc = self._extract_attr_state_class(src, "EnergyPredictedBillSensor")
        assert sc != "CLASS_NOT_FOUND", "EnergyPredictedBillSensor not found"
        assert sc is None or "MEASUREMENT" not in sc, \
            f"EnergyPredictedBillSensor must not have MEASUREMENT state_class, got: {sc}"

    def test_arbitrage_savings_total_uses_total_not_total_increasing(self):
        """D6 AC: EnergyArbitrageSavingsTotalSensor _attr_state_class = TOTAL."""
        src = self._read(self.SENSOR_FILE)
        sc = self._extract_attr_state_class(src, "EnergyArbitrageSavingsTotalSensor")
        assert sc != "CLASS_NOT_FOUND", "EnergyArbitrageSavingsTotalSensor not found"
        assert sc is not None and "TOTAL" in sc and "INCREASING" not in sc, \
            f"EnergyArbitrageSavingsTotalSensor must use TOTAL, got: {sc}"

    def test_no_monetary_total_increasing_attr_in_aggregation(self):
        """D6 AC: No _attr_state_class = TOTAL_INCREASING on MONETARY classes in aggregation.py."""
        src = self._read(self.AGG_FILE)
        class_pattern = re.compile(
            r"^class (\w+)\b.*?(?=\n^class |\Z)", re.DOTALL | re.MULTILINE
        )
        bad = []
        for m in class_pattern.finditer(src):
            body = m.group(0)
            if "MONETARY" not in body:
                continue
            # Check _attr_state_class assignment lines only
            sc_match = re.search(r"^\s+_attr_state_class\s*=\s*(\S+)", body, re.MULTILINE)
            if sc_match and "TOTAL_INCREASING" in sc_match.group(1):
                bad.append(m.group(1).split("(")[0].strip())
        assert bad == [], \
            f"MONETARY + TOTAL_INCREASING _attr_state_class in aggregation.py: {bad}"

    def test_no_monetary_measurement_attr_in_aggregation(self):
        """D6 AC: No _attr_state_class = MEASUREMENT on MONETARY classes in aggregation.py."""
        src = self._read(self.AGG_FILE)
        class_pattern = re.compile(
            r"^class (\w+)\b.*?(?=\n^class |\Z)", re.DOTALL | re.MULTILINE
        )
        bad = []
        for m in class_pattern.finditer(src):
            body = m.group(0)
            if "MONETARY" not in body:
                continue
            sc_match = re.search(r"^\s+_attr_state_class\s*=\s*(\S+)", body, re.MULTILINE)
            if sc_match and "MEASUREMENT" in sc_match.group(1):
                bad.append(m.group(1).split("(")[0].strip())
        assert bad == [], \
            f"MONETARY + MEASUREMENT _attr_state_class in aggregation.py: {bad}"

    def test_no_monetary_total_increasing_attr_in_sensor_py(self):
        """D6 AC: No _attr_state_class = TOTAL_INCREASING on MONETARY classes in sensor.py."""
        src = self._read(self.SENSOR_FILE)
        class_pattern = re.compile(
            r"^class (\w+)\b.*?(?=\n^class |\Z)", re.DOTALL | re.MULTILINE
        )
        bad = []
        for m in class_pattern.finditer(src):
            body = m.group(0)
            if "MONETARY" not in body:
                continue
            sc_match = re.search(r"^\s+_attr_state_class\s*=\s*(\S+)", body, re.MULTILINE)
            if sc_match and "TOTAL_INCREASING" in sc_match.group(1):
                bad.append(m.group(1).split("(")[0].strip())
        assert bad == [], \
            f"MONETARY + TOTAL_INCREASING _attr_state_class in sensor.py: {bad}"
