"""HVAC-GATE8-OVERSHOOT-STAMP-NOT-CLEARED-1 — outcomes of stamp-carried nudge dispatches.

Card: `last_overshoot_started` (Gate 8) is cleared on Gate 4 / Gate 6 fails and at dispatch
(hvac_override.py:4136, :4192, :4952) but NOT on a Gate 7 fail (:4219-4225). M0-P4
(scripts/probes/hvac_w3_m0_p4_gate4_replay.py) found that clearing it on a Gate-7 fail would remove
3/9/1 = 13 of today's replayed dispatches (OLD vs OLDc). Question: are stamp-carried dispatches
worse (less effective, less kWh avoided, more escalation to hard reset, more discomfort) than
fresh-stamp ones?

Method (reuses the P4 replay verbatim for the OLD / OLDc models, today's predicate only):
  A. Replay-level: list the OLD-only dispatches (OLD minus OLDc = the "13"), match each to a real
     detection_fired row (+-150 s), and report its real outcome.
  B. Real-row level (larger n): for EVERY real detection_fired row in the window, the stamp age is
     in its notes (`overshoot_min`). Label it CARRIED if any replayed tick inside
     (dispatch - overshoot_min, dispatch) was a Gate-7 fail under today's predicate (g4 pass,
     cur<=th, kW known and <= zone threshold) — i.e. a tick where the proposed fix would have
     cleared the stamp. Else FRESH.
Outcome per dispatch: next nudge_evaluated for the zone within 60 min (classification, effective,
kwh_avoided, kwh_rate_before/after), whether a hard_reset_started followed within 15 min
(escalation), and comfort = climate current_temperature minus the pre-dispatch target_high over the
30 min after dispatch (max excess, minutes above target+1 F).
READ-ONLY: both DBs mode=ro, SELECT only, stdout only.
Run: ssh ha "python3 -" < scripts/probes/hvac_gate8_stamp_outcomes.py
"""
import sqlite3, json, bisect, statistics as st, collections
from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Chicago")
REC = "file:/config/home-assistant_v2.db?mode=ro"
URA = "file:/config/universal_room_automation/data/universal_room_automation.db?mode=ro"
c = sqlite3.connect(REC, uri=True); u = sqlite3.connect(URA, uri=True)
print("opened:", REC, "|", URA)
SPAN_STALE_S = 600
TICK = 300
BAD = {"unavailable", "unknown", "", None}
COOL = ("cool", "heat_cool", "auto")
FIX = {"zone_1": ("climate.thermostat_bryant_wifi_studyb_zone_1", "sensor.span_panel_ac1_power", "sensor.office_b_odu_status",
                  "number.ura_hvac_coordinator_ac_kwh_rate_threshold_entertainment_master_suite"),
       "zone_2": ("climate.up_hallway_zone_2", "sensor.span_panel_ac_2_power", "sensor.thermostat_bryant_wifi_upstairs_odu_status",
                  "number.ura_hvac_coordinator_ac_kwh_rate_threshold_upstairs_2"),
       "zone_3": ("climate.back_hallway_zone_3", "sensor.span_panel_ac_3_power", "sensor.thermostat_bryant_wifi_backhallway_odu_status",
                  "number.ura_hvac_coordinator_ac_kwh_rate_threshold_back_hallway_2")}
fmt = lambda t: datetime.fromtimestamp(t, TZ).strftime("%m-%d %H:%M")

def raw(eid):
    q = ("SELECT s.last_updated_ts, s.state, sa.shared_attrs FROM states s JOIN states_meta m ON s.metadata_id=m.metadata_id "
         "LEFT JOIN state_attributes sa ON s.attributes_id=sa.attributes_id WHERE m.entity_id=? ORDER BY 1")
    return list(c.execute(q, (eid,)))

def live_value(eid):
    vals = [s for _, s, _ in raw(eid) if s not in BAD]
    return vals[-1], sorted(set(vals))

N_SAMPLES = int(float(live_value("number.ura_hvac_coordinator_ac_sustained_samples")[0]))
DETECT_MIN = float(live_value("number.ura_hvac_coordinator_ac_detection_time_gate")[0])
THRESH = {z: float(live_value(f[3])[0]) for z, f in FIX.items()}
print(f"knobs: samples={N_SAMPLES} detect_min={DETECT_MIN} thresholds={THRESH}")

