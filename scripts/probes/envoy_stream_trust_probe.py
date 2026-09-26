"""ENVOY-STREAM-TRUST-MEASURE-1 — read-only trust measurement of the Envoy MQTT stream.

Criteria: docs/planning/PLANNING_envoy_local_witness_and_solar_follow.md §3.1-3.7
(+ 3.8 partial-fleet, added after the 2026-09-25 Envoy reboot).

Run:  ssh ha "python3 - START_EPOCH END_EPOCH [EXCL_START-EXCL_END ...]" < scripts/probes/envoy_stream_trust_probe.py
All epochs are UTC seconds. Exclusion windows are removed from every criterion except 3.6
(3.6 is a per-day count and reports the contaminated day as-is, flagged).
"""
import sqlite3, statistics as st, sys, time
from datetime import datetime, timezone, timedelta

DB = "file:/config/home-assistant_v2.db?mode=ro"
r = sqlite3.connect(DB, uri=True)

args = sys.argv[1:]
START = float(args[0]) if args else time.time() - 86400
END = float(args[1]) if len(args) > 1 else time.time()
EXCL = []
for a in args[2:]:
    s, e = a.split("-")
    EXCL.append((float(s), float(e)))

CDT = timezone(timedelta(hours=-5))
BAD = ("unavailable", "unknown", None, "")

S_SOC = "sensor.envoy_stream_battery_soc"
S_SOCTOP = "sensor.envoy_stream_soc_top_level"
S_AGE = "sensor.envoy_stream_data_age"
S_TS = "sensor.envoy_stream_data_timestamp"
S_PV = "sensor.envoy_stream_solar_production"
S_LOAD = "sensor.envoy_stream_house_load"
S_BATT = "sensor.envoy_stream_battery_power"
S_GRID = "sensor.envoy_stream_grid_power"
S_RES = "sensor.envoy_stream_backup_reserve"
S_DEV = "sensor.envoy_stream_microinverters_running"
N_SOC = "sensor.envoy_482543015950_battery"
C_SOC = "sensor.iq_battery_hacs_battery_overall_charge"
C_RES = "number.iq_battery_hacs_battery_reserve"

# Physical slew ceiling: ~30.7 kW available power over ~38-40 kWh ~= 1.3 pp/min. 2 pp/min = clearly non-physical.
SLEW_PP_PER_MIN = 2.0


def fmt(t):
    return datetime.fromtimestamp(t, CDT).strftime("%m-%d %H:%M:%S")


def rows(ent, t0=None, t1=None):
    """(ts, state) rows, plus the last row before t0 as the carried-in state."""
    t0 = START if t0 is None else t0
    t1 = END if t1 is None else t1
    mid = r.execute("select metadata_id from states_meta where entity_id=?", (ent,)).fetchone()
    if not mid:
        return []
    mid = mid[0]
    prev = r.execute(
        "select last_updated_ts,state from states where metadata_id=? and last_updated_ts<? "
        "order by last_updated_ts desc limit 1", (mid, t0)).fetchone()
    out = [(t0, prev[1])] if prev else []
    out += r.execute(
        "select last_updated_ts,state from states where metadata_id=? and last_updated_ts>=? "
        "and last_updated_ts<? order by last_updated_ts", (mid, t0, t1)).fetchall()
    return out


def excluded(t):
    return any(a <= t < b for a, b in EXCL)


def intervals(ent):
    """[(t0,t1,state)] clipped to window, exclusion windows cut out."""
    rs = rows(ent)
    out = []
    for i, (t, s) in enumerate(rs):
        t_end = rs[i + 1][0] if i + 1 < len(rs) else END
        a, b = max(t, START), min(t_end, END)
        if b <= a:
            continue
        cuts = [(a, b)]
        for xa, xb in EXCL:
            nxt = []
            for ca, cb in cuts:
                if xb <= ca or xa >= cb:
                    nxt.append((ca, cb))
                else:
                    if ca < xa:
                        nxt.append((ca, xa))
                    if xb < cb:
                        nxt.append((xb, cb))
            cuts = nxt
        out += [(ca, cb, s) for ca, cb in cuts]
    return out


def row_at(rs, t):
    """carry-forward lookup on a sorted row list (binary search) -> (ts, state) or None."""
    lo, hi = 0, len(rs) - 1
    if not rs or rs[0][0] > t:
        return None
    while lo < hi:
        m = (lo + hi + 1) // 2
        if rs[m][0] <= t:
            lo = m
        else:
            hi = m - 1
    return rs[lo]


def value_at(rs, t):
    x = row_at(rs, t)
    return x[1] if x else None


def straddles(t1, t2):
    return any(t1 < b and t2 > a for a, b in EXCL)


def num(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def pct(xs, p):
    if not xs:
        return None
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(p / 100 * len(xs)))]


def sample_times(step=60):
    t = START
    while t < END:
        if not excluded(t):
            yield t
        t += step


