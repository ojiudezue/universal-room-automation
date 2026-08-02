# VISION — Hierarchical Entity Memory

Status: DRAFT v2 (self-critiqued, finalized 2026-08-02). Operator concept,
2026-08-02: "What if each room had memory? ... zones ... house ...
coordinators ... shared, with a standard interface queryable by any node
at any level."

## 1. The claim

URA's founding move is composition: devices compose into rooms, rooms
into zones, zones into a house, with coordinators riding across. That
abstraction is applied to the PRESENT — a room is the unit of *current*
state. Memory applies the same move to TIME: each node (room, zone,
house, coordinator) owns its history, compressed into consultable form,
behind one small query interface any node — or any human, dashboard, or
agent — can use.

The claim is NOT "URA should store more data." URA already stores a lot
(see §4). The claim is that history owned by nobody is forensics, and
history owned by the node is memory — the difference between an operator
(or an AI session) writing a recorder probe to discover that fan
phantoms align with fan transitions, and the room being able to answer
that question itself.

## 2. What "memory" means here — five kinds, one interface

**Episodic memory** — discrete events that happened to this node, WITH
adjudication: not just "occupancy released" but "occupancy released,
later adjudicated phantom (fan transition)." The adjudication is what
raw logs lack and what makes recurrence recognizable. Episodes can be
retro-corrected when later evidence reclassifies them (a demotion
reclassifies the creation that preceded it).

**Baseline memory** — compressed normality: for a signal in a context
(hour-of-day × house-state × season), what is normal for THIS node?
Mean/variance/sample-count style summaries, never raw series. This is
what turns global thresholds into per-node priors and "crossed 85%" into
"unusual for this room at this hour."

**Outcome memory** — predictions and decisions paired with what actually
happened: forecast skill per node, realized-vs-projected savings per
strategy, veto/demotion hit rates. This is the loop-closer: it is how
the system learns which of its own judgments to trust, without ML
machinery.

**Identity memory (operator addition 2026-08-02)** — what a node IS:
what it contains (room → sensors/actuators; zone → member rooms +
thermostat; house → zones) and what it can DO (actuation surface,
mechanisms enabled). The present answer reads live from config — config
IS the store — but memory owns the CHANGES: a swapped sensor or added
fan is an episode, so "when did my composition change" is answerable.
Identity also carries **locality** (operator addition 2026-08-02), in
two senses: *zone locality* — my zone siblings (pure config read; the
§8 access policy already keys on it) — and *self locality* — the rooms
physically around me, derived rather than declared: the room_transitions
table (273k rows) yields a symmetric, physically-sane adjacency graph
(probe 2026-08-02), refinable by BLE co-visibility, overridable by
config. Locality is a queryable PROPERTY of a node, not a permission
boundary (see architecture §5b for the rejection rationale).
Without this kind, every diagnosis query begins by asking something
memory can't answer.

**Consolidated facts (operator addition 2026-08-02, vibememo-inspired)**
— the layer that keeps memory from devolving into aspect logging.
Episodes are the flight recorder; facts are the synthesis: "Study A
mmWave phantoms onset at fan transitions (12 episodes, Jul-Aug 2026)"
as a durable, citable, CORRECTABLE statement. Per vibememo doctrine:
the why-provenance (derived-from episode ids) is the last thing
compressed and the first preserved; facts are never deleted, only
superseded with lineage; and once distilled, the underlying episode
detail can be redacted to counts/spans — compression with a paper
trail, not forgetting.

All five kinds sit behind ONE interface (§3). A consumer never knows or
cares which table serves the answer.

## 3. The interface is the product

A small set of verbs, in domain vocabulary, read-only:

- `baseline(node, signal, context)` → normal value + spread + support
- `unusual(node, window)` → deviations from own baseline, ranked
- `episodes(node, pattern, window)` → adjudicated events matching
- `outcome(node, decision_type, window)` → predicted vs realized
- `narrative(node, window)` → ordered, human-readable event story
- `profile(node)` → composition + capabilities (identity kind)
- `facts(node, topic?)` → consolidated, correctable knowledge with
  why-provenance

(Seven verbs, was five: the two additions are distinct memory KINDS —
identity and consolidated knowledge — not query conveniences. The creep
rule stands for conveniences; kinds earn verbs.)

Three properties are load-bearing and non-negotiable:

1. **Read-only.** No node ever writes another node's memory. Writers are
   the node itself and the adjudication path.
2. **Provenance + confidence on every answer.** An answer names its
   evidence (tables, rows, spans) and its support (sample counts).
