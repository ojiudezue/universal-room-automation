# v5.103.102: Envoy status no longer stuck on "stale"

## What changed
The Envoy firmware reports its lifetime consumption counter on the "consumption today" sensor
(34,412 kWh "today" against a 34.41 MWh lifetime). The hourly consumption cross-check compared
that against URA's own daily total, saw a 99.7% gap every hour, and kept
`sensor.ura_energy_coordinator_envoy_status` on "stale" even though every Envoy reading was fresh.

The cross-check now treats a "today" reading at or above half the lifetime counter as unusable
input: it skips the comparison, clears the flag and logs at debug level. A genuine divergence
(e.g. 40 kWh vs 110 kWh) still flags as before. Constant: `ENVOY_TODAY_LIFETIME_RATIO_MAX = 0.5`
(module constant, a protocol bound, not a policy knob).

Card: ENVOY-FLAKINESS-181243-1 (residual: corrupt consumption_today cross-check).
Review: Tier 1, SHIP (`docs/reviews/code-review/envoy_crosscheck_corrupt_today_review.md`).
Tests: `quality/tests/test_envoy_crosscheck_corrupt_today.py` (mutation-verified: removing the
guard turns one test red).

Operator action done alongside: the corrupted long-term statistic for
`sensor.ura_hvac_coordinator_ac_kwh_avoided_total` (sum ~217,000 kWh from pre-v5.103.101 restart
resets) was cleared via `recorder/clear_statistics`; it rebuilds from the next hour.

## Live validation (prospective)
- `sensor.ura_energy_coordinator_envoy_status` reads online after restart and stays online past
  the next hourly cross-check.
- No new "Consumption cross-check divergence" WARNING in the system log after restart.