print(f"WINDOW {fmt(START)} -> {fmt(END)} CDT  ({(END-START)/3600:.1f} h)")
for a, b in EXCL:
    print(f"  EXCLUDED {fmt(a)} -> {fmt(b)}  ({(b-a)/60:.0f} min)")
clean_s = (END - START) - sum(min(b, END) - max(a, START) for a, b in EXCL if b > START and a < END)
print(f"  clean seconds: {clean_s:.0f} ({clean_s/3600:.1f} h)\n")

# ---- 3.1 Freshness -------------------------------------------------------
print("== 3.1 FRESHNESS (data_age, seconds; includes the constant ~20 s Envoy clock skew)")
ages = [(a, b, num(s)) for a, b, s in intervals(S_AGE)]
w = [(b - a, v) for a, b, v in ages if v is not None]
if w:
    tot = sum(d for d, _ in w)
    vs = sorted(w, key=lambda x: x[1])
    acc, p50, p95 = 0, None, None
    for d, v in vs:
        acc += d
        if p50 is None and acc >= tot * 0.5:
            p50 = v
        if p95 is None and acc >= tot * 0.95:
            p95 = v
    mx = max(v for _, v in w)
    over60 = sum(d for d, v in w if v > 60)
    print(f"  time-weighted p50 {p50:.0f}  p95 {p95:.0f}  max {mx:.0f}  | seconds with age>60: {over60:.0f}")
    print(f"  PASS rule (p95<=10 s) is UNMEETABLE as written: skew floor ~20 s. Skew-adjusted p95 = {p95-20:.0f} s")
ts_rows = [(t, s) for t, s in rows(S_TS) if s not in BAD and not excluded(t)]
gaps = []
for (t1, s1), (t2, s2) in zip(ts_rows, ts_rows[1:]):
    if straddles(t1, t2):
        continue
    try:
        d = (datetime.fromisoformat(s2) - datetime.fromisoformat(s1)).total_seconds()
        if d > 0:
            gaps.append(d)
    except ValueError:
        pass
if gaps:
    print(f"  Envoy payload refresh cadence (distinct meters.last_update deltas): n={len(gaps)} "
          f"p50 {pct(gaps,50):.0f}s p95 {pct(gaps,95):.0f}s max {max(gaps):.0f}s")
unav = [(a, b) for a, b, s in intervals(S_SOC) if s in BAD]
print(f"  stream unavailable episodes: {len(unav)}, total {sum(b-a for a,b in unav):.0f}s, "
      f"longest {max([b-a for a,b in unav], default=0):.0f}s")
for a, b in unav:
    print(f"     {fmt(a)} -> {fmt(b)}  {b-a:.0f}s")

# ---- 3.2 Independence ----------------------------------------------------
print("\n== 3.2 INDEPENDENCE (stream availability while the native integration is unavailable)")
nat = intervals(N_SOC)
srs = rows(S_SOC)
native_down = sum(b - a for a, b, s in nat if s in BAD)
both_down = 0.0
for a, b, s in nat:
    if s not in BAD:
        continue
    for sa, sb, ss in intervals(S_SOC):
        if ss in BAD:
            lo, hi = max(a, sa), min(b, sb)
            if hi > lo:
                both_down += hi - lo
if native_down:
    print(f"  native unavailable: {native_down:.0f}s ({native_down/clean_s*100:.1f}% of clean window)")
    print(f"  stream ALSO unavailable during those: {both_down:.0f}s -> stream up "
          f"{(1-both_down/native_down)*100:.2f}% of native-down time   (PASS >= 99%)")
else:
    print("  native never unavailable in window — criterion UNTESTED")
native_down_ep = [(a, b) for a, b, s in nat if s in BAD]
print(f"  native-down episodes: {len(native_down_ep)}; longest {max([b-a for a,b in native_down_ep], default=0):.0f}s")

# ---- 3.3 Agreement -------------------------------------------------------
print("\n== 3.3 AGREEMENT (60 s samples)")
top = rows(S_SOCTOP); nrs = rows(N_SOC); crs = rows(C_SOC)
d_top, d_nat, d_cld = [], [], []
for t in sample_times():
    s = num(value_at(srs, t))
    if s is None:
        continue
    v = num(value_at(top, t))
    if v is not None:
        d_top.append(s - v)
    v = num(value_at(nrs, t))
    if v is not None:
        d_nat.append(s - v)
    c = row_at(crs, t)
    # cloud only compared while its own reading is <= 600 s old (its tier bound);
    # a stale cloud value measures cloud lag, not stream truth. NB: rows are value-change
    # rows, so an unchanged-but-refreshed cloud value reads older here than it really is.
    if c and num(c[1]) is not None and t - c[0] <= 600:
        d_cld.append(s - num(c[1]))
for name, d in (("stream enc_agg_soc - soc_top_level", d_top),
                ("stream - native (both available)", d_nat),
                ("stream - cloud (cloud <=600 s old)", d_cld)):
    if d:
        ad = [abs(x) for x in d]
        print(f"  {name:38s} n={len(d):5d} mean {st.mean(d):+6.2f}pp  p50|d| {pct(ad,50):.1f}  "
              f"p95|d| {pct(ad,95):.1f}  max|d| {max(ad):.1f}  nonzero {sum(1 for x in d if x)/len(d)*100:.1f}%")
    else:
        print(f"  {name:38s} n=0 (no overlapping samples)")
