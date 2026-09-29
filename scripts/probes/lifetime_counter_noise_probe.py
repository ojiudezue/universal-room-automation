"""D-1 gate for PLANNING_energy_lifetime_counter_poisoning.md (read-only).

Measures legitimate float/quantisation DECREASES in the six Envoy lifetime counters
(hour-to-hour in long-term statistics, 90 days; reading-to-reading in raw states),
excluding glitch values (<= 1.0 MWh, e.g. the constant 0.045505) so only noise between
plausible readings is counted. Also counts glitch readings and how they recover.
Run: ssh ha "python3 -" < scripts/probes/lifetime_counter_noise_probe.py
"""
import sqlite3, time
DB = "file:/config/home-assistant_v2.db?mode=ro"
SENS = ["energy_production", "energy_consumption", "net_energy_consumption", "net_energy_production",
        "battery_energy_discharged", "battery_energy_charged"]
PFX = "sensor.envoy_482543015950_lifetime_"
GLITCH_MAX = 1.0  # MWh; real counters are >> 1 MWh
c = sqlite3.connect(DB, uri=True)
now = time.time()
def summarize(name, vals):
    good = [(t, v) for t, v in vals if v is not None and v > GLITCH_MAX]
    glitch = [(t, v) for t, v in vals if v is not None and v <= GLITCH_MAX]
    decs, incs = [], []
    for (t0, a), (t1, b) in zip(good, good[1:]):
        (decs if b < a else incs).append(b - a if b >= a else a - b)
    ep = [(t0, a, b) for (t0, a), (t1, b) in zip(good, good[1:]) if b < a]
    for t0, a, b in ep[:4]:
        print(f"     dec @ {time.strftime('%Y-%m-%d %H:%M', time.gmtime(t0))}Z {a:.6f} -> {b:.6f}")
    decs.sort()
    top = decs[-5:][::-1]
    gv = sorted({round(v, 6) for _, v in glitch})[:5]
    print(f"  {name:28s} n={len(good):6d} decreases={len(decs):4d} max_dec_MWh={max(decs) if decs else 0:.6f} "
          f"top={['%.6f' % d for d in top]} max_inc_MWh={max(incs) if incs else 0:.4f} glitch_reads={len(glitch)} glitch_values={gv}")
print("== long-term statistics (hourly state), last 90 days")
for s in SENS:
    eid = PFX + s
    r = c.execute("select m.id from statistics_meta m where m.statistic_id=?", (eid,)).fetchone()
    if not r:
        print("  ", s, "no statistics"); continue
    rows = c.execute("select start_ts, state from statistics where metadata_id=? and start_ts>? order by start_ts",
                     (r[0], now - 90 * 86400)).fetchall()
    summarize(s, rows)
print("== raw states (recorder retention)")
for s in SENS:
    eid = PFX + s
    rows = c.execute("""select s.last_updated_ts, s.state from states s join states_meta sm on s.metadata_id=sm.metadata_id
                        where sm.entity_id=? order by s.last_updated_ts""", (eid,)).fetchall()
    vals = []
    for t, v in rows:
        try: vals.append((t, float(v)))
        except (TypeError, ValueError): pass
    summarize(s, vals)
