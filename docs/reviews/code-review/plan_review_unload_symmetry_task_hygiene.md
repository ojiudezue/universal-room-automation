# Plan review: UNLOAD-SYMMETRY-TASK-HYGIENE-1 (Tier 2-DB, one adversarial plan review)

Plan: `docs/planning/PLANNING_unload_symmetry_task_hygiene.md`. Reviewed on develop @ d9513e305, 2026-10-13. Read-only; no pytest run.

**Verdict: FIX-PLAN-REQUIRED.** The design is sound. D2 is more important than the plan says. The defects are in the D2 handler contract, the D2 and D3 Live oracles, and the enumeration in §8.

## HA shutdown ordering (checked against `.venv-ha/.../homeassistant/core.py`)

- `async_add_shutdown_job` (core.py:1020-1039) appends the job to `_shutdown_jobs`. Its `remove_job` calls `list.remove`, so it raises ValueError on a second call.
- `async_stop` Stage 1 (core.py:1077-1091) runs and gathers the shutdown jobs under `STOPPING_STAGE_SHUTDOWN_TIMEOUT`. At this point the state is still `running`, so `is_stopping` is False.
- Stage 2 (core.py:1093-1112) cancels **every background task** and then sets `stopping` and fires `EVENT_HOMEASSISTANT_STOP`. Final write is at core.py:1123-1124 and close at core.py:1136-1137.
- The URA write worker is a background task (`database.py:283` `async_create_background_task`).

So today's STOP listener (`manager.py:554-559`) always runs **after** the worker has been cancelled. Depending on whether `_flush_pending_writes` has finished, it either hits the v5.103.49 fast-fail (`database.py:495-502`) or races the flush. The stop-time save is lost every time, not just sometimes. A shutdown job runs in Stage 1, while the worker is alive and before the fast-fail gate can fire. URA's own `async_close` (`__init__.py:5609-5610`, entry unload) comes later. **The ordering is correct; there is no CRITICAL race.** The plan's wording ("can race") understates the problem but reaches the right conclusion.

## Findings

| # | Sev | Where | Finding |
|---|---|---|---|
| P1 | HIGH | `manager.py:647-649` | `_async_persist_coordinator_baselines_on_stop(self, _event)` needs a positional event argument. `async_add_shutdown_job(HassJob(fn))` calls it with **no args** (core.py:1079, `job.args` = ()), so it raises TypeError. `return_exceptions=True` at core.py:1084 swallows that, so the save silently never runs. That is Bug Class #53 at the very site D2 fixes. The plan must specify `_event: Any = None` or a zero-arg wrapper, and the D2 test must invoke the job the way core does (`hass.async_run_hass_job(job.job, *job.args)`), not by calling the method with an event. |
| P2 | HIGH | plan invariant + D2 Live | (a) `metric_baselines` has no `updated_at` column. The column is `last_updated` (`database.py:1269-1278`). (b) The save now runs in Stage 1, **before** STOP, so it is not "±2 s of FINAL_WRITE". Stage 2 can take up to `STOP_STAGE_SHUTDOWN_TIMEOUT`, which puts the correct save far from FINAL_WRITE and fails the criterion as written. Restate as: `max(last_updated)` is later than the last periodic tick and no later than the "Stopping"/STOP log line. Also include `safety_rate` scope rows (only the STOP path writes them, `include_safety_rate=True`) as the discriminator. |
| P3 | MEDIUM | §8 / D3, `coordinator_diagnostics.py:1636,1670,1776,1872` | The enumeration of `database._db()` sites in this file is incomplete. There are 10 sites, not 6. Two more are reads: `:1636` is a SELECT COUNT on anomaly_log and `:1670` is the baseline load SELECT, both D3 candidates or explicitly excluded with a reason. Two are writes: `:1776` (`save_baselines`, the exact write D2 protects, so its except arm is in D1 scope) and `:1872` (outcome_log INSERT). The "1 `_db()` + 5 `_db_read()`" Verify criterion is therefore wrong. |
| P4 | MEDIUM | D1 scope, `database.py` | The plan treats the 133 `except Exception` arms in `database.py` as mostly migration arms and places "DAO callers" in other files. But `database.py` itself has **98** `async with self._db() as db` DAO methods (e.g. census at `:4060-4080`), and those are the main shutdown-noise sites. Other files with `_db()` callers: websocket_api, sensor, memory_facade, memory_compactor, optimization(_llm), hvac, energy, notification_manager, button, coordinator_diagnostics. `census.py`, `anomaly_log.py` and `safety.py` as named do not hold `_db()` callers (census.py and anomaly_log.py do not exist). The site-set rule ("try wraps `_db(`") is right, but the file list misleads the builder. Fix the hint. |
| P5 | MEDIUM | `database.py:427-441` | Futures drained via `_drain_pending_futures("shutdown timeout")` get a **bare** `RuntimeError("DB write failed: shutdown timeout")`. Callers awaiting those futures will still log ERROR under D1, so the invariant fails. The plan only demotes the *warning*. It must also raise `DBShuttingDown` for drained futures on the shutdown path (flush/cancel). The connection-lost path (`:377`, reason=str(exc)) must stay a generic RuntimeError so it still logs ERROR. State that split explicitly and test both. |
| P6 | MEDIUM | D3 Live | `_db_stats["reads"]` is not exposed. `sensor.py:16115-16117` publishes only `db_writes_total` and `db_queue_peak`. And "writes not incremented" does not discriminate: background writers increment `writes` constantly. Use an in-suite oracle (spy on `_db_read` vs the worker's `writes` counter in isolation), or expose `db_reads_total`. Do not cite `sensor.ura_db_stats "or equivalent"`. |
| P7 | LOW | D2 teardown, `manager.py:831-836` | `remove_job` raises ValueError when called twice. The existing try/except plus `= None` handles that. Keep that shape; the plan should say so. Also, Stage 1 runs before entry unload, so `_running` is still True and the `manager.py` `_running` guard will not skip the save. That is correct, but note it so a builder does not "fix" it. |
| P8 | LOW | §1 table | `ANOMALY_BASELINE_STOP_SAVE_TIMEOUT_S` (`manager.py:659`) now sits inside the Stage 1 `STOPPING_STAGE_SHUTDOWN_TIMEOUT`. Confirm it is shorter than that timeout. Otherwise there are no new numbers, and the ladder claim holds. |

## Checks that passed

- **RuntimeError subclass safety:** the only `except RuntimeError` / `except (…, RuntimeError)` catches are `hvac.py:6235` (dict mutation during zone prune), `presence.py:7902` (loop assertion) and `_loop_stall_watchdog.py:84` (`call_soon_threadsafe` on a closed loop). None of them sits around a `_db()` call, so behavior does not change.
- **Over-swallow discriminator:** D1 routes by **type** (`except DBShuttingDown` ahead of `except Exception`), not by downgrading every RuntimeError, and it includes `test_db_other_errors_still_log_error`. Adequate, given the P5 split.
- **Cited code:** `database.py:497-502` (gate + bare RuntimeError), `:644-654` (`_db_read`, `query_only=ON`, increments `reads`), and `manager.py:554-559` (`async_listen_once(STOP)`) all exist as described.
- **Falsifiable invariant:** falsifiable once P2's column and timing are corrected.
- **Non-goals:** explicit. **Numbers:** none. **Parsimony:** honest.

## Must-fix in plan before build dispatch
P1, P2, P3, P4, P5, P6. P7 and P8 are one-line notes.
