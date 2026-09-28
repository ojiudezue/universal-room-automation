#!/usr/bin/env python3
"""HVAC raw-evidence gap probe — READ-ONLY. Card HVAC-OCCUPANCY-HOLD-CHAINED-AFTER-LIGHT-TIMEOUT-1.

Question (CRIT-1 safety of "release HVAC occupancy at last-raw-evidence + tail"):
how often does a genuinely present person produce NO raw evidence for longer than
the tail T, during the DAY (house state home_day/home_evening)?

    ssh ha "python3 - [--days 7] [--end 2026-09-26T19:20:00Z] [--graces 300,600] [--states home_night]" \
        < scripts/probes/hvac_raw_evidence_gap_probe.py

Reads (read-only): recorder file:/config/home-assistant_v2.db?mode=ro;
/config/.storage/core.config_entries (room motion/presence/occupancy sensors,
occupancy_timeout, room_type, room_name); core.entity_registry + core.device_registry
(sensor device model -> modality); zone membership from the LATEST recorded
attributes of sensor.ura_hvac_coordinator_zone_N_status (live_rooms).

Method, per room (hallways and rooms in no HVAC zone skipped):
  * evidence = union of 'on' intervals of ALL configured raw sensors
    (motion_sensors + presence_sensors + occupancy_sensors). A radar that stays
    'on' is continuous evidence. unavailable/unknown = no evidence (off).
  * gap = maximal interval with ALL configured sensors not 'on', bounded on both
    sides by evidence.  MID-SESSION gap = evidence resumes within the room's
    occupancy_timeout (lighting STATE_OCCUPIED never dropped -> person assumed
    still there).  END = no resumption within occupancy_timeout.
  * Excluded: any gap overlapping [homeassistant_stop, homeassistant_start+15min]
    or after --end (empty-house period).  Day/night bucket = house state at gap start.
  * For T in TAILS: false_release = MID gap > T (the fix would drop hvac_occupied
    while the person is still there).  zone_retreat_risk(G) = MID gap > T+G AND
    no OTHER non-hallway room of the zone has raw evidence (extended by T, i.e.
    HVAC-occupied under the proposed fix) anywhere in [gap_start+T, gap_start+T+G].
    Upper bound: ignores the up-to-5-min decision tick (which only delays retreat).
"""
import sqlite3, sys, time, json, collections, bisect

a = sys.argv[1:]
def arg(k, d):
    return a[a.index(k) + 1] if k in a else d
DAYS = float(arg('--days', 7))
END = arg('--end', '2026-09-26T19:20:00Z')
GRACES = [int(x) for x in arg('--graces', '300,600').split(',')]
TAILS = [60, 120, 180, 240, 300]   # 240 = v5.103.20 bedroom evidence hold
RESTART_PAD = 15 * 60
# v5.103.20 D0c-home_night (plan §8 Gate B): `--states home_night` (comma list)
# replaces the day bucket so a state can be measured ON ITS OWN.
DAY = set(arg('--states', 'home_day,home_evening').split(','))
NIGHT = {'home_night', 'sleep', 'waking'}

def iso(s):
    return time.mktime(time.strptime(s.rstrip('Z')[:19], '%Y-%m-%dT%H:%M:%S')) - time.timezone
t_end = min(time.time(), iso(END))
t0 = time.time() - DAYS * 86400

r = sqlite3.connect('file:/config/home-assistant_v2.db?mode=ro', uri=True)
meta = {e: m for m, e in r.execute('SELECT metadata_id, entity_id FROM states_meta')}

def history(ent):
    """[(ts, state)] from t0-1d (seed) to t_end, deduped by state."""
    m = meta.get(ent)
    if m is None:
        return None
    rows = r.execute('SELECT state, last_updated_ts FROM states WHERE metadata_id=? AND last_updated_ts>=? '
                     'AND last_updated_ts<=? ORDER BY last_updated_ts', (m, t0 - 86400, t_end)).fetchall()
    out = []
    for s, t in rows:
        if s is None:
            continue
        if not out or out[-1][1] != s:
            out.append((t, s))
    return out

