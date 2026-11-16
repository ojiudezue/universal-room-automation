#!/usr/bin/env python3
"""Arc step 8 (identity actions, v6.0.0) D0 -- READ-ONLY probe.

Plan: docs/planning/PLANNING_identity_actions_v6.md section 4 (rev 3.2), plus review 3.1 H1
(counted-return share).

    ssh ha "python3 -" < scripts/probes/identity_actions_d0.py

Both DBs are opened `mode=ro`; `.storage` is read only. Nothing is written. Output: one JSON
document on stdout (paste into the planning/audit doc). Window: WINDOW_DAYS (14) or the recorder's
own retention, whichever is shorter (HA keeps ~7 days here; the URA DB keeps longer).

Everything is resolved through the registry / URA's own config, never by entity-name guessing:
  * residents      = integration entry `tracked_persons` -> person.* id (person_ids rule)
  * person room    = URA's own PersonLocationSensor, unique_id `universal_room_automation_person_
                     <tracked_persons entry .split('.')[-1]>_location` (aggregation.py PersonLocationSensor)
  * room occupancy = URA's own OccupiedBinarySensor, unique_id `<room entry_id>_occupied`
  * room dark      = URA's own DarkBinarySensor, unique_id `<room entry_id>_dark`
  * house state    = URA's own PresenceHouseStateSensor, unique_id `universal_room_automation_presence_house_state`
  * room player    = room entry option `room_media_player`; its MA twin = any `music_assistant`
                     media_player on the SAME device (registry device_id)

Sections:
(a)  F5 per day by source. Proxy = URA DB `ura_activity_log` action='pre_arrival' (HVAC accepted the
     F5: a LOWER bound, gated by the HVAC zone map and its pre-arrival switch), plus the raw
     geofence edges (`person.*` not_home|zone -> home in the recorder: the geofence producer's
     upper bound). Per F5: lag to the person's first location change into a room with a player
     (within ARRIVAL_WINDOW_S), that move's classified confidence (`room_transitions.confidence`,
     expected ~0.50), and at that entry: native player or MA twin `playing`, room already occupied,
     quiet (house state sleep / home_night, the NM default rule). Share of first player-rooms that
     are a plausible own room (the person's top person_visits rooms by dwell).
(a1) Review 3.1 H1: share of F5 by source that are COUNTED returns (raw person.* read not_home or a
     named zone for >= COUNTED_RETURN_MIN_AWAY_S before the edge; the edge outside the 600 s boot
     window after an HA start).
(a2) Per own room: room occupancy onset minus the person's BLE room entry (both signs, seconds),
     for every BLE entry into that room; and the person-location sensor's update cadence. Sizes
     ARRIVAL_OCCUPIED_LEAD_S (p95 of "own motion before BLE" + margin) and ARRIVAL_SCENE_CONFIRM_S.
(b)  Departures per day per resident (raw person.* home -> not_home|zone) and how often the arrival
     room (the person's last room before the edge) read vacant within DEPARTURE_EMPTY_WITHIN_S.
(c)  Day / evening split of the (a) entries under resolve_slot (dark sensor at entry = evening).
(d)  After step 7 ships: share of egress entries named at the crossing (`ura_person_egress_event`
     with a person_id, recorder events table) -- reported if the event type exists.

Go/no-go: none (operator ruling). Numbers that make a gate look wrong go to the operator.
"""
import collections
import datetime as dt
import json
import sqlite3

DOMAIN = "universal_room_automation"
WINDOW_DAYS = 14
ARRIVAL_WINDOW_S = 900
COUNTED_RETURN_MIN_AWAY_S = 900
BOOT_WINDOW_S = 600
DEPARTURE_EMPTY_WITHIN_S = 300
A2_PAIR_MAX_S = 900          # occupancy onset and BLE entry farther apart = unrelated
OWN_ROOM_TOP_N = 3
# person_visits / ura_activity_log rows are naive PROCESS-local (presence state of play #32);
# on this HAOS host the HA core process runs in UTC.
NAIVE_TZ = dt.timezone.utc
NON_ROOMS = {"", "unknown", "unavailable", "away", "home", "not_home", "none"}

r = sqlite3.connect("file:/config/home-assistant_v2.db?mode=ro", uri=True)
u = sqlite3.connect(
    "file:/config/universal_room_automation/data/universal_room_automation.db?mode=ro", uri=True,
)
_store = lambda n: json.load(open(f"/config/.storage/{n}"))["data"]  # noqa: E731
ENTRIES = [e for e in _store("core.config_entries")["entries"] if e.get("domain") == DOMAIN]
REG = _store("core.entity_registry")["entities"]
BY_UID = {(e.get("platform"), str(e.get("unique_id"))): e for e in REG}


