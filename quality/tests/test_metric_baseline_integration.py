"""Tests for v3.13.2 MetricBaseline integration.

Verifies:
- Circuit power z-score anomaly detection
- Peak import baseline z-score threshold
- Baseline save/restore round-trip
- Threshold fallback chain (z-score > percentile > fixed)
"""

import asyncio
import os
import sqlite3
from datetime import datetime
from unittest.mock import MagicMock, AsyncMock, patch, PropertyMock
import pytest
import sys
import types

# ---------------------------------------------------------------------------
# Mock homeassistant before importing URA code
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
    "homeassistant.core": {"HomeAssistant": _mock_cls, "callback": _identity},
    "homeassistant.config_entries": {"ConfigEntry": _mock_cls},
    "homeassistant.const": MagicMock(),
    "homeassistant.helpers": {},
    "homeassistant.helpers.device_registry": {"DeviceInfo": dict},
    "homeassistant.helpers.entity": {"DeviceInfo": dict, "EntityCategory": _mock_cls()},
    "homeassistant.helpers.entity_platform": {"AddEntitiesCallback": _mock_cls},
    "homeassistant.helpers.event": {
        "async_track_time_interval": MagicMock(),
        "async_call_later": MagicMock(),
    },
    "homeassistant.helpers.dispatcher": {
        "async_dispatcher_connect": MagicMock(),
        "async_dispatcher_send": MagicMock(),
    },
    "homeassistant.helpers.update_coordinator": {
        "DataUpdateCoordinator": _mock_cls, "UpdateFailed": Exception,
    },
    "homeassistant.helpers.selector": _mock_cls(),
    "homeassistant.helpers.entity_registry": {"async_get": _mock_cls()},
    "homeassistant.helpers.sun": {},
    "homeassistant.util": {},
    "homeassistant.util.dt": {
        "utcnow": lambda: datetime.utcnow(),
        "now": lambda: datetime.now(),
        "as_local": lambda dt: dt,
    },
    "homeassistant.components": {},
    "homeassistant.components.sensor": {
        "SensorEntity": type("SensorEntity", (), {}),
        "SensorDeviceClass": _mock_cls(), "SensorStateClass": _mock_cls(),
    },
    "homeassistant.components.binary_sensor": {
        "BinarySensorEntity": type("BinarySensorEntity", (), {}),
        "BinarySensorDeviceClass": _mock_cls(),
    },
    "homeassistant.components.button": {"ButtonEntity": type("ButtonEntity", (), {})},
}

for name, attrs in _mods.items():
    if isinstance(attrs, dict):
        sys.modules.setdefault(name, _mock_module(name, **attrs))
    else:
        sys.modules.setdefault(name, attrs)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

_cc = types.ModuleType("custom_components")
_cc.__path__ = [os.path.join(os.path.dirname(__file__), "..", "..", "custom_components")]
sys.modules.setdefault("custom_components", _cc)

_ura = types.ModuleType("custom_components.universal_room_automation")
_ura_path = os.path.join(_cc.__path__[0], "universal_room_automation")
_ura.__path__ = [_ura_path]
_ura.__package__ = "custom_components.universal_room_automation"
sys.modules["custom_components.universal_room_automation"] = _ura


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# Tests: MetricBaseline Core
# ---------------------------------------------------------------------------


class TestMetricBaselineCore:
    """Test MetricBaseline z-score computation."""

    def test_z_score_after_enough_samples(self):
        """Z-score should be computable after sufficient samples."""
        from custom_components.universal_room_automation.domain_coordinators.coordinator_diagnostics import MetricBaseline

        bl = MetricBaseline(
            metric_name="test", coordinator_id="test", scope="unit",
        )
        # Feed 100 samples around 50W with std ~5
        import random
        random.seed(42)
        for _ in range(100):
            bl.update(random.gauss(50, 5))

        assert bl.sample_count == 100
        assert 45 < bl.mean < 55  # Should be close to 50

        # Normal value should have low z-score
        z_normal = bl.z_score(52)
        assert z_normal < 2

        # Extreme value should have high z-score
        z_extreme = bl.z_score(100)
        assert z_extreme > 5

    def test_z_score_zero_variance(self):
        """Z-score with zero variance should return 0."""
        from custom_components.universal_room_automation.domain_coordinators.coordinator_diagnostics import MetricBaseline

        bl = MetricBaseline(
            metric_name="test", coordinator_id="test", scope="unit",
        )
        # Feed identical values
        for _ in range(10):
            bl.update(42.0)

        # With minimum variance floor, z for identical value should be exactly 0.0
        z = bl.z_score(42.0)
        assert z == 0.0

    def test_baseline_update_welford(self):
        """Welford's algorithm should produce correct mean/variance."""
        from custom_components.universal_room_automation.domain_coordinators.coordinator_diagnostics import MetricBaseline

        bl = MetricBaseline(
            metric_name="test", coordinator_id="test", scope="unit",
        )
        values = [10, 20, 30, 40, 50]
        for v in values:
            bl.update(v)

        assert bl.sample_count == 5
        assert abs(bl.mean - 30.0) < 0.001


