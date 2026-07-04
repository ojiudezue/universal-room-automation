#!/usr/bin/env python3
"""URA DB row-rate snapshot — read-only.

Usage:
    python3 db_row_rate_snapshot.py --db-path /path/to/universal_room_automation.db

Prints, for each of a small set of "key" tables (or every table if --all):
  * total row count
  * rows written in the last 24h (if a plausible timestamp column exists)
  * approx rows-per-hour over that window

Schema discovery is fully dynamic via `sqlite_master` and `PRAGMA
table_info`; the script never assumes a schema. Missing tables and
missing timestamp columns are reported clearly rather than fatally.

Intended for pre/post-deploy comparison during DB-sensitive URA cycles.
See CLAUDE.md § "Data Source Verification" for the live DB path.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from typing import Optional

# Table -> ordered candidate timestamp columns. First column that exists on
# the table is used. Add candidates rather than hard-code assumptions.
KEY_TABLES = {
    "anomaly_log": ["created_at", "ts", "timestamp", "occurred_at"],
    "optimization_findings": ["created_at", "ts", "timestamp"],
    "ura_activity_log": ["created_at", "ts", "timestamp"],
}


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def columns_of(conn: sqlite3.Connection, table: str) -> list[str]:
    # PRAGMA table_info returns (cid, name, type, notnull, dflt_value, pk)
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]


def pick_ts_column(conn: sqlite3.Connection, table: str, candidates: list[str]) -> Optional[str]:
    cols = columns_of(conn, table)
    lc = {c.lower(): c for c in cols}
    for cand in candidates:
        if cand.lower() in lc:
            return lc[cand.lower()]
    return None


def snapshot_table(conn: sqlite3.Connection, table: str, candidates: list[str]) -> None:
    if not table_exists(conn, table):
        print(f"[{table}] ABSENT — no such table (skipping)")
        return
    total = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    ts_col = pick_ts_column(conn, table, candidates)
    if ts_col is None:
        print(f"[{table}] total={total} — no timestamp column among {candidates!r} (24h rate unavailable)")
        return
    # Try a few timestamp encodings: epoch seconds vs ISO 8601. Use a
    # tolerant WHERE that accepts either representation.
    try:
        recent = conn.execute(
            f"SELECT COUNT(*) FROM {table} "
            f"WHERE {ts_col} >= strftime('%s','now','-24 hours') "
            f"   OR {ts_col} >= datetime('now','-24 hours')"
        ).fetchone()[0]
    except sqlite3.OperationalError as e:
        print(f"[{table}] total={total} ts_col={ts_col} — 24h query failed: {e}")
        return
    per_hour = recent / 24.0
    print(f"[{table}] total={total} last_24h={recent} rows_per_hour={per_hour:.2f} (ts_col={ts_col})")


def main() -> int:
    ap = argparse.ArgumentParser(description="URA DB row-rate snapshot (read-only).")
    ap.add_argument("--db-path", required=True, help="Path to the URA sqlite DB.")
    ap.add_argument("--all", action="store_true", help="Also snapshot every user table.")
    args = ap.parse_args()

    try:
        conn = sqlite3.connect(f"file:{args.db_path}?mode=ro", uri=True)
    except sqlite3.OperationalError as e:
        print(f"ERROR: cannot open {args.db_path}: {e}", file=sys.stderr)
        return 2

    try:
        for tbl, cands in KEY_TABLES.items():
            snapshot_table(conn, tbl, cands)

        if args.all:
            print("\n--- all user tables ---")
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
            for (name,) in rows:
                if name in KEY_TABLES:
                    continue
                # Try common timestamp column names.
                snapshot_table(conn, name, ["created_at", "ts", "timestamp", "occurred_at"])
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
