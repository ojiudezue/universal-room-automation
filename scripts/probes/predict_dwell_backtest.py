"""Read-only backtest for PREDICT-MODEL-DWELL-MIGRATION-1 (plan D0). Stdlib only.

Run on the HA host (read-only URIs, nothing is written):

    ssh ha "python3 - [--days 14] [--json] [--align runtime|probe] [--leak-test]" \
        < scripts/probes/predict_dwell_backtest.py

Built from the two 2026-10-21 session probes (predict_dwell_probe.py and
predict_dwell_probe_runtime.py). Every test day D is scored with a dwell
model trained only on the 56 local days BEFORE D (no hindsight).

P1   room-hour forecast MSE: dwell cell share vs per-room constant vs global
     base rate, actual = the hour's occupied fraction (environmental_data).
P1-R blend sweep w in {0, .25, .5, .75, 1} at +1 h / +4 h on the alignment
     the runtime has (--align runtime, default): target = cell of now + h,
     now uniform in hour H = T - h, persistence = last completed hour at now
     (H-1 when minute >= TICK_MINUTE, else H-2; weighted 58/60 and 2/60).
     --align probe = the superseded lag-exactly-h alignment (P1 table); the
     two modes must print different +1 h w=0.5 numbers (plan M1 check).
     Reported for all days, the first half (selection) and the second half
     (held out).
P2   head-to-head on the live bayesian_occupancy samples (AUC, Brier).
P3   next room top-1/top-3 per person: constant, time-bin arrival, from
     current room (PatternLearner shape), current room x time bin; raw and
     flap-deduped. NOTE: from-room agreement is 100% BY CONSTRUCTION here
     (the prediction's room IS the transition's from_room) -> this is an
     UPPER BOUND on agreement; the live skip rate is measured by the D4
     counter (skip_ratio on *_next_room_accuracy), not here.
P5   producer agreement (plan §5.2): hourly occupied fraction from
     environmental_data vs time-weighted recorder binary_sensor.<room>_occupied
     for 4 rooms x the last full day; flag hours differing by > 0.1.
ASSERT every model used for day D has max(training timestamp) < D 00:00.
     --leak-test moves the training end PAST the day start (in-sample) and
     must show a lower error AND a failed assertion.
"""
import argparse
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Chicago")
URA = "file:/config/universal_room_automation/data/universal_room_automation.db?mode=ro"
REC = "file:/config/home-assistant_v2.db?mode=ro"
WIN = 56            # = OCC_ANOMALY_WINDOW_DAYS
FLAP_S = 60         # = NEXT_ROOM_FLAP_DEDUPE_S
TICK_MINUTE = 2     # = DWELL_SHARE_TICK_MINUTE
MIN_SAMPLES = 6     # = DWELL_SHARE_MIN_ACTUAL_SAMPLES
W = [0, 0.25, 0.5, 0.75, 1.0]

ap = argparse.ArgumentParser()
ap.add_argument("--days", type=int, default=14)
ap.add_argument("--json", action="store_true")
ap.add_argument("--align", choices=("runtime", "probe"), default="runtime")
ap.add_argument("--leak-test", action="store_true")
args = ap.parse_args(sys.argv[1:])

