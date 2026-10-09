import json, sqlite3, time, collections
reg = json.load(open('/config/.storage/core.entity_registry'))['data']['entities']
dc = {}
for e in reg:
    if e['entity_id'].startswith('binary_sensor.') and not e.get('disabled_by'):
        c = e.get('device_class') or e.get('original_device_class')
        if c: dc[e['entity_id']] = c
db = sqlite3.connect('file:/config/home-assistant_v2.db?mode=ro', uri=True)
meta = {r[1]: r[0] for r in db.execute("select metadata_id, entity_id from states_meta where entity_id like 'binary_sensor.%'")}
now = time.time(); since = now - 7*86400
per = collections.defaultdict(list)   # class -> list of (entity, max_on_h, max_off_h, n_changes)
for eid, cls in dc.items():
    mid = meta.get(eid)
    if mid is None: continue
    rows = db.execute("select state, last_changed_ts, last_updated_ts from states where metadata_id=? and last_updated_ts>? order by last_updated_ts", (mid, since)).fetchall()
    rows = [(s if s in ('on','off') else 'na', lc or lu) for s, lc, lu in rows]
    if not rows: continue
    # collapse to transitions
    tr = []
    for s, t in rows:
        if not tr or tr[-1][0] != s: tr.append((s, t))
    mx = {'on': 0.0, 'off': 0.0, 'na': 0.0}
    for i, (s, t) in enumerate(tr):
        end = tr[i+1][1] if i+1 < len(tr) else now
        mx[s] = max(mx[s], (end - max(t, since))/3600)
    per[cls].append((eid, round(mx['on'], 1), round(mx['off'], 1), len(tr)))
def pct(v, p):
    v = sorted(v); return v[min(len(v)-1, int(p*len(v)))] if v else None
print("class | n | p50/p90/max longest-ON h | p50/p90/max longest-OFF h | sensors never changed in 7d")
for cls, L in sorted(per.items(), key=lambda x: -len(x[1])):
    on = [x[1] for x in L]; off = [x[2] for x in L]
    never = sum(1 for x in L if x[3] == 1)
    print(f"{cls} | {len(L)} | {pct(on,.5)}/{pct(on,.9)}/{max(on)} | {pct(off,.5)}/{pct(off,.9)}/{max(off)} | {never}")
for cls in ('motion', 'occupancy', 'presence'):
    L = sorted(per.get(cls, []), key=lambda x: -x[1])[:6]
    print(f"top longest-ON {cls}:", [(e.split('.')[1][:45], h) for e, h, _, _ in L])
