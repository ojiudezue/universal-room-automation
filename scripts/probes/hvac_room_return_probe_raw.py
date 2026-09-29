#!/usr/bin/env python3
"""HVAC hold-sizing probe re-based on RAW per-room presence sensors — READ-ONLY.

Card: HVAC-HOLD-SIZING-ALL-ROOMS-1. Supersedes the presence-truth of
scripts/probes/hvac_room_return_probe.py, which used the lagged
binary_sensor.*_hvac_occupied (5-min decision-tick artifacts, C18).

    ssh ha "python3 - [--end-utc 2026-09-28T23:44:00] [--days 7] [--verbose]" \
        < scripts/probes/hvac_room_return_probe_raw.py

Emits TWO windows: PRE-SHIP baseline = DAYS days ending at --end-utc (default
2026-09-28 18:44 CDT = the v5.103.20 fast-path ship), and POST-SHIP = --end-utc -> now
(labelled INSUFFICIENT if < 3 days).

Truth: a room is RAW-PRESENT while ANY of its configured motion_sensors /
presence_sensors (CONF_MMWAVE_SENSORS) / occupancy_sensors reads 'on'; on-intervals
closer than MERGE_GAP_S are joined. Room/zone/sensor map pinned below from
.storage/core.config_entries (Zone Manager `zones[*].zone_thermostat` + `zone_rooms`,
merged per thermostat exactly as hvac_zones.discover_zones, hvac_zones.py:395-526);
re-pin if rooms are reconfigured.

Zone-away WRITE = ura_activity_log action=preset_change new_preset=away (the S1 site —
the only occupancy-driven away writer). Writes are collapsed into AWAY EPISODES (first
away write until the next non-away preset write for that zone, from preset_change OR
climate_write set_preset_mode) so the zone_1 away re-write churn (§9.7) is not
multi-counted.

Per episode (W = first away write):
  DURING    a non-hallway room of the zone is raw-present at W
              ENTRY-RACE          raw onset <= ENTRY_RACE_S before W (decision latency)
              STILL-BODY-MISSED   a still-body sensor (mmWave/radar/bed) on at W, sustained
              MOTION-ON-MISSED    only motion-kind sensors on at W, sustained
  RETURNED  zone raw-empty at W, a non-hallway room raw-present within RETURN_MIN after W,
            and the zone had been raw-empty < ARRIVAL_MIN before W
              HOLD-TOO-SHORT        last-occupied room has a still-body sensor
              MOTION-ONLY-COVERAGE  last-occupied room has motion-kind sensors only
  TRANSIT-RETURN  the return stayed < RETURN_STAY_MIN (a pass-through; not harm)
  OVERRIDE-VACANT the attributed room's Override Vacant switch was ON at W (forced vacant; config, not hold)
  STUCK-EXCLUDED  still-body sensor continuously on >= P22_STUCK_H at W (URA's stuck-sensor exclusion,
                  coordinator.py:364/:2114, drops a legitimately long-on radar)
  POLICY-AWAY-*   write reason is not vacant_past_grace (house away transition / energy-shed cap)
  ARRIVAL   returned within RETURN_MIN but zone raw-empty >= ARRIVAL_MIN before W (not a hold issue)
  CLEAN     no raw presence at W or within RETURN_MIN
Hallways are circulation-excluded from HVAC occupancy by design (hvac_zones.py
arm_source="hallway_excluded"); hallway presence is reported (hall_only) but never harm.
"""
import calendar
import json
import sqlite3
import statistics
import sys
import time
from datetime import datetime

MERGE_GAP_S = 120          # join a room's raw on-intervals separated by <= 2 min
RETURN_MIN = 30            # "returned within" window after the away write
ENTRY_RACE_S = 300         # raw onset this close before W = decision latency, not a miss
ARRIVAL_MIN = 60           # zone raw-empty this long before W -> an arrival, not a return
STUCK_ON_H = 6             # a still-body interval longer than this at W is flagged suspect-stuck
RETURN_STAY_MIN = 5        # a return must stay raw-present >= this (merged) to count; shorter = TRANSIT
P22_STUCK_H = 4.0          # coordinator.py:364 _stuck_sensor_hours (hard-coded) -> sensor excluded after 4 h continuous on
VACANCY_REASONS = ("vacant_past_grace",)  # S1 occupancy-driven aways; others = policy (house away / energy shed)
TZ_OFFSET_S = -5 * 3600    # CDT

