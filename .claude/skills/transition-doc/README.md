# transition-doc

A Claude Code skill that turns a planning conversation into a hazard map for the next session.

## What it does

Planning conversations wander. You propose something, the user pushes back, you revise, you converge. The final artifact (a plan, a design doc) reflects only the destination — not the false starts, not the seductive-but-wrong paths, not the user's exact words that redirected the design.

When the next session opens the same artifact cold, it has no protection against re-deriving the same mistakes. Some mistakes are seductive enough to be re-derived in the same shape multiple times.

`transition-doc` writes a structured walkthrough of the path from bad to good — the mistakes made, the user's corrections (verbatim), and the load-bearing reasons each correction matters. The next session reads it before touching the artifact and knows where the cliffs are.

## Why this exists

Memory systems (`.vibememo`, Claude Code's auto-memory, CLAUDE.md) capture *durable* lessons across many sessions. They're optimized for cross-cutting principles like "this user prefers terse responses" or "always validate against the live HA instance."

What memory systems are NOT optimized for: the rich, conversation-specific narrative of "we considered approach A, then B, finally landed on C — here's why A and B don't work even though they look reasonable." That story is too narrow for global memory but too important to lose between sessions on the same project.

`transition-doc` fills that gap. It produces a single doc, scoped to one planning cycle, that lives next to the plan it accompanies.

## Usage

Invoke at the end of a substantial planning or design conversation, before clearing context:

```
/transition-doc
```

Or with an explicit output path:

```
/transition-doc docs/planning/PLANNING_v4.5.0_TRANSITION_NOTES.md
```

The skill walks the conversation, identifies the pivots, quotes the user's corrections, and writes a structured markdown file. It does not commit — that's left to your normal review flow.

## When to use

**Good triggers:**
- A planning conversation that produced or significantly revised a design doc
- The user redirected the framing more than once during the conversation
- The next session will implement or extend the work just designed
- You're about to clear context

**Bad triggers:**
- A quick lookup or bug fix
- A conversation that went straight to a good answer with no pivots
- A code review that already documents every finding

## What gets captured

The output doc has five sections:

1. **Mistakes / false starts (in order)** — each with: what was proposed, why it was wrong, the user's correction (quoted), the right approach, and why a future session is likely to re-make the mistake without this note.
2. **Confirmed-good design decisions** — settled questions that the next session should NOT relitigate.
3. **Hot-zone code-review focus areas** — if implementation is the next step, the specific invariants and edge cases the implementation must respect.
4. **Reference path through prior planning** — breadcrumb of related docs / commits / memory entries.
5. **What good / bad looks like for next session** — two short checklists, scannable, the part the next session reads first.

## Quality bar

A good transition doc passes this test:

> A new model, opening the doc cold with no other context, reads it and can confidently avoid every mistake the previous session already made — and knows what *not* to relitigate.

A bad transition doc summarizes "what changed" without explaining "why a future session would re-make this mistake."

## Pairs well with

- **Memory systems** (`.vibememo`, auto-memory) — capture durable lessons; transition-doc captures session-scoped narrative.
- **Planning docs** — the transition doc lives next to the plan it accompanies and references it.
- **Structured review protocols** — the doc complements code-review reports by explaining the *design path*, not just the final state.

## Installation

Drop `SKILL.md` (and optionally this `README.md`) into your project's `.claude/skills/transition-doc/` directory:

```
your-project/
├── .claude/
│   └── skills/
│       └── transition-doc/
│           ├── SKILL.md
│           └── README.md
```

The skill becomes user-invocable as `/transition-doc` once the directory is created. No other configuration needed.

## Example output

See `docs/planning/PLANNING_v4.5.0_TRANSITION_NOTES.md` in the URA repo (the project where this skill was originally developed) for a real-world transition doc that captures 9 false starts from a multi-turn battery-strategy redesign conversation.

## License

MIT — use freely, modify freely. If you find it useful, a credit-back is appreciated but not required.

## Origin

Originally developed for the [Universal Room Automation](https://github.com/ojiudezue/universal-room-automation) project (a Home Assistant custom integration), where multi-hour planning conversations regularly produced complex design docs. The need for transition notes became obvious after several sessions where productive conversations were followed by next-session repeat-mistakes that wasted everyone's time.

The pattern is general — any sufficiently complex planning conversation benefits from a hazard map for the next session.
