import sqlite3,json,datetime
h=sqlite3.connect("file:/config/home-assistant_v2.db?mode=ro",uri=True)
def t(x): return datetime.datetime.fromtimestamp(x,datetime.timezone.utc).strftime('%m-%d %H:%M:%S')
rows=h.execute("select metadata_id,entity_id from states_meta where entity_id like '%envoy_stream%'").fetchall()
for mid,e in rows:
    c=h.execute("select count(*),sum(state='unavailable'),min(last_updated_ts),max(last_updated_ts) from states where metadata_id=?",(mid,)).fetchone()
    last=h.execute("select state,last_updated_ts from states where metadata_id=? order by last_updated_ts desc limit 1",(mid,)).fetchone()
    print(e,c[0],c[1],t(c[2]) if c[2] else None,last)
d=json.load(open("/config/.storage/core.restore_state"))
for x in d["data"]:
    if 'envoy_stream' in x["state"]["entity_id"] or 'reserve' in x["state"]["entity_id"] and 'envoy' in x["state"]["entity_id"] or 'iq_battery_hacs_battery_reserve' in x["state"]["entity_id"]:
        print(x["state"]["entity_id"],x["state"]["state"],x["state"]["last_updated"])
er=json.load(open("/config/.storage/core.entity_registry"))
for x in er["data"]["entities"]:
    if x["entity_id"]=="sensor.envoy_stream_backup_reserve": print(x)
