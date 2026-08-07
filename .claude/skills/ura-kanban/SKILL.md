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

- **Source of truth (DATA):** `docs/planning/kanban.data.yaml` — structured cards. Edit HERE.
  Must stay valid YAML (`python3 -c "import yaml;yaml.safe_load(open(...))"` before commit).
- **Generated views (KHOST-1):** `docs/planning/KANBAN.md` (human view), the Artifact, and
  `urakanban.phalanxmadrone.com` are all *generated* from the data — never hand-edit a view.
  Until the generator ships, KANBAN.md is maintained alongside the data as an interim view.
- **History:** done cards age out of the data into `docs/planning/kanban.history.yaml`.
- **Live reflection:** the Artifact board (redeploy the SAME file path to keep the URL stable;
  URL in the data `meta.artifact_url` + the `kanban-capture-first` memory).
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
`⏸️ Waiting on operator` · `⏳ Waiting on me (Claude)` · `🅿️ Parked` (deliberate, with a
revisit-trigger).

**Two waiting lanes, symmetric.** Track obligations on *both* sides. "Waiting on operator" =
decisions/actions only the operator can take (physical fixes, go/no-go, design choices).
"Waiting on me (Claude)" = things I owe (a promised re-measurement, a verification, a sweep).
Do not file my own debt under the operator's lane — that hides it and reads as if the ball is
in their court when it is in mine.

## Architecture — data vs representation (KHOST-1 target)

The board is **data**, not prose. The source of truth is a structured file; every view — the
committed markdown, the Artifact, the homelab page — is **generated** from it, so no view can
drift from the data (editing a rendered view is the drift anti-pattern). **Done cards age out**
to a history file rather than bloating the active board — this reuses the existing doctrine that
the git history of shipped-work docs (READMEs / validation ledgers) is the durable record.
Until the KHOST-1 generator ships, `docs/planning/KANBAN.md` serves as both data and view; when
it ships, the markdown becomes a generated artifact like the others and the history file holds
aged-out cards.

## Card schema — the fields ARE the decay vectors

Fill Origin, Why, and Next even when terse. Each field maps to a thing that otherwise leaks:

| Field | Kills this leak |
|---|---|
| **Status / Thread** | which workstream — prevents cross-thread confusion |
| **Origin** (chat date + the originating push) | the origin pointer — so full intent is reconstructable later |
| **Why** | rationale — so a settled decision isn't re-litigated |
| **Constraints** | musts stated in passing ("voice must NOT inherit immunity") |
| **Parked-alts** (+ why) | rejected options resurfacing as fresh proposals |
| **Refinement** (challenge → sharpened form) | the *dialectic* that improved the surviving idea — see below |
| **Knobs** | verbally-proposed configurables reaching the Numbers-Get-Knobs ledger |
| **Next** | the single next action — so a card is never inert |
| **Refs** | planning doc / review record / commit / memory |

### The Refinement trail (append-only)

