---
name: ura-kanban
description: >
  The single durable board for bursty, multi-thread URA work. Fights chat→plan conceptual
  entropy with a capture-first protocol: every operator push AND every pre-planning idea the
  model generates becomes a card the SAME turn, before acting. Source of truth is
  docs/planning/KANBAN.md (committed); a live Artifact board reflects it to the operator at
  all times. LOAD THIS SKILL at the start of any working session, whenever the operator pushes
  a new idea/request, whenever the model proposes something mid-turn (a test, a knob, a bug it
  just found), and before writing a planning doc (to harvest cards into the plan). Pairs with
  vibememo — that captures WHY (reasoning-in-motion); this captures WHAT / WHERE / NEXT. They
  compose; neither replaces the other.
user-invocable: true
---

# URA Kanban — capture-first board

CLAUDE.md is canonical policy; this skill is the mechanical protocol for not losing threads
when work happens in bursts with several things in flight. If this skill and CLAUDE.md
disagree, CLAUDE.md wins.

## Why this exists

Chat is linear and lossy. The model compresses as it goes; compaction preserves *decisions*
but strips *texture* — exact phrasings, half-formed asides, and above all the **origin
pointer** (which message an item came from). When a plan is later written from working memory,
anything that scrolled out is reconstructed from the compressed summary, not the source. The
result is conceptual entropy: constraints stated in passing vanish, rejected alternatives
resurface as fresh proposals, verbally-proposed knobs never reach the Numbers-Get-Knobs
ledger, and the model's own mid-turn discoveries (a bug found inside a tool call) are never
promoted because they didn't come from the operator.

Two observed failure modes this system exists to kill:
- **Capture failure** — an operator flag is dropped (e.g. "interior cams in the SecC exterior
  diagnostic — mistake?" fell off for hours).
- **Reconciliation failure** — stale context is carried forward (e.g. nagging the operator to
  "set immune persons" twice after they'd already set it).

## Files

- **Source of truth:** `docs/planning/KANBAN.md` (committed; versioned history *is* the ledger).
- **Live reflection:** an Artifact board the operator keeps open. Redeploy the SAME file path
  to keep the URL stable. URL recorded in the `kanban-capture-first` memory + KANBAN.md header.
- **Discoverability:** a one-line pointer in MEMORY.md so the board is found at session start
  even after compaction.

## The one rule: capture-first

Every operator push AND every pre-planning idea the model generates lands in KANBAN.md as a
card **in the same turn, before acting** — Inbox first, unprocessed. Nothing is allowed to
live only in the transcript. This includes the model's own mid-turn finds (bugs, knobs,
privacy issues surfaced inside a tool call) — those are the most fragile because nothing else
re-raises them.

## Columns

`📥 Inbox` (raw capture) · `🧭 Pre-planning` (idea being decomposed) · `📝 Planned` (has a
plan / acceptance criteria) · `🔨 In progress` · `🔍 Review` · `🚀 Shipped — organic open` ·
`⏸️ Waiting on operator` · `🅿️ Parked` (deliberate, with a revisit-trigger).

## Card schema — the fields ARE the decay vectors

Fill Origin, Why, and Next even when terse. Each field maps to a thing that otherwise leaks:

| Field | Kills this leak |
|---|---|
| **Status / Thread** | which workstream — prevents cross-thread confusion |
| **Origin** (chat date + the originating push) | the origin pointer — so full intent is reconstructable later |
| **Why** | rationale — so a settled decision isn't re-litigated |
| **Constraints** | musts stated in passing ("voice must NOT inherit immunity") |
| **Parked-alts** (+ why) | rejected options resurfacing as fresh proposals |
| **Knobs** | verbally-proposed configurables reaching the Numbers-Get-Knobs ledger |
| **Next** | the single next action — so a card is never inert |
| **Refs** | planning doc / review record / commit / memory |

Card template:

```markdown
### [ID] Title
- **Status:** column · **Thread:** area · **Origin:** <date> "<one-line gist of the push>"
- **Why:** …  · **Constraints:** …  · **Parked-alts:** … (+ why)
- **Knobs:** NAME (rung, one-line why)
- **Next:** single next action · **Refs:** file / commit / doc
```

## Cadence

1. **Session start:** read KANBAN.md (found via MEMORY.md pointer). Reconcile Shipped-organic
   and Waiting-on-operator against live state before reporting status.
2. **On every push / mid-turn idea:** add or update a card the same turn.
3. **Before writing a planning doc:** harvest the relevant cards — Origin/Why/Constraints/
   Parked-alts/Knobs flow straight into the plan's Institutional-context + Acceptance sections.
   This is the anti-entropy handoff.
4. **Turn end:** reconcile — move cards between columns, mark done, and **redeploy the Artifact**
   if anything material changed.
5. **Reconciliation discipline:** when marking Waiting-on-operator or Shipped, verify against
   live state (config entry / sensor / DB) — do not carry a stale TODO forward.

## Relationship to other systems

- **vibememo** = WHY (decision trail, reasoning-in-motion). **This** = WHAT / WHERE / NEXT.
  A card's `Why` is a pointer to the fuller vibememo entry, not a replacement for it.
- **BACKLOG_*.md + memory bodies** hold the broader, non-active backlog. The board's
  "Broader backlog" footer just points at them; it does not duplicate them.
- **CLAUDE.md** governs *how* work is done (tiers, gates). The board governs *what* is in
  flight and *whether it was lost*.

## Anti-patterns

- A card with a title but no Origin/Next — that's a transcript line, not a card.
- Letting a mid-turn discovery stay in the tool output "because I'll remember it."
- Duplicating vibememo's reasoning into the board, or the board's status into vibememo.
- Editing the Artifact without editing KANBAN.md — the committed file is the source of truth;
  the Artifact is a reflection, never the record.
