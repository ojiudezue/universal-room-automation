"""Skill over a trivial baseline (PREDICT-SCORER-BASELINE-SKILL-1) and the
Optimization next-room read that consumes it (PREDICT-MODEL-DWELL-MIGRATION-1
D7). Oracles are hand-counted from the fixture rows. DB tests use the REAL
schema (database.py DDL) and the REAL readers."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from occ_dwell_helpers import make_real_db, real_package, seed

from custom_components.universal_room_automation.const import DOMAIN

UTC = timezone.utc


@pytest.fixture(autouse=True, scope="module")
def _real_ura_package():
    import importlib

    global ps, sensor, opt, bp
    with real_package():
        ps = importlib.import_module(
            "custom_components.universal_room_automation.prediction_skill")
        sensor = importlib.import_module(
            "custom_components.universal_room_automation.sensor")
        opt = importlib.import_module(
            "custom_components.universal_room_automation.domain_coordinators.optimization")
        bp = importlib.import_module(
            "custom_components.universal_room_automation.bayesian_predictor")
        yield


# ---------------------------------------------------------------------------
# Pure helper
# ---------------------------------------------------------------------------


def test_next_room_skill_per_person_baseline():
    rows = [
        # Oji: actual Kitchen x3, Bath x1; 2 hits
        ("Oji", "Kitchen", "Kitchen", None), ("Oji", "Kitchen", "Bath", None),
        ("Oji", "Bath", "Kitchen", None), ("Oji", "Kitchen", "Kitchen", None),
        # Jaya: actual Bed x2; 1 hit
        ("Jaya", "Bed", "Bed", None), ("Jaya", "Bath", "Bed", None),
    ]
    got = ps.next_room_skill(rows)
    # top-1 3/6 = 50.0; baseline (Oji Kitchen 3 + Jaya Bed 2) 5/6 = 83.3
    assert got == {"n": 6, "top1_pct": 50.0, "baseline_top1_pct": 83.3,
                   "skill_pct": -33.3}


def test_next_room_skill_empty():
    assert ps.next_room_skill([]) == {"n": 0, "top1_pct": None,
                                      "baseline_top1_pct": None,
                                      "skill_pct": None}


def test_next_room_skill_none_top_is_a_miss():
    got = ps.next_room_skill([("Oji", None, "A", None),
                              ("Oji", "A", "A", None)])
    assert got["top1_pct"] == 50.0 and got["baseline_top1_pct"] == 100.0


def _t(sec):
    return (datetime(2026, 10, 21, 10, 0, tzinfo=UTC)
            + timedelta(seconds=sec)).isoformat()


def test_dedupe_flaps():
    rows = [("Oji", "K", "K", _t(0)), ("Jaya", "B", "B", _t(5)),
            ("Oji", "K", "X", _t(10)), ("Oji", "K", "K", _t(20)),
            ("Oji", "X", "K", _t(300))]
    # Oji rows at 0 and 10 are followed by an Oji row < 60 s later -> dropped;
    # Jaya's only row and Oji's 20 / 300 rows stay.
    assert ps.dedupe_flaps(rows, 60) == [rows[1], rows[3], rows[4]]
    # boundary: a gap of exactly 60 s is NOT a flap
    pair = [("Oji", "K", "K", _t(0)), ("Oji", "K", "K", _t(60))]
    assert ps.dedupe_flaps(pair, 60) == pair
    assert ps.dedupe_flaps(pair, 61) == [pair[1]]
    assert ps.dedupe_flaps(rows, 0) == rows


def test_occupancy_skill_constant_has_zero_skill():
    pairs = [(0.1, 1)] + [(0.1, 0)] * 9
    got = ps.occupancy_skill(pairs)
    assert got["base_rate"] == 0.1
    assert got["base_rate_brier"] == 0.09
    assert got["brier_skill"] == 0.0
    assert got["baseline_hit_rate"] == 90.0
    assert got["hit_rate_skill_pct"] == 0.0


def test_occupancy_skill_perfect_and_degenerate():
    got = ps.occupancy_skill([(1.0, 1), (0.0, 0), (0.0, 0), (0.0, 0)])
    assert got["brier_skill"] == 1.0
    assert got["hit_rate_skill_pct"] == 25.0        # 100% vs majority 75%
    assert ps.occupancy_skill([(0.2, 0), (0.3, 0)])["brier_skill"] is None


# ---------------------------------------------------------------------------
# Bayesian accuracy stats carry the baseline
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bayesian_accuracy_stats_report_baseline():
    class _DB:
        async def get_prediction_results(self, days=7, prediction_type=""):
            return [{"predicted_probability": 0.1, "actual_occupied": 1}] + [
                {"predicted_probability": 0.1, "actual_occupied": 0}] * 9

    pred = bp.BayesianPredictor(SimpleNamespace(data={}))
    pred._database = _DB()
    stats = await pred.get_accuracy_stats(days=7)
    assert stats["hit_rate"] == 90.0               # the "94%"-shaped headline
    assert stats["baseline_hit_rate"] == 90.0      # ... equals the constant
    assert stats["hit_rate_skill_pct"] == 0.0
    assert stats["brier_skill"] == 0.0
    assert stats["base_rate"] == 0.1

    ent = sensor.BayesianPredictionAccuracySensor(
        SimpleNamespace(data={DOMAIN: {"bayesian_predictor": pred}}),
        SimpleNamespace())
    await ent.async_update()
    attrs = ent.extra_state_attributes
    assert attrs["baseline_hit_rate_pct"] == 90.0
    assert attrs["hit_rate_skill_pct"] == 0.0
    assert attrs["brier_skill"] == 0.0


# ---------------------------------------------------------------------------
# Real DB: accuracy sensors and the Optimization read
# ---------------------------------------------------------------------------

_INSERT = ("INSERT INTO prediction_results (room_id, prediction_timestamp, "
           "prediction_type, predicted_value, confidence, actual_value, "
           "error_value, person_id) VALUES (?, ?, 'next_room', ?, 0.5, ?, 0.25, ?)")


def _recent(sec):
    return (datetime.now(UTC) - timedelta(hours=2)
            + timedelta(seconds=sec)).isoformat()


def _row(person, top, actual, sec):
    return (top, _recent(sec), '{"top": "%s", "alternatives": []}' % top,
            actual, person)


async def _seeded(tmp_path):
    db = make_real_db(tmp_path)
    assert await db.initialize()
    seed(db, _INSERT, [
        _row("Oji", "Kitchen", "Kitchen", 0),
        _row("Oji", "Kitchen", "Bath", 10),
        _row("Oji", "Kitchen", "Kitchen", 20),
        _row("Oji", "Bath", "Kitchen", 300),
        _row("Jaya", "Bed", "Bed", 0),
        _row("Jaya", "Bath", "Bed", 400),
    ])
    return db


@pytest.mark.asyncio
async def test_person_accuracy_sensor_skill(tmp_path):
    db = await _seeded(tmp_path)
    ent = sensor.PersonNextRoomAccuracySensor(
        SimpleNamespace(data={DOMAIN: {"database": db}}), SimpleNamespace(), "Oji")
    await ent.async_update()
    attrs = ent.extra_state_attributes
    assert ent.native_value == 50.0
    # raw: 2/4 hits; usual room Kitchen 3/4
    assert attrs["baseline_top1_hit_rate_pct"] == 75.0
    assert attrs["skill_pct"] == -25.0
    # dedup 60 s: the rows at +0 and +10 are flaps -> rows +20 (hit), +300
    assert attrs["predictions_dedup"] == 2
    assert attrs["top1_hit_rate_dedup_pct"] == 50.0
    assert attrs["baseline_top1_hit_rate_dedup_pct"] == 100.0
    assert attrs["skill_dedup_pct"] == -50.0


@pytest.mark.asyncio
async def test_house_accuracy_sensor_skill(tmp_path):
    db = await _seeded(tmp_path)
    ent = sensor.HouseNextRoomAccuracySensor(
        SimpleNamespace(data={DOMAIN: {"database": db}}), SimpleNamespace())
    await ent.async_update()
    attrs = ent.extra_state_attributes
    assert ent.native_value == 50.0                  # 3/6
    assert attrs["baseline_top1_hit_rate_pct"] == 83.3   # (3 + 2) / 6
    assert attrs["skill_pct"] == -33.3
    # dedup drops Oji +0 / +10 -> 4 rows: hits Oji +20, Jaya +0 = 2/4;
    # baseline Oji Kitchen 2 + Jaya Bed 2 = 4/4 -> skill -50.0
    assert attrs["predictions_dedup"] == 4
    assert attrs["skill_dedup_pct"] == -50.0


@pytest.mark.asyncio
async def test_optimizer_next_room_read_reports_skill(tmp_path):
    """D7 producer: the Optimization read pools persons and measures the
    usual-room baseline on the same rows (same helper)."""
    db = await _seeded(tmp_path)
    fake_self = SimpleNamespace(hass=SimpleNamespace(data={DOMAIN: {"database": db}}))
    got = await opt.OptimizationCoordinator._read_next_room_accuracy(fake_self, days=7)
    assert got["total_predictions"] == 6
    assert got["top1_hit_rate"] == 50.0
    assert got["baseline_top1_hit_rate"] == 83.3
    assert got["skill_pct"] == -33.3
