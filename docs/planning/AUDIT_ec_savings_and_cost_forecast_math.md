# AUDIT: EC "saved today", cost maths, "Tomorrow's Outlook" predictions
Probed 2026-11-01 ~21:00 CST (DST ended today; times CST). Read-only. Sources: repo `custom_components/universal_room_automation/` (cited), HA recorder `/config/home-assistant_v2.db`, URA DB `.../universal_room_automation.db`, `.storage/lovelace.ura_v8`, `tou_rates.json`.

## Answer
"Saved today" ($0.01) is a BUG, not a label problem. It counts the right thing (grid-charged kWh x rate spread x RTE) but the spread is computed from two non-comparable rates (0.000485 $/kWh instead of 0.04296). Under its own definition today should be ~$0.79, not $0.01. Net Tomorrow is not a solar-minus-load forecast at all (historical-pattern lookup) and has two real bugs plus a missing unit.

## 1. arbitrage_savings_today
- Display: dashboard "Saved today" card ura_v8 line 13013-13019 reads `battery_strategy.arbitrage_savings_today`; sensor.py:9331 = `round(arbitrage_status["today"]["savings"], 2)`.
- Producer: `_account_arbitrage_cycle` (energy.py ~4213-4320). Books a row ONLY on 5-min ticks where phase is CHARGE/ATTAIN and SOC rose. `kwh_charged = dSOC% x capacity`; `savings = kwh_charged x (displaced_rate - off_peak_rate) x 0.90` (energy.py:4283, RTE energy.py:4130). Accrues at CHARGE time, not discharge time. Discharge is never measured.
- Reset/restart: no in-memory state matters. Sensor sums DB `arbitrage_cycles` since local midnight (energy.py:4486-4497, database.py:6337-6360). Restarts at 10:18/14:10 are harmless (the charge window was 14:30+; `_arbitrage_prev_soc` only affects the first tick of a segment).
- THE BUG: `off_peak_rate = self._tou.get_effective_import_rate()` = base + delivery + transmission (energy_tou.py:554-557) = 0.043481+0.022546+0.019930 = **0.085957**. `displaced_rate = _get_displaced_rate()` returns the RAW `mid_peak.import_rate` (energy.py:~4203-4207) = **0.086442**, no adders. Spread booked = 0.000485. True spread (adders cancel) = 0.086442-0.043481 = **0.042961**. DB rows confirm (`arbitrage_cycles` id 811-818: off_peak_rate 0.085957, displaced_rate 0.086442, savings 0.00052/row). Same mismatch in summer (raw peak vs effective off-peak). Every day since 10-12 is ~$0.01 (10-29..10-31: $0.009-0.011).
- Reconstruction today (URA DB, 16 rows, 20.4 kWh charged, 14:45-16:00 CST, off-peak): sensor total $0.0089 = correct arithmetic on the wrong rates. Corrected formula: 20.4 x 0.042961 x 0.9 = **$0.79**.
- Operator definition (energy_history battery_level, 40 kWh pack inferred from 3% = 1.2 kWh): SOC 87% -> 28% during 17:00-21:00 = ~59% = ~23.6 kWh discharged in mid-peak. x (0.128918 - 0.085957 = 0.04296) = **$1.01** spread; avoided-import value 23.6 x 0.128918 = **$3.04** gross (not net of charge cost). Discharge energy was mixed grid- and solar-charged (SOC +39 in the 15:00 hour had grid 17.3 kWh, solar 5.2 kWh), so the sensor's definition (grid-charged only) is narrower than intuition; fine, but its docstring/label "savings" is optimistic by design (sensor.py:~11400 notes this).
- Also: the "Saved today" card shows only this arbitrage term; "peak-avoid"/"Total" live in separate sensors (ura_v8 line 13525).

## 2. Cost maths
- `energy_cost_today` $6.9002 = import_cost 6.9099 - export_credit 0.0096. Pricing is per counter-slice at the live effective rate (energy_billing.py:~453-482). Cross-check: avg 6.9099/79.694 = 0.08671. Implied mid-peak kWh = (6.9099-79.694x0.085957)/0.042961 = 1.39 kWh; energy_history shows 1.4 kWh imported 17:00-18:00, 0 after. Consistent. Export 0.0096/0.221 = 0.0434 = off-peak export rate. **CORRECT** (counter kWh not independently re-verified; history spot-samples sum to ~70 kWh vs 79.7 counter, a 13% gap I attribute to 15-min spot sampling, UNVERIFIED).
- Rates vs `tou_rates.json`: shoulder (Nov): mid 17-21 @0.086442, off-peak else @0.043481; adders 0.042476. CORRECT. `tou_rate` sensor = 0.086442 (base), `tou_period.effective_import_rate` = 0.128918. Two different "rate" numbers exposed; unlabelled.
- `current_grid_cost_per_hour` (sensor.py:9375-9395): uses `energy.tou_rate` (BASE rate 0.0864) x net kW, not the effective rate (0.1289). **BUG, understates 33%** in mid-peak (worse in summer peak: 0.1618 vs ~0.2043). Value 0.00 now (net 0.02 kW, exports excluded); the "$0.01/hr" claim is consistent with 0.06 kW x 0.0864. Units kW/W handled correctly (net_power_w / 1000).

