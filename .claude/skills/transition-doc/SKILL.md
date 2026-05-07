---
name: transition-doc
description: >
  Generate a "transition notes" document that captures the false starts, misconceptions, and corrections
  from the current planning conversation. Designed to be read by the NEXT session before any implementation
  begins, so it doesn't repeat mistakes the current session already made and recovered from. Invoke at the
  end of a planning conversation, before clearing context.
user-invocable: true
---

# Transition Doc Skill

A planning conversation almost always wanders before it converges. Mistakes are made, the user corrects them, the model recovers. By the time the conversation ends, the artifact (a plan, a design doc, a decision) reflects only the final state — the WRONG paths and WHY they were wrong are gone.

When the next session opens that artifact, it has no protection against re-deriving the same mistakes. Worse, some of those mistakes are seductive — they look reasonable on first inspection. Without a record of "we tried this; here's why it doesn't work," future sessions waste the user's time re-walking the same false trails.

This skill writes that record.

## Usage

`/transition-doc [output_path]`

Examples:
- `/transition-doc` — auto-pick a path based on the topic of the conversation
- `/transition-doc docs/planning/PLANNING_v4.5.0_TRANSITION_NOTES.md` — explicit path

## When to invoke

Invoke at the **end of a substantial planning or design conversation**, before clearing context, when:

1. The conversation produced a plan, design doc, decision, or significant code change
2. Mid-conversation, you proposed something and the user redirected ("no, not that," "wrong on this," "what if X?")
3. The final artifact reflects significant pivots from your initial framing
4. The next session will be implementing or extending what was decided

Do NOT invoke when:
- The conversation was a quick lookup, bug fix, or routine task with no design pivots
- Nothing was actually corrected (the conversation went straight to a good answer)
- The artifact already captures the rationale fully (e.g., a code review doc that lists every finding)

## What to capture

A transition doc has five parts. Each is non-optional unless the conversation genuinely doesn't have content for it.

### 1. Mistakes / false starts (in order)

For each significant pivot in the conversation, write a section with this structure:

```markdown
## Mistake N: "<short label of the wrong path>"

**What I proposed:** <one or two sentences describing what was initially suggested>

**Why it was wrong:** <the load-bearing reason — a constraint that was missed, a fact that was wrong, a framing that was off>

**The correction (user direction):** "<exact user quote or close paraphrase, with quote marks>"

**The right approach:** <what was actually adopted>

**Why this matters:** <why a future session is likely to re-make this mistake without this note; what makes it seductive>
```

The "Why this matters" line is what separates a useful transition doc from a diff log. Without it, the next session can read the mistake but not understand why they'd make it themselves.

### 2. Confirmed-good design decisions

A flat numbered list of decisions that were **tested in conversation and approved**. Don't relitigate these. The point is to inoculate the next session against re-opening settled questions.

Each item: one sentence stating the decision. Optionally a parenthetical noting where it lives in the codebase or plan.

### 3. Hot-zone code-review focus areas (only if implementation is the next step)

When the next session will implement what was just designed, list the specific places implementation must be careful — invariants the design relies on, ordering constraints, edge cases that need explicit tests. Pointers to source line numbers when known.

Skip this section if the conversation was pure planning and the next session is more design.

### 4. Reference path through prior planning

Brief breadcrumb of the prior docs / commits / memory entries that contextualize this work. Lets the next session bootstrap its understanding without grepping.

### 5. "What good / bad looks like for next session" checklist

Two short bulleted lists:
- **Should do:** specific actions the next session should take first (read X, then Y, then implement Z)
- **Should NOT do:** the mistakes from section 1, restated as negatives ("Don't re-introduce the saw-tooth charge rate cap")

This is the part the next session will read first. Make it scannable.

## Steps

When invoked:

### Step 1: Identify the topic

Look at the most recent significant artifact created or modified in the conversation:
- A planning doc that was written or heavily revised
- A design decision that was reached
- A code change that resolved a non-trivial issue

This is the "topic" — the transition doc is *about* this artifact.

If the user passed an explicit path argument, skip to Step 2 with that path.

If no path was given:
- For planning docs, default to `<plan_dir>/<plan_name>_TRANSITION_NOTES.md` (e.g., if the plan is `docs/planning/PLANNING_v4.5.0_foo.md`, use `docs/planning/PLANNING_v4.5.0_TRANSITION_NOTES.md`)
- For other topics, default to `docs/planning/TRANSITION_<topic>_<YYYY-MM-DD>.md`
- Confirm the path with the user before writing

### Step 2: Walk the conversation backward

Re-read the conversation history. For every assistant turn, ask:
- Did the user push back on the framing? ("no, that's wrong," "what about X?", "you're missing things")
- Did the user provide a fact or constraint that flipped the design? ("only 1 user," "the schedule actually is...")
- Did the assistant change course significantly between turns? (D4 changed from saw-tooth to mutual-exclusion; lead time changed from 120 to 360)

Each of these is a candidate mistake to capture.

For mistakes you find:
- Quote the user's actual words for the correction. If the wording is uncomfortable in quotes (e.g., includes typos or strong language), you may paraphrase but mark it as paraphrased and stay close to the original.
- The user's words encode the constraint or framing the future session needs. Don't soften them — that loses the signal.

Aim for 5–10 mistakes for a substantial planning conversation. If you have only 1–2, the conversation may not need a transition doc — confirm with the user before writing one.

### Step 3: Identify confirmed-good decisions

Re-read the conversation forward this time. Note decisions that:
- Were proposed and accepted without pushback ("good," "yes," "ok do that")
- Were converged on after debate (the FINAL state, not the wrong path)
- The user explicitly endorsed ("perfect," "I liked the reshuffle")

These belong in section 2 as inoculation against relitigation.

### Step 4: Identify hot-zone implementation risks (if applicable)

If the next session will implement what was designed, scan the design for:
- Invariants the design relies on (state matrix rows, predicate ordering)
- Easy-to-miss edge cases (cross-midnight, cross-month, restart boundaries)
- Pattern compliance (e.g., "this must mirror existing X pattern")

These belong in section 3.

### Step 5: Write the doc

Use the structure under "What to capture" above. Be specific. Quote the user. Cross-link to the authoritative artifact.

After writing, do not commit — leave that to the user's normal flow. The doc should appear in `git status` so the user is aware it was created.

### Step 6: Report

One-line summary: where the doc was written, how many mistakes captured, how many confirmed-good decisions captured. Suggest next-step actions (commit + push, or just commit, or wait).

## Quality bar

A good transition doc passes this test:

> A new model, opening the doc cold with no other context, reads it and can confidently avoid every mistake the previous session already made — and knows what *not* to relitigate.

A bad transition doc summarizes "what changed" without explaining "why a future session would re-make this mistake."

Common failure modes to avoid:

- **Diff-log style.** "We changed X to Y." Doesn't explain why X was tempting in the first place. Future session won't know.
- **Absent quotes.** Without the user's direct words, the framing rationale is lost. Quote them.
- **Soft conclusions.** "We considered both approaches and went with the second." Be direct: "We tried X, it was wrong because of Y, here's the corrected approach."
- **Listing every minor turn.** Only capture mistakes worth a future session's attention. Three good entries beat ten weak ones.

## Notes for the next session

The transition doc's primary reader is **the next session of yourself**. Write to that audience: a competent model with full repo access but zero memory of this conversation. They have the artifact (the plan, the design); they don't have the path that produced it. Your job is to give them just enough of that path to recognize the seductive false starts when they encounter them.

Don't write a memoir. Write a hazard map.
