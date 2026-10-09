"""Tests for scripts/backfill_energy_daily_from_counters.py.

The fixture builds `statistics` and `statistics_meta` from DDL extracted
VERBATIM from the live HA recorder (`file:/config/home-assistant_v2.db`,
sqlite_master) — never a hand-written schema. Tests drive the real
`compute_rows` / `_statistics_sum_at_boundary` / `_daily_delta` /
`_apply_writes` functions from production source.
"""
from __future__ import annotations

import datetime as _dt
import importlib.util
import os
import pathlib
import sqlite3
import sys

import pytest


# DDL extracted via:
#   ssh ha sudo -n sqlite3 'file:/config/home-assistant_v2.db?mode=ro' \
#       "SELECT sql FROM sqlite_master WHERE name IN ('statistics','statistics_meta')"
# on 2026-10-09. Do NOT hand-edit; re-extract if HA recorder schema changes.
RECORDER_DDL = """
CREATE TABLE statistics_meta (
    id INTEGER NOT NULL,
    statistic_id VARCHAR(255),
    source VARCHAR(32),
    unit_of_measurement VARCHAR(255),
    has_mean BOOLEAN,
    has_sum BOOLEAN,
    name VARCHAR(255),
    mean_type INTEGER NOT NULL DEFAULT 0,
    unit_class VARCHAR(255),
    PRIMARY KEY (id)
);
CREATE TABLE statistics (
    id INTEGER NOT NULL,
    created CHAR(0),
    created_ts FLOAT,
    metadata_id INTEGER,
    start CHAR(0),
    start_ts FLOAT,
    mean FLOAT,
    min FLOAT,
    max FLOAT,
    last_reset CHAR(0),
    last_reset_ts FLOAT,
    state FLOAT,
    sum FLOAT,
    mean_weight FLOAT,
    PRIMARY KEY (id),
    FOREIGN KEY(metadata_id) REFERENCES statistics_meta (id) ON DELETE CASCADE
);
"""

URA_ENERGY_DAILY_DDL = """
CREATE TABLE energy_daily (
    date TEXT PRIMARY KEY,
    import_kwh REAL,
    export_kwh REAL,
    consumption_kwh REAL,
    solar_production_kwh REAL,
    import_cost REAL,
    export_credit REAL,
    net_cost REAL,
    billing_source TEXT
);
"""

IMPORT_ENTITY = "sensor.mains_vue_3_mainsfromgrid_energy_today"
EXPORT_ENTITY = "sensor.main_panels_mains_vue_3_mainstogrid_energy_today"


