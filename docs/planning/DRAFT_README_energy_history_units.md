# DRAFT README — energy_history kW summed as kWh (ENERGY-HISTORY-KW-SUMMED-AS-KWH-1)

Tier 1 (display-only, one file + one test file). Branch `fix/energy-history-units`.

## Bug
`energy_history` rows hold **instantaneous kW** (writer:
`domain_coordinators/energy.py` `_log_energy_history_snapshot`, ~3137-3239 — `grid_import =
max(net_power_w,0)/1000`, `solar_export = |min(net_power_w,0)|/1000`, `solar_production =
solar_production_w/1000`, `whole_house_energy = total_consumption_w/1000`; written every 3rd EC
cycle ≈ 15 min, `energy.py` ~6578). The prediction queries in `database.py` `SUM`med those kW
samples as if they were kWh → ~4x inflation. Live probe 2026-10-03: 92 rows, `SUM(grid_import)` =
403.5 → integrated ≈ 101 kWh. `sensor.universal_room_automation_predicted_energy_tomorrow` read
229.7 "kWh".

## Fix
One shared CTE in `database.py` (`_ENERGY_HISTORY_KWH_CTE` + `_energy_history_kwh_params()`)
computes per-row `dt_h` = hours to the next row via `LEAD()` over the whole table (before any
WHERE filter). If the gap exceeds `ENERGY_HISTORY_MAX_INTERVAL_H` (0.5 h — HA restart/outage) or
there is no next row, the sample is credited `ENERGY_HISTORY_NOMINAL_INTERVAL_H` (0.25 h). Both
are module constants (reviewed-code rung: they're tied to the EC write cadence, not tunable policy).
`get_energy_for_similar_days` and `get_energy_for_date_range` now `SUM(COALESCE(col,0) * dt_h)`.
`get_recent_weeks_energy`, `get_recent_months_energy` and `predict_energy` inherit the fix (they
only call those two). Writer schema unchanged.

## Findings that are NOT bugs in the aggregation
- **grid_import_2 duplication:** on 10-03, 90/92 rows have `grid_import_2 == grid_import` (configured
  `CONF_ENERGY_GRID_IMPORT_ENTITY` reads the same flow). No aggregation query reads
  `grid_import_2`, so there is **no double count** in predictions. Not changed.
- **whole_house_energy:** also instantaneous kW (consumption), despite the name. Not read by any
  aggregation query. Not changed.
- **solar_production = 0 since Envoy production broke:** a producer-health issue upstream
  (ENVOY-PRODUCTION-STALE family), not a units issue. Only `get_energy_for_date_range` returns it;
  `predict_energy` uses `net_energy = grid_import - solar_export` and ignores it.
- **Pre-existing, not changed:** `DATE(timestamp)` groups by UTC day (writer uses `utcnow()`), so
  "days" are UTC-days (19:00–19:00 CDT). Card separately if it matters.

## Consumers (all DISPLAY; no decision consumer)
Producer chain: `database.py` `get_energy_for_similar_days` / `get_energy_for_date_range` →
`get_recent_weeks_energy` / `get_recent_months_energy` → `predict_energy`.
| Consumer | file:line | Type |
|---|---|---|
| PredictedEnergyTodaySensor (`predict_energy("day")`) | aggregation.py:2286 | display |
| PredictedEnergyWeekSensor (`"week"`) | aggregation.py:2361 | display |
| PredictedEnergyMonthSensor (`"month"`) | aggregation.py:2434 | display |
| PredictedEnergyTomorrowSensor (`"tomorrow"`) | aggregation.py:2515 | display |
| PredictedCostTomorrowSensor | aggregation.py:2578 | display |
| PredictedCostTodaySensor | aggregation.py:2671 | display |
| PredictedCostWeekSensor | aggregation.py:2739 | display |
| PredictedCostMonthSensor | aggregation.py:2806 | display |
| Lovelace ura v8 dashboard tiles (via those entities) | docs/ha-config-snapshots/lovelace_ura_v8_* | display |
`git grep` of `domain_coordinators/` for these methods/entities: zero hits — no EC/HVAC decision
reads them. Other `energy_history` readers (`get_days_of_energy_data` MIN/MAX timestamps, counts,
cleanup, offline `scripts/probes/*`) don't sum power and are unaffected.

## Tests
`quality/tests/test_energy_history_kwh_integration.py` — real `UniversalRoomDatabase.initialize()`
DDL on a temp file, real query methods, hand-computed expectations:
- 96 x 4 kW @15 min → 96 kWh (raw sum would be 384); export/production likewise.
- 3 h gap → sample credited 0.25 h (1.5 kWh, not 6+).
- interval uses the true next row even when it's outside the WHERE window.
- similar-days per-day kWh; grid_import_2 not added.
- `predict_energy("tomorrow")` end-to-end → 108.0 kWh.

Mutation drill: removing `* dt_h` from both queries → 5/5 fail; restored → 5/5 pass. Adjacent
suites (predicted_energy_tomorrow, b4_live_health, database_resilience, data_pipeline): 57 passed.

## Live validation (post-restart; sensors refresh on their 15-min cache)
- `sensor.universal_room_automation_predicted_energy_tomorrow` drops from ~230 to roughly the real
  daily net grid import (expect ~50-110 kWh range). **Discriminating check:** compare against
  SPAN-measured grid import for the last few same-weekday days (HA statistics daily change of the
  SPAN grid-import energy counter). Fix → within ~±25% of SPAN; unfixed → ~4x SPAN; a different
  failure (e.g. empty query) → `unknown`/None.
- `predicted_cost_tomorrow` falls ~4x proportionally.
- One-shot DB cross-check: `ssh ha sqlite3 <db>` running the CTE for 10-03 ≈ 101 kWh vs raw 403.5.
