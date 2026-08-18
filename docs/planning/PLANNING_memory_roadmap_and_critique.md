# PLANNING — Memory Subsystem Roadmap + Critique + Survivability

**Card:** MEMORY-ROADMAP-1
**Type:** Planning / critique doc (NOT a build; no CONF_*/sensor proposals)
**Author:** orchestrator, 2026-08-18
**Status:** DRAFT for operator review

---

## 0. Framing

The hierarchical-memory program (`MEMORY-PROGRAM-EPIC` on the board) has
delivered its foundation: Stage 0 (hand-build), Stage 1 (facade + episodic
tier), Stage 2 (compactor), and the Stage 3 first wave of writers
(D4–D7 in v5.78.0). This doc asks the question the epic itself now poses
(`next: Consider closing the epic to done and opening a new epic for the
room-to-room agentic layer`): **what is the honest forward roadmap for
memory, and what parts of it should we actually build?**

The critique applies the marginal-benefit decomposition rule to each
candidate phase, with special attention to the arch §8 **memory-ineligible
boundary** — the invariant that memory answers annotate *interpretation
and attention*, never *action*. Every proposed phase is evaluated for
whether it silently smuggles memory onto a trust/actuation path.

---

## 1. Current state — what is shipped, what each layer stores, where it lives

Read end-to-end for this section: `memory_writers.py` (1–644),
`memory_compactor.py` (1–260), `memory_facade.py` (1–120),
`database.py` (memory DDL 1529–1601; DAOs 8355–8952),
`docs/planning/ARCHITECTURE_hierarchical_memory.md` (all sections),
`docs/planning/PLANNING_memory_writers.md`, kanban `MEMORY-PROGRAM-EPIC`
row (2626–2655).

### 1.1 Layer inventory

| Layer | Storage | Populated by | Read by | Kill switch |
|---|---|---|---|---|
| **Episodic tier** (`memory_episodes`) | URA sqlite; indexed on `(node_id, episode_type, started_at)` (db.py:1547) | D4 `phantom_retro`, D5 `away_transition_blocked`, D6 `tracker_trust_excluded`, D7 `house_state_transition` (memory_writers.py) + earlier detector-ride writers (P22, D2, exterior_track, etc.) | `memory_facade.py` verbs (episodes/narrative/unusual); `memory_compactor.py` (READ ONLY via three named DAOs, compactor.py:19–28); NM digest; operator via `memory_query` service | Per-writer rung-1 constants (`AWAY_BLOCK_EPISODE_ENABLED`, `TRACKER_TRUST_WRITER_ENABLED`, `PHANTOM_RETRO_ENABLED`, `HOUSE_STATE_TRANSITION_WRITER_ENABLED`) |
| **Consolidated-facts tier** (`memory_facts`) | URA sqlite; unique `(node_id, topic)` (db.py:1565); superseded-by pointer preserves history | `memory_compactor.py` nightly (distill/correct/redact-stub), via `distill_memory_fact` DAO | `memory_facade.py` (`facts`, `profile`, `unusual` mix); NM narratives | `MEMORY_COMPACTION_RULES` disable + per-run write cap `MEMORY_COMPACTOR_MAX_WRITES_PER_RUN` |
| **Baseline tier** | `memory_baseline.py` (Welford with sample-count cap → implicit decay; arch §5) | Existing per-node baseline writers | Facade `baseline()`; consumers already extant pre-memory epic | `MEMORY_BASELINE_WRITER_ENABLED` |
| **Identity tier** | Live person registry (arch §5b) — profile() reads live, episodes record change | Existing person registry | `memory_facade.profile()` | n/a (reads live) |
| **Outcome tier** | Existing outcome infra (arch §6, reused as-is) | Existing | Existing | n/a |
| **Redaction (stub)** | `memory_compactor.py:412,420` (stub path present, horizon `MEMORY_REDACTION_HORIZON_DAYS` present at const.py:3888, currently disabled per arch design) | Compactor rule set | n/a while stubbed | Setting horizon = None disables |
| **HA recorder** | HA's own sqlite; NOT URA's DB | HA state machine | HA history/logbook, URA sensors that read historical state | HA recorder config |
| **Assistant-side memory** (`~/.claude/projects/.../memory/`) | Filesystem outside URA | Claude session tooling | Assistant sessions | n/a (outside URA scope) |

### 1.2 Facade shape

