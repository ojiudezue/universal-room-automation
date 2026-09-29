#!/usr/bin/env python3
"""Consumption-forecast poisoning probe — READ-ONLY. Card ENERGY-CONSUMPTION-FORECAST-POISONED-1.
    ssh ha "python3 -" < scripts/probes/energy_consumption_forecast_poison_probe.py

Sections:
  A. energy_daily implausible rows (consumption > 1000 kWh or solar > 300 kWh).
  B. Discriminator: for each poisoned row D, is solar_production_kwh == (P(D+1 00:00) - 0.045505) * 1000,
     where P = sensor.envoy_*_lifetime_energy_production (MWh) from recorder long-term statistics?
     I.e. the midnight snapshot captured the Envoy's 0.045505 MWh glitch value, so the "daily" delta
     equals the lifetime counter. Alternative (card) hypothesis = random spike -> would not match.
  C. Window membership: which poisoned rows sit inside each consumer window right now
     (DOW deque: get_consumption_history LIMIT 60 non-null rows, maxlen 8 / DOW;
      temp regression: LIMIT 90 rows w/ temp; accuracy restore: LIMIT 30, filter only < 10 kWh).
  D. Re-simulate the legacy (consumed) estimator per DOW with and without poisoned rows
     (replicates energy.py _fit_temp_regression + energy_forecast._compute_legacy).
  E. Forecast sensor history (recorder) — predicted_consumption_kwh range.
  F. DP (Battery-Aware EV Charging) eval snapshots: did house_load_kw == predicted_consumption/24
     (i.e. max() picked the forecast over SPAN)? Counterfactual decision with SPAN-only load.
"""
import sqlite3, json, datetime as dt, collections

URA = 'file:/config/universal_room_automation/data/universal_room_automation.db?mode=ro'
REC = 'file:/config/home-assistant_v2.db?mode=ro'
CDT = dt.timezone(dt.timedelta(hours=-5))
GLITCH = 0.045505
PROD_STAT = 'sensor.envoy_482543015950_lifetime_energy_production'
u = sqlite3.connect(URA, uri=True)
r = sqlite3.connect(REC, uri=True)


def local_ts(s):
    return dt.datetime.fromisoformat(s).replace(tzinfo=CDT).timestamp()


rows = u.execute("SELECT date, consumption_kwh, solar_production_kwh, avg_temperature, "
                 "predicted_consumption_kwh, prediction_error_pct FROM energy_daily ORDER BY date").fetchall()
bad = [x for x in rows if (x[1] is not None and x[1] > 1000) or (x[2] is not None and x[2] > 300)]
print('== A. energy_daily: %d rows, %d null consumption, %d implausible' %
      (len(rows), sum(1 for x in rows if x[1] is None), len(bad)))
for x in bad:
    print('  %s consumption=%.1f solar=%.1f' % (x[0], x[1], x[2] or 0))

print('\n== B. discriminator: solar_production_kwh vs (lifetime_production(D+1 00:00) - glitch)*1000')
mid = r.execute("SELECT id FROM statistics_meta WHERE statistic_id=?", (PROD_STAT,)).fetchone()[0]


def stat_at_midnight(date_str):
    # statistics row whose hour STARTS at 23:00 the previous day ends at date 00:00; state = end-of-hour value
    d = dt.date.fromisoformat(date_str)
    start = local_ts((d - dt.timedelta(days=1)).isoformat() + 'T23:00:00')
    v = r.execute("SELECT state FROM statistics WHERE metadata_id=? AND start_ts=?", (mid, start)).fetchone()
    return v[0] if v else None


for x in bad:
    d = dt.date.fromisoformat(x[0])
    snap = stat_at_midnight(x[0])
    cur = stat_at_midnight((d + dt.timedelta(days=1)).isoformat())
    pred_solar = (cur - GLITCH) * 1000 if cur is not None else None
    print('  %s P(D 00:00)=%s  P(D+1 00:00)=%s  predicted_solar=%s  stored_solar=%.1f  match=%s' % (
        x[0], snap, cur, None if pred_solar is None else round(pred_solar, 1), x[2],
        None if pred_solar is None else abs(pred_solar - x[2]) < 0.5))
