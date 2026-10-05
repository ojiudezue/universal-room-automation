"""P-D2 resident attribution gap 2026-10-03 (PLANNING_census_inputs_first.md §2). READ-ONLY.
Run: ssh ha "python3 -" < p_d2_attribution.py
"""
import sqlite3, datetime as dt, json
from collections import Counter, defaultdict
r = sqlite3.connect('file:/config/home-assistant_v2.db?mode=ro', uri=True)
u = sqlite3.connect('file:/config/universal_room_automation/data/universal_room_automation.db?mode=ro', uri=True)
CDT = -5 * 3600
A = dt.datetime(2026, 10, 3, 5, tzinfo=dt.timezone.utc).timestamp(); B = A + 86400
def loc(ts): return dt.datetime.fromtimestamp(ts + CDT, dt.timezone.utc).strftime('%H:%M:%S')
def hist(eid, attrs=False, a=A, b=B):
    q = ("select s.state,s.last_updated_ts" + (",sa.shared_attrs" if attrs else "") +
         " from states s join states_meta m using(metadata_id)" +
         (" left join state_attributes sa on s.attributes_id=sa.attributes_id" if attrs else "") +
         " where m.entity_id=? and s.last_updated_ts between ? and ? order by 2")
    return r.execute(q, (eid, a, b)).fetchall()

# 1. person_id attach per hour (CDT)
print("1. ledger rows per CDT hour: total / resident person_id / by source confidence")
per = defaultdict(Counter)
for ts, pid, conf in u.execute("select timestamp,person_id,confidence from person_entry_exit_events where timestamp between ? and ?",
                               ('2026-10-03T05:00', '2026-10-04T05:00')):
    t = dt.datetime.fromisoformat(ts).replace(tzinfo=dt.timezone.utc).timestamp()
    h = int((t - A) // 3600); per[h]['n'] += 1
    if pid: per[h]['pid'] += 1; per[h][f'c{conf}'] += 1
for h in sorted(per): print(f"  {h:02d}h", dict(per[h]))
print("  confidence of attributed rows overall:",
      Counter(c for (c,) in u.execute("select confidence from person_entry_exit_events where person_id is not null and timestamp between ? and ?",
                                       ('2026-10-03T05:00', '2026-10-04T05:00'))))

# 2. every resident tracker incl GPS, all state changes 10-03 (state + source_type)
P = json.load(open('/config/.storage/person'))['data']['items']
print("\n2. resident tracker state sequences 10-03 (CDT; only state changes)")
for p in P:
    if p['id'] not in ('oji_udezue', 'jaya', 'ezinne'): continue
    for e in ['person.' + p['id']] + p.get('device_trackers', []):
        seq, prev, src = [], None, None
        for st, t, at in hist(e, True):
            if st != prev:
                seq.append(f"{loc(t)}={st}"); prev = st
            try: src = json.loads(at or '{}').get('source_type', src)
            except Exception: pass
        print(f"  {e} [src={src}] n={len(seq)}: {seq[:14]}{' ...' if len(seq) > 14 else ''}")

# 3. backfill / attach counters on the census sensor (attribute snapshot near day end)
print("\n3. census producer counters (attr snapshot)")
ids = [m for (m,) in r.execute("select entity_id from states_meta where entity_id like 'sensor.%' and (entity_id like '%census%' or entity_id like '%persons_in_house%' or entity_id like '%identity%')")]
for e in ids:
    rows = hist(e, True, B - 3600, B)
    if not rows: rows = hist(e, True, A, B)[-1:]
    if not rows: continue
    try: at = json.loads(rows[-1][2] or '{}')
    except Exception: continue
    ks = {k: v for k, v in at.items() if any(s in k for s in ('ble_', 'backfill', 'attach', 'edge_no_match', 'face_producer'))}
    if ks: print(f"  {e} @ {loc(rows[-1][1])}: {ks}")

# 4. Path alpha: any per-room/area BLE signal for the operator's phone (distinct from home/away)
print("\n4. Path-alpha candidates (operator area/room signals with changes 11:30-13:45)")
a, b = A + 11.5 * 3600, A + 13.75 * 3600
for (e,) in r.execute("select entity_id from states_meta where (entity_id like '%oji%' or entity_id like '%phalanx%' or entity_id like '%8ce182%') "
                      "and (entity_id like 'sensor.%' or entity_id like 'device_tracker.%')"):
    rows = hist(e, False, a, b)
    vals = Counter(s for s, _ in rows)
    if len(rows) >= 2 and len(vals) >= 2 and any(x in e for x in ('area', 'room', 'distance', 'bermuda', 'nearest', 'location')):
        print(f"  {e}: n={len(rows)} {dict(vals.most_common(6))}")
        for s, t in rows[:25]: print(f"     {loc(t)} {s}")

# 5. Path-alpha test: Bermuda area of each resident at each midday FRONT ledger crossing
print("\n5. Bermuda area at midday front-door ledger rows (±60 s window, CDT)")
import bisect
AREAS = {w: hist(f'sensor.iphone_{w}_area', False, A, B) for w in ('oji', 'jaya', 'ezinne')}
for w in list(AREAS):
    if not AREAS[w]:
        alt = [m for (m,) in r.execute("select entity_id from states_meta where entity_id like ? and entity_id like '%_area'", (f'%{w}%',))]
        print("  alt area entities for", w, alt[:5])
def area_near(w, t):
    rows = AREAS.get(w) or []
    ts = [x[1] for x in rows]; i = bisect.bisect_right(ts, t) - 1
    seen = set(s for s, x in rows if t - 60 <= x <= t + 60)
    return (rows[i][0] if i >= 0 else None), sorted(seen)
for ts, pid, d, cam in u.execute("select timestamp,person_id,direction,egress_camera from person_entry_exit_events where timestamp between ? and ? order by 1",
                                 ('2026-10-03T16:30', '2026-10-03T18:45')):
    t = dt.datetime.fromisoformat(ts).replace(tzinfo=dt.timezone.utc).timestamp()
    if 'front_door' not in cam and 'madrone_g6' not in cam: continue
    print(f"  {loc(t)} {d:5s} pid={pid or '-':10s} " + " | ".join(f"{w}:{area_near(w, t)}" for w in AREAS))
