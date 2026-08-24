import sqlite3
c=sqlite3.connect("file:/config/home-assistant_v2.db?mode=ro",uri=True)
def series(e, states=('on','off')):
    q=("SELECT s.last_updated_ts,s.state FROM states s JOIN states_meta m ON s.metadata_id=m.metadata_id "
       "WHERE m.entity_id=? AND s.state IN (%s) ORDER BY s.last_updated_ts" % ",".join("?"*len(states)))
    return list(c.execute(q,(e,)+states))
def trans(S):
    out=[];prev=None
    for t,s in S:
        if s!=prev: out.append((t,s)); prev=s
    return out
PRES="binary_sensor.mmwave_temp_lux_hum_zigbee_livingroom_presence"
FAN="fan.towerfan_dreopilotmaxs_wifi_livingroom"
P,F=series(PRES),series(FAN)
print(f"pres rows {len(P)}, fan rows {len(F)}")
if not F: print("FAN never toggled in window — untestable"); raise SystemExit
span=(max(P[-1][0],F[-1][0])-min(P[0][0],F[0][0]))/86400
print(f"window {span:.1f} days")
# time-weighted
ev=sorted([(t,'p',s) for t,s in P]+[(t,'f',s) for t,s in F])
ps=fs=None;last=None;acc={}
for t,k,s in ev:
    if last is not None and ps and fs:
        d=t-last; key='fan_on' if fs=='on' else 'fan_off'
        a=acc.setdefault(key,[0.0,0.0]); a[1]+=d
        if ps=='on': a[0]+=d
    if k=='p': ps=s
    else: fs=s
    last=t
for key in ('fan_on','fan_off'):
    if key in acc and acc[key][1]>0:
        on,tot=acc[key]; print(f"P(presence=on | {key}) = {on/tot:6.1%}  ({on/3600:.1f}h / {tot/3600:.1f}h)")
PT,FT=trans(P),trans(F)
rise=[];fall=[]
for t,s in FT:
    if s=='on':
        d=[tt-t for tt,ss in PT if ss=='on' and tt>=t-1]
        if d: rise.append(round(d[0],1))
    else:
        d=[tt-t for tt,ss in PT if ss=='off' and tt>=t-1]
        if d: fall.append(round(d[0],1))
print("fan_on  -> presence_on  lags:", sorted(rise)[:14])
print("fan_off -> presence_off lags:", sorted(fall)[:14])
tight=[x for x in rise if x<10]
print(f">>> rising lags under 10s: {len(tight)}/{len(rise)}  ==> {'LATCH SIGNATURE' if len(tight)>=3 else 'NO latch signature'}")
