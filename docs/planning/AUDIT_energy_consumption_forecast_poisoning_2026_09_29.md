# AUDIT — Consumption-forecast poisoning (card ENERGY-CONSUMPTION-FORECAST-POISONED-1)

**Date:** 2026-09-29 · **Mode:** read-only measurement (no code, config, DB or HA state changed)
**Probe:** `scripts/probes/energy_consumption_forecast_poison_probe.py` (`ssh ha "python3 -" < scripts/probes/energy_consumption_forecast_poison_probe.py`)
**Sources:** URA DB `energy_daily`, `energy_midnight_snapshot`, `decision_log` (dp_eval); HA recorder `statistics` (long-term, hourly), `states` (kept since 2026-09-21).

## TL;DR

- **The card's mechanism is wrong in its detail, but its conclusion holds.** Envoy "consumption today" / "production today" are **not** what poisons the history; URA never writes those into `energy_daily`. The culprit is **`sensor.envoy_482543015950_lifetime_energy_production`**, which sometimes reports a constant **0.045505 MWh** instead of its real ~15–19 MWh. When the midnight snapshot catches that value, the next midnight's delta equals the lifetime counter: `solar_production_kwh = (P_real − 0.045505) × 1000`. That value then flows straight into `consumption_kwh`.
- **Discriminator: 4 of 4 poisoned rows match exactly, to 0.1 kWh** (table below). A random spike could not reproduce the lifetime counter to one decimal.
- **The poison reaches the forecast two ways.** (1) The per-weekday average (Thu/Fri/Sun baselines are 3,049/2,089/2,126 kWh, against ~150–165 clean). (2) The temperature regression, which is refit on every restart and now has a **negative** slope (base 1,375, coeff −64.4 kWh/°F, against a clean 135.6 / +1.85). That is why the prediction swings 55→2,003 kWh within days and even within one day: every restart re-predicts at the current temperature. On hot days it falls to the 0.1 kWh floor (2026-09-01, 97 °F → pred 0.1).
- **Still poisoned now, and it will get worse tonight.** Today's persisted midnight snapshot has `lifetime_production = 0.045505`. Unless the 2026-09-30 00:00 read also glitches, tonight's 2026-09-29 row will be written at about **18,850 kWh** (falsifiable tomorrow).
- **Decision impact: none measured.** In 30 of 31 recorded DP evals since 09-21, `house_load_kw` was **exactly** forecast/24 (the `max()` picked the poisoned value), but every one stopped earlier at `already_below_target`. For the 18 older `fits` evals that can be rebuilt (Aug 21 – Sep 13), putting a clean forecast (120/150/180 kWh) into the same `max(SPAN, forecast/24)` flips **0** verdicts. The risk is latent, not realised.

## 1. Producer map

| Step | Site | Notes |
|---|---|---|
| Lifetime reads (MWh) | `domain_coordinators/energy.py:2714-2736` `_get_lifetime_*` → `_get_state_float` `:10577-10587` | Only rejects `unknown`/`unavailable`. **0.045505 passes as valid.** |
| Midnight snapshot set | `energy.py:2895-2900` (rollover), `:2907-2919` (seed-if-None, e.g. after restart), `:3081-3097` (cross-check re-seed), restore `:2321-2328` (same-day DB restore) | No monotonic or plausibility check on any path. |
| Daily derivation | `energy.py:2771-2823`: `consumption = Δnet_import + (Δproduction − Δnet_export) + (Δbatt_dis − Δbatt_chg)`, deltas × 1000 | Guards: any negative delta → None (`:2789`); `actual_kwh <= 0` → None (`:2825`). **No upper bound.** |
| Row write | `_save_daily_snapshot` `energy.py:2917-2957` → `database.py:4438-4480` `log_energy_daily` (INSERT OR REPLACE) | Writes `consumption_kwh`, `solar_production_kwh`, `predicted_consumption_kwh`, `prediction_error_pct`, `avg_temperature`. |
| In-memory learning | `energy.py:2840` `record_actual_consumption` → per-DOW deque (maxlen 8) `energy_forecast.py:766-774` | No filter. |
| Restore: DOW history | `energy.py:2264-2274` → `database.py:5041-5070` `get_consumption_history(60)` (**60 non-null ROWS**, not days) → `energy_forecast.py:736-764` | No filter. |
| Restore: temp regression | `energy.py:2225-2258` `_fit_temp_regression` ← `database.py:4545-4560` `get_energy_temp_pairs` (LIMIT 90) | No filter. **Refit on every startup** (`energy.py:1371`). |
| Restore: accuracy / adj factor | `energy.py:1430-1458` ← `get_energy_daily_recent(30)` | Only existing plausibility clamp: `consumption_kwh >= 10.0` (`:1446`, lower bound only, from the pre-v3.14 CT bug). No upper bound. Unbounded `pct_error` values (8,014 %, 213,147 %) drive `get_adjustment_factor` (`energy_forecast.py:893-908`, clamped 0.7–1.3). It was pinned at 1.3 from Aug 21 to Sep 8 and is now 0.803. |
| Consumed estimator | `energy_forecast.py:352-417`: `CONF_R1_ESTIMATOR_SHADOW_ONLY = True` (`energy_const.py:170`), so **legacy DOW + regression is CONSUMED** (`_compute_legacy` `:312-350`: `0.7·(base + coeff·|T−72|) + 0.3·DOW_mean`, × adj, floor 0.1). The v1 constant-coefficient arm is **shadow only** and immune (126–175 kWh over the same period). |

