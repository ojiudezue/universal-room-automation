#!/usr/bin/env python3
"""INTERIOR-PATH-MAP-1 / FACE-ARRIVAL-REBUILD-1 D7: offline learned-pair report
(READ-ONLY). For every ordered pair of path-candidate cameras, count person
`on` -> `on` hops within 120 s over the recorder window and print hops/day and
lag p50/p90. Output feeds AUDIT_interior_path_map_learned_vs_operator.md. Never
writes anything; the runtime never reads a learned map.

    ssh ha "python3 -" < scripts/probes/interior_path_learned_pairs.py
"""
import re
import sqlite3

STEMS = ["rear_ptz", "g5_bullet", "doorbell_lite", "garage_a", "staircase", "stairs_top",
         "playroom", "upstairs_hall", "family_room", "front_side_ptz", "utilities_ptz",
         "sonoffwindow", "front_door_aerial", "madrone_g6_entry", "foyer_fisheye",
         "master_hallway", "reolinkpatio", "garage_b", "garage_hallway"]
r = sqlite3.connect("file:/config/home-assistant_v2.db?mode=ro", uri=True)
now = r.execute("select max(last_updated_ts) from states").fetchone()[0]
days = 7.5
t0 = now - days * 86400
sfx = re.compile(r"_(person_occupancy|person_detected|camera_person_detected)(_\d+)?$")
edges = {}
for (eid, mid) in r.execute("select entity_id, metadata_id from states_meta where entity_id like 'binary_sensor.%'"):
    base = sfx.sub("", eid.split(".", 1)[1])
    if base not in STEMS or not sfx.search(eid) or "property" in eid or "package" in eid:
        continue
    prev = None
    for ts, st in r.execute("select last_updated_ts, state from states where metadata_id=? and last_updated_ts>=? order by 1", (mid, t0)):
        if st == "on" and prev != "on":
            edges.setdefault(base, []).append(ts)
        prev = st
for k in edges:
    edges[k].sort()


def pct(v, p):
    v = sorted(v)
    return round(v[min(len(v) - 1, int(round(p / 100 * (len(v) - 1))))], 1) if v else None


rows = []
for a in STEMS:
    for b in STEMS:
        if a == b or a not in edges or b not in edges:
            continue
        lags, j, eb = [], 0, edges[b]
        for t in edges[a]:
            while j < len(eb) and eb[j] <= t:
                j += 1
            if j < len(eb) and eb[j] - t <= 120:
                lags.append(eb[j] - t)
        if lags:
            rows.append((len(lags) / days, a, b, pct(lags, 50), pct(lags, 90)))
for hpd, a, b, p50, p90 in sorted(rows, reverse=True):
    if hpd >= 2:
        print(f"{a} -> {b}: {hpd:.1f}/d p50 {p50} p90 {p90}")
