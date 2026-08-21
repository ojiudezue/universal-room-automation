"""RESTART-SAFETY-DOCTRINE-1 tranche 1 tests.

Covers:
  F1/F2 — safety.py and manager.py now call save_baselines on teardown.
  F3/F11/F13/F14 — DailyCounter primitive: rollover semantics, restart
      RESET behaviour, and forced-declaration invariant.
  Wire-in anchors — a mutation drill that neuters the save_baselines
      CALL SITE (not just the helper) must fail a specific test.

Run: PYTHONPATH=quality python3 -m pytest quality/tests/test_restart_safety_doctrine_1.py -v
"""
from __future__ import annotations

import ast
import pathlib
import re
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

# Reuse the HA stubs already installed for the safety-coordinator tests.
from test_safety_coordinator import *  # noqa: F401,F403 — sets sys.modules stubs

from custom_components.universal_room_automation.domain_coordinators.coordinator_diagnostics import (  # noqa: E402
    DailyCounter,
)

ROOT = pathlib.Path(__file__).parents[2]
DC_DIR = ROOT / "custom_components" / "universal_room_automation" / "domain_coordinators"


# ---------------------------------------------------------------------------
# DailyCounter — primitive semantics
# ---------------------------------------------------------------------------

class TestDailyCounter:
    def test_construction_requires_reason_when_reset(self):
        with pytest.raises(ValueError, match="UNDECLARED"):
            DailyCounter(name="test.x", persist=False, reason="")

    def test_persist_true_not_implemented(self):
        with pytest.raises(NotImplementedError, match="persist=True"):
            DailyCounter(name="test.x", persist=True, reason="unused")

    def test_increment_and_value(self):
        c = DailyCounter(name="test.x", persist=False, reason="display only")
        assert c.value == 0
        c.increment()
        c.increment(4)
        assert c.value == 5
        assert int(c) == 5

    def test_rollover_at_date_change(self):
        c = DailyCounter(name="test.x", persist=False, reason="display only")
        # Seed at a fake "today" via direct state manipulation so subsequent
        # increments do not silently roll to the real wall-clock date.
        c._date = "2026-08-20"
        c._value = 3
        # Now force a rollover to a NEW date.
        c.rollover_if_needed("2026-08-21")
        assert c._value == 0, "rollover to a new date must zero the counter"
        assert c._date == "2026-08-21"

    def test_lazy_rollover_via_value(self):
        c = DailyCounter(name="test.x", persist=False, reason="display only")
        # Simulate stale state as if from yesterday.
        c._date = "1999-01-01"
        c._value = 99
        # value property triggers rollover_if_needed against today's real date
        v = c.value
        assert v == 0, f"stale-date access must roll over to 0, got {v}"

    def test_simulated_restart_is_RESET(self):
        """The doctrine says: RESET is the correct behaviour for this
        primitive on restart. A "restart" is a fresh construction — the
        primitive MUST come up at value=0 with no persistence path."""
        c = DailyCounter(name="test.x", persist=False, reason="display")
        c.increment(10)
        assert c.value == 10
        # Simulate restart: drop the instance, build a new one.
        c2 = DailyCounter(name="test.x", persist=False, reason="display")
        assert c2.value == 0

    def test_reason_is_stored_and_readable(self):
        c = DailyCounter(name="test.x", persist=False, reason="metric-only")
        assert c.reason == "metric-only"
        assert c.name == "test.x"


# ---------------------------------------------------------------------------
# F1/F2 — source-level wire-in verification for save_baselines call sites
# ---------------------------------------------------------------------------

SAFETY_SRC = (DC_DIR / "safety.py").read_text()
MANAGER_SRC = (DC_DIR / "manager.py").read_text()


def _find_teardown_body(src: str, method_name: str) -> str:
    """Extract the body-text of a named async method from a source file."""
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == method_name:
            return ast.get_source_segment(src, node) or ""
    return ""


class TestF1SafetySaveBaselinesWireIn:
    """F1: safety.py async_teardown MUST call self.anomaly_detector.save_baselines."""

    def test_teardown_contains_save_baselines_call(self):
        body = _find_teardown_body(SAFETY_SRC, "async_teardown")
        assert body, "safety.py: async_teardown not found"
        assert "self.anomaly_detector.save_baselines()" in body, (
            "safety.py async_teardown must call self.anomaly_detector.save_baselines() "
            "(RESTART-SAFETY-DOCTRINE-1 F1). Mutation drill anchor."
        )

    def test_teardown_guards_save_baselines_in_try(self):
        body = _find_teardown_body(SAFETY_SRC, "async_teardown")
        # The call must appear inside a try/except, matching the HVAC/security/music pattern.
        assert re.search(
            r"try:\s*[^{}]*await self\.anomaly_detector\.save_baselines\(\)",
            body,
            re.DOTALL,
        ), "safety.py save_baselines call must be try/except-guarded"