**Health of the dependency:** the production lifetime sensor glitched to 0.045505 in **346 hourly LTS points (2026-04-11 → 2026-09-29 01:00)**. It read the glitch value at **12 of 28 midnights in September**. It is the **only** lifetime MWh sensor that glitches since 2026-08-01. The other sensors' sub-1 MWh values are early-install genuine readings. The cause of the constant 45.505 kWh is not investigated here (adjacent: ENVOY-FLAKINESS-181243-1).

**Second-order effects of the same glitch** (not poisoning upward):
- **Current value glitched at midnight** → negative delta → row gets `consumption_kwh = NULL`. This explains most of the 83 null rows; for example, all of Sep 13–23 is null.
- **Both ends glitched** → `solar = 0.0` and consumption undercounts: 2026-09-24 = 48.2 kWh and 2026-09-25 = 78.1 kWh, against ~190–220 real. These pass the `>= 10` filter.

## 2. Poisoned rows (URA `energy_daily`, 198 rows, 2026-03-06 → 2026-09-28)

| date | consumption_kwh | solar_production_kwh | in DOW-60 window | in its DOW deque(8) | in regression-90 | in accuracy-30 |
|---|---|---|---|---|---|---|
| 2026-06-19 (Fri) | 6,803.6 | 6,691.6 | yes (rank 58) | no | **yes** | no |
| 2026-08-20 (Thu) | 14,646.5 | 14,554.5 | yes (rank 19) | **yes** | **yes** | **yes** |
| 2026-08-28 (Fri) | 15,583.5 | 15,537.2 | yes (rank 15) | **yes** | **yes** | **yes** |
| 2026-08-30 (Sun) | 15,897.3 | 15,786.9 | yes (rank 14) | **yes** | **yes** | **yes** |

All 4 rows are inside the current forecast windows. The low undercount rows (Sep 24/25) and the tiny March/April rows (<10, already filtered for accuracy) are listed in the probe output.

## 3. Ground-truth discriminator

Prediction under "snapshot captured the 0.045505 glitch": `stored_solar == (P(D+1 00:00) − 0.045505) × 1000`. P comes from recorder LTS (`statistics.state` of the hour starting 23:00 = the value at midnight).

| row D | P(D 00:00) (LTS) | P(D+1 00:00) (LTS) | predicted solar | stored solar | match |
|---|---|---|---|---|---|
| 2026-06-19 | n/a (mid-day seed) | 6.737063 | 6,691.6 | 6,691.6 | ✅ |
| 2026-08-20 | **0.045505** | 14.599998 | 14,554.5 | 14,554.5 | ✅ |
| 2026-08-28 | n/a (mid-day seed; glitch hours 17–19) | 15.582737 | 15,537.2 | 15,537.2 | ✅ |
| 2026-08-30 | **0.045505** | 15.832424 | 15,786.9 | 15,786.9 | ✅ |

