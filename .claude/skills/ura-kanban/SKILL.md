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

## The second rule: adjacency sweep before any new card is accepted

**No new card is accepted as its own item before sweeping ALL existing work for adjacency or
duplication.** This does not weaken capture-first — capture into Inbox immediately, then run the
sweep *before the card is promoted out of Inbox*. Board hygiene fails in the mirror-image direction
from capture failure: a board that never merges becomes a list nobody reads, and duplicate cards
**split the evidence for one problem across two places so neither is decisive.**

### Sweep surfaces — the board is NOT the whole prior art

Sweep all four, in this order. Skipping the last two is the observed failure mode (2026-08-09):

1. `kanban.data.yaml` — every card's title + `why`, **not just the thread you assume it belongs
   to**. Adjacency routinely crosses threads.
2. `docs/BACKLOG.md` — dated `B-YYYY-MM-DD-N` items. Newer diagnoses often land here, not on the board.
3. **`docs/planning/PLANNING_*.md` PARKED / deferred deliverables + "Plan Completion Tracking"
   sections.** A parked `Dn` with an evidence trigger *is* a card living in a planning doc. This is
   the surface that gets missed, because it looks like shipped work.
4. `docs/planning/CATALOG_*.md` + `AUDIT_*.md` — the extend-vs-new adjudicators and probe results.

This mirrors CLAUDE.md's **Institutional Context First** protocol, applied to work items rather
than to symbols: cite where you looked, and say DUPLICATE / ADJACENT / NEW with the evidence.

### The three relationships, tested in order

- **Duplicate** — same problem, same fix surface → merge into the existing item; do not create.
- **Adjacent** — different problem, but *same code surface, same decision, or same discriminator*
  → fold in as a sub-finding, or create the card with an explicit `depends_on:` / `sibling_of:`
  link. **Adjacency is the case most often mis-filed as new.**
- **New** — no shared surface or decision → create it, and record what it was swept against.

### Recording and merging

- **Record the ruling on the survivor** (`DEDUPE_<date>:` with what was folded in and why). A
  silent merge is indistinguishable from a dropped card three weeks later; the *reason* it merged
  is the evidence it wasn't lost.
- **Merging is lossy if careless** — carry the new item's Origin, Constraints and evidence across
  verbatim. The survivor inherits the **union**, never the intersection.
- **A parked item whose trigger has since fired is not "done" — it is READY.** When the sweep finds
  one, promote it and say so; do not re-plan it from scratch.

