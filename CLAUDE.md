# URA Project Instructions

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
