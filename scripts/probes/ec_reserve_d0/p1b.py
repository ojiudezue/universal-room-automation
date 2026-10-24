import json,datetime,collections
G=json.load(open('grid.json'))
f=lambda x:datetime.datetime.fromtimestamp(x,datetime.timezone.utc).strftime('%m-%d %H:%M')
ok=[g for g in G if g['l'] is not None and g['s'] is not None]
# episodes (UTC epoch) where local==hold/unreleased: exclude windows A-E
import calendar
def ep(m,d,h,mi): return calendar.timegm((2026,m,d,h,mi,0))
EP=[(ep(10,19,18,26),ep(10,19,19,34)),(ep(10,19,21,37),ep(10,20,6,8)),(ep(10,22,6,5),ep(10,23,10,1)),(ep(10,23,19,35),ep(10,24,0,24))]
def inep(t): return any(a<=t<=b for a,b in EP)
print("total grid min",len(ok))
# regime table by (soc - local_or_cmd): local vs soc relation when soc <= cmd+10
bins=collections.defaultdict(list)
for g in ok:
    if inep(g['t']): continue
    if g['age']<600: continue
    bins[max(-10,min(30,(g['s']-g['cmd'])//2*2))].append(g)
print("soc-cmd bin | n | n(|l-cmd|>=2) | max(l-cmd) | min(l-cmd) | max(l-soc) | min(l-soc)")
for k in sorted(bins):
    v=bins[k]
    w=[g for g in v if abs(g['l']-g['cmd'])>=2]
    print(k,len(v),len(w),max(g['l']-g['cmd'] for g in v),min(g['l']-g['cmd'] for g in v),max(g['l']-g['s'] for g in v),min(g['l']-g['s'] for g in v))
# wobble minutes list with soc-cmd>2
print("\nwobble minutes (non-episode, |l-cmd|>=2, age>600) with soc-cmd>=3:")
for g in ok:
    if inep(g['t']) or g['age']<600: continue
    if abs(g['l']-g['cmd'])>=2 and g['s']-g['cmd']>=3: print(f(g['t']),g)
# failed rows
import json as j
D=json.load(open('dump.json'))
print("\nfailed rows:",[(ts[5:19],json.loads(x)['value'],json.loads(x)['path']) for ts,x in D['rw'] if json.loads(x)['status']!='applied'])
# local readings per change with soc (event-level) near low soc
print("\nlocal change events with soc<=cmd+9 (non-episode):")
