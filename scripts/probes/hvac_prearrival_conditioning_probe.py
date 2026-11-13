#!/usr/bin/env python3
"""HVAC-PRECOOL-STANDDOWN-WHEN-COOL-1 D0 — READ-ONLY probe.

Plan: docs/planning/PLANNING_hvac_precool_standdown_and_seasons.md rev 4, D0.

    ssh ha "python3 -" < scripts/probes/hvac_prearrival_conditioning_probe.py
    ssh ha "PROBE_MODE=check PROBE_FROM=2026-11-13 PROBE_TO=2026-11-16 python3 -" \
        < scripts/probes/hvac_prearrival_conditioning_probe.py

SURVEY mode (default): for every pre-arrival intake since 2026-08-23
  * intakes = `ura_activity_log` action `pre_arrival` rows (one per zone in
    details.zones; from 10-13), plus, before the first such row,
    `hvac_excursion_events` rows with site `S12_pre_arrival`;
  * T at the intake = the recorder thermostat `current_temperature` at or
    before the intake (THERMOSTAT column), else the mean of the zone's room
    temperatures in `environmental_data` within 15 min before (PROXY column,
    kept separate — rooms are mapped through the Zone Manager entry's
    `zone_rooms` / `zone_thermostat`);
  * the configured Home (heat, cool) for the intake's season from the CM entry
    options (`hvac_baseline_<season>_home_<heat|cool>`, SEASONAL_DEFAULTS
    fallback) and the live `hvac_solar_bank_floor` option (default 72);
  * effective_high = max(home_cool - 2, floor) (live low + 2 ignored: the
    recorder low is read when available and folded in);
    effective_low  = min(home_heat + 2, home_cool, live_high - 2);
  * outdoor = the first `weather.*` entity's `temperature` attribute at or
    before the intake (entity printed; informational).
  Output per month x season: arrivals with T > effective_high (pre-cool),
  inside the band (stand-down), T < effective_low (pre-heat would fire), and
  inverted-band intakes, separately for THERMOSTAT and PROXY T.

CHECK mode: INV-SD-COOL / INV-SD-HEAT over [PROBE_FROM, PROBE_TO):
  * every `climate_write` row site=S12_pre_cool reason=pre_arrival whose
    recorder T at/before ts_issued <= values_after.target_temp_high -> VIOLATION;
  * every `climate_write` row site=S13_pre_heat reason=pre_arrival (the
    energy pre-heat shares the site with reason=pre_heat — filtered) whose
    recorder T is missing or >= values_after.target_temp_low -> VIOLATION;
  * every `hvac_excursion_events` row with site S12_pre_arrival /
    S13_pre_arrival ended `lease_expiry` or `banking_release` -> VIOLATION
    (INV-LIFECYCLE);
  * `pre_arrival_standdown` rows counted.

Both DBs are opened `mode=ro`. Margin is the code's 0.0 (rung 1).
"""
import collections
import datetime as dt
import json
import os
import sqlite3

CDT = dt.timezone(dt.timedelta(hours=-6))
SINCE = dt.datetime(2026, 8, 23, 0, 0, tzinfo=CDT)
MARGIN = 0.0
PROXY_WINDOW_S = 900
SEASONAL_DEFAULTS = {  # (cool, heat), hvac_const.SEASONAL_DEFAULTS home rows
    "summer": (77, 70), "shoulder": (74, 70), "winter": (72, 70),
}
SUMMER_MONTHS, WINTER_MONTHS = {6, 7, 8, 9}, {12, 1, 2}
DOMAIN = "universal_room_automation"

r = sqlite3.connect("file:/config/home-assistant_v2.db?mode=ro", uri=True)
u = sqlite3.connect(
    "file:/config/universal_room_automation/data/universal_room_automation.db?mode=ro",
    uri=True,
)
with open("/config/.storage/core.config_entries") as fh:
    ENTRIES = [e for e in json.load(fh)["data"]["entries"] if e.get("domain") == DOMAIN]


def merged(e):
    return {**(e.get("data") or {}), **(e.get("options") or {})}


CM = next((merged(e) for e in ENTRIES
           if merged(e).get("entry_type") == "coordinator_manager"), {})
