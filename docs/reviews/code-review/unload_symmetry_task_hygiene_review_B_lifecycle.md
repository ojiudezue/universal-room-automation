# UNLOAD-SYMMETRY-TASK-HYGIENE-1 — Review B (async / lifecycle / shutdown ordering / races)

Branch `feature/unload-symmetry` @ c93265887. Diff base 66a8fb6a9 (merge-base verified), three-dot.
Static review only (no pytest). HA core cited from `.venv-ha/lib/python3.13/site-packages/homeassistant/core.py`.
Not HVAC/presence scope; state-of-play docs not applicable.

## HA core ground truth (`async_stop`, core.py:1051-1130)
- **Stage 1** (1074-1090): iterates `self._shutdown_jobs`, `async_run_hass_job(job.job, *job.args)`, gathers with
  `return_exceptions=True` under `STOPPING_STAGE_SHUTDOWN_TIMEOUT = 20` (112). **State is NOT changed yet** —
  `hass.is_stopping` (448-450: `stopping`/`final_write`) is **False** throughout Stage 1.
- **Stage 2** (1092-1121): background tasks cancelled (1103-1106) — includes `ura_db_write_worker`
  (database.py:295 `async_create_background_task`) — then `set_state(stopping)` (1111), then `EVENT_HOMEASSISTANT_STOP` (1112).
- `async_add_shutdown_job` (1019-1039): append `HassJobWithArgs(hassjob, args)`; remove = `list.remove` (raises
  `ValueError` on double remove; the job is never cleared from the list after running).

## D2 — shutdown job
| Question | Verdict | Evidence |
|---|---|---|
| DB worker alive when job runs? | HOLDS | Job runs in Stage 1; worker cancel is Stage 2 (core.py:1103). Writes route through live worker, `_db()` fast-fail gate (database.py:537-540) cannot trip (worker alive AND is_stopping False). |
| Zero-arg signature | HOLDS | `HassJob(..., )` registered with no args (manager.py:565-570); core calls `job.job(*())`. Method is `(self)` only (manager.py:660). |
| Registered after shutdown began | HOLDS (benign) | Append after Stage-1 iteration simply never runs; iteration is synchronous (no await inside the `for`), so no list-mutation-during-iteration. |
| Double registration (reload then stop) | HOLDS | `async_stop` removes + nulls (manager.py:849-854); new CM instance re-wires guarded by `is None` (561). Remove wrapped in `try/except` so a double remove's `ValueError` is swallowed. |
| Remove on every unload path | HOLDS for unload/reload (`__init__.py:5564` → `async_stop`). Setup-failure path: see B-LOW-2 (pre-existing). |
| 15 s vs 20 s Stage-1 | HOLDS | `asyncio.timeout(15)` (manager.py:677) fires first; CancelledError is converted to TimeoutError by the CM and caught (679-686) — job returns normally, no task leak. The parked `_db()` caller sets `done` on cancel (database.py:595-600 `_wait_ready_stage` BaseException arm / yield-finally), so the worker is not wedged. |
| Partial transaction on timeout | LOW/INFO | Cancel between a detector's statements and its `commit` leaves uncommitted statements on the worker connection; the next queued factory's commit could commit them. Content is idempotent baseline upserts → at worst a mix of fresh/old baselines. Pre-existing `_db()` property, not new. |

## D1 — is_stopping-gated demotion
- Stage 2 ordering: worker `cancel()` (1105) and `set_state(stopping)` (1111) happen in the same synchronous step;
  the CancelledError is delivered to the worker afterwards, so `_flush_pending_writes` sees `is_stopping is True` → DEBUG. HOLDS.
- Normal runtime errors (connection lost) use `_drain_pending_futures(str(exc))` with `is_shutdown=False` → plain
  `RuntimeError` → DAO ERROR. HOLDS (database.py:375-379).

## Findings

**B-LOW-1 — runtime worker stops mislabeled as shutdown (Observation-mode-ish diagnostic demotion).**
`database.py:449` passes `is_shutdown=True` unconditionally from `_flush_pending_writes`, and the comment at
database.py:412-415 claims HA shutdown is "the only legitimate caller". False: `_flush_pending_writes` runs on ANY
worker cancel — `stop_write_worker()` (database.py:300-321; VACUUM path database.py:9609, SPAN re-migration) and
`async_close()` on config-entry unload/reload (`__init__.py:5609-5610`). Scenario: parent entry reload while >5 s of
writes are queued → budget WARNING still logs (is_stopping False), but drained futures raise `DBShuttingDown` and
every producer's except arm (coordinator_diagnostics.py:303, 1821, 1918) logs at DEBUG, and the drained-count line
(database.py:477) is DEBUG. Real row loss during runtime is reduced to one generic WARNING. Fix (≈2 LoC):
`self._drain_pending_futures("shutdown timeout", is_shutdown=getattr(self.hass, "is_stopping", False) is True)` and
correct the comment. Fix in-cycle per fix-LOWs policy.

**B-LOW-2 — pre-existing: setup-failure leaves the shutdown job registered.** `_wire_anomaly_baseline_persistence`
runs inside `async_start` (manager.py:535); if a later step of `async_start` / parent setup raises, nothing calls
`async_stop`, so the job (and the periodic timer) stay registered on a dead CM; at HA stop it runs a save against it.
Same leak existed with the prior `async_listen_once`; bounded by the 15 s timeout and per-detector try. Not
introduced by this diff — card, don't block.

**B-LOW-3 — D1 completeness gap (pre-existing).** Worker mid-write cancel (database.py:362-372) still sets plain
`RuntimeError("...Home Assistant is stopping")` → that one in-flight caller logs ERROR at Stage 2. Could be
`DBShuttingDown`. Cosmetic.

**Cleared:** no new background task, timer, or listener introduced (D3 `_db_read` is a transient connection with
`query_only=ON`, database.py:686-696; orphan-prune split keeps the write on `_db()`). Periodic-timer path unchanged.
`EVENT_HOMEASSISTANT_STOP` import in manager.py still used by the house-state hook.

## Summary
| Sev | Found | Must-fix |
|---|---|---|
| CRITICAL | 0 | 0 |
| HIGH | 0 | 0 |
| MEDIUM | 0 | 0 |
| LOW | 3 | 0 (B-LOW-1 recommended in-cycle) |

Bug classes: diagnostic demotion / mislabelled shutdown (B-LOW-1), setup/unload asymmetry (B-LOW-2), incomplete log-routing (B-LOW-3).

**Verdict: SHIP** (fix B-LOW-1 in the fix-up pass if one runs).
