#!/usr/bin/env python3
"""D-A0 night still-sleeper probe (PLANNING_hvac_w2_night_sleeper_and_placeholder_readers.md).

READ-ONLY. Run on the HA host against the recorder:

    ssh ha "python3 - [--days 7] [--verbose]" < scripts/probes/hvac_night_sleeper_probe.py

For every bedroom-typed URA room, over the last N nights (drop time in 22:00-08:00 local,
America/Chicago, CDT = UTC-5 in the recorder window), enumerate episodes where the room's
`binary_sensor.<room>_<room>_hvac_occupied` fell on->off, and classify:

  * RETURNED  - came back on within <= RETURN_MAX_MIN (still-sleeper candidate)
  * STAYED    - stayed off > RETURN_MAX_MIN (or until the window/data ended)

Per episode (gap = [drop, min(return, drop + RETURN_MAX_MIN)]):
  (a) BLE: for each bound person (else each zone person) - time-weighted fraction of the gap
      Bermuda `*_area` was in the room's suite (room area + en-suite/scanner areas), and the
      std-dev / range of Bermuda `*_distance` (ft) inside the gap -> "stationary in-suite" when
      in-suite >= 90% and std <= 3 ft (plan's provisional threshold).
  (b) radar/raw micro-blips: off->on transitions of the room's configured presence / motion /
      occupancy sensors inside the gap, EXCLUDING the final RETURN_TRIGGER_S (330 s) before a
      return (that blip is the return trigger - see note at the constant).
  (c) BLE degraded: area/distance unknown/unavailable in the gap, or no distance update for
      > BLE_STALE_MIN inside the gap.
  (d) thermostat: zone climate `preset_mode` or `hold_activity` == "away" at any point in
      [drop, gap_end]; plus whether the zone's fused `any_room_hvac_occupied` went False.

Room / sensor / zone mapping is pinned below from `.storage/core.config_entries`
(read 2026-09-26). Re-verify it if rooms are reconfigured.
"""
import json
import sqlite3
import statistics
import sys
import time

DB = "file:/config/home-assistant_v2.db?mode=ro"
TZ_OFFSET_S = -5 * 3600  # CDT
RETURN_MAX_MIN = 90
STATIONARY_STD_FT = 3.0
IN_SUITE_FRAC = 0.90
BLE_STALE_MIN = 15
# A raw blip lifts the room's grace-held STATE_OCCUPIED immediately, but the D1 producer
# (_compute_hvac_occupied, hvac_zones.py:966) only re-arms on its next pass (measured lag
# 25 s - 4 min, decision-tick cadence). Blips within this window before the return ARE the
# return trigger; only blips earlier than that are "non-returning" micro-blips.
RETURN_TRIGGER_S = 330

args = sys.argv[1:]
DAYS = int(args[args.index("--days") + 1]) if "--days" in args else 7
VERBOSE = "--verbose" in args

ZONES = {
    "zone_1": ("climate.thermostat_bryant_wifi_studyb_zone_1", "sensor.ura_hvac_coordinator_zone_1_status"),
    "zone_2": ("climate.up_hallway_zone_2", "sensor.ura_hvac_coordinator_zone_2_status"),
    "zone_3": ("climate.back_hallway_zone_3", "sensor.ura_hvac_coordinator_zone_3_status"),
}
PERSON_ENT = {"jaya": "person.jaya", "ziri": "person.ziri", "oji": "person.oji_udezue",
              "ezinne": "person.ezinne"}
PERSONS = {  # Bermuda
    "jaya": ("sensor.iphone_jaya_area", "sensor.iphone_jaya_distance"),
    "ziri": ("sensor.iphone_ziri_area", "sensor.iphone_ziri_distance"),
    "oji": ("sensor.iphone_oji_area", "sensor.iphone_oji_distance"),
    "ezinne": ("sensor.ezinne_iphone_area", "sensor.ezinne_iphone_distance"),
}
ZONE_PERSONS = {"zone_1": ["oji", "ezinne"], "zone_2": ["ziri", "jaya"], "zone_3": []}