a = sys.argv[1:]
END_UTC = a[a.index("--end-utc") + 1] if "--end-utc" in a else "2026-09-28T23:44:00"
DAYS = float(a[a.index("--days") + 1]) if "--days" in a else 7.0
VERBOSE = "--verbose" in a
T_SHIP = calendar.timegm(time.strptime(END_UTC, "%Y-%m-%dT%H:%M:%S"))
NOW = time.time()

CLIMATE = {"zone_1": "climate.thermostat_bryant_wifi_studyb_zone_1",
           "zone_2": "climate.up_hallway_zone_2", "zone_3": "climate.back_hallway_zone_3"}

# (room, room_type, zone, [sensors]) — config keys motion_sensors + presence_sensors +
# occupancy_sensors, pinned from .storage/core.config_entries 2026-09-29.
ROOMS = [
    # zone_1 = Zone Manager "Entertainment" + "Master Suite" (shared thermostat)
    ("Living Room", "common_area", "zone_1", ["binary_sensor.mmwave_temp_lux_hum_zigbee_livingroom_presence", "binary_sensor.screek_human_sensor_l13_2412s_presence", "binary_sensor.mmwave_lux_temp_hum_zigbee_livingroom_presence"]),
    ("Receiving Room", "common_area", "zone_1", ["binary_sensor.occupancy_lux_temp_humidity_hobeian_receiving_presence"]),
    ("Foyer", "hallway", "zone_1", ["binary_sensor.occupancy_lux_temp_humidity_hobeian_entry_presence"]),
    ("Study A", "generic", "zone_1", ["binary_sensor.mmwave_zigbee_studya_presence"]),
    ("Study B", "generic", "zone_1", ["binary_sensor.mmwave_lux_wifi_esphome_studyb_presence"]),
    ("Master Bedroom", "bedroom", "zone_1", ["binary_sensor.screek_human_sensor_l13_b38b24_presence", "binary_sensor.mmwave_temp_hum_lux_zigbee_masterbedroom_presence", "binary_sensor.switch_mmwave_inovelli_occupancy", "binary_sensor.bed_presence_2bd7b4_bed_occupied_either_fast"]),
    ("Study A Closet", "closet", "zone_1", ["binary_sensor.occupancy_lux_temp_humidity_studyacloset_presence"]),
    ("AV Closet", "infrastructure", "zone_1", ["binary_sensor.occupancy_lux_temp_humidity_avcloset_presence"]),
    ("Master Bathroom", "bathroom", "zone_1", ["binary_sensor.outlet_lux_pir_mmwave_temp_voc_pressure_invisoutet_mqtt_masterbath_motion", "binary_sensor.outlet_lux_pir_mmwave_temp_voc_pressure_invisoutet_mqtt_masterbath_occupancy"]),
    ("Oji Vanity", "bathroom", "zone_1", ["binary_sensor.pir_zigbee_ojivanity_occupancy"]),
    ("Master Bath Toilet", "bathroom", "zone_1", ["binary_sensor.rgbw_motion_lux_3rdr_wifi_matter_mastertoilet_occupancy"]),
    ("Master Hallway", "hallway", "zone_1", ["binary_sensor.rgbw_motion_lux_3rd_zigbee_masterhallway_occupancy", "binary_sensor.mmwave_temp_lux_hum_masterhallway_presence"]),
    # zone_2 = "Upstairs"
    ("Guest Bedroom 2", "bedroom", "zone_2", ["binary_sensor.mmwave_motion_lux_meross_wifi_jaya_sensor_presence_motion", "binary_sensor.occupancy_lux_temp_humidity_hobeian_upguestroom_presence_2", "binary_sensor.mmwave_motion_lux_matter_wifi_guestbedroom2_occupancy"]),
    ("Guest Bedroom 2 Bathroom", "bathroom", "zone_2", ["binary_sensor.smart_night_light_w_occupancy"]),
    ("Media Room Closet", "closet", "zone_2", ["binary_sensor.pir_zigbee_mediacloset_occupancy"]),
    ("Exercise Room Closet", "closet", "zone_2", ["binary_sensor.pir_zigbee_exercisecloset_occupancy"]),
    ("Ziri Bedroom", "bedroom", "zone_2", ["binary_sensor.ziri_3_moving_target", "binary_sensor.ziri_3_presence", "binary_sensor.mmwave_zigbee_ziribedroom_presence"]),
    ("Jaya Bedroom", "bedroom", "zone_2", ["binary_sensor.jaya_3_presence", "binary_sensor.mmwave_zigbee_jayabedroom_presence"]),
    ("Game Room", "common_area", "zone_2", ["binary_sensor.0xa4c1382e60e05225_presence"]),
    ("Media", "media_room", "zone_2", ["binary_sensor.mmwave_motion_lux_meross_wifi_mediaroom_sensor_presence_motion", "binary_sensor.mmwave_motion_lux_matter_wifi_mediaroom_occupancy"]),
    ("Exercise Room", "common_area", "zone_2", ["binary_sensor.rgbw_motion_lux_3rd_zigbee_exercise_occupancy", "binary_sensor.occupancy_lux_temp_humidity_hobeian_exercise_presence_2", "binary_sensor.mmwave_zigbee_gameroom_presence"]),
    ("Jaya Bathroom", "bathroom", "zone_2", ["binary_sensor.pir_zigbee_jayabathroom_occupancy"]),
    ("Ziri Bathroom", "bathroom", "zone_2", ["binary_sensor.rgbw_motion_lux_3rdr_wifi_matter_ziribath_occupancy"]),
    ("Upstairs Hallway", "hallway", "zone_2", ["binary_sensor.mmwavemotion_lux_temp_hum_upstairshallway_presence"]),
    ("Up Guestbedroom Closet", "closet", "zone_2", ["binary_sensor.pir_zigbee_guestbedroom2_closet_occupancy"]),
    ("Guest Bedroom 2 Hallway", "hallway", "zone_2", ["binary_sensor.pir_zigbee_upguesthallway_occupancy"]),
    # zone_3 = "Back Hallway"
    ("Guest Bedroom 1 Bathroom", "bathroom", "zone_3", ["binary_sensor.rgbw_lux_motion_3rdr_wifi_matter_guestroom1bath_occupancy"]),
    ("Stair Closet", "closet", "zone_3", ["binary_sensor.rgbw_motion_lux_3rdr_wifi_matter_staircloset_occupancy"]),
    ("Laundry Closet", "closet", "zone_3", ["binary_sensor.occupancy_lux_temp_humidity_hobeian_utilitycloset_presence_2"]),
    ("Kitchen Hallway", "hallway", "zone_3", ["binary_sensor.occupancy_lux_temp_humidity_stairkitchenhallway_presence"]),
    ("Guest Bedroom 1", "bedroom", "zone_3", ["binary_sensor.occupancy_lux_temp_humidity_hobeian_downguestroom_presence_2", "binary_sensor.smart_presence_sensor_24111917146201662002c4e7ae109bd3_sensor_presence_motion", "binary_sensor.mmwave_motion_lux_matter_wifi_guestbedroom1_occupancy"]),
    ("Kitchen", "common_area", "zone_3", ["binary_sensor.motiontempluxhum_protect_blu_kitchen_motion", "binary_sensor.mmwave_lux_wifi_esphome_kitchen_presence", "binary_sensor.mmwave_lux_temp_humidity_zigbee_kitchen_presence"]),
    ("Breakfast Nook", "common_area", "zone_3", ["binary_sensor.occupancy_lux_temp_humidity_hobeian_breakfast_presence_2"]),
    ("Dining Room", "common_area", "zone_3", ["binary_sensor.occupancy_lux_temp_humidity_hobeian_dining_presence"]),
    ("Garage Hallway", "hallway", "zone_3", ["binary_sensor.rgbw_motion_lux_3rdr_zigbee_garagehallway_occupancy_2", "binary_sensor.mmwave_temp_hum_lux_garagehallway_presence"]),
    ("Kitchen Hallway Garage", "hallway", "zone_3", ["binary_sensor.occupancy_lux_temp_humidity_garagekitchenhallway_presence"]),
    ("Kitchen Pantry", "utility", "zone_3", ["binary_sensor.rgbw_motion_lux_3rdr_wifi_matter_pantry_occupancy"]),
    ("Butler Pantry", "common_area", "zone_3", ["binary_sensor.occupancy_lux_temp_humidity_hobeian_butler_presence_2"]),
    ("Laundry", "utility", "zone_3", ["binary_sensor.rgbw_lux_motion_3rdr_wifi_matter_laundry_occupancy"]),
    ("Guest Bedroom 1 Closet", "closet", "zone_3", ["binary_sensor.occupancy_lux_temp_humidity_hobeian_dnguestcloset_presence_2"]),
]


