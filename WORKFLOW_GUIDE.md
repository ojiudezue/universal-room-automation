# URA Development Workflow Guide

**Primary Workflow:** Claude CLI with Auto-Spawned Subagents  
**Updated:** February 2026

---

## 🚀 Primary Workflow: Claude CLI + Subagents

Run `claude` from the project root. Claude will **automatically spawn** the right agent for each task, or you can invoke one directly with `@agent-name`.

```bash
cd /Users/ojiudezue/Code/universal-room-automation
claude
```

### The 4 URA Agents

| Agent | Model | When Claude Spawns It | Direct Invoke |
|-------|-------|----------------------|---------------|
| `ura-planner` | `claude-opus-4-6` | When reviewing/critiquing a planning doc | `@ura-planner review docs/PLANNING_v3_5_0_Camera_Intelligence.md` |
| `ura-builder` | `claude-sonnet-4-6` | When implementing features or fixing bugs | `@ura-builder fix the music transition bug in music_following.py` |
| `ura-reviewer` | `claude-opus-4-6` | When ingesting changes from an external version | `@ura-reviewer review v3.3.5.4 at [path]` |
| `ura-validator` | `claude-sonnet-4-6` | After any code change, before commits | `@ura-validator run tests` |

Agents are defined in `.claude/agents/`. The HA coding skill is at `.claude/skills/homeassistant_coding/SKILL.md`.

---

## 📋 Core Workflows

### Ingest an Old OneDrive Version (e.g. v3.3.5.4)

```
1. @ura-reviewer review v3.3.5.4 at /Users/ojiudezue/Library/CloudStorage/
   OneDrive-Personal/2025/Download 2025/Madrone Labs/Integrations/
   Room Appliance Integration/v3.3.5.4/universal_room_automation

2. Review the ✅/⚠️/❌ report

3. @ura-builder adopt the approved changes

4. @ura-validator run tests

5. git commit -m "[builder] feat: adopt v3.3.5.4 changes — [summary]"
```

### Fix a Bug

```
1. Describe the bug: "Fix music transition timing in music_following.py"
   → Claude auto-invokes ura-builder
   
2. ura-builder reads quality/QUALITY_CONTEXT.md and POST_MORTEM docs first

3. @ura-validator (auto-invoked after fix)

4. git commit
```

### Review an Existing Plan (Not Replanning)

```
1. "Review the v3.5.0 camera intelligence plan"
   → Claude auto-invokes ura-planner
   
2. ura-planner reads VISION_v7.md + ROADMAP_v9.md + the planning doc

3. Returns critique with ✅/⚠️/❌ — no new plan written
```

### Implement a Planned Feature

```
1. "Implement [feature] from PLANNING_v3_5_0_Camera_Intelligence.md"
   → Claude auto-invokes ura-builder

2. ura-builder reads planning doc + DEVELOPMENT_CHECKLIST.md

3. @ura-validator after implementation

4. git commit → PR to develop
```

---

## 🎯 Model Selection (Current Versions)

| Model | API ID | Role |
|-------|--------|------|
| Claude Opus 4.6 | `claude-opus-4-6` | Planning critique, code review, architecture |
| Claude Sonnet 4.6 | `claude-sonnet-4-6` | Building, testing, validation, documentation |

> **Sonnet 4.6** (released Feb 17, 2026) has a 1M token context window — can read the entire URA codebase in a single pass.  
> **Opus 4.6** (released Feb 5, 2026) is for complex reasoning and cross-file architectural decisions.

---

## 📚 Key Resources

| Resource | Path | Used By |
|----------|------|---------|
| HA Coding Skill | `.claude/skills/homeassistant_coding/SKILL.md` | ura-builder |
| Vision | `docs/VISION_v7.md` | ura-planner |
| Roadmap | `docs/ROADMAP_v9.md` | ura-planner |
| Current State | `docs/CURRENT_STATE.md` | All agents |
| Quality Context | `quality/QUALITY_CONTEXT.md` | ura-builder, ura-reviewer |
| Dev Checklist | `quality/DEVELOPMENT_CHECKLIST.md` | ura-builder, ura-validator |
| Config Flow Checklist | `quality/CONFIG_FLOW_VALIDATION_CHECKLIST.md` | ura-validator |

