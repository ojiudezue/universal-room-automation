"""D0 backtest for the room occupancy-anomaly dwell model (read-only).

Card BAYES-OCCUPANCY-ANOMALY-NEVER-EVALUATES-1, plan
docs/planning/PLANNING_occupancy_anomaly_dwell_model.md §7 D0. Operator
2026-10-21: the build ships first; this replay runs AFTER deploy as the live
check and the knob-tuning input. It does not gate the build.

Run on the HA host (stdlib only, read-only on both databases):

    ssh ha "python3 -" < scripts/probes/occupancy_dwell_backtest.py
    ssh ha "python3 - --days 14 --json" < scripts/probes/occupancy_dwell_backtest.py

Reports, against the plan's thresholds:
  step 1  producer health (environmental_data rows / room / day, NULL share)
  step 2+3 no-hindsight replay of the last N local days: the model for day D
          is trained ONLY on [D-56, D) (asserted), the day is replayed from the
          recorder's binary_sensor.<room>_occupied + house-state history every
          60 s applying invariant I1; sweep threshold x debounce x model
          (48-cell hour x day-type, 168-cell hour-of-week)
  step 4  learned share vs resident person_visits dwell for four rooms
  step 5  fire sample with context and a heuristic judgement
  G1 rate, G2 quality (heuristic, needs a human read), G3 discrimination
  (Study A weekday daytime), G4 learning coverage, plus the DAO query time.

Mirrors the shipped logic in custom_components/universal_room_automation/
room_dwell_model.py + binary_sensor.OccupancyAnomalyBinarySensor._evaluate.
Keep the I1 copy below in step with them.
"""
from __future__ import annotations

import json
import sqlite3
import statistics
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

URA_DB = "file:/config/universal_room_automation/data/universal_room_automation.db?mode=ro"
HA_DB = "file:/config/home-assistant_v2.db?mode=ro"
STORAGE = "/config/.storage"
DOMAIN = "universal_room_automation"

# Shipped defaults (const.py OCC_ANOMALY_*); the sweep varies the first two.
WINDOW_DAYS = 56
THRESHOLDS = (0.01, 0.02, 0.05)
DEBOUNCES = (0, 300, 900, 1800)
# Learning gate (const.OCC_ANOMALY_MIN_CELL_DAYS / _MIN_CELL_SAMPLES).
MIN_CELL_DAYS = 4
MIN_CELL_SAMPLES = 24
SHIPPED = (0.02, 1800, "48")
STEP_S = 60
# Plan G-thresholds.
G1_MEDIAN_FIRES_PER_DAY = 1.0
G1_MAX_FIRES_PER_ROOM = 4
G2_MAX_NORMAL_USE = 1 / 3
G4_MIN_ROOM_FRACTION = 40 / 46
STUDY_A = "Study A"
GROUND_TRUTH_ROOMS = ("Study A", "Master Bedroom", "Jaya Bedroom", "Living Room")
OJI_TOKEN = "oji"

ARGS = sys.argv[1:]
DAYS = int(ARGS[ARGS.index("--days") + 1]) if "--days" in ARGS else 14
AS_JSON = "--json" in ARGS


def _load(name):
    with open(f"{STORAGE}/{name}") as f:
        return json.load(f)["data"]


def _tz():
    try:
        return ZoneInfo(_load("core.config")["time_zone"])
    except Exception:  # noqa: BLE001
        return ZoneInfo("America/Chicago")


def _rooms():
    """[(entry_id, room_name, occupied_entity_id)] for URA room entries."""
    entries = [e for e in _load("core.config_entries")["entries"]
               if e.get("domain") == DOMAIN
               and (e.get("data") or {}).get("entry_type") == "room"]
    reg = {e["unique_id"]: e["entity_id"]
           for e in _load("core.entity_registry")["entities"]
           if e.get("platform") == DOMAIN}
    out = []
    for e in entries:
        ent = reg.get(f"{e['entry_id']}_occupied")
        out.append((e["entry_id"], e["data"].get("room_name", e["title"]), ent))
    hs = reg.get(f"{DOMAIN}_presence_house_state")
    return out, hs