The alternative hypothesis (a random spike, or Envoy's "today" counters reporting lifetime) predicts no exact identity with the lifetime production counter, so it is **rejected**. The identity is exact to 0.1 kWh on all four rows. `consumption − solar` on those rows is 46–111 kWh, which are normal grid/battery deltas. That confirms the production term alone carries the poison.

Live confirmation: `energy_midnight_snapshot` right now = `snapshot_date 2026-09-29, lifetime_production 0.045505, lifetime_consumption NULL`.

## 4. Forecast behaviour (re-simulation, section D of the probe)

Legacy estimator, before the adj factor (live adj = 0.803), poisoned vs clean history:

| DOW | DOW baseline poisoned / clean | pred @72 °F | pred @85 °F | pred @95 °F |
|---|---|---|---|---|
| Mon/Tue/Wed/Sat | 166–181 / same | ~1,015 / ~148 | ~430 / ~165 | **−20** (→ floor 0.1) / ~178 |
| Thu | 3,049 / 150 | 1,877 / 140 | 1,291 / 157 | 841 / 170 |
| Fri | 2,089 / 164 | 1,589 / 144 | 1,003 / 161 | 553 / 174 |
| Sun | 2,126 / 160 | 1,600 / 143 | 1,014 / 160 | 564 / 172 |

Even days with no poisoned row of their own are poisoned through the shared regression. The recorder (09-21 → now) shows 39 valued forecast states with predicted consumption ranging 55.3–2,003.2 kWh; the shadow v1 arm ranged 126–175 kWh over the same period. Latest (2026-09-29 00:00): predicted_consumption **327.0**, shadow v1 **146.0**.

## 5. Consumer map

| Consumer | Site | Trust / display |
|---|---|---|
| `sensor.ura_energy_coordinator_energy_forecast_today` (predicted net) | `sensor.py:11652-11690` via `energy.forecast_today` `energy.py:10052` | display |
| `sensor.ura_energy_coordinator_forecasted_energy_import` | `sensor.py:11696+` via `energy.py:10095-10121` | display |
| `sensor.ura_energy_coordinator_forecasted_consumption` | `sensor.py:~11774` via `energy.py:10124-10126` | display |
| Diagnostics blob | `energy.py:10733` | display |
| **DP (Battery-Aware EV Charging) house load** | `_dp_house_load_kw` `energy.py:4352-4394`; source `max_span_r1` default (`energy_const.py:1585`, live select = `max_span_r1`); fed to real tick `:4737` and shadow `:4501` → `evaluate_dp_transition` `energy_drain_precedence.py:673-678` (`drain_hours = drain_kWh / house_load_kw`) | **TRUST (decision)**. Note the docstring says "R1 fitted-model", but it reads `predicted_consumption_kwh`, which is the **legacy** arm while shadow-only is on. The v1 value lives in `shadow_predicted_consumption_kwh`. This is a concept split (Bug Class #63 shape). |
| Accuracy → adjustment factor → prediction | `energy.py:2843-2860`, `energy_forecast.py:893-908` | **TRUST (self-referential feedback)** |
| `_solar_forecast_error_baseline` | `energy.py:2863`; persisted `:8593`, restored `:8792` | persisted only; no decision reader found by grep |

## 6. Decision-impact verdict

- **Recent (recorder states, Sep 21–29):** 31 distinct DP evals. In **30/31**, `house_load_kw == predicted_consumption/24` exactly (for example, 13.625 = 327.0/24 on 09-29, against a SPAN live load of 5.5–7.9 kW). So the `max()` picked the poisoned forecast every time. **All 30 returned `already_below_target`** (SOC ≤ drain target), which short-circuits before the drain arithmetic (`energy_drain_precedence.py:669-671`), so the value was never used. The remaining eval was `l1_only`.
- **Older (URA `decision_log` dp_eval, Jul 23 – Sep 29):** 399 rows logged `fits`, but `decision_log` does **not** record `house_load_kw` or `needed_kwh`. Only 18 rows are arithmetic-consistent (soc > target, rate > 0). The other 381 carry a reason inconsistent with the eval order, probably the carrier's stale reason. For the 18, I rebuilt house load from LTS hourly means. Forecast/24 exceeded SPAN in 6 of them. The **correct counterfactual** keeps the `max()` and swaps in a **clean** forecast (120/150/180 kWh) → **0 verdict flips**. (A SPAN-only counterfactual flips 2, on 09-06 21:09 and 09-13 13:31, but that tests removing the forecast arm, not un-poisoning it.) Example, 09-06: the poisoned model predicted a 0.2 h drain; the real drain of SOC 32→10 took 1.0 h (from the log); a clean forecast predicts ~1.4 h. All three fit.
- **Verdict:** **no EV/battery decision was measurably changed.** Direction of the latent risk: an inflated `house_load_kw` shortens `drain_hours`, which biases toward `fits` / TRANSITIONED (pausing the EV to drain the battery first). The must-start-by guard (INV-DP2) is the backstop. Partly unmeasurable because `dp_eval` does not log `house_load_kw` / `needed_kwh` (assumed 25 kWh), and recorder attributes only go back to 09-21.

## 7. Current state (2026-09-29 ~02:00)

- Forecast sensor: `-228.5` (predicted consumption 327.0, v1 shadow 146.0). **Still poisoned.**
- Midnight snapshot: `lifetime_production = 0.045505`. **Prediction:** the 2026-09-29 row written at 2026-09-30 00:00 reads ≈ (P − 0.0455)×1000 ≈ **18,850 kWh**. If P glitches again at that midnight, the row is NULL instead. Either outcome confirms the mechanism.
- Other rows affected by the same glitch: 83/198 `consumption_kwh` NULL; 2 undercount rows (Sep 24/25, solar 0.0).

## 8. Recommended fix shape

**Config-first (operator action, zero code, reversible):** set `select.ura_energy_coordinator_dp_house_load_source` = `live_span`. This removes the only trust consumer's exposure now. Trade-off: SPAN minus EV sometimes reads ~0 (09-06), which makes DP abstain with MISSING_INPUTS rather than decide on a wrong load.

**Producer side (the root fix):**
1. **Lifetime-counter monotonic guard** at every snapshot-set site (`energy.py:2895-2919`, `:3081-3097`, restore `:2321-2328`) and at the rollover read. Reject a lifetime reading below the last-known-good for that counter (treat it as unavailable). Also reject a DB-restored snapshot that is below the live value by more than a small tolerance. This fixes the overcount, the null rows, and the zero-solar undercount together. Keep the last-known-good per counter in memory, persisted alongside the midnight snapshot.
2. **Daily plausibility reject** before `record_actual_consumption` / `log_energy_daily`: if `actual_kwh` or `solar_produced_kwh` exceeds a ceiling, store NULL and log a warning. Suggested knob: module constants, rung 1 (a data-hygiene safety bound; changing it should require review), for example `DAILY_CONSUMPTION_MAX_KWH ≈ 600` and a solar max derived from nameplate. Wire it to an NM/anomaly trip-wire so a recurrence is visible.

**Consumer side:**
3. Apply the same bounds on **read** in `get_consumption_history`, `get_energy_temp_pairs` and `get_energy_daily_recent` (or in their callers). Also bound `prediction_error_pct` / `pct_error` used by `get_adjustment_factor`. That way existing poisoned rows cannot re-poison after a restart even before cleanup.
4. **Cleanup** (a DB write needing operator approval): NULL `consumption_kwh` / `solar_production_kwh` / `prediction_error_pct` on the 4 poisoned rows (plus tonight's, if written), and consider the 2 zero-solar undercount rows. Then a restart refits the regression cleanly.
5. Optional (parsimony alternative, separate decision): flip `CONF_R1_ESTIMATOR_SHADOW_ONLY` (`energy_const.py:170`; its D-MED-1 R2-flip prerequisite is noted at `:136`). The v1 arm is history-immune. This does not replace fixes 1–3, because `energy_daily` actuals feed billing/coverage too.
6. Fix the `_dp_house_load_kw` docstring/concept split (it claims the R1 fitted model but reads the legacy arm), or point it at the v1 value explicitly.

**Tier:** **Tier 2-DB** (3 framing-disjoint reviews) under the standing regression-prone policy. It changes the lifetime-snapshot producer that feeds daily billing/consumption accounting, adds read-side filters to `database.py` DAOs, includes a data-cleanup step, and touches an input to an energy decision (DP). **Not Tier 3:** no measured decision impact, and the invariant is simple and local ("no `energy_daily` row stores consumption/solar above the ceiling or derived from a non-monotonic lifetime snapshot"), not threaded through many emission sites. Suggested framings: A = arithmetic/guard correctness incl. Envoy-reboot legit resets; B = restart/restore/midnight-boundary + cross-check re-seed interplay; C = test authority (fixture replays the real 0.045505 sequence; per-site mutation of each snapshot site).

**Not measured / out of scope:** the physical cause of Envoy's 45.505 kWh value (ENVOY-FLAKINESS-181243-1); the card's side note that "Net Energy" and "Net Tomorrow" use opposite signs (dashboard/audit card); the inconsistent `fits` reasons in 381 `dp_eval` rows (likely a stale-reason logging quirk and possibly worth its own card).
