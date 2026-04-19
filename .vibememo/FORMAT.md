# VibeMemo Format v2

> An open format for capturing the decision trail of software projects.

## Overview

VibeMemo captures the inner story of how and why code was built — decisions, alternatives considered, implications, counseling moments, and pivots. It's the flight data recorder for software development.

The format is **open and free to implement.** Any tool can write `.vibememo` data. The value is in the tooling that reads, synthesizes, and counsels — not in the format itself.

## Design Principles

1. **vibememo.md is the artifact.** It's what humans read. It's what the read-side product ingests. Everything else is backing data.
2. **"Why" is the core value.** Architecture can be read from code. The reasoning behind decisions cannot. Every entry must capture *why* a decision was made. The "why" is the last thing compressed and the first thing preserved. If a narrative loses "why," it has failed.
3. **Per-user, checked in, visible to all.** Each developer owns their namespace. Pull to see everyone's trail.
4. **JSON is continuous. Narrative is periodic.** JSON entries capture decisions as they happen. Narratives are synthesized on commit (or on a loop) — not on every entry.
5. **High bar, not low.** Only load-bearing decisions get entries. The narrative bar is even higher — it stays concise across any timescale.
6. **Travel with the code.** `.vibememo/` is committed to the repo. Clone the repo, get the decision trail.

## File Structure

```
.vibememo/
├── FORMAT.md                              # This spec
├── settings.json                          # Project-level VibeMemo settings
├── vibememo.md                            # Project narrative (synthesized from all users)
├── vibememo_v1.md                         # Archived narrative (when current exceeds threshold)
│
├── references/                            # Supporting specification documents
│   ├── DETECTION.md                       # Decision point detection taxonomy
│   ├── COUNSELING_ARC.md                  # Five-step counseling response templates
│   ├── INTEROP.md                         # Cross-tool coordination protocol
│   └── NARRATIVE_PROMPT.md                # Default narrative synthesis prompt
│
├── users/                                 # All per-user namespaces
│   ├── {username}/                        # Per-user namespace (git username)
│   │   ├── vibememo.md                    # This user's narrative of their work
│   │   ├── entries/                       # This user's decision entries
│   │   │   ├── 001_short_descriptor.json
│   │   │   ├── 002_short_descriptor.json
│   │   │   └── ...
│   │   └── index.json                     # This user's entry index
│   │
│   └── {username2}/                       # Another developer
│       ├── vibememo.md
│       ├── entries/
│       └── index.json
│
├── .vibememorc                            # Local-only user identity (gitignored)
├── .session                               # Current session state (gitignored)
├── .lock                                  # Write lock (gitignored)
├── .events                                # Cross-tool event log (gitignored)
└── .gitignore                             # Ignores local-only files
```

### Key design choices

**Per-user folders:** Eliminates merge conflicts on JSON entries. Each developer's trail is independent. When you pull, you pull everyone's decision history. A new developer reads across all users' vibememo.md files — or reads the synthesized root `vibememo.md`.

**Root vibememo.md:** The project-level narrative, synthesized from all per-user narratives. This is what a new developer reads first. Generated automatically on commit (or manually via tooling). In the skill version (Claude Code), this is manually maintained. In the extension version, it's auto-generated.

**Versioned narratives:** When a vibememo.md exceeds the compaction threshold (see Compaction), the current version is archived as `vibememo_v{N}.md` and a new current narrative begins. Old versions are preserved — the decision trail is never deleted, only compressed.

## Entry Schema (v2)

