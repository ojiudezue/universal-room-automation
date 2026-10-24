import sqlite3,json
h=sqlite3.connect("file:/config/home-assistant_v2.db?mode=ro",uri=True)
out={}
for k,e in [('ga','sensor.span_panel_garage_a_evse_power'),('gb','sensor.span_panel_garage_b_evse_power'),('l1a','binary_sensor.ura_energy_coordinator_l1_charger_garage_a'),('disch','sensor.envoy_482543015950_current_battery_discharge')]:
    mid=h.execute("select metadata_id from states_meta where entity_id=?",(e,)).fetchone()[0]
    out[k]=[(r[0],r[1]) for r in h.execute("select state,last_updated_ts from states where metadata_id=? and last_updated_ts>=1792240000 order by last_updated_ts",(mid,))]
print(json.dumps(out))
