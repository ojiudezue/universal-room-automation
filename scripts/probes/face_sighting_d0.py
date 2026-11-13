#!/usr/bin/env python3
"""FACE-ARRIVAL-REBUILD-1 (person sightings) D0 -- READ-ONLY probe.

Plan: docs/planning/PLANNING_person_sighting_layer.md rev 11, section 7 (P1-P5, P7 baseline).

    ssh ha "python3 -" < scripts/probes/face_sighting_d0.py

Both DBs are opened `mode=ro`; `.storage` is read only. Nothing is written.

P1  pick resolution: every ZM `zone_cameras` pick -> registry -> (camera-integration
    pick: its device's Frigate face-name sensors plus every Frigate face-name sensor
    whose device shares the pick's camera stem) | (URA fused room pick: the room's
    `room_cameras`, or `room_cameras_empty`). Named face events per pick in the window.
    This is an offline approximation of `CameraResolver.resolve_pick_to_fusions`; the
    live count (`face_sighting_picks_resolved`) is the authority after deploy.
P2  per face entity named events/day; lag person-sensor `on` edge -> name; fraction of
    names landing after the person sensor went `off`; egress events (recorder bus
    `ura_person_egress_event`) per direction with/without person_id, by
    identity_confidence tier; entries with a person_id whose tracker read not_home
    within 300 s before.
P3  interior resident face events on resolved picks: raw tracker state at ts and the
    nearest `-> home` edge -> classes (i) face-before-phone, (ii) away no edge 30 min,
    (iii) home edge before ts (context), (iv) home otherwise. Per person and camera,
    plus the p90 of the (iii) home-edge-to-face lag (capped 300 s).
P4  interior hop lags between the operator's path cameras (person-sensor `on` edges,
    A on -> B on within 120 s): p50/p90 and hops/day, day vs night.
P5  consumer reality from config entries + recorder (toggle, lock switches, HVAC).
P7  baseline replay (7 days): egress entries whose in-window single face slug read
    not_home / a zone at the crossing (would-be arrival candidates), each auto-labelled
    true arrival (non-face home edge within 10 min; 2/5/30 also reported) or
    mis/phoneless (none within 30 min).
"""
import collections
import datetime as dt
import json
import re
import sqlite3
import statistics

DOMAIN = "universal_room_automation"
SENTINELS = {"", "unknown", "none", "unavailable"}
WINDOW_DAYS = 7.5
NIGHT_HOURS = set(range(22, 24)) | set(range(0, 6))
CDT = dt.timezone(dt.timedelta(hours=-6))

r = sqlite3.connect("file:/config/home-assistant_v2.db?mode=ro", uri=True)
u = sqlite3.connect(
    "file:/config/universal_room_automation/data/universal_room_automation.db?mode=ro",
    uri=True,
)
_store = lambda n: json.load(open(f"/config/.storage/{n}"))["data"]  # noqa: E731
ENTRIES = [e for e in _store("core.config_entries")["entries"] if e.get("domain") == DOMAIN]
REG = _store("core.entity_registry")["entities"]
REG_BY_ID = {e["entity_id"]: e for e in REG}


def merged(e):
    return {**(e.get("data") or {}), **(e.get("options") or {})}


NOW = r.execute("select max(last_updated_ts) from states").fetchone()[0]
T0 = NOW - WINDOW_DAYS * 86400


def history(entity_id, t0=T0):
    """[(ts, state)] for an entity, ascending."""
    row = r.execute("select metadata_id from states_meta where entity_id=?", (entity_id,)).fetchone()
    if not row:
        return []
    return [
        (ts, st) for ts, st in r.execute(
            "select last_updated_ts, state from states where metadata_id=? and last_updated_ts>=? "
            "order by last_updated_ts", (row[0], t0))
    ]


def changes(hist):
    out, prev = [], None
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


# ---------------------------------------------------------------- face registry
FACE_SENSORS = {
    e["entity_id"]: e for e in REG
    if e.get("platform") == "frigate" and e["entity_id"].startswith("sensor.")
    and ":sensor_recognized_face:" in str(e.get("unique_id", ""))
}
FACE_BY_DEVICE = collections.defaultdict(list)
for eid, e in FACE_SENSORS.items():
    FACE_BY_DEVICE[e.get("device_id")].append(eid)
