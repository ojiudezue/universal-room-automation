"""HVAC W3 G0-Q7 — hvac_action vs SPAN circuit draw (G2 short-cycle gate).

Q7: Per zone, cool mode, 7 days: minutes where SPAN >= 0.5 kW & hvac_action != cooling (BLIND) and
minutes where SPAN < 0.5 kW & hvac_action == cooling (PHANTOM RUN). Short cycles (< 600 s) derived
from hvac_action (replicating the producer hvac.py:6097-6210, incl. its unavailable-drop rule) vs from
SPAN 0.5 kW crossings, plus the % of hvac_action short cycles that a SPAN on-cycle < 600 s overlaps.
SPAN flap: SPAN on-cycles < 60 s, and the kW floor across genuine (>= 600 s) on-cycles.
Plan REV 2 additions: ODU `Stage N`/`off` vs SPAN agreement % (L6); SPAN unavailable/unknown episodes
that occur mid on-cycle (M4).
GO (short-cycle re-source) if corroboration < 80 % OR counts differ by > 50 %, AND SPAN flap < 5 %.

Fixture (hand-built, hvac_w3_g0_fixture.py, 2026-09-28):
  zone_1 climate.thermostat_bryant_wifi_studyb_zone_1 -> sensor.span_panel_ac1_power
  zone_2 climate.up_hallway_zone_2                  -> sensor.span_panel_ac_2_power
  zone_3 climate.back_hallway_zone_3                -> sensor.span_panel_ac_3_power
READ-ONLY (mode=ro), stdout only.  Run: ssh ha "python3 -" < scripts/probes/hvac_w3_g0_q7_action_vs_span.py
"""
import sqlite3, json, collections, statistics as st
from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Chicago")
REC = "file:/config/home-assistant_v2.db?mode=ro"
ON_KW = 0.5
SC_S = 600
ODU = {"zone_1": "sensor.office_b_odu_status", "zone_2": "sensor.thermostat_bryant_wifi_upstairs_odu_status",
       "zone_3": "sensor.thermostat_bryant_wifi_backhallway_odu_status"}
FIX = {
    "zone_1": ("climate.thermostat_bryant_wifi_studyb_zone_1", "sensor.span_panel_ac1_power"),
    "zone_2": ("climate.up_hallway_zone_2", "sensor.span_panel_ac_2_power"),
    "zone_3": ("climate.back_hallway_zone_3", "sensor.span_panel_ac_3_power"),
}
COOL_MODES = {"cool", "heat_cool", "auto"}
BAD = {"unavailable", "unknown", None, ""}
c = sqlite3.connect(REC, uri=True)
print("opened:", REC)

def series(eid, attrs=False):
    mid = c.execute("SELECT metadata_id FROM states_meta WHERE entity_id=?", (eid,)).fetchone()[0]
    if attrs:
        q = ("SELECT s.last_updated_ts, s.state, sa.shared_attrs FROM states s LEFT JOIN state_attributes sa "
             "ON s.attributes_id=sa.attributes_id WHERE s.metadata_id=? ORDER BY s.last_updated_ts")
        out = []
        for ts, stt, a in c.execute(q, (mid,)):
            act = None
            if a:
                try: act = json.loads(a).get("hvac_action")
                except Exception: pass
            out.append((ts, stt, act))
        return out
    return [(ts, s) for ts, s in c.execute(
        "SELECT last_updated_ts, state FROM states WHERE metadata_id=? ORDER BY last_updated_ts", (mid,))]

def kw(s):
    try: return float(s) / 1000.0
    except (TypeError, ValueError): return None

