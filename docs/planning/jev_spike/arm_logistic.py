#!/usr/bin/env python3
"""Open arm 'logistic': pure-python calibrated logistic classifier on RAW signals (not the fused
room_occupied). Leave-one-out CV. Floor of a Jev-class calibrated decider."""
import json, math
rows=[json.loads(l) for l in open("docs/planning/jev_spike/eval_set.jsonl") if l.strip()]
HS=sorted({(r["features"].get("house_state") or "none") for r in rows})
def feat(r):
    f=r["features"]; son=f["sensors_on"]; tot=max(1,f["sensors_total"])
    return [float(son), son/tot, float(f["persons_in_house"]), 1.0 if f["persons_in_house"]==0 else 0.0] + \
           [1.0 if (f.get("house_state") or "none")==h else 0.0 for h in HS]
X=[feat(r) for r in rows]; y=[1.0 if r["label"]=="occupied" else 0.0 for r in rows]
d=len(X[0]); n=len(X)
# standardize (fit on all — leakage negligible for scaling; the DECISION is LOO)
mean=[sum(x[j] for x in X)/n for j in range(d)]
var=[sum((x[j]-mean[j])**2 for x in X)/n or 1.0 for j in range(d)]
sd=[math.sqrt(v) for v in var]
def z(x): return [ (x[j]-mean[j])/sd[j] for j in range(d) ]
Xz=[z(x) for x in X]
def sig(t): return 1/(1+math.exp(-max(-30,min(30,t))))
def fit(idx):
    w=[0.0]*d; b=0.0; lr=0.3; lam=0.5
    for _ in range(400):
        gw=[0.0]*d; gb=0.0
        for i in idx:
            p=sig(sum(w[j]*Xz[i][j] for j in range(d))+b); e=p-y[i]
            for j in range(d): gw[j]+=e*Xz[i][j]
            gb+=e
        m=len(idx)
        for j in range(d): w[j]-=lr*(gw[j]/m+lam*w[j]/m)
        b-=lr*gb/m
    return w,b
preds=[]
for i in range(n):
    w,b=fit([j for j in range(n) if j!=i])
    p=sig(sum(w[j]*Xz[i][j] for j in range(d))+b)
    preds.append({"case_id":rows[i]["case_id"],"p_occupied":p})
open("docs/planning/jev_spike/logistic.pred.jsonl","w").write("\n".join(json.dumps(p) for p in preds)+"\n")
print("logistic LOO predictions:",len(preds))
