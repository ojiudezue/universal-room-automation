#!/usr/bin/env python3
"""FACE-ARRIVAL-REBUILD-1 D8a: weekly egress-outcome labeller (plan rev 11 §7 P7).

READ-ONLY on HA. Two modes:

    # 1. On HA (read-only; prints one JSON document to stdout):
    ssh ha "python3 -" < scripts/probes/egress_outcome_label_weekly.py > /tmp/week.json
    # 2. Locally, merge that week into the committed fixture (dedup by crossing key):
    python3 scripts/probes/egress_outcome_label_weekly.py --merge /tmp/week.json

What it does for the last 7 days of `egress_identity_outcome` rows (memory_episodes):
  * selects WOULD-BE arrival candidates: entry rows whose considered face slug read
    `not_home` or a named zone at resolution (outcome `vetoed`, or an attach with a
    non-home raw state and a face provenance);
  * auto-labels each from that person's NON-FACE edges after the crossing (tracker
    `-> home` edge, Bermuda/BLE tracker `-> home`, a GPS fix that reads `home`):
    `true` if one follows within 600 s; `late` within 1800 s; `mis_or_phoneless`
    otherwise; plus the first-edge lead and per-window booleans for
    LABEL_WINDOWS_S (mirror of const.EGRESS_OUTCOME_LABEL_WINDOWS_S, pinned by
    test_egress_label_weekly.py);
  * SNAPSHOTS the raw guard inputs (rev 11 M6) because the recorder keeps 7 days:
    every person-sensor `on`/`off` edge on every path-node camera over
    [crossing - PATH_BUFFER_S, crossing + POST_S], and every state of each GPS
    `device_tracker` of that person over [crossing - GPS_MAX_AGE_S, crossing + 600]
    as (lat, lon, gps_accuracy, last_updated, last_changed). `raw_inputs_v: 1`.

The auto-label IS the Phase 2 confirmation rule, so it cannot measure that rule's
precision: the Wilson n counts only operator-reviewed rows (`review` field, filled
by the operator). A missed week is a gap in n, never back-filled.
"""
from __future__ import annotations

import json
import sys

RAW_INPUTS_V = 1
LABEL_WINDOWS_S = (120, 300, 600, 1800)  # == const.EGRESS_OUTCOME_LABEL_WINDOWS_S
TRUE_WINDOW_S = 600
LATE_WINDOW_S = 1800
PATH_BUFFER_S = 180  # plan §2B.4 horizon (EGRESS_PATH_BUFFER_S)
POST_S = 75
GPS_MAX_AGE_S = 86400  # EGRESS_ARRIVAL_GPS_MAX_AGE_S
GPS_POST_S = 600
WEEK_S = 7 * 86400
EPISODE = "egress_identity_outcome"
FIXTURE = "quality/tests/fixtures/egress_arrival_d0_labelled.json"
NON_ARRIVAL_STATES = {None, "home", "unknown", "unavailable", ""}


# ----------------------------------------------------------------- pure functions
def would_be_candidates(rows):
    """rows: [{"attrs": {...}, "crossing_ts": epoch}] -> the would-be candidates."""
    out = []
    for r in rows:
        a = r["attrs"]
        if a.get("direction") != "entry" or not a.get("slug"):
            continue
        if a.get("person_state") in NON_ARRIVAL_STATES:
            continue
        if a.get("outcome") == "vetoed" or a.get("provenance") in ("face", "ble+face"):
            out.append(r)
    return out


def first_nonface_edge(crossing_ts, edges):
    """edges: [(epoch, source)] non-face arrival edges of that person. Returns
    (lead_s, source) of the first edge strictly AFTER the crossing, or None."""
    after = sorted((t - crossing_ts, s) for t, s in edges if t > crossing_ts)
    return after[0] if after else None


