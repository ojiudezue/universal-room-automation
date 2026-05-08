# PLANNING v4.5.2 — Test baseline cleanup (tech debt #0)

**Status:** Implementation complete (D1–D7 done, awaiting deploy)
**Tier:** Tier 2 cycle (multiple deliverables; review per phase)
**Predecessors:** v4.5.0.4 (production), tech debt #0 documented in `docs/QUALITY_CONTEXT.md` since v3.x
**v4.5.1:** **SKIPPED** — see "Skip rationale" below

## Completion summary (2026-05-07)

Per-file isolated baseline before v4.5.2: 70+ fails / 14 errors.
Per-file isolated baseline after v4.5.2: **0 / 0** across 50 test files (~11s wall).

| Deliverable | Status | Notes |
|---|---|---|
| D1 Python 3.9 compat | ✅ | `from __future__ import annotations` added to 11 modules (initial 4 + 7 swept after coordinator/person_coordinator triggered the same TypeError under test import). |
| D2 DB harness fixture | ✅ | Pinned `aiosqlite` + `voluptuous`; replaced `sys.modules.setdefault("aiosqlite", MagicMock())` with try-import + defensive fallback in `conftest.py`; added `_do_db_op_with_worker` helper to wire `hass.async_create_background_task → asyncio.ensure_future` and drive init+start+drain in one coroutine. |
| D3 Stale test triage | ✅ | `test_cycle_c_stub_cleanup`: 5 entities had been resurrected as B2 Bayesian sensors in v4.0.2 — narrowed `removed_*` lists, added `test_b2_restored_*_present` for the resurrected ones. `test_low_cleanup`: `_retry_restore` now accepts the boolean-flag, None-check, and `_ec_switch_factory` one-shot variants instead of asserting one specific string. |
| D4 activity_logger | ✅ | 14 errors collapsed to 0 once D1's union-syntax sweep added future-annotations to coordinator.py / person_coordinator.py. Two stale dedup tests rewritten for post-v4.0.11 behavior (critical events use a 5-min safety-net dedup window, not "never deduped"). |
| D5 Generalize migration AST regression | ✅ | New test `test_all_migration_helpers_imports_resolve` AST-walks every `_migrate_*` helper in `__init__.py`, resolves relative imports against the actual modules, and asserts every name exists. Catches v4.5.0.1's class of bug for any future `_migrate_*`. |
| D6 CI failure-count guard | ✅ | `scripts/test_isolation_check.py` runs every `quality/tests/test_*.py` in its own pytest invocation; exit code = number of files with real isolated failures; `--baseline N` flag for ratcheting. Wired into DEVELOPMENT_CHECKLIST. |
| D7 Documentation sweep | ✅ | `docs/QUALITY_CONTEXT.md` #0 → DONE; `docs/ROADMAP_v11.md` #0 → DONE; `quality/DEVELOPMENT_CHECKLIST.md` adds isolation-check step + v4.5.2 dep notes. |

**Bulk-run cleanup deferred.** A bulk `pytest quality/tests/` run still
shows ~50 noise fails because some tests mutate `sys.modules` for HA
mocks and don't restore on teardown. Per-file isolation is the truth;
the CI guard reflects that. Auditing every test for sys.modules hygiene
is a separate hygiene pass, not v4.5.2 scope.

