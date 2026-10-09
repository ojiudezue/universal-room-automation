# URA v5.103.45 — Bill sensors from meter counters

Tier 2-DB: plan + 2 plan re-reviews, 3 framing-disjoint build reviews (A data integrity, B lifecycle/consumers, C test authority), fix pass, orchestrator re-drill (29/29 sites caught), full-suite name-diff clean after a clock-leak test fix. Plan: docs/planning/PLANNING_ec_billing_emporia_counters.md. Cards: ENERGY-BILL-ACCURACY-1, ENERGY-CONSUMPTION-FORECAST-POISONED-1 (the impossible daily rows).

## Problem
URA's bill/cost sensors read 24–34% low against PEC bills (import 1,854 / 2,104 / 2,360 kWh vs 2,778 / 2,752 / 3,564). The bill tracker integrated the Envoy's live grid power, and every Envoy dropout lost energy permanently. Four `energy_daily` rows had impossible consumption (≈ lifetime counter × 1000) from a missing day-start value.

## Solution
- **Bill from meter counters.** When the two existing EC settings "Grid import entity" / "Grid export entity" point at kWh counters (any brand — Emporia, Shelly, utility meter), the bill tracker books the change in each counter: import and export separately, each slice priced by the live TOU engine (by reference, never copied; flat-rate installs work). Gaps catch up losslessly and are priced across the periods they span; daily resets, restarts and restarts across midnight are handled.
- New setting **"Bill from"**: Auto (default — counters if kWh counters are configured, otherwise the old power method) / Meter totals / Power readings. With today's power-sensor config nothing changes (proven by a golden test).
- **Observability:** cost today / cost this cycle / predicted bill keep their entity IDs; new attributes `billing_source_today`, `counter_last_update`, `outage_days_this_cycle`; new sensor **Meter outage days**. During a meter outage cost figures pause, then catch up.
- **Data fixes:** day-start validity guard at all three daily-rollover sites (units unchanged — Envoy lifetime is MWh), write-time clamp as backstop, the 4 bad rows cleaned once. Peak-avoidance gets real kW (never a stale or fake 0).
- **Backfill script** (`scripts/backfill_energy_daily_from_counters.py`): dry-run by default, per-column before/after, updates import/export only, never wipes other columns.

## Post-deploy step (operator config)
Energy Coordinator options: Grid import entity = `sensor.mains_vue_3_mainsfromgrid_energy_today`, Grid export entity = `sensor.main_panels_mains_vue_3_mainstogrid_energy_today`, Bill from = Auto.

## Live validation (prospective)
- Cost today attribute `billing_source_today` = counters after the config step; `sensor.ura_meter_outage_days` present.
- After one full day: URA import today within ±2% of the Emporia daily counter (ideally a day with Envoy dropouts).
- `energy_daily` has no consumption > 240 kWh rows; the 4 bad dates are NULL.
- No URA errors at boot.
