#!/usr/bin/env python3
"""D0 probe for ZONE-CAMERA-DISCOVERY-DEVICE-AREA-1 (docs/planning/PLANNING_camera_area_map_device_fallback.md rev 2).

READ-ONLY. Measures what switching the camera area map from the entity-only area to
entity-else-device area would do, BEFORE any build. Writes the markdown report body to stdout
(progress to stderr). Nothing is written to HA, the recorder or the URA DB: every SQLite open is
`mode=ro`, `.storage` is read with json and filtered to the fields used (no config-entry secrets are
printed: only the integration option keys named below and the room/zone structure).

Run (from the repo root, on the Mac):
    ssh ha python3 - < scripts/probes/camera_area_map_replay.py > /tmp/body.md
It reads /config/.storage, /config/home-assistant_v2.db (recorder) and
/config/universal_room_automation/data/universal_room_automation.db (URA DB) ON the HA host.
Override with PROBE_ROOT (default /config) and PROBE_WINDOW_DAYS (default 7).

Sections (names follow plan D0): (a) rebuilt map + Wr/U self-check, (b) zones gaining cameras + roles,
(c) room hold replay, (d) census replay (four semantics), (e) zone tier house-state replay, (f) family
room through glass, (g) 3b Wr/U deltas, (h) stuck discount.

Model limits (stated in the report too): the recorder does not hold tracking_status, so BLE-by-area
ignores the STALE/LOST exclusion; room occupancy is the recorded `binary_sensor.<room>_occupied`
(a superset of raw Tier-1); W1 twin collapse is re-implemented by device area + NVR platform
(`frigate_object_name_pairs` is not importable here); the census hold/decay machine is replayed on a
10 s grid, not on HA's tick instants.
"""
import bisect
import json
import os
import re
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

ROOT = os.environ.get("PROBE_ROOT", "/config")
WINDOW_DAYS = int(os.environ.get("PROBE_WINDOW_DAYS", "7"))
STORAGE = ROOT + "/.storage/"
REC_DB = ROOT + "/home-assistant_v2.db"
URA_DB = ROOT + "/universal_room_automation/data/universal_room_automation.db"
LOC = timezone(timedelta(hours=-6))  # CST; the whole window is after DST ended 2026-11-01
GRID = 5  # s, census replay base grid (plus every input change instant)

# Constants copied from code (file:line in the report)
CAMERA_OCC_TIMEOUT_S = 300          # presence.py:150
STREAM_DEAD_GRACE_S = 120           # const CAMERA_INPUT_STREAM_DEAD_GRACE_S
STREAM_DEAD_HOLD_MAX_S = 900        # const CAMERA_INPUT_STREAM_DEAD_HOLD_MAX_S / _CENSUS_
FACE_WINDOW_S = 1800                # const CENSUS_FACE_RECOGNITION_WINDOW_SECONDS
PEAK_SUSTAIN_S = 15                 # const CENSUS_PEAK_SUSTAIN_SECONDS
WAKING_SUSTAIN_S = 90               # presence.py:202
SLEEP_START_H, SLEEP_END_H = 22, 6  # live house sleep window (house_state_log shows SLEEP from 22:00 local; engine reads CM options)
STUCK_HOURS, STUCK_NEVERZERO_HOURS = 3.0, 6.0  # const.py:5971, :6039
HOLD_DAY = {"closet": 60, "infrastructure": 60, "generic": 120, "utility": 120, "media_room": 120,
            "garage": 120, "bathroom": 180, "common_area": 180, "bedroom": 240, "hallway": 0}
HOLD_NIGHT = {"bedroom": 1800, "media_room": 1800, "common_area": 900, "generic": 600, "closet": 300,
              "bathroom": 600, "garage": 600, "utility": 600, "infrastructure": 300, "hallway": 0}
HOLD_LEGACY = {"bedroom": 60, "media_room": 120, "common_area": 60, "generic": 60, "closet": 60,
               "bathroom": 60, "garage": 60, "utility": 60, "infrastructure": 60, "hallway": 0}
NVR_TWIN_PLATFORMS = {"unifiprotect", "reolink", "amcrest", "dahua"}
UNUSABLE = ("unavailable", "unknown", "", "none", "no_match")


def log(*a):
    print(*a, file=sys.stderr, flush=True)


# ----------------------------------------------------------------------------------------------
# time and interval helpers
# ----------------------------------------------------------------------------------------------
NOW = int(time.time())
T1 = NOW - NOW % GRID
T0 = T1 - WINDOW_DAYS * 86400


def fmt(t, secs=False):
    d = datetime.fromtimestamp(t, LOC)
    return d.strftime("%m-%d %H:%M:%S" if secs else "%m-%d %H:%M")


def parse_iso(s):
    s = s.replace("Z", "+00:00")
    d = datetime.fromisoformat(s)
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.timestamp()


def is_night(t):
    h = datetime.fromtimestamp(t, LOC).hour
    return h >= 22 or h < 6


def iv_merge(iv):
    iv = sorted((a, b) for a, b in iv if b > a)
    out = []
    for a, b in iv:
        if out and a <= out[-1][1]:
            if b > out[-1][1]:
                out[-1] = (out[-1][0], b)
        else:
            out.append((a, b))
    return out


def iv_and(x, y):
    x, y = iv_merge(x), iv_merge(y)
    i = j = 0
    out = []
    while i < len(x) and j < len(y):
        a, b = max(x[i][0], y[j][0]), min(x[i][1], y[j][1])
        if b > a:
            out.append((a, b))
        if x[i][1] < y[j][1]:
            i += 1
        else:
            j += 1
    return out


def iv_minus(x, y):
    x, y = iv_merge(x), iv_merge(y)
    out = []
    j = 0
    for a, b in x:
        cur = a
        while j < len(y) and y[j][1] <= cur:
            j += 1
        k = j
        while k < len(y) and y[k][0] < b:
            if y[k][0] > cur:
                out.append((cur, y[k][0]))
            cur = max(cur, y[k][1])
            k += 1
        if cur < b:
            out.append((cur, b))
    return out


def iv_clip(x, a, b):
    return iv_and(x, [(a, b)])


def iv_total(x):
    return sum(b - a for a, b in iv_merge(x))


def mins(sec):
    return round(sec / 60.0, 1)


def iv_extend(x, tail):
    return iv_merge([(a, b + tail) for a, b in x])


def iv_contains(x, t):
    x = iv_merge(x)
    i = bisect.bisect_right([a for a, _ in x], t) - 1
    return i >= 0 and x[i][0] <= t < x[i][1]


# ----------------------------------------------------------------------------------------------
# registries
# ----------------------------------------------------------------------------------------------
def load_json(name):
    with open(STORAGE + name) as fh:
        return json.load(fh)["data"]


log("loading registries")
ENT_LIST = load_json("core.entity_registry")["entities"]
DEV = {d["id"]: d for d in load_json("core.device_registry")["devices"]}
AREAS = {a["id"]: a["name"] for a in load_json("core.area_registry")["areas"]}
CE = load_json("core.config_entries")["entries"]
ENT = {e["entity_id"]: e for e in ENT_LIST}
ENT_BY_DEV = defaultdict(list)
for _e in ENT_LIST:
    if _e.get("device_id"):
        ENT_BY_DEV[_e["device_id"]].append(_e)
ENT_BY_UID = {}
for _e in ENT_LIST:
    if _e["platform"] == "universal_room_automation" and _e.get("unique_id"):
        ENT_BY_UID[_e["unique_id"]] = _e


def dev_name(did):
    d = DEV.get(did) or {}
    return d.get("name_by_user") or d.get("name") or ""


def area_name(a):
    return AREAS.get(a, a) if a else "-"


def area_entity_only(eid):
    return (ENT.get(eid) or {}).get("area_id")


def area_resolver(eid):
    """camera_resolver.resolve_area_id_for_entity (camera_resolver.py:474): entity area else device area."""
    e = ENT.get(eid)
    if not e:
        return None
    if e.get("area_id"):
        return e["area_id"]
    did = e.get("device_id")
    if not did:
        return None
    return (DEV.get(did) or {}).get("area_id") or None


def strip_n(name):
    return re.sub(r"_\d+$", "", name)


URA = [e for e in CE if e["domain"] == "universal_room_automation"]
INTEG = [e for e in URA if e["data"].get("entry_type") == "integration"][0]
INTEG_M = {**INTEG["data"], **(INTEG.get("options") or {})}
LISTS = {
    "interior": list(INTEG_M.get("camera_person_entities") or []),
    "egress": list(INTEG_M.get("egress_cameras") or []),
    "perimeter": list(INTEG_M.get("perimeter_cameras") or []),
}
HOLD_INTERIOR_S = int(INTEG_M.get("census_hold_interior", 3)) * 60
BLE_CANCEL_ON = bool(INTEG_M.get("census_ble_cancel_enabled", True))
XVAL_ON = bool(INTEG_M.get("census_cross_validation", True))
DIVERGENCE_DOWNGRADE = bool(INTEG_M.get("census_divergence_downgrade", True))
TRACKED = INTEG_M.get("tracked_persons") or []

ZM = [e for e in URA if e["data"].get("entry_type") == "zone_manager"][0]
ZM_M = {**ZM["data"], **(ZM.get("options") or {})}
ZONES = ZM_M.get("zones") or {}


class Room:
    pass


ROOMS = []
for e in URA:
    d = e["data"]
    m = {**d, **(e.get("options") or {})}
    if d.get("entry_type") != "room":
        continue
    r = Room()
    r.entry_id = e["entry_id"]
    r.title = e["title"]
    r.room_name = m.get("room_name") or e["title"]
    r.area = m.get("area_id")
    r.zone = m.get("zone") or None
    r.room_type = m.get("room_type") or "generic"
    r.dis_cam = bool(m.get("disable_camera_presence", False))
    r.timeout = float(m.get("occupancy_timeout") or 300)
    r.sensors = []
    for k in ("motion_sensors", "presence_sensors", "occupancy_sensors"):
        for s in m.get(k) or []:
            if s and s not in r.sensors:
                r.sensors.append(s)
    r.room_cameras = list(m.get("room_cameras") or [])
    r.disabled = e.get("disabled_by")
    ents = [x for x in ENT_LIST if x.get("config_entry_id") == e["entry_id"]]
    r.occupied_eid = next((x["entity_id"] for x in ents if (x.get("unique_id") or "").endswith("_occupied")
                           and x["entity_id"].startswith("binary_sensor.")
                           and not (x.get("unique_id") or "").endswith("hvac_occupied")), None)
    r.hvac_eid = next((x["entity_id"] for x in ents if (x.get("unique_id") or "").endswith("hvac_occupied")), None)
    r.auto_eid = (ENT_BY_UID.get(e["entry_id"] + "_automation") or {}).get("entity_id")
    ROOMS.append(r)
ROOM_BY_AREA = defaultdict(list)
for _r in ROOMS:
    if _r.area:
        ROOM_BY_AREA[_r.area].append(_r)
ZONE_OF_ROOM = {}
for zn, zc in ZONES.items():
    for rn in (zc or {}).get("zone_rooms") or []:
        ZONE_OF_ROOM[rn] = zn
for _r in ROOMS:
    _r.zone_name = ZONE_OF_ROOM.get(_r.room_name) or ZONE_OF_ROOM.get(_r.title) or _r.zone
ZONE_PICKS = sorted({p for zc in ZONES.values() for p in ((zc or {}).get("zone_cameras") or [])})
ZONE_OUTDOOR = {zn for zn, zc in ZONES.items() if (zc or {}).get("zone_is_outdoor")}


# ----------------------------------------------------------------------------------------------
# (a) map emulation: camera_census.resolve_camera_entity (:680) old vs new rule
# ----------------------------------------------------------------------------------------------
class Cam:
    pass


def camera_devices_of_lists():
    """registry device of each configured camera.* entity, per role (never from names)."""
    role_of_dev = defaultdict(set)
    for role, lst in LISTS.items():
        for c in lst:
            e = ENT.get(c)
            if e and e.get("device_id"):
                role_of_dev[e["device_id"]].add(role)
    return role_of_dev


ROLE_OF_DEV = camera_devices_of_lists()


