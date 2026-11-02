# EC Forecast Build 2: Review A (data integrity + money correctness)

Branch `fix/ec-forecast-build2` @ 5a58c6d7. Base develop 12e979b7 (`git merge-base` confirmed). Three-dot diff.
Targeted tests: build2, savings_money, house_energy_correctness, predicted_energy_tomorrow, energy_history_kwh_integration. 118 passed.

## Findings

| # | Sev | Site | Finding | Bug class |
|---|---|---|---|---|
| A1 | LOW | `aggregation.py` week/month cost (`_price_predicted(..., now.date())`) | A 7-day or month kWh total is priced with *today's* day-type and season representative instants. INV-FC-2 holds (period mix, not one instant), but a weekend run or a month that crosses a season change prices the whole span on one day's schedule. Display only. | approximation / day-boundary-blind |
| A2 | LOW | `energy_forecast_tomorrow.py:price_net_kwh` | Net (import − export) is priced on one side's shares, so a day with 40 kWh import and 30 kWh export prices 10 kWh at import rates, not 40×imp − 30×exp. This follows plan D4 (`Σ_p share_p × net × rate_p`). It is a model choice, not a defect; the D5 `cost_mae_30d` will measure it. | model choice |
| A3 | LOW | `sensor.py:11814-11827` lifetime | `max(baseline, live)` was replaced by "live when rows > 0, else baseline". Safe today because nothing deletes from `arbitrage_cycles` (grep: no `DELETE FROM arbitrage_cycles`; the only writer is `INSERT`, `database.py:6482`). If a prune is added later, lifetime would silently drop. That needs a comment-level fence at the prune site, not a code change now. | latent coupling |
| A4 | LOW | `aggregation.py:_ec_today_net_import` | Today's net = −(pv − consumption) with **no** D3 bias term. Tomorrow = consumption − solar + 14-day bias. The two are on different bases, and the bias covers battery/net-meter gaps. This was decided by the operator (Q3), but the dashboards will show today and tomorrow on different bases. | concept split (#63-adjacent) |

No CRITICAL/HIGH/MEDIUM.

## Cleared (holds because)

- **Signed savings, writer:** `energy_billing.py:951-964` unclamped; `energy.py:4632` books `!= 0`. Off-peak cannot reach it because the caller gates `period in _DISPLACED_PERIODS and served_kwh > 0` (`energy.py:4618`). The legacy charge-time path still drops negatives (`energy.py:4319`), but discharge accrual returns before it.
- **Signed savings, readers:** today/cycle/total come from `SUM(savings)` (`database.py:6533-6610`). Pace is a Python sum of signed rows (`:6660+`). The three arbitrage sensors and the total family are `state_class TOTAL`, not TOTAL_INCREASING, so negatives are legal. `predicted_bill_without_arbitrage` now flows a negative pace (`sensor.py:11324`), and `arbitrage_savings_pct` stays guarded by `without_arb > 0`. `total_savings_this_cycle` adds signed values. No reader clamps.
- **Lifetime:** `query_arbitrage_savings_total` returns a `rows` key (`database.py:6578-6584`). A failed query returns `rows: 0` and falls back to baseline, so there is no zero-flash.
- **energy_forecast_log:** `CREATE TABLE IF NOT EXISTS` via `_create_table_safe`, PK (target_date, arm). Writes are one `executemany` + commit per day, batched, through `_db()`, with `DBShuttingDown` handled. Reads use `_db_read`. No existing table is touched.
- **Local-midnight helpers:** `_local_midnight_utc_naive` / `local_day_bounds_utc_naive` produce naive-UTC ISO, which matches the `energy_history` writer (`datetime.utcnow().isoformat()`, `database.py:3149`), so string comparisons are consistent. Week/month boundaries are now local. `predict_energy` uses the local target weekday.
- **INV-RATE-1:** every rate in `price_net_kwh` / `hour_weighted_rates` is read live from `tou.get_effective_import_rate` / `get_export_rate`. No literals, and nothing caches a rate across calls. The `CONF_EXPORT_REIMBURSEMENT_RATE` import was removed from aggregation.
- **Sign flip:** EC `predicted_net_kwh = pv − consumption` (`energy_forecast.py:330`), and the sensor negates it to import − export. Correct.
- **INV-SHADOW-1:** `CONF_R1_ESTIMATOR_SHADOW_ONLY=True` (`energy_const.py:271`), so the consumed value stays legacy on `temp`. Only the shadow arm reads `shadow_temp`.

## Verdict: **SHIP** (4 LOW, optional; A3 comment fence recommended)