def merged(e):
    return {**(e.get("data") or {}), **(e.get("options") or {})}


def person_entity_id(name):
    s = str(name)
    return s if s.startswith("person.") else "person." + s.lower().replace(" ", "_")


def slug(name):
    return person_entity_id(name)[len("person."):]


def uid_entity(uid):
    e = BY_UID.get((DOMAIN, uid))
    return e["entity_id"] if e else None


NOW = r.execute("select max(last_updated_ts) from states").fetchone()[0]
T0 = NOW - WINDOW_DAYS * 86400


def history(entity_id, t0=T0):
    if not entity_id:
        return []
    row = r.execute("select metadata_id from states_meta where entity_id=?", (entity_id,)).fetchone()
    if not row:
        return []
    return list(r.execute(
        "select last_updated_ts, state from states where metadata_id=? and last_updated_ts>=? "
        "order by last_updated_ts", (row[0], t0)))


def changes(hist):
    out, prev = [], object()
    for ts, st in hist:
        if st != prev:
            out.append((ts, st))
        prev = st
    return out


def state_at(hist, ts):
    s = None
    for t, st in hist:
        if t > ts:
            break
        s = st
    return s


def pct(vals, p):
    if not vals:
        return None
    v = sorted(vals)
    return round(v[min(len(v) - 1, int(round(p / 100 * (len(v) - 1))))], 1)


def dist(vals):
    return {"n": len(vals), "p05": pct(vals, 5), "p50": pct(vals, 50), "p95": pct(vals, 95),
            "min": round(min(vals), 1) if vals else None, "max": round(max(vals), 1) if vals else None}


def naive_ts(s):
    try:
        return dt.datetime.fromisoformat(str(s)).replace(tzinfo=NAIVE_TZ).timestamp()
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------------ config
integ = next((e for e in ENTRIES if (e.get("data") or {}).get("entry_type") == "integration"), {})
cm = next((e for e in ENTRIES if (e.get("data") or {}).get("entry_type") == "coordinator_manager"), {})
TRACKED = list((integ.get("data") or {}).get("tracked_persons") or [])
ROOMS = {}
for e in ENTRIES:
    m = merged(e)
    if m.get("entry_type") != "room":
        continue
    ROOMS[e["entry_id"]] = {
        "name": m.get("room_name") or e.get("title"),
        "type": m.get("room_type"),
        "player": m.get("room_media_player"),
        "occupied": uid_entity(f"{e['entry_id']}_occupied"),
        "adjacent": list(m.get("adjacent_rooms") or []),
        "timeout": m.get("occupancy_timeout"),
        "dark": uid_entity(f"{e['entry_id']}_dark"),
    }
ROOM_BY_NAME = {v["name"]: k for k, v in ROOMS.items()}
REG_BY_EID = {e["entity_id"]: e for e in REG}


def ma_twin(player):
    dev = (REG_BY_EID.get(player) or {}).get("device_id")
    if not dev:
        return None
    for e in REG:
        if (e.get("device_id") == dev and e.get("platform") == "music_assistant"
                and e["entity_id"].startswith("media_player.") and e["entity_id"] != player):
            return e["entity_id"]
    return None


HOUSE = history(uid_entity(f"{DOMAIN}_presence_house_state"))
QUIET_STATES = {"sleep", "home_night"}   # NM quiet-hours house-state rule (default)

# HA starts in the window (recorder `events` homeassistant_start), for the boot window.
STARTS = []
try:
    STARTS = [ts for (ts,) in r.execute(
        "select e.time_fired_ts from events e join event_types t on e.event_type_id=t.event_type_id "
        "where t.event_type='homeassistant_start' and e.time_fired_ts>=?", (T0,))]
except sqlite3.Error:
    STARTS = []


def in_boot_window(ts):
    return any(0 <= ts - s < BOOT_WINDOW_S for s in STARTS)


# ------------------------------------------------------------------ per person data
def person_rows():
    out = {}
    for name in TRACKED:
        loc_uid = f"{DOMAIN}_person_{str(name).split('.')[-1]}_location"
        out[name] = {
            "entity": person_entity_id(name),
            "loc": changes(history(uid_entity(loc_uid))),
            "loc_raw": history(uid_entity(loc_uid)),
            "person": changes(history(person_entity_id(name))),
        }
    return out