# URA's own per-room signals (entity registry, unique_id *_occupied / *_hvac_occupied), pinned 2026-09-29
URA_ENT = {
    "AV Closet": ("binary_sensor.av_closet_occupied", "binary_sensor.av_closet_av_closet_hvac_occupied"),
    "Breakfast Nook": ("binary_sensor.breakfast_nook_occupied", "binary_sensor.breakfast_breakfast_nook_hvac_occupied"),
    "Butler Pantry": ("binary_sensor.butler_pantry_occupied", "binary_sensor.butler_pantry_butler_pantry_hvac_occupied"),
    "Dining Room": ("binary_sensor.dining_room_occupied", "binary_sensor.dining_room_dining_room_hvac_occupied"),
    "Exercise Room": ("binary_sensor.exercise_room_occupied", "binary_sensor.exercise_room_exercise_room_hvac_occupied"),
    "Game Room": ("binary_sensor.game_room_occupied", "binary_sensor.game_room_game_room_hvac_occupied"),
    "Guest Bedroom 1": ("binary_sensor.guest_bedroom_1_occupied", "binary_sensor.guest_bedroom_1_guest_bedroom_1_hvac_occupied"),
    "Guest Bedroom 2": ("binary_sensor.upstairs_guest_bedroom_occupied", "binary_sensor.guest_bedroom_2_guest_bedroom_2_hvac_occupied"),
    "Jaya Bedroom": ("binary_sensor.jaya_bedroom_bedroom_4_occupied", "binary_sensor.jaya_bedroom_jaya_bedroom_hvac_occupied"),
    "Kitchen": ("binary_sensor.kitchen_occupied", "binary_sensor.kitchen_kitchen_hvac_occupied"),
    "Kitchen Pantry": ("binary_sensor.kitchen_pantry_occupied", "binary_sensor.pantry_kitchen_pantry_hvac_occupied"),
    "Laundry": ("binary_sensor.laundry_occupied", "binary_sensor.laundry_laundry_hvac_occupied"),
    "Living Room": ("binary_sensor.living_room_occupied", "binary_sensor.living_room_living_room_hvac_occupied"),
    "Master Bathroom": ("binary_sensor.master_bathroom_occupied", "binary_sensor.master_bathroom_master_bathroom_hvac_occupied"),
    "Master Bedroom": ("binary_sensor.master_bedroom_occupied", "binary_sensor.master_bedroom_master_bedroom_hvac_occupied"),
    "Media": ("binary_sensor.media_room_occupied", "binary_sensor.media_room_media_room_hvac_occupied"),
    "Receiving Room": ("binary_sensor.receiving_room_occupied", "binary_sensor.receiving_room_receiving_room_hvac_occupied"),
    "Study A": ("binary_sensor.study_a_occupied", "binary_sensor.study_a_study_a_hvac_occupied"),
    "Study B": ("binary_sensor.study_b_occupied", "binary_sensor.study_b_study_b_hvac_occupied"),
    "Ziri Bedroom": ("binary_sensor.ziri_bedroom_bedroom_5_occupied", "binary_sensor.ziri_bedroom_ziri_bedroom_bedroom_5_hvac_occupied"),
}

