# Tier-3+1 Review Record — CameraResolver Cycle

Branch `feature/camera-resolver`: build f9f7ea553 → 17-item fix-up eb9963c63 → D-prime fixes 7f16024bf.
FIVE reviews (A-D + external-expert E, operator-mandated) + D-prime re-sweep + orchestrator drills.

## Headline findings (all fixed unless noted)
| Sev | Finding | Source | Status |
|---|---|---|---|
| HIGH×4 | Census cutover unsafe blind: flag default True, keyspace mismatch losing the staircase fusion, F2-collapse count change, dropped count-only sensors | A/B/D/E converged | FIXED: default FALSE + keyspace fix; golden-master required before flip (follow-up) |
| HIGH | Fused sensor not event-driven (stale veto evidence) | A/B/E | FIXED (subscription + lifecycle re-resolve) |
| HIGH | Stem matching broken 3 ways (base_head, substring fallback, prefix collisions) | A/D/E independently | FIXED (full-base word-boundary) |
| HIGH | Built OR-fusion regressed to max-wins vs our own doctrine | E (literature-grounded) | FIXED (confidence/agreement-gated veto leg + same-family downgrade) |
| HIGH (test) | F1/F2/F3/cross-camera safety claims not load-bearing (order-shielded, broken fixture) | C drills | FIXED (order-inversion variants, rebuilt F2 fixture — all now red under mutation) |
| HIGH | D'-HIGH-1 census caller missed Fix#7 (booby-trapped cutover flag: AttributeError→silent legacy) | D-prime | FIXED (flatten + state_getter) |
| HIGH | D'-HIGH-2 single-integration rooms locked out of veto camera leg | D-prime | ADJUDICATED per v5.43.0 precedent: divergence = DISAGREEMENT; single_source (uncontested) grants, split denies. 4 gate tests, drill-anchored (orchestrator found the gate untested, wrote+drilled the tests) |
| MED | Deterministic F2 winner; sticky-wrong winner on host recovery | A + D-prime | FIXED (live-state rank + dropped-sensor recovery re-resolve) |
| MED | Multi-select → N fusions (attribution) | D | FIXED (list return, all callers migrated incl. census) |
| MED/LOW | slugify, sticky face, format_mac, (integration,key) identifiers, package filter frigate-gated, options-surfaced D4 kill switch, dry-run early-return, strip-on-miss, dead-branch annotation | various | ALL FIXED |
| — | Doctrine full scorer (DS/weighted), MAC/identifier live consumers, post-gate family half-weight | E | PARKED with E's evidence triggers (in plan) |

## What ships live vs dark
LIVE: resolver primitive (all rungs, synthetic-tested), event-driven fused room sensor, divergence-aware veto camera leg, D4 dry-run inventory (no actuation — grep-guardrail test proves zero switch calls). DARK: census cutover (CENSUS_USE_NEW_RESOLVER=False until golden-master diff artifact lands); F1↔F2 corroboration (72h stability gate, earliest ~Aug 4); D4 live enable (CAMERA_AUTOENABLE_DRY_RUN=True).

## Verification
Builder drills (per-rung + F1-F4 + face + dry-run), C re-execution (found 4 hollow anchors → closed), orchestrator personal drills: stem-match neuter → red; divergence gate neuter → found UNTESTED → wrote 4 gate tests → re-drill red → restored. Suite: 70/70 cycle tests; full suite 7901 passed / 32 failed = baseline byte-identical.
