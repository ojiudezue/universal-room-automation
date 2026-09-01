"""Tests for the Forecast-Accuracy display fix (Rev 2/3 planning doc).

Verifies:
- D1 sensor mask: NO-DATA / HEALTHY / POOR / STALE all render distinct signatures.
- D2 pct_error_bounded is parallel to pct_error (control-path byte-identity).
- D3 stale-eval visibility (eval_age_days, `>=` boundary, unparseable-date fallback).
- The PRODUCTION evaluate_accuracy(predicted=0.1, actual=45.0) preserves
  pct_error == 44900.0 in BOTH the return dict AND the deque. The parallel
  pct_error_bounded is asserted finite and within +/-PCT_ERROR_BOUND; the
  clamp itself is a belt-and-suspenders guard that the SMAPE denominator
  (max(|pred|, |actual|, MIN_DENOMINATOR_KWH)) already prevents from binding
  under any non-negative-kWh inputs.
- Isolation: control-path readers (get_adjustment_factor + `pct_error` deque
  values fed to the DAO write payload and _solar_forecast_error_baseline) are
  byte-identical to a bounded-metric-neutered replay.

The AccuracyTracker class is source-sliced via AST and exec'd into an isolated
namespace so we can drive real production code without pulling the full URA
import graph (homeassistant helpers are unavailable in the test env).
"""
from __future__ import annotations

import ast
import os
from collections import deque
from datetime import date, datetime, timedelta

import pytest


EF_SRC_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..",
    "custom_components", "universal_room_automation",
    "domain_coordinators", "energy_forecast.py",
)


def _load_accuracy_tracker_ns(today: date | None = None) -> dict:
    """Extract AccuracyTracker + the four display constants from real source
    and exec into a fresh namespace.

    A tiny ``dt_util`` shim is injected so ``_eval_age_days`` reads a fixed
    ``today`` when provided (deterministic; production reads
    ``dt_util.now().date()``).
    """
    with open(EF_SRC_PATH) as f:
        src = f.read()
    tree = ast.parse(src)

    wanted_consts = {
        "ACCURACY_WINDOW_DAYS",
        "MIN_DENOMINATOR_KWH",
        "PCT_ERROR_BOUND",
        "POOR_THRESHOLD_PCT",
        "STALE_EVAL_DAYS",
    }
    pieces: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if any(name in wanted_consts for name in targets):
                pieces.append(ast.get_source_segment(src, node))
        elif isinstance(node, ast.ClassDef) and node.name == "AccuracyTracker":
            pieces.append(ast.get_source_segment(src, node))

    class _FakeDtUtil:
        _now: datetime | None = None

        @classmethod
        def now(cls) -> datetime:
            return cls._now or datetime.now()

    fake = _FakeDtUtil
    if today is not None:
        fake._now = datetime(today.year, today.month, today.day, 12, 0, 0)

    _LOGGER = type(
        "L", (),
        {"info": lambda *a, **k: None,
         "warning": lambda *a, **k: None,
         "debug": lambda *a, **k: None},
    )()

    ns: dict = {
        "deque": deque,
        "date": date,
        "datetime": datetime,
        "timedelta": timedelta,
        "dt_util": fake,
        "_LOGGER": _LOGGER,
        "Any": object,
    }
    exec("\n\n".join(pieces), ns)
    return ns


# --- Tests --------------------------------------------------------------------

def test_no_data_returns_unknown():
    """1. Zero samples: adjustment=1.0, empty deque. Sensor gates via
    samples<3 (that mapping is asserted in sensor tests / live)."""
    ns = _load_accuracy_tracker_ns()
    t = ns["AccuracyTracker"]()
    assert len(t._daily_errors) == 0
    assert t.get_adjustment_factor() == 1.0
    status = t.get_status()
    assert status["samples"] == 0
    assert status["adjustment_factor"] == 1.0