# Room Override Vacant switches seen ON in the recorder (sweep printed at the end catches new ones)
OVERRIDE_VACANT = {"Kitchen": "switch.kitchen_override_vacant", "Exercise Room": "switch.exercise_room_override_vacant"}


def kind(eid):
    """STILL = radar / mmWave / bed sensor that holds a motionless body; MOTION = PIR-class.
    Name heuristic (hardware models inferred from entity names) — printed for audit."""
    n = eid.lower()
    if "moving_target" in n or n.startswith("binary_sensor.pir_") or "_pir_" in n and n.endswith("_motion"):
        return "MOTION"
    if n.endswith("_motion") and "presence_motion" not in n:
        return "MOTION"
    if any(t in n for t in ("mmwave", "presence", "bed_", "human_sensor", "existence")):
        return "STILL"
    return "MOTION"  # rgbw_*_occupancy (3RD-Reality PIR night lights), smart_night_light_w_occupancy


r = sqlite3.connect("file:/config/home-assistant_v2.db?mode=ro", uri=True)
u = sqlite3.connect("file:/config/universal_room_automation/data/universal_room_automation.db?mode=ro", uri=True)
REC_MIN = r.execute("SELECT min(last_updated_ts) FROM states").fetchone()[0] or 0
LOAD_T0 = min(T_SHIP - DAYS * 86400, NOW) - 86400


