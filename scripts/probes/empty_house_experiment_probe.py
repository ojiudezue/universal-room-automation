#!/usr/bin/env python3
"""Empty-house natural experiment probe — READ-ONLY.
Card: NATURAL-EXPERIMENT-EMPTY-HOUSE-2026-09-26. Window: house empty from 2026-09-26 14:20 CDT until the
first person.* -> home that lasts > 60 s (zero-second flickers are NOT a return; they are item 8).
    ssh ha "python3 - [START_EPOCH] [END_EPOCH]" < scripts/probes/empty_house_experiment_probe.py
START defaults to 14:35 CDT (window start + the pre-registered 15-min settle); END defaults to the first
real return minus 30 min, else now. Anything URA attributes to a person inside the window is a false
positive (pets: unknown confound).

TIMESTAMP FORMATS (verified 2026-09-27, they differ per table — do not unify by assumption):
  ura_activity_log / census_snapshots / notification_log : ISO with +00:00 (UTC)
  occupancy_events / house_state_log / energy_history     : naive ISO, UTC
  HA recorder                                             : epoch seconds
Pre-registered items (card `preregistered`): 1 room occupancy by source, 2 census/guest, 3 override /
manual on any zone, 4 zone presets + re-issued away writes, 5 URA actuation, 6 perimeter alerts,
7 hourly whole-house energy. Item 8 (not pre-registered, flagged as such): person-entity flickers.
"""
import sqlite3, sys, time, json, collections, datetime as dt

UTC = dt.timezone.utc
CDT = dt.timezone(dt.timedelta(hours=-5))
WIN_START = dt.datetime(2026, 9, 26, 14, 20, tzinfo=CDT).timestamp()
FLICKER_S = 60  # a person 'home' shorter than this is a flicker, not a return

r = sqlite3.connect('file:/config/home-assistant_v2.db?mode=ro', uri=True)
u = sqlite3.connect('file:/config/universal_room_automation/data/universal_room_automation.db?mode=ro', uri=True)


def hist(ent, t0):
    return [(s, t) for s, t in r.execute(
        "SELECT s.state, s.last_updated_ts FROM states s JOIN states_meta m ON s.metadata_id=m.metadata_id "
        "WHERE m.entity_id=? AND s.last_updated_ts>? ORDER BY 2", (ent, t0))]


def changes(rows):
    out, prev = [], object()
    for s, t in rows:
        if s != prev:
            out.append((s, t)); prev = s
    return out


# ---- window end: first person home lasting > FLICKER_S ----------------------------------------
persons = [e for (e,) in r.execute("SELECT entity_id FROM states_meta WHERE entity_id LIKE 'person.%'")]
flickers, first_return = [], None
for p in persons:
    ch = changes(hist(p, WIN_START))
    for i, (s, t) in enumerate(ch):
        if s != 'home':
            continue
        t_end = ch[i + 1][1] if i + 1 < len(ch) else time.time()
        if t_end - t < FLICKER_S:
            flickers.append((t, p, t_end - t))
        elif first_return is None or t < first_return[0]:
            first_return = (t, p)

a = sys.argv[1:]
START = float(a[0]) if a else WIN_START + 15 * 60
if len(a) > 1:
    END = float(a[1])
elif first_return:
    END = first_return[0] - 30 * 60
else:
    END = time.time()


def fmt(t):
    return dt.datetime.fromtimestamp(t, CDT).strftime('%m-%d %H:%M:%S')


def iso_utc(t):
    return dt.datetime.fromtimestamp(t, UTC).strftime('%Y-%m-%dT%H:%M:%S')


def parse(ts):
    ts = ts.replace('+00:00', '')[:19]
    return dt.datetime.strptime(ts, '%Y-%m-%dT%H:%M:%S').replace(tzinfo=UTC).timestamp()


S, E = iso_utc(START), iso_utc(END)
print(f"WINDOW {fmt(START)} -> {fmt(END)} CDT ({(END-START)/3600:.1f} h)  "
      f"{'[INTERIM: nobody has returned yet]' if not first_return else f'[first return {fmt(first_return[0])} {first_return[1]}]'}")

# ---- 1. room occupancy (URA occupancy_events) --------------------------------------------------
print("\n== 1. ROOM OCCUPANCY ENTRIES (URA occupancy_events) — each is a phantom")
names = {}
for eid, title in r.execute("SELECT 1,1").fetchall()[:0]:
    pass
try:
    import json as _j
    for e in _j.load(open('/config/.storage/core.config_entries'))['data']['entries']:
        if e['domain'] == 'universal_room_automation':
            names[e['entry_id']] = e['title']
except Exception:
    pass
occ = collections.Counter(); src = collections.defaultdict(collections.Counter)
for rid, ts, et, ts_src in u.execute(
        "SELECT room_id,timestamp,event_type,trigger_source FROM occupancy_events WHERE timestamp>=? AND timestamp<?", (S, E)):
    if et == 'entry':
        n = names.get(rid, rid); occ[n] += 1; src[n][ts_src or '?'] += 1
print(f"  total entries {sum(occ.values())} across {len(occ)} rooms")
for n, c in occ.most_common():
    print(f"   {c:4d}  {n:28s} by source {dict(src[n])}")