# ---- config ----
ce = json.load(open('/config/.storage/core.config_entries'))
er = {x['entity_id']: x for x in json.load(open('/config/.storage/core.entity_registry'))['data']['entities']}
dr = {x['id']: x for x in json.load(open('/config/.storage/core.device_registry'))['data']['devices']}
PIR_MODELS = ('motion sensor', 'smart night light', 'night light', 'up sense', 'garage-door', 'secplus')
def modality(ent):
    x = er.get(ent) or {}
    dv = dr.get(x.get('device_id')) or {}
    model = (dv.get('model') or '').lower()
    return 'pir' if any(p in model for p in PIR_MODELS) else 'radar'

rooms = {}
for e in ce['data']['entries']:
    if e['domain'] != 'universal_room_automation':
        continue
    c = {**e.get('data', {}), **e.get('options', {})}
    if c.get('entry_type') != 'room':
        continue
    sens = []
    for k in ('motion_sensors', 'presence_sensors', 'occupancy_sensors'):
        for s in c.get(k) or []:
            if s and s not in sens:
                sens.append(s)
    rooms[c.get('room_name') or e['title']] = dict(
        type=c.get('room_type') or 'generic', timeout=float(c.get('occupancy_timeout') or 300),
        sensors=sens, mods=sorted({modality(s) for s in sens}),
        hold=c.get('hvac_vacancy_hold'), disabled=e.get('disabled_by'))

zone_of = {}
for n in (1, 2, 3):
    row = r.execute("SELECT a.shared_attrs FROM states s JOIN state_attributes a ON s.attributes_id=a.attributes_id "
                    "WHERE s.metadata_id=? AND a.shared_attrs LIKE '%live_rooms%' ORDER BY s.last_updated_ts DESC LIMIT 1",
                    (meta.get(f'sensor.ura_hvac_coordinator_zone_{n}_status'),)).fetchone()
    for rn in json.loads(row[0]).get('live_rooms', []):
        zone_of[rn] = f'zone_{n}'

# ---- exclusions: restarts ----
et = dict(r.execute("SELECT event_type, event_type_id FROM event_types"))
def evts(name):
    return [t for (t,) in r.execute('SELECT time_fired_ts FROM events WHERE event_type_id=? AND time_fired_ts>=? ORDER BY 1',
                                    (et.get(name, -1), t0 - 86400))]
stops, starts = evts('homeassistant_stop'), evts('homeassistant_start')
excl = []
for st in starts:
    prev_stop = max([s for s in stops if s <= st] or [st - 60])
    excl.append((prev_stop, st + RESTART_PAD))
excl.append((t_end, 9e18))
def excluded(a_, b_):
    return a_ < t0 or any(a_ < y and b_ > x for x, y in excl)
incl_s = (t_end - t0) - sum(max(0, min(y, t_end) - max(x, t0)) for x, y in excl[:-1])
DAYS_EFF = incl_s / 86400

# ---- house state ----
hs = history('sensor.universal_room_automation_house_state') or []
hs_t = [t for t, _ in hs]
def house(ts):
    i = bisect.bisect_right(hs_t, ts) - 1
    return hs[i][1] if i >= 0 else None
def bucket(ts):
    s = house(ts)
    return 'day' if s in DAY else ('night' if s in NIGHT else 'other')
# day-state hours inside included window
day_s = 0.0
for i, (t, s) in enumerate(hs):
    t2 = hs[i + 1][0] if i + 1 < len(hs) else t_end
    a_, b_ = max(t, t0), min(t2, t_end)
    if b_ > a_ and s in DAY:
        day_s += b_ - a_  # (restart overlap ignored for this denominator; small)

# ---- evidence intervals per room ----
def on_intervals(ent):
    h = history(ent)
    if h is None:
        return None, 0
    iv, cur = [], None
    for t, s in h:
        if s == 'on' and cur is None:
            cur = t
        elif s != 'on' and cur is not None:
            iv.append((cur, t)); cur = None
    if cur is not None:
        iv.append((cur, t_end))
    return iv, len(h)

def union(ivs):
    ivs = sorted(ivs); out = []
    for a_, b_ in ivs:
        if out and a_ <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b_))
        else:
            out.append((a_, b_))
    return out

