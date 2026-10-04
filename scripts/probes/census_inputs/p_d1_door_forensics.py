"""P-D1 door-event forensics 2026-10-03 (PLANNING_census_inputs_first.md §2). READ-ONLY.
Run: ssh ha "python3 -" < p_d1_door_forensics.py
"""
import sqlite3, datetime as dt, bisect
from collections import defaultdict, Counter

REC = 'file:/config/home-assistant_v2.db?mode=ro'
URA = 'file:/config/universal_room_automation/data/universal_room_automation.db?mode=ro'
r = sqlite3.connect(REC, uri=True); u = sqlite3.connect(URA, uri=True)
CDT = -5 * 3600
A = dt.datetime(2026, 10, 3, 5, tzinfo=dt.timezone.utc).timestamp(); B = A + 86400
def loc(ts): return dt.datetime.fromtimestamp(ts + CDT, dt.timezone.utc).strftime('%H:%M:%S')
def hist(eid, a=A - 3600, b=B + 3600):
    return r.execute("select s.state,s.last_updated_ts from states s join states_meta m using(metadata_id) "
                     "where m.entity_id=? and s.last_updated_ts between ? and ? order by 2", (eid, a, b)).fetchall()
def on_edges(eid):
    out, prev = [], None
    for st, t in hist(eid):
        on = st == 'on' or (st.isdigit() and int(st) > 0)
        if on and prev is False: out.append(t)
        prev = on if st not in ('unavailable', 'unknown') else prev
    return out

GROUP = {'front_door_aerial': 'front', 'madrone_g6_entry': 'front', 'doorbell_lite': 'garage_a',
         'garage_a': 'garage_a', 'garage_b': 'garage_b'}
def cam_of(e):
    for k in GROUP:
        if k in e: return k
    return e

# ledger
L = []
for ts, pid, d, cam, conf in u.execute("select timestamp,person_id,direction,egress_camera,confidence from person_entry_exit_events "
                                       "where timestamp between ? and ? order by timestamp",
                                       ('2026-10-03T05:00', '2026-10-04T05:00')):
    t = dt.datetime.fromisoformat(ts).replace(tzinfo=dt.timezone.utc).timestamp()
    L.append((t, pid, d, cam_of(cam)))
print(f"LEDGER 10-03 rows={len(L)} by cam/dir:", Counter((c, d) for _, _, d, c in L))
print("  person_id non-null:", Counter(p for _, p, _, _ in L if p))

# raw legs: on-edges of every egress sensor
SENS = {}
for c in GROUP:
    for suf in ('_person_detected', '_person_occupancy_2', '_person_occupancy'):
        SENS[f'binary_sensor.{c}{suf}'] = c
    for suf in ('_person_count', '_person_active_count_2'):
        SENS[f'sensor.{c}{suf}'] = c
raw = []
for e, c in SENS.items():
    for t in on_edges(e):
        if A <= t < B: raw.append((t, c, e))
raw.sort()
print(f"\nRAW egress on-edges 10-03: {len(raw)} by cam:", Counter(c for _, c, _ in raw))

# stem/door-group dedup simulation on raw legs
for W in (5, 15, 30, 60):
    for keyf, name in ((lambda c: c, 'stem'), (lambda c: GROUP[c], 'door_group')):
        last, n = {}, Counter()
        for t, c, _ in raw:
            k = keyf(c)
            if k in last and t - last[k] < W: continue
            last[k] = t; n[GROUP[c]] += 1
        print(f"  dedup {name:10s} W={W:>2}s survivors by door: {dict(n)}")

# interior fires
INT = ['family_room', 'foyer_fisheye', 'master_hallway', 'staircase', 'stairs_top', 'upstairs_hall', 'playroom']
iedges = []
for c in INT:
    for suf in ('_person_detected', '_person_occupancy', '_person_occupancy_2', '_person_count'):
        e = (f'sensor.{c}{suf}' if 'count' in suf else f'binary_sensor.{c}{suf}')
        iedges += [(t, c) for t in on_edges(e)]
for st, t in hist('binary_sensor.camera_protect_garagehallway_person_detected'):
    if st == 'on': iedges.append((t, 'garagehallway_protect'))
