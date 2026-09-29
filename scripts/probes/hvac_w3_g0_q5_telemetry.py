"""HVAC W3 G0-Q5 — Carrier telemetry coverage & freshness, per system (G3-b eligibility).

Q5: For each of the 3 systems over the 7-day recorder window: state distribution of *_odu_status /
*_idu_status; attribute keys present and their non-null fraction WHILE SPAN draw >= 0.5 kW
(suction_superheat, discharge_temperature, suction_pressure, outdoor_coil_temperature, line_voltage,
static_pressure, blower_rpm, airflow_cfm); median/p95 gap between value changes while running; age of
*_updated_websocket_at / *_updated_all_data_at; any *odu_var* in states_meta?
G3-b only ever eligible if all 3 systems carry superheat + discharge + static at >= 90 % non-null while
running AND p95 freshness <= 30 min.
READ-ONLY (mode=ro), stdout only. Run: ssh ha "python3 -" < scripts/probes/hvac_w3_g0_q5_telemetry.py
"""
import sqlite3, json, collections
from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Chicago")
REC = "file:/config/home-assistant_v2.db?mode=ro"
SYS = {  # hand-built fixture (hvac_w3_g0_fixture.py)
    "zone_1": ("office_b", "sensor.span_panel_ac1_power"),
    "zone_2": ("thermostat_bryant_wifi_upstairs", "sensor.span_panel_ac_2_power"),
    "zone_3": ("thermostat_bryant_wifi_backhallway", "sensor.span_panel_ac_3_power"),
}
ODU_KEYS = ["suction_superheat", "discharge_temperature", "suction_pressure", "outdoor_coil_temperature", "line_voltage", "static_pressure", "blower_rpm"]
IDU_KEYS = ["airflow_cfm", "static_pressure", "blower_rpm"]
c = sqlite3.connect(REC, uri=True)
print("opened:", REC)
print("odu_var in states_meta:", [r[0] for r in c.execute("SELECT entity_id FROM states_meta WHERE entity_id LIKE '%odu_var%'")])

def rows(eid):
    mid = c.execute("SELECT metadata_id FROM states_meta WHERE entity_id=?", (eid,)).fetchone()
    if not mid:
        return []
    out = []
    for ts, s, a in c.execute("SELECT s.last_updated_ts, s.state, sa.shared_attrs FROM states s LEFT JOIN state_attributes sa "
                              "ON s.attributes_id=sa.attributes_id WHERE s.metadata_id=? ORDER BY 1", (mid[0],)):
        try: out.append((ts, s, json.loads(a) if a else {}))
        except Exception: out.append((ts, s, {}))
    return out

def running_intervals(span_eid):
    iv = []; on = None; last = None
    for ts, s, _ in rows(span_eid):
        try: k = float(s) / 1000
        except (TypeError, ValueError): k = None
        if k is not None and k >= 0.5 and on is None: on = ts
        elif (k is None or k < 0.5) and on is not None: iv.append((on, ts)); on = None
        last = ts
    if on is not None: iv.append((on, last))
    return iv

def overlap(a0, a1, iv):
    return sum(max(0, min(a1, b1) - max(a0, b0)) for b0, b1 in iv)

summary = {}
for zid, (pfx, span) in SYS.items():
    iv = running_intervals(span); run_s = sum(b - a for a, b in iv)
    print(f"\n==== {zid} system {pfx} | SPAN-running {run_s/3600:.1f} h over window")
    res = {}
    for kind, keys in (("odu", ODU_KEYS), ("idu", IDU_KEYS)):
        r = rows(f"sensor.{pfx}_{kind}_status")
        if not r:
            print(f"  {kind}: NO ENTITY"); continue
        t_end = r[-1][0]
        dist = collections.Counter()
        present = collections.Counter(); keyset = set()
        changes = collections.defaultdict(list); prevv = {}
        for i, (ts, s, a) in enumerate(r):
            nxt = r[i + 1][0] if i + 1 < len(r) else t_end
            dist[s] += nxt - ts
            ov = overlap(ts, nxt, iv)
            keyset |= set(a)
            for k in keys:
                if a.get(k) is not None:
                    present[k] += ov
                v = a.get(k)
                if k in prevv and v != prevv[k] and overlap(ts - 1, ts + 1, iv) > 0:
                    changes[k].append(ts)
                prevv[k] = v
        tot = sum(dist.values()) or 1
        print(f"  {kind}_status state share: " + ", ".join(f"{k} {100*v/tot:.1f}%" for k, v in dist.most_common(8)))
        print(f"  {kind} attribute keys seen: {sorted(keyset)}")
        for k in keys:
            g = sorted(b - a for a, b in zip(changes[k], changes[k][1:]))
            nn = 100 * present[k] / max(run_s, 1)
            p50 = g[len(g) // 2] / 60 if g else None; p95 = g[int(len(g) * 0.95)] / 60 if g else None
            print(f"    {k:26s} non-null while running {nn:5.1f}% | value changes while running={len(changes[k])} gap p50={p50 if p50 is None else round(p50,1)} min p95={p95 if p95 is None else round(p95,1)} min")
            res[(kind, k)] = (nn, p95)
    for fe in ("updated_websocket_at", "updated_all_data_at"):
        r = rows(f"sensor.{pfx}_{fe}")
        ages = []
        for i, (ts, s, _) in enumerate(r):
            try: v = datetime.fromisoformat(s).timestamp()
            except Exception: continue
            nxt = r[i + 1][0] if i + 1 < len(r) else ts
            t = ts
            while t < nxt:   # sample age every 60 s until the next row
                ages.append(t - v); t += 60
        ages.sort()
        if ages:
            print(f"  {fe}: age p50={ages[len(ages)//2]/60:.1f} min p95={ages[int(len(ages)*0.95)]/60:.1f} min max={ages[-1]/60:.1f} min (n={len(ages)} 1-min samples)")
    summary[zid] = res

print("\n==== G3-b eligibility (superheat + discharge + static >= 90 % non-null while running, p95 value-change gap <= 30 min)")
ok_all = True
for zid, res in summary.items():
    for key in (("odu", "suction_superheat"), ("odu", "discharge_temperature"), ("odu", "static_pressure")):
        nn, p95 = res.get(key, (0, None))
        ok = nn >= 90 and p95 is not None and p95 <= 30
        ok_all &= ok
        print(f"  {zid} {key[1]}: non-null {nn:.1f}% p95 gap {p95 if p95 is None else round(p95,1)} min -> {'PASS' if ok else 'FAIL'}")
print("G3-b telemetry gate:", "PASS" if ok_all else "FAIL")
