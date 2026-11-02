# v5.103.100: savings can go negative; tomorrow's forecast on the local date with Solcast and per-period pricing; forecast accuracy log

Card: EC-COST-AND-FORECAST-MATH-1 (Build 2 of 2). Plan: `docs/planning/PLANNING_ec_savings_and_tomorrow_forecast.md` rev 5. Tier 2-DB: reviews A SHIP, B SHIP (2 MEDIUM fixed in 29fd7d33), C SHIP (100 mutation sites; 17 gaps closed with 23 tests, 95372b2d). Deploy risk: LOW-MEDIUM (display, savings ledger and a new log table; no battery, drain, EVSE or HVAC decision input changed; R1 stays shadow).

## Changes
- **Saved today can go negative** (operator 2026-11-02). The ≥ 0 clamp is gone: a mid-peak/peak discharge whose stored cost ÷ 0.90 exceeds the current rate books a loss row. Today, cycle, lifetime and the predicted bill "without arbitrage" carry it. Lifetime is now the live table total (the baseline is used only when the table reads empty), so a net loss is not hidden. Off-peak discharge still books nothing.
- **Tomorrow's forecast (D3):** uses the local date (not UTC after 18:00), Solcast for production, and a 14-day bias term. The old history model stays as a fallback arm.
- **Per-period pricing (D4):** predicted cost uses the historical share of use per TOU period × live TOU rates (export at the engine's export rate). Week/month windows start at local midnight.
- **Forecast temperature (D8):** date-keyed daily mean (high + low)/2 from `weather.phalanxmadrone`, no fallback; the list ages out after 6 h without a good fetch. Feeds the shadow arm only.
- **Models (D9):** v2 refit FAILED its gate (October MAE 47.4 vs v1 27.3 kWh/day; history starts 2026-03, no winter), so `CONSUMPTION_REGRESSION_ACTIVE` stays `v1`. v2 (no EV term) and a per-HVAC-zone model (AC 1-3 = zones 1-3, MAE 20.8; a trailing 14-day mean scores 22.2) are logged only.
- **Accuracy log (D5):** new table `energy_forecast_log`, one batch per day at/after 21:00 local, first complete row wins, skipped and retried when the active arm is missing. Per-model accuracy attributes on the forecast sensors.
- Forecast work runs in a tracked background task, never inside the battery decision tick.
- `predicted_energy_today` keeps its meaning (import − export); it is the negated EC net.
- EC manual §4.3 updated.

## Known limits
- Net forecast is priced at import rates only (D4 design); `cost_mae_30d` will measure it.
- Week/month cost prices the span with today's day type and season.
- Predicted today has no bias term; tomorrow does.
- Lifetime savings assume `arbitrage_cycles` is never pruned (comment fence; no test).
- Backtest used actual temperatures (forecast temps are not recorded), so live error will be somewhat higher.
- Model constants are fitted to this house.

## Live acceptance (prospective)
| Criterion | How to check |
|---|---|
| Signed savings | A losing discharge tick books a negative `arbitrage_cycles` row; `arbitrage_savings_today` can read < 0 |
| Tomorrow on local date | After 18:00 local, predicted tomorrow uses tomorrow's local weekday and Solcast tomorrow |
| Per-period cost | Predicted cost tomorrow ≈ Σ period share × live rate × kWh (attrs) |
| Log | At 21:00+ one `energy_forecast_log` batch for tomorrow with non-null active-arm values |
| No tick delay | No skipped TOU-boundary tick; decision cycle timing unchanged |
| Load clean | No URA ERROR after restart |