FLOOR = float(CM.get("hvac_solar_bank_floor", 72.0))
ZONE_ROOMS = collections.defaultdict(set)   # thermostat -> {room entry_id}
for e in ENTRIES:
    m = merged(e)
    if m.get("entry_type") != "zone_manager":
        continue
    for _zn, zc in (m.get("zones") or {}).items():
        th = zc.get("zone_thermostat")
        if th:
            ZONE_ROOMS[th].update(zc.get("zone_rooms") or [])
THERMOSTATS = sorted(ZONE_ROOMS)


def season_of(t):
    m = dt.datetime.fromtimestamp(t, CDT).month
    return "summer" if m in SUMMER_MONTHS else "winter" if m in WINTER_MONTHS else "shoulder"


def home(season):
    dc, dh = SEASONAL_DEFAULTS[season]
    return (float(CM.get(f"hvac_baseline_{season}_home_heat", dh)),
            float(CM.get(f"hvac_baseline_{season}_home_cool", dc)))


def iso(s):
    t = dt.datetime.fromisoformat(s)
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)
    return t.timestamp()


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def meta_id(ent):
    row = r.execute("select metadata_id from states_meta where entity_id=?", (ent,)).fetchone()
    return row[0] if row else None


def attrs_at(ent, t):
    mid = meta_id(ent)
    if mid is None:
        return None
    row = r.execute(
        "select s.state, sa.shared_attrs from states s "
        "left join state_attributes sa on s.attributes_id=sa.attributes_id "
        "where s.metadata_id=? and s.last_updated_ts<=? "
        "order by s.last_updated_ts desc limit 1", (mid, t)).fetchone()
    if not row:
        return None
    try:
        return row[0], json.loads(row[1] or "{}")
    except Exception:
        return row[0], {}


def proxy_t(th, t):
    rooms = ZONE_ROOMS.get(th) or set()
    if not rooms:
        return None
    lo = dt.datetime.fromtimestamp(t - PROXY_WINDOW_S, dt.timezone.utc).isoformat()
    hi = dt.datetime.fromtimestamp(t, dt.timezone.utc).isoformat()
    q = ",".join("?" * len(rooms))
    vals = [v for (v,) in u.execute(
        f"select temperature from environmental_data where room_id in ({q}) "
        "and timestamp between ? and ? and temperature is not null",
        (*rooms, lo[:19], hi[:19]))]
    return sum(vals) / len(vals) if vals else None


WEATHER = next((e for (e,) in r.execute(
    "select entity_id from states_meta where entity_id like 'weather.%' order by 1")), None)


def zone_thermostat(zone_id):
    # zone_N -> the N-th thermostat in discovery order is NOT guaranteed; map
    # through the ledger rows instead (climate_write rows carry both).
    return ZONE_TH.get(zone_id)


ZONE_TH = {}
for zid, ent in u.execute(
    "select zone, entity_id from ura_activity_log "
    "where action='climate_write' and zone is not null and entity_id like 'climate.%' "
    "order by timestamp desc limit 5000"
):
    ZONE_TH.setdefault(zid, ent)


