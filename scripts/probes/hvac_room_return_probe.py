#!/usr/bin/env python3
"""HVAC room drop-and-return probe (all rooms, all hours) — READ-ONLY.
Card: HVAC-HOLD-SIZING-ALL-ROOMS-1. Generalises hvac_night_sleeper_probe.py (bedrooms/night only).
    ssh ha "python3 - [--days 7] [--ret 30]" < scripts/probes/hvac_room_return_probe.py
For each room's binary_sensor.*_hvac_occupied: episodes on->off followed by on within --ret minutes
(RETURNED = person likely never left). HARM = URA wrote preset away to that room's zone (ura_activity_log
action=preset_change, new preset away) inside the gap. Buckets by local hour of the drop:
day 08-18, evening 18-22, night 22-08 (America/Chicago, CDT=UTC-5).
Zone map pinned from sensor.ura_hvac_coordinator_zone_N_status live_rooms (2026-09-26).
"""
import sqlite3,sys,time,json,collections
a=sys.argv[1:]
DAYS=int(a[a.index('--days')+1]) if '--days' in a else 7
RET=int(a[a.index('--ret')+1]) if '--ret' in a else 30
Z={'zone_1':['living_room','receiving_room','foyer','study_a','study_b','master_bedroom','av_closet','master_bathroom','oji_vanity','master_toilet','master_hallway'],
   'zone_2':['guest_bedroom_2','guest_bedroom_hallway','media_room','exercise_room','ziri','jaya','game_room','upstairs_hallway'],
   'zone_3':['guest_bedroom_1','stair_closet','laundry','kitchen','breakfast','dining','garage_hallway','pantry','butler']}
def zone_of(e):
    for z,keys in Z.items():
        if any(e.startswith('binary_sensor.'+k) for k in keys): return z
    return None
now=time.time(); t0=now-DAYS*86400
r=sqlite3.connect('file:/config/home-assistant_v2.db?mode=ro',uri=True)
u=sqlite3.connect('file:/config/universal_room_automation/data/universal_room_automation.db?mode=ro',uri=True)
aways=collections.defaultdict(list)
for ts,zone,dj in u.execute("SELECT timestamp,zone,details_json FROM ura_activity_log WHERE action='preset_change' AND timestamp>=?",(time.strftime('%Y-%m-%dT%H:%M:%S',time.gmtime(t0)),)):
    d=json.loads(dj or '{}')
    if str(d.get('new_preset') or d.get('preset_mode') or d.get('to'))=='away':
        aways[zone].append(time.mktime(time.strptime(ts[:19],'%Y-%m-%dT%H:%M:%S'))-time.timezone)
meta={e:m for m,e in r.execute("SELECT metadata_id,entity_id FROM states_meta WHERE entity_id LIKE 'binary_sensor.%hvac_occupied'")}
def bucket(ts):
    h=time.gmtime(ts-5*3600).tm_hour
    return 'day' if 8<=h<18 else ('evening' if 18<=h<22 else 'night')
rows=[]
for e,m in sorted(meta.items()):
    z=zone_of(e)
    if not z: continue
    st=[(s,t) for s,t in r.execute("SELECT state,last_updated_ts FROM states WHERE metadata_id=? AND last_updated_ts>=? ORDER BY last_updated_ts",(m,t0)) if s in('on','off')]
    c=collections.Counter(); harm=collections.Counter(); gaps=[]
    for i in range(1,len(st)):
        if st[i-1][0]=='on' and st[i][0]=='off':
            nxt=next(((s,t) for s,t in st[i+1:] if s=='on'),None)
            if nxt and nxt[1]-st[i][1]<=RET*60:
                b=bucket(st[i][1]); c[b]+=1; gaps.append((nxt[1]-st[i][1])/60)
                if any(st[i][1]<=x<=nxt[1] for x in aways[z]): harm[b]+=1
    if c: rows.append((sum(harm.values()),e.replace('binary_sensor.','').replace('_hvac_occupied',''),z,dict(c),dict(harm),round(sorted(gaps)[len(gaps)//2],1)))
print(f"# room drop->return<= {RET}min over {DAYS}d; HARM = URA wrote zone away inside the gap")
print("harm_total|room|zone|returned_by_bucket|harm_by_bucket|median_gap_min")
for x in sorted(rows,reverse=True): print('|'.join(map(str,x)))