```json
{
  "format_version": "2.0",
  "entry_id": "NNN",
  "author": "git username",
  "session_id": "string — groups entries from one working session",
  "timestamp": "ISO 8601",
  "type": "decision | observation | counseling | milestone | pivot",
  "weight": "critical | significant | notable",

  "title": "One-line summary",
  "summary": "2-3 sentence plain-English description",

  "decisions": [
    {
      "id": "entry_id.N",
      "category": "architecture | stack | brand | product | security | deployment | data_model | ux | pricing | process",
      "decision": "What was decided",
      "alternatives_considered": ["Alternative 1", "Alternative 2"],
      "why": "Why this choice was made — specific constraint, evidence, or tradeoff",
      "implications": "What this means going forward — the 3/6/12 month view",
      "confidence": "high | medium-high | medium | low",
      "revisit_trigger": "Condition under which this should be reconsidered",
      "supersedes": "entry_id of decision this replaces, if any"
    }
  ],

  "counseling": [
    {
      "id": "entry_id.c.N",
      "trigger": "what pattern/action triggered counseling",
      "trigger_type": "pattern_match | dependency_add | config_change | security_flag | architecture_shift | manual",
      "category": "security | architecture | scalability | cost | consistency | data_model | deployment",
      "severity": "high | medium | low",
      "exchange": {
        "detection": "What was detected (1 sentence)",
        "explanation": "Why this matters (1-2 sentences, plain English)",
        "implications": {
          "3_month": "Near-term consequence",
          "6_month": "Medium-term consequence",
          "12_month": "Long-term consequence"
        },
        "second_order_effects": ["Non-obvious downstream effect 1", "Effect 2"],
        "alternatives": [
          {
            "option": "Alternative approach",
            "tradeoff": "What you gain vs lose",
            "effort": "trivial | moderate | significant"
          }
        ]
      },
      "resolution": {
        "verb": "string — flexible, not a frozen enum. See Resolution Verbs below.",
        "verb_data": "object — verb-specific payload (e.g., alternative index, reminder date)",
        "reasoning": "Why the user made this choice (optional, captured when provided)",
        "confidence": "high | medium | low",
        "resolved_at": "ISO 8601 — when the resolution was recorded (null if unresolved)"
      }
    }
  ],

  "refs": {
    "what_prompted_this": "The trigger for this entry",
    "tools_in_use": ["claude_code", "cursor", "aider", "terminal"],
    "files_affected": ["path/to/file"],
    "related_entries": ["NNN"],
    "commits": ["sha — if associated with a specific commit"]
  },

  "meta": {
    "session_duration_minutes": 0,
    "ai_suggestions_accepted": 0,
    "ai_suggestions_modified": 0,
    "ai_suggestions_rejected": 0,
    "security_flags_raised": 0,
    "consistency_flags_raised": 0
  }
}
```

### New in v2

- **`author`**: Git username. Required. Maps to per-user folder.
- **`weight`**: Replaces implicit "bar" with explicit classification. Determines compaction behavior.
  - `critical` — Pivots, security issues, architectural constraints. Survives all compaction.
  - `significant` — Load-bearing decisions. Survives first compaction, summarized in second.
  - `notable` — Observations, minor tradeoffs. First to be compacted.
- **`supersedes`**: Links a decision to the one it replaces. Creates a revision chain for pivots.
- **`refs.commits`**: Links entries to git commits for cross-referencing.

### New in v2.1

- **Structured counseling exchange.** The `counseling` array now captures the full five-step counseling arc: detection, explanation, implications (3/6/12 month), second-order effects, and alternatives with tradeoffs. See [COUNSELING_ARC.md](references/COUNSELING_ARC.md).
- **`trigger_type`** on counseling entries. Classifies how the decision point was detected (pattern match, dependency add, config change, etc.). See [DETECTION.md](references/DETECTION.md).
- **`session_id` generation spec.** Standardized format for session identifiers.
- **Cross-project identity.** Optional `.vibememorc` for stable identity across repos.
- **Interop protocol.** File-based coordination for multiple tools. See [INTEROP.md](references/INTEROP.md).
- **Narrative synthesis prompt.** Default LLM prompt for narrative generation. See [NARRATIVE_PROMPT.md](references/NARRATIVE_PROMPT.md).

## Session ID

Session IDs group entries from one working session. They must follow this format:

```
{tool}_{YYYYMMDD}_{HHmmss}_{4-char-random-hex}
```

**Tool prefixes:**

| Prefix | Tool |
|--------|------|
| `claude` | Claude Code (CLI) |
| `cursor` | Cursor |
| `aider` | Aider |
| `vscode` | VS Code extension |
| `chrome` | Chrome extension |
| `web` | Web builder (Lovable, v0, etc.) |
| `manual` | Manual entry (user typed `/vibememo`) |

**Example:** `claude_20260415_143022_a7f2`

