"""Frigate-2 detection-health probe.

Context: Frigate 2 was STORAGE-BOUND and swallowing detections from ~2026-08-20
until fixed 2026-08-23. The egress-identity NO-GO ruling rests partly on
measurements taken INSIDE that window. This probe dates the outage and measures
recovery, using the person:face ratio as the discriminator the operator proposed.

Discriminating logic:
  person detections NORMAL + face events ~0   -> face recognition is the problem
  person AND face both collapsed              -> storage/ingest was the problem
  both healthy now, both collapsed before     -> outage confirmed + recovered
"""
import sqlite3, collections, statistics as st
from datetime import datetime, timedelta

REC = "/config/home-assistant_v2.db"
URA = "/config/universal_room_automation/data/universal_room_automation.db"
r = sqlite3.connect(REC)

def daily_on_transitions(like, days=14):
    """Count OFF->ON transitions per day. Transitions, NOT rows —
    row counts are inflated by attribute churn (46-89x on some sensors)."""
    out = collections.defaultdict(lambda: collections.Counter())
    q = ("select m.entity_id, s.state, s.last_updated_ts from states s "
         "join states_meta m on m.metadata_id=s.metadata_id "
         "where m.entity_id like ? and s.last_updated_ts > strftime('%s','now')-? "
         "order by m.entity_id, s.last_updated_ts")
    prev = {}
    for ent, state, ts in r.execute(q, (like, days*86400)):
        d = datetime.fromtimestamp(ts).strftime("%m-%d")
        if prev.get(ent) != "on" and state == "on":
            out[ent][d] += 1
        prev[ent] = state
    return out

def rollup(d):
    tot = collections.Counter()
    for ent, days in d.items():
        for day, n in days.items():
            tot[day] += n
    return tot

print("=== PERSON detections per day (all cameras, OFF->ON transitions) ===")
person = rollup(daily_on_transitions("binary_sensor.%person%"))
for day in sorted(person):
    print(f"  {day}  {person[day]:5d}  {'#'*min(60, person[day]//3)}")

print("\n=== FACE recognitions per day ===")
# CORRECTED: face signal is sensor.<cam>_last_recognized_face_2 — a STATE sensor
# carrying a NAME, not a binary sensor. Count transitions INTO a real name.
# 2026-08-23 FIX: the filter was CASE-SENSITIVE and the live state is "Unknown"
# (capital U) — verified on sensor.master_hallway_last_recognized_face_2, which
# on 08-22 carried ONLY {unavailable:3, Unknown:3} and zero real names, yet the
# probe scored it 3 recognitions. Every unavailable->Unknown cycle (i.e. every HA
# restart) was being counted as a face recognition, inflating post-outage days.
_JUNK = {"", "unknown", "unavailable", "none", "unrecognized", "unknown person"}

def _is_junk(v):
    return v is None or str(v).strip().casefold() in _JUNK
face = collections.Counter()
face_by_cam = collections.defaultdict(collections.Counter)
prevf = {}
for ent, state, ts in r.execute(
        "select m.entity_id, s.state, s.last_updated_ts from states s "
        "join states_meta m on m.metadata_id=s.metadata_id "
        "where m.entity_id like '%last_recognized_face%' "
        "and s.last_updated_ts > strftime('%s','now')-?  order by m.entity_id, s.last_updated_ts",
        (14*86400,)):
    d = datetime.fromtimestamp(ts).strftime("%m-%d")
    if not _is_junk(state) and prevf.get(ent) != state:
        face[d] += 1
        face_by_cam[ent.split(".")[1].replace("_last_recognized_face_2","")][d] += 1
    prevf[ent] = state
for day in sorted(face):
    print(f"  {day}  {face[day]:5d}")
if not face:
    print("  ZERO named-face recognitions in the whole window")
print("\n  --- by camera (top 12) ---")
for cam, days in sorted(face_by_cam.items(), key=lambda kv: -sum(kv[1].values()))[:12]:
    print(f"    {cam:34s} {sum(days.values()):4d}   " + " ".join(f"{d}:{n}" for d,n in sorted(days.items())))

print("\n=== person:face RATIO per day (the discriminator) ===")
for day in sorted(person):
    f = face.get(day, 0)
    ratio = (f / person[day] * 100) if person[day] else 0
    print(f"  {day}  person={person[day]:5d}  face={f:4d}  face/person={ratio:5.1f}%")

print("\n=== EGRESS crossings + person_id population (URA DB) ===")
try:
    u = sqlite3.connect(URA)
    rows = list(u.execute(
        "select date(timestamp), count(*), sum(case when person_id is not null then 1 else 0 end) "
        "from person_entry_exit_events where timestamp > date('now','-14 day') group by 1 order by 1"))
    if rows:
        for d, n, pid in rows:
            print(f"  {d}  crossings={n:4d}  with person_id={pid}")
    else:
        print("  no crossings in the last 14 days")
    tot = u.execute("select count(*), sum(case when person_id is not null then 1 else 0 end) "
                    "from person_entry_exit_events").fetchone()
    print(f"  ALL TIME: {tot[0]} rows, {tot[1] or 0} with person_id")
except Exception as e:
    print("  URA DB read failed:", e)

print("\n=== recorder horizon (bounds every claim above) ===")
h = r.execute("select datetime(min(last_updated_ts),'unixepoch','-5 hours') from states").fetchone()[0]
print(f"  states reach back only to {h} — anything earlier CANNOT be measured here")
