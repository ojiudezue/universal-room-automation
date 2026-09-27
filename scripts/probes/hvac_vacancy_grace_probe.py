#!/usr/bin/env python3
"""HVAC vacancy-grace sizing probe — READ-ONLY. Operator question 2026-09-26: shorten vacancy grace now that entry is faster?
    ssh ha "python3 - [--days 7]" < scripts/probes/hvac_vacancy_grace_probe.py
Signal: sensor.ura_hvac_coordinator_zone_N_status attribute any_room_hvac_occupied (the fused HVAC occupancy the
retreat grace is measured against; tail holds are already inside it). A VACANCY GAP = True->False->True.
For candidate grace G: gaps > G cause a retreat; a retreat whose gap ended within R minutes of the retreat is a
"return flap" (away write, then home write shortly after). Conditioning-minutes saved vs 15 = sum over gaps of
(min(d,15) - min(d,G)) for d > G ... reported as avoided conditioned-empty minutes. Excludes house-empty (from
2026-09-26 19:20Z) and HA restart windows (+15 min).
"""
import sqlite3,json,sys,time,collections
a=sys.argv[1:]; DAYS=int(a[a.index('--days')+1]) if '--days' in a else 7
r=sqlite3.connect('file:/config/home-assistant_v2.db?mode=ro',uri=True)
now=time.time(); t0=now-DAYS*86400; EMPTY=time.mktime(time.strptime('2026-09-26T19:20','%Y-%m-%dT%H:%M'))-time.timezone
rs=[t for (t,) in r.execute("SELECT time_fired_ts FROM events WHERE event_type_id=(SELECT event_type_id FROM event_types WHERE event_type='homeassistant_start') AND time_fired_ts>=?",(t0,))]
def bad(t): return t>=EMPTY or any(x-60<=t<=x+900 for x in rs)
G=[2,5,8,10,15]; R=10
for z in (1,2,3):
    e=f"sensor.ura_hvac_coordinator_zone_{z}_status"
    m=r.execute("SELECT metadata_id FROM states_meta WHERE entity_id=?",(e,)).fetchone()
    if not m: print(e,'missing'); continue
    seq=[]
    for ts,sa in r.execute("SELECT s.last_updated_ts,a.shared_attrs FROM states s LEFT JOIN state_attributes a ON s.attributes_id=a.attributes_id WHERE s.metadata_id=? AND s.last_updated_ts>=? ORDER BY 1",(m[0],t0)):
        if not sa: continue
        v=json.loads(sa).get('any_room_hvac_occupied')
        if v is None: continue
        if not seq or seq[-1][1]!=v: seq.append((ts,v))
    gaps=[]
    for i in range(1,len(seq)-1):
        if seq[i-1][1] is True and seq[i][1] is False and seq[i+1][1] is True:
            s,e2=seq[i][0],seq[i+1][0]
            if bad(s) or bad(e2): continue
            gaps.append((e2-s)/60)
    gaps.sort()
    q=lambda p: round(gaps[int(p*(len(gaps)-1))],1) if gaps else None
    print(f"== zone_{z}: vacancy gaps n={len(gaps)} over {DAYS}d  p25={q(.25)} p50={q(.5)} p75={q(.75)} p90={q(.9)} min")
    for g in G:
        retreats=[d for d in gaps if d>g]; flaps=[d for d in retreats if d-g<=R]
        saved=sum(min(d,15)-min(d,g) for d in gaps)
        print(f"   grace {g:>2} min: retreats {len(retreats):>3}  return-flaps(<= {R} min after retreat) {len(flaps):>3}  conditioned-empty minutes saved vs 15: {round(saved)}")
