"""HVAC-ANOMALY-BLIND-1 residual A — the anomaly detector must not say
"nominal" when it cannot see (PLANNING_anomaly_detector_blind_metrics.md
REV 2.1 + operator ruling 2026-09-29 on "learning").

Falsifiable invariants (plan §6):

INV-COVERAGE  An AnomalyDetector-backed sensor reports `nominal` only if every
              declared metric has best-scope sample_count ≥ its gate. Otherwise
              the state ∈ {insufficient_data, learning, partial, advisory,
              alert, critical} and `metrics_blind` names every such metric.
              `constant_baseline` and `suppressed` never affect the state.
              (Ruling: `learning` only while a metric is actively collecting;
              a below-gate metric with no sample in ANOMALY_LEARNING_STALL_DAYS
              is `not_collecting` → blind → `partial`.)
INV-SEVERITY-PRECEDENCE  worst severity ≠ nominal ⇒ state == that severity.
INV-NOOP      house-only, all-ok, empty unwired set ⇒ byte-identical pre-cycle
              output, no read creates a baseline key, save writes same rows.

Every test drives the REAL AnomalyDetector (no fake detector). Sensor-site
tests drive the REAL `native_value` property bodies (and the real
HVACCoordinator / SecurityCoordinator `get_anomaly_status`).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import types
from datetime import datetime, timedelta, timezone

import pytest

_HERE = os.path.dirname(__file__)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import _anomaly_noop_scenario as NOOP  # noqa: E402

from custom_components.universal_room_automation import (  # noqa: E402
    button as button_mod,
    sensor as sensor_mod,
)
from custom_components.universal_room_automation.domain_coordinators import (  # noqa: E402
    base as base_mod,
    coordinator_diagnostics as diag,
    hvac as hvac_mod,
    manager as manager_mod,
    security as security_mod,
)

AnomalyDetector = diag.AnomalyDetector
MetricBaseline = diag.MetricBaseline
DOMAIN = "universal_room_automation"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _now_iso(delta_days: float = 0.0) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=delta_days)).isoformat()


def _det(metrics, **kw):
    kw.setdefault("minimum_samples", 24)
    return AnomalyDetector(NOOP.make_hass(), "t", list(metrics), **kw)


_NOW = object()


def _seed(det, metric, scope, n, *, mean=1.0, variance=1.0, last_updated=_NOW):
    det._baselines[(metric, scope)] = MetricBaseline(
        metric_name=metric, coordinator_id=det.coordinator_id, scope=scope,
        mean=mean, variance=variance, sample_count=n,
        last_updated=_now_iso() if last_updated is _NOW else last_updated,
    )


def _fire(det, metric, z, scope="house"):
    """Record one observation `z` std away from the metric's mean (real
    record_observation path). Returns the AnomalyRecord (or None)."""
    b = det._baselines[(metric, scope)]
    return det.record_observation(metric, scope, b.mean + z * b.std)


# ===========================================================================
# D1 — coverage classifier
# ===========================================================================

def test_coverage_reasons_each_class():
    det = _det(
        ["m_ok", "m_learn", "m_stalled", "m_never", "m_unwired", "m_supp", "m_const"],
        suppressed_metric_names=frozenset({"m_supp"}),
        unwired_metric_names=frozenset({"m_unwired"}),
    )
    _seed(det, "m_ok", "house", 30, variance=2.0)
    _seed(det, "m_learn", "house", 5, last_updated=_now_iso(1))
    _seed(det, "m_stalled", "house", 5, last_updated=_now_iso(25))
    _seed(det, "m_supp", "house", 40, variance=0.5)
    _seed(det, "m_const", "house", 30, variance=0.0)
    cov = det.get_coverage()
    got = {m: (c["reason"], c["suppressed"], c["constant_baseline"], c["sample_count"])
           for m, c in cov.items()}
    oracle = {
        "m_ok": ("ok", False, False, 30),
        "m_learn": ("learning", False, False, 5),
        "m_stalled": ("not_collecting", False, False, 5),
        "m_never": ("never_fed", False, False, 0),
        "m_unwired": ("not_wired", False, False, 0),
        "m_supp": ("ok", True, False, 40),
        "m_const": ("ok", False, True, 30),
    }
    assert got == oracle
    assert det.get_blind_metrics() == {
        "m_learn": "learning",
        "m_stalled": "not_collecting",
        "m_never": "never_fed",
        "m_unwired": "not_wired",
    }


def test_declared_unwired_but_fed_reports_data_reason_and_warns_once(caplog):
    det = _det(["m_a", "m_b"], unwired_metric_names=frozenset({"m_a"}))
    _seed(det, "m_a", "house", 30)
    _seed(det, "m_b", "house", 30)
    with caplog.at_level(logging.WARNING, logger=diag.__name__):
        for _ in range(4):
            cov = det.get_coverage()
            det.get_status_summary()
    assert cov["m_a"]["reason"] == "ok"
    warns = [r for r in caplog.records if "declared unwired but has data" in r.getMessage()]
    assert len(warns) == 1
    assert "m_a" in warns[0].getMessage()
    # still listed as declared-unwired, but NOT blind (data wins)
    s = det.get_status_summary()
    assert s["metrics_unwired"] == ["m_a"]
    assert s["metrics_blind"] == {}
    assert det.get_sensor_state() == "nominal"


def test_constant_baseline_is_annotation_not_blind():
    det = _det(["m_const"])
    for _ in range(30):
        assert det.record_observation("m_const", "house", 1.0) is None
    b = det._baselines[("m_const", "house")]
    assert b.variance == 0.0 and b.sample_count == 30
    cov = det.get_coverage()["m_const"]
    assert cov["reason"] == "ok"
    assert cov["constant_baseline"] is True
    s = det.get_status_summary()
    assert "m_const" not in s["metrics_blind"]
    assert s["metrics_constant"] == ["m_const"]
    # The withdrawn "degenerate ⇒ blind" rule would read `partial` here.
    assert det.get_sensor_state() == "nominal"
    # Hair trigger (documented): std is floored at 0.1, so |3 - 1| / 0.1 = 20.
    anomaly = det.record_observation("m_const", "house", 3.0)
    assert anomaly is not None
    assert anomaly.severity == diag.AnomalySeverity.CRITICAL
    assert round(anomaly.z_score, 6) == 20.0
    assert det.get_coverage()["m_const"]["constant_baseline"] is False
    assert det.get_sensor_state() == "critical"


def _save_then_load(seed_fn, tmp_path, metrics, **kw):
    """Seed rows through the PRODUCTION save path, load them into a fresh
    detector through the PRODUCTION load path (real aiosqlite, prod DDL)."""
    async def run():
        db = NOOP.AiosqliteDB(str(tmp_path / "b.db"))
        await db.setup()
        writer = AnomalyDetector(NOOP.make_hass(db), "t", list(metrics), minimum_samples=24, **kw)
        seed_fn(writer)
        await writer.save_baselines()
        reader = AnomalyDetector(NOOP.make_hass(db), "t", list(metrics), minimum_samples=24, **kw)
        await reader.load_baselines()
        return reader
    return asyncio.run(run())


def test_zone_scoped_metric_not_reported_silent(tmp_path):
    def seed(w):
        w._get_baseline("m_zone", "house")  # the real phantom creator (n=0, None ts)
        _seed(w, "m_zone", "zone_1", 30)
        _seed(w, "m_house", "house", 30)
    det = _save_then_load(seed, tmp_path, ["m_zone", "m_house"])
    assert det._baselines[("m_zone", "house")].sample_count == 0  # phantom loaded
    cov = det.get_coverage()["m_zone"]
    assert cov["reason"] == "ok"
    assert cov["best_scope"] == "zone_1"
    s = det.get_status_summary()
    assert "m_zone" not in s["metrics_silent"]
    assert s["metrics_active_ratio"] == "2/2"
    assert s["metrics"]["m_zone"]["best_scope"] == "zone_1"
    # per-metric `active` stays requested-scope (house phantom)
    assert s["metrics"]["m_zone"]["active"] is False
    assert s["metrics"]["m_zone"]["reason"] == "ok"
    assert det.get_sensor_state() == "nominal"


def test_starved_sibling_scope_is_ok_by_design():
    det = _det(["m"])
    _seed(det, "m", "zone_1", 30)
    _seed(det, "m", "zone_2", 0, last_updated="")
    assert det.get_coverage()["m"]["reason"] == "ok"
    assert det.get_sensor_state() == "nominal"
    s = det.get_status_summary()
    assert s["metrics"]["m"]["scopes"]["zone_2"]["sample_count"] == 0


def test_best_scope_tie_break_is_deterministic():
    det = _det(["m"])
    # insertion order deliberately NOT the name order
    _seed(det, "m", "zone_b", 30, variance=2.0)
    _seed(det, "m", "zone_a", 30, variance=0.0)
    _seed(det, "m", "house", 3)
    cov = det.get_coverage()["m"]
    assert cov["best_scope"] == "zone_a"
    assert cov["constant_baseline"] is True  # zone_a's variance, by name order
    det2 = _det(["m"])
    _seed(det2, "m", "zone_a", 30, variance=0.0)
    _seed(det2, "m", "zone_b", 30, variance=2.0)
    assert det2.get_coverage()["m"]["best_scope"] == "zone_a"


def _all_read_paths(det):
    det.get_learning_status()
    det.get_learning_status("zone_x")
    det.get_status_summary()
    det.get_status_summary("zone_x")
    det.get_coverage()
    det.get_blind_metrics()
    det.get_coverage_state()
    det.get_sensor_state()
    det.get_worst_severity()
    det.get_worst_metric()


def test_status_reads_do_not_create_baselines():
    det = _det(["m_absent", "m_zone", "m_house"], unwired_metric_names=frozenset({"m_absent"}))
    _seed(det, "m_zone", "zone_1", 30)
    _seed(det, "m_house", "house", 30)
    before = set(det._baselines)
    _all_read_paths(det)
    assert set(det._baselines) == before


def test_house_only_detector_summary_byte_identical(tmp_path):
    golden = json.loads(NOOP.GOLDEN_PATH.read_text())

    def project(expected, actual):
        """Pre-existing keys only (the golden's), recursively."""
        if isinstance(expected, dict):
            assert isinstance(actual, dict)
            return {k: project(v, actual[k]) for k, v in expected.items()}
        return actual

    for name in NOOP.SCENARIOS:
        got = asyncio.run(NOOP.capture(
            name, str(tmp_path), state_fn=lambda d: d.get_sensor_state(),
        ))
        exp = golden[name]
        assert project(exp["summary"], got["summary"]) == exp["summary"], name
        assert got["state"] == exp["state"], name
        assert got["learning_status"] == exp["learning_status"], name
        assert got["worst_severity"] == exp["worst_severity"], name
        assert got["baseline_keys"] == exp["baseline_keys"], name
        assert got["saved_rows"] == exp["saved_rows"], name
        # additive keys present, and the NOOP domain is `full`
        assert got["summary"]["coverage"] == "full"
        assert got["summary"]["metrics_blind"] == {}


def test_save_baselines_survives_concurrent_key_insert(tmp_path):
    async def run():
        db = NOOP.AiosqliteDB(str(tmp_path / "race.db"))
        await db.setup()
        det = AnomalyDetector(NOOP.make_hass(db), "race", ["m1", "m2", "m3"], minimum_samples=24)
        for m in ("m1", "m2", "m3"):
            _seed(det, m, "house", 30, last_updated=NOOP.PINNED_TS)

        def creator(call_no):
            if call_no == 1:  # a key creator runs during the first awaited write
                det._get_baseline("m_new_during_save", "house")
        db.on_execute = creator
        await det.save_baselines()
        return await db.rows()

    rows = asyncio.run(run())
    written = {(r[1], r[2]) for r in rows}
    assert {("m1", "house"), ("m2", "house"), ("m3", "house")} <= written


def test_worst_metric_excludes_suppressed():
    det = _det(["m_loud", "m_real"], suppressed_metric_names=frozenset({"m_loud"}))
    _seed(det, "m_loud", "house", 30)
    _seed(det, "m_real", "house", 30)
    _fire(det, "m_loud", 9.0)
    _fire(det, "m_real", 2.5)
    assert det.get_worst_metric()[0] == "m_real"
    det2 = _det(["m_loud"], suppressed_metric_names=frozenset({"m_loud"}))
    _seed(det2, "m_loud", "house", 30)
    _fire(det2, "m_loud", 9.0)
    assert det2.get_worst_metric() == ("", 0.0)


def test_unwired_names_must_be_declared(caplog):
    with caplog.at_level(logging.WARNING, logger=diag.__name__):
        det = _det(["m_a"], unwired_metric_names=frozenset({"m_a", "m_ghost"}))
    assert det._unwired_metric_names == frozenset({"m_a"})
    assert any("m_ghost" in r.getMessage() for r in caplog.records)
    assert _det(["m_a"])._unwired_metric_names == frozenset()


def test_last_updated_mixed_naive_aware_normalised():
    det = _det(["m", "m2"])
    _seed(det, "m", "zone_1", 5, last_updated="2026-05-12T04:48:24.220732")
    _seed(det, "m", "zone_2", 5, last_updated="2026-09-01T00:00:00+00:00")
    assert det.get_coverage()["m"]["last_updated"] == "2026-09-01T00:00:00+00:00"
    # Discriminates a lexicographic max: the -05:00 value is the later instant.
    _seed(det, "m2", "zone_1", 5, last_updated="2026-09-02T00:30:00")
    _seed(det, "m2", "zone_2", 5, last_updated="2026-09-01T20:00:00-05:00")
    _seed(det, "m2", "zone_3", 0, last_updated=None)
    _seed(det, "m2", "zone_4", 1, last_updated="not-a-date")
    assert det.get_coverage()["m2"]["last_updated"] == "2026-09-02T01:00:00+00:00"
    assert det.get_status_summary()["metrics"]["m2"]["last_updated"] == (
        "2026-09-02T01:00:00+00:00"
    )


# ---------------------------------------------------------------------------
# Operator ruling 2026-09-29: `learning` = actively collecting
# ---------------------------------------------------------------------------

def test_stalled_below_gate_metric_is_not_collecting_and_partial():
    """Safety shape: 1 metric, gate 720, 42 samples, last sample 25 days ago."""
    det = AnomalyDetector(NOOP.make_hass(), "safety", ["active_hazard_count"], minimum_samples=720)
    _seed(det, "active_hazard_count", "house", 42, variance=0.0,
          last_updated=_now_iso(25))
    assert det.get_coverage()["active_hazard_count"]["reason"] == "not_collecting"
    assert det.get_learning_status() == diag.LearningStatus.PAUSED
    s = det.get_status_summary()
    assert s["metrics_blind"] == {"active_hazard_count": "not_collecting"}
    assert s["coverage"] == "partial"
    assert det.get_sensor_state() == "partial"


def test_below_gate_metric_still_gaining_is_learning():
    det = AnomalyDetector(NOOP.make_hass(), "safety", ["active_hazard_count"], minimum_samples=720)
    _seed(det, "active_hazard_count", "house", 42, last_updated=_now_iso(25))
    # a fresh sample through the real write path makes it collecting again
    det.record_observation("active_hazard_count", "house", 1.0)
    assert det.get_coverage()["active_hazard_count"]["reason"] == "learning"
    assert det.get_learning_status() == diag.LearningStatus.LEARNING
    assert det.get_sensor_state() == "learning"
    # a sample just inside the window is still collecting
    det2 = AnomalyDetector(NOOP.make_hass(), "s2", ["m"], minimum_samples=720)
    _seed(det2, "m", "house", 42, last_updated=_now_iso(diag.ANOMALY_LEARNING_STALL_DAYS - 0.5))
    assert det2.get_sensor_state() == "learning"


def test_below_gate_metric_without_timestamp_is_not_judged_stalled():
    det = AnomalyDetector(NOOP.make_hass(), "s", ["m"], minimum_samples=720)
    _seed(det, "m", "house", 42, last_updated="")
    assert det.get_coverage()["m"]["reason"] == "learning"


def test_mature_below_threshold_with_nothing_collecting_is_partial_not_learning():
    """4 metrics (threshold 2): 1 mature, 1 stalled, 2 never fed → nothing is
    collecting → `paused` aggregate → `partial` (ruling: not `learning`)."""
    det = _det(["m1", "m2", "m3", "m4"])
    _seed(det, "m1", "house", 30)
    _seed(det, "m2", "house", 5, last_updated=_now_iso(30))
    assert det.get_learning_status() == diag.LearningStatus.PAUSED
    assert det.get_sensor_state() == "partial"
    assert det.get_blind_metrics() == {
        "m2": "not_collecting", "m3": "never_fed", "m4": "never_fed",
    }


def test_no_data_at_all_is_still_insufficient_data():
    det = _det(["m1", "m2"])
    assert det.get_learning_status() == diag.LearningStatus.INSUFFICIENT_DATA
    assert det.get_sensor_state() == "insufficient_data"


# ===========================================================================
# D2 — shared projection
# ===========================================================================

def _matrix_case(name):
    if name == "learning_plus_mature_advisory":
        det = _det(["m1", "m2", "m3", "m4", "m5"])  # threshold 2
        _seed(det, "m1", "house", 30)
        _seed(det, "m2", "house", 5)
        _fire(det, "m1", 2.5)
        return det
    if name == "learning_no_anomaly":
        det = _det(["m1", "m2", "m3", "m4", "m5"])
        _seed(det, "m1", "house", 30)
        _seed(det, "m2", "house", 5)
        return det
    if name == "active_advisory_blind":
        det = _det(["m1", "m2"])
        _seed(det, "m1", "house", 30)
        _fire(det, "m1", 2.5)
        return det
    if name == "active_blind_only":
        det = _det(["m1", "m2"])
        _seed(det, "m1", "house", 30)
        return det
    if name == "active_constant_only":
        det = _det(["m1", "m2"])
        _seed(det, "m1", "house", 30, variance=0.0)
        _seed(det, "m2", "house", 30)
        return det
    if name == "all_ok":
        det = _det(["m1", "m2"])
        _seed(det, "m1", "house", 30)
        _seed(det, "m2", "house", 30)
        return det
    if name == "active_suppressed_anomaly_blind":
        det = _det(["m1", "m2"], suppressed_metric_names=frozenset({"m1"}))
        _seed(det, "m1", "house", 30)
        _fire(det, "m1", 9.0)
        return det
    if name == "stalled_only":
        det = _det(["m1"], minimum_samples=720)
        _seed(det, "m1", "house", 42, last_updated=_now_iso(25))
        return det
    raise KeyError(name)


@pytest.mark.parametrize("case,expected", [
    ("learning_plus_mature_advisory", "advisory"),
    ("learning_no_anomaly", "learning"),
    ("active_advisory_blind", "advisory"),
    ("active_blind_only", "partial"),
    ("active_constant_only", "nominal"),
    ("all_ok", "nominal"),
    ("active_suppressed_anomaly_blind", "partial"),
    ("stalled_only", "partial"),
])
def test_sensor_state_precedence_matrix(case, expected):
    det = _matrix_case(case)
    assert det.get_sensor_state() == expected
    # severity semantics untouched: `partial` is never a severity
    assert det.get_worst_severity().value != "partial"


def _blind_only_detector():
    det = _det(["m_ok", "m_blind"], unwired_metric_names=frozenset({"m_blind"}))
    _seed(det, "m_ok", "house", 30)
    return det


def _sensor_native_value(site: str, det) -> str:
    """Drive the REAL native_value body of each of the 5 anomaly sensors."""
    if site == "hvac":
        coord = types.SimpleNamespace(anomaly_detector=det)
        coord.get_anomaly_status = types.MethodType(
            hvac_mod.HVACCoordinator.get_anomaly_status, coord)
        key, cls = "hvac", sensor_mod.HVACAnomalySensor
    elif site == "security":
        coord = types.SimpleNamespace(anomaly_detector=det)
        coord.get_anomaly_status = types.MethodType(
            security_mod.SecurityCoordinator.get_anomaly_status, coord)
        key, cls = "security", sensor_mod.SecurityAnomalySensor
    else:
        coord = types.SimpleNamespace(anomaly_detector=det)
        key, cls = {
            "presence": ("presence", sensor_mod.PresenceAnomalySensor),
            "safety": ("safety", sensor_mod.SafetyAnomalySensor),
            "music_following": ("music_following", sensor_mod.MusicFollowingAnomalySensor),
        }[site]
    hass = types.SimpleNamespace(data={DOMAIN: {
        "coordinator_manager": types.SimpleNamespace(coordinators={key: coord}),
    }})
    return cls.native_value.fget(types.SimpleNamespace(hass=hass))


@pytest.mark.parametrize("site", ["presence", "safety", "security", "music_following", "hvac"])
def test_all_five_sensors_route_through_get_sensor_state(site):
    det = _blind_only_detector()
    # the old projection (learning ACTIVE → worst severity) would say nominal
    assert det.get_learning_status() == diag.LearningStatus.ACTIVE
    assert det.get_worst_severity().value == "nominal"
    assert _sensor_native_value(site, det) == "partial"


@pytest.mark.parametrize("site", ["presence", "safety", "security", "music_following", "hvac"])
def test_all_five_sensors_show_severity_over_learning(site):
    """M2 at every site: aggregate learning + persisted advisory → advisory."""
    det = _matrix_case("learning_plus_mature_advisory")
    assert _sensor_native_value(site, det) == "advisory"


# ===========================================================================
# D3 — roll-ups + dump button
# ===========================================================================

class _StubCoordinator(base_mod.BaseCoordinator):
    async def async_setup(self):
        return None

    async def evaluate(self, intents, context):
        return []

    async def async_teardown(self):
        return None


def _hass_for_manager():
    from unittest.mock import MagicMock  # noqa: PLC0415
    hass = MagicMock()
    hass.data = {DOMAIN: {}}
    return hass


def _manager_with(detectors: dict):
    hass = _hass_for_manager()
    mgr = manager_mod.CoordinatorManager(hass)
    for cid, det in detectors.items():
        c = _StubCoordinator(hass, cid, cid.title(), 50)
        mgr.register_coordinator(c)
        c.anomaly_detector = det
    return hass, mgr


def _full_detector():
    det = _det(["m1"])
    _seed(det, "m1", "house", 30)
    return det


def test_manager_summary_status_unchanged_coverage_added():
    _hass, mgr = _manager_with({"blindco": _blind_only_detector(), "fullco": _full_detector()})
    s = mgr.get_summary()["status_per_coordinator"]
    assert s["blindco"]["status"] == "nominal"
    assert s["blindco"]["coverage"] == "partial"
    assert s["fullco"]["coverage"] == "full"
    assert mgr.get_summary()["health_status"] == "green"


def test_system_anomaly_lists_partial_coordinators():
    _hass, mgr = _manager_with({"blindco": _blind_only_detector(), "fullco": _full_detector()})
    st = mgr.get_system_anomaly_status()
    assert st["coordinators_partial"] == ["blindco"]
    assert st["state"] == "nominal"


def test_base_diagnostics_summary_carries_coverage():
    _hass, mgr = _manager_with({"blindco": _blind_only_detector()})
    anomaly = mgr._coordinators["blindco"].get_diagnostics_summary()["anomaly"]
    assert anomaly["coverage"] == "partial"
    assert anomaly["metrics_blind"] == {"m_blind": "not_wired"}


def _press_dump(hass, caplog) -> dict:
    hass.data[DOMAIN]["database"] = object()  # DB sections fail soft; not under test
    fake_self = types.SimpleNamespace(hass=hass)
    with caplog.at_level(logging.ERROR, logger=button_mod.__name__):
        asyncio.run(button_mod.AnomalyDiagnosticDumpButton.async_press(fake_self))
    line = next(r.getMessage() for r in caplog.records
                if "URA ANOMALY DIAGNOSTIC DUMP" in r.getMessage())
    return json.loads(line.split("URA ANOMALY DIAGNOSTIC DUMP: ", 1)[1])


def test_anomaly_dump_includes_diagnostics_summary(caplog):
    hass, mgr = _manager_with({"blindco": _blind_only_detector(), "fullco": _full_detector()})
    hass.data[DOMAIN]["coordinator_manager"] = mgr
    dump = _press_dump(hass, caplog)
    assert dump["anomaly_summary"]["system_anomaly"]["coordinators_partial"] == ["blindco"]
    assert "anomaly_summary_error" not in dump


def test_anomaly_dump_records_summary_error(caplog):
    hass, mgr = _manager_with({"blindco": _blind_only_detector()})

    def boom():
        raise RuntimeError("diag-summary-exploded")
    mgr._coordinators["blindco"].get_diagnostics_summary = boom
    hass.data[DOMAIN]["coordinator_manager"] = mgr
    dump = _press_dump(hass, caplog)
    assert "diag-summary-exploded" in dump["anomaly_summary_error"]
    assert "RuntimeError" in dump["anomaly_summary_error"]


def test_partial_is_not_a_severity_member():
    assert diag.COVERAGE_PARTIAL == "partial"
    assert "partial" not in {s.value for s in diag.AnomalySeverity}
    assert all(getattr(k, "value", k) != "partial" for k in manager_mod._SEVERITY_RANK)
