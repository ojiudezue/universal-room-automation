import sqlite3, collections, statistics as st
c=sqlite3.connect("file:/config/home-assistant_v2.db?mode=ro",uri=True)
ZON=["climate.thermostat_bryant_wifi_studyb_zone_1","climate.up_hallway_zone_2","climate.back_hallway_zone_3"]
ACTIVE={"cooling","heating"}
for z in ZON:
    r=c.execute("SELECT metadata_id FROM states_meta WHERE entity_id=?",(z,)).fetchone()
    if not r: print(z,"NOT FOUND"); continue
    rows=[]
    q=("SELECT s.last_updated_ts, sa.shared_attrs FROM states s LEFT JOIN state_attributes sa "
       "ON s.attributes_id=sa.attributes_id WHERE s.metadata_id=? ORDER BY s.last_updated_ts")
    import json
    prev=None; start=None; durs=[]
    for ts,attrs in c.execute(q,(r[0],)):
        if not attrs: continue
        try: a=json.loads(attrs).get("hvac_action")
        except Exception: continue
        act = a in ACTIVE
        if prev is None: prev=act; start=ts if act else None; continue
        if act and not prev: start=ts
        elif prev and not act and start is not None:
            durs.append((ts-start)/60.0); start=None
        prev=act
    if not durs: print(f"{z.split('.')[-1]}: no complete cycles"); continue
    durs=[d for d in durs if d>0]
    u5=[d for d in durs if d<5]; u10=[d for d in durs if d<10]
    print(f"{z.split('.')[-1]:34} cycles={len(durs):4}  median={st.median(durs):6.1f}m  "
          f"<5min={len(u5):3} ({100*len(u5)/len(durs):4.1f}%)  <10min={len(u10):3} ({100*len(u10)/len(durs):4.1f}%)")