c = sqlite3.connect(URA, uri=True)
now_l = datetime.now(TZ)
today0 = now_l.replace(hour=0, minute=0, second=0, microsecond=0)
first_test = today0 - timedelta(days=args.days)
mid = first_test + timedelta(days=args.days // 2)
train_start = first_test - timedelta(days=WIN)


def utc_naive(dt):
    return dt.astimezone(timezone.utc).replace(tzinfo=None).isoformat()


names = {}
st = json.load(open("/config/.storage/core.config_entries"))
for e in st["data"]["entries"]:
    if e["domain"] == "universal_room_automation" and e["data"].get("entry_type") == "room":
        names[e["entry_id"]] = e["data"].get("room_name")
by_name = {v: k for k, v in names.items()}

rows = c.execute(
    "SELECT room_id, substr(timestamp,1,13), SUM(occupied), COUNT(occupied) "
    "FROM environmental_data WHERE timestamp >= ? AND timestamp < ? "
    "AND occupied IS NOT NULL GROUP BY 1,2",
    (utc_naive(train_start), utc_naive(today0))).fetchall()
hours = {}
for rid, b, s, n in rows:
    if rid not in names:
        continue
    lt = datetime.strptime(b, "%Y-%m-%dT%H").replace(tzinfo=timezone.utc).astimezone(TZ)
    hours[(rid, lt)] = (s, n)


def cell(lt):
    return (lt.hour, "we" if lt.weekday() >= 5 else "wd")


def model_for(day0):
    """Train on [day0 - WIN, end); end = day0, or day0 + 1 day under
    --leak-test (deliberately in-sample). Returns the max training hour."""
    lo = day0 - timedelta(days=WIN)
    hi = day0 + timedelta(days=1) if args.leak_test else day0
    m = defaultdict(lambda: [0, 0]); rm = defaultdict(lambda: [0, 0]); g = [0, 0]
    max_ts = None
    for (rid, lt), (s, n) in hours.items():
        if lo <= lt < hi:
            k = m[(rid, cell(lt))]; k[0] += s; k[1] += n
            r = rm[rid]; r[0] += s; r[1] += n
            g[0] += s; g[1] += n
            if max_ts is None or lt > max_ts:
                max_ts = lt
    return m, rm, g, max_ts


def auc(pairs):
    pos = [p for p, y in pairs if y]; neg = [p for p, y in pairs if not y]
    if not pos or not neg:
        return None
    allv = sorted([(p, 1) for p in pos] + [(p, 0) for p in neg])
    ranks = {}; i = 0
    while i < len(allv):
        j = i
        while j < len(allv) and allv[j][0] == allv[i][0]:
            j += 1
        for k in range(i, j):
            ranks.setdefault(allv[k][0], (i + j + 1) / 2)
        i = j
    rp = sum(ranks[p] for p in pos)
    return (rp - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg))


def mean(xs):
    return round(sum(xs) / len(xs), 4) if xs else None


out = {"align": args.align, "leak_test": args.leak_test, "days": args.days}
leak_violations = 0
models = {}
se = defaultdict(list); bin_pairs = []
sweep = {}   # (h, half, w) -> [weighted se, weight]
day = first_test
while day < today0:
    m, rm, g, max_ts = model_for(day)
    if max_ts is not None and max_ts >= day:
        leak_violations += 1
    models[day.date()] = (m, rm, g)
    half = "first" if day < mid else "second"
    gbase = g[0] / g[1] if g[1] else 0
    for (rid, lt), (s, n) in hours.items():
        if not (day <= lt < day + timedelta(days=1)) or n < MIN_SAMPLES:
            continue
        act = s / n
        k = m.get((rid, cell(lt)))
        if not k or not k[1]:
            continue
        p = k[0] / k[1]
        rc = rm[rid][0] / rm[rid][1]
        se["dwell_cell"].append((p - act) ** 2)
        se["room_const"].append((rc - act) ** 2)
        se["global_base"].append((gbase - act) ** 2)
        bin_pairs.append((p, act >= 0.5))
        for h in (1, 4):
            if args.align == "runtime":
                lags = ((h + 1, (60 - TICK_MINUTE) / 60), (h + 2, TICK_MINUTE / 60))
            else:
                lags = ((h, 1.0),)
            for lag, wt in lags:
                prev = hours.get((rid, lt - timedelta(hours=lag)))
                if not prev or prev[1] < MIN_SAMPLES:
                    continue
                pers = prev[0] / prev[1]
                for w in W:
                    for key in ((h, half, w), (h, "all", w)):
                        a = sweep.setdefault(key, [0.0, 0.0])
                        a[0] += wt * ((w * pers + (1 - w) * p) - act) ** 2
                        a[1] += wt
    day += timedelta(days=1)

