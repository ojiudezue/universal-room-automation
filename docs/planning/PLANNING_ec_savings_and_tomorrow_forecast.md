# PLANNING — EC "saved today", grid cost/hr, and the tomorrow forecast

**Card:** EC-COST-AND-FORECAST-MATH-1 · **Filed:** 2026-11-01 · **Mode:** plan only (no code) · **Rev 3** (2026-11-01): fixes every finding of `docs/reviews/code-review/ec_savings_forecast_plan_review_1.md`. H1 → §4.1/D1 (B2); H2 → D4; H3 → §8; H4 → D8; H5 → INV-SHADOW-1, D8, §9; M6 → D8/D9 sections; M7 → §9/§11/D4/D5; L8 → D1 cutover. **Rev 4** (2026-11-01): folds in `AUDIT_forecast_inputs_ev_and_class_probe.md` — D8 feature = (high+templow)/2 for train and run; D9 EV constant replaced; D9 per-HVAC-zone arm replaces the setpoint-delta arm; §1.2 R2 note. **Rev 5** (2026-11-01): fixes all 5 findings of `docs/reviews/code-review/ec_savings_forecast_plan_review_2.md` and adopts its build split. F1 → §4.1 / D1 (split computed before the served/net gates, `energy_billing.py:1015-1023`); F2 → D8 / INV-SHADOW-1 / §8 (`shadow_temp` threaded only into the v1/v2 call; consumers `energy.py:12782`, `:3579` added); F3 → D9 signature; F4 → D1 reader semantics; F5 → §4.1 export-drift note. Split → §10 + §13 (Build 1 brief).
**Evidence:** `docs/planning/AUDIT_ec_savings_and_cost_forecast_math.md` (probed 2026-11-01 ~21:00 CST) plus the probes in §1.4 below.
**Operator decisions (2026-11-01):** (1) "Saved today" = option A: the rate spread on battery energy DISCHARGED in mid-peak/peak, accrued at discharge time, same rate basis on both sides (effective rates). (2) `current_grid_cost_per_hour` uses the effective rate. (3) Net Tomorrow and predicted cost tomorrow get fixed in code, with a better design and options.

Scope note: presence is not touched. D9's setpoint arm reads HVAC setpoint history from the recorder, display-only. `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` was read completely for rev 3 and again for rev 4 (D9 now reads thermostat indoor temps and AC circuit kWh from the recorder, display-only; zones 1/2/3 = `climate.thermostat_bryant_wifi_studyb_zone_1` / `climate.up_hallway_zone_2` / `climate.back_hallway_zone_3`, tonnage 4/3/3 per §1). Relevant fact: there is no per-day preset schedule (presets follow house state, §5/§9b), which sets D9's tomorrow-setpoint rule. No §10 ledger claim is re-asserted.

---

## 1. Institutional context verified

### 1.1 Prior-art scan (code / plans / memory): REUSE or BUILD per piece

| Piece | Verdict | Existing symbol |
|---|---|---|
| Effective import rate at any instant | REUSED | `TOURateEngine.get_effective_import_rate(now)` `energy_tou.py:554` (base + delivery + transmission) |
| Export rate at any instant | REUSED | `TOURateEngine.get_export_rate(now)` `energy_tou.py:546` |
| Live effective rate for cost/hr | REUSED | `EnergyCoordinator.current_effective_rate` `energy.py:12700` (already feeds `sensor.ura_energy_current_rate`, `sensor.py:~11930`) |
| Displaced-period set | REUSED | `_DISPLACED_PERIODS = ("peak","mid_peak")` `energy_billing.py:886` |
| Per-tick battery-discharge-served-locally kWh | REUSED | `PeakAvoidanceTracker.accumulate` `energy_billing.py:973-1060` already computes `battery_served_kw` (discharge net of charge and export) every tick, fed from `energy.py:~4420-4450` |
| Round-trip efficiency | REUSED | `_ARBITRAGE_RTE = 0.90` `energy.py:4130` |
| Savings persistence + lifetime baselines | REUSED | `arbitrage_cycles` table `database.py:1618`, `save_arbitrage_cycle` `database.py:6300`, today/cycle/total sums `database.py:~6337-6431`, baseline+rollup `energy.py:~4337` |
| Daily consumption model | REUSED | `CONSUMPTION_REGRESSION_V1` `energy_const.py:141` and `_compute_v1` `energy_forecast.py:302-347` (season + HDD/CDD + EV term, fit on daily MEAN temp per `scripts/energy/fit_consumption_regression.py:159-166`) |
| Solcast tomorrow | REUSED | `CONF_ENERGY_SOLCAST_TOMORROW_ENTITY` `energy_const.py:301` → `BatteryStrategy.solcast_tomorrow` `energy_battery.py:2649` (live: 68.2 kWh) |
| Weather forecast for day N | NEW helper (D8) | `aggregation._get_forecast_temp` (`aggregation.py:1187`) REJECTED: it is index-based and silently falls back to `forecast[0]` and then the current temperature (`:1206-1220`). The WeatherProviderManager keeps only `forecasts[0]` (`weather_manager.py:425`). EC's `_update_forecast_temps` (`energy.py:8502`) is today-only |
| B2 inventory persistence | REUSED | `energy_state` via `save_energy_state`/`restore_energy_state` `database.py:5718/5735` |
| Per-period kWh history | REUSED | `energy_history` kW snapshots + `_ENERGY_HISTORY_KWH_CTE` `database.py:82-101`; period via `TOURateEngine._period_at` `energy_tou.py:707` |
| Shadow consumption arm | REUSED | `_shadow_predicted_consumption_kwh` `energy_forecast.py:422`; consumed `_predicted_consumption_kwh` `:281` |
| Realized TOU-priced daily cost | REUSED | `energy_daily.import_kwh / import_cost / export_kwh / export_credit` (EC slice-priced at the live effective rate, verified CORRECT in the audit §2) |
| Bill remainder forecast | CONSIDERED, not reused | `forecast_remainder` `energy_billing.py:1374` (same-weekday mean of utility-priced days). Basis for Option B cost only |
| SOC projection primitive | NOT NEEDED | `EnergyProjector` `energy_projector.py` answers intraday SOC-at-boundary, not daily kWh |
| Prediction-vs-actual log for the tomorrow forecast | NEW | Nothing exists: `energy_daily.predicted_consumption_kwh` logs only the EC *today* predictor, and the row is written by INSERT OR REPLACE at day close (`database.py:5050`), so a forward prediction cannot live there. `prediction_results` is room-transition only. `BillForecastLedger` (`energy_billing.py:1470`) is bill-only, JSON in `energy_state` |
| Discharge-accrual marker on `arbitrage_cycles` | NEW column | No column distinguishes charge-time rows from discharge-time rows (DDL `database.py:1618-1629`) |

Greps run (results above): `CONSUMPTION_REGRESSION_V1|predict_energy|_predicted_import_rate|predicted_cost_tomorrow|predicted_energy_tomorrow|forecast_outlook|solcast` and `SOLCAST_TOMORROW|solcast_tomorrow` across the package; `_attr_unique_id .*(predict|forecast|projected|bill|cost|savings|tomorrow)` over `sensor.py` + `aggregation.py`; `_get_displaced_rate|get_effective_import_rate|get_current_rate|tou_rate` (all rate consumers); `arbitrage_status|peak_avoidance_status|predicted_*|current_grid_cost` for decision consumers (none outside sensors: every value in this cycle is display-only).

