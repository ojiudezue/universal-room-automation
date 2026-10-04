"""D0 census estimator replay (PLANNING_census_occupancy_estimator.md §8). READ-ONLY.
Run: ssh ha "python3 -" < census_estimator_replay.py
All DBs opened ?mode=ro; .storage read with open(...,'r'). Writes nothing.
"""
import sqlite3, json, bisect, re, statistics as st, datetime as dt
from collections import defaultdict, Counter

REC = 'file:/config/home-assistant_v2.db?mode=ro'
URA = 'file:/config/universal_room_automation/data/universal_room_automation.db?mode=ro'
CDT = -5 * 3600
r = sqlite3.connect(REC, uri=True)
u = sqlite3.connect(URA, uri=True)

def loc(ts):  # CDT string
    return dt.datetime.fromtimestamp(ts + CDT, dt.timezone.utc).strftime('%m-%d %H:%M')

T0 = r.execute("select min(last_updated_ts) from states").fetchone()[0]
T1 = r.execute("select max(last_updated_ts) from states").fetchone()[0]
D3a = dt.datetime(2026, 10, 3, 5, 0, tzinfo=dt.timezone.utc).timestamp()  # 10-03 00:00 CDT
D3b = D3a + 86400

def hist(eid, attrs=False):
    q = ("select s.state, s.last_updated_ts, coalesce(s.last_changed_ts, s.last_updated_ts)"
         + (", a.shared_attrs" if attrs else "") +
         " from states s join states_meta m on s.metadata_id=m.metadata_id"
         + (" left join state_attributes a on s.attributes_id=a.attributes_id" if attrs else "") +
         " where m.entity_id=? order by s.last_updated_ts")
    return r.execute(q, (eid,)).fetchall()

class Series:
    def __init__(self, rows, f):
        self.t = [x[1] for x in rows]; self.v = [f(x[0]) for x in rows]
    def at(self, ts, default=None):
        i = bisect.bisect_right(self.t, ts) - 1
        return self.v[i] if i >= 0 else default
    def maxin(self, a, b, default=0):
        i = max(bisect.bisect_right(self.t, a) - 1, 0); best = self.at(a, default) or 0
        while i < len(self.t) and self.t[i] <= b:
            if self.t[i] >= a and self.v[i] is not None: best = max(best, self.v[i])
            i += 1
        return best

def num(s):
    try: return int(float(s))
    except: return 0
def onoff(s): return 1 if s == 'on' else 0

# ---------------- entities
INTERIOR = ['family_room', 'foyer_fisheye', 'master_hallway', 'staircase', 'stairs_top', 'playroom', 'upstairs_hall']
CAM_AREA = {'family_room': 'Living Room', 'foyer_fisheye': 'Entry Way', 'master_hallway': 'Master Hallway',
            'staircase': 'Garage Hallway', 'stairs_top': 'Stairs', 'playroom': 'Game Room', 'upstairs_hall': 'Upstairs Hallway'}
DOORS = {'front': ['madrone_g6_entry', 'front_door_aerial', 'g4_doorbell_pro'], 'garageA': ['garage_a', 'doorbell_lite'], 'garageB': ['garage_b']}
STEM2DOOR = {s: d for d, l in DOORS.items() for s in l}
cnt = {c: Series(hist(f'sensor.{c}_person_count'), num) for c in INTERIOR}
dcnt = {c: Series(hist(f'sensor.{c}_person_count'), num) for c in ['madrone_g6_entry', 'front_door_aerial', 'garage_a', 'doorbell_lite', 'garage_b']}
PERS = {'ezinne': 'person.ezinne', 'oji': 'person.oji_udezue', 'jaya': 'person.jaya', 'ziri': 'person.ziri'}
pers = {k: Series(hist(v), lambda s: 1 if s == 'home' else 0) for k, v in PERS.items()}
AREA = {'oji': 'sensor.iphone_oji_area', 'ezinne': 'sensor.ezinne_iphone_area', 'jaya': 'sensor.iphone_jaya_area'}
area = {k: Series(hist(v), lambda s: s) for k, v in AREA.items()}
GR = {'Guest Bedroom 1': ['binary_sensor.occupancy_lux_temp_humidity_hobeian_downguestroom_presence_2',
                          'binary_sensor.smart_presence_sensor_24111917146201662002c4e7ae109bd3_sensor_presence_motion'],
      'Guest Bedroom 2': ['binary_sensor.mmwave_motion_lux_matter_wifi_guestbedroom2_occupancy']}
gr = {k: [Series(hist(e), onoff) for e in v] for k, v in GR.items()}
legacy = Series(hist('sensor.universal_room_automation_persons_in_house'), num)
guestmode = Series(hist('binary_sensor.ura_presence_coordinator_guest_mode'), onoff)
hs = Series(hist('sensor.ura_presence_coordinator_presence_house_state'), lambda s: s)

# ---------------- Revel trackers (replicates camera_census._get_wifi_guest_count)
src = open('/config/custom_components/universal_room_automation/const.py').read()
def tup(name):
    m = re.search(name + r': Final = \((.*?)\n\)', src, re.S)
    return tuple(re.findall(r'"([^"]+)"', m.group(1)))
NONG, TAB = tup('NON_GUEST_HOSTNAME_PREFIXES'), tup('TABLET_HOSTNAME_PREFIXES')
er = json.load(open('/config/.storage/core.entity_registry'))['data']['entities']
dev_of = {e['entity_id']: e.get('device_id') for e in er}
by_dev = defaultdict(list)
for e in er:
    if e['entity_id'].startswith('device_tracker.') and e.get('device_id'): by_dev[e['device_id']].append(e['entity_id'])
fam = set()
for p in PERS.values():
    row = hist(p, attrs=True)[-1]
    a = json.loads(row[3] or '{}'); fam.update(a.get('device_trackers', []));
    if a.get('source'): fam.add(a['source'])
for t in list(fam):
    if dev_of.get(t): fam.update(by_dev[dev_of[t]])
fam_mac = set()
for t in fam:
    h = hist(t, attrs=True)
    for row in h[-50:]:
        m = json.loads(row[3] or '{}').get('mac')
        if m: fam_mac.add(m.lower())
SKIP_REVEL = True  # hybrid replay excludes Revel (operator ruling 5)
rev_eids = [] if SKIP_REVEL else [e for (e,) in r.execute("""select distinct m.entity_id from states s join states_meta m on s.metadata_id=m.metadata_id
   join state_attributes a on s.attributes_id=a.attributes_id where a.shared_attrs like '%"essid":"Revel"%'""")]
