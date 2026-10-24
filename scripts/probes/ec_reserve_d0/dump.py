import sqlite3,json
h=sqlite3.connect("file:/config/home-assistant_v2.db?mode=ro",uri=True)
out={}
def series(e,attrs=False):
    mid=h.execute("select metadata_id from states_meta where entity_id=?",(e,)).fetchone()[0]
    q="select s.state,s.last_updated_ts,a.shared_attrs from states s left join state_attributes a on s.attributes_id=a.attributes_id where s.metadata_id=? order by s.last_updated_ts"
    return [(r[0],r[1],r[2] if attrs else None) for r in h.execute(q,(mid,))]
for k,e in [('cloud','number.iq_battery_hacs_battery_reserve'),('local','sensor.envoy_482543015950_reserve_battery_level'),('enpower','number.enpower_482348004678_reserve_battery_level'),('soc','sensor.envoy_482543015950_battery')]:
    out[k]=series(e)
out['profile']=series('sensor.iq_gateway_hacs_system_profile_status',True)
u=sqlite3.connect("file:/config/universal_room_automation/data/universal_room_automation.db?mode=ro",uri=True)
out['rw']=[(r[0],r[1]) for r in u.execute("select timestamp,details_json from ura_activity_log where action='reserve_write' order by id")]
out['anom']=u.execute("select timestamp,coordinator_id,metric_name,event_class,anomaly_type,severity,context_json from anomaly_log where timestamp>='2026-10-16'").fetchall()
out['notif']=u.execute("select * from notification_log where timestamp>='2026-10-16'").fetchall()
out['nlcols']=[r[1] for r in u.execute("pragma table_info(notification_log)")]
out['soc_meta']=h.execute("select state from states where metadata_id=(select metadata_id from states_meta where entity_id='sensor.envoy_482543015950_battery') order by last_updated_ts desc limit 3").fetchall()
json.dump(out,open('/tmp/dump.json','w'))
print(json.dumps(out))