def label(crossing_ts, edges):
    first = first_nonface_edge(crossing_ts, edges)
    lead = None if first is None else round(first[0], 1)
    if lead is not None and lead <= TRUE_WINDOW_S:
        lab = "true"
    elif lead is not None and lead <= LATE_WINDOW_S:
        lab = "late"
    else:
        lab = "mis_or_phoneless"
    return {
        "auto_label": lab,
        "lead_s": lead,
        "confirmed_by": None if first is None else first[1],
        "within": {str(w): lead is not None and lead <= w for w in LABEL_WINDOWS_S},
    }


def snapshot_raw_inputs(crossing_ts, path_edges, gps_states):
    """path_edges: {camera_entity: [(epoch, state)]}; gps_states:
    {tracker_entity: [(epoch_last_updated, epoch_last_changed, lat, lon, acc)]}."""
    lo, hi = crossing_ts - PATH_BUFFER_S, crossing_ts + POST_S
    path = {
        cam: [[round(t, 3), st] for t, st in edges if lo <= t <= hi and st in ("on", "off")]
        for cam, edges in sorted(path_edges.items())
    }
    glo, ghi = crossing_ts - GPS_MAX_AGE_S, crossing_ts + GPS_POST_S
    gps = {
        trk: [
            {"lat": lat, "lon": lon, "gps_accuracy": acc,
             "last_updated": round(lu, 3), "last_changed": round(lc, 3)}
            for lu, lc, lat, lon, acc in states if glo <= lu <= ghi
        ]
        for trk, states in sorted(gps_states.items())
    }
    return {"raw_inputs_v": RAW_INPUTS_V, "path_edges": path, "gps_fixes": gps}


def build_rows(candidates, edges_by_slug, path_edges, gps_by_slug):
    out = []
    for r in candidates:
        a, ts = r["attrs"], r["crossing_ts"]
        slug = a["slug"]
        row = {
            "crossing_key": f"{a.get('egress_camera')}@{a.get('crossing_ts')}",
            "crossing_ts": ts,
            "egress_camera": a.get("egress_camera"),
            "slug": slug,
            "outcome": a.get("outcome"),
            "tier": a.get("tier"),
            "synthetic": a.get("synthetic"),
            "person_state": a.get("person_state"),
            "review": None,
        }
        row.update(label(ts, edges_by_slug.get(slug, [])))
        row.update(snapshot_raw_inputs(ts, path_edges, gps_by_slug.get(slug, {})))
        out.append(row)
    return out


def merge(fixture_rows, week_rows):
    seen = {r["crossing_key"] for r in fixture_rows}
    return fixture_rows + [r for r in week_rows if r["crossing_key"] not in seen]


