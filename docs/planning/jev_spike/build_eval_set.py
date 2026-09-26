#!/usr/bin/env python3
"""Assemble a labeled occupancy-trust eval set from the live HA recorder (read-only).
Label rules (no hand-labeling; each case carries its provenance):
  code-works OCCUPIED : persons_in_house>=1 AND room _occupied==on AND >=2 distinct configured sensors on
  code-works EMPTY    : persons_in_house==0 AND room _occupied==off (a clean empty snapshot)
  code-fails EMPTY    : persons_in_house==0 AND room _occupied==on via a SINGLE configured sensor (phantom proxy)
The code-fails split is the adaptiveness test: a lone sensor holding a room 'occupied' with nobody home.
"""
import json, subprocess, collections
from datetime import datetime, timezone

ROOMS = {
 "jaya":     ("binary_sensor.jaya_bedroom_bedroom_4_occupied",
              ["binary_sensor.jaya_3_presence","binary_sensor.mmwave_zigbee_jayabedroom_presence"]),
 "ziri":     ("binary_sensor.ziri_bedroom_bedroom_5_occupied",
              ["binary_sensor.ziri_3_presence","binary_sensor.mmwave_zigbee_ziribedroom_presence","binary_sensor.ziri_3_moving_target"]),
 "living":   ("binary_sensor.living_room_occupied",
              ["binary_sensor.living_room_motion","binary_sensor.living_room_camera_person_detected"]),
 "masterbr": ("binary_sensor.master_bedroom_occupied",
              ["binary_sensor.master_bedroom_motion","binary_sensor.master_bedroom_camera_person_detected"]),
}
PERSONS="sensor.universal_room_automation_persons_in_house"
HOUSE="sensor.ura_coordinator_manager_house_state"

ents=set([PERSONS,HOUSE])
for occ,sens in ROOMS.values():
    ents.add(occ); ents.update(sens)
inlist=",".join(f"'{e}'" for e in ents)
q=(f"SELECT sm.entity_id, st.state, st.last_updated_ts FROM states st "
   f"JOIN states_meta sm ON st.metadata_id=sm.metadata_id "
   f"WHERE sm.entity_id IN ({inlist}) AND st.last_updated_ts > strftime('%s','now','-7 day') "
   f"ORDER BY st.last_updated_ts;")
raw=subprocess.run(["ssh","ha",f"sqlite3 -readonly /config/home-assistant_v2.db \"{q}\""],
                   capture_output=True,text=True,timeout=90).stdout
series=collections.defaultdict(list)
for line in raw.splitlines():
    p=line.split("|")
    if len(p)!=3: continue
    eid,state,ts=p
    try: series[eid].append((float(ts),state))
    except: pass
def at(eid,t):
    s=series.get(eid,[]); v=None
    for ts,st in s:
        if ts<=t: v=st
        else: break
    return v
def is_on(eid,t): return at(eid,t)=="on"
def pcount(t):
    v=at(PERSONS,t)
    try: return int(float(v))
    except: return None

cases=[]
# sample at every _occupied state-change per room (dedup by minute), snapshot features + label
for room,(occ,sens) in ROOMS.items():
    seen=set()
    for ts,st in series.get(occ,[]):
        key=int(ts//60)
        if key in seen: continue
        seen.add(key)
        pc=pcount(ts)
        if pc is None: continue
        son=[s for s in sens if is_on(s,ts)]
        occ_on=(st=="on")
        label=split=prov=None
        if pc>=1 and occ_on and len(son)>=2:
            label,split,prov="occupied","works",f"persons={pc}, occ on, {len(son)} sensors on"
        elif pc==0 and not occ_on:
            label,split,prov="empty","works",f"all away, occ off"
        elif pc==0 and occ_on and len(son)==1:
            label,split,prov="empty","fails",f"all away but occ held on by SINGLE sensor {son[0]} (phantom proxy)"
        else:
            continue
        cases.append({"case_id":f"{room}-{int(ts)}","room":room,
            "ts":datetime.fromtimestamp(ts,tz=timezone.utc).isoformat(),
            "features":{"room_occupied":occ_on,"sensors_on":len(son),"sensors_total":len(sens),
                "persons_in_house":pc,"house_state":at(HOUSE,ts),"driver_sensors":son},
            "label":label,"split":split,"label_provenance":prov})

# cap per (room,split,label) to keep balanced, and merge the confirmed anchor
from collections import Counter
cap=8; bucket=Counter(); kept=[]
for c in cases:
    k=(c["room"],c["split"],c["label"])
    if bucket[k]<cap: bucket[k]+=1; kept.append(c)
try:
    for ln in open("docs/planning/jev_spike/eval_set.confirmed.jsonl"):
        if ln.strip(): kept.append(json.loads(ln))
except FileNotFoundError: pass
open("docs/planning/jev_spike/eval_set.jsonl","w").write("\n".join(json.dumps(c) for c in kept)+"\n")
sc=Counter((c["split"],c["label"]) for c in kept)
print("TOTAL cases:",len(kept))
for k,v in sorted(sc.items()): print(f"  {k[0]:6} {k[1]:9} {v}")
