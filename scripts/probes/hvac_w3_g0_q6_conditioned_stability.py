"""HVAC W3 G0-Q6 — conditioned stability of refrigerant telemetry (informational, G3-b revival).

Q6: Bucket suction_superheat and discharge_temperature (odu_status attributes, 7-day recorder window,
samples taken only while SPAN >= 0.5 kW) by (ODU stage x outdoor-temp 5 F band); IQR per bucket with
n >= 30. Static pressure (sensor.*_static_pressure, LTS hourly mean since 2025-03) by month: median, IQR.
A drift detector is viable only if >= 3 buckets have superheat IQR <= 4 F.
Outdoor temp = the system's own Carrier *_outdoor_temperature sensor (state at sample time).
READ-ONLY (mode=ro), stdout only. Run: ssh ha "python3 -" < scripts/probes/hvac_w3_g0_q6_conditioned_stability.py
"""
import sqlite3, json, bisect, collections
from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Chicago")
REC = "file:/config/home-assistant_v2.db?mode=ro"
SYS = {"zone_1": ("office_b", "sensor.span_panel_ac1_power"),
       "zone_2": ("thermostat_bryant_wifi_upstairs", "sensor.span_panel_ac_2_power"),
       "zone_3": ("thermostat_bryant_wifi_backhallway", "sensor.span_panel_ac_3_power")}
c = sqlite3.connect(REC, uri=True)
print("opened:", REC)

def mid(e):
    r = c.execute("SELECT metadata_id FROM states_meta WHERE entity_id=?", (e,)).fetchone()
    return r[0] if r else None

def step(e):
    ts, vs = [], []
    for t, s in c.execute("SELECT last_updated_ts, state FROM states WHERE metadata_id=? ORDER BY 1", (mid(e),)):
        try: v = float(s)
        except (TypeError, ValueError): v = None
        ts.append(t); vs.append(v)
    return ts, vs

def at(series, t):
    ts, vs = series
    i = bisect.bisect_right(ts, t) - 1
    return vs[i] if i >= 0 else None

def iqr(x):
    x = sorted(x); n = len(x)
    return x[3 * n // 4] - x[n // 4]

tot_stable = 0
for zid, (pfx, span) in SYS.items():
    sp = step(span); oat = step(f"sensor.{pfx}_outdoor_temperature")
    buckets = collections.defaultdict(lambda: {"sh": [], "dt": []})
    for t, s, a in c.execute("SELECT s.last_updated_ts, s.state, sa.shared_attrs FROM states s LEFT JOIN state_attributes sa "
                             "ON s.attributes_id=sa.attributes_id WHERE s.metadata_id=? ORDER BY 1", (mid(f"sensor.{pfx}_odu_status"),)):
        if not s or not s.startswith("Stage"):
            continue
        k = at(sp, t)
        if k is None or k / 1000 < 0.5:
            continue
        o = at(oat, t)
        if o is None:
            continue
        a = json.loads(a) if a else {}
        key = (s, int(o // 5) * 5)
        if a.get("suction_superheat") is not None: buckets[key]["sh"].append(a["suction_superheat"])
        if a.get("discharge_temperature") is not None: buckets[key]["dt"].append(a["discharge_temperature"])
    print(f"\n==== {zid} ({pfx}): buckets with n>=30 (stage, OAT band F): superheat IQR / discharge IQR")
    stable = 0
    for key in sorted(buckets):
        b = buckets[key]
        if len(b["sh"]) >= 30:
            si = iqr(b["sh"]); di = iqr(b["dt"]) if len(b["dt"]) >= 30 else None
            stable += si <= 4
            print(f"   {key}: n={len(b['sh'])} superheat median={sorted(b['sh'])[len(b['sh'])//2]} IQR={si} | discharge IQR={di}")
    small = sum(1 for b in buckets.values() if len(b["sh"]) < 30)
    print(f"   buckets with superheat IQR <= 4 F: {stable} (buckets below n=30 and ignored: {small})")
    tot_stable += stable
    # static pressure LTS by month
    m = c.execute("SELECT id FROM statistics_meta WHERE statistic_id=?", (f"sensor.{pfx}_static_pressure",)).fetchone()
    bym = collections.defaultdict(list)
    for st, mean in c.execute("SELECT start_ts, mean FROM statistics WHERE metadata_id=?", (m[0],)):
        if mean: bym[datetime.fromtimestamp(st, TZ).strftime("%Y-%m")].append(mean)
    print("   static pressure LTS (psi) by month: median / IQR / n-hours")
    print("   " + " | ".join(f"{k}: {sorted(v)[len(v)//2]:.4f}/{iqr(v):.4f}/{len(v)}" for k, v in sorted(bym.items())))
print(f"\nTotal buckets (all systems) with superheat IQR <= 4 F: {tot_stable}")