**Rules:**
- Generated once at session start, reused for all entries in that session
- Stored in `.vibememo/.session` (gitignored) for tools to read
- If no session file exists, the tool creating the first entry generates a new session ID
- See [INTEROP.md](references/INTEROP.md) for session ownership rules

## Cross-Project Identity

The `author` field uses the git username, which may vary across repos. For stable identity across projects (needed for Wrapped and cross-project analytics), use `.vibememorc`.

### User-level identity: `~/.vibememorc`

Stored in the user's home directory. Not project-specific. Not checked in.

```json
{
  "canonical_id": "ojiudezue",
  "display_name": "Oji Udezue",
  "aliases": ["ojiudezue", "oji-work", "oji@company.com"]
}
```

### Project-level identity: `.vibememo/.vibememorc`

Stored in the project's `.vibememo/` directory. Gitignored. Overrides the user-level file for this project.

```json
{
  "canonical_id": "ojiudezue",
  "display_name": "Oji Udezue"
}
```

**Resolution order:** Project `.vibememorc` > User `~/.vibememorc` > git config `user.name`

**Rules:**
- `canonical_id` is the stable identifier used for cross-project linking
- `aliases` lists all git usernames this person uses (for matching across repos)
- Tools should write `author` as the git username (for filesystem compatibility) but include `canonical_id` in the entry's `meta` block if available

## Entry Types

| Type | When | Weight guidance |
|------|------|----------------|
| `decision` | Architectural, technical, product, or strategic choice made | `significant` or `critical` |
| `observation` | Notable insight, risk, or pattern noticed — no action yet | `notable` |
| `counseling` | VibeMemo flagged a security, consistency, or implications issue | `significant` or `critical` |
| `milestone` | Significant deliverable completed | `significant` |
| `pivot` | Previous decision reversed or significantly changed | Always `critical` |

## Resolution Verbs

Counseling resolutions use a flexible verb system. Verbs are strings, not a frozen enum — tools can define new verbs as capabilities grow. The schema validates the structure, not the verb value.

### Standard Verbs

| Verb | Meaning | `verb_data` payload | Status |
|------|---------|-------------------|--------|
| `accepted` | User proceeded as-is after reading counseling | `{}` | Defined |
| `overridden` | User went against advice | `{ "reasoning": "why" }` | Defined |
| `deferred` | User will revisit later | `{ "remind_at": "ISO 8601", "remind_context": "string" }` | Defined |
| `alternative_chosen` | User picked a suggested alternative | `{ "alternative_index": 0 }` | Defined |
| `remind_me` | Surface this decision again at a future date | `{ "remind_at": "ISO 8601" }` | Future |
| `fix_now` | Tool implements the recommended alternative | `{ "alternative_index": 0, "auto_applied": true }` | Future |
| `explain_more` | User requested deeper analysis | `{ "depth": "codebase_aware" }` | Future |
| `dismissed` | User dismissed without reading | `{}` | Defined |
| `escalated` | Flagged for team review | `{ "escalated_to": "team_channel_or_person" }` | Future |

### Custom Verbs

Tools can define custom verbs. Convention: prefix with the tool name to avoid collisions.

```json
{
  "verb": "vscode_quick_fix",
  "verb_data": { "fix_applied": "moved_to_env_var", "file": ".env" }
}
```

### Resolution is Optional

In MVP, counseling entries may have `resolution: null`. The counseling was delivered; the user's response was not explicitly captured. This is the default — recording a resolution requires the user to take an action beyond reading the counseling.

Tools should NOT prompt for resolution. If the user wants to record their decision, they use `/vibememo` or the tool's equivalent.

## Verbosity Settings

Projects can configure capture verbosity in `settings.json`:

```json
{
  "verbosity": "standard",
  "narrative_max_words": 2000,
  "narrative_version_threshold": 1500,
  "auto_narrative_on_commit": true,
  "auto_narrative_loop_minutes": null
}
```

| Level | What gets captured | When to use |
|-------|-------------------|-------------|
| `critical` | Only pivots, security flags, and architectural constraints | Mature/stable projects with low decision velocity |
| `standard` | Above + significant feature decisions, integration choices, notable tradeoffs | Default. Most projects. |
| `verbose` | Above + minor decisions, session observations, alternative explorations | Early-stage projects, spikes, R&D, or when deliberately building a rich trail |