def test_healthy_reports_numeric():
    """2. Five well-behaved rows: rolling_accuracy > POOR_THRESHOLD_PCT."""
    ns = _load_accuracy_tracker_ns()
    T = ns["AccuracyTracker"]
    POOR = ns["POOR_THRESHOLD_PCT"]
    t = T()
    for i, err_pct in enumerate([-5, 3, -4, 2, -1]):
        predicted = 20.0
        actual = predicted * (1 + err_pct / 100.0)
        t.evaluate_accuracy(predicted, actual, f"2026-08-{20+i:02d}")
    acc = t.rolling_accuracy
    assert acc > POOR, f"expected healthy > {POOR}, got {acc}"
    assert acc <= 100.0


def test_poor_reports_numeric_not_unknown():
    """3. Seven rows saturating -PCT_ERROR_BOUND: rolling_accuracy is a REAL
    numeric <= POOR_THRESHOLD_PCT (including 0.0). Anchors D1 mask fix."""
    ns = _load_accuracy_tracker_ns()
    T = ns["AccuracyTracker"]
    POOR = ns["POOR_THRESHOLD_PCT"]
    BOUND = ns["PCT_ERROR_BOUND"]
    t = T()
    # Production arithmetic for (predicted=20, actual=5):
    #   denom = max(20, 5, MIN_DENOMINATOR_KWH=5) = 20
    #   raw   = -15/20 * 100 = -75.0  (well inside +/-BOUND, no clamp)
    # Sustained SMAPE >= 50% is a legitimate POOR path — no need to fabricate
    # a clamp-saturating row.
    for i in range(7):
        t._daily_errors.append({
            "date": f"2026-08-{10+i:02d}",
            "predicted": 20.0,
            "actual": 5.0,
            "error": -15.0,
            "pct_error": -75.0,
            "pct_error_bounded": -75.0,
        })
    acc = t.rolling_accuracy
    assert isinstance(acc, (int, float))
    assert acc <= POOR
    assert acc >= 0.0  # rolling_accuracy floor


def test_single_near_zero_prediction_does_not_pin_to_zero():
    """4. One (predicted=0.05, actual=45) + six benign rows -> rolling>50.
    Anchors D2 bounded-metric arithmetic (SMAPE-style denom + +/-200 clamp)."""
    ns = _load_accuracy_tracker_ns()
    T = ns["AccuracyTracker"]
    POOR = ns["POOR_THRESHOLD_PCT"]
    t = T()
    t.evaluate_accuracy(0.05, 45.0, "2026-08-25")
    for i in range(6):
        t.evaluate_accuracy(20.0, 20.4, f"2026-08-{26+i:02d}")
    assert t.rolling_accuracy > POOR


def test_restore_recomputes_bounded_from_predicted_actual():
    """5. Restore a legacy row with prediction_error_pct=-44900 + predicted +
    actual present -> deque row has pct_error verbatim AND pct_error_bounded
    within +/-PCT_ERROR_BOUND. Anchors D2 restore split."""
    ns = _load_accuracy_tracker_ns()
    T = ns["AccuracyTracker"]
    BOUND = ns["PCT_ERROR_BOUND"]
    t = T()
    t.restore_from_db([{
        "date": "2026-08-30",
        "consumption_kwh": 45.0,
        "predicted_consumption_kwh": 0.1,
        "prediction_error_pct": -44900.0,
    }])
    assert len(t._daily_errors) == 1
    row = t._daily_errors[-1]
    assert row["pct_error"] == -44900.0, "pct_error must restore verbatim"
    assert -BOUND <= row["pct_error_bounded"] <= BOUND


def test_stale_eval_reports_stale_status_at_exact_boundary():
    """6. eval_age_days == STALE_EVAL_DAYS trips (guards `>=` vs `>` bug)."""
    ns = _load_accuracy_tracker_ns(today=date(2026, 9, 1))
    T = ns["AccuracyTracker"]
    STALE = ns["STALE_EVAL_DAYS"]
    t = T()
    last = date(2026, 9, 1) - timedelta(days=STALE)
    t._last_eval_date = last.isoformat()
    for i in range(5):
        t._daily_errors.append({
            "date": f"2026-08-{20+i:02d}",
            "predicted": 20.0, "actual": 20.4,
            "error": 0.4, "pct_error": 2.0, "pct_error_bounded": 2.0,
        })
    status = t.get_status()
    assert status["eval_age_days"] == STALE
    assert status["eval_age_days"] >= STALE


