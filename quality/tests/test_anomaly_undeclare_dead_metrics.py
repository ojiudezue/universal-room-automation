"""ANOMALY-METRIC-DISPOSITION-1 slices (a)+(b) — undeclare two dead metrics.

(a) HVAC `egress_pause_frequency` and (b) Security `entry_anomaly_score` were
declared with no producer, which kept both anomaly sensors blind (`partial`)
for good. They are removed from the coordinators' METRICS lists and from the
suppressed / unwired sets; the persisted `metric_baselines` row each one left
behind is dropped by the REAL orphan prune in `AnomalyDetector.load_baselines`.

The prune tests build a real AnomalyDetector from the coordinator's own
declared METRICS constant (the value its ctor site passes — the ctor wiring is
pinned separately by test_anomaly_coverage_ctor_wiring.py) over a real
UniversalRoomDatabase, seed a row for the removed metric plus one for a kept
metric, and run load_baselines.

Drill: re-add a removed name to its METRICS list -> the matching
`test_*_declared_metrics_*` and `test_*_prune_*` tests go RED.
"""

from __future__ import annotations

import asyncio
import importlib
import sqlite3
import sys
from unittest.mock import MagicMock

import pytest

# HA mock prelude + the hermetic (database, coordinator_diagnostics) pair
# fixture (autouse here because it is bound in this module's namespace;
# it restores sys.modules on teardown).
from test_db_write_worker_boot_race import ura_db  # noqa: F401,E402
from test_unload_symmetry_shutdown_db_hygiene import (  # noqa: E402
    _hermetic_db_modules,  # noqa: F401
    _make_db,
)

_P = "custom_components.universal_room_automation.domain_coordinators."


def _hvac_const():
    return importlib.import_module(_P + "hvac_const")


def _security():
    return importlib.import_module(_P + "security")


# ---------------------------------------------------------------------------
# Declarations
# ---------------------------------------------------------------------------


def test_hvac_declared_metrics_exclude_egress_pause_frequency():
    hc = _hvac_const()
    assert "egress_pause_frequency" not in hc.HVAC_METRICS
    assert "egress_pause_frequency" not in hc.HVAC_SUPPRESSED_FROM_PERSISTENCE
    assert hc.HVAC_UNWIRED_METRICS == frozenset({"comfort_deviation_hours"})
    # The other four metrics are untouched.
    assert list(hc.HVAC_METRICS) == [
        "zone_call_frequency",
        "short_cycle_rate",
        "override_frequency",
        "comfort_deviation_hours",
    ]


def test_security_declared_metrics_exclude_entry_anomaly_score():
    sec = _security()
    assert sec.SECURITY_METRICS == ["alert_trigger_frequency"]
    # Kept defined (ctor + meta-tests import them), now empty.
    assert sec.SECURITY_SUPPRESSED_FROM_PERSISTENCE == frozenset()
    assert sec.SECURITY_UNWIRED_METRICS == frozenset()


# ---------------------------------------------------------------------------
# Orphan prune — real detector, real DB
# ---------------------------------------------------------------------------


def _count(db_file, coord, metric):
    conn = sqlite3.connect(db_file)
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM metric_baselines "
            "WHERE coordinator_id=? AND metric_name=?",
            (coord, metric),
        ).fetchone()[0]
    finally:
        conn.close()


def _run_prune(tmp_path, *, coord_id, metric_names, suppressed, unwired,
               removed, kept):
    cdiag = sys.modules[_P + "coordinator_diagnostics"]
    db = _make_db(str(tmp_path), is_stopping=False)
    hass = MagicMock()
    hass.data = {cdiag.DOMAIN: {"database": db}}
    det = cdiag.AnomalyDetector(
        hass,
        coord_id,
        metric_names,
        suppressed_metric_names=suppressed,
        unwired_metric_names=unwired,
    )

    async def _scenario():
        await db.initialize()
        await db.start_write_worker()
        try:
            async with db._db() as conn:
                for metric, n in ((removed, 0), (kept, 40)):
                    await conn.execute(
                        "INSERT OR REPLACE INTO metric_baselines "
                        "(coordinator_id, metric_name, scope, mean, variance, "
                        "sample_count, last_updated) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (coord_id, metric, "house", 1.0, 0.5, n,
                         None if n == 0 else "2026-11-01T00:00:00"),
                    )
                await conn.commit()
            await det.load_baselines()
        finally:
            await db.stop_write_worker()

    asyncio.new_event_loop().run_until_complete(_scenario())
    return db, det


def test_hvac_prune_drops_egress_pause_frequency_row(tmp_path):
    hc = _hvac_const()
    db, det = _run_prune(
        tmp_path,
        coord_id="hvac",
        metric_names=hc.HVAC_METRICS,
        suppressed=hc.HVAC_SUPPRESSED_FROM_PERSISTENCE,
        unwired=hc.HVAC_UNWIRED_METRICS,
        removed="egress_pause_frequency",
        kept="override_frequency",
    )
    assert _count(db.db_file, "hvac", "egress_pause_frequency") == 0
    assert _count(db.db_file, "hvac", "override_frequency") == 1
    assert ("override_frequency", "house") in det._baselines
    assert ("egress_pause_frequency", "house") not in det._baselines
    assert det._baselines_loaded is True


def test_security_prune_drops_entry_anomaly_score_row(tmp_path):
    sec = _security()
    db, det = _run_prune(
        tmp_path,
        coord_id="security",
        metric_names=sec.SECURITY_METRICS,
        suppressed=sec.SECURITY_SUPPRESSED_FROM_PERSISTENCE,
        unwired=sec.SECURITY_UNWIRED_METRICS,
        removed="entry_anomaly_score",
        kept="alert_trigger_frequency",
    )
    assert _count(db.db_file, "security", "entry_anomaly_score") == 0
    assert _count(db.db_file, "security", "alert_trigger_frequency") == 1
    assert ("entry_anomaly_score", "house") not in det._baselines
    # Empty unwired set: no metric is reported as a declared gap.
    assert det._unwired_metric_names == frozenset()
    assert det._baselines_loaded is True


def _detector(coord_id, metrics, suppressed, unwired):
    cdiag = sys.modules[_P + "coordinator_diagnostics"]
    return cdiag.AnomalyDetector(
        MagicMock(), coord_id, metrics,
        suppressed_metric_names=suppressed, unwired_metric_names=unwired,
    )


def test_security_coverage_no_longer_lists_entry_anomaly_score():
    """Sensor-facing surface (coverage / blind map / status summary)."""
    sec = _security()
    det = _detector("security", sec.SECURITY_METRICS,
                    sec.SECURITY_SUPPRESSED_FROM_PERSISTENCE,
                    sec.SECURITY_UNWIRED_METRICS)
    assert set(det.get_coverage()) == {"alert_trigger_frequency"}
    assert "entry_anomaly_score" not in det.get_blind_metrics()
    assert det.get_status_summary()["metrics_unwired"] == []


def test_hvac_coverage_lists_only_comfort_deviation_as_not_wired():
    hc = _hvac_const()
    det = _detector("hvac", hc.HVAC_METRICS,
                    hc.HVAC_SUPPRESSED_FROM_PERSISTENCE,
                    hc.HVAC_UNWIRED_METRICS)
    cov = det.get_coverage()
    assert "egress_pause_frequency" not in cov
    not_wired = sorted(m for m, c in cov.items() if c["reason"] == "not_wired")
    assert not_wired == ["comfort_deviation_hours"]
    assert det.get_status_summary()["metrics_unwired"] == [
        "comfort_deviation_hours"]