Single door (`memory_facade.py`), seven read-only verbs, one return
shape (`MemoryAnswer` = verdict/value/support/provenance/as_of).
`verdict` gracefully degrades to `no_data` on kill or DB failure
(arch §9). Access policy per arch §8 narrows caller-tier standing;
enforced via caller-node prefix vs facade check.

### 1.3 Compactor invariants (compactor.py:6–17)

(a) atomicity per fact (one commit per INSERT[+ supersede UPDATE]),
(b) cross-fact ordering via single-writer FIFO,
(c) preservation — `count(memory_episodes)` never decreases; no in-place
edits; corrections always write a new row and set `superseded_by`.

### 1.4 Memory-ineligible boundary (arch §8)

Four decision classes MAY NOT read memory: safety response, security
arm/disarm, occupancy creation/release, reserve-floor/clamp invariants
(Tier 3). Memory-writer contract in `memory_writers.py:29–43`:
fire-and-forget onto the DB write queue, own-exceptions swallowed,
NOTHING in the integration reads the four D4–D7 episode types on any
actuation path. Enforced by consumer-graph test in `quality/tests/`.

---

## 2. Forward roadmap

Phased by horizon. Each phase carries the problem it solves, the
simplest version, and testable acceptance criteria. Phase **P**
numbering is stable so §3 critique can reference by ID.

### NEAR (0–1 cycles ahead)

#### P1 — Close out MEMORY-WRITERS-1 zone_phantom follow-up (parked, evidence-triggered)
- **Problem it solves:** the F2 zone-vs-house divergence class has zero
  memory witnesses (audit "Missing episode types"). Card
  `MEMORY-ZONE-PHANTOM-WRITER-1` is parked pending a real recurrence.
- **Simplest version:** ONE additive writer copy-adapted from D5, spec
  already fully written in `docs/planning/PLANNING_memory_writers.md`
  §4. No new architecture surface.
- **Acceptance:** the plan's D1 acceptance table (§6 of that doc) is
  the contract — do not re-derive.
- **Trigger to unpark:** first organic F2-shape divergence observed.