_SUFFIX = re.compile(r"_(person_occupancy|person_detected|person|smart_motion_human|camera_person_detected)(_\d+)?$")


def stem_of(entity_id):
    base = entity_id.split(".", 1)[1]
    return _SUFFIX.sub("", base)


def face_base(eid):
    return re.sub(r"_last_recognized_face(_\d+)?$", "", eid.split(".", 1)[1])


def faces_for_camera_entity(eid):
    ent = REG_BY_ID.get(eid) or {}
    out = set(FACE_BY_DEVICE.get(ent.get("device_id"), []))
    stem = stem_of(eid)
    out |= {f for f in FACE_SENSORS if face_base(f) == stem}
    return sorted(out)


def tracked_slugs():
    slugs = set()
    for e in ENTRIES:
        m = merged(e)
        for p in m.get("tracked_persons") or []:
            slugs.add(str(p).split(".", 1)[-1])
    if not slugs:
        slugs = {x[0].split(".", 1)[1] for x in r.execute(
            "select entity_id from states_meta where entity_id like 'person.%'")}
    return sorted(slugs)


TRACKED = tracked_slugs()


def canon(name):
    s = "_".join(str(name).strip().lower().replace("-", " ").split())
    if not s or s in SENTINELS:
        return None
    if s in TRACKED:
        return s
    m = [t for t in TRACKED if t.split("_", 1)[0] == s.split("_", 1)[0]]
    return m[0] if len(m) == 1 else None


print(f"# FACE-ARRIVAL-REBUILD-1 D0 probe  window {WINDOW_DAYS} d  ending "
      f"{dt.datetime.fromtimestamp(NOW, CDT):%Y-%m-%d %H:%M} CST")
print(f"tracked persons: {TRACKED}")

# ---------------------------------------------------------------- P1
ZM = next((merged(e) for e in ENTRIES if merged(e).get("entry_type") == "zone_manager"), {})
ROOMS = {e["entry_id"]: merged(e) for e in ENTRIES if merged(e).get("entry_type") == "room"}
picks = collections.OrderedDict()
for zname, z in (ZM.get("zones") or {}).items():
    for p in z.get("zone_cameras") or []:
        picks.setdefault(p, []).append(zname)
print("\n## P1 pick resolution")
resolved = {}
for pick, zones in picks.items():
    ent = REG_BY_ID.get(pick) or {}
    reason, faces = None, []
    if ent.get("platform") == DOMAIN:
        room = ROOMS.get(ent.get("config_entry_id"))
        if room is None:
            reason = "room_entry_missing"
        else:
            cams = room.get("room_cameras") or []
            if not cams:
                reason = "room_cameras_empty"
            for c in cams:
                faces += faces_for_camera_entity(c)
    else:
        faces = faces_for_camera_entity(pick)
    if not faces and reason is None:
        reason = "no_face_name_source" if ent else "no_fusion"
    named = 0
    for f in faces:
        named += sum(1 for _, s in changes(history(f)) if canon(s))
    resolved[pick] = faces
    print(f"- {pick} zones={sorted(zones)} platform={ent.get('platform')} faces={faces} "
          f"{'UNRESOLVED ' + reason if reason else 'resolved'} resident-named-changes={named}")
n_res = sum(1 for p, f in resolved.items() if f and "garage_a_camera_person_detected" not in p)
print(f"P1 resolved (Garage A excluded): {n_res}/{len(picks)}  go(>=5): {'GO' if n_res >= 5 else 'NO-GO'}")

