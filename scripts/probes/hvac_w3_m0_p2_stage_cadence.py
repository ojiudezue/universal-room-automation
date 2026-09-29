"""HVAC W3 M0-P2 — ODU stage-update cadence and edge latency vs SPAN.

Question: per ODU entity, the `last_updated` gap distribution while in `Stage N` and while `off`
(recorder rows = last_updated changes; attribute churn writes rows too), and edge latency ODU off->Stage
vs SPAN rising through 0.2 kW, and Stage->off vs SPAN falling through 0.2 kW (p50/p95; signed, + = ODU late).
Sets ODU_STAGE_STALE_S = max(900 s, next 5-min step >= p99.9 running-state gap). Latency p95 > 120 s -> note.

Gap hygiene: a gap is excluded if an HA start falls inside it (HA down -> no rows), and the gap is
attributed to the state of the row that opens it. Rows in unavailable/unknown are not running/off and
open no gap. SPAN blips (non-numeric) are skipped (level held).
READ-ONLY: sqlite mode=ro, SELECT only, stdout only.
Run: ssh ha "python3 -" < scripts/probes/hvac_w3_m0_p2_stage_cadence.py
"""
import sqlite3, bisect, math
from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Chicago")
REC = "file:/config/home-assistant_v2.db?mode=ro"
c = sqlite3.connect(REC, uri=True)
print("opened:", REC)
FIX = {"zone_1": ("sensor.office_b_odu_status", "sensor.span_panel_ac1_power"),
       "zone_2": ("sensor.thermostat_bryant_wifi_upstairs_odu_status", "sensor.span_panel_ac_2_power"),
       "zone_3": ("sensor.thermostat_bryant_wifi_backhallway_odu_status", "sensor.span_panel_ac_3_power")}
BAD = {"unavailable", "unknown", "", None}
THR = 0.2
starts = [t for (t,) in c.execute(
    "SELECT e.time_fired_ts FROM events e JOIN event_types t ON e.event_type_id=t.event_type_id "
    "WHERE t.event_type='homeassistant_start' ORDER BY 1")]

def start_between(a, b):
    i = bisect.bisect_right(starts, a)
    return i < len(starts) and starts[i] <= b

def pct(v, p):
    if not v: return 0
    v = sorted(v); return v[min(len(v) - 1, int(math.ceil(p / 100 * len(v))) - 1)]

def running(s):
    return s is not None and (s.startswith("Stage") or s in ("on", "dehumidify"))

def rows(eid):
    return list(c.execute("SELECT s.last_updated_ts, s.state, s.last_changed_ts FROM states s JOIN states_meta m "
                          "ON s.metadata_id=m.metadata_id WHERE m.entity_id=? ORDER BY 1", (eid,)))

all_run_gaps = []
for zid, (odu, span) in FIX.items():
    r = rows(odu)
    print(f"\n==== {zid} {odu}: rows={len(r)} first={datetime.fromtimestamp(r[0][0], TZ)}")
    g_run, g_off, excl = [], [], 0
    attr_only = sum(1 for k in range(1, len(r)) if r[k][1] == r[k - 1][1])
    for k in range(len(r) - 1):
        t, s, _ = r[k]; t2 = r[k + 1][0]
        if s in BAD: continue
        if start_between(t, t2): excl += 1; continue
        (g_run if running(s) else g_off).append(t2 - t)
    all_run_gaps += g_run
    for lbl, g in (("Stage N", g_run), ("off", g_off)):
        print(f"  gap while {lbl:7s}: n={len(g)} p50={pct(g,50):.0f}s p90={pct(g,90):.0f}s p99={pct(g,99):.0f}s "
              f"p99.9={pct(g,99.9):.0f}s max={max(g) if g else 0:.0f}s  (>900s: {sum(1 for x in g if x > 900)})")
    print(f"  rows that repeat the previous state (attribute-only churn)={attr_only}; gaps excluded for spanning an HA start={excl}")
    # edges
    ou, od, prev = [], [], None
    for t, s, _ in r:
        if s in BAD: prev = None; continue
        if prev is not None:
            if prev == "off" and running(s): ou.append(t)
            elif running(prev) and s == "off": od.append(t)
        prev = s
    su, sd, pk = [], [], None
    for t, s, _ in rows(span):
        try: k = float(s) / 1000.0
        except (TypeError, ValueError): continue
        if pk is not None:
            if pk < THR <= k: su.append(t)
            elif k < THR <= pk: sd.append(t)
        pk = k
    for lbl, oe, se in (("off->Stage vs SPAN rise", ou, su), ("Stage->off vs SPAN fall", od, sd)):
        lat = []
        for t in oe:
            i = bisect.bisect_left(se, t - 900)
            cands = [x for x in se[i:i + 20] if abs(x - t) <= 900]
            if cands:
                lat.append(t - min(cands, key=lambda x: abs(x - t)))
        a = [abs(x) for x in lat]
        print(f"  {lbl}: paired {len(lat)}/{len(oe)} within ±15 min | signed (ODU-SPAN, +=ODU late) p50={pct(lat,50):.0f}s "
              f"| |lat| p50={pct(a,50):.0f}s p95={pct(a,95):.0f}s max={max(a) if a else 0:.0f}s | ODU late share={100*sum(1 for x in lat if x>0)/max(len(lat),1):.0f}%")

p999 = pct(all_run_gaps, 99.9)
stale = max(900, int(math.ceil(p999 / 300.0)) * 300)
print(f"\npooled running-state gaps n={len(all_run_gaps)} p99={pct(all_run_gaps,99):.0f}s p99.9={p999:.0f}s max={max(all_run_gaps):.0f}s")
print(f"ODU_STAGE_STALE_S = max(900, ceil5min(p99.9)) = {stale}")
