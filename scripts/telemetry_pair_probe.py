#!/usr/bin/env python3
"""One-shot local<->cloud telemetry pair probe (failover-map Phase B0).

Reads the HA recorder DB READ-ONLY, prints a per-pair measurement report,
and exits. No daemon, no writes, no HA integration. Run on the HA host:

    python3 telemetry_pair_probe.py [hours]

Per pair it reports: update cadence, staleness p50/p95, best-fit lag
(cross-correlation on a 60s grid), and divergence stats at that lag —
including a sign-flip test for the battery-power pair. These numbers are
the go/no-go gate for admitting each pair into the failover map
(AUDIT_envoy_telemetry_pairing_manual.md §5).
"""
import sqlite3
import statistics
import sys

DB = "/config/home-assistant_v2.db"
HOURS = float(sys.argv[1]) if len(sys.argv) > 1 else 48.0

# (name, local_eid, cloud_eid, cloud_to_local_factor, try_sign_flip)
PAIRS = [
    ("battery_soc",
     "sensor.envoy_482543015950_battery",
     "sensor.iq_battery_hacs_battery_overall_charge", 1.0, False),
    ("production_power",
     "sensor.envoy_482543015950_current_power_production",
     "sensor.enphase_cloud_hacs_current_production_power", 0.001, False),
    ("battery_power",
     "sensor.envoy_482543015950_current_battery_discharge",
     "sensor.enphase_cloud_hacs_current_battery_power", 0.001, True),
    ("net_power",
     "sensor.envoy_482543015950_current_net_power_consumption",
     "sensor.enphase_cloud_hacs_current_grid_power", 0.001, False),
]

GRID_S = 60
MAX_LAG_S = 1800


def series(con, eid):
    q = ("SELECT s.last_updated_ts, s.state FROM states s "
         "JOIN states_meta sm ON s.metadata_id=sm.metadata_id "
         "WHERE sm.entity_id=? AND s.last_updated_ts > strftime('%s','now')-? "
         "ORDER BY s.last_updated_ts")
    out = []
    for ts, st in con.execute(q, (eid, HOURS * 3600)):
        try:
            out.append((float(ts), float(st)))
        except (TypeError, ValueError):
            continue
    return out


def cadence_stats(pts):
    if len(pts) < 3:
        return None
    gaps = sorted(b[0] - a[0] for a, b in zip(pts, pts[1:]))
    n = len(gaps)
    return {"n": len(pts), "p50": gaps[n // 2], "p95": gaps[int(n * 0.95)]}


def resample(pts, t0, t1):
    """Step-hold resample onto the 60s grid (recorder stores changes only)."""
    grid, i, last = [], 0, None
    t = t0
    while t <= t1:
        while i < len(pts) and pts[i][0] <= t:
            last = pts[i][1]
            i += 1
        grid.append(last)
        t += GRID_S
    return grid


def divergence(a, b):
    diffs = [x - y for x, y in zip(a, b) if x is not None and y is not None]
    if len(diffs) < 5:
        return None
    ad = sorted(abs(d) for d in diffs)
    return {"n": len(diffs), "mean": statistics.mean(diffs),
            "p50_abs": ad[len(ad) // 2], "p95_abs": ad[int(len(ad) * 0.95)]}


def best_lag(local, cloud):
    """Shift cloud EARLIER by k steps; find k minimizing p50 |diff|."""
    best = (None, None)
    for k in range(0, MAX_LAG_S // GRID_S + 1):
        d = divergence(local[k:], cloud[:len(cloud) - k or None])
        if d and (best[1] is None or d["p50_abs"] < best[1]["p50_abs"]):
            best = (k * GRID_S, d)
    return best


def main():
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    print(f"=== telemetry pair probe — window {HOURS:.0f}h, grid {GRID_S}s ===")
    for name, leid, ceid, factor, flip in PAIRS:
        lp, cp = series(con, leid), series(con, ceid)
        lc, cc = cadence_stats(lp), cadence_stats(cp)
        print(f"\n-- {name}")
        for tag, st, eid in (("local", lc, leid), ("cloud", cc, ceid)):
            if st:
                print(f"   {tag} {eid}: {st['n']} updates, "
                      f"gap p50 {st['p50']:.0f}s p95 {st['p95']:.0f}s")
            else:
                print(f"   {tag} {eid}: INSUFFICIENT DATA")
        if not (lc and cc):
            continue
        t0 = max(lp[0][0], cp[0][0])
        t1 = min(lp[-1][0], cp[-1][0])
        if t1 - t0 < 3600:
            print("   overlap < 1h — skipping lag analysis")
            continue
        lg = resample(lp, t0, t1)
        variants = [(1.0, "as-is")] + ([(-1.0, "sign-flipped")] if flip else [])
        for sgn, label in variants:
            cg = resample([(t, v * factor * sgn) for t, v in cp], t0, t1)
            lag, d = best_lag(lg, cg)
            if d:
                print(f"   [{label}] best lag {lag:.0f}s -> "
                      f"diff mean {d['mean']:+.3f}, |p50| {d['p50_abs']:.3f}, "
                      f"|p95| {d['p95_abs']:.3f}  (n={d['n']}, local-unit)")
            else:
                print(f"   [{label}] not enough overlapping samples")
    print("\nDone (read-only, exiting).")


if __name__ == "__main__":
    main()
