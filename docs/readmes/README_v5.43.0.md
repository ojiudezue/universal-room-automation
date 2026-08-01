# v5.43.0 — Census Fusion Policy: divergence-aware confidence

## What shipped
When two camera platforms cover the same interior zone and DISAGREE (one sees a
person, the other sees zero) with NO corroboration (no fresh face recognition,
no BLE person, no zone occupancy anywhere), the census now takes the MINIMUM and
marks `source_agreement="disagree"` → confidence LOW/NONE → below the guest bar.
Agreeing sources, single-source zones, and exterior census are byte-identical.
This closes the phantom→GUEST chain (3 flips on 2026-08-01 alone) and un-launders
the comfort-fan away-veto.

Corroboration bundle (any one restores legacy behavior): fresh face recognition
(freshness-gated — a stale hours-old recognition no longer counts), BLE person,
or any zone occupied.

Kill switch: `census_divergence_downgrade` (options flow, camera_census step,
default ON; OFF = byte-identical pre-cycle max-wins).

## Documented trade-offs (accepted)
- A perfectly-still person seen by only ONE platform with no face/BLE loses the
  guest-flip ONLY — unexpected-person sensor, perimeter alerting, raw
  person_count entities, and NM alerts are all unaffected (verified paths).
  A moving person self-corroborates via zone occupancy.
- Corroboration is house-wide: a lingering mmWave hold or a Bermuda BLE flap
  anywhere can corroborate a camera divergence elsewhere (phantom classes can
  cross-validate). Bounded by fan-recheck + v5.42.0 demotion; revisit if
  shipwatch shows regression.

## Review
docs/reviews/code-review/census_fusion_policy_tier2db.md — 3 reviews; 2 CRIT +
2 HIGH found and fixed (dead zone-corroboration limb; stale-face loophole);
9 mutation drills incl. orchestrator's. 12/12 tests; zero suite drift.

## Live Validation — prospective
- **Live:** replay condition organically: next playroom-class single-source
  phantom (frigate>0, unifi=0, house away) → census confidence LOW/NONE,
  `source_agreement="disagree"` in census_snapshots, NO guest flip.
- **Live:** normal guest detection unaffected: next REAL arrival (faces/BLE
  present) flips guest as before.
- **Live:** zero drift-WARNs from the zone-snapshot accessor.
