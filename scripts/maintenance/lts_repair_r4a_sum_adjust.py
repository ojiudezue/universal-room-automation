#!/usr/bin/env python3
"""R4a — Envoy uint32-rollover LTS statistics `sum` repair (DRY-RUN BY DEFAULT).

Root cause (see docs/planning/RUNBOOK_lts_repairs_r4.md and
docs/planning/B0_net_energy_classification_probe.md):
Envoy firmware transiently reports uint32-max Wh on the consumption CT
(2^32 Wh = 4,294,967.296 kWh; observed states ~4,294,629 kWh). HA's
`total_increasing` statistics bake each spike into the cumulative `sum`
permanently, corrupting `sensor.envoy_<serial>_energy_consumption_today`
statistics for all 4 Envoy serials.

This script:
  * connects READ-ONLY unless --execute is passed
  * finds spike delta events (|hour-over-hour sum delta| > --threshold kWh)
  * prints the exact UPDATE statements + affected row counts
  * prints the equivalent (PREFERRED, safer) HA WebSocket
    `recorder/adjust_sum` calls — see runbook for the two paths

Run ON the HA host (needs /config/home-assistant_v2.db):
    ssh ha "python3 -" < scripts/maintenance/lts_repair_r4a_sum_adjust.py            # dry-run
    ssh ha "python3 - --execute" < scripts/maintenance/lts_repair_r4a_sum_adjust.py  # AFTER backup + operator review

NEVER run --execute while HA core is running: stop core (or at minimum
accept a WAL race) and ALWAYS take the backup first:
    sqlite3 /config/home-assistant_v2.db ".backup /config/home-assistant_v2.db.pre_r4a"
"""

from __future__ import annotations

import argparse
import datetime
import sqlite3
import sys

DB = "/config/home-assistant_v2.db"
# Statistic IDs corrupted by the uint32 rollover (probed live 2026-07-16):
#   metadata_id 108  sensor.envoy_202442014493_energy_consumption_today (dead serial)
#   metadata_id 2464 sensor.envoy_202504003374_energy_consumption_today (dead serial)
#   metadata_id 3066 sensor.envoy_202428004328_energy_consumption_today (dead serial)
#   metadata_id 5651 sensor.envoy_482543015950_energy_consumption_today (LIVE serial)
TARGET_LIKE = "sensor.envoy_%_energy_consumption_today"
DEFAULT_THRESHOLD_KWH = 100_000.0  # no residential house consumes 100 MWh/hour


def fmt_ts(ts: float) -> str:
    return datetime.datetime.fromtimestamp(ts).isoformat()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true",
                    help="apply the UPDATEs (default: dry-run, read-only connection)")
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD_KWH)
    ap.add_argument("--db", default=DB)
    args = ap.parse_args()

    if args.execute:
        confirm = input("EXECUTE MODE — did you take the .backup and stop HA core? type 'yes': ")
        if confirm.strip() != "yes":
            print("aborted")
            return 1
        con = sqlite3.connect(args.db)
    else:
        con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    c = con.cursor()

    c.execute(
        "SELECT id, statistic_id, unit_of_measurement FROM statistics_meta "
        "WHERE statistic_id LIKE ?", (TARGET_LIKE,))
    metas = c.fetchall()
    if not metas:
        print("No matching statistics_meta rows — nothing to do.")
        return 0

    plans = []  # (mid, sid, [(event_ts, delta)], per-table row counts)
    for mid, sid, unit in metas:
        c.execute("SELECT start_ts, state, sum FROM statistics "
                  "WHERE metadata_id=? ORDER BY start_ts", (mid,))
        rows = c.fetchall()
        events = []
        prev_sum = None
        for ts, state, s in rows:
            if s is None:
                continue
            if prev_sum is not None:
                d = s - prev_sum
                if abs(d) > args.threshold:
                    events.append((ts, d, state))
            prev_sum = s
        if not events:
            print(f"-- {sid} (metadata_id={mid}, unit={unit}): CLEAN, no spike deltas")
            continue
        plans.append((mid, sid, unit, events))

    total_updates = 0
    for mid, sid, unit, events in plans:
        print(f"\n== {sid}  (metadata_id={mid}, unit={unit}) — "
              f"{len(events)} spike event(s), net spurious offset "
              f"{sum(d for _, d, _ in events):,.3f} kWh ==")
        for ts, d, state in events:
            for table in ("statistics", "statistics_short_term"):
                c.execute(f"SELECT COUNT(*) FROM {table} "
                          "WHERE metadata_id=? AND start_ts>=?", (mid, ts))
                n = c.fetchone()[0]
                if n == 0:
                    continue
                sql = (f"UPDATE {table} SET sum = sum - {d!r} "
                       f"WHERE metadata_id = {mid} AND start_ts >= {ts!r};")
                print(f"  -- event {fmt_ts(ts)} state={state!r} delta={d:,.3f} kWh "
                      f"-> {n} rows in {table}")
                print(f"  {sql}")
                total_updates += 1
                if args.execute:
                    c.execute(f"UPDATE {table} SET sum = sum - ? "
                              "WHERE metadata_id=? AND start_ts>=?", (d, mid, ts))
                    print(f"  APPLIED ({c.rowcount} rows)")
        # PREFERRED alternative: HA's own statistics adjustment API. One call
        # per event, from HA's frontend Developer Tools > Statistics ("Adjust
        # sum") or via WebSocket. It shifts `sum` for all rows AFTER
        # start_time via supported recorder code — no raw SQL, no core stop.
        print("  -- PREFERRED equivalent via HA WebSocket (per event, adjustment = -delta):")
        for ts, d, _ in events:
            start_iso = datetime.datetime.fromtimestamp(
                ts, tz=datetime.timezone.utc).isoformat()
            print(f'  {{"type": "recorder/adjust_sum", "statistic_id": "{sid}", '
                  f'"start_time": "{start_iso}", "adjustment": {-d!r}, '
                  f'"adjustment_unit_of_measurement": "kWh"}}')

    print(f"\nTotal UPDATE statements: {total_updates}")
    if args.execute:
        con.commit()
        print("COMMITTED. Run verification queries from the runbook now.")
    else:
        print("DRY-RUN ONLY — no writes performed (read-only connection).")

    # Verification (run after execute):
    print("\n-- Post-repair verification (expect 0 rows / plausible max):")
    for mid, sid, _, _ in plans:
        print(f"SELECT COUNT(*) FROM statistics WHERE metadata_id={mid} AND sum > 1e6;  -- expect 0 ({sid})")
        print(f"SELECT MAX(d) FROM (SELECT sum - LAG(sum) OVER (ORDER BY start_ts) AS d "
              f"FROM statistics WHERE metadata_id={mid});  -- expect < 100 (kWh/hour)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