## 3. Tomorrow's Outlook
- Card: ura_v8 lines 12815-12880. "Net Tomorrow" = `predicted_energy_tomorrow.raw_net_kwh`; label = `predicted_cost_tomorrow` + `forecast_temp_tomorrow`. "Solar Tomorrow" = Solcast 68.225 kWh (state, 16:32).
- Producer (aggregation.py:2456-2535, database.py:3285-3370): mean over up to 10 prior same-weekday days of (grid_import - solar_export) kWh. **Does NOT use Solcast, load, battery, or any forward model**; docstring (aggregation.py:2458) "solar forecast - expected consumption" is false. The adjacent 68 kWh solar tile and 53 kWh import look contradictory but are unrelated numbers. Net implicitly includes battery charging from grid (history import).
- Bug A (weekday): `predict_energy` uses `datetime.utcnow()` for `target_day` (database.py:~3322). After 18:00 CST UTC is already tomorrow, so "tomorrow" = day-after: 52.9 = mean of **Tuesdays** (replicated: 52.87, matches live 52.9); Monday mean replicates 46.05.
- Bug B (partial days): `get_energy_for_similar_days` filters ROWS by `outside_temp BETWEEN fc-10 AND fc+10` (database.py:~3153-3160), then sums per date, so days contribute only the in-range hours (rows 30-96 of 96). Observed nets mixed -27, -26, +72, +117 (10-06, 10-20, 10-13, 09-29). Temp should be a per-day (avg/high) filter. Also winter solar-export days cancel summer AC-heavy days: 83 F in November is summer-like load, but current-house baseline (last 7 days actual net 26-84 kWh/day; 10-26 Monday 17 kWh) differs.
- Confidence = 0 ("collecting") yet value shown without caveat on the card (display string says "(collecting)"; card label drops it).
- Cost $6.82 = 52.9 x 0.128918 (live `electricity_rate`, attrs; computed at 19:20 in mid-peak, cached). Producer `_predicted_import_rate` -> `_get_effective_rate_kwh` -> current-instant effective rate (energy_billing.py:61-67; aggregation.py:803-817). **BUG: whole-day kWh priced at whichever rate applies when it last refreshed** (mid-peak 0.1289 now; ~0.086 off-peak = $4.55; actual mix is mostly off-peak). Export credit uses CONF export rate 0.08 (config) vs engine 0.0435/0.0864 export rates: inconsistent. Delivery 0.05 is correctly NOT added (aggregation.py:803 note).
- Temp 83: `_get_forecast_temp(1)` (aggregation.py:1223) = tomorrow's forecast; used as +/-10 F row filter (see bug B). Unit/source of the weather entity: UNVERIFIED.
- Accuracy vs actual: no log of predictions vs actuals exists for these sensors (`prediction_results` holds room next-room predictions only). Last 7 days actual net (spot-sample est.): 10-26 17, 10-27 28, 10-28 26, 10-29 65, 10-30 70, 10-31 63, 11-01 ~84. Last-7 mean ~50, so 53 is plausible by luck, not by method. Day-to-day spread 17-84 means +/-30 kWh; low confidence.
- Display issues: "53 import" has no unit (card pv expression, ura_v8 ~12846, appends ' import'/' export' only; sibling "Tomorrow" tile at ~91101 uses 'kWh in'). `Net Tomorrow` name misleading (not solar-aware). `$6.82 cost` gives no hint it is a current-rate x historical estimate.

## Findings
| Item | Verdict | Evidence | Fix | Type |
|---|---|---|---|---|
| arbitrage_savings_today = $0.01 | BUG | energy.py:4283, ~4203; DB rows 811-818 (spread 0.000485) | displaced_rate must include adders (or both raw); expect ~$0.79 today | code |
| Arbitrage counts charge not discharge | MISLEADING-LABEL | energy.py:4213 | relabel "Arbitrage charge value"; optionally add discharge-measured metric | code/dashboard |
| energy_cost_today / import / export credit | CORRECT | slice pricing; implied mid-peak kWh 1.39 vs 1.4 history | none | n/a |
| tou rates vs schedule | CORRECT | tou_rates.json | none | n/a |
| current_grid_cost_per_hour | BUG (-33%) | sensor.py:9381 uses base `tou_rate` | use effective rate | code |
| Net Tomorrow producer | MISLEADING-LABEL | database.py:3285; not Solcast-based | rename "Typical net (history)" or build solar-aware model | dashboard/code |
| Weekday uses UTC | BUG | database.py ~3322; replicated Tuesday=52.87 | use local date | code |
| Row-level temp filter | BUG | database.py ~3153; partial days (33/96 rows) | filter by day avg/forecast high | code |
| Predicted cost rate | BUG | instantaneous rate applied to full day | use TOU-weighted or off-peak/mid mix from hourly profile | code |
| Predicted export rate 0.08 vs engine | MISLEADING | aggregation.py (CONF_EXPORT_REIMBURSEMENT_RATE) | use engine export rates | code |
| "53 Import" no unit | MISLEADING-LABEL | ura_v8 ~12846 | append ' kWh' | dashboard-only |
| Prediction accuracy vs actual | UNVERIFIED | no logged predictions | log daily predicted vs actual | code |
