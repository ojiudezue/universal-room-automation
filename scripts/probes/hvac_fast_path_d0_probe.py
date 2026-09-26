#!/usr/bin/env python3
"""W2-1 D0 fast-path rate probe (PLANNING_hvac_w2_occupancy_fast_path.md §3 / §5.D0).

READ-ONLY. Run on the HA host:

    ssh ha "python3 - [--days 7] [--no-overrides] [--json]" < scripts/probes/hvac_fast_path_d0_probe.py

Sources (all opened read-only):
  * recorder   file:/config/home-assistant_v2.db?mode=ro
  * URA DB     file:/config/universal_room_automation/data/universal_room_automation.db?mode=ro
  * /config/.storage/core.config_entries, core.entity_registry (plain file reads)

What it measures (plan §3):
  1. Rising edges (strict "off" -> "on", plan §4.1 finding 6) per ROOM on the room's own
     STATE_OCCUPIED entity, resolved from the entity registry by unique_id
     f"{entry_id}_occupied" (platform universal_room_automation). Rooms: non-disabled ROOM
     entries, room_type != hallway, member of an HVAC zone (zone membership = latest
     `sensor.ura_hvac_coordinator_zone_N_status` attrs live_rooms + excluded_rooms +
     transient_rooms).
  2. Armed-gate replay. Two variants:
       P ("plan replay")  - edge is eligible iff the room's last on->off (falling) edge is
                            >= hold seconds before it (tail measured from the falling edge).
       S ("cycle sim")    - replays the D1 producer `_compute_hvac_occupied`
                            (hvac_zones.py:1048-1123) at every cycle: inferred periodic ticks
                            + house-state-change cycles + one cycle at every eligible edge
                            (the fast path itself, limiter ignored). An edge is eligible iff
                            `_hvac_armed[room]` was not True after the last cycle. Producer
                            state is reset at every HA start (in-memory dicts).
     hold = `_effective_hvac_hold_seconds` (hvac_zones.py:976-1046): per-room override
     CONF_HVAC_VACANCY_HOLD[_NIGHT] (const.py:1252-1253) if set in options, else
     ROOM_TYPE_HVAC_HOLD (const.py:1219-1224, default DEFAULT_HVAC_VACANCY_HOLD=60 const.py:1213)
     / ROOM_TYPE_HVAC_HOLD_NIGHT (const.py:1230-1241, default DEFAULT_HVAC_VACANCY_HOLD_NIGHT=60
     const.py:1217); night iff house_state in FAN_TRUST_STATES = (home_night, sleep, waking)
     (hvac_const.py:881); night >= day clamp. House state = recorded
     `sensor.ura_coordinator_manager_house_state` (CoordinatorManager.house_state, the
     HVAC boot seed at hvac.py:1250-1253; live updates via SIGNAL_HOUSE_STATE_CHANGED).
     Variant P keys the hold on house state at the falling edge (when the producer sets the
     tail, hvac_zones.py:1111).
     S also tags each eligible edge 'zone-cold' when NO room of its zone was armed at the
     edge (the only edges that can change the zone's fused any_room_hvac_occupied).
  3. Per zone per local day: eligible-edge count median/p95/max; inter-edge gap percentiles;
     sliding 5-min burst p95/max.
  4. Periodic-tick coverage: seconds from each eligible edge to the next inferred periodic
     tick; share <= 60/120/300 s.
  5. Cycle-duration proxy (see TICK INFERENCE below).
  6. Limiter replay for candidate HVAC_FAST_PATH_MIN_INTERVAL_S / _GLOBAL_MIN_INTERVAL_S.

Windows: last N days. MAIN = window start .. EMPTY_HOUSE_START (2026-09-26 19:20Z, nobody home
afterwards -> phantom edges reported as a separate bonus column). Every HA restart is
excluded from homeassistant_stop to homeassistant_started + 15 min.

TICK INFERENCE. `async_track_time_interval` re-arms at loop.time()+300 s each firing
(homeassistant/helpers/event.py _TrackTimeInterval._schedule_timer), so periodic ticks sit on
a fixed 300 s grid per HA run (plus tiny loop lateness). `SIGNAL_HVAC_ENTITIES_UPDATE` is sent
only at the END of `_run_decision_cycle` (hvac.py:1799) and `HVACZoneStatusSensor` writes state
on it (sensor.py:12274-12276). So zone-status recorder rows = cycle END times (when attrs
changed). Per 3-h chunk, the tick phase is the lower envelope (2nd pct) of the densest 30-s
circular cluster of (row_ts mod 300); cycle-duration proxy = row residual - phase. This is a
PROXY: it measures cycle end relative to the fastest cycle in the chunk, not absolute duration.
"""
import bisect
import collections
import datetime as dt
import json
import sqlite3
import statistics
import sys
import time
from zoneinfo import ZoneInfo

