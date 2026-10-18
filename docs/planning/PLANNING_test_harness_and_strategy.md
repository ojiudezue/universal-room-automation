# PLANNING — Test harness and strategy (real-HA default, order-independence, honest green)

**Cards:** `TEST-HARNESS-REAL-HA-DEFAULT-1` (kanban.data.yaml:21149) + parent `TEST-STRATEGY-REARCH-1` (:21366).
Children / linked cards folded in: `TEST-SUITE-ORDER-INDEP-PRODSTUBS-1` (:26876, done — collection order-independence),
`TEST-SOURCE-MUTATION-INPLACE-RESIDUAL-1`, `TEST-SILENT-WHOLE-FILE-SKIPS-1`, `SHADOW-IMPORT-AUDIT-1`,
`HA-2027-DEPRECATIONS-URA-1` (device-registry half parked behind the harness card), `TOU-RATE-FILE-KEY-UNWIRED-1`.
**Priority:** operator 2026-10-17, highest.
**Author role:** ura-planner. **Measured at:** develop `91c52c841`, 2026-10-17 evening.
**Supersedes for scope:** `PLANNING_test_strategy_rearchitecture.md` (the measure-only cycle; its D1–D7 artifacts in
`docs/planning/artifacts/test_strategy/` are DONE and are inputs here, not work).

---

## 0. Measurements (2026-10-17, one serial full run, read-only)

Command: `PYTHONPATH=quality .venv-ha/bin/python -m pytest quality/tests/ -q -p no:randomly -p no:cacheprovider --durations=40`
(no other pytest running; verified with `pgrep`).

| Metric | Value | Prior record |
|---|---|---|
| Result | **117 failed, 3 errors, 17,400 passed, 64 skipped, 2 xfailed** | 09-26: 194F/3E of 10.8k; operator brief: ~118 @ e2de7f4e1 |
| Wall time | **741 s (12m21s)** | 09-26: 483 s at 10.8k tests (+61% tests, +53% time) |
| Test files | 603 `test_*.py` | card said 429/479 |
| Files faking HA in `sys.modules` (ModuleType/MagicMock + `"homeassistant…"` + sys.modules) | **210** | card said 230 |
| Files writing `custom_components` source (`write_text`) | 11 | — |
| Distinct failing files | 47 | 56 |
| Pytest config file in repo | **none** (no pytest.ini / pyproject / setup.cfg) | unchanged |
| `pytest-randomly` installed in .venv-ha | **no** (`pytest-xdist 3.8.0` IS installed) | — |

### Classification (in-suite failures vs the same files each run ALONE, serially)

| Class | Count | Where |
|---|---|---|
| **Order-dependent** (fail in suite, pass alone) | **62** | weather_manager 17, identity_fusion_d2_d3_d4 10, v47x_dynamic_preset 6, v4623_humidity_fan 5, dp_drain_target_value_stamp 5, v4_7_18_dpm_drift_guard 4, + 12 files with 1–2 |
| **Intrinsic** (fail in suite AND alone) | **57** | 29 files, sub-classed below |
| **Hidden run-alone breakage** (pass or fail differently in suite; break alone) | 2 files fail to COLLECT alone (`test_v4623_humidity_fan_behavioral.py` → no module `cover_ownership`; `test_v570_fixup_wiring.py` → no module `database`); +3 extra test names alone | these pass only because an earlier file loaded the real module |

Intrinsic 57, sub-classed from the first `E` line of each alone run:

| Sub-class | ≈Count | Examples (file: error) |
|---|---|---|
| **Fake-HA drift** (hand-built fake lacks what real HA/prod now uses) | ~23 | census_device_switches: `_FakeHass` has no `.loop`; room_rename_writethrough: no `.data`; runtime_smoke: `StubBus.async_listen() got unexpected kw event_filter`; websocket_api: `'Schema' has no attribute 'validators'`; fan_interference_gate_layer1 + presence_coordinator: naive vs aware datetimes; egress_exit_backfill: `_DummyThread` thread-leak assert |
| **Stale source-text anchors** (Bug Class #62) | ~12 | energy_write_verification, evse_b1, fan_trust_state_extension ×2, low_cleanup, v462_d3, v472_dpm_surfaces ×2, v4_7_17_2, v4511 (asserts `Severity` defined in notification_manager; it is re-exported from `.base` at notification_manager.py:153, so runtime is fine), coordinator_diagnostics `9 == 8` |
| **Stale behavioural expectation / schema drift** | ~10 | hvac_excursion_d1 (`init_db`, `HVACOverrideCoordinator` gone), v467 sqlite `21 vs 20 bindings`, prediction_sensor_kill_list, reconcile_on_return, memory_compactor, exterior_cycle2, identity_fusion 1 |
| **Probable REAL defects** (the test is right) | ~4–6 | `test_setup_unload_symmetry`: untracked `hass.async_create_task(fire_stuck_signal(` at `__init__.py:4211`; `test_zone_delete_flow`: `hvac_ac_reset_*_zone_N` unique_ids (sensor.py:18658) not in the zone-delete enumerator → orphans on zone delete; `test_face_resolver_migrate` ("_2-only face sensor not resolved — census resolver call not wired"); `test_v5_7_1_energy_precool` B-1 (RestoreEntity OFF not overriding options-True). Each needs a 10-minute read before it's called a bug. |
| **Env / timing** | 1–2 | deploy_scripts: SIGINT trap timeout (subprocess, machine-load sensitive) |
| **Self-inflicted** | 1–2 | loop_stall_watchdog (see incident below) |

### Slowest tests (top-40 durations)
`test_chatter_wire_in.py` ≈ 25 subprocess mutation drills × 4.5–9.5 s ≈ **~150 s (~20% of wall)**; `test_ledger_golden_replay.py` 38 s;
`test_snap1_at_detection_snapshots.py::…traversal_event_id` 35 s (single test — suspicious, likely a timeout path);
`test_kanban_render.py` ~25 s; `test_fan_transition_gate`, `test_loop_stall_watchdog`, `test_owner_registry_mutation_matrix` drills 5–11 s each.
**Pattern: in-suite subprocess source-mutation drills are the dominant cost AND the tree-corruption hazard.**

### INCIDENT observed during this measurement (must be fixed first)
After the full run, `domain_coordinators/_loop_stall_watchdog.py` was left **mutated on disk** (`self._episode_active = False  # MUTATION`)
by `test_loop_stall_watchdog.py::test_mutation_drill_removes_per_episode_latch`. The tree was clean at session start; no other
pytest ran. So **a plain full-suite run on develop corrupts production source** — a live repro of
`TEST-SOURCE-MUTATION-INPLACE-RESIDUAL-1` and the `unrestored-mutation-drill-poisons-evidence` memory. The planner's restore was
permission-denied; **the file is still mutated in the main checkout and must be restored (`git checkout -- <file>`) before any
further run or commit.** Every suite result taken after that test in file order is evidence about a mutant.

---

## 1. Institutional context verified

**Cards read in full:** TEST-HARNESS-REAL-HA-DEFAULT-1 (:21149–21365), TEST-STRATEGY-REARCH-1 (:21366–21560),
TEST-SUITE-ORDER-INDEP-PRODSTUBS-1 (:26876–26967), BLE-HOLD-CAP-SUITE-POLLUTION-1 (:26968+). Linking cards enumerated via
`awk` over the board (SHADOW-IMPORT-AUDIT-1, TEST-SILENT-WHOLE-FILE-SKIPS-1, TEST-LEAK-DETECTOR-WRONG-LOOP-1,
TEST-SOURCE-MUTATION-KILL-UNSAFE-1, TEST-SOURCE-MUTATION-INPLACE-RESIDUAL-1, PYTEST-SUITE-CONST-STUB-ISOLATION-1,
SUITE-ORDER-POLLUTION-1, HA-2027-DEPRECATIONS-URA-1, FAN-RECHECK-D2-DEADLOCK-1, COVERAGE-RATING-FALSE-ANOMALOUS-1).

**Prior docs:** `docs/planning/PLANNING_test_strategy_rearchitecture.md` (full; measure-only, executed) and its artifacts
`D1_triage.md`…`D7_leverage_ranking.md`, `baseline_real_ha_273.txt` (D7's "AST-slice keep-set" lever has since landed — those 65
are not in today's set); `PLANNING_v4.5.2_test_baseline_cleanup.md` (skim).

**Memories pulled:** `feedback_serialise_suite_runs_across_agents`, `feedback_hollow_test_anchors`,
`feedback_unrestored_mutation_drill_poisons_evidence`, `feedback_mutation_verification_pycache_staleness`,
`feedback_worktree_isolation_all_agents` (index), CLAUDE.md §Testing.

**REUSE-or-BUILD per proposed piece:**

| Piece | Verdict | Existing symbol |
|---|---|---|
| Name-diff baseline + cache | **REUSE** | `scripts/suite_namediff.py` (cached by tree hash, waits for other pytest, `--files`, `--isolate`) |
| Shuffle-order collection gate | **REUSE/EXTEND** | `quality/tools/collect_order_matrix.py` (135 lines; collect-only, seeds + reverse, drift check) — extend to a RUN mode |
| Partial-stub backfill | **REUSE** | `quality/tests/conftest.py:143 pytest_collectstart` (PRODSTUBS-1) + `quality/tests/_ura_const_support.py` |
| sys.modules snapshot restore | **REUSE** | SUITE-HYGIENE-1 snapshot in `quality/tests/conftest.py` (678 lines) |
| phcc loop fixture override | **REUSE** | leak-detector override in conftest (shipped 09-20) |
| Serialisation guard | **REUSE** | `scripts/hooks/pytest_serialize.sh` (KILL semantics — unchanged) |
| Random-order plugin | **NEW dependency** (`pytest-randomly`), or **REUSE** collect_order_matrix's file-shuffle approach — operator decision Q2 |
| Pytest config file | **NEW** (`quality/pytest.ini` or root) — none exists after `ls pytest.ini pyproject.toml setup.cfg quality/pytest.ini` |
| Quarantine marker | **NEW** — `grep -rn "quarantine" quality/tests/conftest.py` → none; xfail(strict) is the reuse candidate (see D3) |
| Real-HA test fixtures (`hass`) | **REUSE** | phcc `hass` fixture, already used by 15 files importing `homeassistant` directly |

**Interpreter trap (D0) prior art:** CLAUDE.md §Testing and `.claude/agents/ura-validator.md:45` are ALREADY corrected to
`.venv-ha/bin/python`. Still wrong (grep `python3 -m pytest|PYTHONPATH=quality python3`): 9 skills
(`deploy`, `ura-validation-and-qa`, `ura-change-control`, `ura-analysis-methodology`, `ura-energy-invariants-campaign`,
`ura-optimizer-autonomy-campaign`, `ura-presence-reliability-campaign`, `ura-research-frontier`, `ura-ha-platform-reference`),
`docs/QUALITY_CONTEXT.md`, `quality/TEST_SUITE_ACCESS.md`, `quality/DEVELOPMENT_CHECKLIST.md`.

---

## 2. Falsifiable goal

> **G1 (honest green):** On develop, `PYTHONPATH=quality .venv-ha/bin/python -m pytest quality/tests/` exits 0, with every
> non-passing test either fixed or carried by a `quarantine` marker naming a card id and a class — **0 unexplained failures**.
>
> **G2 (order-independence):** the same suite run under ≥3 shuffled seeds + reverse file order produces the **identical
> pass/fail name set** (and identical collected count) as default order.
>
> **G3 (tree integrity):** after ANY suite run, killed or completed, `git status --porcelain custom_components/` is empty.
>
> **G4 (real-HA default):** the harness interpreter is pinned by repo config, not by memory; a run under any other
> interpreter fails fast with a message naming `.venv-ha`, and new tests are forbidden from adding `sys.modules["homeassistant…"]`
> fakes (lint gate), so the 210-file fake count is monotone non-increasing.

**How to break it (Reviewer D's target):** find one test whose outcome differs between two orderings; find one test that
leaves `custom_components/` dirty when SIGKILLed mid-run; find one quarantined test with no card; find one new file adding an HA
`sys.modules` fake that the lint gate admits.

---

## 3. Producer / consumer check (the value is "suite verdict")

- **Producer:** pytest under .venv-ha → pass/fail name set. Dependencies and health: interpreter (healthy only if invoked
  correctly — D0), phcc fixtures (healthy since 09-20), sys.modules state (UNHEALTHY: 62 order-dependent names), production
  source on disk (UNHEALTHY: a drill leaves it mutated — G3), wall clock (EVSE wall-clock family, carved into REARCH).
- **Consumers:** `scripts/suite_namediff.py` (trust decision: NEW names block merge), ura-validator, Pre-Deploy Zero-Bugs Gate,
  Reviewer C mutation drills, builder definition-of-done, `deploy` skill. Every one of them currently trusts a name-DIFF against a
  noisy 120-name baseline that is itself order- and mutation-contaminated. Making the producer honest (G1–G3) lets consumers move
  from name-diff to plain exit code — that is the payoff, and D7 below is the consumer switch.

---

## 4. Deliverables

Wave structure answers the operator's serial-vs-parallel question. **Rule across all waves:** builders run only targeted files
(`--files`); ONE coordinator-owned serial full run per wave close (serialise memory). Every parallel builder gets a worktree under
`.claude/worktrees/<id>`.

### Wave 0 — SERIAL, first, small (prerequisites everything else measures against)

**D0 — Interpreter trap + config pin (Tier 1, docs + one config file).**
Fix the 12 surfaces listed in §1 to `PYTHONPATH=quality .venv-ha/bin/python -m pytest …`. Add a repo pytest config
(`quality/pytest.ini` or root `pytest.ini`) setting `testpaths`, `asyncio_mode` (match current behaviour — measure first), and a
`conftest.py` session-start guard: if `sys.version_info < (3,13)` or phcc not importable → `pytest.exit("wrong interpreter: use .venv-ha/bin/python")`.
- **Verify:** `grep -rnE "python3 -m pytest|PYTHONPATH=quality python3" CLAUDE.md .claude docs/QUALITY_CONTEXT.md quality/*.md` → 0 hits.
- **Verify (discriminating):** `PYTHONPATH=quality python3 -m pytest quality/tests/test_aggregation.py` → exits within 1 s with the
  "wrong interpreter" message, NOT 98 `expected_lingering_tasks` errors. Under the old state the observation is the fixture error; under the fix it is the named message.
- **Test:** `test_harness_interpreter_guard.py` (subprocess with bare python3 → exit code + message).
- **Live:** n/a (test infra). Full serial run name set unchanged vs §0 baseline except nothing.

**D1 — Tree integrity: no test may leave production source mutated (Tier 2, test-infra; regression-prone → 2 reviews).**
Fix the immediate `_loop_stall_watchdog` drill (why did `finally/_restore` not restore? read `_mutate/_restore` + the
`_run_subtest` subprocess); then the structural guard: (a) a session-scoped autouse fixture snapshotting the bytes of every
file the 11 `write_text` tests target and restoring them at session finish, plus `atexit`/SIGTERM handler; (b) a
`pytest_sessionfinish` assertion that `git status --porcelain custom_components/` is empty → session FAILS loudly if not;
(c) preferred long-term: drills mutate a COPY in `tmp_path` and run the subtest with `PYTHONPATH` pointing at the copy — so the
real tree is never written. (c) is the real fix; (a)+(b) are the backstop. Owns `TEST-SOURCE-MUTATION-INPLACE-RESIDUAL-1`.
- **Verify:** full serial run → `git status --porcelain custom_components/` empty.
- **Verify (discriminating):** SIGKILL a run 3 s into `test_chatter_wire_in.py` → tree clean on next session start (backstop
  restores) vs today: mutation left on disk.
- **Test:** `test_suite_tree_integrity.py` (inject a deliberately unrestored write in a scratch test → sessionfinish fails).
- **Knob:** none (safety invariant; module-level constant list of protected roots only).

**D2 — Authoritative baseline + classification ledger (Tier 1, artifact).**
After D0/D1, ONE clean serial run → `docs/planning/artifacts/test_strategy/baseline_2026_10_<dd>.txt` and a CSV ledger
`test_id | class (order-dep / fake-drift / stale-anchor / stale-expect / real-bug / env) | owner deliverable | card`. Seeds the
quarantine list. This replaces the 120-name contaminated baseline in §0.
- **Verify:** ledger rows == failing names exactly (no silent drops); every class column non-empty.

### Wave 1 — PARALLEL (worktree-isolated builders; disjoint file sets; coordinator runs one name-diff at close)

All of these touch DISJOINT test files, so they cannot conflict. Each builder works only in its listed files plus, where stated, a new helper. **None edits `quality/tests/conftest.py`** (that file is Wave-2-serial territory).

| Lane | Deliverable | Files | Tier | Count |
|---|---|---|---|---|
| **P1** | **D3 — Quarantine mechanism** (marker `@pytest.mark.quarantine(card="…", cls="…")` registered in the D0 ini; implemented as `xfail(strict=False)` + a report section) and apply it to every D2 ledger row not fixed in this wave. Lint: marker without a card id = collection error. | new `quality/tests/_quarantine.py`, ini | 1 | — |
| **P2** | **D4a — Stale source-text anchors**: rewrite each as a behavioural test driving the real entry point, or delete-and-replace with a retirement anchor if the behaviour was superseded (cite the superseding commit). No assertion may simply be loosened. | energy_write_verification, evse_b1, fan_trust_state_extension, low_cleanup, v462_d3, v472_dpm_surfaces, v4_7_17_2, v4511, coordinator_diagnostics | 1 per file | ~12 |
| **P3** | **D4b — Fake-HA drift → migrate to real HA** (`hass` fixture from phcc). Strangler pilot: these files are the evidence that fakes rot. | census_device_switches, room_rename_writethrough, runtime_smoke, websocket_api, fan_interference_gate_layer1, presence_coordinator, egress_exit_backfill | 2 (shared fixture patterns; behavioural) | ~23 |
| **P4** | **D4c — Stale expectation / schema drift** | hvac_excursion_d1_observability, v467_anomaly_log_null_relaxation, prediction_sensor_kill_list, reconcile_on_return, memory_compactor, exterior_cycle2, identity_fusion (alone-1) | 1–2 | ~10 |
| **P5** | **D5 — Real-defect triage → production cards** (read-only; each confirmed one becomes its own card and normal cycle — NOT fixed in this plan): `__init__.py:4211` untracked task, zone-delete enumerator vs `hvac_ac_reset_*`, face_resolver `_2` wiring, v5.7.1 B-1 restore precedence, kanban_render, deploy_scripts timing. Quarantine each pending its card. | read-only | 1 | ~6 |
| **P6** | **D6 — Speed**: move subprocess mutation drills (`test_chatter_wire_in.py` ~150 s, fan_transition_gate, loop_stall, owner_registry_mutation_matrix, snap1 35 s outlier) behind a `drill` marker excluded from the default run and executed by Reviewer C / pre-merge gate; investigate the 35 s snap1 single test. Pair with D1(c) if the same files. | the drill files only | 2 | — |

**P6 ↔ D1 coupling:** D1(c) and P6 both edit the drill files. Either sequence D1 before Wave 1 (as planned) or give both to the
same builder. Do not run them in parallel.

**P2/P3/P4 per-file rule:** a test may not be weakened to pass. Each fix ships with the file passing ALONE and in suite;
a fix that only passes in one is not done.

### Wave 2 — SERIAL (shared-harness changes; each changes every test's environment)

**D7 — Order-independence (Tier 2-DB elevated: shared primitive = conftest consumed by all 603 files; 3 framing-disjoint reviews).**
Attack the 62 order-dependent names + 2 hidden run-alone collection breaks. Method, in order: (1) extend
`collect_order_matrix.py` with a `--run` mode that executes, not just collects, across seeds + reverse and reports per-name
outcome diffs (this is the G2 gate); (2) for each order-dependent file, find the donor (bisect with `--files A B`); (3) fix
donor-side by converting import-time `sys.modules` installs to fixture-scoped `monkeypatch.setitem(sys.modules, …)` (auto-restored),
or migrate the donor to real HA. The REARCH-recorded donors to start with: test_census_device_switches /
test_optimization_coordinator / test_evse_drain_precedence_session_b1 (→ nm_cycle_c2), test_bayesian_predictor /
test_envoy_auto_derive / test_hvac_fan_control (signals + package-root stubs at import time). The weather_manager 17 and
identity_fusion 10 are the biggest single victims — bisect them first.
**History warning:** the broad conftest-level restore was shipped once and REVERTED (exposed 87 reds). Donor-side fixture
scoping is the chosen path BECAUSE it changes one file at a time and each step is name-diffable.
- **Verify (discriminating):** `collect_order_matrix.py --run --seeds 1,2,3 --reverse` → identical failing-name set to default
  order (empty, after quarantine). Under a donor left unfixed, the victim name appears only in some seeds.
- **Test:** the matrix tool itself has a self-test (a planted order-dependent pair must be reported).

**D7 slice 3 — residuals carried from slice 2 (review B, 2026-10-18).**
- **Load-bearing evictors.** `test_optimization_coordinator`, `test_oc_pillar_a_handshake` and `test_oc_pillar_b_admin_surface`
  evict every `custom_components.universal_room_automation*` module per test and never restore. In the full suite that
  eviction is load-bearing CLEANUP: it re-imports URA fresh and so heals collection-time stubs left by files collected
  later (e.g. `_provenance_harness` importers, `zzz_*`). Slice 2 scoped them and exposed 21 victims
  (zone_migration_mint_guard x3, unload_symmetry_task_hygiene x2, fan_interference_gate_layer1 x4, ec_billing x2,
  energy_savings, house_state_restore x2, hvac_batch_d x2, prediction_sensor_kill_list, property_getter_pure,
  s10_post_preset_change_settle, zone_safety_alert x2), so the scoping was reverted and their own victims were fixed
  victim-side. Slice 3: retire the collection-time donors first (shared `_provenance_harness`, `_excursion_harness`,
  the `_set_now` HA-mock preamble family, `v47x_dynamic_preset` / `v47x_weather_manager`), THEN scope the three
  evictors. The abandoned broad attempt is on branch `test-wave2-d7-s2-round2-wip` (121 failing in the full-prefix
  run; do not merge -- reference only).
- Remaining every-order failures (D5): census_device_switches x6, v4623_humidity_fan_behavioral x5, deploy_scripts,
  setup_unload_symmetry, zone_delete_flow; optimization_coordinator x10 fail when run ALONE.

**D8 — Real-HA default + no-new-fakes gate (Tier 2).**
(a) Lint test `test_no_new_ha_sysmodules_fakes.py`: AST-scan `quality/tests/*.py` for `sys.modules[...]`/`setdefault` writes of
`homeassistant*` keys; allowlist = today's 210 files frozen in a committed file; any NEW file → fail. Allowlist may only shrink.
(b) A template / README section in `quality/TEST_SUITE_ACCESS.md` for writing a new test against phcc `hass`. (c) The strangler
rule recorded in the builder definition of done: a cycle that touches a fake-HA file migrates it.
- **Verify:** adding a scratch test with `sys.modules["homeassistant.core"] = MagicMock()` → lint fails; removing a file from the
  allowlist without migrating it → lint fails.

**D9 — Consumer switch (Tier 1, docs/agents).** Once G1–G3 hold: ura-validator, deploy skill, Pre-Deploy gate move from
"name-diff vs baseline" to "exit 0 + quarantine count did not grow"; keep `suite_namediff.py` as the diagnostic. Add
`collect_order_matrix --run` (one seed) to the pre-merge gate for Tier 2+.

### Wave 3 — PARKED (strangler migration of the remaining ~200 fake-HA files)
Not scheduled. Migrated opportunistically per D8(c). Revival trigger: fake-drift failures (P3 class) re-appear at > 5 new names
per month after D8 ships, or HA-2027-DEPRECATIONS-URA-1 needs real-HA coverage of device-registry paths.

---

## 5. Serial vs parallel — summary

```
Wave 0 (serial):  D0 -> D1 -> D2
Wave 1 (parallel, worktrees, disjoint files): P1 D3 | P2 D4a | P3 D4b | P4 D4c | P5 D5 (read-only) | P6 D6*
                  * P6 after D1 or same builder as D1
                  -> one coordinator full serial run + name-diff at wave close
Wave 2 (serial):  D7 (order-indep, Tier 2-DB) -> D8 (lint + real-HA default) -> D9 (consumer switch)
Wave 3: parked
```
Wave 1 can also overlap D7's step (1) (the matrix tool's `--run` mode is a standalone file) but not its donor fixes, because donor
files overlap the Wave-1 file lists (e.g. census_device_switches is both P3 and a D7 donor) — **give census_device_switches to D7,
not P3**, or sequence.

Concurrency budget (memory "fewer agents"): ≤2 concurrent builders is the operator's standing preference; with 5 lanes that means
Wave 1 runs as ~3 pairs. Override only on operator say-so (Q1).

---

## 6. Tier per deliverable

D0 T1 · D1 T2 (regression-prone harness; 2 reviews) · D2 T1 · D3 T1 · D4a T1/file · D4b T2 · D4c T1–2 · D5 T1 (read-only; spawned
production cards are tiered on their own) · D6 T2 · D7 **T2-DB (elevated, 3 framing-disjoint reviews: A no-test-weakened/
no-assertion-loosened, B order-independence via matrix, C mutation: neuter each donor fix → victim goes red in the seed that
exposed it)** · D8 T2 · D9 T1. Whole program: test-only, zero production risk EXCEPT if D5 spawns production fixes (separate cycles).
No version bump / deploy needed for test-only waves (merge to develop, rides next deploy).

---

## 7. Numbers get knobs
Test infrastructure, not runtime behaviour; numbers live as module constants in the tool files (rung 1, change requires review):
`ORDER_MATRIX_SEEDS = (1,2,3)` + reverse (collect_order_matrix.py), `DRILL_MARKER_DEFAULT_EXCLUDED = True` (ini `addopts -m "not drill"`;
kill switch = `-m ""`), quarantine growth tolerance `0` (D9). No CONF_*, no entities.

## 8. Non-goals
- No production code changes in this program. D5 only CARDS real defects.
- No deleting / skipping / loosening a test to get green. Quarantine requires a card id; deletion requires a superseding-commit citation.
- No flag-day migration of the 210 fake-HA files (08-23 measurement: wholesale switch = +207 failures, fixes 10).
- No change to `pytest_serialize.sh` KILL semantics.
- No xdist parallel execution by default (revisit after G2 holds — xdist on an order-dependent suite is a randomiser).
- No HA-version bump of phcc (harness HA 2026.2.3 vs live 2026.9.x drift is acknowledged and parked with HA-2027-DEPRECATIONS-URA-1).

## 9. Operator decisions needed
- **Q1 concurrency:** Wave 1 has 5 independent lanes. Run all in parallel (faster, more agents than the ≤2 preference) or in pairs?
- **Q2 random-order tool:** add `pytest-randomly` to .venv-ha (new dependency, per-test shuffling — stricter), or extend
  `collect_order_matrix.py` with file-level shuffled RUNS (no dependency, coarser)? Planner recommends the latter first: it is
  REUSE, and file-level order is where every measured donor lives.
- **Q3 drill tests out of the default run (D6):** ~20% of wall time and the tree-corruption hazard. Moving them behind a marker means
  a plain run no longer exercises them; Reviewer C and the pre-merge gate would. Approve?
- **Q4 restore the mutated file now:** `git checkout -- custom_components/universal_room_automation/domain_coordinators/_loop_stall_watchdog.py`
  (planner was denied permission).
