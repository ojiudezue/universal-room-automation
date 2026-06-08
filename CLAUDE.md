# URA Project Instructions

## Sibling project: Shipwatch

Shipwatch (post-deploy acceptance-hypothesis watcher) lives as a
sibling repo at `~/Code/shipwatch/` as of 2026-06-02. It used to live
inside this repo at `.claude/agents/ura-shipwatch.md` + `docs/dashboard-prototypes/shipwatch/`.

- **Runtime agent:** `~/.claude/agents/shipwatch.md` (global; invokable
  as `@shipwatch` or `/shipwatch` from any project).
- **Repo:** `~/Code/shipwatch/`. Its own `CLAUDE.md`, `scripts/deploy.sh`,
  versioning (1.x), and release cadence.
- **URA's `scripts/deploy.sh` is URA-only.** Do not co-opt it for
  Shipwatch releases — Shipwatch has its own deploy script.
- **URA's `.claude/agents/ura-shipwatch.md` is a deprecation stub**
  pointing at the new location. Invocations of `@ura-shipwatch` still
  resolve, but new work should use `@shipwatch`.
- **URA-side config:** none needed today. When Shipwatch v1.2.0 ships
  the `deploy.sh` integration, URA's `scripts/deploy.sh` will gain a
  small hook that writes `~/.shipwatch/sessions/ura_<version>.json` on
  successful deploy. Scoped under a separate URA cycle planning doc.

Shipwatch's `~/.shipwatch/projects.yaml` is user-local (not in any
repo) and registers URA as one of its onboarded projects. See
`~/Code/shipwatch/config/projects.yaml.example` for the schema.

## Subagent Usage Protocol — MANDATORY

For URA cycles, route each phase to the designated subagent. Do NOT default to `general-purpose` for cycle work — the URA subagents have institutional muscle memory (bug class names, file caution levels, ceremony rules).

| Phase | Agent | When |
|---|---|---|
| Planning doc / architecture | `ura-planner` | Writing PLANNING_v*.md, critiquing scope, tier classification |
| Implementation | `ura-builder` | Code changes to `custom_components/universal_room_automation/`, tests |
| Test execution + baseline-diff | `ura-validator` | After build, before review. Runs pytest, compares against `pre-review-vX.Y.Z`. Never edits code. |
| Code review | `ura-reviewer` | Tier 1 = one pass; Tier 2 = TWO parallel passes with different framings; Tier 2-DB = THREE parallel passes per Tier 2-DB protocol below |
| Deploy | `/deploy` skill OR `./scripts/deploy.sh` directly | `ura-deployer` is redundant — slated for deletion |

**Tier 2 review framings** — when dispatching two reviewers, give them DIFFERENT explicit focus areas so blind spots don't overlap. Example: Reviewer A = "correctness + edge cases", Reviewer B = "async + lifecycle + race conditions".

**Exception:** `general-purpose` is appropriate for one-off exploratory work OUTSIDE the URA cycle protocol (e.g., dashboard prototype investigation, branch state audits, broad codebase questions).

**No soak watching.** Never propose "monitor for 24h" / "soak overnight" as a post-deploy step. Cycles close at live-validation. Trip-wires for regression go in code (anomaly detection wired to NM), not calendar reminders.

**Worktree location discipline (added 2026-05-30 per v4.7.15 Reviewer C C5.2).** All agent worktrees MUST live under `.claude/worktrees/<agent-id>` (the project-managed location, already gitignored). The `/tmp` directory and other system tmpdirs are OFF-LIMITS for any worktree intended to hold uncommitted work, because macOS / Linux tmpfs eviction policies can wipe state without warning. If the main checkout is under contention from concurrent agents, use `git worktree add .claude/worktrees/<agent-id>-<cycle> <branch>` — never `/tmp/...`.