REC = "file:/config/home-assistant_v2.db?mode=ro"
URADB = "file:/config/universal_room_automation/data/universal_room_automation.db?mode=ro"
STORAGE = "/config/.storage"
TZ = ZoneInfo("America/Chicago")
DOMAIN = "universal_room_automation"

args = sys.argv[1:]
DAYS = int(args[args.index("--days") + 1]) if "--days" in args else 7
NO_OVERRIDES = "--no-overrides" in args
AS_JSON = "--json" in args

EMPTY_HOUSE_START = dt.datetime(2026, 9, 26, 19, 20, tzinfo=dt.timezone.utc).timestamp()
RESTART_TAIL_S = 15 * 60
TICK_S = 300  # HVAC_DECISION_TICK, hvac_const.py:13
FAN_TRUST_STATES = ("home_night", "sleep", "waking")  # hvac_const.py:881
DEFAULT_HOLD_DAY = 60     # const.py:1213
DEFAULT_HOLD_NIGHT = 60   # const.py:1217
ROOM_TYPE_HVAC_HOLD = {"bedroom": 60, "media_room": 120, "common_area": 60, "hallway": 0}  # const.py:1219-1224
ROOM_TYPE_HVAC_HOLD_NIGHT = {  # const.py:1230-1241
    "bedroom": 1800, "media_room": 1800, "common_area": 900, "generic": 600, "closet": 300,
    "bathroom": 600, "garage": 600, "utility": 600, "infrastructure": 300, "hallway": 0,
}
ZONE_ENTRY_DWELL_S = 120      # live option hvac_zone_entry_dwell = 2 (state of play §3.2)
FAST_PATH_DWELL_SLACK_S = 2   # plan §4.3
L_CANDIDATES = [0, 15, 30, 45, 60, 90, 120, 180, 240, 300]
G_CANDIDATES = [0, 10, 20, 30, 45, 60]

NOW = time.time()
W_START = NOW - DAYS * 86400
PRE = 86400  # history before window for prior falling edges / sim warm-up


def pct(xs, p):
    if not xs:
        return None
    xs = sorted(xs)
    k = (len(xs) - 1) * p / 100.0
    lo = int(k)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def fmt(x, nd=0):
    if x is None:
        return "-"
    return f"{x:.{nd}f}"


def iso(ts):
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")


def lday(ts):
    return dt.datetime.fromtimestamp(ts, TZ).date().isoformat()


def coerce_override(raw):  # hvac_zones.py:42-58 _coerce_hold_override
    if raw is None or raw == "":
        return None
    try:
        v = int(raw)
    except (TypeError, ValueError):
        return None
    return None if v < 0 else v


def eff_hold(room, house_state):  # hvac_zones.py:976-1046
    rt = room["type"]
    day = ROOM_TYPE_HVAC_HOLD.get(rt, DEFAULT_HOLD_DAY)
    night = ROOM_TYPE_HVAC_HOLD_NIGHT.get(rt, DEFAULT_HOLD_NIGHT)
    if not NO_OVERRIDES:
        if room["ov_day"] is not None:
            day = room["ov_day"]
        if room["ov_night"] is not None:
            night = room["ov_night"]
    if night < day:
        night = day
    return night if house_state in FAN_TRUST_STATES else day


