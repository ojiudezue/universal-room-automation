import sqlite3, json, time, sys, datetime as dt
def emit(o):
    print(json.dumps(o), flush=True)
DB="file:/config/home-assistant_v2.db?mode=ro"
Z={"zone_1":("sensor.span_panel_ac1_power","climate.thermostat_bryant_wifi_studyb_zone_1",1500),
   "zone_3":("sensor.span_panel_ac_3_power","climate.back_hallway_zone_3",2200),
   "zone_2":("sensor.span_panel_ac_2_power","climate.up_hallway_zone_2",2200)}
def latest(c, ent, attr=None):
    r=c.execute("SELECT metadata_id FROM states_meta WHERE entity_id=?",(ent,)).fetchone()
    if not r: return None
    if attr is None:
        q=c.execute("""SELECT state FROM states WHERE metadata_id=? AND state NOT IN
                       ('unknown','unavailable') ORDER BY last_updated_ts DESC LIMIT 1""",(r[0],)).fetchone()
        return float(q[0]) if q else None
    q=c.execute("""SELECT sa.shared_attrs FROM states s LEFT JOIN state_attributes sa
                   ON s.attributes_id=sa.attributes_id WHERE s.metadata_id=? AND sa.shared_attrs IS NOT NULL
                   ORDER BY s.last_updated_ts DESC LIMIT 1""",(r[0],)).fetchone()
    if not q: return None
    try: return json.loads(q[0]).get(attr)
    except Exception: return None
streak={k:0 for k in Z}
deadline=time.time()+21600
while time.time()<deadline:
    c=sqlite3.connect(DB,uri=True)
    for z,(pw,cl,thr) in Z.items():
        p=latest(c,pw); a=latest(c,cl,"hvac_action")
        if p is not None and p>thr and a!="cooling":
            streak[z]+=1
            if streak[z]>=3:
                emit({"BLIND":True,"zone":z,"power":p,"hvac_action":a,
                    "conditioning":latest(c,cl,"conditioning"),"blower_rpm":latest(c,cl,"blower_rpm"),
                    "temp":latest(c,cl,"current_temperature"),"target":latest(c,cl,"target_temp_high"),
                    "climate_entity":cl,"at":dt.datetime.now().isoformat()})
                sys.exit(0)
        else:
            streak[z]=0
    c.close(); time.sleep(40)
emit({"BLIND":False,"note":"no blind episode within 6h window"})
sys.exit(1)