revel = {}
for e in rev_eids:
    rows = []
    for st_, lu, lc, at in hist(e, attrs=True):
        a = json.loads(at or '{}')
        rows.append((lu, st_, lc, a))
    revel[e] = rows
def w_at(ts, recency_h=4):
    n = 0; nr = 0; names = []
    for e, rows in revel.items():
        i = bisect.bisect_right(revel_ts[e], ts) - 1
        if i < 0: continue
        lu, s, lc, a = rows[i]
        if s != 'home' or a.get('source_type') != 'router' or a.get('essid') != 'Revel': continue
        hn = (a.get('host_name') or '').lower()
        if not hn or hn.startswith(NONG) or hn.startswith(TAB): continue
        if e in fam or (a.get('mac', '').lower() in fam_mac): continue
        nr += 1; names.append(hn)
        if recency_h is None or ts - lc <= recency_h * 3600: n += 1
    return n, nr, names
# precompute per-minute W (cache rows' ts lists)
revel_ts = {e: [x[0] for x in rows] for e, rows in revel.items()}

# ---------------- door events (URA ledger, naive UTC)
def stem(eid):
    s = eid.split('.', 1)[1]
    s = re.sub(r'(_person_detected|_person_occupancy|_person_count)(_2)?$', '', s)
    return re.sub(r'_2$', '', s)
ev = []
for ts, pid, d, cam in u.execute("select timestamp, person_id, direction, egress_camera from person_entry_exit_events order by timestamp"):
    t = dt.datetime.fromisoformat(ts).replace(tzinfo=dt.timezone.utc).timestamp()
    if t < T0: continue
    sm = stem(cam); ev.append(dict(t=t, pid=pid, d=d, cam=cam, stem=sm, door=STEM2DOOR.get(sm, sm)))
out = []
P = out.append

def collapse(evs, w, key):
    kept = []; merged = []
    last = {}
    for e in evs:
        k = (e[key], e['d'])
        if k in last and e['t'] - last[k]['t0'] <= w:
            last[k]['legs'].append(e); merged.append((last[k], e)); continue
        c = dict(e); c['t0'] = e['t']; c['legs'] = [e]; kept.append(c); last[k] = c
    return kept, merged

# ===================== HYBRID FLOOR REPLAY (PLANNING §0/§4.3/§7/§8.2) =====================
# FLOOR = R + max(0, max(M_cam - R, 0), U_gr, T)   ;   ESTIMATE = FLOOR + B
# Per-event door pipeline: leg-collapse(30 s, stem) -> same-person(10 s, door_group)
#   -> round-trip(180 s, unattributed, same door_group) -> resident attribution
#   (pid | tracker edge +-120 s, one edge per crossing | main-entry prior garage_a 300 s,
#   provisional, reversed into T on expiry) -> T accounting (unattributed only).
# Revel EXCLUDED. Overlap groups = {family_room, master_hallway}. Empty anchor = R=0 & M_cam=0 & U_gr=0 held 900 s.
HYBRID_ONLY = True
VARIANTS_ONLY = False  # set True (or env VARIANTS_ONLY=1) for the sensitivity table only
RES = {'ezinne': 'ezinne', 'oji udezue': 'oji', 'oji': 'oji', 'ojini': 'oji', 'jaya': 'jaya', 'ziri': 'ziri'}
KN = dict(FLOOR_WINDOW_S=1200, FLOOR_SHRINK_HOLD_S=600, SHRINK_WINDOW_S=180, DOOR_ROUNDTRIP_S=180,
          DOOR_SAMEPERSON_S=10, STEM_DEDUP_S=30, DOOR_TALLY_STALE_S=3600, AMBIGUOUS_DECAY_S=1800,
          RESIDENT_CROSSING_MATCH_S=120, MAIN_ENTRY_PRIOR_S=300, EMPTY_ANCHOR_SETTLE_S=900,
          BOOT_SETTLE_S=600, DOOR_TALLY_MAX=30, ESTIMATE_DECAY_S=1800, MAIN_ENTRY_DOOR='garage_a',
          TICK_S=60, S_SAMPLE_S=15)
H_DOORS = {'front': ['madrone_g6_entry', 'front_door_aerial', 'doorbell_lite'], 'garage_a': ['garage_a'], 'garage_b': ['garage_b']}
OVERLAP = [['family_room', 'master_hallway']]
COMPONENTS = OVERLAP + [[c] for c in INTERIOR if not any(c in g for g in OVERLAP)]


def floor_formula(R, M_cam, U_gr, T, cam_present=True):
    return R + max(0, max(M_cam - R, 0) if cam_present else 0, U_gr, T)


def door_pipeline(evs, doors, K, edges):
    s2d = {s: d for d, l in doors.items() for s in l}
    evs = [dict(e, door=s2d.get(e['stem'], e['stem'])) for e in sorted(evs, key=lambda x: x['t'])]
    # 1 leg-collapse by stem (one physical camera via resolver), 30 s from cluster start
    L1, _ = collapse(evs, K['STEM_DEDUP_S'], 'stem')
    # 2 same-person within door_group, same direction, 10 s (chain on cluster start)
    L2 = []; last = {}
    for e in sorted(L1, key=lambda x: x['t0']):
        k = (e['door'], e['d'])
        if k in last and e['t0'] - last[k]['t_last'] <= K['DOOR_SAMEPERSON_S']:
            last[k]['legs'] += e['legs']; last[k]['t_last'] = e['t0']; continue
        c = dict(e); c['legs'] = list(e['legs']); c['t_last'] = e['t0']; L2.append(c); last[k] = c
    for c in L2:
        c['pids'] = {RES.get((l['pid'] or '').lower()) for l in c['legs']} - {None}
    # 3 round-trip pairing: opposite direction, same door_group, <=180 s, neither carrying a resident pid
    for i, a in enumerate(L2):
        if a.get('rt') or a['pids']: continue
        for b in L2[i + 1:]:
            if b['t0'] - a['t0'] > K['DOOR_ROUNDTRIP_S']: break
            if b.get('rt') or b['pids'] or b['door'] != a['door'] or b['d'] == a['d']: continue
            a['rt'] = b['t0']; b['rt'] = a['t0']; break
    # 4 resident attribution (two-sided, each tracker edge consumed once)
    used = set()
    for c in L2:
        c['attr'] = None; c['t_resolve'] = c['t0']
        if c.get('rt'): c['attr'] = 'roundtrip'; continue
        if c['pids']: c['attr'] = 'pid'; continue
        best = None
        for j, (te, k, d) in enumerate(edges):
            if j in used or d != c['d']: continue
            if abs(te - c['t0']) <= K['RESIDENT_CROSSING_MATCH_S'] and (best is None or abs(te - c['t0']) < abs(edges[best][0] - c['t0'])): best = j
        if best is not None:
            used.add(best); c['attr'] = 'edge'; c['edge'] = edges[best]
            c['t_resolve'] = max(c['t0'], edges[best][0]); continue  # provisional T until edge arrives
        if K['MAIN_ENTRY_DOOR'] and c['door'] == K['MAIN_ENTRY_DOOR']:
            best = None
            for j, (te, k, d) in enumerate(edges):
                if j in used or d != c['d']: continue
                if abs(te - c['t0']) <= K['MAIN_ENTRY_PRIOR_S'] and (best is None or abs(te - c['t0']) < abs(edges[best][0] - c['t0'])): best = j
            if best is not None:
                used.add(best); c['attr'] = 'prior_final'; c['edge'] = edges[best]
                c['t_resolve'] = max(c['t0'], edges[best][0])
            elif not K.get('PRIOR_REVERSAL', True):
                c['attr'] = 'prior_final'
            else:
                c['attr'] = 'prior_reversed'; c['t_resolve'] = c['t0'] + K['MAIN_ENTRY_PRIOR_S']
            continue
    return L1, L2