PERSONS = person_rows()


def own_rooms_guess(name):
    """Top person_visits rooms by dwell (the D1 suggestion rule) -> room entry ids."""
    since = dt.datetime.fromtimestamp(T0, NAIVE_TZ).replace(tzinfo=None).isoformat(" ")
    tot = collections.Counter()
    for pid, room, a, b in u.execute(
            "select person_id, room_id, entry_time, exit_time from person_visits "
            "where entry_time>=? and exit_time is not null", (since,)):
        if slug(pid) != slug(name):
            continue
        ta, tb = naive_ts(a), naive_ts(b)
        if ta and tb and tb > ta:
            tot[room] += tb - ta
    return [ROOM_BY_NAME[n] for n, _ in tot.most_common(OWN_ROOM_TOP_N) if n in ROOM_BY_NAME]


# ------------------------------------------------------------------ (a) F5
def f5_rows():
    rows = []
    since = dt.datetime.fromtimestamp(T0, NAIVE_TZ).replace(tzinfo=None).isoformat()
    for ts, det in u.execute(
            "select timestamp, details_json from ura_activity_log where coordinator='hvac' "
            "and action='pre_arrival' and timestamp>=?", (since,)):
        try:
            d = json.loads(det or "{}")
        except ValueError:
            d = {}
        t = naive_ts(ts)
        if t is None:
            continue
        rows.append({"ts": t, "person": d.get("person"), "source": d.get("source") or "unknown"})
    return rows


def geofence_edges(p):
    out = []
    prev = None
    for ts, st in p["person"]:
        if st == "home" and prev is not None and prev != "home" and prev not in ("unknown", "unavailable"):
            out.append(ts)
        prev = st
    return out


def counted_return(p, ts):
    """Raw person.* read not_home / a zone for >= MIN_AWAY before ts, edge outside boot window."""
    if in_boot_window(ts):
        return False
    hist = p["person"]
    last_home = None
    for t, st in hist:
        if t >= ts:
            break
        if st == "home":
            last_home = t
    away_start = None
    for t, st in hist:
        if t >= ts:
            break
        if last_home is not None and t <= last_home:
            continue
        if st not in ("home", "unknown", "unavailable"):
            away_start = t
            break
    return away_start is not None and ts - away_start >= COUNTED_RETURN_MIN_AWAY_S


def first_player_room(p, ts):
    for t, st in p["loc"]:
        if t < ts or t > ts + ARRIVAL_WINDOW_S:
            continue
        rid = ROOM_BY_NAME.get(st)
        if rid and ROOMS[rid]["player"]:
            return t, rid
    return None


def transition_conf(name, rid, t):
    rn = ROOMS[rid]["name"]
    best = None
    for ts, conf in u.execute(
            "select timestamp, confidence from room_transitions where to_room=? "
            "order by timestamp desc limit 2000", (rn,)):
        tt = naive_ts(ts)
        if tt is not None and abs(tt - t) <= 120:
            best = conf
            break
    return best


SECTION_A = {"per_day_by_source": {}, "geofence_edges_per_day": {}, "entries": [], "counted_return_share": {}}
f5 = f5_rows()
days = WINDOW_DAYS
by_src = collections.Counter(r_["source"] for r_ in f5)
SECTION_A["per_day_by_source"] = {k: round(v / days, 2) for k, v in by_src.items()}
counted = collections.defaultdict(lambda: [0, 0])
lags, confs = [], []
playing = occupied = quiet = own = 0
for row in f5:
    name = next((n for n in TRACKED if person_entity_id(n) == row["person"] or slug(n) == slug(row["person"] or "")), None)
    if name is None:
        continue
    p = PERSONS[name]
    c = counted[row["source"]]
    c[1] += 1
    c[0] += int(counted_return(p, row["ts"]))
    hit = first_player_room(p, row["ts"])
    if not hit:
        continue
    t, rid = hit
    room = ROOMS[rid]
    lags.append(t - row["ts"])
    cf = transition_conf(name, rid, t)
    if cf is not None:
        confs.append(float(cf))
    native = state_at(history(room["player"], t - 3600), t)
    twin = ma_twin(room["player"])
    ma = state_at(history(twin, t - 3600), t) if twin else None
    is_play = "playing" in (native, ma)
    occ_hist = history(room["occupied"], t - 3600)
    occ_on = [ts_ for ts_, s in changes(occ_hist) if s == "on" and ts_ <= t]
    was_occ = state_at(occ_hist, t - 1) == "on" and bool(occ_on) and (t - occ_on[-1]) > 120
    is_quiet = state_at(HOUSE, t) in QUIET_STATES
    is_own = rid in own_rooms_guess(name)
    playing += is_play
    occupied += was_occ
    quiet += is_quiet
    own += is_own
    SECTION_A["entries"].append({"person": slug(name), "source": row["source"], "lag_s": round(t - row["ts"]),
                                 "room": room["name"], "playing": is_play, "occupied_before": was_occ,
                                 "quiet": is_quiet, "own_room": is_own, "transition_conf": cf,
                                 "entry_ts": t})
