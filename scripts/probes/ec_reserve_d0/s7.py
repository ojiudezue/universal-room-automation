import sqlite3,json,datetime
h=sqlite3.connect("file:/config/home-assistant_v2.db?mode=ro",uri=True)
u=sqlite3.connect("file:/config/universal_room_automation/data/universal_room_automation.db?mode=ro",uri=True)
print([(r[1]) for r in u.execute("pragma table_info(evse_state)")])
print(u.execute("select * from evse_state limit 2").fetchall())
print([r[0] for r in h.execute("select entity_id from states_meta where (entity_id like '%evse%' or entity_id like '%charger%' or entity_id like '%iq_ev%' or entity_id like '%ura_energy%hold%') and (entity_id like 'sensor.%' or entity_id like 'binary_sensor.%') ")][:60])