def survey():
    intakes = []
    first_act = None
    for ts, dj in u.execute(
        "select timestamp, details_json from ura_activity_log "
        "where action='pre_arrival' and coordinator='hvac' order by timestamp"
    ):
        t = iso(ts)
        if t < SINCE.timestamp():
            continue
        first_act = t if first_act is None else first_act
        for z in (json.loads(dj or "{}").get("zones") or []):
            intakes.append((t, z, "activity"))
    for z, st in u.execute(
        "select zone_id, started_ts from hvac_excursion_events where site='S12_pre_arrival'"
    ):
        t = iso(st)
        if t >= SINCE.timestamp() and (first_act is None or t < first_act):
            intakes.append((t, z, "excursion"))
    print(f"floor={FLOOR} thermostats={THERMOSTATS} weather={WEATHER} "
          f"zone->thermostat={ZONE_TH}")
    print("home (heat, cool) per season:", {s: home(s) for s in SEASONAL_DEFAULTS})
    agg = collections.Counter()
    out_by = collections.defaultdict(list)
    for t, z, src in sorted(intakes):
        th = zone_thermostat(z)
        season = season_of(t)
        h_heat, h_cool = home(season)
        a = attrs_at(th, t) if th else None
        T_th = num(a[1].get("current_temperature")) if a else None
        lo = num(a[1].get("target_temp_low")) if a else None
        hi = num(a[1].get("target_temp_high")) if a else None
        eh = max(h_cool - 2, FLOOR, (lo + 2) if lo is not None else -1e9)
        el = min(h_heat + 2, h_cool, (hi - 2) if hi is not None else 1e9)
        T_px = None if T_th is not None else proxy_t(th, t)
        month = dt.datetime.fromtimestamp(t, CDT).strftime("%Y-%m")
        wa = attrs_at(WEATHER, t) if WEATHER else None
        if wa:
            out_by[(month, season)].append(num(wa[1].get("temperature")))
        for col, T in (("THERMOSTAT", T_th), ("PROXY", T_px)):
            if T is None:
                continue
            if el > eh:
                cls = "inverted"
            elif T > eh + MARGIN:
                cls = "pre_cool"
            elif T < el - MARGIN:
                cls = "pre_heat"
            else:
                cls = "standdown"
            agg[(month, season, col, cls)] += 1
        if T_th is None and T_px is None:
            agg[(month, season, "NO_T", "unknown")] += 1
    print("\nmonth    season    column      pre_cool standdown pre_heat inverted unknown  outdoor_mean")
    for month, season in sorted({(k[0], k[1]) for k in agg}):
        for col in ("THERMOSTAT", "PROXY", "NO_T"):
            c = {cls: agg[(month, season, col, cls)]
                 for cls in ("pre_cool", "standdown", "pre_heat", "inverted", "unknown")}
            if not any(c.values()):
                continue
            ow = [x for x in out_by[(month, season)] if x is not None]
            om = f"{sum(ow) / len(ow):.1f}" if ow else "-"
            print(f"{month}  {season:9s} {col:11s} {c['pre_cool']:8d} {c['standdown']:9d} "
                  f"{c['pre_heat']:8d} {c['inverted']:8d} {c['unknown']:7d}  {om}")


def check():
    lo_t = iso(os.environ.get("PROBE_FROM", "2026-11-13") + "T00:00:00-06:00")
    hi_t = iso(os.environ.get("PROBE_TO", "2027-01-01") + "T00:00:00-06:00")
    viol, n = [], collections.Counter()
    for ts, ent, dj in u.execute(
        "select timestamp, entity_id, details_json from ura_activity_log "
        "where action='climate_write' order by timestamp"
    ):
        t = iso(ts)
        if not (lo_t <= t < hi_t):
            continue
        d = json.loads(dj or "{}")
        if d.get("reason") != "pre_arrival":
            continue
        site, va = d.get("site"), d.get("values_after") or {}
        a = attrs_at(ent, t)   # ts_issued is a monotonic clock; use the row time
        T = num(a[1].get("current_temperature")) if a else None
        if site == "S12_pre_cool":
            n["cool_writes"] += 1
            th = num(va.get("target_temp_high"))
            if T is not None and th is not None and T <= th + MARGIN:
                viol.append(("INV-SD-COOL", ts, ent, T, th))
        elif site == "S13_pre_heat":
            n["heat_writes"] += 1
            tl = num(va.get("target_temp_low"))
            if T is None or tl is None or T >= tl - MARGIN:
                viol.append(("INV-SD-HEAT", ts, ent, T, tl))
    for z, st, en, trig, site in u.execute(
        "select zone_id, started_ts, ended_ts, trigger, site from hvac_excursion_events "
        "where site in ('S12_pre_arrival','S13_pre_arrival')"
    ):
        if not (lo_t <= iso(st) < hi_t):
            continue
        n[f"rows_{site}"] += 1
        if trig in ("lease_expiry", "banking_release"):
            viol.append(("INV-LIFECYCLE", st, z, site, trig))
    (sd,) = u.execute(
        "select count(*) from ura_activity_log where action='pre_arrival_standdown' "
        "and timestamp >= ? and timestamp < ?",
        (dt.datetime.fromtimestamp(lo_t, dt.timezone.utc).isoformat(),
         dt.datetime.fromtimestamp(hi_t, dt.timezone.utc).isoformat())).fetchone()
    print("counts:", dict(n), "standdown_rows:", sd)
    print("VIOLATIONS:", len(viol))
    for v in viol:
        print(v)


if os.environ.get("PROBE_MODE", "survey") == "check":
    check()
else:
    survey()
