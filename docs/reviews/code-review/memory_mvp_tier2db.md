# Hierarchical Memory MVP (Stage 1) — Tier 2-DB Review Record (shipped v5.47.0)

Build: `feature/memory-mvp` 6ccdcad80 (builder, ~150 tool-use build with two
mid-flight operator spec changes: complete capability registry; +diagnostics
sensor +NM switch). Fix-up: dde443f16 (17 adjudicated items). Orchestrator
test repair follows.

Three framing-disjoint reviews, all FIX-THEN-SHIP, zero blockers:

## Findings (consolidated)
| Sev | Finding | Source | Disposition |
|---|---|---|---|
| HIGH | 5-min baseline listener + facade never torn down on unload (leak across reloads) | A+B independently | FIXED — entry.async_on_unload + hass.data pops |
| HIGH | Seed idempotency TOCTOU + partial-failure stranding | A | FIXED — UNIQUE(node,topic,statement) + INSERT OR IGNORE; partial-shape test |
| HIGH | ALL memory reads on the WRITE queue (v5.2.1 write-flood pattern; NM hazard bursts would stack reads on the write lock) | B | FIXED — _db_read pool for 5 DAOs + public status-counts accessor for the sensor |
| HIGH | narrative() episodes-only; comment claimed context merge that didn't exist; fixture Q3 unreproducible | C | FIXED — writers stamp house_state; narrative merges house_state_log + decision_log (read pool), degradation tagged |
| HIGH | unusual() ranked baseline dispersion, not live z-scores — fixture Q4's z→∞ finding unrepresentable; verb semantics diverged from spec | C | FIXED — live-sample z-scorer, honest inf on zero-variance deviation |
| MED | Welford count-clamp never decayed M2 → variance inflates monotonically → unusual() progressively under-flags | A | FIXED — proportional M2 shrink at cap + distribution-shift test |
| MED | profile() affirmed falsehoods (enabled=True unconditionally) | B+C | FIXED — per-mechanism toggle reads, None=unknown; actionable_now for concrete actuator lists; music_following added |
| MED | NM conditioning switch bypassed during boot (missing entity treated as ON) | B | FIXED — absent switch = no conditioning |
| MED | Unbounded per-tick episode inserts (gate/veto chatter → flood shape) | B | FIXED — 60s per-(node,type) dedup gate + test |
| MED | MEMORY_INELIGIBLE_HAZARD_TYPES listed non-existent hazard names (dead defense-in-depth) | B | FIXED — real HazardType values + operative-allowlist comment |
| MED | Unknown caller-id prefix escalated to observer (typo = full read access) | C | FIXED — deny + warn; observer explicit |
| MED | Writer-site wiring untested (DAO driven, sites not) | C | FIXED — fan_veto site-drive test; others mutation-anchored |
| MED | Coordinator query scope: code unrestricted vs doc domain-scoped | C | RECONCILED — doc updated (narrowing deferred until a coordinator consumer exists) |
| MED | Zone-sibling ALLOW path untested | C | FIXED — ZM-config fixture test |
| NEW | Fixture Q1 had no data path (no dropout writer) | C walk | FIXED — minimal sensor_dropout writer on existing unavailable-entities tracking; no systemic writer (observer-tier cross-node query answers it) |
| LOW ×5 | slugify dedup, read-DAO WARNING latch, cache-staleness comment, legacy naive-tz one-liner, insufficient-history breadcrumb | A/B | ALL FIXED (fix-lows-in-cycle) |

## Orchestrator verification
- Drill 1: neuter distant-room access denial → 1 failed. Drill 2: remove
  Welford variance decay → 1 failed. Drill 3: neuter _is_room_suppressed →
  **32 passed = HOLLOW TEST CAUGHT** (fixture returned no samples, so the
  gate was never the discriminator — dead-limb anchor, bug class #62,
  FIFTH strike this week). Repaired: real humidity sample + release leg;
  re-drill → 1 failed. All restores byte-identical.
- Fixture fidelity (review C walk, post-fix): Q2/Q5/Q6 reproducible,
  Q1/Q3/Q4/Q7 repaired this cycle; final live proof is the deploy's
  memory_query canonical demo (Study A 08-01 narrative).

## Suite
Memory suite 32/32. Full suite 7962 passed / 30 failed = pre-existing
baseline, zero drift.

## Bug-class notes
#62 fifth strike (dead-limb fixture) — caught by orchestrator drill, not
review; drills remain mandatory. New pattern worth QUALITY_CONTEXT entry:
**"reads on the write queue"** — any new DAO read defaulting to _db()
should be flagged in review (B's catch; v5.2.1 lineage).
