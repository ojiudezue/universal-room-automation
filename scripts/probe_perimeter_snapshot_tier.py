"""D8 (PLANNING_perimeter_fp_build_2026_11.md): snapshot tier x detection
duration probe. READ-ONLY. Run on the HA host:

    ssh ha "python3 -" < scripts/probe_perimeter_snapshot_tier.py

Joins the last 7 days of `exterior_person` [audit] rows (URA DB) to the files
in /media/ura/snapshots (camera + epoch join, as in the street-noise audit),
classifies the capture tier from the filename and joins the recorder ON
period of the triggering leg (`location` = sensor entity id).

Filename tiers (perimeter_alert.py `_try_capture_frigate_event` /
`_try_capture_live_grab`):
  <cam>_<frigate-event-id>.jpg   event id `\\d+\\.\\d+-\\w+`  -> frigate_event
  <cam>_<epoch>_<hex6>.jpg                                    -> live_grab
"""
import os
import re
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone

URA_DB = "/config/universal_room_automation/data/universal_room_automation.db"
HA_DB = "/config/home-assistant_v2.db"
SNAP_DIR = "/media/ura/snapshots"
DAYS = 7
JOIN_S = 90  # file mtime/epoch within this many seconds of the audit row

FE = re.compile(r"^(?P<cam>.+?)_(?P<eid>\d{9,11}\.\d+-\w+)\.jpg$")
LG = re.compile(r"^(?P<cam>.+?)_(?P<ep>\d{9,11})_[0-9a-f]{6}\.jpg$")


def _ts(s):
    try:
        d = datetime.fromisoformat(str(s))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.timestamp()
    except Exception:
        return None


def _cam_of_sensor(eid):
    b = eid.split(".", 1)[-1]
    if b.endswith("_2"):
        b = b[:-2]
    for suf in ("_person_occupancy", "_person_detected", "_smart_motion_human", "_person"):
        if b.endswith(suf):
            return b[: -len(suf)]
    return b


def main():
    since = time.time() - DAYS * 86400
    files = []
    for n in os.listdir(SNAP_DIR) if os.path.isdir(SNAP_DIR) else []:
        m = FE.match(n)
        if m:
            files.append((m["cam"], float(m["eid"].split("-")[0]), "frigate_event", n))
            continue
        m = LG.match(n)
        if m:
            files.append((m["cam"], float(m["ep"]), "live_grab", n))
    by_cam = defaultdict(list)
    for f in files:
        by_cam[f[0]].append(f)

    con = sqlite3.connect(f"file:{URA_DB}?mode=ro", uri=True)
    rows = con.execute(
        "SELECT timestamp, location, severity FROM notification_log "
        "WHERE hazard_type='exterior_person' AND message='[audit]' "
        "ORDER BY timestamp"
    ).fetchall()
    seen = set()
    alerts = []
    for ts, loc, sev in rows:
        t = _ts(ts)
        if t is None or t < since or not loc:
            continue
        key = (loc, int(t))  # one audit row per recipient -> dedupe
        if key in seen:
            continue
        seen.add(key)
        alerts.append((t, loc, sev))

    ha = None
    try:
        ha = sqlite3.connect(f"file:{HA_DB}?mode=ro", uri=True)
    except Exception:
        pass

    def on_duration(eid, t):
        if ha is None:
            return None
        try:
            q = ha.execute(
                "SELECT s.state, s.last_updated_ts FROM states s JOIN states_meta m "
                "ON s.metadata_id=m.metadata_id WHERE m.entity_id=? AND "
                "s.last_updated_ts BETWEEN ? AND ? ORDER BY s.last_updated_ts",
                (eid, t - 120, t + 600),
            ).fetchall()
        except Exception:
            return None
        on_t = None
        for st, lu in q:
            if st == "on" and on_t is None and lu <= t + 5:
                on_t = lu
            elif st != "on" and on_t is not None and lu > on_t:
                return lu - on_t
        return None

    table = Counter()
    for t, loc, sev in alerts:
        cam = _cam_of_sensor(loc)
        cands = [f for f in by_cam.get(cam, []) if abs(f[1] - t) <= JOIN_S]
        tier = min(cands, key=lambda f: abs(f[1] - t))[2] if cands else "no_file"
        dur = on_duration(loc, t)
        b = ("unknown" if dur is None else "<2s" if dur < 2 else "2-10s"
             if dur < 10 else "10-60s" if dur < 60 else ">=60s")
        table[(cam, tier, b)] += 1
    print(f"alerts={len(alerts)} files={len(files)} days={DAYS}")
    print("camera\ttier\tduration\tcount")
    for (cam, tier, b), n in sorted(table.items()):
        print(f"{cam}\t{tier}\t{b}\t{n}")
    tot = Counter()
    for (cam, tier, b), n in table.items():
        tot[tier] += n
    print("TOTAL", dict(tot))


if __name__ == "__main__":
    sys.exit(main())
