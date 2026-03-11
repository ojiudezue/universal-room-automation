---
name: documenter
description: Maintain project documentation and architecture diagrams after feature completion or structural changes. Use when completing features, modifying architecture, changing schemas, adding coordinators, updating config flow, or changing data flow.
---

You are responsible for keeping project documentation in sync with the codebase. This skill has two parts: version tracking (after any feature completion) and doc updates (after structural changes).

---

## Part 1: Version Tracking

Source of truth: **docs/readmes/README_v<version>.md** (one per release cycle)

### After completing a feature

1. Ensure a README exists for the current version in `docs/readmes/`
2. If the change was structural, continue to Part 2

---

## Part 2: Documentation

Living docs live in `/docs`. Use Markdown with **Mermaid diagrams for all diagrams** (flowcharts, sequence diagrams, state diagrams, etc.). Never use ASCII art or image-based diagrams — always use Mermaid. Docs must stay synced with code.

See [references.md](references.md) for the full doc file table (what each file covers, when to update it).

### Update rules

After any structural change — new coordinator, sensor, config flow step, database table, MCP integration, or dependency shift — update **all** affected doc files before considering the work complete.

- Keep entries concise — prefer Mermaid diagrams over long prose
- Never let docs drift from implementation
- When in doubt, update

### Post-change checklist

After a structural change, walk this list and update every affected file:

- [ ] `docs/architecture-overview.md` — System map with Mermaid component diagram
- [ ] `docs/data-flow.md` — Data lifecycle: sensors → coordinators → actions
- [ ] `docs/data-model.md` — Database tables, config entries, persistent state
- [ ] `docs/coordinator-map.md` — All domain coordinators: role, signals, sensors, priority
- [ ] `docs/config-map.md` — Config flow steps, options, env vars
- [ ] `docs/dependency-graph.md` — Internal module dependencies, Mermaid flowcharts

Not every change touches every file. Use judgment — but bias toward updating.
