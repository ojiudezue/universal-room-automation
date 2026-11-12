"""Lock suspicious-arrival probe (GARAGE-REMOTE-LOCKOUT-SCHEDULE-1, plan D0).

READ-ONLY. Run on the HA host against the recorder:

    ssh ha "python3 -" < scripts/probes/lock_arrival_edge_probe.py > out.json

Emits JSON ``{"window": [start, end], "edges": [...], "crossings": [...]}``.

Per person ``-> home`` edge (from any non-home state):
  person, edge_ts, prev, dur (s until the person left home again; 1e9 if never),
  source (the person's ``source`` attribute at the edge), source_type,
  src_age (edge ts minus the last state CHANGE of the source tracker at or before
  the edge; None if the tracker has no history), unav_ago (s since ANY of the
  person's trackers last read unavailable/unknown).
Per proximity crossing (> 1500 m to <= 1500 m; unit ft on this house):
  sensor, ts, from_ft, to_ft, and ``edge_ts`` of a person edge within 0.5 s (or None).
No coordinates are emitted. Window: START_TS..END_TS (epoch seconds).
"""

import json
import sqlite3

START_TS = 1793873520.0  # 2026-11-05 04:12 CST
END_TS = 1794515400.0  # 2026-11-12 14:30 CST
PERSONS = ["oji_udezue", "ezinne", "jaya", "ziri"]
DISTANCE_SENSORS = ["sensor.madronehaos_oji_udezue_distance"]
RADIUS_FT = 4921.0  # 1500 m
UNREAL = {"unavailable", "unknown", None}

db = sqlite3.connect("file:/config/home-assistant_v2.db?mode=ro", uri=True)
c = db.cursor()
_items = json.load(open("/config/.storage/person"))["data"]["items"]
TRK = {p["id"]: set(p.get("device_trackers") or []) for p in _items}


def hist(eid):
    rows = c.execute(
        """select s.state, s.last_updated_ts, sa.shared_attrs from states s
        join states_meta m on s.metadata_id=m.metadata_id
        left join state_attributes sa on s.attributes_id=sa.attributes_id
        where m.entity_id=? order by s.last_updated_ts""",
        (eid,),
    ).fetchall()
    out = []
    for st, ts, a in rows:
        try:
            a = json.loads(a) if a else {}
        except Exception:
            a = {}
        out.append((ts, st, a))
    return out


def changes(h):
    ch, prev = [], object()
    for ts, st, a in h:
        if st != prev:
            ch.append((ts, st, a))
            prev = st
    return ch


edges = []
for p in PERSONS:
    ph = changes(hist("person." + p))
    trk = set(TRK.get(p, set()))
    for _ts, _st, a in ph:
        if a.get("source"):
            trk.add(a["source"])
    th = {t: changes(hist(t)) for t in trk}
    stype = {}
    for t, h in th.items():
        for _ts, _st, a in h:
            if a.get("source_type"):
                stype[t] = a["source_type"]
    for i in range(1, len(ph)):
        ts, st, a = ph[i]
        _pts, pst, _ = ph[i - 1]
        if st != "home" or pst == "home" or not (START_TS <= ts <= END_TS):
            continue
        nxt = ph[i + 1] if i + 1 < len(ph) else None
        src = a.get("source")
        last = [x for x in th.get(src, []) if x[0] <= ts + 0.5]
        unav_ago = None
        for _t, h in th.items():
            for x in h:
                if x[0] <= ts + 0.5 and x[1] in UNREAL:
                    ago = ts - x[0]
                    if unav_ago is None or ago < unav_ago:
                        unav_ago = ago
        edges.append(dict(
            person=p, edge_ts=ts, prev=pst,
            dur=(nxt[0] - ts) if nxt else 1e9,
            source=src, source_type=stype.get(src),
            src_age=(ts - last[-1][0]) if last else None,
            unav_ago=unav_ago,
        ))

crossings = []
for sid in DISTANCE_SENSORS:
    prev = None
    for ts, st, _a in hist(sid):
        try:
            v = float(st)
        except (TypeError, ValueError):
            v = None
        if (prev is not None and v is not None and prev > RADIUS_FT
                and v <= RADIUS_FT and START_TS <= ts <= END_TS):
            near = [e["edge_ts"] for e in edges if abs(e["edge_ts"] - ts) <= 0.5]
            crossings.append(dict(sensor=sid, ts=ts, from_ft=prev, to_ft=v,
                                  edge_ts=near[0] if near else None))
        if v is not None:
            prev = v

print(json.dumps({"window": [START_TS, END_TS], "edges": edges, "crossings": crossings}))