# ---------------------------------------------------------------------------
# Tests: Circuit Z-Score Anomaly Detection
# ---------------------------------------------------------------------------


class TestCircuitZScoreDetection:
    """Test SPANCircuitMonitor MetricBaseline integration."""

    def _make_circuit_monitor(self):
        """Create a SPANCircuitMonitor with mocked HA states."""
        from custom_components.universal_room_automation.domain_coordinators.energy_circuits import (
            SPANCircuitMonitor, CircuitInfo,
        )
        hass = MagicMock()
        monitor = SPANCircuitMonitor(hass)
        return monitor, hass

    def test_baseline_created_per_circuit(self):
        """Each circuit should get its own MetricBaseline."""
        monitor, hass = self._make_circuit_monitor()
        from custom_components.universal_room_automation.domain_coordinators.energy_circuits import CircuitInfo

        # Add circuits
        monitor._circuits = {
            "sensor.span_panel_kitchen_power": CircuitInfo(
                "sensor.span_panel_kitchen_power", "Kitchen", "left"
            ),
            "sensor.span_panel_hvac_power": CircuitInfo(
                "sensor.span_panel_hvac_power", "HVAC", "right"
            ),
        }
        monitor._discovered = True

        # Mock states with normal power
        state_map = {
            "sensor.span_panel_kitchen_power": MagicMock(state="100"),
            "sensor.span_panel_hvac_power": MagicMock(state="200"),
        }
        hass.states.get = lambda eid: state_map.get(eid)

        # Run check — should create baselines
        monitor.check_anomalies()
        assert len(monitor._power_baselines) == 2
        assert "sensor.span_panel_kitchen_power" in monitor._power_baselines
        assert "sensor.span_panel_hvac_power" in monitor._power_baselines

    def test_z_score_anomaly_after_learning(self):
        """After enough samples, extreme values should trigger consumption_anomaly."""
        monitor, hass = self._make_circuit_monitor()
        from custom_components.universal_room_automation.domain_coordinators.energy_circuits import (
            CircuitInfo, CIRCUIT_MIN_SAMPLES,
        )

        monitor._circuits = {
            "sensor.span_panel_kitchen_power": CircuitInfo(
                "sensor.span_panel_kitchen_power", "Kitchen", "left"
            ),
        }
        monitor._discovered = True

        # Feed normal readings (100W ± small noise) to build baseline
        import random
        random.seed(42)
        for _ in range(CIRCUIT_MIN_SAMPLES + 5):
            power = random.gauss(100, 5)
            state_map = {
                "sensor.span_panel_kitchen_power": MagicMock(state=str(power)),
            }
            hass.states.get = lambda eid, sm=state_map: sm.get(eid)
            monitor.check_anomalies()

        # Verify baseline has enough samples
        bl = monitor._power_baselines["sensor.span_panel_kitchen_power"]
        assert bl.sample_count >= CIRCUIT_MIN_SAMPLES

        # Now inject extreme value — should trigger consumption_anomaly
        state_map = {
            "sensor.span_panel_kitchen_power": MagicMock(state="500"),
        }
        hass.states.get = lambda eid: state_map.get(eid)
        anomalies = monitor.check_anomalies()

        consumption_anomalies = [a for a in anomalies if a["type"] == "consumption_anomaly"]
        assert len(consumption_anomalies) == 1
        assert consumption_anomalies[0]["circuit"] == "Kitchen"
        assert consumption_anomalies[0]["z_score"] > 4

    def test_normal_reading_no_anomaly(self):
        """Normal readings within expected range should not trigger anomaly."""
        monitor, hass = self._make_circuit_monitor()
        from custom_components.universal_room_automation.domain_coordinators.energy_circuits import (
            CircuitInfo, CIRCUIT_MIN_SAMPLES,
        )

        monitor._circuits = {
            "sensor.span_panel_kitchen_power": CircuitInfo(
                "sensor.span_panel_kitchen_power", "Kitchen", "left"
            ),
        }
        monitor._discovered = True

        import random
        random.seed(42)
        for _ in range(CIRCUIT_MIN_SAMPLES + 5):
            power = random.gauss(100, 5)
            state_map = {
                "sensor.span_panel_kitchen_power": MagicMock(state=str(power)),
            }
            hass.states.get = lambda eid, sm=state_map: sm.get(eid)
            monitor.check_anomalies()

        # Normal value within range
        state_map = {
            "sensor.span_panel_kitchen_power": MagicMock(state="105"),
        }
        hass.states.get = lambda eid: state_map.get(eid)
        anomalies = monitor.check_anomalies()

        consumption_anomalies = [a for a in anomalies if a["type"] == "consumption_anomaly"]
        assert len(consumption_anomalies) == 0

    def test_baseline_status_in_get_status(self):
        """get_status should include baseline tracking info."""
        monitor, hass = self._make_circuit_monitor()
        from custom_components.universal_room_automation.domain_coordinators.energy_circuits import CircuitInfo

        monitor._circuits = {
            "sensor.span_panel_kitchen_power": CircuitInfo(
                "sensor.span_panel_kitchen_power", "Kitchen", "left"
            ),
        }
        monitor._discovered = True

        state_map = {
            "sensor.span_panel_kitchen_power": MagicMock(state="100"),
        }
        hass.states.get = lambda eid: state_map.get(eid)
        monitor.check_anomalies()

        status = monitor.get_status()
        assert "baselines_tracked" in status
        assert "baselines_active" in status
        assert status["baselines_tracked"] == 1
        assert status["baselines_active"] == 0  # Not enough samples yet

    def test_save_and_restore_baselines(self):
        """Baselines should round-trip through save/restore."""
        monitor, hass = self._make_circuit_monitor()
        from custom_components.universal_room_automation.domain_coordinators.coordinator_diagnostics import MetricBaseline

        # Pre-populate a baseline
        bl = MetricBaseline(
            metric_name="circuit_power", coordinator_id="energy", scope="Kitchen",
            mean=100.0, variance=25.0, sample_count=200,
        )
        monitor._power_baselines["sensor.span_panel_kitchen_power"] = bl

        # Save
        saved = monitor.get_baselines_for_save()
        assert len(saved) == 1

        # Create new monitor, restore
        monitor2, _ = self._make_circuit_monitor()
        monitor2.restore_baselines(saved)
        assert len(monitor2._power_baselines) == 1
        restored = monitor2._power_baselines["sensor.span_panel_kitchen_power"]
        assert restored.mean == 100.0
        assert restored.sample_count == 200