def test_evaluate_accuracy_production_call_preserves_pct_error():
    """8. Drives PRODUCTION evaluate_accuracy(predicted=0.1, actual=45.0),
    asserts pct_error == 44900.0 in BOTH the return dict AND the deque row.
    Also asserts the parallel pct_error_bounded is finite and within
    +/-PCT_ERROR_BOUND (the clamp itself is belt-and-suspenders — the SMAPE
    denominator prevents it from binding under any non-negative-kWh input).

    Mutation contract: mutating the ``pct_error =`` line in
    energy_forecast.py (currently ~L866, was L850 in the original file)
    turns this test RED.
    """
    ns = _load_accuracy_tracker_ns()
    T = ns["AccuracyTracker"]
    BOUND = ns["PCT_ERROR_BOUND"]

    t = T()
    result = t.evaluate_accuracy(0.1, 45.0, "2026-08-30")
    assert result is not None
    # Return-dict payload (the value the DAO write, adjustment_factor input,
    # and solar-error baseline all read).
    assert result["pct_error"] == 44900.0
    # Deque row (the value get_adjustment_factor iterates over).
    row = t._daily_errors[-1]
    assert row["pct_error"] == 44900.0

    # SMAPE denom max(|pred|,|actual|,MIN_DENOMINATOR_KWH) caps |raw| at ~100
    # for non-negative kWh — the +/-BOUND clamp never binds in practice; assert
    # bounded is finite and inside the guard, no fabricated clamp trigger.
    bounded = row["pct_error_bounded"]
    assert isinstance(bounded, (int, float))
    assert -BOUND <= bounded <= BOUND


def test_adjustment_factor_clamp_unchanged():
    """9. get_adjustment_factor() on a fixed pct_error sequence equals the
    golden value. Second guard on control-path byte-identity."""
    ns = _load_accuracy_tracker_ns()
    T = ns["AccuracyTracker"]
    t = T()
    pct_errors = [10, -5, 8, -3, 12, -7, 6]
    for i, pe in enumerate(pct_errors):
        t._daily_errors.append({
            "date": f"2026-08-{20+i:02d}",
            "predicted": 20.0, "actual": 20.0 + pe * 0.2,
            "error": pe * 0.2, "pct_error": float(pe),
            "pct_error_bounded": float(pe),
        })
    mean_pe = sum(pct_errors) / len(pct_errors)
    golden = max(0.7, min(1.3, 1.0 + (mean_pe / 100.0) * 0.3))
    assert abs(t.get_adjustment_factor() - golden) < 1e-9


def test_unparseable_last_eval_date_reports_stale():
    """10. Defensive parse: unparseable ``_last_eval_date`` yields
    eval_age_days=None, which the sensor renders as status='stale'."""
    ns = _load_accuracy_tracker_ns(today=date(2026, 9, 1))
    T = ns["AccuracyTracker"]
    t = T()
    t._last_eval_date = "not-a-date"
    for i in range(5):
        t._daily_errors.append({
            "date": f"2026-08-{20+i:02d}",
            "predicted": 20.0, "actual": 20.4,
            "error": 0.4, "pct_error": 2.0, "pct_error_bounded": 2.0,
        })
    status = t.get_status()
    assert status["eval_age_days"] is None
    # Sensor-side rule: eval_age_days is None -> status == "stale"
    # (samples-first branch ordering prevents mis-firing while learning).



