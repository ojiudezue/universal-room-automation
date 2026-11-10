#!/usr/bin/env python3
"""Settle each house state for the HVAC evidence rule (read-only).

HVAC-GUEST-EVIDENCE-RULE-1 phase 1, plan rev 2 §7. Runs
`hvac_evidence_shadow_verdict.sql` against the URA database and prints one row
per house state: legacy-occupied zone-hours, eligible / premature / saved
`less` episodes, the rate, the reference rate (home_day + home_evening), the
bar and the verdict (SAFE / NOT SAFE / INSUFFICIENT / REFERENCE).

Rule: a state is SAFE when it has >= --floor-h legacy-occupied zone-hours and
its premature rate is <= max(--ratio x reference rate, --abs-floor). It is
NOT SAFE when above that bar with >= 3 premature events. Otherwise
INSUFFICIENT. A thin reference (< --floor-h) reads INSUFFICIENT (reference).
Episodes with any pending room, any refresh-failed room, or opened within
--boot-exclude seconds of a restart are excluded in every state.

These are ANALYSIS parameters, not runtime knobs.

Example (on the HA host, read-only):
  python3 hvac_evidence_shadow_verdict.py --db /config/universal_room_automation/data/universal_room_automation.db \
      --since 2026-11-11T00:00:00 --grace 300
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys

SQL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hvac_evidence_shadow_verdict.sql")

DEFAULTS = {"boot": 600.0, "floor_h": 30.0, "ratio": 1.5, "abs_floor": 0.02}


def run_verdict(conn: sqlite3.Connection, *, since: str, grace: float,
                boot: float = DEFAULTS["boot"], floor_h: float = DEFAULTS["floor_h"],
                ratio: float = DEFAULTS["ratio"],
                abs_floor: float = DEFAULTS["abs_floor"]) -> list[dict]:
    """Execute the verdict SQL; return one dict per house state."""
    with open(SQL_PATH, encoding="utf-8") as fh:
        sql = fh.read()
    cur = conn.execute(sql, {
        "since": since, "grace": float(grace), "boot": float(boot),
        "floor_h": float(floor_h), "ratio": float(ratio), "abs_floor": float(abs_floor),
    })
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def guest_resumed_rooms(conn: sqlite3.Connection, since: str) -> list[tuple]:
    """Guest caveat (plan §7): the rooms of each guest `resumed` episode."""
    return conn.execute(
        "SELECT started_at, zone_id, duration_s, "
        "json_extract(details_json,'$.resumed_rooms') "
        "FROM hvac_evidence_shadow WHERE row_type='episode' AND house_state='guest' "
        "AND kind='less' AND outcome='resumed' AND timestamp >= ? ORDER BY started_at",
        (since,),
    ).fetchall()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", required=True, help="path to the URA sqlite database (opened read-only)")
    ap.add_argument("--since", required=True, help="UTC ISO start (the D3 live date)")
    ap.add_argument("--grace", type=float, required=True, help="live knob 48 in SECONDS")
    ap.add_argument("--boot-exclude", type=float, default=DEFAULTS["boot"], help="seconds (default 600)")
    ap.add_argument("--floor-h", type=float, default=DEFAULTS["floor_h"], help="zone-hours (default 30)")
    ap.add_argument("--ratio", type=float, default=DEFAULTS["ratio"], help="x reference rate (default 1.5)")
    ap.add_argument("--abs-floor", type=float, default=DEFAULTS["abs_floor"],
                    help="premature per zone-hour (default 0.02)")
    a = ap.parse_args(argv)
    conn = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True)
    try:
        rows = run_verdict(conn, since=a.since, grace=a.grace, boot=a.boot_exclude,
                           floor_h=a.floor_h, ratio=a.ratio, abs_floor=a.abs_floor)
        if not rows:
            print("no exposure rows since", a.since)
            return 0
        cols = list(rows[0])
        print("\t".join(cols))
        for r in rows:
            print("\t".join("" if r[c] is None else str(r[c]) for c in cols))
        gr = guest_resumed_rooms(conn, a.since)
        if gr:
            print("\nguest resumed episodes (started_at, zone, duration_s, resumed_rooms):")
            for row in gr:
                print("  ", *row)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