ev, missing = {}, []
for rn, c in rooms.items():
    allv = []
    for s in c['sensors']:
        iv, n = on_intervals(s)
        if iv is None:
            missing.append((rn, s)); continue
        allv += iv
    ev[rn] = union(allv)

def zone_other_occupied(rn, a_, b_, T):
    z = zone_of.get(rn)
    for o, c in rooms.items():
        if o == rn or zone_of.get(o) != z or c['type'] == 'hallway':
            continue
        for x, y in ev.get(o, []):
            if x < b_ and y + T > a_:
                return True
    return False

# ---- gaps ----
res = {}
allgaps = []
lategaps = []
for rn, c in sorted(rooms.items()):
    if c['type'] == 'hallway' or rn not in zone_of or c['disabled']:
        continue
    iv = ev[rn]
    stat = dict(mid=collections.Counter(), end=collections.Counter(), mids=collections.defaultdict(list),
                fr={}, zr={}, late={})
    for i in range(1, len(iv)):
        g0, g1 = iv[i - 1][1], iv[i][0]
        if excluded(g0, g1):
            continue
        L = g1 - g0
        b = bucket(g0)
        if L <= c['timeout']:
            stat['mid'][b] += 1; stat['mids'][b].append(L)
            allgaps.append((rn, b, L, g0))
            for T in TAILS:
                if L > T:
                    stat['fr'][(T, b)] = stat['fr'].get((T, b), 0) + 1
                    for G in GRACES:
                        if L > T + G and not zone_other_occupied(rn, g0 + T, g0 + T + G, T):
                            stat['zr'][(T, G, b)] = stat['zr'].get((T, G, b), 0) + 1
        else:
            stat['end'][b] += 1
            # LATE resume: longer than the lighting timeout, but evidence came back
            # before TODAY's design could retreat the zone for this room alone
            # (timeout + current day tail + grace). Today: no retreat; fix: possible.
            cur_tail = 120 if c['type'] == 'media_room' else 60
            for G in GRACES:
                if L <= c['timeout'] + cur_tail + G:
                    for T in TAILS:
                        if L > T + G and not zone_other_occupied(rn, g0 + T, g0 + T + G, T):
                            stat['late'][(T, G, b)] = stat['late'].get((T, G, b), 0) + 1
                            if T == TAILS[0]:
                                lategaps.append((rn, b, L, g0, G))
    res[rn] = stat

def pct(v, p):
    if not v: return '-'
    v = sorted(v); return round(v[min(len(v) - 1, int(p * len(v)))])

print(f'# window {time.strftime("%F %T", time.gmtime(t0))}Z .. {time.strftime("%F %T", time.gmtime(t_end))}Z; '
      f'included {DAYS_EFF:.2f} d; day-state hours {day_s/3600:.1f}; graces {GRACES}; restarts excluded {len(starts)}')
print('# missing sensor history:', missing)
for B in ('day', 'night'):
    print(f'\n## {B.upper()} — per room (MID gaps n, p50/p90/p99/max s; false releases/day at T; zone-retreat count (G={GRACES[0]}) at T; END n)')
    print('room|zone|type|mods|timeout|mid_n|p50|p90|p99|max|' + '|'.join(f'FR{T}/d' for T in TAILS) + '|' +
          '|'.join(f'ZR{T}' for T in TAILS) + '|' + '|'.join(f'ZR{T}g{GRACES[-1]}' for T in TAILS) + '|end_n')
    for rn, s in sorted(res.items(), key=lambda kv: (zone_of[kv[0]], kv[0])):
        c = rooms[rn]; m = s['mids'][B]
        print('|'.join(map(str, [rn, zone_of[rn], c['type'], '+'.join(c['mods']), int(c['timeout']), len(m),
              pct(m, .5), pct(m, .9), pct(m, .99), round(max(m)) if m else '-'] +
              [round(s['fr'].get((T, B), 0) / DAYS_EFF, 2) for T in TAILS] +
              [s['zr'].get((T, GRACES[0], B), 0) for T in TAILS] +
              [s['zr'].get((T, GRACES[-1], B), 0) for T in TAILS] + [s['end'][B]])))