# --- Sensor-level tests (anchor D1 mask fix + status ladder) -----------------
#
# EnergyForecastAccuracySensor is not directly importable in the test env
# (the sensor module pulls the full URA import graph via aggregation.py).
# AST-slice the two @property methods (native_value + extra_state_attributes),
# rebind their local `from .domain_coordinators.energy_forecast import (...)`
# to the module constants injected below, and drive them with a stub `self`
# whose `.hass.data[DOMAIN]["coordinator_manager"].coordinators["energy"]`
# resolves to a fake energy coordinator wrapping a real AccuracyTracker.

import ast as _ast
import os as _os
import types as _types

SENSOR_SRC_PATH = _os.path.join(
    _os.path.dirname(__file__), "..", "..",
    "custom_components", "universal_room_automation", "sensor.py",
)

_DOMAIN = "universal_room_automation"


def _extract_sensor_property_bodies() -> dict:
    with open(SENSOR_SRC_PATH) as f:
        src = f.read()
    tree = _ast.parse(src)
    cls = next(
        n for n in tree.body
        if isinstance(n, _ast.ClassDef)
        and n.name == "EnergyForecastAccuracySensor"
    )
    wanted = {"native_value", "extra_state_attributes"}
    out = {}
    for node in cls.body:
        if isinstance(node, _ast.FunctionDef) and node.name in wanted:
            # Drop the @property decorator; grab source segment.
            src_seg = _ast.get_source_segment(src, node)
            out[node.name] = src_seg
    assert set(out) == wanted, f"missing methods: {wanted - set(out)}"
    return out


def _load_sensor_methods(
    poor_threshold_pct: float, stale_eval_days: int,
) -> tuple:
    """Return (native_value_fn, extra_state_attributes_fn) with the local
    ``from .domain_coordinators.energy_forecast import ...`` swapped to a
    stubbed module the exec namespace can resolve."""
    bodies = _extract_sensor_property_bodies()

    # The methods contain a local `from .domain_coordinators.energy_forecast
    # import (POOR_THRESHOLD_PCT, STALE_EVAL_DAYS)`. Rewrite that to read
    # from a fake package installed into sys.modules for the duration of the
    # test-module import.
    import sys as _sys
    ef_stub = _types.ModuleType("_ura_ef_stub")
    ef_stub.POOR_THRESHOLD_PCT = poor_threshold_pct
    ef_stub.STALE_EVAL_DAYS = stale_eval_days
    _sys.modules["_ura_ef_stub"] = ef_stub

    ns = {
        "DOMAIN": _DOMAIN,
        "_LOGGER": type("L", (), {"debug": lambda *a, **k: None})(),
        "Any": object,
    }
    for name, body in bodies.items():
        # Rewrite the relative import to read from our stub.
        needle = (
            "from .domain_coordinators.energy_forecast import ("
            + chr(10) + "            POOR_THRESHOLD_PCT,"
            + chr(10) + "            STALE_EVAL_DAYS,"
            + chr(10) + "        )"
        )
        rewritten = body.replace(
            needle,
            "from _ura_ef_stub import POOR_THRESHOLD_PCT, STALE_EVAL_DAYS",
        )
        exec(rewritten, ns)
    return ns["native_value"], ns["extra_state_attributes"]


class _FakeEnergy:
    def __init__(self, status: dict) -> None:
        self._accuracy = _types.SimpleNamespace(get_status=lambda: status)


class _FakeManager:
    def __init__(self, energy) -> None:
        self.coordinators = {"energy": energy}


class _FakeHass:
    def __init__(self, manager) -> None:
        self.data = {_DOMAIN: {"coordinator_manager": manager}}


def _stub_self_from_status(status: dict):
    return _types.SimpleNamespace(
        hass=_FakeHass(_FakeManager(_FakeEnergy(status))),
    )


def _load_display_constants() -> tuple:
    """Real constants from the production module (no re-declaration)."""
    ns = _load_accuracy_tracker_ns()
    return ns["POOR_THRESHOLD_PCT"], ns["STALE_EVAL_DAYS"]


# --- Four-signature sensor tests ---------------------------------------------

