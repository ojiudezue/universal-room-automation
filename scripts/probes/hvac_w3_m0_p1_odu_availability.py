"""HVAC W3 M0-P1 — ODU `*_odu_status` availability pattern.

Question: per ODU entity, count and duration (p50/p90/p99/max) of unavailable/unknown episodes; how many
fall mid on-cycle (previous and next real states both `Stage N`), how many are adjacent to an off edge
(an `off` row within 60 s before or after), how many are within 15 min of an HA start.
Sets ODU_UNAVAILABLE_GRACE_S = next 30 s step >= p99 mid-cycle episode duration (cap 300 s).
STOP if > 10 % of on-cycles contain an episode longer than the cap.

Restart rule (operator): unknown/unavailable within 3 min of an HA start is a restart transient and is
EXCLUDED from the grace derivation (reported separately). An episode's duration runs from its first
bad row to the next real row; if HA was down in between (a start event inside the episode) that
episode is a restart episode by construction.
READ-ONLY: sqlite mode=ro, SELECT only, stdout only.
Run: ssh ha "python3 -" < scripts/probes/hvac_w3_m0_p1_odu_availability.py
"""
import sqlite3, bisect, math, collections
from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Chicago")
REC = "file:/config/home-assistant_v2.db?mode=ro"
c = sqlite3.connect(REC, uri=True)
print("opened:", REC)
ODU = {"zone_1": "sensor.office_b_odu_status", "zone_2": "sensor.thermostat_bryant_wifi_upstairs_odu_status",
       "zone_3": "sensor.thermostat_bryant_wifi_backhallway_odu_status"}
BAD = {"unavailable", "unknown", "", None}
CAP = 300
starts = [t for (t,) in c.execute(
    "SELECT e.time_fired_ts FROM events e JOIN event_types t ON e.event_type_id=t.event_type_id "
    "WHERE t.event_type='homeassistant_start' ORDER BY 1")]
stops = [t for (t,) in c.execute(
    "SELECT e.time_fired_ts FROM events e JOIN event_types t ON e.event_type_id=t.event_type_id "
    "WHERE t.event_type IN ('homeassistant_stop','homeassistant_final_write') ORDER BY 1")]
print(f"HA starts={len(starts)} stops={len(stops)}")

def within(lst, ts, s):
    i = bisect.bisect_left(lst, ts - s)
    return i < len(lst) and lst[i] <= ts + s

def pct(v, p):
    if not v: return 0
    v = sorted(v); return v[min(len(v) - 1, int(math.ceil(p / 100 * len(v))) - 1)]

def running(s):
    return s is not None and (s.startswith("Stage") or s in ("on", "dehumidify"))

grace_inputs = []
for zid, eid in ODU.items():
    r = list(c.execute("SELECT s.last_updated_ts, s.state FROM states s JOIN states_meta m ON s.metadata_id=m.metadata_id "
                       "WHERE m.entity_id=? ORDER BY 1", (eid,)))
    print(f"\n==== {zid} {eid}: rows={len(r)} first={datetime.fromtimestamp(r[0][0], TZ)} last={datetime.fromtimestamp(r[-1][0], TZ)}")
    eps = []  # (start, dur, prev_real, next_real, state, restart_flag)
    i = 0
    while i < len(r):
        ts, st = r[i]
        if st in BAD:
            j = i
            while j < len(r) and r[j][1] in BAD: j += 1
            end = r[j][0] if j < len(r) else None
            prev_real = next((r[k][1] for k in range(i - 1, -1, -1) if r[k][1] not in BAD), None)
            prev_ts = next((r[k][0] for k in range(i - 1, -1, -1) if r[k][1] not in BAD), None)
            next_real = r[j][1] if j < len(r) else None
            restart = within(starts, ts, 180) or (end is not None and any(ts <= s <= end for s in starts))
            eps.append(dict(t=ts, dur=(end - ts) if end else None, prev=prev_real, nxt=next_real, st=st,
                            restart=restart, near15=within(starts, ts, 900),
                            adj_off=(prev_real == "off" and prev_ts is not None and ts - prev_ts <= 60) or
                                    (next_real == "off" and end is not None and end - ts <= 60) or
                                    (next_real == "off" and end is not None)))
            i = j
        else:
            i += 1
    states = collections.Counter(e["st"] for e in eps)
    rs = [e for e in eps if e["restart"]]; nr = [e for e in eps if not e["restart"]]
    print(f"episodes={len(eps)} states={dict(states)} restart-transient (<=3 min of a start or spans a start)={len(rs)} "
          f"within 15 min of a start={sum(e['near15'] for e in eps)} NON-restart={len(nr)}")
    for lbl, grp in (("ALL", eps), ("NON-restart", nr)):
        d = [e["dur"] for e in grp if e["dur"] is not None]
        mid = [e for e in grp if running(e["prev"]) and running(e["nxt"])]
        adj = [e for e in grp if e["adj_off"]]
        md = [e["dur"] for e in mid if e["dur"] is not None]
        print(f"  {lbl:11s} n={len(grp)} dur p50={pct(d,50):.0f}s p90={pct(d,90):.0f}s p99={pct(d,99):.0f}s max={max(d) if d else 0:.0f}s | "
              f"mid on-cycle={len(mid)} (dur p99={pct(md,99):.0f}s max={max(md) if md else 0:.0f}s) | adjacent to/ending in off={len(adj)}")
        if lbl == "NON-restart":
            grace_inputs += md
    for e in eps[:25]:
        print(f"    {datetime.fromtimestamp(e['t'], TZ).strftime('%m-%d %H:%M:%S')} {e['st']:11s} dur={e['dur'] and round(e['dur'])}s "
              f"prev={e['prev']} next={e['nxt']} restart={e['restart']}")
    # on-cycles (real states; a restart episode splits) and how many contain a NON-restart episode > CAP
    cyc = 0; long_in = 0; on = None; has_long = False
    for k, (ts, st) in enumerate(r):
        if st in BAD:
            ep = next((e for e in eps if e["t"] == ts), None)
            if on is not None and ep is not None and not ep["restart"] and (ep["dur"] or 0) > CAP: has_long = True
            if ep is not None and ep["restart"]: on = None; has_long = False
            continue
        if running(st) and on is None: on = ts; has_long = False
        elif st == "off" and on is not None:
            cyc += 1; long_in += has_long; on = None; has_long = False
    print(f"  on-cycles={cyc}; containing a non-restart episode > {CAP}s = {long_in} ({100*long_in/max(cyc,1):.1f}%)")

p99 = pct(grace_inputs, 99)
grace = min(CAP, max(30, int(math.ceil(p99 / 30.0)) * 30)) if grace_inputs else None
print(f"\nNON-restart mid on-cycle episode durations pooled: n={len(grace_inputs)} p99={p99}")
print(f"ODU_UNAVAILABLE_GRACE_S = {grace if grace is not None else 'NO DATA (no non-restart mid-cycle episodes)'}")
