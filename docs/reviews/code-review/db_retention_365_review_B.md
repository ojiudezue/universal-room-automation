# DB-SIZE-GROWTH-1 (365-day room-history retention) — Review B

Framing B: migration correctness of the nightly-cleanup refactor + async/lifecycle.
Branch `feature/db-retention-365` @ c9564f286, base f86375283 (merge-base verified, three-dot diff).

## Migration trace (old `_cleanup_ops` / `_cleanup_ops_d` -> `nightly_cleanup_ops()`)

All 19 pre-existing ops are carried over with identical name, method and kwargs, in the same
order, on both paths: predictions(days=30), census(90), energy_history(180),
external_conditions(90), notifications(30), inbound(30), person_data(90),
room_energy_baselines(90), anomaly_log(90/365), egress_state(cutoff_days=7), the 3 optimizer
prunes, the 3 decision_log types (90), incremental_vacuum, memory_compactor,
memory_writer_health. One op was added: `room_history` (365), placed before incremental_vacuum.
The primary and deferred lists were already identical before this change, so sharing one list
does not change either path.

Runner (`nightly_maintenance.py:73-106`) is equivalent to both old loops: rotating start index on
the same `_nightly_start_idx` key, 300 s budget checked between ops only, `getattr`-missing ->
skip, `except Exception` -> WARNING + continue, 1.0 s sleep between ops, index advances by 1 per
night. The deferred path still passes `hass.data.get(DOMAIN, {})` (`__init__.py:2817`), the same
as before. The rotation modulus changes from 19 to 20; the index lives only in memory and resets
to 0 on restart, so this is harmless.

Timers are unchanged and outside the diff: primary `async_track_time_change(... 2:30)` stored in
`unsub_nightly_maintenance` (`__init__.py:2754-2757`), deferred `__init__.py:2829-2830`, same key,
same unload. The regime-detector background task still fires after the cleanup is awaited, so
the sequencing is the same.

## Findings

| Sev | Where | Finding |
|---|---|---|
| LOW | `database.py` cleanup_room_history | `timestamp < ?` cannot use the `(room_id, timestamp)` composite indexes (`database.py:845/861/878`), and room_transitions has no timestamp index (`:1007-1009`). While a backlog exists, a rowid-order scan with LIMIT finds the old rows early, so it is cheap. Once caught up, the final short batch per table is a full table scan held on the single writer, once a night per table at 02:30. Writes queue during that time but are not lost. Accept, or add a timestamp index if live timing shows writer stalls longer than a few seconds. Class: write-queue occupancy. |
| LOW | `nightly_maintenance.py:93` / `database.py` | The first-night backlog (up to 4 tables x 100 batches with 0.1 s yields) can take most of the 300 s budget. The budget check is between ops only, so ops after room_history in that night's rotation are deferred ("continuing tomorrow"). The same pre-existing behavior applies to energy_history. Self-limiting through the batch cap and rotation. |
| LOW | tests | Tests drive `run_nightly_cleanup` and `nightly_cleanup_ops` directly. No test shows that BOTH `__init__` closures call `run_nightly_cleanup` (`__init__.py:2740`, `:2817`). Removing either call would probably leave the suite green. Bug Class #62 wire-in anchor; Reviewer C to confirm. Mitigated because both call sites are single one-liners. |

## Cleared

- Event loop is never blocked: every DELETE is awaited through `_db()` (single serialized writer, WAL), with `asyncio.sleep(0.1)` between batches and 1.0 s between ops.
- A restart mid-prune is safe: each batch commits on its own and is idempotent (age predicate), and the remainder is picked up the next night. During shutdown, `DBShuttingDown` is caught per table, logged and the loop breaks. CancelledError (BaseException) propagates and is not swallowed.
- Kill switch: `retention_days<=0` sends no query.
- Error isolation per op is unchanged, and per-table isolation is added inside room_history.

Tests: 6 related files, 220 passed (PYTHONDONTWRITEBYTECODE=1).

## Verdict: SHIP

No CRITICAL, HIGH or MEDIUM findings. The LOWs are optional; the wire-in anchor test is recommended.
