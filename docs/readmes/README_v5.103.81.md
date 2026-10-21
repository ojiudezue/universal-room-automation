# v5.103.81: energy state is saved at shutdown, and nothing actuates after it

Card: EC-SHUTDOWN-SAVE-AFTER-WRITER-CLOSED-1. Tier 2, reviews A (correctness) SHIP, B (lifecycle/actuation) SHIP, plus a focused review of the fix-up SHIP. Deploy risk: LOW-MED (shutdown path only; one new stop flag on the decision cycle).

## Problem

- HA never unloads integrations on stop (`config_entries.py:2176`), so the Energy Coordinator's teardown persist never ran on a restart. EC state was only saved by the 15-minute periodic writer, so up to 15 minutes was lost per restart, including EVSE pause owner sets (a fresh pause could boot as a physically-off EVSE with no owner).
- EC timers (decision interval, TOU boundary, solar-follow, drain must-start-by) are not `cancel_on_shutdown`, so they kept firing for up to ~160 s after URA's DB writer was cancelled: they could actuate during shutdown, and their saves failed (26-34 ERROR lines per restart).

## Fix

- EC registers a Stage-1 shutdown job (`hass.async_add_shutdown_job`, same pattern as the anomaly baselines in `manager.py`), which runs while the DB writer is alive:
  1. cancels every EC actuation timer (`_cancel_actuation_timers`, shared with teardown) and sets `_ec_stopping` (decision cycle, TOU re-arm and DP must-start-by return early; solar-follow tick stops);
  2. waits up to `EC_STOP_CYCLE_WAIT_S` (3 s) for an in-flight decision cycle;
  3. persists state under `EC_STOP_SAVE_TIMEOUT_S` (10 s): EVSE state first, then peak history, circuit, baselines, envoy cache, midnight snapshot, load-shed level, power profiles.
- Idempotent: teardown on a reload saves only if the job didn't run.
- Six EC save functions log `DBShuttingDown` at DEBUG instead of ERROR; other errors still ERROR.
- Stop guards require a real `True` (mock-safe).
- Deliberately unchanged: the safety-hazard emergency load-shed listener stays live during shutdown.

## Tests

- `test_ec_shutdown_save_stage1.py`: 28 tests; 30 mutation drills RED (real DB rows written by the job; no service calls from any EC callback fired after the stop job; EVSE saved first when the timeout cuts the sequence; bounded waits).
- Full-suite name-diff vs develop 406c03485 with URA_SOURCE_MUTATION=1: CLEAN, 11 = 11, 0 new / 0 gone (after fixing a mock-truthiness regression in the first fix-up).

## Validated 2026-10-21

| Criterion | Result | Evidence |
|---|---|---|
| Load (restart 14:13 CDT) | PASS | 50/50 URA entries loaded, 0 URA ERRORs after boot |
| Stop job saves while the writer is alive (restart 15:45 CDT, first stop running the new job) | PASS | URA DB `energy_state` rows (peak_avoidance_snapshot, drain_precedence_state_v1, ev_force_charge_until, wv_* ...) all stamped 20:45:47 UTC = the stop instant |
| No shutdown save errors | PASS | 0 `write worker is closed` lines in the HA container log over the restart (previous restarts: 26 and 34) |
