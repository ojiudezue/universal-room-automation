#!/usr/bin/env python3
"""Fan-signature probe, part 2 (read-only) — windows discovered by part 1.

Run:  ssh ha "python3 -" < fan_signature_probe_part2.py

Part 1 (fan_signature_probe.py) discovered:
  - Jaya Bedroom 2026-07-26 03:24:13Z: 'mmwave' occupancy entry at the exact
    second the ceiling fan turned on (automated, house departing) -> a labeled
    FAN-PHANTOM window on a unit WITH numeric LD2410 energy channels (jaya_3).
  - Study A phantom 07-31 20:41:16Z began at the exact second of a fan speed
    transition (33->55->100%), cleared 33 s after fan-off.
This script computes the per-class numeric feature tables used in
AUDIT_fan_signature_separability_probe.md and traces the fan-attribute
transitions around the Study A phantom onset.
"""
import sqlite3, math, json, statistics as st
from datetime import datetime, timezone

def T(s): return datetime.fromisoformat(s).replace(tzinfo=timezone.utc).timestamp()
def iso(ts): return datetime.fromtimestamp(ts, timezone.utc).strftime("%m-%d %H:%M:%S")

rec = sqlite3.connect('file:/config/home-assistant_v2.db?mode=ro', uri=True); rc = rec.cursor()

def hist(eid, t0, t1):
    rc.execute("""select s.last_updated_ts,s.state from states s
        join states_meta m on s.metadata_id=m.metadata_id
        where m.entity_id=? and s.last_updated_ts>=? and s.last_updated_ts<=?
        order by s.last_updated_ts""", (eid, t0, t1))
    return rc.fetchall()

def stats(eid, t0, t1, label):
    h = [(ts, float(s)) for ts, s in hist(eid, t0, t1) if s not in ("unavailable", "unknown", "")]
    if len(h) < 30:
        print(f"{label:28s} {eid.split('.')[-1]:20s} n={len(h)} insufficient"); return
    ts = [a for a, _ in h]; v = [b for _, b in h]
    dts = sorted(b - a for a, b in zip(ts, ts[1:])); mdt = dts[len(dts)//2]
    rate = len(h) / ((t1 - t0) / 3600)
    mean = st.mean(v); sd = st.pstdev(v); cv = sd/mean if mean else 0
    vs = sorted(v); q = lambda p: vs[int(p*len(vs))]
    zf = sum(1 for x in v if x == 0) / len(v)
    g = []; j = 0; n = min(int(ts[-1]-ts[0]), 15000)   # 1 s zero-order-hold grid
    for i in range(n):
        t = ts[0] + i
        while j+1 < len(ts) and ts[j+1] <= t: j += 1
        g.append(v[j])
    def ac(lag):
        m = st.mean(g); var = sum((x-m)**2 for x in g)
        return sum((g[i]-m)*(g[i+lag]-m) for i in range(len(g)-lag))/var if var else 0
    m = st.mean(v); best = (0, 0); tot = 0; nf = 0; f = 0.02   # DFT periodogram
    while f <= 0.45:
        re = sum((x-m)*math.cos(2*math.pi*f*t) for t, x in h[:6000])
        im = sum((x-m)*math.sin(2*math.pi*f*t) for t, x in h[:6000])
        p = (re*re+im*im)/min(len(h), 6000); tot += p; nf += 1
        if p > best[1]: best = (f, p)
        f += 0.005
    print(f"{label:28s} {eid.split('.')[-1]:20s} n={len(h)} rate={rate:.0f}/hr mdt={mdt:.1f}s "
          f"mean={mean:.1f} sd={sd:.1f} CV={cv:.2f} p10/50/90={q(.1):.0f}/{q(.5):.0f}/{q(.9):.0f} "
          f"zero%={zf:.2f} ac1={ac(1):.2f} ac10={ac(10):.2f} ac60={ac(60):.2f} "
          f"peak={best[0]:.3f}Hz snr={best[1]/(tot/nf):.1f}")

W = [("PHANTOM fan-on vacant",  T("2026-07-26 04:00"), T("2026-07-26 09:30")),
     ("OCCUPIED 07-25 evening", T("2026-07-25 16:00"), T("2026-07-25 22:40")),
     ("EMPTY fan-off 07-28",    T("2026-07-28 03:00"), T("2026-07-28 23:00"))]
for eid in ("sensor.jaya_3_move_energy", "sensor.jaya_3_still_energy", "sensor.jaya_3_detection_distance"):
    for label, t0, t1 in W: stats(eid, t0, t1, label)

rc.execute("select entity_id from states_meta where entity_id like 'binary_sensor.jaya_3%' or entity_id like 'binary_sensor.%jayabedroom%'")
for e in [r[0] for r in rc.fetchall()]:
    line = []
    for label, t0, t1 in W:
        h = [x for x in hist(e, t0, t1) if x[1] in ("on", "off")]
        line.append(f"{label.split()[0]}:{len(h)}")
    print("edges", e, line)

# Study A fan attribute transitions around the 07-31 20:41 phantom onset
rc.execute("""select s.last_updated_ts,s.state,a.shared_attrs from states s
    join states_meta m on s.metadata_id=m.metadata_id
    left join state_attributes a on s.attributes_id=a.attributes_id
    where m.entity_id='fan.polyfan_dreo704s_wifi_studya'
      and s.last_updated_ts>=? and s.last_updated_ts<=? order by s.last_updated_ts""",
    (T("2026-07-31 19:30"), T("2026-07-31 21:30")))
prev = None
print("\nStudy A fan transitions around phantom onset (20:41:16Z):")
for ts, s, at in rc.fetchall():
    a = json.loads(at) if at else {}
    key = (s, a.get('percentage'), a.get('oscillating'), a.get('preset_mode'))
    if key != prev: print(" ", iso(ts), key); prev = key
