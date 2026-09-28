#!/usr/bin/env python3
"""D0 for PLANNING_hvac_reloading_room_placeholder_readers.md — READ-ONLY.
    ssh ha "python3 -" < scripts/probes/hvac_reloading_room_probe.py
P0 restarts; P1 ticks that saw a transient/absent room (boot vs live); P3 restart wipes the zone
occupancy clock; P4 D5/D6 exposure in ura_activity_log. (P2 room-unavailable proxy omitted: P1 is the
direct signal since v5.103.15.)"""
import sqlite3, json, datetime as dt, collections
CDT = dt.timezone(dt.timedelta(hours=-5))
f = lambda t: dt.datetime.fromtimestamp(t, CDT).strftime('%m-%d %H:%M:%S')
r = sqlite3.connect('file:/config/home-assistant_v2.db?mode=ro', uri=True)
u = sqlite3.connect('file:/config/universal_room_automation/data/universal_room_automation.db?mode=ro', uri=True)
starts = [t for (t,) in r.execute("select e.time_fired_ts from events e join event_types et on e.event_type_id=et.event_type_id where et.event_type='homeassistant_start' order by 1")]
span = (dt.datetime.now().timestamp() - r.execute("select min(last_updated_ts) from states").fetchone()[0]) / 86400
print(f'P0 restarts in {span:.1f} d: {len(starts)} ->', [f(t) for t in starts])
def near_boot(t): return any(s - 60 <= t <= s + 900 for s in starts)
def attrs(ent):
    return r.execute("select s.state, s.last_updated_ts, sa.shared_attrs from states s join states_meta m on s.metadata_id=m.metadata_id left join state_attributes sa on s.attributes_id=sa.attributes_id where m.entity_id=? order by 2", (ent,)).fetchall()
zones = [x[0] for x in r.execute("select entity_id from states_meta where entity_id like 'sensor.ura_hvac%zone%status%' or entity_id like 'sensor.ura_hvac_coordinator_zone_%_status'")]
print('zone status entities:', zones)
boot = live = 0; live_ex = []
series = {}
for z in zones:
    rows = attrs(z); series[z] = rows
    for s, t, a in rows:
        try: a = json.loads(a or '{}')
        except Exception: continue
        if a.get('transient_rooms') or a.get('coordinator_absent_rooms'):
            if near_boot(t): boot += 1
            else:
                live += 1
                if len(live_ex) < 5: live_ex.append((z, f(t), a.get('transient_rooms'), a.get('coordinator_absent_rooms')))
print(f'P1 status samples with transient/absent rooms: boot={boot} live={live}', live_ex)
# P3
keys = None
for z, rows in series.items():
    for s, t, a in rows[-5:]:
        try: keys = sorted(json.loads(a or '{}').keys())
        except Exception: pass
    break
print('P3 status attr keys sample:', [k for k in (keys or []) if 'occup' in k or 'continuous' in k])
reset = across = 0; det = []
for z, rows in series.items():
    parsed = []
    for s, t, a in rows:
        try: parsed.append((t, json.loads(a or '{}')))
        except Exception: pass
    for st in starts:
        before = [x for x in parsed if x[0] < st - 5]
        after = [x for x in parsed if x[0] > st + 5]
        if not before or not after: continue
        b, a = before[-1][1], after[0][1]
        bh, ah = b.get('continuous_occupied_hours'), a.get('continuous_occupied_hours')
        bo, ao = b.get('any_room_hvac_occupied'), a.get('any_room_hvac_occupied')
        if bo and ao:
            across += 1
            if (bh or 0) > 0 and (ah or 0) == 0:
                reset += 1; det.append((z, f(st), bh, ah))
print(f'P3 BOOT-RESET {reset}/{across} occupied-across-restart', det[:6])
# P4
since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=14)).isoformat()
c = collections.Counter()
for act, dj in u.execute("select action, details_json from ura_activity_log where coordinator='hvac' and timestamp>=? and action in ('preset_change','preset_change_suppressed')", (since,)):
    try: d = json.loads(dj or '{}')
    except Exception: continue
    rs = d.get('reason')
    if rs in ('energy_shed_cap_reached', 'stale_occupancy', 'energy_shed_cap_deferred_occupied', 'transient_room_hold'):
        c[(act, rs, d.get('constraint_mode'))] += 1
print('P4 (14 d):', dict(c))