# ---------------------------------------------------------------------------
# Tests: Load Shedding Z-Score Threshold
# ---------------------------------------------------------------------------


class TestLoadSheddingZScoreThreshold:
    """Test _get_effective_shedding_threshold with MetricBaseline."""

    def _make_energy_coordinator(self):
        """Create a minimal EnergyCoordinator for testing threshold."""
        from custom_components.universal_room_automation.domain_coordinators.energy import (
            EnergyCoordinator,
        )
        from custom_components.universal_room_automation.domain_coordinators.coordinator_diagnostics import MetricBaseline

        hass = MagicMock()
        hass.data = {}

        ec = object.__new__(EnergyCoordinator)
        ec.hass = hass
        ec._load_shedding_threshold_kw = 8.0  # Fixed threshold
        ec._load_shedding_mode = "auto"
        ec._peak_import_history = []
        ec._learned_threshold_kw = None
        ec._peak_import_baseline = MetricBaseline(
            metric_name="peak_import_kw",
            coordinator_id="energy",
            scope="load_shedding",
        )
        return ec

    def test_fallback_to_fixed_threshold(self):
        """With no data, should use fixed threshold."""
        ec = self._make_energy_coordinator()
        threshold = ec._get_effective_shedding_threshold()
        assert threshold == 8.0

    def test_percentile_with_enough_history(self):
        """With 30+ days of history but no baseline, uses percentile."""
        ec = self._make_energy_coordinator()
        # Need LOAD_SHEDDING_AUTO_MIN_DAYS * 10 readings
        from custom_components.universal_room_automation.domain_coordinators.energy_const import (
            LOAD_SHEDDING_AUTO_MIN_DAYS,
        )
        ec._peak_import_history = [float(i) for i in range(LOAD_SHEDDING_AUTO_MIN_DAYS * 10 + 1)]
        threshold = ec._get_effective_shedding_threshold()
        # Should be 90th percentile, not the fixed 8.0
        assert threshold != 8.0
        assert threshold > 0

    def test_z_score_with_enough_baseline(self):
        """With 300+ baseline samples, uses mean + 2*std."""
        ec = self._make_energy_coordinator()
        import random
        random.seed(42)
        # Feed 350 samples around 5.0 kW with std ~1.0
        for _ in range(350):
            ec._peak_import_baseline.update(random.gauss(5.0, 1.0))

        threshold = ec._get_effective_shedding_threshold()
        # Should be ~5.0 + 2*1.0 = ~7.0 kW (not 8.0 fixed)
        assert 5.0 < threshold < 9.0  # mean + 2*std
        assert threshold != 8.0

    def test_z_score_beats_percentile(self):
        """Z-score threshold should take priority over percentile when both available."""
        ec = self._make_energy_coordinator()
        from custom_components.universal_room_automation.domain_coordinators.energy_const import (
            LOAD_SHEDDING_AUTO_MIN_DAYS,
        )
        # Both history and baseline have enough data
        ec._peak_import_history = [3.0] * (LOAD_SHEDDING_AUTO_MIN_DAYS * 10 + 1)
        import random
        random.seed(42)
        for _ in range(350):
            ec._peak_import_baseline.update(random.gauss(5.0, 1.0))

        threshold = ec._get_effective_shedding_threshold()
        # Z-score should win (mean + 2*std ~ 7.0), not percentile of history (3.0)
        assert 5.0 < threshold < 9.0
        assert threshold != 3.0  # Not the percentile value

    def test_fixed_mode_ignores_baseline(self):
        """In 'fixed' mode, should always use configured threshold."""
        ec = self._make_energy_coordinator()
        from custom_components.universal_room_automation.domain_coordinators.energy_const import (
            LOAD_SHEDDING_MODE_FIXED,
        )
        ec._load_shedding_mode = LOAD_SHEDDING_MODE_FIXED
        import random
        random.seed(42)
        for _ in range(350):
            ec._peak_import_baseline.update(random.gauss(5.0, 1.0))

        threshold = ec._get_effective_shedding_threshold()
        assert threshold == 8.0  # Fixed, ignores baseline


