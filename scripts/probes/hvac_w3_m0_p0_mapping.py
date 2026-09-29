"""HVAC W3 M0-P0 — zone -> ODU mapping, verified by physics (co-movement), not by name.

Question: for each of the 3 Carrier `*_odu_status` entities, which zone's SPAN AC circuit and
`climate.*` entity co-move with its off->Stage transitions?  Report % of ODU off->Stage edges followed
within 120 s by a SPAN >= 0.2 kW rise on EACH of the 3 circuits (+ symmetric/lead-tolerant variants,
because the ODU state cadence is coarse and SPAN may lead), and the same for Stage->off vs SPAN fall,
and for climate hvac_action -> cooling edges.
GO iff every ODU co-moves >= 90 % with exactly one circuit, and that circuit is the fixture's.

Restart rule: unknown/unavailable rows within 3 min of an HA start are dropped (restart transients);
an edge is only counted when both sides are real states (off / Stage N).
READ-ONLY: sqlite mode=ro, SELECT only, stdout only.
Run: ssh ha "python3 -" < scripts/probes/hvac_w3_m0_p0_mapping.py
"""
import sqlite3, json, bisect
from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Chicago")
REC = "file:/config/home-assistant_v2.db?mode=ro"
c = sqlite3.connect(REC, uri=True)
print("opened:", REC)
ODU = {"office_b": "sensor.office_b_odu_status",
       "upstairs": "sensor.thermostat_bryant_wifi_upstairs_odu_status",
       "backhallway": "sensor.thermostat_bryant_wifi_backhallway_odu_status"}
SPAN = {"ac1": "sensor.span_panel_ac1_power", "ac_2": "sensor.span_panel_ac_2_power", "ac_3": "sensor.span_panel_ac_3_power"}
CLIM = {"zone_1": "climate.thermostat_bryant_wifi_studyb_zone_1", "zone_2": "climate.up_hallway_zone_2",
        "zone_3": "climate.back_hallway_zone_3"}
FIXTURE = {"office_b": ("ac1", "zone_1"), "upstairs": ("ac_2", "zone_2"), "backhallway": ("ac_3", "zone_3")}
THR = 0.2
BAD = {"unavailable", "unknown", "", None}

starts = [t for (t,) in c.execute(
    "SELECT e.time_fired_ts FROM events e JOIN event_types t ON e.event_type_id=t.event_type_id "
    "WHERE t.event_type='homeassistant_start' ORDER BY 1")]
print(f"HA starts in recorder: {len(starts)}; first {datetime.fromtimestamp(starts[0], TZ) if starts else None}")

def near_start(ts, s=180):
    i = bisect.bisect_left(starts, ts - s)
    return i < len(starts) and starts[i] <= ts + s

def rows(eid, attrs=False):
    q = ("SELECT s.last_updated_ts, s.state, sa.shared_attrs FROM states s JOIN states_meta m ON s.metadata_id=m.metadata_id "
         "LEFT JOIN state_attributes sa ON s.attributes_id=sa.attributes_id WHERE m.entity_id=? ORDER BY s.last_updated_ts")
    out = []
    for ts, st, a in c.execute(q, (eid,)):
        if st in BAD and near_start(ts):
            continue  # restart transient
        if attrs:
            try: a = json.loads(a).get("hvac_action") if a else None
            except Exception: a = None
            out.append((ts, st, a))
        else:
            out.append((ts, st))
    return out

def kw(s):
    try: return float(s) / 1000.0
    except (TypeError, ValueError): return None

def running(s):
    return s is not None and (s.startswith("Stage") or s in ("on", "dehumidify"))

# ODU edges (real states on both sides; a bad state between breaks adjacency)
odu_edges = {}
for name, eid in ODU.items():
    r = rows(eid); up = []; dn = []; prev = None
    for ts, st in r:
        if st in BAD:
            prev = None; continue
        if prev is not None:
            if prev == "off" and running(st): up.append(ts)
            elif running(prev) and st == "off": dn.append(ts)
        prev = st
    odu_edges[name] = (up, dn)
    print(f"{eid}: rows={len(r)} first={datetime.fromtimestamp(r[0][0], TZ)} off->run edges={len(up)} run->off edges={len(dn)}")