def hybrid_main(K=None, doors=None, start_ts=None):
    K = K or KN; doors = doors or H_DOORS
    # tracker edges (resident)
    edges_h = []
    for k, s in pers.items():
        for i in range(1, len(s.t)):
            if s.v[i] != s.v[i - 1]: edges_h.append((s.t[i], k, 'entry' if s.v[i] == 1 else 'exit'))
    edges_h.sort()
    L1, L2 = door_pipeline(ev, doors, K, edges_h)
    # T delta schedule: (time, dT, dB, crossing)
    sched = []
    for c in L2:
        sg = 1 if c['d'] == 'entry' else -1
        a = c['attr']
        if a in ('roundtrip', 'pid'): continue
        if a in ('edge',):  # provisional-apply then retro-reconcile at edge time
            if c['t_resolve'] > c['t0']: sched.append((c['t0'], sg, 0, c)); sched.append((c['t_resolve'], -sg, 0, c))
            continue
        if a == 'prior_final':  # provisional resident (B in-flight), finalised at edge
            sched.append((c['t0'], 0, 1, c)); sched.append((c['t_resolve'], 0, -1, c)); continue
        if a == 'prior_reversed':
            sched.append((c['t0'], 0, 1, c)); sched.append((c['t_resolve'], sg, -1, c)); continue
        sched.append((c['t0'], sg, 0, c))  # unattributed guest crossing
    sched.sort(key=lambda x: x[0])
    # downtime
    evs_ = [(t, ts) for t, ts in r.execute("""select et.event_type,e.time_fired_ts from events e join event_types et on e.event_type_id=et.event_type_id
       where et.event_type in ('homeassistant_stop','homeassistant_start') order by 2""")]
    down = []; ls = None
    for t, ts in evs_:
        if t == 'homeassistant_stop': ls = ts
        elif ls: down.append((ls, ts)); ls = None
    isdown = lambda t: any(a <= t < b for a, b in down)

    def S_at(t):
        return sum(max(cnt[c].at(t, 0) or 0 for c in comp) for comp in COMPONENTS)

    def ugr_at(t):
        u_ = 0
        for room, ss in gr.items():
            if any(s.at(t, 0) for s in ss) and not any(pers[k].at(t, 0) and area[k].at(t) == room for k in area): u_ += 1
        return u_

    start = int((start_ts or T0) // 60 + 1) * 60
    Ssamp = []  # (t, S)
    T = 0; B = 0.0; si = 0; anchors = []; empty_since = None; boot_until = 0; prev_down = False
    shrink_until = 0; last_body = start; stale_step = None; stale_next = None
    out_rows = []; log = []
    t = start
    while t < T1:
        if isdown(t):
            prev_down = True; out_rows.append(dict(t=t, down=True)); t += K['TICK_S']; continue
        if prev_down: prev_down = False; boot_until = t + K['BOOT_SETTLE_S']
        # ingest S samples within the tick
        for ts in range(t - K['TICK_S'] + K['S_SAMPLE_S'], t + 1, K['S_SAMPLE_S']): Ssamp.append((ts, S_at(ts)))
        S_now = Ssamp[-1][1]
        if S_now > 0: last_body = t; stale_step = None
        # reconcile: apply door schedule
        while si < len(sched) and sched[si][0] <= t:
            ts_, dT, dB, c = sched[si]; si += 1
            if dT < 0 and c['d'] == 'exit' and T == 0 and S_now == 0 and c['attr'] not in ('edge',):
                shrink_until = ts_ + K['FLOOR_SHRINK_HOLD_S']
            T = min(max(T + dT, 0), K['DOOR_TALLY_MAX']); B = max(B + dB, 0)
            if dT and c['attr'] not in ('edge',): log.append((ts_, c['door'], c['d'], c['attr'], T))
        # B decay (in-flight provisionals only here -> settle on schedule; keep linear decay cap)
        # tally stale age-out
        if T > 0 and t - last_body >= K['DOOR_TALLY_STALE_S']:
            if stale_step is None: stale_step = K['DOOR_TALLY_STALE_S'] / T; stale_next = t + stale_step
            if t >= stale_next: T -= 1; stale_next = t + stale_step
        FW = K['SHRINK_WINDOW_S'] if t < shrink_until else K['FLOOR_WINDOW_S']
        Ssamp = [x for x in Ssamp if x[0] > t - K['FLOOR_WINDOW_S']]
        M = max((s for ts, s in Ssamp if ts > t - FW), default=0)
        R = sum(pers[k].at(t, 0) or 0 for k in pers)
        U = ugr_at(t)
        # anchor
        if R == 0 and M == 0 and U == 0 and t >= boot_until:
            empty_since = empty_since or t
            if t - empty_since >= K['EMPTY_ANCHOR_SETTLE_S']:
                if T or B: anchors.append((t, T, B))
                elif not anchors or anchors[-1][0] < empty_since: anchors.append((t, 0, 0))
                T = 0; B = 0; Ssamp = []
                empty_since = t  # re-arm
        else: empty_since = None
        F = floor_formula(R, M, U, T)
        out_rows.append(dict(t=t, R=R, M=M, U=U, T=T, B=B, F=F, E=F + B, S=S_now, down=False))
        t += K['TICK_S']
    return L1, L2, out_rows, anchors, log


def h_truth(t):
    """(lo, hi) reconciled truth band §8.1, 10-03 CDT."""
    h = (t - D3a) / 3600
    if h < 8: return (4, 4)
    if h < 13.5: return (3, 3)
    if h < 14 + 20 / 60: return (1, 2)
    if h < 15: return (10, 11)
    if h < 23: return (10, 12)
    if h < 23 + 24 / 60: return (10, 10)
    if h < 23 + 55 / 60: return (12, 12)
    return (11, 11)


def gates_only(rows):
    up = [x for x in rows if not x['down']]
    tab = []
    for t0 in range(int(D3a), int(D3b), 900):
        br = [x for x in up if t0 <= x['t'] < t0 + 900]
        if br: tab.append((t0, st.mean(x['F'] for x in br), st.mean(x['E'] for x in br)))
    dist = lambda v, lo, hi: 0 if lo <= v <= hi else (lo - v if v < lo else v - hi)
    cut = D3a + (14 + 20 / 60) * 3600
    pre = [x for x in tab if x[0] + 450 < cut]; post = [x for x in tab if x[0] + 450 >= cut]
    mor = [x for x in up if D3a + 8 * 3600 <= x['t'] < D3a + 13.5 * 3600 and x['R'] == 3]
    return dict(G1=sum(f <= e + 1e-9 for _, f, e in tab) / len(tab), G2=sum(f <= h_truth(t + 450)[1] + 1e-9 for t, f, _ in tab) / len(tab),
                G3=sum(dist(f, *h_truth(t + 450)) <= 1 for t, f, _ in pre) / len(pre),
                G4a=sum(dist(f, *h_truth(t + 450)) <= 2 for t, f, _ in post) / len(post), G4b=sum(f >= 4 for _, f, _ in post) / len(post),
                G5=sum(x['F'] == x['R'] for x in mor) / max(len(mor), 1),
                G3_pre12=sum(dist(f, *h_truth(t + 450)) <= 1 for t, f, _ in pre if t < D3a + 12 * 3600) / max(1, sum(1 for t, *_ in pre if t < D3a + 12 * 3600)))


def hybrid_variants():
    V = [('baseline (plan)', {}, None), ('doorbell_lite->garage_a', {}, {'front': ['madrone_g6_entry', 'front_door_aerial'], 'garage_a': ['garage_a', 'doorbell_lite'], 'garage_b': ['garage_b']}),
         ('prior permanent (no reversal)', {'PRIOR_REVERSAL': False}, None), ('FLOOR_WINDOW_S=600', {'FLOOR_WINDOW_S': 600}, None),
         ('no main-entry prior', {'MAIN_ENTRY_DOOR': None}, None),
         ('doorbell->garage_a + prior permanent', {'PRIOR_REVERSAL': False}, {'front': ['madrone_g6_entry', 'front_door_aerial'], 'garage_a': ['garage_a', 'doorbell_lite'], 'garage_b': ['garage_b']})]
    print('### Sensitivity variants (start 10-01 00:00 CDT warm-up)')
    print('| variant | G1 | G2 | G3 | G3 00-12 only | G4 within2 | G4 F>=4 | G5 | FLOOR 13:00 | FLOOR 23:45 |')
    print('|---|---|---|---|---|---|---|---|---|---|')
    for name, ov, doors in V:
        K = dict(KN); K.update(ov)
        _, _, rows, _, _ = hybrid_main(K, doors, D3a - 2 * 86400)
        g = gates_only(rows); idx = {x['t']: x for x in rows if not x['down']}
        f = lambda hh: idx.get(int(D3a + hh * 3600), {}).get('F')
        print(f"| {name} | {g['G1']:.0%} | {g['G2']:.0%} | {g['G3']:.0%} | {g['G3_pre12']:.0%} | {g['G4a']:.0%} | {g['G4b']:.0%} | {g['G5']:.0%} | {f(13)} | {f(23.75)} |")


def hybrid_report():
    L1, L2, rows, anchors, log = hybrid_main()
    P = print
    P('## HYBRID replay (knobs: ' + json.dumps(KN) + ')')
    P(f'Overlap components: {COMPONENTS}; door groups: {H_DOORS}; Revel EXCLUDED; ledger directions: entry/exit only (no AMBIGUOUS rows -> P-AMB/T_amb inert)')
    d3 = [c for c in L2 if D3a <= c['t0'] < D3b]
    P(f"10-03 crossings: raw ledger rows={sum(1 for e in ev if D3a<=e['t']<D3b)}, after leg-collapse={sum(1 for c in L1 if D3a<=c['t0']<D3b)}, after same-person={len(d3)}")
    P('Attribution (10-03): ' + json.dumps(Counter(f"{c['d']}:{c['attr']}" for c in d3)))
    # 14:20 front burst
    a, b = D3a + 14 * 3600 + 10 * 60, D3a + 14 * 3600 + 40 * 60
    raw = [e for e in ev if a <= e['t'] < b and e['stem'] in H_DOORS['front']]
    l1 = [c for c in L1 if a <= c['t0'] < b and c['stem'] in H_DOORS['front']]
    l2 = [c for c in L2 if a <= c['t0'] < b and c['door'] == 'front']
    P(f"### d0_front_14_20 (front, 14:10-14:40): raw rows entry/exit={sum(e['d']=='entry' for e in raw)}/{sum(e['d']=='exit' for e in raw)}; "
      f"leg-collapsed entries={sum(c['d']=='entry' for c in l1)}; same-person entries={sum(c['d']=='entry' for c in l2)}; "
      f"surviving round-trip+attribution (count into T) = {sum(1 for c in l2 if c['d']=='entry' and c['attr'] is None)}")
    for c in l2: P(f"- {loc(c['t0'])[6:]}:{int((c['t0']+CDT)%60):02d} {c['d']} legs={len(c['legs'])} attr={c['attr']}")
    P('### 23:24 garage_a window (23:15-23:40)')
    for c in L2:
        if D3a + 23.25 * 3600 <= c['t0'] < D3a + 23 * 3600 + 40 * 60:
            P(f"- {loc(c['t0'])[6:]}:{int((c['t0']+CDT)%60):02d} {c['door']} {c['d']} legs={len(c['legs'])} attr={c['attr']} edge={c.get('edge')} resolve={loc(c['t_resolve'])[6:]}")
    # bins
    up = [x for x in rows if not x['down']]
    def binrows(t0, step=900): return [x for x in up if t0 <= x['t'] < t0 + step]
    tab = []
    for t0 in range(int(D3a), int(D3b), 900):
        br = binrows(t0)
        if not br: tab.append((t0, None)); continue
        m = lambda k: st.mean(x[k] for x in br)
        tab.append((t0, dict(F=m('F'), E=m('E'), R=m('R'), M=m('M'), U=m('U'), T=m('T'), B=m('B'), Fmax=max(x['F'] for x in br))))
    P('### 15-min bins (means)')
    P('| CDT | R | M_cam | U_gr | T | B | FLOOR | ESTIMATE | truth | legacy |')
    P('|---|---|---|---|---|---|---|---|---|---|')
    for t0, b_ in tab:
        lo, hi = h_truth(t0 + 450); lg = st.mean(legacy.at(t, 0) or 0 for t in range(t0, t0 + 900, 60))
        if not b_: P(f'| {loc(t0)[6:]} | DOWN |||||| | {lo}-{hi} | {lg:.1f} |'); continue
        P(f"| {loc(t0)[6:]} | {b_['R']:.1f} | {b_['M']:.1f} | {b_['U']:.1f} | {b_['T']:.1f} | {b_['B']:.1f} | {b_['F']:.1f} | {b_['E']:.1f} | {lo}-{hi} | {lg:.1f} |")
    good = [(t0, b_) for t0, b_ in tab if b_]
    dist = lambda v, lo, hi: 0 if lo <= v <= hi else (lo - v if v < lo else v - hi)
    g = {}
    g[1] = sum(b_['F'] <= b_['E'] + 1e-9 for _, b_ in good) / len(good)
    g[2] = sum(b_['F'] <= h_truth(t0 + 450)[1] + 1e-9 for t0, b_ in good) / len(good)
    pre = [(t0, b_) for t0, b_ in good if t0 + 450 < D3a + (14 + 20 / 60) * 3600]
    g[3] = sum(dist(b_['F'], *h_truth(t0 + 450)) <= 1 for t0, b_ in pre) / len(pre)
    post = [(t0, b_) for t0, b_ in good if t0 + 450 >= D3a + (14 + 20 / 60) * 3600]
    g['4a'] = sum(dist(b_['F'], *h_truth(t0 + 450)) <= 2 for t0, b_ in post) / len(post)
    g['4b'] = sum(b_['F'] >= 4 for t0, b_ in post) / len(post)
    mor = [x for x in up if D3a + 8 * 3600 <= x['t'] < D3a + 13.5 * 3600 and x['R'] == 3]
    g[5] = sum(x['F'] - x['R'] == 0 for x in mor) / max(len(mor), 1)
    P(f"### Gates\nG1 {g[1]:.0%} | G2 {g[2]:.0%} | G3 {g[3]:.0%} (n={len(pre)}) | G4 |F-truth|<=2 {g['4a']:.0%}, F>=4 {g['4b']:.0%} (n={len(post)}) | G5 {g[5]:.0%} (n={len(mor)} min)")
    P('G5 guest_estimate>0 minutes (morning R=3): ' + ', '.join(sorted({loc(x['t'])[6:] for x in mor if x['F'] > x['R']}))[:600])
    # G6 anchors
    P(f'G6 anchors over retention: {len(anchors)}')
    idx = {x['t']: x for x in up}
    for t_, T_, B_ in anchors:
        x = idx.get(t_); P(f"- {loc(t_)} T_pre={T_} B_pre={B_} FLOOR_after={x and x['F']} T_after={x and x['T']}")
    # G7 F5
    P('G7 F5: ' + '; '.join(f"{hh}: " + (lambda x: f"R={x['R']} M={x['M']} U={x['U']} T={x['T']} F={x['F']} hs={hs.at(x['t'])}" if x else 'DOWN')(idx.get(int(D3a + int(hh[:2]) * 3600 + int(hh[3:]) * 60))) for hh in ('15:53', '15:57', '16:01', '17:02')))
    P(f"G9 synthetic floor_formula(R=2,M=3,U=1,T=0) = {floor_formula(2,3,1,0)}; (R=2,M=3,U=0,T=0) = {floor_formula(2,3,0,0)}")
    P('### T change log 10-03 (non-edge)')
    for ts_, d, dd, at, T_ in log:
        if D3a <= ts_ < D3b: P(f'- {loc(ts_)[6:]} {d} {dd} {at} -> T={T_}')
    # CSV fixture comparison (30-min slots)
    P('### CSV fixture (30-min slot start value) vs FLOOR mean over slot')
    return tab, g


if HYBRID_ONLY:
    import sys
    import os
    if os.environ.get('VARIANTS_ONLY') or VARIANTS_ONLY: hybrid_variants()
    else: hybrid_report()
    sys.exit(0)

# P1
ev3 = [e for e in ev if D3a <= e['t'] < D3b]
P('### P1 Door dedup collapse (10-03 CDT, ledger rows=%d, entries=%d, exits=%d, raw net=%+d)' % (
    len(ev3), sum(e['d'] == 'entry' for e in ev3), sum(e['d'] == 'exit' for e in ev3),
    sum(1 if e['d'] == 'entry' else -1 for e in ev3)))
P('| key | window s | logical | entries | exits | net | residual same-key same-dir pairs <60s (%) | over-merge (door cam count returned to 0 between merged legs) |')
P('|---|---|---|---|---|---|---|---|')
def door_series_zero_between(door, a, b):
    for c in DOORS[door]:
        s = dcnt.get(c)
        if not s: continue
        i = bisect.bisect_right(s.t, a)
        while i < len(s.t) and s.t[i] < b:
            if s.v[i] == 0: return True
            i += 1
    return False
p1 = {}
for key in ('stem', 'door'):
    for w in (5, 10, 20, 30, 60):
        k, m = collapse(ev3, w, key)
        res = 0
        for i, e in enumerate(k):
            if any(o[key] == e[key] and o['d'] == e['d'] and 0 < o['t0'] - e['t0'] < 60 for o in k[i + 1:i + 30]): res += 1
        om = sum(1 for c, e in m if e['t'] - c['legs'][-2]['t'] > 2 and c['door'] in DOORS and door_series_zero_between(c['door'], c['legs'][-2]['t'] + 1, e['t'] - 1))
        ne = sum(x['d'] == 'entry' for x in k); nx = len(k) - ne
        P(f'| {key} | {w} | {len(k)} | {ne} | {nx} | {ne-nx:+d} | {res} ({100*res/max(len(k),1):.0f}%) | {om}/{len(m)} |')
        p1[(key, w)] = k
gaps = []
for c in p1[('stem', 60)]:
    for a, b in zip(c['legs'], c['legs'][1:]): gaps.append(b['t'] - a['t'])
hb = Counter(min(int(g // 2) * 2, 40) for g in gaps)
P('Inter-leg gap histogram (stem, 60 s clusters, s bucket:count): ' + ', '.join(f'{k}:{hb[k]}' for k in sorted(hb)))
legs = Counter(tuple(sorted(set(l['cam'].split('.')[0] + ':' + l['cam'].split('.', 1)[1].replace(l['stem'], '*') for l in c['legs']))) for c in p1[('stem', 10)])
P('Leg-signature of stem@10s logical events (top 6): ' + '; '.join(f'{"+".join(k)}={v}' for k, v in legs.most_common(6)))

# choose working dedup
DEDUP = p1[('door', 10)]

# P2 group size
P('\n### P2 Group size (door-group dedup @10 s; group_hi = max person_count over all cameras of that door in [t-2, t+W])')
P('| W s | burst 12:00-13:30 entries n | group_hi dist (size:count) | sum group_hi | day entries sum group_hi | day exits sum group_hi |')
P('|---|---|---|---|---|---|')
def ghi(e, W):
    m = 0
    for c in DOORS.get(e['door'], []):
        if c in dcnt: m = max(m, dcnt[c].maxin(e['t0'] - 2, e['t0'] + W))
    return max(1, min(m, 6))
burst_a, burst_b = D3a + 12 * 3600, D3a + 13.5 * 3600
for W in (4, 8, 12):
    b = [e for e in DEDUP if burst_a <= e['t0'] < burst_b and e['d'] == 'entry']
    g = Counter(ghi(e, W) for e in b)
    P(f"| {W} | {len(b)} | {dict(sorted(g.items()))} | {sum(ghi(e,W) for e in b)} | {sum(ghi(e,W) for e in DEDUP if e['d']=='entry')} | {sum(ghi(e,W) for e in DEDUP if e['d']=='exit')} |")
P('Burst entries detail (time CDT, door, pid, group_hi@8): ' + '; '.join(f"{loc(e['t0'])[6:]} {e['door']} {e['pid'] or '-'} {ghi(e,8)}" for e in DEDUP if burst_a - 3600 <= e['t0'] < burst_b + 1800 and e['d'] == 'entry'))

# P3 resident attribution
edges = []
for k, s in pers.items():
    for i in range(1, len(s.t)):
        if s.v[i] != s.v[i - 1]: edges.append((s.t[i], k, 'entry' if s.v[i] == 1 else 'exit'))
RES = {'ezinne': 'ezinne', 'oji udezue': 'oji', 'oji': 'oji', 'ojini': 'oji', 'jaya': 'jaya', 'ziri': 'ziri'}
def attribute(evs, M):
    used = set(); outl = []
    for e in evs:
        res = None
        if e.get('pid') and any(RES.get((l['pid'] or '').lower()) for l in e['legs']):
            res = 'pid'
        else:
            best = None
            for j, (t, k, d) in enumerate(edges):
                if j in used or d != e['d']: continue
                if abs(t - e['t0']) <= M and (best is None or abs(t - e['t0']) < abs(edges[best][0] - e['t0'])): best = j
            if best is not None: used.add(best); res = 'edge'
        outl.append(dict(e, res=res))
    return outl
P('\n### P3 Resident attribution (10-03, door-group dedup @10 s)')
P('| match window s | entries resident/anon | exits resident/anon | anon entry Σgroup_hi@8 | anon exit Σgroup_hi@8 | resident tracker edges that day (entry/exit) |')
P('|---|---|---|---|---|---|')
e3 = [e for e in edges if D3a <= e[0] < D3b]
for M in (60, 120, 300):
    a = attribute(DEDUP, M); a3 = [x for x in a if D3a <= x['t0'] < D3b]
    f = lambda d, rs: sum(1 for x in a3 if x['d'] == d and bool(x['res']) == rs)
    P(f"| {M} | {f('entry',True)}/{f('entry',False)} | {f('exit',True)}/{f('exit',False)} | {sum(ghi(x,8) for x in a3 if x['d']=='entry' and not x['res'])} | {sum(ghi(x,8) for x in a3 if x['d']=='exit' and not x['res'])} | {sum(1 for x in e3 if x[2]=='entry')}/{sum(1 for x in e3 if x[2]=='exit')} |")
ATTR = attribute(DEDUP, 120)
anon = [x for x in ATTR if not x['res']]

# ---------------- per-minute series over full retention
start = int(T0 // 60 + 1) * 60; mins = list(range(start, int(T1), 60))
GROUPINGS = {'sum (no dedup)': [[c] for c in INTERIOR],
             'plan §5.2 candidates (components)': [['foyer_fisheye', 'staircase', 'stairs_top', 'upstairs_hall'], ['family_room'], ['master_hallway'], ['playroom']],
             'house max (extreme collapse)': [INTERIOR]}
CAMAREAS = set(CAM_AREA.values())
# downtime spans
evs = [(t, ts) for t, ts in r.execute("""select et.event_type,e.time_fired_ts from events e join event_types et on e.event_type_id=et.event_type_id
   where et.event_type in ('homeassistant_stop','homeassistant_start') order by 2""")]
down = []; last_stop = None
for t, ts in evs:
    if t == 'homeassistant_stop': last_stop = ts
    elif last_stop: down.append((last_stop, ts)); last_stop = None
def is_down(t): return any(a <= t < b for a, b in down)

series = []
wcache = {}
for t in mins:
    rh = sum(pers[k].at(t, 0) or 0 for k in pers)
    rcam = sum(1 for k in area if pers[k].at(t, 0) and area[k].at(t) in CAMAREAS)
    S = {g: sum(max(cnt[c].at(t, 0) or 0 for c in comp) for comp in comps) for g, comps in GROUPINGS.items()}
    ugr = 0
    for room, ss in gr.items():
        if any(s.at(t, 0) for s in ss) and not any(pers[k].at(t, 0) and area[k].at(t) == room for k in area): ugr += 1
    w4, wall, _ = w_at(t) if (t % 300 == 0 or True) else (0, 0, [])
    series.append(dict(t=t, rh=rh, rcam=rcam, S=S, ugr=ugr, w=w4, wall=wall, down=is_down(t)))

def truth(t):
    """(lo, hi) for 10-03 CDT; None elsewhere. Residents from trackers."""
    rh = sum(pers[k].at(t, 0) or 0 for k in pers)
    h = (t - D3a) / 3600
    if not (0 <= h < 24): return None
    lo = rh + (1 if (h < 8 or h >= 23) else 0) + (8 if h >= 13.5 else 0)
    hi = rh + 1 + (8 if h >= 12 else 0) + (1 if h >= 12 else 0)
    return lo, hi
def truth_other(t):
    rh = sum(pers[k].at(t, 0) or 0 for k in pers)
    return rh, rh + 1  # long-stay guest present at unknown hours

# ---------------- estimator
def run(grouping, FW, useW=True, recon=5 * 3600, decay=1800, dwell=900, boot=600, restore_fence=True):
    an = sorted(anon, key=lambda x: x['t0']); ai = 0
    Ahist = []  # (t, A)
    C = N = 0.0; treconf = mins[0]; empty_since = None; resets = []; res_out = []
    exits_after = []  # (t, ghi) anon exits
    last_up = mins[0]; prev_down = False; boot_until = 0
    for row in series:
        t = row['t']
        if row['down']:
            prev_down = True; res_out.append(None); continue
        if prev_down:
            prev_down = False; boot_until = t + boot
            if restore_fence: Ahist = []  # boot floor 0 until settle; persisted C,N kept
        A = max(max(0, row['S'][grouping] - row['rcam']) + row['ugr'], row['w'] if useW else 0)
        if t < boot_until: A = 0
        entries_now = []
        while ai < len(an) and an[ai]['t0'] <= t:
            e = an[ai]; ai += 1
            g = ghi(e, 8)
            gmed = g  # samples-agree check approximated: med=hi when hi==1 else round((1+hi)/2)
            gmed = g if g == 1 else round((1 + g) / 2)
            if e['d'] == 'entry':
                C += g; N += gmed; treconf = t
            else:
                C -= 1; N -= gmed; exits_after.append((e['t0'], g))
        Ahist.append((t, A)); Ahist = [x for x in Ahist if x[0] >= t - FW] if FW > 0 else [(t, A)]
        F = 0
        for tau, a in Ahist:
            x = sum(g for te, g in exits_after if te > tau)
            F = max(F, a - x)
        F = max(F, 0)
        exits_after = [x for x in exits_after if x[0] >= t - max(FW, 60)]
        if C < F: C = F
        if F >= C - 1: treconf = t
        if t - treconf > recon and C > F: C = max(F, C - (C - F) * 60 / decay if decay else F)
        N = min(max(N, F), C)
        # verified-empty reset
        if row['rh'] == 0 and F == 0 and row['S']['sum (no dedup)'] == 0 and row['ugr'] == 0 and row['w'] == 0 and t >= boot_until:
            empty_since = empty_since or t
            if t - empty_since >= dwell and (C > 0 or N > 0):
                resets.append((t, C, N)); C = N = 0
        else: empty_since = None
        res_out.append(dict(t=t, F=row['rh'] + F, C=row['rh'] + C, E=row['rh'] + N, Fa=F, Ca=C, Na=N, A=A))
    return res_out, resets

def bins(res, a, b, step=900):
    outb = []
    for t0 in range(int(a), int(b), step):
        rows = [x for x in res if x and t0 <= x['t'] < t0 + step]
        if not rows: outb.append((t0, None)); continue
        m = lambda k: st.mean(x[k] for x in rows)
        outb.append((t0, dict(F=m('F'), C=m('C'), E=m('E'), Ea=m('Na'), Fa=m('Fa'))))
    return outb

P('\n### P4 Floor series inputs (10-03, hourly means; S per grouping, R_cam, U_gr, W(4 h recency), W(no recency))')
P('| hour CDT | S sum | S plan§5.2 | S housemax | R_cam | U_gr | W | W no-recency | legacy census | truth lo-hi |')
P('|---|---|---|---|---|---|---|---|---|---|')
for h in range(24):
    rows = [x for x in series if D3a + h * 3600 <= x['t'] < D3a + (h + 1) * 3600 and not x['down']]
    if not rows: P(f'| {h:02d} | (HA down) |'); continue
    m = lambda f: st.mean(f(x) for x in rows)
    tl = truth(D3a + h * 3600 + 1800)
    P(f"| {h:02d} | {m(lambda x:x['S']['sum (no dedup)']):.2f} | {m(lambda x:x['S']['plan §5.2 candidates (components)']):.2f} | {m(lambda x:x['S']['house max (extreme collapse)']):.2f} | {m(lambda x:x['rcam']):.2f} | {m(lambda x:x['ugr']):.2f} | {m(lambda x:x['w']):.2f} | {m(lambda x:x['wall']):.2f} | {st.mean(legacy.at(x['t'],0) or 0 for x in rows):.2f} | {tl[0]}-{tl[1]} |")

# pairwise co-on (overlap evidence) over retention
P('\nInterior camera simultaneous co-occupancy over all retained minutes (person_count>0): Jaccard')
P('| pair | J | co-on minutes |')
P('|---|---|---|')
on = {c: set(x['t'] for x in series if (cnt[c].at(x['t'], 0) or 0) > 0) for c in INTERIOR}
pairs = []
for i, a in enumerate(INTERIOR):
    for b in INTERIOR[i + 1:]:
        I = len(on[a] & on[b]); U = len(on[a] | on[b]); pairs.append((I / U if U else 0, a, b, I))
for j, a, b, I in sorted(pairs, reverse=True)[:8]: P(f'| {a}+{b} | {j:.3f} | {I} |')
P('Minutes with count>0 per camera: ' + ', '.join(f'{c}={len(on[c])}' for c in INTERIOR))

# P5 Revel
P('\n### P5 Revel connected-now (filtered per `_get_wifi_guest_count`; per-minute)')
P('| day (CDT) | W(4h recency) mean | p90 | max | W(no recency) mean | p90 | max |')
P('|---|---|---|---|---|---|---|')
def pct(v, p): v = sorted(v); return v[min(len(v) - 1, int(p * len(v)))] if v else 0
for d in range(-8, 1):
    a, b = D3a + d * 86400, D3a + (d + 1) * 86400
    rows = [x for x in series if a <= x['t'] < b and not x['down']]
    if not rows: continue
    w = [x['w'] for x in rows]; wa = [x['wall'] for x in rows]
    P(f"| {loc(a)[:5]} | {st.mean(w):.2f} | {pct(w,.9)} | {max(w)} | {st.mean(wa):.2f} | {pct(wa,.9)} | {max(wa)} |")
for hh in (11, 12, 13, 14, 15, 16, 18, 21):
    n, nr, names = w_at(D3a + hh * 3600)
    P(f'- 10-03 {hh:02d}:00 W={n} no-recency={nr} hosts={sorted(names)}')

# estimator runs
P('\n### P6 Ceiling / estimate / floor vs truth (10-03, 15-min bins)')
configs = []
for g in GROUPINGS:
    for FW in (900, 1200, 1800):
        for useW in (True, False):
            configs.append((g, FW, useW))
summary = []
store = {}
for g, FW, useW in configs:
    res, resets = run(g, FW, useW)
    store[(g, FW, useW)] = (res, resets)
    bb = bins(res, D3a, D3b)
    n = order = fs = cc = ea = em = ntot = 0; aft = mor = 0
    for t0, b in bb:
        if not b: continue
        lo, hi = truth(t0 + 450); ntot += 1
        order += (b['F'] <= b['E'] + 1e-9 <= b['C'] + 2e-9)
        fs += b['F'] <= hi + 1e-9
        h = (t0 - D3a) / 3600
        if h >= 13.5:
            aft += 1; cc += b['C'] >= lo - 1e-9
            ea += (lo - 2 <= b['E'] <= hi + 2)
        if h < 12:
            mor += 1; em += (lo - 1 <= b['E'] <= hi + 1)
    summary.append((g, FW, useW, ntot, order / ntot, fs / ntot, cc / aft, ea / aft, em / mor))
P('| grouping | FLOOR_WINDOW_S | W in floor | bins | G1 order | G2 floor≤truth_hi | G3 ceil≥truth_lo (13:30-24) | G4a |E−band|≤2 (13:30-24) | G4b |E−band|≤1 (00-12) |')
P('|---|---|---|---|---|---|---|---|---|')
for s in summary:
    P(f'| {s[0]} | {s[1]} | {"yes" if s[2] else "no"} | {s[3]} | {100*s[4]:.0f}% | {100*s[5]:.0f}% | {100*s[6]:.0f}% | {100*s[7]:.0f}% | {100*s[8]:.0f}% |')

REF = ('plan §5.2 candidates (components)', 1200, True)
res, resets = store[REF]
P(f'\nReference run {REF}: 15-min bins (means)')
P('| bin CDT | FLOOR | ESTIMATE | CEILING | truth lo-hi | legacy census | guest_estimate |')
P('|---|---|---|---|---|---|---|')
for t0, b in bins(res, D3a, D3b):
    lo, hi = truth(t0 + 450)
    lg = st.mean(legacy.at(t, 0) or 0 for t in range(t0, t0 + 900, 60))
    if not b: P(f'| {loc(t0)[6:]} | (HA down) | | | {lo}-{hi} | {lg:.1f} | |'); continue
    P(f"| {loc(t0)[6:]} | {b['F']:.1f} | {b['E']:.1f} | {b['C']:.1f} | {lo}-{hi} | {lg:.1f} | {b['Ea']:.1f} |")

# P5/G5 substitute: other days guest_estimate
P('\n### G5 discrimination substitute (no guest-free day in retention): per-day guest_estimate on 1-guest days (09-26..10-02), reference run')
P('| day | bins | guest_estimate=0 % | ≤1 % | max | mean | anon entries/exits that day | legacy guest_mode on minutes |')
P('|---|---|---|---|---|---|---|---|')
for d in range(-7, 0):
    a, b = D3a + d * 86400, D3a + (d + 1) * 86400
    bb = [x for _, x in bins(res, max(a, mins[0]), b) if x]
    if not bb: continue
    ge = [x['Ea'] for x in bb]
    ae = sum(1 for x in anon if a <= x['t0'] < b and x['d'] == 'entry'); ax = sum(1 for x in anon if a <= x['t0'] < b and x['d'] == 'exit')
    gm = sum(1 for t in range(int(a), int(b), 60) if guestmode.at(t, 0))
    P(f'| {loc(a)[:5]} | {len(bb)} | {100*sum(g < 0.5 for g in ge)/len(ge):.0f}% | {100*sum(g < 1.5 for g in ge)/len(ge):.0f}% | {max(ge):.1f} | {st.mean(ge):.2f} | {ae}/{ax} | {gm} |')

# P7 drift
P('\n### P7 Verified-empty anchors and drift residuals (reference run, all retention)')
P(f'Anchors: {len(resets)}')
for t, C, N in resets[:20]: P(f'- {loc(t)} pre-reset C_anon={C:.1f} N_anon={N:.1f}')
if resets: P(f'median |N residual| = {st.median(abs(n) for _, _, n in resets):.2f}; median C residual = {st.median(c for _, c, _ in resets):.2f}')
# near-empty diagnostic: minutes with R_home=0
r0 = [x for x in series if x['rh'] == 0 and not x['down']]
P(f"Minutes with R_home=0 in retention: {len(r0)}; of those with S=0,U_gr=0,W=0: {sum(1 for x in r0 if x['S']['sum (no dedup)']==0 and x['ugr']==0 and x['w']==0)}")

# P8 F5 replay
P('\n### P8 F5 replay (10-03 15:40-17:15 CDT, reference run, 5-min samples)')
P('| CDT | HA | house_state (recorded) | R_home | FLOOR | ESTIMATE | CEILING |')
P('|---|---|---|---|---|---|---|')
idx = {x['t']: x for x in res if x}
for t in range(int(D3a + 15 * 3600 + 40 * 60), int(D3a + 17 * 3600 + 15 * 60), 300):
    x = idx.get(t); rh = sum(pers[k].at(t, 0) or 0 for k in pers)
    if x: P(f"| {loc(t)[6:]} | up | {hs.at(t)} | {rh} | {x['F']:.0f} | {x['E']:.1f} | {x['C']:.1f} |")
    else: P(f"| {loc(t)[6:]} | DOWN | {hs.at(t)} | {rh} | — | (persisted) | — |")
print('\n'.join(out))
