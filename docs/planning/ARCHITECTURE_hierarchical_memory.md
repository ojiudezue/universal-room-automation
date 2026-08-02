# ARCHITECTURE — Hierarchical Entity Memory (min-medium build)

Status: DRAFT v2 (self-critiqued, finalized 2026-08-02). Downstream of
`VISION_hierarchical_memory.md`; read that first. Sized deliberately:
enough structure to be reviewable and extensible, no speculative layers.

## Institutional context verified

- **REUSED `metric_baselines`** (database.py:1050) — schema is already
  `(coordinator_id, metric_name, scope)` with mean/variance/sample_count.
  The `scope` column carries node identity today for energy circuits;
  room/zone/house nodes are new scope VALUES, not a new table.
- **REUSED `outcome_log`** (database.py:1065) — coordinator_id + scope +
  metrics_json; already the outcome-memory substrate.
- **REUSED `anomaly_log`, `decision_log`, `occupancy_events`,
  `house_state_log`, `zone_events`, `room_transitions`** — episodic raw
  material; none carry adjudication (verified: no adjudication/verdict
  column in any).
- **REUSED `BayesianPredictor`** (bayesian_predictor.py) — time-binned
  room occupancy priors with restore path; it IS baseline memory for one
  signal and should eventually serve `baseline()` for occupancy rather
  than being duplicated.
- **REUSED write-queue discipline** (database.py managed batched queue;
  write-flood incident 2026-06-09 is the binding constraint on any new
  write cadence).
- **Prior planning consulted:** PLANNING_v4.6.5_in_memory_anomaly_
  persistence.md (anomaly persistence shape), PLANNING_paper_and_oss_
  fusion_library.md (this interface is its likely spine).
- **NEW (justified below):** `memory_episodes` table (adjudication does
  not exist anywhere); `memory_facts` table + daily compaction batch
  (no consolidation/redaction exists; vibememo-inspired, see §5c);
  `MemoryFacade` module (no query surface exists); baseline-writer job
  (nothing populates node-scoped baselines today). Vibememo consulted
  (.vibememo/FORMAT.md) for the compaction doctrine: synthesis is the
  artifact, why-provenance compressed last, archive-never-delete.

## 1. Definition made concrete

A node's memory is: **its episodes + its baselines + its outcomes +
its identity-change record + its consolidated facts, reachable only
through the facade.** Architecturally, memory is NOT a
place — it is an ACCESS DISCIPLINE over (mostly existing) storage:

```
                 ┌──────────────────────────────┐
 any consumer →  │  MemoryFacade (7 verbs, RO)  │ → MemoryAnswer
 (node, NM,      └──────────────┬───────────────┘   {value, provenance,
  dashboard,                    │                     support, verdict}
  operator, AI)     ┌───────────┼─────────────┐
                    ▼           ▼             ▼
              memory_episodes  metric_baselines  outcome_log
              + memory_facts   (REUSED, new     (REUSED)
              (NEW)             scopes)   + config/registries (live,
                    │                       for profile())
                    ▼
              existing logs + HA recorder (raw tier, consulted
              lazily for narrative(); never duplicated)
```

## 2. Node identity