for name in TRACKED:
    SECTION_A["geofence_edges_per_day"][slug(name)] = round(len(geofence_edges(PERSONS[name])) / days, 2)
n = len(SECTION_A["entries"])
SECTION_A["lag_f5_to_first_player_room_s"] = dist(lags)
SECTION_A["first_transition_confidence"] = dist(confs)
SECTION_A["share"] = {k: (round(v / n, 3) if n else None) for k, v in
                      {"playing": playing, "occupied_before": occupied, "quiet": quiet, "own_room": own}.items()}
SECTION_A["counted_return_share"] = {k: {"counted": v[0], "of": v[1], "share": round(v[0] / v[1], 3) if v[1] else None}
                                     for k, v in counted.items()}

# ------------------------------------------------------------------ (a2) onset - BLE entry
SECTION_A2 = {"per_room": {}, "location_update_cadence_s": {}}
for name in TRACKED:
    p = PERSONS[name]
    raw = [ts for ts, _ in p["loc_raw"]]
    gaps = [b - a for a, b in zip(raw, raw[1:]) if b > a]
    SECTION_A2["location_update_cadence_s"][slug(name)] = dist(gaps)
    for rid in own_rooms_guess(name):
        room = ROOMS[rid]
        onsets = [ts for ts, s in changes(history(room["occupied"])) if s == "on"]
        deltas = []
        for t, st in p["loc"]:
            if st != room["name"]:
                continue
            near = [o for o in onsets if abs(o - t) <= A2_PAIR_MAX_S]
            if near:
                o = min(near, key=lambda x: abs(x - t))
                deltas.append(o - t)   # negative = occupancy began BEFORE the BLE entry
        before = [-d for d in deltas if d <= 0]
        SECTION_A2["per_room"].setdefault(room["name"], {})[slug(name)] = {
            "onset_minus_ble_entry_s": dist(deltas),
            "own_motion_before_ble_s": dist(before),
            "suggested_lead_s": (round(pct(before, 95) + 30) if before else None),
        }

# ------------------------------------------------------------------ (b) departures
SECTION_B = {}
for name in TRACKED:
    p = PERSONS[name]
    deps, emptied = 0, 0
    prev = None
    for ts, st in p["person"]:
        if prev == "home" and st not in ("home", "unknown", "unavailable"):
            deps += 1
            last_room = state_at([(t, s) for t, s in p["loc"] if s not in NON_ROOMS], ts)
            rid = ROOM_BY_NAME.get(last_room)
            if rid:
                occ = history(ROOMS[rid]["occupied"], ts - 3600)
                if any(s == "off" for t, s in changes(occ) if ts <= t <= ts + DEPARTURE_EMPTY_WITHIN_S) \
                        or state_at(occ, ts) == "off":
                    emptied += 1
        prev = st
    SECTION_B[slug(name)] = {"departures_per_day": round(deps / days, 2),
                             "arrival_room_empty_within_5min": emptied, "of": deps}

# ------------------------------------------------------------------ (c) day / evening split
SECTION_C = collections.Counter({"day": 0, "evening": 0})
for e in SECTION_A["entries"]:
    rid = ROOM_BY_NAME.get(e["room"])
    # The dark sensor at the entry time; unknown = day (resolve_slot: is_dark not True -> day).
    st = state_at(history(ROOMS[rid]["dark"]), e["entry_ts"]) if rid else None
    SECTION_C["evening" if st == "on" else "day"] += 1