---

## 🌿 Branch Strategy

```
main         ← production releases (tagged: v3.3.5.x)
develop      ← integration branch
feature/*    ← new version work (e.g. feature/v3.5.0-camera)
hotfix/*     ← urgent bug fixes
```

```bash
# Start a bug fix
git checkout -b hotfix/v3.3.5.4-music-fix
# ... fix + validate ...
git commit -m "[builder] fix: music transition timing"
git push -u origin hotfix/v3.3.5.4-music-fix

# Start a feature
git checkout -b feature/v3.5.0-camera-intelligence
```

---

## 🚢 Deploy to HACS

### Version Stamping

`scripts/stamp_version.py` keeps version numbers in sync across the codebase. It updates:
- The `VERSION` constant in `const.py`
- Header comments (`# Universal Room Automation vX.X.X.X`) in all `.py` files
- The `version` field in `manifest.json`

```bash
# Set a new version and stamp everywhere
python3 scripts/stamp_version.py 3.3.5.7

# Just re-stamp from whatever VERSION is already in const.py
python3 scripts/stamp_version.py
```

### One-Command Deploy

`scripts/deploy.sh` chains the full release pipeline into a single command:

```bash
./scripts/deploy.sh <version> <commit-summary> <release-notes>
```

What it does (7 steps):
1. Stamps version via `stamp_version.py`
2. Stages changed component files
3. Commits with `v<version>: <summary>`
4. Pushes to `develop`
5. Creates PR `develop → master`
6. Merges the PR
7. Creates a GitHub release `v<version>` with release notes

**Example:**
```bash
./scripts/deploy.sh "3.3.5.7" "Fix zone entity grouping" "- Fixed zone entities not grouping correctly
- Improved entity discovery for grouped zones"
```

**Dry run** (prints steps without executing):
```bash
./scripts/deploy.sh "3.3.5.7" "Fix zone entity grouping" "- Fixed..." --dry-run
```

### Single-Approval Workflow

The intended workflow with Claude:
1. Describe the bug or change needed — Claude investigates and implements the fix
2. Review and approve the code changes
3. Tell Claude: `deploy 3.3.5.7 with summary "Fix zone grouping" and notes "- Fixed zone entities..."`
4. Claude runs `deploy.sh` — everything from commit to release happens automatically

---

## 💰 Token Efficiency — Model Selection by Task

When working in the main Claude CLI session, delegate work to the right model tier:

| Task Type | Model | How |
|-----------|-------|-----|
| Bug investigation, architecture review | Opus | Main session (default) |
| Code edits, feature implementation | Sonnet | `Task` tool with `model: "sonnet"` or `@ura-builder` |
| Deploy mechanics (commit, PR, release) | Haiku | `Task` tool with `model: "haiku"` |
| Validation, testing | Sonnet | `@ura-validator` |

**Why this matters:** Running code edits on Opus costs ~5x more than Sonnet for equivalent quality on implementation tasks. Reserve Opus for reasoning-heavy work (debugging from screenshots, cross-file architecture decisions, review).

---

## ⚡ Quick Reference

| Question | Answer |
|----------|--------|
| Reviewing an existing plan? | `@ura-planner` with Opus 4.6 |
| Implementing from a plan? | `@ura-builder` with Sonnet 4.6 |
| Ingesting from OneDrive? | `@ura-reviewer` first, then `@ura-builder` |
| Before any git commit? | `@ura-validator` |
| Unknown root cause bug? | Ask Claude — it'll escalate to Opus via `ura-reviewer` |

---

## 📌 Legacy Reference (Claude Desktop / Manual Model Switching)

If you're in **Claude Desktop without CLI**, use these manually:

| Task | Model |
|------|-------|
| Plan critique / architecture | Opus 4.6 |
| Bug fix (known pattern) | Sonnet 4.6 |
| Feature implementation | Sonnet 4.6 (Opus for complex) |
| Tests / validation | Sonnet 4.6 |
| Documentation | Sonnet 4.6 |

Rules still apply: always read `quality/QUALITY_CONTEXT.md` before changing code, and `docs/VISION_v7.md` + `docs/ROADMAP_v9.md` before planning sessions.
