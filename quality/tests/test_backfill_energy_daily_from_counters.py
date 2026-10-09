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
    val, kind = mod._statistics_sum_at_boundary(recorder, 1, b)
    assert val == 1010.0
    assert kind == "exact"


def test_statistics_sum_at_boundary_missing_returns_none(recorder, tz):
    # offset=3 was skipped for both counters.
    b = _dt.datetime(2026, 7, 4, 0, 0, tzinfo=tz)
    val, kind = mod._statistics_sum_at_boundary(recorder, 1, b)
    assert val is None
    assert kind == "missing"


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


# ---------------------------------------------------------------------------
# CRITICAL: one-sided None must not clobber a live column.
# ---------------------------------------------------------------------------


def test_apply_writes_one_sided_none_preserves_other_column(tmp_path):
    """repro from reviewer: existing import=10, export=1; a backfill row
    (import=None, export=2.0) must NOT write import=0.0 — it must leave
    import at 10 and update only export."""
    ura_path = tmp_path / "ura.db"
    conn = sqlite3.connect(ura_path)
    conn.executescript(URA_ENERGY_DAILY_DDL)
    conn.execute(
        "INSERT INTO energy_daily (date, import_kwh, export_kwh) "
        "VALUES ('2026-07-01', 10.0, 1.0)"
    )
    conn.commit()
    conn.close()

    row = mod.DayRow(
        date="2026-07-01", import_kwh=None, export_kwh=2.0, source="recorder",
    )
    ura = sqlite3.connect(ura_path)
    existing = mod._read_existing(ura, ["2026-07-01"])
    ura.close()
    mod._apply_writes(str(ura_path), [row], existing, force_overwrite=False)

    conn = sqlite3.connect(ura_path)
    r = conn.execute(
        "SELECT import_kwh, export_kwh, billing_source FROM energy_daily "
        "WHERE date='2026-07-01'"
    ).fetchone()
    conn.close()
    assert r == (10.0, 2.0, "recorder_backfill")


def test_apply_writes_one_sided_none_insert_leaves_null(tmp_path):
    """INSERT path for a brand-new row with export=None must leave
    export_kwh NULL (not 0.0)."""
    ura_path = tmp_path / "ura.db"
    conn = sqlite3.connect(ura_path)
    conn.executescript(URA_ENERGY_DAILY_DDL)
    conn.commit()
    conn.close()
    row = mod.DayRow(
        date="2026-07-01", import_kwh=5.0, export_kwh=None, source="recorder",
    )
    mod._apply_writes(str(ura_path), [row], existing={}, force_overwrite=False)
    conn = sqlite3.connect(ura_path)
    r = conn.execute(
        "SELECT import_kwh, export_kwh FROM energy_daily WHERE date='2026-07-01'"
    ).fetchone()
    conn.close()
    assert r == (5.0, None)


# ---------------------------------------------------------------------------
# HIGH: tz is DST-aware; boundaries land at TRUE local midnight across
# both DST transitions. 2026-03-08 (spring forward: 23h day),
# 2026-11-01 (fall back: 25h day) in America/Chicago.
# ---------------------------------------------------------------------------


def _mk_recorder_with_midnight_rows(tz_name: str, dates_sums: dict):
    """Build a recorder with one 'sum' row per listed local-midnight date.
    Keys are ISO-date strings in the TZ."""
    from zoneinfo import ZoneInfo
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
    tz = ZoneInfo(tz_name)
    for iso, s in dates_sums.items():
        d = _dt.date.fromisoformat(iso)
        midnight = _dt.datetime.combine(d, _dt.time.min, tzinfo=tz)
        conn.execute(
            "INSERT INTO statistics (metadata_id, start_ts, state, sum) "
            "VALUES (1, ?, ?, ?)",
            (midnight.timestamp(), 0.0, s),
        )
        conn.execute(
            "INSERT INTO statistics (metadata_id, start_ts, state, sum) "
            "VALUES (2, ?, ?, ?)",
            (midnight.timestamp(), 0.0, s / 10.0),
        )
    conn.commit()
    return conn


def test_dst_spring_forward_boundary_lands_at_local_midnight():
    """America/Chicago spring-forward: 2026-03-08 is a 23h day. The
    boundary at 2026-03-09 00:00 local must be EXACTLY 23*3600s after
    2026-03-08 00:00 local, and we must find the row written at
    local-midnight (not UTC-midnight)."""
    from zoneinfo import ZoneInfo
    rec = _mk_recorder_with_midnight_rows(
        "America/Chicago",
        {"2026-03-07": 100.0, "2026-03-08": 110.0, "2026-03-09": 123.0},
    )
    tz = ZoneInfo("America/Chicago")
    b_before = _dt.datetime(2026, 3, 8, 0, 0, tzinfo=tz)
    b_after = _dt.datetime(2026, 3, 9, 0, 0, tzinfo=tz)
    # Verify the 23-hour day.
    assert b_after.timestamp() - b_before.timestamp() == 23 * 3600
    val_before, kind_before = mod._statistics_sum_at_boundary(rec, 1, b_before)
    val_after, kind_after = mod._statistics_sum_at_boundary(rec, 1, b_after)
    assert kind_before == "exact" and kind_after == "exact"
    assert val_before == 110.0 and val_after == 123.0

    rows = mod.compute_rows(
        rec, IMPORT_ENTITY, EXPORT_ENTITY,
        _dt.date(2026, 3, 7), _dt.date(2026, 3, 8), tz="America/Chicago",
    )
    by = {r.date: r for r in rows}
    assert by["2026-03-07"].import_kwh == 10.0
    assert by["2026-03-08"].import_kwh == 13.0  # 23h day, sum - sum