# SPAN crossings at THR
span_x = {}
for name, eid in SPAN.items():
    r = rows(eid); up = []; dn = []; prev = None
    for ts, st in r:
        k = kw(st)
        if k is None:
            continue  # blip: keep previous level (short blips; P1/G0 measured p50 1 s)
        if prev is not None:
            if prev < THR <= k: up.append(ts)
            elif k < THR <= prev: dn.append(ts)
        prev = k
    span_x[name] = (up, dn)
    print(f"{eid}: rows={len(r)} rises>={THR}kW={len(up)} falls={len(dn)}")

clim_x = {}
for name, eid in CLIM.items():
    r = rows(eid, attrs=True); up = []; dn = []; prev = None
    for ts, st, a in r:
        if st in BAD:
            prev = None; continue
        if prev is not None:
            if prev != "cooling" and a == "cooling": up.append(ts)
            elif prev == "cooling" and a != "cooling": dn.append(ts)
        prev = a
    clim_x[name] = (up, dn)
    print(f"{eid}: action->cooling edges={len(up)} cooling->other={len(dn)}")

def frac(edges, cands, lo, hi):
    """fraction of edges with a candidate crossing in [edge+lo, edge+hi]"""
    if not edges: return float("nan")
    hit = 0
    for t in edges:
        i = bisect.bisect_left(cands, t + lo)
        if i < len(cands) and cands[i] <= t + hi: hit += 1
    return 100.0 * hit / len(edges)

WINDOWS = [("strict [0,+120s]", 0, 120), ("lead-tolerant [-300,+120s]", -300, 120), ("symmetric [-120,+120s]", -120, 120)]
verdict_ok = True
for name, (up, dn) in odu_edges.items():
    print(f"\n==== ODU {name} (fixture -> {FIXTURE[name]})")
    for lbl, lo, hi in WINDOWS:
        row_up = {s: frac(up, span_x[s][0], lo, hi) for s in SPAN}
        row_dn = {s: frac(dn, span_x[s][1], lo, hi) for s in SPAN}
        row_cl = {z: frac(up, clim_x[z][0], lo, hi) for z in CLIM}
        print(f"  {lbl:28s} off->Stage vs SPAN rise: " + "  ".join(f"{s}={v:5.1f}%" for s, v in row_up.items()))
        print(f"  {'':28s} Stage->off vs SPAN fall: " + "  ".join(f"{s}={v:5.1f}%" for s, v in row_dn.items()))
        print(f"  {'':28s} off->Stage vs action->cooling: " + "  ".join(f"{z}={v:5.1f}%" for z, v in row_cl.items()))
    # decision on the lead-tolerant window (documented), also report strict
    for lbl, lo, hi in WINDOWS[:2]:
        row_up = {s: frac(up, span_x[s][0], lo, hi) for s in SPAN}
        ge90 = [s for s, v in row_up.items() if v >= 90]
        ok = ge90 == [FIXTURE[name][0]]
        print(f"  RULE ({lbl}): circuits >=90% = {ge90} -> {'MATCHES fixture' if ok else 'NO unique fixture match'}")

# Time-state agreement as a second, cadence-independent discriminator: % of time ODU-running == SPAN>=0.2
print("\n==== time-share agreement ODU running vs SPAN >= 0.2 kW (all modes, ODU real states only)")
def series_level(eid, fn):
    return [(ts, fn(st)) for ts, st in rows(eid)]
for name, eid in ODU.items():
    o = [(ts, (None if st in BAD else running(st))) for ts, st in rows(eid)]
    res = {}
    for s, seid in SPAN.items():
        sp = [(ts, kw(st)) for ts, st in rows(seid)]
        ev = [(t, 0, v) for t, v in o] + [(t, 1, v) for t, v in sp]
        ev.sort(key=lambda x: (x[0], x[1]))
        ov = None; sv = None; pt = None; agree = tot = 0.0
        for t, k, v in ev:
            if pt is not None and ov is not None and sv is not None:
                dt = t - pt
                if dt < 3600:  # skip HA-down gaps
                    tot += dt; agree += dt if ov == (sv >= THR) else 0
            if k == 0: ov = v
            elif v is not None: sv = v
            pt = t
        res[s] = 100 * agree / max(tot, 1)
    print(f"  {name:12s} " + "  ".join(f"{s}={v:5.1f}%" for s, v in res.items()))
