"""ENERGY-HISTORY-KW-SUMMED-AS-KWH-1: energy_history stores instantaneous kW
snapshots (~15 min); aggregation queries must integrate kW x interval, not
SUM raw kW (~4x inflation).

Schema comes from production: UniversalRoomDatabase.initialize() runs the
real CREATE TABLE + migrations against a temp file. Rows are seeded with
sqlite3; the queries under test are the real production methods.
"""

import asyncio
import os
import sqlite3
import tempfile
from datetime import datetime, timedelta

import pytest

# Reuse the HA module mocks + _make_db from the resilience suite.
from test_database_resilience import _make_db  # noqa: E402


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _seed(db_path, rows):
    conn = sqlite3.connect(db_path)
    for ts, gi, exp, prod, temp in rows:
        conn.execute(
            "INSERT INTO energy_history (timestamp, grid_import, grid_import_2, "
            "solar_export, solar_production, outside_temp, rooms_occupied, "
            "day_of_week, hour_of_day, is_weekend) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (ts.isoformat(), gi, gi, exp, prod, temp, 2,
             ts.weekday(), ts.hour, ts.weekday() >= 5),
        )
    conn.commit()
    conn.close()


@pytest.fixture
def db():
    with tempfile.TemporaryDirectory() as tmp:
        d = _make_db(tmp)
        _run(d.initialize())
        yield d


# 2026-09-28 is a Monday.
_DAY = datetime(2026, 9, 28, 0, 3, 54, 259747)


def _day_rows(day_start, gi_kw, exp_kw=0.0, prod_kw=0.0, temp=80.0, n=96):
    """n samples at a 15-min cadence starting at day_start."""
    return [
        (day_start + timedelta(minutes=15 * i), gi_kw, exp_kw, prod_kw, temp)
        for i in range(n)
    ]


def test_date_range_integrates_kw_to_kwh(db):
    """96 x 4 kW samples at 15 min = 96 kWh (raw SUM would be 384)."""
    _seed(db.db_file, _day_rows(_DAY, 4.0, exp_kw=1.0, prod_kw=2.0))
    out = _run(db.get_energy_for_date_range(
        _DAY - timedelta(minutes=1), _DAY + timedelta(days=1)))
    # 95 intervals of exactly 0.25 h + newest row at nominal 0.25 h.
    assert out["grid_import"] == pytest.approx(96.0, abs=1e-6)
    assert out["solar_export"] == pytest.approx(24.0, abs=1e-6)
    assert out["solar_production"] == pytest.approx(48.0, abs=1e-6)
    assert out["net_energy"] == pytest.approx(72.0, abs=1e-6)
    assert out["record_count"] == 96


def test_gap_falls_back_to_nominal(db):
    """A 3 h write gap (HA restart) credits the sample only its nominal
    0.25 h slot -- never the whole gap."""
    rows = [
        (_DAY, 2.0, 0.0, 0.0, 80.0),
        (_DAY + timedelta(hours=3), 2.0, 0.0, 0.0, 80.0),
        (_DAY + timedelta(hours=3, minutes=15), 2.0, 0.0, 0.0, 80.0),
    ]
    _seed(db.db_file, rows)
    out = _run(db.get_energy_for_date_range(
        _DAY - timedelta(minutes=1), _DAY + timedelta(hours=4)))
    # 2 kW * (0.25 gap->nominal + 0.25 real + 0.25 nominal tail) = 1.5 kWh
    assert out["grid_import"] == pytest.approx(1.5, abs=1e-6)


def test_interval_uses_next_row_outside_filter(db):
    """dt is computed against the true next sample even when the WHERE
    window excludes it (window evaluated before the filter)."""
    rows = [
        (_DAY, 4.0, 0.0, 0.0, 80.0),
        (_DAY + timedelta(minutes=10), 4.0, 0.0, 0.0, 80.0),
    ]
    _seed(db.db_file, rows)
    out = _run(db.get_energy_for_date_range(
        _DAY - timedelta(minutes=1), _DAY + timedelta(minutes=1)))
    # Only the first row is in range; its interval is 10 min -> 4 * 1/6
    assert out["grid_import"] == pytest.approx(4.0 / 6.0, abs=1e-6)


def test_similar_days_daily_kwh(db):
    """Per-day totals are kWh, and grid_import_2 (duplicate of grid_import
    on this install) is not added in."""
    rows = []
    for w in range(3):
        rows += _day_rows(_DAY + timedelta(days=7 * w), 4.0 + w, exp_kw=0.5)
    _seed(db.db_file, rows)
    out = _run(db.get_energy_for_similar_days(
        day_of_week=0, temp_low=70, temp_high=90, limit=10))
    by_date = {r["date"]: r for r in out}
    assert len(by_date) == 3
    for w in range(3):
        d = (_DAY + timedelta(days=7 * w)).date().isoformat()
        assert by_date[d]["grid_import"] == pytest.approx(24.0 * (4.0 + w), abs=1e-6)
        assert by_date[d]["solar_export"] == pytest.approx(12.0, abs=1e-6)
        assert by_date[d]["net_energy"] == pytest.approx(24.0 * (4.0 + w) - 12.0, abs=1e-6)


def test_predict_energy_tomorrow_is_kwh(db, monkeypatch):
    """End-to-end: predict_energy('tomorrow') averages daily kWh.
    Days: 96, 120, 144 kWh grid, 12 kWh export -> net mean 108."""
    rows = []
    for w in range(3):
        rows += _day_rows(_DAY + timedelta(days=7 * w), 4.0 + w, exp_kw=0.5)
    _seed(db.db_file, rows)

    import custom_components.universal_room_automation.database as dbmod

    class _FakeDT(datetime):
        @classmethod
        def utcnow(cls):
            # Sunday -> tomorrow is Monday (weekday 0)
            return datetime(2026, 10, 18, 12, 0, 0)

    monkeypatch.setattr(dbmod, "datetime", _FakeDT)

    async def _days():
        return 30
    db.get_days_of_energy_data = _days
    value, _conf = _run(db.predict_energy("tomorrow", forecast_temp=80.0))
    assert value == pytest.approx(108.0, abs=0.05)