# ---------------------------------------------------------------- P2 + P3
print("\n## P2 per face entity (resident-named changes/day, lag after person-on edge)")
PERSON_HIST = {s: changes(history(f"person.{s}", T0 - 86400)) for s in TRACKED}
p3 = collections.Counter()
p3_by = collections.Counter()
iii_lags = []
for pick, faces in resolved.items():
    person_hist = changes(history(pick))
    on_edges = [t for t, s in person_hist if s == "on"]
    for f in faces:
        ev = [(t, canon(s)) for t, s in changes(history(f)) if canon(s)]
        lags, after_off = [], 0
        for t, slug in ev:
            prior = [e for e in on_edges if e <= t]
            if prior:
                lags.append(t - prior[-1])
            if state_at(person_hist, t) == "off":
                after_off += 1
            ph = PERSON_HIST.get(slug, [])
            st = state_at(ph, t)
            home_edges = [ts for ts, s2 in ph if s2 == "home"]
            nxt = [e for e in home_edges if e > t]
            prev = [e for e in home_edges if e <= t]
            if st and st != "home" and st not in ("unknown", "unavailable"):
                cls = "i" if nxt and nxt[0] - t <= 600 else ("ii" if not nxt or nxt[0] - t > 1800 else "i_late")
            elif st == "home":
                if prev and t - prev[-1] <= 3600:
                    cls = "iii"
                    iii_lags.append(t - prev[-1])
                else:
                    cls = "iv"
            else:
                cls = "unknown_state"
            p3[cls] += 1
            p3_by[(slug, pick, cls)] += 1
        per_day = round(len(ev) / WINDOW_DAYS, 1)
        print(f"- {f}: {len(ev)} ({per_day}/d) lag p50={pct(lags, 50)} p90={pct(lags, 90)} "
              f"named-after-off={after_off}/{len(ev)}")
print("\n## P3 arrival classes (interior resident faces on resolved picks)")
print(dict(p3))
for (slug, pick, cls), n in sorted(p3_by.items()):
    if cls in ("i", "ii", "i_late"):
        print(f"  {slug} {pick} {cls} {n}")
weeks = WINDOW_DAYS / 7
i_n, ii_n = p3["i"], p3["ii"]
ratio = i_n / (i_n + ii_n) if (i_n + ii_n) else 0
print(f"P3 go rule: (i)/week={i_n / weeks:.2f} (>=1)  (i)/((i)+(ii))={ratio:.2f} (>=0.5) -> "
      f"{'GO' if i_n / weeks >= 1 and ratio >= 0.5 else 'NO-GO (FACE_ARRIVAL_INTERIOR_ENABLED stays False)'}")
gap = min(300.0, pct(iii_lags, 90) or 60.0)
print(f"P3 FACE_ARRIVAL_PRIOR_HOME_GAP_S suggestion = p90 of (iii) lag capped 300 = {gap}")

# egress (recorder bus events)
print("\n## P2 egress events (recorder bus ura_person_egress_event)")
etid = r.execute("select event_type_id from event_types where event_type='ura_person_egress_event'").fetchone()
egress = []
if etid:
    for ts, data in r.execute(
            "select e.time_fired_ts, d.shared_data from events e left join event_data d "
            "on e.data_id=d.data_id where e.event_type_id=? and e.time_fired_ts>=? order by 1",
            (etid[0], T0)):
        try:
            egress.append((ts, json.loads(data or "{}")))
        except ValueError:
            pass
cnt = collections.Counter()
for ts, d in egress:
    tier = d.get("identity_confidence")
    cnt[(d.get("direction"), d.get("person_id") is not None, tier)] += 1
for k, v in sorted(cnt.items(), key=str):
    print(f"  dir={k[0]} named={k[1]} identity_confidence={k[2]}: {v}")
nh = 0
for ts, d in egress:
    if d.get("direction") == "entry" and d.get("person_id"):
        st = state_at(PERSON_HIST.get(d["person_id"], []), ts - 300)
        nh += st == "not_home"
print(f"  named entries whose tracker read not_home 300 s before: {nh} (expected ~0: the veto)")

# ---------------------------------------------------------------- P4
print("\n## P4 hop lags between operator path cameras (person-sensor on edges, <=120 s)")
PATH_PAIRS = [
    ("rear_ptz", "garage_a"), ("g5_bullet", "garage_a"), ("garage_a", "staircase"),
    ("staircase", "stairs_top"), ("stairs_top", "playroom"), ("stairs_top", "upstairs_hall"),
    ("staircase", "family_room"), ("front_side_ptz", "front_door_aerial"),
    ("utilities_ptz", "front_door_aerial"), ("sonoffwindow", "front_door_aerial"),
    ("front_door_aerial", "foyer_fisheye"), ("madrone_g6_entry", "foyer_fisheye"),
    ("foyer_fisheye", "family_room"), ("foyer_fisheye", "master_hallway"),
    ("reolinkpatio", "family_room"),
]
person_entities = collections.defaultdict(list)
for e in REG:
    eid = e["entity_id"]
    if eid.startswith("binary_sensor.") and _SUFFIX.search(eid):
        person_entities[stem_of(eid)].append(eid)


