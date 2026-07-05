---
name: ura-validation-and-qa
description: URA evidence and validation runbook — run the test suite, add tests for a new coordinator feature, write acceptance criteria, run live validation against HA, write the post-deploy live-validation table back into a README, perform Tier-3 framing-C mutation testing, or diagnose fixture/env-drift "failures". Triggers — "run the tests", "validate the cycle", "write acceptance criteria", "check that this actually works live", "mutation test the load-bearing site", "the suite baseline diverged", "write the live-validation table into the README".
---

# URA Validation and QA

**Purpose.** In URA, code review is not enough. Every change has to clear a specific evidence bar — deterministic tests **plus** a live-validation observation on the real house — before the cycle is closed. This skill is the runbook for producing that evidence.

**Audience.** A single Sonnet-class session or mid-level engineer, no subagent fleet. Multi-agent parallelism is an optional accelerator, not a prerequisite.

**Authority order.** `CLAUDE.md` (project root) > this skill > individual planning docs. If this skill conflicts with `CLAUDE.md`, `CLAUDE.md` wins — file an issue.

## When NOT to use this skill

- **Actually deploying** the change (stamp / commit / release / restart HA): use the `deploy` skill.
- **Writing the planning doc itself** (deliverables, tier classification, institutional-context section): use `ura-plan` / hand-write per `CLAUDE.md`.
- **Doing the code review passes A/B/C/D**: use `ura-review` or hand-run per `CLAUDE.md` Tier 2 / 2-DB / 3 protocols.
- **Configuring HA entities/dashboards themselves**: use `homeassistant_coding` or `ha-dashboard`.

This skill covers ONLY: tests, evidence, acceptance criteria, live validation, mutation testing, README write-back.

---

## 1. The evidence bar (verified 2026-07-02)

URA's release gate is **process, not CI** (no GitHub Actions gate as of 2026-07-02). Evidence is what stands between a change and prod.

| Layer | Artefact | Where it lives | Mandatory? |
|---|---|---|---|
| Deterministic unit / behavioural tests | `test_*.py` under `quality/tests/` | 232 files | Yes for every cycle |
| Baseline-suite diff | `git tag pre-review-v<version>` + `pytest` output diff | git tags | Yes before any review fixes are applied |
| Acceptance criteria | Per-deliverable block in the planning doc | `docs/planning/PLANNING_v<version>_*.md` | Yes per `CLAUDE.md` |
| Live-validation observations | Post-restart entity / log / DB reads via MCP | Recorded in the README | Yes for every cycle before close |
| README validation table | `Validated <date>` results table | `docs/readmes/README_v<version>.md` | Yes — the README git history IS the ledger |
| Mutation test evidence (Tier 3 only) | Real source edit → single test fails → restore | Recorded in framing-C review doc | Yes for Tier 3 |

A cycle is not closed until the README carries the post-restart validation table (`CLAUDE.md` — "Record Live Validation Back Into the README"). Reviewers gate on it.

---

## 2. Test-suite reality

### 2.1 Exact invocation

Always run from the repo root (`/Users/okosisi/Code/universal-room-automation`):

```bash
PYTHONPATH=quality python3 -m pytest quality/tests/ -v
```

Focus a single file or test:

```bash
PYTHONPATH=quality python3 -m pytest quality/tests/test_energy_battery.py -v
PYTHONPATH=quality python3 -m pytest quality/tests/test_energy_battery.py::test_reserve_floor_clamps -v
```

Rerun only failures:

```bash
PYTHONPATH=quality python3 -m pytest quality/tests/ --lf -v
```

Short traceback for suite baselining:

```bash
PYTHONPATH=quality python3 -m pytest quality/tests/ --tb=short -q > /tmp/ura_suite.out 2>&1; tail -30 /tmp/ura_suite.out
```

> `PYTHONPATH=quality` is required — the tests do `from tests.conftest import ...` style imports resolved relative to `quality/`.

### 2.2 Dependencies (verified `quality/requirements_test.txt`)

Install once per fresh environment:

