---
name: vibememo
description: >
  The decision trail capture system for software projects. Persists load-bearing architectural,
  product, and strategic decisions to `.vibememo/` as structured JSON entries and maintains a
  compressed human-readable narrative (`vibememo.md`). Invoke with /vibememo to capture a decision,
  or let it activate automatically when significant decisions are made in conversation. Pairs with
  the vibememo-eval companion skill for periodic quality checks.
user-invocable: true
---

# VibeMemo -- Decision Trail Capture

VibeMemo is the flight data recorder for software development. It captures **why** your codebase is built the way it is -- not just what was built, but the reasoning, tradeoffs, and pivots behind every load-bearing decision.

Architecture can be read from code. The reasoning behind decisions cannot. VibeMemo preserves the reasoning.

## Why This Is a Product Skill

Most decision-logging tools are engineering-only -- they capture stack choices and architecture patterns. VibeMemo captures the full spectrum: product decisions, pricing tradeoffs, UX pivots, security concerns, and strategic bets alongside the technical choices. It treats product judgment as a first-class part of the decision trail, because in practice, the most important decisions are never purely technical.

## When to Activate

Trigger a VibeMemo entry when:

1. **A load-bearing technical decision is made** -- stack choice, data model, architecture pattern, deployment strategy
2. **A previous decision is reversed** -- pivot. These are the most important entries.
3. **A critical security or scalability concern surfaces** -- counseling
4. **A significant milestone is reached** -- first working prototype, first deploy, first user
5. **The user explicitly asks** -- `/vibememo` or "remember this" or "log this"

Do NOT create entries for:
- Routine code changes with no architectural significance
- Minor bug fixes or formatting changes
- Questions that don't result in decisions

## How to Write an Entry

1. **Read the current index**: `.vibememo/users/ojiudezue/index.json` to get the next entry number
2. **Determine entry type and weight**:
   - Types: `decision` | `observation` | `counseling` | `milestone` | `pivot`
   - Weights: `critical` | `significant` | `notable`
3. **Write the entry JSON** to `.vibememo/users/ojiudezue/entries/NNN_short_descriptor.json` following the v2 schema in `.vibememo/FORMAT.md`
4. **Update the user index**
5. **Update narratives**:
   - **User narrative** (`.vibememo/users/ojiudezue/vibememo.md`): Update when a `critical` entry is created or the user's work arc shifts
   - **Project narrative** (`.vibememo/vibememo.md`): Follows **eventual consistency** -- updates only at these checkpoints:
     1. During narrative compaction pass 2 or 3
     2. On commit (triggered by PreToolUse hook)
     3. On session end (triggered by Stop hook)
6. **Include refs**: Link to related entries and affected files

## Entry Quality Standards

- **`why` must be specific.** Not "because it's better." Say what constraint, tradeoff, or evidence drove the decision.
- **`implications` must be forward-looking.** "This means that in 6 months..." or "This constrains future choices because..."
- **`alternatives_considered` must be real.** Include options that were actually discussed, not strawmen.
- **`confidence` must be honest.** If uncertain, say `medium` or `low`. This helps future readers know which decisions are load-bearing vs. provisional.
- **`revisit_trigger` is important.** Under what condition should someone reconsider this?

## Narrative Guidelines

The narrative (`vibememo.md`) is the primary artifact -- what humans read. It should:

- Read like a senior engineer telling a new team member how this project came to be **and why it was built this way**
- Be chronological but compressed -- skip the boring parts
- **Always preserve the "why" behind decisions.** Architecture can be read from code. Reasoning cannot. The "why" is the last thing to compress, ever.
- Include pivots and the reasoning for the reversal, not just the final state
- Target 800-1500 words. Hard ceiling 2000 words. When over ceiling, follow the compress-then-version cycle in FORMAT.md.
- Reference important JSON entries inline: `-> [023](users/ojiudezue/entries/023_database_selection.json)`

### Eventual Consistency for Project Narrative

The project narrative (`.vibememo/vibememo.md`) synthesizes across all users and updates only at consistency checkpoints:

1. **Compaction pass 2+** -- when any user narrative is being compressed
2. **On commit** -- before the commit lands, synthesize all user narratives
3. **On session end** -- ensure the project narrative reflects all work done this session

This means the project narrative may lag behind individual user narratives during active work, but is guaranteed fresh at every commit and session boundary.

## Tone

Direct. Opinionated. Honest about uncertainty. Not corporate. Not filler. If a decision was made under uncertainty, say so. If a previous decision turned out to be wrong, say that too.

## Installation — Required File Structure

VibeMemo must be installed correctly for Claude Code to recognize it as an invocable skill. Follow these steps exactly.

### Step 1: Create the skill directory and file

The skill MUST live at `.claude/skills/vibememo/SKILL.md` — not as a flat file in `.claude/skills/`.

```bash
mkdir -p .claude/skills/vibememo
```

### Step 2: SKILL.md frontmatter — REQUIRED

The file MUST begin with this exact YAML frontmatter block. Without `user-invocable: true`, the `/vibememo` slash command will not register.

```yaml
---
name: vibememo
description: >
  The decision trail capture system for software projects. Persists load-bearing architectural,
  product, and strategic decisions to `.vibememo/` as structured JSON entries and maintains a
  compressed human-readable narrative (`vibememo.md`). Invoke with /vibememo to capture a decision,
  or let it activate automatically when significant decisions are made in conversation.
user-invocable: true
---
```

**Common mistakes that break the skill:**
- Placing the file at `.claude/skills/vibememo.md` instead of `.claude/skills/vibememo/SKILL.md`
- Missing `user-invocable: true` in the frontmatter (skill loads but `/vibememo` command doesn't work)
- Missing the `---` delimiters around the frontmatter block

### Step 3: Create the `.vibememo/` data directory

```bash
mkdir -p .vibememo/users/{username}/entries
```

Replace `{username}` with the git username (e.g., `ojiudezue`).

### Step 4: Copy FORMAT.md

Copy `.vibememo/FORMAT.md` from an existing VibeMemo installation. This is the schema spec that the skill references for entry structure, compaction rules, and narrative guidelines.

### Step 5: Verify

After installation, start a new Claude Code session in the project directory. You should see `vibememo` listed in the available skills. Type `/vibememo` to confirm it invokes.

### Quick install (copy from existing project)

```bash
# From the target project root:
SOURCE="/path/to/project/with/vibememo"

# Skill (Claude Code integration)
mkdir -p .claude/skills/vibememo
cp "$SOURCE/.claude/skills/vibememo/SKILL.md" .claude/skills/vibememo/SKILL.md

# Data directory + format spec
mkdir -p .vibememo/users/$(git config user.name)/entries
cp "$SOURCE/.vibememo/FORMAT.md" .vibememo/FORMAT.md

# Optional: reference docs
cp -r "$SOURCE/.vibememo/references" .vibememo/references/ 2>/dev/null || true

# Optional: settings template
cp "$SOURCE/.vibememo/settings.json" .vibememo/settings.json 2>/dev/null || true
```

## References

- `.vibememo/FORMAT.md` -- Full v2 format specification, entry schema, compaction algorithm
- `.claude/skills/vibememo-eval/SKILL.md` -- Companion evaluation skill with 9-dimension quality scoring