# ---------------------------------------------------------------- config / registry
ce = json.load(open(f"{STORAGE}/core.config_entries"))["data"]["entries"]
er = json.load(open(f"{STORAGE}/core.entity_registry"))["data"]["entities"]
uid_to_eid = {
    e["unique_id"]: e["entity_id"] for e in er
    if e["platform"] == DOMAIN and e["entity_id"].startswith("binary_sensor.")
}

rec = sqlite3.connect(REC, uri=True)


def latest_attrs(eid):
    r = rec.execute(
        "select a.shared_attrs from states s join states_meta m using(metadata_id) "
        "join state_attributes a on a.attributes_id=s.attributes_id "
        "where m.entity_id=? order by s.last_updated_ts desc limit 1", (eid,)).fetchone()
    return json.loads(r[0]) if r else {}


zone_of = {}
for zn in (1, 2, 3):
    a = latest_attrs(f"sensor.ura_hvac_coordinator_zone_{zn}_status")
    for key in ("live_rooms", "excluded_rooms", "transient_rooms"):
        for rn in a.get(key) or []:
            zone_of[rn] = f"zone_{zn}"

rooms = {}
skipped = []
for e in ce:
    if e["domain"] != DOMAIN or e["data"].get("entry_type") != "room":
        continue
    m = {**e["data"], **e["options"]}
    name = m.get("room_name", "")
    rtype = m.get("room_type") or "generic"
    why = None
    if e.get("disabled_by"):
        why = "disabled"
    elif rtype == "hallway":
        why = "hallway"
    elif name not in zone_of:
        why = "no HVAC zone"
    eid = uid_to_eid.get(f"{e['entry_id']}_occupied")
    if why is None and not eid:
        why = "no registry entity"
    if why:
        skipped.append((name, rtype, why))
        continue
    rooms[name] = {
        "name": name, "type": rtype, "zone": zone_of[name], "eid": eid,
        "ov_day": coerce_override(m.get("hvac_vacancy_hold")),
        "ov_night": coerce_override(m.get("hvac_vacancy_hold_night")),
    }


# ---------------------------------------------------------------- recorder series
def series(eid, since):
    rows = rec.execute(
        "select s.state, s.last_updated_ts from states s join states_meta m using(metadata_id) "
        "where m.entity_id=? and s.last_updated_ts>=? order by s.last_updated_ts", (eid, since)).fetchall()
    prior = rec.execute(
        "select s.state, s.last_updated_ts from states s join states_meta m using(metadata_id) "
        "where m.entity_id=? and s.last_updated_ts<? order by s.last_updated_ts desc limit 1",
        (eid, since)).fetchone()
    out = []
    if prior:
        out.append((prior[1], prior[0]))
    for st, ts in rows:
        if out and out[-1][1] == st:
            continue
        out.append((ts, st))
    return out


def state_at(ser, ts_list, t):
    i = bisect.bisect_right(ts_list, t) - 1
    return ser[i][1] if i >= 0 else None


HS = series("sensor.ura_coordinator_manager_house_state", W_START - PRE)
HS_T = [x[0] for x in HS]


def house_at(t):
    s = state_at(HS, HS_T, t)
    # "unavailable" -> the coordinator keeps its last known state; walk back.
    i = bisect.bisect_right(HS_T, t) - 1
    while i >= 0 and HS[i][1] in ("unavailable", "unknown", None):
        i -= 1
    return HS[i][1] if i >= 0 else s


# HA runs (stop -> started)
evs = rec.execute(
    "select et.event_type, e.time_fired_ts from events e join event_types et using(event_type_id) "
    "where et.event_type in ('homeassistant_stop','homeassistant_started') and e.time_fired_ts>? "
    "order by 2", (W_START - PRE,)).fetchall()