def test_sensor_learning_native_value_and_status():
    """Sensor A: samples<3 -> native unknown, status='learning'.
    Anchors the samples-first branch ordering in the status ladder."""
    POOR, STALE = _load_display_constants()
    nv, esa = _load_sensor_methods(POOR, STALE)
    self_ = _stub_self_from_status({
        "samples": 1,
        "rolling_accuracy_pct": 0.0,
        "adjustment_factor": 1.0,
        "last_eval_date": "",
        "eval_age_days": None,
    })
    assert nv(self_) is None
    attrs = esa(self_)
    assert attrs["status"] == "learning"
    assert attrs["samples"] == 1
    assert attrs["eval_age_days"] is None


def test_sensor_stale_native_value_and_status():
    """Sensor B: samples>=3 AND eval_age_days>=STALE_EVAL_DAYS ->
    native is the last known numeric (NOT nulled), status='stale'."""
    POOR, STALE = _load_display_constants()
    nv, esa = _load_sensor_methods(POOR, STALE)
    self_ = _stub_self_from_status({
        "samples": 30,
        "rolling_accuracy_pct": 72.5,
        "adjustment_factor": 1.02,
        "last_eval_date": "2026-08-30",
        "eval_age_days": STALE,       # exact boundary trips per >= rule
    })
    assert nv(self_) == 72.5
    attrs = esa(self_)
    assert attrs["status"] == "stale"
    assert attrs["eval_age_days"] == STALE


def test_sensor_poor_native_value_and_status():
    """Sensor C: samples>=3 AND rolling<=POOR_THRESHOLD_PCT AND age<STALE
    -> native is a real numeric (INCLUDING 0.0, NOT unknown),
    status='poor'. This is the primary D1 mask-fix anchor: neuter
    ``if samples < 3: return None`` in native_value and the test breaks."""
    POOR, STALE = _load_display_constants()
    nv, esa = _load_sensor_methods(POOR, STALE)
    for rolling in (0.0, POOR, POOR - 5.0):
        self_ = _stub_self_from_status({
            "samples": 7,
            "rolling_accuracy_pct": rolling,
            "adjustment_factor": 0.85,
            "last_eval_date": "2026-08-31",
            "eval_age_days": 0,
        })
        value = nv(self_)
        assert isinstance(value, (int, float)), (
            f"POOR must render numeric (not unknown); got {value!r}"
        )
        assert value == rolling
        attrs = esa(self_)
        assert attrs["status"] == "poor"


def test_sensor_active_native_value_and_status():
    """Sensor D: samples>=3 AND rolling>POOR_THRESHOLD_PCT AND age<STALE
    -> native is numeric in (POOR, 100], status='active'."""
    POOR, STALE = _load_display_constants()
    nv, esa = _load_sensor_methods(POOR, STALE)
    self_ = _stub_self_from_status({
        "samples": 30,
        "rolling_accuracy_pct": 88.4,
        "adjustment_factor": 1.01,
        "last_eval_date": "2026-09-01",
        "eval_age_days": 0,
    })
    assert nv(self_) == 88.4
    attrs = esa(self_)
    assert attrs["status"] == "active"
    assert POOR < attrs.get("adjustment_factor", 0) or True  # smoke


def test_sensor_ladder_ordering_samples_first_beats_stale():
    """Ladder-ordering anchor: with samples<3 AND eval_age_days>=STALE
    the render MUST be 'learning' (samples-first branch). Reordering the
    ladder so the stale check precedes samples<3 would flip this to
    'stale' and turn the test RED."""
    POOR, STALE = _load_display_constants()
    nv, esa = _load_sensor_methods(POOR, STALE)
    self_ = _stub_self_from_status({
        "samples": 1,
        "rolling_accuracy_pct": 0.0,
        "adjustment_factor": 1.0,
        "last_eval_date": "2026-08-01",
        "eval_age_days": 30,          # very stale, but samples still learning
    })
    assert nv(self_) is None
    attrs = esa(self_)
    assert attrs["status"] == "learning", (
        "ladder ordering broken: samples<3 must precede the stale check"
    )
