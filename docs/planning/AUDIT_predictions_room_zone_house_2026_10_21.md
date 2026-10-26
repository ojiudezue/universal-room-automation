# AUDIT: URA prediction outputs, room / person / house level (2026-10-21, ~16:00 CDT)

Read-only probe. Scope excludes the occupancy-anomaly sensor (`AUDIT_occupancy_anomaly_rate_2026_10_20.md`) and the bill prediction (v5.103.79). This is not HVAC/presence design work; the two STATE_OF_PLAY docs were not needed and were not read. Evidence: live recorder (`ssh ha`, `/config/home-assistant_v2.db`), URA DB (`/config/universal_room_automation/data/universal_room_automation.db`), repo code at the cited file:line. Scripts were in the session scratchpad (not committed).

## Answer
**No prediction output in URA is both useful and correct today.** None is consumed as a trust decision (all are display or diagnostic), so nothing is currently being harmed, but none is safe to build "advanced things" on yet.

- The three **occupancy / next-room** predictions all come from one model (`BayesianPredictor`, Dirichlet counts of room *arrivals* per person x 6 time bins x weekday/weekend). Backtested, they have **no skill over a trivial constant** (details below). Root cause is the model (counts arrivals, not dwell, and is blind to where the person is now), not wiring.
- The **per-room next-occupancy / precool / preheat** family has no skill over a random hour (36% vs 34% base).
- The **energy / cost** family is the best-intended and is still wrong or stale: the net-import forecast has a ~41 kWh mean absolute error over 6 days, and the consumption forecast is rated "poor" by its own scorer.
- 3 outputs are **dead** (never populate); several others are **not predictions** (heuristic scores or operator-entered lists).

## Table