def resolve_configured(rule):
    """Return list[Cam] exactly as CameraIntegrationManager.resolve_configured_cameras for the union of the
    three lists (device dedup, person-suffix rule, Frigate count sensor). rule 'old' | 'new'."""
    out = []
    seen_dev = set()
    allc = []
    for k in ("interior", "egress", "perimeter"):
        for c in LISTS[k]:
            if c not in allc:
                allc.append(c)
    for cam_eid in allc:
        ce = ENT.get(cam_eid)
        if not ce:
            continue
        did = ce.get("device_id")
        if not did or did in seen_dev:
            continue
        seen_dev.add(did)
        bss = [x for x in ENT_BY_DEV[did] if x["entity_id"].startswith("binary_sensor.")]
        sens = [x for x in ENT_BY_DEV[did] if x["entity_id"].startswith("sensor.")]
        for bs in bss:
            nm = strip_n(bs["entity_id"].split(".", 1)[1])
            plat = bs["platform"] or ""
            if nm.endswith("_person_occupancy"):
                dp = "frigate"
            elif nm.endswith("_person_detected"):
                dp = plat if plat in ("unifiprotect", "reolink", "dahua") else "unifiprotect"
            elif plat in ("reolink", "dahua") and "person" in (bs.get("name") or "").lower():
                dp = plat
            else:
                continue
            c = Cam()
            c.eid = bs["entity_id"]
            c.platform = dp
            c.cam_entity = cam_eid
            c.device_id = did
            c.entity_area = bs.get("area_id")
            c.device_area = (DEV.get(did) or {}).get("area_id")
            if rule == "old":
                c.area = bs.get("area_id") or ce.get("area_id")
            else:
                c.area = area_resolver(bs["entity_id"]) or area_resolver(cam_eid)
            c.count_sensor = None
            if dp == "frigate":
                base = nm[: -len("_person_occupancy")]
                canonical = "sensor." + base + "_person_count"
                fb = None
                for s in sens:
                    sn = s["entity_id"].split(".", 1)[1]
                    if strip_n(sn).endswith("_person_count") and s["entity_id"] != canonical:
                        if fb is None:
                            fb = s["entity_id"]
                if canonical in ENT:
                    c.count_sensor = canonical
                elif fb:
                    c.count_sensor = fb
            c.roles = sorted(ROLE_OF_DEV.get(did, set()))
            c.disabled = bs.get("disabled_by")
            out.append(c)
    return out


CAMS_OLD = resolve_configured("old")
CAMS_NEW = resolve_configured("new")
CAM_BY_EID_OLD = {c.eid: c for c in CAMS_OLD}
CAM_BY_EID_NEW = {c.eid: c for c in CAMS_NEW}
INTERIOR_BS = []  # census interior list: bs of devices of the interior-list cameras
_int_dev = set()
for _c in LISTS["interior"]:
    _e = ENT.get(_c)
    if _e and _e.get("device_id"):
        _int_dev.add(_e["device_id"])
for _c in CAMS_OLD:
    if _c.device_id in _int_dev:
        INTERIOR_BS.append(_c.eid)


def amap(cams):
    m = defaultdict(list)
    for c in cams:
        m[c.area or ""].append(c)
    return m


AMAP_OLD, AMAP_NEW = amap(CAMS_OLD), amap(CAMS_NEW)


def get_person_sensor_for_area(m, area):
    return [c.eid for c in m.get(area, [])] if area else []


def camera_device_for_entity(eid):
    e = ENT.get(eid)
    did = e.get("device_id") if e else None
    if not did:
        return None
    cams = [x for x in ENT_BY_DEV[did] if x["entity_id"].startswith("camera.") and not x.get("disabled_by")]
    return did if cams else None


def interior_only_for_zone(c):
    """D3a' rule: interior-list device and on neither egress nor perimeter list (by registry device)."""
    return "interior" in c.roles and not ({"egress", "perimeter"} & set(c.roles))


def zone_registrations(cams, amp, role_filter):
    """presence._discover_zone_cameras (:5192): area -> zone via room area; skip opted-out rooms."""
    area_to_zone, opted = {}, set()
    for r in ROOMS:
        if r.zone_name and r.area and r.zone_name in ZONES:
            area_to_zone[r.area] = r.zone_name
            if r.dis_cam:
                opted.add(r.area)
    reg = defaultdict(list)
    seen = set()
    for area, zn in area_to_zone.items():
        if area in opted:
            continue
        for c in amp.get(area, []):
            if role_filter and not interior_only_for_zone(c):
                continue
            if c.eid not in seen:
                seen.add(c.eid)
                reg[zn].append(c)
    return reg


def wr_and_u(amp, zone_reg):
    wr, room_inputs = set(), []
    for r in ROOMS:
        if r.disabled:
            continue
        extras = [x for x in get_person_sensor_for_area(amp, r.area) if x not in r.sensors]
        for eid in r.sensors + extras:
            d = camera_device_for_entity(eid)
            if d:
                wr.add(d)
                room_inputs.append((r.title, eid, d))
    census = list(INTERIOR_BS)
    zone_ents = set(c.eid for zl in zone_reg.values() for c in zl) | set(ZONE_PICKS)
    cand = set(census) | zone_ents
    u = sorted(e for e in cand if camera_device_for_entity(e) and camera_device_for_entity(e) not in wr)
    return wr, u, room_inputs, census


ZREG_OLD = zone_registrations(CAMS_OLD, AMAP_OLD, False)
ZREG_NEW_FULL = zone_registrations(CAMS_NEW, AMAP_NEW, False)
ZREG_NEW = zone_registrations(CAMS_NEW, AMAP_NEW, True)
WR_OLD, U_OLD, RI_OLD, _ = wr_and_u(AMAP_OLD, ZREG_OLD)
WR_NEW, U_NEW, RI_NEW, _ = wr_and_u(AMAP_NEW, ZREG_NEW)

# ----------------------------------------------------------------------------------------------
# recorder access
# ----------------------------------------------------------------------------------------------
REC = sqlite3.connect("file:%s?mode=ro" % REC_DB, uri=True)
URAC = sqlite3.connect("file:%s?mode=ro" % URA_DB, uri=True)
MID = {}


def mid(eid):
    if eid not in MID:
        r = REC.execute("select metadata_id from states_meta where entity_id=?", (eid,)).fetchone()
        MID[eid] = r[0] if r else None
    return MID[eid]


class Series:
    """Piecewise-constant state series; states compressed to value changes."""

    def __init__(self, rows):
        self.t, self.v = [], []
        for ts, st in rows:
            if st is None:
                continue
            if self.v and self.v[-1] == st:
                continue
            self.t.append(ts)
            self.v.append(st)

    def at(self, t):
        i = bisect.bisect_right(self.t, t) - 1
        return self.v[i] if i >= 0 else None

    def since(self, t):
        i = bisect.bisect_right(self.t, t) - 1
        return self.t[i] if i >= 0 else None

    def ivals(self, pred, a=None, b=None):
        a = T0 if a is None else a
        b = T1 if b is None else b
        out = []
        n = len(self.t)
        for i in range(n):
            s = max(self.t[i], a)
            e = min(self.t[i + 1] if i + 1 < n else b, b)
            if e > s and pred(self.v[i]):
                out.append((s, e))
        if not n:
            return []
        return iv_merge(out)

    def changes(self, a=None, b=None):
        a = T0 if a is None else a
        b = T1 if b is None else b
        return [(t, v) for t, v in zip(self.t, self.v) if a <= t <= b]


_HIST = {}


def hist(eid):
    if eid in _HIST:
        return _HIST[eid]
    m = mid(eid)
    rows = []
    if m is not None:
        pre = REC.execute("select last_updated_ts,state from states where metadata_id=? and last_updated_ts<? "
                          "order by last_updated_ts desc limit 1", (m, T0)).fetchone()
        if pre:
            rows.append((T0 - 1, pre[1]))
        rows += REC.execute("select last_updated_ts,state from states where metadata_id=? and last_updated_ts>=? "
                            "and last_updated_ts<=? order by last_updated_ts", (m, T0, T1 + 60)).fetchall()
    s = Series(rows)
    _HIST[eid] = s
    return s


def on_iv(eid):
    return hist(eid).ivals(lambda v: v == "on")


def latest_state(eid):
    m = mid(eid)
    if m is None:
        return None
    r = REC.execute("select state,last_updated_ts from states where metadata_id=? order by last_updated_ts desc limit 1",
                    (m,)).fetchone()
    return r


# house state timeline (URA DB, naive UTC strings)
def house_timeline():
    rows = URAC.execute("select timestamp,state,previous_state from house_state_log where timestamp>=? order by id",
                        ((datetime.fromtimestamp(T0 - 7 * 86400, timezone.utc)).strftime("%Y-%m-%dT%H:%M:%S"),)).fetchall()
    ev = []
    for ts, st, prev in rows:
        ev.append((parse_iso(ts), st, prev))
    return ev


HS_EV = house_timeline()
HS_SERIES = Series([(t, st) for t, st, _ in HS_EV])


def hs_ivals(states):
    return HS_SERIES.ivals(lambda v: v in states)


HS_ALL = {"home_day", "home_evening", "home_night", "sleep", "waking", "guest", "arriving", "away", "vacation"}
HS_IV = {s: hs_ivals({s}) for s in HS_ALL}
AWAY_IV = HS_IV["away"]


def split_house(iv_list):
    """minutes of an interval list per house state + night (22-06)"""
    out = {}
    for s in sorted(HS_ALL):
        x = iv_and(iv_list, HS_IV[s])
        if x:
            out[s] = mins(iv_total(x))
    night = []
    d0 = datetime.fromtimestamp(T0, LOC).replace(hour=0, minute=0, second=0, microsecond=0)
    for k in range(-1, WINDOW_DAYS + 2):
        base = (d0 + timedelta(days=k)).timestamp()
        night.append((base, base + 6 * 3600))
        night.append((base + 22 * 3600, base + 24 * 3600))
    return out, mins(iv_total(iv_and(iv_list, night)))


# person location / BLE
PERSON_SLUGS = []
for p in TRACKED:
    s = re.sub(r"^person\.", "", str(p)).lower().replace(" ", "_")
    PERSON_SLUGS.append(s)
LOC_SENSOR = {}
for s in PERSON_SLUGS:
    cand = "sensor.universal_room_automation_%s_location" % s
    if cand in ENT and ENT[cand]["platform"] == "universal_room_automation":
        LOC_SENSOR[s] = cand
ROOM_NAME_TO_AREA = {r.room_name: r.area for r in ROOMS if r.room_name and r.area}
ROOM_NAME_TO_AREA_LC = {k.lower(): v for k, v in ROOM_NAME_TO_AREA.items()}
SENTINELS = {"away", "unknown", "home", "lost", "", "unavailable"}


def ble_area_of(slug, t):
    loc = hist(LOC_SENSOR[slug]).at(t) if slug in LOC_SENSOR else None
    if loc is None or loc.lower() in SENTINELS:
        return None
    return ROOM_NAME_TO_AREA_LC.get(loc.lower())


def ble_loc_name(slug, t):
    loc = hist(LOC_SENSOR[slug]).at(t) if slug in LOC_SENSOR else None
    return None if loc is None or loc.lower() in SENTINELS else loc


# ----------------------------------------------------------------------------------------------
# report assembly
# ----------------------------------------------------------------------------------------------
OUT = []


def P(s=""):
    OUT.append(s)


def table(header, rows):
    P("| " + " | ".join(header) + " |")
    P("|" + "|".join("---" for _ in header) + "|")
    for r in rows:
        P("| " + " | ".join(str(x) for x in r) + " |")
    P()


def short(eid):
    return eid.split(".", 1)[1] if eid and "." in eid else eid


def room_str(area):
    rs = ROOM_BY_AREA.get(area, [])
    return ", ".join(r.title for r in rs) if rs else "-"


# ===================== (a) =====================
log("section a")
P("## (a) The rebuilt map")
P()
P("Window: %s to %s CST (%d days; recorder holds %s onward). Probe run %s. Rule: `old` = `bs_entity.area_id or "
  "camera_entry.area_id` (`camera_census.py:680`); `new` = `resolve_area_id_for_entity(bs) or "
  "resolve_area_id_for_entity(camera)` (`camera_resolver.py:474`, entity area else device area)." % (
      fmt(T0), fmt(T1), WINDOW_DAYS, fmt(REC.execute("select min(last_updated_ts) from states").fetchone()[0]),
      fmt(NOW, True)))
P()
P("Configured lists (integration entry): interior `camera_person_entities` = %d, `egress_cameras` = %d, "
  "`perimeter_cameras` = %d camera.* entities. Roles below are resolved per registry DEVICE of each configured camera.* entity; "
  "no name is used." % (len(LISTS["interior"]), len(LISTS["egress"]), len(LISTS["perimeter"])))
P()
P("### Self-check: the old rule must reproduce Wr 3 / U 14 (`AUDIT_v5_108_25_watched_set_2026_11_15.md`)")
P()
old_keys = Counter({k or "''": len(v) for k, v in AMAP_OLD.items()})
P("- Old-rule area map keys: `%s` (audit: `{'': 28}`)." % dict(old_keys))
P("- Rooms with camera extras under the old rule: %d." % sum(1 for r in ROOMS if get_person_sensor_for_area(AMAP_OLD, r.area)))
SC_WR = len(WR_OLD)
SC_U = len(U_OLD)
P("- **Wr (old rule) = %d, U (old rule) = %d** -> %s" % (SC_WR, SC_U, "PASS (3 / 14)" if (SC_WR, SC_U) == (3, 14) else
                                                          "**FAIL: expected 3 / 14, probe does not match the code**"))
