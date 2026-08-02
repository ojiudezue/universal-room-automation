# v5.47.0 — Hierarchical Memory MVP (Stage 1)

## What this is
The first build of entity-owned memory: rooms, zones, the house, and
coordinators each own their history — episodes (adjudicated events),
baselines (context-conditioned normality), outcomes, identity, and
consolidated facts — behind one read-only seven-verb facade
(`baseline / unusual / episodes / outcome / narrative / profile / facts`),
per docs/planning/{VISION,ARCHITECTURE,MVP}_hierarchical_memory.md.
Stage 0 hand-built one month of Study A memory
(AUDIT_memory_handbuild_study_a.md) and is the acceptance fixture.

## Ships live
- **Tables**: `memory_episodes` (adjudication + retro-correction columns,
  60s per-(node,type) dedup), `memory_facts` (supersession lineage;
  seeded F1–F4 from the audit, idempotent). All reads on the READ pool.
- **Episode writers ×4**: D2 demotion (occupancy_phantom, retro-
  adjudicating), fan-transition gate suppression, comfort-fan away-veto,
  sensor_dropout (hooks existing unavailable-entities tracking). Each
  stamps house_state; exception-contained off the hot paths.
- **Baseline writer**: 5-min Welford fold (variance-decaying at cap) for
  a 6-room allowlist (Study A first), phantom-window quality gate
  (suppressed/demoted rooms excluded from folds), CDT context bins ×
  home/away/sleep. House-wide only after live write-volume check.
- **Facade**: 7 verbs, MemoryAnswer (verdict/support/provenance/as_of),
  tier-scoped access policy (unknown callers DENIED), context fallback
  ladder, kill switch. profile() = complete declared-capability registry
  × honest enablement (None=unknown, never fabricated) × actionable-now
  for concrete actuators.
- **Consumers (zero actuation)**: NM humidity/CO2/TVOC severity
  conditioning (one-notch dampening when normal-for-context; safety
  classes untouchable; OFF during boot window;
  `switch.ura_memory_nm_conditioning`) and `unusual_today` attr on
  occupied sensors (allowlist rooms).
- **Surfaces**: `sensor.ura_memory_status` (episode/fact/baseline counts,
  fold cadence — the write-volume watch) and service
  `universal_room_automation.memory_query` (MemoryAnswer JSON — the
  operator/AI door).

## Deferred with triggers (architecture keeps the mature designs)
Compactor (distill/correct/redact) at 50+ episodes/type; adjacency
derivation + roll-up surfaces per architecture §10; outcome() beyond the
read stub; any memory-driven actuation (memory-ineligible list enforced).

## Review
docs/reviews/code-review/memory_mvp_tier2db.md — 3 framing-disjoint
reviews, 5 HIGH + 9 MED found and fixed (incl. reads-on-write-queue and
a fabricating profile()); orchestrator drills caught a fifth #62 strike
(hollow quality-gate test) and repaired it. 32 memory tests; full suite
7962/30 baseline, zero drift.

## Live Validation — prospective
- **Live:** clean boot; `sensor.ura_memory_status` present with F1–F4
  facts and zero episodes; no memory-related WARN/ERROR.
- **Live (canonical demo):** `memory_query` verb=narrative
  node=room:study_a for 2026-08-01 returns the fan-incident story with
  house-state context and provenance.
- **Live:** `memory_query` verb=facts node=room:study_a returns F1–F4;
  verb=profile returns capability ladder with honest enablement.
- **Live:** baselines appear for allowlist rooms within 3 fold cycles;
  `unusual_today` populated on Study A within 24h.
- **Live:** write-queue depth unchanged (±10%) after one full day —
  gates house-wide allowlist expansion.
- **Organic:** next D2 demotion writes + retro-adjudicates an episode;
  first NM conditioning event logged (dampen or insufficient-history
  breadcrumb).
