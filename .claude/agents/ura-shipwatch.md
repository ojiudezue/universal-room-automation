---
name: ura-shipwatch
description: DEPRECATED — moved to global agent. Use `shipwatch` (at ~/.claude/agents/shipwatch.md). Canonical repo lives at ~/Code/shipwatch/. This stub exists for backward-compatibility with old invocations.
model: claude-sonnet-4-6
---

# Moved

Shipwatch has been spun off into a sibling repo as of 2026-06-02.

- **Canonical agent:** `~/.claude/agents/shipwatch.md`
- **Canonical repo:** `~/Code/shipwatch/`
- **Repo-side copy of the agent definition:** `~/Code/shipwatch/agents/watcher.md`

If something invokes `@ura-shipwatch` or `/ura-shipwatch`, switch the
invocation to `@shipwatch` or `/shipwatch`. The behaviour is identical;
the agent now also accepts a `~/.shipwatch/projects.yaml` config so it
can watch more than just URA.
