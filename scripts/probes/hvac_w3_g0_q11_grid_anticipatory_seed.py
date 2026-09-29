"""HVAC W3 G0-Q11 — grid-anticipatory pre-cool seed (EC-GRID-ANTICIPATORY-PRECOOL-GAP-1 stays parked).

Q11: For days in the recorder window (reaches back only to ~09-21; a run before 10-01 cannot include
09-29/30), count days with pre_cool_skip_reason == no_pv_surplus at any tick inside 10-14 local AND an
EC forecast high >= 90 F that day. Forecast source: any *forecast_high* attribute on the HVAC mode
sensor if present, else sensor.ura_energy_coordinator_weather_apparent_forecast_high (APPARENT high —
noted as a caveat).
READ-ONLY (mode=ro), stdout only. Run: ssh ha "python3 -" < scripts/probes/hvac_w3_g0_q11_grid_anticipatory_seed.py
"""
import sqlite3, json, collections
from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Chicago")
REC = "file:/config/home-assistant_v2.db?mode=ro"
c = sqlite3.connect(REC, uri=True)
print("opened:", REC)

def rows(e, attrs=True):
    m = c.execute("SELECT metadata_id FROM states_meta WHERE entity_id=?", (e,)).fetchone()
    q = ("SELECT s.last_updated_ts, s.state, sa.shared_attrs FROM states s LEFT JOIN state_attributes sa "
         "ON s.attributes_id=sa.attributes_id WHERE s.metadata_id=? ORDER BY 1")
    return [(t, s, json.loads(a) if a else {}) for t, s, a in c.execute(q, (m[0],))]

mode = rows("sensor.ura_hvac_coordinator_mode")
print("mode sensor earliest:", datetime.fromtimestamp(mode[0][0], TZ), "rows", len(mode))
fc_keys = sorted({k for _, _, a in mode for k in a if "forecast" in k})
print("forecast-like attrs on mode sensor:", fc_keys)
day = collections.defaultdict(lambda: {"reasons": collections.Counter(), "fc": None})
for t, s, a in mode:
    dl = datetime.fromtimestamp(t, TZ)
    if 10 <= dl.hour < 14:
        day[dl.date()]["reasons"][a.get("pre_cool_skip_reason")] += 1
fce = rows("sensor.ura_energy_coordinator_weather_apparent_forecast_high")
for t, s, a in fce:
    try: v = float(s)
    except (TypeError, ValueError): continue
    d = datetime.fromtimestamp(t, TZ).date()
    day[d]["fc"] = max(day[d]["fc"] or v, v)
seed = 0
for d in sorted(day):
    r = day[d]; hit = r["reasons"].get("no_pv_surplus", 0) > 0 and (r["fc"] or 0) >= 90
    seed += hit
    print(f"  {d}: 10-14 skip reasons={dict(r['reasons'])} apparent_forecast_high={r['fc']} -> {'SEED' if hit else '-'}")
print(f"seed days: {seed}")
