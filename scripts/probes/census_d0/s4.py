import json
er=json.load(open('/config/.storage/core.entity_registry'))['data']['entities']
dr={d['id']:d for d in json.load(open('/config/.storage/core.device_registry'))['data']['devices']}
ar={a['id']:a['name'] for a in json.load(open('/config/.storage/core.area_registry'))['data']['areas']}
for e in er:
    if e['entity_id'].endswith('_person_count') or e['entity_id'].startswith('camera.'):
        a=e.get('area_id') or (dr.get(e.get('device_id'),{}) or {}).get('area_id')
        if any(k in e['entity_id'] for k in ['family_room','foyer','master_hall','staircase','stairs_top','playroom','upstairs_hall','garage','madrone_g6','doorbell','front_door_aerial']):
            print(e['entity_id'],e['platform'],ar.get(a))