def loc(ts):
    return time.strftime("%m-%d %H:%M", time.gmtime(ts + TZ_OFFSET_S))


def trans(eid):
    m = r.execute("SELECT metadata_id FROM states_meta WHERE entity_id=?", (eid,)).fetchone()
    if not m:
        return None
    seed = r.execute("SELECT last_updated_ts,state FROM states WHERE metadata_id=? AND last_updated_ts<? "
                     "ORDER BY last_updated_ts DESC LIMIT 1", (m[0], LOAD_T0)).fetchall()
    rows = seed + r.execute("SELECT last_updated_ts,state FROM states WHERE metadata_id=? AND last_updated_ts>=? "
                            "ORDER BY last_updated_ts", (m[0], LOAD_T0)).fetchall()
    out = []
    for ts, st in rows:
        if not out or out[-1][1] != st:
            out.append((ts, st))
    return out


def on_intervals(tr):
    iv, start = [], None
    for ts, st in tr:
        if st == "on" and start is None:
            start = ts
        elif st != "on" and start is not None:
            iv.append((start, ts)); start = None
    if start is not None:
        iv.append((start, NOW))
    return iv


def merge(ivs, gap):
    out = []
    for s, e in sorted(ivs):
        if out and s - out[-1][1] <= gap:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


# ---- raw presence
SENS = {}       # eid -> intervals
MISSING = []
ROOMIV = {}     # room -> merged intervals
for room, rtype, zone, sens in ROOMS:
    allv = []
    for e in sens:
        tr = trans(e)
        if tr is None:
            MISSING.append(e); SENS[e] = []; continue
        SENS[e] = on_intervals(tr); allv += SENS[e]
    ROOMIV[room] = merge(allv, MERGE_GAP_S)
RMETA = {room: (rtype, zone, sens) for room, rtype, zone, sens in ROOMS}


def on_at(ivs, t):
    for s, e in ivs:
        if s <= t < e:
            return (s, e)
    return None


_UT = {}


def ura_at(room, t):
    """(room occupied, room hvac_occupied) states at t, from the recorder."""
    if room not in URA_ENT:
        return (None, None)
    out = []
    for e in URA_ENT[room]:
        if e not in _UT:
            _UT[e] = trans(e) or []
        cur = None
        for ts, st in _UT[e]:
            if ts > t:
                break
            cur = st
        out.append(cur)
    return tuple(out)


_OV = {}


def override_on(room, t):
    e = OVERRIDE_VACANT.get(room)
    if not e:
        return False
    if e not in _OV:
        _OV[e] = on_intervals(trans(e) or [])
    return on_at(_OV[e], t) is not None


def first_onset(ivs, a, b):
    xs = [s for s, e in ivs if a < s <= b]
    return min(xs) if xs else None


def last_end_before(ivs, t):
    xs = [e for s, e in ivs if e <= t]
    return max(xs) if xs else None


# ---- away writes -> episodes
def iso(ts):
    return datetime.fromisoformat(ts).timestamp()


pw = []  # (ts, zone, preset, details)
for ts, zone, dj in u.execute("SELECT timestamp,zone,details_json FROM ura_activity_log WHERE action='preset_change' "
                              "AND timestamp>=?", (time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(LOAD_T0)),)):
    d = json.loads(dj or "{}")
    pw.append((iso(ts), zone, d.get("new_preset"), d))
for ts, zone, dj in u.execute("SELECT timestamp,zone,details_json FROM ura_activity_log WHERE action='climate_write' "
                              "AND timestamp>=?", (time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(LOAD_T0)),)):
    d = json.loads(dj or "{}")
    if d.get("verb") != "set_preset_mode" or not d.get("wire_ok"):
        continue
    p = (d.get("values_after") or {}).get("preset_mode")
    if p and p not in ("away", "resume"):
        pw.append((iso(ts), zone, p, {"_cw": True, "site": d.get("site")}))
