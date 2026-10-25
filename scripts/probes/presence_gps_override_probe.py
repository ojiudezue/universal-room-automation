"""PERSON-BLE-WINS-OVER-STALE-GPS-1 — D0 / D0b probe (read-only).

Plan: docs/planning/PLANNING_presence_gps_assistive.md §5 (probe4.py + f1c.py,
combined here for the post-deploy re-run in D1 "Live re-run").

Run on the HA host against the recorder (read-only URI):

    ssh ha "python3 -" < scripts/probes/presence_gps_override_probe.py

Section 1 (D0, was probe4.py): segments where URA's person location reads
`home` with `tracker_sources.gps == home`, per app user, with the fraction
of each segment the person's own BLE trackers read home and the minutes
where ALL of them read not_home. Post-deploy acceptance: GPS-home segments
with all BLE not_home > 10 min, excluding the 6 min after a restart -> 0.

Section 2 (D0b, was f1c.py): every 0 / unavailable reading of Bermuda's
Active Proxy Count, its duration, whether it sits at an HA restart, and
when each resident BLE tracker next read home.

Entity ids are this house's (2026-10-24 live registry); edit BLE / GPS /
TRK for another install.
"""
import datetime as dt
import json
import sqlite3

c = sqlite3.connect("file:/config/home-assistant_v2.db?mode=ro", uri=True)
NOW = c.execute("select max(last_updated_ts) from states").fetchone()[0]


def L(t, secs=False):
    fmt = "%m-%d %H:%M:%S" if secs else "%m-%d %H:%M"
    return (dt.datetime.utcfromtimestamp(t) - dt.timedelta(hours=5)).strftime(fmt)


def rows(e):
    return c.execute(
        "select s.last_updated_ts,s.state,sa.shared_attrs from states s "
        "join states_meta m on s.metadata_id=m.metadata_id "
        "left join state_attributes sa on s.attributes_id=sa.attributes_id "
        "where m.entity_id=? order by 1", (e,)).fetchall()


def series(e):
    return [(t, (s or "").lower()) for t, s, _ in rows(e)]


def frac(ser, a, b, val):
    tot = 0
    cur = None
    ct = a
    for t, s in ser:
        if t <= a:
            cur = s
            continue
        if t >= b:
            break
        if cur == val:
            tot += t - ct
        cur = s
        ct = t
    if cur == val:
        tot += b - ct
    return tot / (b - a) if b > a else 0


# ---------------------------------------------------------------- section 1
BLE = {
    "oji_udezue": ["device_tracker.private_ble_device_8ce182",
                   "device_tracker.iphone_oji_bermuda_tracker"],
    "ezinne": ["device_tracker.ezinne_iphone",
               "device_tracker.ezinne_iphone_bermuda_tracker"],
}
GPS = {"oji_udezue": "device_tracker.phalanxiphone15promaxcflare",
       "ezinne": "device_tracker.zinny_s_iphone_15"}

print("== D0: GPS-home URA segments vs own BLE ==")
for p in BLE:
    print("=====", p)
    segs = []
    prev = None
    for ts, st, a in rows(f"sensor.universal_room_automation_{p}_location"):
        aj = json.loads(a) if a else {}
        src = aj.get("tracker_sources") or {}
        k = ((st or "").lower() == "home" and src.get("gps") == "home")
        if prev is None or prev[0] != k:
            if prev:
                segs.append((prev[0], prev[1], ts))
            prev = (k, ts)
    if prev:
        segs.append((prev[0], prev[1], NOW))
    bs = [series(e) for e in BLE[p]]
    gts = [t for t, _, _ in rows(GPS[p])]
    tot = 0
    n = 0
    for k, a, b in segs:
        if not k or b - a < 120:
            continue
        n += 1
        tot += b - a
        fb = [frac(s, a, b, "home") for s in bs]
        pts = sorted(set([a, b] + [t for s in bs for t, _ in s if a < t < b]))
        nh = 0
        for i in range(len(pts) - 1):
            m = (pts[i] + pts[i + 1]) / 2
            st = []
            for s in bs:
                cur = None
                for t, v in s:
                    if t <= m:
                        cur = v
                    else:
                        break
                st.append(cur)
            if all(v == "not_home" for v in st):
                nh += pts[i + 1] - pts[i]
        upd = [t for t in gts if a <= t <= b]
        prior = [t for t in gts if t <= a]
        age = (a - prior[-1]) / 60 if prior else -1
        print(f"{L(a)} {(b - a) / 60:6.1f}m  ble_home_frac={['%.2f' % x for x in fb]} "
              f"all_ble_not_home={nh / 60:6.1f}m gps_updates_in_seg={len(upd)} "
              f"gps_age_at_start={age:.0f}m")
    print("total gps-home-override segments", n, "minutes", tot / 60)

# ---------------------------------------------------------------- section 2
print("== D0b: proxy-count zero / unavailable readings ==")


def ser2(e):
    return c.execute(
        "select s.last_updated_ts,s.state from states s join states_meta m "
        "on s.metadata_id=m.metadata_id where m.entity_id=? order by 1",
        (e,)).fetchall()


pc = ser2("sensor.bermuda_global_active_proxy_count")
TRK = {"oji_pb": "device_tracker.private_ble_device_8ce182",
       "oji_b": "device_tracker.iphone_oji_bermuda_tracker",
       "ez": "device_tracker.ezinne_iphone",
       "ez_b": "device_tracker.ezinne_iphone_bermuda_tracker",
       "jaya_pb": "device_tracker.private_ble_device_249050",
       "jaya_b": "device_tracker.iphone_jaya_bermuda_tracker"}
S = {k: ser2(v) for k, v in TRK.items()}
rs = [t for (t,) in c.execute(
    "select time_fired_ts from events e join event_types et "
    "on e.event_type_id=et.event_type_id where et.event_type='homeassistant_start'")]
print("restarts", [L(t, True) for t in rs])
DEAD = ("0", "0.0", "unavailable", "unknown")
for i, (t, s) in enumerate(pc):
    if s in DEAD:
        nxt = next(((tt, ss) for tt, ss in pc[i + 1:] if ss not in DEAD), None)
        dur = (nxt[0] - t) if nxt else None
        rec = {}
        for k, ser_ in S.items():
            before = [ss for tt, ss in ser_ if tt < t - 1]
            h = next((tt for tt, ss in ser_ if tt >= t and ss == "home"), None)
            rec[k] = (before[-1] if before else "?",
                      round((h - t) / 60, 1) if h else None)
        near_restart = any(abs(r - t) < 180 for r in rs)
        print(L(t, True), s, "zero_dur_s", round(dur) if dur else None,
              "restart" if near_restart else "", rec)