restarts = []  # (stop, started)
pending_stop = None
for et, ts in evs:
    if et == "homeassistant_stop":
        pending_stop = ts
    elif et == "homeassistant_started":
        restarts.append((pending_stop if pending_stop else ts - 60, ts))
        pending_stop = None
EXCL = [(a, b + RESTART_TAIL_S) for a, b in restarts]


def excluded(t):
    return any(a <= t <= b for a, b in EXCL)


def bucket(t):
    if t < W_START:
        return None
    if excluded(t):
        return "restart"
    return "main" if t < EMPTY_HOUSE_START else "empty"


# ---------------------------------------------------------------- tick inference
seg_bounds = []  # HA runs: [started, next stop)
starts = [b for _, b in restarts]
stops = [a for a, _ in restarts]
run_starts = [W_START - PRE] + starts
for i, s in enumerate(run_starts):
    nxt = stops[i] if i < len(stops) else NOW
    seg_bounds.append((s, nxt))

zs_rows = []
for zn in (1, 2, 3):
    zs_rows += [r[0] for r in rec.execute(  # raw rows: attribute-only writes count (cycle ends)
        "select s.last_updated_ts from states s join states_meta m using(metadata_id) "
        "where m.entity_id=? and s.last_updated_ts>=?",
        (f"sensor.ura_hvac_coordinator_zone_{zn}_status", W_START - PRE))]
zs_rows = sorted(set(round(t, 3) for t in zs_rows))

CHUNK = 6 * 3600
PERIODS = [299.8 + k * 0.02 for k in range(91)]  # 299.8 .. 301.6 s (loop lateness drift)
ticks = []          # inferred periodic tick start times
dur_proxy = []      # cycle end - inferred tick start, rows in [phase, phase+60) (main window)
phase_log = []      # (chunk_start, rows, best_period, cluster_count)


def densest(rr, width, period):
    rr = sorted(rr)
    n = len(rr)
    ext = rr + [x + period for x in rr]
    best = (0, 0.0)
    j = 0
    for i in range(n):
        while j < len(ext) and ext[j] < rr[i] + width:
            j += 1
        if j - i > best[0]:
            best = (j - i, rr[i])
    return best


for s, e in seg_bounds:
    c = s
    while c < e:
        ce_ = min(c + CHUNK, e)
        rows = [t for t in zs_rows if c <= t < ce_]
        if len(rows) >= 20:
            cand = []
            for P_ in PERIODS:
                cnt, r0 = densest([(t - c) % P_ for t in rows], 15, P_)
                cand.append((cnt, -abs(P_ - 300.5), P_, r0))
            cnt, _, P_, r0 = max(cand)
            res = [(t - c) % P_ for t in rows]
            near = [((r - r0 + 20) % P_) - 20 for r in res]          # centred on r0
            lo = pct([x for x in near if -20 <= x < 60], 2)
            phase = (r0 + lo) % P_
            if c >= W_START:
                phase_log.append((c, len(rows), round(P_, 2), cnt))
            for t in rows:
                d = ((t - c) - phase) % P_
                if d < 60 and bucket(t) == "main":
                    dur_proxy.append(d)
            k = 0
            tk = c + phase
            while tk < ce_:
                if tk > s + 5:
                    ticks.append(tk)
                tk += P_
        c = ce_
ticks.sort()


def next_tick_wait(t):
    i = bisect.bisect_left(ticks, t)
    if i >= len(ticks):
        return None
    w = ticks[i] - t
    return w if w <= TICK_S + 10 else None  # gap (restart) -> unknown


# ---------------------------------------------------------------- room series + edges
RS = {}
for rn, r in rooms.items():
    ser = series(r["eid"], W_START - PRE)
    RS[rn] = (ser, [x[0] for x in ser])

edges = []          # (t, room)
noise_edges = collections.Counter()  # non-off -> on transitions (not rising edges)
for rn, (ser, _) in RS.items():
    for (t0_, s0), (t1, s1) in zip(ser, ser[1:]):
        if s1 == "on" and s0 == "off":
            edges.append((t1, rn))
        elif s1 == "on" and s0 != "on" and t1 >= W_START:
            noise_edges[s0] += 1
