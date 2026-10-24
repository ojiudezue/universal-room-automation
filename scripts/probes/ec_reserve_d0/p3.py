import json,datetime,bisect
D=json.load(open('dump.json'))
f=lambda x:datetime.datetime.fromtimestamp(x,datetime.timezone.utc).strftime('%m-%d %H:%M:%S')
P=[]
for s,t,a in D['profile']:
    try: a=json.loads(a) if a else {}
    except: a={}
    P.append((t,s,a.get('pending'),a.get('requested_reserve_percentage'),a.get('selected_reserve_percentage'),a.get('effective_reserve_percentage'),a.get('pending_requested_at')))
print(len(P),"states; pending key present in",sum(1 for p in P if p[2] is not None),"; true:",sum(1 for p in P if p[2] is True))
# intervals
ivs=[];start=None
for p in P:
    if p[2] is True and start is None: start=p
    elif p[2] is not True and start is not None:
        ivs.append((start,p));start=None
if start: ivs.append((start,None))
loc=[(t,float(s)) for s,t,a in D['local'] if s not in('unavailable','unknown')]
lt=[x[0] for x in loc]
print("pending=true intervals:",len(ivs))
import statistics
durs=[]
for a,b in ivs:
    end=b[0] if b else None
    dur=(end-a[0]) if end else None
    req=a[3]
    # first local change to within 1 of requested at/after a[0]-60
    lap=None
    for t,v in loc:
        if t>=a[0]-120 and req is not None and abs(v-req)<=1: lap=t;break
    print(f(a[0]),'req',req,'sel',a[4],'eff',a[5],'dur_s',None if dur is None else round(dur),'local_applied_at',f(lap) if lap else None,'pending_after_local_s',None if (lap is None or end is None) else round(end-lap))
    if dur is not None: durs.append(dur)
if durs:
    durs.sort();print('dur p50/p90/max',durs[len(durs)//2],durs[int(len(durs)*.9)-1],durs[-1],'n',len(durs),'frac<=300s',sum(1 for d in durs if d<=300)/len(durs))