def on_edges_for(stem):
    edges = []
    for eid in person_entities.get(stem, []):
        edges += [t for t, s in changes(history(eid)) if s == "on"]
    return sorted(edges)


for a, b in PATH_PAIRS:
    ea, eb = on_edges_for(a), on_edges_for(b)
    lags_d, lags_n = [], []
    j = 0
    for t in ea:
        while j < len(eb) and eb[j] < t:
            j += 1
        if j < len(eb) and eb[j] - t <= 120:
            hr = dt.datetime.fromtimestamp(t, CDT).hour
            (lags_n if hr in NIGHT_HOURS else lags_d).append(eb[j] - t)
    allv = lags_d + lags_n
    print(f"- {a} -> {b}: hops/day={len(allv) / WINDOW_DAYS:.1f} day={len(lags_d)} night={len(lags_n)} "
          f"p50={pct(allv, 50)} p90={pct(allv, 90)} (legs {len(person_entities.get(a, []))}/"
          f"{len(person_entities.get(b, []))})")

# ---------------------------------------------------------------- P5
print("\n## P5 consumer reality")
CM = next((merged(e) for e in ENTRIES if merged(e).get("entry_type") == "coordinator_manager"), {})
print(f"  security_on_arrival_add_expected={CM.get('security_on_arrival_add_expected', 'absent (default False)')}")
print(f"  pre_arrival_sources={CM.get('pre_arrival_sources')}")
for sw in ("switch.ura_security_coordinator_garage_remote_lockout",
           "switch.ura_security_coordinator_away_lock",
           "switch.ura_hvac_coordinator_pre_arrival_conditioning"):
    h = history(sw)
    print(f"  {sw}: {h[-1][1] if h else 'no history'}")
for e in REG:
    if e["entity_id"].startswith("switch.") and ("lockout" in e["entity_id"] or "away_lock" in e["entity_id"]):
        h = history(e["entity_id"])
        print(f"  {e['entity_id']}: {h[-1][1] if h else 'no history'}")

# ---------------------------------------------------------------- P7 baseline
print("\n## P7 baseline replay: egress entries with a single in-window face slug not home")
ENTRY_LO, ENTRY_HI = -60, 300
EGRESS_FACES = {}
INTEG = next((merged(e) for e in ENTRIES if merged(e).get("entry_type") == "integration"), {})
nbrs = INTEG.get("door_interior_neighbours") or {}
groups = INTEG.get("door_groups") or {}
FACE_EVENTS = {}
for f in FACE_SENSORS:
    FACE_EVENTS[f] = [(t, canon(s)) for t, s in changes(history(f)) if canon(s)]
labels = collections.Counter()
rows = []
for ts, d in egress:
    if d.get("direction") != "entry":
        continue
    cam = str(d.get("egress_camera", ""))
    st = stem_of(cam)
    group = groups.get(st)
    leg_stems = {st} | {stem_of(x) for x in (nbrs.get(group) or [])}
    names = set()
    for f, evs in FACE_EVENTS.items():
        if face_base(f) not in leg_stems:
            continue
        for t, slug in evs:
            if ENTRY_LO <= t - ts <= ENTRY_HI:
                names.add(slug)
    if len(names) != 1:
        continue
    slug = next(iter(names))
    pst = state_at(PERSON_HIST.get(slug, []), ts)
    if pst in (None, "home", "unknown", "unavailable"):
        continue
    nxt = [t for t, s in PERSON_HIST.get(slug, []) if s == "home" and t > ts]
    lead = (nxt[0] - ts) if nxt else None
    lab = "true_10m" if lead is not None and lead <= 600 else (
        "mis_or_phoneless" if lead is None or lead > 1800 else "late_10_30m")
    labels[lab] += 1
    rows.append((dt.datetime.fromtimestamp(ts, CDT).strftime("%m-%d %H:%M"), cam, slug, pst,
                 d.get("person_id"), None if lead is None else round(lead)))
for row in rows:
    print("  ", row)
print(f"P7 would-be candidates {len(rows)} in {WINDOW_DAYS} d: {dict(labels)} "
      f"(2/5/30-min variants derivable from the lead column)")
print("\nEND")
