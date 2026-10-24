import sqlite3
h=sqlite3.connect("file:/config/home-assistant_v2.db?mode=ro",uri=True)
print([r[0] for r in h.execute("select name from sqlite_master where type='table'")])
print(h.execute("select min(last_updated_ts),max(last_updated_ts) from states").fetchall())
for e in ['sensor.envoy_stream_backup_reserve','number.iq_battery_hacs_battery_reserve','sensor.envoy_482543015950_reserve_battery_level','sensor.iq_gateway_hacs_system_profile_status']:
    r=h.execute("select metadata_id from states_meta where entity_id=?",(e,)).fetchall()
    print(e,r)
    if r:
        mid=r[0][0]
        print(h.execute("select count(*),min(last_updated_ts),max(last_updated_ts) from states where metadata_id=?",(mid,)).fetchall())
        print(h.execute("select s.state,s.last_updated_ts,s.attributes_id from states s where metadata_id=? order by last_updated_ts desc limit 3",(mid,)).fetchall())
print([r[0] for r in h.execute("select entity_id from states_meta where entity_id like '%soc%' or entity_id like '%battery%' limit 60")])
u=sqlite3.connect("file:/config/universal_room_automation/data/universal_room_automation.db?mode=ro",uri=True)
print([r[0] for r in u.execute("select name from sqlite_master where type='table'")])
