#!/usr/bin/env python3
"""D0 for PLANNING_hvac_night_tail_follows_sleep.md — READ-ONLY.
    ssh ha "python3 -" < scripts/probes/hvac_home_night_bedroom_exposure_probe.py
Counts room-occupancy gaps (on->off->on) that START between 21:00 and 22:00 local and last
60 s..30 min (media 120 s..30 min) for bedroom + media rooms, over recorder retention.
These are the gaps today's 30-min night hold absorbs and B (night holds only in sleep/waking)
would expose. Room list = URA room entries of type bedroom/media_room (read from config entries).
"""
import sqlite3, json, datetime as dt, collections, re
CDT = dt.timezone(dt.timedelta(hours=-5))
cfg = json.load(open('/config/.storage/core.config_entries'))
rooms = []
for e in cfg['data']['entries']:
    if e['domain'] != 'universal_room_automation': continue
    o = {**e.get('data', {}), **e.get('options', {})}
    if o.get('room_type') in ('bedroom', 'media_room'):
        rooms.append((e['title'], o['room_type']))
r = sqlite3.connect('file:/config/home-assistant_v2.db?mode=ro', uri=True)
ents = {x[0] for x in r.execute("select entity_id from states_meta where entity_id like 'binary_sensor.%_occupied'")}
def slug(t): return re.sub(r'[^a-z0-9]+', '_', t.lower()).strip('_')
ALIAS = {'Upstairs Guestroom': 'binary_sensor.upstairs_guest_bedroom_occupied', 'Media': 'binary_sensor.media_room_occupied'}
oldest = r.execute("select min(last_updated_ts) from states").fetchone()[0]
days = (dt.datetime.now().timestamp() - oldest) / 86400
print(f'recorder span {days:.1f} days')
for title, rt in rooms:
    ent = ALIAS.get(title) or f'binary_sensor.{slug(title)}_occupied'
    if ent not in ents:
        cand = [x for x in ents if slug(title).split('_')[0] in x and x.endswith('_occupied') and 'hvac' not in x]
        print(f'{title:32s} {rt:10s} entity not found; candidates {cand[:3]}'); continue
    rows = r.execute("select s.state,s.last_updated_ts from states s join states_meta m on s.metadata_id=m.metadata_id where m.entity_id=? order by 2", (ent,)).fetchall()
    lo = 120 if rt == 'media_room' else 60
    prev, off_at, gaps, nights = None, None, [], set()
    for s, t in rows:
        if s == 'off' and prev == 'on': off_at = t
        elif s == 'on' and prev == 'off' and off_at:
            dur = t - off_at; h = dt.datetime.fromtimestamp(off_at, CDT)
            if h.hour == 21 and lo <= dur <= 1800:
                gaps.append((h.strftime('%m-%d %H:%M'), round(dur / 60, 1))); nights.add(h.date())
            off_at = None
        if s in ('on', 'off'): prev = s
    rate = len(gaps) / days * 7 if days else 0
    print(f'{title:32s} {rt:10s} exposed gaps {len(gaps):3d} (~{rate:.1f}/week) on {len(nights)} nights {gaps[:6]}')
