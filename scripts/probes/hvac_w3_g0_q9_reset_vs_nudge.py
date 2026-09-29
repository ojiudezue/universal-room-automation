"""HVAC W3 G0-Q9 — reset vs nudge SPAN trajectory (P2 -> G3-a).

Q9: For every hard reset and every nudge_started in ac_ramp_events over the last 7 days (SPAN
fine-grained recorder states) and 30 days (older events: short-term 5-min stats if still kept, else
not assessable), the SPAN kW trajectory 0-20 min after. Does a reset produce draw -> ~0 -> full-draw
restart within 10 min (a forced short cycle), while a nudge produces a partial kW drop without
reaching zero?
Recommend switch.ura_hvac_coordinator_ac_reset OFF (config) if >= 50 % of resets show
off -> full-draw restart <= 10 min. Otherwise leave it on.
Definitions: before = last SPAN kW at/before the event; OFF = first sample < 0.05 kW within 20 min;
RESTART = first sample >= 0.8 x before (and >= 0.5 kW) after OFF; forced short cycle = OFF then
RESTART within 10 min of OFF.
READ-ONLY (mode=ro). Run: ssh ha "python3 -" < scripts/probes/hvac_w3_g0_q9_reset_vs_nudge.py
"""
import sqlite3, bisect, statistics as st
from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Chicago")
REC = "file:/config/home-assistant_v2.db?mode=ro"
URA = "file:/config/universal_room_automation/data/universal_room_automation.db?mode=ro"
SPAN = {"zone_1": "sensor.span_panel_ac1_power", "zone_2": "sensor.span_panel_ac_2_power", "zone_3": "sensor.span_panel_ac_3_power"}
rec = sqlite3.connect(REC, uri=True); ura = sqlite3.connect(URA, uri=True)
print("opened:", REC, "|", URA)
ser = {}
for z, e in SPAN.items():
    mid = rec.execute("SELECT metadata_id FROM states_meta WHERE entity_id=?", (e,)).fetchone()[0]
    pts = []
    for ts, s in rec.execute("SELECT last_updated_ts, state FROM states WHERE metadata_id=? ORDER BY 1", (mid,)):
        try: pts.append((ts, float(s) / 1000))
        except (TypeError, ValueError): pass
    ser[z] = pts
earliest = min(p[0][0] for p in ser.values())
print("SPAN recorder earliest:", datetime.fromtimestamp(earliest, TZ))
sts = rec.execute("SELECT min(start_ts) FROM statistics_short_term").fetchone()[0]
print("statistics_short_term earliest:", datetime.fromtimestamp(sts, TZ) if sts else None)

def traj(z, t):
    pts = ser[z]; ts = [p[0] for p in pts]
    i = bisect.bisect_right(ts, t) - 1
    if i < 0:
        return None
    before = pts[i][1]
    win = [p for p in pts[i:] if p[0] <= t + 1200]
    mn = min(p[1] for p in win)
    off = next((p[0] for p in win if p[0] >= t and p[1] < 0.05), None)
    rst = None
    if off is not None:
        rst = next((p[0] for p in win if p[0] > off and p[1] >= max(0.8 * before, 0.5)), None)
    return before, mn, off, rst

ev = ura.execute("SELECT zone_id, timestamp, event_type, kwh_rate_before, action_taken, reset_outcome FROM ac_ramp_events "
                 "WHERE event_type IN ('hard_reset_started','nudge_started') ORDER BY timestamp").fetchall()
res = {"hard_reset_started": [], "nudge_started": []}
older = {"hard_reset_started": 0, "nudge_started": 0}
for z, ts, et, kb, act, ro in ev:
    t = datetime.fromisoformat(ts).timestamp()
    if t < earliest + 60 or z not in SPAN:
        older[et] += 1; continue
    tr = traj(z, t)
    if tr is None:
        older[et] += 1; continue
    before, mn, off, rst = tr
    forced = off is not None and rst is not None and rst - off <= 600
    res[et].append((ts[:16], z, before, mn, None if off is None else round(off - t), None if rst is None else round(rst - t), forced))
for et, lst in res.items():
    n = len(lst); reached0 = sum(1 for x in lst if x[4] is not None); forced = sum(1 for x in lst if x[6])
    ratio = [x[3] / x[2] for x in lst if x[2] and x[2] >= 0.5]
    print(f"\n{et}: in 7-d SPAN window n={n} (older, not assessable at 10-min resolution: {older[et]})")
    print(f"  reached ~0 kW (<0.05) within 20 min: {reached0}/{n} = {100*reached0/max(n,1):.0f}%")
    print(f"  forced short cycle (OFF then full-draw RESTART <= 10 min after OFF): {forced}/{n} = {100*forced/max(n,1):.0f}%")
    if ratio:
        print(f"  min-kW / before-kW (events with before >= 0.5 kW): median={st.median(ratio):.2f} p25={sorted(ratio)[len(ratio)//4]:.2f}")
    if et == "hard_reset_started":
        for x in lst:
            print("   ", x)
    # restart delay distribution
    d = [x[5] - x[4] for x in lst if x[4] is not None and x[5] is not None]
    if d:
        print(f"  OFF->RESTART seconds: n={len(d)} median={st.median(d):.0f} min={min(d)} max={max(d)}")
print("\nhard resets over all 30 d by zone:", dict((z, sum(1 for e in ev if e[0] == z and e[2] == 'hard_reset_started')) for z in SPAN))
