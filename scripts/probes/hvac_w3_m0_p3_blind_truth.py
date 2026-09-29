"""HVAC W3 M0-P3 — does the ODU stage share hvac_action's blindness?

Question: ODU-running vs SPAN >= 0.2 kW time agreement, restricted to (a) G0's hvac_action-BLIND minutes
(cool mode, SPAN >= 0.5 kW, hvac_action != cooling), (b) the reverse phantom band (action == cooling and
SPAN < 0.05 kW, truly off), and (c) Carrier stale episodes, proxied two ways: the climate entity's
last_updated frozen > 15 min (the stale-reload machinery keys on climate age, hvac.py ~7040-7110), and
`*_updated_websocket_at` age > 15 min.
GO iff agreement >= 95 % in blind minutes.

Excluded: time where ODU is unavailable/unknown (reported), gaps > 1 h (HA down), restart transients
(unknown/unavailable rows within 3 min of an HA start dropped).
READ-ONLY: sqlite mode=ro, SELECT only, stdout only.
Run: ssh ha "python3 -" < scripts/probes/hvac_w3_m0_p3_blind_truth.py
"""
import sqlite3, json, bisect
from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Chicago")
REC = "file:/config/home-assistant_v2.db?mode=ro"
c = sqlite3.connect(REC, uri=True)
print("opened:", REC)
FIX = {"zone_1": ("climate.thermostat_bryant_wifi_studyb_zone_1", "sensor.span_panel_ac1_power", "sensor.office_b_odu_status", "sensor.office_b_updated_websocket_at"),
       "zone_2": ("climate.up_hallway_zone_2", "sensor.span_panel_ac_2_power", "sensor.thermostat_bryant_wifi_upstairs_odu_status", "sensor.thermostat_bryant_wifi_upstairs_updated_websocket_at"),
       "zone_3": ("climate.back_hallway_zone_3", "sensor.span_panel_ac_3_power", "sensor.thermostat_bryant_wifi_backhallway_odu_status", "sensor.thermostat_bryant_wifi_backhallway_updated_websocket_at")}
BAD = {"unavailable", "unknown", "", None}
COOL = {"cool", "heat_cool", "auto"}
starts = [t for (t,) in c.execute(
    "SELECT e.time_fired_ts FROM events e JOIN event_types t ON e.event_type_id=t.event_type_id "
    "WHERE t.event_type='homeassistant_start' ORDER BY 1")]
def near_start(ts, s=180):
    i = bisect.bisect_left(starts, ts - s)
    return i < len(starts) and starts[i] <= ts + s

def rows(eid, attrs=False):
    q = ("SELECT s.last_updated_ts, s.state, sa.shared_attrs FROM states s JOIN states_meta m ON s.metadata_id=m.metadata_id "
         "LEFT JOIN state_attributes sa ON s.attributes_id=sa.attributes_id WHERE m.entity_id=? ORDER BY 1")
    out = []
    for ts, st, a in c.execute(q, (eid,)):
        if st in BAD and near_start(ts): continue
        if attrs:
            try: a = json.loads(a).get("hvac_action") if a else None
            except Exception: a = None
        out.append((ts, st, a if attrs else None))
    return out

def running(s):
    return s is not None and (s.startswith("Stage") or s in ("on", "dehumidify"))

def parse_ts(s):
    try: return datetime.fromisoformat(s).timestamp()
    except Exception: return None