3. **"Insufficient history" is a first-class answer.** Consumers MUST
   handle it; a new room with no history behaves exactly as rooms do
   today. Memory degrades to the present, never to confident garbage.

## 4. Why this is more than what we have

We already persist: `occupancy_events`, `environmental_data`,
`decision_log`, `anomaly_log`, `house_state_log`, `outcome_log`,
`metric_baselines`, `parameter_beliefs`, plus a `BayesianPredictor`
holding time-binned room occupancy priors, plus the HA recorder itself.
Honest accounting of the delta:

| Have today | Memory adds |
|---|---|
| Logs and aggregates, each with a bespoke reader (or none) | One query surface; the next consumer composes instead of plumbing (`get_fan_last_transition` is a hand-built memory query — every fusion cycle builds several) |
| Events without adjudication | Episodes that know what they turned out to be, retro-corrected |
| Coordinator-scoped baselines (metric_baselines) | Node-scoped normality at every tier, context-conditioned |
| Predictions made, outcomes sometimes logged | Skill tracked per node; trust-weighting has a substrate |
| Cross-node questions answered by a human writing SQL | Cross-node questions answered by nodes ("am I the only one seeing dropouts?" — one dead sensor is a fault; twelve in 90s is a network event) |

## 5. What it unlocks, ranked by value density

1. **Anomaly = deviation from own baseline** — NM gets quieter AND
   sharper; thresholds gain per-node priors (Numbers Get Knobs → knobs
   get priors).
2. **Decision-outcome loops** — energy strategy learns realized yield;
   HVAC learns preset efficacy per zone per season.
3. **Cross-node differential diagnosis** — local-fault vs systemic-event
   distinction made by the system, not the operator's checklist.
4. **Episodic recurrence** — second occurrences of any incident class
   get cheap ("matches 2026-08-01, adjudicated phantom").
5. **Explainability** — "why did you do that?" answered from the node's
   own narrative; the operator, dashboard, and AI sessions are
   first-class consumers of the SAME interface.
6. **The paper/OSS story** — hierarchical entity memory with a uniform
   query interface is a bigger contribution than any single fusion
   doctrine; it becomes the spine of the queued fusion-library work.

## 6. Dangers, named up front

- **Shared primitive = Tier 3 ingredient.** Every consumer couples to
  the interface. The interface must be small, versioned, and reviewed
  like the signal bus.
- **Garbage in becomes confident garbage out.** Phantom events would
  have poisoned the occupancy baseline. Hence: write-quality gating +
  retroactive correction are part of the CONCEPT, not an enhancement.
- **Query language creep.** The recorder already speaks SQL. If a need
  can't be said in the seven verbs, that is a design signal, not a reason
  to add verbs. We are building a semantic layer, not a database on a
  database.
- **Memory-driven actuation is a trust-hierarchy ripple by definition.**
  Phase discipline: memory informs confidence, explanation, and
  notification first; any behavior change gated on memory goes through
  tiered review like any trust change.

## 7. Non-goals

- Not an ML platform; summaries are transparent statistics.
- Not a replacement for the recorder, the URA DB, or shipwatch.
- Not cross-home federation (single-install product; see
  single-user-no-backcompat policy).
- Not unbounded retention: decay and resolution policy are part of the
  design (raw → episode → baseline is a compression pipeline).

## 8. Proof gate (Measure Before You Build)

Before any implementation: hand-build ONE MONTH of Study A's memory from
existing recorder + URA DB data, then hand-answer five real queries
against it (one each from: a sibling room, NM, the operator, a
dashboard, a diagnosis session). The concept passes only if those
answers would have demonstrably earned their keep (caught the fan
incident sooner, suppressed a redundant alert, explained an AC retreat).
The hand-built artifact becomes the acceptance fixture the
implementation is diffed against.

---

## Critique applied before finalizing (v1 → v2)

- v1 defined memory as a storage system; reframed to "semantic layer
  over existing persistence" after the prior-art grep showed
  metric_baselines/outcome_log/parameter_beliefs/BayesianPredictor
  already exist. The delta table in §4 is the correction.
- v1 listed seven interface verbs including `similar(node_a, node_b)`
  and `trend(signal)`; cut to five — `similar` is `episodes` with a
  pattern, `trend` is `baseline` at two contexts. Verb-creep is the
  named danger; the vision doc must model the discipline it preaches.
- v1 undersold the danger section; adjudication/retro-correction was an
  implementation note. Promoted to concept-level (§6) because the
  fan-phantom case proves baseline poisoning is the default outcome,
  not an edge case.
- Added §7 non-goals after noticing v1 could be read as proposing
  federation and ML — both out of scope for a single-install product.
