# v5.103.97: zone power and energy include zone-level loads

Card: ZONE-LIVE-POWER-ROLLUP-1. Tier 1-2, one review (SHIP after fix-up). Deploy risk: LOW (display sensors only; no actuation).

## Problem
Zone sensors (`sensor.zone_<name>_total_power`, `_energy_today`, `_cost_per_hour`, `_energy_cost_today`) summed only their rooms. The zone-level config fields were ignored: `zone_power_sensors` had no reader, and `zone_energy_sensors` (e.g. the zone AC circuits) fed only the house coverage total.

## Fix
- All four zone sensors add the zone's own loads on top of the rooms, skipping any entity already in any room's list or counted by another zone (one entity counts once; a two-zone listing counts in the zone whose name sorts first). Unavailable sensors are skipped, never zeroing the sum. kW/Wh converted.
- Zone kWh treats a reading ≤1000 kWh as a today counter and above as a lifetime counter (today's increase only), mirroring house coverage.
- Zone energy survives a mid-day restart (RestoreEntity extra data: last value, date, per-sensor baselines); a new day starts fresh. Cost today restores baselines only (its value follows the TOU rate).
- Attributes split room vs zone-level contributions. Options label for zone power sensors updated.

## Tests
`test_zone_power_rollup.py` (31), 24 mutation drills RED. Full-suite name-diff vs e3c75a99: 0 new failures.

## Known limits
- House coverage still doesn't skip room overlap in its zone tier (zone sensors now do); they can disagree for overlapping config.
- `zone_power_sensors` is still hidden in the options form unless Advanced mode or already set; filling it with the zone AC circuits is a config step after deploy.

## Live acceptance (prospective)
| Criterion | How to check |
|---|---|
| Zone-level loads counted | A zone with zone_energy_sensors: `zone_level_energy_kwh` attribute > 0 and value = rooms + zone-level |
| No double count | `zone_level_skipped_room_overlap` lists any entity also in a room |
| Restart safe | Zone energy today after a restart ≥ value before |
| Load clean | No URA ERROR after restart |