### 1.2 Prior plans and audits consulted
- `PLANNING_net_energy_program_R1_R7_R2.md` (Tier-3 program): R1 built the v1 regression in SHADOW (`CONF_R1_ESTIMATOR_SHADOW_ONLY = True`, `energy_const.py:170`); flipping it is an R2 prerequisite with its own Tier-3 gate (D-MED-1 adjustment-factor reset). **This plan does not flip it.** It calls the v1 arithmetic as a pure function for the *tomorrow display*, which leaves every trust path where it is.
- `AUDIT_energy_consumption_forecast_poisoning_2026_09_29.md` + card ENERGY-CONSUMPTION-FORECAST-POISONED-1: the legacy DOW + refit-regression arm was poisoned by the Envoy lifetime-counter glitch. The poisoned history is parked there; this plan does not reopen it.
- `PLANNING_ec_bill_prediction_forecast.md` (EC-BILL-PREDICTION-FORECAST-1): utility-priced per-local-date series + same-weekday remainder. This is the prior art for local-date bucketing and per-period pricing.
- `AUDIT_house_sensors_correctness_2026_10_25` (cited in code at `aggregation.py:803`, `database.py:~3163`): already fixed delivery double-count and partial-day/week/month exclusion. Its "rows are UTC, as is day_of_week" note is the root of Bug A below.
- `AUDIT_forecast_inputs_ev_and_class_probe.md` (2026-11-01, rev 4 input): OWM daily entries carry `temperature`=max and `templow`=min, no mean (§1); EV circuit averaged 9.2 kWh/day in the 2025 fit window, so `ev_term_kwh` 18.58 double-counts (§2); per-HVAC-zone AC kWh vs (outdoor − thermostat indoor) R² 0.79/0.75/0.65 vs outdoor-only 0.69/0.65/0.56, in-sample (§5). **R2 note (§4):** re-running the B0 classification on 2026-07-16..10-31 gives 73% solar-only-vs-net disagreement, all net-worse, ~$69 undercharge over 59 usable days (method reproduces B0 imperfectly, +8 pts). R2 stays worth doing and remains the later Tier-3 cycle after the shadow flip (§9); this plan does not touch it.
- Cards: EC-PREDICTOR-SOLCAST-UNWIRED-1 (done; today's predictor reads Solcast again), EC-CONSUMPTION-SOURCE-EXCLUDES-BATTERY-LOAD-1 (done), EC-FORECAST-TRUTH-GAPS-1 (parked).

### 1.3 Memory bodies pulled
- `project_advanced_energy_mgt_v47x.md`: LightGBM forecaster deferred 2026-05-13. Parked here too (Option C below), with no change to its revival trigger.
- `project_battery_soc_envoy_not_span.md`: battery power/SOC is read from Envoy. The discharge measurement reuses the Envoy `battery_power_w` already feeding PeakAvoidanceTracker.
- `feedback_marginal_benefit_pushback.md`, `feedback_measure_before_build.md`, `feedback_extend_existing_never_rebuild.md`.

### 1.4 Measurements taken for this plan (read-only, URA DB `energy_daily`)
- **EC today-predictor (consumed arm = `dow_legacy`)** over-predicts heavily: 10-22..10-31 predicted 114–193 kWh against actual 61–129. Live today: `forecasted_consumption` 131.2 against a typical ~100. MAE 10-22..10-31 ≈ 35 kWh. **v1 arm backtest** (daily mean temp, 27 days since 10-02) MAE **17.3 kWh**. Trailing-7-day mean MAE 22.2.
- **Net-tomorrow backtest** (28 clean days since 09-15, actual net = import − export): Option A shape (v1 consumption − actual solar) MAE **21.6 kWh**; Option B shape (same-weekday mean over the last 4 local weeks) MAE **41.1 kWh**. Cost MAE at the 14-day realized import rate: A **$2.0**, B **$3.0** (mean |daily net cost| $4.68). Caveat: A used actual solar and actual mean temp, so it is an upper bound. Real Solcast error (Solcast's own 14-day MAPE 24.7%) and forecast-temp error will widen it.
- **D0 result (Build 2, 2026-11-02; `scripts/probes/ec_forecast_daily_extract.py` → `data/energy_fit/ec_forecast_daily_inputs.csv`, `scripts/probes/ec_tomorrow_forecast_backtest.py`).** 44 target days 09-17..10-31, REAL evening-before Solcast, ACTUAL (high+low)/2 temp (no forecast history kept). Option A net MAE 35.84 (v1) vs Option B 41.62 → **gate PASSED, A ships**. A per arm: v2 35.37, hvac_zone 28.02, trailing-14 33.13, weekly persistence 43.10. D9 fit (`fit_consumption_regression.py --version v2`): energy_daily starts 2026-03-06 (not 2025-11), 97 clean train days, 28 Oct holdout days. Holdout MAE v1 27.33, v2 E1 47.40, v2 E2 41.67, v1-shape refit on hourly-mean temp 34.91 → **v2 FAILS, ACTIVE="v1"**; v2 logged as E1 (E2 would need a per-house EV statistic with no role key). hvac_zone 20.75 (trailing-14 base; fitted base 39.68) → **passes** its ≥2.0 gain gate (vs v2 and vs v1); caveat: trailing-14 consumption alone scores 22.19, so most of the gain is the recent-base term. No heating slope fit (c=0); setpoints are not in recorder statistics, so the setpoint variant could not be backtested.
- **Energy-balance gap:** actual (import − export) exceeds (consumption − solar) by **+14.1 kWh/day mean (sd 17.5)**. That gap is battery round-trip loss, SOC carry-over and meter disagreement. Option A must carry a bias term for it (D3).

---

## 2. Falsifiable invariants

- **INV-SAV-1 (one credit, one basis):** for every tick in a displaced period (`peak`/`mid_peak`), each kWh the battery discharges to house load is credited **exactly once**, in arbitrage savings, at `get_effective_import_rate(t_discharge) − avg_basis/RTE`, where `avg_basis` is the B2 inventory average (grid kWh at the effective import rate of its charge tick, solar kWh at the export rate of its charge tick), or the off-peak effective rate when the inventory is empty. PeakAvoidanceTracker credits **zero** battery kWh in those periods. After the cutover, no charge-time row contributes to today or cycle arbitrage savings. *Break it by finding any path where one discharged kWh appears in both `arbitrage_savings_today` and `peak_avoidance_today`, or where one side of a spread is a base rate and the other an effective rate.*
- **INV-FC-1 (tomorrow means local tomorrow):** at any wall-clock time, including 18:00–23:59 local and DST transition days, the tomorrow forecast's target date equals `dt_util.now().date() + 1 day` (local), and every historical input it reads is bucketed by local date. *Break it with a frozen clock at 19:30 CST on a Sunday: the target must be Monday.*
- **INV-FC-2 (no single-instant pricing of a day):** no predicted daily, weekly or monthly cost multiplies a multi-hour kWh total by a rate sampled at one instant. *Break it by moving the clock across 17:00 (off-peak → mid-peak) with identical inputs: the predicted cost must not change.*
- **INV-RATE-1 (single rate source, operator 2026-11-01: "make sure rates come from the tou code so it changes if it changes"):** every rate used by D1–D7 (displaced rate, cost basis, off-peak rate, effective adders, per-period pricing, export credit) is read at use time from the TOU engine (`get_effective_import_rate` / the TOU schedule accessors), never a literal, a module constant, a value cached across a schedule/options change, or a rate copied into a stored row and re-used for later math. Stored rows may record the rate used, for audit only. *Break it by changing a TOU rate in the options (or swapping the schedule in a test): the next savings accrual, cost/hr and tomorrow price must use the new rate with no restart; a grep of the diff for numeric rate literals must be empty.*
- **INV-SHADOW-1 (no consumed value moves):** while `CONF_R1_ESTIMATOR_SHADOW_ONLY=True`, every value a decision reads is byte-identical before and after this cycle: `predicted_consumption_kwh` → DP `house_load_kw` under `max_span_r1`/`r1_base` (`energy.py:5213-5229`), `_predicted_consumption_kwh` → `battery_full_time` (`energy_forecast.py:698`), D7 `predicted_import_kwh` (`energy.py:12782`), yesterday's accuracy evaluation (`energy.py:3579`), and `_prediction_temperature` → `energy_daily.avg_temperature`. *Break it by finding any D8/D9 path that reaches the consumed arm with the shadow flag on.*

---

## 3. Producer / consumer map (current state, with defects)

| # | Value (entity / attr) | Producer arithmetic | Units / TZ / rate basis | Consumers | Verdict |
|---|---|---|---|---|---|
| 1 | `battery_strategy.arbitrage_savings_today`, `sensor.*_arbitrage_savings_today/_this_cycle/_total` | `_account_arbitrage_cycle` `energy.py:4214-4320`: ΔSOC×cap on CHARGE/ATTAIN ticks × (`_get_displaced_rate` RAW − `get_effective_import_rate`) × 0.9 | $; rows UTC ts, summed since local midnight; **mixed basis** (raw vs effective) | sensor.py:9331, 11380-11530; `energy_savings_total_*` sensors; dashboard "Saved today" | **BUG** (spread 0.000485 instead of 0.043). Accrues at charge, not discharge |
| 2 | `energy_savings_peak_avoidance_*` | `PeakAvoidanceTracker.accumulate` `energy_billing.py:995-1060`: solar_served×rate + battery_served×(displaced periods: `rate − displaced_raw`; else: full `rate`) | $; local-midnight reset; **mixed basis**: in mid/peak the battery "residual" equals the adders (~$0.0425/kWh), which is an artefact of the same mismatch | savings-total sensors | **BUG (twin of #1)**. Off-peak battery discharge is credited at the full gross rate with no charge cost netted |
| 3 | `battery_strategy.current_grid_cost_per_hour` | `sensor.py:9374-9395`: net import kW × `energy.tou_rate` | $/h; **base rate** | display; reason string `sensor.py:~9455` | **BUG** (33% low in mid-peak) |
| 4 | `sensor.universal_room_automation_predicted_energy_tomorrow` (`raw_net_kwh`) | `database.predict_energy("tomorrow")` `database.py:3285-3370`: mean of ≤10 same-weekday days' (import − export), rows filtered by forecast temp ±10 °F | kWh; **UTC weekday + UTC day buckets** (18:00–18:00 CST); per-row temp filter → partial days; no Solcast | dashboard "Net Tomorrow" | **BUG A** (UTC weekday), **BUG B** (partial days), misleading docstring `aggregation.py:2458` |
| 5 | `sensor.*_predicted_cost_tomorrow` | #4 × `_predicted_import_rate` (current instant) or × CONF export 0.08 | $; **single-instant rate**; export rate from config, not the engine | dashboard label | **BUG** (INV-FC-2), export-rate inconsistency |
| 6 | `predicted_energy_today` / `predicted_cost_today` | same as #4/#5 for `"day"` | same defects (UTC weekday is right before 18:00, wrong after) | dashboards | **BUG** (same family). Also duplicates EC #8 under a different method |
| 7 | `predicted_energy_week/_month`, `predicted_cost_week/_month` | mean of last 4 weeks / 3 months net (UTC naive boundaries `database.py:~3218,3240`), cost = × instant rate | kWh, $; UTC-offset boundaries (6 h skew); **single-instant rate** | dashboards | **BUG** (cost: INV-FC-2). Boundary skew is minor |
| 8 | `sensor.ura_energy_coordinator_energy_forecast_today` (`predicted_net_kwh`), `forecasted_consumption` | `_do_prediction` `energy_forecast.py:271-299`: Solcast today − consumed estimator (`dow_legacy` while shadow on) × adj factor | kWh; local; uses **current instant temp** at sunrise (v1 was fit on daily mean) | display; `dp_house_load_source=r1_base/max_span_r1` arm `energy.py:5213-5229` (code default `max_span_r1`, `energy_const.py:2248` / `energy.py:5222`; live select reportedly `live_span`) and `battery_full_time` `energy_forecast.py:698`. Consumed arm = `dow_legacy`, pinned by INV-SHADOW-1 | **INACCURATE** (MAE ~35 kWh, biased high). D8/D9 improve the shadow arm only; the flip is a later Tier-3 gate (§9) |
| 9 | `sensor.ura_energy_coordinator_forecasted_energy_import` | `predicted_import_kwh` `energy.py:12770-12799`: (consumption − production) − usable battery | kWh | display | **BUG (physics).** Over a whole day the battery cannot cancel a deficit unless SOC ends lower; the solar that refills it is already counted in production. Live: 15.0 predicted vs 79.7 imported today |
| 10 | `sensor.ura_energy_coordinator_energy_predicted_bill` | `_update_prediction` `energy_billing.py:~715-765`: utility-priced to date + same-weekday remainder + service charge | $; local dates; per-hour TOU pricing | display; `BillForecastLedger` scoring | **CORRECT** by construction (live source `utility`, $162.96). Not re-audited numerically |
| 11 | `forecast_accuracy` (`ura_energy_coordinator_forecast_accuracy` 64.3%) | `ForecastAccuracyTracker` `energy_forecast.py:~844-1000` on `energy_daily` | %; local | display; adjustment factor (clamped 0.7–1.3) multiplies the consumed estimate | Scores the poisoned legacy arm. `prediction_error_pct` is unbounded (16,664.8 on 10-18). Covered by ENERGY-CONSUMPTION-FORECAST-POISONED-1; not this cycle |
| 12 | `forecast_outlook.d1_kwh/d2_kwh`, solar classes | `energy_battery.py:8410-8420`, Solcast passthrough + `classify_solar_day` | kWh; local | **trust** (drain targets / arbitrage gate) | CORRECT for this cycle's scope; not touched |
| 13 | `battery_full_time` | `_estimate_battery_full_time` `energy_forecast.py:556-770` | local time | display | Not audited (out of scope) |
| 14 | `inclement.schedule_buy_hours` ranks by `get_current_rate` (base) `inclement.py:1135` | — | base rate | trust | **CORRECT**: the adders are flat across periods, so ranking by base equals ranking by effective. Noted so nobody "fixes" it |
| 15 | `_get_forecast_temp(1)` fallback | `aggregation.py:1187-1222` | °F | #4/#5 | **LATENT → replaced by D8**: when offset 1 is missing it silently returns today's forecast or the current temperature, so tomorrow can be keyed on tonight's temperature |
| 16 | HVAC AC-ramp savings `sensor.py:13992-14050` | not traced | — | display | Not audited. Flagged for a follow-up probe only if the operator wants it |

---

## 4. Design: "the rate the energy cost" (Saved today, option A, basis B2, operator-decided)

Savings per kWh discharged in a displaced period (`peak`/`mid_peak`) = `eff_import_rate(t) − avg_basis/RTE`, clamped ≥ 0, accrued at the discharge tick. Off-peak discharge earns **$0** (operator Q2) but still draws down the inventory.

### 4.1 B2 inventory: the simplest design that works
| Question | Answer |
|---|---|
| State | Two numbers: `inv_kwh`, `inv_cost_usd` (avg basis = cost/kWh). Nothing per-charge-event. |
| Where stored | `energy_state` key `arbitrage_inventory` (JSON `{kwh, cost_usd, updated_at}`) through the existing `save_energy_state` / `restore_energy_state` (`database.py:5718/5735`). REUSED; no new table or column. |
| Charge tick (battery_power > 0) | `grid_charge_kw = min(charge_kw, max(net_import_kw, 0))`; `solar_charge_kw = charge_kw − grid_charge_kw`. This follows from solar serving the house first: with `house = solar + net − charge`, solar surplus = `charge − net`. It uses only the inputs `PeakAvoidanceTracker.accumulate` already receives (`energy_billing.py:973-977`). Add `grid_kWh × get_effective_import_rate(t) + solar_kWh × get_export_rate(t)` to cost, and the kWh to inventory. |
| Where the split is computed (F1) | In `accumulate`, **after** the `now is None` / first-tick / `elapsed_h` gates (`energy_billing.py:993-1003`; with no valid elapsed there is no kWh to integrate) and **before** the `net_import_kw is None` return (`:1015-1016`) and the `served_kw < PEAK_AVOIDANCE_MIN_SERVED_KW` return (`:1023`). An overnight grid charge has served = 0 and must still fill the inventory. If `net_import_kw is None`, the charge kWh are booked at the off-peak effective basis (`basis_source` of later draws unaffected; no grid/solar split possible) and the discharge kWh still drain. The PA credit logic stays behind both gates, unchanged. First-tick and gap > 1 h losses are repaired by the SOC cap / restore seed. |
| Discharge tick | Remove `kWh_d × avg` from cost and `kWh_d` from kWh, in every period. Book savings only in displaced periods. |
| Empty inventory (`inv_kwh < ARBITRAGE_INVENTORY_MIN_KWH`) | Basis = the engine's current off-peak effective rate (B1 value). The row records `basis_source='empty_fallback'`. |
| Drift bound | Each tick, cap `inv_kwh` at `SOC × usable_capacity`. When capped, scale cost by the same ratio, so the average basis is kept. A missed tick can therefore never inflate the inventory. **Known drift (F5):** savings are booked on `battery_served_kwh`, but the inventory drains on total `discharge_kwh`, so battery energy sent to export also leaves the inventory. Discharge on ticks the tracker skips (first tick, gap > 1 h, `now` None) is not drained; only this SOC cap repairs that. Accepted: display-only and bounded by the cap. |
| Restore | Load at EC setup, before the first tick. If the key is missing, corrupt or older than `ARBITRAGE_INVENTORY_MAX_AGE_H`, seed `inv_kwh = SOC × usable_capacity` at the off-peak effective basis and log one INFO. |
| Persist | Save on every 3rd changed tick (~15 min) and at unload: ≤ 96 writes/day through the write queue, no per-tick flood. A crash loses ≤ 15 min of deltas, and the SOC cap repairs kWh drift. |
| Midnight | No reset. The inventory is physical stored energy. Only the today/cycle *sums* are bucketed by local date. |

**Risk, said plainly:** B2 is the riskiest piece of this cycle. It adds persisted cross-tick state, a restore path, a seeding rule and an attribution rule, to a display number worth about $0.2/day over B1. The risk is contained: no decision consumer reads it, the SOC cap bounds drift, and setting `ARBITRAGE_COST_BASIS_MODE="offpeak_effective"` reverts to B1 with no revert. I rate it MEDIUM, not high. The operator chose it, so it is built.

---

## 5. Net Tomorrow and Predicted Cost Tomorrow: chosen design (Option A)

- `consumption_tomorrow = consumption_model(date=tomorrow_local, temp=D8 mean(high, low))` uses the arm selected by `CONSUMPTION_REGRESSION_ACTIVE` (D9). It is a pure function extracted from `_compute_v1`, with no adjustment factor and no shadow-gate change.
- `solar_tomorrow = BatteryStrategy.solcast_tomorrow`.
- `net = consumption − solar + bias`, where bias = the trailing `FORECAST_NET_BIAS_DAYS` mean of (import − export) − (consumption − solar) from `energy_daily`.
- Cost (D4): `Σ_p share_p × net_kWh × rate_p(now)`. The shares come from history and the rates live from the TOU engine.
- Option B (historical, local-date fix) is the D0-gate fallback (D3b). Option C (hourly simulation) is parked, revival trigger: D5 cost MAE > $1.50/day over 30 days, or the tariff gains a demand component. Marginal-benefit reasoning is unchanged from rev 2: A halves B's error with reused parts, and C's margin is cents.

---

## 6. Deliverables

### D0: Pre-build probe (read-only, gate)
Script `scripts/probes/ec_tomorrow_forecast_backtest.py`, run via `ssh ha "python3 -"`. It replays Option A over 45 days using the recorded Solcast-tomorrow state at ~21:00 the evening before, and the recorded forecast temperature if available (else the actual mean temperature, labelled). It also runs the D9 arms (v1, v2 refit, EV variants, per-HVAC-zone).
- **Verify:** report pasted into §1.4.
- **Gate:** if A's net MAE with real Solcast is ≥ B's, ship D3b and park A. This discriminates: a Solcast-dominated error shows as A ≈ B on cloudy days only, while a model bias shows as a constant offset.

### D1: Arbitrage savings at discharge time (option A, basis B2)
- Single producer: `accumulate` returns its `battery_served_kwh`, `discharge_kwh`, `charge_kwh_grid`, `charge_kwh_solar` for the tick (savings on served, inventory drain on discharge). EC applies them to the §4.1 inventory, so there is no second integration.
- Displaced-period tick with `battery_served_kwh > 0`: write one `arbitrage_cycles` row with `kwh_charged=0.0` (NOT NULL), `kwh_discharged`, `accrual='discharge'`, `off_peak_rate` = avg basis used, `displaced_rate` = `get_effective_import_rate(t)`, `basis_source` ∈ {`inventory`,`empty_fallback`}, and `savings` clamped ≥ 0. ≤ 48 rows/day.
- Charge ticks write no savings row. The SOC log line stays.
- **Cutover:** at the first EC setup with `ARBITRAGE_DISCHARGE_ACCRUAL_ENABLED=True`, write `energy_state` key `arbitrage_discharge_cutover_ts` once (ISO UTC; never overwritten). Today and cycle sums filter `accrual='discharge'` **unconditionally**, so they need no timestamp compare. The cutover-day and cutover-cycle legacy rows (cents) drop out of today/cycle. Lifetime = baseline + all rows (history kept, no backfill). The key is for audit and the Live query only.
- **Restart mid-evening:** rows already written stay, and today is re-summed from the DB. The tracker's `_last_accumulate_ts` is None after boot, so the first tick is skipped and never smeared (`energy_billing.py:997-1003`). The inventory is restored per §4.1. Expected loss: one tick.
- **INV-RATE-1 for stored rows:** sums read `SUM(savings)` only (`database.py:6346, 6367, 6431`). No reader re-prices from `off_peak_rate`/`displaced_rate`. Those columns are audit-only. A test pins this.
- `_get_displaced_rate` is retired from savings. Its other caller (`energy.py:4437`) goes in D2.
- **Readers of `kwh_charged` (F4):** discharge rows carry `kwh_charged=0.0`, so each reader gets defined semantics:
  - `query_arbitrage_savings_since` (today and cycle, `database.py:6337`) and `query_arbitrage_savings_total` (`:6362`), both `SUM(kwh_charged)`: keep the column sum (it now counts only legacy charge rows) **and** add `SUM(kwh_discharged)` as `kwh_discharged`. Sensor attrs `kwh_charged_today` / `kwh_charged_this_cycle` / `total_kwh_charged` (`sensor.py:11405, 11469, 11524`) and `_arb_kwh_scope` (`sensor.py:11560-11565`) switch to `kwh_discharged` for discharge-era scopes (today/cycle), with new attr names `kwh_discharged_*`; the old names stay for one release reading the legacy sum, documented as legacy. Lifetime baseline at `energy.py:4362` keeps `kwh_charged` (history).
  - `query_arbitrage_last_cycle` (`database.py:6382`): filter `WHERE accrual='discharge'` once the cutover key exists, and return `kwh_discharged`; `last_cycle_kwh_charged` (`sensor.py:11421`) becomes `last_cycle_kwh_discharged`.
  - `query_arbitrage_pace_recent` (`database.py:~6413`): reads `savings` only; unaffected, but filter `accrual='discharge'` for days ≥ cutover so legacy cents don't dilute pace. A test pins each reader.
- Migration: add columns `accrual TEXT NOT NULL DEFAULT 'charge'`, `kwh_discharged REAL`, `basis_source TEXT`, idempotent via the existing column-add pattern.
#### Acceptance criteria
- **Verify:** inventory built from 15 grid kWh at 0.085957 ($1.2894) plus 5 solar kWh at 0.0435 ($0.2175) = 20 kWh, $1.5069, avg 0.07535. A mid_peak tick discharging 5 kW for 5 min (0.4167 kWh) at effective 0.128918 gives savings = 0.4167 × (0.128918 − 0.07535/0.9) = $0.01883. The inventory drops by 0.4167 kWh and 0.4167 × 0.07535.
- **Verify (discriminating vs B1):** the same tick with a grid-only inventory (avg 0.085957) books $0.01392. The difference ($0.0049) appears only when solar charged the battery. Under a base-rate regression the value is ≤ 0 and clamps to 0, so no row is written.
- **Verify:** charge tick with charge 4 kW and net import 1.5 kW → grid 1.5, solar 2.5. With net −2 kW (exporting) → grid 0, solar 4.
- **Verify:** an off-peak discharge tick writes no row and decrements the inventory.
- **Verify:** empty inventory gives the off-peak effective basis and `basis_source='empty_fallback'`. Restore with a missing or corrupt key seeds from SOC. With SOC cap 10 kWh and inventory 14 kWh/$1.12, the result is 10 kWh/$0.80.
- **Test:** `test_arbitrage_discharge_accrual_inventory_basis`, `test_arbitrage_charge_split_grid_solar`, `test_arbitrage_offpeak_discharge_zero_but_drains_inventory`, `test_arbitrage_empty_inventory_fallback`, `test_arbitrage_inventory_restore_and_seed`, `test_arbitrage_inventory_soc_cap_scales_cost`, `test_arbitrage_inventory_survives_midnight`, `test_arbitrage_no_charge_time_savings_after_cutover`, `test_arbitrage_cutover_key_written_once`, `test_arbitrage_sums_never_reprice_stored_rates`, `test_arbitrage_cycles_migration_adds_columns` (DDL extracted from production source), `test_arbitrage_inventory_fills_on_grid_only_charge` (F1: solar 0, house load 0.5 kW, charge 5 kW, net +5.5 kW, served 0 → `inv_kwh` grows by 5×dt at the effective rate; the served gate must not block it), `test_arbitrage_inventory_net_none_books_offpeak_basis`, `test_arbitrage_readers_discharge_rows` (today/cycle/total `kwh_discharged`, last_cycle filter, pace filter).
- **Live:** on the first evening, convert row timestamps to America/Chicago in Python (not SQLite `localtime`). Rows ≥ the cutover key are all `discharge` and fall within 17:00–21:00 local. 11-01 is the DST-end day: from 11-02 that window is 23:00–03:00 UTC, before it 22:00–02:00 UTC, so never compare raw UTC hours. `arbitrage_savings_today` is $0.6–1.5 by 21:00. `energy_state.arbitrage_inventory.updated_at` is < 20 min old.

### D2: Peak-avoidance double-count guard
- In `_DISPLACED_PERIODS`, set `battery_credit_per_kwh = 0` (arbitrage owns it). Outside them also 0 (operator Q2: off-peak discharge earns $0). Solar-served credit is unchanged. Drop the `displaced_rate` parameter.
#### Acceptance criteria
- **Verify:** a displaced tick with 5 kW battery-served and 0 solar adds $0 to PA and the D1 amount to arbitrage, and total-today rises by exactly the arbitrage amount (INV-SAV-1). An off-peak battery-served tick adds $0 to both.
- **Test:** `test_peak_avoidance_zero_battery_credit_all_periods`, `test_savings_total_no_double_count_displaced_tick`.
- **Live:** with solar 0, `peak_avoidance_today` growth during 17–21 local is ≈ 0.

### D3: Net Tomorrow, Option A (D3b = Option B if D0 fails)
- Pure `predict_net_tomorrow(...)` in `energy_forecast.py`. `PredictedEnergyTomorrowSensor.async_update` calls the EC method instead of `db.predict_energy("tomorrow")`.
- Target = `dt_util.now().date() + 1`. Temp = the D8 helper for that date. If the input is missing, the value is None with `missing_input: forecast_temp|solcast`. There is no fallback.
- Attrs: `consumption_kwh`, `solar_kwh`, `bias_kwh`, `raw_net_kwh`, `target_date`, `temp_used`, `model_arm`, `method`. `confidence` is dropped. `backtest_mae_kwh` comes from D5 at ≥ 7 rows.
#### Acceptance criteria
- **Verify:** frozen 2026-11-01 19:30 America/Chicago → target 2026-11-02. 2026-03-08 23:30 → 03-09.
- **Verify (discriminating):** Solcast 20 vs 90 with all else equal → net differs by exactly 70. The historical model would not move.
- **Test:** `test_net_tomorrow_local_date_after_1800`, `test_net_tomorrow_dst_boundary`, `test_net_tomorrow_solcast_sensitivity`, `test_net_tomorrow_missing_forecast_temp_is_none`, `test_consumption_model_parity_with_compute_v1`.
- **Live:** after 18:00 local, `target_date` = local tomorrow, `solar_kwh` = `sensor.solcast_pv_forecast_forecast_tomorrow`, and `raw_net_kwh` = consumption − solar + bias to 0.1.

### D4: Cost sensors priced as per-period kWh shares × live TOU rates (INV-FC-2, INV-RATE-1)
- **Per-period kWh source (existing data, no new column):** `energy_history` instantaneous-kW snapshots integrated with the existing `_ENERGY_HISTORY_KWH_CTE` (`database.py:82-101`, kW × dt_h with the gap guard). Each row's timestamp is converted to local time and bucketed by `TOURateEngine._period_at` (`energy_tou.py:707`) in Python, over the trailing `FORECAST_PERIOD_MIX_DAYS` local days. New DAO `get_period_kwh_mix(days)` returns `{period: {import_kwh, export_kwh}}`. It is read-only, with one query per refresh.
- Helper `period_shares(mix)` → `{p: share}` for import and for export. Cost = `Σ_p imp_share_p·max(net,0)·get_effective_import_rate(t_p) + Σ_p exp_share_p·min(net,0)·get_export_rate(t_p)`, where `t_p` is a representative instant of period p today, from the engine's schedule. Rates are never stored.
- Fallback when < 3 days of mix: hour-weighted mean of the engine's rates over a local day. Never an instant rate.
- Used by predicted cost tomorrow, today, week and month. **`predicted_energy_today`/`predicted_cost_today` read EC `forecast_today.predicted_net_kwh`** (operator Q3, decided). Week/month kWh keep the historical model, with local boundaries.
- Export rate: all six `CONF_EXPORT_REIMBURSEMENT_RATE` reads change to the engine (§8).
#### Acceptance criteria
- **Verify:** identical inputs at 16:59 and 17:01 local → identical `predicted_cost_tomorrow`.
- **Verify:** mix {off_peak 0.9, mid_peak 0.1} on import, net 50 kWh, engine rates 0.085957/0.128918 → cost = 50 × (0.9 × 0.085957 + 0.1 × 0.128918) = $4.513.
- **Verify (discriminating, INV-RATE-1):** swap the engine's off-peak rate to 0.10 with history unchanged. The cost changes on the next refresh to 50 × (0.09 + 0.0128918) = $5.145. A trailing realized-$ design would not move.
- **Test:** `test_predicted_cost_not_instant_rate`, `test_period_kwh_mix_from_energy_history_local_buckets`, `test_predicted_cost_follows_tou_rate_change`, `test_predicted_cost_export_uses_engine_rate`, `test_predicted_today_reads_ec_forecast`.
- **Live:** `predicted_cost_tomorrow` attrs `rate_source='period_mix_<N>d'`, `import_shares` summing to 1.0 ±0.001, value constant across 17:00. `predicted_energy_today` = `energy_forecast_today.predicted_net_kwh`.

### D5: Prediction log, every arm
- New table `energy_forecast_log(target_date TEXT, arm TEXT, made_at TEXT, pred_consumption_kwh REAL, pred_solar_kwh REAL, pred_net_kwh REAL, pred_cost REAL, temp_used REAL, consumed INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(target_date, arm))`. There is one row per local target date per arm. Arms: `dow_legacy`, `v1`, `v2`, `hvac_zone` (only if D9 ships it), `weekly_persistence`. `consumed=1` marks the arm the EC actually used that day.
- INSERT OR REPLACE all arms in one batch at `FORECAST_LOG_LOCAL_HOUR`, through the write queue (one batch/day). Actuals JOIN `energy_daily` on date at read time.
- Sensor attrs per arm: `mae_7d_kwh`, `mae_30d_kwh`, `bias_30d_kwh` (NMBE), plus `cost_mae_30d` and `log_rows` for the D3 arm.
#### Acceptance criteria
- **Verify:** two simulated days × 4 arms → 8 rows. JOIN errors equal hand-computed values per arm. Exactly one row per date has `consumed=1`.
- **Test:** `test_forecast_log_one_row_per_day_per_arm`, `test_forecast_log_accuracy_join_per_arm`, `test_forecast_log_single_batch_write`, `test_forecast_log_table_ddl_from_production`.
- **Live:** the day after deploy, `SELECT arm, COUNT(*) FROM energy_forecast_log GROUP BY arm` gives 1 per arm for local tomorrow, `made_at` ≈ 21:00 local, and the `consumed=1` row = `dow_legacy`.

### D6: Grid cost per hour on the effective rate
- `sensor.py:9377` and the reason string at `~9455` use `energy.current_effective_rate`.
#### Acceptance criteria
- **Verify:** 2 kW net import in mid_peak → 0.26 (not 0.17). **Test:** `test_grid_cost_per_hour_uses_effective_rate`. **Live:** cost/hr ÷ net kW ≈ `sensor.ura_energy_current_rate` in mid-peak.

### D7: Forecasted-import physics fix
- `predicted_import_kwh` (`energy.py:12770`) = `max(consumption − production + bias, 0)`, with no usable-battery subtraction.
#### Acceptance criteria
- **Verify:** consumption 131, production 80 → 51 + bias. **Test:** `test_predicted_import_no_battery_cancellation`. **Live:** next evening, within ±25 kWh of `energy_daily.import_kwh`.

### D8: Target-date forecast temperature helper (EC side)
- New `EnergyCoordinator.async_forecast_temps_for_date(target: date) -> tuple[high, low] | None`. It calls `weather.get_forecasts` (type daily, bounded by `FORECAST_FETCH_TIMEOUT_S`) on the active provider (`energy.py` active-provider resolver ~8490), keeps the **full list** (the WeatherProviderManager returns only `forecasts[0]`, `weather_manager.py:425`), and selects the entry whose `datetime`, parsed and converted to local time, has `.date() == target`. It is cached per (provider, target date) until the next EC forecast refresh.
- **No silent fallback:** no matching entry, or a missing high or low → None (the caller exposes `missing_input`). It is never index-based, never `forecast[0]`, never the current temperature. `aggregation._get_forecast_temp` is untouched; it is no longer used by any sensor in this cycle.
- **Feature definition:** `temp_feature = (temperature + templow) / 2` of the selected entry (OWM One Call 3.0 daily entries have `temperature` = high and `templow` = low, no mean). D9 fits on the SAME proxy, so train and run match.
- Two callers: D3 (tomorrow) and the EC today predictor's **v1/v2 shadow arm** (today). The shadow arm gets `temp_feature` for today's local date as a **separate `shadow_temp`** threaded only into the v1/v2 call. The existing single `temp` at `energy_forecast.py:278` (passed to `_estimate_consumption`) is **unchanged**: it still feeds `_compute_legacy` (temp-scaled, `:349-386`), `_prediction_temperature` (→ `energy_daily.avg_temperature`, `energy.py:~3612`) and the consumed value. Nothing from D8 reaches `temp`, `_compute_legacy` or `_prediction_temperature`. A missing input → that arm reports unavailable (`missing_input: forecast_temp`); no fallback.
- **Shadow invariant (INV-SHADOW-1):** while `CONF_R1_ESTIMATOR_SHADOW_ONLY=True`, `_predicted_consumption_kwh` (`energy_forecast.py:281`) and `_get_current_prediction()["predicted_consumption_kwh"]` are byte-identical before and after D8/D9. Only `_shadow_predicted_*` (`:422-428`) change. These consumed values feed DP `house_load_kw` (`energy.py:5213-5229`, default `max_span_r1`, `energy_const.py:2248`), `battery_full_time` (`energy_forecast.py:698`), D7 `predicted_import_kwh` (`energy.py:12782`), the daily accuracy evaluation (`energy.py:3579`), and `energy_daily.avg_temperature` via `_prediction_temperature`.
#### Acceptance criteria
- **Verify:** a forecast list whose first entry is tomorrow (provider dropped today after sunset) → `for_date(tomorrow)` returns that entry and `for_date(today)` returns None. With the list starting today, both resolve correctly.
- **Verify:** a list missing the target date → None, even though the current temperature exists.
- **Verify (discriminating):** a frozen evening with today's entry still present → `for_date(tomorrow)` returns tomorrow's entry. The old index-1 path would also return it, so the post-sunset case above is the discriminator.
- **Test:** `test_forecast_temps_for_date_selects_by_local_date`, `test_forecast_temps_for_date_no_fallback`, `test_forecast_temps_for_date_dst_day`, `test_shadow_on_consumed_value_byte_identical` (golden: same inputs pre/post → equal `predicted_consumption_kwh`, equal `_dp_house_load_kw` under `max_span_r1`, equal `battery_full_time`, equal `_prediction_temperature`), `test_shadow_temp_not_passed_to_legacy_arm` (a distinct forecast midpoint vs current temp: legacy output and `avg_temperature` follow the current temp only).
- **Live:** `energy_forecast_today` attrs show the shadow `temp_used` = mean of today's forecast high and low (± 0.1). `forecasted_consumption` is unchanged from the pre-deploy method (consumed arm still `dow_legacy`).

### D9: `CONSUMPTION_REGRESSION_V2` refit (+ per-HVAC-zone arm, backtest-gated)
- **Constants:** `CONSUMPTION_REGRESSION_V2: Final[dict]` in `energy_const.py` beside V1 (`:141`), rung 1 (reviewed code; a fitted model must stay reproducible from the script). Selector `CONSUMPTION_REGRESSION_ACTIVE: Final[str] = "v2"` (rung 1; `"v1"` = rollback).
- **Fit:** `scripts/energy/fit_consumption_regression.py` with `--version v2`. Fit window: clean `energy_daily` days from the earliest clean day on or after 2025-11-01 (UNVERIFIED that `energy_daily` reaches back that far; D0 reports the actual start) → 2026-09-30, excluding the poisoned dates listed in ENERGY-CONSUMPTION-FORECAST-POISONED-1. Holdout: 2026-10-01 → 2026-10-31, never used in the fit. Input: per local date, (daily max + daily min)/2 of `sensor.thermostat_bryant_wifi_backhallway_outdoor_temperature` from recorder hourly stats (not the hourly mean), the same proxy D8 feeds at run time. The script prints the coefficient dict, which is pasted verbatim.
- **EV term (replaces `ev_term_kwh` 18.58):** the 2025 fit window already carried ~9.2 kWh/day of EV load, so the constant double-counts. V2 drops it. The fit script backtests two variants and ships the simpler one unless the other wins the holdout: **(E1, default)** EV inside the base, i.e. fit on whole-house consumption including EV, no EV term; **(E2)** base fit on consumption minus EV, plus a measured trailing EV mean (`EV_TRAILING_MEAN_DAYS`, §7) from `sensor.span_panel_car_charger_consumed_energy` through 2026-10-12, then `sensor.span_panel_garage_a_evse_consumed_energy` from 2026-10-13 (garage_b excluded as junk). E2 ships only if its holdout MAE is lower than E1's.
- **Ship gate (v2):** holdout MAE < v1 holdout MAE. Otherwise `ACTIVE="v1"` and record why.
- **Per-HVAC-zone arm (`hvac_zone`; subsumes the rev-3 setpoint-delta arm):** `pred = Σ_z [a_z + b_z·max(outdoor − indoor_z, 0) (+ c_z·max(indoor_z − outdoor, 0) if the fit shows a heating term)] + base_nonhvac`. Per-zone target = daily kWh of `sensor.span_panel_ac1_consumed_energy` (Z1) / `ac_2` (Z2) / `ac_3` (Z3); indoor_z = the zone's thermostat temperature (`sensor.office_b_zone_1_temperature`, `sensor.up_hallway_zone_2_temperature`, `sensor.back_hallway_zone_3_temperature`), daily (max+min)/2 to match D8. Use the thermostat readings, NOT `sensor.zone_*_avg_temperature` (house zones ≠ HVAC zones). `base_nonhvac` = whole house − Σ AC circuits, as a trailing mean or a simple fit, whichever backtests better. The circuit→zone mapping is inferred from Zone Manager config: **operator to confirm wiring before build.** The fit script also tries setpoint (`target_temp_high/low`) in place of indoor and keeps whichever backtests better; indoor needs no schedule.
  - **Ship gate:** Oct holdout MAE at least **2.0 kWh/day better** than the house-level refit arm (v2) (`HVAC_ZONE_ARM_MIN_GAIN_KWH = 2.0`, rung 1, fit script only). Otherwise record the result in §1.4 and do not ship the arm. If shipped, D5 logs it as arm `hvac_zone`.
  - **Tomorrow's indoor_z:** the trailing 7-day mean of each zone's thermostat temperature (recorder, display-only read). If the setpoint variant wins instead, tomorrow's setpoints follow the rule below. HVAC has no per-day preset schedule. S1 maps house state to a preset (`hvac_preset.get_preset_for_house_state`, `hvac_preset.py:119`), and the thermostats' own schedules are being retired (HVAC STATE_OF_PLAY §5, §9b). So "scheduled presets for the target day" has no source, and the operator's fallback becomes the method: the trailing 7-day mean of each zone's `target_temp_high/low`, from the recorder. This is a display-only read. It reads no HVAC coordinator object and calls no HVAC method.
- **Pure-function signature (F3):** today `_compute_v1(self, now, temp)` (`energy_forecast.py:302`) derives season and EV era from `now` and hard-codes `CONSUMPTION_REGRESSION_V1` (`:313`). Extract a module-level pure function `compute_consumption_regression(target_date: date, temp_feature: float | None, consts: Mapping[str, Any]) -> tuple[float | None, float | None, float, str]` that derives season and EV era from `target_date` (local) and reads coefficients only from `consts`. `_compute_v1` becomes a thin wrapper `compute_consumption_regression(dt_util.as_local(now).date(), temp, CONSUMPTION_REGRESSION_V1)`, byte-identical. D3 calls it with `target_date = tomorrow_local` and the selected consts. Test `test_consumption_model_season_from_target_date` (now = Nov 30 evening, target Dec 1 → winter season coefficients).
- Shadow invariant INV-SHADOW-1 holds: V2 changes only the shadow arm and D3.
#### Acceptance criteria
- **Verify:** the fit script with a fixed seed and window reproduces the committed dict to 6 dp.
- **Verify:** `compute_consumption_regression(day, temp, consts=V2)` on three holdout days equals the script's predictions to 0.01 kWh.
- **Verify (discriminating):** holdout MAE is reported for v1, v2 (E1 and E2) and `hvac_zone` for the same days. If v2's gain comes from the window change only, v1 refit on the same window matches it (reported as a fourth number).
- **Test:** `test_consumption_regression_v2_shape`, `test_consumption_model_selector_v1_rollback`, `test_hvac_zone_arm_absent_when_gate_failed` (or `test_hvac_zone_arm_sums_zones_plus_base` if shipped), `test_temp_feature_is_high_low_midpoint`, `test_shadow_on_consumed_value_byte_identical` (shared with D8).
- **Live:** D5 logs `v2` rows. `energy_forecast_today` shadow attrs carry `model_arm='v2'`, and the consumed `forecasted_consumption` is unchanged.

---

## 7. Numbers get knobs
| Number | Knob | Rung | Why / kill-switch |
|---|---|---|---|
| RTE 0.90 | `_ARBITRAGE_RTE` (REUSED `energy.py:4130`) | 1 | physical constant |
| Basis mode | `ARBITRAGE_COST_BASIS_MODE = "inventory"` (NEW) | 1 | `"offpeak_effective"` = B1 rollback |
| Inventory empty threshold | `ARBITRAGE_INVENTORY_MIN_KWH = 0.1` (NEW) | 1 | below this, average basis is noise |
| Inventory max restore age | `ARBITRAGE_INVENTORY_MAX_AGE_H = 12` (NEW) | 1 | older state is reseeded from SOC |
| Inventory save cadence | `ARBITRAGE_INVENTORY_SAVE_EVERY_TICKS = 3` (NEW) | 1 | write-queue bound |
| Accrual cutover | `ARBITRAGE_DISCHARGE_ACCRUAL_ENABLED = True` (NEW) | 1 | False restores charge-time rows |
| Period-mix window | `FORECAST_PERIOD_MIX_DAYS = 14` (NEW; replaces rev-2 realized-rate window) | 1 | smooths weekday mix, follows season |
| Bias window | `FORECAST_NET_BIAS_DAYS = 14` (NEW) | 1 | 0 disables bias |
| Log hour | `FORECAST_LOG_LOCAL_HOUR = 21` (NEW) | 1 | after Solcast evening refresh |
| Tomorrow model | `NET_TOMORROW_MODEL = "v1_solcast"` (NEW) | 1 | `"historical"` = D3b |
| Regression arm | `CONSUMPTION_REGRESSION_ACTIVE = "v2"` (NEW) | 1 | `"v1"` rollback |
| HVAC-zone gain gate | `HVAC_ZONE_ARM_MIN_GAIN_KWH = 2.0` (NEW, fit-script only) | 1 | |
| EV trailing window (E2 only) | `EV_TRAILING_MEAN_DAYS = 14` (NEW, only if E2 ships) | 1 | follows charging habit; unused under E1 |

None goes to rung 3: none is tuned by watching the dashboard.

## 8. Emission/decision-site enumeration
- **Savings writers:** `save_arbitrage_cycle` called only at `energy.py:~4303`; PA credit only in `PeakAvoidanceTracker.accumulate`. **Readers:** `database.py:6346, 6367, 6390, 6431` (sum `savings` only); `sensor.py:9329, 11282, 11391, 11402, 11454-11466, 11510-11521, 11556-11564, 11771`.
- **Inventory:** one writer (EC tick plus unload) and one reader (EC setup restore), both via `energy_state`.
- **Rate sites:** `energy.py:4281-4283, 4433-4437` (CHANGE, D1/D2); `energy_billing.py:1033-1043` (CHANGE, D2); `sensor.py:9377` (CHANGE, D6); `aggregation.py:803-817` `_get_effective_rate_kwh`/`_predicted_import_rate` (CHANGE, D4); export `CONF_EXPORT_REIMBURSEMENT_RATE` at `aggregation.py:2567` (tomorrow attrs), `:2600` (tomorrow value), `:2646` (today attrs), `:2692` (today value), `:2758` (week), `:2824` (month): **all six CHANGE** to the engine's export rate through the D4 helper. After the change, `CONF_EXPORT_REIMBURSEMENT_RATE` has no reader in `aggregation.py`. The import at `:113` is removed and the config field is left for its other users (builder greps the package).
- **Tomorrow/day TZ sites:** `database.py:3163, 3218, 3240, 3305, 3317`.
- **Consumption consumers (INV-SHADOW-1):** DP `energy.py:5213-5229` (+ real tick `:5585`), `battery_full_time` `energy_forecast.py:698`, D7 `energy.py:12782`, accuracy eval `energy.py:3579`, `energy_daily.predicted_consumption_kwh`, `energy_daily.avg_temperature` (via `_prediction_temperature`), display.

## 9. Non-goals
- **Flipping `CONF_R1_ESTIMATOR_SHADOW_ONLY` (the shadow flip).** It is moved out of this cycle to its own Tier-3 gate, because it changes DP drain-pause `house_load_kw` under the `max_span_r1` default and `battery_full_time`. Gate definition for that later cycle:
  - **Metric:** D5 rows for the arm that would be consumed (`v2`, or `hvac_zone` if shipped).
  - **Window:** ≥ 14 consecutive local days after D8/D9 deploy, with no poisoned-input days.
  - **Pass:** |NMBE| ≤ 10 kWh/day and MAE ≤ the `dow_legacy` MAE on the same days. That cycle also owns the D-MED-1 adjustment-factor reset.
- Backfilling `arbitrage_cycles` or rewriting lifetime baselines.
- Option C hourly simulation.
- Battery-full-time logic, HVAC ramp savings, predicted bill.
- Dashboard work beyond relabelling: "Net tomorrow (forecast)" (operator Q4 yes; dashboard-only step at ship).
- The poisoned `energy_history`/`energy_daily` history. D4 reads energy_history only for shares over the last 14 days, after the poisoning window.
- Any HVAC decision change (D9 reads recorder history only).

## 10. Tier and build split (rev 5)
**Two builds** (plan review 2, Scope):
- **Build 1 = D1, D2, D6, D7** (money + physics). Tier 2-DB. Ships first. No dependency on D0/D8/D9. D7 reads the consumed `predicted_consumption_kwh`, unchanged.
- **Build 2 = D0, D8, D9, D3, D4, D5** (forecast). Tier 2-DB. D0 runs first and gates D3 (A vs D3b). D9's `hvac_zone` arm waits on the operator confirming `sensor.span_panel_ac1` / `ac_2` / `ac_3` → HVAC zones 1/2/3; the v2 refit and the rest of Build 2 do not wait. Build 2 gets its own plan review against this doc before dispatch.

**Tier 2-DB** (three framing-disjoint reviews + live validation). Triggers: new columns on `arbitrage_cycles`, a new table, changed savings-record semantics, a new persisted `energy_state` key with restore, and the arbitrage↔PA double-count guard. **Not Tier 3:** every value in scope is display-only. The only decision-adjacent path (DP / battery_full_time via consumed consumption) is pinned unchanged by INV-SHADOW-1, and the flip that would change it is out (§9).
- **A:** arithmetic, rate basis, the B2 split, TZ/DST, the D8 date selection.
- **B:** migration, write queue (inventory cadence, D5 batch), restore/seed/cutover, today/cycle/lifetime no-double-count.
- **C:** per-site mutation: D1 accrual, inventory split, D2 guard, D4 helper, D8 selector, and the INV-SHADOW-1 golden.

## 11. Operator decisions (2026-11-01) — all applied in rev 3
1. Solar-charged basis **B2**: §4.1, D1. 2. Off-peak discharge **$0**: §4, D2. 3. Predicted-today **→ EC forecast**: D4. 4. Relabel **yes**: §9. 5. Net-energy program merged (R1 temp fix and refit) as D8/D9. The shadow flip is out (§9). 6. INV-RATE-1: §2, D4, §8.

Rev 2's open questions Q1–Q4 are all answered above and have been deleted.

## 12. Setpoint-vs-outdoor delta (operator input) — folded into D9
The physics rationale stands: heat gain scales with (outdoor − indoor), and a fitted balance point learns only the average setpoint. Rev 4: superseded by D9's per-HVAC-zone arm (indoor or setpoint, whichever backtests better). "Correct as you go" = the D3 bias term, applied on top of whichever arm wins.

## 13. Build 1 brief (self-contained)
**Scope:** D1 (discharge-time arbitrage savings, B2 inventory), D2 (PA battery credit = 0), D6 (cost/hr on effective rate), D7 (forecasted import without battery cancellation). Tier 2-DB; reviews A/B/C per §10 restricted to these deliverables.

**Files:** `domain_coordinators/energy_billing.py` (`PeakAvoidanceTracker.accumulate`: return per-tick `battery_served_kwh`, `charge_kwh_grid`, `charge_kwh_solar`, `discharge_kwh`; battery credit 0), `domain_coordinators/energy.py` (`_account_arbitrage_cycle` ~4214-4320 → inventory apply + discharge rows; `_get_displaced_rate` callers 4281, 4437; inventory restore/persist via `save_energy_state`/`restore_energy_state`; `predicted_import_kwh` ~12770), `database.py` (migration of 3 columns; `save_arbitrage_cycle`; readers ~6340-6420 per D1 F4), `sensor.py` (9377 + ~9455 effective rate; arbitrage attrs 11405-11565), `energy_const.py` (§7 knobs for D1), tests under `quality/tests/`.

**Invariants:** INV-SAV-1, INV-RATE-1 (no rate literals; sums read `SUM(savings)` only). Split computed before the net/served gates (§4.1 F1). Inventory writes ≤ 96/day through the write queue. Consumed consumption values untouched (D7 changes only its own formula).

**Tests:** all D1, D2, D6, D7 tests listed above, including `test_arbitrage_inventory_fills_on_grid_only_charge` and `test_arbitrage_readers_discharge_rows`. Migration test extracts DDL from production source. Per-site mutation targets for reviewer C: split placement, D1 accrual, D2 guard, D6 rate, D7 formula.

**Acceptance:** the D1/D2/D6/D7 Verify + Live criteria. Key live checks: overnight `energy_state.arbitrage_inventory.kwh` rises during off-peak grid charge; evening rows are all `accrual='discharge'` (local-time conversion in Python); `peak_avoidance_today` flat 17-21 with solar 0; cost/hr ÷ net kW ≈ effective rate.

**Out of scope for Build 1:** D0, D3, D4, D5, D8, D9; any `aggregation.py` change (export-rate sites, `_predicted_import_rate`); predicted energy/cost sensors; the shadow flip; backfill of `arbitrage_cycles`.