## Release Process — MANDATORY
- **Always use `./scripts/deploy.sh <version> <summary> <release-notes>`** for releases
- Create `docs/readmes/README_v<version>.md` BEFORE deploying
- Pre-stage new directories with `git add` before running deploy.sh
- Do NOT manually commit, push, or create PRs for releases

## Before Making Changes
- Read `docs/QUALITY_CONTEXT.md` for known bug classes (22 classes — includes stale data source #7, enum mismatch #22, observation mode gating #23)
- Read `quality/DEVELOPMENT_CHECKLIST.md` for review checklist
- Read the relevant source files before proposing changes

## No Fabrication — CRITICAL
Never describe HA APIs, library behavior, or in-repo code patterns from a plausible-sounding mental model. There are three valid options when a question about code/library behavior comes up:
1. **Verify**: read the actual source, the HA dev docs (https://developers.home-assistant.io), or the library docs. Cite file:line.
2. **Ask**: surface the gap before continuing.
3. **Admit**: say "I don't know" or "I'd be guessing." Explicit uncertainty beats confident-sounding fiction.
A fabricated spec wastes review cycles defending against bugs that can't happen and may miss the real ones. If you catch yourself writing "the standard pattern is..." without having read the standard pattern in this session — stop and verify.

## Institutional Context First — MANDATORY

Before proposing any new CONF_*, sensor, helper, constant, signal, or config-flow field — and before responding to "we have X" claims from the operator — verify via exhaustive search across the canonical prior-art surfaces:

1. **`custom_components/universal_room_automation/const.py`** — grep for similar-named constants in the same domain
2. **`config_flow.py`** + **`options_flow.py`** — grep for similar fields / selectors / steps
3. **`sensor.py`**, **`binary_sensor.py`**, **`number.py`**, **`switch.py`**, **`select.py`**, **`button.py`** — grep for similar entities
4. **`domain_coordinators/*.py`** — grep for similar helpers, signals, and dispatch sites
5. **Per-coordinator design doc at `docs/Coordinator/<NAME>.md`** — read before scoping changes to that coordinator
6. **Prior planning docs in `docs/planning/`** — at minimum skim filenames + headers for the affected coordinator area; pull bodies for any cycle that clearly touches the surface
7. **Memory bodies (not just `MEMORY.md` index lines)** — pull the full file for related backlog / live / shipped memos

For every proposed addition, cite **REUSED** (with file:line of existing) or **NEW** (with brief justification of why nothing equivalent exists). If you catch yourself proposing something without doing this verification, STOP and do it before continuing.

When the operator says "we have X" — treat it as a verification task before responding, not a statement to react to. If you can't find it, tell the operator exactly what you searched and ask where it lives.

**Why this rule exists (2026-05-30 incident):** A 14-hour session shipped multiple cycles and during scoping the assistant repeatedly proposed new fields/sensors/helpers without verifying against prior art. The operator had to push back each time, surfacing existing infrastructure the assistant should have found (`CONF_SCANNER_AREAS` v3.2.4, `PersonPhoneLeftBehindSensor`, `_check_zone_occupancy_confidence`, `is_direct_ble_room`, tier-naming collision). Codifying the verification protocol made it durable across sessions.

## Data Source Verification — CRITICAL
- **MCP `ura-sqlite`** reads the URA DB. Verify `--db-path` in `~/.claude.json` points to the **live** Samba-mounted path (`/Users/ojiudezue/ha-config/universal_room_automation/data/universal_room_automation.db`), NOT a stale cache (`~/.cache/ura/`).
- Before acting on any "missing table" or schema diagnosis from MCP tools, cross-validate against the live HA instance (use `ha-mcp` or SSH).
- If the Samba mount is stale or down, remount before querying: `mount_smbfs '//homeassistant:Verycool9277%40%5E@192.168.13.13/config' /Users/ojiudezue/ha-config`

## Testing
```bash
PYTHONPATH=quality python3 -m pytest quality/tests/ -v
```

## Key Architecture
- Home Assistant custom integration at `custom_components/universal_room_automation/`
- Domain coordinators: `domain_coordinators/` (safety, presence, base, house_state, signals, diagnostics)
- Branch strategy: main (production), develop (integration)
- Config entries: ENTRY_TYPE_ROOM, ENTRY_TYPE_ZONE_MANAGER, ENTRY_TYPE_COORDINATOR_MANAGER

## Review Protocol — TIERED BY SCOPE

Classify the change, then follow the matching review tier.

### Tier Classification
- **Hotfix** (1-3 files, single bug/issue, no new features): 1 review
- **Feature cycle** (new capability, multiple files, new sensors/entities): 2 reviews + live validation
- **DB-sensitive feature cycle** (see Tier 2-DB trigger criteria below): **3 reviews targeted at different risks** + live validation
- **When in doubt:** Use 2 reviews. Better to over-review than ship a regression.

#### Operator-elevated Tier 2-DB

The operator may explicitly elevate any cycle to Tier 2-DB review even when the listed triggers don't fire. Standard justification: trust-hierarchy ripple changes — situations where a small surgical fix risks regressions across multiple coordinators (presence ↔ HVAC ↔ compliance ↔ safety). When elevated, the three-reviewer protocol applies with the same framing-disjoint requirement. Document the elevation in the planning doc's tier-classification section so reviewers understand why the higher bar applies.

**Standing policy (operator-coined 2026-06-08): use the Tier 2-DB review protocol — 3 framing-disjoint reviews — for ALL regression-prone work, regardless of whether the DB triggers fire.** The "DB" in the name is historical; what the protocol actually buys is three disjoint framings so blind spots can't converge. Default to elevating, not to the 2-review tier, whenever a change is regression-prone. Regression-prone includes (non-exhaustive):
- **Trust-hierarchy / cross-coordinator ripple** — battery ↔ grid ↔ cost ↔ EVSE, presence ↔ HVAC ↔ compliance ↔ safety.
- **Strategy / decision-logic changes** affecting cost, comfort, or safety (e.g. battery TOU strategy, HVAC presets, load shedding).
- **Changes to a shared primitive** consumed by multiple coordinators (e.g. the TOU engine, signal bus, house-state machine).
- **Fixes to long-standing logic** that other code has come to depend on (reconciliation risk), or any change where "a small surgical fix" could silently break a sibling path.

Still pick the review *framings* to fit the change (the canonical A=data-integrity / B=migration / C=surfaces axes are for DB cycles; a strategy fix might use A=correctness+edge-cases / B=cross-coordinator+precedence+no-flap / C=test-authority+day/cycle-boundary). The invariant is **three disjoint framings + live validation + README write-back**, not the specific axis names. Non-regression-prone work (pure docs, isolated additive sensors, hotfixes with no ripple) may still use Tier 1 / Tier 2.

### Pre-Review: Tag the Baseline
Before applying ANY review fixes, tag the current state so you can diff back if fixes introduce regressions:
```bash
git tag pre-review-v<version> -m "Pre-review baseline for v<version>"
```
This lets you `git diff pre-review-v<version>..HEAD` to isolate review-fix changes.

### Tier 1: Hotfix Review (single review)
1. One staff-engineer adversarial review against `docs/QUALITY_CONTEXT.md` bug classes
2. Focus on: the specific fix, its blast radius, edge cases
3. Fix CRITICAL/HIGH issues, re-run tests
4. Deploy

### Tier 2: Feature Cycle Review (two reviews + live validation)
1. **Review 1 (Core A):** Domain logic files against QUALITY_CONTEXT.md bug classes. Check: correctness, edge cases, None handling, security, HA patterns, error propagation, missing channels/params in all codepaths.
2. **Review 2 (Core B):** Independent second review. Focus: race conditions, restart resilience, DB transaction safety, cross-coordinator interactions, HA lifecycle patterns, timer/listener cleanup.
3. **Fix all CRITICAL and HIGH issues**, re-run tests.
4. **Deploy** via `/deploy` skill.
5. **Live Validation (Review 3):** After HA restarts, run `@ura-validator` with live validation mode — checks entities, logs, DB state via MCP tools. This catches runtime wiring issues that static review misses.

### Tier 2-DB: DB-Sensitive Feature Cycle (three targeted reviews + live validation)

**User-coined rule:** *"We will need 3x staff end reviews that are targeted at diff risks."* — captured 2026-05-14 after v4.6.3 build shipped 6 CRITICAL findings to the first review pass that two generic reviewers would have converged on missing.

**Trigger when ANY of:**
- Cycle touches `database.py` DAO definitions
- Cycle migrates ≥3 callers to a new DAO
- Cycle changes payload shape of a dispatched event or persisted record
- Cycle adds behavioral test infrastructure against real schemas
- Cycle is followed within 1-2 versions by a planned schema migration that will depend on the new infra

**Why three, framed differently:** Two reviewers using the same framing converge on the same blind spots. v4.6.3 needed Review A (data integrity), Review B (migration correctness), and Review C (new surfaces) because each frame surfaced findings the others missed:
- Review B caught CRITICAL B1 (payload shape) that Review A had only flagged as MEDIUM
- Review C caught CRITICAL test-infra defects (C1-C5) that A and B would not have looked for

**Three parallel reviews, each framed by a different risk axis:**
1. **Review A — Data integrity + DB architecture preservation.** Existing rows preserved, no schema regression, write queue unchanged, indexes still cover, existing readers unaffected, existing analytics queries return the same shape post-deploy.
2. **Review B — Migration correctness + signal chain integrity.** Every migrated call site produces equivalent rows AND fires any downstream signals/dispatches AND no double-emit risk. End-to-end trace per migrated site. Field-by-field shape comparison vs the pre-migration emit.
3. **Review C — New surfaces + test fixture authority.** New sensors / buttons / config knobs round-trip through options flow + RestoreEntity. Behavioral test fixtures extract schema from production source (never hand-copy DDL). Tests drive production code paths, not their own INSERT/UPDATE/DELETE.

Run the three reviews in PARALLEL — different framings can't share blind spots.

**Fix CRITICAL/HIGH from any review before deploy.** Re-verify after fix-up. If fix-up was substantial, spot-check the changed surfaces or run a focused fourth review pass.

**Pre-deploy snapshot of affected table row rates** by `(coordinator, severity, type)` (or analogous shape for non-anomaly cycles). Without this, post-deploy ±25% comparison is impossible.

**Live Validation (Review D):** Post-restart, verify real values flow through — at least one row in the affected table has non-zero NOT NULL columns within an hour of restart. **Sentinels-only = payload shape broken** (the v4.6.1.1 / v4.6.3-initial-build shape). This single check would have caught both prior incidents.

### Record Live Validation Back Into the README — MANDATORY

**Operator-coined 2026-06-05 (v4.7.24).** The `README_v<version>.md` is written pre-deploy with *prospective* "Live" acceptance criteria. After Live Validation (Review 3 / Review D) runs against the restarted HA instance, the README is NOT done — you MUST write the *observed* results back into it before closing the cycle:

- Replace the prospective "Live Validation" bullet list with a **`Validated <date>`** results table: one row per acceptance criterion, each marked PASS / FAIL / as-expected, with the concrete observed evidence (entity_id + attribute value, log scan result, DB row read). Cite the authoritative signal actually used (e.g. a live entity attribute), not just "looks fine".
- Note any criterion that could only be proven in-suite rather than live (and why), and any boot-only transients you saw and dismissed.
- This makes the README the durable record of what the running house actually did, so future cycles don't re-litigate whether the feature shipped working. The git history of the README *is* the validation ledger.

A cycle is not closed until its README carries the post-restart validation table.

### Post-Review Documentation — MANDATORY
After every review cycle, persist findings in `docs/reviews/code-review/v<version>_<name>.md`:
- All bugs found (CRITICAL/HIGH/MEDIUM/LOW) and whether they were fixed
- **Bug class** for each finding (e.g., "Untracked Background Tasks", "Concurrent Reload Race")
- Summary statistics table (found/fixed/deferred by severity)
- Bug class frequency table showing which classes recur
- Recommendations for updating QUALITY_CONTEXT.md with new bug classes

After writing the review doc, check if any new bug classes should be added to `docs/QUALITY_CONTEXT.md`.

## Planning Docs — Acceptance Criteria Required

Every planning doc deliverable MUST include testable acceptance criteria. This is the "sprint contract" — what "done" looks like, agreed before implementation begins.

### Mandatory "Institutional context verified" section

Every planning doc MUST include an "Institutional context verified" section at the top, BEFORE the deliverables section. This section is the proof-of-work that the planner consulted the codebase's institutional knowledge before proposing changes. Reviewers verify it during Tier 1 / 2 / 2-DB review. It must list:

1. **Greps run + results** — for every proposed addition (CONF_*, sensor, helper, constant), either "REUSED <existing> at file:line" or "NEW because no equivalent found after grep of <surfaces>"
2. **Prior planning docs consulted** — filename + relevance (skim or full read)
3. **Memory bodies pulled** — filename + relevance
4. **Design docs read** — `docs/Coordinator/<NAME>.md` if the coordinator is affected
5. **Code locations surveyed** — files read end-to-end during scoping

Planners that omit this section produce plans that propose duplicate or conflicting work. The discipline materially reduces builder churn — empirically validated 2026-05-30 (three planners caught ~14 institutional errors before build).

**Format for each deliverable:**
```markdown
## D1: [Deliverable Name]
[Description of what to build]

### Acceptance Criteria
- **Verify:** [observable behavior that proves it works]
- **Verify:** [second observable behavior]
- **Sensor:** [entity_id] shows [expected value/state]
- **Test:** [test function names that cover this]
- **Live:** [what to check on running HA instance post-deploy]
```

The "Live" criteria feed directly into the post-deploy validation step. Without them, the validator doesn't know what to check.

## Plan Completion Tracking — MANDATORY
After every implementation cycle, explicitly document what was NOT done from the plan:
- List each planned item that was skipped or deferred
- State WHY it was deferred (time, complexity, dependency, or explicit decision)
- Where it should be tracked for future work
- Do NOT silently drop planned items — always account for them

## Don't Ask — Read First
- `WORKFLOW_GUIDE.md` — dev workflow
- Current cycle planning doc in `docs/` — implementation spec
- `docs/VISION_v7.md` + `docs/ROADMAP_v11.md` — architecture context

## graphify

The knowledge graph at `graphify-out/` is mostly a structural community map, not a semantic index. The GRAPH_REPORT.md is a community hub list — useful for navigation, not for "does X exist" or "where is Y" questions.

Rules:
- For **semantic questions** ("where does feature X live," "what consumes signal Y," "how do A and B relate"), prefer `graphify query "<question>"` / `graphify path "<A>" "<B>"` / `graphify explain "<concept>"` over grep — these traverse the graph's EXTRACTED + INFERRED edges
- For **existence questions** ("does CONF_X exist already," "what sensor exposes Y"), go direct with exhaustive grep across the prior-art surfaces in the **Institutional Context First** section above. The graph report won't answer these questions reliably.
- IF `graphify-out/wiki/index.md` EXISTS, navigate it instead of reading raw files
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).

**2026-05-30 revision:** the prior rule "ALWAYS read graphify-out/GRAPH_REPORT.md before reading any source files" was based on an assumption that the report would carry semantic content. It carries community navigation only. The rule was being ignored anyway because it wasn't producing useful context. Replaced with the targeted-use rules above.
