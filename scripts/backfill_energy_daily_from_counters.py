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

Mode 2 — `--fill-null-actuals` (EC-FORECAST-TRUTH-GAPS-1)
---------------------------------------------------------
Fills ONLY NULL `consumption_kwh` / `solar_production_kwh` cells on
EXISTING `energy_daily` rows, from the same Envoy lifetime counters the
live producer uses (`energy.py` `_check_midnight_reset` derived path):

    solar       = d(production_ct_energy_delivered)
    consumption = d(net_import) + solar - d(net_export)
                  + d(battery_discharged) - d(battery_charged)

Entity ids come from `energy_const.derive_envoy_config(serial)` (loaded by
path, so the script and the integration cannot disagree). Each leg's
daily delta is the statistics `sum` delta at local midnights (same
boundary lookup as mode 1) AND must agree with the `state` delta — a
counter flap/reset makes them diverge, and that day is left NULL rather
than trusted. A non-NULL cell is never overwritten, a missing row is
never inserted, and the prediction columns are never touched (model
state, no historical source). Dry-run by default; `--apply` writes.
Idempotent: a re-run finds no NULL cells left to fill.

    python3 scripts/backfill_energy_daily_from_counters.py --fill-null-actuals \
        --ura-db <path> --recorder-db <path> --envoy-serial 482543015950 \
        --from 2026-10-01 --to 2026-10-21

Usage (mode 1):
    python3 scripts/backfill_energy_daily_from_counters.py \
        --ura-db <path> --recorder-db <path> \
        --import-entity sensor.mains_vue_3_mainsfromgrid_energy_today \
        --export-entity sensor.main_panels_mains_vue_3_mainstogrid_energy_today \
        --from 2026-06-01 --to 2026-10-08
