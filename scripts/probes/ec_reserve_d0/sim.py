import json,bisect,datetime,sys,collections
D=json.load(open('dump.json')); E=json.load(open('evse.json'))
MARGIN=float(sys.argv[1]) if len(sys.argv)>1 else 3
SPAN=float(sys.argv[2]) if len(sys.argv)>2 else 20
LAG=float(sys.argv[3]) if len(sys.argv)>3 else 30
GAP=900;DB=2
f=lambda x:datetime.datetime.fromtimestamp(x,datetime.timezone.utc).strftime('%m-%d %H:%M')
def ser(k):
    o=[]
    for s,t,a in D[k]:
        try:v=float(s)
        except:v=None
        o.append((t,v))
    return o
class S:
    def __init__(s,l): s.l=l;s.t=[x[0] for x in l]
    def at(s,t):
        i=bisect.bisect_right(s.t,t)-1
        return s.l[i][1] if i>=0 else None
local=S(ser('local'));cloud=S(ser('cloud'));soc=S(ser('soc'))
def pw(k):
    return [(t,abs(float(s))) for s,t in E[k] if s not in('unavailable','unknown')]
ga=S(pw('ga'));gb=S(pw('gb'))
def evon(t):
    for dt in (0,60,120,180,240,300):
        a=ga.at(t-dt);b=gb.at(t-dt)
        if (a or 0)>500 or (b or 0)>500: return True
    return False
rw=[]
for ts,j in D['rw']:
    j=json.loads(j);rw.append((datetime.datetime.fromisoformat(ts).timestamp(),j))
rt=[x[0] for x in rw]
def lastrow(t,pred=None):
    i=bisect.bisect_right(rt,t)-1
    while i>=0:
        if pred is None or pred(rw[i][1]): return rw[i]
        i-=1
    return (None,None)
# stale windows from recorded: |local-cloud|>=2 both numeric, sustained >=900s
def nudge(t): return t+1 if t<100 else t-1
def trusted(L,target,sc):
    if L is None: return None,'unavailable'
    if sc is None: return (L,'local') if L<=target else (None,'soc_unknown_high')
    if sc<=target+MARGIN and target<L<=sc+SPAN: return None,'low_soc_guard'
    return L,'local'
NUMCHG=[]
_p=None
for _t,_v in ser('local'):
    if _v is None: continue
    if _p is not None and _v!=_p: NUMCHG.append(_t)
    _p=_v
