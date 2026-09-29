"""HVAC W3 M0-P4 — Gate 4 flip replay (today's SPAN-0.5 predicate vs the ODU-stage predicate).

Question: reconstruct every 5-min arrester tick per zone (cool-capable mode, ramp_zone_enabled, ramp
master ON), compute today's Gate-4 verdict (live mode: mode guard + fresh SPAN >= 0.5 kW, fail-closed)
vs the new stage verdict (RUNNING -> True, OFF -> False, UNKNOWN -> today's SPAN step). For every flip,
replay Gates 6-8 (hvac_override.py:4135-4258) with the LIVE per-zone Gate-7 threshold and the live
sustained-samples / detection-time knobs, and report whether the flip changes
  (a) any dispatch (_handle_overshoot_detected),
  (b) Gate-8 `last_overshoot_started` retention (a Gate-7 fail keeps the stamp; only Gates 4/6 clear
      it) -> an EARLIER dispatch,
  (c) ramp_state only.
GO for the Gate-4 wiring iff (a) = 0 and (b) produces 0 earlier dispatches in 7 d.

Models (same tick grid, same inputs):
  OLD   = today's predicate, today's stamp rule           (validated against real detection_fired rows)
  NEW   = stage predicate,   today's stamp rule            (what the plan ships)
  NEWc  = stage predicate,   stamp also cleared on Gate-7 fail (isolates (b): NEW vs NEWc)
  OLDc  = today's predicate, stamp also cleared on Gate-7 fail (latent pre-existing effect, info)
Not modelled (identical for all models): Gate 5 lockout / 5b daily cap, egress pause, override-active,
corrective-write suppression, S1 same-tick skip. Gate 9 in-flight = dispatch -> real nudge_evaluated
when the dispatch matches a real detection_fired row, else dispatch + median(real evaluated - detection).
Tick grid: 300 s, phase-anchored per HA-up segment on real detection_fired timestamps (a tick's `now`).
Constants: ODU_STAGE_STALE_S = 900 (M0-P2). SPAN staleness 600 s (AC_KWH_SENSOR_STALENESS_S).
READ-ONLY: both DBs mode=ro, SELECT only, stdout only.
Run: ssh ha "python3 -" < scripts/probes/hvac_w3_m0_p4_gate4_replay.py
"""
import sqlite3, json, bisect, statistics as st, collections
from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Chicago")
REC = "file:/config/home-assistant_v2.db?mode=ro"
URA = "file:/config/universal_room_automation/data/universal_room_automation.db?mode=ro"
c = sqlite3.connect(REC, uri=True); u = sqlite3.connect(URA, uri=True)
print("opened:", REC, "|", URA)
STALE_S = 900
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

def raw(eid):
    q = ("SELECT s.last_updated_ts, s.state, sa.shared_attrs FROM states s JOIN states_meta m ON s.metadata_id=m.metadata_id "
         "LEFT JOIN state_attributes sa ON s.attributes_id=sa.attributes_id WHERE m.entity_id=? ORDER BY 1")
    return list(c.execute(q, (eid,)))

def live_value(eid):
    vals = [s for _, s, _ in raw(eid) if s not in BAD]
    return vals[-1], sorted(set(vals))

# ---- live knobs (and whether they changed in the window) ----
knobs = {}
for k, e in (("samples", "number.ura_hvac_coordinator_ac_sustained_samples"), ("detect_min", "number.ura_hvac_coordinator_ac_detection_time_gate"),
             ("gate4_mode", "select.ura_hvac_ac_gate4_predicate_mode"), ("nudge", "switch.ura_hvac_coordinator_26_ac_nudge"),
             ("master", "switch.ura_hvac_coordinator_ac_ramp_down_energy_aware")):
    v, allv = live_value(e); knobs[k] = v
    print(f"knob {k:10s} = {v}  (distinct non-unavailable values in window: {allv})")
N_SAMPLES = int(float(knobs["samples"])); DETECT_MIN = float(knobs["detect_min"])
THRESH = {}
for z, f in FIX.items():
    v, allv = live_value(f[3]); THRESH[z] = float(v)
    print(f"knob threshold {z} = {v} kW  (values in window: {allv})")
assert knobs["gate4_mode"] == "live" and knobs["nudge"] == "on" and knobs["master"] == "on"

starts = [t for (t,) in c.execute(
    "SELECT e.time_fired_ts FROM events e JOIN event_types t ON e.event_type_id=t.event_type_id "
    "WHERE t.event_type='homeassistant_start' ORDER BY 1")]

