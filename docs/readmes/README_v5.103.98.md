# v5.103.98: "Saved today" counts battery energy used at mid-peak and peak; cost per hour on the full rate

Card: EC-COST-AND-FORECAST-MATH-1 (Build 1 of 2). Plan: `docs/planning/PLANNING_ec_savings_and_tomorrow_forecast.md` rev 5 (two plan reviews). Tier 2-DB: reviews A/B/C SHIP (C added 14 tests), full-suite name-diff vs ca3a0eb6 clean (31 pre-existing on both). Deploy risk: LOW-MEDIUM (display and savings ledger only; no battery, drain, EVSE or HVAC decision input changed).

## Problem
Audit `docs/planning/AUDIT_ec_savings_and_cost_forecast_math.md`:
- `arbitrage_savings_today` booked grid-charged kWh at charge time with a base-rate vs effective-rate mismatch: a 0.05¢ spread instead of ~4.3¢ ($0.01 on 11-01 instead of ~$0.79).
- Peak avoidance credited battery discharge in mid-peak/peak at the adders only, which would double count once savings move to discharge.
- `current_grid_cost_per_hour` used the base rate (~33% low).
- Forecasted import subtracted battery capacity from a whole-day shortfall (15 kWh predicted vs ~80 actual).

## Fix (operator decisions 2026-11-01)
- Savings accrue at DISCHARGE, in mid-peak and peak only: battery kWh served × (live effective rate − cost of that stored energy). Off-peak discharge earns $0.
- Cost of stored energy (B2): a running inventory (kWh, $). Grid share of each charge = min(charge, grid import), priced at the off-peak effective rate; the rest is solar, priced at the export credit forgone. Capped at SOC × capacity; restored after restart (retries if the read fails or SOC is unknown); empty → off-peak effective rate.
- Every rate is read live from the TOU engine (new `get_offpeak_effective_import_rate`); a tariff change applies on the next tick.
- Peak avoidance gives the battery zero credit in any period. Cost per hour uses the effective rate. Forecasted import = max(consumption − production, 0).
- `arbitrage_cycles` gains 3 columns (guarded migration; old rows read as charge-time). Today and cycle totals use discharge rows only. `cycles_*` = distinct local days with savings; raw tick counts in `discharge_ticks_*`. Lifetime attrs split old charge-time and new discharge-time kWh.

## Known limits
- Cutover night: the lifetime total counts energy charged before the deploy once at charge time and again at discharge. Today and cycle totals are unaffected.
- Discharge straight to export is not removed from the inventory; the SOC cap corrects it.
- Net Tomorrow, predicted costs and the consumption forecast are Build 2.

## Tests
`test_ec_savings_money.py` (55), 130 of 133 mutation sites RED (3 equivalent mutants). Name-diff clean.

## Live acceptance (prospective)
| Criterion | How to check |
|---|---|
| Savings accrue at discharge | During tomorrow's 17:00+ mid-peak discharge, `arbitrage_savings_today` rises tick by tick; order of $1/day, not $0.01 |
| Off-peak earns $0 | No accrual rows with an off-peak timestamp |
| Cost/hr on effective rate | `current_grid_cost_per_hour` ≈ net import kW × effective rate (≈0.129 mid-peak) |
| Inventory | Diagnostics show inventory kWh ≤ SOC × capacity and a cost basis between export credit and off-peak effective rate |
| Load clean | No URA ERROR after restart |