for zid, (clim, span, odu, ws) in FIX.items():
    cl = rows(clim, attrs=True); sp = rows(span); od = rows(odu)
    try: wsr = rows(ws)
    except Exception: wsr = []
    ev = [(t, 0, (s, a)) for t, s, a in cl] + [(t, 1, s) for t, s, _ in sp] + [(t, 2, s) for t, s, _ in od] + [(t, 3, parse_ts(s)) for t, s, _ in wsr]
    ev.sort(key=lambda x: (x[0], x[1]))
    cur = {0: (None, None), 1: None, 2: None, 3: None}; clim_ts = None; pt = None
    acc = {k: [0.0, 0.0, 0.0] for k in ("blind", "phantom_off", "stale_climate", "stale_ws", "all_cool")}  # agree, tot, odu_unknown
    for t, k, v in ev:
        if pt is not None and t - pt < 3600:
            dt = t - pt
            mode, act = cur[0]
            try: kw = float(cur[1]) / 1000.0
            except (TypeError, ValueError): kw = None
            o = cur[2]
            if mode in COOL and kw is not None:
                cats = ["all_cool"]
                if kw >= 0.5 and act != "cooling": cats.append("blind")
                if act == "cooling" and kw < 0.05: cats.append("phantom_off")
                if clim_ts is not None and pt - clim_ts > 900: cats.append("stale_climate")
                if cur[3] is not None and pt - cur[3] > 900: cats.append("stale_ws")
                for cat in cats:
                    if o in BAD or o is None:
                        acc[cat][2] += dt
                    else:
                        acc[cat][1] += dt
                        if running(o) == (kw >= 0.2): acc[cat][0] += dt
        if k == 0: cur[0] = v; clim_ts = t
        elif k == 1:
            if v not in BAD: cur[1] = v
        elif k == 2: cur[2] = v
        else: cur[3] = v
        pt = t
    # ---- decomposition of blind-minute disagreement: edge latency vs sustained blindness ----
    sx = []; pk = None
    for t, s_, _ in sp:
        try: kk = float(s_) / 1000.0
        except (TypeError, ValueError): continue
        if pk is not None and ((pk < 0.2 <= kk) or (kk < 0.2 <= pk)): sx.append(t)
        pk = kk
    ox = []; po = None
    for t, s_, _ in od:
        if s_ in BAD: po = None; continue
        if po is not None and running(po) != running(s_): ox.append(t)
        po = s_
    def near(lst, t, w):
        i = bisect.bisect_left(lst, t - w); return i < len(lst) and lst[i] <= t + w
    cur = {0: (None, None), 1: None, 2: None}; pt = None
    eps = []; ep = None; edge_ok = [0.0, 0.0]
    for t, k, v in ev:
        if k == 3: continue
        if pt is not None and t - pt < 3600:
            dt = t - pt; mode, act = cur[0]
            try: kw = float(cur[1]) / 1000.0
            except (TypeError, ValueError): kw = None
            o = cur[2]
            blind = mode in COOL and kw is not None and kw >= 0.5 and act != "cooling" and o not in BAD and o is not None
            dis = blind and not running(o)
            if blind and not (near(sx, pt, 300) or near(ox, pt, 300)):
                edge_ok[1] += dt; edge_ok[0] += dt if running(o) else 0
            if dis:
                if ep is None: ep = [pt, 0.0, o]
                ep[1] += dt
            elif ep is not None and not blind:
                eps.append(ep); ep = None
        if k == 0: cur[0] = v
        elif k == 1:
            if v not in BAD: cur[1] = v
        else: cur[2] = v
        pt = t
    if ep: eps.append(ep)
    d = sorted(e[1] for e in eps)
    print(f"\n==== {zid}")
    print(f"  blind-minute DISAGREEMENT episodes (ODU says off while SPAN>=0.5 & action!=cooling): n={len(eps)} total={sum(d)/60:.0f} min "
          f"dur p50={d[len(d)//2] if d else 0:.0f}s p90={d[int(len(d)*0.9)] if d else 0:.0f}s max={d[-1] if d else 0:.0f}s; "
          f"within 5 min of a SPAN-0.2 or ODU edge={sum(1 for e in eps if near(sx, e[0], 300) or near(ox, e[0], 300))}; >10 min={sum(1 for x in d if x>600)}")
    print(f"  blind minutes EXCLUDING +-5 min of any SPAN-0.2/ODU edge: {edge_ok[1]/60:.0f} min, ODU running share={100*edge_ok[0]/max(edge_ok[1],1):.1f}%")
    for e in sorted(eps, key=lambda e: -e[1])[:5]:
        print(f"    longest: {datetime.fromtimestamp(e[0], TZ).strftime('%m-%d %H:%M:%S')} {e[1]:.0f}s ODU={e[2]}")
    for cat, (a, tot, unk) in acc.items():
        print(f"  {cat:14s} minutes={tot/60:7.0f} (+ODU unknown {unk/60:.0f}) ODU-vs-SPAN>=0.2 agreement={100*a/max(tot,1):5.1f}%")
