# v5.103.83 — Daily solar uses the production-CT counter

**Card:** EC-SOLAR-LIFETIME-COUNTER-FLAP-1 · **Tier:** 1 (energy accounting; no battery/reserve decision path touched)

## Problem
The Energy Coordinator computes each day's solar production (and the derived
`consumption_kwh` = grid import + solar produced − solar exported + battery net)
from day-start snapshots of Envoy lifetime counters. The derived default for
production was `sensor.envoy_{serial}_lifetime_energy_production`, which flaps
between its true value (~17–20.7 MWh) and 0.046 MWh: 32 drops in 686 hourly
samples since 2026-09-20 (the other lifetime legs had none). Of the last 40
`energy_daily` rows, 5 had `solar_production_kwh` silently `0.0` (both snapshots
caught at 0.046, which the D5a baseline check accepted) and 31 were NULL.
Consumption was understated on the 0.0 days, and that fed the forecast.

## Changes
1. **Derived default swapped** (`energy_const.py` `derive_envoy_config`):
   `CONF_ENERGY_LIFETIME_PRODUCTION_ENTITY` → `sensor.envoy_{serial}_production_ct_energy_delivered`
   (monotonic, MWh, agrees with the old counter when healthy). An explicit config
   value still wins. Every consumer (`__init__.py` setdefault injection,
   `repairs.py`, `validate_envoy_config`) goes through `derive_envoy_config`, so
   they all move together. The live config has no explicit override.
2. **Snapshot provenance** (`energy.py`): `_save_midnight_snapshot` records the
   entity the production snapshot came from in the existing `energy_state` KV
   store (key `lifetime_production_snapshot_entity`; no schema change). On
   restore, if the recorded entity is absent or differs from the current one,
   the production snapshot is set to `0.0` (D5a's "never seeded" value). That
   day's solar and derived consumption are then NULL instead of a cross-entity
   delta, and the next midnight re-seeds a clean baseline. Expect exactly one
   NULL solar day after deploy.
3. **Flap rejection** (`energy.py` `_production_not_flapped`): an in-memory
   high-water mark of the production reading (it only rises). A snapshot below
   `(1 − LIFETIME_PRODUCTION_MAX_DROP_FRACTION) × hwm` is rejected and the day
   is written NULL, not 0.0. Knob: `LIFETIME_PRODUCTION_MAX_DROP_FRACTION = 0.5`,
   rung 1 (module constant: a safety bound on a monotonic counter should need
   review to change; `1.0` disables it). A flapped *current* needs no separate
   check because it is already caught by the monotonic check or by the snapshot
   check.
4. `get_energy_summary()` now carries `lifetime_production_entity`.

## Backfill
`scripts/backfill_energy_daily_from_counters.py` repairs only `import_kwh` /
`export_kwh` / `billing_source` from the Emporia import/export counters. It
reads neither production counter and never writes `solar_production_kwh`, so
there was nothing to switch to the CT statistic. It is already dry-run by default
(`--apply` writes). Repairing past solar rows would need a new mode that reads
statistics id 5654 (`sensor.envoy_482543015950_production_ct_energy_delivered`)
and recomputes consumption from all five legs. That is not part of this cycle.
It was not run against the live DB.

## Tests
`quality/tests/test_ec_solar_ct_counter_flap.py` (11 tests) drives the real
`_maybe_reset_daily`, `_restore_midnight_snapshot`, and `_save_midnight_snapshot`.
Shared stub `test_ec_billing_d5a_baseline_guard_sites._bare_ec` gains `_lifetime_production_hwm`.

## Live acceptance criteria (prospective)
- **Live:** EC `get_energy_summary()["lifetime_production_entity"]` ==
  `sensor.envoy_482543015950_production_ct_energy_delivered`.
- **Live:** On the first restart after deploy, the log shows `Production snapshot
  provenance None != current entity ...`, and that day's `energy_daily` solar is NULL.
- **Live:** The following midnight's `energy_daily` row has non-null
  `solar_production_kwh` that matches the CT counter's daily delta (statistics id
  5654, local-midnight `state` difference × 1000) within ±1%.
- **Discriminator:** under the old counter a flap day reads `0.0` or NULL. Under the
  fix it reads a positive value matching the CT delta. A different failure, such as
  a stale CT, would show a value that disagrees with the statistics delta.