START=1792241222+600; END=1792855170
def run(newrules):
    ov=None  # (value, since)
    Ssel=None
    att_v=att_t=ok_v=None;ok_t=None
    sends=[];viol=[];dwell_start=None;d4=[];log=[]
    L_prev_rec=None
    first=True
    for t in range(START,int(END),300):
        rec_l=local.at(t); c=cloud.at(t); sc=soc.at(t)
        rt_,r=lastrow(t+60)
        if r is None: continue
        target=r['desire']; hold=(r['value']!=r['desire']) and evon(t)
        # override ends when recorded local changes
        if ov is not None:
            # recorded local changed since override started?
            if any(ov[1]-LAG<ct<=t for ct in NUMCHG): ov=None
        L = ov[0] if (ov is not None and t>=ov[1]) else rec_l
        eff = r['value'] if hold else target
        # recorded-world stamps (rows prior to t) as the baseline of attempts/landed
        # sim stamps override when sim sent after the latest recorded row
        okrow=lastrow(t+60,lambda j:j['status']=='applied'); atrow=lastrow(t+60)
        ov_ok_v,ov_ok_t=(ok_v,ok_t) if ok_t is not None and ok_t>(okrow[0] or 0) else (okrow[1]['value'] if okrow[1] else None, okrow[0])
        a_v,a_t=(att_v,att_t) if att_t is not None and att_t>(atrow[0] or 0) else (atrow[1]['value'],atrow[0])
        if hold: 
            # overlay writes the hold; stamps follow recorded rows
            ov=None; Ssel=r['value']; dwell_start=None; continue
        # INV-R1/D4 dwell on trusted witness vs eff
        tl,src=trusted(L,eff,sc)
        if tl is not None and abs(tl-eff)>=DB:
            if dwell_start is None: dwell_start=t
            if t-dwell_start>2400 and not any(v[1]==dwell_start for v in viol): viol.append((t,dwell_start))
            if t-dwell_start>2700 and not any(v[0]==dwell_start for v in d4): d4.append((dwell_start,t))
        else: dwell_start=None
        # decision
        send=None;why=None
        if not newrules:
            if c is None or abs(c-target)>=DB: send=target;why='C'
        else:
            tl,src=trusted(L,target,sc)
            cand=None
            if tl is None:
                if c is None or abs(c-target)>=DB: send=target;why='C'
                # rule L (no gap vs C)
            else:
                if abs(tl-target)>=DB: cand=('T',tl)
            if ov_ok_v is not None and abs(ov_ok_v-target)>=DB and ov_ok_v!=nudge(target):
                if cand is None: cand=('L',tl)
            if cand is not None:
                raise_=(tl is not None and target>tl+DB) or (tl is None and ov_ok_v is not None and target>ov_ok_v)
                gated=(a_t is not None and t-a_t<GAP and a_v in (target,nudge(target)) and not raise_)
                if not gated: send=target;why=cand[0]
                else: why='G'
            if send is None and tl is None and why is None:
                pass
            if send is not None and why!='C':
                trig_a = c is not None and abs(c-target)<0.5
                trig_b = ov_ok_v is not None and abs(ov_ok_v-target)<0.5
                if trig_a or trig_b: send=nudge(target)
            elif send is not None and why=='C':
                # D2 also applies to rule C sends? plan: when D1 decides to send target, emit nudge if trigger
                trig_a = c is not None and abs(c-target)<0.5
                trig_b = ov_ok_v is not None and abs(ov_ok_v-target)<0.5
                if trig_a or trig_b: send=nudge(target)
        if send is not None:
            sends.append((t,send,why,L,c,sc,target))
            att_v,att_t=send,t
            ok_v,ok_t=send,t
            if send!=Ssel:   # integration accepts
                Ssel=send
                ov=(send,t+LAG)
            # else dropped silently
    return sends,viol,d4
for name,nr in (('PRE',False),('NEW',True)):
    sends,viol,d4=run(nr)
    print('==',name,'sends(non-hold ticks):',len(sends))
    c=collections.Counter(s[2] for s in sends);print(dict(c))
    byhr=collections.Counter(int(s[0]//3600) for s in sends)
    print('max sends/hr',max(byhr.values()) if byhr else 0, 'hours>4:',sum(1 for v in byhr.values() if v>4))
    print('INV-R1 violations (trusted local>=2 from eff >2400s):',[(f(a),f(b)) for a,b in viol])
    print('D4 would fire (dwell>2700s):',[(f(a),f(b)) for a,b in d4])
    if name=='NEW':
        for s in sends:
            if s[2]!='C': print(f(s[0]),s[1:])
if len(sys.argv)>4:
    sends,viol,d4=run(True)
    byhr=collections.defaultdict(list)
    for s in sends: byhr[int(s[0]//3600)].append(s)
    for h,v in sorted(byhr.items()):
        if len(v)>3: print('HR',f(h*3600),len(v),[(f(x[0]),x[1],x[2],x[6]) for x in v])
    print('C-sends:',[(f(x[0]),x[1],x[3],x[4],x[5],x[6]) for x in sends if x[2]=='C'])
    sends,viol,d4=run(False)
    byhr=collections.Counter(int(s[0]//3600) for s in sends)
    print('PRE hours with >=6 sends:',sorted((f(h*3600),n) for h,n in byhr.items() if n>=6)[:30])
    print('PRE sends in B window (10-19 21:37..10-20 06:07):',sum(1 for s in sends if 1792445800<s[0]<1792476500))
