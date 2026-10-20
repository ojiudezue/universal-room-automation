# EC-BILL-CYCLE-DAY-WIRED-1 — Review A (correctness + edge cases + money math)

Branch `fix/ec-bill-cycle-day-wired` @ 00c394da5. Base verified: `git merge-base HEAD develop` = e0beb6f82; diff three-dot.

## Consumer re-enumeration (grep `_get_cycle_start|cycle_start|bill_cycle_day|get_energy_daily_for_cycle`)
Every cycle-boundary consumer reads the CostTracker, so all follow the configured day:
- energy.py:1569 startup DB restore — `_billing._get_cycle_start`
- energy.py:3266 outage-days refresh — `_billing._get_cycle_start`
- energy.py:4102 arbitrage cycle savings — `billing.cycle_start_date`
- energy.py:11791 utility-stats divergence windows — `_billing._get_cycle_start`
- energy.py:11984 utility reset compare — `cycle_start_date`
- energy.py:12036 `get_billing_cycle_start` -> hvac_override.py:2107 (AC-ramp kWh avoided)
- sensor.py:11133/11176 cycle attrs + cycle length
- energy_billing.py:666 prediction, :835 / :1020 PeakAvoidanceTracker (own day, now wired at energy.py:709)
No hand-rolled second cycle-day source found. PASS.

## Findings
- **None CRITICAL/HIGH/MEDIUM.**
- LOW (pre-existing, not introduced): days missing from `energy_daily` undercount the reseeded cycle (database.py:4949 SUM over present rows only). Same as startup restore (energy.py:1569). No action.
- LOW (documented): PeakAvoidanceTracker.set_bill_cycle_day (energy_billing.py:815) keeps running PA cycle totals across a re-key, so after a day change PA cycle $ may include days outside the new window until the next real boundary. Display-only (isolated from cost_this_cycle). Accept.
- LOW (pre-existing asymmetry, now in the fix's favour): startup `update_from_db` (energy_billing.py:571) sets cycle = DB days only and `restore_daily` (:640) does not fold today into cycle, so post-restart cycle omits pre-restart today. `reseed_cycle` (:560) adds today's accumulators — more correct than startup. Not a double count.

## Money-math checks
- Reseed = DB rows `date >= start AND date < today` (database.py:4958) + today's in-memory `_import/_export/_cost_today`. `energy_daily` is only written for yesterday at rollover (energy.py:3297 "Save yesterday's"), so today is never in the DB sum. No double count. PASS.
- Key names match DAO return (`import_kwh`, `export_kwh`, `net_cost`, `days`; database.py:4962-4968). PASS.
- Accumulation between setter and reseed: reseed reads `_*_today` after the await, overwriting cycle = DB + current today, so interim ticks are neither lost nor doubled. PASS.
- `_cycle_start_date` re-keyed in setter (energy_billing.py:557) so `_check_cycle_reset` (:522) does not zero the cycle. PASS. `_days_in_cycle` recomputed on next reset check. PASS.

## Truth table (today = Oct 20)
| old | new | new start | DB window | result |
|---|---|---|---|---|
| 23 | 23 | — | — | setter returns False, no reseed (no-op) PASS |
| 23 | 24 | Sep 24 | Sep24..Oct19 | + today PASS |
| 23 | 15 | Oct 15 | Oct15..Oct19 | + today PASS |
| 23 | 20 | Oct 20 | empty | cycle = today only, days=0 -> "Learning" PASS |
| 23 | 28, today Mar 5 | Feb 28 | Feb28..Mar4 | ≤28 always exists; ValueError fallback (:541) unreachable PASS |

## Coercion
`clamp_bill_cycle_day` (energy_const.py:282): 24.0 -> 24; "24" -> 24; None/"x" -> 23; 0 -> 1; 31 -> 28. Dispatch casts `int(...)` first (__init__.py:8159); NumberSelector min1/max28 step1 (config_flow.py:6513). Equal value not in `changed_keys` -> setter never called. PASS.

## Verdict: **SHIP**