# bedroom-typed rooms (room_type == "bedroom" in config entries)
ROOMS = [
    dict(room="Jaya Bedroom", zone="zone_2", bound=["jaya"],
         hvac="binary_sensor.jaya_bedroom_jaya_bedroom_hvac_occupied",
         suite={"Jaya Bedroom", "Jaya Bathroom"},
         raw=["binary_sensor.jaya_3_presence", "binary_sensor.mmwave_zigbee_jayabedroom_presence"]),
    dict(room="Ziri Bedroom", zone="zone_2", bound=["ziri"],
         hvac="binary_sensor.ziri_bedroom_ziri_bedroom_bedroom_5_hvac_occupied",
         suite={"Ziri Bedroom", "Ziri Bathroom", "Balcony"},
         raw=["binary_sensor.ziri_3_presence", "binary_sensor.mmwave_zigbee_ziribedroom_presence",
              "binary_sensor.ziri_3_moving_target"]),
    dict(room="Upstairs Guestroom", zone="zone_2", bound=[],
         hvac="binary_sensor.guest_bedroom_2_guest_bedroom_2_hvac_occupied",
         suite={"Guest Bedroom 2", "Guest Bedroom 2 Bath", "Guest Bedroom 2 Closet"},
         raw=["binary_sensor.mmwave_motion_lux_meross_wifi_jaya_sensor_presence_motion",
              "binary_sensor.occupancy_lux_temp_humidity_hobeian_upguestroom_presence_2",
              "binary_sensor.mmwave_motion_lux_matter_wifi_guestbedroom2_occupancy"]),
    dict(room="Master Bedroom", zone="zone_1", bound=["oji", "ezinne"],
         hvac="binary_sensor.master_bedroom_master_bedroom_hvac_occupied",
         suite={"Master Bedroom", "Master Bathroom", "Oji Vanity", "Ezinne Vanity", "Ezinne Makeup"},
         raw=["binary_sensor.screek_human_sensor_l13_b38b24_presence",
              "binary_sensor.mmwave_temp_hum_lux_zigbee_masterbedroom_presence",
              "binary_sensor.switch_mmwave_inovelli_occupancy",
              "binary_sensor.bed_presence_2bd7b4_bed_occupied_either_fast"]),
    dict(room="Guest Bedroom 1", zone="zone_3", bound=[],
         hvac="binary_sensor.guest_bedroom_1_guest_bedroom_1_hvac_occupied",
         suite={"Guest Bedroom 1", "Guest Bedroom 1 Bathroom"},
         raw=["binary_sensor.mmwave_motion_lux_matter_wifi_guestbedroom1_occupancy",
              "binary_sensor.occupancy_lux_temp_humidity_hobeian_downguestroom_presence_2",
              "binary_sensor.smart_presence_sensor_24111917146201662002c4e7ae109bd3_sensor_presence_motion"]),
    dict(room="Guest Bedroom 1 Closet", zone="zone_3", bound=[],
         hvac="binary_sensor.guest_bedroom_1_closet_guest_bedroom_1_closet_hvac_occupied",
         suite={"Guest Bedroom 1", "Guest Bedroom 1 Bathroom"},
         raw=["binary_sensor.occupancy_lux_temp_humidity_hobeian_dnguestcloset_presence_2"]),
]

BAD = ("unknown", "unavailable", "", None)

c = sqlite3.connect(DB, uri=True)
NOW = time.time()
T0 = NOW - DAYS * 86400 - 12 * 3600


def loc(ts):
    return time.strftime("%m-%d %H:%M", time.gmtime(ts + TZ_OFFSET_S))