print("  PASS rule: |stream - native| <= 2 pp at p95 and |mean| small (no systematic offset)")

# ---- 3.4 Cloud cadence ---------------------------------------------------
print("\n== 3.4 CLOUD CADENCE (row gaps for overall_charge; value-change rows only)")
cts = [t for t, s in rows(C_SOC) if s not in BAD and not excluded(t)]
cg = [b - a for a, b in zip(cts, cts[1:])]
if cg:
    print(f"  n={len(cg)} p50 {pct(cg,50):.0f}s p95 {pct(cg,95):.0f}s max {max(cg):.0f}s  "
          f"(cloud tier bound 600 s; >600 = {sum(1 for g in cg if g>600)/len(cg)*100:.0f}% of gaps)")

# ---- 3.5 Self-consistency -------------------------------------------------
print("\n== 3.5 SELF-CONSISTENCY  residual = pv + grid + battery - load")
pv, gr, bt, ld = rows(S_PV), rows(S_GRID), rows(S_BATT), rows(S_LOAD)
fr = []
for t, s in ld:
    if excluded(t) or t < START:
        continue
    L = num(s)
    vals = [num(value_at(x, t + 0.5)) for x in (pv, gr, bt)]
    L2 = num(value_at(ld, t + 0.5))
    if L2 is None or any(v is None for v in vals) or L2 < 500:
        continue
    fr.append(abs(sum(vals) - L2) / L2)
if fr:
    print(f"  n={len(fr)} (load>=500 W) p50 {pct(fr,50)*100:.2f}%  p95 {pct(fr,95)*100:.2f}%  max {max(fr)*100:.1f}%   (PASS p95 < 2%)")

# ---- 3.6 Contention ------------------------------------------------------
print("\n== 3.6 CONTENTION (native battery -> unavailable transitions per local day; recorder keeps 7 d)")
mid = r.execute("select metadata_id from states_meta where entity_id=?", (N_SOC,)).fetchone()[0]
allr = r.execute("select last_updated_ts,state from states where metadata_id=? order by last_updated_ts", (mid,)).fetchall()
per_day = {}
prev = None
for t, s in allr:
    down = s in BAD
    if down and prev is False:
        k = datetime.fromtimestamp(t, CDT).strftime("%m-%d")
        per_day[k] = per_day.get(k, 0) + 1
    prev = down
for k in sorted(per_day):
    print(f"  {k}: {per_day[k]:4d} down-events")
print("  baseline (pre-add-on, ALL state changes/2 ~= down-events): 09-18 ~110, 09-19 ~162, 09-20 ~112; add-on live 09-25 ~16:10")

# ---- 3.7 Reserve witness -------------------------------------------------
print("\n== 3.7 RESERVE WITNESS")
lr = [(t, s) for t, s in rows(S_RES) if t > START and not excluded(t) and num(s) is not None]
cr = [(t, s) for t, s in rows(C_RES) if t > START and not excluded(t) and num(s) is not None]
print(f"  stream backup_reserve now {value_at(rows(S_RES), END)}; cloud reserve now {value_at(rows(C_RES), END)}")
print(f"  cloud reserve changes in window: {len(cr)}; stream changes: {len(lr)}")
for t, s in cr:
    conv = next((t2 for t2, s2 in lr if t2 >= t and num(s2) == num(s)), None)
    print(f"     cloud -> {s} at {fmt(t)}; stream converged {'at '+fmt(conv)+f' (lag {conv-t:.0f}s)' if conv else 'NOT in window'}")
if not cr:
    print("  no reserve change in window — convergence lag UNTESTED (needs a reserve change)")

# ---- 3.8 Partial fleet ---------------------------------------------------
print(f"\n== 3.8 PARTIAL FLEET (stream SOC slew > {SLEW_PP_PER_MIN} pp/min = non-physical)")
sv = [(t, num(s)) for t, s in srs if num(s) is not None and not excluded(t) and t >= START]
bad = []
for (t1, a), (t2, b) in zip(sv, sv[1:]):
    if straddles(t1, t2):
        continue
    dt = max(t2 - t1, 1) / 60
    if abs(b - a) / dt > SLEW_PP_PER_MIN and abs(b - a) >= 3:
        bad.append((t2, a, b))
print(f"  non-physical SOC jumps: {len(bad)}")
for t, a, b in bad[:20]:
    print(f"     {fmt(t)}  {a:.0f} -> {b:.0f}")
dv = [(a, b, num(s)) for a, b, s in intervals(S_DEV) if num(s) is not None]
if dv:
    mx = max(v for _, _, v in dv)
    tot = sum(b - a for a, b, _ in dv)
    low = sum(b - a for a, b, v in dv if v < mx)
    print(f"  device-count max {mx:.0f}; time below max {low/tot*100:.1f}% of {tot/3600:.1f} h")