```bash
python3 -m pip install -r quality/requirements_test.txt
```

Pinned:

| Dep | Pin | Why (from repo history) |
|---|---|---|
| `pytest` | `>=8.2,<9` | baseline |
| `pytest-asyncio` | `>=1.0,<2` | v4.5.0 — without it, ~180 async tests silently fail to collect and inflate the failure count, hiding real regressions |
| `aiosqlite` | `>=0.20,<1` | v4.5.2 — HA bundles it in prod; conftest used to `sys.modules.setdefault("aiosqlite", MagicMock())` which made `await db.execute(...)` a no-op and let ~30 DB-harness fails pretend to pass |
| `voluptuous` | `>=0.13` | v4.5.2 D3 — imported transitively via `config_flow.py` in `test_cycle_b_config_flow.py` |

### 2.3 MockHass / MockState / MockConfigEntry / MockCoordinator (verified `quality/tests/conftest.py:26–100`)

URA does **not** use `pytest-homeassistant`. The mocks are hand-rolled:

| Class | File:line | What it fakes | Key gotcha |
|---|---|---|---|
| `MockState` | `conftest.py:26` | `hass.states.get(...)` return value: `entity_id`, `state`, `attributes`, `last_changed`, `last_updated` | `last_changed` defaults to `datetime.now()` — pass an explicit ts via `set_state_with_time` for age-based tests |
| `MockHass` | `conftest.py:36` | `hass.states` as `MagicMock`, `.get` re-bound to an internal dict; `.data`, `.config_entries` also `MagicMock` | Anything you don't set is a `MagicMock` — reads succeed, comparisons silently pass. **Explicitly set every state your unit reads.** |
| `MockConfigEntry` | `conftest.py:62` | `data`, `options`, `entry_id`, `title` | Options-vs-data resolution is not modelled — production `entry.options` takes precedence over `entry.data`; tests must set the right one |
| `MockCoordinator` | `conftest.py:73` | `hass`, `entry`, `data`, `_last_motion_time`; `async_config_entry_first_refresh` is a no-op | No real dispatcher; assert on `hass.data` state, not on signal fanout |

> **Implication:** if a test appears to pass but the production code never reads the state you set, `MockHass` will happily return a `MagicMock` for `attributes.get(...)` and every branch is silently truthy. When a test's assertion is on a value that came out of `MockHass` without you setting it, the test is worthless.

### 2.4 `conftest_db.py` — real-schema sqlite fixtures (verified `quality/tests/conftest_db.py:1–286`)

**Rule:** behavioural DAO tests write through a fixture whose schema is extracted **from `custom_components/universal_room_automation/database.py` at test time**. The schema is never hand-copied.

Registered as a pytest plugin via `conftest.py:10`:

```python
pytest_plugins = ["conftest_db"]
```

Two fixtures:

| Fixture | Scope | Use for |
|---|---|---|
| `real_schema_db` | function | Behavioural tests that INSERT / UPDATE / SELECT — get a fresh in-memory sqlite each test |
| `real_schema_db_session` | session | Read-only schema checks (PRAGMA table_info, indexes) — DO NOT mutate |

Currently extracted (see `_REQUIRED_TABLES`, `conftest_db.py:39–48`, verified 2026-07-02):

```
anomaly_log, decision_log, compliance_log, outcome_log,
metric_baselines, ura_activity_log, notification_log,
house_state_log, optimization_findings, optimization_daily_digest
```

If you add a behavioural DAO test against a table **not** in that set, add it to `_REQUIRED_TABLES` — do not hand-copy DDL into your test module.

**Extraction is fragile but self-checking.** The regex parses triple-quoted strings and both literal-string ALTER TABLE calls and f-string tuple-list migrations (`conftest_db.py:80–150`). v4.7.12 D4 widened the tuple-list scan window from 800→2000 chars because the anomaly_log ALTER tuple grew past 800 chars. If the extractor stops finding statements, do not hack around it — fix the regex and add a regression test (see `test_v4712_anomaly_type_discriminator.py` for pattern).