edges.sort()

# ---- variant P: plan replay (tail from the falling edge)
eligP = set()
for rn, (ser, _) in RS.items():
    last_fall = None
    for (t0_, s0), (t1, s1) in zip(ser, ser[1:]):
        if s0 == "on" and s1 != "on":
            last_fall = t1
        if s1 == "on" and s0 == "off":
            if last_fall is None or (t1 - last_fall) >= eff_hold(rooms[rn], house_at(last_fall)):
                eligP.add((t1, rn))

# ---- variant S: cycle simulation of the D1 producer
cycles_fixed = [(t, "tick") for t in ticks] + [(t, "house_state") for t, _ in HS if t >= W_START - PRE]
events = [(t, 1, kind, None) for t, kind in cycles_fixed] + [(t, 0, "edge", rn) for t, rn in edges]
run_start_set = sorted(starts)
events += [(t, -1, "reset", None) for t in run_start_set]
events.sort(key=lambda x: (x[0], x[1]))

armed = {}
prev = {}
tail = {}
eligS = {}  # (t, room) -> zone_cold flag


def producer_pass(t):
    hs = house_at(t)
    for rn, (ser, ts_) in RS.items():
        st = state_at(ser, ts_, t)
        if st not in ("on", "off"):
            continue  # coordinator absent / unavailable: producer does not touch armed
        occ = st == "on"
        p = prev.get(rn, False)
        if occ and not p:
            armed[rn] = True
            tail.pop(rn, None)
            prev[rn] = True
            continue
        prev[rn] = occ
        if not armed.get(rn, False):
            continue
        if occ:
            tail.pop(rn, None)
            continue
        te = tail.get(rn)
        if te is None:
            h = eff_hold(rooms[rn], hs)
            if h <= 0:
                armed[rn] = False
            else:
                tail[rn] = t + h
            continue
        if t >= te:
            armed[rn] = False
            tail.pop(rn, None)


for t, _, kind, rn in events:
    if kind == "reset":
        armed.clear(); prev.clear(); tail.clear()
        continue
    if kind == "edge":
        if not armed.get(rn, False):
            z = rooms[rn]["zone"]
            cold = not any(armed.get(o, False) for o, rr in rooms.items() if rr["zone"] == z)
            eligS[(t, rn)] = cold
            producer_pass(t)  # the fast-path cycle itself
        continue
    producer_pass(t)

# ---------------------------------------------------------------- aggregation
ZONES = ["zone_1", "zone_2", "zone_3"]


def zone_edges(elig, bkt="main", cold_only=False):
    out = {z: [] for z in ZONES}
    for key in elig:
        t, rn = key
        if bucket(t) != bkt:
            continue
        if cold_only and not (isinstance(elig, dict) and elig[key]):
            continue
        out[rooms[rn]["zone"]].append(t)
    for z in out:
        out[z].sort()
    return out


# day coverage (hours of MAIN window per local day)
day_hours = collections.Counter()
t = W_START
while t < NOW:
    if bucket(t) == "main":
        day_hours[lday(t)] += 60
    t += 60
day_hours = {d: v / 3600 for d, v in day_hours.items()}
full_days = [d for d, h in sorted(day_hours.items()) if h >= 20]


