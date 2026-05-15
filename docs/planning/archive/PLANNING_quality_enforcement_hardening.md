# PLANNING: Quality Enforcement Hardening (ARCHIVED — build on degradation)

**Status:** SHELF-READY, do NOT build unless triggered
**Created:** 2026-05-14, after v4.6.3 Tier 2-DB cycle surfaced 6 CRITICAL + 3 HIGH findings that would have shipped silently under generic two-review framing
**Tier (when built):** Tier 1 per item, OR Tier 2 if shipping all at once
**Predecessor (assumed):** v4.6.3 doctrine codification (CLAUDE.md Tier 2-DB section, QUALITY_CONTEXT.md Bug Classes #39/#40/#41, DEVELOPMENT_CHECKLIST.md DB-Sensitive Cycle Checklist)

## Why this is archived, not queued

Today's session codified the quality directives but did NOT enforce them. Enforcement is currently 100% advisory — reviewer judgment + orchestrator discipline. That works as long as the orchestrator is paying attention. If quality signals degrade (review misses, deploy regressions, agents shipping CRITICAL bugs that pass tests), pull this plan off the shelf and build the appropriate subset.

This is intentionally NOT in the active backlog as a queued cycle. URA is single-developer with low write rate, so friction-adding enforcement infrastructure has a real cost. Build only when the cost of NOT having it exceeds the cost of having it.

## Trigger criteria — when to build

Build this plan (in whole or in part) when ANY of the following degradation signals fire:

1. **A CRITICAL bug ships to production despite review** — the v4.6.1.1 / v4.6.3-initial-build pattern. One occurrence = file as a near-miss; two within 90 days = build at least the post-deploy sentinel check.
2. **A Tier 2-DB cycle gets shipped with fewer than three independent reviews** — i.e., the directive in CLAUDE.md was bypassed under time pressure. Build the deploy.sh gate that requires three review docs.
3. **A behavioral test fixture is found drifted from production** — same shape as v4.6.3's `conftest_db.py`. Build the schema-equality regression meta-test.
4. **A build agent reports completion with uncommitted changes** more than once in a quarter — build the Claude Code PostToolUse hook on `Agent`.
5. **A dedup-mask under-refresh is observed in a sensor** — `sensor.ura_recent_anomalies` or similar shows zero rows despite `anomaly_log` having recent entries. Build the static dedup-mask heuristic check.
6. **Multi-developer expansion** — if URA ever gains a second active contributor, build the full pre-commit hook set (Tier B in the recommendation tree). The cost-benefit for single-developer flips entirely with a second person on the codebase.

## Scope — four enforcement layers, build in priority order

### Layer 1 — `validate-deploy.sh` + post-deploy sentinel check (HIGHEST ROI)

**Why first:** Closes the v4.6.1.1 / v4.6.3-initial-build CRITICAL bug class shape. Sentinels-only NOT NULL columns in `anomaly_log` (or analogous tables) is automatically detectable post-restart. Would have caught both incidents without human in the loop.

**Deliverables:**

**D1.1 — `scripts/validate-deploy.sh`** invoked by the `/deploy` skill after `ha_restart` + warmup wait.
- Connects to live HA via the existing MCP-style query path OR direct samba-mounted SQLite read.
- Queries `anomaly_log` for rows written in the 5 minutes post-restart with all NOT NULL columns at sentinel values (`observed_value=0.0 AND expected_mean=0.0 AND z_score=0.0 AND sample_size=0`).
- If any rows match, exit non-zero with the row IDs printed. Deploy skill displays the failure and instructs orchestrator to investigate before declaring shipped.
- Threshold: 0 sentinel-only rows acceptable when emit sites have legitimate non-zero metric values upstream. Allow exceptions via a documented `coordinator_id` allow-list (e.g., binary hazards that legitimately have no metric value).

**D1.2 — Coordinator coverage check** (24h soak window)
- 24 hours post-deploy, query `SELECT DISTINCT coordinator_id FROM anomaly_log WHERE timestamp > <deploy_time>`.
- Expected list comes from a manifest committed alongside the cycle: `docs/cycles/v<version>_expected_emitters.json`.
- If any expected coordinator hasn't emitted in 24h, fire a warning. Silent broken emit = the v4.6.3 NM-correlation failure mode if the linked_event_id threading had failed.

**D1.3 — `/deploy` skill integration**
- New step between Step 8 (Wait + Verify) and Step 9 (Report): invoke `validate-deploy.sh`.
- On non-zero exit, skill output includes a clear "VALIDATION FAILED" banner with the offending rows.

**Acceptance Criteria**
- **Verify:** synthetic test against a known-good v4.6.3 deploy (all real values) → exit 0
- **Verify:** synthetic test with a hand-inserted 0.0-sentinel row → exit non-zero with row ID printed
- **Verify:** the deploy skill invokes the validator after restart, displays output, asks orchestrator to confirm before declaring shipped

**Cost:** ~60 LoC bash + ~20 LoC skill integration + ~30 LoC tests (with mock DB).

### Layer 2 — Pytest meta-tests for v4.6.3 bug classes (DETERMINISTIC, RUNS EVERY `pytest`)

**Why second:** Catches regressions in the v4.6.3 anti-patterns automatically at test time. Cost is low (a few small test files), reliability is high (runs on every test invocation including pre-deploy).

**Deliverables:**

**D2.1 — `test_no_hand_typed_ddl_in_test_fixtures` (Bug Class #39)**
- Greps every file matching `quality/tests/conftest*db*.py` AND `quality/tests/*_db.py` for literal `CREATE TABLE` strings.
- If a literal `CREATE TABLE` is found AND the file doesn't have a header comment `# SCHEMA-EXTRACTED-FROM-PRODUCTION` or similar opt-out marker, fail.
- Allows the existing `real_schema_db` fixture's runtime regex-extraction approach to pass (CREATE TABLE strings are read from `database.py`, not embedded in the fixture file itself).

**D2.2 — `test_behavioral_tests_call_production_dao` (Bug Class #40)**
- AST-walks every file matching `quality/tests/test_*behavioral*.py` AND `quality/tests/test_*_dao.py`.
- For each test function, asserts the function body contains at least one call to a `database.*` or `<coordinator>.<emit_method>` function.
- Fails if a test body contains only raw SQL (`INSERT INTO|UPDATE|DELETE FROM` in string literals) and no production function call.
- Allow-list mechanism: tests can be marked with `# allow-raw-sql: <reason>` if there's a legitimate reason (e.g., negative-path test that constructs a malformed row).

**D2.3 — `test_conftest_schema_matches_production` (Bug Class #39, positive form)**
- Uses the existing `real_schema_db` fixture from v4.6.3.
- For every table the fixture creates, runs `PRAGMA table_info(<table>)` on both the fixture's connection AND a fresh in-memory DB initialized via production's actual code path.
- Asserts column-set + type + NOT NULL constraint equality per table.
- This test is the regression-prevention insurance for the schema extraction logic itself — if anyone breaks the extraction regex or production schema definition diverges from what the fixture parses, this test fires.

**Acceptance Criteria (each)**
- **Test:** test runs and passes against current main branch (post-v4.6.3) state.
- **Test:** test fails if a hand-edited bad pattern is introduced (synthetic regression test per meta-test, possibly via a `bad_pattern_test/` subdirectory the meta-test deliberately points at to confirm it catches violations).

**Cost:** ~80 LoC total across 3 test files.

### Layer 3 — Pre-deploy baseline snapshot (extends `deploy.sh`)

**Why third:** Mechanical addition to deploy.sh that makes the Tier 2-DB ±25% post-deploy drift check trivially possible. Without this, the orchestrator has to manually capture baselines, which is error-prone.

**Deliverables:**

**D3.1 — Baseline capture step in `scripts/deploy.sh`**
- Insert between Step 2 (Staging) and Step 3 (Commit): `scripts/capture-deploy-baseline.sh v<version>`.
- Script queries live HA's anomaly_log (via the same path validate-deploy.sh uses) for `SELECT coordinator_id, severity, COUNT(*) FROM anomaly_log WHERE timestamp >= datetime('now', '-24 hours') GROUP BY 1,2`.
- Saves to `.deploy-baselines/v<version>-pre.json` (gitignored or committed — design choice; lean toward committed for audit trail).
- 24h after deploy, an automated `scripts/compare-deploy-baseline.sh v<version>` queries again, compares to baseline, prints any coordinator/severity rate outside ±25% of baseline.

**D3.2 — Post-deploy baseline comparison invocation**
- Could be a cron-style HA automation triggered 24h after deploy, OR a manual invocation the orchestrator runs as part of the 24h soak check.
- Recommended: a `/baseline-compare` skill that runs against the most recent baseline.

**Acceptance Criteria**
- **Verify:** running deploy.sh writes the pre-baseline file.
- **Verify:** running compare 24h later shows expected delta against baseline for an unchanged-behavior cycle (within ±25%).
- **Verify:** synthetic test that injects 10x normal rate → comparison flags it.

**Cost:** ~30 LoC bash + ~20 LoC for the compare script + skill integration.

### Layer 4 — Claude Code PostToolUse hook on `Agent` tool (orchestrator-side enforcement)

**Why fourth:** Closes the v4.6.2.1 "agent reported done but didn't commit" near-miss class. Runs in the harness, not the repo, so it doesn't add friction for non-agent flows.

**Deliverables:**

**D4.1 — PostToolUse hook in `.claude/settings.json` or user-level settings**
- Fires after every `Agent` tool call.
- Inspects the agent's return summary for keywords like "branch", "commit", "feature/" and extracts a claimed branch name.
- If a branch name was claimed, runs `git log --oneline <base>..<branch> | wc -l` against the worktree or main repo.
- If output is 0 lines (no new commits), injects a system reminder into the orchestrator's context: "Agent claimed completion with branch `<X>` but no new commits found. Verify with `git status` in the worktree before declaring done."
- Doesn't BLOCK the orchestrator's next action; just informs.

**D4.2 — Stop hook for uncommitted-changes warning**
- Fires at session end.
- If any `feature/*` branch in any worktree has uncommitted modifications, prints a warning so the orchestrator can decide whether to commit, stash, or accept the loss.

**Acceptance Criteria**
- **Verify:** spawn a test agent that intentionally doesn't commit; hook fires the reminder.
- **Verify:** spawn an agent that commits properly; hook does NOT fire (no false positive).

**Cost:** ~30 LoC across settings.json + a tiny shell script.

## Out of scope (do not build even if triggered)

- **Pre-commit hooks** (Tier B in the May 14 recommendation tree) — too much friction for single-developer URA. Only revisit if multi-developer.
- **CI gates on PR creation** — same reason; PRs are auto-created and auto-merged by deploy.sh, there's no review window where a CI gate would meaningfully help.
- **Heuristic dedup-mask description scanner** — too noisy; false-positives would create alert fatigue. The pytest meta-test in Layer 2 is more reliable.
- **Mandatory three-review enforcement in deploy.sh** — would require parsing review doc filenames, which is brittle. Reviewer discipline via CLAUDE.md is sufficient until proven otherwise.

## Phasing — partial builds allowed

If quality degrades but not catastrophically, build only the layers that match the degradation signal:

- CRITICAL bug ships → build **Layer 1** only (~2 hours)
- Behavioral fixture drifts → build **Layer 2.3** only (~30 minutes)
- Agent commit miss recurrence → build **Layer 4** only (~30 minutes)
- Multiple degradation signals → build **Layers 1+2** together (~3 hours)
- Full hardening cycle → build **Layers 1+2+3+4** as a v4.x.y cycle (~5-6 hours, Tier 2 if shipped all at once)

## Recovery — what if this plan itself becomes stale

This plan was written 2026-05-14 against the post-v4.6.3 codebase. The directives it enforces depend on:
- `database.py` having a `save_anomaly_event` DAO
- `anomaly_log` table having NOT NULL constraints on metric columns
- `quality/tests/conftest_db.py` using runtime regex-extraction from `database.py`
- `CLAUDE.md` containing the Tier 2-DB section

If any of those drift significantly (e.g., schema gets relaxed via the NOT NULL relaxation cycle and sentinels become valid), revisit the plan before building. The sentinel check in Layer 1 in particular is calibrated to the current schema.

## Memory + discoverability

This plan is in `docs/planning/archive/` to signal "shelf-ready, not queued." When promoted to active build:
1. Move (or symlink) to `docs/planning/PLANNING_v4.x.y_quality_enforcement.md` with a real version number
2. Add a `BACKLOG.md` entry pointing at the active version
3. Update memory entry `feedback_db_sensitive_3x_targeted_reviews.md` to note enforcement has shipped

For now, this plan lives only in the archive; the BACKLOG entry just references its existence as a deferred option.
