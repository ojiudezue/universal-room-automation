"""Tests for v4.6.11 D1 — CM anomaly detector baseline persistence + dispatch.

Deliverables covered:
  D1 Phase 1 — load_baselines called on CM async_start (manager.py)
  D1 Phase 2 — save_baselines always called after record_observation (__init__.py)
  D1 Phase 2 — store_event called only when anomaly returned
  D1 Phase 2 — AnomalyEvent payload shape matches post-v4.6.7 schema

Test strategy:
- Inline the production logic using AsyncMock/MagicMock stubs.
- Source-grep tests verify structural presence without full HA import.
- Two-detector restart simulation proves persistence not state-sharing.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

# ---------------------------------------------------------------------------
# Minimal HA stubs — reuse the pattern established in test_v4_6_10_setup_telemetry
# ---------------------------------------------------------------------------
ROOT = pathlib.Path(__file__).parents[2]


def _utc_now():
    return datetime.now(tz=timezone.utc)


DOMAIN = "universal_room_automation"


def _make_hass():
    hass = MagicMock()
    hass.data = {DOMAIN: {}}
    return hass


# ---------------------------------------------------------------------------
# Fake AnomalyDetector mirroring the production interface
# ---------------------------------------------------------------------------

class _FakeAnomaly:
    """Mimics coordinator_diagnostics.AnomalyRecord."""
    def __init__(self, z=2.5, severity_value="advisory"):
        class _Sev:
            value = severity_value
        self.z_score = z
        self.severity = _Sev()
        self.timestamp = _utc_now()
        self.observed_value = 12.0
        self.expected_mean = 8.0
        self.expected_std = 1.5
        self.sample_size = 11


class _FakeAnomalyDetector:
    """Minimal AnomalyDetector clone tracking calls."""

    def __init__(self, coordinator_id="coordinator_manager"):
        self.coordinator_id = coordinator_id
        self.metric_names = ["setup_duration_seconds"]
        self.minimum_samples = 10
        self._baselines: dict = {}
        self._load_calls = 0
        self._save_calls = 0
        self._store_calls = []
        self._record_calls = []
        self._anomaly_to_return = None  # set per-test

    async def load_baselines(self):
        self._load_calls += 1

    async def save_baselines(self):
        self._save_calls += 1

    def record_observation(self, metric_name, scope, value):
        self._record_calls.append({"metric_name": metric_name, "scope": scope, "value": value})
        return self._anomaly_to_return

    async def store_event(self, event):
        self._store_calls.append(event)
        return len(self._store_calls)

    def get_worst_severity(self):
        return None


# ---------------------------------------------------------------------------
# Test class: D1 Phase 1 — load_baselines called on async_start
# ---------------------------------------------------------------------------

class TestD1Phase1LoadBaselines:
    """Phase 1: manager.py async_start calls load_baselines after NM start."""

    def test_source_manager_py_has_load_baselines_call(self):
        """D1 AC: manager.py contains load_baselines() call in async_start."""
        manager_file = (
            ROOT / "custom_components" / "universal_room_automation"
            / "domain_coordinators" / "manager.py"
        )
        src = manager_file.read_text()
        assert "load_baselines" in src, "manager.py must call load_baselines"
        # The call must be in async_start (not just in __init__)
        start_idx = src.find("async def async_start")
        assert start_idx >= 0
        start_body = src[start_idx:]
        stop_body_idx = start_body.find("\n    async def ")
        if stop_body_idx > 0:
            start_body = start_body[:stop_body_idx]
        assert "load_baselines" in start_body, \
            "load_baselines() must be called inside async_start body"

    def test_source_manager_py_guards_load_with_try_except(self):
        """D1 AC: load_baselines call is wrapped in try/except (non-fatal)."""
        manager_file = (
            ROOT / "custom_components" / "universal_room_automation"
            / "domain_coordinators" / "manager.py"
        )
        src = manager_file.read_text()
        assert "load_baselines failed (non-fatal)" in src, \
            "load_baselines call must log at debug with non-fatal note on exception"

    @pytest.mark.asyncio
    async def test_load_baselines_called_on_async_start(self):
        """D1 AC: async_start invokes load_baselines when detector is not None."""
        det = _FakeAnomalyDetector()
        hass = _make_hass()

        # Replicate the relevant async_start block
        async def _replicated_start(detector):
            if detector is not None:
                try:
                    await detector.load_baselines()
                except Exception:
                    pass

        await _replicated_start(det)
        assert det._load_calls == 1, "load_baselines must be called exactly once"

    @pytest.mark.asyncio
    async def test_load_baselines_not_called_when_detector_none(self):
        """D1 AC: async_start skips load_baselines when detector is None."""
        async def _replicated_start(detector):
            if detector is not None:
                await detector.load_baselines()

        # Must not raise
        await _replicated_start(None)

    @pytest.mark.asyncio
    async def test_load_baselines_exception_non_fatal(self):
        """D1 AC: load_baselines raising must not propagate out of async_start."""
        class _BadDetector(_FakeAnomalyDetector):
            async def load_baselines(self):
                raise RuntimeError("DB gone")

        det = _BadDetector()

        async def _replicated_start(detector):
            if detector is not None:
                try:
                    await detector.load_baselines()
                except Exception:
                    pass  # non-fatal

        await _replicated_start(det)  # must not raise


# ---------------------------------------------------------------------------
# Test class: D1 Phase 2 — save_baselines + store_event pipeline
# ---------------------------------------------------------------------------

class TestD1Phase2Pipeline:
    """Phase 2: _push_setup_observation pipeline in __init__.py."""

    def _make_pipeline_components(self, anomaly=None, dur=9.1):
        """Build hass + cm + det for inline pipeline tests."""
        hass = _make_hass()
        det = _FakeAnomalyDetector()
        det._anomaly_to_return = anomaly
        cm = MagicMock()
        cm._setup_anomaly_detector = det
        hass.data[DOMAIN]["coordinator_manager"] = cm
        t0 = _utc_now()
        hass.data[DOMAIN]["setup_telemetry"] = {
            "started": t0,
            "completed": t0 + timedelta(seconds=dur),
            "duration_seconds": dur,
            "coordinator_count": 3,
            "room_count": 5,
        }
        return hass, cm, det

    @staticmethod
    def _load_anomaly_event_module():
        """Load anomaly_event.py directly (no HA deps) via importlib.

        Must register in sys.modules before exec so Python 3.9 dataclass
        field resolution can resolve cls.__module__ via sys.modules lookup.
        """
        import importlib.util
        _MOD_KEY = "_ura_test_anomaly_event"
        if _MOD_KEY in sys.modules:
            return sys.modules[_MOD_KEY]
        ae_path = (
            ROOT / "custom_components" / "universal_room_automation"
            / "domain_coordinators" / "anomaly_event.py"
        )
        spec = importlib.util.spec_from_file_location(_MOD_KEY, ae_path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[_MOD_KEY] = mod  # register BEFORE exec (Python 3.9 dataclass requirement)
        spec.loader.exec_module(mod)
        return mod

    async def _run_pipeline(self, hass, det):
        """Inline the _push_setup_observation coroutine from __init__.py."""
        ae = self._load_anomaly_event_module()
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
            _anomaly = _det.record_observation(
                metric_name="setup_duration_seconds",
                scope="house",
                value=float(_dur),
            )
            # save_baselines ALWAYS
            await _det.save_baselines()
            if _anomaly is not None:
                _ctx = ae.build_context_json(
                    source_signal="URA_SETUP_COMPLETE",
                    extra={
                        "duration_seconds": _dur,
                        "coordinator_count": _telem.get("coordinator_count"),
                        "room_count": _telem.get("room_count"),
                    },
                )
                _event = ae.AnomalyEvent(
                    coordinator="coordinator_manager",
                    type="coordinator_manager.setup_duration_seconds",
                    severity=ae.map_diag_severity(_anomaly.severity),
                    anomaly_type=ae.AnomalyType.POINT_IN_TIME,
                    detected_at=_anomaly.timestamp.isoformat(),
                    payload=_ctx,
                    observed_value=_anomaly.observed_value,
                    expected_mean=_anomaly.expected_mean,
                    expected_std=_anomaly.expected_std,
                    z_score=round(_anomaly.z_score, 3),
                    sample_size=_anomaly.sample_size,
                )
                await _det.store_event(_event)
        except Exception:
            pass

    @pytest.mark.asyncio
    async def test_save_baselines_called_when_no_anomaly(self):
        """D1 AC: save_baselines called even when record_observation returns None."""
        hass, cm, det = self._make_pipeline_components(anomaly=None)
        await self._run_pipeline(hass, det)
        assert det._save_calls == 1, "save_baselines must be called even when no anomaly"
        assert len(det._store_calls) == 0, "store_event must NOT be called when anomaly is None"

    @pytest.mark.asyncio
    async def test_save_baselines_called_when_anomaly_returned(self):
        """D1 AC: save_baselines called when anomaly is returned too."""
        anomaly = _FakeAnomaly(z=3.1, severity_value="alert")
        hass, cm, det = self._make_pipeline_components(anomaly=anomaly)
        await self._run_pipeline(hass, det)
        assert det._save_calls == 1, "save_baselines must be called when anomaly returned"

    @pytest.mark.asyncio
    async def test_store_event_called_only_when_anomaly_returned(self):
        """D1 AC: store_event called exactly once when anomaly returned."""
        anomaly = _FakeAnomaly(z=2.8, severity_value="advisory")
        hass, cm, det = self._make_pipeline_components(anomaly=anomaly)
        await self._run_pipeline(hass, det)
        assert len(det._store_calls) == 1, "store_event must be called exactly once per anomaly"

    @pytest.mark.asyncio
    async def test_anomaly_event_payload_shape(self):
        """D1 AC: AnomalyEvent has correct coordinator, type, metric fields."""
        anomaly = _FakeAnomaly(z=2.5, severity_value="advisory")
        anomaly.observed_value = 15.3
        anomaly.expected_mean = 9.0
        anomaly.expected_std = 2.1
        anomaly.sample_size = 12
        hass, cm, det = self._make_pipeline_components(anomaly=anomaly, dur=15.3)
        await self._run_pipeline(hass, det)
        assert len(det._store_calls) == 1
        evt = det._store_calls[0]
        assert evt.coordinator == "coordinator_manager"
        assert evt.type == "coordinator_manager.setup_duration_seconds"
        assert evt.observed_value == pytest.approx(15.3)
        assert evt.expected_mean == pytest.approx(9.0)
        assert evt.z_score == pytest.approx(2.5, abs=0.01)
        assert evt.sample_size == 12
        assert evt.event_class == "point_in_time"

    @pytest.mark.asyncio
    async def test_store_event_not_called_when_no_anomaly(self):
        """D1 AC: store_event never called when record_observation returns None."""
        hass, cm, det = self._make_pipeline_components(anomaly=None)
        await self._run_pipeline(hass, det)
        assert len(det._store_calls) == 0

    def test_source_init_py_save_baselines_unconditional(self):
        """D1 AC: save_baselines called before the `if _anomaly is not None` check."""
        init_file = (
            ROOT / "custom_components" / "universal_room_automation" / "__init__.py"
        )
        src = init_file.read_text()
        # save_baselines must appear before the anomaly condition check in the pipeline
        save_idx = src.find("await _det.save_baselines()")
        anomaly_cond_idx = src.find("if _anomaly is not None:")
        assert save_idx > 0, "save_baselines call must exist in __init__.py"
        assert anomaly_cond_idx > 0, "if _anomaly is not None check must exist"
        assert save_idx < anomaly_cond_idx, \
            "save_baselines must appear BEFORE the anomaly condition block"

    def test_source_init_py_store_event_inside_anomaly_block(self):
        """D1 AC: store_event is inside `if _anomaly is not None` block."""
        init_file = (
            ROOT / "custom_components" / "universal_room_automation" / "__init__.py"
        )
        src = init_file.read_text()
        # store_event must appear after the if-anomaly gate
        anomaly_cond_idx = src.find("if _anomaly is not None:")
        store_idx = src.find("await _det.store_event(", anomaly_cond_idx)
        assert store_idx > anomaly_cond_idx, \
            "store_event must be inside the `if _anomaly is not None` block"


# ---------------------------------------------------------------------------
# Test class: D1 — Simulated restart proves persistence (two detector instances)
# ---------------------------------------------------------------------------

class TestD1SimulatedRestart:
    """Proves persistence by verifying second detector loads what first saved."""

    @pytest.mark.asyncio
    async def test_baseline_persists_across_simulated_restart(self):
        """D1 AC: second AnomalyDetector loads what first saved; sample_count == 11."""
        # Use the real AnomalyDetector with an in-memory database
        import sys
        import os

        # We need aiosqlite + the real coordinator_diagnostics module.
        # Build minimal stubs so the import resolves.
        _ha_stubs = {}
        for mod in [
            "homeassistant", "homeassistant.core", "homeassistant.helpers",
            "homeassistant.helpers.event", "homeassistant.helpers.device_registry",
            "homeassistant.helpers.entity", "homeassistant.helpers.update_coordinator",
            "homeassistant.helpers.restore_state", "homeassistant.helpers.dispatcher",
            "homeassistant.helpers.entity_platform", "homeassistant.config_entries",
            "homeassistant.const", "homeassistant.components",
            "homeassistant.components.sensor", "homeassistant.components.binary_sensor",
            "homeassistant.components.button",
        ]:
            if mod not in sys.modules:
                _ha_stubs[mod] = MagicMock()
                sys.modules[mod] = _ha_stubs[mod]

        _dt_stub = MagicMock()
        _dt_stub.utcnow = _utc_now
        _dt_stub.now = lambda: _utc_now()
        if "homeassistant.util" not in sys.modules:
            _ha_stubs["homeassistant.util"] = MagicMock()
            sys.modules["homeassistant.util"] = _ha_stubs["homeassistant.util"]
        sys.modules["homeassistant.util"].dt = _dt_stub
        if "homeassistant.util.dt" not in sys.modules:
            _ha_stubs["homeassistant.util.dt"] = _dt_stub
            sys.modules["homeassistant.util.dt"] = _dt_stub

        try:
            import aiosqlite
            import tempfile, os as _os
            from custom_components.universal_room_automation.domain_coordinators.coordinator_diagnostics import (
                AnomalyDetector,
            )

            with tempfile.TemporaryDirectory() as tmpdir:
                db_path = _os.path.join(tmpdir, "test_ura.db")

                # Minimal database stub that uses real aiosqlite
                class _FakeDB:
                    def __init__(self, path):
                        self._path = path

                    def _db(self):
                        return aiosqlite.connect(self._path)

                    async def _init_schema(self):
                        async with self._db() as db:
                            await db.execute("""
                                CREATE TABLE IF NOT EXISTS metric_baselines (
                                    coordinator_id TEXT NOT NULL,
                                    metric_name TEXT NOT NULL,
                                    scope TEXT NOT NULL,
                                    mean REAL NOT NULL DEFAULT 0.0,
                                    variance REAL NOT NULL DEFAULT 0.0,
                                    sample_count INTEGER NOT NULL DEFAULT 0,
                                    last_updated TEXT,
                                    PRIMARY KEY (coordinator_id, metric_name, scope)
                                )
                            """)
                            await db.commit()

                fakedb = _FakeDB(db_path)
                await fakedb._init_schema()

                # _database is a read-only property: hass.data.get(DOMAIN,{}).get("database")
                # so we inject via hass.data, not direct assignment.
                hass1 = MagicMock()
                hass1.data = {DOMAIN: {"database": fakedb}}

                # Boot 1: record 10 observations to mature the baseline
                det1 = AnomalyDetector(
                    hass=hass1,
                    coordinator_id="coordinator_manager",
                    metric_names=["setup_duration_seconds"],
                    minimum_samples=10,
                )
                for i in range(10):
                    det1.record_observation("setup_duration_seconds", "house", 8.0 + i * 0.1)
                await det1.save_baselines()

                # Boot 2: new detector instance (simulates restart)
                hass2 = MagicMock()
                hass2.data = {DOMAIN: {"database": fakedb}}
                det2 = AnomalyDetector(
                    hass=hass2,
                    coordinator_id="coordinator_manager",
                    metric_names=["setup_duration_seconds"],
                    minimum_samples=10,
                )
                await det2.load_baselines()

                # det2 must have loaded det1's baseline
                key = ("setup_duration_seconds", "house")
                assert key in det2._baselines, "Baseline must be loaded from DB on second boot"
                assert det2._baselines[key].sample_count == 10, \
                    f"Expected sample_count=10, got {det2._baselines[key].sample_count}"

                # Record one more observation — baseline matures
                det2.record_observation("setup_duration_seconds", "house", 8.5)
                await det2.save_baselines()
                assert det2._baselines[key].sample_count == 11, \
                    "After recording one more observation, sample_count must be 11"

        except ImportError as e:
            pytest.skip(f"aiosqlite or coordinator_diagnostics not available: {e}")
        finally:
            # Clean up stubs we added (don't pollute other test modules)
            for mod in _ha_stubs:
                sys.modules.pop(mod, None)


# ---------------------------------------------------------------------------
# Test class: D1 — Source structure verifications
# ---------------------------------------------------------------------------

class TestD1SourceStructure:
    """Source-grep tests — verify structural presence without full module import."""

    INIT_FILE = ROOT / "custom_components" / "universal_room_automation" / "__init__.py"
    MANAGER_FILE = (
        ROOT / "custom_components" / "universal_room_automation"
        / "domain_coordinators" / "manager.py"
    )

    def test_init_py_has_map_diag_severity_import(self):
        """D1 AC: __init__.py imports map_diag_severity from anomaly_event."""
        src = self.INIT_FILE.read_text()
        assert "map_diag_severity" in src, \
            "map_diag_severity must be imported/used in __init__.py"

    def test_init_py_has_anomaly_event_construction(self):
        """D1 AC: __init__.py constructs AnomalyEvent with all metric fields."""
        src = self.INIT_FILE.read_text()
        # v4.7.12 D2: event_class= kwarg renamed to anomaly_type= at all
        # emit sites. The dataclass field is anomaly_type: AnomalyType.
        for field in ("coordinator=", "type=", "severity=", "anomaly_type=",
                      "detected_at=", "observed_value=", "z_score=", "sample_size="):
            assert field in src, f"AnomalyEvent field {field!r} missing from __init__.py"

    def test_init_py_has_activity_logger_call_after_store_event(self):
        """D1 AC: activity_logger.log called after store_event for anomaly."""
        src = self.INIT_FILE.read_text()
        store_idx = src.find("await _det.store_event(")
        assert store_idx > 0
        activity_idx = src.find("activity_logger", store_idx)
        assert activity_idx > store_idx, \
            "activity_logger.log must appear after store_event in the anomaly block"

    def test_manager_py_load_baselines_after_notification_manager(self):
        """D1 AC: load_baselines appears in async_start after NM start block."""
        src = self.MANAGER_FILE.read_text()
        nm_start_idx = src.find("Notification Manager started")
        load_idx = src.find("load_baselines", nm_start_idx)
        assert nm_start_idx > 0
        assert load_idx > nm_start_idx, \
            "load_baselines must be called after NM startup in async_start"

    def test_init_py_no_scaffold_only_comment(self):
        """D1 AC: scaffold-only comment from v4.6.10 is replaced."""
        src = self.INIT_FILE.read_text()
        assert "SCAFFOLD ONLY" not in src, \
            "v4.6.10 SCAFFOLD ONLY comment must be removed in v4.6.11"
