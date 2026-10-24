import sqlite3,datetime,json
h=sqlite3.connect("file:/config/home-assistant_v2.db?mode=ro",uri=True)
def t(x): return datetime.datetime.utcfromtimestamp(x).strftime('%m-%d %H:%M:%S')
for e in ['sensor.envoy_stream_backup_reserve','number.iq_battery_hacs_battery_reserve','sensor.envoy_482543015950_reserve_battery_level']:
    print("==",e)
    mid=h.execute("select metadata_id from states_meta where entity_id=?",(e,)).fetchone()[0]
    for s,ts in h.execute("select state,last_updated_ts from states where metadata_id=? order by last_updated_ts",(mid,)):
        print(t(ts),s)
print([r for r in h.execute("select entity_id from states_meta where entity_id like '%soc%' or entity_id like 'sensor.envoy%batt%' or entity_id like '%battery_level%' or entity_id like '%state_of_charge%' or entity_id like '%available_battery%'")][:40])
