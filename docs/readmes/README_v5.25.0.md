# URA v5.25.0 — NM Cycle A-2: Volume-Reduction Knob Surface

Promotes NM Cycle A's noise thresholds to operator-facing rung-2 options-flow
knobs on the CoordinatorManager, per the product-surface directive ("We need
reasonable volume reduction knobs. This is meant to be opened to more people").
Plan: `docs/planning/PLANNING_nm_cycle_a2_knob_surface.md`. Review record:
`docs/reviews/code-review/v5.25.0_nm_cycle_a2.md` (Tier 2-DB, 3 framing-disjoint
reviews; 3 HIGH + 5 MED found, all fixed; orchestrator-verified mutation anchors).

## What ships

1. **New CM options step** `coordinator_notifications_volume` — 13 fields:
   breaker zero-window + route, lock dedup, humidity ladder (78/85/92) + swing
   delta, CO2/TVOC thresholds, sensor-exclusion blocklist (sensor +
   binary_sensor), and the A2 optimizer-HIGH allowlist (pick-list over
   optimization dimensions; empty = everything defers to digest).
   Humidity ladder validated monotonic at save (inverted entries rejected).
   Unchanged fields are NOT persisted (default-drop) so future const retunes
   reach every deployment.
2. **Live apply without reload:** all 13 keys reload-suppressed; module-level
   knob cache in `_nm_cycle_a.py` invalidated on options save AND CM entry
   setup/unload. Consumers see new values next tick. EXCEPTION: the discovery
   blocklist applies after restart (discovery-time read; labeled as such in
   the UI — forcing a CM reload would risk the known event-loop-stall hazard).
3. **A2 allowlist wired behaviorally** — `high_finding_allowlisted` /
   `should_defer_high_to_digest` helpers with L4 enum-vs-str normalization on
   both sides; empty-by-default preserved (safe default).
4. Deprecated bare `OPTIMIZER_NM_HIGH_ALLOWLIST_DIMENSIONS` retained one
   release (nothing imports it; removal next minor).

## Invariant

With no options set, behavior is byte-identical to v5.24.0 — every knob
defaults to the shipped constant. Affirmed independently by Reviews A and B;
default-path equivalence tests in `test_nm_cycle_a2_knob_surface.py`.

## Test evidence

- 7225 passed; failure set = exact pre-existing env-drift baseline (36+14).
- Mutation anchors (orchestrator re-ran personally): knob-ignores-options,
  listener-flush removal, suppress-splat removal, L4 coercion strip, gate
  bypass — each fails exactly one named test.

## Live Validation (prospective — write back observed results post-restart)

| # | Criterion | How to check |
|---|---|---|
| L1 | CM entry loads; options step reachable; no URA ERROR logs post-restart | log scan + UI |
| L2 | NM knob defaults active: no behavior change vs v5.24.0 (notification_log shape unchanged over 24h) | recorder |
| L3 | Options save of a knob (e.g. lock dedup) does NOT reload the CM entry (sibling-entity last_changed invariant) and takes effect next tick | live edit + entity check |
| L4 | Optimizer HIGH findings defer to digest (allowlist empty) | notification_log |

L3 is operator-exercised (needs a UI options save); if not exercised at
validation time, mark pending-operator.
