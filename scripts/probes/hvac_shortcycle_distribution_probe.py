import sqlite3, json, statistics as st, math
c=sqlite3.connect("file:/config/home-assistant_v2.db?mode=ro",uri=True)
ZON=["climate.thermostat_bryant_wifi_studyb_zone_1","climate.up_hallway_zone_2","climate.back_hallway_zone_3"]
ACT={"cooling","heating"}
for z in ZON:
    r=c.execute("SELECT metadata_id FROM states_meta WHERE entity_id=?",(z,)).fetchone()
    if not r: continue
    prev=None;start=None;durs=[]
    for ts,attrs in c.execute("SELECT s.last_updated_ts, sa.shared_attrs FROM states s LEFT JOIN state_attributes sa "
            "ON s.attributes_id=sa.attributes_id WHERE s.metadata_id=? ORDER BY s.last_updated_ts",(r[0],)):
        if not attrs: continue
        try: a=json.loads(attrs).get("hvac_action")
        except Exception: continue
        act=a in ACT
        if prev is None: prev=act; start=ts if act else None; continue
        if act and not prev: start=ts
        elif prev and not act and start is not None:
            d=(ts-start)/60.0
            if d>0: durs.append(d)
            start=None
        prev=act
    if len(durs)<10: continue
    m=st.mean(durs); sd=st.pstdev(durs)
    lm=st.mean([math.log(d) for d in durs]); lsd=st.pstdev([math.log(d) for d in durs])
    name=z.split('.')[-1][:26]
    print(f"{name:27} n={len(durs):3} mean={m:5.1f} std={sd:5.1f}  RAW z(5min)={(5-m)/sd:6.2f}  z(3min)={(3-m)/sd:6.2f}")
    print(f"{'':27} log-space: mu={lm:.2f} sd={lsd:.2f}  LOG z(5min)={(math.log(5)-lm)/lsd:6.2f}  z(3min)={(math.log(3)-lm)/lsd:6.2f}")
