"""HVAC W3 G0-Q1 — TOU truth.

Q1 (per plan review H1/H2): (b) sensor sanity — over the last 7 days of
sensor.ura_energy_coordinator_tou_period, do observed transitions land on the tariff boundaries
(14/16/20/21 summer) within one EC update interval (<= 10 min)? Transitions OUT OF unknown/unavailable
(restart artifacts) are excluded. No weekday/weekend clause: the tariff has no day types.
Plus: does every energy_history row's tou_period match the tariff for its LOCAL time (timestamp
converted to America/Chicago; the UTC-derived calendar columns are never read)? tou_file_status == ok?
The real engine check is offline: hvac_w3_g0_q1_engine_offline.py (Q1a).

Oracle: the operator-stated tariff (PEC), hard-coded below independently of the engine.
READ-ONLY: both DBs opened mode=ro; stdout only.
Run: ssh ha "python3 -" < scripts/probes/hvac_w3_g0_q1_tou_truth.py
"""
import json, sqlite3, collections
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Chicago")
REC = "file:/config/home-assistant_v2.db?mode=ro"
URA = "file:/config/universal_room_automation/data/universal_room_automation.db?mode=ro"

# Independent oracle (operator-stated PEC tariff), NOT read from the engine.
TARIFF = {
    "summer": ({6, 7, 8, 9}, [("off_peak", 0, 14), ("mid_peak", 14, 16), ("peak", 16, 20), ("mid_peak", 20, 21), ("off_peak", 21, 24)]),
    "shoulder": ({3, 4, 5, 10, 11}, [("off_peak", 0, 17), ("mid_peak", 17, 21), ("off_peak", 21, 24)]),
    "winter": ({12, 1, 2}, [("off_peak", 0, 5), ("mid_peak", 5, 9), ("off_peak", 9, 17), ("mid_peak", 17, 21), ("off_peak", 21, 24)]),
}

def period_at(dt_local):
    for season, (months, spans) in TARIFF.items():
        if dt_local.month in months:
            for p, a, b in spans:
                if a <= dt_local.hour < b:
                    return p
    return None

def expected_transitions(day):
    """[(local datetime, from, to)] for a local date."""
    out = []
    for season, (months, spans) in TARIFF.items():
        if day.month in months:
            for i in range(1, len(spans)):
                if spans[i][0] != spans[i - 1][0]:
                    out.append((datetime(day.year, day.month, day.day, spans[i][1], tzinfo=TZ), spans[i - 1][0], spans[i][0]))
    return out

rec = sqlite3.connect(REC, uri=True)
ura = sqlite3.connect(URA, uri=True)
print("opened:", REC, "|", URA)

# ---- Part A: recorder, last 7 days ----
mid = rec.execute("SELECT metadata_id FROM states_meta WHERE entity_id='sensor.ura_energy_coordinator_tou_period'").fetchone()[0]
rows = rec.execute(
    "SELECT s.state, s.last_updated_ts, sa.shared_attrs FROM states s LEFT JOIN state_attributes sa "
    "ON s.attributes_id=sa.attributes_id WHERE s.metadata_id=? ORDER BY s.last_updated_ts", (mid,)).fetchall()
print(f"\n[A] recorder tou_period rows={len(rows)} earliest={datetime.fromtimestamp(rows[0][1], TZ)} latest={datetime.fromtimestamp(rows[-1][1], TZ)}")
fstat = collections.Counter()
for st, ts, attrs in rows:
    try:
        fstat[json.loads(attrs).get("tou_file_status") if attrs else None] += 1
    except Exception:
        fstat["<bad-json>"] += 1
print("tou_file_status distribution over rows:", dict(fstat))
print("state distribution:", dict(collections.Counter(r[0] for r in rows)))

# observed transitions between valid periods (skip unavailable/unknown gaps but keep last valid)
valid = {"off_peak", "mid_peak", "peak"}
TOL = 600  # one EC update interval (review H1)
obs = []; restart_edges = 0
prev = None; raw_prev = None
for st, ts, _ in rows:
    if st not in valid:
        raw_prev = st
        continue
    if prev is not None and st != prev:
        if raw_prev in valid:
            obs.append((datetime.fromtimestamp(ts, TZ), prev, st))
        else:
            restart_edges += 1  # transition out of unknown/unavailable: excluded
    prev = st; raw_prev = st
