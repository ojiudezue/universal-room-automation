"""D5a (PLANNING_perimeter_fp_build_2026_11.md): second-engine lag and
agreement rate per dual-leg perimeter camera. READ-ONLY (recorder only;
the Protect-API comparison is run separately from the dev box).

    ssh ha "python3 -" < scripts/probe_perimeter_engine_lag.py

For every rising edge (off->on) of a Frigate `_person_occupancy_2` or
Protect `_person_detected` leg in the last DAYS days, find the first rising
edge of the OTHER family on the same camera stem within ±60 s. Reports per
camera: edges, agreement rate (paired / all), and the p50/p90 of the lag of
the second engine after the first. p90 sets PERIMETER_SS_SETTLE_S; the rate
is the go/no-go for turning on switch.ura_perimeter_single_source_demote.
"""
import sqlite3
import sys
import time
from collections import defaultdict

HA_DB = "/config/home-assistant_v2.db"
DAYS = 30
PAIR_S = 60


def _stem(eid):
    b = eid.split(".", 1)[-1]
    if b.endswith("_2"):
        b = b[:-2]
    for suf in ("_person_occupancy", "_person_detected"):
        if b.endswith(suf):
            return b[: -len(suf)]
    return None


def _pct(xs, p):
    if not xs:
        return None
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(p * len(xs)))], 1)


def main():
    since = time.time() - DAYS * 86400
    ha = sqlite3.connect(f"file:{HA_DB}?mode=ro", uri=True)
    rises = defaultdict(lambda: {"frigate": [], "protect": []})
    for mid, eid in ha.execute(
        "SELECT metadata_id, entity_id FROM states_meta WHERE entity_id LIKE "
        "'binary_sensor.%_person_occupancy_2' OR entity_id LIKE 'binary_sensor.%_person_detected'"
    ).fetchall():
        st = _stem(eid)
        fam = "frigate" if "_person_occupancy" in eid else "protect"
        prev = None
        for s, lu in ha.execute(
            "SELECT state, last_updated_ts FROM states WHERE metadata_id=? AND "
            "last_updated_ts>=? ORDER BY last_updated_ts", (mid, since)):
            if s == "on" and prev == "off":
                rises[st][fam].append(lu)
            prev = s
    print("camera\tedges_f\tedges_p\tagreement\tlag_p50\tlag_p90")
    for st, d in sorted(rises.items()):
        f, p = d["frigate"], d["protect"]
        if not f or not p:
            continue
        lags, paired, total = [], 0, 0
        for mine, other in ((f, p), (p, f)):
            for t in mine:
                total += 1
                near = [o - t for o in other if abs(o - t) <= PAIR_S]
                if near:
                    paired += 1
                    lag = min(near, key=abs)
                    if lag > 0:
                        lags.append(lag)
        print(f"{st}\t{len(f)}\t{len(p)}\t{round(paired / total, 3) if total else None}\t"
              f"{_pct(lags, 0.5)}\t{_pct(lags, 0.9)}")


if __name__ == "__main__":
    sys.exit(main())
