#!/usr/bin/env python3
"""Backfill `energy_daily` import/export kWh from HA recorder counter history.

PLANNING_ec_billing_emporia_counters §D8 (REV 5 — statistics-sourced).

Source of truth
---------------
The import/export counters are `state_class = total` daily-reset sensors
with `last_reset` on local midnight. The recorder keeps TWO relevant
surfaces for them:

* `states` — purged after ~7 days on this install. **Unusable for a
  June→Sept backfill.** Additionally on this HA version the `states.entity_id`
  column is `CHAR(0)` (dead) and entity resolution MUST go through
  `states_meta.metadata_id` — the old `WHERE entity_id = ?` query matched
  zero rows, which is why the previous backfill printed every day as
  `SKIP(novalue)`.
* `statistics` — hourly rows retained indefinitely. Each row carries
  `state` (counter reading at hour start) AND `sum` (HA's monotonic
  integral since the statistic began — NOT reset by the daily zero).

Because `sum` is monotonic across the midnight reset, the robust daily
total is:

    daily_kwh = sum(local_midnight_next_day) - sum(local_midnight_this_day)

Live sanity check against known bill-period totals (import, metadata_id 98):
    07-25 → 08-25 : 30171.91 - 28088.41 = 2083.50 kWh (bill ~2063 w/ gap)
    08-25 → 09-24 : 33619.69 - 30171.91 = 3447.78 kWh (bill ~3480)

Safety contract (unchanged)
---------------------------
* Dry-run by default; `--apply` writes.
* Per-column BEFORE / AFTER table.
* UPDATE only `import_kwh`, `export_kwh`, `billing_source` on existing
  rows — never touches consumption/solar/cost/prediction columns.
* INSERT new rows with only those three columns + date.
* Idempotent (keyed on date).
* A row with live `consumption_kwh` or `solar_production_kwh` is
  `SKIP(live>backfill)` unless `--force-overwrite`.

Usage:
    python3 scripts/backfill_energy_daily_from_counters.py \
        --ura-db <path> --recorder-db <path> \
        --import-entity sensor.mains_vue_3_mainsfromgrid_energy_today \
        --export-entity sensor.main_panels_mains_vue_3_mainstogrid_energy_today \
        --from 2026-06-01 --to 2026-10-08
"""
from __future__ import annotations

import argparse
import datetime as _dt
import sqlite3
import sys
from dataclasses import dataclass


# Window (seconds) around the exact local-midnight boundary within which
# we will accept a statistics row. Statistics are UTC-hour-aligned; on
# whole-hour TZ offsets local midnight IS an hour boundary, so the exact
# row almost always exists. A small window lets us tolerate a one-off
# DST transition or a missing row by picking the nearest-prior sample.
BOUNDARY_WINDOW_S = 90 * 60  # 90 minutes


@dataclass
class DayRow:
    date: str
    import_kwh: float | None
    export_kwh: float | None
    source: str  # "recorder" | "skip_novalue"


def _iter_dates(start: _dt.date, end: _dt.date):
    cur = start
    while cur <= end:
        yield cur
        cur += _dt.timedelta(days=1)


def _resolve_metadata_id(
    conn: sqlite3.Connection, entity_id: str
) -> int | None:
    try:
        cur = conn.execute(
            "SELECT id FROM statistics_meta WHERE statistic_id = ?",
            (entity_id,),
        )
        row = cur.fetchone()
        return int(row[0]) if row else None
    except Exception as e:  # noqa: BLE001
        print(f"  WARN statistics_meta lookup failed for {entity_id}: {e}",
              file=sys.stderr)
        return None


def _statistics_sum_at_boundary(
    conn: sqlite3.Connection,
    metadata_id: int,
    boundary: _dt.datetime,
) -> float | None:
    """Return `sum` from the statistics row aligned to `boundary`.

    Prefers an exact-start_ts match; falls back to the latest row within
    `BOUNDARY_WINDOW_S` seconds before the boundary (never after — we
    must not pull a row from inside the day we are closing).
    """
    bts = boundary.timestamp()
    try:
        # 1. Exact boundary.
        cur = conn.execute(
            "SELECT sum FROM statistics "
            "WHERE metadata_id = ? AND start_ts = ? AND sum IS NOT NULL",
            (metadata_id, bts),
        )
        row = cur.fetchone()
        if row is not None and row[0] is not None:
            return float(row[0])

        # 2. Nearest-prior within window.
        cur = conn.execute(
            "SELECT sum FROM statistics "
            "WHERE metadata_id = ? AND start_ts <= ? AND start_ts >= ? "
            "  AND sum IS NOT NULL "
            "ORDER BY start_ts DESC LIMIT 1",
            (metadata_id, bts, bts - BOUNDARY_WINDOW_S),
        )
        row = cur.fetchone()
        if row is not None and row[0] is not None:
            return float(row[0])
    except Exception as e:  # noqa: BLE001
        print(f"  WARN statistics read failed @ {boundary}: {e}",
              file=sys.stderr)
    return None


