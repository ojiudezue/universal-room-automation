# DB-SIZE-GROWTH-1 (365-day room-history retention) - Review C (test authority, real per-site mutation)

Branch feature/db-retention-365 @ c9564f286. Diff base: HEAD~1 (master...HEAD is not the cycle diff).
Method: one production-source edit per run, pycache cleared, PYTHONDONTWRITEBYTECODE=1, restore in try/finally,
`git status` clean after the run. Targets: new retention tests + the five touched test files. Drill-marked
in-suite tests were NOT enabled (an earlier run with `-m ""` left database.py mutated: the in-suite subprocess
drills rewrite source files; do not combine them with an external mutation harness).

## Mutation table

| Site | Mutation | Result (first failing test) |
|---|---|---|
| __init__ primary nightly closure | `await run_nightly_cleanup(...)` -> `pass` | RED (new) test_nightly_closure_runs_shared_cleanup_with_db[primary]; GREEN before this review |
| __init__ deferred nightly closure | same -> `pass` | RED (new) ...[deferred]; GREEN before |
| __init__ primary registration | minute 30 -> 31 | RED (new) test_nightly_closure_registered_at_0230 |
| __init__ deferred registration | minute 30 -> 31 | RED (new) test_nightly_closure_registered_at_0230 |
| DAO UTC-table clock | utc date -> local date | RED test_room_history_prune_keeps_rows_younger_than_cutoff_both_formats |
| DAO room_transitions clock | local -> utc | RED same test |
| DAO cutoff | retention_days-1 | RED same test |
| DAO off switch | `retention_days <= 0` guard removed | RED test_room_history_prune_zero_disables[0] |
| DAO batch cap | `<` -> `<=` | RED test_room_history_prune_batch_cap |
| DAO default cap | const -> literal 5 | RED test_room_history_prune_default_cap_is_module_constant |
| DAO batch_size | LIMIT 1 | RED test_room_history_prune_batch_cap |
| DAO table env / energy / occupancy / transitions (4 runs) | row removed from tuple | all RED (cutoff test; per-table parametrized test also covers) |
| DAO short-batch exit | removed | GREEN before; RED (new) test_prune_yields_between_full_batches_and_stops_on_short_batch |
| DAO 0.1 s yield | removed | GREEN before; RED (new) same test |
| DAO `timestamp <` -> `<=` | | GREEN, EQUIVALENT mutant (date-only cutoff vs 'T'/space strings never compares equal) |
| const RETENTION 365->30 / MAX_BATCHES 100->50 | | RED test_nightly_ops_include... / test_retention_constant_values |
| runner op removed / kwargs retention->0 | | RED test_nightly_ops_include_room_history_primary_and_deferred |
| runner rotation index / budget break / exception swallow / budget 300 | | all RED (named runner tests) |
| runner 1.0 s inter-op gap | removed | GREEN before; RED (new) test_run_nightly_cleanup_sleeps_op_gap_between_ops |

## Findings

- MEDIUM (fixed here, Bug Class #62 / untested site): both __init__ call sites of `run_nightly_cleanup` were
  untested (builder's two surviving mutants confirmed). Added `quality/tests/test_db_retention_nightly_callsites.py`:
  AST-slices the real closures out of `async_setup_entry`, execs them against a spy, calls them, asserts the
  shared runner is awaited once with (domain dict, db), is a no-op without a DB, and that each closure is handed to
  the time-change registrar at 02:30:00 (AST of the registration call, plus behaviour of the closure itself).
- LOW (fixed here): short-batch exit, inter-batch yield and inter-op gap had no test; added.
- Note: `test_nightly_ops_include_room_history_primary_and_deferred` name is a misnomer (it checks the shared list;
  the per-path guarantee now comes from the new call-site tests).
- Residual: the equivalent `<`/`<=` mutant is not killable; accepted.

Verdict (Review C): SHIP once the new test file is included. 23 related tests pass; tree clean after every mutation.
