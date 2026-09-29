"""HVAC W3 M0-P5 — stage-derived compressor short cycles.

Question: per zone, on-cycles from ODU off<->Stage edges, run through the plan §5.2 grace state machine
(RUNNING->UNKNOWN keeps on_since; UNKNOWN->RUNNING within grace continues; UNKNOWN->OFF within grace
discards; UNKNOWN longer than grace drops), counting cycles < 600 s and flap (< 60 s); compared, over the
SAME window, with SPAN@0.2 kW crossings and the hvac_action producer replica (hvac.py:6099-6210).
Also: stale guard (ODU_STAGE_STALE_S from P2) — a RUNNING row older than the stale window when the next
row arrives is treated as UNKNOWN for that span (the tick-time sweep in the plan).
GO for the short-cycle wiring iff stage flap < 5 % on every zone.

Constants in use (from M0-P1 / M0-P2): GRACE_S = 300, STALE_S = 900.
READ-ONLY: sqlite mode=ro, SELECT only, stdout only.
Run: ssh ha "python3 -" < scripts/probes/hvac_w3_m0_p5_stage_short_cycles.py
"""
import sqlite3, json, bisect, math
from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Chicago")
REC = "file:/config/home-assistant_v2.db?mode=ro"
c = sqlite3.connect(REC, uri=True)
print("opened:", REC)
GRACE_S = 300
STALE_S = 900
SC_S = 600
FIX = {"zone_1": ("climate.thermostat_bryant_wifi_studyb_zone_1", "sensor.span_panel_ac1_power", "sensor.office_b_odu_status"),
       "zone_2": ("climate.up_hallway_zone_2", "sensor.span_panel_ac_2_power", "sensor.thermostat_bryant_wifi_upstairs_odu_status"),
       "zone_3": ("climate.back_hallway_zone_3", "sensor.span_panel_ac_3_power", "sensor.thermostat_bryant_wifi_backhallway_odu_status")}
BAD = {"unavailable", "unknown", "", None}
starts = [t for (t,) in c.execute(
    "SELECT e.time_fired_ts FROM events e JOIN event_types t ON e.event_type_id=t.event_type_id "
    "WHERE t.event_type='homeassistant_start' ORDER BY 1")]
def near_start(ts, s=180):
    i = bisect.bisect_left(starts, ts - s)
    return i < len(starts) and starts[i] <= ts + s
def start_between(a, b):
    i = bisect.bisect_right(starts, a)
    return i < len(starts) and starts[i] <= b

def rows(eid, attrs=False):
    q = ("SELECT s.last_updated_ts, s.state, sa.shared_attrs FROM states s JOIN states_meta m ON s.metadata_id=m.metadata_id "
         "LEFT JOIN state_attributes sa ON s.attributes_id=sa.attributes_id WHERE m.entity_id=? ORDER BY 1")
    out = []
    for ts, st, a in c.execute(q, (eid,)):
        if attrs:
            try: a = json.loads(a).get("hvac_action") if a else None
            except Exception: a = None
        out.append((ts, st, a if attrs else None))
    return out

def cstate(s):
    if s in BAD: return "UNKNOWN"
    if s == "off": return "OFF"
    if s.startswith("Stage") or s in ("on", "dehumidify"): return "RUNNING"
    return "UNKNOWN"

def pct(v, p):
    if not v: return 0
    v = sorted(v); return v[min(len(v) - 1, int(math.ceil(p / 100 * len(v))) - 1)]