# ------------------------------------------------------------------ (d) named at the crossing
SECTION_D = {"available": False}
try:
    rows = list(r.execute(
        "select d.shared_data from events e join event_types t on e.event_type_id=t.event_type_id "
        "left join event_data d on e.data_id=d.data_id where t.event_type='ura_person_egress_event' "
        "and e.time_fired_ts>=?", (T0,)))
    entries = named = 0
    for (blob,) in rows:
        try:
            d = json.loads(blob or "{}")
        except ValueError:
            continue
        if d.get("direction") != "entry":
            continue
        entries += 1
        named += int(bool(d.get("person_id")))
    SECTION_D = {"available": True, "entries": entries, "named": named,
                 "share": round(named / entries, 3) if entries else None}
except sqlite3.Error as err:
    SECTION_D = {"available": False, "error": str(err)}

# ------------------------------------------------------------------ rev 3.4 additions
# (a-gate) the §5.4 gate 5 rule per F5 source, on residency rows (memory_episodes
# person_arrival / person_departure, attrs.edge_ts epoch). Residency rows exist only
# since the residency producer shipped, so the sample is what the DB holds.
LOOKBACK_S = 120
MIN_AWAY_S = 15 * 60
EDGES = collections.defaultdict(list)   # person slug -> [(edge_ts, kind, attrs)]
for et, a in u.execute("select episode_type, attrs_json from memory_episodes "
                       "where episode_type in ('person_arrival','person_departure')"):
    try:
        d = json.loads(a or "{}")
        ts = float(d.get("edge_ts"))
    except (TypeError, ValueError):
        continue
    EDGES[slug(d.get("person") or "")].append((ts, "arrival" if et == "person_arrival" else "departure", d))
for k in EDGES:
    EDGES[k].sort(key=lambda x: x[0])
EDGES_FROM = min((e[0] for v in EDGES.values() for e in v), default=None)
GATE = collections.defaultdict(collections.Counter)
DEP_AGE = collections.defaultdict(list)
GEO_LAG = []
for row in f5:
    if EDGES_FROM is None or row["ts"] < EDGES_FROM:
        continue
    ps = slug(row["person"] or "")
    ev = EDGES.get(ps, [])
    src = row["source"]
    if src == "geofence":
        hits = [e for e in ev if e[1] == "arrival" and row["ts"] - LOOKBACK_S <= e[0] <= row["ts"] + 5
                and e[2].get("counted") is True and e[2].get("source_stale") is False
                and e[2].get("in_boot_window") is False]
        GATE[src]["pass" if hits else "skipped_not_counted_return"] += 1
        if hits:
            GEO_LAG.append(row["ts"] - hits[-1][0])
    else:
        prior = [e for e in ev if e[0] <= row["ts"]]
        dep = [e for e in prior if e[1] == "departure"]
        if not dep:
            GATE[src]["no_departure_seen"] += 1
            continue
        last_dep = dep[-1][0]
        later_arr = any(e[1] == "arrival" and e[0] > last_dep for e in prior)
        DEP_AGE[src].append(row["ts"] - last_dep)
        if later_arr or row["ts"] - last_dep < MIN_AWAY_S:
            GATE[src]["recent_departure"] += 1
        else:
            GATE[src]["pass"] += 1
SECTION_AGATE = {
    "residency_rows_from": EDGES_FROM,
    "by_source": {k: dict(v) for k, v in GATE.items()},
    "geofence_f5_minus_counted_arrival_s": dist(GEO_LAG),
    "f5_minus_last_departure_s": {k: dist(v) for k, v in DEP_AGE.items()},
}

# (a2-near) per bedroom: at each occupancy onset that its owner (person_visits top
# rooms) walks into within NEAR_ENTRY_S, where BLE placed the owner, and the share
# the §5.5 near check passes under (i) adjacency either direction, (ii) (i) plus the
# approach room (the owner's room just before entering), (iii) same house zone.
NEAR_ENTRY_S = 900
zm = next((e for e in ENTRIES if (e.get("data") or {}).get("entry_type") == "zone_manager"), {})
_zones = (zm.get("options") or {}).get("zones") or (zm.get("data") or {}).get("zones") or {}
_data_name = {e["entry_id"]: (e.get("data") or {}).get("room_name") for e in ENTRIES}
ZONE_OF_NAME = {}
for zname, zcfg in _zones.items():
    for ref in (zcfg or {}).get("zone_rooms") or []:
        nm = _data_name.get(ref) or ref
        ZONE_OF_NAME.setdefault(nm, zname)

def adjacent(rid_a, rid_b):
    return rid_b in ROOMS[rid_a]["adjacent"] or rid_a in ROOMS.get(rid_b, {}).get("adjacent", [])

