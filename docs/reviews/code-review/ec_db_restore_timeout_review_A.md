# EC-DB-RESTORE-TIMEOUT-1 — Review A (local correctness + edge cases)

Branch `fix/ec-db-restore-timeout` (466ab5dd7, 34bdcd82e). Base 107f1400e verified = `git merge-base HEAD develop`.
Targeted suite: `test_ec_restore_per_step_timeout.py` 36 passed.

## Findings

**MEDIUM — partial-cancel of `midnight_snapshot` breaks the "skipped ⇒ rollover reseeds" premise** (Bug class: #53-adjacent / suppression-without-discharge)
`energy.py:2879` sets the six lifetime snapshots and `_last_reset_date = today` BEFORE two further awaits: the provenance read
(`db.restore_energy_state(...PRODUCTION_SNAPSHOT_ENTITY)`, ~2895) and the peak-avoidance read (~2932); `restore_daily` sits between them (2913).
If `wait_for` cancels at the provenance await (both attempts, e.g. sustained write contention), the result is:
snapshots + `_last_reset_date=today` set, provenance poisoning skipped (possible cross-entity solar delta, the EC-SOLAR-LIFETIME-COUNTER-FLAP-1 bug),
`restore_daily` NOT applied (today's import/cost = 0), and the step is recorded skipped. Because `_last_reset_date == today`, the
day-rollover branch (3415) does NOT run, contradicting the comment at `energy.py:1687` ("when it is skipped, _last_reset_date is \"\"").
The retry is idempotent when it completes (re-assigns same values; `restore_daily` overwrites; only side effect is a second
outage-days background task, benign). Pre-existing under the old 15 s wrapper, but this cycle claims the boot-only reasoning.
Fix: on final timeout of `midnight_snapshot`, reset `_last_reset_date = ""` (and the six snapshots to None, `_production_snapshot_poisoned` False) so the rollover path reseeds; or move `_last_reset_date = today` to after `restore_daily`. Add a test that cancels at the provenance await.

**LOW — cancel during `aiosqlite.connect` (timeout 30 s, `database.py:734`) under a 10 s `wait_for`** may leave the aiosqlite worker thread to finish opening and not close the connection. Not verified against the installed aiosqlite version; pre-existing with the old 15 s wrapper. Note only.

## Cleared
- `cycle` step: single await then sync `update_from_db` — atomic w.r.t. cancellation. Late retry via `reseed_cycle` = DB full days + today's accumulators, and re-keys `_cycle_start_date` (`energy.py` `_reseed_cycle_after_boot`), so `_check_cycle_reset` (`energy_billing.py:533`) won't zero it. Holds.
- Budget arithmetic: per step `min(10, 45 - elapsed)`; `remaining <= 0` ⇒ skip; immediate retry clipped to the remaining budget recomputed after the timeout. Worst case ≈ 45 s plus scheduling jitter. Holds.
- Exception propagation: steps catch their own exceptions; non-timeout exceptions/CancelledError still propagate out of setup exactly as the old `wait_for` did. Only `TimeoutError` is absorbed. Unchanged.
- Entry reset of `_restore_skipped` at top of pass; retry pops the list before awaiting. Holds.
- peak_import / bill_forecast_ledger late guards correct for "accrued since boot" / "already loaded".

## Verdict
**SHIP with MEDIUM fix recommended** (FIX-REQUIRED if the orchestrator treats MEDIUM in billing as must-fix): reset `_last_reset_date` on final midnight_snapshot timeout + test.