# ----------------------------------------------------------------- HA side (I/O)
def _run_on_ha():  # pragma: no cover — runs on the HA host only
    import datetime as dt
    import sqlite3

    rec = sqlite3.connect("file:/config/home-assistant_v2.db?mode=ro", uri=True)
    ura = sqlite3.connect(
        "file:/config/universal_room_automation/data/universal_room_automation.db?mode=ro",
        uri=True,
    )
    store = lambda n: json.load(open(f"/config/.storage/{n}"))["data"]  # noqa: E731
    reg = store("core.entity_registry")["entities"]
    entries = [e for e in store("core.config_entries")["entries"]
               if e.get("domain") == "universal_room_automation"]
    now = rec.execute("select max(last_updated_ts) from states").fetchone()[0]
    rows = []
    for attrs_json, started in ura.execute(
            "select attrs_json, started_at from memory_episodes where episode_type=?",
            (EPISODE,)):
        a = json.loads(attrs_json or "{}")
        try:
            ts = dt.datetime.fromisoformat(a.get("crossing_ts") or started).timestamp()
        except ValueError:
            continue
        if now - ts <= WEEK_S:
            rows.append({"attrs": a, "crossing_ts": ts})
    cands = would_be_candidates(rows)

    def hist(eid, t0, t1, attrs=False):
        m = rec.execute("select metadata_id from states_meta where entity_id=?", (eid,)).fetchone()
        if not m:
            return []
        q = ("select s.last_updated_ts, s.last_changed_ts, s.state, a.shared_attrs from states s "
             "left join state_attributes a on s.attributes_id=a.attributes_id "
             "where s.metadata_id=? and s.last_updated_ts between ? and ? order by 1")
        return list(rec.execute(q, (m[0], t0, t1)))

    # Path-node cameras: every person binary sensor on a camera device in the fixture
    # list, the live door neighbours and the perimeter cameras (registry-resolved).
    integ = next(({**(e.get("data") or {}), **(e.get("options") or {})} for e in entries
                  if (e.get("data") or {}).get("entry_type") == "integration"), {})
    path_stems = {"rear_ptz", "g5_bullet", "doorbell_lite", "garage_a", "staircase",
                  "stairs_top", "playroom", "upstairs_hall", "family_room", "front_side_ptz",
                  "utilities_ptz", "sonoffwindow", "front_door_aerial", "madrone_g6_entry",
                  "foyer_fisheye", "master_hallway", "reolinkpatio", "reolinkstudybporchptz",
                  "garage_b"}
    nodes = set()
    for cams in (integ.get("door_interior_neighbours") or {}).values():
        nodes |= set(cams)
    for e in reg:
        eid = e["entity_id"]
        if not eid.startswith("binary_sensor."):
            continue
        if not any(k in eid for k in ("person_occupancy", "person_detected", "_person")):
            continue
        if any(eid.split(".", 1)[1].startswith(s) for s in path_stems):
            nodes.add(eid)
    # Per-person trackers from the person entity's device_trackers attribute.
    out = []
    for r in cands:
        ts, slug = r["crossing_ts"], r["attrs"]["slug"]
        path_edges = {n: [(lu, st) for lu, _lc, st, _a in hist(n, ts - PATH_BUFFER_S, ts + POST_S)]
                      for n in sorted(nodes)}
        p = hist(f"person.{slug}", ts - GPS_MAX_AGE_S, ts + LATE_WINDOW_S + 60)
        trackers = []
        for _lu, _lc, _st, a in p[-1:]:
            trackers = (json.loads(a or "{}").get("device_trackers") or [])
        edges, gps = [], {}
        prev = None
        for lu, _lc, st, _a in p:
            if st == "home" and prev not in (None, "home"):
                edges.append((lu, "tracker"))
            prev = st
        for trk in trackers:
            th = hist(trk, ts - GPS_MAX_AGE_S, ts + GPS_POST_S)
            src = None
            prev = None
            for lu, lc, st, a in th:
                at = json.loads(a or "{}")
                src = at.get("source_type") or src
                if src == "gps" and at.get("latitude") is not None:
                    gps.setdefault(trk, []).append(
                        (lu, lc, at.get("latitude"), at.get("longitude"), at.get("gps_accuracy")))
                if st == "home" and prev not in (None, "home") and lu > ts:
                    edges.append((lu, "ble" if src == "bluetooth_le" else ("gps" if src == "gps" else "tracker")))
                prev = st
        out += build_rows([r], {slug: edges}, path_edges, {slug: gps})
    print(json.dumps({"generated_ts": now, "rows": out}, default=str))


def _merge_local(path):
    with open(path) as fh:
        week = json.load(fh)
    try:
        with open(FIXTURE) as fh:
            fixture = json.load(fh)
    except FileNotFoundError:
        fixture = {"schema": 1, "rows": []}
    fixture["rows"] = merge(fixture.get("rows", []), week.get("rows", []))
    with open(FIXTURE, "w") as fh:
        json.dump(fixture, fh, indent=1, sort_keys=True)
    print(f"merged {len(week.get('rows', []))} rows -> {len(fixture['rows'])} total")


if __name__ == "__main__":  # pragma: no cover
    if len(sys.argv) >= 3 and sys.argv[1] == "--merge":
        _merge_local(sys.argv[2])
    else:
        _run_on_ha()