g = r.execute("SELECT count(*), min(start_ts), max(start_ts) FROM statistics WHERE metadata_id=? AND state < 1.0",
              (mid,)).fetchone()
print('  glitch hours (state<1 MWh) in LTS: %d, %s .. %s' % (
    g[0], dt.datetime.fromtimestamp(g[1], CDT), dt.datetime.fromtimestamp(g[2], CDT)))
others = r.execute("SELECT m.statistic_id, count(*) FROM statistics s JOIN statistics_meta m ON s.metadata_id=m.id "
                   "WHERE m.statistic_id LIKE 'sensor.envoy_482543015950_lifetime%' AND m.unit_of_measurement='MWh' "
                   "AND s.state < 1.0 GROUP BY 1").fetchall()
print('  lifetime MWh sensors with any state<1 hour:', others)

print('\n== C. window membership (now)')
nonnull = [x for x in reversed(rows) if x[1] is not None]           # DESC
dow_window = nonnull[:60]
paired = [x for x in nonnull if x[3] is not None][:90]
acc = nonnull[:30]
for x in bad:
    dd = dt.date.fromisoformat(x[0])
    same_dow = [y for y in dow_window if dt.date.fromisoformat(y[0]).weekday() == dd.weekday()]
    in_deque = x in same_dow[:8]
    print('  %s (%s): in DOW-60 window=%s, in that DOW deque(8)=%s, in regression-90=%s, in accuracy-30=%s' % (
        x[0], dd.strftime('%a'), x in dow_window, in_deque, x in paired, x in acc))

print('\n== D. legacy estimator re-simulation (adj factor excluded; multiply by live adj ~0.803)')


def fit(pairs):
    n = len(pairs)
    if n < 30:
        return None
    xs = [abs(t - 72.0) for _, t in pairs]
    ys = [c for c, _ in pairs]
    sx, sy = sum(xs), sum(ys)
    sxy = sum(a * b for a, b in zip(xs, ys)); sx2 = sum(a * a for a in xs)
    den = n * sx2 - sx * sx
    if abs(den) < 1e-10:
        return None
    b = (n * sxy - sx * sy) / den
    return (sy - b * sx) / n, b


def deques(win):
    dq = {k: collections.deque(maxlen=8) for k in range(7)}
    for x in reversed(win):                         # oldest first
        dq[dt.date.fromisoformat(x[0]).weekday()].append(x[1])
    return dq