P("- Wr devices (old): %s" % ", ".join(sorted(dev_name(d) for d in WR_OLD)))
P("- U entities (old, %d): %s" % (SC_U, ", ".join(short(x) for x in U_OLD)))
P()
P("### Per-camera table (every person sensor reached by the configured lists)")
P()
rows = []
for c in sorted(CAMS_NEW, key=lambda x: (",".join(x.roles), x.eid)):
    old = CAM_BY_EID_OLD.get(c.eid)
    rms = ROOM_BY_AREA.get(c.area, [])
    zones = sorted({r.zone_name for r in rms if r.zone_name})
    autos = []
    for r in rms:
        st = latest_state(r.auto_eid) if r.auto_eid else None
        autos.append("%s=%s" % (r.title, st[0] if st else "?"))
    rows.append((
        "`%s`" % short(c.eid), c.platform, "/".join(c.roles) or "-", dev_name(c.device_id),
        area_name(c.entity_area), area_name(c.device_area), area_name(old.area if old else None),
        area_name(c.area), room_str(c.area), ", ".join(zones) or "-", "; ".join(autos) or "-",
        ", ".join("%s:%s" % (r.title, "mute" if r.dis_cam else "ok") for r in rms) or "-"))
table(["person sensor", "platform", "role", "device", "entity area", "device area", "OLD area", "NEW area",
       "URA room on NEW area", "zone", "room Automation switch (live)", "disable_camera_presence"], rows)
# full-scan output (camera_census._discover_full_scan: frigate platform or *_person_occupancy, unifi platform or *_person_detected; area = entity area)
FS = []
for e in ENT_LIST:
    if not e["entity_id"].startswith("binary_sensor."):
        continue
    nm = strip_n(e["entity_id"].split(".", 1)[1])
    if e["platform"] == "frigate" or nm.endswith("_person_occupancy"):
        FS.append((e["entity_id"], "frigate", e.get("area_id")))
    elif e["platform"] == "unifiprotect" or nm.endswith("_person_detected"):
        FS.append((e["entity_id"], "unifiprotect", e.get("area_id")))
fs_keys = Counter((a or "''") for _, _, a in FS)
P("Full-scan output (no lists configured; `camera_census.py:1130-1200`): %d sensors (every `frigate`-platform binary sensor plus "
  "name-suffix matches, so it includes non-person Frigate sensors); area keys by ENTITY area only: %s. Under the NEW rule full-scan "
  "would still read entity area only (the plan changes `:1163/:1191` to the resolver, which would key them by device area; not "
  "live because lists are configured)." % (len(FS), dict(fs_keys)))
P()
# legacy fire-axe cross-platform (:975-1030): siblings of base infos by stem; area = entry.area_id or info.area_id
leg = []
for c in CAMS_OLD:
    stem = re.sub(r"_(person_occupancy|person_detected|person|person_count)$", "", strip_n(c.eid.split(".", 1)[1]))
    for cand in ("binary_sensor.%s_person_detected" % stem, "binary_sensor.%s_person_occupancy" % stem,
                 "binary_sensor.%s_person" % stem, "sensor.%s_person_count" % stem):
        if cand in ENT and cand != c.eid:
            leg.append((cand, (ENT[cand].get("area_id") or c.area)))
P("Legacy cross-platform fire-axe path (`:975-1030`, taken only when `CENSUS_USE_NEW_RESOLVER` is False): %d sibling entities found, "
  "areas (entity area or the base info's area) = %s; the live path `:919` uses `resolve_area_id_for_entity` already and so equals the "
  "NEW column for any entity it returns." % (len(leg), dict(Counter((a or "''") for _, a in leg))))
P()
n_old = sum(len(v) for k, v in AMAP_OLD.items() if k)
P("NEW map: %d person sensors keyed under %d real areas, %d under `''` (device without area)." % (
    sum(len(v) for k, v in AMAP_NEW.items() if k), sum(1 for k in AMAP_NEW if k),
    len(AMAP_NEW.get("", []))))
P()
unmapped = [c for c in CAMS_NEW if not ROOM_BY_AREA.get(c.area)]
P("Cameras whose NEW area has **no URA room** (the room hold and the zone tier never see them; they only change the census "
  "area key and Wr/U): %s." % (", ".join("`%s` (%s)" % (short(c.eid), area_name(c.area)) for c in unmapped) or "none"))
P()

# ===================== (b) =====================
log("section b")
P("## (b) Zones that gain cameras, with roles")
P()
P("Zone camera tier = `presence._discover_zone_cameras` (`presence.py:5192`): area -> zone via the room's `CONF_AREA_ID`, "
  "rooms with `disable_camera_presence` skipped. Plan D3a' admits only cameras whose configured `camera.*` device is on the "
  "interior list and on neither egress nor perimeter. Role = union of the lists the device's configured camera.* entities are on.")
P()
rows = []
for zn in sorted(ZONES):
    full = ZREG_NEW_FULL.get(zn, [])
    adm = {c.eid for c in ZREG_NEW.get(zn, [])}
    for c in full:
        rms = [r.title for r in ROOM_BY_AREA.get(c.area, []) if r.zone_name == zn]
        rows.append((zn, "`%s`" % short(c.eid), dev_name(c.device_id), area_name(c.device_area), ", ".join(rms),
                     "/".join(c.roles), "**YES**" if c.eid in adm else "no (role)"))
if not rows:
    P("(no zone gains a camera)")
else:
    table(["zone", "person sensor", "device", "device area (mount)", "room", "role", "admitted by D3a'"], rows)
reg_old = sum(len(v) for v in ZREG_OLD.values())
P("Zone tier registrations: old rule %d; new rule without role filter %d; new rule with D3a' %d (boot INFO "
  "\"Subscribed to N zone camera entities\" should read %d)." % (
      reg_old, sum(len(v) for v in ZREG_NEW_FULL.values()), sum(len(v) for v in ZREG_NEW.values()),
      len({c.eid for v in ZREG_NEW.values() for c in v})))
P()
excl = [c for v in ZREG_NEW_FULL.values() for c in v if c.eid not in {x.eid for y in ZREG_NEW.values() for x in y}]
P("Egress/perimeter cameras the role filter keeps OUT of the zone tier (they still enter the room hold lookup and Wr, because "
  "`get_person_sensor_for_area` reads the full map): %s." % (", ".join("`%s` (%s, %s)" % (short(c.eid), "/".join(c.roles), area_name(c.area)) for c in excl) or "none"))
P()
opted = [r.title for r in ROOMS if r.dis_cam and any(c.area == r.area for c in CAMS_NEW)]
P("Rooms on a camera area that are opted out (`disable_camera_presence` True): %s." % (", ".join(opted) or "none"))
P()

# ===================== (g) computed here for ordering =====================
# ===================== (c) =====================
log("section c")
P("## (c) 7-day room-hold replay")
P()
P("Model (code: `coordinator.py:4491`): the v3.5.1 block runs when the room reads vacant and a camera person sensor in the "
  "room's area reads `on`; it sets occupied, `occupancy_source=camera`, and stamps HVAC evidence. Base occupancy = the recorded "
  "`binary_sensor.<room>_occupied` (no camera sensor is in any room's extras today, so it IS the no-camera room). "
  "**Created minutes** = camera `on` while the room reads vacant. **Extra hold (upper bound)** adds the room's occupancy timeout "
  "after each camera-held stretch ends (the plan's \"+ room occupancy timeout\"; the code block itself does not refresh "
  "`_last_motion_time`, so the lower bound is the created minutes alone). **HVAC extra** = minutes `hvac_occupied` would be "
  "added using the room-type evidence hold (`const.py:1788` day table in home_day/evening, night table in sleep/waking, legacy "
  "tail elsewhere; hallways 0). \"Supported\" = a BLE person located in that room or a configured Tier-1 sensor on within "
  "+-120 s; unsupported minutes are the leak.")
P()
CAM_ROOMS = []
for r in ROOMS:
    sens = get_person_sensor_for_area(AMAP_NEW, r.area)
    if sens:
        CAM_ROOMS.append((r, sens))
P("Entities resolved per camera room by registry unique_id (`<entry_id>_occupied`, `_automation`, `hvac_occupied`): " + "; ".join(
    "%s: `%s` / `%s` / `%s`" % (r.title, short(r.occupied_eid or "NONE"), short(r.hvac_eid or "NONE"), short(r.auto_eid or "NONE"))
    for r, _ in CAM_ROOMS))
P()
ROOM_RES = {}
rows, rows2 = [], []
for r, sens in CAM_ROOMS:
    cam_on = iv_merge([x for s in sens for x in on_iv(s)])
    base_occ = on_iv(r.occupied_eid) if r.occupied_eid else []
    create = iv_minus(cam_on, base_occ)
    upper = iv_minus(iv_extend(create, r.timeout), base_occ)
    tail = iv_minus(upper, create)
    # support
    t1_on = iv_merge([x for s in r.sensors for x in on_iv(s)])
    t1_pad = iv_merge([(a - 120, b + 120) for a, b in t1_on])
    ble_here = []
    for s in PERSON_SLUGS:
        if s in LOC_SENSOR:
            nm = r.room_name.lower()
            ble_here += hist(LOC_SENSOR[s]).ivals(lambda v, nm=nm: (v or "").lower() == nm)
    ble_here = iv_merge(ble_here)
    supported = iv_and(create, iv_merge(t1_pad + ble_here))
    unsupported = iv_minus(create, supported)
    # HVAC
    hv_base = on_iv(r.hvac_eid) if r.hvac_eid else []
    rt = r.room_type
    parts = []
    for st, tbl in (("home_day", HOLD_DAY), ("home_evening", HOLD_DAY), ("sleep", None), ("waking", None)):
        pass
    ext = []
    for a, b in create:
        for st, ivs in HS_IV.items():
            seg = iv_and([(a, b)], ivs)
            if not seg:
                continue
            if st in ("home_day", "home_evening"):
                hold = HOLD_DAY.get(rt, 120)
            elif st in ("sleep", "waking"):
                hold = max(HOLD_NIGHT.get(rt, 600), HOLD_LEGACY.get(rt, 60))
            else:
                hold = HOLD_LEGACY.get(rt, 60)
            for s0, e0 in seg:
                ext.append((s0, e0 + hold))
    hv_cf = iv_merge(hv_base + (ext if rt != "hallway" else []))
    hv_extra = iv_minus(hv_cf, hv_base)
    eps = len(iv_merge(create))
    cs, cn = split_house(create)
    ROOM_RES[r.title] = dict(room=r, sens=sens, create=create, cam_on=cam_on, supported=supported,
                             unsupported=unsupported, eps=eps, split=cs, night=cn, hv_extra=hv_extra, tail=tail,
                             ble_here=ble_here)
    rows.append((r.title, ", ".join("`%s`" % short(s) for s in sens), r.zone_name or "-", r.room_type,
                 "mute" if r.dis_cam else "ok", mins(iv_total(cam_on)), mins(iv_total(create)), eps,
                 mins(iv_total(tail)), mins(iv_total(hv_extra)),
                 mins(iv_total(unsupported)),
                 ("%.0f%%" % (100.0 * iv_total(unsupported) / iv_total(create))) if iv_total(create) else "-"))
    rows2.append((r.title, ", ".join("%s %s" % (k, v) for k, v in sorted(cs.items())) or "-", cn))
rows.sort(key=lambda x: -float(x[9]))
table(["room", "camera sensors in its area", "zone", "type", "camera presence", "camera-on min", "created min",
       "episodes", "extra hold min (upper, +timeout tail)", "HVAC extra occupied min", "unsupported created min",
       "unsupported %"], rows)
P("Created minutes split by house state (minutes) and night (22:00-06:00 local):")
P()
table(["room", "created min by house state", "of which night"], rows2)

P("### Per-room hold recommendation under the plan's Q1 rule")
P()
P("Q1 text (plan §8): *\"None until D0 (c)/(f) is shown; then only rooms whose cameras watch only that room (no glass, no doorway "
  "into another area) and where D0 shows held minutes that match real presence.\"* Operationalised here so it is falsifiable "
  "(thresholds are this probe's, not the plan's, and are stated so the operator can change them): ON only if ALL of: room not "
  "muted; every camera in the area is interior-role (no egress/perimeter device); >= 30 created minutes in %d days (the hold "
  "does something); unsupported share of created minutes <= 10%% (held minutes agree with BLE-in-room or a Tier-1 sensor +-120 s); "
  "no documented glass/doorway hazard (Living Room: patio through glass, card CENSUS-PATIO-THROUGH-GLASS-1, "
  "`IDENTITY_FUSION_CAMERAS_MANUAL.md` §1.2 pool-overhead trap has no room today)." % WINDOW_DAYS)
P()
HAZ = {"Living Room": "patio through glass (CENSUS-PATIO-THROUGH-GLASS-1, config fix pending)"}
q1rows = []
Q1_ON = []
for r, sens in CAM_ROOMS:
    rr_ = ROOM_RES[r.title]
    cams_ = [CAM_BY_EID_NEW[x] for x in sens if x in CAM_BY_EID_NEW]
    roles_ok = all("interior" in c.roles and not ({"egress", "perimeter"} & set(c.roles)) for c in cams_)
    created = iv_total(rr_["create"]) / 60.0
    uns = iv_total(rr_["unsupported"]) / 60.0
    share = (uns / created) if created else None
    reasons = []
    if r.dis_cam:
        reasons.append("muted (disable_camera_presence)")
    if not roles_ok:
        reasons.append("exterior-role camera in the area (%s)" % ",".join(sorted({x for c in cams_ for x in c.roles if x != "interior"})))
    if created < 30:
        reasons.append("created %.1f min < 30" % created)
    if share is not None and share > 0.10:
        reasons.append("unsupported %.0f%% > 10%%" % (100 * share))
    if r.title in HAZ:
        reasons.append("hazard: " + HAZ[r.title])
    verdict = "ON" if not reasons else "off"
    if verdict == "ON":
        Q1_ON.append(r.title)
    sw = latest_state(r.auto_eid)
    d14 = datetime.strptime("2026-11-14", "%Y-%m-%d").replace(tzinfo=LOC).timestamp()
    c14 = iv_total(iv_and(rr_["create"], [(d14, d14 + 86400)])) / 60.0
    u14 = iv_total(iv_and(rr_["unsupported"], [(d14, d14 + 86400)])) / 60.0
    q1rows.append((r.title, verdict, "; ".join(reasons) or "meets every test", "%.1f" % created,
                   ("%.0f%%" % (100 * share)) if share is not None else "-", "%.1f / %.1f" % (c14, u14),
                   sw[0] if sw else "?"))
