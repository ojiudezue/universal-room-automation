#!/usr/bin/env python3
"""Score an arm's predictions against the labeled eval set, per split.
Arm prediction row: {case_id, p_occupied: float in [0,1]}. Decision = occupied if p>=0.5.
Reports accuracy per split + ECE (calibration). CODE arm has no probability (hard 0/1) -> ECE degenerate."""
import json, sys, collections
ev={json.loads(l)["case_id"]:json.loads(l) for l in open("docs/planning/jev_spike/eval_set.jsonl") if l.strip()}
def load_preds(path):
    return {json.loads(l)["case_id"]:json.loads(l)["p_occupied"] for l in open(path) if l.strip()}
def score(preds,name):
    per=collections.defaultdict(lambda:[0,0]); bins=collections.defaultdict(lambda:[0.0,0,0])
    for cid,c in ev.items():
        if cid not in preds: continue
        p=preds[cid]; pred="occupied" if p>=0.5 else "empty"; truth=c["label"]; sp=c["split"]
        per[sp][1]+=1; per[sp][0]+= (pred==truth)
        # ECE bins (confidence = distance from 0.5 mapped to prob-of-predicted-class)
        conf=p if pred=="occupied" else 1-p
        b=min(9,int(conf*10)); bins[b][0]+=conf; bins[b][1]+= (pred==truth); bins[b][2]+=1
    print(f"\n### {name}")
    for sp in ("works","fails"):
        c,n=per[sp]; print(f"  {sp:6}: {c}/{n} = {100*c/n:.1f}%" if n else f"  {sp}: n/a")
    tot_c=sum(v[0] for v in per.values()); tot_n=sum(v[1] for v in per.values())
    N=sum(v[2] for v in bins.values()); ece=sum(abs(v[0]/v[2]-v[1]/v[2])*v[2]/N for v in bins.values() if v[2])
    print(f"  overall: {tot_c}/{tot_n} = {100*tot_c/tot_n:.1f}% | ECE={ece:.3f}")
# CODE arm: prediction = the fused room_occupied (hard). p=1.0 occupied else 0.0.
code={cid:(1.0 if c['features']['room_occupied'] else 0.0) for cid,c in ev.items()}
score(code,"CODE (fused room_occupied; no calibration)")
for path in sys.argv[1:]:
    name=path.split("/")[-1].replace(".pred.jsonl","")
    score(load_preds(path),name)