`node_id` is a string with tier prefix: `room:study_a`, `zone:upstairs`,
`house`, `coordinator:energy`. It slots into the EXISTING `scope` /
`coordinator_id` columns — no schema migration for reused tables.
Hierarchy is resolved by the facade (a zone query fans out to member
rooms + the zone's own rows), not materialized in storage: roll-up
summaries are computed on read and cached in-process, because
pre-aggregated zone rows would be a second source of truth to keep
consistent (rejected).

## 3. The facade (the only door)

One module, `memory_facade.py`, one class, seven methods mirroring the
vision verbs. Sync, read-only, in-process (same pattern as existing DAO
reads). Every method returns a `MemoryAnswer`:

```python
@dataclass(frozen=True)
class MemoryAnswer:
    verdict: str          # "ok" | "insufficient_history" | "no_data"
    value: Any            # verb-specific payload; None unless ok
    support: int          # sample count / episode count behind the answer
    provenance: list[str] # e.g. ["metric_baselines:room:study_a:humidity:h14_home_day"]
    as_of: datetime
```

Power lives inside the verbs, not in more verbs (operator-ratified
constraint):
- `baseline(node, signal, context)` — context is a small frozen dict
  (hour_bin, house_state, season); the facade quantizes and falls back
  up a declared ladder (exact context → drop season → drop house_state
  → all) with the fallback recorded in provenance.
- `episodes(node, pattern, window)` — pattern is a registered episode
  TYPE + optional attribute filters, not free-form matching.
- `unusual(node, window)` — z-score style deviation vs own baseline,
  ranked; support threshold gates emission (below it → verdict
  insufficient_history).
- `outcome(node, decision_type, window)` — reads outcome_log; pairs
  predicted vs realized where both exist.
- `narrative(node, window)` — merges episodes + decision_log +
  house_state_log rows into an ordered story, citing facts for context;
  the ONE verb allowed to touch raw logs at read time.
- `profile(node)` — live composition/capability read (§5b); no storage.
- `facts(node, topic?)` — consolidated tier read (§5c); current facts
  by default, lineage on request.

Interface change control: the verb set and MemoryAnswer shape are
versioned in one place and reviewed like the signal bus (shared
primitive, Tier 2-DB minimum for any change).

## 4. Episodic tier — the one new table

```sql
CREATE TABLE memory_episodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id TEXT NOT NULL,
    episode_type TEXT NOT NULL,      -- registered vocabulary, e.g.
                                     -- occupancy_phantom, fan_adopted,
                                     -- sensor_dropout, hvac_retreat
    started_at TEXT NOT NULL,
    ended_at TEXT,
    adjudication TEXT NOT NULL DEFAULT 'unadjudicated',
        -- unadjudicated | confirmed | phantom | operator_override | ...
    adjudicated_at TEXT,
    adjudicated_by TEXT,             -- mechanism name or 'operator'
    attrs_json TEXT NOT NULL DEFAULT '{}',
    source_ref TEXT                  -- pointer into the raw log it came from
);
CREATE INDEX idx_episodes_node_type ON memory_episodes(node_id, episode_type, started_at);
```

Writers: (a) the node's own mechanisms at event time (a D2 demotion
writes `occupancy_phantom` adjudicated `phantom` and retro-adjudicates
the creation episode it corrects); (b) an operator adjudication path
(service call) for manual verdicts. Episode types are a REGISTERED
vocabulary in const-land — adding a type is a reviewed change, which is
the write-quality gate in practice. All writes go through the existing
write queue; episodic events are low-rate by construction (they are
notable events, not samples).

## 5. Baseline tier — reuse + one writer