poison_dates = {x[0] for x in bad}
reg_p = fit([(x[1], x[3]) for x in paired])
reg_c = fit([(x[1], x[3]) for x in [y for y in nonnull if y[3] is not None and y[0] not in poison_dates][:90]])
dq_p = deques(dow_window)
dq_c = deques([x for x in nonnull if x[0] not in poison_dates][:60])
print('  regression poisoned: base=%.1f coeff=%.2f   clean: base=%.1f coeff=%.2f' % (reg_p + reg_c))
for dow in range(7):
    bp = sum(dq_p[dow]) / len(dq_p[dow]); bc = sum(dq_c[dow]) / len(dq_c[dow])
    line = []
    for t in (60, 72, 85, 95):
        pp = 0.7 * (reg_p[0] + reg_p[1] * abs(t - 72)) + 0.3 * bp
        pc = 0.7 * (reg_c[0] + reg_c[1] * abs(t - 72)) + 0.3 * bc
        line.append('%dF %.0f/%.0f' % (t, pp, pc))
    print('  %s baseline poisoned=%.0f clean=%.0f | pred poisoned/clean: %s' % (
        ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'][dow], bp, bc, ', '.join(line)))

print('\n== E. forecast sensor history (recorder)')
fs = r.execute("SELECT s.last_updated_ts, a.shared_attrs FROM states s JOIN states_meta m ON s.metadata_id=m.metadata_id "
               "LEFT JOIN state_attributes a ON a.attributes_id=s.attributes_id "
               "WHERE m.entity_id='sensor.ura_energy_coordinator_energy_forecast_today' ORDER BY 1").fetchall()
pcs = []
for t, a in fs:
    try:
        j = json.loads(a or '{}')
    except ValueError:
        continue
    if j.get('predicted_consumption_kwh') is not None:
        pcs.append((t, j['predicted_consumption_kwh'], j.get('shadow_predicted_consumption_kwh')))
print('  %d valued states since %s; predicted_consumption min=%.1f max=%.1f; shadow v1 min=%s max=%s' % (
    len(pcs), dt.datetime.fromtimestamp(pcs[0][0], CDT), min(p[1] for p in pcs), max(p[1] for p in pcs),
    min(p[2] for p in pcs if p[2]), max(p[2] for p in pcs if p[2])))
print('  latest: %s predicted_consumption=%.1f shadow_v1=%s' % (
    dt.datetime.fromtimestamp(pcs[-1][0], CDT), pcs[-1][1], pcs[-1][2]))

print('\n== F. DP eval snapshots (sensor.ura_energy_coordinator_ev_charging_plan)')
ev = r.execute("SELECT a.shared_attrs FROM states s JOIN states_meta m ON s.metadata_id=m.metadata_id "
               "LEFT JOIN state_attributes a ON a.attributes_id=s.attributes_id "
               "WHERE m.entity_id='sensor.ura_energy_coordinator_ev_charging_plan' ORDER BY s.last_updated_ts").fetchall()
span = {}
for eid in ('sensor.span_panel_current_power', 'sensor.span_panel_current_power_2'):
    span[eid] = r.execute("SELECT s.last_updated_ts, s.state FROM states s JOIN states_meta m ON s.metadata_id=m.metadata_id "
                          "WHERE m.entity_id=? AND s.state NOT IN ('unavailable','unknown') ORDER BY 1", (eid,)).fetchall()


def asof(series, ts):
    lo, hi, best = 0, len(series) - 1, None
    while lo <= hi:
        mid_ = (lo + hi) // 2
        if series[mid_][0] <= ts:
            best = series[mid_]; lo = mid_ + 1
        else:
            hi = mid_ - 1
    return float(best[1]) if best else None


def pc_asof(ts):
    best = None
    for t, p, _ in pcs:
        if t <= ts:
            best = p
        else:
            break
    return best


seen, evals = set(), []
for (a,) in ev:
    try:
        j = json.loads(a or '{}')
    except ValueError:
        continue
    for key, kind in (('last_eval_snapshot', 'real'), ('shadow_last_eval_snapshot', 'shadow')):
        snap = j.get(key) or {}
        inp, dec = snap.get('inputs'), snap.get('decision')
        if not inp or not dec:
            continue
        k = (kind, inp.get('now'))
        if k in seen:
            continue
        seen.add(k); evals.append((kind, inp, dec))
reasons = collections.Counter((k, d.get('reason')) for k, _, d in evals)
print('  distinct evals: %d  reasons: %s' % (len(evals), dict(reasons)))
forecast_won = 0
for kind, inp, dec in evals:
    ts = dt.datetime.fromisoformat(inp['now']).timestamp()
    pc = pc_asof(ts)
    s1, s2 = asof(span['sensor.span_panel_current_power'], ts), asof(span['sensor.span_panel_current_power_2'], ts)
    live_kw = None
    if s1 is not None or s2 is not None:
        live_kw = max(0.0, ((s1 or 0) + (s2 or 0) - inp['charger_rate_kw'] * 1000) / 1000)
    fw = pc is not None and abs(inp['house_load_kw'] - pc / 24) < 0.02
    forecast_won += fw
    line = '  [%s] %s soc=%s tgt=%s load=%.2f fc/24=%s span_live=%s forecast_won=%s reason=%s' % (
        kind, inp['now'][:16], inp['soc'], inp['drain_target_soc'], inp['house_load_kw'],
        None if pc is None else round(pc / 24, 2), None if live_kw is None else round(live_kw, 2), fw, dec.get('reason'))
    if dec.get('drain_hours') is not None and live_kw:
        # counterfactual: same arithmetic with SPAN-only load
        cap_pp = (inp['soc'] - inp['drain_target_soc'])
        ratio = inp['house_load_kw'] / live_kw
        line += ' drain_h=%.2f -> span-only drain_h=%.2f (x%.1f)' % (dec['drain_hours'], dec['drain_hours'] * ratio, ratio)
    print(line)
print('  evals where forecast/24 was the house_load (max() picked forecast): %d / %d' % (forecast_won, len(evals)))

print('\n== G. historic dp_eval "fits" rows (URA decision_log) — counterfactual with SPAN-only house load')
# decision_log.dp_eval context does NOT carry house_load_kw; reconstruct it from recorder LTS hourly means:
#   forecast arm = mean(sensor.ura_energy_coordinator_forecasted_consumption)/24, SPAN arm = mean(span r1+r2) - ev_load.
# needed_kwh is NOT logged either -> assume 25 kWh (the live per-EVSE knob value seen in the 09-29 snapshot).
# Approximate (hourly means); treat flips as indicative, not proof.
NEEDED, CAP_PP, MARGIN_H = 25.0, 0.40, 1.0
lts = {}
for sid in ('sensor.ura_energy_coordinator_forecasted_consumption', 'sensor.span_panel_current_power',
            'sensor.span_panel_current_power_2'):
    m_ = r.execute("SELECT id FROM statistics_meta WHERE statistic_id=?", (sid,)).fetchone()
    lts[sid] = dict(r.execute("SELECT start_ts, mean FROM statistics WHERE metadata_id=?", (m_[0],)).fetchall()) if m_ else {}
dl = u.execute("SELECT context_json FROM decision_log WHERE decision_type='dp_eval' "
               "AND json_extract(context_json,'$.reason') IN ('fits','does_not_fit') ORDER BY id").fetchall()
tot = consistent = flips = fc_higher = 0
CLEAN_KWH = (120.0, 150.0, 180.0)   # clean-forecast counterfactual (shadow v1 ranged 126-175 kWh)
clean_flips = collections.Counter()
nights = collections.Counter()
for (cj,) in dl:
    c = json.loads(cj)
    tot += 1
    soc, tgt, rate = c.get('soc'), c.get('drain_target_soc'), c.get('charger_rate_kw') or 0
    if soc is None or tgt is None or soc <= tgt or rate <= 0:
        continue                                   # logged reason inconsistent with eval order -> not a fresh arithmetic eval
    consistent += 1
    now = dt.datetime.fromisoformat(c['now_iso'])
    h = (int(now.timestamp()) // 3600) * 3600
    fc = lts['sensor.ura_energy_coordinator_forecasted_consumption'].get(h)
    s1 = lts['sensor.span_panel_current_power'].get(h); s2 = lts['sensor.span_panel_current_power_2'].get(h)
    if fc is None or (s1 is None and s2 is None):
        continue
    span_kw = max(0.0, ((s1 or 0) + (s2 or 0) - (c.get('ev_load_w') or 0)) / 1000)
    load_used = max(fc / 24, span_kw)
    if fc / 24 > span_kw:
        fc_higher += 1

    def fits(load):
        if load <= 0:
            return False
        dh = (soc - tgt) * CAP_PP / load
        msb = now.replace(hour=3, minute=0, second=0, microsecond=0)
        if msb <= now:
            msb += dt.timedelta(days=1)
        eon = msb.replace(hour=6)
        return (now + dt.timedelta(hours=dh) <= msb and
                dh + NEEDED / rate + MARGIN_H <= (eon - now).total_seconds() / 3600)
    for ck in CLEAN_KWH:
        if fits(load_used) and not fits(max(span_kw, ck / 24)):
            clean_flips[ck] += 1
    if fits(load_used) and not fits(span_kw):
        flips += 1; nights[now.strftime('%m-%d')] += 1
        print('    flip: %s state=%s soc=%s tgt=%s rate=%.1fkW fc/24=%.2f span=%.2f' % (
            c['now_iso'][:16], c.get('state'), soc, tgt, rate, fc / 24, span_kw))
print('  dp_eval fits/does_not_fit rows: %d; arithmetic-consistent (soc>target, rate>0): %d' % (tot, consistent))
print('  of consistent rows with LTS coverage: forecast/24 > SPAN in %d; verdict flips fits->does_not_fit under SPAN-only: %d %s' % (
    fc_higher, flips, dict(nights)))
print('  CORRECT counterfactual = max(SPAN, CLEAN forecast/24) (the max() is by design; only the forecast is poisoned):')
print('  verdict flips fits->does_not_fit with clean forecast of 120/150/180 kWh: %s' % dict((k, clean_flips[k]) for k in CLEAN_KWH))