Verbosity controls **entry creation frequency**, not narrative quality. Even at `verbose`, the narrative stays concise — it just has more raw material to draw from.

## vibememo.md — The Narrative

### What it is

The compressed, human-readable story of the project's decision history. This is the primary artifact. When a new developer clones the repo, this is the first thing they read.

### Content Length Guidelines

| Guideline | Value | Notes |
|-----------|-------|-------|
| **Target length** | 800-1500 words | Long enough to tell the story, short enough to read in 5 minutes |
| **Hard ceiling** | 2000 words | Compaction triggers when exceeded |
| **Version threshold** | 1500 words after compaction | If compaction can't get below this without destructive loss, archive and start fresh |
| **Minimum useful** | 200 words | Below this, the narrative isn't telling enough of the story |

### The Compress-Then-Version Cycle

When the narrative grows beyond the hard ceiling, it enters a compression cycle:

```
1. COMPRESS PASS 1: Drop `notable` entries, summarize `significant` to 1-2 sentences
   (decision + why + key implication).
   → If under 1500 words: done, continue in this file.

2. COMPRESS PASS 2: Summarize `significant` to 1 sentence (decision + why).
   Drop implications, drop alternatives. The "why" survives this pass.
   → If under 1500 words: done, continue in this file.

3. COMPRESS PASS 3: Reduce `critical` entries to 2-3 sentences. Keep pivots and their
   reasoning fuller. The "why" behind any decision is the LAST thing to compress.
   → If under 1500 words: done, continue in this file.

4. DESTRUCTIVE LOSSINESS DETECTED: Further compression would lose "why" context
   that cannot be recovered from code alone.
   → Archive current file as vibememo_v{N}.md
   → Start fresh vibememo.md with a "Previously..." header linking to archived version
   → New file carries forward ONLY: current architecture state + why it's that way,
     open questions, and critical decisions still actively relevant with their reasoning
```

The key principle: **compress for a few cycles before versioning.** Each pass is less lossy than starting fresh. Only version when additional summarization would destroy information a future developer needs. The JSON entries are always the source of truth — the narrative is a lossy view, but it should never be *misleadingly* lossy.

### Structure

```markdown
# Project Name — VibeMemo

*Last updated: YYYY-MM-DD | Version N | Contributors: user1, user2*

## How This Started
[Origin story — why the project exists, initial constraints]

## Key Decisions
[Chronological but compressed — the decisions that shaped the project]
[Each major decision references its JSON entry: → [023](ojiudezue/entries/023_database_selection.json)]

## Pivots
[Decisions that were reversed and why — these are the most valuable entries]

## Current Architecture
[The state of the codebase NOW, as a result of all decisions above]

## Open Questions
[Decisions still pending or under active debate]
```

### References / hyperlinks

The narrative MUST reference the most important JSON entries inline using relative paths:

```markdown
We chose Postgres over MongoDB after evaluating both for 2 weeks.
→ [023](ojiudezue/entries/023_database_selection.json)
The key factor was relational query needs for the billing module.
```

This serves two purposes:
1. **Drill-down.** A reader who wants the full context (alternatives, implications, confidence) can follow the link.
2. **Reconstruction.** If the narrative is ever corrupted or needs regeneration, the references identify the most load-bearing entries to reconstruct from.

### Per-user vs project narrative

- **Per-user** (`{username}/vibememo.md`): Each developer's story of their work. Written by the developer's VibeMemo instance. Authoritative for what that person decided and why.
- **Project-level** (root `vibememo.md`): Synthesized from all per-user narratives. Written by tooling (extension auto-generates, or the skill maintains manually). This is the "single pane of glass" for a new developer.

## Compaction Strategy

Compaction is how narratives stay concise as projects grow. The strategy must be semi-deterministic so we can write evals for quality.

### Compaction triggers

1. **Word count threshold.** When a vibememo.md exceeds `narrative_max_words` (default 2000), compaction runs.
2. **Time-based.** Optionally, compaction runs on a schedule (weekly, monthly) to maintain consistent granularity.
3. **Version boundary.** When compaction produces a narrative that's still too long after one pass, the current version is archived and a new one starts.