def agg(key, B):
    groups = collections.defaultdict(lambda: dict(n=0, rooms=set(), fr=collections.Counter(), zr=collections.Counter(), zr2=collections.Counter(), L=[]))
    for rn, s in res.items():
        g = groups[key(rn)]; g['rooms'].add(rn); g['L'] += s['mids'][B]; g['n'] += len(s['mids'][B])
        for T in TAILS:
            g['fr'][T] += s['fr'].get((T, B), 0)
            g['zr'][T] += s['zr'].get((T, GRACES[0], B), 0)
            g['zr2'][T] += s['zr'].get((T, GRACES[-1], B), 0)
    return groups
for label, key in (('room type', lambda rn: rooms[rn]['type']),
                   ('modality', lambda rn: '+'.join(rooms[rn]['mods']))):
    for B in ('day', 'night'):
        print(f'\n## {B.upper()} by {label}')
        print('group|rooms|mid_n|p50|p90|p99|max|' + '|'.join(f'FR{T}/d' for T in TAILS) + '|' +
              '|'.join(f'ZR{T}' for T in TAILS) + '|' + '|'.join(f'ZR{T}g{GRACES[-1]}' for T in TAILS))
        for k, g in sorted(agg(key, B).items()):
            L = g['L']
            print('|'.join(map(str, [k, len(g['rooms']), g['n'], pct(L, .5), pct(L, .9), pct(L, .99), round(max(L)) if L else '-'] +
                  [round(g['fr'][T] / DAYS_EFF, 2) for T in TAILS] + [g['zr'][T] for T in TAILS] + [g['zr2'][T] for T in TAILS])))

def elsewhere(rn, a_, b_):
    return sorted(o for o, iv in ev.items() if o != rn and any(x < b_ and y > a_ for x, y in iv))

print('\n## LATE-resume zone-retreat risk (gap > timeout, resumed <= timeout+current_tail+G, zone otherwise empty) count by T, G, bucket')
for B in ('day', 'night'):
    for G in GRACES:
        print(B, 'G=%d' % G, {T: sum(s['late'].get((T, G, B), 0) for s in res.values()) for T in TAILS},
              'by room:', {rn: [s['late'].get((T, G, B), 0) for T in TAILS] for rn, s in res.items() if any(s['late'].get((T, G, B), 0) for T in TAILS)})
PHONES = ['sensor.iphone_oji_area', 'sensor.ezinne_iphone_area', 'sensor.iphone_jaya_area']
ph = {p_: (history(p_) or []) for p_ in PHONES}
def area_match(area, rn):
    a_, r_ = (area or '').lower(), rn.lower()
    return bool(a_) and (a_ == r_ or r_.startswith(a_) or a_.startswith(r_))
def phone_in_room(rn, a_, b_):
    """phones whose Bermuda area == this room for >= 50% of [a_, b_]; plus each phone's modal area."""
    hits, modal = [], {}
    for p_, h in ph.items():
        ts = [t for t, _ in h]; acc = collections.Counter()
        i0 = max(0, bisect.bisect_right(ts, a_) - 1)
        for j in range(i0, len(h)):
            t, st = h[j]
            if t >= b_: break
            t2 = h[j + 1][0] if j + 1 < len(h) else b_
            acc[st] += max(0, min(t2, b_) - max(t, a_))
        tot = sum(acc.values()) or 1
        inr = sum(v for k, v in acc.items() if area_match(k, rn))
        if inr / tot >= 0.5: hits.append(p_.split('.')[1])
        if acc: modal[p_.split('.')[1]] = acc.most_common(1)[0][0]
    return hits, modal

unav = {}
for rn_, c_ in rooms.items():
    for s_ in c_['sensors']:
        h = history(s_) or []
        unav[s_] = [(t, h[j + 1][0] if j + 1 < len(h) else t_end) for j, (t, st) in enumerate(h) if st in ('unavailable', 'unknown')]
def unavail_during(rn, a_, b_):
    return [s_.split('.')[1][:40] for s_ in rooms[rn]['sensors'] if any(x < b_ and y > a_ for x, y in unav[s_])]

