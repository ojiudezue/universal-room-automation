#!/usr/bin/env python3
"""Carrier feed-truth probe — READ-ONLY. Which feed does the PHYSICAL thermostat follow?
    ssh ha "python3 - [--days 7]" < scripts/probes/carrier_feed_truth_probe.py
For each Bryant zone climate entity: find intervals where STATUS preset_mode != CONFIG hold_activity.
Profile table per zone: target_temp_high per activity, learned from rows where the two feeds AGREE.
Discriminating sub-intervals: current_temperature T strictly between the two feeds' cooling setpoints
(status_high vs hold_high), in cool/heat_cool. Physical evidence = blower_rpm:
  follows HOLD   : T >= lower_setpoint + 1 and the side with the LOWER setpoint predicts cooling, but blower==0
                   sustained (>= 10 min) -> device is NOT cooling -> it is on the higher setpoint.
  follows STATUS/lower : blower > 0 while T < higher setpoint -> device IS cooling -> it is on the lower setpoint.
Attribution: which feed had the lower vs higher setpoint in that interval.
Also reports manual-vs-X disagreements separately (C20 case: hold_activity may itself read 'manual').
"""
import sqlite3,json,sys,time,collections
a=sys.argv[1:]; DAYS=int(a[a.index('--days')+1]) if '--days' in a else 7
MARGIN=float(a[a.index('--margin')+1]) if '--margin' in a else 2.0  # cooling differential guard (F)
ENT=['climate.thermostat_bryant_wifi_studyb_zone_1','climate.up_hallway_zone_2','climate.back_hallway_zone_3']
r=sqlite3.connect('file:/config/home-assistant_v2.db?mode=ro',uri=True)
t0=time.time()-DAYS*86400
for e in ENT:
    mid=r.execute("SELECT metadata_id FROM states_meta WHERE entity_id=?",(e,)).fetchone()[0]
    rows=[]
    for st,ts,sa in r.execute("""SELECT s.state,s.last_updated_ts,a.shared_attrs FROM states s LEFT JOIN state_attributes a ON s.attributes_id=a.attributes_id
                                  WHERE s.metadata_id=? AND s.last_updated_ts>=? ORDER BY s.last_updated_ts""",(mid,t0)):
        if st in('unavailable','unknown',None) or not sa: continue
        d=json.loads(sa); rows.append((ts,st,d))
    prof=collections.defaultdict(collections.Counter)
    for ts,st,d in rows:
        if d.get('preset_mode')==d.get('hold_activity') and d.get('target_temp_high') is not None:
            prof[d['preset_mode']][d['target_temp_high']]+=1
    P={k:v.most_common(1)[0][0] for k,v in prof.items()}
    ev=collections.Counter(); dis=collections.Counter(); hold_ev=0.0; stat_ev=0.0; undecided=0.0; manual_pairs=collections.Counter()
    for i,(ts,st,d) in enumerate(rows):
        dur=(rows[i+1][0]-ts) if i+1<len(rows) else 0
        sp,ha=d.get('preset_mode'),d.get('hold_activity')
        if not sp or not ha or sp==ha: continue
        dis[(sp,ha)]+=dur/60
        if 'manual' in (sp,ha): manual_pairs[(sp,ha)]+=dur/60
        sh=d.get('target_temp_high'); hh=P.get(ha)
        T=d.get('current_temperature'); b=d.get('blower_rpm') or 0
        if sh is None or hh is None or T is None or sh==hh or st not in('cool','heat_cool'): undecided+=dur/60; continue
        lo,hi=min(sh,hh),max(sh,hh)
        if not (lo < T < hi+0.5): undecided+=dur/60; continue
        lower_is_status = sh<hh
        if b>0 and T<=hi-1:   # cooling while at/below (higher-1) -> device must be on the lower setpoint
            k='status' if lower_is_status else 'hold'
        elif b==0 and T>=lo+MARGIN and dur>=600: # sustained idle >=MARGIN over the lower setpoint -> on the higher one
            k='hold' if lower_is_status else 'status'
        else:
            undecided+=dur/60; continue
        if k=='hold': hold_ev+=dur/60
        else: stat_ev+=dur/60
        ev[(k,sp,ha,T,sh,hh,b>0)]+=dur/60
    print(f"== {e}  profiles(high by activity, agreeing rows)={dict(P)}")
    print(f"   disagreement minutes by (status,hold): {{ {', '.join(f'{k}:{round(v)}' for k,v in dis.most_common(8))} }}")
    print(f"   PHYSICAL EVIDENCE minutes -> device followed HOLD: {round(hold_ev)} | followed STATUS: {round(stat_ev)} | undecidable: {round(undecided)}")
    for k,v in ev.most_common(6): print('     evidence', dict(zip(('follows','status','hold','T','status_high','hold_high','blower_on'),k)), round(v),'min')
    if manual_pairs: print(f"   manual-involved pairs (C20 case) minutes: {dict((k,round(v)) for k,v in manual_pairs.items())}")