pw.sort(key=lambda x: x[0])
EPIS = []
state = {}
for ts, zone, p, d in pw:
    if zone not in CLIMATE:
        continue
    if p == "away" and not d.get("_cw"):
        if state.get(zone) is None:
            state[zone] = dict(zone=zone, W=ts, reason=d.get("reason"), hs=d.get("house_state"), n=1, end=None)
            EPIS.append(state[zone])
        else:
            state[zone]["n"] += 1
    elif p and p != "away" and state.get(zone) is not None:
        state[zone]["end"] = ts; state[zone] = None


def classify(ep):
    W, zone = ep["W"], ep["zone"]
    rooms = [x for x in RMETA if RMETA[x][1] == zone]
    live = [x for x in rooms if RMETA[x][0] != "hallway"]
    halls = [x for x in rooms if RMETA[x][0] == "hallway"]
    ep["hall_only"] = any(on_at(ROOMIV[h], W) for h in halls)
    # zone last-occupied (non-hallway) room before W
    ends = [(last_end_before(ROOMIV[x], W), x) for x in live]
    ends = [e for e in ends if e[0]]
    last_end, last_room = max(ends) if ends else (None, None)
    present = [(x, on_at(ROOMIV[x], W)) for x in live if on_at(ROOMIV[x], W)]
    ep["last_room"] = last_room
    ep["empty_before_min"] = round((W - last_end) / 60, 1) if last_end else None
    if present:
        # the room present at W with the latest onset is the most plausible "missed" room
        room, (s, e) = max(present, key=lambda p: p[1][0])
        on_sens = [x for x in RMETA[room][2] if on_at(SENS[x], W)]
        still_on = [x for x in on_sens if kind(x) == "STILL"]
        ep["ura_at_W"] = ura_at(room, W)
        ep.update(kind_="DURING", room=room, onset_before_s=round(W - s), present_len_min=round((e - s) / 60, 1),
                  on_sens=on_sens, is_last=(room == last_room))
        ep["stuck"] = any((W - on_at(SENS[x], W)[0]) >= P22_STUCK_H * 3600 for x in still_on)
        if override_on(room, W):
            ep["cls"] = "OVERRIDE-VACANT"
        elif ep["reason"] not in VACANCY_REASONS:
            ep["cls"] = "POLICY-AWAY-PRESENT"
        elif W - s <= ENTRY_RACE_S:
            ep["cls"] = "ENTRY-RACE"
        elif still_on and ep["stuck"]:
            ep["cls"] = "STUCK-EXCLUDED"
        elif still_on:
            ep["cls"] = "STILL-BODY-MISSED"
        else:
            ep["cls"] = "MOTION-ON-MISSED"
        ep["ret_ts"] = W
        return
    onsets = [(first_onset(ROOMIV[x], W, W + RETURN_MIN * 60), x) for x in live]
    onsets = [o for o in onsets if o[0]]
    if not onsets:
        ep.update(kind_="CLEAN", cls="CLEAN", room=last_room)
        return
    rts, rroom = min(onsets)
    riv = on_at(ROOMIV[rroom], rts)
    ep["ret_stay_min"] = round((riv[1] - riv[0]) / 60, 1) if riv else 0
    ep["ura_after_ret"] = ura_at(rroom, rts + 120)
    ep.update(ret_room=rroom, ret_after_min=round((rts - W) / 60, 1), ret_ts=rts,
              total_gap_min=round((rts - last_end) / 60, 1) if last_end else None)
    if last_end is None or (W - last_end) >= ARRIVAL_MIN * 60:
        ep.update(kind_="ARRIVAL", cls="ARRIVAL", room=rroom)
        return
    if ep["ret_stay_min"] < RETURN_STAY_MIN:
        ep.update(kind_="TRANSIT", cls="TRANSIT-RETURN", room=last_room)
        return
    if override_on(last_room, W) or override_on(rroom, W):
        ep.update(kind_="RETURNED", cls="OVERRIDE-VACANT", room=last_room if override_on(last_room, W) else rroom)
        return
    if ep["reason"] not in VACANCY_REASONS:
        ep.update(kind_="RETURNED", cls="POLICY-AWAY-RETURN", room=last_room)
        return
    has_still = any(kind(x) == "STILL" for x in RMETA[last_room][2])
    ep.update(kind_="RETURNED", room=last_room, is_last=True, same_room=(rroom == last_room),
              cls="HOLD-TOO-SHORT" if has_still else "MOTION-ONLY-COVERAGE")


