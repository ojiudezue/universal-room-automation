#!/usr/bin/env python3
"""PLANNING_hvac_w1_w2_finish.md §2 P7 (W3 G0 follow-up) — READ-ONLY.

    ssh ha "python3 -" < scripts/probes/hvac_borrow_end_p7_probe.py

Classifies S12 BANKING borrows that start OUTSIDE the Path A window [10,14)
local and have NO `pre_arrival` ledger row within 2 min before their start
(the W3 G0 orchestrator cross-check found 12 such of 73). Per borrow:
 (a) the reason on its first `climate_write` (coverage only from 09-27);
 (b) any `pre_arrival` row in the 30 min before;
 (c) master / energy gate flips (switch recorder rows in the 10 min before);
 (d) a HA start within 15 min before (post-restart orphan reconcile /
     stale_boot_release) and the borrow's own end trigger;
 (e) time-zone slip: would the UTC hour fall in [10,14)?;
 (f) other.
Both DBs `mode=ro`.
"""
import datetime as dt
import json
import sqlite3

CDT = dt.timezone(dt.timedelta(hours=-5))
r = sqlite3.connect("file:/config/home-assistant_v2.db?mode=ro", uri=True)
u = sqlite3.connect(
    "file:/config/universal_room_automation/data/universal_room_automation.db?mode=ro",
    uri=True,
)


def iso(s):
    t = dt.datetime.fromisoformat(s)
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)
    return t.timestamp()


def f(t):
    return dt.datetime.fromtimestamp(t, CDT).strftime("%m-%d %H:%M:%S")


pre_arr = []
for ts, dj in u.execute(
    "select timestamp, details_json from ura_activity_log where action='pre_arrival'"
):
    # the ledger row carries its zones in details_json["zones"] (zone column NULL)
    zs = (json.loads(dj or "{}") or {}).get("zones") or []
    for zone in zs:
        pre_arr.append((iso(ts), zone, dj))
starts = [t for (t,) in r.execute(
    "select e.time_fired_ts from events e join event_types et on "
    "e.event_type_id=et.event_type_id where et.event_type='homeassistant_start'")]
writes = {}
for ts, dj in u.execute(
    "select timestamp, details_json from ura_activity_log where action='climate_write' order by timestamp"
):
    d = json.loads(dj or "{}")
    xid = d.get("excursion_id")
    if xid and xid not in writes:
        writes[xid] = (f(iso(ts)), d.get("site"), d.get("reason"))
gate_ents = [e for (e,) in r.execute(
    "select entity_id from states_meta where entity_id like 'switch.%pre_cool%' "
    "or entity_id like 'switch.%pre_condition%' or entity_id like 'switch.%energy_saver%'")]


def flips(t):
    out = []
    for e in gate_ents:
        for st, lt in r.execute(
            "select s.state, s.last_updated_ts from states s join states_meta m on "
            "s.metadata_id=m.metadata_id where m.entity_id=? and s.last_updated_ts between ? and ?",
            (e, t - 600, t)):
            out.append((e, st, f(lt)))
    return out


rows = u.execute(
    "select excursion_id, zone_id, started_ts, ended_ts, trigger, trigger_detail, "
    "duration_actual_s from hvac_excursion_events where kind='banking' and site='S12_pre_cool' "
    "order by started_ts").fetchall()
out_win = []
for xid, zone, st, en, trig, det, dur in rows:
    t = iso(st)
    h = dt.datetime.fromtimestamp(t, CDT).hour
    if 10 <= h < 14:
        continue
    out_win.append((xid, zone, t, en, trig, det, dur))
print(f"banking S12 borrows: {len(rows)}; outside [10,14) local: {len(out_win)}")
unexplained = []
for x in out_win:
    xid, zone, t = x[0], x[1], x[2]
    if any(p[1] == zone and t - 120 <= p[0] <= t + 5 for p in pre_arr):
        continue
    unexplained.append(x)
print(f"no pre_arrival row within 2 min before: {len(unexplained)}")
for xid, zone, t, en, trig, det, dur in unexplained:
    pa30 = [f(p[0]) for p in pre_arr if p[1] == zone and t - 1800 <= p[0] <= t]
    pa_any = [f(p[0]) for p in pre_arr if t - 1800 <= p[0] <= t]
    boot = [f(s) for s in starts if t - 900 <= s <= t]
    utc_h = dt.datetime.fromtimestamp(t, dt.timezone.utc).hour
    cls = []
    if xid in writes:
        cls.append(f"a:first_write={writes[xid]}")
    if pa30:
        cls.append(f"b:pre_arrival_30min={pa30}")
    elif pa_any:
        cls.append(f"b:pre_arrival_other_zone={pa_any}")
    fl = flips(t)
    if fl:
        cls.append(f"c:gate_flips={fl}")
    if boot:
        cls.append(f"d:boot={boot}")
    if 10 <= utc_h < 14:
        cls.append("e:utc_hour_in_window")
    if not cls:
        cls.append("f:other")
    print(json.dumps({"id": xid, "zone": zone, "start": f(t), "trigger": trig,
                      "detail": det, "dur_s": dur, "class": cls}, default=str))