### Compaction rules (deterministic)

These rules determine what survives compaction and in what form:

| Entry weight | First compaction | Second compaction | Archival |
|-------------|-----------------|-------------------|----------|
| `critical` | **Full detail preserved.** Pivots, security decisions, and architectural constraints are never summarized. The "why" is always kept. | Full detail preserved. | Full detail preserved. |
| `significant` | **Summarized to 1-2 sentences.** Decision + why + key implication. Alternatives dropped. | **Summarized to 1 sentence. Decision + why.** Implications dropped, but the reasoning is NEVER dropped — "why" is the last thing to compress. | Referenced by link only, but link text includes the "why" in parentheses. |
| `notable` | **Removed from narrative.** Only survives in JSON entries. | Removed. | Removed. |

### Compaction algorithm

```
1. Measure current word count against hard ceiling (2000 words)
2. If under ceiling: no action needed
3. If over ceiling, enter compression cycle:
   a. PASS 1: Remove sections referencing only `notable` entries.
      Summarize `significant` entries to 1-2 sentences (decision + why + implication).
      → Check: under 1500 words? Stop.
   b. PASS 2: Summarize `significant` entries to 1 sentence (decision + why).
      Drop implications, drop alternatives. The "why" is NEVER dropped before versioning.
      → Check: under 1500 words? Stop.
   c. PASS 3: Reduce `critical` entries to 2-3 sentences. Preserve pivots and their
      reasoning more fully. The "why" behind critical decisions survives all compression.
      → Check: under 1500 words? Stop.
   d. PASS 4 (versioning): Further compression would lose "why" context.
      Archive as vibememo_v{N}.md. Start fresh with:
      - "Previously..." header linking to archived version(s)
      - Current architecture state AND why it's that way
      - Open questions
      - Critical decisions still actively load-bearing, with their reasoning
4. After any pass, verify all entry hyperlinks still resolve
```

**The eval test for destructive lossiness:** If removing another sentence would cause a new developer to either (a) make a wrong assumption about the codebase architecture, or (b) not understand *why* a decision was made and accidentally reverse it, that's the line. Architecture can be inferred from code. The "why" cannot. Preserve "why" above all else. Compress up to that line. Version beyond it.

### Versioning

When a narrative is archived:

```
.vibememo/
├── vibememo.md              # Current (v3, covering months 7-9)
├── vibememo_v1.md           # Archived (months 1-3)
├── vibememo_v2.md           # Archived (months 3-7)
```

Each archived version is immutable. The current `vibememo.md` opens with:

```markdown
*Previously: [v1](vibememo_v1.md) covers project inception through MVP launch.
[v2](vibememo_v2.md) covers beta period through first enterprise customer.*
```

### Eval criteria for compaction quality

A compacted narrative is good if:

1. **A new developer reading only the current vibememo.md can understand:**
   - What the project does and why it exists
   - The current architecture and key technology choices
   - **Why those choices were made** — the reasoning, constraints, and tradeoffs behind each decision
   - Which decisions are load-bearing (critical) vs. provisional
   - What decisions were reversed, **why they were reversed**, and what replaced them (pivots)
   - Where the open questions are

2. **No critical decision's "why" is missing or misrepresented.** The architecture can be read from code. The reasoning cannot. If a compacted narrative says "We use Postgres" but not *why* Postgres over the alternatives, the compaction failed.

3. **Drill-down works.** Every major claim in the narrative has a JSON reference. A reader can verify or get full context.

4. **The archived versions form a coherent chain.** Reading v1 → v2 → current tells the full story without gaps.

5. **Word count stays within threshold.** A 6-month project's current narrative is ≤2000 words. A 2-year project has 3-4 archived versions and a current narrative of ≤2000 words.

## Settings

### Project settings (`settings.json`, checked in)