class TestF2ManagerSaveBaselinesWireIn:
    """F2: manager.py async_stop MUST call self._setup_anomaly_detector.save_baselines."""

    def test_async_stop_contains_save_baselines_call(self):
        body = _find_teardown_body(MANAGER_SRC, "async_stop")
        assert body, "manager.py: async_stop not found"
        assert "self._setup_anomaly_detector.save_baselines()" in body, (
            "manager.py async_stop must call self._setup_anomaly_detector.save_baselines() "
            "(RESTART-SAFETY-DOCTRINE-1 F2). Mutation drill anchor."
        )


# ---------------------------------------------------------------------------
# Behavioural: save -> new instance -> load -> baselines present
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_anomaly_detector_baselines_survive_simulated_restart(tmp_path):
    """Drive the REAL save_baselines / load_baselines path against an
    in-memory-ish AnomalyDetector, then a fresh instance loads the same rows.

    This exercises coordinator_diagnostics.AnomalyDetector.save_baselines and
    .load_baselines end-to-end. If the save path is neutered (mutation drill
    target), this test fails because the second instance sees 0 baselines.
    """
    from custom_components.universal_room_automation.domain_coordinators.coordinator_diagnostics import (
        AnomalyDetector,
        MetricBaseline,
    )

    # Fake shared "DB": a dict backing INSERT OR REPLACE / SELECT semantics.
    stored_rows: dict = {}

    class _FakeCursor:
        def __init__(self, rows=None):
            self._rows = rows or []

        async def fetchone(self):
            return self._rows[0] if self._rows else None

        async def fetchall(self):
            return list(self._rows)

    class _FakeDB:
        row_factory = None

        async def execute(self, sql, params=()):
            if sql.strip().upper().startswith("INSERT OR REPLACE INTO METRIC_BASELINES"):
                (cid, metric, scope, mean, var, count, ts) = params
                stored_rows[(cid, metric, scope)] = dict(
                    metric_name=metric, scope=scope, mean=mean,
                    variance=var, sample_count=count, last_updated=ts,
                    coordinator_id=cid,
                )
                return _FakeCursor()
            if sql.strip().upper().startswith("SELECT METRIC_NAME"):
                (cid,) = params
                rows = [r for k, r in stored_rows.items() if k[0] == cid]
                return _FakeCursor(rows)
            if sql.strip().upper().startswith("DELETE FROM METRIC_BASELINES"):
                return _FakeCursor()
            return _FakeCursor()

        async def commit(self):
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

    class _FakeDatabase:
        def _db(self):
            return _FakeDB()

    # First instance: record baselines, save.
    det1 = AnomalyDetector(
        hass=MagicMock(),
        coordinator_id="safety_test",
        metric_names=["hazard_rate"],
        minimum_samples=1,
    )
    det1._database_override = _FakeDatabase()  # not the real API; patch _database
    # Patch _database property via monkeypatch on the instance's class in scope:
    det1.__class__._database = property(lambda s: _FakeDatabase())
    b = MetricBaseline(
        metric_name="hazard_rate",
        coordinator_id="safety_test",
        scope="global",
        mean=1.5, variance=0.5, sample_count=12,
    )
    det1._baselines[("hazard_rate", "global")] = b
    await det1.save_baselines()
    assert stored_rows, "save_baselines must have written a row"

    # Second instance: load and confirm the baseline came back.
    det2 = AnomalyDetector(
        hass=MagicMock(),
        coordinator_id="safety_test",
        metric_names=["hazard_rate"],
        minimum_samples=1,
    )
    det2.__class__._database = property(lambda s: _FakeDatabase())
    await det2.load_baselines()
    key = ("hazard_rate", "global")
    assert key in det2._baselines, (
        "After simulated restart, baseline should be re-hydrated from the "
        "shared store — this is what F1/F2 wire in for safety + manager."
    )
    assert det2._baselines[key].mean == 1.5
    assert det2._baselines[key].sample_count == 12