def test_dst_fall_back_boundary_lands_at_local_midnight():
    """America/Chicago fall-back: 2026-11-01 is a 25h day."""
    from zoneinfo import ZoneInfo
    rec = _mk_recorder_with_midnight_rows(
        "America/Chicago",
        {"2026-10-31": 200.0, "2026-11-01": 215.0, "2026-11-02": 245.0},
    )
    tz = ZoneInfo("America/Chicago")
    b_before = _dt.datetime(2026, 11, 1, 0, 0, tzinfo=tz)
    b_after = _dt.datetime(2026, 11, 2, 0, 0, tzinfo=tz)
    assert b_after.timestamp() - b_before.timestamp() == 25 * 3600

    rows = mod.compute_rows(
        rec, IMPORT_ENTITY, EXPORT_ENTITY,
        _dt.date(2026, 10, 31), _dt.date(2026, 11, 1), tz="America/Chicago",
    )
    by = {r.date: r for r in rows}
    assert by["2026-10-31"].import_kwh == 15.0
    assert by["2026-11-01"].import_kwh == 30.0  # 25h day, sum - sum


# ---------------------------------------------------------------------------
# MEDIUM: unit scaling (kWh pass-through, Wh scaled, unknown refuses).
# ---------------------------------------------------------------------------


def _mk_unit_recorder(unit: str):
    conn = sqlite3.connect(":memory:")
    for stmt in RECORDER_DDL.strip().split(";"):
        if stmt.strip():
            conn.execute(stmt)
    conn.execute(
        "INSERT INTO statistics_meta (id, statistic_id, source, "
        "unit_of_measurement, has_sum, mean_type) VALUES "
        "(1, ?, 'recorder', ?, 1, 0), (2, ?, 'recorder', 'kWh', 1, 0)",
        (IMPORT_ENTITY, unit, EXPORT_ENTITY),
    )
    return conn


def test_resolve_metadata_kwh_scale_one():
    conn = _mk_unit_recorder("kWh")
    r = mod._resolve_metadata(conn, IMPORT_ENTITY)
    assert r is not None and r[1] == 1.0


def test_resolve_metadata_wh_scale_thousandth():
    conn = _mk_unit_recorder("Wh")
    r = mod._resolve_metadata(conn, IMPORT_ENTITY)
    assert r is not None and r[1] == 0.001


def test_resolve_metadata_unknown_unit_refused(capsys):
    conn = _mk_unit_recorder("MJ")
    r = mod._resolve_metadata(conn, IMPORT_ENTITY)
    assert r is None
    err = capsys.readouterr().err
    assert "unknown unit" in err


def test_compute_rows_scales_wh_to_kwh(tz):
    """A Wh-reporting counter with sum deltas in Wh must be returned in
    kWh (×0.001)."""
    conn = sqlite3.connect(":memory:")
    for stmt in RECORDER_DDL.strip().split(";"):
        if stmt.strip():
            conn.execute(stmt)
    conn.execute(
        "INSERT INTO statistics_meta (id, statistic_id, source, "
        "unit_of_measurement, has_sum, mean_type) VALUES "
        "(1, ?, 'recorder', 'Wh', 1, 0), (2, ?, 'recorder', 'kWh', 1, 0)",
        (IMPORT_ENTITY, EXPORT_ENTITY),
    )
    day0 = _dt.date(2026, 7, 1)

    def midnight(d):
        return _dt.datetime.combine(d, _dt.time.min, tzinfo=tz).timestamp()

    # import counter: Wh — sum goes 1_000_000 → 1_010_000 → 1_030_000
    # (i.e. 10 kWh then 20 kWh)
    for offset, s in enumerate([1_000_000.0, 1_010_000.0, 1_030_000.0]):
        d = day0 + _dt.timedelta(days=offset)
        conn.execute(
            "INSERT INTO statistics (metadata_id, start_ts, state, sum) "
            "VALUES (1, ?, 0.0, ?)",
            (midnight(d), s),
        )
    # export counter: kWh — 100 → 101 → 103
    for offset, s in enumerate([100.0, 101.0, 103.0]):
        d = day0 + _dt.timedelta(days=offset)
        conn.execute(
            "INSERT INTO statistics (metadata_id, start_ts, state, sum) "
            "VALUES (2, ?, 0.0, ?)",
            (midnight(d), s),
        )
    conn.commit()
    rows = mod.compute_rows(
        conn, IMPORT_ENTITY, EXPORT_ENTITY,
        _dt.date(2026, 7, 1), _dt.date(2026, 7, 2), tz=tz,
    )
    by = {r.date: r for r in rows}
    assert by["2026-07-01"].import_kwh == 10.0  # 10_000 Wh → 10 kWh
    assert by["2026-07-02"].import_kwh == 20.0  # 20_000 Wh → 20 kWh
    assert by["2026-07-01"].export_kwh == 1.0   # already kWh
    assert by["2026-07-02"].export_kwh == 2.0
