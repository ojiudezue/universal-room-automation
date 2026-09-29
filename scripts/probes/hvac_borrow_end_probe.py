#!/usr/bin/env python3
"""PLANNING_hvac_w1_w2_finish.md §2 — P1 (+P5) — READ-ONLY.

    ssh ha "python3 -" < scripts/probes/hvac_borrow_end_probe.py

P1: every recorder change on the three Bryant zones where BOTH sides are
`heat_cool`, `preset_mode == manual`, all four legs numeric and >= 1 leg
changed (the D1 rule steps 1-3). Each is classified against the last 4 URA
`set_temperature` rows (`climate_write.values_after`) for that entity issued
at or before the change, with the D1 changed-legs rule (tol 0.5 F):
    matched                -> ura_echo
    unmatched_borrow_live  -> no match, a borrow / nudge window is live
    unmatched_no_borrow    -> no match, no borrow window
It also reports the lag from the last URA temp write, whether the change sits
inside the 15 s temp suppression window (dropped before D1 runs), and splits
out arrivals > 5 min after the last URA write (ha_carrier full-read release,
C16/C21).

P5: `climate_write` S4_revert rows pinning `manual`, and startup_audit nudge
preset restores pinning `manual`.

Both DBs are opened `mode=ro`.
"""
import collections
import datetime as dt
import json
import sqlite3

CDT = dt.timezone(dt.timedelta(hours=-5))
ENT = {
    "zone_1": "climate.thermostat_bryant_wifi_studyb_zone_1",
    "zone_2": "climate.up_hallway_zone_2",
    "zone_3": "climate.back_hallway_zone_3",
}
TOL = 0.5
DEPTH = 4
TEMP_SUPPRESS_S = 15
FULL_READ_S = 300
SINCE = dt.datetime(2026, 9, 26, 0, 0, tzinfo=CDT)

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


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# URA set_temperature writes per entity
writes = collections.defaultdict(list)
for ts, ent, dj in u.execute(
    "select timestamp, entity_id, details_json from ura_activity_log "
    "where action='climate_write' order by timestamp"
):
    d = json.loads(dj or "{}")
    if d.get("verb") != "set_temperature":
        continue
    va = d.get("values_after") or {}
    writes[ent].append((iso(ts), num(va.get("target_temp_low")),
                        num(va.get("target_temp_high")), d.get("site"),
                        d.get("excursion_id")))
cov_start = min((w[0][0] for w in writes.values() if w), default=None)
print("climate_write set_temperature coverage from", f(cov_start) if cov_start else None,
      {k: len(v) for k, v in writes.items()})

# Known URA windows per zone: nudge start->restore (+300 s), borrow start->end
windows = collections.defaultdict(list)
open_n = {}
for z, ts, et in u.execute(
    "select zone_id, timestamp, event_type from ac_ramp_events "
    "where event_type in ('nudge_started','nudge_restored') order by timestamp"
):
    if et == "nudge_started":
        open_n[z] = iso(ts)
    elif z in open_n:
        windows[z].append((open_n.pop(z), iso(ts) + FULL_READ_S, "nudge"))
for z, st, en, kind, site, trig in u.execute(
    "select zone_id, started_ts, ended_ts, kind, site, trigger from hvac_excursion_events"
):
    s = iso(st)
    e = iso(en) if en else s + 7200
    windows[z].append((s, e, f"{kind}/{site}/{trig}"))


def live_window(z, t):
    return [w[2] for w in windows[z] if w[0] <= t <= w[1]]


def attrs(ent):
    return r.execute(
        "select s.state, s.last_updated_ts, sa.shared_attrs from states s "
        "join states_meta m on s.metadata_id=m.metadata_id "
        "left join state_attributes sa on s.attributes_id=sa.attributes_id "
        "where m.entity_id=? and s.last_updated_ts>=? order by 2",
        (ent, SINCE.timestamp()),
    ).fetchall()


rows = []
for z, ent in ENT.items():
    prev = None
    for st, t, a in attrs(ent):
        try:
            a = json.loads(a or "{}")
        except Exception:
            continue
        cur = (st, a.get("preset_mode"), num(a.get("target_temp_low")),
               num(a.get("target_temp_high")), t)
        if prev is not None:
            ps, pp, pl, ph, _ = prev
            cs, cp, cl, ch, _ = cur
            if (ps == cs == "heat_cool" and pp == cp == "manual"
                    and None not in (pl, ph, cl, ch)):
                changed = [leg for leg, o, n in (("low", pl, cl), ("high", ph, ch))
                           if o != n]
                if changed:
                    recent = [w for w in writes[ent] if w[0] <= t][-DEPTH:]
                    new = {"low": cl, "high": ch}

                    def ok(w):
                        vals = {"low": w[1], "high": w[2]}
                        return all(vals[leg] is not None
                                   and abs(vals[leg] - new[leg]) <= TOL
                                   for leg in changed)
                    matched = any(ok(w) for w in recent)
                    lag = (t - recent[-1][0]) if recent else None
                    lw = live_window(z, t)
                    cls = ("matched" if matched else
                           "unmatched_borrow_live" if lw else "unmatched_no_borrow")
                    rows.append({
                        "zone": z, "t": f(t), "ts": t, "cls": cls,
                        "old": (pl, ph), "new": (cl, ch), "changed": changed,
                        "lag_s": None if lag is None else round(lag, 1),
                        "in_temp_window": lag is not None and lag <= TEMP_SUPPRESS_S,
                        "late_gt_5min": lag is None or lag > FULL_READ_S,
                        "windows": lw,
                        "recent": [(f(w[0]), w[1], w[2], w[3]) for w in recent],
                        "pre_coverage": cov_start is None or t < cov_start,
                    })
        prev = cur

print(f"\nP1 within-manual changes since {SINCE:%m-%d %H:%M} CDT: N={len(rows)}")
print("class counts:", collections.Counter(x["cls"] for x in rows))
print("post-coverage class counts:",
      collections.Counter(x["cls"] for x in rows if not x["pre_coverage"]))
for x in rows:
    print(json.dumps({k: v for k, v in x.items() if k != "ts"}, default=str))

# The named gate: an unmatched row that is an ECHO candidate = unmatched, post
# coverage, and within FULL_READ_S of a URA temp write or inside a nudge window.
cands = [x for x in rows if x["cls"] != "matched" and not x["pre_coverage"]
         and ((x["lag_s"] is not None and x["lag_s"] <= FULL_READ_S)
              or any(w == "nudge" for w in x["windows"]))]
print(f"\nP1 GATE: unmatched rows inside a URA echo window (<=5 min of a URA temp "
      f"write, or a nudge window): {len(cands)}")
for x in cands:
    print("  ", json.dumps({k: v for k, v in x.items() if k != "ts"}, default=str))

# P5
print("\nP5 S4_revert rows pinning manual / startup-audit nudge restores pinning manual:")
for ts, dj in u.execute(
    "select timestamp, details_json from ura_activity_log where action='climate_write' "
    "and (details_json like '%S4_revert%' or details_json like '%startup_audit_nudge%')"
):
    d = json.loads(dj or "{}")
    va = d.get("values_after") or {}
    if va.get("preset_mode") == "manual":
        print("  ", ts, d.get("site"), d.get("reason"), va)
print("P5 S4_revert total:", u.execute(
    "select count(*) from ura_activity_log where action='climate_write' "
    "and details_json like '%\"site\": \"S4_revert\"%'").fetchone())