for ep in EPIS:
    classify(ep)
    # time the zone sat away while a person was raw-present (return/presence -> next non-away write)
    if ep.get("ret_ts") and ep["end"]:
        ep["away_while_present_min"] = round(max(0, ep["end"] - ep["ret_ts"]) / 60, 1)
    else:
        ep["away_while_present_min"] = None


def pct(xs, q):
    xs = sorted(x for x in xs if x is not None)
    return None if not xs else xs[min(len(xs) - 1, int(q * len(xs)))]


def report(label, t0, t1):
    days = (t1 - t0) / 86400
    cov = "" if t0 >= REC_MIN else f"  (recorder starts {loc(REC_MIN)} -> effective {max(0,(t1-REC_MIN)/86400):.1f}d)"
    ins = "  ** INSUFFICIENT (< 3 days) **" if days < 3 else ""
    eps = [e for e in EPIS if t0 <= e["W"] < t1]
    print(f"\n==== {label}: {loc(t0)} -> {loc(t1)} CDT ({days:.2f} d){cov}{ins}")
    print("-- zone summary: away_episodes | by class | by (reason,house_state) of HARM")
    HARM = ("ENTRY-RACE", "STILL-BODY-MISSED", "STUCK-EXCLUDED", "MOTION-ON-MISSED", "HOLD-TOO-SHORT",
            "MOTION-ONLY-COVERAGE", "OVERRIDE-VACANT")
    for z in sorted(CLIMATE):
        ze = [e for e in eps if e["zone"] == z]
        c = {}
        for e in ze:
            c[e["cls"]] = c.get(e["cls"], 0) + 1
        rh = {}
        for e in ze:
            if e["cls"] in HARM:
                k = f"{e['reason']}/{e['hs']}"; rh[k] = rh.get(k, 0) + 1
        print(f"{z}|{len(ze)}|{c}|{rh}")
    print("-- per room (harm attributed to the missed room for DURING, the zone's last-occupied room for RETURNED)")
    print("room|type|zone|kinds|" + "|".join(HARM) + "|"
          "harm_in_last_occ_room|ret_after_min(med/max)|total_gap_min(med/p90/max)|away_while_present_min(med/max)|"
          "episodes_as_last_room(all/clean/transit)|release_delay_min_med(W-last_raw)")
    for room, rtype, zone, sens in ROOMS:
        re_ = [e for e in eps if e.get("room") == room and e["cls"] in HARM]
        asl = [e for e in eps if e.get("last_room") == room]
        if not re_ and not asl:
            continue
        k = "+".join(sorted({kind(x) for x in sens}))
        cnt = [sum(1 for e in re_ if e["cls"] == h) for h in HARM]
        last = sum(1 for e in re_ if e.get("is_last"))
        ra = [e.get("ret_after_min") for e in re_ if e.get("ret_after_min") is not None]
        tg = [e.get("total_gap_min") for e in re_ if e.get("total_gap_min") is not None]
        aw = [e.get("away_while_present_min") for e in re_]
        f = lambda xs: "-" if not xs else f"{statistics.median(xs):.1f}/{max(xs):.1f}"
        g = lambda xs: "-" if not xs else f"{statistics.median(xs):.1f}/{pct(xs,.9):.1f}/{max(xs):.1f}"
        aw2 = [x for x in aw if x is not None]
        rd = [e["empty_before_min"] for e in asl if e.get("empty_before_min") is not None and e["cls"] in ("CLEAN", "TRANSIT-RETURN", "HOLD-TOO-SHORT", "MOTION-ONLY-COVERAGE")]
        den = f"{len(asl)}/{sum(e['cls']=='CLEAN' for e in asl)}/{sum(e['cls']=='TRANSIT-RETURN' for e in asl)}"
        print(f"{room}|{rtype}|{zone}|{k}|" + "|".join(map(str, cnt)) + f"|{last}/{len(re_)}|{f(ra)}|{g(tg)}|{f(aw2)}|{den}|"
              f"{statistics.median(rd) if rd else '-'}")
    nh = [e for e in eps if e["cls"] in HARM]
    print(f"-- totals: episodes={len(eps)} harm={len(nh)} ("
          + ", ".join(f"{h}={sum(e['cls']==h for e in nh)}" for h in HARM) + "); "
          f"ARRIVAL={sum(e['cls']=='ARRIVAL' for e in eps)} TRANSIT-RETURN={sum(e['cls']=='TRANSIT-RETURN' for e in eps)} "
          f"POLICY-AWAY-PRESENT={sum(e['cls']=='POLICY-AWAY-PRESENT' for e in eps)} POLICY-AWAY-RETURN={sum(e['cls']=='POLICY-AWAY-RETURN' for e in eps)} CLEAN={sum(e['cls']=='CLEAN' for e in eps)} "
          f"hallway-present-at-W(not harm)={sum(1 for e in eps if e.get('hall_only'))}; "
          f"harm/day={len(nh)/days:.2f}")
    print("-- harm episodes")
    print("W|zone|reason|house|cls|room|last_room|empty_before_min|onset_before_s|ret_after_min|total_gap_min|"
          "away_while_present_min|n_writes|on_sensors|stuck|ret_stay_min|ura(occ,hvac)@W_or_ret+2m")
    shown = [e for e in eps if e["cls"] in HARM or e["cls"].startswith("POLICY")]
    for e in shown if VERBOSE or len(shown) <= 80 else shown[:80]:
        print(f"{loc(e['W'])}|{e['zone']}|{e['reason']}|{e['hs']}|{e['cls']}|{e.get('room')}|{e.get('last_room')}|"
              f"{e.get('empty_before_min')}|{e.get('onset_before_s','-')}|{e.get('ret_after_min','-')}|"
              f"{e.get('total_gap_min','-')}|{e.get('away_while_present_min')}|{e['n']}|"
              f"{','.join(x.split('.',1)[1][:40] for x in e.get('on_sens', []))}|{e.get('stuck','-')}|"
              f"{e.get('ret_stay_min','-')}|{e.get('ura_at_W') or e.get('ura_after_ret') or '-'}")


