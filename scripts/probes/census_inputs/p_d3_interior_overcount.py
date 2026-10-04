"""P-D3 interior camera over-count 10:00-11:15 CDT 2026-10-03 (PLANNING_census_inputs_first.md §2). READ-ONLY.
Run: ssh ha "python3 -" < p_d3_interior_overcount.py
"""
import sqlite3, datetime as dt, json, bisect
from collections import Counter
r = sqlite3.connect('file:/config/home-assistant_v2.db?mode=ro', uri=True)
CDT = -5 * 3600
A = dt.datetime(2026, 10, 3, 5, tzinfo=dt.timezone.utc).timestamp()
W0, W1 = A + 10 * 3600, A + 11.25 * 3600
def loc(ts): return dt.datetime.fromtimestamp(ts + CDT, dt.timezone.utc).strftime('%H:%M')
def hist(eid, a, b):
    rows = r.execute("select s.state,s.last_updated_ts from states s join states_meta m using(metadata_id) "
                     "where m.entity_id=? and s.last_updated_ts between ? and ? order by 2", (eid, a, b)).fetchall()
    prev = r.execute("select s.state,s.last_updated_ts from states s join states_meta m using(metadata_id) "
                     "where m.entity_id=? and s.last_updated_ts < ? order by 2 desc limit 1", (eid, a)).fetchall()
    return prev + rows
cfg = [e for e in json.load(open('/config/.storage/core.config_entries'))['data']['entries']
       if e['domain'] == 'universal_room_automation' and e['title'] == 'Universal Room Automation'][0]
cams = {**cfg.get('data', {}), **cfg.get('options', {})}.get('camera_person_entities', [])
stems = sorted({c.split('.')[1].replace('_high_resolution_channel', '') for c in cams})
print("configured interior camera stems:", stems)

def series(eid):
    h = hist(eid, W0 - 3600, W1)
    t = [x[1] for x in h]; v = []
    for s, _ in h:
        try: v.append(int(float(s)))
        except Exception: v.append(None)
    return t, v
grid = list(range(int(W0), int(W1), 15))
S = {}
for st in stems:
    for e in (f'sensor.{st}_person_count', f'sensor.{st}_person_active_count_2'):
        t, v = series(e)
        if len(t) > 1 or (t and v[0]):
            S[e] = [v[bisect.bisect_right(t, g) - 1] if bisect.bisect_right(t, g) else None for g in grid]
            break
print("\ncount source per stem:", list(S))
print("\nper-camera over 10:00-11:15 (15 s grid): %>0, %>1, max, mean when >0")
for e, vs in S.items():
    xs = [x or 0 for x in vs]; pos = [x for x in xs if x > 0]
    print(f"  {e:45s} >0={100*len(pos)/len(xs):5.1f}% >1={100*sum(x>1 for x in xs)/len(xs):5.1f}% max={max(xs)} "
          f"mean>0={sum(pos)/len(pos) if pos else 0:.2f}")
tot = [sum((S[e][i] or 0) for e in S) for i in range(len(grid))]
print("\nsum-across-cams distribution (truth=3 home; guest OUT):", sorted(Counter(tot).items()))
print("per-minute max of sum:", [(loc(grid[i]), max(tot[i:i+4])) for i in range(0, len(grid), 4) if max(tot[i:i+4]) > 3])
print("\npairwise co-occurrence (both >0) as % of grid points; J = both / either")
es = list(S)
for i in range(len(es)):
    for j in range(i + 1, len(es)):
        a = [(x or 0) > 0 for x in S[es[i]]]; b = [(x or 0) > 0 for x in S[es[j]]]
        both = sum(x and y for x, y in zip(a, b)); either = sum(x or y for x, y in zip(a, b))
        if both: print(f"  {es[i].split('.')[1][:22]:22s} & {es[j].split('.')[1][:22]:22s} both={100*both/len(a):5.1f}% J={both/either:.2f}")
# contribution to >3 inflation: which cams are >0 when sum>3
print("\nwhen sum>3: share of grid points each cam is >0:")
idx = [i for i, x in enumerate(tot) if x > 3]
for e in es:
    print(f"  {e:45s} {100*sum((S[e][i] or 0) > 0 for i in idx)/max(len(idx),1):5.1f}%  mean={sum((S[e][i] or 0) for i in idx)/max(len(idx),1):.2f}")
print(f"  (n grid points with sum>3: {len(idx)} of {len(grid)})")
# URA's own census sensor in window
for e in ('sensor.universal_room_automation_persons_in_house',):
    print("\n", e, Counter(s for s, _ in hist(e, W0, W1)).most_common(8))