A card records its *final* shape but loses how it got there. The operator challenges ideas and
the design sharpens through that push-back — and that trail is load-bearing: it is what stops a
later session **backsliding to the naive version** ("just mirror the automation," "test the
alert"). Capture it as an append-only list of `challenge → sharpened form` beats, newest last.

Distinct from Parked-alts: Parked-alts are options we *rejected*; Refinement is the sequence of
challenges that *improved the option we kept*. It is card-level WHY — the compact shape of the
pivot — and points at the fuller **vibememo** entry for the depth. Board shows the shape;
vibememo holds the reasoning.

**Hook-based capture (not remembered).** Like update hygiene, refinement is bound to an event,
not to noticing. The trigger fires whenever an idea *already on the board* is challenged or
sharpened. Detection signals:

- Operator **pushes back / redirects / corrects**: "why not X", "I'm more interested in Y",
  "that's not it", "mirror AND improve", a reframe of the goal, or a correction of one of my
  claims ("we already have X — find it").
- Operator **adds a constraint or a new angle** to a carded idea ("does it clean up?", "which
  one when there are multiple?").
- **I self-correct**: I asserted X, then evidence or the operator showed Y.

On any of these: append one `challenge → sharpened form` line to that card's Refinement trail
**the same turn, before acting on the new direction** — the append comes first, then the work.
This is the same discipline as capture-first, scoped to the dialectic. A challenge that changes
the design but leaves no trail line is a hygiene miss, logged like any other.

Card template:

```markdown
### [ID] Title
- **Status:** column · **Thread:** area · **Origin:** <date> "<one-line gist of the push>"
- **Why:** …  · **Constraints:** …  · **Parked-alts:** … (+ why)
- **Refinement:**
  - <challenge> → <how the idea sharpened>
  - <next challenge> → <next sharpening>
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

## Update hygiene — anti-drift (why vibememo lags, and how this must not)

The vibememo failure pattern is a **clock-based cadence** ("catch up every ~30 min"): it
relies on *remembering* to do a separate chore, so under bursty load it drifts, and a lagging
capture system produces an inadequate backlog. This board must not inherit that. The fix is a
principle, not more willpower:

> **Bind the update to the work, not to the clock.** Every board update is a side-effect of a
> checkpoint that *already has to happen* — never a standalone task to remember.

### Event hooks (each is an existing mandatory checkpoint the update rides on)

| Trigger (always happens) | Board action (same turn) |
|---|---|
| Operator sends a message | Capture card(s) + reconcile touched cards BEFORE substantive work — part of reading the message |
| A tool result reveals a bug / knob / constraint | Card it before continuing — mid-turn finds are the most fragile |
| Operator challenges / redirects / corrects a carded idea (or I self-correct) | Append a Refinement beat (`challenge → sharpened form`) to that card the same turn, before acting on the new direction |
| About to write a planning doc | Harvest the relevant cards into the plan (the anti-entropy handoff) |
| Pre-Deploy Zero-Bugs Gate / README write-back / commit | Reconcile In-progress → Review → Shipped as part of that ritual |
| Turn end (same self-check as "check your last paragraph") | Move cards, write dispositions, **redeploy the Artifact if anything changed** |
| Session start | Read board; if stale (below), reconcile before reporting status |

### Enforcement — make drift visible, not silent

1. **Turn-end gate (hard, not aspirational).** A turn that changed work state does not end until
   the board reflects it. Treat a missing board update like a skipped Zero-Bugs Gate.
2. **Staleness signal.** The KANBAN.md header carries `_Last reconciled: <date>_`. At session
   start, compare it to `git log` / live state; if newer work shipped than the board shows,
   reconcile first. A stale date is the tripwire the clock-based system lacks.
3. **No silent moves.** Closing or moving a card writes a one-line disposition (done / deferred
   + why), mirroring CLAUDE.md Plan-Completion-Tracking. A card never just disappears.
4. **Redeploy-on-change, not on-timer.** The Artifact redeploys whenever a card changes column
   or is added — bound to the change event, so the operator's always-open board is never stale
   without a corresponding silent lag.
5. **Backlog adequacy is a consequence, not a separate task.** Because capture is at birth
   (capture-first) and reconciliation rides existing gates, the backlog stays current by
   construction — there is no "go update the backlog later" step to fall behind on.

If the board is ever found lagging, that is itself a `feedback`-class memory event: record the
missed hook so the trigger list gets tighter, the same way a caught bug tightens a test.

## Approval & autonomy — so the board is drivable, not just visible

Each card carries an **approval** state so I can plough independent work without waiting, while
never ploughing into things that need a human call:

- `unreviewed` — captured, not yet judged.
- `implied` — reversible / low-blast-radius / inside an already-approved thread → **I may act
  autonomously.**
- `explicit` — operator said go (record who + date).
- `blocked` — needs an operator decision before anything happens.

**Implied-approval threshold — when I may proceed without an explicit go:** ALL of (a) reversible
or a bug fix, (b) within a thread the operator already approved, (c) low blast radius (no
destructive/outward-facing/cost-or-safety effect, no new cross-coordinator scope), (d) it has
passed the parsimony test below. If any fails → `blocked`, surface it. **Always explicit,
never implied:** destructive actions, outward-facing/published changes, cost- or safety-impacting
logic, Tier-3 shared-primitive work, anything the operator flagged delicate. This is the CLAUDE.md
"reversible → proceed; destructive/scope-change → ask" rule, made per-card.

## Quality-practice tags — the gates a card must pass

Tag each card with the arrived-at practices it must honor, so the gate travels with the work
(controlled vocabulary; extend as we coin more):

`audit-first` (read-only audit before building — e.g. the F1-sunset / HA-side audits) ·
`measure-before-build` (one-shot read-only probe over existing data first) ·
`hand-build-fixture` (construct the mapping by hand once, commit it as the acceptance fixture) ·
`institutional-context` (exhaustive prior-art grep + REUSED/NEW before proposing) ·
`no-fabrication-verify` (cite source/file:line, never a plausible mental model) ·
`tier-2db` / `tier-3` (review tier) · `mutation-drill` (per-site source mutation must go red) ·
`numbers-get-knobs` (every behavioral number gets a named configurable + rung) ·
`probe-first` (empirically-gated — go/no-go on measured data).

## Sharp-problem + parsimony test — systematized, not organic

Before a card leaves Pre-planning it gets a **parsimony verdict** — the CLAUDE.md
Marginal-Benefit Decomposition, applied per card and *recorded* so we stop re-deriving it
organically. Two questions, then a verdict:

1. **Is the problem sharp and real?** State it in one falsifiable sentence. A fuzzy problem is a
   PARK, not a plan.
2. **Is it worth solving vs. the simplest version?** How much does the simplest version capture;
   what is the *marginal* benefit of the fancier one; does that margin pay for its ingredient
   risk + review cost?

Verdict (recorded on the card): **BUILD** · **SIMPLIFY** (build the simplest version, park the
rest with a trigger) · **PARK** (good idea, problem not worth solving *now* — record the evidence
that would revive it) · **DROP** (not worth solving). Reaching "yeah, good idea but not worth
it → park" is a *success* of the gate, not a failure — it is the outcome we most often miss by
only doing this organically. Every Pre-planning card shows its verdict before promotion.

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
