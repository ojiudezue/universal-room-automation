"""Measured delta between Emporia mains and Envoy net-consumption CT."""
import sqlite3, statistics as st
r=sqlite3.connect("/config/home-assistant_v2.db")

EMP="sensor.mains_vue_3_power_minute_average"                       # WATTS, signed
ENV="sensor.envoy_482543015950_current_net_power_consumption"       # kW,    signed

def series(ent, scale=1.0):
    mid=r.execute("select metadata_id from states_meta where entity_id=?",(ent,)).fetchone()
    if not mid: return []
    out=[]
    for t,v in r.execute("select last_updated_ts,state from states where metadata_id=? order by last_updated_ts",(mid[0],)):
        try: out.append((t, float(v)*scale))
        except (TypeError,ValueError): pass
    return out

emp=series(EMP, 1.0)        # already W
env=series(ENV, 1000.0)     # kW -> W
print(f"samples: emporia={len(emp)}  envoy={len(env)}")
if not emp or not env:
    raise SystemExit("missing series")

# forward-fill envoy onto emporia timestamps (emporia is the 1-min average = coarser)
env.sort(); ei=0; cur=None; deltas=[]; pairs=[]
for t,e in emp:
    while ei < len(env) and env[ei][0] <= t:
        cur = env[ei][1]; ei += 1
    if cur is None: continue
    if abs(t - (env[ei-1][0] if ei else t)) > 300: continue   # skip if envoy stale >5min
    deltas.append(e - cur); pairs.append((e, cur))
if not deltas:
    raise SystemExit("no aligned pairs")

s=sorted(deltas)
n=len(s)
print(f"\naligned pairs: {n}")
print(f"  mean delta   {st.mean(deltas):9.1f} W   ({st.mean(deltas)/1000:6.3f} kW)")
print(f"  median       {st.median(deltas):9.1f} W")
print(f"  stdev        {st.pstdev(deltas):9.1f} W")
print(f"  p10 / p90    {s[n//10]:9.1f} / {s[9*n//10]:.1f} W")
print(f"  min / max    {s[0]:9.1f} / {s[-1]:.1f} W")
within=lambda w: sum(1 for d in deltas if abs(d)<=w)/n*100
print(f"\n  |delta| <= 250 W : {within(250):5.1f}%")
print(f"  |delta| <= 500 W : {within(500):5.1f}%")
print(f"  |delta| <= 1000 W: {within(1000):5.1f}%")
# agreement on SIGN (both say exporting / both say importing)
same=sum(1 for a,b in pairs if (a<0)==(b<0))/len(pairs)*100
print(f"\n  sign agreement (both export or both import): {same:.1f}%")