def series(eid, attrs=False):
    """[(ts, state, attrs_dict_or_None)] from T0-6h, with the last row before that as a seed."""
    m = c.execute("SELECT metadata_id FROM states_meta WHERE entity_id=?", (eid,)).fetchone()
    if not m:
        return None
    sel = "s.last_updated_ts, s.state" + (", a.shared_attrs" if attrs else ", NULL")
    q = (f"SELECT {sel} FROM states s LEFT JOIN state_attributes a ON s.attributes_id=a.attributes_id "
         "WHERE s.metadata_id=? AND s.last_updated_ts>=? ORDER BY s.last_updated_ts")
    rows = c.execute(q, (m[0], T0 - 6 * 3600)).fetchall()
    out = []
    for ts, st, at in rows:
        out.append((ts, st, json.loads(at) if at else None))
    return out


def transitions(ser):
    """collapse attribute-only rows -> [(ts, state)] on state change"""
    out = []
    for ts, st, _ in ser:
        if not out or out[-1][1] != st:
            out.append((ts, st))
    return out


def state_at(trans, ts):
    cur = None
    for t, s in trans:
        if t > ts:
            break
        cur = s
    return cur


def in_night(ts):
    h = time.gmtime(ts + TZ_OFFSET_S).tm_hour
    return h >= 22 or h < 8


def night_label(ts):
    lt = ts + TZ_OFFSET_S
    if time.gmtime(lt).tm_hour < 8:
        lt -= 86400
    g = time.gmtime(lt)
    g2 = time.gmtime(lt + 86400)
    return f"{g.tm_mon:02d}-{g.tm_mday:02d}/{g2.tm_mday:02d}"


# ---- load
cache = {}


def get(eid, attrs=False):
    k = (eid, attrs)
    if k not in cache:
        cache[k] = series(eid, attrs)
    return cache[k]


def ble_eval(person, suite, a, b):
    area_e, dist_e = PERSONS[person]
    ar = transitions(get(area_e) or [])
    ds = get(dist_e) or []
    # time-weighted in-suite fraction over [a, b]
    pts = [(a, state_at(ar, a))] + [(t, s) for t, s in ar if a < t < b]
    tot = insu = 0.0
    bad = False
    areas = set()
    for i, (t, s) in enumerate(pts):
        t2 = pts[i + 1][0] if i + 1 < len(pts) else b
        dur = t2 - t
        tot += dur
        areas.add(s)
        if s in BAD:
            bad = True
        elif s in suite:
            insu += dur
    frac = insu / tot if tot else 0.0
    # distance
    prev = [r for r in ds if r[0] <= a][-1:]  # seed value
    inside = [r for r in ds if a < r[0] < b]
    vals = []
    for _, st, _ in prev + inside:
        if st in BAD:
            bad = True
            continue
        try:
            vals.append(float(st))
        except ValueError:
            bad = True
    stamps = [a] + [r[0] for r in inside] + [b]
    max_silence = max((stamps[i + 1] - stamps[i]) for i in range(len(stamps) - 1)) / 60
    if max_silence > BLE_STALE_MIN:
        bad = True
    std = statistics.pstdev(vals) if len(vals) >= 2 else None
    rng = (max(vals) - min(vals)) if vals else None
    stationary = (frac >= IN_SUITE_FRAC and std is not None and std <= STATIONARY_STD_FT)
    return dict(person=person, in_suite=round(frac, 2), std=None if std is None else round(std, 1),
                rng=None if rng is None else round(rng, 1), n=len(vals), silence=round(max_silence, 1),
                degraded=bad, stationary=stationary,
                areas=sorted(x for x in areas if x is not None)[:5])


def blips(eids, a, b):
    out = {}
    unav = []
    for e in eids:
        ser = get(e)
        if ser is None:
            out[e] = None
            continue
        tr = transitions(ser)
        n = 0
        prev = state_at(tr, a)
        for t, s in tr:
            if a < t < b - RETURN_TRIGGER_S and s == "on" and prev != "on":
                n += 1
            if a < t < b:
                prev = s
        # unavailable during gap?
        st0 = state_at(tr, a)
        if st0 in BAD or any(s in BAD for t, s in tr if a < t < b):
            unav.append(e.split(".", 1)[1])
        out[e] = n
    return out, unav


