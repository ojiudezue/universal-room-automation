import sqlite3,json
ce=json.load(open('/config/.storage/core.config_entries'))['data']['entries']
for e in ce:
    if e['domain']!='universal_room_automation':continue
    m={**e['data'],**e['options']}
    if m.get('room_is_guest_room') or 'uest' in e['title']:
        print(e['title'],m.get('room_is_guest_room'),m.get('occupancy_sensors') or m.get('motion_sensors'),m.get('mmwave_sensors'))
    if m.get('entry_type')=='integration': print('INTEG',{k:v for k,v in m.items() if 'guest' in k or 'egress' in k or 'tracked' in k})
r=sqlite3.connect('file:/config/home-assistant_v2.db?mode=ro',uri=True)
for e in ['sensor.iphone_oji_area','sensor.ezinne_iphone_area','sensor.iphone_jaya_area']:
    print(e,r.execute("select s.state,count(*) from states s join states_meta m using(metadata_id) where m.entity_id=? group by 1 order by 2 desc limit 25",(e,)).fetchall())
