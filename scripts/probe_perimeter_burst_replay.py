"""D4a (PLANNING_perimeter_fp_build_2026_11.md): burst-demote all-day replay.
READ-ONLY. Run on the HA host:

    ssh ha "python3 -" < scripts/probe_perimeter_burst_replay.py

Mirrors `_evaluate_burst_demotion` with PERIMETER_BURST_NIGHT_ONLY=False:
an alert would demote when (a) a prior dispatched alert on the same camera
exists inside 1800 s, (b) no other-NVR-family person leg on that camera
rose within ±60 s, (c) no ADJACENT camera dispatched within 1800 s.
(c) is an APPROXIMATION of the linker's open-track adjacency (another
camera's audit row in the window), stated here and in the report.
Prints counts per camera x hour and the would-demote list (camera, epoch)
so the matching snapshots can be pulled and labelled (GO = 0 harmful in a
sample of >= 30).
"""
import ast
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone

URA_DB = "/config/universal_room_automation/data/universal_room_automation.db"
HA_DB = "/config/home-assistant_v2.db"
CONST = "/config/custom_components/universal_room_automation/const.py"
DAYS = 30
WINDOW_S = 1800
SIB_S = 60


def _ts(s):
    try:
        d = datetime.fromisoformat(str(s))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.timestamp()
    except Exception:
        return None


def _stem(eid):
    b = eid.split(".", 1)[-1]
    if b.endswith("_2"):
        b = b[:-2]
    for suf in ("_person_occupancy", "_person_detected", "_smart_motion_human", "_person"):
        if b.endswith(suf):
            return b[: -len(suf)]
    return b


def _family(eid):
    if "_person_occupancy" in eid:
        return "frigate"
    if "_person_detected" in eid:
        return "protect"
    return eid


def _adjacency():
    try:
        tree = ast.parse(open(CONST).read())
        for node in ast.walk(tree):
            if isinstance(node, (ast.AnnAssign, ast.Assign)):
                tgt = node.target if isinstance(node, ast.AnnAssign) else node.targets[0]
                if getattr(tgt, "id", "") == "EXTERIOR_ADJACENCY_GRAPH":
                    return ast.literal_eval(node.value)
    except Exception:
        pass
    return {}


def main():
    since = time.time() - DAYS * 86400
    adj = _adjacency()
    con = sqlite3.connect(f"file:{URA_DB}?mode=ro", uri=True)
    seen, alerts = set(), []
    for ts, loc in con.execute(
        "SELECT timestamp, location FROM notification_log WHERE "
        "hazard_type='exterior_person' AND message='[audit]' ORDER BY timestamp"
    ):
        t = _ts(ts)
        if t is None or t < since or not loc or (loc, int(t)) in seen:
            continue
        seen.add((loc, int(t)))
        alerts.append((t, loc, _stem(loc)))
    ha = sqlite3.connect(f"file:{HA_DB}?mode=ro", uri=True)
    meta = {eid: mid for mid, eid in ha.execute(
        "SELECT metadata_id, entity_id FROM states_meta WHERE entity_id LIKE 'binary_sensor.%person%'")}

    def other_family_rose(stem, fam, t):
        for eid, mid in meta.items():
            if _stem(eid) != stem or _family(eid) == fam:
                continue
            n = ha.execute(
                "SELECT COUNT(*) FROM states WHERE metadata_id=? AND state='on' AND "
                "last_updated_ts BETWEEN ? AND ?", (mid, t - SIB_S, t + SIB_S)).fetchone()[0]
            if n:
                return True
        return False

    by_cam = defaultdict(list)
    out, per = [], Counter()
    for t, loc, stem in alerts:
        prior = [x for x in by_cam[stem] if t - WINDOW_S <= x < t]
        by_cam[stem].append(t)
        if not prior:
            continue
        if other_family_rose(stem, _family(loc), t):
            continue
        neigh = set(adj.get(stem, ()))
        if any(n in neigh and abs(t2 - t) <= WINDOW_S and n != stem
               for t2, _l, n in alerts):
            continue
        hr = datetime.fromtimestamp(t).hour
        per[(stem, hr)] += 1
        out.append((stem, int(t)))
    print(f"alerts={len(alerts)} would_demote={len(out)} days={DAYS} "
          "(adjacency approximated by adjacent-camera audit rows)")
    print("camera\thour\tcount")
    for (c, h), n in sorted(per.items()):
        print(f"{c}\t{h:02d}\t{n}")
    print("WOULD_DEMOTE (camera epoch):")
    for c, e in out:
        print(c, e)


if __name__ == "__main__":
    sys.exit(main())