table(["room", "hold on ship day?", "why", "created min", "unsupported", "11-14 (party) created / unsupported min",
       "room Automation switch (live)"], q1rows)
P("**Rooms recommended ON under this reading: %s.**" % (", ".join(Q1_ON) or "none"))
P()

# ===================== (f) =====================
log("section f")
P("## (f) Family Room patio through glass (CENSUS-PATIO-THROUGH-GLASS-1)")
P()
FR_DEVS = {d for d in DEV if (DEV[d].get("area_id") == "living_room" and
                              any(x["entity_id"].startswith("camera.") for x in ENT_BY_DEV[d]))}
FR_SENS = [c.eid for c in CAMS_NEW if c.device_id in FR_DEVS]
FR_COUNT = [c.count_sensor for c in CAMS_NEW if c.device_id in FR_DEVS and c.count_sensor]
living = [r for r in ROOMS if r.area == "living_room"]
P("Family-room camera devices (device area `living_room`, registry): %s. Person sensors: %s; count sensors: %s. "
  "Room(s) on that area: %s (room_cameras fusion picks: %s)." % (
      ", ".join(dev_name(d) for d in sorted(FR_DEVS)) or "none", ", ".join("`%s`" % short(x) for x in FR_SENS),
      ", ".join("`%s`" % short(x) for x in FR_COUNT), ", ".join(r.title for r in living) or "none",
      "; ".join("%s: %s" % (r.title, r.room_cameras) for r in living)))
P()
fr_res = None
if living and FR_SENS:
    r = living[0]
    cam_on = iv_merge([x for s in FR_SENS for x in on_iv(s)])
    cnt_pos = iv_merge([x for s in FR_COUNT for x in hist(s).ivals(
        lambda v: v not in ("unavailable", "unknown", None) and float(v) > 0)])
    cam_any = iv_merge(cam_on + cnt_pos)
    t1_on = iv_merge([x for s in r.sensors for x in on_iv(s)])
    ble = ROOM_RES.get(r.title, {}).get("ble_here", [])
    quiet = iv_minus(cam_any, iv_merge(t1_on + ble + (on_iv(r.occupied_eid) if r.occupied_eid else [])))
    quiet_strict = iv_minus(cam_any, iv_merge(t1_on + ble))
    sun_below = hist("sun.sun").ivals(lambda v: v == "below_horizon")
    sun_above = hist("sun.sun").ivals(lambda v: v == "above_horizon")
    fr_res = dict(any=iv_total(cam_any), quiet=iv_total(quiet_strict), quiet_vacant=iv_total(quiet))
    P("Room sensors considered quiet = %d configured Tier-1 sensors (`%s`) all off and no BLE person located in `%s`." % (
        len(r.sensors), ", ".join(short(s) for s in r.sensors), r.room_name))
    P()
    rows = []
    for label, x in (("camera person on OR count > 0", cam_any),
                     ("... while room's own sensors quiet AND no BLE person in room", quiet_strict),
                     ("... and the room itself reads vacant (what a hold would CREATE)", quiet)):
        sp, nt = split_house(x)
        rows.append((label, mins(iv_total(x)), ", ".join("%s %s" % (k, v) for k, v in sorted(sp.items())) or "-",
                     mins(iv_total(iv_and(x, AWAY_IV))), mins(iv_total(iv_and(x, sun_above))),
                     mins(iv_total(iv_and(x, sun_below)))))
    table(["measure", "total min", "by house state (min)", "house AWAY min", "sun up min", "dark min"], rows)
    P("Reading: the quiet-room row is the upper bound of patio leak into the room hold and (via the same sensors) the census; "
      "the AWAY column is the same minutes while no resident is home, i.e. a body the room sensors and BLE cannot corroborate.")
    P()
else:
    P("No family-room camera mapped; nothing to measure.")
    P()

# ===================== (e) zone tier =====================
log("section e")
P("## (e) Zone tier house-state replay (camera-INCLUSIVE counterfactual)")
P()
P("Model: `ZonePresenceTracker._any_camera_occupied` (`presence.py:819`): a registered camera holds its zone while detecting or "
  "within %d s of its last `on`; S2 \"dead input holds\": a sensor `unavailable` longer than the %d s grace keeps its last "
  "reading for up to %d s from the first unavailable, then reads off. Non-camera zone occupancy = any room of the zone "
  "occupied (recorded `binary_sensor.<room>_occupied`, which already includes BLE extension) OR a BLE person located in a room "
  "of the zone. Cameras registered = D3a' set (interior role only) in non-opted-out rooms." % (
      CAMERA_OCC_TIMEOUT_S, STREAM_DEAD_GRACE_S, STREAM_DEAD_HOLD_MAX_S))
P()


def cam_tier_ivals(eid):
    s = hist(eid)
    out = []
    n = len(s.t)
    i = 0
    cur_on_start = None
    detect = False
    last_on = None
    # build detect intervals with dead-hold semantic
    dead_start = None
    segs = []  # (start,end) detecting
    state = None
    times = list(s.t) + [T1 + 1]
    vals = list(s.v) + [None]
    seg_start = None
    for k in range(n):
        t, v = times[k], vals[k]
        tn = times[k + 1]
        if v == "on":
            if seg_start is None:
                seg_start = t
            seg_end_candidate = tn
            # continue; closed when state leaves on
            if k + 1 >= n or vals[k + 1] != "on":
                pass
        else:
            if v in ("unavailable", "unknown") and seg_start is not None:
                # dead hold: keep detecting for up to hold max if dead longer than grace
                dur = tn - t
                if dur > STREAM_DEAD_GRACE_S:
                    hold = min(dur, STREAM_DEAD_HOLD_MAX_S)
                    # still detecting during the hold
                    if t + hold >= tn:  # recovers inside the cap: detection continues through, resync at return
                        # return state decides next iteration; keep seg_start
                        continue
                    segs.append((seg_start, t + hold))
                    seg_start = None
                    continue
            if seg_start is not None:
                segs.append((seg_start, t))
                seg_start = None
    if seg_start is not None:
        segs.append((seg_start, T1))
    return iv_merge([(a, b + CAMERA_OCC_TIMEOUT_S) for a, b in segs])


ZONE_ROOMS = defaultdict(list)
for r in ROOMS:
    if r.zone_name:
        ZONE_ROOMS[r.zone_name].append(r)
ZN_NONCAM = {}
ZN_CAM = {}
ZN_CAM_BY_SENSOR = {}
for zn in ZONES:
    rooms = ZONE_ROOMS.get(zn, [])
    occ = []
    for r in rooms:
        if r.occupied_eid:
            occ += on_iv(r.occupied_eid)
        for s in PERSON_SLUGS:
            if s in LOC_SENSOR:
                names = {x.room_name.lower() for x in rooms}
                occ += hist(LOC_SENSOR[s]).ivals(lambda v, names=names: (v or "").lower() in names)
    ZN_NONCAM[zn] = iv_merge(occ)
    cams = ZREG_NEW.get(zn, [])
    per = {c.eid: cam_tier_ivals(c.eid) for c in cams}
    ZN_CAM_BY_SENSOR[zn] = per
    ZN_CAM[zn] = iv_merge([x for v in per.values() for x in v])
indoor = [z for z in ZONES if z not in ZONE_OUTDOOR]
K_ALL = iv_merge([x for z in indoor for x in ZN_CAM[z]])
N_ALL = iv_merge([x for z in indoor for x in ZN_NONCAM[z]])

# calibration: recorded zone mode occupied (camera-free today) vs my non-camera model
calib = []
for zn in indoor:
    ent = "sensor.zone_%s_presence_status" % re.sub(r"[^a-z0-9]+", "_", zn.lower()).strip("_")
    s = hist(ent)
    if s.t:
        rec = s.ivals(lambda v: v == "occupied")
        awake = iv_minus([(T0, T1)], HS_IV["sleep"])
        a = iv_total(iv_and(rec, awake))
        mymod = iv_total(iv_and(ZN_NONCAM[zn], awake))
        both = iv_total(iv_and(iv_and(rec, ZN_NONCAM[zn]), awake))
        calib.append((zn, mins(a), mins(mymod), mins(both),
                      "%.0f%%" % (100.0 * both / a) if a else "-"))
P("Calibration of the non-camera zone model against the recorded `sensor.zone_<z>_presence_status` (cameras are not "
  "registered today, so the recorded mode IS the camera-free mode; SLEEP excluded because the mode is pinned):")
P()
table(["zone", "recorded occupied min", "model non-camera min", "overlap min", "recorded covered by model"], calib)
rows = []
for zn in sorted(ZONES):
    cams = ZREG_NEW.get(zn, [])
    only = iv_minus(ZN_CAM[zn], ZN_NONCAM[zn])
    sp, nt = split_house(only)
    rows.append((zn, ", ".join("`%s`" % short(c.eid) for c in cams) or "-", mins(iv_total(ZN_CAM[zn])),
                 mins(iv_total(only)), ", ".join("%s %s" % (k, v) for k, v in sorted(sp.items())) or "-", nt))
P("### Minutes a zone reads occupied ONLY because of a camera (timeout %d s + dead-hold included)" % CAMERA_OCC_TIMEOUT_S)
P()
table(["zone", "registered cameras", "camera-tier min", "camera-ONLY min", "camera-ONLY by house state", "of which night"], rows)

# AWAY edges
away_rows = []
mm = mid("sensor.ura_presence_coordinator_presence_house_state")
CAM_RUNS = {}  # sensor -> merged tier intervals (all zones)
for zn_, per_ in ZN_CAM_BY_SENSOR.items():
    if zn_ in ZONE_OUTDOOR:
        continue
    for se_, iv_ in per_.items():
        CAM_RUNS[se_] = iv_
for t, st, prev in HS_EV:
    if st != "away" or not (T0 <= t <= T1):
        continue
    vp = lab = None
    stamp_ok = False
    for row in REC.execute("select s.last_updated_ts,a.shared_attrs from states s join state_attributes a on a.attributes_id=s.attributes_id "
                           "where s.metadata_id=? and s.last_updated_ts>=? and s.last_updated_ts<=? and s.state='away' "
                           "order by s.last_updated_ts limit 12", (mm, t - 5, t + 240)).fetchall():
        try:
            d = json.loads(row[1])
        except Exception:
            continue
        la = d.get("last_away_at")
        try:
            la_ts = parse_iso(la) if la else None
        except Exception:
            la_ts = None
        if la_ts is not None and abs(la_ts - t) <= 120:
            vp, lab, stamp_ok = d.get("veto_path"), d.get("last_away_branch"), True
            break
        if vp is None:
            vp, lab = d.get("veto_path"), d.get("last_away_branch")
    in_run = None
    for a_, b_ in K_ALL:
        if a_ - 1 <= t < b_:
            in_run = (a_, b_)
            break
    remaining = (in_run[1] - t) if in_run else 0
    cams_cov = sorted(short(se) for se, iv_ in CAM_RUNS.items() if iv_contains(iv_, t))
    branch = lab if lab and lab not in ("none", "?") else (vp or "?")
    reads_zone = branch != "active"
    away_rows.append((fmt(t, True), prev, vp or "?", lab or "?", "yes" if stamp_ok else "NO (stale attr)", int(remaining),
                      int(remaining) if reads_zone else 0, ", ".join(cams_cov) or "-"))
P("### AWAY edges split by `veto_path` / `last_away_branch` (recorded attributes on `sensor.ura_presence_coordinator_presence_house_state`), with the delay "
  "the camera-INCLUSIVE tier would add")
P()
P("`veto_path` is the engine's current value and resets after the edge (many rows read `none`); `last_away_branch` is the value AT the "
  "inference edge and is used as the split key; the attribute row is accepted only if its `last_away_at` is within 120 s of the "
  "edge. Path semantics (code): nobody-home reads `any_zone_occupied_for_empty`; path beta (`lost_admitted*`) reads "
  "`any_indoor_zone_occupied`; path alpha (`active`) reads no zone (`presence.py:1227-1232`, ledger #12), so its delay is 0 by "
  "construction (column 'delay applied'); column 'camera run remaining' shows how long a camera-tier run covered the instant, "
  "for information. Cameras: D3a' set, indoor zones.")