def zone_eval(zone, a, b):
    cl_e, zs_e = ZONES[zone]
    cl = get(cl_e, attrs=True) or []
    away_ts = None
    seed = [r for r in cl if r[0] <= a][-1:]
    for ts, st, at in seed + [r for r in cl if a < r[0] <= b]:
        if at and (at.get("preset_mode") == "away" or at.get("hold_activity") == "away"):
            away_ts = max(ts, a)
            break
    back_ts = None
    if away_ts:
        for ts, st, at in [r for r in cl if r[0] > away_ts and r[0] <= away_ts + 6 * 3600]:
            if at and at.get("preset_mode") not in ("away", None) and at.get("hold_activity") != "away":
                back_ts = ts
                break
    zs = get(zs_e, attrs=True) or []
    fused_false_ts = None
    seed = [r for r in zs if r[0] <= a][-1:]
    for ts, st, at in seed + [r for r in zs if a < r[0] <= b]:
        if at and at.get("any_room_hvac_occupied") is False:
            fused_false_ts = max(ts, a)
            break
    return away_ts, fused_false_ts, back_ts


def house_state(ts):
    tr = transitions(get("sensor.ura_coordinator_manager_house_state") or [])
    return state_at(tr, ts)


episodes = []
for R in ROOMS:
    ser = get(R["hvac"])
    if not ser:
        continue
    tr = transitions(ser)
    for i, (t, s) in enumerate(tr):
        if s != "off" or i == 0 or tr[i - 1][1] != "on" or t < NOW - DAYS * 86400 - 8 * 3600:
            continue
        if not in_night(t):
            continue
        # next on
        ret = None
        unav_in_gap = False
        for t2, s2 in tr[i + 1:]:
            if s2 == "on":
                ret = t2
                break
            if s2 in BAD:
                unav_in_gap = True
        gap_min = (ret - t) / 60 if ret else None
        returned = ret is not None and gap_min <= RETURN_MAX_MIN
        censored = (ret is None) and (NOW - t) / 60 <= RETURN_MAX_MIN
        end = ret if returned else min(t + RETURN_MAX_MIN * 60, NOW)
        people = R["bound"] or ZONE_PERSONS[R["zone"]]
        ble = [ble_eval(p, R["suite"], t, end) for p in people]
        bl, unav = blips(R["raw"], t, end)
        away_ts, fused_ts, back_ts = zone_eval(R["zone"], t, end)
        pstate = {p: state_at(transitions(get(PERSON_ENT[p]) or []), t) for p in people}
        episodes.append(dict(
            room=R["room"], zone=R["zone"], night=night_label(t), drop=t, drop_l=loc(t),
            ret_l=loc(ret) if ret else None, gap_min=None if gap_min is None else round(gap_min, 1),
            cls="CENSORED" if censored else ("RETURNED" if returned else "STAYED"),
            hs=house_state(t), ble=ble, bound=bool(R["bound"]),
            blips=sum(v for v in bl.values() if v), blips_by={k.split(".", 1)[1]: v for k, v in bl.items()},
            raw_unav=unav, hvac_unav_in_gap=unav_in_gap,
            away_l=loc(away_ts) if away_ts else None,
            away_min=round((away_ts - t) / 60, 1) if away_ts else None,
            fused_false_l=loc(fused_ts) if fused_ts else None,
            away_dur=round((back_ts - away_ts) / 60, 1) if (away_ts and back_ts) else None,
            pstate=pstate))

# ---- print
print(f"# D-A0 night still-sleeper probe  now={loc(NOW)} CDT  days={DAYS}  "
      f"return<= {RETURN_MAX_MIN}m  stationary: in-suite>={IN_SUITE_FRAC:.0%} & std<={STATIONARY_STD_FT}ft")
