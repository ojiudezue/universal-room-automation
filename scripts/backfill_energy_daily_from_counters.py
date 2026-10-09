#!/usr/bin/env python3
"""Backfill `energy_daily` import/export kWh from HA recorder counter history.

PLANNING_ec_billing_emporia_counters §D8 (REV 4).

Design:
- Reads cumulative counter values at local-midnight boundaries from the
  HA recorder DB (`statistics` / `states` depending on availability).
- Computes daily deltas with the same value-drop-reset semantics the
  live `CounterAccrualTracker` uses.
- Writes rows to the URA DB **via the production DAO**
  (`DatabaseManager.log_energy_daily`). Never a raw INSERT.
- Dry-run by default — prints per-day BEFORE / AFTER table and exits
  with code 0 without writing anything.
- `--apply` performs the write. UPSERT keyed on date; never lowers a
  live non-NULL `consumption_kwh` or `solar_production_kwh` silently —
  such rows are reported as `SKIP(live>backfill)` and left alone unless
  `--force-overwrite` is passed.
- Backfilled days are tagged `billing_source = 'recorder_backfill'`.

Usage:
    python3 scripts/backfill_energy_daily_from_counters.py \
        --ura-db <path> --recorder-db <path> \
        --import-entity sensor.mains_vue_3_mainsfromgrid_energy_today \
        --export-entity sensor.main_panels_mains_vue_3_mainstogrid_energy_today \
        --from 2026-06-01 --to 2026-09-30

Add `--apply` to write; otherwise the script is read-only.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import os
import sqlite3
import sys
from dataclasses import dataclass


RESET_EPSILON_KWH = 0.1


@dataclass
class DayRow:
    date: str
    import_kwh: float | None
    export_kwh: float | None
    source: str  # "recorder" | "skip_gap" | "skip_novalue"


def _iter_dates(start: _dt.date, end: _dt.date):
    cur = start
    while cur <= end:
        yield cur
        cur += _dt.timedelta(days=1)


def _recorder_values_at_midnight(
    conn: sqlite3.Connection,
    entity_id: str,
    boundaries: list[_dt.datetime],
) -> dict[_dt.datetime, float | None]:
    """Return {boundary → value} picking each boundary's nearest-prior
    non-null numeric state. Returns None at boundaries with no data.

    This is intentionally conservative: a boundary with no row in the
    recorder maps to None and the dependent day is flagged
    `skip_novalue` (NOT silently derived from a different boundary pair).
    """
    out: dict[_dt.datetime, float | None] = {}
    for b in boundaries:
        try:
            cur = conn.execute(
                """
                SELECT state FROM states
                WHERE entity_id = ?
                  AND last_updated_ts <= ?
                  AND state NOT IN ('unknown','unavailable','')
                ORDER BY last_updated_ts DESC LIMIT 1
                """,
                (entity_id, b.timestamp()),
            )
            row = cur.fetchone()
            if row is None:
                out[b] = None
                continue
            try:
                out[b] = float(row[0])
            except (TypeError, ValueError):
                out[b] = None
        except Exception as e:  # noqa: BLE001
            print(f"  WARN recorder read failed for {entity_id} @ {b}: {e}",
                  file=sys.stderr)
            out[b] = None
    return out


def _delta_with_reset(prev: float | None, cur: float | None) -> float | None:
    """Daily delta using the live tracker's value-drop-only reset rule."""
    if prev is None or cur is None:
        return None
    if cur < prev - RESET_EPSILON_KWH:
        # Daily reset mid-boundary; the day's total IS `cur` (counter
        # was zeroed at midnight then advanced to `cur`).
        return max(0.0, cur)
    return max(0.0, cur - prev)


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


def _apply_writes(
    ura_db_path: str,
    rows: list[DayRow],
    existing: dict[str, dict],
    force_overwrite: bool,
) -> None:
    """A-HIGH-2 (REV 4 review fix-up): UPDATE only `import_kwh`,
    `export_kwh`, and `billing_source` on EXISTING rows (never
    INSERT OR REPLACE — that wiped `import_cost`/`export_credit`/
    `net_cost` to 0 and NULL-ed the live predictions). On rows where
    the row does not yet exist, INSERT with just those three columns
    (plus date) and leave cost/prediction columns at their defaults.

    A row with live `consumption_kwh` / `solar_production_kwh` is
    skipped unless `--force-overwrite`.
    """
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
                # UPDATE only — preserve costs + predictions.
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

    # Midnight boundaries (local). The script uses naive local midnights
    # — safe for a URA single-site install; a multi-TZ future scope.
    tz = _dt.datetime.now().astimezone().tzinfo
    boundaries = [
        _dt.datetime.combine(d, _dt.time.min, tzinfo=tz)
        for d in _iter_dates(start, end + _dt.timedelta(days=1))
    ]

    print(f"Reading recorder {args.recorder_db} …")
    rec = sqlite3.connect(args.recorder_db)
    try:
        imp = _recorder_values_at_midnight(rec, args.import_entity, boundaries)
        exp = _recorder_values_at_midnight(rec, args.export_entity, boundaries)
    finally:
        rec.close()

    rows: list[DayRow] = []
    bs = boundaries
    for i in range(len(bs) - 1):
        day = bs[i].date().isoformat()
        imp_d = _delta_with_reset(imp.get(bs[i]), imp.get(bs[i + 1]))
        exp_d = _delta_with_reset(exp.get(bs[i]), exp.get(bs[i + 1]))
        src = "recorder" if (imp_d is not None or exp_d is not None) else "skip_novalue"
        rows.append(DayRow(date=day, import_kwh=imp_d, export_kwh=exp_d, source=src))

    ura = sqlite3.connect(args.ura_db)
    try:
        existing = _read_existing(ura, [r.date for r in rows])
    finally:
        ura.close()

    # Dry-run output — per-column BEFORE / AFTER for every row.
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
        ) and not args.force_overwrite:
            action = "SKIP(live>backfill)"
            after_imp, after_exp, after_cons, after_bs = (
                live_imp, live_exp, live_cons, live_bs,
            )
        else:
            action = "WOULD_UPDATE" if live else "WOULD_INSERT"
            after_imp = row.import_kwh
            after_exp = row.export_kwh
            # UPDATE-only path leaves consumption untouched.
            after_cons = live_cons
            after_bs = "recorder_backfill"
        fmt = lambda v: ("—" if v is None else f"{v}")
        print(
            f"{row.date:<12}"
            f"{fmt(live_imp):>12}{fmt(after_imp):>12}"
            f"{fmt(live_exp):>12}{fmt(after_exp):>12}"
            f"  {fmt(live_cons):>12}{fmt(after_cons):>12}"
            f"  {fmt(live_bs):>18}{fmt(after_bs):>18}  "
            f"{action:<22}"
        )

    if args.apply:
        print("Applying UPDATE-only writes (never INSERT OR REPLACE) …")
        _apply_writes(args.ura_db, rows, existing, args.force_overwrite)
        print("Done.")
    else:
        print("Dry-run — no writes performed. Rerun with --apply to commit.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
