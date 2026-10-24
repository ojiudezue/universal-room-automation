import json,bisect,datetime,collections
D=json.load(open('dump.json'))
T0=1792228320+3000; T1=1792855170+0
f=lambda x:datetime.datetime.fromtimestamp(x,datetime.timezone.utc).strftime('%m-%d %H:%M')
def ser(k):
    out=[]
    for s,t,a in D[k]:
        try: v=float(s)
        except: v=None
        out.append((t,v))
    return out
def at(s,t):
    ts=[x[0] for x in s]; i=bisect.bisect_right(ts,t)-1
    return s[i][1] if i>=0 else None
local=ser('local'); cloud=ser('cloud'); soc=ser('soc')
rw=[]
for ts,j in D['rw']:
    j=json.loads(j); t=datetime.datetime.fromisoformat(ts).timestamp()
    rw.append((t,j))
rt=[x[0] for x in rw]
def lastrow(t):
    i=bisect.bisect_right(rt,t)-1
    return rw[i] if i>=0 else (None,None)
rows=[]
for t in range(int(T0),int(T1),60):
    l=at(local,t); c=at(cloud,t); s=at(soc,t); rt_,r=lastrow(t)
    if r is None: continue
    rows.append(dict(t=t,l=l,c=c,s=s,cmd=r['value'],des=r['desire'],age=t-rt_,own=r.get('hold_owner')))
json.dump(rows,open('grid.json','w'))
print(len(rows),f(rows[0]['t']),f(rows[-1]['t']))