print("room|night|drop|return|gap_min|class|house|person_state|BLE(person:in_suite/std/range/n/silence/deg/STAT)|nonreturn_blips|raw_unavail|zone_away_at(+min)|zone_away_dur_min|fused_false_at")
for e in episodes:
    b = ";".join(f"{x['person']}:{x['in_suite']}/{x['std']}/{x['rng']}/{x['n']}/{x['silence']}m/"
                 f"{'DEG' if x['degraded'] else 'ok'}/{'STAT' if x['stationary'] else '-'}" for x in e["ble"]) or "no-person"
    ps = ",".join(f"{k}={v}" for k, v in e["pstate"].items()) or "-"
    print(f"{e['room']}|{e['night']}|{e['drop_l']}|{e['ret_l']}|{e['gap_min']}|{e['cls']}|{e['hs']}|{ps}|{b}|"
          f"{e['blips']}|{','.join(e['raw_unav']) or '-'}|"
          f"{(e['away_l'] + ' (+' + str(e['away_min']) + ')') if e['away_l'] else '-'}|{e['away_dur']}|"
          f"{e['fused_false_l'] or '-'}")
    if VERBOSE:
        print("    blips_by:", e["blips_by"], " areas:", [x["areas"] for x in e["ble"]])


def summarize(rows, label):
    n = len(rows)
    ret = [r for r in rows if r["cls"] == "RETURNED"]
    stay = [r for r in rows if r["cls"] == "STAYED"]
    stat = [r for r in rows if any(x["stationary"] for x in r["ble"])]
    deg = [r for r in rows if r["ble"] and all(x["degraded"] for x in r["ble"])]
    anydeg = [r for r in rows if any(x["degraded"] for x in r["ble"])]
    blip = [r for r in rows if r["blips"] > 0]
    away = [r for r in rows if r["away_l"]]
    gaps = sorted(r["gap_min"] for r in ret)
    med = statistics.median(gaps) if gaps else None
    stat_ret = [r for r in stat if r["cls"] == "RETURNED"]
    stat_blip = [r for r in stat if r["blips"] > 0]
    stat_away = [r for r in stat if r["away_l"]]
    print(f"{label}|{n}|{len(ret)}|{len(stay)}|{med}|{len(stat)}|{len(stat_ret)}|{len(stat_blip)}|"
          f"{len(stat_away)}|{len(blip)}|{len(ret and [r for r in ret if r['blips']>0])}|{len(anydeg)}|{len(deg)}|{len(away)}")


print("\nroom|drops|returned<=90|stayed|median_return_gap|N_stationary_in_suite|stat&returned|stat&blip|"
      "stat&zone_away|any_blip|returned&blip|BLE_any_degraded|BLE_all_degraded|zone_away_in_gap")
for R in ROOMS:
    summarize([e for e in episodes if e["room"] == R["room"]], R["room"])
summarize([e for e in episodes if e["bound"]], "TOTAL(bound-person rooms)")
summarize(episodes, "TOTAL(all bedrooms)")


# ---- per-person night BLE availability (sizes INV-A3 no-op fraction)
print("\nperson|night_hours_home|area_bad_frac_while_home|area_in_own_suite_frac_while_home")
OWN_SUITE = {"jaya": ROOMS[0]["suite"], "ziri": ROOMS[1]["suite"], "oji": ROOMS[3]["suite"],
             "ezinne": ROOMS[3]["suite"]}
start = NOW - DAYS * 86400
for p, (area_e, _) in PERSONS.items():
    ar = transitions(get(area_e) or [])
    pe = transitions(get(PERSON_ENT[p]) or [])
    step = 60
    home = bad = own = 0
    t = start
    while t < NOW:
        if in_night(t) and state_at(pe, t) == "home":
            home += 1
            a = state_at(ar, t)
            if a in BAD:
                bad += 1
            elif a in OWN_SUITE[p]:
                own += 1
        t += step
    print(f"{p}|{home / 60:.1f}|{(bad / home) if home else 0:.2f}|{(own / home) if home else 0:.2f}")
