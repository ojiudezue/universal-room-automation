import sqlite3, json, statistics as st, collections
from datetime import datetime
c=sqlite3.connect("file:/config/home-assistant_v2.db?mode=ro",uri=True)
ZON=["climate.thermostat_bryant_wifi_studyb_zone_1","climate.up_hallway_zone_2","climate.back_hallway_zone_3"]
ACT={"cooling","heating"}
for THRESH in (10.0,):
    for z in ZON:
        r=c.execute("SELECT metadata_id FROM states_meta WHERE entity_id=?",(z,)).fetchone()
        if not r: continue
        prev=None;start=None;per=collections.Counter();tot=collections.Counter()
        for ts,attrs in c.execute("SELECT s.last_updated_ts, sa.shared_attrs FROM states s LEFT JOIN state_attributes sa "
                "ON s.attributes_id=sa.attributes_id WHERE s.metadata_id=? ORDER BY s.last_updated_ts",(r[0],)):
            if not attrs: continue
            try: a=json.loads(attrs).get("hvac_action")
            except Exception: continue
            act=a in ACT
            if prev is None: prev=act; start=ts if act else None; continue
            if act and not prev: start=ts
            elif prev and not act and start is not None:
                d=(ts-start)/60.0; day=datetime.fromtimestamp(start).strftime("%m-%d")
                if d>0:
                    tot[day]+=1
                    if d<THRESH: per[day]+=1
                start=None
            prev=act
        days=sorted(tot)
        vals=[per[d] for d in days]
        if len(vals)<4: continue
        m=st.mean(vals); sd=st.pstdev(vals) or 0.1
        name=z.split('.')[-1][:26]
        print(f"{name:27} sub-{THRESH:.0f}min/day: {vals}  mean={m:.2f} std={sd:.2f}")
        print(f"{'':27} z if a day had 8: {(8-m)/sd:5.2f}   if 12: {(12-m)/sd:5.2f}   total cycles/day: {[tot[d] for d in days]}")