P()
table(["AWAY edge (CST)", "from", "veto_path (attr)", "last_away_branch", "attr row matches edge", "camera run remaining s",
       "delay applied s", "cameras holding at the edge"], away_rows)
by_vp = defaultdict(list)
for row in away_rows:
    by_vp[row[3] if row[3] not in ("?", "none") else row[2]].append(row[6])
summ = []
for k, v in sorted(by_vp.items()):
    summ.append((k, len(v), sum(1 for x in v if x > 0), max(v) if v else 0, sum(1 for x in v if x > 1200)))
table(["split key (last_away_branch)", "edges", "edges delayed by camera tier", "max delay s", "edges over the 1200 s bound"], summ)
P("Corrected bound (plan HIGH 1): 300 s camera timeout + up to %d s stream-dead hold = %d s PER CAMERA SENSOR in a healthy-or-dead-"
  "but-recovering state. A sensor that stays `on` (stuck or real) holds without limit, which is why the observed maximum below "
  "can exceed the bound: observed max delay applied %d s." % (STREAM_DEAD_HOLD_MAX_S, CAMERA_OCC_TIMEOUT_S + STREAM_DEAD_HOLD_MAX_S,
                               max([r[6] for r in away_rows] or [0])))
P()

# ARRIVING while AWAY
arr_rows = []
for a, b in AWAY_IV:
    for ka, kb in K_ALL:
        if a <= ka < b:
            real = any(T for T in [t for t, st, _ in HS_EV if st == "arriving" and ka <= t <= ka + 600])
            arr_rows.append((fmt(ka, True), int(kb - ka), "yes (house left AWAY within 10 min)" if real else "no (phantom)"))
P("### Would-be ARRIVING edges while AWAY (camera-inclusive counterfactual; D3c keeps these at zero)")
P()
if arr_rows:
    table(["camera-tier run starts while house AWAY (CST)", "run length s", "real arrival followed"], arr_rows)
else:
    P("None: no registered interior camera produced a run while the house was AWAY in the window.")
    P()

# WAKING
log("section e waking")
wk_rows = []
for t, st, prev in HS_EV:
    if st != "waking" or prev != "sleep" or not (T0 <= t <= T1):
        continue
    day0 = datetime.fromtimestamp(t, LOC).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    gate0 = day0 + SLEEP_END_H * 3600

    def first_sustained(iv):
        for a, b in iv_merge(iv):
            if b <= gate0:
                continue
            s0 = max(a, gate0)
            if b - s0 >= WAKING_SUSTAIN_S or (a < gate0 and b - a >= WAKING_SUSTAIN_S and b > gate0):
                return max(a + WAKING_SUSTAIN_S, gate0)
        return None

    cf0 = first_sustained(N_ALL)
    cf1 = first_sustained(iv_merge(N_ALL + K_ALL))
    moved = (t - cf1) if cf1 is not None else 0
    cam_caused = cf1 is not None and (cf0 is None or cf1 < cf0 - 30)
    # someone up in the minute: BLE location change within +-5 min of cf1, or Tier-1 raw on
    up = None
    if cam_caused:
        moves = 0
        for s in PERSON_SLUGS:
            if s in LOC_SENSOR:
                moves += len([1 for tt, v in hist(LOC_SENSOR[s]).changes(cf1 - 300, cf1 + 300)])
        t1 = 0
        for r in ROOMS:
            for sn in r.sensors:
                t1 += len([1 for tt, v in hist(sn).changes(cf1 - 300, cf1 + 300) if v == "on"])
        up = "BLE moves %d, Tier-1 on-edges %d" % (moves, t1)
    wk_rows.append((fmt(t, True), fmt(cf0, True) if cf0 else "-", fmt(cf1, True) if cf1 else "-",
                    int(moved) if cam_caused else 0, "YES" if cam_caused else "no", up or "-"))
P("### WAKING edges (SLEEP -> WAKING) moved earlier by the camera tier")
P()
P("Model: after `sleep_end_hour` 06:00 local the sustained gate needs `any_zone_raw_occupied` for %d s (`presence.py:202`, "
  "`:7767`). cf0 = first sustained run of the non-camera model after 06:00 (calibration: should sit just before the actual "
  "edge); cf1 = same with the camera tier OR-ed in. An edge is camera-moved only if cf1 is earlier than cf0 by > 30 s." % WAKING_SUSTAIN_S)
P()
if wk_rows:
    table(["actual WAKING edge", "model cf0 (no camera)", "model cf1 (with camera)", "moved earlier s", "camera-moved?",
           "was someone up? (+-5 min of cf1)"], wk_rows)
else:
    P("No SLEEP -> WAKING edge in the window.")
    P()

# SLEEP night limb
nights = Counter()
nights_z = defaultdict(Counter)
cam_only_sleep = iv_and(iv_minus(K_ALL, N_ALL), HS_IV["sleep"])
for a_, b_ in cam_only_sleep:
    key = datetime.fromtimestamp(a_ - 12 * 3600, LOC).strftime("%m-%d")
    nights[key] += b_ - a_
zrows = []
for zn_ in indoor:
    zo = iv_and(iv_minus(ZN_CAM[zn_], ZN_NONCAM[zn_]), HS_IV["sleep"])
    nz = Counter()
    for a_, b_ in zo:
        nz[datetime.fromtimestamp(a_ - 12 * 3600, LOC).strftime("%m-%d")] += b_ - a_
    zrows.append((zn_, mins(iv_total(zo)), len(nz), ", ".join("%s: %s" % (k, mins(v)) for k, v in sorted(nz.items())) or "-"))
P("### SLEEP held by `_zone_night_raw` through a camera limb")
P()
P("House-wide (decisive for nobody-home / path beta, which need ANY indoor zone occupied): minutes during house SLEEP where the "
  "camera tier is the only occupied input of EVERY indoor zone that is occupied: **%s min over %d nights** (%s)." % (
      mins(iv_total(cam_only_sleep)), len(nights),
      ", ".join("night of %s: %s min" % (k, mins(v)) for k, v in sorted(nights.items())) or "none"))
P()
P("Per zone (display / HVAC night tail only; the zone reads occupied through SLEEP only because of a camera):")
P()
table(["zone", "camera-only SLEEP min", "nights", "per night (min)"], zrows)
# inference triggers per day
trig = defaultdict(int)
for zn in ZONES:
    for c in ZREG_NEW.get(zn, []):
        for t, v in hist(c.eid).changes():
            if v in ("on", "off"):
                trig[datetime.fromtimestamp(t, LOC).strftime("%m-%d")] += 1
P("`camera_detection` inference triggers per day (state edges on registered sensors): %s." % (
    ", ".join("%s: %d" % (k, v) for k, v in sorted(trig.items())) or "none"))
P()

# ===================== (d) census replay =====================
log("section d")
P("## (d) Census replay under the four semantics")
P()
INT_CAMS_NEW = [CAM_BY_EID_NEW[e] for e in INTERIOR_BS if e in CAM_BY_EID_NEW]
INT_CAMS_OLD = [CAM_BY_EID_OLD[e] for e in INTERIOR_BS if e in CAM_BY_EID_OLD]
FRIG = [c for c in INT_CAMS_NEW if c.platform == "frigate"]
FRIG_CNT = [c for c in FRIG if c.count_sensor]
BIN = [c for c in INT_CAMS_NEW if c.platform != "frigate"]
P("Interior census set (resolved by registry from the interior list): %d person sensors; Frigate with a count sensor %d (feed "
  "`unidentified_count`), Frigate binary-only %d, other platforms %d (feed only the raw camera total). Options read: "
  "census_hold_interior %d s, census_ble_cancel_enabled %s, cross-validation %s, divergence downgrade %s." % (
      len(INT_CAMS_NEW), len(FRIG_CNT), len(FRIG) - len(FRIG_CNT), len(BIN), HOLD_INTERIOR_S, BLE_CANCEL_ON, XVAL_ON,
      DIVERGENCE_DOWNGRADE))
P()
# face sensors per Frigate camera device (registry device join)
FACE = {}
for c in FRIG_CNT:
    fl = [x["entity_id"] for x in ENT_BY_DEV[c.device_id]
          if x["entity_id"].startswith("sensor.") and strip_n(x["entity_id"].split(".", 1)[1]).endswith("_last_recognized_face")]
    FACE[c.eid] = fl
IDENT_SENSOR = "sensor.universal_room_automation_identified_persons_in_house"
UNID_SENSOR = "sensor.universal_room_automation_unidentified_persons_in_house"
ZONE_STATUS = ["sensor.zone_%s_presence_status" % re.sub(r"[^a-z0-9]+", "_", z.lower()).strip("_") for z in indoor]

# samples = census_snapshots house rows in window
iso_lo = datetime.fromtimestamp(T0, timezone.utc).isoformat()
iso_hi = datetime.fromtimestamp(T1, timezone.utc).isoformat()
SNAP = []
for ts, ident, unid, total, fc, uc in URAC.execute(
        "select timestamp,identified_count,unidentified_count,total_persons,frigate_count,unifi_count from census_snapshots "
        "where zone='house' and timestamp>=? and timestamp<=? order by timestamp", (iso_lo, iso_hi)):
    SNAP.append((parse_iso(ts), ident, unid, total, fc, uc))
log("snapshots", len(SNAP))


def int_state(v):
    try:
        return int(float(v))
    except Exception:
        return None