def _daily_delta(prev_sum: float | None, next_sum: float | None) -> float | None:
    """Daily kWh from two cumulative statistics `sum` samples.

    `sum` is monotonic across the sensor's own daily reset (HA integrates
    the carried-over value), so a plain subtraction is correct. We clamp
    to >= 0 to swallow tiny FP jitter but do NOT invent a value on an
    actual regression (that's a sign of missing data; return None).
    """
    if prev_sum is None or next_sum is None:
        return None
    delta = next_sum - prev_sum
    if delta < -0.1:
        # True regression — recorder gap or statistic repair; refuse.
        return None
    return max(0.0, delta)


def _read_existing(
    ura_conn: sqlite3.Connection,
    dates: list[str],
) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    for d in dates:
        cur = ura_conn.execute(
            "SELECT date, import_kwh, export_kwh, consumption_kwh, "
            "solar_production_kwh, billing_source FROM energy_daily WHERE date = ?",
            (d,),
        )
        r = cur.fetchone()
        if r:
            rows[d] = {
                "date": r[0], "import_kwh": r[1], "export_kwh": r[2],
                "consumption_kwh": r[3], "solar_production_kwh": r[4],
                "billing_source": r[5],
            }
    return rows


def compute_rows(
    recorder_conn: sqlite3.Connection,
    import_entity: str,
    export_entity: str,
    start: _dt.date,
    end: _dt.date,
    tz: _dt.tzinfo | None = None,
) -> list[DayRow]:
    """Pure function: compute per-day DayRow list from a recorder DB
    connection. Factored out for testing."""
    if tz is None:
        tz = _dt.datetime.now().astimezone().tzinfo
    imp_meta = _resolve_metadata_id(recorder_conn, import_entity)
    exp_meta = _resolve_metadata_id(recorder_conn, export_entity)
    if imp_meta is None:
        print(f"  WARN no statistics_meta row for {import_entity}",
              file=sys.stderr)
    if exp_meta is None:
        print(f"  WARN no statistics_meta row for {export_entity}",
              file=sys.stderr)

    boundaries = [
        _dt.datetime.combine(d, _dt.time.min, tzinfo=tz)
        for d in _iter_dates(start, end + _dt.timedelta(days=1))
    ]
    imp_sum: dict[_dt.datetime, float | None] = {}
    exp_sum: dict[_dt.datetime, float | None] = {}
    for b in boundaries:
        imp_sum[b] = (
            _statistics_sum_at_boundary(recorder_conn, imp_meta, b)
            if imp_meta is not None else None
        )
        exp_sum[b] = (
            _statistics_sum_at_boundary(recorder_conn, exp_meta, b)
            if exp_meta is not None else None
        )

    rows: list[DayRow] = []
    for i in range(len(boundaries) - 1):
        day = boundaries[i].date().isoformat()
        imp_d = _daily_delta(imp_sum[boundaries[i]], imp_sum[boundaries[i + 1]])
        exp_d = _daily_delta(exp_sum[boundaries[i]], exp_sum[boundaries[i + 1]])
        src = "recorder" if (imp_d is not None or exp_d is not None) else "skip_novalue"
        rows.append(DayRow(date=day, import_kwh=imp_d, export_kwh=exp_d, source=src))
    return rows