### 2.5 aiosqlite: real package vs mock (verified `conftest.py:12–23`)

The defensive `sys.modules.setdefault("aiosqlite", MagicMock())` only fires on `ImportError`. On any properly-provisioned dev box the real package is used, and `await db.execute(...)` actually hits SQL. If you see DB-harness tests inexplicably passing on an unusual machine, check `python3 -c "import aiosqlite; print(aiosqlite.__version__)"` first.

### 2.6 Single-writer queue reminder (verified `custom_components/universal_room_automation/database.py:49`)

Production DB writes go through `self._write_queue: asyncio.Queue` (a single worker). Do NOT invent tests that write directly to a raw `aiosqlite.Connection` and assert queue-side behaviour — you will miss backpressure, single-writer serialisation, and the v5.0.0-v5.2.1 optimizer write-flood failure class. Drive writes through the DAO the coordinator uses.

---

## 3. Adding tests for a new coordinator feature

Checklist. Follow in order — later steps depend on earlier.

- [ ] **Find the closest existing sibling test.** Use the golden inventory in §7 to grep the right file. Copy its scaffolding — imports, fixture wiring, MockHass setup — never start blank.
- [ ] **File name:** `test_v<version>_<short_name>.py` if the change is version-scoped, or `test_<feature>.py` if it's a generic capability. Follow the naming in `quality/tests/`.
- [ ] **Import your production code.** `from custom_components.universal_room_automation.domain_coordinators.<name> import ...`. If import fails at collection time, that IS a real failure — don't `try/except` around it.
- [ ] **Instantiate MockHass and set every state your code reads** (§2.3 gotcha). If your coordinator calls `hass.states.get("sensor.foo")`, you MUST `hass.set_state("sensor.foo", ..., attributes={...})`.
- [ ] **Behavioural DB test?** Add the table to `_REQUIRED_TABLES` in `conftest_db.py` if it's not already there, and take the `real_schema_db` fixture as a param. Write via the DAO your coordinator uses; read via SQL to assert row shape.
- [ ] **Async test?** Decorate with `@pytest.mark.asyncio` (plugin is pinned §2.2). Confirm at least one `await` in the test body — a mistaken sync-def test with the decorator silently passes.
- [ ] **Assert on observable outputs, not private state.** Prefer: sensor `.native_value`, dispatcher signal fired, DB row present with expected columns non-null. Avoid: reaching into `coord._internal_dict`.
- [ ] **Add a mutation-anchored assertion for load-bearing sites** if this is a Tier 3 cycle (§6): pick ONE production line the test is supposed to prove is load-bearing and ensure the test would fail if it were neutered.
- [ ] **Run the ONE test** first (`pytest quality/tests/test_<file>.py -v`). Then run the full suite; compare against the baseline (§4).
- [ ] **Update the golden inventory (§7)** if this is a new coordinator or a new load-bearing file.

---

## 4. Baseline-suite diff discipline (verified `CLAUDE.md` — Pre-Review: Tag the Baseline)

### 4.1 Tag the baseline **before** applying any review fixes

```bash
git tag pre-review-v<version> -m "Pre-review baseline for v<version>"
```

This lets you isolate what your fixes changed: `git diff pre-review-v<version>..HEAD`.

### 4.2 Capture the pre-review pytest output

```bash
PYTHONPATH=quality python3 -m pytest quality/tests/ --tb=short -q > /tmp/pre_review_v<version>.out 2>&1
```

Note the pass / fail counts on the last line. That is your baseline failure count.

### 4.3 After review fixes, re-run and diff

```bash
PYTHONPATH=quality python3 -m pytest quality/tests/ --tb=short -q > /tmp/post_review_v<version>.out 2>&1
diff <(tail -5 /tmp/pre_review_v<version>.out) <(tail -5 /tmp/post_review_v<version>.out)
```

Acceptable outcomes:

| Delta | Verdict |
|---|---|
| Same counts | Ship |
| Fewer failures | Investigate: are the newly-passing ones related to your cycle? If unrelated, flag in the review doc but do not ship a "silent fix". |
| More failures | Do NOT ship. Find the regression by bisect on the fixes. |

