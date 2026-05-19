---
description: Write a URA planning doc via ura-planner agent. Args = the planning topic / cycle name.
---

Use the `ura-planner` agent to produce a planning document for the topic below.

**Topic / cycle:** $ARGUMENTS

**Required output:** A new file at `docs/planning/PLANNING_v<version>_<topic>.md` with:
- TL;DR
- Origin (what triggered this cycle)
- Tier classification (Tier 1 / Tier 2 / Tier 2-DB) with justification
- Numbered deliverables (D1, D2, ...) each with:
  - Goal
  - Sub-deliverables with file:line refs
  - Acceptance criteria (Test/Verify/Live/Sensor lines per CLAUDE.md mandate)
  - LoC budget
- Out of scope (explicit)
- Risk register
- Review focus areas
- Ship plan

Before writing the plan, read:
- `docs/QUALITY_CONTEXT.md` — bug classes
- `docs/ROADMAP_v11.md` + `docs/VISION_v7.md` — architecture context
- Any prior cycle's planning doc that's relevant
- The source files the cycle will touch

Do NOT propose changes to code you haven't read.