```json
{
  "format_version": "2.1",
  "project_name": "CodeEli5",
  "verbosity": "standard",
  "narrative_target_words": 1200,
  "narrative_hard_ceiling": 2000,
  "narrative_version_threshold": 1500,
  "narrative_min_useful": 200,
  "auto_narrative_on_commit": true,
  "auto_narrative_loop_minutes": null,
  "narrative_generation": "llm",
  "heuristic_fallback": true,
  "categories": [
    "architecture", "stack", "brand", "product",
    "security", "deployment", "data_model", "ux",
    "pricing", "process"
  ],
  "counseling": {
    "tier": "guide",
    "auto_detect": true,
    "detection_sensitivity": "standard",
    "security_always_free": true
  }
}
```

### Local settings (`.vibememorc`, gitignored)

```json
{
  "canonical_id": "ojiudezue",
  "display_name": "Oji Udezue",
  "aliases": ["ojiudezue"],
  "preferred_verbosity_override": null,
  "narrative_generation": "llm",
  "llm_provider": "anthropic",
  "auto_commit_entries": false
}
```

`narrative_generation` options:
- `"llm"` — **Default for paid.** Use LLM to synthesize narrative. Periodic in-session generation + fast hook at check-in. Higher quality. Costs tokens. It is acceptable to delay check-in for this, just like other pre-commit hooks. See [NARRATIVE_PROMPT.md](references/NARRATIVE_PROMPT.md) for the default prompt.
- `"heuristic"` — **Fallback.** Local rule-based compaction. Used when LLM is unavailable (local models, API failures, offline). Free, fast, lower quality.
- `"manual"` — Narrative is written/updated by the developer directly (skill mode, early prototyping).

`counseling` settings:
- `tier` — `"record"` (free: detection + explanation + security flags) or `"guide"` (paid: full five-step arc with implications, second-order effects, and alternatives). See [COUNSELING_ARC.md](references/COUNSELING_ARC.md).
- `auto_detect` — Whether to automatically detect decision points. See [DETECTION.md](references/DETECTION.md).
- `detection_sensitivity` — `"low"` (critical + high only), `"standard"` (default), `"high"` (all categories).
- `security_always_free` — Security issues (severity: critical) are always counseled, even in Record tier.

**Generation strategy:** LLM-first, always. Periodic narrative construction during active sessions (on a loop or at natural breakpoints). Mandatory narrative update at check-in as a pre-commit hook — the commit waits for this, same as linting or tests. Heuristic compaction is the fallback, not the default.

## Eventual Consistency

The project narrative (root `vibememo.md`) follows an eventual consistency model. Individual user narratives update on every critical entry, but the project narrative only updates at consistency checkpoints:

| Checkpoint | What updates | Trigger |
|-----------|-------------|---------|
| Entry creation | User narrative (if critical/arc shift) | `/vibememo` or auto-detect |
| Compaction pass 2+ | User narrative + project narrative | Narrative exceeds word ceiling |
| Commit | User narrative + project narrative | PreToolUse hook on `git commit` |
| Session end | User narrative + project narrative | Stop hook |
| Loop (30m) | User narrative only (if new entries) | Cron/loop scheduler |

This means the project narrative may lag during active work but is guaranteed fresh at every commit and session boundary — the points where other developers will actually see the changes.

See [INTEROP.md](references/INTEROP.md) for how multiple tools coordinate narrative updates.

## Open Format Philosophy

The `.vibememo` format is open and free to implement. Any tool — IDE extensions, CLI tools, CI pipelines, AI coding assistants — can read and write `.vibememo` data.

**What's open:** The format spec, the file structure, the entry schema, the compaction algorithm.

**What's product (not in the spec):** Counseling intelligence (Guide), narrative synthesis quality (LLM prompts and knowledge base), codebase comprehension analysis (CodeStory), Wrapped content generation.

The format is the protocol. The products are the implementations. More tools writing `.vibememo` data means more repos with decision trails means more demand for the read side.

## References

- [DETECTION.md](references/DETECTION.md) — Decision point detection taxonomy with patterns and severity levels
- [COUNSELING_ARC.md](references/COUNSELING_ARC.md) — Five-step counseling response format (Detection, Explanation, Implications, Second-order, Alternatives)
- [INTEROP.md](references/INTEROP.md) — Cross-tool coordination protocol (locking, session ownership, deduplication)
- [NARRATIVE_PROMPT.md](references/NARRATIVE_PROMPT.md) — Default LLM prompt for narrative synthesis, updates, and compaction