out["P1_room_hour_mse"] = {k: mean(v) for k, v in se.items()}
out["P1_n"] = len(se["dwell_cell"])
out["P1_auc_hour_mostly_occupied"] = round(auc(bin_pairs) or 0, 3)
out["P1R_blend_sweep_mse"] = {
    f"+{h}h w={w}": {
        part: (round(sweep[(h, part, w)][0] / sweep[(h, part, w)][1], 4)
               if sweep.get((h, part, w), [0, 0])[1] else None)
        for part in ("all", "first", "second")
    }
    for h in (1, 4) for w in W
}
out["no_hindsight_assert"] = "PASS" if leak_violations == 0 else (
    f"FAIL ({leak_violations} test days trained on their own day)")

# ---------------- P2
bo = c.execute(
    "SELECT room_id, prediction_timestamp, predicted_value, actual_value "
    "FROM prediction_results WHERE prediction_type='bayesian_occupancy' "
    "AND prediction_timestamp >= ?",
    (first_test.astimezone(timezone.utc).isoformat(),)).fetchall()
bp, dp = [], []
for rname, ts, pv, av in bo:
    rid = by_name.get(rname)
    if not rid:
        continue
    lt = datetime.fromisoformat(ts).astimezone(TZ)
    md = models.get(lt.date())
    if not md:
        continue
    k = md[0].get((rid, cell(lt)))
    if not k or not k[1]:
        continue
    y = int(av); bp.append((float(pv), y)); dp.append((k[0] / k[1], y))
base = sum(y for _, y in bp) / len(bp) if bp else 0
out["P2"] = {
    "n": len(bp), "base_rate": round(base, 3),
    "bayes_auc": round(auc(bp) or 0, 3), "dwell_auc": round(auc(dp) or 0, 3),
    "bayes_brier": mean([(p - y) ** 2 for p, y in bp]),
    "dwell_brier": mean([(p - y) ** 2 for p, y in dp]),
    "const_brier": mean([(base - y) ** 2 for _, y in bp]),
}


# ---------------- P3
def tbin(h):
    return 0 if h < 6 else 1 if h < 9 else 2 if h < 12 else 3 if h < 17 else 4 if h < 21 else 5


tr = c.execute(
    "SELECT person_id, from_room, to_room, timestamp FROM room_transitions "
    "WHERE timestamp >= ? ORDER BY person_id, timestamp",
    ((first_test - timedelta(days=30)).isoformat(),)).fetchall()
per = defaultdict(list)
for pid, fr, to, ts in tr:
    try:
        t = datetime.fromisoformat(ts)
        if t.tzinfo is None:
            t = t.replace(tzinfo=TZ)
    except ValueError:
        continue
    per[pid].append((t.astimezone(TZ), fr, to))
res = {}
for pid, evs in per.items():
    flap = [False] * len(evs)
    for i in range(len(evs) - 1):
        if (evs[i + 1][0] - evs[i][0]).total_seconds() < FLAP_S:
            flap[i] = True
    for mode in ("raw", "dedup"):
        E = [e for e, f in zip(evs, flap) if not (mode == "dedup" and f)]
        train = [e for e in E if e[0] < first_test]
        test = [e for e in E if e[0] >= first_test]
        if len(train) < 20 or len(test) < 20:
            continue
        const = Counter(e[2] for e in train).most_common(3)
        tb = defaultdict(Counter); mk = defaultdict(Counter); mkt = defaultdict(Counter)
        for t, fr, to in train:
            tb[(tbin(t.hour), t.weekday() >= 5)][to] += 1
            mk[fr][to] += 1; mkt[(fr, tbin(t.hour))][to] += 1
        score = defaultdict(lambda: [0, 0])
        for t, fr, to in test:
            cands = {
                "constant": [r for r, _ in const],
                "timebin_arrival": [r for r, _ in tb[(tbin(t.hour), t.weekday() >= 5)].most_common(3)] or [r for r, _ in const],
                "from_current_room": [r for r, _ in mk[fr].most_common(3)] or [r for r, _ in const],
                "current_room_x_bin": ([r for r, _ in mkt[(fr, tbin(t.hour))].most_common(3)]
                                       if sum(mkt[(fr, tbin(t.hour))].values()) >= 5
                                       else [r for r, _ in mk[fr].most_common(3)]) or [r for r, _ in const],
            }
            for k, v in cands.items():
                score[k][0] += (v[:1] == [to]); score[k][1] += (to in v[:3])
        n = len(test)
        res[f"{pid}|{mode}"] = {
            "n": n,
            "from_room_agreement": "100% (upper bound on agreement, by construction)",
            **{k: f"{100*a/n:.1f}/{100*b/n:.1f}" for k, (a, b) in score.items()},
        }