### 4.4 Pre-Deploy Zero-Bugs Gate (per `MEMORY.md` — coined post-v4.7.4.3)

Immediately before `scripts/deploy.sh`, always run:

```bash
grep -rn "<<<<<<< \|=======$\|>>>>>>> " custom_components/universal_room_automation/ && echo "CONFLICT MARKERS" || echo "clean"
python3 -m py_compile $(git diff --name-only develop..HEAD -- '*.py')
PYTHONPATH=quality python3 -m pytest quality/tests/ -q
```

Source-grep AST tests DO NOT catch syntax errors — `py_compile` is the one that does.

---

## 5. Acceptance criteria and live validation

### 5.1 Acceptance-criteria format (verbatim from `CLAUDE.md` — Planning Docs)

Every planning-doc deliverable MUST include a block of this exact shape:

```markdown
## D1: [Deliverable Name]
[Description of what to build]

### Acceptance Criteria
- **Verify:** [observable behaviour that proves it works]
- **Verify:** [second observable behaviour]
- **Sensor:** [entity_id] shows [expected value/state]
- **Test:** [test function names that cover this]
- **Live:** [what to check on running HA instance post-deploy]
```

The `Live:` bullets are the input to §5.3. Without them, the validator does not know what to observe.

### 5.2 What Review 3 / Review D checks (verified `CLAUDE.md` — Tier 2 §5, Tier 2-DB Review D)

Live validation runs **after HA restart**, using the MCP tools listed below. It gates on three signal classes:

| Class | What to check | Fail-mode you're looking for |
|---|---|---|
| **Entities** | Sensor state + attributes on the sensors your acceptance criteria named. Read them, don't infer. | Entity `unavailable`, attribute missing, wrong value shape (e.g. dict where a str was documented) |
| **Logs** | `ha_get_logs` filtered to the URA integration around restart-time | ERROR entries mentioning the cycle's code; UnboundLocalError-class (Bug Class #34) regressions; boot-storm ERRORs |
| **DB rows** | For DB-writing features: at least one row with **non-zero NOT NULL columns** within ~1 hour of restart | **Sentinels-only ≠ pass.** Rows where every non-key column is a placeholder = payload shape broken (v4.6.1.1 / v4.6.3-initial-build shape). This single check would have caught both prior incidents. |

### 5.3 Live-validation commands (verified against `CLAUDE.md` — Data Source Verification)

**Preferred path — MCP tools:**

| Purpose | MCP tool |
|---|---|
| Read entity state + attrs | `ha_get_state` |
| Recent HA logs (filter to URA) | `ha_get_logs` |
| Historic state | `ha_get_history` |
| Config-entry status | `ha_get_integration` |
| URA DB reads | `ura-sqlite` MCP server |

Before you trust `ura-sqlite`, confirm `--db-path` in `~/.claude.json` points to the live Samba-mounted DB (NOT a stale `~/.cache/ura/` copy).

**Fallback path (MCP or mount down):** exact `mount_smbfs` command, live DB path, and MCP tool inventory live in `ura-diagnostics-and-tooling` § Live-access commands (fact-home). If both are down, SSH to HA and hit the DB with `sqlite3` on the mounted path; use `journalctl` for logs. Cross-validate every "missing table" or schema diagnosis against the live instance before acting on it.

### 5.4 README write-back — mandatory (verified `CLAUDE.md`)

The `README_v<version>.md` is written **pre-deploy** with prospective `Live:` bullets. After live validation runs, replace the prospective bullets with an observed-results table. **The cycle is NOT closed until this table is written.**

Format (canonical shape used across `docs/readmes/README_v5.5.3.md` etc.):