**Production code touched.** D1 only adds `from __future__ import annotations`
— a string-deferral toggle for type hints, zero runtime change on
Python 3.10+ (HA's runtime). Files: `__init__.py`, `automation.py`,
`binary_sensor.py`, `camera_census.py`, `config_flow.py`, `coordinator.py`,
`person_coordinator.py`, `sensor.py`, `aggregation.py`,
`transit_validator.py`, `perimeter_alert.py`. No HACS-visible behavior
should change.

## Skip rationale: why v4.5.1 was skipped

The original v4.5.0 plan (and the v4.5.0 README) noted v4.5.1 as a config-flow restructure cycle:
> v4.5.1 — Config-flow restructure (paginated form, rate-plan top-level toggle, net-metering branch)

During v4.5.0 live deployment (2026-05-07), two findings reshuffled the queue:

1. **Charge-rate control via barneyonline doesn't exist.** The v4.5.0 plan promoted "barneyonline rate control" as the v4.5.1 essential after the user's panel breaker tripped twice during arbitrage CHARGE. Investigation in v4.5.0.3 (and confirmed by user's barneyonline install) revealed that `barneyonline/ha-enphase-energy` is fundamentally an EV-charger + cloud-telemetry integration that exposes battery storage_mode + reserve controls (already in URA via the core Envoy integration) but **does NOT expose battery charge-rate / amp control**. Enphase's residential firmware doesn't expose that knob to ANY integration; the binary `charge_from_grid` switch is the only knob. The "charge-rate control" v4.5.1 deliverable cannot exist on current hardware.

2. **Tech debt #0 (test baseline cleanup) is BLOCKING per its own status** — `docs/QUALITY_CONTEXT.md` has flagged this as needed-before-architectural-work for months. With the v4.5.0 cycle now shipped (4 hotfixes!), starting test cleanup is the right next step. The config-flow restructure can wait — it's UX polish, not blocking.

**Decision (2026-05-07):** v4.5.1 deferred indefinitely (config-flow restructure may resurface as v4.5.3 or fold into v4.6.0). v4.5.2 begins next, focused exclusively on test baseline.

This skip is documented in:
- `docs/ROADMAP_v11.md` (this doc's reference + tech debt section update)
- `docs/QUALITY_CONTEXT.md` (#0 narrative updated to point at v4.5.2)
- Memory `project_v451_skipped_2026_05_07.md` (cross-cycle persistence)

## Context

The quality test suite has accumulated 57 fails + 14 errors over multiple cycles. CLAUDE.md tech debt #0 has flagged this as **BLOCKING** since at least Mar 2026 because new regressions in those areas are invisible — both v4.2.22's storm bug and v4.2.24's silent-save bug lived in untested code paths. v4.5.0's recalibration (after pinning `pytest-asyncio`) brought the count from a misleading 238 down to the actual 57+14, but the underlying drift remains.

The baseline must be driven to zero, with a CI guard preventing future drift, before further feature work compounds the problem.

## Goals

1. **All test files collect cleanly** — zero collection errors (currently 4 blocked).
2. **All tests pass or are explicitly skipped with documented reasons** — zero unhealthy fails.
3. **CI guard on failure count** — automated check that blocks merge when failure count grows.
4. **Document the test harness pattern** — make it easy for future cycles to add real-import tests that don't break under Python 3.9 dev environment.
5. **Generalize the migration helper AST regression test** — per memory `feedback_migration_helper_imports.md`. Single test scans all `_migrate_*` helpers in `__init__.py`.

## Non-goals (deferred)

- Adding NEW test coverage for currently-untested code paths. v4.5.2 is **fix existing tests**, not grow test coverage. Coverage growth is a separate cycle.
- Refactoring production code structure. Where a test fails because production code's structure makes it hard to test, the test gets skipped (with reason) and the production refactor is queued. Don't drag production refactors into a test-cleanup cycle.
- Migration of test infrastructure to pytest fixtures / pytest-homeassistant-custom-component. v4.5.2 keeps the existing `_mock_module` + `_load` patterns; it just makes them work consistently.

## Failure categorization (current state)

### Category A: Python 3.9 union-syntax (4 collection errors)

`int | None` / `str | list[str]` syntax requires Python 3.10+. URA targets HA 2026.x (Python 3.14+) so production runs fine, but the dev test environment is Python 3.9.6 which can't compile the type hints at module load.

| File | Line | Token |
|---|---|---|
| `custom_components/universal_room_automation/automation.py` | 508 | `float \| None` |
| `custom_components/universal_room_automation/config_flow.py` | 380 | `str \| list[str] \| None` |
| `quality/tests/test_fan_control_v318.py` | 540 | `float \| None` |
| `quality/tests/test_update_listener_async.py` | 31 | `ast.AST \| None` |

**Fix:** Add `from __future__ import annotations` as the first non-shebang line of each affected file. Defers all type-hint evaluation to string form; Python 3.9+ accepts. Zero runtime behavior change.

### Category B: DB harness gaps (~30 failures)

Multiple test files (`test_metric_baseline_integration.py`, `test_database_resilience.py`, `test_data_pipeline.py`, possibly `test_energy_restart_resilience.py`) hit `Error connecting to DB for circuit state save: DB write worker not running — call start_write_worker() first`.

**Diagnosis:** Tests construct a `UniversalRoomDatabase` instance but don't call `database.start_write_worker()` — production setup does this in `async_setup_entry` but tests bypass that path.

**Fix:** Either:
- Update each test's fixture to call `start_write_worker()` after construction, OR
- Add a shared `pytest fixture` in `conftest.py` for "initialized URA database" that handles setup + teardown

Sub-category — `test_metric_baseline_integration.py` may also need the DB to have specific tables initialized. Investigation per file.

### Category C: Stale tests (~20 failures)

Tests written against earlier URA versions whose assumptions no longer hold:
- `test_envoy_auto_derive.py:test_get_net_power_returns_zero_when_unconfigured` (3 fails) — likely v4.3.1 changed `_get_net_power` to return None when entity unconfigured (drop of envoy DEFAULT_*_ENTITY constants).
- `test_hvac_fan_control.py` (5 fails) — likely v4.x HVAC changes
- `test_cycle_c_stub_cleanup.py` (4 fails) — drift; investigate
- `test_low_cleanup.py:test_retry_restore_guard_in_source` (1 fail) — assertion against switch.py source code; v4.5.0.2 switch.py docstring expansion may have invalidated

**Fix:** Per file, either:
- Update test to match current production behavior, OR
- Document the drift, mark test as `@pytest.mark.skip(reason="...")` with a follow-up tracking task, OR
- Delete the test if it's testing behavior that no longer exists

### Category D: Missing module (`activity_logger`, 14 errors + 4 fails)

`test_activity_logger.py` imports `custom_components.universal_room_automation.activity_logger` — module doesn't exist.

**Diagnosis:** Either:
- The module was renamed/removed at some point and the test wasn't updated
- The test references a module that was planned but never built
- Need to grep production for any `activity_logger` reference

**Fix:** Either restore the module (if production references suggest it should exist), or skip / delete the test (if the feature is gone).

## Deliverables

### D1 — Python 3.9 compat (Category A)

Add `from __future__ import annotations` to:
- `custom_components/universal_room_automation/automation.py`
- `custom_components/universal_room_automation/config_flow.py`
- `quality/tests/test_fan_control_v318.py`
- `quality/tests/test_update_listener_async.py`

Run any other production .py files through `python3 -m py_compile` to catch additional 3.10+ syntax that would similarly block tests.

#### Acceptance criteria
- **Verify:** `PYTHONPATH=quality python3 -m pytest quality/tests/ --collect-only` returns 0 collection errors.
- **Verify:** `python3 -c "import ast; [ast.parse(open(f).read()) for f in <all_modified_files>]"` clean.
- **Test:** existing passing tests continue to pass (no regressions).
- **Live:** v4.5.0.4 production behavior unchanged (deployed identical bytecode on Python 3.14+).

### D2 — DB harness fixture (Category B)

Add a shared pytest fixture in `quality/tests/conftest.py`:

```python
@pytest.fixture
async def initialized_ura_db(tmp_path):
    """Provides a UniversalRoomDatabase with start_write_worker() called.
    Yield, then teardown via stop_write_worker()."""
    ...
```

Update each Cat B test file to consume the fixture instead of constructing the DB inline.

#### Acceptance criteria
- **Verify:** `pytest quality/tests/test_metric_baseline_integration.py quality/tests/test_database_resilience.py quality/tests/test_data_pipeline.py quality/tests/test_energy_restart_resilience.py` returns 0 fails (or documented skips).
- **Test:** the fixture handles repeat construction (one DB per test); no leaked state between tests.

### D3 — Stale test triage (Category C)

Per file:
- Investigate the failure
- Decide: fix / skip-with-reason / delete
- Document decision in test comments

Files: `test_envoy_auto_derive.py`, `test_hvac_fan_control.py`, `test_cycle_c_stub_cleanup.py`, `test_low_cleanup.py`.

#### Acceptance criteria
- **Verify:** each file passes (with skips counted as pass).
- **Verify:** every skip has a `reason=` arg explaining why.
- **Document:** any production-code drift that prevented a test fix is captured as a follow-up task or in `docs/QUALITY_CONTEXT.md`.

### D4 — activity_logger investigation (Category D)

`grep -rn "activity_logger" custom_components/` to determine if the module exists under a different name OR was abandoned.

If abandoned: delete `test_activity_logger.py`. If renamed: update the test imports.

#### Acceptance criteria
- **Verify:** `pytest quality/tests/test_activity_logger.py` returns 0 errors and 0 fails (whatever path is chosen).

### D5 — Generalize migration helper AST regression test

Per memory `feedback_migration_helper_imports.md`, the v4.5.0.1 ImportError class of bug (rename one place, miss the helper's import statement) deserves a parametric test that scans **all** `_migrate_*` helpers in `__init__.py`.

The current test in `test_v450_d2_migration.py::test_migration_helper_imports_resolve` is hardcoded to one helper name. Generalize it to:
1. Walk `__init__.py` AST
2. Find every function whose name starts with `_migrate_`
3. For each, collect imports from `.const` / `.domain_coordinators.*`
4. Assert each name resolves on the imported module

#### Acceptance criteria
- **Verify:** the generalized test catches a deliberate import typo in any `_migrate_*` helper.
- **Verify:** existing v4.5.0.1 import-resolution test still passes (or is replaced by the generalized version).

### D6 — CI failure-count guard

Add a CI workflow (or a pytest plugin / pre-commit hook) that:
1. Runs the full test suite
2. Compares failure count against a documented baseline (target: 0 after D1-D5)
3. Fails CI if count grows above baseline

Implementation options:
- GitHub Actions workflow yaml in `.github/workflows/`
- `quality/scripts/test_baseline_check.py` invoked from a git pre-commit hook
- Documented in `quality/DEVELOPMENT_CHECKLIST.md` as a manual gate (less automation but easier to ship)

User decides at planning review which option fits the project.

#### Acceptance criteria
- **Verify:** introducing a deliberate test failure to a passing file causes the guard to fail (block merge).
- **Verify:** the baseline file (e.g. `quality/test_baseline.txt`) is the single source of truth and is updated only on intentional changes.

### D7 — Documentation sweep

Update:
- `docs/QUALITY_CONTEXT.md` tech debt #0 — mark as **DONE** post-deploy; update to current baseline (target: 0)
- `docs/ROADMAP_v11.md` — remove tech debt #0 from blocking-queue; add to "completed milestones"
- `quality/DEVELOPMENT_CHECKLIST.md` — add the failure-count guard step before commit
- `CLAUDE.md` if any new test patterns established

#### Acceptance criteria
- **Verify:** new contributor reading these docs understands the test pattern + failure-count guard.

## Tier 2 Review Plan

### Phase 1 (D1): Python 3.9 compat + collection unblock

Quick deploy to confirm Cat A fixes don't regress production. Tier 1 review (1-line additions, low risk).

### Phase 2 (D2-D5): Substantive fixes

Per-deliverable review:
- D2: Tier 1 (fixture infrastructure + per-test consumption)
- D3: Tier 2 (multiple files, decisions to make)
- D4: Tier 1 (per chosen path)
- D5: Tier 1 (test generalization)

### Phase 3 (D6-D7): CI + docs

Tier 1 each. CI guard most important — it's what makes this cycle's work durable.

## Cost

| Component | Effort | LoC |
|---|---|---|
| D1 Python 3.9 compat | 30 min | 4 lines added |
| D2 DB harness fixture | 2-4 hours | ~80 lines |
| D3 Stale test triage | 4-8 hours | ~variable; investigate per file |
| D4 activity_logger | 30 min - 2 hours | depends on path |
| D5 AST regression generalization | 1 hour | ~30 lines |
| D6 CI guard | 1-2 hours | ~50 lines (workflow yaml or script) |
| D7 Documentation | 30 min | ~50 lines |
| **Total** | **9-18 hours** | **~250 LoC + variable test fixes** |

## Risks ranked

**Process:**
1. **D3 stale tests may surface production bugs.** A test failing because production behavior changed in an undocumented way could be either (a) the test is wrong, or (b) there's a real regression that nobody noticed. Each Cat C investigation needs to consider both possibilities.
2. **D6 CI guard scope creep.** If the project doesn't have CI infrastructure today, this could blow up to "build a CI pipeline" — that's its own multi-day effort. Mitigation: ship D6 as a pre-commit script if no CI exists. Document the desire for proper CI as a follow-up.

**Implementation:**
3. **`from __future__ import annotations` interaction with `dataclass` or runtime type checks.** Some libraries inspect `__annotations__` at runtime and may behave differently when annotations are strings. Mitigation: D1 deploys quickly; if any test starts breaking that wasn't broken before, revert and use targeted `Optional[X]` instead of union syntax.

**System:**
4. **Single-user no-back-compat means I can be aggressive on fixes** — but if I delete `test_activity_logger.py` and the module DOES exist somewhere, I'd lose the regression net. Mitigation: thorough grep before delete.

## Acceptance criteria summary

The release is "done" when:
- `PYTHONPATH=quality python3 -m pytest quality/tests/` reports **0 fails, 0 errors, 0 collection errors**.
- Failure-count guard exists and is documented (CI workflow or pre-commit hook).
- `docs/QUALITY_CONTEXT.md` tech debt #0 marked DONE.
- `docs/ROADMAP_v11.md` reflects v4.5.1 skip + v4.5.2 completion.
- All Tier-2 review CRITICAL/HIGH findings resolved; LOW findings explicitly tracked per memory `feedback_review_bug_visibility.md`.
- Migration helper AST regression test (D5) catches a deliberate import typo.

## Dependencies / preconditions

- v4.5.0.4 (current production) — ✅ shipped
- No URA functional changes during v4.5.2 cycle (test cleanup only) — to keep the cycle scope-pure.

## Next after v4.5.2

- **v4.5.3 (or fold to v4.6.0):** config-flow restructure (was v4.5.1 before skip)
- **v4.6.0** — Routine Awareness with reconciled AnomalyEvent foundation
- **v4.6.x** — Advanced energy-cost optimization (Bayesian peak_buffer, etc.)
- **v4.7.x** — B5 Appliance Scheduler
- **v5.0** — Config subentries + architectural debt cleanup