# ---- 2. census / guest --------------------------------------------------------------------------
print("\n== 2. CENSUS / GUEST")
for z, n, mx_t, mx_u in u.execute(
        "SELECT zone, count(*), max(total_persons), max(unidentified_count) FROM census_snapshots "
        "WHERE timestamp>=? AND timestamp<? GROUP BY zone", (S, E)):
    nz = u.execute("SELECT count(*) FROM census_snapshots WHERE zone=? AND timestamp>=? AND timestamp<? AND total_persons>0",
                   (z, S, E)).fetchone()[0]
    print(f"  zone {z:9s} snapshots {n:5d}  max total {mx_t}  max unidentified {mx_u}  snapshots with total>0: {nz}")
hs = u.execute("SELECT timestamp,state,trigger,previous_state FROM house_state_log WHERE timestamp>=? AND timestamp<? ORDER BY id",
               (S, E)).fetchall()
print(f"  house_state_log transitions in window: {len(hs)}")
for ts, st, trig, prev in hs:
    print(f"     {fmt(parse(ts))}  {prev} -> {st}  ({trig})")

# ---- 3/4. HVAC: overrides, manual, presets ------------------------------------------------------
print("\n== 3. OVERRIDE / MANUAL (cannot be human in an empty house)")
acts = collections.Counter(a for (a,) in u.execute(
    "SELECT action FROM ura_activity_log WHERE timestamp>=? AND timestamp<?", (S, E)))
ov = [(ts, z, d) for ts, z, d in u.execute(
    "SELECT timestamp,zone,description FROM ura_activity_log WHERE timestamp>=? AND timestamp<? AND "
    "(action LIKE '%override%' OR action LIKE '%manual%' OR description LIKE '%override%' OR description LIKE '%manual%')", (S, E))]
print(f"  activity rows mentioning override/manual: {len(ov)}")
for ts, z, d in ov[:15]:
    print(f"     {fmt(parse(ts))} {z}: {d[:140]}")
print("\n== 4. ZONE PRESET WRITES (URA preset_change)")
pc = collections.defaultdict(collections.Counter); first_last = {}
for ts, z, dj in u.execute(
        "SELECT timestamp,zone,details_json FROM ura_activity_log WHERE action='preset_change' AND timestamp>=? AND timestamp<?", (S, E)):
    d = json.loads(dj or '{}')
    pc[z][str(d.get('new_preset') or d.get('preset_mode') or d.get('to'))] += 1
for z in sorted(pc):
    hrs = (END - START) / 3600
    print(f"  {z}: {dict(pc[z])}  ({sum(pc[z].values())/hrs:.1f} writes/h)")
cw = collections.Counter(z for (z,) in u.execute(
    "SELECT zone FROM ura_activity_log WHERE action='climate_write' AND timestamp>=? AND timestamp<?", (S, E)))
print(f"  climate_write rows by zone: {dict(cw)}")
for z in ('zone_1', 'zone_2', 'zone_3'):
    ent = f'climate.{z}' if False else None
pa = [(ts, d) for ts, d in u.execute(
    "SELECT timestamp,description FROM ura_activity_log WHERE action='pre_arrival' AND timestamp>=? AND timestamp<?", (S, E))]
print(f"  pre_arrival events: {len(pa)}")
for ts, d in pa:
    print(f"     {fmt(parse(ts))} {d[:140]}")

# ---- 5. URA actuation ---------------------------------------------------------------------------
print("\n== 5. URA ACTUATION / ACTIVITY BY ACTION (window)")
for k, v in acts.most_common(30):
    print(f"   {v:5d}  {k}")
oc = [(ts, room, d) for ts, room, d in u.execute(
    "SELECT timestamp,room,description FROM ura_activity_log WHERE action IN ('occupancy_entry','occupancy_exit') AND timestamp>=? AND timestamp<?", (S, E))]
for ts, room, d in oc:
    print(f"     {fmt(parse(ts))} {room}: {d[:120]}")

# ---- 6. notifications / perimeter ---------------------------------------------------------------
print("\n== 6. NOTIFICATIONS (notification_log) by coordinator / severity / title")
nl = collections.Counter((c, sv, t[:70]) for c, sv, t in u.execute(
    "SELECT coordinator_id,severity,title FROM notification_log WHERE timestamp>=? AND timestamp<?", (S, E)))
for (c, sv, t), n in nl.most_common(25):
    print(f"   {n:4d}  {c:14s} {sv:8s} {t}")

# ---- 7. energy baseload -------------------------------------------------------------------------
print("\n== 7. EMPTY-HOUSE LOAD (energy_history rows in window: rooms_occupied, grid_import)")
eh = u.execute("SELECT timestamp,rooms_occupied,whole_house_energy,grid_import,tou_period FROM energy_history "
               "WHERE timestamp>=? AND timestamp<? ORDER BY timestamp", (S, E)).fetchall()
ro = collections.Counter(x[1] for x in eh)
print(f"  energy_history rows {len(eh)}; rooms_occupied distribution {dict(sorted(ro.items(), key=lambda kv: (kv[0] is None, kv[0])))}")
print("  (whole-house kWh left for the final run: energy_history whole_house_energy is NULL in recent rows — use SPAN/Emporia recorder series)")

# ---- 8. person flickers (NOT pre-registered) ----------------------------------------------------
print(f"\n== 8. PERSON 'home' FLICKERS < {FLICKER_S}s since window start (not pre-registered; found 2026-09-27)")
for t, p, d in sorted(flickers):
    print(f"     {fmt(t)} {p} home for {d:.1f}s")