SECTION_NEAR = {}
for rid, room in ROOMS.items():
    if room["type"] != "bedroom":
        continue
    owners = [n for n in TRACKED if rid in own_rooms_guess(n)]
    if not owners:
        continue
    onsets = [ts for ts, s_ in changes(history(room["occupied"])) if s_ == "on"]
    rec = {"owners": [slug(n) for n in owners], "zone": ZONE_OF_NAME.get(_data_name.get(rid)),
           "onsets_with_owner_entry": 0, "placed": collections.Counter(),
           "pass_i_adjacency": 0, "pass_ii_adjacency_plus_approach": 0, "pass_iii_same_zone": 0,
           "in_arrival_window": 0, "holder_rooms": collections.Counter(), "ble_after_body_s": []}
    for o in onsets:
        for n in owners:
            p = PERSONS[n]
            entry = next(((t, i) for i, (t, st) in enumerate(p["loc"])
                          if st == room["name"] and o - 120 <= t <= o + NEAR_ENTRY_S), None)
            if not entry:
                continue
            t_in, idx = entry
            placed = state_at(p["loc"], o)
            approach = p["loc"][idx - 1][1] if idx > 0 else None
            prid = ROOM_BY_NAME.get(placed)
            rec["onsets_with_owner_entry"] += 1
            rec["ble_after_body_s"].append(t_in - o)
            rec["holder_rooms"][placed or "none"] += 1
            if placed == room["name"]:
                rec["placed"]["this_room"] += 1
            elif prid:
                rec["placed"]["other_room"] += 1
            else:
                rec["placed"]["away_or_unknown"] += 1
            p_i = placed == room["name"] or (prid is not None and adjacent(rid, prid))
            p_ii = p_i or (prid is not None and placed == approach)
            zr = ZONE_OF_NAME.get(_data_name.get(rid))
            p_iii = placed == room["name"] or (zr is not None and ZONE_OF_NAME.get(placed) == zr)
            rec["pass_i_adjacency"] += p_i
            rec["pass_ii_adjacency_plus_approach"] += p_ii
            rec["pass_iii_same_zone"] += p_iii
            rec["in_arrival_window"] += any(0 <= o - g <= ARRIVAL_WINDOW_S for g in geofence_edges(p))
            break
    k = rec["onsets_with_owner_entry"]
    for key in ("pass_i_adjacency", "pass_ii_adjacency_plus_approach", "pass_iii_same_zone"):
        rec[key + "_share"] = round(rec[key] / k, 3) if k else None
    rec["ble_after_body_s"] = dist(rec["ble_after_body_s"])
    rec["placed"] = dict(rec["placed"])
    rec["holder_rooms"] = dict(rec["holder_rooms"].most_common(6))
    SECTION_NEAR[room["name"]] = rec

# (b2) departure edge -> the last room's next occupied->vacant edge, and the share
# still occupied at timeout + 300 s (the §5.6 wait with the default margin).
SECTION_B2 = {}
for name in TRACKED:
    p = PERSONS[name]
    lags, kept = [], 0
    prev = None
    for ts, st in p["person"]:
        if prev == "home" and st not in ("home", "unknown", "unavailable"):
            last_room = state_at([(t, s_) for t, s_ in p["loc"] if s_ not in NON_ROOMS], ts)
            rid = ROOM_BY_NAME.get(last_room)
            if rid:
                occ = changes(history(ROOMS[rid]["occupied"], ts - 3600))
                off = next((t for t, s_ in occ if s_ == "off" and t >= ts), None)
                wait = float(ROOMS[rid]["timeout"] or 300) + 300
                if state_at(occ, ts) == "off":
                    lags.append(0.0)
                elif off is not None:
                    lags.append(off - ts)
                    kept += int(off - ts > wait)
                else:
                    kept += 1
        prev = st
    SECTION_B2[slug(name)] = {"departure_to_vacant_s": dist(lags), "still_occupied_after_wait": kept}

print(json.dumps({
    "window_days": WINDOW_DAYS,
    "tracked": [slug(n) for n in TRACKED],
    "rooms_with_player": sorted(v["name"] for v in ROOMS.values() if v["player"]),
    "arrival_master_stored": (merged(cm) if cm else {}).get("music_on_arrival_start", "UNSET"),
    "a": SECTION_A, "a2": SECTION_A2, "b": SECTION_B, "c": dict(SECTION_C), "d": SECTION_D,
    "a_gate": SECTION_AGATE, "a2_near": SECTION_NEAR, "b2": SECTION_B2,
}, indent=1, default=str))
