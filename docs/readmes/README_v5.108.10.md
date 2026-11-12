# v5.108.10 — Battery charge source, per day

Card: EC-BATTERY-CHARGE-SOURCE-DAY-1 (Tier 1).

## What

Two new Energy Coordinator sensors show how much the battery charged from the grid and from the
sun since local midnight:

- `sensor.ura_energy_coordinator_battery_charged_from_grid_today` (kWh)
- `sensor.ura_energy_coordinator_battery_charged_from_sun_today` (kWh)

Both carry `unsplit_kwh_today` (charge while grid net power was unknown, so it could not be split)
and the latest tick's live split, `grid_charge_kw` and `solar_charge_kw` (None when net was
unknown). The dashboard can read these instead of computing its own split.

## Why

The EC already splits every battery-charge tick into grid and solar (grid = the smaller of charge
and grid import) to cost the arbitrage inventory. That split was never shown as a daily total. This
release sums it; the split maths is unchanged.

## How

The totals live in `PeakAvoidanceTracker` next to its other "today" values. They reset with them at
local midnight (the date of `dt_util.now()`, not the Envoy `*_today` counters, which roll at UTC
midnight) and persist in the existing `peak_avoidance_snapshot`, so a restart during the day keeps
them and a snapshot from an earlier day is dropped.

Tests: `quality/tests/test_ec_battery_charge_source_day.py`.

## Validated 2026-11-11 (after the 19:24 CST restart)

| Criterion | Result | Evidence |
|---|---|---|
| Installed | PASS | `update.universal_room_automation_update` installed_version v5.108.10; installed manifest v5.108.10 |
| Both entities exist with numeric kWh states | PASS | `sensor.ura_energy_coordinator_battery_charged_from_grid_today` and `..._from_sun_today` = 0.0 kWh, device_class energy, state_class total_increasing |
| Sensors refresh from EC ticks | PASS | `grid_charge_kw` went null -> 0.0 within minutes of boot while the battery discharged 4.7 kW (no charge, so no split) |
| No URA ERROR after restart | PASS | system_log: URA entries are WARNING only (boot transients: sensors unavailable 60s hold, Bermuda polling fallback, census cameras not ready, zone-kWh seed warning, see below) |
| Grid rises overnight, sun rises midday | PASS (2026-11-12) | grid 0.0 -> 0.699 kWh overnight; sun 25.779 kWh by 12:05 CST with `solar_charge_kw` 10.42 |
| grid + sun + unsplit vs Envoy day charge | PASS (2026-11-12) | 25.779 + 0.699 + 0.0 = 26.48 kWh vs Envoy `lifetime_battery_energy_charged_2` since local midnight 7.95838 -> 7.984692 MWh = 26.31 kWh (+0.6%) |
| Same-day restart carries totals | in-suite only | `test_restore_same_day_keeps_totals`; the deploy restart happened with 0 kWh accrued |
| Midnight reset | in-suite only | `test_local_midnight_reset`; the 00:00 live check could not discriminate because both buckets were about 0 before midnight (they started at the 19:24 restart) |

Boot transient dismissed: "Zone-kWh seed UNRESOLVED" for all three HVAC zones. Probe: live and every recorded value since 11-04 is 0.8 kW (the default), the Numbers self-restore after the seed runs; wording-only issue, carded separately.

Dashboard: URA v8 Battery cards now read these sensors (backup `docs/dashboard-prototypes/ura-v8-backups/20261111T_pre_charge_source_sensors.json`).