def day_type(local):
    return "weekend" if local.weekday() >= 5 else "weekday"


def cell(local, model):
    if model == "48":
        return (local.hour, day_type(local))
    return (local.hour, local.weekday())


def train(ura, tz, start_local, end_local):
    """{model: {entry_id: {cell: [occ, n]}}} from [start, end) only."""
    s = start_local.astimezone(timezone.utc).replace(tzinfo=None).isoformat()
    e = end_local.astimezone(timezone.utc).replace(tzinfo=None).isoformat()
    t0 = time.time()
    rows = ura.execute(
        """SELECT room_id, substr(timestamp, 1, 13) AS h,
                  SUM(CASE WHEN occupied THEN 1 ELSE 0 END), COUNT(occupied),
                  MAX(timestamp)
           FROM environmental_data
           WHERE timestamp >= ? AND timestamp < ? AND occupied IS NOT NULL
           GROUP BY room_id, h""", (s, e)).fetchall()
    secs = time.time() - t0
    for r in rows:  # no-hindsight assertion (plan D0 acceptance)
        assert r[4] < e, f"training row {r[4]} not before day start {e}"
    out = {"48": defaultdict(dict), "168": defaultdict(dict)}
    for room, h, occ, n in (r[:4] for r in rows):
        local = datetime.strptime(h, "%Y-%m-%dT%H").replace(
            tzinfo=timezone.utc).astimezone(tz)
        for m in ("48", "168"):
            slot = out[m][room].setdefault(cell(local, m), [0, 0, set()])
            slot[0] += occ or 0
            slot[1] += n or 0
            slot[2].add(local.date())
    return out, secs


def history(ha, entity_id, start_utc, end_utc):
    """[(ts, state)] for the window plus the last state before it."""
    if not entity_id:
        return []
    r = ha.execute("SELECT metadata_id FROM states_meta WHERE entity_id=?",
                   (entity_id,)).fetchone()
    if not r:
        return []
    mid = r[0]
    prev = ha.execute(
        """SELECT last_updated_ts, state FROM states WHERE metadata_id=?
           AND last_updated_ts < ? ORDER BY last_updated_ts DESC LIMIT 1""",
        (mid, start_utc.timestamp())).fetchone()
    rows = ha.execute(
        """SELECT last_updated_ts, state FROM states WHERE metadata_id=?
           AND last_updated_ts >= ? AND last_updated_ts < ?
           ORDER BY last_updated_ts""",
        (mid, start_utc.timestamp(), end_utc.timestamp())).fetchall()
    return ([prev] if prev else []) + rows


def state_at(hist, ts, idx):
    """Advance a cursor through sorted history; return (state, idx)."""
    while idx + 1 < len(hist) and hist[idx + 1][0] <= ts:
        idx += 1
    if not hist or hist[idx][0] > ts:
        return None, idx
    return hist[idx][1], idx


