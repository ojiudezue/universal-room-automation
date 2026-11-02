# Review A — EC savings money (fix/ec-savings-money 7016bfe4 vs ca3a0eb6)

Framing A: local correctness, edge cases, rate basis. Cycle tests ran green (44 passed).

## Findings
1. **LOW: `cycles` now counts ticks, not cycles.** `energy.py:4615-4648` writes one `accrual='discharge'` row on every peak/mid_peak tick with savings > 0, which is about 12 rows per hour. `cycles_today` / `cycles_this_cycle` (`sensor.py:11407`, `:11480`) now report tick counts under the name "cycles". This is display-only and goes through the write queue. Fix: relabel the attribute, or document it.
2. **LOW: legacy names stay in the total sensor.** `query_arbitrage_savings_total` mixes legacy charge rows with discharge rows (kwh_charged=0). `total_kwh_charged` is legacy-only and the old "v4.5.0" methodology text is still there (`sensor.py:11540-11546`). `_arb_kwh_scope('total')` still reads kwh_charged. Display-only.
3. **INFO (builder deviations, accepted):** the inventory is restored on the first applied tick. The first PA tick returns None, so restore-before-use still holds. The pace filter drops legacy rows by design.

## Cleared
- Grid split `min(charge, max(net,0))` matches the physics, and solar = the remainder (`energy_billing.py:1124`). When net is None, charge kWh are booked unsplit at the off-peak rate and earn no PA credit.
- Drain at the average leaves the basis unchanged. The cap scales cost so the average holds. An empty inventory or unknown SOC falls back to the off-peak rate. Savings are clamped ≥0.
- Off-peak discharge earns $0 and battery PA credit is 0 in every period. No double count.
- Cost/hr reads the effective rate live (`energy_billing.py:815`).
- `get_offpeak_effective_import_rate` = the season's lowest base rate + adders, read live per call. No rate literals outside tests.
- D7: `max(c−p,0)` handles None. The only consumer is display (`sensor.py:12164`).
- The migration ALTER is idempotent. Legacy rows default to `'charge'`. Readers of kwh_charged=0 rows are safe (no division).

INV-SAV-1 PASS · INV-RATE-1 PASS · INV-SHADOW-1 PASS

**Verdict: SHIP** (LOWs fold into the fix-up pass).