first_day = datetime.fromtimestamp(rows[0][1], TZ).date()
last_day = datetime.fromtimestamp(rows[-1][1], TZ).date()
matched = 0; unmatched = []
exp_all = []
d = first_day
while d <= last_day:
    exp_all += expected_transitions(d)
    d += timedelta(days=1)
used = set()
for t, a, b in obs:
    hit = None
    for i, (et, ea, eb) in enumerate(exp_all):
        if i not in used and ea == a and eb == b and abs((t - et).total_seconds()) <= TOL:
            hit = i; break
    if hit is None:
        unmatched.append((t.isoformat(), a, b))
    else:
        used.add(hit); matched += 1
first_ts = datetime.fromtimestamp(rows[0][1], TZ); last_ts = datetime.fromtimestamp(rows[-1][1], TZ)
exp_in_window = [(i, e) for i, e in enumerate(exp_all) if first_ts <= e[0] <= last_ts]
missed = [(e[0].isoformat(), e[1], e[2]) for i, e in exp_in_window if i not in used]
print(f"observed transitions={len(obs)} matched(<=10min)={matched} unmatched={len(unmatched)} | excluded transitions out of unknown/unavailable={restart_edges}")
lat = []
for i in used:
    et = exp_all[i][0]
    t = next(o[0] for o in obs if o[1] == exp_all[i][1] and o[2] == exp_all[i][2] and abs((o[0] - et).total_seconds()) <= TOL)
    lat.append((t - et).total_seconds())
if lat:
    print(f"lag vs boundary (s): min={min(lat):.0f} max={max(lat):.0f}")
print("unmatched observed:", unmatched)
print(f"expected-in-window={len(exp_in_window)} missed (no observed edge within 10 min):", missed)
for t, a, b in obs:
    print("   ", t.strftime("%a %m-%d %H:%M:%S"), a, "->", b)

# ---- Part B: URA energy_history, full retention, per-row label vs oracle ----
eh = ura.execute("SELECT timestamp, tou_period FROM energy_history ORDER BY timestamp").fetchall()
print(f"\n[B] energy_history rows={len(eh)} earliest={eh[0][0]}Z latest={eh[-1][0]}Z (timestamps are naive UTC; database.py:2697)")
per_month = collections.defaultdict(lambda: [0, 0, 0])  # rows, match, null
mism = []
for ts, p in eh:
    dl = datetime.fromisoformat(ts).replace(tzinfo=timezone.utc).astimezone(TZ)
    m = per_month[dl.strftime("%Y-%m")]
    m[0] += 1
    if p is None:
        m[2] += 1; continue
    exp = period_at(dl)
    if p == exp:
        m[1] += 1
    else:
        # boundary-straddle tolerance: row written within 5 min after a boundary may carry the previous label
        prev_exp = period_at(dl - timedelta(minutes=5))
        if p == prev_exp:
            m[1] += 1
        else:
            mism.append((dl.isoformat(), p, exp))
for k in sorted(per_month):
    r, ok, nul = per_month[k]
    print(f"  {k}: rows={r} match={ok} null={nul} mismatch={r-ok-nul}")
print("total mismatches:", len(mism), "first 15:", mism[:15])
# Apr-May first mid_peak row per day (should land 17:00-17:15 local)
first_mid = {}
for ts, p in eh:
    dl = datetime.fromisoformat(ts).replace(tzinfo=timezone.utc).astimezone(TZ)
    if dl.month in (4, 5) and dl.year == 2026 and p == "mid_peak":
        first_mid.setdefault(dl.date(), dl)
hrs = collections.Counter(v.strftime("%H") for v in first_mid.values())
print("Apr-May 2026: first mid_peak row hour-of-day (local) distribution:", dict(hrs), "days=", len(first_mid))
last_mid = {}
for ts, p in eh:
    dl = datetime.fromisoformat(ts).replace(tzinfo=timezone.utc).astimezone(TZ)
    if dl.month in (4, 5) and dl.year == 2026 and p == "mid_peak":
        last_mid[dl.date()] = dl
print("Apr-May 2026: last mid_peak row hour (local):", dict(collections.Counter(v.strftime('%H') for v in last_mid.values())))