#### P2 — Compactor per-type coverage sweep
- **Problem it solves:** shipped compactor covers a documented rule set
  (`MEMORY_COMPACTION_RULES`), but D4/D6/D7 episode types will accrue
  volume without matching distillation rules. Over time this yields a
  large episodic tier and a thin facts tier (works, but wastes the
  compactor's whole point).
- **Simplest version:** one-shot audit script that lists episode types
  by rolling 30-day row count and flags any type with row_count > N
  and no compaction rule. Add rules only for types actually crossing
  the threshold; hand-build the distillation template first per the
  "measure before you build" rule (already the compactor's own
  discipline — cf. AUDIT_memory_handbuild_compactor_exterior_track).
- **Acceptance:**
  - Audit script produces a table (type × count × has_rule × proposed_rule_or_none)
    committed to `docs/planning/AUDIT_memory_compactor_type_coverage.md`.
  - Any new rule ships with a hand-oracle diff fixture (same shape as
    the existing exterior_track baseline oracle).

#### P3 — Redaction horizon enable (stub → live)
- **Problem it solves:** redaction stub exists (compactor.py:412,420)
  behind `MEMORY_REDACTION_HORIZON_DAYS` (const.py:3888) but is
  disabled. Table size will grow monotonically. Arch: enable at ~20k
  rows (kanban epic §Future).
- **Simplest version:** measure current row count and per-type
  distribution; only when a type crosses the horizon, set its
  redaction rule; roll-up-row shape is already specified (arch §5c
  point 3).
- **Acceptance:**
  - Row-count probe committed as an AUDIT.
  - Enable ONE horizon at a time, each behind its own knob; PASS = the
    invariant `count(memory_episodes)` never decreases still holds
    (rollup writes NEW rows, does not delete). Compactor invariant (c)
    already asserts this — the enable is a knob turn, not a code change.

### MID (1–3 cycles ahead)

#### P4 — Memory-first diagnostics doctrine, deepened
- **Problem it solves:** doctrine is documented (`memory_first`
  memory-body; MEMORY-FIRST-DIAGNOSTICS-1 skills amended) but the
  facade verbs are still under-used vs raw recorder mining in
  investigations. This is a workflow/tooling gap, not a code gap.
- **Simplest version:** add one more example-driven skill entry per
  common investigation shape (guest-FP recurrence, phantom-latch
  recurrence, block-episode recurrence). No new code.
- **Acceptance:** three worked examples in the skill referencing the
  facade verb that answers each; measured by the next investigation
  starting with `memory_query` instead of a `select … from states`.

#### P5 — NM consumer deepening (READ-only)
- **Problem it solves:** NM digest already consumes some memory
  answers; broader consumption (e.g. tone-adjustment on recurring
  sensor false-alarms) is on the epic's `Future` list.
- **Simplest version:** ONE new NM tone-adjust site keyed off the
  `unusual` verb; strictly read-only; explicitly memory-ineligible
  boundary preserved (annotate tone, never suppress or dispatch).
- **Acceptance:**
  - Grep-anchored consumer-graph test extended to prove the new
    consumer is on a *tone* branch, not a *fire* branch.
  - Live: one organic recurrence produces a demonstrably softer NM
    message; screenshot into README write-back.

#### P6 — Adjacency-graph batch refresh (arch §7 / kanban Future)
- **Problem it solves:** enables cross-node/cross-tier queries the
  facade already exposes but currently answers with `no_data` for the
  graph-derived cases. Named on the epic `Future` list.
- **Simplest version:** batch job derives an adjacency edge set from
  episode co-occurrence within a short join window; write to a new
  small table; facade reads it. NO runtime instrumentation on the
  actuation path (probe-first discipline: measure co-occurrence
  cardinality on existing episodes before designing the schema).
- **Acceptance:** probe committed as AUDIT with co-occurrence
  histogram; only then a Tier-2 build. Kill switch on the writer,
  kill switch on the facade read.

### FAR (unscheduled — architecture-level)

#### P7 — Room-to-room agentic layer (foundation is memory; scope is NOT memory)
- Called out in `ROADMAP-STALE-AGENTIC-LAYER-1`. This is the *consumer*
  the memory foundation was built for. It is a separate epic; from the
  memory subsystem's point of view the only ask is that the facade
  remain the sole door. **Recommend closing MEMORY-PROGRAM-EPIC as
  DONE and opening AGENTIC-LAYER-EPIC on top of it** rather than
  extending the memory epic to absorb agentic scope.

#### P8 — REJECTED: memory-informed decisions on any of the four §8-ineligible classes
- **Direction:** letting memory adjust presence/safety/security/clamp
  decisions directly ("this room is usually empty at 2pm, downweight
  the mmWave hit").
- **Verdict:** REJECT. This is precisely the §8 memory-ineligible
  boundary. Promotion would be Tier 3 by architecture, and the
  operator has repeatedly re-affirmed the boundary (arch §8 v2
  addition; the "cross-investigation synthesis" and census
  double-count near-miss both traced to trust-path derivations
  interacting badly). Park permanently unless a specific decision
  class provides a proven-value case AND a Tier 3 build.

#### P9 — Summarization quality improvements (narrative verb)
- **Problem:** the `narrative()` verb currently synthesizes from
  episodes + facts (facade §3). Quality is fine for one node; multi-
  node roll-ups will bloat.
- **Simplest version:** cap fan-out (already implicit via §8 tier
  scoping); no LLM in the loop yet. If narrative quality becomes a
  bottleneck, revisit with an LLM summarizer BEHIND the facade with
  an aggressive rate-limit and NO trust-path consumer.
- **Verdict:** defer until a measurable narrative-quality complaint
  surfaces. Do not build on speculation.

#### P10 — Cross-session continuity (assistant-side)
- **Problem:** assistant memory (Claude MEMORY.md) and URA memory
  are separate. Bridging them would let the assistant query the
  facade at session start.
- **Simplest version:** the `memory_query` service already answers
  read-only. No URA-side build needed; this is an assistant-tooling
  question, not a memory-subsystem question. Track under
  MEMORY-FIRST-DIAGNOSTICS-1 sibling, not here.

#### P11 — Decay / forgetting policy
- **Baselines already decay** (Welford with sample-count cap; arch §5).
- **Episodes preserved by design** (compactor invariant (c)); the
  forgetting mechanism is *redaction rollup*, not deletion. P3 is the
  operational lever.
- **Verdict:** no separate phase needed. Rejected as its own build.

#### P12 — Privacy / PII in stored episodes
- **Problem:** episodes and their `attrs_json` payloads can carry
  person names, phone identifiers, camera-face IDs.
- **Current state:** DB is local-only on HAOS; no third-party egress.
  Assistant-side memory is separate.
- **Simplest version:** enumerate the attribute keys that carry
  identifiers in episode payloads (grep-based audit); document the
  set; if any of them exit the DB (e.g. via a future dashboard export
  or cloud sync), gate that egress with a redactor.
- **Verdict:** worth the audit (P12a — AUDIT only, small); the
  redactor is deferred until an actual egress path exists. Do NOT
  redact at write time (destroys diagnostic value); redact at
  egress only.

---

## 3. Critique — marginal-benefit decomposition per phase

Following the operator-coined pushback rule (`marginal-benefit
pushback`): compare margin over the simplest version, not totals.

| Phase | Simplest capture | Marginal ingredient risk | Recommendation |
|---|---|---|---|
| **P1** zone_phantom | Fills the one enumerated writer gap. Zero if F2 divergence never recurs. | Zero new architecture — parallel to shipped D5. | **Build on trigger** (already parked correctly). |
| **P2** compactor coverage audit | Preserves the ratio of episodes-to-facts the arch expects (thin episodes, rich facts). Simplest = a read-only audit script. | The AUDIT itself: none. Adding rules: each rule is a per-type hand-oracle diff (existing discipline). | **BUILD the audit now** (AUDIT-tier work); build individual rules only for types crossing the threshold. |
| **P3** redaction enable | Bounds table growth. Simplest = enable per-type at horizon crossing, keep rollup shape. | Compactor invariant (c) already asserts count-never-decreases via rollup rows. Risk is a mis-scoped redaction rule dropping a diagnostically load-bearing episode class. | **Measure first**, enable one class at a time with its own kill switch. Do NOT enable in bulk. |
| **P4** doctrine deepening | Faster investigations. Simplest = three worked examples. | Zero. | **Do it** (docs work, no code). |
| **P5** NM consumer deepening | Nicer NM tone on recurring FPs. Simplest = ONE new tone-adjust site. | Categorically risky if consumer creeps to a suppression branch. Requires the consumer-graph test extension per site. | Build ONE site, extend the test, hold. Do not batch. |
| **P6** adjacency graph | Enables cross-node queries the facade already promises. | Probe-first mandatory; without it the schema is a guess. NEW writer (rate-bound), NEW small table, NEW facade read path — 3 ingredient risks. | **Probe first (AUDIT-tier)**; scope the build only after the probe justifies it. Explicit Tier-2. |
| **P7** agentic layer epic | Realizes the vision memory was built for. | Enormous — a whole new epic. Not a *memory* build. | Not this doc's scope. Recommend closing this epic and opening the next. |
| **P8** memory-informed §8 decisions | **Would** let live signals be biased by history. | Violates the §8 memory-ineligible boundary; Tier 3 by architecture; census double-count precedent shows what happens when memory-shape state leaks onto a trust path. | **REJECT permanently.** Park with an evidence trigger only for a *specific* decision class that carries an independently-proven value case AND a Tier 3 review commitment. |
| **P9** narrative quality / LLM | Prettier narratives. | LLM in the loop = new external dependency, latency, and a whole tone-vs-truth QA surface. Zero identified user impact today. | **Park.** Revisit only on a concrete complaint. |
| **P10** cross-session continuity | Bridges Claude and URA memories. | Not a URA build; assistant-tooling scope. | Out of scope for this roadmap. |
| **P11** decay / forgetting | Already handled (baselines Welford; episodes preserved w/ rollup). | n/a. | **No separate phase.** |
| **P12** PII audit | Enumerate identifier-bearing attrs; only redact on egress. | AUDIT: none. Egress redactor: build only when egress exists. | **Do the audit; defer the redactor.** |

### Recommended near-mid ordering

1. **P4** (docs, zero risk, immediate)
2. **P12a** (audit only, zero risk)
3. **P2** (audit → rules only for types crossing threshold)
4. **P1** on organic trigger (already parked correctly)
5. **P3** after P2 gives a per-type histogram (redaction enable rides P2's data)
6. **P5** one site at a time
7. **P6** probe first; only then scope the build
8. **CLOSE MEMORY-PROGRAM-EPIC**; open AGENTIC-LAYER epic

### Rejected/parked with triggers

- **P8** (memory-informed §8 decisions): rejected on architectural grounds; only revisit per specific decision class with Tier 3.
- **P9** (LLM narrative summarizer): park until a concrete quality complaint.
- **P11** (dedicated decay phase): rejected — already handled.

---

## 4. What survives — durability matrix

Survivability of each memory artifact across the three axes that
matter (HA restart, HA recorder purge, assistant session end),
plus consumers and trust-path status.

| Artifact / layer | Storage | Survives HA restart? | Survives HA recorder purge? | Survives assistant session end? | Consumers | On trust path? |
|---|---|---|---|---|---|---|
| `memory_episodes` (D4–D7 + earlier writers) | URA sqlite (`.../universal_room_automation.db`) | **YES** — writes are DB-durable; boot reconcile force-closes stranded OPEN rows | **YES** — HA recorder purge does not touch URA's own DB | **YES** — independent of assistant | Facade verbs; compactor (read); NM digest; operator via `memory_query` | **NO** (arch §8; consumer-graph test enforced) |
| `memory_facts` (compacted, with `superseded_by`) | URA sqlite | **YES** | **YES** | **YES** | Facade `facts` / `profile` / `unusual`; NM narratives | **NO** |
| Baselines (`memory_baseline.py`) | URA sqlite | **YES** (Welford state persisted) | **YES** | **YES** | Facade `baseline` | **NO** (annotates confidence only) |
| Identity/profile | Live person registry (HA registry + URA state) | YES (via HA registry) | Not applicable | YES | Facade `profile` (reads live) | Presence trust path uses the live registry directly, not the memory facade — the facade READ is read-only annotation, so memory-facade access itself is NOT on the trust path |
| Outcome tier (existing) | URA sqlite (existing) | YES | YES | YES | Existing consumers (pre-memory) | Existing (unchanged) |
| Compactor per-run stats | In-memory + kanban-visible via diagnostics sensor + DB written facts | Stats sensor: NO (recomputed); facts: YES | YES | YES | Diagnostics sensor; NM switch | NO |
| Redaction rollup rows | URA sqlite (arch §5c point 3; enabled via P3) | YES | YES | YES | Facade (transparently — replaces detail rows for old episodes) | NO |
| HA recorder history (state/events) | HA sqlite | YES | **NO — purged by HA's own retention** (this is why URA writes its own memory) | YES | HA history/logbook; URA sensors that historically consumed HA state | Varies (HA history is not itself a URA trust surface, but downstream sensors that read it may be) |
| Assistant-side memory (`~/.claude/projects/.../memory/*.md`) | Filesystem outside URA and outside HA | Independent of HA restart | Independent of HA purge | **DEPENDS** — persists across sessions by design, but is per-user and per-machine | Assistant sessions | NO (not part of URA runtime) |
| Kanban board (`docs/planning/kanban.data.yaml`) | Git-tracked file | YES | YES | YES | Operator + all agents | NO |
| Vibememo (`.vibememo/counseling.jsonl`) | Git-tracked file | YES | YES | YES | Operator retro; agents on read | NO |

**Key survivability point.** The whole reason URA has its own memory
tables is that HA recorder purge deletes exactly the history a
long-horizon consultative memory needs. Every URA memory artifact
above (except the reused HA recorder line) is durable across HA
restart AND HA purge. The compactor preservation invariant (c)
plus rollup-rather-than-delete gives us a strong story: **rows
change shape (detail → rollup) but the count never decreases**.

**Trust-path summary.** No URA memory artifact is on a trust /
actuation path today. The four architectural ineligibility classes
(§8) plus the consumer-graph test are the enforcement. Any future
consumer that would put memory onto a trust path is a Tier 3 change
by architecture — see P8.

---

## 5. Recommendation to operator

1. **Close `MEMORY-PROGRAM-EPIC` as DONE** when P1's zone_phantom
   trigger fires (or explicitly declare P1 optional and close now).
2. **Open the small AUDIT tickets** (P2 coverage, P12a PII enumeration)
   as read-only cycles — near-zero risk, high leverage.
3. **Open an AGENTIC-LAYER epic** to hold the consumer work the memory
   foundation exists for (`ROADMAP-STALE-AGENTIC-LAYER-1` is already
   flagging this vacuum).
4. **Explicitly park P8 (memory-informed §8 decisions) permanently**;
   revisit only per-decision-class with a Tier 3 commitment.
5. **Do not open P9/P11** without evidence triggers.

Doc path: `docs/planning/PLANNING_memory_roadmap_and_critique.md`.