# ---- real arrester events ----
ev = collections.defaultdict(list)
for z, ts, et in u.execute("SELECT zone_id, timestamp, event_type FROM ac_ramp_events WHERE event_type IN "
                           "('detection_fired','nudge_evaluated') AND timestamp >= '2026-09-21' ORDER BY timestamp"):
    ev[(z, et)].append(datetime.fromisoformat(ts).timestamp())
det_all = sorted(t for (z, et), l in ev.items() if et == "detection_fired" for t in l)
lat = []
for z in FIX:
    for d in ev[(z, "detection_fired")]:
        nx = [e for e in ev[(z, "nudge_evaluated")] if 0 < e - d < 3600]
        if nx: lat.append(min(nx) - d)
INFLIGHT_MED = st.median(lat) if lat else 366
print(f"real detection_fired: { {z: len(ev[(z,'detection_fired')]) for z in FIX} }; detection->evaluated median {INFLIGHT_MED:.0f}s")

# ---- tick grid ----
rec_lo = min(r[0] for r in raw(FIX["zone_1"][2])[:1]); rec_hi = max(r[0] for r in raw(FIX["zone_1"][2])[-1:])
seg_bounds = [rec_lo] + [s for s in starts if s > rec_lo] + [rec_hi]
ticks = []; unanchored = 0
for a, b in zip(seg_bounds, seg_bounds[1:]):
    anchors = [d for d in det_all if a + 60 <= d < b]
    if anchors:
        anc = anchors[0]; k0 = -int((anc - (a + 60)) // TICK)
        t = anc + k0 * TICK
    else:
        t = a + TICK; unanchored += 1
    while t < b:
        if t >= a + 60: ticks.append(t)
        t += TICK
print(f"ticks={len(ticks)} over {len(seg_bounds)-1} HA-up segments ({unanchored} without a phase anchor); "
      f"{datetime.fromtimestamp(ticks[0], TZ):%m-%d %H:%M} .. {datetime.fromtimestamp(ticks[-1], TZ):%m-%d %H:%M}")

def asof_factory(rows):
    ts = [r[0] for r in rows]
    def f(t):
        i = bisect.bisect_right(ts, t) - 1
        return rows[i] if i >= 0 else None
    return f

def cstate(row, t):
    if row is None: return "UNKNOWN"
    ts, s, _ = row
    if s in BAD or t - ts > STALE_S: return "UNKNOWN"
    if s == "off": return "OFF"
    if s.startswith("Stage") or s in ("on", "dehumidify"): return "RUNNING"
    return "UNKNOWN"

summary = {}
for z, (clim, span, odu, _) in FIX.items():
    cl = []
    for ts, s, a in raw(clim):
        try: a = json.loads(a) if a else {}
        except Exception: a = {}
        cl.append((ts, s, (a.get("hvac_action"), a.get("current_temperature"), a.get("target_temp_high"))))
    CL = asof_factory(cl); SP = asof_factory(raw(span)); OD = asof_factory(raw(odu))
    real_det = ev[(z, "detection_fired")]; real_eval = ev[(z, "nudge_evaluated")]

    def span_kw(t):
        r = SP(t)
        if r is None or t - r[0] > SPAN_STALE_S or r[1] in BAD: return None
        try: return float(r[1]) / 1000.0
        except (TypeError, ValueError): return None

    inputs = []
    flips = collections.Counter(); srcs = collections.Counter()
    for t in ticks:
        r = CL(t)
        mode = r[1] if r else None
        act, cur, th = r[2] if r else (None, None, None)
        kw = span_kw(t)
        guard = mode in COOL
        g_old = guard and kw is not None and kw >= 0.5
        cs = cstate(OD(t), t)
        if not guard: g_new = False; src = "guard"
        elif cs == "RUNNING": g_new = True; src = "odu"
        elif cs == "OFF": g_new = False; src = "odu"
        else: g_new = g_old; src = "span_fallback"
        if guard: srcs[src] += 1
        if g_old != g_new:
            band = "None" if kw is None else ("<0.05" if kw < 0.05 else "0.05-0.3" if kw < 0.3 else "0.3-0.5" if kw < 0.5 else ">=0.5")
            flips[f"kW {band}"] += 1
            flips["new_True_old_False (ODU running, SPAN<0.5 or stale)" if g_new else "new_False_old_True (ODU off, SPAN>=0.5)"] += 1
        inputs.append((t, g_old, g_new, cur, th, kw, cs))

    def run(use_new, clear_g7):
        stamp = None; samples = 0; inflight_until = 0; disp = []; states = []
        for t, g_old, g_new, cur, th, kw, cs in inputs:
            g4 = g_new if use_new else g_old
            if not g4:
                stamp = None; samples = 0; states.append("idle"); continue
            if th is None or cur is None:
                states.append("-"); continue
            if not (cur <= th):
                stamp = None; samples = 0; states.append("idle"); continue
            if kw is None:
                states.append("-"); continue
            if kw > THRESH[z]:
                samples += 1
            else:
                samples = 0
                if clear_g7: stamp = None
                states.append("idle"); continue
            if samples < N_SAMPLES:
                states.append("detecting"); continue
            if stamp is None:
                stamp = t; states.append("detecting"); continue
            if (t - stamp) / 60 < DETECT_MIN:
                states.append("detecting"); continue
            if t < inflight_until:
                states.append("inflight"); continue
            disp.append((t, t - stamp))
            m = [d for d in real_det if abs(d - t) <= 150]
            if m:
                nx = [e for e in real_eval if 0 < e - m[0] < 3600]
                inflight_until = (min(nx) if nx else t + INFLIGHT_MED)
            else:
                inflight_until = t + INFLIGHT_MED
            states.append("dispatch")
        return disp, states

    old, s_old = run(False, False); new, s_new = run(True, False)
    newc, _ = run(True, True); oldc, _ = run(False, True)
    # validation of OLD vs reality
    hit = sum(1 for t, _ in old if any(abs(d - t) <= 150 for d in real_det))
    rec = sum(1 for d in real_det if any(abs(d - t) <= 150 for t, _ in old))
    set_old = {t for t, _ in old}; set_new = {t for t, _ in new}; set_newc = {t for t, _ in newc}; set_oldc = {t for t, _ in oldc}
    only_new = sorted(set_new - set_old); only_old = sorted(set_old - set_new)
    b_diff = sorted(set_new - set_newc); b_diff2 = sorted(set_newc - set_new)
    ramp_only = sum(1 for a, b in zip(s_old, s_new) if a != b and "dispatch" not in (a, b))
    print(f"\n==== {z}  threshold={THRESH[z]} kW samples={N_SAMPLES} detect={DETECT_MIN:.0f} min")
    print(f"  Gate-4 source share on guard-pass ticks: {dict(srcs)}")
    print(f"  Gate-4 flips: {dict(flips)}")
    print(f"  OLD replay dispatches={len(old)} vs real detection_fired={len(real_det)}: precision {hit}/{len(old)}, recall {rec}/{len(real_det)}")
    print(f"  NEW dispatches={len(new)} | (a) only-in-NEW={len(only_new)} only-in-OLD={len(only_old)}")
    for t in only_new[:10]:
        i = ticks.index(t); print(f"     +NEW {datetime.fromtimestamp(t, TZ):%m-%d %H:%M} stamp_age={dict(new)[t]/60:.0f}m inputs={inputs[i][1:]}")
    for t in only_old[:10]:
        i = ticks.index(t); print(f"     -OLD {datetime.fromtimestamp(t, TZ):%m-%d %H:%M} inputs={inputs[i][1:]}")
    print(f"  (b) NEW vs NEWc (stamp kept on Gate-7 fail): extra/earlier in NEW={len(b_diff)} {[datetime.fromtimestamp(t, TZ).strftime('%m-%d %H:%M') for t in b_diff][:10]}; only in NEWc={len(b_diff2)}")
    early = 0
    for t in only_new:
        later_old = [x for x in set_old if t < x <= t + 3600]
        if later_old: early += 1
    print(f"  NEW dispatches that pre-empt an OLD dispatch within 60 min (earlier dispatch): {early}")
    print(f"  latent (today): OLD vs OLDc dispatch diff = +{len(set_old - set_oldc)} / -{len(set_oldc - set_old)}")
    print(f"  (c) ramp_state-only differences (ticks): {ramp_only}")
    # attribution trace for every differing dispatch: ticks from 60 min before to the dispatch
    for t in sorted(set(only_new) | set(only_old)):
        i = ticks.index(t)
        print(f"   TRACE around {'+NEW' if t in set_new else '-OLD'} {datetime.fromtimestamp(t, TZ):%m-%d %H:%M} "
              f"(tick | g4_old g4_new odu kW cur/th | ramp old/new)")
        for j in range(max(0, i - 12), min(len(inputs), i + 4)):
            tt, go, gn, cur, th, kw, cs = inputs[j]
            mark = " <-- flip" if go != gn else ""
            print(f"     {datetime.fromtimestamp(tt, TZ):%H:%M} | {int(go)} {int(gn)} {cs:7s} {kw if kw is None else round(kw,2)} {cur}/{th} | {s_old[j]}/{s_new[j]}{mark}")
    summary[z] = (len(only_new), len(only_old), len(b_diff), early)
print("\nSUMMARY per zone (only_new, only_old, b_stamp_effect, earlier):", summary)
