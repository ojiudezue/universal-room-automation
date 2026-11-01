import json,sqlite3,sys
ents=json.load(open('/config/.storage/core.config_entries'))['data']['entries']
rooms={}
for e in ents:
    if e['domain']!='universal_room_automation': continue
    o={**e['data'],**e['options']}
    nm=o.get('room_name') or e['title']
    if 'lights' in o or 'fans' in o or 'night_lights' in o:
        rooms[nm]=o
        rooms[e['title']]=o
db=sqlite3.connect('file:/config/home-assistant_v2.db?mode=ro',uri=True)
q=db.cursor()
def mid(e):
    r=q.execute("select metadata_id from states_meta where entity_id=?",(e,)).fetchone(); return r[0] if r else None
fires=[]
for z in (1,2,3):
    m=mid(f'sensor.ura_hvac_coordinator_zone_{z}_status')
    rows=q.execute("select s.last_updated_ts,json_extract(a.shared_attrs,'$.vacancy_sweep_done'),json_extract(a.shared_attrs,'$.live_rooms') from states s join state_attributes a using(attributes_id) where metadata_id=? order by 1",(m,)).fetchall()
    pd=None;live=None
    for ts,d,lr in rows:
        if lr: live=json.loads(lr)
        if d==1 and pd==0: fires.append((z,ts,live))
        pd=d
paused=set()
# swept set
def swept(live):
    s=set()
    for r in live or []:
        o=rooms.get(r)
        if not o: continue
        L=set(o.get('lights',[]) or [])|set(o.get('night_lights',[]) or [])
        L-=set(o.get('lights_leave_on_when_empty',[]) or [])
        s|=L
        if o.get('room_fan_mode')=='follow_thermostat' or (o.get('room_fan_mode') is None and o.get('hvac_coordination_enabled')):
            s|=set(o.get('fans',[]) or [])
    return s
cache={}
def st(ent,t0,t1):
    m=cache.get(ent) or mid(ent); cache[ent]=m
    if m is None: return None,[]
    before=q.execute("select state from states where metadata_id=? and last_updated_ts<=? order by last_updated_ts desc limit 1",(m,t0)).fetchone()
    tr=q.execute("select last_updated_ts,state,context_parent_id_bin is not null from states where metadata_id=? and last_updated_ts>? and last_updated_ts<=? order by 1",(m,t0,t1)).fetchall()
    return (before[0] if before else None),tr
out=[];noop=0;on=0;off=0
for z,ts,live in fires:
    sw=swept(live)
    any_on=[];offs=[]
    for e in sw:
        b,tr=st(e,ts-3,ts+15)
        if b=='on': any_on.append(e)
        for t,s,ctx in tr:
            if s=='off' and b=='on': offs.append((e,round(t-ts,1),bool(ctx)))
    out.append((z,ts,len(sw),any_on,offs))
print("fires",len(out),"swept_sizes",sorted({(z,n) for z,_,n,_,_ in out}))
print("fires with >=1 swept ON at T-3:",sum(1 for o in out if o[3]))
print("fires with ON->OFF within +15s (any ctx):",sum(1 for o in out if o[4]))
print("fires with URA-ctx OFF:",sum(1 for o in out if any(x[2] for x in o[4])))
import csv
w=csv.writer(sys.stdout)
for o in out:
    if o[3]: print("FIRE",o[0],__import__('datetime').datetime.fromtimestamp(o[1]).isoformat(),"on:",o[3],"offs:",o[4])
