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

## Live validation (prospective)

- Both entities exist on the Energy Coordinator device with numeric kWh states.
- During off-peak overnight charging, the grid sensor rises and the sun sensor stays flat; at midday
  solar charging, the sun sensor rises.
- grid + sun + `unsplit_kwh_today` roughly matches the day's battery charge energy from the Envoy.
- After an HA restart during the day, the values carry on from where they were, not from zero.
- Just after local midnight, both read 0.