for zid, (clim, spn) in FIX.items():
    cs = series(clim, attrs=True); ss = series(spn)
    t0 = max(cs[0][0], ss[0][0]); t1 = min(cs[-1][0], ss[-1][0])
    print(f"\n==== {zid} {clim} / {spn}")
    print(f"window {datetime.fromtimestamp(t0,TZ)} .. {datetime.fromtimestamp(t1,TZ)} ({(t1-t0)/86400:.2f} d); climate rows={len(cs)} span rows={len(ss)}")
    # merged timeline
    ev = [(ts, 0, (st_, a)) for ts, st_, a in cs] + [(ts, 1, kw(s)) for ts, s in ss]
    ev.sort(key=lambda x: (x[0], x[1]))
    cur_c = (None, None); cur_k = None
    tot = blind = phantom = coolmode = span_on = act_cool = unk = 0.0
    prev_t = None
    for ts, kind, val in ev:
        if prev_t is not None and ts > t0 and prev_t < t1:
            a0 = max(prev_t, t0); a1 = min(ts, t1); dt = a1 - a0
            mode, act = cur_c
            if dt > 0:
                if mode in BAD or cur_k is None:
                    unk += dt
                elif mode in COOL_MODES:
                    coolmode += dt
                    on = cur_k >= ON_KW
                    span_on += dt if on else 0
                    act_cool += dt if act == "cooling" else 0
                    if on and act != "cooling": blind += dt
                    if (not on) and act == "cooling": phantom += dt
        if kind == 0: cur_c = val
        else: cur_k = val
        prev_t = ts
    print(f"cool-mode min={coolmode/60:.0f} | SPAN-on min={span_on/60:.0f} | action=cooling min={act_cool/60:.0f} | unknown/unavail min={unk/60:.0f}")
    print(f"BLIND   (SPAN>=0.5 & action!=cooling) = {blind/60:.0f} min = {100*blind/max(span_on,1):.1f}% of SPAN-on")
    print(f"PHANTOM (SPAN<0.5 & action==cooling)  = {phantom/60:.0f} min = {100*phantom/max(act_cool,1):.1f}% of action=cooling")

    # short cycles from hvac_action, replicating the producer
    on_since = None; a_cycles = []; prev = None
    for ts, stt, act in cs:
        if prev is None:
            prev = (stt, act); continue
        pst, pact = prev
        prev = (stt, act)
        if stt in BAD or pst in BAD or act is None:
            on_since = None; continue
        if (pact or "") == (act or ""):
            continue
        if (pact not in ("cooling", "heating")) and act in ("cooling", "heating"):
            on_since = ts
        elif pact in ("cooling", "heating") and act not in ("cooling", "heating"):
            if on_since is not None:
                a_cycles.append((on_since, ts)); on_since = None
    # SPAN on-cycles
    s_cycles = []; on = None; vals = []
    for ts, s in ss:
        k = kw(s)
        if k is None:
            on = None; vals = []; continue
        if k >= ON_KW and on is None:
            on = ts; vals = [k]
        elif k >= ON_KW:
            vals.append(k)
        elif on is not None:
            s_cycles.append((on, ts, vals)); on = None; vals = []
    a_sc = [x for x in a_cycles if x[1] - x[0] < SC_S]
    s_sc = [x for x in s_cycles if x[1] - x[0] < SC_S]
    flap = [x for x in s_cycles if x[1] - x[0] < 60]
    # off-gaps < 60 s between consecutive SPAN on-cycles (dropouts that split one run)
    gaps = [s_cycles[i + 1][0] - s_cycles[i][1] for i in range(len(s_cycles) - 1)]
    short_gaps = [g for g in gaps if g < 60]
    corro = 0
    for a0, a1 in a_sc:
        if any(b0 < a1 + 60 and b1 > a0 - 60 for b0, b1, _ in s_sc):
            corro += 1
    print(f"hvac_action cycles={len(a_cycles)} short(<600s)={len(a_sc)} | SPAN on-cycles={len(s_cycles)} short(<600s)={len(s_sc)}")
    print(f"corroboration: {corro}/{len(a_sc)} = {100*corro/max(len(a_sc),1):.0f}% of action short cycles overlap a SPAN short on-cycle (±60 s)")
    if len(a_sc) or len(s_sc):
        base = max(len(a_sc), len(s_sc))
        print(f"count difference: |{len(a_sc)}-{len(s_sc)}|/{base} = {100*abs(len(a_sc)-len(s_sc))/base:.0f}%")
    print(f"SPAN flap: on-cycles <60 s = {len(flap)} = {100*len(flap)/max(len(s_cycles),1):.1f}% of on-cycles; off-gaps <60 s = {len(short_gaps)}")
    gen = [x for x in s_cycles if x[1] - x[0] >= SC_S and len(x[2]) >= 3]
    if gen:
        mins = [min(v[1:-1] or v) for _, _, v in gen]  # drop edge samples
        meds = [st.median(v) for _, _, v in gen]
        print(f"genuine on-cycles={len(gen)}: interior min kW p5={sorted(mins)[len(mins)//20]:.2f} min={min(mins):.2f}; per-cycle median kW min={min(meds):.2f} median={st.median(meds):.2f}")
    allk = [kw(s) for _, s in ss if kw(s) is not None]
    band = [k for k in allk if 0.05 <= k < ON_KW]
    print(f"SPAN samples in 0.05-0.5 kW band: {len(band)}/{len(allk)} = {100*len(band)/max(len(allk),1):.2f}% (max in band {max(band) if band else 0:.2f})")
    print("action short cycles (local start, dur s):", [(datetime.fromtimestamp(a, TZ).strftime('%m-%d %H:%M'), round(b - a)) for a, b in a_sc][:20])

    # Informational for a re-plan: time-weighted SPAN kW histogram while action==cooling (cool mode),
    # and flap/short-cycle counts at alternative thresholds.
    edges = [0, 0.05, 0.2, 0.3, 0.4, 0.5, 0.7, 1.0, 99]
    hist = [0.0] * (len(edges) - 1)
    cur_c = (None, None); cur_k = None; prev_t = None
    for ts, kind, val in ev:
        if prev_t is not None and cur_k is not None and cur_c[0] in COOL_MODES and cur_c[1] == "cooling":
            dt = min(ts, t1) - max(prev_t, t0)
            if dt > 0:
                for i in range(len(hist)):
                    if edges[i] <= cur_k < edges[i + 1]:
                        hist[i] += dt; break
        if kind == 0: cur_c = val
        else: cur_k = val
        prev_t = ts
    tot_h = sum(hist) or 1
    print("SPAN kW while action==cooling (time share):",
          ", ".join(f"[{edges[i]}-{edges[i+1]}) {100*hist[i]/tot_h:.1f}%" for i in range(len(hist))))
    for thr in (0.1, 0.2, 0.3, 0.5):
        cyc = []; on = None
        for ts, s in ss:
            k = kw(s)
            if k is None:
                on = None; continue
            if k >= thr and on is None: on = ts
            elif k < thr and on is not None: cyc.append(ts - on); on = None
        print(f"  thr {thr} kW: on-cycles={len(cyc)} <60s={sum(1 for d in cyc if d < 60)} ({100*sum(1 for d in cyc if d < 60)/max(len(cyc),1):.1f}%) <600s={sum(1 for d in cyc if d < SC_S)}")

    # ---- REV 2: ODU stage vs SPAN agreement (L6) and SPAN unavailable mid on-cycle (M4) ----
    odu = [(ts, st_) for ts, st_ in series(ODU[zid])]
    ev2 = [(ts, 0, st_) for ts, st_ in odu] + [(ts, 1, kw(s_)) for ts, s_ in ss] + [(ts, 2, (st_, a)) for ts, st_, a in cs]
    ev2.sort(key=lambda x: (x[0], x[1]))
    o = None; k = None; cc = (None, None); pt = None
    agree = {0.5: [0.0, 0.0], 0.2: [0.0, 0.0]}; ostates = collections.Counter()
    for ts, kind, v in ev2:
        if pt is not None and o not in BAD and k is not None and cc[0] in COOL_MODES:
            dt = min(ts, t1) - max(pt, t0)
            if dt > 0:
                ostates[o] += dt
                orun = o.lower().startswith("stage") or o.lower() in ("on", "high", "low")
                for thr in agree:
                    agree[thr][1] += dt
                    if orun == (k >= thr): agree[thr][0] += dt
        if kind == 0: o = v
        elif kind == 1: k = v
        else: cc = v
        pt = ts
    print("ODU status time share (cool mode):", {kk: f"{100*vv/max(sum(ostates.values()),1):.1f}%" for kk, vv in ostates.most_common(8)})
    for thr, (a_, n_) in agree.items():
        print(f"ODU running (Stage N) vs SPAN >= {thr} kW agreement: {100*a_/max(n_,1):.1f}% of cool-mode time")
    mid_unavail = 0; on = False
    for ts, s_ in ss:
        kv = kw(s_)
        if kv is None:
            if on: mid_unavail += 1
            on = False; continue
        on = kv >= ON_KW
    print(f"SPAN unavailable/unknown episodes occurring mid on-cycle (0.5 kW): {mid_unavail}; total SPAN non-numeric rows: {sum(1 for _, s_ in ss if kw(s_) is None)}")

# ---- SPAN non-numeric episodes: durations and relation to HA restarts (context for M4) ----
starts = [ts for (ts,) in c.execute(
    "SELECT e.time_fired_ts FROM events e JOIN event_types t ON e.event_type_id=t.event_type_id "
    "WHERE t.event_type IN ('homeassistant_start','homeassistant_stop')")]
print("\n==== SPAN unavailable/unknown episodes (all 3 circuits)")
for zid, (clim, spn) in FIX.items():
    ss = series(spn); eps = []; st0 = None; stv = None
    for ts, s_ in ss:
        bad = kw(s_) is None
        if bad and st0 is None: st0 = ts; stv = s_
        elif not bad and st0 is not None: eps.append((st0, ts - st0, stv)); st0 = None
    near = sum(1 for t, d, v in eps if any(abs(t - x) < 900 for x in starts))
    durs = sorted(d for _, d, _ in eps)
    print(f"{spn}: episodes={len(eps)} states={dict(collections.Counter(v for _, _, v in eps))} "
          f"within 15 min of an HA start/stop={near} | duration p50={durs[len(durs)//2] if durs else 0:.0f}s p90={durs[int(len(durs)*0.9)] if durs else 0:.0f}s max={durs[-1] if durs else 0:.0f}s")