"""
from __future__ import annotations

import argparse
import datetime as _dt
import importlib.util
import pathlib
import sqlite3
import sys
from dataclasses import dataclass
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_TZ = "America/Chicago"
# Known kWh unit spellings in HA statistics_meta.unit_of_measurement.
_KWH_UNITS = {"kwh", "kWh".lower()}
_WH_UNITS = {"wh", "Wh".lower()}


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


def _resolve_metadata(
    conn: sqlite3.Connection, entity_id: str
) -> tuple[int, float] | None:
    """Return (metadata_id, unit_scale_to_kwh) for `entity_id`.

    unit_scale: 1.0 for kWh, 0.001 for Wh. Unknown units → refuse
    (return None) so we never silently publish 1000x values.
    """
    try:
        cur = conn.execute(
            "SELECT id, unit_of_measurement FROM statistics_meta "
            "WHERE statistic_id = ?",
            (entity_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        unit = (row[1] or "").strip().lower()
        if unit in _KWH_UNITS:
            scale = 1.0
        elif unit in _WH_UNITS:
            scale = 0.001
        else:
            print(f"  WARN unknown unit {row[1]!r} for {entity_id}; "
                  f"refusing to backfill this counter",
                  file=sys.stderr)
            return None
        return (int(row[0]), scale)
    except Exception as e:  # noqa: BLE001
        print(f"  WARN statistics_meta lookup failed for {entity_id}: {e}",
              file=sys.stderr)
        return None


# Backward-compatible shim: older tests may import _resolve_metadata_id.
def _resolve_metadata_id(conn, entity_id):
    r = _resolve_metadata(conn, entity_id)
    return r[0] if r else None


def _statistics_sum_at_boundary(
    conn: sqlite3.Connection,
    metadata_id: int,
    boundary: _dt.datetime,
) -> tuple[float | None, str]:
    """Return (`sum`, match_kind) from the statistics row aligned to
    `boundary`. match_kind ∈ {"exact", "fallback", "missing"}.

    Prefers an exact-start_ts match; falls back to the latest row within
    `BOUNDARY_WINDOW_S` seconds before the boundary (never after — we
    must not pull a row from inside the day we are closing).
    """
    bts = boundary.timestamp()
    try:
        cur = conn.execute(
            "SELECT sum FROM statistics "
            "WHERE metadata_id = ? AND start_ts = ? AND sum IS NOT NULL",
            (metadata_id, bts),
        )
        row = cur.fetchone()
        if row is not None and row[0] is not None:
            return (float(row[0]), "exact")

        cur = conn.execute(
            "SELECT sum FROM statistics "
            "WHERE metadata_id = ? AND start_ts <= ? AND start_ts >= ? "
            "  AND sum IS NOT NULL "
            "ORDER BY start_ts DESC LIMIT 1",
            (metadata_id, bts, bts - BOUNDARY_WINDOW_S),
        )
        row = cur.fetchone()
        if row is not None and row[0] is not None:
            return (float(row[0]), "fallback")
    except Exception as e:  # noqa: BLE001
        print(f"  WARN statistics read failed @ {boundary}: {e}",
              file=sys.stderr)
    return (None, "missing")


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


def _coerce_tz(tz) -> _dt.tzinfo:
    """Accept a tzinfo or an IANA name string; default = America/Chicago."""
    if tz is None:
        return ZoneInfo(DEFAULT_TZ)
    if isinstance(tz, _dt.tzinfo):
        return tz
    try:
        return ZoneInfo(str(tz))
    except ZoneInfoNotFoundError as e:
        raise SystemExit(f"ERROR: unknown timezone {tz!r}: {e}")


def compute_rows(
    recorder_conn: sqlite3.Connection,
    import_entity: str,
    export_entity: str,
    start: _dt.date,
    end: _dt.date,
    tz=None,
    report_boundary_kinds: bool = False,
) -> list[DayRow]:
    """Pure function: compute per-day DayRow list from a recorder DB
    connection. Factored out for testing.

    `tz`: tzinfo or IANA name (default America/Chicago). DST-aware — each
    boundary is built via `ZoneInfo`, so days that cross a DST transition
    land at TRUE local midnight (23h or 25h long).
    """
    tz = _coerce_tz(tz)
    imp = _resolve_metadata(recorder_conn, import_entity)
    exp = _resolve_metadata(recorder_conn, export_entity)
    if imp is None:
        print(f"  WARN no usable statistics_meta row for {import_entity}",
              file=sys.stderr)
    if exp is None:
        print(f"  WARN no usable statistics_meta row for {export_entity}",
              file=sys.stderr)
    imp_meta, imp_scale = (imp if imp else (None, 1.0))
    exp_meta, exp_scale = (exp if exp else (None, 1.0))

    boundaries = [
        _dt.datetime.combine(d, _dt.time.min, tzinfo=tz)
        for d in _iter_dates(start, end + _dt.timedelta(days=1))
    ]
    imp_sum: dict[_dt.datetime, tuple[float | None, str]] = {}
    exp_sum: dict[_dt.datetime, tuple[float | None, str]] = {}
    for b in boundaries:
        imp_sum[b] = (
            _statistics_sum_at_boundary(recorder_conn, imp_meta, b)
            if imp_meta is not None else (None, "missing")
        )
        exp_sum[b] = (
            _statistics_sum_at_boundary(recorder_conn, exp_meta, b)
            if exp_meta is not None else (None, "missing")
        )
        if report_boundary_kinds:
            print(f"  boundary {b.isoformat()} import={imp_sum[b][1]} "
                  f"export={exp_sum[b][1]}")

    rows: list[DayRow] = []
    for i in range(len(boundaries) - 1):
        day = boundaries[i].date().isoformat()
        a_imp, _ = imp_sum[boundaries[i]]
        b_imp, _ = imp_sum[boundaries[i + 1]]
        a_exp, _ = exp_sum[boundaries[i]]
        b_exp, _ = exp_sum[boundaries[i + 1]]
        imp_d = _daily_delta(a_imp, b_imp)
        exp_d = _daily_delta(a_exp, b_exp)
        if imp_d is not None:
            imp_d *= imp_scale
        if exp_d is not None:
            exp_d *= exp_scale
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
                # None-PRESERVING: a one-sided None (e.g. import=None,
                # export=1.0) MUST NOT clobber the live import_kwh value.
                # COALESCE(?, import_kwh) keeps the live column when the
                # bind is NULL.
                conn.execute(
                    """
                    UPDATE energy_daily
                       SET import_kwh = COALESCE(?, import_kwh),
                           export_kwh = COALESCE(?, export_kwh),
                           billing_source = 'recorder_backfill'
                     WHERE date = ?
                    """,
                    (row.import_kwh, row.export_kwh, row.date),
                )
            else:
                # INSERT leaves the None side NULL (not 0.0).
                conn.execute(
                    """
                    INSERT INTO energy_daily
                        (date, import_kwh, export_kwh, billing_source)
                    VALUES (?, ?, ?, 'recorder_backfill')
                    """,
                    (row.date, row.import_kwh, row.export_kwh),
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


# ---------------------------------------------------------------------------
# Mode 2: --fill-null-actuals (EC-FORECAST-TRUTH-GAPS-1)
# ---------------------------------------------------------------------------

# Max |sum-delta - state-delta| (kWh) for a leg's day to be trusted. A
# healthy counter gives identical deltas; a flap or reset diverges by
# thousands of kWh. Module constant (reviewed change only): a data-trust
# bound, not operator policy.
LEG_AGREEMENT_TOL_KWH = 0.5

_LEGS = ("production", "net_import", "net_export",
         "battery_charged", "battery_discharged")
_CONF_KEY_BY_LEG = {
    "production": "energy_lifetime_production_entity",
    "net_import": "energy_lifetime_net_import_entity",
    "net_export": "energy_lifetime_net_export_entity",
    "battery_charged": "energy_lifetime_battery_charged_entity",
    "battery_discharged": "energy_lifetime_battery_discharged_entity",
}
FILL_COLUMNS = ("consumption_kwh", "solar_production_kwh")
_UNIT_SCALE = {"mwh": 1000.0, "kwh": 1.0, "wh": 0.001}

_DEFAULT_ENERGY_CONST = (
    pathlib.Path(__file__).resolve().parent.parent
    / "custom_components" / "universal_room_automation"
    / "domain_coordinators" / "energy_const.py"
)


def load_envoy_entities(serial: str, energy_const_path=None) -> dict[str, str]:
    """Leg -> entity_id via the integration's own derive_envoy_config."""
    path = str(energy_const_path or _DEFAULT_ENERGY_CONST)
    spec = importlib.util.spec_from_file_location("_ura_energy_const", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    cfg = mod.derive_envoy_config(serial)
    return {leg: cfg[key] for leg, key in _CONF_KEY_BY_LEG.items()}


def _statistics_row_at_boundary(conn, metadata_id, boundary):
    """(state, sum, kind) at `boundary`; same exact-then-prior-window rule
    as `_statistics_sum_at_boundary`."""
    bts = boundary.timestamp()
    row = conn.execute(
        "SELECT state, sum FROM statistics WHERE metadata_id = ? AND start_ts = ? "
        "AND sum IS NOT NULL AND state IS NOT NULL",
        (metadata_id, bts),
    ).fetchone()
    if row is not None:
        return (float(row[0]), float(row[1]), "exact")
    row = conn.execute(
        "SELECT state, sum FROM statistics WHERE metadata_id = ? "
        "AND start_ts <= ? AND start_ts >= ? AND sum IS NOT NULL "
        "AND state IS NOT NULL ORDER BY start_ts DESC LIMIT 1",
        (metadata_id, bts, bts - BOUNDARY_WINDOW_S),
    ).fetchone()
    if row is not None:
        return (float(row[0]), float(row[1]), "fallback")
    return (None, None, "missing")


def _leg_delta_kwh(a, b, scale):
    """(trusted daily kWh, "ok") for one leg, or (None, reason)."""
    if a[0] is None or b[0] is None:
        return None, "boundary_missing"
    st = (b[0] - a[0]) * scale
    sm = (b[1] - a[1]) * scale
    if abs(st - sm) > LEG_AGREEMENT_TOL_KWH:
        return None, f"flap(state={st:.1f},sum={sm:.1f})"
    if sm < -0.1:
        return None, f"negative({sm:.1f})"
    return max(0.0, sm), "ok"


def _meta_and_scale(conn, entity_id):
    """(metadata_id, scale_to_kwh) or None (missing / unknown unit)."""
    row = conn.execute(
        "SELECT id, unit_of_measurement FROM statistics_meta WHERE statistic_id = ?",
        (entity_id,),
    ).fetchone()
    if not row:
        return None
    scale = _UNIT_SCALE.get((row[1] or "").strip().lower())
    return None if scale is None else (int(row[0]), scale)


@dataclass
class ActualsDay:
    date: str
    solar_kwh: float | None
    consumption_kwh: float | None
    reasons: dict  # leg -> "ok" | reason


def compute_actuals(recorder_conn, entities, start, end, tz=None):
    """Per-day solar/consumption from the five lifetime legs."""
    tz = _coerce_tz(tz)
    meta = {leg: _meta_and_scale(recorder_conn, entities[leg]) for leg in _LEGS}
    out: list[ActualsDay] = []
    for d in _iter_dates(start, end):
        b0 = _dt.datetime.combine(d, _dt.time.min, tzinfo=tz)
        b1 = _dt.datetime.combine(d + _dt.timedelta(days=1), _dt.time.min, tzinfo=tz)
        deltas, reasons = {}, {}
        for leg in _LEGS:
            m = meta[leg]
            if m is None:
                deltas[leg], reasons[leg] = None, "no_statistics_meta"
                continue
            a = _statistics_row_at_boundary(recorder_conn, m[0], b0)
            b = _statistics_row_at_boundary(recorder_conn, m[0], b1)
            deltas[leg], reasons[leg] = _leg_delta_kwh(a, b, m[1])
        solar = deltas["production"]
        cons = None
        if all(deltas[leg] is not None for leg in _LEGS):
            cons = (deltas["net_import"] + solar - deltas["net_export"]
                    + deltas["battery_discharged"] - deltas["battery_charged"])
            if cons <= 0:  # same guard as the live producer
                reasons["consumption"] = f"non_positive({cons:.1f})"
                cons = None
        out.append(ActualsDay(d.isoformat(), solar, cons, reasons))
    return out


def plan_fill(ura_conn, days):
    """Return (writes, skipped): writes = [(date, column, value, source)]
    for NULL cells on existing rows; skipped = [(date, column, why)]."""
    writes, skipped = [], []
    for day in days:
        row = ura_conn.execute(
            "SELECT consumption_kwh, solar_production_kwh FROM energy_daily "
            "WHERE date = ?", (day.date,),
        ).fetchone()
        if row is None:
            skipped.append((day.date, "*", "no_row (never inserted)"))
            continue
        live = {"consumption_kwh": row[0], "solar_production_kwh": row[1]}
        new = {"consumption_kwh": day.consumption_kwh,
               "solar_production_kwh": day.solar_kwh}
        bad = {k: v for k, v in day.reasons.items() if v != "ok"}
        for col in FILL_COLUMNS:
            if live[col] is not None:
                continue  # never overwrite
            if new[col] is None:
                why = ",".join(f"{k}:{v}" for k, v in bad.items()) or "no_value"
                skipped.append((day.date, col, why))
                continue
            src = ("recorder:production_ct" if col == "solar_production_kwh"
                   else "recorder:net_import+solar-net_export+dis-chg")
            writes.append((day.date, col, new[col], src))
    return writes, skipped


def apply_fill(ura_conn, writes) -> int:
    """UPDATE one NULL cell at a time; the `IS NULL` guard means a stale
    plan or a concurrent producer write can never be overwritten."""
    n = 0
    for date, col, val, _src in writes:
        if col not in FILL_COLUMNS:
            raise ValueError(col)
        cur = ura_conn.execute(
            f"UPDATE energy_daily SET {col} = ? WHERE date = ? AND {col} IS NULL",
            (val, date),
        )
        n += cur.rowcount
    ura_conn.commit()
    return n


def run_fill_null_actuals(args) -> int:
    start = _dt.date.fromisoformat(args.dfrom)
    end = _dt.date.fromisoformat(args.dto)
    if end < start:
        print("ERROR: --to is before --from", file=sys.stderr)
        return 2
    entities = load_envoy_entities(args.envoy_serial, args.energy_const)
    for leg, ent in entities.items():
        print(f"  leg {leg:<20} {ent}")
    rec = sqlite3.connect(f"file:{args.recorder_db}?mode=ro", uri=True)
    try:
        days = compute_actuals(rec, entities, start, end, tz=args.tz)
    finally:
        rec.close()
    # Dry-run opens the URA DB read-only, so it physically cannot write.
    ura = (sqlite3.connect(args.ura_db) if args.apply
           else sqlite3.connect(f"file:{args.ura_db}?mode=ro", uri=True))
    try:
        writes, skipped = plan_fill(ura, days)
        print(f"\n{'date':<12}{'column':<22}{'value':>12}  source")
        for date, col, val, src in writes:
            print(f"{date:<12}{col:<22}{_fmt_num(val)}  {src}")
        print("\nLeft NULL (no trustworthy source):")
        for date, col, why in skipped:
            print(f"  {date:<12}{col:<22}{why}")
        print("  (all dates) predicted_consumption_kwh / prediction_error_pct / "
              "adjustment_factor: model state, no historical source; never filled")
        if args.apply:
            n = apply_fill(ura, writes)
            print(f"\nApplied {n} cell(s).")
        else:
            print(f"\nDry-run — {len(writes)} cell(s) would be written. "
                  "Rerun with --apply to commit.")
    finally:
        ura.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ura-db", required=True)
    p.add_argument("--recorder-db", required=True)
    p.add_argument("--import-entity")
    p.add_argument("--export-entity")
    p.add_argument("--fill-null-actuals", action="store_true", default=False,
                   help="Mode 2: fill NULL consumption/solar from Envoy lifetime counters.")
    p.add_argument("--envoy-serial", help="Envoy serial (mode 2).")
    p.add_argument("--energy-const", default=None,
                   help="Path to energy_const.py (mode 2; default: repo copy).")
    p.add_argument("--from", dest="dfrom", required=True)
    p.add_argument("--to", dest="dto", required=True)
    p.add_argument("--apply", action="store_true", default=False)
    p.add_argument("--force-overwrite", action="store_true", default=False)
    p.add_argument("--tz", default=DEFAULT_TZ,
                   help=f"IANA timezone for day boundaries (default {DEFAULT_TZ}). "
                        f"DST-aware via zoneinfo.")
    p.add_argument("--show-boundary-kinds", action="store_true", default=False,
                   help="Print per-boundary match kind (exact|fallback|missing).")
    args = p.parse_args(argv)

    if args.fill_null_actuals:
        if not args.envoy_serial:
            p.error("--fill-null-actuals requires --envoy-serial")
        return run_fill_null_actuals(args)
    if not (args.import_entity and args.export_entity):
        p.error("--import-entity and --export-entity are required (mode 1)")

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
            tz=args.tz,
            report_boundary_kinds=args.show_boundary_kinds,
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
