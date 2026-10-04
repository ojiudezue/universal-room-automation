import sqlite3,json
r=sqlite3.connect('file:/config/home-assistant_v2.db?mode=ro',uri=True)
q="""select et.event_type,e.time_fired_ts from events e join event_types et using(event_type_id) where et.event_type in ('homeassistant_stop','homeassistant_start','homeassistant_final_write','homeassistant_started') order by 2"""
import datetime as d
for t,ts in r.execute(q): print(t,d.datetime.utcfromtimestamp(ts-5*3600))
for p in ['person.ezinne','person.oji_udezue','person.jaya','person.ziri']:
    print(p,[(s,d.datetime.utcfromtimestamp(ts-18000).strftime('%m-%d %H:%M')) for s,ts in r.execute("select state,last_updated_ts from states join states_meta using(metadata_id) where entity_id=? and last_updated_ts>1791003600 and (last_changed_ts is null or last_changed_ts=last_updated_ts) order by 2",(p,))])
