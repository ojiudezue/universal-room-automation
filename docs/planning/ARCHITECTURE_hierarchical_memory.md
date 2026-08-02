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
  not exist anywhere); `MemoryFacade` module (no query surface exists);
  baseline-writer job (nothing populates node-scoped baselines today).

## 1. Definition made concrete

A node's memory is: **its episodes + its baselines + its outcomes,
reachable only through the facade.** Architecturally, memory is NOT a
place — it is an ACCESS DISCIPLINE over (mostly existing) storage:

```
                 ┌──────────────────────────────┐
 any consumer →  │  MemoryFacade (5 verbs, RO)  │ → MemoryAnswer
 (node, NM,      └──────────────┬───────────────┘   {value, provenance,
  dashboard,                    │                     support, verdict}
  operator, AI)     ┌───────────┼─────────────┐
                    ▼           ▼             ▼
              memory_episodes  metric_baselines  outcome_log
              (NEW, adjudicated) (REUSED, new     (REUSED)
                    │             scopes)
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

One module, `memory_facade.py`, one class, five methods mirroring the
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
  house_state_log rows into an ordered story; the ONE verb allowed to
  touch raw logs at read time.

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
- No background summarizer daemon — the baseline writer piggybacks the
  existing cycle; narrative() computes on demand.
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