def zone_stats(zedges):
    out = {}
    for z, ts in zedges.items():
        per_day = collections.Counter(lday(t) for t in ts)
        counts_full = [per_day.get(d, 0) for d in full_days]
        gaps = [b - a for a, b in zip(ts, ts[1:]) if not any(x <= b and a <= y for x, y in EXCL)]
        bursts = [bisect.bisect_left(ts, t + 300) - i for i, t in enumerate(ts)]
        waits = [w for w in (next_tick_wait(t) for t in ts) if w is not None]
        out[z] = {
            "n": len(ts),
            "per_day": {d: per_day.get(d, 0) for d in sorted(day_hours)},
            "day_med": statistics.median(counts_full) if counts_full else None,
            "day_p95": pct(counts_full, 95), "day_max": max(counts_full) if counts_full else None,
            "gap": {p: pct(gaps, p) for p in (1, 5, 50, 95, 99)},
            "burst5_p95": pct(bursts, 95), "burst5_max": max(bursts) if bursts else None,
            "cov": {x: (100.0 * sum(1 for w in waits if w <= x) / len(waits)) if waits else None
                    for x in (60, 120, 300)},
            "wait_med": pct(waits, 50), "n_wait": len(waits),
        }
    return out


def limiter(zedges, L, G, followups=None, cold=None):
    """Replay per-zone limiter L and global limiter G (plan §4.1 gates 5-6, stamps only on run)."""
    evs = [(t, z, "edge") for z, ts in zedges.items() for t in ts]
    if followups:
        evs += [(t, z, "followup") for z, ts in followups.items() for t in ts]
    evs.sort()
    last_z = {}
    last_any = None
    den = collections.Counter()
    tot = collections.Counter()
    runs = []
    for t, z, kind in evs:
        is_cold = cold is not None and (t, z) in cold
        if kind == "edge":
            tot[z] += 1
            if is_cold:
                tot["cold"] += 1
            if z in last_z and t - last_z[z] < L:
                den[z] += 1
                den["cold"] += is_cold
                continue
        if last_any is not None and t - last_any < G:
            if kind == "edge":
                den[z] += 1
                den["cold"] += is_cold
            else:
                den["followup_" + z] += 1
            continue
        last_z[z] = t
        last_any = t
        runs.append(t)
    return den, tot, runs


result = {"window": [iso(W_START), iso(NOW)], "empty_house_start": iso(EMPTY_HOUSE_START),
          "restarts": [(iso(a), iso(b)) for a, b in restarts if b >= W_START],
          "overrides": not NO_OVERRIDES, "rooms": len(rooms), "skipped": skipped,
          "full_days": full_days, "day_hours": {d: round(h, 1) for d, h in sorted(day_hours.items())},
          "ticks_inferred": len([t for t in ticks if t >= W_START])}

raw_by_b = collections.Counter(bucket(t) for t, _ in edges)
result["raw_edges"] = dict(raw_by_b)
result["noise_edges_non_off_to_on"] = dict(noise_edges)

per_room = collections.defaultdict(lambda: collections.Counter())
for t, rn in edges:
    b = bucket(t)
    if b is None:
        continue
    per_room[rn]["raw_" + b] += 1
    if (t, rn) in eligP:
        per_room[rn]["P_" + b] += 1
    if (t, rn) in eligS:
        per_room[rn]["S_" + b] += 1
        if eligS[(t, rn)]:
            per_room[rn]["Scold_" + b] += 1
result["per_room"] = {rn: dict(c) for rn, c in per_room.items()}

zP = zone_edges(eligP)
zS = zone_edges(eligS)
zScold = zone_edges(eligS, cold_only=True)
result["P"] = zone_stats(zP)
result["S"] = zone_stats(zS)
result["S_cold"] = zone_stats(zScold)
for v, ze in (("P", zone_edges(eligP, "empty")), ("S", zone_edges(eligS, "empty")),
              ("S_cold", zone_edges(eligS, "empty", True))):
    result.setdefault("empty", {})[v] = {z: len(ts) for z, ts in ze.items()}
empty_h = max(0.0, (NOW - EMPTY_HOUSE_START - sum(max(0, min(b, NOW) - max(a, EMPTY_HOUSE_START))
                                                   for a, b in EXCL)) / 3600)
result["empty_hours"] = round(empty_h, 2)

# raw edges per zone (all rising edges, pre-gate)
raw_z = {z: 0 for z in ZONES}
for t, rn in edges:
    if bucket(t) == "main":
        raw_z[rooms[rn]["zone"]] += 1