def _load_module():
    here = pathlib.Path(__file__).resolve()
    repo = here.parent.parent.parent  # worktree root
    path = repo / "scripts" / "backfill_energy_daily_from_counters.py"
    spec = importlib.util.spec_from_file_location("backfill_mod", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["backfill_mod"] = mod
    spec.loader.exec_module(mod)
    return mod


mod = _load_module()


@pytest.fixture
def tz():
    # Use a fixed whole-hour TZ so statistics UTC-hour alignment coincides
    # with local midnight (matches the live install's behavior).
    return _dt.timezone(_dt.timedelta(hours=-5))


@pytest.fixture
def recorder(tz):
    """Build a tiny recorder DB with 4 days of hourly rows for the
    import/export counters. Daily totals we embed:
        day0: import=10, export=1
        day1: import=20, export=2
        day2: import=0  (gap: no row at day2+1 midnight)
        day3: import=15, export=5
    """
    conn = sqlite3.connect(":memory:")
    for stmt in RECORDER_DDL.strip().split(";"):
        if stmt.strip():
            conn.execute(stmt)
    conn.execute(
        "INSERT INTO statistics_meta (id, statistic_id, source, "
        "unit_of_measurement, has_sum, mean_type) VALUES "
        "(1, ?, 'recorder', 'kWh', 1, 0), (2, ?, 'recorder', 'kWh', 1, 0)",
        (IMPORT_ENTITY, EXPORT_ENTITY),
    )

    day0 = _dt.date(2026, 7, 1)

    def _midnight(d):
        return _dt.datetime.combine(d, _dt.time.min, tzinfo=tz).timestamp()

    # Import counter: cumulative sum at midnights 0..4
    import_sums = {0: 1000.0, 1: 1010.0, 2: 1030.0, 3: 1030.0, 4: 1045.0}
    export_sums = {0: 100.0, 1: 101.0, 2: 103.0, 3: 103.0, 4: 108.0}
    for offset, s in import_sums.items():
        # skip the day2+1 (offset=3) boundary for the import counter to simulate a gap
        if offset == 3:
            continue
        d = day0 + _dt.timedelta(days=offset)
        conn.execute(
            "INSERT INTO statistics (metadata_id, start_ts, state, sum) "
            "VALUES (1, ?, ?, ?)",
            (_midnight(d), 0.0, s),
        )
    for offset, s in export_sums.items():
        if offset == 3:
            continue
        d = day0 + _dt.timedelta(days=offset)
        conn.execute(
            "INSERT INTO statistics (metadata_id, start_ts, state, sum) "
            "VALUES (2, ?, ?, ?)",
            (_midnight(d), 0.0, s),
        )
    conn.commit()
    return conn


def test_resolve_metadata_id(recorder):
    assert mod._resolve_metadata_id(recorder, IMPORT_ENTITY) == 1
    assert mod._resolve_metadata_id(recorder, EXPORT_ENTITY) == 2
    assert mod._resolve_metadata_id(recorder, "sensor.nope") is None


def test_statistics_sum_at_boundary_exact(recorder, tz):
    b = _dt.datetime(2026, 7, 2, 0, 0, tzinfo=tz)
    assert mod._statistics_sum_at_boundary(recorder, 1, b) == 1010.0


def test_statistics_sum_at_boundary_missing_returns_none(recorder, tz):
    # offset=3 was skipped for both counters.
    b = _dt.datetime(2026, 7, 4, 0, 0, tzinfo=tz)
    assert mod._statistics_sum_at_boundary(recorder, 1, b) is None


def test_daily_delta_basic():
    assert mod._daily_delta(1000.0, 1010.0) == 10.0


def test_daily_delta_none_passthrough():
    assert mod._daily_delta(None, 10.0) is None
    assert mod._daily_delta(10.0, None) is None


def test_daily_delta_regression_returns_none():
    # A real backwards jump > 0.1 is a recorder gap, not a reset.
    assert mod._daily_delta(1000.0, 500.0) is None


def test_daily_delta_tiny_fp_jitter_clamped():
    assert mod._daily_delta(1000.0, 999.99) == 0.0


def test_compute_rows_e2e(recorder, tz):
    rows = mod.compute_rows(
        recorder, IMPORT_ENTITY, EXPORT_ENTITY,
        _dt.date(2026, 7, 1), _dt.date(2026, 7, 4), tz=tz,
    )
    assert len(rows) == 4
    by = {r.date: r for r in rows}
    # day0: 1010-1000 = 10
    assert by["2026-07-01"].import_kwh == 10.0
    assert by["2026-07-01"].export_kwh == 1.0
    # day1: 1030-1010 = 20
    assert by["2026-07-02"].import_kwh == 20.0
    # day2: next-day boundary missing → None → skip_novalue
    assert by["2026-07-03"].import_kwh is None
    assert by["2026-07-03"].source == "skip_novalue"
    # day3: boundary at day4 exists (1045), but boundary at day3 missing → None
    assert by["2026-07-04"].import_kwh is None


def test_apply_writes_update_only_preserves_cost_columns(tmp_path, recorder, tz):
    ura_path = tmp_path / "ura.db"
    conn = sqlite3.connect(ura_path)
    conn.executescript(URA_ENERGY_DAILY_DDL)
    # Seed an existing row with cost columns populated — the backfill
    # MUST NOT wipe them.
    conn.execute(
        "INSERT INTO energy_daily (date, import_cost, export_credit, net_cost) "
        "VALUES ('2026-07-01', 7.77, 1.23, 6.54)"
    )
    conn.commit()
    conn.close()

    rows = mod.compute_rows(
        recorder, IMPORT_ENTITY, EXPORT_ENTITY,
        _dt.date(2026, 7, 1), _dt.date(2026, 7, 2), tz=tz,
    )
    ura = sqlite3.connect(ura_path)
    existing = mod._read_existing(ura, [r.date for r in rows])
    ura.close()
    mod._apply_writes(str(ura_path), rows, existing, force_overwrite=False)

    conn = sqlite3.connect(ura_path)
    r = conn.execute(
        "SELECT import_kwh, export_kwh, import_cost, export_credit, net_cost, "
        "billing_source FROM energy_daily WHERE date='2026-07-01'"
    ).fetchone()
    conn.close()
    assert r == (10.0, 1.0, 7.77, 1.23, 6.54, "recorder_backfill")


def test_apply_writes_skips_live_consumption(tmp_path, recorder, tz):
    ura_path = tmp_path / "ura.db"
    conn = sqlite3.connect(ura_path)
    conn.executescript(URA_ENERGY_DAILY_DDL)
    conn.execute(
        "INSERT INTO energy_daily (date, consumption_kwh) VALUES ('2026-07-01', 42.0)"
    )
    conn.commit()
    conn.close()
    rows = mod.compute_rows(
        recorder, IMPORT_ENTITY, EXPORT_ENTITY,
        _dt.date(2026, 7, 1), _dt.date(2026, 7, 1), tz=tz,
    )
    ura = sqlite3.connect(ura_path)
    existing = mod._read_existing(ura, [r.date for r in rows])
    ura.close()
    mod._apply_writes(str(ura_path), rows, existing, force_overwrite=False)
    conn = sqlite3.connect(ura_path)
    r = conn.execute(
        "SELECT import_kwh, consumption_kwh FROM energy_daily WHERE date='2026-07-01'"
    ).fetchone()
    conn.close()
    # import_kwh untouched (NULL), consumption_kwh preserved.
    assert r == (None, 42.0)


def test_apply_writes_idempotent(tmp_path, recorder, tz):
    ura_path = tmp_path / "ura.db"
    conn = sqlite3.connect(ura_path)
    conn.executescript(URA_ENERGY_DAILY_DDL)
    conn.commit()
    conn.close()
    rows = mod.compute_rows(
        recorder, IMPORT_ENTITY, EXPORT_ENTITY,
        _dt.date(2026, 7, 1), _dt.date(2026, 7, 2), tz=tz,
    )
    ura = sqlite3.connect(ura_path)
    existing = mod._read_existing(ura, [r.date for r in rows])
    ura.close()
    mod._apply_writes(str(ura_path), rows, existing, force_overwrite=False)
    # Second apply shouldn't double-count.
    ura = sqlite3.connect(ura_path)
    existing2 = mod._read_existing(ura, [r.date for r in rows])
    ura.close()
    mod._apply_writes(str(ura_path), rows, existing2, force_overwrite=False)
    conn = sqlite3.connect(ura_path)
    r = conn.execute(
        "SELECT import_kwh FROM energy_daily WHERE date='2026-07-01'"
    ).fetchone()
    conn.close()
    assert r[0] == 10.0


def test_fmt_num_no_concatenation():
    # The old `>12` spec would output a 20-digit repr unpadded next to
    # the next column, producing '164.722...164.722...'. Guard the fix.
    s = mod._fmt_num(164.72222222222222222)
    assert len(s) == 12
    assert s.strip() == "164.722"


def test_fmt_num_none():
    assert mod._fmt_num(None).strip() == "—"
