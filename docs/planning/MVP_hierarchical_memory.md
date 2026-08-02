# MVP — Hierarchical Memory: Study A Hand-Build + Thin Facade

Status: DRAFT v2 (self-critiqued, finalized 2026-08-02). Downstream of
VISION_hierarchical_memory.md and ARCHITECTURE_hierarchical_memory.md.
Awaiting operator build approval.

## Shape: probe-first, then the thinnest honest slice

Per Measure Before You Build, the MVP is TWO stages with a kill gate
between them. Stage 0 costs a session and no code; if it fails, we
stop having spent nothing.

### Stage 0 — the hand-build (no integration code)

Construct ONE MONTH of memory for `room:study_a` (and the minimum
sibling/house context to answer cross-node queries) entirely offline
from existing data: HA recorder + URA DB (occupancy_events,
decision_log, anomaly_log, house_state_log, environmental_data).
Produce one committed artifact, `docs/planning/AUDIT_memory_handbuild_
study_a.md`, containing:

1. **The episode ledger** — every notable Study A event in July, hand-
   adjudicated (including the 2026-08-01 fan phantom chain), in the
   exact memory_episodes shape (node_id, type, adjudication, attrs).
2. **The baseline table** — occupancy rate, temperature, humidity, fan
   runtime per (3h-bin × home/away/sleep) context, computed with
   support counts, in the exact metric_baselines key shape.
3. **Five hand-answered queries**, one per consumer class, each written
   as the MemoryAnswer it would return (verdict/value/support/
   provenance):
   - Sibling room (Study B): "sensor dropouts in the same window as
     mine?" (differential diagnosis)
   - NM: "is this humidity reading unusual for this room-hour-state?"
     (severity conditioning)
   - Operator: "why did the fan run for 4 hours on 08-01?" (narrative)
   - Dashboard: "what was unusual in Study A this week?" (unusual())
   - Diagnosis session: "episodes matching occupancy_phantom in July?"
     (recurrence)

**Stage-0 pass criteria (the kill gate):** at least 3 of 5 answers are
judged by the operator to have earned their keep — concretely: would
have shortened the fan forensics, suppressed or sharpened a real July
notification, or correctly explained a real decision. Fewer than 3 →
park the whole workstream with this doc as the record; the concept
loses on evidence, not on taste.

### Stage 1 — the thin slice (only after Stage 0 passes + operator go)

Build order and scope (one Tier 2-DB cycle):

1. **`memory_episodes` table** + registered episode-type vocabulary
   seeded with exactly the types Stage 0 needed (no speculative types).
2. **Episode writers at 3 existing sites** — D2 demotion (writes
   phantom + retro-adjudicates the creation), fan-transition gate
   suppression, comfort-fan away-veto fire. All three already have the
   event in hand at write time; each is ~5 lines through the existing
   write queue.
3. **Baseline writer** — the 5-min-cycle Welford fold, Study-A signals
   first, all rooms once cadence is proven (write-volume test BEFORE
   enabling house-wide, per the write-flood postmortem).
4. **`memory_facade.py`** — all five verbs, MemoryAnswer, §8 access
   policy, kill switches. Verbs whose tier has no data yet return
   honest `insufficient_history` (the facade ships complete; the DATA
   arrives incrementally — interface stability over feature count).
5. **Two real consumers, zero actuation:**
   - NM humidity severity conditioning for bathrooms/Study A: a reading
     that is normal-for-context gets severity dampened one notch (never
     suppressed to zero; safety-ineligible list respected).
   - A per-room `unusual_today` attribute on the occupied sensor
     (dashboard + operator surface, pure annotation).
6. **Operator/AI service** — `universal_room_automation.memory_query`
   service returning MemoryAnswer JSON: makes every future diagnosis
   session a consumer on day one and gives the operator the toy to
   evaluate against Stage 0's hand-built answers.

Explicitly OUT of the MVP (parked in architecture §7 + vision §6):
zone/house roll-up verbs beyond what the five queries need (zone
fan-out ships; house aggregation waits), outcome() beyond reading
what outcome_log already holds, BayesianPredictor unification, any
memory-driven actuation, any new dashboard cards.

## How the MVP proves itself

| Claim | Proof |
|---|---|
| Interface is right-sized | The five Stage-0 hand answers reproduce EXACTLY through the facade (diff vs the hand-built artifact — it is the acceptance fixture) |
| Adjudication works | The next organic D2 demotion retro-adjudicates its creation episode within one cycle (live check, DB read) |
| Baseline quality gate works | Samples during suppression/demotion windows provably absent from folds (test: inject phantom window in fixture, assert baseline unmoved) |
| Write cadence safe | Measured rows/cycle for baseline writer under full-house load < 10% of write-queue budget, BEFORE house-wide enable |
| Consumers degrade honestly | Facade kill switch ON → NM severity and attributes byte-identical to today (regression harness) |
| Value is real, not aesthetic | ≥1 NM notification in the first live week measurably improved (dampened noise or sharpened anomaly) AND the operator uses memory_query in ≥1 real diagnosis and prefers it to raw SQL |
| Access policy enforced | Facade rejects an out-of-policy caller in test (room querying distant room) |

## Acceptance criteria (build contract)

- **Verify:** five Stage-0 queries answer identically via facade
  (fixture diff).
- **Verify:** episode retro-adjudication round-trip on organic demotion.
- **Verify:** baseline rows carry support counts; unusual() returns
  insufficient_history below threshold (test at threshold ± 1).
- **Sensor:** `binary_sensor.study_a_occupied` gains `unusual_today`
  attr; populated within 24h of deploy.
- **Test:** facade verb suite incl. access-policy rejection + kill-
  switch degradation + fallback-ladder provenance.
- **Live:** memory_query service returns a provenance-bearing answer
  for Study A narrative of 2026-08-01 evening (the fan incident is the
  canonical demo query).
- **Live:** write-queue depth unchanged (±10%) after one full day with
  baseline writer on, house-wide.

---

## Critique applied before finalizing (v1 → v2)

- v1 shipped only Study-A-scoped facade verbs; changed to full facade +
  incremental data after noticing interface-narrowing is the expensive
  thing to change later (operator-ratified constraint is verb COUNT,
  not coverage). "Wise extra" #1.
- v1 had no service call; added memory_query as "wise extra" #2 —
  near-zero cost, converts every future working session into a live
  consumer, and gives Stage-0's fixture a permanent comparison target.
- v1 deferred the NM consumer to a follow-up cycle, making the MVP
  value-free (pure infrastructure). Pulled ONE conditioning consumer in
  — the vision's top value-density item — because an MVP that changes
  no observable behavior cannot prove value claim #6.
- v1 had episode writers at 5 sites incl. HVAC retreat + sensor
  dropout; cut to 3 (the fan-trust stack) — they share one already-
  instrumented code area, and Stage 0 will tell us which further types
  earn registration. Scope-creep guard.
- Checked the "could be the Study A hand build" operator framing: kept
  Stage 0 as the hand-build exactly, but made it a kill gate with a
  numeric bar (3 of 5) instead of an open-ended exploration — probes
  need pass criteria or they always "pass".
