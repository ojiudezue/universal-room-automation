# v4.5.2 — Test baseline cleanup (tech debt #0 → DONE)

**Date:** 2026-05-07
**Type:** Tier 2 cycle (test infrastructure + minimal production change)
**Predecessor:** v4.5.0.4 (v4.5.1 skipped — see PLANNING_v4.5.2 for rationale)
**Tech debt closed:** #0 from `docs/QUALITY_CONTEXT.md` / `docs/ROADMAP_v11.md`

## Summary

Drives the URA quality test suite from a calibrated baseline of **70+ failures / 14 errors** (per-file isolated, post-pytest-asyncio pin) to **0 failures / 0 errors** across all 50 test files. Adds a CI-style guard at `scripts/test_isolation_check.py` so the baseline is enforced going forward. **Production behavior is unchanged.** The only production-code change is adding `from __future__ import annotations` to 11 modules, a string-deferral toggle for type hints with zero runtime effect on Python 3.10+ (HA's runtime).

This was tech debt #0 — the longest-standing item on the architectural debt list (open since at least Mar 2026). Both v4.2.22's storm bug and v4.2.24's silent-save bug lived in code paths the existing tests didn't model, because nobody could distinguish a NEW regression from the noise of pre-existing fails. v4.5.0 calibrated the actual count by pinning `pytest-asyncio` (which had been masking ~180 fails as collection errors). v4.5.2 finishes the job.

## What was broken

| Class | Symptom | Root cause |
|---|---|---|
| Python 3.9 collection | 4 files refused to collect with `TypeError: unsupported operand type(s) for \|: 'type' and 'NoneType'` | PEP 604 unions (`X \| None`) parsed at module load on Python 3.9 dev env. Production runs Python 3.13/3.14 where this is a non-issue. |
| DB harness silent no-op | ~30 DB tests "passed" against an empty schema | `conftest.py` had `sys.modules.setdefault("aiosqlite", MagicMock())` — every `await db.execute(...)` returned a MagicMock instead of running. `db.initialize()` looked successful but no tables got written. |
| DB write worker not running | DB write-path tests failed with "DB write worker not running" | `hass.async_create_background_task` was a MagicMock; the worker coroutine got captured but never scheduled. |
| Cross-call event loop | Each `_run()` made a new event loop, orphaning any worker the previous run started. | Worker had to start + drain + cancel inside a single coroutine. |
| Stale tests (5 sensors) | `test_cycle_c_stub_cleanup` asserted classes were absent that v4.0.2-B2 had legitimately resurrected | Test written for v3.20.2 stub-removal cycle; never updated when the deferred-to-Bayesian sensors came back. |
| Stale tests (`_retry_restore`) | `test_low_cleanup` asserted one specific guard string verbatim | Two equivalent guard patterns coexist in production (`if not self._deferred_restore:` and `if state is None:`); the `_ec_switch_factory` closure is a one-shot variant. |
| Stale tests (dedup) | `test_activity_logger` asserted critical dedup window == 0 | v4.0.11 introduced a 5-min safety-net dedup for critical events (coordinators are expected to transition-gate; the dedup is a backup). |
| Missing test mock | `test_music_following_coordinator` failed at import | Mock of `homeassistant.helpers.dispatcher` exposed `async_dispatcher_send` but not `async_dispatcher_connect`. |

## What changed

### Production code (annotation deferral only — no runtime effect)

`from __future__ import annotations` added to:

- `__init__.py`, `automation.py`, `aggregation.py`, `binary_sensor.py`,
  `camera_census.py`, `config_flow.py`, `coordinator.py`,
  `perimeter_alert.py`, `person_coordinator.py`, `sensor.py`,
  `transit_validator.py`

Effect: every type annotation in these modules is stored as a string instead of evaluated eagerly. Runtime tools that introspect `__annotations__` (like Home Assistant's config-flow voluptuous coercion) treat both forms identically. URA's HACS-visible behavior is byte-equivalent.

### Test infrastructure

- `quality/requirements_test.txt` — pinned `pytest>=8.2`, `pytest-asyncio>=1.0`, `aiosqlite>=0.20`, `voluptuous>=0.13`. Production HA bundles all of these; the dev env now matches.
- `quality/tests/conftest.py` — replaced `sys.modules.setdefault("aiosqlite", MagicMock())` with a try-import that prefers the real package and falls back defensively if missing (so collection still works on a broken dev env, with DB-touching tests rightfully failing instead of silently no-op'ing).
- `quality/tests/test_database_resilience.py`, `test_data_pipeline.py`, `test_energy_restart_resilience.py` — added `_do_db_op_with_worker(db, op_factory)` helper: wires `hass.async_create_background_task = asyncio.ensure_future`, drives `initialize → start_write_worker → op → write_queue.join → cancel_worker` in a single coroutine so the same event loop owns the worker's lifetime.

### Stale test repairs

- `test_cycle_c_stub_cleanup.py` — narrowed `removed_*` lists to the entities still genuinely absent (7 sensors, 1 binary sensor); added `test_b2_restored_*_present` asserting the v4.0.2-B2 resurrected entities (4 sensors + `OccupancyAnomalyBinarySensor`) ARE present.
- `test_low_cleanup.py::test_retry_restore_guard_in_source` — accepts three equivalent variants: boolean-flag guard, `_deferred_restore_state is None` check, and the `_ec_switch_factory` one-shot closure (no guard needed, scheduled exactly once).
- `test_activity_logger.py` — `test_critical_bypasses_dedup` rewritten to `test_critical_safety_net_dedupes_within_window` (asserts post-v4.0.11 5-min safety net behavior); `test_notable_has_longer_dedup_window` rewritten to `test_dedup_windows_are_tiered` asserting the strict ordering `info < notable < critical`.
- `test_music_following_coordinator.py` — mock added `async_dispatcher_connect` to the `homeassistant.helpers.dispatcher` mock module so `music_following.py` can import.

### New regression coverage

- `test_v450_d2_migration.py::test_all_migration_helpers_imports_resolve` — AST-walks every `_migrate_*` helper in `__init__.py`, finds each relative `ImportFrom` inside the helper body, dynamically imports the target module, and asserts every imported name exists. Generalizes the v4.5.0.1-specific check to cover all current and future migration helpers.

### CI guard

- `scripts/test_isolation_check.py` — runs every `quality/tests/test_*.py` in its own pytest invocation; exit code = number of files with real isolated failures; `--baseline N` to ratchet. Per-file isolation is necessary because some tests mutate `sys.modules` for HA mocks and don't restore on teardown — a bulk run still shows ~50 "noise" fails the isolation runner doesn't.

  ```
  $ python3 scripts/test_isolation_check.py
  Running 50 test files in isolation...
  Files: 50   real isolated fails: 0   elapsed: 11.3s
  OK: zero isolated failures.
  ```

## What this DOESN'T do

- **Doesn't fix the bulk-run noise.** Running `pytest quality/tests/` directly still shows ~48 failures and 14 errors, all in files that pass alone. Root cause is cross-test `sys.modules` pollution: tests register HA mocks via `sys.modules["homeassistant.x"] = MagicMock()` and don't restore on teardown, so later tests inherit a MagicMock-shaped `homeassistant.x` instead of the real (or test-specified) one. Auditing every test for `sys.modules` hygiene is a separate hygiene pass — not v4.5.2 scope. Per-file isolation is the truth, and the CI guard reflects that.
- **Doesn't grow test coverage** for currently-untested code paths. v4.5.2 is "fix existing tests, not add new ones." Coverage growth is its own cycle.
- **Doesn't refactor production code structure** beyond the annotation-deferral toggle. Where a test failed because production code structure made it hard to test, the test got updated to reflect actual behavior; production code was left alone.

## Tier 2 Review

| Severity | Finding | Resolution |
|---|---|---|
| (no CRITICAL) | — | — |
| (no HIGH) | — | — |
| MEDIUM | `from __future__ import annotations` interacts with libraries that introspect `__annotations__` at runtime (e.g. some dataclass / pydantic patterns) | URA doesn't use those patterns. HA's voluptuous-based config flows treat string and live-type annotations identically. Verified via test suite: no regressions in `test_cycle_b_config_flow` (29/29 pass in isolation) or any entity-description test. |
| LOW | Bulk-run noise (~50 fails) is not fixed | Documented as deferred hygiene. Per-file isolation is the truth and is now CI-enforced. |
| LOW | Some _retry_restore patterns are inconsistent (closure has no guard at all, others have boolean vs. None-check guards) | Documented in test rationale. The closure is provably one-shot; the variation isn't a defect. Future cleanup welcome but out of scope for a test cycle. |

**Verdict: READY TO DEPLOY.**

## Tests

- **Per-file isolated baseline:** **0 fails / 0 errors** across 50 files (~11s wall time).
- **Total tests passing:** 1912.
- **New tests added:** 1 (`test_all_migration_helpers_imports_resolve`); plus 2 restored entity assertions and 2 rewrites for current behavior.

## Live validation (post-restart)

This release has no user-facing behavioral changes. Validation is "nothing broke":

1. After HACS download + HA restart, watch logs for the first 5 minutes:
   - No new SyntaxError / ImportError at startup
   - No new TypeErrors in entity setup
   - All previously-working URA entities still load and update
2. Confirm Coordinator Manager still reports normal state (no extra "Setup failed" messages).
3. Spot-check one room: trigger occupancy → confirm light response unchanged.
4. Spot-check Battery: arbitrage state machine still cycles WAIT → CHARGE/HOLD/DISCHARGE per existing rules.
5. Optional: run `python3 scripts/test_isolation_check.py` in the dev env to confirm 0 isolated failures.

If any of these regress, revert is `git revert <commit>` — production-code change is purely the annotation-deferral toggle, fully reversible.

## Deploy notes

- No DB schema changes
- No migration needed
- HACS download required after deploy.sh per memory `feedback_verify_hacs_install.md`
- HA restart required (not just integration reload) to pick up the new bytecode across 11 modules.

## Next

- **v4.6.0** — Routine Awareness with reconciled AnomalyEvent foundation
- **v4.5.3 (or fold to v4.6.0)** — Config-flow restructure (was v4.5.1 before skip): paginated form, rate-plan top-level toggle, net-metering branch
- **v4.7.x** — B5 Appliance Scheduler
- **v5.0** — Config subentries + architectural debt cleanup (#1 setup/unload symmetry; #2 tracked background tasks; #3 EntityDescription rollout; #4 ConfigEntry.runtime_data)