result["raw_main_by_zone"] = raw_z

# limiter sweeps
lim = {}
for vname, ze in (("P", zP), ("S", zS)):
    lim[vname] = {}
    for L in L_CANDIDATES:
        den, tot, _ = limiter(ze, L, 0)
        lim[vname][L] = {z: (100.0 * den[z] / tot[z]) if tot[z] else None for z in ZONES}
result["per_zone_limiter_deny_pct"] = lim

# busiest day per zone (variant S) deny at each L
busy = {}
for z in ZONES:
    pdays = collections.Counter(lday(t) for t in zS[z])
    if not pdays:
        continue
    d, _ = pdays.most_common(1)[0]
    only = {zz: ([t for t in zS[z] if lday(t) == d] if zz == z else []) for zz in ZONES}
    busy[z] = {"day": d, "n": len(only[z]),
               "deny": {L: (100.0 * limiter(only, L, 0)[0][z] / len(only[z])) for L in L_CANDIDATES}}
result["busiest_day_deny_S"] = busy

# global limiter with dwell follow-ups (follow-up per cold edge at +dwell+slack, S variant)
fol = {z: [t + ZONE_ENTRY_DWELL_S + FAST_PATH_DWELL_SLACK_S for t in zScold[z]] for z in ZONES}
glob = {}
cold_set = {(t, z) for z, ts in zScold.items() for t in ts}
for L in (15, 30, 60, 90, 120, 300):
    glob[L] = {}
    for G in G_CANDIDATES:
        den, tot, runs = limiter(zS, L, G, fol, cold_set)
        n_edges = sum(tot[z] for z in ZONES)
        edge_den = sum(den[z] for z in ZONES)
        fden = sum(v for k, v in den.items() if k.startswith("followup_"))
        # max runs in any 20 s window
        mx20 = max((bisect.bisect_left(runs, t + 20) - i for i, t in enumerate(runs)), default=0)
        glob[L][G] = {"edge_deny_pct": 100.0 * edge_den / n_edges if n_edges else None,
                      "followup_deny": fden, "followups": sum(len(v) for v in fol.values()),
                      "runs": len(runs), "max_runs_20s": mx20,
                      "cold_deny": den["cold"], "cold_total": tot["cold"]}
result["global_limiter"] = glob
main_hours = sum(day_hours.values())
result["main_hours"] = round(main_hours, 1)

