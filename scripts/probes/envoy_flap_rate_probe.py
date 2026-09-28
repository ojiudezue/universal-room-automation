#!/usr/bin/env python3
"""Envoy native-integration flap rate — READ-ONLY. Card ENVOY-FLAKINESS-181243-1.
    ssh ha "python3 -" < scripts/probes/envoy_flap_rate_probe.py
Counts unavailable-transitions of sensor.envoy_482543015950_battery per local day, plus
since the most recent HA core start (recorder_runs). Discriminator for the 2026.9.4 upgrade:
baseline 110-160 down-events/day (09-18..09-25); "fixed" = <= 5/day over >= 2 full days.
"""
import sqlite3, datetime as dt, collections
E = 'sensor.envoy_482543015950_battery'
CDT = dt.timezone(dt.timedelta(hours=-5))
r = sqlite3.connect('file:/config/home-assistant_v2.db?mode=ro', uri=True)
rows = r.execute("SELECT s.state, s.last_updated_ts FROM states s JOIN states_meta m ON s.metadata_id=m.metadata_id "
                 "WHERE m.entity_id=? ORDER BY 2", (E,)).fetchall()
start = r.execute("SELECT max(start) FROM recorder_runs").fetchone()[0]
start_ts = dt.datetime.fromisoformat(start).replace(tzinfo=dt.timezone.utc).timestamp() if start else 0
per_day, prev, since, longest = collections.Counter(), None, 0, collections.defaultdict(float)
down_at = None
for s, t in rows:
    d = dt.datetime.fromtimestamp(t, CDT).strftime('%m-%d')
    if s == 'unavailable' and prev not in (None, 'unavailable'):
        per_day[d] += 1; down_at = t
        if t >= start_ts: since += 1
    if s != 'unavailable' and prev == 'unavailable' and down_at:
        longest[d] = max(longest[d], t - down_at); down_at = None
    prev = s
print('core start (UTC):', start)
for d in sorted(per_day): print(f'{d}: {per_day[d]:4d} down-events  longest outage {longest[d]/60:6.1f} min')
hrs = (dt.datetime.now().timestamp() - start_ts) / 3600
print(f'since core start: {since} down-events in {hrs:.1f} h  (~{since/hrs*24 if hrs else 0:.0f}/day pace)')
print('current state:', rows[-1][0] if rows else None)