def replay_day(ura, ha, tz, rooms, hs_entity, day_local):
    start = day_local
    end = day_local + timedelta(days=1)
    models, qsecs = train(ura, tz, start - timedelta(days=WINDOW_DAYS), start)
    s_utc, e_utc = start.astimezone(timezone.utc), end.astimezone(timezone.utc)
    hs_hist = history(ha, hs_entity, s_utc, e_utc)
    fires = defaultdict(list)  # (thr, deb, model) -> [(room, local_ts, dur)]
    steps = int((e_utc - s_utc).total_seconds() // STEP_S)
    house = []
    idx = 0
    for k in range(steps):
        st, idx = state_at(hs_hist, s_utc.timestamp() + k * STEP_S, idx)
        house.append(st)
    covered = 0
    for entry_id, name, ent in rooms:
        hist = history(ha, ent, s_utc, e_utc)
        if not hist:
            continue
        covered += 1
        occ_since = None
        idx = 0
        # pre-compute occupied + occupied_for per step
        series = []
        for k in range(steps):
            ts = s_utc.timestamp() + k * STEP_S
            st, idx = state_at(hist, ts, idx)
            on = st == "on"
            if on:
                if occ_since is None:
                    # walk back to the on-edge (bounded by history start)
                    j = idx
                    while j > 0 and hist[j - 1][1] == "on":
                        j -= 1
                    occ_since = hist[j][0]
            else:
                occ_since = None
            series.append((on, ts - occ_since if on else None))
        for m in ("48", "168"):
            room_cells = models[m].get(entry_id, {})
            for thr in THRESHOLDS:
                for deb in DEBOUNCES:
                    was = False
                    run_start = None
                    for k, (on, occ_for) in enumerate(series):
                        ts = s_utc.timestamp() + k * STEP_S
                        local = datetime.fromtimestamp(ts, timezone.utc).astimezone(tz)
                        slot = room_cells.get(cell(local, m))
                        fire = False
                        if (on and slot and slot[1] >= MIN_CELL_SAMPLES
                                and len(slot[2]) >= MIN_CELL_DAYS):
                            share = slot[0] / slot[1]
                            fire = (share < thr and occ_for >= deb
                                    and house[k] != "guest")
                        if fire and not was:
                            run_start = local
                        if was and not fire:
                            fires[(thr, deb, m)].append(
                                (name, run_start, (local - run_start).total_seconds()))
                        was = fire
                    if was:
                        fires[(thr, deb, m)].append(
                            (name, run_start, (end - run_start).total_seconds()))
    return fires, models, qsecs, covered


def producer_health(ura, tz, rooms):
    now = datetime.now(tz)
    since = (now - timedelta(days=70)).astimezone(timezone.utc).replace(
        tzinfo=None).isoformat()
    rows = ura.execute(
        """SELECT room_id, substr(timestamp, 1, 10), COUNT(*),
                  SUM(CASE WHEN occupied IS NULL THEN 1 ELSE 0 END)
           FROM environmental_data WHERE timestamp >= ?
           GROUP BY 1, 2""", (since,)).fetchall()
    per = defaultdict(list)
    nulls = total = 0
    for room, _d, n, nn in rows:
        per[room].append(n)
        total += n
        nulls += nn or 0
    names = {e: n for e, n, _ in rooms}
    med = {names.get(r, r): statistics.median(v) for r, v in per.items()}
    low = sorted(r for r, v in med.items() if v < 200)
    return {"rooms_with_rows": len(med), "median_rows_per_day": med,
            "rooms_under_200_per_day": low,
            "null_share": round(nulls / total, 4) if total else None,
            "writer_broken": len(low) > len(med) / 2}


def visits(ura, since_local, until_local):
    return ura.execute(
        """SELECT person_id, room_id, entry_time, exit_time FROM person_visits
           WHERE entry_time >= ? AND entry_time < ? AND exit_time IS NOT NULL""",
        (str(since_local.replace(tzinfo=None)),
         str(until_local.replace(tzinfo=None)))).fetchall()


def main():
    tz = _tz()
    rooms, hs_entity = _rooms()
    ura = sqlite3.connect(URA_DB, uri=True)
    ha = sqlite3.connect(HA_DB, uri=True)
    report = {"rooms": len(rooms), "days": DAYS}

    report["step1_producer_health"] = producer_health(ura, tz, rooms)

    today = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    all_fires = defaultdict(list)
    qtimes = []
    coverage = {}
    last_models = None
    for d in range(DAYS, 0, -1):
        day = (today - timedelta(days=d))
        day = day.replace(tzinfo=None).replace(tzinfo=tz)  # wall-clock midnight
        fires, models, qsecs, covered = replay_day(
            ura, ha, tz, rooms, hs_entity, day)
        coverage[str(day.date())] = covered
        qtimes.append(qsecs)
        last_models = models
        for k, v in fires.items():
            all_fires[k].extend(v)
    report["dao_query_seconds_max"] = round(max(qtimes), 2) if qtimes else None
    # Recorder coverage: rooms with binary_sensor.<room>_occupied history per
    # replayed day. A day with low coverage cannot fire (reads as quiet).
    report["recorder_rooms_with_history_per_day"] = coverage

    # sweep (G1)
    sweep = []
    for (thr, deb, m) in [(t, b, m) for m in ("48", "168")
                          for t in THRESHOLDS for b in DEBOUNCES]:
        f = all_fires.get((thr, deb, m), [])
        per_day = defaultdict(int)
        per_room = defaultdict(int)
        for name, ts, _dur in f:
            per_day[ts.date()] += 1
            per_room[name] += 1
        days = [per_day.get((today - timedelta(days=d)).date(), 0)
                for d in range(DAYS, 0, -1)]
        # Median over days the recorder actually covers (an uncovered day
        # replays as silent and would drag the median to 0).
        covered_days = [
            n for d, n in zip(range(DAYS, 0, -1), days)
            if coverage.get(str((today - timedelta(days=d)).date()), 0) > 0
        ]
        med = statistics.median(covered_days) if covered_days else None
        # Scale the per-room cap (plan: 4 in 14 days) to the covered span.
        room_cap = G1_MAX_FIRES_PER_ROOM * max(1, len(covered_days)) / 14
        top = max(per_room.values()) if per_room else 0
        sweep.append({
            "model": m, "threshold": thr, "debounce_s": deb,
            "fires_total": len(f),
            "median_fires_per_day_house": med,
            "max_fires_one_room": top,
            "room_cap_scaled": round(room_cap, 1),
            "fires_per_day": days,
            "G1": med is not None and med <= G1_MEDIAN_FIRES_PER_DAY
            and top <= room_cap,
        })
    report["step3_sweep"] = sweep

    # ground truth (step 4) on the latest training window
    names = {e: n for e, n, _ in rooms}
    by_name = {n: e for e, n, _ in rooms}
    since = today - timedelta(days=WINDOW_DAYS)
    vis = visits(ura, since, today)
    dwell = defaultdict(float)  # (room, hour, day_type) -> seconds
    for person, room, a, b in vis:
        try:
            s, e = datetime.fromisoformat(a), datetime.fromisoformat(b)
        except ValueError:
            continue
        if e <= s or (e - s).total_seconds() > 86400:
            continue
        cur = s
        while cur < e:
            nxt = min(e, cur.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1))
            dwell[(room, cur.hour, day_type(cur))] += (nxt - cur).total_seconds()
            cur = nxt
    gt = {}
    for room in GROUND_TRUTH_ROOMS:
        eid = by_name.get(room)
        cells = (last_models or {}).get("48", {}).get(eid, {})
        gt[room] = {
            dt_: {h: {"share": round(cells[(h, dt_)][0] / cells[(h, dt_)][1], 3)
                      if cells.get((h, dt_)) and cells[(h, dt_)][1] else None,
                      "ble_visit_h": round(dwell[(room, h, dt_)] / 3600, 1)}
                  for h in range(24)}
            for dt_ in ("weekday", "weekend")}
    report["step4_share_vs_visits"] = gt
    sa = gt.get(STUDY_A, {}).get("weekday", {})
    sa_day = [sa[h]["share"] for h in range(9, 17) if sa.get(h, {}).get("share") is not None]
    report["discriminator_study_a_weekday_daytime_mean_share"] = (
        round(statistics.mean(sa_day), 3) if sa_day else None)

    # fire sample (step 5) + G2/G3 at the shipped setting
    thr, deb, m = SHIPPED
    shipped = all_fires.get((thr, deb, m), [])
    sample = []
    normal = 0
    g3 = 0
    for name, ts, dur in shipped[:20] if len(shipped) > 20 else shipped:
        lo = (ts - timedelta(minutes=10)).replace(tzinfo=None)
        hi = (ts + timedelta(seconds=dur) + timedelta(minutes=10)).replace(tzinfo=None)
        overlap = sorted({p for p, r, a, b in vis if r == name
                          and datetime.fromisoformat(a) < hi
                          and datetime.fromisoformat(b) > lo})
        judged = "normal_use?" if overlap else "plausible_unusual?"
        normal += bool(overlap)
        sample.append({"room": name, "local": ts.isoformat(), "duration_min":
                       round(dur / 60), "resident_visit_overlap": overlap,
                       "heuristic": judged})
    for name, ts, dur in shipped:
        if name == STUDY_A and ts.weekday() < 5 and 9 <= ts.hour < 17:
            if any(OJI_TOKEN in p.lower() for p, r, a, b in vis if r == STUDY_A
                   and datetime.fromisoformat(a) <= ts.replace(tzinfo=None)
                   <= datetime.fromisoformat(b)):
                g3 += 1
    report["step5_fire_sample_shipped_setting"] = sample

    # G4 on the latest window (48-cell)
    full = 0
    weekday_full = 0
    for eid in names:
        cells = (last_models or {}).get("48", {}).get(eid, {})
        def ok(v):
            return v[1] >= MIN_CELL_SAMPLES and len(v[2]) >= MIN_CELL_DAYS
        if len(cells) == 48 and all(ok(v) for v in cells.values()):
            full += 1
        wd = [v for (h, d), v in cells.items() if d == "weekday"]
        if len(wd) == 24 and all(ok(v) for v in wd):
            weekday_full += 1
    # Max distinct days a weekend cell can have in the window.
    weekend_cap = int(WINDOW_DAYS * 2 / 7)
    shipped_row = next(r for r in sweep if (r["threshold"], r["debounce_s"],
                                             r["model"]) == (thr, deb, m))
    report["gates_shipped_setting"] = {
        "setting": {"threshold": thr, "debounce_s": deb, "model": m},
        "G1_rate": shipped_row["G1"],
        "G2_quality_heuristic": (normal / len(sample) <= G2_MAX_NORMAL_USE)
        if sample else True,
        "G2_note": "heuristic: a resident BLE visit overlapping the fire = "
                   "normal_use?; a human must judge the sample",
        "G3_study_a_daytime_fires": g3, "G3": g3 == 0,
        "G4_rooms_fully_learned": f"{full}/{len(names)}",
        "G4_rooms_weekday_cells_learned": f"{weekday_full}/{len(names)}",
        "weekend_cell_max_days": weekend_cap,
        "weekend_cells_can_learn": weekend_cap >= MIN_CELL_DAYS,
        "G4": (full / len(names) >= G4_MIN_ROOM_FRACTION) if names else False,
    }

    if AS_JSON:
        print(json.dumps(report, default=str, indent=1))
        return
    ph = report["step1_producer_health"]
    print(f"rooms={len(rooms)}  days={DAYS}  dao_query_max_s={report['dao_query_seconds_max']}")
    print(f"STEP1 producer: rooms_with_rows={ph['rooms_with_rows']} "
          f"null_share={ph['null_share']} under200={ph['rooms_under_200_per_day']} "
          f"writer_broken={ph['writer_broken']}")
    print("recorder rooms with occupied history per day:",
          report["recorder_rooms_with_history_per_day"])
    print("STEP3 sweep (model thr deb | fires median/day maxroom G1 | per day)")
    for r in sweep:
        print(f"  {r['model']:>3} {r['threshold']:.2f} {r['debounce_s']:>4} | "
              f"{r['fires_total']:>4} {str(r['median_fires_per_day_house']):>5} "
              f"{r['max_fires_one_room']:>3} {r['G1']} | {r['fires_per_day']}")
    print("DISCRIMINATOR Study A weekday 09-17 mean share:",
          report["discriminator_study_a_weekday_daytime_mean_share"],
          "(dwell model > 0.2; arrival-shaped < 0.05)")
    print("STEP4 share vs BLE visit hours (weekday):")
    for room, v in gt.items():
        row = " ".join(f"{h:02d}:{(v['weekday'][h]['share'] or 0):.2f}/"
                       f"{v['weekday'][h]['ble_visit_h']}" for h in range(24))
        print(f"  {room}: {row}")
    print("STEP5 fire sample at shipped setting:")
    for s in sample:
        print("  ", s)
    print("GATES:", json.dumps(report["gates_shipped_setting"]))


if __name__ == "__main__":
    main()