```markdown
## Validated <YYYY-MM-DD>

| Acceptance criterion | Result | Evidence |
|---|---|---|
| Bathroom exhaust runs 20 min after shower detected | PASS | `sensor.bathroom_exhaust_runtime` = 20; `switch.bathroom_exhaust` observed `on` at 21:14:03, `off` at 21:34:11 (ha_get_history) |
| No sentinels-only rows in optimization_findings | PASS | `SELECT COUNT(*) FROM optimization_findings WHERE finding_type IS NOT NULL AND severity IS NOT NULL AND created_at > <restart_ts>` = 6 |
| Away-actuation storm not re-triggered on boot | PASS | ha_get_logs since restart: 0 ERRORs matching `turn_off.*away`; boot-storm regression absent |
| Boot-transient `unavailable` on `sensor.ura_...` | Boot-only transient | Cleared within 40s of restart; documented, not a failure |
```

One row per acceptance criterion. Cite the authoritative signal (entity + attr, log grep result, SQL row count) — never "looks fine". Note any criterion that could only be proven in-suite (and why), and any boot-transients you saw and dismissed.

---

## 6. Tier 3 framing-C mutation testing (verified `CLAUDE.md` — Tier 3, framing C)

**Rule:** an aggregate monkeypatch proves the helper is load-bearing **in aggregate**. It does NOT prove that each production site actually routes through it. Framing C's job is to prove **per-site** coverage by editing production source directly.

### 6.1 Per-site mutation procedure

For each load-bearing production site (each place the invariant must hold):

1. **Identify the site** (`grep -n` the helper name in `custom_components/universal_room_automation/`). Enumerate all callers.
2. **Neuter ONE site** — edit `custom_components/universal_room_automation/<file>.py` to bypass the guard at that single call: e.g. inline the raw value instead of the clamped value, or comment out the helper call and use the unguarded input.
3. **Run the suite**:
   ```bash
   PYTHONPATH=quality python3 -m pytest quality/tests/ --tb=short -q
   ```
4. **Assertion:** at least one SPECIFIC test must fail, and it must be a test that names or exercises this site. If the suite stays green, the site is untested and **unacceptable** — file a NEW test that fails on this mutation before continuing.
5. **Restore the source** (`git checkout -- <file>.py` or unapply the diff) BEFORE moving to the next site. Never commit a mutated tree.
6. **Record in the framing-C review doc:** file, line, mutation applied, test that failed, restored (Y). One row per site.

### 6.2 Orchestrator independent verification (before ship, per `CLAUDE.md` Tier 3)

Do NOT trust reviewer summaries. Before deploy:

- Personally re-grep every emission / decision site of the invariant. Compare against the enumeration in the plan and in framing D's completeness pass.
- Re-run the mutation on at least one load-bearing site and confirm the specific test fails.

v5.5.3 caught a multi-line clamp that the initial verification regex missed. The re-run is not ceremony — it is what closed the gap.

### 6.3 Framing D — adversarial completeness (Tier 3 only, brief)

Not this skill's job to run, but note the coupling: framing D re-enumerates the entire invariant surface **including pre-existing code**, not just the diff. If D finds a leak (e.g. v5.5.3 D-HIGH-1 was a latent v5.5.0 gap), it feeds back into §6.1: a new load-bearing site got added retroactively → framing C must mutate it.

---

## 7. Golden inventory — which test file is authoritative for which coordinator

Verified against `quality/tests/` file listing 2026-07-02 (partial — grep for the coordinator name to catch version-scoped supplements like `test_v<ver>_*.py`).