# ---------------------------------------------------------------- cycle duration proxy
result["cycle_end_proxy_s"] = {p: pct(dur_proxy, p) for p in (5, 25, 50, 75, 90, 95, 99, 100)}
result["cycle_end_proxy_hist_5s"] = sorted(collections.Counter(int(d // 5) * 5 for d in dur_proxy).items())
result["tick_periods"] = sorted(collections.Counter(p for _, _, p, _ in phase_log).items())
result["cycle_end_proxy_n"] = len(dur_proxy)

# ---------------------------------------------------------------- W1-A rows (informational only)
try:
    u = sqlite3.connect(URADB, uri=True)
    r = u.execute("select count(*), min(timestamp), max(timestamp) from ura_activity_log "
                  "where action='climate_write'").fetchone()
    result["climate_write_rows_so_far"] = r
except Exception as ex:  # noqa: BLE001
    result["climate_write_rows_so_far"] = f"error: {ex}"

if AS_JSON:
    print(json.dumps(result, indent=1, default=str))
    sys.exit(0)

# ---------------------------------------------------------------- human report
P = print
P(f"# D0 probe  window {result['window'][0]} .. {result['window'][1]}  overrides={not NO_OVERRIDES}")
P(f"restarts excluded (stop .. started+15m): {result['restarts']}")
P(f"MAIN hours={result['main_hours']}  full local days (>=20h MAIN)={full_days}")
P(f"day_hours={result['day_hours']}  empty-house hours={result['empty_hours']}")
P(f"rooms measured={len(rooms)}; skipped={len(skipped)}")
for s in skipped:
    P(f"   skip {s}")
P(f"ticks inferred in window={result['ticks_inferred']}  (7d max ~{DAYS*288})")
P(f"raw strict off->on edges by bucket: {result['raw_edges']}; raw MAIN by zone {raw_z}")
P(f"non-off->on 'on' transitions (NOT rising edges, lifecycle noise): {result['noise_edges_non_off_to_on']}")
P("")
P("## per room (MAIN / empty):  raw  P-elig  S-elig  S-cold")
for rn in sorted(rooms, key=lambda x: (rooms[x]["zone"], x)):
    c = per_room.get(rn, {})
    P(f"  {rooms[rn]['zone']} {rn:<28} {rooms[rn]['type']:<14} "
      f"{c.get('raw_main',0):>5} {c.get('P_main',0):>5} {c.get('S_main',0):>5} {c.get('Scold_main',0):>5}"
      f"   | empty {c.get('raw_empty',0):>3} {c.get('P_empty',0):>3} {c.get('S_empty',0):>3} {c.get('Scold_empty',0):>3}")
for v in ("P", "S", "S_cold"):
    P("")
    P(f"## variant {v}")
    P("zone   n  day_med day_p95 day_max | gap_p1 gap_p5 gap_p50 gap_p95 gap_p99 | b5_p95 b5_max | "
      "cov60 cov120 cov300 wait_med | empty")
    for z in ZONES:
        s = result[v][z]
        g = s["gap"]
        P(f"{z} {s['n']:>4} {fmt(s['day_med'],1):>7} {fmt(s['day_p95'],1):>7} {fmt(s['day_max']):>7} | "
          f"{fmt(g[1]):>6} {fmt(g[5]):>6} {fmt(g[50]):>7} {fmt(g[95]):>7} {fmt(g[99]):>7} | "
          f"{fmt(s['burst5_p95'],1):>6} {fmt(s['burst5_max']):>6} | "
          f"{fmt(s['cov'][60],1):>5} {fmt(s['cov'][120],1):>6} {fmt(s['cov'][300],1):>6} {fmt(s['wait_med']):>8} | "
          f"{result['empty'][v][z]}")
    P("  per local day: " + "; ".join(f"{z}: " + ",".join(f"{d[5:]}={n}" for d, n in result[v][z]['per_day'].items())
                                      for z in ZONES))
P("")
P("## per-zone limiter deny % (edge denied if a fast-path cycle for the same zone ran < L s earlier)")
for v in ("P", "S"):
    for L in L_CANDIDATES:
        P(f"  {v} L={L:>3}: " + "  ".join(f"{z}={fmt(lim[v][L][z],1)}" for z in ZONES))
P("## busiest day per zone (S) deny %")
for z, b in busy.items():
    P(f"  {z} {b['day']} n={b['n']}: " + " ".join(f"L{L}={fmt(d,1)}" for L, d in b["deny"].items()))
P("## global limiter G (S edges + dwell follow-ups at +122 s per cold edge)")
for L, gd in glob.items():
    for G, s in gd.items():
        P(f"  L={L:>3} G={G:>2}: edge_deny={fmt(s['edge_deny_pct'],2)}%  followups={s['followups']} "
          f"followup_denied={s['followup_deny']}  cold_edges_denied={s['cold_deny']}/{s['cold_total']}  non-periodic runs={s['runs']} "
          f"({s['runs']/main_hours*24:.1f}/day)  max runs in any 20 s={s['max_runs_20s']}")
P("")
P(f"## cycle-end proxy (s after inferred tick start; n={len(dur_proxy)}): "
  + " ".join(f"p{p}={fmt(v,2)}" for p, v in result['cycle_end_proxy_s'].items()))
P(f"   5-s histogram: {result['cycle_end_proxy_hist_5s']}")
P(f"   fitted tick periods per 6-h chunk: {result['tick_periods']}")
P(f"## W1-A climate_write rows so far (informational, NOT the baseline): {result['climate_write_rows_so_far']}")