def _apply_writes(
    ura_db_path: str,
    rows: list[DayRow],
    existing: dict[str, dict],
    force_overwrite: bool,
) -> None:
    """UPDATE only `import_kwh`/`export_kwh`/`billing_source`; INSERT
    new rows with just those three columns + date. Never INSERT OR
    REPLACE (would wipe cost/prediction columns)."""
    conn = sqlite3.connect(ura_db_path)
    try:
        for row in rows:
            live = existing.get(row.date)
            if live and (
                (live.get("consumption_kwh") is not None
                 or live.get("solar_production_kwh") is not None)
                and not force_overwrite
            ):
                print(f"  SKIP(live>backfill) {row.date}")
                continue
            if row.import_kwh is None and row.export_kwh is None:
                print(f"  SKIP(novalue) {row.date}")
                continue
            if live is not None:
                conn.execute(
                    """
                    UPDATE energy_daily
                       SET import_kwh = ?,
                           export_kwh = ?,
                           billing_source = 'recorder_backfill'
                     WHERE date = ?
                    """,
                    (row.import_kwh or 0.0, row.export_kwh or 0.0, row.date),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO energy_daily
                        (date, import_kwh, export_kwh, billing_source)
                    VALUES (?, ?, ?, 'recorder_backfill')
                    """,
                    (row.date, row.import_kwh or 0.0, row.export_kwh or 0.0),
                )
        conn.commit()
    finally:
        conn.close()


def _fmt_num(v: float | None, width: int = 12) -> str:
    """Format one numeric cell. Floats get 3dp + right-align in `width`
    columns; None is a dash. Non-numeric strings are right-aligned too.
    Fixes the prior concatenation bug ('164.722...164.722...') caused by
    `>12` not truncating a 20-digit repr."""
    if v is None:
        return f"{'—':>{width}}"
    if isinstance(v, (int, float)):
        return f"{float(v):>{width}.3f}"
    s = str(v)
    if len(s) > width:
        s = s[: width - 1] + "…"
    return f"{s:>{width}}"


def _print_table(rows: list[DayRow], existing: dict[str, dict],
                 force_overwrite: bool) -> None:
    hdr = (
        f"{'date':<12}"
        f"{'imp_before':>12}{'imp_after':>12}"
        f"{'exp_before':>12}{'exp_after':>12}"
        f"  {'cons_before':>12}{'cons_after':>12}"
        f"  {'bs_before':>18}{'bs_after':>18}  {'action':<22}"
    )
    print(hdr)
    for row in rows:
        live = existing.get(row.date, {}) or {}
        live_imp = live.get("import_kwh")
        live_exp = live.get("export_kwh")
        live_cons = live.get("consumption_kwh")
        live_bs = live.get("billing_source")
        if row.source == "skip_novalue":
            action = "SKIP(novalue)"
            after_imp, after_exp, after_cons, after_bs = (
                live_imp, live_exp, live_cons, live_bs,
            )
        elif (
            live.get("consumption_kwh") is not None
            or live.get("solar_production_kwh") is not None
        ) and not force_overwrite:
            action = "SKIP(live>backfill)"
            after_imp, after_exp, after_cons, after_bs = (
                live_imp, live_exp, live_cons, live_bs,
            )
        else:
            action = "WOULD_UPDATE" if live else "WOULD_INSERT"
            after_imp = row.import_kwh
            after_exp = row.export_kwh
            after_cons = live_cons
            after_bs = "recorder_backfill"
        print(
            f"{row.date:<12}"
            f"{_fmt_num(live_imp)}{_fmt_num(after_imp)}"
            f"{_fmt_num(live_exp)}{_fmt_num(after_exp)}"
            f"  {_fmt_num(live_cons)}{_fmt_num(after_cons)}"
            f"  {_fmt_num(live_bs, 18)}{_fmt_num(after_bs, 18)}  "
            f"{action:<22}"
        )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ura-db", required=True)
    p.add_argument("--recorder-db", required=True)
    p.add_argument("--import-entity", required=True)
    p.add_argument("--export-entity", required=True)
    p.add_argument("--from", dest="dfrom", required=True)
    p.add_argument("--to", dest="dto", required=True)
    p.add_argument("--apply", action="store_true", default=False)
    p.add_argument("--force-overwrite", action="store_true", default=False)
    args = p.parse_args(argv)

    start = _dt.date.fromisoformat(args.dfrom)
    end = _dt.date.fromisoformat(args.dto)
    if end < start:
        print("ERROR: --to is before --from", file=sys.stderr)
        return 2

    print(f"Reading recorder {args.recorder_db} …")
    rec = sqlite3.connect(f"file:{args.recorder_db}?mode=ro", uri=True)
    try:
        rows = compute_rows(
            rec, args.import_entity, args.export_entity, start, end,
        )
    finally:
        rec.close()

    ura = sqlite3.connect(args.ura_db)
    try:
        existing = _read_existing(ura, [r.date for r in rows])
    finally:
        ura.close()

    _print_table(rows, existing, args.force_overwrite)

    # Period totals footer — useful for bill reconciliation.
    tot_imp = sum((r.import_kwh or 0.0) for r in rows if r.import_kwh is not None)
    tot_exp = sum((r.export_kwh or 0.0) for r in rows if r.export_kwh is not None)
    n_novalue = sum(1 for r in rows if r.source == "skip_novalue")
    print(
        f"\nTOTAL days={len(rows)} novalue={n_novalue} "
        f"import_kwh={tot_imp:.3f} export_kwh={tot_exp:.3f}"
    )

    if args.apply:
        print("Applying UPDATE-only writes …")
        _apply_writes(args.ura_db, rows, existing, args.force_overwrite)
        print("Done.")
    else:
        print("Dry-run — no writes performed. Rerun with --apply to commit.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
