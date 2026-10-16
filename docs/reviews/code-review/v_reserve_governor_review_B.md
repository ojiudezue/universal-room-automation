# EC-RESERVE-WRITE-GOVERNOR-1 — Review B (integration / async / lifecycle / state-machine)

Base verified: `53b3ecb8f` (plan rev3.2 commit) .. `1c5d9bc97`. Diff touches energy.py, energy_battery.py, energy_const.py + tests. Targeted suite: 63 passed (rows, A/B golden, lint).

## Verified (holds because)

| Area | Evidence |
|---|---|
| Timer `pre_state` read vs awaits | energy.py:7432-7439: sync `hass.states.get` read immediately before `await _execute_service_action`; no await between read and dispatch, so no other task can interleave. Threaded as a local into the tap kwarg (energy.py:7448). Capture-before-await rule satisfied. |
| Byte-identical dispatch | Added reads are pure: `_get_state_float` (energy_battery.py:881), `_resolve_hold_owner` + `_dp_transition_floor`/`_evse_hold_state` (energy_write_verify.py:1738+) mutate nothing. The only write is `_last_reserve_row_key` (RAM memo, never read by dispatch). Tap's ledger stamp, `_note_battery_dispatch_outcome`, and its existing filter are unchanged and run in the same order. Golden A/B test passes. |
| Write-verify ordering | C1 row is emitted synchronously inside the tap after the `_last_reserve_level` stamp and before `_note_battery_dispatch_outcome` (energy.py:9298-9313); no new await, so stale-stamp / self-heal / `_pending_fire_retry` sequencing is untouched. |
| force_redispatch (C3) | Rows sit in their own try after the failure record (FAILED) and after step-5 ledger stamp (APPLIED), getattr-only reach (energy_battery.py:6844-6898); cannot re-enter the service-call except or skip the stamp. |
| DB path — SETTLED | `log_activity` (database.py:6233) does `async with self._db()`; `_db` (database.py:523) is the write-queue submitter, `await self._write_queue.put(...)` (database.py:642). Rows go through the single serialized writer. The ground-truth audit's "direct insert" reading is wrong; Review A is correct. Each row is its own queue item (not batched), but volume is bounded by the change gate (only state-changing dispatches + redispatch) — no boot burst: first post-boot write produces exactly one row. Shutdown: `_db` raises `DBShuttingDown` when stopping, swallowed by log_activity's `except Exception`. |
| Event loop | No executor needed: small dict + `json.dumps`, cached local imports. Task exceptions impossible to escape (log_activity swallows). |
| Restart / reload | Memo is an instance attr initialised in `__init__` (energy.py:329); reload builds a new coordinator → fresh memo → first write logs (intended). Nothing restored, nothing persisted. |
| Observation mode | Timer actuation gated at energy.py:6591 → no C1 rows while observing. `_evaluate_battery` has no gate (pre-existing bypass, already carded from the audit) → C2 DEFERRED row is written because the CM really does execute; truthful to current behaviour. |
| CM path / twice-per-tick | C2 fires only from `evaluate()` on TOU transition (energy.py:1378-1385). CM execution (manager.py:1035-1065) is untouched; DEFERRED is the honest status since the outcome is unseen. |

## Findings

| SEV | Location | Class | Finding |
|---|---|---|---|
| LOW | energy.py:7225-7238 + memo energy.py:9165-9177 | observational noise | Single-slot memo keyed on `path`: on a TOU transition the timer and evaluate paths alternate keys, so the gate cannot suppress the second of the pair. If the timer wrote first, C2 records a DEFERRED row with `pre_state == value` for a CM write that is a hardware no-op, and the next timer re-send logs once more. At most ~2 extra rows per transition (~4-6/day). No dispatch impact. Optional fix: gate on `(value, hold_owner)` with pre_state equality regardless of path, or accept. |
| LOW | energy.py:9246-9247 | silent coverage gap | If `WriteVerifier` construction failed (energy.py:330-), the tap returns before the C1 hook, so timer-path reserve writes produce no rows. C2/C3 still log. Verifier failure is already a degraded state; acceptable, worth one line in the plan's known limits. |
| LOW | energy.py:9224 `hass.async_create_task` | untracked background task (pre-existing pattern) | Task is hass-scoped, not entry-scoped. During a parent reload with the write worker stopped (not HA stopping), the row parks on the queue up to the hard cap and outlives the entry. Same contract as `hvac_setpoint._schedule_climate_write_row`; bounded, lossless, harmless. No change required. |

No CRITICAL / HIGH / MEDIUM.

## Verdict: **SHIP**

Must-fix: none. LOW-1 is optional; LOW-2 should go into the plan's known limits.
