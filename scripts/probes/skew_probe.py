"""Is the Emporia/Envoy delta timing skew, or genuine disagreement?

If skew: |delta| should scale with the RATE OF CHANGE of the signal.
If real: |delta| should be flat regardless of how fast load is moving.
"""
import sqlite3, statistics as st
r=sqlite3.connect("/config/home-assistant_v2.db")
EMP="sensor.mains_vue_3_power_minute_average"
ENV="sensor.envoy_482543015950_current_net_power_consumption"

def series(ent, scale=1.0):
    mid=r.execute("select metadata_id from states_meta where entity_id=?",(ent,)).fetchone()
    out=[]
    for t,v in r.execute("select last_updated_ts,state from states where metadata_id=? order by last_updated_ts",(mid[0],)):
        try: out.append((t,float(v)*scale))
        except (TypeError,ValueError): pass
    return out

emp=series(EMP); env=series(ENV,1000.0)
ei=0; cur=None; rows=[]
prev_env=None; prev_t=None
for t,e in emp:
    while ei<len(env) and env[ei][0]<=t:
        prev_env = cur; prev_t = env[ei-1][0] if ei else None
        cur=env[ei][1]; ei+=1
    if cur is None or prev_env is None or prev_t is None: continue
    dt = t - prev_t
    if dt<=0 or dt>300: continue
    slew = abs(cur - prev_env)/dt*60.0        # W per minute of change in the FAST signal
    rows.append((slew, e-cur))
print(f"pairs with slew: {len(rows)}")
buckets=[(0,50),(50,200),(200,500),(500,1500),(1500,5000),(5000,10**9)]
print(f"\n{'slew (W/min)':>16}  {'n':>5}  {'median |delta| W':>17}  {'mean delta W':>13}")
for lo,hi in buckets:
    sel=[d for s,d in rows if lo<=s<hi]
    if len(sel)<20: continue
    print(f"{lo:7d}-{hi if hi<10**9 else 999999:7d}  {len(sel):5d}  {st.median([abs(x) for x in sel]):17.0f}  {st.mean(sel):13.0f}")
quiet=[d for s,d in rows if s<50]
busy=[d for s,d in rows if s>=1500]
if quiet and busy:
    print(f"\n  QUIET (slew<50 W/min):  n={len(quiet):5d}  median|delta|={st.median([abs(x) for x in quiet]):.0f} W")
    print(f"  BUSY  (slew>1500):      n={len(busy):5d}  median|delta|={st.median([abs(x) for x in busy]):.0f} W")
    print(f"  ratio busy/quiet: {st.median([abs(x) for x in busy])/max(1,st.median([abs(x) for x in quiet])):.1f}x")
