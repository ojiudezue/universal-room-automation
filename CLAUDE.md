# URA Project Instructions

## Release Process — MANDATORY
- **Always use `./scripts/deploy.sh <version> <summary> <release-notes>`** for releases
- Create `docs/readmes/README_v<version>.md` BEFORE deploying
- Pre-stage new directories with `git add` before running deploy.sh
- Do NOT manually commit, push, or create PRs for releases

## Before Making Changes
- Read `quality/QUALITY_CONTEXT.md` for known bug classes
- Read `quality/DEVELOPMENT_CHECKLIST.md` for review checklist
- Read the relevant source files before proposing changes

## Testing
```bash
PYTHONPATH=quality python3 -m pytest quality/tests/ -v
```

## Key Architecture
- Home Assistant custom integration at `custom_components/universal_room_automation/`
- Domain coordinators: `domain_coordinators/` (safety, presence, base, house_state, signals, diagnostics)
- Branch strategy: main (production), develop (integration)
- Config entries: ENTRY_TYPE_ROOM, ENTRY_TYPE_ZONE_MANAGER, ENTRY_TYPE_COORDINATOR_MANAGER

## Don't Ask — Read First
- `WORKFLOW_GUIDE.md` — dev workflow
- `docs/PLANNING_v3.6.0_REVISED.md` — current milestone state
- `docs/VISION_v7.md` + `docs/ROADMAP_v9.md` — architecture context