iedges.sort(); it = [x[0] for x in iedges]
def interior_in(t, w):
    i = bisect.bisect_left(it, t - w); s = set()
    while i < len(it) and it[i] <= t + w: s.add(iedges[i][1]); i += 1
    return s
# fraction of any 45 s window after a random leg containing an interior fire (direction degeneracy)
print("\nInterior on-edges 10-03:", Counter(c for t, c in iedges if A <= t < B))

# tracker edges
TRK = {'oji': ['person.oji_udezue', 'device_tracker.phalanxiphone15promax', 'device_tracker.iphone_oji_bermuda_tracker',
               'device_tracker.private_ble_device_8ce182', 'device_tracker.unifi_default_12_83_ec_78_6d_6c'],
       'jaya': ['person.jaya', 'device_tracker.jjs_iphone', 'device_tracker.iphone_jaya_bermuda_tracker',
                'device_tracker.private_ble_device_249050'],
       'ezinne': ['person.ezinne', 'device_tracker.ezinne_iphone', 'device_tracker.ezinne_iphone_bermuda_tracker']}
tedges = []
for who, ents in TRK.items():
    for e in ents:
        prev = None
        for st, t in hist(e):
            if st in ('unavailable', 'unknown'): continue
            h = st == 'home'
            if prev is not None and h != prev and A <= t < B:
                tedges.append((t, who, e.split('.')[1][:28], 'arr' if h else 'dep'))
            prev = h
tedges.sort(); tt = [x[0] for x in tedges]
def trk_in(t, w):
    i = bisect.bisect_left(tt, t - w); s = []
    while i < len(tt) and tt[i] <= t + w: s.append(tedges[i]); i += 1
    return s
print("\nTRACKER edges 10-03 (CDT):")
for t, who, e, k in tedges: print(f"  {loc(t)} {who:6s} {k} {e}")

def report(a_hhmm, b_hhmm, title):
    a = A + int(a_hhmm[:2]) * 3600 + int(a_hhmm[3:]) * 60; b = A + int(b_hhmm[:2]) * 3600 + int(b_hhmm[3:]) * 60
    print(f"\n=== {title} {a_hhmm}-{b_hhmm} ===")
    print(" RAW legs:")
    for t, c, e in raw:
        if a <= t <= b: print(f"   {loc(t)} {GROUP[c]:8s} {e}")
    print(" LEDGER rows (dir, pid, interior ±20/±60, tracker edges ±120/300/900):")
    for t, pid, d, c in L:
        if not (a <= t <= b): continue
        w = {W: [(who, k, int(x - t)) for x, who, _, k in trk_in(t, W)] for W in (120, 300, 900)}
        b_ = 'attributed(pid)' if pid else ('a:edge@' + str(min(W for W in w if w[W])) if any(w.values()) else 'b:no-edge')
        print(f"   {loc(t)} {GROUP.get(c, c):8s} {c:18s} {d:9s} pid={pid or '-':7s} int20={sorted(interior_in(t, 20))} "
              f"int60n={len(interior_in(t, 60))} trk900={sorted(set((who, k) for who, k, _ in w[900]))} -> {b_}")

report('11:30', '13:45', 'MIDDAY (truth: operator porch + operator+Jaya car out garage_a)')
report('13:45', '14:12', 'ACTUAL op+Jaya BLE departure 14:01-14:03')
report('14:10', '14:40', '14:22 8-GUEST FRONT ARRIVAL')
report('15:30', '15:50', 'operator return ~15:42')
report('22:55', '23:59', 'LATE (visitor out 23:00 front; op+Jaya back ~23:24 garage_a; guest out 23:55 front)')

# 14:22 multiplicity
print("\n14:22 person_count timeline (front cams + doorbell_lite):")
a = A + 14 * 3600 + 10 * 60; b = A + 14 * 3600 + 40 * 60
for c in ('front_door_aerial', 'madrone_g6_entry', 'doorbell_lite'):
    for e in (f'sensor.{c}_person_count', f'sensor.{c}_person_active_count_2'):
        seq = [(loc(t), s) for s, t in hist(e, a, b)]
        print(f"  {e}: {seq}")
# distinct peaks: count local maxima >=1 of max-across-cams