**Worked example (2026-08-09, the miss that produced this rule).** Motion-chatter detection arrived
as a candidate new card. Sweeping the board alone found STUCK-SENSOR-1 (adjacent — same detector,
same exclusion decision, same corroboration discriminator) and it was folded in correctly. But the
sweep stopped there, and the operator had to push twice ("I'm suspicious… look for other work or
plans", "as well as new checks") before surfaces 2–4 were checked — which held the *actual* prior
art: a **PARKED D6 "dead/stuck mmwave in stuck-signal watchdog"** inside
`PLANNING_mmwave_corroboration_tier3.md` with an explicit evidence trigger that had already fired,
plus two dated BACKLOG items (`B-2026-08-04-1` state/class-awareness, `B-2026-08-04-2` fleet rot).
Sweeping only the board would have re-planned parked work as novel.

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
| About to create a NEW card | Run the four-surface adjacency sweep first; record DUPLICATE / ADJACENT / NEW + what was swept |
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
missed hook so the trigger list gets tighter, the same way a caught bug tightens a test. **But
diagnose first: coverage gaps get rules, forcing-function gaps get mechanisms.** If the hook
already existed and was simply not followed, do NOT add a rule — add a forcing function (below).
Adding rules against compliance failures is how a rule-set bloats until nobody reads it.

## Forcing functions — the currency ladder

**Operator-coined 2026-08-09: *"A banner is not a forcing function. Is there a harder one? A kanban
that does not keep current is fairly useless."*** A board that lags is worse than no board, because
picking "next" off a stale board can rebuild already-shipped work.

The diagnosis that produced this section: board reconciliation is **the only step in the deploy
ritual with no forcing function.** `deploy.sh` refuses without tests and refuses without a README —
nothing refuses without a board update, so it is the only step running on willpower. It rotted twice
(2026-08-09: the board said "build" for two features already shipped as v5.63.0 / v5.64.0), and the
staleness tripwire `meta.last_reconciled` was correctly showing stale the whole time. **A signal that
must be interrogated is not a mechanism.**

> **Principle: the board update must be an OUTPUT of the work, never a task beside it.**

| Rung | Kind | Mechanism |
|---|---|---|
| **1** | **HARD** | `deploy.sh --cards ID[,ID…]` — **refuses to deploy** when absent, printing current `in_progress`/`review` cards as candidates. On success it *writes* `status: shipped_organic` + `shipped_version` per card and `meta.last_reconciled: <today>`, in the release commit. `--no-cards` escape for pure-docs releases, explicit and logged. |
| **2** | **HARD** | **Vibememo chained to the same gate** — the release also emits a vibememo entry (the WHY of the ship). Both systems are release-coupled, so the decision trail cannot lag either. |
| **3** | soft | Generator renders a loud **STALE banner** + warns on build when `meta.last_reconciled` is older than the newest git tag or `README_v*.md`. |
| **4** | soft | Session-start staleness check (enforcement #2 above). |
| **5** | soft | Recurring overnight agentic pass reconciles the board as its **first** action, before picking up `overnight-agentic` work. |

**Soft rungs are backups, not substitutes.** They exist because the hard gate covers one transition;
they must never be cited as reason to skip rung 1.

**Scope limit, stated honestly.** Rung 1 hardens only the **shipped** transition;
`pre_planning → planned → in_progress` remains soft (turn-end hook). This is deliberate rather than a
half-measure: every card found stale on 2026-08-09 was *shipped work the board still called "build."*
The rot concentrates exactly where rung 1 bites. If in-flight statuses prove to rot too, add a second
mechanism **on evidence**, not by guess.

**Safety constraint on any release-coupled write:** a failed board/vibememo write must **never** abort
a deploy that has already pushed — trading a stale board for a half-released version is strictly
worse. Write after the push succeeds, warn loudly on failure, never exit non-zero post-push.

### Overnight / autonomous work needs a trigger, not an intention

Same class of failure: *"build it tonight while I'm sleeping"* has no forcing function — the session
ends and nothing wakes anything up (observed 2026-08-09, KHOST-1 missed). Work tagged
`autonomy: overnight-agentic` must be bound to a **real recurring scheduled job**, whose first action
is a board reconciliation. An overnight commitment with no scheduler is a promise, and promises are
the thing this skill exists to replace.

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

## Ranking & sequencing — batch by affinity, order by dependency

Cards are not a flat list. Rank/sequence by, in priority:

1. **Dependency (hard order)** — X precedes Y when Y trusts X's output. Record as `blocks:`/`after:`.
2. **Affinity / batch** — cards touching the same primitive, review cycle, or surface ship as one
   `batch:` (one build, one Tier-2DB review, shared context) — not scattered across cycles.
3. **Leverage** — foundational / shared-primitive work first; it de-risks everything downstream.
4. **Unblocked-ness** — prefer `implied`/`explicit` cards with no pending decision; `blocked` waits.
5. **Freshness / cost-of-delay** — a live-broken bug jumps the queue *unless* it folds into a
   batched cycle (then it rides that cycle rather than spawning a one-off).

Record `batch:` (named group) and optional `seq:` (order within/among batches) on cards. Do not
start a card whose `after:` dependency is unmet, or a `blocked` card, no matter how appealing.

### 6. Concurrency — the depletion lever

**Operator-coined 2026-08-09: *"Concurrency is definitely a strategy for kanban depletion."*** Ranking
answers *what next*; concurrency answers *how many at once*. A board with 30 cards worked strictly
serially is a board that never empties. Treat parallelism as a first-class sequencing dimension, not
an occasional optimization: at each turn, ask not only "what is next" but "**what else can run right
now that this does not block.**"

**What safely parallelizes:**
- **Disjoint surfaces** — cards touching different files/subsystems (a presence plan and a perimeter
  build).
- **Framing-disjoint reviews of the SAME diff** — this is the highest-value parallelism we have; the
  Tier-2DB/Tier-3 protocols already mandate it precisely because different framings cannot share blind
  spots.
- **Read/scope work beside build work** — a planner scoping card X while a builder implements card Y.
- **Independent items inside one batch** where no `after:` links them.

**What must NOT parallelize:**
- Anything in a dependency chain (`after:` / `depends_on:` / `blocks:`) — running a blocked card early
  just means rework when its prerequisite changes shape.
- Two agents writing the same file. This is not theoretical: three worktree collisions in one day
  produced the standing isolation rule.
- Work that depends on a diff still under review — if the review can force a redesign, a dependent
  build is speculative.

**The hard requirement:** every concurrent repo-writing dispatch gets **worktree isolation**, and the
orchestrator freezes the main tree while builders run. Without it, concurrency converts throughput
into merge damage.

**Verify the worktree's BASE, not just that it is isolated (added 2026-08-09).** A worktree can be
isolated and still branch from a stale ref. Observed: a Tier-3 build came back green on
`19 failed / 8125 passed` — but its base was **214 commits behind develop**, so it had validated
against a suite missing ~370 tests and against source predating the whole day's work. Isolation
protected the tree; it did not protect the baseline.

> Before trusting ANY agent's suite numbers, run
> `git rev-list --count $(git merge-base <branch> develop)..develop`. Non-zero means the numbers
> describe a codebase that no longer exists.

A green suite on the wrong base is worse than a red one — it reads as evidence. The cheap recovery is
a cherry-pick onto current develop plus a re-run; check first whether the specific functions the build
refactored moved in the interim (`git diff <base>..develop -- <file>`), because that decides between a
rebase and a redo.

**The real bottleneck is orchestrator attention, not agent count.** Each concurrent agent returns a
report that must be independently verified — never accept a builder's or reviewer's summary as fact.
Fan out to the width you can actually verify, then stop. Depletion that outruns verification is how
unreviewed work reaches the house.

**Current batches:**
- `resolver-correctness` (foundation, largely autonomous): RESACC-1 → TEST-1 → TRANSIT-1.
- `perimeter-delivery` (one Tier-2DB cycle; needs SNAP-1 decisions): CONSOL-1 + SNAP-1 +
  FRIG2SNAP-1 + TEST-2 + KP-ESCALATE-1 (KP-ESCALATE-1 gates the doorbell retirement).
- `overnight`: KHOST-1 (do NOT pull into collaborative daytime).
- standalone: SECC-1 (quick read-only verify).

## Referencing cards in user-facing messages — always gloss

Never name a card by its bare code in chat/reports. Append **problem → solution + scope** every
time (operator rule 2026-08-07). Scope = size / what it touches / tier ("~30 LoC additive",
"Tier 2-DB, touches presence", "config-only"). The code is the board index; the reader needs the
meaning and the blast radius to act. Example: "SNAP-1 (alerts arrive with no/stale photo → attach
an at-detection local file → Tier 2-DB, perimeter_alert + NM, folds into CONSOL-1)".

## Relationship to other systems

- **vibememo** = WHY (decision trail, reasoning-in-motion). **This** = WHAT / WHERE / NEXT.
  A card's `Why` is a pointer to the fuller vibememo entry, not a replacement for it.
  **They are chained at the release gate** (rung 2 above): a ship updates both or neither. Vibememo's
  historical weakness was the same clock-based cadence this skill rejects — coupling it to the release
  ritual gives it the forcing function it never had, without making it a separate chore to remember.
- **BACKLOG_*.md + memory bodies** hold the broader, non-active backlog. The board's
  "Broader backlog" footer just points at them; it does not duplicate them.
- **CLAUDE.md** governs *how* work is done (tiers, gates). The board governs *what* is in
  flight and *whether it was lost*.

## Count the consumers before fixing the defect

**Coined 2026-08-09, from the most expensive miss of that session.** RESACC-1 measured the camera
resolver against a hand-built fixture and found two real bugs. A fix shipped, passed two of three
framing-disjoint reviews with excellent mutation-anchored tests — and was reverted, because the third
reviewer asked the question nobody had: **who actually reads this value?**

Answer: one caller, and it used the *other* code path. Both "bugs" were latent; the fix's new failure
mode landed on the only live consumer, where the old behavior (`None`) was *safe* and the new one
(a wrong value) was actively harmful.

The measurement was correct. The fixture was correct. The tests were excellent. The work was still
wrong, because *impact* was inferred from the size of the data defect rather than from consumption.

> **A defect's severity is a property of its consumers, not of the data.** Before scoping a fix,
> grep for who reads the value and on which path. Put the consumer count in the plan.

Corollaries learned the same day:
- **A measurement licenses only what it measured.** "We measured grouping is sound, so this guard is
  unnecessary" was false: the guard protected a *different* property than the one measured. Name the
  property before citing a measurement as evidence.
- **`None` is often safer than a wrong value.** Anything that filters on membership (`x not in set`)
  fails *closed* on `None` and *open* on a wrong value. Turning a "missing" into a "wrong" is a
  regression even when it looks like an improvement.
- **Ask which latent state fires first.** When both benefit and risk are latent, the deciding evidence
  is base rates in *this* deployment — not which sounds worse.

## Anti-patterns

- A card with a title but no Origin/Next — that's a transcript line, not a card.
- Letting a mid-turn discovery stay in the tool output "because I'll remember it."
- Duplicating vibememo's reasoning into the board, or the board's status into vibememo.
- Creating a card without the adjacency sweep — or sweeping only the board and not BACKLOG.md,
  parked planning-doc deliverables, and the catalogs/audits.
- Treating a PARKED deliverable as shipped work. Parked ≠ done; check whether its trigger fired.
- Merging silently, or merging down to the intersection instead of the union.
- Editing the Artifact without editing KANBAN.md — the committed file is the source of truth;
  the Artifact is a reflection, never the record.
