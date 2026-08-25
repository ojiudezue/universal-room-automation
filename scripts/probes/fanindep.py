import sqlite3, datetime
c=sqlite3.connect("file:/config/home-assistant_v2.db?mode=ro",uri=True)
def series(e):
    q="""SELECT s.last_updated_ts, s.state FROM states s JOIN states_meta m ON s.metadata_id=m.metadata_id
         WHERE m.entity_id=? AND s.state IS NOT NULL ORDER BY s.last_updated_ts"""
    return [(t,st) for t,st in c.execute(q,(e,))]
PAIRS=[("binary_sensor.occupancy_lux_temp_humidity_hobeian_exercise_presence_2","fan.fan_switch_3"),
       ("binary_sensor.occupancy_lux_temp_humidity_hobeian_exercise_presence","fan.fan_switch_3"),
       ("binary_sensor.occupancy_lux_temp_humidity_hobeian_upguestroom_presence_2","fan.guest_room_fan_combined")]
for pres,fan in PAIRS:
    P,F=series(pres),series(fan)
    if not P or not F:
        print(f"\n### {pres} + {fan}: NO DATA (pres={len(P)} fan={len(F)})"); continue
    span=(max(P[-1][0],F[-1][0])-min(P[0][0],F[0][0]))/86400
    print(f"\n### {pres.split('hobeian_')[-1]}  +  {fan.split('.')[-1]}   [{span:.1f}d, {len(P)} pres rows, {len(F)} fan rows]")
    # time-weighted: walk merged timeline
    ev=sorted([(t,'p',s) for t,s in P]+[(t,'f',s) for t,s in F])
    ps=fs=None; last=None
    acc={} # (fanstate) -> [time_pres_on, time_total]
    for t,k,s in ev:
        if last is not None and ps is not None and fs is not None:
            d=t-last
            key = 'fan_on' if fs=='on' else ('fan_off' if fs=='off' else None)
            if key:
                a=acc.setdefault(key,[0.0,0.0]); a[1]+=d
                if ps=='on': a[0]+=d
        if k=='p': ps=s
        else: fs=s
        last=t
    for key in ('fan_on','fan_off'):
        if key in acc and acc[key][1]>0:
            on,tot=acc[key]
            print(f"   P(presence=on | {key}) = {on/tot:6.1%}   ({on/3600:.1f}h on / {tot/3600:.1f}h)")
        else:
            print(f"   {key}: no overlap time")