print(f"# HVAC raw-presence harm probe  now={loc(NOW)} CDT  ship={loc(T_SHIP)} CDT  merge_gap={MERGE_GAP_S}s  "
      f"return<={RETURN_MIN}m  entry_race<={ENTRY_RACE_S}s  arrival>={ARRIVAL_MIN}m")
if MISSING:
    print("# MISSING in recorder:", ", ".join(MISSING))
print("# sensor kinds:", "; ".join(f"{x.split('.',1)[1][:48]}={kind(x)}" for _, _, _, s in ROOMS for x in s))
report("PRE-SHIP BASELINE", T_SHIP - DAYS * 86400, T_SHIP)
report("POST-SHIP", T_SHIP, NOW)

# override sweep: any room Override Vacant / Occupied switch ON since the pre-ship window start
print("\n-- room override switches ON since pre-ship window start")
for (eid,) in r.execute("SELECT entity_id FROM states_meta WHERE entity_id LIKE 'switch.%override_vacant' "
                        "OR entity_id LIKE 'switch.%override_occupied'"):
    iv = [x for x in on_intervals(trans(eid) or []) if x[1] >= T_SHIP - DAYS * 86400]
    if iv:
        print(eid, [(loc(a_), "still-on" if b_ >= NOW - 1 else loc(b_)) for a_, b_ in iv])

# live knob values (recorder latest non-unavailable)
print("\n-- live HVAC knobs (recorder latest)")
for (eid,) in r.execute("SELECT entity_id FROM states_meta WHERE entity_id LIKE 'number.ura_hvac_coordinator_%' AND "
                        "(entity_id LIKE '%vacancy%' OR entity_id LIKE '%entry_dwell%' OR entity_id LIKE '%return_window%')"):
    row = r.execute("SELECT s.state, s.last_updated_ts FROM states s JOIN states_meta m ON s.metadata_id=m.metadata_id "
                    "WHERE m.entity_id=? AND s.state NOT IN ('unavailable','unknown') ORDER BY s.last_updated_ts DESC "
                    "LIMIT 1", (eid,)).fetchone()
    print(f"{eid}={row[0] if row else None} (as of {loc(row[1]) if row else '-'})")
