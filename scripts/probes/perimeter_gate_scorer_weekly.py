#!/usr/bin/env python3
"""PERIMETER-GATE-EVIDENCE D2: weekly perimeter gate scorer.

READ-ONLY on HA. Prints markdown to stdout:

    ssh ha "python3 -" < scripts/probes/perimeter_gate_scorer_weekly.py

For the last 7 days of `perimeter_gate_decision` rows (memory_episodes):
  * counts per camera x gate x reason x day/night: decisions, would_demote,
    demoted;
  * every would-demote row with the nearest snapshot in /media/ura/snapshots
    (same camera key in the filename, mtime within +-10 s of the row's `at`)
    for operator labelling (street / property / other);
  * the D6 PERSON x LOCATION cross-tab (D3 shadow data).

Pure functions (`aggregate`, `person_location_crosstab`, `nearest_snapshot`)
take plain data so they can be unit-tested off-box.
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter
from datetime import datetime

EPISODE = "perimeter_gate_decision"
WEEK_S = 7 * 86400
SNAP_DIR = "/media/ura/snapshots"
SNAP_WINDOW_S = 10.0
URA_DB = "file:/config/universal_room_automation/data/universal_room_automation.db?mode=ro"


def _epoch(at):
    try:
        return datetime.fromisoformat(str(at)).timestamp()
    except Exception:  # noqa: BLE001
        return None


def daypart(attrs):
    v = attrs.get("is_day")
    return "day" if v is True else ("night" if v is False else "unknown")


def aggregate(rows):
    """rows: [attrs dict] -> {(camera, gate, reason, daypart): [n, would, demoted]}."""
    out: dict = {}
    for a in rows:
        k = (a.get("camera"), a.get("gate"), a.get("reason"), daypart(a))
        c = out.setdefault(k, [0, 0, 0])
        c[0] += 1
        c[1] += 1 if a.get("would_demote") else 0
        c[2] += 1 if a.get("demoted") else 0
    return out


def person_location_crosstab(rows):
    return Counter(
        (a.get("verdict") or "?", a.get("location") or "?")
        for a in rows if a.get("gate") == "vlm"
    )


def nearest_snapshot(camera, at_epoch, files):
    """files: [(name, mtime)]. Nearest same-camera file within the window."""
    if at_epoch is None or not camera:
        return None
    best = None
    for name, mtime in files:
        if camera not in name:
            continue
        dt = abs(mtime - at_epoch)
        if dt <= SNAP_WINDOW_S and (best is None or dt < best[1]):
            best = (name, dt)
    return best[0] if best else None


def _list_snapshots():
    try:
        return [
            (e.name, e.stat().st_mtime)
            for e in os.scandir(SNAP_DIR) if e.is_file()
        ]
    except Exception:  # noqa: BLE001
        return []


def main():
    import sqlite3
    import time

    since = datetime.fromtimestamp(time.time() - WEEK_S).isoformat()
    con = sqlite3.connect(URA_DB, uri=True)
    rows = [
        json.loads(r[0]) for r in con.execute(
            "SELECT attrs_json FROM memory_episodes WHERE episode_type = ? "
            "AND started_at >= ? ORDER BY started_at", (EPISODE, since),
        )
    ]
    con.close()
    print(f"# Perimeter gate scorer (since {since}, {len(rows)} rows)\n")
    print("| camera | gate | reason | day/night | n | would_demote | demoted |")
    print("|---|---|---|---|---|---|---|")
    for (cam, gate, reason, dp), (n, w, d) in sorted(
        aggregate(rows).items(), key=lambda kv: tuple(str(x) for x in kv[0]),
    ):
        print(f"| {cam} | {gate} | {reason} | {dp} | {n} | {w} | {d} |")
    files = _list_snapshots()
    print("\n## Would-demote rows (label: street / property / other)\n")
    print("| at | camera | gate | reason | demoted | snapshot | label |")
    print("|---|---|---|---|---|---|---|")
    for a in rows:
        if not a.get("would_demote") and not a.get("would_demote_if_day"):
            continue
        at = a.get("at") or ""
        snap = a.get("snapshot") or nearest_snapshot(
            a.get("camera"), _epoch(at), files)
        print(f"| {at} | {a.get('camera')} | {a.get('gate')} | {a.get('reason')} "
              f"| {a.get('demoted')} | {snap or '-'} | |")
    print("\n## D6 PERSON x LOCATION\n")
    print("| person | location | n |")
    print("|---|---|---|")
    for (p, loc), n in sorted(person_location_crosstab(rows).items()):
        print(f"| {p} | {loc} | {n} |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