`metric_baselines` gains node scopes (`room:study_a`), context-qualified
metric names (`humidity:h14:home_day`), and a single **baseline writer**:
one batched job on the existing 5-minute strategy cycle that folds
current samples into (mean, variance, count) via Welford update — one
UPSERT batch per cycle, well inside write-queue budget (verified against
the write-flood postmortem: batch size = rooms × tracked signals ≈ 200
rows/cycle max, versus the incident's per-row-per-cycle flood pattern).
Contexts quantized coarse on purpose: 3-hour bins × house-state-family
(home/away/sleep) × season. Finer bins multiply rows and dilute support;
coarse bins with honest support counts beat fine bins with none.
Decay: exponential via sample-count cap (Welford with count clamp), so
baselines track season drift without a scheduled forgetting job.
Quality gate: samples tagged by an active suppression/demotion/veto in
that room-window are EXCLUDED from baseline folding (the fan-phantom
lesson, structurally enforced).

## 5b. Identity tier — profile() reads live, episodes record change

`profile(node)` is computed from config entries + registries at call
time and answers BOTH halves:

**"What do I contain"** — composition: configured sensors/actuators per
bucket (room), member rooms + thermostat (zone), zones (house).

**"What can I do"** — capability, three layers multiplied together:
1. *Declared* — a static capability registry per node type, code-owned:
   which mechanisms exist (room: lighting, comfort-fan w/ away-veto +
   D2 + transition gate, humidity-fan, covers, night-light; coordinator:
   its decision/action surface — e.g. energy: reserve strategy, TOU
   arbitrage, load proposals). This is the piece config alone cannot
   answer and the reason profile() is not just a config echo.
2. *Enabled* — the live enablement state of each declared mechanism
   (master switches, observation mode, per-feature toggles, kill-switch
   constants).
3. *Actionable now* — whether the actuators behind an enabled mechanism
   are currently available (the AV-Closet lesson: a dead actuator makes
   a capability nominal; profile() surfaces "can, but actuator
   unavailable" distinctly).

**"Who is around me"** — locality, two senses (operator addition):
- *zone locality*: member/sibling rooms from Zone Manager config (live
  read; already the §8 visibility key).
- *self locality*: physical neighbors, resolved by ladder — operator-
  declared adjacency (optional config, wins if present) → derived from
  `room_transitions` statistics (probe-validated 2026-08-02: 273k rows,
  symmetric pair counts, physically sane graph; the table's path_type/
  via_room columns mean routes, not just hops, are derivable) → BLE
  co-visibility as tie-break. Derived adjacency is recomputed by the
  daily compaction batch and stored as a house-level fact
  (topic: adjacency_graph) with derived_from support counts — so it
  self-corrects after a remodel and carries provenance like everything
  else.

**Locality is NOT a query-permission boundary (considered, rejected).**
Permission stays tier-scoped per §8. Rationale: (a) the proven
cross-node use case (systemic-vs-local, Q1 in the Stage-0 audit) needs
zone/house reach that adjacency would wrongly deny; (b) permission
derived from a learned graph means a statistics shift silently changes
security posture — policy must not float on data; (c) zone-sibling
scope already bounds coupling. Locality is an ANSWER (profile content,
narrative context), and later possibly a fusion FEATURE — transit
plausibility: occupancy appearing with no preceding neighbor activity
is suspect (the 08-01 Study A phantom had exactly this signature).
That feature is PARKED behind the memory-ineligible discipline (§8:
occupancy decisions stay live-evidence) with evidence trigger: if
post-v5.46.0 phantoms still occur, transit plausibility is the next
corroborator to evaluate.

So a coordinator's profile is dominated by the "can do" half (its
contain half is thin), a room's carries both plus locality, and the
answer distinguishes designed / enabled / currently-actionable — which
is exactly the triage ladder of every "why didn't X happen" diagnosis.

NO new storage — duplicating config into memory would create a second
source of truth. What memory
OWNS is change: a `config_changed` episode (registered type) written on
options-update/reload with a before/after delta in attrs. "What do I
contain" = live read; "when did that change" = episodes.

## 5c. Consolidated-facts tier — the anti-logging layer (vibememo-inspired)

```sql
CREATE TABLE memory_facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id TEXT NOT NULL,
    topic TEXT NOT NULL,             -- registered, e.g. occupancy_reliability
    statement TEXT NOT NULL,         -- human-readable, citable
    attrs_json TEXT NOT NULL DEFAULT '{}',  -- structured form
    confidence REAL NOT NULL,
    derived_from TEXT NOT NULL,      -- episode ids / baseline keys (the WHY)
    created_at TEXT NOT NULL,
    superseded_by INTEGER            -- lineage; facts are never deleted
);
```

**Compaction cycle** (the vibememo move): a low-frequency batch job
(daily, on the existing scheduler — no new loop) that:
1. **Distills** — rule-based, transparent: N+ same-type adjudicated
   episodes on a node within a window → propose/refresh a fact, with
   derived_from carrying the episode ids. No ML; distillation rules are
   registered per episode type alongside the type itself.
2. **Corrects** — a fact contradicted by newer evidence (adjudication
   distribution shifted, config_changed invalidates premise) is
   superseded, not edited: new row, superseded_by back-link. Lineage IS
   the correction history.
3. **Redacts** — episodes older than the redaction horizon whose type
   has been distilled compress to rollup rows (type, count, span,
   adjudication distribution); attrs dropped. The why survives in the
   fact's derived_from; the bulk does not survive in the table. Bounded
   growth, auditable compression.

`facts()` and `narrative()` read this tier; `narrative` cites facts for
context and episodes for sequence.

## 6. Outcome tier — reuse as-is

`outcome_log` already carries (coordinator_id, scope, metrics_json).
The facade's `outcome()` reads it; the only addition is the convention
that predictions log a row at prediction time and the realizing
mechanism updates/pairs it. No schema change in the min-medium build;
pairing lives in metrics_json.

## 7. What is deliberately NOT in this architecture

- No zone/house materialized aggregates (computed on read).
- No new query language, no free-text search, no embeddings.
- No memory-driven ACTUATION path — consumers in phase 1 are NM
  severity/suppression, diagnostics, dashboard, and the operator/AI via
  a read-only service. Actuation gating on memory is a later, separately
  reviewed trust change (vision §6).
- No background summarizer daemon beyond the daily compaction batch on
  the existing scheduler; narrative() computes on demand.
- No LLM in the compaction loop — distillation rules are registered,
  transparent statistics (the session AI may PROPOSE facts via the
  operator adjudication path, but the cycle itself is deterministic).
- No retention machinery beyond: episodes are small and kept; baselines
  are fixed-size by key; raw logs keep their existing policies.

## 8. Access policy — hierarchy constraints + memory-ineligible decisions

(Operator addition 2026-08-02: "hierarchy constraints if it made sense,
or decisions that cannot be made from queries or lookups.")

**Query-visibility constraints, by consumer tier.** "Any node can query
any node" is the capability; policy narrows it to what each tier has
legitimate standing to know, enforced in the facade (one check, node_id
prefix vs caller identity):

| Caller | May query |
|---|---|
| Room | Itself; its siblings within the same zone (differential diagnosis); the house (context) — NOT arbitrary distant rooms, NOT coordinators |
| Zone | Itself; its member rooms; sibling zones; the house |
| House | Everything below it |
| Coordinator | Any node in its domain of action (presence → all; energy → energy-relevant scopes; etc.) |
| NM / diagnostics / dashboard / operator / AI service | Everything (read-only observers) |

Rationale: the one cross-room use case with proven value (am-I-the-only-
one) is zone-local; unrestricted room→room queries buy no identified
capability and create exactly the invisible-coupling surface §6 of the
vision warns about. Widening a cell in this table is a reviewed change.

**Memory-ineligible decisions.** Some classes must NEVER take a memory
answer as an input, regardless of confidence — enumerated, enforced by
review (and greppable, since all memory access goes through the facade):

1. **Safety actions** — hazard detection/response acts on live signals
   only; "this smoke sensor false-alarms a lot" may inform notification
   TONE, never suppression of the response.
2. **Security arming/disarming** — never keyed off historical patterns
   ("usually home by now" must not disarm anything).
3. **Occupancy creation/release** — live-evidence fusion only. Memory
   may annotate confidence and trigger review, not flip presence. (A
   room "usually empty at 2pm" must never out-vote a live sensor.)
4. **Anything on the reserve-floor/clamp invariant surface** (Tier 3
   territory) — memory-informed strategy proposals route through the
   existing decision paths and their clamps; memory never bypasses.

The common principle: memory adjusts *interpretation and attention*
(confidence, severity, explanation, what to investigate); live evidence
decides *action*. Promotion of any decision class out of this list is a
Tier 3 review by definition.

## 9. Failure containment

- Facade import/read failure → consumers receive `no_data` verdict and
  proceed exactly as today (facade is additive by construction).
- Baseline writer failure → baselines go stale; support counts and
  `as_of` expose staleness to consumers; nothing downstream breaks.
- DB unavailable → same degradation path as every existing DAO read.
- Kill switches: `MEMORY_FACADE_ENABLED` (all verbs return no_data),
  `MEMORY_BASELINE_WRITER_ENABLED`, per the Numbers-Get-Knobs ladder
  (rung 1 constants; promotion to entities only if operator tuning
  proves warranted).

---

## Critique applied before finalizing (v1 → v2)

- v1 had a `memory_baselines` NEW table; killed after re-reading
  metric_baselines' actual schema — its (coordinator_id, metric_name,
  scope) triple already fits node-scoped, context-qualified keys.
  One less table, one less migration, one less Tier 2-DB trigger.
- v1 materialized zone roll-ups nightly; rejected as a second source of
  truth (and a silent-divergence bug class). Compute-on-read + cache.
- v1's baseline writer subscribed to state-change events (sample per
  change); rewritten to fold on the existing 5-min cycle after checking
  the write-flood postmortem — event-cadence writes are exactly the
  incident's shape.
- v1 let `episodes()` accept attribute regexes; narrowed to registered
  types + equality filters (query-creep discipline from the vision).
- v1 omitted the phantom-exclusion quality gate from baselines; promoted
  from "note" to structural rule after checking it against the fan
  incident timeline (the 4h phantom would have contributed ~48 poisoned
  samples to the away-context occupancy baseline).
- Sizing check (min-medium test): one new table, one new module, one
  batched writer, zero migrations of existing data, zero new loops or
  listeners beyond a cycle hook. Under-build risk checked the other
  way: adjudication + provenance + fallback ladder are all present —
  the three things whose absence would make it a toy.
- v2 addition (operator, mid-review): §8 access policy. Two operator
  prompts folded in — tier-scoped query visibility (rooms see zone
  siblings, not the world) and an enumerated memory-ineligible decision
  list (safety, security arming, occupancy flips, clamp-invariant
  surfaces). Both are policy in ONE chokepoint (the facade), so they
  are cheap now and expensive to retrofit — the right time is first
  version.