| Coordinator / area | Primary test file(s) |
|---|---|
| Presence coordinator | `test_presence_coordinator.py`, `test_presence_provenance_split.py`, `test_presence_provenance_audit.py`, `test_presence_provenance_surface.py`, `test_presence_provenance_docs.py`, `test_presence_fan_interference_layer1.py` |
| Occupancy substrate | `test_room_substrate_integration.py`, `test_substrate_classification.py`, `test_substrate_discovery.py`, `test_substrate_lifecycle.py`, `test_substrate_seed.py`, `test_substrate_backcompat.py`, `test_substrate_boot_settle.py`, `test_zone_substrate_migration.py`, `test_substrate_no_conf_lists_fallback.py` |
| Fan recheck (Mode 2) | `test_fan_recheck_mode2_cycle.py`, `test_fan_recheck_db_schema.py`, `test_fan_recheck_deferred_surfaces.py`, `test_fan_interference_gate_layer1.py`, `test_fan_trust_state_extension.py`, `test_hotfix_sleep_occupied_fan_trust.py` |
| HVAC (base, zones, presets) | `test_hvac_fan_control.py`, `test_hvac_zone_intelligence.py`, `test_hvac_presence_timer_knobs.py`, `test_hvac_post_peak_coast_release.py`, `test_hc_precool_oc_observability.py`, `test_heatcool_enforcer.py`, `test_v47x_dynamic_preset.py`, `test_v4732_heat_cool_and_span_prune.py`, `test_zzz_v318_hvac_sensors.py` |
| HVAC egress | `test_v478_egress_db_schema.py`, `test_v478_egress_window.py` |
| Energy — base | `test_energy_consumption.py`, `test_energy_unit_normalization.py`, `test_energy_restart_resilience.py` |
| Energy — battery / arbitrage | `test_energy_battery.py`, `test_arbitrage_grid_import_guard_expose.py`, `test_arbitrage_solar_attainability_ladder.py`, `test_attain_hold_reason_wording.py`, `test_attainability_branch.py`, `test_battery_inclement_arbitrage_floor.py`, `test_battery_inclement_precedence.py`, `test_freeze_floor.py` |
| Energy — TOU / day-boundary | `test_energy_tou.py`, `test_day_boundary_tou.py`, `test_v47x_ev_tou_hardening.py` |
| Energy — pool / load-shed | `test_energy_pool_drain.py`, `test_energy_pool_fill_priority.py`, `test_energy_load_shedding_correctness.py` |
| Energy — EVSE / EV | `test_energy_evse.py`, `test_evse_offpeak_fill_release.py`, `test_evse_solar_aware_ux.py`, `test_ev_grid_cap.py`, `test_ev_offpeak_proactive.py` |
| Energy — Envoy / boot | `test_envoy_auto_derive.py`, `test_envoy_boot_decoupling.py` |
| Energy — Precool | `test_v5_7_1_energy_precool.py` |
| Inclement weather | `test_inclement_alert_classifier.py`, `test_inclement_solar_horizon.py`, `test_inclement_state_sensor.py` |
| Safety coordinator | `test_safety_coordinator.py` |
| Notification Manager | `test_notification_manager.py` |
| Optimization Coordinator | `test_optimization_coordinator.py`, `test_oc_pillar_a_handshake.py`, `test_oc_pillar_b_admin_surface.py`, `test_hc_precool_oc_observability.py` |
| Regime detector / Bayesian | `test_bayesian_predictor.py`, `test_bayesian_b2_prediction_sensors.py`, `test_v462_d4_regime_detector.py`, `test_v462_d4_js_divergence_math.py`, `test_v462_d4_schema_migration.py`, `test_v462_regime_detector_dispatches_signals.py`, `test_b4_energy_integration.py`, `test_b4_live_health.py` |
| Routine forecaster / music-following | `test_routine_forecaster.py`, `test_music_following.py`, `test_music_following_coordinator.py` |
| House state / person tracking | `test_v4714_away_state_person_tracker_trust.py`, `test_v4715_universalize_veto.py`, `test_v4716_room_veto_density.py`, `test_person_tracking.py`, `test_v47181_sleep_wake_deadlock.py`, `test_v570_guest_detection_trust.py` |
| Aggregation | `test_aggregation.py`, `test_v4_6_12_aggregator_sensors.py` |
| Domain coordinators (generic) | `test_domain_coordinators.py`, `test_coordinator_diagnostics.py`, `test_v4_6_13_coordinator_telemetry.py` |
| DB — schema / resilience / migrations | `test_database_resilience.py`, `test_db_incremental_vacuum.py`, `test_v460_db_migration.py`, `test_v461_db_migration.py`, `test_v461_canary_migrations.py`, `test_v463_anomaly_migration.py`, `test_v463_behavioral_dao.py`, `test_v450_d2_migration.py`, `test_room_energy_baseline_migration.py` |
| Anomaly framework | `test_v461_anomaly_event_dataclass.py`, `test_v461_severity_unification.py`, `test_v461_store_event_writer.py`, `test_v4712_anomaly_type_discriminator.py`, `test_v4514_anomaly_visibility.py`, `test_v4520_anomaly_refresh_signals.py`, `test_v461_cleanup_anomaly_log.py`, `test_v467_anomaly_log_null_relaxation.py` |
| Config flow | `test_cycle_b_config_flow.py`, `test_v475_d5_config_flow_runtime_smoke.py` |
| Bathroom exhaust cycle (v5.6.0) | `test_bathroom_exhaust_intelligence_cycle.py` |
| Boot behaviour | `test_boot_settle_gate.py`, `test_v4_7_18_2_boot_warning_logonce.py`, `test_v4_6_9_boot_state_robustness.py` |
| Deploy scripts / setup / teardown | `test_deploy_scripts.py`, `test_setup_unload_symmetry.py`, `test_update_listener_async.py` |
| Regressions catch-all | `test_regressions.py` |

