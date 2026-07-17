#!/usr/bin/env python3
"""R4c — purge LTS statistics for DEAD Envoy serials (DRY-RUN BY DEFAULT).

Four Envoy serials fragment the statistics history (hardware/RMA swaps):
    202442014493  2025-03-10 -> 2025-08-04   (dead)
    202504003374  2025-08-12 -> 2025-10-02   (dead)
    202428004328  2025-10-03 -> 2026-03-29   (dead)
    482543015950  2026-04-11 -> now          (LIVE — never touched here)

Dead = statistics_meta.statistic_id has no matching entity in
/config/.storage/core.entity_registry. This script cross-checks the live
registry at runtime; it does NOT hardcode the dead list.

WARNING (operator decision point): deleting dead-serial statistics removes
that period's history from the Energy dashboard / history graphs
permanently. The uint32-corrupted consumption stats are worthless, but the
production/battery MWh stats for dead serials are CLEAN — purging them
trades historic dashboard continuity for a clean statistics_meta. Review
the per-statistic table in the dry-run output before executing.

Run ON the HA host:
    ssh ha "python3 -" < scripts/maintenance/lts_repair_r4c_dead_serial_purge.py            # dry-run
    ssh ha "python3 - --execute" < scripts/maintenance/lts_repair_r4c_dead_serial_purge.py  # AFTER backup + review
Optional: --only-serial 202442014493 to scope to one serial.

Backup first: sqlite3 /config/home-assistant_v2.db ".backup /config/home-assistant_v2.db.pre_r4c"
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys

DB = "/config/home-assistant_v2.db"
REGISTRY = "/config/.storage/core.entity_registry"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--only-serial", default=None)
    ap.add_argument("--db", default=DB)
    args = ap.parse_args()

    with open(REGISTRY) as f:
        live = {e["entity_id"] for e in json.load(f)["data"]["entities"]}

    if args.execute:
        confirm = input("EXECUTE MODE — backup taken + operator reviewed the plan? type 'yes': ")
        if confirm.strip() != "yes":
            print("aborted")
            return 1
        con = sqlite3.connect(args.db)
    else:
        con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    c = con.cursor()

    pattern = (f"sensor.envoy_{args.only_serial}%" if args.only_serial
               else "sensor.envoy_%")
    c.execute("SELECT id, statistic_id FROM statistics_meta WHERE statistic_id LIKE ?",
              (pattern,))
    dead = [(mid, sid) for mid, sid in c.fetchall() if sid not in live]

    total_lts = total_st = 0
    print(f"{'metadata_id':>11}  {'lts_rows':>8}  {'st_rows':>7}  statistic_id")
    plan = []
    for mid, sid in sorted(dead, key=lambda x: x[1]):
        c.execute("SELECT COUNT(*) FROM statistics WHERE metadata_id=?", (mid,))
        n = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM statistics_short_term WHERE metadata_id=?", (mid,))
        ns = c.fetchone()[0]
        total_lts += n
        total_st += ns
        print(f"{mid:>11}  {n:>8}  {ns:>7}  {sid}")
        plan.append((mid, sid, n, ns))

    print(f"\n{len(dead)} dead statistics_meta rows; {total_lts} statistics rows; "
          f"{total_st} short-term rows")
    print("\n-- DELETE plan (FK order: child rows first, then meta):")
    for mid, sid, n, ns in plan:
        print(f"DELETE FROM statistics WHERE metadata_id = {mid};            -- {n} rows ({sid})")
        if ns:
            print(f"DELETE FROM statistics_short_term WHERE metadata_id = {mid};  -- {ns} rows")
        print(f"DELETE FROM statistics_meta WHERE id = {mid};")

    if args.execute:
        for mid, _, _, _ in plan:
            c.execute("DELETE FROM statistics WHERE metadata_id=?", (mid,))
            c.execute("DELETE FROM statistics_short_term WHERE metadata_id=?", (mid,))
            c.execute("DELETE FROM statistics_meta WHERE id=?", (mid,))
        con.commit()
        print("COMMITTED. Verify: SELECT COUNT(*) FROM statistics_meta "
              "WHERE statistic_id LIKE 'sensor.envoy_%'; -- expect only live-serial rows")
    else:
        print("\nDRY-RUN ONLY — no writes performed (read-only connection).")
        print("NOTE: HA also offers a supported path — Developer Tools > Statistics "
              "lists these as 'no longer provided' with a per-statistic FIX/remove "
              "button (WS recorder/clear_statistics). Prefer it for small counts; "
              "this script exists to do all 53 in one reviewed pass.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