def report(title, events):
    print(title)
    n_ble = n_un = 0
    for rn, b, L, g0 in events:
        hits, modal = phone_in_room(rn, g0, g0 + L)
        n_ble += bool(hits)
        un = unavail_during(rn, g0, g0 + L); n_un += bool(un)
        print(rn, 'UNAVAIL=' + (','.join(un) or '-'), time.strftime('%F %T', time.gmtime(g0)), round(L), house(g0), 'PHONE_IN_ROOM=' + (','.join(hits) or '-'),
              'phone_areas=', modal, 'evidence_elsewhere=', elsewhere(rn, g0, g0 + L))
    print(f'-- {len(events)} events, {n_ble} with a phone in-room >=50% of the gap, {n_un} with a configured sensor unavailable/unknown during the gap')

# fraction of ALL day MID gaps (>T) touched by sensor unavailability, per room
print('\n## DAY MID gaps > 60 s touched by a sensor unavailable/unknown during the gap (artifact share)')
for rn_ in sorted(res):
    gs = [(L, g0) for r2, b, L, g0 in allgaps if r2 == rn_ and b == 'day' and L > 60]
    if gs:
        k = sum(1 for L, g0 in gs if unavail_during(rn_, g0, g0 + L))
        print(rn_, len(gs), k)

G0 = GRACES[0]
mid_ev = [(rn, b, L, g0) for rn, b, L, g0 in allgaps
          if b == 'day' and L > TAILS[0] + G0 and not zone_other_occupied(rn, g0 + TAILS[0], g0 + TAILS[0] + G0, TAILS[0])]
late_ev = [(rn, b, L, g0) for rn, b, L, g0, G in lategaps if b == 'day' and G == G0]
report(f'\n## DAY MID-session zone-retreat-risk events (T={TAILS[0]}, G={G0})', sorted(mid_ev, key=lambda x: -x[2]))
report(f'\n## DAY LATE-resume zone-retreat-risk events (T={TAILS[0]}, G={G0})', sorted(late_ev, key=lambda x: -x[2]))

print('\n## Camera cross-check: rooms with a URA camera person sensor; MID gaps > T with camera person ON during the gap (radar/PIR silent, camera saw a person)')
import re
for rn_ in sorted(res):
    ent = 'binary_sensor.' + re.sub(r'[^a-z0-9]+', '_', rn_.lower()).strip('_') + '_camera_person_detected'
    civ, n = on_intervals(ent)
    if not civ:
        continue
    for B in ('day', 'night'):
        out = []
        for T in TAILS:
            gs = [(L, g0) for r2, b, L, g0 in allgaps if r2 == rn_ and b == B and L > T]
            k = sum(1 for L, g0 in gs if any(x < g0 + L and y > g0 + T for x, y in civ))
            out.append(f'T{T}: {k}/{len(gs)}')
        print(rn_, ent, B, ' '.join(out))
    # re-run the gap count with camera person merged INTO the evidence union
    iv2 = union(ev[rn_] + civ); tmo = rooms[rn_]['timeout']
    cnt = collections.Counter(); late = collections.Counter()
    for i in range(1, len(iv2)):
        g0, g1 = iv2[i - 1][1], iv2[i][0]
        if excluded(g0, g1) or bucket(g0) != 'day':
            continue
        L = g1 - g0
        for T in TAILS:
            if L > T and L <= tmo:
                cnt[T] += 1
            if L > T + GRACES[0] and L <= tmo + 60 + GRACES[0] and not zone_other_occupied(rn_, g0 + T, g0 + T + GRACES[0], T):
                late[T] += 1
    print(rn_, 'raw+camera DAY: MID gaps > T per day', {T: round(cnt[T] / DAYS_EFF, 2) for T in TAILS},
          '| zone-retreat-risk (MID+LATE, G=%d)' % GRACES[0], dict(late))

print('\n## DAY raw-evidence duty cycle (fraction of day-state time with evidence on), non-zone rooms included')
dayiv = [(t, hs[i + 1][0] if i + 1 < len(hs) else t_end) for i, (t, st) in enumerate(hs) if st in DAY]
for rn in sorted(ev):
    on = sum(max(0, min(y, d1) - max(x, d0, t0)) for x, y in ev[rn] for d0, d1 in dayiv if x < d1 and y > d0)
    print(rn, round(on / max(day_s, 1), 3))
