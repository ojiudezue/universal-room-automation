# Plan review 2 — PLANNING_ec_savings_and_tomorrow_forecast.md rev 4 (Tier 2-DB)

Verdict: **FIX-PLAN** (small fixes; most of the plan is sound)

Prior findings: 1 (B2), 2 (D4), 3 (six export sites, `aggregation.py:2567…2824` in §8), 4 (D8 date-keyed, no fallback), 6, 7 and 8 are fixed. 5 is only partly fixed (see F2).

1. **HIGH: the inventory never fills from grid charging.** `accumulate` returns early when `served_kw < PEAK_AVOIDANCE_MIN_SERVED_KW` (`energy_billing.py:1018-1023`). An overnight grid charge has served = 0, so the "returned" charge split is never computed. It also returns on the first tick, when net is None, and when elapsed > 1 h. The inventory would sit on the SOC seed or the empty fallback. Fix: compute the charge split and the discharge kWh before any served-gate return. Add a test: a grid-only charge tick with solar 0 grows `inv_kwh`.
2. **HIGH: the D8 shadow temp would leak into the consumed arm.** The plan points at `energy_forecast.py:278`, which is the single `temp` passed to `_estimate_consumption`. That feeds `_compute_legacy` (temp-scaled, :362-386), `_prediction_temperature` (→ `energy_daily.avg_temperature`, `energy.py:3612`), and the consumed value. Fix: say that a separate `shadow_temp` is threaded only into the v1/v2 call, and that `temp`/`_prediction_temperature` stay as they are. Add `energy.py:12782` (D7) and `:3579` to the INV-SHADOW-1 consumer list.
3. **MEDIUM: the D9 pure function is keyed on `now`.** `_compute_v1` takes the season and the EV era from `now` and hard-codes `CONSUMPTION_REGRESSION_V1` (:302-345). Tomorrow needs the target date (Nov 30 → Dec 1 changes season) and a consts parameter. State the signature.
4. **MEDIUM: other readers break on discharge rows.** `query_arbitrage_last_cycle` and `pace_recent` (`database.py:~6382, 6413`) and the `SUM(kwh_charged)` attributes will read 0 kWh. Define their semantics or filter them.
5. **LOW:** a battery discharge that goes to export is not drained from the inventory. Only the SOC cap repairs this. Document it.

**Scope:** the cycle is too big for one build. **Split it.** Build 1 = D1, D2, D6, D7 (money and physics; Tier 2-DB). Build 2 = D0, D8, D9, D3, D4, D5 (forecast; D0 gates D3, and the operator still has to confirm the D9 wiring).