Cross-cutting rule: for any version-scoped supplement, grep first:

```bash
grep -rln "<coord_name>\|<feature_name>" quality/tests/ | sort
```

---

## 8. Troubleshooting — is this failure real or environmental?

Diagnose in this order before blaming code:

1. **Fresh env?** `python3 -m pip install -r quality/requirements_test.txt`. Missing `pytest-asyncio` fakes ~180 fails; missing `aiosqlite` fakes ~30. See §2.2.
2. **Test importable?** `PYTHONPATH=quality python3 -c "import tests.test_<name>"`. Import-time failure looks like a runtime failure but is really a syntax / import bug.
3. **Baseline drift?** `git tag -l 'pre-review-v*' | tail -5` — is your baseline recent? If you're comparing against a months-old tag, expect noise.
4. **`MockHass` silent-pass?** If a test asserts on an attribute of a state you never called `hass.set_state(...)` for, you're comparing `MagicMock() == MagicMock()` which is always truthy (§2.3). Add the explicit `set_state`.
5. **`aiosqlite` mocked?** `python3 -c "import aiosqlite; print(aiosqlite.__version__)"`. If it errors, DB tests are running against `MagicMock` no-ops.
6. **Live actuator offline?** If it's a live-validation "failure", the URA code may be fine and the device dead — see `CLAUDE.md` — "Troubleshooting — room automation broke".

---

## 9. Provenance and maintenance

Facts in this skill that may drift. Re-verify before stating them in a plan or review.

| Fact | Re-verify command |
|---|---|
| Test count | `ls quality/tests/test_*.py \| wc -l` |
| Pinned versions of pytest / pytest-asyncio / aiosqlite / voluptuous | `cat quality/requirements_test.txt` |
| MockHass / MockState signatures | `sed -n '26,100p' quality/tests/conftest.py` |
| Real-schema fixture required tables | `sed -n '35,50p' quality/tests/conftest_db.py` |
| Schema-extraction regex window sizes | `grep -n 'window_start\|max(0, idx' quality/tests/conftest_db.py` |
| Single-writer queue location | `grep -n '_write_queue' custom_components/universal_room_automation/database.py \| head` |
| Golden inventory (§7) | `ls quality/tests/` then grep by coordinator name |
| Live DB path / mount command | `CLAUDE.md` — "Data Source Verification" (canonical; copy verbatim) |
| Bug-class count / QUALITY_CONTEXT header | `grep -c '^### Bug Class #' docs/QUALITY_CONTEXT.md` — 52 entries as of 2026-07-02, highest number in body is #53, header at `QUALITY_CONTEXT.md:7` still says "51 documented" (stale — fix in the same edit when adding the next class). Bug-class catalog fact-home: `ura-failure-archaeology`. |
| README write-back mandate wording | `CLAUDE.md` — "Record Live Validation Back Into the README" |

Last verified end-to-end against the repo: **2026-07-02**. When any of the above check-commands returns a materially different answer, update the corresponding section of this skill.
