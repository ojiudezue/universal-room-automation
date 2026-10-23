# v5.103.83 — Energy coverage audit reads TOTAL house consumption

> DRAFT. The version may change at deploy.

Card: COVERAGE-EVENING-ATTRIBUTION-DRIFT-1 (Tier 1-2, display/audit only).

## Problem
`sensor.universal_room_automation_energy_coverage_delta` computes
unattributed = whole house - sum(rooms, zones, house devices). Its whole-house
input came from `whole_house_energy_sensors`, which is live-configured to
`sensor.envoy_482543015950_lifetime_net_energy_consumption`. That is Envoy NET
consumption: grid import, net of the solar the house used itself. Coverage needs
TOTAL consumption. On sunny afternoons the net figure flattens while rooms keep
accumulating, so the parts exceed the whole and `delta_percent` walks steadily
negative from about 14:00 to midnight. The 2026-09-23 measurement confirmed it:
total minus net = production minus export, to five decimal places.

## Change
- The coverage sensor now prefers the Energy Coordinator's existing total entity
  (`CONF_ENERGY_LIFETIME_CONSUMPTION_ENTITY`, an explicit setting or the
  serial-derived default `sensor.envoy_<serial>_lifetime_energy_consumption`),
  already resolved on `EnergyCoordinator._entity_lifetime_consumption`. New helper:
  `EnergyCoverageDeltaSensor._resolve_whole_house_sources` (aggregation.py).
- Fallback: if there is no EC, no total entity, or the entity is not in the state
  machine, the sensor uses `whole_house_energy_sensors` as before. A total entity
  that exists but is unavailable stays selected and shows "No data". It is not
  swapped to NET mid-day.
- New attribute `whole_house_source`: `ec_total` | `whole_house_energy_sensors`.
- Unchanged: the shared field, `WholeHouseEnergySensor`, `WholeHouseCostTodaySensor`
  (still NET), unit normalization, no-data handling, and the 120-min midnight
  re-anchor window.
- Anchor at the switch: baselines are keyed per sensor id and held in memory. The
  first read after the upgrade anchors the total counter fresh, which matches
  normal post-restart behaviour (`post_restart_window` already covers the gap).
- Comment-only: energy.py comments that said lifetime_energy_consumption = net
  import now say it is TOTAL on this Envoy.

No new config field and no new knob.

## Tests
`quality/tests/test_coverage_whole_house_total_source.py` (6 tests) drives the
real sensor with separate NET (+3 kWh) and TOTAL (+10 kWh) counters: EC total is
used (delta 6, not -1); fallback when EC is absent, has no entity, or the entity
is missing; unavailable total stays on `ec_total`; the cost sensor still reads NET.
Mutation drills: neutering the EC branch, reverting the call site, or dropping the
states guard each turns specific tests RED.

## Live acceptance (prospective)
- `sensor.universal_room_automation_energy_coverage_delta` attribute
  `whole_house_source` = `ec_total`.
- On a sunny afternoon, `delta_percent` does not walk steadily negative from
  14:00 to 23:00. Under the old bug it fell from about -10% to -59% (2026-09-21).
- The attribute `whole_house` tracks the daily rise of
  `sensor.envoy_482543015950_lifetime_energy_consumption`, not of the net sensor.
- `sensor.universal_room_automation_whole_house_cost_today` is unchanged (still NET-based).
- After a CM reload, `whole_house_source` returns to `ec_total` and coverage does not
  publish a NET-based value. A source switch yields one no-data cycle (debug log
  "whole-house source switched"), then TOTAL reads against a baseline anchored at
  the switch.
