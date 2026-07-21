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

## Live Validation — Validated 2026-07-20 (restart, boot 20:42 CDT)

| # | Criterion | Result | Observed evidence |
|---|---|---|---|
| L1 | CM loads; no URA ERROR logs post-restart | PASS | Zero URA ERROR lines after the 20:42:55 boot across 9+ min of runtime. House state `away → arriving → home_evening` by 20:43:55; EC `self_consumption` at 20:42:25. All coordinators emitting. |
| L2 | Defaults active, no behavior change vs v5.24.0 | PASS | Validated 2026-07-21 ~17:45 CDT: notification_log = 0 rows in trailing 26h (live DB query; target ≤6) — zero outdoor-humidity rows, zero optimizer rows outside digest. notifications_today sensor = 0. Zero URA ERROR lines in log. |
| L3 | Knob options save applies without CM reload, next tick | PENDING-OPERATOR | Needs a UI options save; verify via sibling-entity last_changed invariant when first exercised. |
| L4 | Optimizer HIGH defers to digest (empty allowlist) | PENDING-ORGANIC | Awaits next optimizer HIGH finding. |

Boot-only transients seen and dismissed: five `DB write worker did not
process request within 35s` errors at 20:37–20:39, all BEFORE the new
instance's 20:42 boot — old-instance shutdown-phase stall (write queue
cannot drain during teardown). Zero recurrence in steady state; not the
write-flood signature (no per-cycle growth, no watchdog).

**Deploy incident (process, not code):** the initial v5.25.0 release was
cut codeless — deploy.sh ran while HEAD was on `build/nm-cycle-a2`
(second occurrence of the deploy-from-feature-branch trap; v5.8.0 was
the first). Recovered in place: recovery merge 934f4e3c → PR #435 →
tag v5.25.0 force-moved to master tip e8a091ab; installed tree verified
to contain A-2 code (grep of live mount) BEFORE restart. Follow-up filed:
deploy.sh should refuse to run when HEAD ≠ develop.
