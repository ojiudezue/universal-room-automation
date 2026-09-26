#!/usr/bin/env python3
"""Carrier feed-truth, EPISODE level — READ-ONLY (W1-B D0 input).
    ssh ha "python3 - [--days 7] [--margin 2]" < scripts/probes/carrier_feed_truth_episodes.py
Episode = contiguous rows where STATUS preset_mode != CONFIG hold_activity (unavailable rows break episodes).
Per episode: disagreement CLASS = named-vs-named (neither is 'manual') or manual-involved (which side is manual).
Implied cooling setpoints: status side = the row's target_temp_high; hold side = zone profile high for the hold activity
(learned from agreeing rows). lo/hi = lower/higher of the two.
Physical minutes inside the episode (time-weighted):
  IDLE_ABOVE  = blower 0 and T >= lo+MARGIN     -> device on the HIGHER setpoint
  COOL_BELOW  = blower >0 and T <= hi-1         -> device on the LOWER setpoint
Verdict = the side whose setpoint matches the majority of decisive minutes (needs >= 15 decisive min).
"""
import sqlite3,json,sys,time,collections
a=sys.argv[1:]; DAYS=int(a[a.index('--days')+1]) if '--days' in a else 7
MARGIN=float(a[a.index('--margin')+1]) if '--margin' in a else 2.0
ENT={'zone_1':'climate.thermostat_bryant_wifi_studyb_zone_1','zone_2':'climate.up_hallway_zone_2','zone_3':'climate.back_hallway_zone_3'}
r=sqlite3.connect('file:/config/home-assistant_v2.db?mode=ro',uri=True); t0=time.time()-DAYS*86400
tally=collections.Counter(); pooled=collections.Counter()
for z,e in ENT.items():
    mid=r.execute("SELECT metadata_id FROM states_meta WHERE entity_id=?",(e,)).fetchone()[0]
    rows=[]
    for st,ts,sa in r.execute("SELECT s.state,s.last_updated_ts,a.shared_attrs FROM states s LEFT JOIN state_attributes a ON s.attributes_id=a.attributes_id WHERE s.metadata_id=? AND s.last_updated_ts>=? ORDER BY s.last_updated_ts",(mid,t0)):
        rows.append((ts,st,json.loads(sa) if sa else {}))
    prof=collections.defaultdict(collections.Counter)
    for ts,st,d in rows:
        if d.get('preset_mode') and d.get('preset_mode')==d.get('hold_activity') and d.get('target_temp_high') is not None: prof[d['preset_mode']][d['target_temp_high']]+=1
    P={k:v.most_common(1)[0][0] for k,v in prof.items()}
    eps=[]; cur=None
    for i,(ts,st,d) in enumerate(rows):
        dur=(rows[i+1][0]-ts) if i+1<len(rows) else 0
        sp,ha=d.get('preset_mode'),d.get('hold_activity')
        dis= st not in('unavailable','unknown') and sp and ha and sp!=ha
        if not dis:
            if cur: eps.append(cur); cur=None
            continue
        if cur is None: cur=dict(start=ts,pairs=collections.Counter(),idle_hi=0.0,cool_lo=0.0,mins=0.0,lo_side=collections.Counter())
        cur['pairs'][(sp,ha)]+=dur; cur['mins']+=dur/60
        sh=d.get('target_temp_high'); hh=P.get(ha); T=d.get('current_temperature'); b=d.get('blower_rpm') or 0
        if None in (sh,hh,T) or sh==hh or st not in('cool','heat_cool'): continue
        lo,hi=min(sh,hh),max(sh,hh); lower='status' if sh<hh else 'hold'; higher='hold' if lower=='status' else 'status'
        if b==0 and T>=lo+MARGIN: cur['idle_hi']+=dur/60; cur['lo_side'][higher]+=dur/60
        elif b>0 and T<=hi-1: cur['cool_lo']+=dur/60; cur['lo_side'][lower]+=dur/60
    if cur: eps.append(cur)
    print(f"== {z} profile={P}")
    for ep in eps:
        dec=sum(ep['lo_side'].values())
        (sp0,ha0),_=ep['pairs'].most_common(1)[0]
        cls0='named-vs-named' if 'manual' not in (sp0,ha0) else ('status-manual' if sp0=='manual' else 'hold-manual')
        for side,m in ep['lo_side'].items(): pooled[(z,cls0,side)]+=m
        if dec<15: continue
        (sp,ha),_=ep['pairs'].most_common(1)[0]
        cls='named-vs-named' if 'manual' not in (sp,ha) else ('status-manual' if sp=='manual' else 'hold-manual')
        win=ep['lo_side'].most_common(1)[0][0]; share=round(100*ep['lo_side'][win]/dec)
        tally[(cls,win)]+=1
        print(f"  {time.strftime('%m-%d %H:%M',time.gmtime(ep['start']-5*3600))} dur={round(ep['mins'])}m pair(status,hold)=({sp},{ha}) class={cls} decisive={round(dec)}m -> follows {win.upper()} ({share}%)")
print("== POOLED decisive minutes (zone,class,device followed):", {k:round(v) for k,v in sorted(pooled.items())})
print("== TALLY (class, device followed):", dict(tally))