starts = [t for (t,) in c.execute(
    "SELECT e.time_fired_ts FROM events e JOIN event_types t ON e.event_type_id=t.event_type_id "
    "WHERE t.event_type='homeassistant_start' ORDER BY 1")]

# ---- real arrester rows ----
rows = collections.defaultdict(list)
for z, ts, et, notes, kb, ka, eff, th in u.execute(
        "SELECT zone_id, timestamp, event_type, notes, kwh_rate_before, kwh_rate_after, effective, target_high "
        "FROM ac_ramp_events WHERE timestamp >= '2026-09-21' ORDER BY timestamp"):
    rows[(z, et)].append((datetime.fromisoformat(ts).timestamp(), notes or "", kb, ka, eff, th))
ev = {k: [r[0] for r in v] for k, v in rows.items()}
det_all = sorted(t for (z, et), l in ev.items() if et == "detection_fired" for t in l)
lat = []
for z in FIX:
    for d in ev.get((z, "detection_fired"), []):
        nx = [e for e in ev.get((z, "nudge_evaluated"), []) if 0 < e - d < 3600]
        if nx: lat.append(min(nx) - d)
INFLIGHT_MED = st.median(lat) if lat else 366

# ---- tick grid (identical to P4) ----
rec_lo = raw(FIX["zone_1"][2])[0][0]; rec_hi = raw(FIX["zone_1"][2])[-1][0]
seg_bounds = [rec_lo] + [s for s in starts if s > rec_lo] + [rec_hi]
ticks = []
for a, b in zip(seg_bounds, seg_bounds[1:]):
    anchors = [d for d in det_all if a + 60 <= d < b]
    if anchors:
        anc = anchors[0]; k0 = -int((anc - (a + 60)) // TICK); t = anc + k0 * TICK
    else:
        t = a + TICK
    while t < b:
        if t >= a + 60: ticks.append(t)
        t += TICK
print(f"ticks={len(ticks)} {fmt(ticks[0])} .. {fmt(ticks[-1])}; recorder window starts {fmt(rec_lo)}")

def asof_factory(rows_):
    ts = [r[0] for r in rows_]
    def f(t):
        i = bisect.bisect_right(ts, t) - 1
        return rows_[i] if i >= 0 else None
    return f

def parse_notes(n):
    d = {}
    for kv in n.split(";"):
        if "=" in kv:
            k, v = kv.split("=", 1); d[k] = v
    return d

def outcome(z, d):
    """Real outcome for a real detection at epoch d."""
    evs = [r for r in rows.get((z, "nudge_evaluated"), []) if 0 < r[0] - d < 3600]
    if not evs: return None
    e = min(evs, key=lambda r: r[0]); n = parse_notes(e[1])
    hr = [r for r in rows.get((z, "hard_reset_started"), []) if 0 <= r[0] - e[0] < 900]
    return dict(cls=n.get("classification"), eff=e[4], avoided=float(n.get("kwh_avoided", "nan")),
                kb=e[2], ka=e[3], post_mean=n.get("post_mean"), reset=bool(hr))

ALL = []  # per real detection records
REPLAY13 = []
for z, (clim, span, odu, _) in FIX.items():
    cl = []
    for ts, s, a in raw(clim):
        try: a = json.loads(a) if a else {}
        except Exception: a = {}
        cl.append((ts, s, (a.get("hvac_action"), a.get("current_temperature"), a.get("target_temp_high"))))
    CL = asof_factory(cl); SP = asof_factory(raw(span))
    real_det = ev.get((z, "detection_fired"), []); real_eval = ev.get((z, "nudge_evaluated"), [])

    def span_kw(t):
        r = SP(t)
        if r is None or t - r[0] > SPAN_STALE_S or r[1] in BAD: return None
        try: return float(r[1]) / 1000.0
        except (TypeError, ValueError): return None

    inputs = []
    for t in ticks:
        r = CL(t); mode = r[1] if r else None
        act, cur, th = r[2] if r else (None, None, None)
        kw = span_kw(t)
        g_old = mode in COOL and kw is not None and kw >= 0.5
        inputs.append((t, g_old, cur, th, kw))

    def g7fail(tup):
        t, g4, cur, th, kw = tup
        return bool(g4 and th is not None and cur is not None and cur <= th and kw is not None and kw <= THRESH[z])

    def run(clear_g7, clear_on_dispatch=True):
        stamp = None; samples = 0; inflight_until = 0; disp = {}; g7_during = 0
        for tup in inputs:
            t, g4, cur, th, kw = tup
            if not g4: stamp = None; samples = 0; g7_during = 0; continue
            if th is None or cur is None: continue
            if not (cur <= th): stamp = None; samples = 0; g7_during = 0; continue
            if kw is None: continue
            if kw > THRESH[z]: samples += 1
            else:
                samples = 0
                if stamp is not None: g7_during += 1
                if clear_g7: stamp = None; g7_during = 0
                continue
            if samples < N_SAMPLES: continue
            if stamp is None: stamp = t; g7_during = 0; continue
            if (t - stamp) / 60 < DETECT_MIN: continue
            if t < inflight_until: continue
            disp[t] = (t - stamp, g7_during)
            m = [d for d in real_det if abs(d - t) <= 150]
            if m:
                nx = [e for e in real_eval if 0 < e - m[0] < 3600]
                inflight_until = (min(nx) if nx else t + INFLIGHT_MED)
            else:
                inflight_until = t + INFLIGHT_MED
            if clear_on_dispatch: stamp = None; samples = 0; g7_during = 0  # dispatch clears (:4952)
        return disp

    old = run(False); oldc = run(True)
    p4o = run(False, False); p4c = run(True, False)
    print(f"  [P4-faithful, no clear on dispatch] OLD={len(p4o)} OLDc={len(p4c)} OLD-only={len(set(p4o)-set(p4c))} {[fmt(x) for x in sorted(set(p4o)-set(p4c))]}")
    only_old = sorted(set(old) - set(oldc)); only_oldc = sorted(set(oldc) - set(old))
    print(f"\n==== {z} thr={THRESH[z]}  OLD={len(old)} OLDc={len(oldc)}  OLD-only={len(only_old)} OLDc-only={len(only_oldc)}")
    for t in only_old:
        age, g7n = old[t]
        m = [d for d in real_det if abs(d - t) <= 150]
        oc = outcome(z, m[0]) if m else None
        later = [x for x in only_oldc if t < x <= t + 3600]
        print(f"  OLD-only {fmt(t)} stamp_age={age/60:.0f}m g7_fails_in_stamp={g7n} real_match={'Y' if m else 'N'} "
              f"OLDc_later={[fmt(x) for x in later]} outcome={oc}")
        REPLAY13.append((z, t, m[0] if m else None, oc))

    # ---- B: every real detection, labelled by the replayed ticks inside its real stamp window ----
    tick_ts = [x[0] for x in inputs]
    for d, notes, kb, ka, eff, th in rows.get((z, "detection_fired"), []):
        if d < rec_lo: continue
        om = float(parse_notes(notes).get("overshoot_min", "nan"))
        lo = d - om * 60
        i0 = bisect.bisect_right(tick_ts, lo); i1 = bisect.bisect_left(tick_ts, d - 60)
        g7n = sum(1 for tup in inputs[i0:i1] if g7fail(tup))
        # comfort: temp minus pre-dispatch target_high over 30 min after
        base_th = th
        seg = [(ts, a[1]) for ts, s, a in cl if d <= ts <= d + 1800 and a[1] is not None]
        pre = CL(d); cur0 = pre[2][1] if pre else None
        if seg or cur0 is not None:
            pts = ([(d, cur0)] if cur0 is not None else []) + seg
            excess = max(p[1] - base_th for p in pts) if base_th is not None else None
            # minutes above base+1 (step function)
            mins = 0.0
            for (t1, v1), (t2, _) in zip(pts, pts[1:] + [(d + 1800, None)]):
                if base_th is not None and v1 > base_th + 1: mins += (t2 - t1) / 60
        else:
            excess = None; mins = None
        ALL.append(dict(z=z, t=d, om=om, g7=g7n, carried=g7n > 0, oc=outcome(z, d), excess=excess, mins_hot=mins))

# ---- summaries ----
def summ(label, recs):
    ocs = [r["oc"] for r in recs if r["oc"]]
    n = len(ocs)
    effn = sum(1 for o in ocs if o["eff"] == 1)
    incon = sum(1 for o in ocs if o["eff"] is None)
    av = [o["avoided"] for o in ocs if o["avoided"] == o["avoided"]]
    kbs = [o["kb"] for o in ocs if o["kb"] is not None]
    rs = sum(1 for o in ocs if o["reset"])
    ex = [r["excess"] for r in recs if r["excess"] is not None]
    mh = [r["mins_hot"] for r in recs if r["mins_hot"] is not None]
    oms = [r["om"] for r in recs]
    print(f"{label:28s} n_det={len(recs):3d} n_eval={n:3d} effective={effn}/{n - incon} "
          f"({100*effn/max(1,n-incon):.0f}%) inconclusive={incon} reset_after={rs} "
          f"kwh_avoided mean={st.mean(av) if av else float('nan'):.3f} med={st.median(av) if av else float('nan'):.3f} "
          f"kW_before med={st.median(kbs) if kbs else float('nan'):.2f} stamp_age med={st.median(oms) if oms else float('nan'):.1f}m "
          f"max_excess_F med={st.median(ex) if ex else float('nan'):.1f} max={max(ex) if ex else float('nan'):.1f} "
          f"mins>th+1 total={sum(mh):.0f} n_hot={sum(1 for m in mh if m > 0)}")
    return effn, n - incon

print("\n==== B: all real detections in recorder window, labelled by replayed Gate-7 fails inside real stamp window")
for z in FIX:
    zr = [r for r in ALL if r["z"] == z]
    summ(f"{z} CARRIED", [r for r in zr if r["carried"]]); summ(f"{z} FRESH", [r for r in zr if not r["carried"]])
cE, cN = summ("ALL CARRIED", [r for r in ALL if r["carried"]])
fE, fN = summ("ALL FRESH", [r for r in ALL if not r["carried"]])
summ("ALL stamp_age>12m", [r for r in ALL if r["om"] > 12]); summ("ALL stamp_age<=12m", [r for r in ALL if r["om"] <= 12])

# Fisher exact (two-sided) on effective vs not
from math import comb
def fisher(a, b, c_, d):
    n = a + b + c_ + d; r1 = a + b; c1 = a + c_
    p0 = comb(r1, a) * comb(n - r1, c1 - a) / comb(n, c1)
    p = 0.0
    for x in range(max(0, c1 - (n - r1)), min(r1, c1) + 1):
        px = comb(r1, x) * comb(n - r1, c1 - x) / comb(n, c1)
        if px <= p0 + 1e-12: p += px
    return p
print(f"\nFisher two-sided effective CARRIED {cE}/{cN} vs FRESH {fE}/{fN}: p={fisher(cE, cN-cE, fE, fN-fE):.3f}")

print("\n==== per-dispatch CARRIED list")
for r in sorted([r for r in ALL if r["carried"]], key=lambda r: r["t"]):
    o = r["oc"] or {}
    print(f"  {r['z']} {fmt(r['t'])} stamp_age={r['om']:.1f}m g7_fails={r['g7']} cls={o.get('cls')} avoided={o.get('avoided')} "
          f"kW {o.get('kb')}->{o.get('ka')} reset={o.get('reset')} excess={r['excess']} mins_hot={r['mins_hot']}")

print("\n==== A: the replay OLD-only ('13') matched to real outcomes")
m = [x for x in REPLAY13 if x[2] is not None]
print(f"  total={len(REPLAY13)} matched_to_real={len(m)}")
for z, t, d, oc in REPLAY13:
    rr = [r for r in ALL if d is not None and r['t'] == d]
    print(f"  {z} {fmt(t)} real={'-' if d is None else fmt(d)} cls={oc and oc['cls']} avoided={oc and oc['avoided']} "
          f"reset={oc and oc['reset']} stamp_age_real={rr[0]['om'] if rr else None} excess={rr[0]['excess'] if rr else None}")
