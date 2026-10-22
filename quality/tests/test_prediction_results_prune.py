"""prediction_results prune covers every type (PREDICT-MODEL-DWELL-MIGRATION-1
D5). Real DB from database.py's own DDL; the real prune DAO; literals for the
retention (not the imported constant)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from occ_dwell_helpers import fetch, make_real_db, real_package, seed


@pytest.fixture(autouse=True, scope="module")
def _real_ura_package():
    import importlib

    global nm
    with real_package():
        nm = importlib.import_module(
            "custom_components.universal_room_automation.nightly_maintenance")
        yield


_INSERT = ("INSERT INTO prediction_results (room_id, prediction_timestamp, "
           "prediction_type, predicted_value) VALUES (?, ?, ?, ?)")


def _iso(days_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


async def _db(tmp_path):
    db = make_real_db(tmp_path)
    assert await db.initialize()
    await db.start_write_worker()
    return db


@pytest.mark.asyncio
async def test_prunes_all_types(tmp_path):
    db = await _db(tmp_path)
    try:
        seed(db, _INSERT, [
            ("Kitchen", _iso(60), "bayesian_occupancy", "0.1"),
            ("Oji", _iso(60), "next_room", '{"top": "Kitchen"}'),
            ("E1", _iso(60), "dwell_share", "0.25"),
            ("Kitchen", _iso(1), "bayesian_occupancy", "0.1"),
            ("Oji", _iso(1), "next_room", '{"top": "Kitchen"}'),
            ("E1", _iso(1), "dwell_share", "0.25"),
        ])
        deleted = await db.prune_prediction_results(days=45)
    finally:
        await db.stop_write_worker()
    assert deleted == 3
    left = fetch(db, "SELECT prediction_type FROM prediction_results "
                     "ORDER BY prediction_type")
    assert left == [("bayesian_occupancy",), ("dwell_share",), ("next_room",)]


@pytest.mark.asyncio
async def test_keeps_rows_inside_retention(tmp_path):
    db = await _db(tmp_path)
    try:
        seed(db, _INSERT, [
            ("Oji", _iso(44), "next_room", "{}"),     # inside 45 d: kept
            ("Oji", _iso(46), "next_room", "{}"),     # outside: pruned
        ])
        deleted = await db.prune_prediction_results(days=45)
    finally:
        await db.stop_write_worker()
    assert deleted == 1
    assert len(fetch(db, "SELECT 1 FROM prediction_results")) == 1


@pytest.mark.asyncio
async def test_batching_unchanged(tmp_path):
    db = await _db(tmp_path)
    try:
        seed(db, _INSERT, [("Oji", _iso(90), "next_room", "{}")] * 5)
        deleted = await db.prune_prediction_results(days=45, batch_size=2)
    finally:
        await db.stop_write_worker()
    assert deleted == 5
    assert fetch(db, "SELECT count(*) FROM prediction_results") == [(0,)]


def test_nightly_op_uses_45_day_retention():
    ops = {name: (method, kw) for name, method, kw in nm.nightly_cleanup_ops()}
    assert ops["predictions"] == ("prune_prediction_results", {"days": 45})
