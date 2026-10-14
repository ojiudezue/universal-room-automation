# UNLOAD-SYMMETRY-TASK-HYGIENE-1 — Review A (Data integrity + DB architecture preservation)

- Branch: `feature/unload-symmetry` @ c93265887
- Diff base: `66a8fb6a9` = `git merge-base feature/unload-symmetry develop` (verified; reviewed `develop...feature/unload-symmetry`, three-dot)
- Method: static only (no pytest, per orchestrator). HA core API checked against `.venv-ha` `homeassistant/core.py`.

## Verdict: SHIP (no CRITICAL/HIGH/MEDIUM; 3 LOW, all optional)

## D1: DBShuttingDown subclass

| Check | Result | Evidence |
|---|---|---|
| Existing `except RuntimeError` arms still catch it | PASS | `DBShuttingDown(RuntimeError)` at database.py:35. Repo-wide grep: the only `except RuntimeError` is `_loop_stall_watchdog.py:84`, which doesn't touch the DB. Every other DAO uses `except Exception`, which still catches the subclass. |
| Except-arm ordering | PASS | All 4 new arms (`coordinator_diagnostics.py:303, 1736, 1821, 1918`) come before `except Exception`. |
| Real error demoted to DEBUG | PASS | The lost-connection path `database.py:385-389` still logs ERROR "connection lost". It calls `_drain_pending_futures(str(exc))` with `is_shutdown=False`, so the drained futures raise plain `RuntimeError` and the DAOs log ERROR. The 300s hard-cap raise (`:647`) stays `RuntimeError`. Only two raise sites became `DBShuttingDown`: the stop-time fast-fail (`:541`, worker done AND `is_stopping is True`) and the shutdown-timeout drain (`:449`). |
| Write silently dropped that previously succeeded | PASS | No new raise site. The fast-fail condition at `:537-540` is unchanged; only its exception class changed. The flush budget and drain are unchanged; only the log level changed. |
| DAOs outside diagnostics | as-expected | They still log ERROR on `DBShuttingDown` through `except Exception`. Behavior is unchanged, and so is the noise. |

## D3: 7 SELECTs moved to `_db_read()` + load_baselines split

- **Semantics:** `_db_read` (`database.py:685-696`) opens a fresh connection with `query_only=ON`. All 7 moved bodies are pure SELECTs (get_decisions, decision count, 3× compliance, anomaly count, load_baselines SELECT). None of them writes, so `query_only` cannot reject anything.
- **WAL visibility:** a new read connection sees everything committed before its read transaction starts. Every producer (log_decision, store_outcome, save_baselines) runs `await db.commit()` inside the `_db()` yield before the context exits, so a row is committed before the producer gets control back. A read issued after a write call returns sees that row. Nothing depended on seeing uncommitted rows from the writer connection. Row shape is unchanged: the same SQL and the same `row_factory`, with `aiosqlite.Row` kept where it was set before.
- **load_baselines split (SELECT on the read connection, DELETE on `_db()`):** no race and no lost prune. The DELETE targets only `metric_name IN orphans`, and orphans are by definition not in `valid_metrics`. `save_baselines` writes only `self._baselines` keys, which exclude orphans, so no concurrent writer can recreate an orphan row between the SELECT and the DELETE. A prune skipped with `DBShuttingDown` is retried on the next boot because the SELECT finds the orphans again.
- **Boot timing:** before this change the SELECT queued behind the writer. Now it runs immediately. Tables are created in DB init before the handle is published to `hass.data`, so there is no cold-table window.

## D2: shutdown job

- `async_add_shutdown_job(HassJob)` returns a remove callable (core.py:1020-1039). The unsub is stored and called on teardown (manager.py:849-854), so a reload does not leave a stale job behind.
- Effect on rows: the stop-time save now actually lands because it runs in Stage 1 while the worker is still alive. This is the intended fix. It writes the same `INSERT OR REPLACE` metric_baselines rows, plus safety_rate, which were silently lost before. Each save is batched per coordinator into one `_db()` transaction, so there is no per-row pressure on the queue. The writes are idempotent if they overlap the periodic save.

## Findings

| # | Sev | file:line | Scenario | Bug class |
|---|---|---|---|---|
| A-L1 | LOW | database.py:366 | The worker gets cancelled mid-write at shutdown. The waiting future still gets a plain `RuntimeError`, not `DBShuttingDown`, so that DAO still logs ERROR at stop. The D1 noise cleanup misses this one path. No data impact. | Observation/log-level gating (incomplete) |
| A-L2 | LOW | coordinator_diagnostics.py:1724-1736, 1749 | The orphan prune raises a non-shutdown error (for example the hard-cap `RuntimeError`). The outer `except` sets `_baselines_loaded=False` even though the SELECT and in-memory load succeeded, which disables saves until the save-path retry. This is pre-existing (the DELETE was always in the same try), but the split makes it cheap to decouple by catching `Exception` around the prune. | Pre-existing coupling |
| A-L3 | LOW | manager.py:72 (30→15s) + database.py:676-683 | The 15s `asyncio.timeout` cancels a save inside the `_db()` yield after some INSERTs but before commit. The worker connection is left holding an open implicit transaction, and the next writer's commit lands those rows. This was pre-existing at 30s and the lower cap makes it slightly more likely. The rows are idempotent upserts of valid values, so there is no corruption. | Pre-existing (partial-txn carryover) |

## Invariant checklist
- No real failure demoted below ERROR: PASS
- No previously-succeeding write now dropped: PASS
- Reads return the same shape / visibility: PASS
- Single serialized writer + WAL architecture unchanged (writes still only via `_db()`): PASS
- Stop-time baseline rows now persisted: PASS (by construction; needs live confirmation)

## Bug-class frequency
Log-level gating ×1, pre-existing coupling ×2. No new QUALITY_CONTEXT class recommended.
