# v5.103.76: the EC bill check compares against SmartHub hourly statistics

> **Draft.** The version number may be renumbered at deploy.

Card: EC-BILL-UTILITY-DIVERGENCE-FROM-STATS-1 (Step 2). Plan: `docs/planning/PLANNING_ec_bill_divergence_from_smarthub_stats.md` (plan-reviewed; Rev 2 binding). Audit: `docs/planning/AUDIT_smarthub_bill_actual_2026_10_18.md`.

**Tier 2, reviewed with 3 framing-disjoint passes** (A correctness/window/TOU math, B async/lifecycle/decision-cycle non-blocking, C mutation). Display/diagnostic only: no decision path reads these attributes. Deploy risk: LOW.

## Problem → solution

- **The problem.** `utility_divergence_pct` on the predicted-bill sensor read a false 100.0. It compared the dead SmartHub *monthly* entity (month-start reset) against EC's 23rd-start cycle accumulator.
- **The fix.** EC now reads SmartHub's *hourly* long-term statistics (alive, gap-free, within about 1% of three PEC bills), prices each hour through the same TOU engine calls as counter-mode billing, and compares against EC's `energy_daily` over the identical set of local dates.
  - Recorder call: `get_instance(hass).async_add_executor_job(statistics_during_period, hass, start, None, ids, "hour", None, {"change"})` (`energy.py` `_query_utility_statistics`). `recorder` is not added to the manifest.
  - The decision cycle only *schedules* the refresh as a tracked background task (`hass.async_create_background_task`, the `_refresh_outage_days_this_cycle` idiom; handle kept in a slot like `_dp_eval_last_task` and cancelled in `async_teardown`). Single-flight, at most once per `UTILITY_STATS_REFRESH_MIN` = 60 min, stamp set before the first await.
  - Pure helpers in `energy_billing.py`: `price_hourly_utility_rows`, `utility_window_end`, `sum_utility_window`, `tou_import_rate_floor`, `build_utility_divergence_block`.
  - Previous cycle start = `CostTracker._get_cycle_start(cycle_start − 1 day)` (no month arithmetic).
  - `ec_underpriced_days`: window days whose EC import cost / kWh is below the TOU engine's lowest effective rate for that date.
- **New options fields** (EC options step, next to the utility meter): *Utility import statistic*, *Utility export statistic*. Blank import = feature off (kill switch, legacy entity path unchanged, attributes byte-identical). A non-blank value must contain `:`.
- **Knobs:** `UTILITY_STATS_REFRESH_MIN` 60, `UTILITY_STATS_STALE_H` 48, `UTILITY_DAY_COMPLETE_LAST_HOUR` 23, `UTILITY_RATE_FLOOR_REL_TOL` 1e-6 (module consts, `energy_const.py`); statistic ids (options flow).

## Prerequisite (Step 1, operator config action, same restart window)

1. Clear `energy_utility_meter_entity` in the Coordinator Manager EC options (it is ignored once the statistic ids are set, but clearing it removes the dead entity).
2. Set *Utility import statistic* = `smarthub:smarthub_energy_sensor_<ACCT>_<LOC>` and *Utility export statistic* = `smarthub:smarthub_energy_return_sensor_<ACCT>_<LOC>` (ids in plan §2, `statistics_meta` 4699 / 6396).
3. Both are construction keys: saving reloads the integration. Do it in a planned restart window, not while the house sleeps.

## Tests

- `test_ec_bill_divergence_smarthub_stats.py` (19), `test_ec_bill_divergence_sensor_attrs.py` (2), `test_ec_bill_divergence_options.py` (4).
- The blank-ids snapshot test also passes against the pre-change `sensor.py`/`energy.py` (byte-identical no-op path).
- Builder mutation drills M1–M20, all RED (incl. schedule→direct await, deleted schedule call, deleted teardown cancel).

## Live validation (to be replaced by a Validated table)

All one-shot reads of `sensor.ura_energy_coordinator_predicted_bill` attributes, within ~1 h of the restart (the first refresh can land one interval late if the recorder was not ready at boot).

- **Source:** `utility_source == "statistics"`; `utility_divergence_pct` is NOT 100.0; `utility_stats_error` is null.
- **Last cycle (valid ONLY with `energy_bill_cycle_day = 23`; if the knob changed, recompute with `.claude/scratch/billprobe/` first and note it here):**
  - `utility_last_cycle.utility_import_kwh` = **3669.4 ± 0.5**
  - `utility_last_cycle.utility_net_cost` = **295.13 ± 0.5** (a base-rate build gives ~139.27; an end-exclusive or day-23 off-by-one build gives neither)
  - `utility_last_cycle.ec_import_kwh` = **3428.4** (= `SELECT SUM(import_kwh) FROM energy_daily WHERE date >= '2026-08-23' AND date < '2026-09-23'`)
- **Current cycle:** `utility_kwh` ≥ **2204.1** (09-23..10-17) and grows by one day per daily import; `utility_window` ends the day after the newest complete local day.
- **F1 attribution:** current-cycle `ec_underpriced_days` > 0 while pre-10-09 EC history is in the window; `utility_divergence_cost_pct` roughly +20–30%. That is an EC history artifact (F1), not a regression.
- **Cadence / loop safety:** `utility_stats_refreshed_at` advances at most once per hour; no `Detected blocking call` warnings mention `statistics` in the HA log after restart.