# ---------------------------------------------------------------------------
# Tests: Baseline DB Round-Trip
# ---------------------------------------------------------------------------


class TestBaselineDBRoundTrip:
    """Test baseline save/restore through actual SQLite DB."""

    def _make_db(self, tmp_path):
        """Create a UniversalRoomDatabase pointing at a temp directory."""
        from custom_components.universal_room_automation.database import UniversalRoomDatabase
        hass = MagicMock()
        hass.config.path = lambda *parts: os.path.join(str(tmp_path), *parts)
        return UniversalRoomDatabase(hass)

    def test_metric_baselines_table_exists(self, tmp_path):
        """metric_baselines table should exist after initialize."""
        db = self._make_db(tmp_path)
        _run(db.initialize())
        conn = sqlite3.connect(db.db_file)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='metric_baselines'"
        )
        assert cursor.fetchone() is not None
        conn.close()

    def test_baseline_insert_and_query(self, tmp_path):
        """Should be able to insert and query metric_baselines."""
        db = self._make_db(tmp_path)
        _run(db.initialize())

        conn = sqlite3.connect(db.db_file)
        conn.execute("""
            INSERT OR REPLACE INTO metric_baselines
            (coordinator_id, metric_name, scope, mean, variance, sample_count, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, ("energy", "circuit_power", "Kitchen", 100.0, 25.0, 200, "2026-03-12T10:00:00"))
        conn.commit()

        cursor = conn.execute(
            "SELECT mean, variance, sample_count FROM metric_baselines WHERE coordinator_id='energy'"
        )
        row = cursor.fetchone()
        conn.close()

        assert row is not None
        assert row[0] == 100.0
        assert row[1] == 25.0
        assert row[2] == 200


class TestCircuitZScoreEdgeCases:
    """Edge case tests for circuit z-score detection."""

    def _make_circuit_monitor(self):
        from custom_components.universal_room_automation.domain_coordinators.energy_circuits import (
            SPANCircuitMonitor, CircuitInfo,
        )
        hass = MagicMock()
        monitor = SPANCircuitMonitor(hass)
        return monitor, hass

    def test_advisory_z_score_no_anomaly(self):
        """Z-score between advisory (3.0) and alert (4.0) should not generate anomaly."""
        monitor, hass = self._make_circuit_monitor()
        from custom_components.universal_room_automation.domain_coordinators.energy_circuits import (
            CircuitInfo, CIRCUIT_MIN_SAMPLES,
        )

        monitor._circuits = {
            "sensor.span_panel_kitchen_power": CircuitInfo(
                "sensor.span_panel_kitchen_power", "Kitchen", "left"
            ),
        }
        monitor._discovered = True

        # Build baseline with known mean=100, low variance
        import random
        random.seed(42)
        for _ in range(CIRCUIT_MIN_SAMPLES + 5):
            power = random.gauss(100, 5)
            state_map = {"sensor.span_panel_kitchen_power": MagicMock(state=str(power))}
            hass.states.get = lambda eid, sm=state_map: sm.get(eid)
            monitor.check_anomalies()

        bl = monitor._power_baselines["sensor.span_panel_kitchen_power"]
        # Find a value that gives z ~3.5 (between advisory and alert)
        target_z = 3.5
        mildly_elevated = bl.mean + target_z * bl.std
        state_map = {"sensor.span_panel_kitchen_power": MagicMock(state=str(mildly_elevated))}
        hass.states.get = lambda eid: state_map.get(eid)
        anomalies = monitor.check_anomalies()

        consumption_anomalies = [a for a in anomalies if a["type"] == "consumption_anomaly"]
        assert len(consumption_anomalies) == 0  # Advisory only, no alert

    def test_zero_power_no_consumption_anomaly(self):
        """Zero power after learning should not trigger consumption_anomaly."""
        monitor, hass = self._make_circuit_monitor()
        from custom_components.universal_room_automation.domain_coordinators.energy_circuits import (
            CircuitInfo, CIRCUIT_MIN_SAMPLES,
        )

        monitor._circuits = {
            "sensor.span_panel_kitchen_power": CircuitInfo(
                "sensor.span_panel_kitchen_power", "Kitchen", "left"
            ),
        }
        monitor._discovered = True

        import random
        random.seed(42)
        for _ in range(CIRCUIT_MIN_SAMPLES + 5):
            power = random.gauss(100, 5)
            state_map = {"sensor.span_panel_kitchen_power": MagicMock(state=str(power))}
            hass.states.get = lambda eid, sm=state_map: sm.get(eid)
            monitor.check_anomalies()

        # Zero power — should not trigger consumption_anomaly (power > 0 guard)
        state_map = {"sensor.span_panel_kitchen_power": MagicMock(state="0")}
        hass.states.get = lambda eid: state_map.get(eid)
        anomalies = monitor.check_anomalies()
        consumption_anomalies = [a for a in anomalies if a["type"] == "consumption_anomaly"]
        assert len(consumption_anomalies) == 0

    def test_unavailable_state_skipped(self):
        """Unavailable circuit state should be skipped entirely."""
        monitor, hass = self._make_circuit_monitor()
        from custom_components.universal_room_automation.domain_coordinators.energy_circuits import CircuitInfo

        monitor._circuits = {
            "sensor.span_panel_kitchen_power": CircuitInfo(
                "sensor.span_panel_kitchen_power", "Kitchen", "left"
            ),
        }
        monitor._discovered = True

        state_map = {"sensor.span_panel_kitchen_power": MagicMock(state="unavailable")}
        hass.states.get = lambda eid: state_map.get(eid)
        anomalies = monitor.check_anomalies()
        assert len(anomalies) == 0
        # No baseline should be created for unavailable state
        assert len(monitor._power_baselines) == 0

    def test_restore_baselines_merges(self):
        """restore_baselines should merge, not replace existing baselines."""
        monitor, hass = self._make_circuit_monitor()
        from custom_components.universal_room_automation.domain_coordinators.coordinator_diagnostics import MetricBaseline

        # Pre-existing baseline
        existing = MetricBaseline(
            metric_name="circuit_power", coordinator_id="energy", scope="HVAC",
            mean=200.0, variance=100.0, sample_count=500,
        )
        monitor._power_baselines["sensor.span_panel_hvac_power"] = existing

        # Restore a different circuit's baseline
        restored = {
            "sensor.span_panel_kitchen_power": MetricBaseline(
                metric_name="circuit_power", coordinator_id="energy", scope="Kitchen",
                mean=100.0, variance=25.0, sample_count=200,
            )
        }
        monitor.restore_baselines(restored)

        # Both should be present
        assert len(monitor._power_baselines) == 2
        assert monitor._power_baselines["sensor.span_panel_hvac_power"].mean == 200.0
        assert monitor._power_baselines["sensor.span_panel_kitchen_power"].mean == 100.0

    def test_zscore_cooldown_dedup(self):
        """Repeated z-score alerts should be suppressed within cooldown window."""
        monitor, hass = self._make_circuit_monitor()
        from custom_components.universal_room_automation.domain_coordinators.energy_circuits import (
            CircuitInfo, CIRCUIT_MIN_SAMPLES, CIRCUIT_ZSCORE_COOLDOWN_S,
        )

        monitor._circuits = {
            "sensor.span_panel_kitchen_power": CircuitInfo(
                "sensor.span_panel_kitchen_power", "Kitchen", "left"
            ),
        }
        monitor._discovered = True

        import random
        random.seed(42)
        for _ in range(CIRCUIT_MIN_SAMPLES + 5):
            power = random.gauss(100, 5)
            state_map = {"sensor.span_panel_kitchen_power": MagicMock(state=str(power))}
            hass.states.get = lambda eid, sm=state_map: sm.get(eid)
            monitor.check_anomalies()

        # First extreme value — should trigger
        state_map = {"sensor.span_panel_kitchen_power": MagicMock(state="500")}
        hass.states.get = lambda eid: state_map.get(eid)
        anomalies1 = monitor.check_anomalies()
        assert any(a["type"] == "consumption_anomaly" for a in anomalies1)

        # Second extreme value immediately after — should be suppressed (cooldown)
        anomalies2 = monitor.check_anomalies()
        assert not any(a["type"] == "consumption_anomaly" for a in anomalies2)


class TestMaxSamplesDecay:
    """Test MetricBaseline max_samples recency weighting."""

    def test_max_samples_caps_influence(self):
        """With max_samples, old data should have less influence on mean."""
        from custom_components.universal_room_automation.domain_coordinators.coordinator_diagnostics import MetricBaseline

        # Baseline without cap
        bl_unlimited = MetricBaseline(
            metric_name="test", coordinator_id="test", scope="unit",
        )
        # Baseline with cap at 100
        bl_capped = MetricBaseline(
            metric_name="test", coordinator_id="test", scope="unit",
            max_samples=100,
        )

        # Feed 200 samples at 50, then 100 at 150
        for _ in range(200):
            bl_unlimited.update(50.0)
            bl_capped.update(50.0)
        for _ in range(100):
            bl_unlimited.update(150.0)
            bl_capped.update(150.0)

        # Capped baseline should have mean closer to 150 (recent data)
        # Unlimited baseline should have mean closer to 83.3 ((200*50 + 100*150)/300)
        assert bl_capped.mean > bl_unlimited.mean
        assert bl_capped.mean > 100  # Shifted toward recent values

    def test_max_samples_zero_means_unlimited(self):
        """max_samples=0 should behave like classic Welford's."""
        from custom_components.universal_room_automation.domain_coordinators.coordinator_diagnostics import MetricBaseline

        bl = MetricBaseline(
            metric_name="test", coordinator_id="test", scope="unit",
            max_samples=0,
        )
        values = [10, 20, 30, 40, 50]
        for v in values:
            bl.update(v)
        assert bl.sample_count == 5
        assert abs(bl.mean - 30.0) < 0.001

    def test_max_samples_preserved_in_dataclass(self):
        """max_samples should be a proper dataclass field."""
        from custom_components.universal_room_automation.domain_coordinators.coordinator_diagnostics import MetricBaseline

        bl = MetricBaseline(
            metric_name="test", coordinator_id="test", scope="unit",
            max_samples=500,
        )
        assert bl.max_samples == 500

    def test_max_samples_one_degenerates(self):
        """max_samples=1 should make variance always 0.0 and mean track last value."""
        from custom_components.universal_room_automation.domain_coordinators.coordinator_diagnostics import MetricBaseline

        bl = MetricBaseline(
            metric_name="test", coordinator_id="test", scope="unit",
            max_samples=1,
        )
        bl.update(10.0)
        bl.update(20.0)
        bl.update(30.0)
        # Mean should be last value (effective_n=1 always)
        assert abs(bl.mean - 30.0) < 0.001
        assert bl.variance == 0.0
        assert bl.sample_count == 3

    def test_negative_max_samples_treated_as_unlimited(self):
        """Negative max_samples should behave like 0 (unlimited)."""
        from custom_components.universal_room_automation.domain_coordinators.coordinator_diagnostics import MetricBaseline

        bl = MetricBaseline(
            metric_name="test", coordinator_id="test", scope="unit",
            max_samples=-5,
        )
        values = [10, 20, 30, 40, 50]
        for v in values:
            bl.update(v)
        assert bl.sample_count == 5
        assert abs(bl.mean - 30.0) < 0.001

    def test_variance_non_negative_with_max_samples(self):
        """Variance should never go negative even with aggressive max_samples cap."""
        from custom_components.universal_room_automation.domain_coordinators.coordinator_diagnostics import MetricBaseline

        bl = MetricBaseline(
            metric_name="test", coordinator_id="test", scope="unit",
            max_samples=10,
        )
        # Feed 100 values at 50, then abruptly shift to 200
        for _ in range(100):
            bl.update(50.0)
        for _ in range(50):
            bl.update(200.0)
        assert bl.variance >= 0.0


class TestCooldownExpiry:
    """Test that z-score cooldown expires after the configured period."""

    def _make_circuit_monitor(self):
        from custom_components.universal_room_automation.domain_coordinators.energy_circuits import (
            SPANCircuitMonitor, CircuitInfo,
        )
        hass = MagicMock()
        monitor = SPANCircuitMonitor(hass)
        return monitor, hass

    def test_cooldown_expiry_allows_re_alert(self):
        """After cooldown expires, the same circuit should alert again."""
        monitor, hass = self._make_circuit_monitor()
        from custom_components.universal_room_automation.domain_coordinators.energy_circuits import (
            CircuitInfo, CIRCUIT_MIN_SAMPLES, CIRCUIT_ZSCORE_COOLDOWN_S,
        )
        import time as time_mod

        monitor._circuits = {
            "sensor.span_panel_kitchen_power": CircuitInfo(
                "sensor.span_panel_kitchen_power", "Kitchen", "left"
            ),
        }
        monitor._discovered = True

        import random
        random.seed(42)
        for _ in range(CIRCUIT_MIN_SAMPLES + 5):
            power = random.gauss(100, 5)
            state_map = {"sensor.span_panel_kitchen_power": MagicMock(state=str(power))}
            hass.states.get = lambda eid, sm=state_map: sm.get(eid)
            monitor.check_anomalies()

        # First extreme — should trigger
        state_map = {"sensor.span_panel_kitchen_power": MagicMock(state="500")}
        hass.states.get = lambda eid: state_map.get(eid)

        base_time = time_mod.time()
        with patch("time.time") as mock_time_fn:
            mock_time_fn.return_value = base_time
            anomalies1 = monitor.check_anomalies()
            assert any(a["type"] == "consumption_anomaly" for a in anomalies1)

            # Immediately after — suppressed
            mock_time_fn.return_value = base_time + 10
            anomalies2 = monitor.check_anomalies()
            assert not any(a["type"] == "consumption_anomaly" for a in anomalies2)

            # After cooldown — should fire again
            mock_time_fn.return_value = base_time + CIRCUIT_ZSCORE_COOLDOWN_S + 1
            anomalies3 = monitor.check_anomalies()
            assert any(a["type"] == "consumption_anomaly" for a in anomalies3)


class TestNewBaselinesFeedAndRestore:
    """Test the 3 new EC baselines (soc, cost, forecast) and DB restore with max_samples."""

    def test_soc_at_peak_baseline_feed(self):
        """soc_at_peak_start baseline should accept float SOC values."""
        from custom_components.universal_room_automation.domain_coordinators.coordinator_diagnostics import MetricBaseline

        bl = MetricBaseline(
            metric_name="soc_at_peak_start", coordinator_id="energy",
            scope="battery", max_samples=365,
        )
        for soc in [85.0, 90.0, 88.0, 92.0, 87.0]:
            bl.update(soc)
        assert bl.sample_count == 5
        assert 85.0 < bl.mean < 92.0
        assert bl.max_samples == 365

    def test_daily_import_cost_baseline_feed(self):
        """daily_import_cost baseline should track positive cost values."""
        from custom_components.universal_room_automation.domain_coordinators.coordinator_diagnostics import MetricBaseline

        bl = MetricBaseline(
            metric_name="daily_import_cost", coordinator_id="energy",
            scope="billing", max_samples=365,
        )
        costs = [3.50, 4.20, 2.80, 5.10, 3.90]
        for c in costs:
            bl.update(c)
        assert bl.sample_count == 5
        expected_mean = sum(costs) / len(costs)
        assert abs(bl.mean - expected_mean) < 0.01

    def test_solar_forecast_error_baseline_feed(self):
        """solar_forecast_error_pct baseline should track absolute error percentages."""
        from custom_components.universal_room_automation.domain_coordinators.coordinator_diagnostics import MetricBaseline

        bl = MetricBaseline(
            metric_name="solar_forecast_error_pct", coordinator_id="energy",
            scope="forecast", max_samples=365,
        )
        errors = [5.2, 8.1, 3.0, 12.5, 6.7]
        for e in errors:
            bl.update(abs(e))
        assert bl.sample_count == 5
        assert bl.mean > 0

    def test_restore_sets_max_samples_correctly(self, tmp_path):
        """Restoring from DB should set max_samples even though DB doesn't store it."""
        import sqlite3 as sql3

        db_dir = os.path.join(str(tmp_path), "universal_room_automation", "data")
        os.makedirs(db_dir, exist_ok=True)
        db_path = os.path.join(db_dir, "universal_room_automation.db")

        conn = sql3.connect(db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS metric_baselines (
                coordinator_id TEXT,
                metric_name TEXT,
                scope TEXT,
                mean REAL,
                variance REAL,
                sample_count INTEGER,
                last_updated TEXT,
                PRIMARY KEY (coordinator_id, metric_name, scope)
            )
        """)
        # Insert baselines like pre-v3.13.3 (no max_samples column)
        rows = [
            ("energy", "peak_import_kw", "load_shedding", 5.0, 1.0, 500, "2026-03-12"),
            ("energy", "soc_at_peak_start", "battery", 88.0, 10.0, 100, "2026-03-12"),
            ("energy", "daily_import_cost", "billing", 4.0, 2.0, 90, "2026-03-12"),
            ("energy", "solar_forecast_error_pct", "forecast", 7.0, 5.0, 60, "2026-03-12"),
        ]
        for row in rows:
            conn.execute("""
                INSERT INTO metric_baselines
                (coordinator_id, metric_name, scope, mean, variance, sample_count, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, row)
        conn.commit()
        conn.close()

        # Simulate _restore_energy_baselines logic
        from custom_components.universal_room_automation.domain_coordinators.coordinator_diagnostics import MetricBaseline
        import sqlite3 as sql3b

        conn2 = sql3b.connect(db_path)
        conn2.row_factory = sql3b.Row
        cursor = conn2.execute(
            "SELECT metric_name, scope, mean, variance, sample_count, last_updated "
            "FROM metric_baselines WHERE coordinator_id = 'energy'"
        )
        restored = {}
        for row in cursor:
            bl = MetricBaseline(
                metric_name=row["metric_name"],
                coordinator_id="energy",
                scope=row["scope"],
                mean=row["mean"],
                variance=row["variance"],
                sample_count=row["sample_count"],
                last_updated=row["last_updated"],
            )
            if row["metric_name"] == "peak_import_kw":
                bl.max_samples = 1500
            elif row["metric_name"] == "soc_at_peak_start":
                bl.max_samples = 365
            elif row["metric_name"] == "daily_import_cost":
                bl.max_samples = 365
            elif row["metric_name"] == "solar_forecast_error_pct":
                bl.max_samples = 365
            restored[row["metric_name"]] = bl
        conn2.close()

        assert restored["peak_import_kw"].max_samples == 1500
        assert restored["peak_import_kw"].mean == 5.0
        assert restored["soc_at_peak_start"].max_samples == 365
        assert restored["daily_import_cost"].max_samples == 365
        assert restored["solar_forecast_error_pct"].max_samples == 365
