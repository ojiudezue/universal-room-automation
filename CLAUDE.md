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