| # | Output (entity pattern) | Level | Producer (file:line) | Model | Consumers | Live (2026-10-21) | Backtest | Verdict |
|---|---|---|---|---|---|---|---|---|
| 1 | `sensor.<person>_likely_next_room` (4, diagnostic, disabled by default; enabled for persons) | person | `sensor.py:3340`, calls `bayesian_predictor.predict_room_at_time` (`bayesian_predictor.py:796-813`, `:407-464`) | argmax of per-person arrival counts in the current time-bin cell; **not conditioned on current room** | Display only. Logged to `prediction_results` (feeds #3). No actuator/coordinator reads it (grep of `custom_components`) | Populated. Oji "Receiving Room" 0.20, Jaya "Kitchen" 0.13, Ezinne "Master Bedroom" 0.18, Ziri "Game Room" 0.11 | See #3 | USEFUL-BUT-WRONG |
| 2 | `bayesian_occupancy_forecast` / `_pattern` (per room; 4 / 2 of 47 enabled) | room | `sensor.py:15199`, `:15061`, `predict_room_occupancy` `bayesian_predictor.py:466-504` | 1 - prod(1 - alpha_room/alpha_total) over persons, per time bin | Display only. Same probability feeds anomaly sensor (excluded) | Populated, but `forecast_now`, `+1h`, `+4h` are near-identical (Game Room 11.9 / 11.9 / 11.8; Laundry 3.9 / 3.9 / 2.6) so the "forecast" is flat across a bin | AUC 0.605, Brier 0.0854 vs 0.0847 for a constant (14 d, 3127 samples); see notes | USEFUL-BUT-WRONG (no skill) |
| 3 | `*_next_room_accuracy` (4) + `house_next_room_accuracy` + `bayesian_prediction_accuracy` | person/house | `sensor.py:15325`, `:15526`, `:15262` | Scorers over `prediction_results` | Display, plus Optimization "Prediction-Validation pillar" read (`optimization.py:3693-3760`, read-only) | Oji 17.0%, Jaya 15.4%, Ezinne 31.9%, **Ziri unknown (0 predictions in 7 d)**; house 16.9%; occupancy "hit rate 94.4%, Brier 0.0572" | Re-scored by me, below | USEFUL (as a scorer) but the 94.4% headline is misleading |
| 4 | `sensor.<room>_next_occupancy_time` (+ `precool/preheat_start_time`, `_lead_minutes`; 1 of 47 precool/preheat enabled) | room | `database.py:3609-3680` (`get_next_occupancy_prediction`), `coordinator.py:5517-5561` | Mode of entry-hours on the same weekday in the last 7 days, i.e. essentially ONE prior day. Lead times hard-coded 15 / 20 min (`coordinator.py:5557-5558`) | Display only (grep: no coordinator reads `STATE_NEXT_OCCUPANCY_*`/`STATE_PRECOOL_*` outside `sensor.py`) | Mixed: ~16 rooms populated, ~14 `unknown`; Study A precool/preheat `unknown` | 20 of 55 hits (36%) vs 34% base rate of any entry in a random hour | NOT USEFUL |
| 5 | `sensor.<room>_occupancy_pattern_detected` (23-27 registry entries) | room | **None.** `STATE_OCCUPANCY_PATTERN` is defined (`const.py:1969`) but assigned nowhere; sensor removed, superseded by #2 (`sensor.py:644`) | n/a | n/a | `unavailable` since 2026-10-20 22:23 CDT (orphan registry entries) | n/a | DEAD (orphan) |
| 6 | `predicted_energy_today / tomorrow / week / month`, `predicted_cost_*` (non-bill) | house | `aggregation.py:2211-2300`, `:2459-2530`; `database.py` `predict_energy` | Historical "similar days" net grid import (`import - export`), clamped >= 0 for display; confidence 11-22 "very low" for day/week/tomorrow | Display only (no reader found) | Populated. today 55.6, tomorrow 55.8, week 304.7, month 1828 kWh | Today-forecast at 01:xx vs actual net import (import - export, `energy_daily`): see notes. MAE 41.1 kWh over 10-15..10-20 | USEFUL-BUT-WRONG |
| 7 | `ura_energy_coordinator_forecasted_consumption`, `energy_forecast_today`, `forecasted_energy_import` | house | `energy_forecast.py:50` (`DailyEnergyPredictor`) -> `sensor.py:12006-12170` | Day-of-week legacy baseline x adjustment factor (0.785); R1 estimator in shadow | Feeds Energy coordinator planning (this is the one prediction with a real consumer; consumers not enumerated further here, unknown) | Consumption populated (124.1 kWh). `forecast_today` and `forecasted_import` `unknown` since 14:56 because `predicted_production_kwh` is null (`battery_full_time` basis "unavailable") | Self-scorer: 28.5% "poor", 30 samples. `energy_daily`: 10-02..10-04 predicted 1204 / 743 / 1144 kWh vs actual ~86-98 (poisoning, known); 10-19 pred 211 vs 107.9 actual (+96%), 10-20 pred 126.5 vs 120.25 (+5%) | USEFUL-BUT-WRONG |
| 8 | `forecast_accuracy` (energy) | house | `sensor.py:12174` | Rolling error scorer | Display | 28.5 "poor" | n/a | USEFUL (honest scorer) |
| 9 | `predicted_cooling_need`, `predicted_heating_need` | house | `aggregation.py:1718-1815` | Hard-coded degree-day: cool = 2.0 + 0.5 x (high-65) + 0.3 x max(occupied rooms, zones); heat = 1.5 + 0.4 x (65-low). Constants are not fitted | Display only | 12.0 and 6.3 kWh | No cheap ground truth (no HVAC-only kWh series located). **Unknown** | NOT USEFUL (uncalibrated, and uses *current* occupied-room count as a forecast input) |
| 10 | `hvac_pre_cool_likelihood` | house | `hvac_predict.py:303-346` | Additive score: forecast high (0-40) + near-TOU-peak (0-30) + low SOC (0-20) + summer (+10) | Display / attribute only (`hvac.py:8216`) | 15 | Not a probability, no outcome to score | NOT A PREDICTION (heuristic score) |
| 11 | `weather_apparent_forecast_high` | house | `sensor.py:9765` -> `weather_manager` | Passes provider forecast | Energy coordinator caches it (`energy.py:8102-8127`) | `unavailable` | Unknown | DEAD (live) / check provider |
| 12 | `security_expected_arrivals` | house | `sensor.py:7547`, `security.py:246-312` | **Operator-entered** expected-arrival list, not a prediction | Security sanction checker | 0 | n/a | NOT A PREDICTION |
| 13 | `hvac_pre_arrival_status`, `*_routine_status`, `household_routine_status` | house/person | `hvac.py`, regime detector | Trigger state / drift detector, not forecasts | HVAC pre-arrival logic; display | idle; Jaya/Oji "drifting", Ezinne "shifted", Ziri "stable" | n/a | NOT A PREDICTION |

(`solcast_pv_forecast_accuracy` 72.8 is Solcast's own sensor, not a URA output, so it was not audited.)

## Notes (plain language, per item)

### 1 and 3. Next room is effectively a constant per time-of-day
- Producer check. `predict_room_at_time` only looks up the person's time-bin cell (`bayesian_predictor.py:407-464`). It never asks where the person is *now*, so "next room" is "the room where this person most often arrives at this time of day". Over 14 days Oji's 6,844 logged predictions took only **2 distinct values** (Receiving Room 3,629, Master Bedroom 3,215); Ezinne 3; Jaya 5.
- Backtest (`prediction_results`, `prediction_type='next_room'`, 2026-10-07 to 10-21, actual = room actually entered at the transition):

| person | n | top-1 | top-1 + 2 alternatives | trivial baseline "always the most common actual room" |
|---|---|---|---|---|
| Oji | 6844 | 19.2% | 38.3% | 19.3% (Master Bedroom) |
| Ezinne | 3125 | 26.5% | 48.2% | 26.2% (Master Bedroom) |
| Jaya | 3119 | 14.6% | 38.5% | **25.6%** (Jaya Bedroom) |
| Ziri | 0 | n/a | n/a | n/a |

  Oji and Ezinne equal the constant baseline; Jaya is **worse** than it. Stated confidence (0.17-0.24) roughly matches the hit rate for Oji/Ezinne, so it is honest about being weak.
- Caveat on n: Oji's rows are dominated by flapping neighbours (e.g. Foyer / Study A transitions seconds apart at 2026-10-21 20:30-20:33 UTC), so the effective sample is far smaller than 6,844 and the 17-19% is noisy.
- Ziri: `likely_next_room` shows "Game Room" but `next_room_accuracy` has 0 predictions in 7 d. Why no results are logged for Ziri is **unknown** (not traced).
- Consumers: none beyond display and the accuracy scorers. Producer-only today.

### 2. Occupancy probability has no discrimination
- Backtest (`bayesian_occupancy`, 14 d, 3,127 room-samples; 292 occupied, 2,835 empty):
  - Mean predicted when occupied 0.145 vs 0.082 when empty. **AUC 0.605** (0.5 = coin flip).
  - Brier 0.0854 vs 0.0847 for always predicting the base rate (0.093). No skill.
  - Calibration: predicted < 0.02 -> actually occupied 7.8% (n=1116); predicted 0.10-0.20 -> 8.4%; predicted 0.20-0.40 -> 12.3%; only the >= 0.40 bin (n=55) is calibrated (0.50 vs 0.56). Low and mid predictions are not ordered correctly.
- Matches the 2026-10-20 anomaly audit: the model measures where people *arrive*, not where they *dwell* (Oji spends 20 h in Study A, but Study A has 1.1% belief share).
- The "+1h / +4h" forecast values are the same bin lookup, so they carry no extra information over "now".

### 3b. The accuracy headline is misleading
- `bayesian_prediction_accuracy` shows hit rate 94.4% and Brier 0.0572 (7 d, 1,495 predictions). But 90.7% of room-samples in my 14-day pull were simply "empty", so always saying "empty" scores about 91%. Brier 0.0572 is a different window and room mix from my 0.0854 and I did not reconcile the two. Do not read 94.4% as skill.

### 4. Next-occupancy / precool / preheat
- Producer (`database.py:3609-3680`): for the same weekday in the last 7 days, take the hour with the most entries after now; that is one prior day. Lead times are literals 15 and 20 min (`coordinator.py:5557-5558`), which breaks the Numbers-Get-Knobs rule and is not tied to any room's thermal response.
- Backtest: simulated 7 days x 8 busiest rooms (55 valid predictions), hit = an entry in the predicted hour. 20/55 = 36% vs 34% for "any entry in a random hour 10-23". The one room with 7/7 is the busiest (1,151 entries in 3 weeks), where almost any hour hits. Approximation: I replayed the "today" branch only and used `occupancy_events` entry rows (which include flapping), and the DB `room_id` there is the config-entry id.
- Consumers: none found outside the sensors. HVAC pre-arrival uses geofence / BLE / camera triggers instead (`hvac_pre_arrival_status` sources), not these.

### 5. occupancy_pattern_detected
- No producer exists anywhere in `custom_components` (`grep STATE_OCCUPANCY_PATTERN` hits only `const.py:1969`). The registry still has 23-27 orphan entries. Candidate for registry cleanup (a card, not done here).

### 6. Net-import energy forecast
- Definition matters: the value is *net grid import* (import minus export) and clamps negative to 0 (`aggregation.py:2218-2232`), so on solar-export days "predicted 55 kWh" is compared against a net that can be negative.
- Backtest, forecast read from the recorder at ~01:00 vs actual net import from `energy_daily`:

| day | predicted (01:xx) | actual net (import - export) | error |
|---|---|---|---|
| 10-15 | 40.6 | 0.0 | +40.6 |
| 10-16 | 55.7 | -8.1 | +63.8 |
| 10-17 | 32.5 | -16.8 | +49.3 |
| 10-18 | 55.0 | -22.0 | +77.0 |
| 10-19 | 52.3 | 39.7 | +12.6 |
| 10-20 | 65.3 | 62.0 | +3.3 |

  Mean absolute error 41.1 kWh. Naive "yesterday's actual" would have scored 21.2 kWh MAE over the 5 comparable days. n=6 so this is indicative only. The error was largest on high-export days (10-15..10-18), when the history-based "similar days" cannot see that solar was strong.
- `energy_daily` has gaps: `import_kwh` is populated every day but `consumption_kwh` and `predicted_consumption_kwh` are NULL on most days (2026-10-05 to 10-17 entirely), so the consumption forecast cannot be scored for those days. That gap is itself a finding (scorer starved of ground truth).

### 7. Energy-coordinator consumption forecast
- Producer: `DailyEnergyPredictor` (`energy_forecast.py:50`). Output swings day to day (recorder, 01:xx: 10-14 113.2, 10-15 107.1, 10-16 105.1, 10-17 132.0, 10-18 128.0, **10-19 223.8**, 10-21 126.6) against actual consumption of ~108-120 kWh on the two days with ground truth (10-19 107.9, 10-20 120.25). So it is plausible most days with one large outlier (10-19) and the earlier 700-1200 kWh poisoning (`AUDIT_energy_consumption_forecast_poisoning_2026_09_29.md`).
- `forecast_today` and `forecasted_import` are `unknown` because the production (solar) half is null; the consumption half is fine. Worth a card only if something is meant to consume the import figure.

### 9 to 13
- #9 cooling/heating need: constants not fitted, units "kWh" unverified. The current-occupied-room count (`:1745-1749`) makes the "forecast" move with who is home right now.
- #10: a rule-of-thumb score; it is neither calibrated nor tested against outcomes.
- #11: `unavailable` at the time of reading; producer path `current_apparent_forecast_high()` not traced. Unknown why.
- #12, #13: listed only so the inventory is complete; they are not predictions.

## Shared root causes
1. **Arrival-count model** (`bayesian_predictor.py:233-405`) feeds #1, #2 and the anomaly sensor. It counts room *transitions into* a room, so heavily used rooms with few arrivals look "never occupied", and scanner-borrow / flapping neighbours (Study A Closet, Receiving Room) soak up probability. Fix is one model change (dwell-weighted cells, and conditioning next-room on the current room), not per-sensor patches.
2. **Time-bin-only lookup**: nothing conditions on current room, house state or whether the person is home, so "now / +1h / +4h" are nearly identical.
3. **Scorer inflation**: accuracy headlines are dominated by the empty-room base rate (occupancy) and by flapping transitions (next room).
4. **Ground-truth gaps** starve the energy scorers (`energy_daily` NULLs) and Ziri has no scored predictions.
5. **No skill baseline anywhere**: no scorer compares against the trivial constant, which is how a no-skill model reads as "active / 94% hit rate".

## Falsification and limits
- Conclusion #1/#2 "no skill" would be wrong if a fresh 14-day window showed AUC well above 0.6 or top-1 well above the constant. I used the live `prediction_results` table, so a different window or the online model's earlier states could differ slightly; the 2026-10-20 audit independently found the same shape (57% of occupied samples scored < 0.10).
- Sample caveats: energy backtest n=6; next-occupancy backtest is a replay approximation; flapping inflates row counts.
- Not done: HVAC-only kWh ground truth for #9, tracing why Ziri logs no scored predictions, tracing the `unavailable` apparent-forecast-high, enumerating every consumer of the energy consumption forecast.

## Suggested cards (not created; I make no board changes)
1. Cleanup: remove orphan `occupancy_pattern_detected` registry entries (#5).
2. Scorer: add a "vs trivial baseline" skill metric to the next-room and occupancy accuracy sensors, and dedupe flapping transitions (#3).
3. Model: next-room conditioned on current room, dwell-based occupancy (shared root cause 1). Gate any consumer of predictions on that skill metric.
4. Energy: backfill `energy_daily.consumption_kwh` so the forecast scorer has truth; investigate null `predicted_production_kwh` and the `unavailable` apparent-forecast-high.