class Hold:
    """_apply_hold_decay replica (camera_census.py:6064), house zone."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.peak = 0
        self.peak_ts = None
        self.pend = 0
        self.pend_since = None

    def step(self, fresh, now):
        hs = HOLD_INTERIOR_S
        if self.peak_ts is None:
            self.peak, self.peak_ts = fresh, now
            self.pend, self.pend_since = 0, None
            return fresh
        if fresh > self.peak:
            if self.pend_since is None or fresh > self.pend:
                self.pend, self.pend_since = fresh, now
                if now - self.peak_ts < hs:
                    return self.peak
                self.pend, self.pend_since = 0, None
            else:
                if now - self.pend_since >= PEAK_SUSTAIN_S:
                    self.peak, self.peak_ts = self.pend, now
                    self.pend, self.pend_since = 0, None
                    return self.peak
                if now - self.peak_ts < hs:
                    return self.peak
                self.pend, self.pend_since = 0, None
        elif fresh == self.peak:
            self.pend, self.pend_since = 0, None
            return fresh
        else:
            if self.pend_since is not None and fresh < self.pend:
                self.pend, self.pend_since = 0, None
        if now - self.peak_ts < hs:
            return self.peak
        self.peak, self.peak_ts = fresh, now
        return fresh


def count_reading(c, t, held):
    """_get_sensor_int with the S2 dead-hold: unavailable keeps the last reading up to the cap, then missing."""
    s = hist(c.count_sensor)
    v = s.at(t)
    if v is None:
        return None
    if v in ("unavailable", "unknown"):
        st = s.since(t)
        last = held.get(c.eid)
        if last is not None and t - st <= STREAM_DEAD_HOLD_MAX_S:
            return last
        return None
    n = int_state(v)
    if n is None:
        return None
    held[c.eid] = n
    return n


def binary_reading(c, t, held):
    s = hist(c.eid)
    v = s.at(t)
    if v is None:
        return None
    if v in ("unavailable", "unknown"):
        st = s.since(t)
        last = held.get(c.eid)
        if last is not None and t - st <= STREAM_DEAD_HOLD_MAX_S:
            return last
        return None
    held[c.eid] = 1 if v == "on" else 0
    return held[c.eid]


def face_fresh(c, t):
    for fe in FACE.get(c.eid, []):
        s = hist(fe)
        v = s.at(t)
        if v is None:
            continue
        if v.strip().lower() in UNUSABLE:
            continue
        ch = s.since(t)
        return ch is not None and (t - ch) <= FACE_WINDOW_S
    return False


def ble_by_area_at(t):
    out = defaultdict(int)
    for s in PERSON_SLUGS:
        if s in LOC_SENSOR:
            a = ble_area_of(s, t)
            if a:
                out[a] += 1
    return out


def ble_nonempty(t):
    for s in PERSON_SLUGS:
        if s in LOC_SENSOR:
            loc = hist(LOC_SENSOR[s]).at(t)
            if loc and loc.lower() not in ("away", "unknown", "", "unavailable"):
                return True
    return False


class Variant:
    def __init__(self, name, cams, use_area, cancel):
        self.name, self.cams, self.use_area, self.cancel = name, cams, use_area, cancel
        self.hold = Hold()
        self.held = {}
        self.res = {}  # t -> dict


def area_of_variant(v, c):
    return c.area if v.use_area else None


def evaluate(v, t, ident, ble_area, zone_occ, ble_any, stuck_discounted=()):
    """one census evaluation for variant v at instant t. returns dict."""
    contribs = []
    frig_contribs, bin_contribs = [], []
    raw_f = raw_b = 0
    frig_avail = bin_avail = False
    for c in v.cams:
        a = area_of_variant(v, c)
        if c.platform == "frigate":
            if c.count_sensor:
                n = count_reading(c, t, v.held)
                if n is None:
                    continue
                frig_avail = True
                if c.eid in stuck_discounted:
                    pass
                else:
                    raw_f += n
                    if n > 0:
                        frig_contribs.append((a, n))
                # unrecognized path
                if n > 0:
                    if face_fresh(c, t):
                        rc = max(0, n - 1)
                    else:
                        rc = n
                    if rc > 0:
                        contribs.append((a, rc))
            else:
                b = binary_reading(c, t, v.held)
                if b is None:
                    continue
                frig_avail = True
                if b:
                    raw_f += 1
                    frig_contribs.append((a, 1))
        else:
            b = binary_reading(c, t, v.held)
            if b is None:
                continue
            bin_avail = True
            if b:
                raw_b += 1
                bin_contribs.append((a, 1))

    def dedup(lst):
        am, un = {}, []
        for a, n in lst:
            if n <= 0:
                continue
            if a:
                am[a] = max(am.get(a, 0), n)
            else:
                un.append(n)
        return sum(am.values()) + sum(un)

    ftot, btot = dedup(frig_contribs), dedup(bin_contribs)
    # unrecognized: per-area max, BLE cancel
    area_max, un = {}, []
    for a, n in contribs:
        if a:
            area_max[a] = max(area_max.get(a, 0), n)
        else:
            un.append(n)
    pre_cancel = sum(area_max.values()) + sum(un)
    cancelled = 0
    area_contrib = {}
    for a, mx in area_max.items():
        corr = min(mx, ble_area.get(a, 0)) if (v.cancel and BLE_CANCEL_ON) else 0
        cancelled += corr
        if mx - corr > 0:
            area_contrib[a] = mx - corr
    camera_unrec = sum(area_contrib.values()) + sum(un)
    held_unid = v.hold.step(camera_unrec, t)
    ceiling = max(pre_cancel, ident)
    clamped_total = min(ident + held_unid, ceiling)
    unid = max(0, clamped_total - ident)
    # camera total (raw, cross-validated)
    if XVAL_ON:
        if frig_avail and bin_avail:
            if ftot == 0 and btot == 0:
                ct = 0
            elif ftot > 0 and btot > 0:
                ct = ftot
            else:
                corro = ble_any or zone_occ
                if not corro and DIVERGENCE_DOWNGRADE:
                    ct = min(ftot, btot)
                else:
                    ct = max(ftot, btot)
        elif frig_avail:
            ct = ftot
        elif bin_avail:
            ct = btot
        else:
            ct = 0
    else:
        ct = ftot
    return dict(unid=unid, camera_unrec=camera_unrec, pre_cancel=pre_cancel, cancelled=cancelled, ftot=ftot,
                btot=btot, ct=ct, areas=dict(area_contrib), amax=dict(area_max))


# watchdog (stuck) replica for V3 -------------------------------------------------------------
class Stuck:
    def __init__(self, cams):
        self.cams = [c for c in cams if c.platform == "frigate" and c.count_sensor]
        self.state = {}
        self.discounted = set()
        self.diag = []
        self.interior_areas = {r.area for r in ROOMS if r.area}

    def step(self, t, ble_area, room_tier_area):
        now_disc = set()
        for c in self.cams:
            v = hist(c.count_sensor).at(t)
            if v is None or v in ("unavailable", "unknown"):
                self.state.pop(c.eid, None)
                continue
            n = int_state(v)
            if n is None:
                self.state.pop(c.eid, None)
                continue
            if n <= 0:
                self.state.pop(c.eid, None)
                continue
            rec = self.state.get(c.eid)
            if rec is None:
                self.state[c.eid] = dict(since=t, last=n, nz=t)
                continue
            if rec["last"] != n:
                rec["since"], rec["last"] = t, n
            hrs = (t - rec["since"]) / 3600.0
            nzh = (t - rec["nz"]) / 3600.0
            if not (hrs >= STUCK_HOURS or nzh >= STUCK_NEVERZERO_HOURS):
                continue
            a = c.area
            corro = int((ble_area.get(a, 0) > 0) if a else False) + int((room_tier_area.get(a, 0) > 0) if a else False)
            if corro >= 1:
                rec["nz"] = t
                continue
            if a and a in self.interior_areas:
                now_disc.add(c.eid)
        self.discounted = now_disc


room_occ_series = {r.area: [] for r in ROOMS if r.area}
for r in ROOMS:
    if r.area and r.occupied_eid:
        room_occ_series[r.area].append(hist(r.occupied_eid))


def room_tier_at(t):
    out = {}
    for a, ss in room_occ_series.items():
        out[a] = sum(1 for s in ss if s.at(t) == "on")
    return out


VAR = {
    "V0": Variant("(i) null areas (today)", INT_CAMS_OLD, False, True),
    "V1": Variant("(ii) device areas, per-area max", INT_CAMS_NEW, True, False),
    "V2": Variant("(iii) (ii) + BLE cancel", INT_CAMS_NEW, True, True),
    "V3": Variant("(iv) (iii) + stuck discount", INT_CAMS_NEW, True, True),
}
STK = Stuck(INT_CAMS_NEW)
unid_rec = hist(UNID_SENSOR)
ident_rec = hist(IDENT_SENSOR)
SAMP = {}  # snapshot index -> per variant result at the snapshot's exact timestamp
log("building evaluation instants")
EVT = set(float(x) for x in range(int(T0), int(T1) + 1, 5))
for c in INT_CAMS_OLD:
    for eid in (c.eid, c.count_sensor):
        if eid:
            EVT.update(t_ for t_, _ in hist(eid).changes())
for fl in FACE.values():
    for fe in fl:
        EVT.update(t_ for t_, _ in hist(fe).changes())
for ls in LOC_SENSOR.values():
    EVT.update(t_ for t_, _ in hist(ls).changes())
for z_ in ZONE_STATUS:
    EVT.update(t_ for t_, _ in hist(z_).changes())
EVT.update(float(sn[0]) for sn in SNAP)
EVT.add(float(T0))
EVTS = sorted(x for x in EVT if T0 <= x <= T1)
SNAP_AT = {float(sn[0]): i for i, sn in enumerate(SNAP)}
log("replaying", len(EVTS), "instants")
zs = [hist(z) for z in ZONE_STATUS]
prev_restart = None
last_stuck = -1e18
viol = {"V1": [], "V2": []}
viol_ct = {"V1": [], "V2": []}
n_eval = 0
stuck_hits = defaultdict(list)
for t in EVTS:
    idv = ident_rec.at(t)
    ident = int_state(idv) if idv not in (None, "unavailable", "unknown") else 0
    if t in SNAP_AT:
        ident = SNAP[SNAP_AT[t]][1]
    uv = unid_rec.at(t)
    if uv in ("unavailable", "unknown", None):
        if prev_restart is not True:
            for vv in VAR.values():
                vv.hold.reset()
                vv.held.clear()
            STK.state.clear()
        prev_restart = True
    else:
        prev_restart = False
    ba = ble_by_area_at(t)
    bany = ble_nonempty(t)
    zocc = any(z.at(t) == "occupied" for z in zs)
    if t - last_stuck >= 30:
        STK.step(t, ba, room_tier_at(t))
        last_stuck = t
        for eid in STK.discounted:
            stuck_hits[eid].append(t)
    n_eval += 1
    for k, vv in VAR.items():
        disc = STK.discounted if k == "V3" else ()
        vv.last = evaluate(vv, t, ident, ba, zocc, bany, disc)
    v0 = VAR["V0"].last
    for k in ("V1", "V2"):
        vk = VAR[k].last
        if vk["camera_unrec"] > v0["camera_unrec"] or vk["pre_cancel"] > v0["pre_cancel"]:
            viol[k].append((t, v0["camera_unrec"], vk["camera_unrec"]))
        if vk["ct"] > v0["ct"]:
            viol_ct[k].append((t, v0["ct"], vk["ct"]))
    if t in SNAP_AT:
        i = SNAP_AT[t]
        SAMP[i] = {k: dict(vv.last) for k, vv in VAR.items()}
        SAMP[i]["ident"] = ident
        SAMP[i]["areas_ble"] = dict(ba)
log("replay done")

# self-check (i) vs recorded -----------------------------------------------------------------
n_all = len(SNAP)
match = match_active = n_active = 0
match_tol = 0
match_f = match_u = 0
mism = []
for i, s in enumerate(SNAP):
    if i not in SAMP:
        continue
    st, ident_r, unid_r, total_r, fc_r, uc_r = s
    v0 = SAMP[i]["V0"]
    ok = v0["unid"] == unid_r
    match += ok
    active = (unid_r > 0) or (v0["unid"] > 0)
    if active:
        n_active += 1
        match_active += ok
    # tolerance: replay within +-60 s reaches the recorded value
    match_f += (v0["ftot"] == fc_r)
    match_u += (v0["btot"] == uc_r)
    if not ok and len(mism) < 400:
        mism.append((st, unid_r, v0["unid"], v0["camera_unrec"], v0["pre_cancel"], SAMP[i]["ident"], ident_r))
P("### Self-check: today's semantics replayed against the recorded rows")
P()
P("Samples = every `census_snapshots` row (`zone='house'`) in the window (%d rows; one per ~60-90 s). Replay = variant (i) "
  "(null areas), evaluated at every input change plus a %d s grid and at each row's exact timestamp, with the real hold/decay machine (`camera_census.py:6064`, hold %d s, sustain %d s), the clamp "
  "against the recorded `identified_persons_in_house` (identity inputs are not replayed: BLE/face/egress-face are folded in by "
  "that recorded value), BLE-by-area from the recorded `sensor.universal_room_automation_<p>_location`, face freshness from "
  "the recorded face sensors." % (n_all, GRID, HOLD_INTERIOR_S, PEAK_SUSTAIN_S))
P()
rate = 100.0 * match / n_all if n_all else 0
rate_a = 100.0 * match_active / n_active if n_active else 100.0
P("- `unidentified_count` replay equals recorded on **%d / %d samples = %.2f%%** (gate: >= 99%%) -> **%s**." % (
    match, n_all, rate, "PASS" if rate >= 99.0 else "FAIL"))
P("- Restricted to the %d samples where either side is > 0 (idle minutes dominate the all-sample rate): %d / %d = %.1f%%." % (
    n_active, match_active, n_active, rate_a))
P("- Raw dedup totals: Frigate total equals recorded `frigate_count` on %.2f%% of samples, binary-platform total equals "
  "recorded `unifi_count` on %.2f%%." % (100.0 * match_f / n_all if n_all else 0, 100.0 * match_u / n_all if n_all else 0))
P()
if mism:
    P("First mismatches (CST, recorded unid, replay unid, replay camera_unrecognized, replay pre-cancel, replay identified, "
      "recorded identified):")
    P()
    table(["t", "rec unid", "replay unid", "camera_unrec", "pre_cancel", "replay ident", "rec ident"],
          [(fmt(m[0], True),) + tuple(m[1:]) for m in mism[:12]])

# per-day deltas -------------------------------------------------------------------------------
P("### Variant comparison (per census sample; 11-14 is the party)")
P()
day = defaultdict(lambda: defaultdict(int))
dist = {k: Counter() for k in ("V1", "V2", "V3")}
cross0 = {k: [] for k in ("V1", "V2", "V3")}
raise_ct = {k: 0 for k in ("V1", "V2", "V3")}
ct_raise = {k: 0 for k in ("V1", "V2", "V3")}
for i, s in enumerate(SNAP):
    if i not in SAMP:
        continue
    d = fmt(s[0])[:5]
    v0 = SAMP[i]["V0"]
    day[d]["n"] += 1
    for k in ("V1", "V2", "V3"):
        vk = SAMP[i][k]
        delta = vk["unid"] - v0["unid"]
        dist[k][delta] += 1
        if delta != 0:
            day[d][k + "_diff"] += 1
        if delta > 0:
            raise_ct[k] += 1
        if vk["ct"] > v0["ct"]:
            ct_raise[k] += 1
        if v0["unid"] > 0 and vk["unid"] == 0:
            day[d][k + "_cross0"] += 1
            cross0[k].append((s[0], i))
    if v0["unid"] > 0:
        day[d]["rec_pos"] += 1
rows = []
for d in sorted(day):
    x = day[d]
    rows.append((d, x["n"], x["rec_pos"], x["V1_diff"], x["V2_diff"], x["V3_diff"], x["V1_cross0"], x["V2_cross0"]))
table(["day", "samples", "unid>0 today", "(ii) differs", "(iii) differs", "(iv) differs", "(ii) crosses to 0", "(iii) crosses to 0"], rows)
P("Delta distribution (variant minus today, over all samples): " + "; ".join(
    "%s: %s" % ({"V1": "(ii)", "V2": "(iii)", "V3": "(iv)"}[k], dict(sorted(dist[k].items()))) for k in dist))
P()
P("**INV-CENSUS-DOWN check (plan D0 discriminating criterion).** The invariant is stated over an evidence STATE S "
  "(before the stateful hold/decay machine), so it is tested two ways. (A) Stateless: at each of the %d evaluation instants "
  "(every input change + %d s grid), variant (ii)/(iii) `camera_unrecognized`/pre-cancel vs today's: violations (ii) %d, (iii) %d; "
  "raw camera body total violations (ii) %d, (iii) %d. (B) Through the hold/decay machine, per census sample: samples where the "
  "variant's `unidentified_count` exceeds today's: (ii) %d, (iii) %d, (iv) %d; camera total exceeds: (ii) %d, (iii) %d, (iv) %d." % (
      n_eval, GRID, len(viol["V1"]), len(viol["V2"]), len(viol_ct["V1"]), len(viol_ct["V2"]),
      raise_ct["V1"], raise_ct["V2"], raise_ct["V3"], ct_raise["V1"], ct_raise["V2"], ct_raise["V3"]))
P()
if viol["V1"] or viol["V2"] or viol_ct["V1"] or viol_ct["V2"]:
    P("**Stateless INV-CENSUS-DOWN is FALSE on this window: stop and re-plan D4.** First violations: %s" % (
        "; ".join("%s (today %s, variant %s)" % (fmt(x[0], True), x[1], x[2]) for x in (viol["V1"] + viol["V2"] + viol_ct["V1"] + viol_ct["V2"])[:5])))
else:
    P("**Stateless INV-CENSUS-DOWN holds on this window (0 violations): per-area max and BLE cancel never raised the evidence-state "
      "count or the body total.**")
P()
raised = [(i, k) for k in ("V1", "V2", "V3") for i in SAMP if SAMP[i][k]["unid"] > SAMP[i]["V0"]["unid"]]
if raised:
    P("Samples where the stateful `unidentified_count` exceeded today's (hold/decay path dependence, NOT a count of more bodies):")
    P()
    rr = []
    for i, k in raised[:12]:
        sn = SNAP[i]
        rr.append((fmt(sn[0], True), k, SAMP[i]["V0"]["unid"], SAMP[i][k]["unid"], SAMP[i]["V0"]["camera_unrec"], SAMP[i][k]["camera_unrec"],
                   SAMP[i]["V0"]["pre_cancel"], SAMP[i][k]["pre_cancel"], sn[2]))
    table(["t", "variant", "today unid", "variant unid", "today camera_unrec", "variant camera_unrec", "today pre_cancel",
           "variant pre_cancel", "recorded unid"], rr)
# camera total (raw) delta
ctd = Counter()
for i in SAMP:
    ctd[SAMP[i]["V2"]["ct"] - SAMP[i]["V0"]["ct"]] += 1
P("Camera body total (raw census, `_cross_validate_platforms`) delta (iii) minus today: %s." % dict(sorted(ctd.items())))
P()
# 11-14 hour by hour
P("### 11-14 (the party) hour by hour")
P()
hr = defaultdict(lambda: defaultdict(int))
for i, s in enumerate(SNAP):
    if i not in SAMP:
        continue
    dt_ = datetime.fromtimestamp(s[0], LOC)
    if dt_.strftime("%m-%d") != "11-14":
        continue
    h = dt_.hour
    v0 = SAMP[i]["V0"]
    hr[h]["n"] += 1
    hr[h]["rec"] += s[2] > 0
    hr[h]["recmax"] = max(hr[h]["recmax"], s[2])
    hr[h]["V0max"] = max(hr[h]["V0max"], v0["unid"])
    for k in ("V1", "V2", "V3"):
        vk = SAMP[i][k]
        hr[h][k + "pos"] += vk["unid"] > 0
        hr[h][k + "max"] = max(hr[h][k + "max"], vk["unid"])
    hr[h]["ct0"] = max(hr[h]["ct0"], v0["ct"])
    hr[h]["ct2"] = max(hr[h]["ct2"], SAMP[i]["V2"]["ct"])
    hr[h]["id"] = max(hr[h]["id"], SAMP[i]["ident"])
rows = []
for h in sorted(hr):
    x = hr[h]
    rows.append(("%02d:00" % h, x["n"], x["recmax"], x["rec"], x["V0max"], x["V1max"], x["V1pos"], x["V2max"], x["V2pos"],
                 x["V3max"], x["id"], x["ct0"], x["ct2"]))
table(["hour (CST)", "samples", "recorded unid max", "recorded unid>0 samples", "replay (i) max", "(ii) max", "(ii) >0 samples",
       "(iii) max", "(iii) >0 samples", "(iv) max", "identified (recorded) max", "camera total today max", "camera total (iii) max"], rows)

# oracle (4): operator head count for 11-14 (Q6 answered: high-water 14-15, no time given; census peak 10 at 16:26/16:43; busy 16:00-19:00)
d14 = datetime.strptime("2026-11-14", "%Y-%m-%d").replace(tzinfo=LOC).timestamp()
pk = {}
for i, sn in enumerate(SNAP):
    if not (d14 <= sn[0] < d14 + 86400) or i not in SAMP:
        continue
    cand = {"recorded": (sn[3], sn[0])}
    for k in ("V0", "V1", "V2", "V3"):
        cand[k] = (SAMP[i]["ident"] + SAMP[i][k]["unid"], sn[0])
    for k2 in ("V0", "V1", "V2", "V3"):
        cand["cam_" + k2] = (SAMP[i][k2]["ct"], sn[0])
    for k2, v2 in cand.items():
        if k2 not in pk or v2[0] > pk[k2][0]:
            pk[k2] = v2
lowered = lowered_busy = busy_n = 0
for i, sn in enumerate(SNAP):
    if not (d14 + 16 * 3600 <= sn[0] < d14 + 19 * 3600) or i not in SAMP:
        continue
    busy_n += 1
    t0_ = SAMP[i]["ident"] + SAMP[i]["V0"]["unid"]
    t2_ = SAMP[i]["ident"] + SAMP[i]["V2"]["unid"]
    if t2_ < t0_:
        lowered_busy += 1
P("### Oracle (4): 11-14 head count (Q6 answered by the operator)")
P()
P("Ground truth: party high-water mark **14 to 15 people**, no time given; recorded census peak 10 at 16:26 and 16:43; busy window about "
  "16:00 to 19:00. Peak of each quantity over the whole of 11-14 (CST), person total = identified + unidentified:")
P()
lab = {"recorded": "recorded `total_persons`", "V0": "(i) today, replayed", "V1": "(ii) device areas, per-area max",
       "V2": "(iii) + BLE cancel (CORRECT)", "V3": "(iv) + stuck discount",
       "cam_V0": "raw camera body total (i)", "cam_V1": "raw camera body total (ii)", "cam_V2": "raw camera body total (iii)",
       "cam_V3": "raw camera body total (iv)"}
table(["semantics", "11-14 peak", "at (CST)", "short of 14", "short of 15"],
      [(lab[k], pk[k][0], fmt(pk[k][1], True), 14 - pk[k][0], 15 - pk[k][0]) for k in lab if k in pk])
P("Within 16:00-19:00 (%d samples) CORRECT (iii) reads a lower person total than today on %d samples." % (busy_n, lowered_busy))
P()
P("Reading: today's summing census already sits 4-5 below the operator's count at the peak; any semantics that can only lower the "
  "count (per-area max, BLE cancel) cannot close that gap. Whether CORRECT's removed double counts outweigh a lost real person is read "
  "from the table above: compare the (iii) peak with today's.")
P()
# contradicted-zero table ----------------------------------------------------------------------
log("contradicted")
P("### Contradicted-zero table (the D4 gate input)")
P()
P("Population: every sample where variant (ii) or (iii) reads `unidentified_count` 0 while (i) read > 0 (the minutes the "
  "change would remove). Oracles per plan D0 (d): **(1)** a `person.*` whose trust state (recorded `person.<x>` state; the "
  "BLE-overrule refinement of `person_state_for_trust` is not recorded) is `home` with no BLE room in the camera's area and no "
  "fresh face; **(2)** a door-crossing entry in the prior 2 h with no later exit (`person_entry_exit_events`); **(3)** a Tier-1 "
  "sensor `on` in the camera's area with no BLE person there; **(4)** 11-14 operator head counts: **PENDING (Q6 unanswered), source not evaluated**. "
  "A minute is CONTRADICTED if any of (1)-(3) holds.")
P()
PERSON_ENT = {s: "person.%s" % s for s in PERSON_SLUGS}
ent_ev = URAC.execute("select timestamp,person_id,direction from person_entry_exit_events where timestamp>=? and event_type='egress' "
                      "order by timestamp", ((datetime.fromtimestamp(T0 - 3 * 3600, timezone.utc)).strftime("%Y-%m-%dT%H:%M:%S"),)).fetchall()
EV = [(parse_iso(a), b, c) for a, b, c in ent_ev]


def face_fresh_person(slug, t):
    first = slug.split("_")[0]
    for fe_list in FACE.values():
        for fe in fe_list:
            s = hist(fe)
            v = s.at(t)
            if v is None or v.strip().lower() in UNUSABLE:
                continue
            if v.strip().lower() == first and (t - (s.since(t) or 0)) <= FACE_WINDOW_S:
                return True
    return False


def eval_oracles(t, cams_areas, refined_out=None):
    o1 = o2 = o3 = False
    detail = []
    for slug, ent in PERSON_ENT.items():
        st = hist(ent).at(t)
        if st == "home":
            bl = ble_area_of(slug, t)
            if not (bl and bl in cams_areas) and not face_fresh_person(slug, t):
                o1 = True
                detail.append("p:" + slug)
                break
    # (2) entry in prior 2 h with no later exit by same person or unattributed
    ents = [(tt, p) for tt, p, d in EV if d == "entry" and t - 7200 <= tt <= t]
    located_here = {s_ for s_ in PERSON_SLUGS if s_ in LOC_SENSOR and ble_area_of(s_, t) in cams_areas}
    for tt, p in ents:
        later_exit = any(d == "exit" and tt < t2 <= t and (p is None or p2 == p or p2 is None)
                         for t2, p2, d in EV)
        if not later_exit:
            o2 = True
            detail.append("entry:" + (p or "?"))
            # refinement (2'): the entry is explained when it names the resident BLE-located in the camera area
            if refined_out is not None and (p is None or p not in located_here):
                refined_out.append("entry:" + (p or "unattributed"))
            break
    # (3) tier-1 on in camera area, no BLE person there
    for a in cams_areas:
        for r in ROOM_BY_AREA.get(a, []):
            if any(hist(sn).at(t) == "on" for sn in r.sensors):
                if not any(ble_area_of(s, t) == a for s in PERSON_SLUGS if s in LOC_SENSOR):
                    o3 = True
                    detail.append("t1:" + r.title)
    return o1, o2, o3, detail


rows = []
contra = {"V1": 0, "V2": 0}
contra_by_src = {"V1": Counter(), "V2": Counter()}
contra_refined_explained = {"V1": 0, "V2": 0}
listing = []
for k in ("V1", "V2"):
    for tt, i in cross0[k]:
        t_g = float(tt)
        cams_areas = {c.area for c in INT_CAMS_NEW if c.platform == "frigate" and c.count_sensor and c.area
                      and (int_state(hist(c.count_sensor).at(t_g)) or 0) > 0}
        ref_ = []
        o1, o2, o3, det = eval_oracles(t_g, cams_areas, ref_)
        if o2 and not ref_:
            contra_refined_explained[k] += 1
        bl = {s_: ble_loc_name(s_, t_g) for s_ in PERSON_SLUGS if s_ in LOC_SENSOR}
        if o1 or o2 or o3:
            contra[k] += 1
        for nm_, f in (("(1)", o1), ("(2)", o2), ("(3)", o3)):
            if f:
                contra_by_src[k][nm_] += 1
        listing.append((fmt(tt, True), k, ",".join(sorted(area_name(a_) for a_ in cams_areas)),
                        SAMP[i]["V0"]["unid"], SAMP[i]["ident"],
                        ", ".join("%s@%s" % (a_, b_) for a_, b_ in bl.items() if b_) or "none located",
                        "(1)" if o1 else "", "(2)" if o2 else "", "(3)" if o3 else "", ";".join(det)))
table(["variant", "samples crossing to 0", "CONTRADICTED samples", "by oracle (1)/(2)/(3)", "oracle (4) party counts"],
      [("(ii) device areas", len(cross0["V1"]), contra["V1"], dict(contra_by_src["V1"]) or "-", "PENDING (Q6)"),
       ("(iii) + BLE cancel", len(cross0["V2"]), contra["V2"], dict(contra_by_src["V2"]) or "-", "PENDING (Q6)")])
if listing:
    P("Every crossing sample (CST; BLE-located residents at that instant; oracle flags):")
    P()
    table(["t", "variant", "camera areas > 0", "today unid", "identified", "BLE located", "(1)", "(2)", "(3)", "detail"], listing)
GATE_ZERO_CROSS = len(cross0["V1"]) + len(cross0["V2"])
P("Oracle (2) refinement (reported separately, NOT the plan's rule): an entry whose `person_id` is the resident who is BLE-located in "
  "the camera area is explained by that resident, not an uncounted person. Contradicted samples whose only flag was such an explained "
  "entry: (ii) %d, (iii) %d." % (contra_refined_explained["V1"], contra_refined_explained["V2"]))
P()
P("Gate reading (sources 1-3): crossing minutes total = %d; contradicted = %d (ii) + %d (iii). %s" % (
    GATE_ZERO_CROSS, contra["V1"], contra["V2"],
    "-> **0 contradicted: KEEP/CORRECT gate passes on sources 1-3.**" if (contra["V1"] + contra["V2"]) == 0 else
    "-> **contradicted > 0: the hard gate FAILS on sources 1-3 (threshold 0, no tolerance) => D4-KEEP.**"))
P()

# hidden second person table ---------------------------------------------------------------------
log("hidden second")
P("### Hidden-second-person table (area max below the sum across DIFFERENT physical cameras)")
P()


def twin_groups():
    cam_devs = {}
    for d in DEV:
        cams = [x for x in ENT_BY_DEV[d] if x["entity_id"].startswith("camera.") and not x.get("disabled_by")]
        if cams:
            cam_devs[d] = cams
    key = defaultdict(list)
    for d, cams in cam_devs.items():
        nm = re.sub(r"[^a-z0-9]", "", dev_name(d).lower())
        key[((DEV[d].get("area_id") or ""), nm)].append(d)
    groups = {}
    for (ar, nm), ds in key.items():
        plats = {d: {x["platform"] for x in cam_devs[d]} for d in ds}
        frig = [d for d in ds if plats[d] == {"frigate"}]
        sib = [d for d in ds if plats[d] and plats[d] <= NVR_TWIN_PLATFORMS]
        if frig and sib:
            g = frozenset(frig + sib)
            for d in g:
                groups[d] = g
    return groups


TW = twin_groups()


def physical(c):
    g = TW.get(c.device_id)
    return tuple(sorted(g)) if g else (c.device_id,)


by_area_phys = defaultdict(set)
for c in INT_CAMS_NEW:
    if c.area:
        by_area_phys[c.area].add(physical(c))
rows_multi = [(area_name(a), len(p)) for a, p in by_area_phys.items() if len(p) >= 2]
P("Interior census sensors grouped by area (NEW rule) and physical camera (W1 twin collapse approximated by registry device "
  "area + device name + NVR-platform check, see header). Areas with >= 2 distinct physical interior cameras: %s." % (
      ", ".join("%s (%d)" % x for x in rows_multi) or "**none**"))
P()
P("Physical cameras per area: " + "; ".join(
    "%s = %d (%s)" % (area_name(a), len(p), ", ".join(sorted({short(c.eid) for c in INT_CAMS_NEW if c.area == a})))
    for a, p in sorted(by_area_phys.items())))
P()
hidden_rows = []
if rows_multi:
    for a, nph in rows_multi:
        phys = sorted(by_area_phys[a])
        mc = 0
        mins_hidden = 0
        for tt in range(T0, T1, 30):
            vals = []
            for pg in phys:
                best = 0
                for c in INT_CAMS_NEW:
                    if c.area == a and physical(c) == pg:
                        if c.platform == "frigate" and c.count_sensor:
                            n = int_state(hist(c.count_sensor).at(tt)) or 0
                        else:
                            n = 1 if hist(c.eid).at(tt) == "on" else 0
                        best = max(best, n)
                vals.append(best)
            if sum(1 for v in vals if v >= 1) >= 2 and max(vals) < sum(vals):
                mins_hidden += 30
        hidden_rows.append((area_name(a), nph, mins(mins_hidden)))
    table(["area", "physical cameras", "minutes two cameras each read >=1 and max < sum"], hidden_rows)
else:
    P("Result: with the NEW map no area holds two distinct physical interior cameras, so per-area max can only collapse a "
      "camera's own two NVR legs (Frigate + Protect twins). The residual that does exist is within one camera (its own count), "
      "which per-area max does not change. Table empty.")
    P()
# twin groups listing
P("W1 twin groups used (device names): " + "; ".join(sorted(" + ".join(sorted(dev_name(d) for d in g)) for g in set(TW.values()))) or "none")
P()

# ===================== (g) =====================
log("section g")
P("## (g) 3b Wr / U changes")
P()
P("Definitions: Wr = devices of every enabled room's configured motion/presence/occupancy inputs plus the camera manager's area "
  "lookup (`camera_stream_health.room_stream_input_entities`, `camera_twin_health.py:~520`); U = (census interior person sensors "
  "UNION zone-tier registered cameras UNION `zone_cameras` picks) whose camera device is not in Wr.")
P()
P("| | Wr (devices) | U (entities) |")
P("|---|---|---|")
P("| OLD (self-checked) | %d | %d |" % (len(WR_OLD), len(U_OLD)))
P("| NEW (D1 + D3a' zone registrations) | %d | %d |" % (len(WR_NEW), len(U_NEW)))
P()
P("NEW Wr devices: %s." % ", ".join(sorted(dev_name(d) for d in WR_NEW)))
P()
P("NEW U (%d): %s." % (len(U_NEW), ", ".join("`%s`" % short(x) for x in U_NEW) or "none"))
P()
moved = []
for r_title, eid, d in RI_NEW:
    if d not in WR_OLD:
        moved.append((r_title, short(eid), dev_name(d)))
table(["room that gains the input", "input", "camera device"], sorted(set(moved)))
P("Entities leaving U (owner pages become room pages): %s." % (
    ", ".join("`%s`" % short(x) for x in sorted(set(U_OLD) - set(U_NEW))) or "none"))
P()
P("Entities joining U: %s." % (", ".join("`%s`" % short(x) for x in sorted(set(U_NEW) - set(U_OLD))) or "none"))
P()
# per room extras
rows = []
for r in ROOMS:
    ex = [x for x in get_person_sensor_for_area(AMAP_NEW, r.area) if x not in r.sensors]
    if ex:
        rows.append((r.title, ", ".join("`%s`" % short(x) for x in ex)))
P("Rooms whose stream-health watch set gains extras (the room hold lookup, full map incl. egress/perimeter roles):")
P()
table(["room", "extras"], rows)

# ===================== (h) =====================
log("section h")
P("## (h) Stuck-camera discount check")
P()
P("Code: `_watchdog_stuck_cameras` (`camera_census.py:2959`): discount only when `area_id` is set, the area has a URA room, the "
  "stuck window (unchanged %.0f h or never-zero %.0f h) is exceeded and no corroborator (BLE in area, or a room of the area "
  "with motion/presence/occupied) is present. The discount feeds only `_calculate_house_census` (`:2105`, the raw camera total), "
  "NOT `_get_unrecognized_camera_count`, so it can lower the camera body total / ledger input but never `unidentified_count` "
  "(grep `_watchdog_discounted_cameras`: set at `:1510/:1818/:2982/:3144`, read only at `:2105`)." % (STUCK_HOURS, STUCK_NEVERZERO_HOURS))
P()
cam_nm = []
for ts, cj in URAC.execute("select timestamp,context_json from anomaly_log where metric_name='camera_stuck' order by id"):
    try:
        j = json.loads(cj)["extra"]
        key = j.get("key") or []
        cam_nm.append((parse_iso(ts), key[0] if key else "?", key[1] if len(key) > 1 else "?", j.get("diagnosis", "")))
    except Exception:
        pass
in_win = [x for x in cam_nm if T0 <= x[0] <= T1]
P("`camera_stuck` NMs in the URA DB (`anomaly_log`, metric `camera_stuck`): %d total since %s, **%d inside the %d-day window** "
  "(latest %s). The recorder window therefore holds no stuck NM; the check below uses the URA DB's own history for every NM "
  "(BLE = `person_visits` open at the NM instant, room signal = `environmental_data.occupied` 5-min samples +-5 min), which is a "
  "weaker oracle than the recorder, and the house state at that instant from `house_state_log`." % (
      len(cam_nm), fmt(min(x[0] for x in cam_nm)) if cam_nm else "-", len(in_win), WINDOW_DAYS,
      fmt(max(x[0] for x in cam_nm)) if cam_nm else "-"))
P()
HSL = URAC.execute("select timestamp,state from house_state_log order by id").fetchall()
HSL_T = [parse_iso(a_) for a_, _ in HSL]


def house_state_at(tt):
    i = bisect.bisect_right(HSL_T, tt) - 1
    return HSL[i][1] if i >= 0 else "?"


rows = []
tally = Counter()
for tt, ent, rule, diag in cam_nm:
    c = CAM_BY_EID_NEW.get(ent)
    area = c.area if c else None
    rooms = ROOM_BY_AREA.get(area, [])
    ble_note = occ_note = "-"
    hs = house_state_at(tt)
    if rooms:
        ts_utc = datetime.fromtimestamp(tt, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        ts_lo = datetime.fromtimestamp(tt - 300, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        ts_hi = datetime.fromtimestamp(tt + 300, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        nvis = 0
        for r in rooms:
            nvis += URAC.execute("select count(*) from person_visits where room_id=? and entry_time<=? and "
                                 "(exit_time is null or exit_time>=?)", (r.room_name, ts_utc, ts_utc)).fetchone()[0]
        nocc = 0
        for r in rooms:
            q = URAC.execute("select max(occupied) from environmental_data where room_id=? and timestamp>=? and timestamp<=?",
                             (r.entry_id, ts_lo, ts_hi)).fetchone()[0]
            nocc += int(bool(q))
        ble_note = "%d open visit(s)" % nvis
        occ_note = "room occupied (+-5 min): %s" % ("yes" if nocc else "no")
        verdict = "corroborated -> NOT discounted" if (nvis or nocc) else "uncorroborated -> WOULD DISCOUNT"
    elif c is None:
        verdict = "camera not in map"
    else:
        verdict = "no URA room on area %s -> notify-only" % area_name(area)
    tally[verdict.split(" ->")[0] if "WOULD" not in verdict else "WOULD DISCOUNT"] += 1
    rows.append((fmt(tt, True), "in window" if T0 <= tt <= T1 else "older", "`%s`" % short(ent), rule, area_name(area),
                 ", ".join(r.title for r in rooms) or "-", hs, ble_note, occ_note, verdict))
table(["NM time (CST)", "recorder", "camera", "rule", "NEW area", "room(s)", "house state at NM", "BLE (person_visits)",
       "room signal (environmental_data)", "verdict under NEW area"], rows)
P("Tally of the %d NMs under the NEW area: %s." % (len(cam_nm), dict(tally)))
P()
wd = [r_ for r_ in rows if "WOULD DISCOUNT" in r_[-1]]
P("The %d would-discount rows by house state at the NM instant: %s; by camera: %s. Still-guest reading: rows in `sleep` / "
  "`home_night` are the ones a motionless person on a motion-class-only room could explain (Rule 1, `SENSOR_FLEET_CLASSES.md`); "
  "rows in `home_day`/`home_evening` with no BLE and no room signal are more likely a real stuck stream." % (
      len(wd), dict(Counter(r_[6] for r_ in wd)), dict(Counter(r_[2] for r_ in wd))))
P()
P("Today every stuck row has `area_id=None` -> `notify_only_reason: no_area_id` (the discount has never applied, so these %d "
  "stuck cameras were never removed from any count). Window replica of the watchdog over the recorded count sensors (3 h unchanged / "
  "6 h never-zero, corroboration = BLE in the area or a room of the area occupied): eligible-and-uncorroborated discount "
  "instants per camera: %s." % (len(cam_nm), "; ".join("`%s` first %s, %d samples of 30 s" % (short(k), fmt(min(v), True), len(v))
                                         for k, v in sorted(stuck_hits.items())) or "none"))
P()
disc_samples = sum(1 for i in SAMP if SAMP[i]["V3"]["ct"] != SAMP[i]["V2"]["ct"])
P("Camera-total samples where the stuck discount changed the value (iv vs iii): %d of %d. The discount feeds only the raw camera "
  "total (`:2105`), never `unidentified_count`." % (disc_samples, len(SAMP)))
P()

DBG = globals().get("DEBUG_RANGE")
if DBG:
    lo = parse_iso(DBG[0] + ":00-06:00") if False else datetime.strptime("2026-" + DBG[0], "%Y-%m-%d %H:%M").replace(tzinfo=LOC).timestamp()
    hi = datetime.strptime("2026-" + DBG[1], "%Y-%m-%d %H:%M").replace(tzinfo=LOC).timestamp()
    P("DEBUG")
    for i, sn in enumerate(SNAP):
        if lo <= sn[0] <= hi:
            P("snap %s rec unid=%s ident=%s total=%s f=%s u=%s | replay %s" % (fmt(sn[0], True), sn[2], sn[1], sn[3], sn[4], sn[5],
              {k: (SAMP[i][k]["unid"], SAMP[i][k]["camera_unrec"], SAMP[i][k]["pre_cancel"]) for k in ("V0",)} if i in SAMP else None))
    tt = int(lo // GRID * GRID)
    while tt <= hi:
        row = []
        for c in FRIG_CNT:
            row.append("%s=%s%s" % (short(c.count_sensor)[:14], hist(c.count_sensor).at(tt), "F" if face_fresh(c, tt) else ""))
        P("grid %s %s | unid_sensor=%s ident_sensor=%s" % (fmt(tt, True), " ".join(row), unid_rec.at(tt), ident_rec.at(tt)))
        tt += 60

# final self-check footer
P("---")
P("Probe self-checks: Wr/U old = %d/%d (%s); (d)(i) unidentified match = %.2f%% (%s)." % (
    SC_WR, SC_U, "PASS" if (SC_WR, SC_U) == (3, 14) else "FAIL", rate, "PASS" if rate >= 99.0 else "FAIL"))

print("\n".join(OUT))