out["P3_top1/top3_pct"] = res
out["P3_note"] = ("upper bound on agreement; the live skip rate is measured by "
                  "D4's counter (skip_ratio), not here")

# ---------------- P4
out["P4_rooms"] = len(names)
out["P4_pred_rows_by_type"] = c.execute(
    "SELECT prediction_type, count(*), min(prediction_timestamp) "
    "FROM prediction_results GROUP BY 1").fetchall()

# ---------------- P5 producer agreement (4 rooms x last full day)
try:
    reg = json.load(open("/config/.storage/core.entity_registry"))
    occ_eid = {}
    for ent in reg["data"]["entities"]:
        uid = ent.get("unique_id") or ""
        if ent.get("platform") == "universal_room_automation" and uid.endswith("_occupied"):
            occ_eid[uid[: -len("_occupied")]] = ent["entity_id"]
    rec = sqlite3.connect(REC, uri=True)
    day0 = today0 - timedelta(days=1)
    cand = sorted(
        (rid for rid in names if rid in occ_eid),
        key=lambda r: -sum(s for (rr, lt), (s, n) in hours.items()
                           if rr == r and day0 <= lt < today0))[:4]
    agree = {}
    for rid in cand:
        eid = occ_eid[rid]
        lo, hi = day0.timestamp(), today0.timestamp()
        q = ("SELECT s.last_updated_ts, s.state FROM states s JOIN states_meta m "
             "ON s.metadata_id = m.metadata_id WHERE m.entity_id = ? "
             "AND s.last_updated_ts < ? ORDER BY s.last_updated_ts")
        ser = [(t, st_) for t, st_ in rec.execute(q, (eid, hi)) if st_ in ("on", "off")]
        prior = [x for x in ser if x[0] < lo]
        ser = ([(lo, prior[-1][1])] if prior else []) + [x for x in ser if x[0] >= lo]
        worst = 0.0; bad = 0
        for hh in range(24):
            hs = day0 + timedelta(hours=hh); he = hs + timedelta(hours=1)
            a, b = hs.timestamp(), he.timestamp()
            on = 0.0
            for i, (t, s) in enumerate(ser):
                t2 = ser[i + 1][0] if i + 1 < len(ser) else b
                lo_, hi_ = max(t, a), min(t2, b)
                if hi_ > lo_ and s == "on":
                    on += hi_ - lo_
            rec_frac = on / 3600.0
            env = hours.get((rid, hs.astimezone(TZ)))
            if not env or not env[1]:
                continue
            diff = abs(env[0] / env[1] - rec_frac)
            worst = max(worst, diff); bad += diff > 0.1
        agree[names[rid]] = {"max_abs_diff": round(worst, 3), "hours_over_0.1": bad}
    out["P5_producer_agreement"] = agree
except Exception as exc:  # noqa: BLE001
    out["P5_producer_agreement"] = f"unavailable: {type(exc).__name__}: {exc}"

if args.json:
    print(json.dumps(out, default=str))
else:
    print(json.dumps(out, indent=1, default=str))
if args.leak_test:
    # The self-test must FAIL the no-hindsight assertion.
    assert leak_violations > 0, "leak-test did not trip the no-hindsight assert"
    print("leak-test: no-hindsight assertion FAILED as intended", file=sys.stderr)
    sys.exit(1)
assert leak_violations == 0, "no-hindsight assertion failed"