for zid, (clim, span, odu) in FIX.items():
    od = rows(odu); t_lo, t_hi = od[0][0], od[-1][0]
    # ODU state machine per plan §5.2 (event-driven; restart = HA start between rows -> drop on_since, RAM-only)
    on_since = None; unknown_since = None; prev = None; prev_t = None; prev_raw = None
    cycles = []; discarded = dropped_grace = dropped_restart = dropped_stale = 0
    for t, s, _ in od:
        if prev_t is not None and start_between(prev_t, t):
            if on_since is not None: dropped_restart += 1
            on_since = None; unknown_since = None; prev = None
        new = cstate(s)
        # stale guard: a RUNNING state that went un-updated > STALE_S is UNKNOWN from prev_t+STALE_S
        stale_hit = prev_raw == "RUNNING" and prev_t is not None and t - prev_t > STALE_S and unknown_since is None
        if stale_hit:
            unknown_since = prev_t + STALE_S
        # grace expiry check on each event
        if unknown_since is not None and on_since is not None and t - unknown_since > GRACE_S:
            dropped_grace += 1; on_since = None; unknown_since = None
            if stale_hit: dropped_stale += 1
        if new == "RUNNING":
            if on_since is None and prev == "OFF": on_since = t
            unknown_since = None
        elif new == "OFF":
            if on_since is not None:
                if unknown_since is not None:
                    discarded += 1  # UNKNOWN -> OFF within grace: ambiguous end
                else:
                    cycles.append((on_since, t))
            on_since = None; unknown_since = None
        else:  # UNKNOWN
            if on_since is not None and unknown_since is None: unknown_since = t
        if new != "UNKNOWN":
            prev = new
        elif not (on_since is not None and unknown_since is not None):
            prev = "UNKNOWN"  # outside a held cycle an UNKNOWN breaks adjacency (no on_since from UNKNOWN->RUNNING)
        prev_t = t; prev_raw = new
    d = [b - a for a, b in cycles]
    sc = [x for x in d if x < SC_S]; fl = [x for x in d if x < 60]
    # SPAN @0.2 over the same window
    sd = []; on = None
    for t, s, _ in rows(span):
        if t < t_lo or t > t_hi: continue
        try: k = float(s) / 1000.0
        except (TypeError, ValueError): continue  # hold level through blips
        if k >= 0.2 and on is None: on = t
        elif k < 0.2 and on is not None: sd.append(t - on); on = None
    # hvac_action producer replica (cooling only here; heating reported separately)
    ad = []; aon = None; prv = None; acyc = []
    for t, s, a in rows(clim, attrs=True):
        if t < t_lo or t > t_hi: continue
        if prv is None: prv = (s, a); continue
        ps, pa = prv; prv = (s, a)
        if s in BAD or ps in BAD or a is None: aon = None; continue
        if pa == a: continue
        if pa != "cooling" and a == "cooling": aon = t
        elif pa == "cooling" and a != "cooling" and aon is not None: ad.append(t - aon); acyc.append((aon, t)); aon = None
    print(f"\n==== {zid} window {datetime.fromtimestamp(t_lo, TZ):%m-%d %H:%M} .. {datetime.fromtimestamp(t_hi, TZ):%m-%d %H:%M}")
    print(f"  ODU stage : cycles={len(d)} short(<600s)={len(sc)} flap(<60s)={len(fl)} = {100*len(fl)/max(len(d),1):.1f}% | "
          f"dur p5={pct(d,5):.0f}s p50={pct(d,50):.0f}s | discarded(UNKNOWN->OFF)={discarded} dropped(grace)={dropped_grace} "
          f"(of which stale-guard={dropped_stale}) dropped(restart)={dropped_restart}")
    print(f"  SPAN@0.2  : cycles={len(sd)} short(<600s)={sum(1 for x in sd if x < SC_S)} flap(<60s)={sum(1 for x in sd if x < 60)} = {100*sum(1 for x in sd if x < 60)/max(len(sd),1):.1f}%")
    print(f"  hvac_action (cooling): cycles={len(ad)} short(<600s)={sum(1 for x in ad if x < SC_S)} flap(<60s)={sum(1 for x in ad if x < 60)}")
    osc = [(a, b) for a, b in cycles if b - a < SC_S]; asc = [(a, b) for a, b in acyc if b - a < SC_S]
    ov = sum(1 for a, b in osc if any(x < b + 120 and y > a - 120 for x, y in asc))
    print(f"  overlap: {ov}/{len(osc)} ODU short cycles coincide (+-120 s) with an hvac_action short cycle; "
          f"total-cycle count diff ODU vs action = {len(d)-len(ad):+d}; short-cycle count diff = {len(sc)-len(asc):+d}")
    print(f"  ODU short cycles (local start, dur s): {[(datetime.fromtimestamp(a, TZ).strftime('%m-%d %H:%M'), round(b-a)) for a, b in cycles if b-a < SC_S][:15]}")
