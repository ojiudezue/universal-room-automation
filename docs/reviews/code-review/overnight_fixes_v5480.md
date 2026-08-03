# Overnight Incident Fixes (v5.48.0) — Review Record

Two branches, five framing-disjoint reviews, one combined deploy.
Incidents: 2026-08-03 occupied-bedroom fan sweeps (spurious 6AM home_day
promotion + adoption-without-cooldown + fan_control switch restore
resurrection since 7/29) and the overnight small-fix set (3.4W z=10.4
anomaly, 15x away<->arriving flapping, 6-day silent NM suppression).

## Findings (consolidated)
| Sev | Finding | Source | Disposition |
|---|---|---|---|
| HIGH | Trio broke the 08-01 incident-replay guard (builder's zero-new-failures claim hid it in flaky churn) | trio-B | FIXED — guard split to pin BOTH sweep boundaries |
| HIGH | FIX-A restore tests anchor-only; reviewer mutation on the apply line left all green | trio-B | FIXED — behavioral tests, builder + orchestrator mutation-red |
| CRIT-class (#62 strike 6) | Arriving-cooldown tests 100% replica/anchor — production gate neutered, 13/13 stayed green | sf-C | FIXED — bypass predicate extracted to production method, tests drive it; orchestrator re-drill red |
| CRIT-class (#62 strike 7) | Abs-floor tests dead on collection (mock-table ImportError) — mutation invisible | sf-C | FIXED — mock repaired, 31 dead tests revived (0 revealed failures), AND->OR mutation red |
| MED | Cooldown bypass omitted egress-camera evidence class (real-arrival latency risk) | sf-A | FIXED — arming narrowed to outdoor-only-evidence collapses; exterior bypass deferred w/ rationale |
| MED | Cooldown counters unsurfaced (no live-validation signal) | sf-B | FIXED — 3 attrs on house-state sensor |
| MED+LOW x6 | conflict-episode noise on operator global-off; slugify duplication; docstring honesty; boundary comment; import hoist; breaker-trip safety trace (clean) | A/B/C | ALL FIXED or verified-clean |

## Orchestrator drills (personal)
Trio: apply-line neuter -> 5 failed. SF: gate neuter -> 2 failed;
abs-floor AND->OR -> 1 failed. All byte-restored.

## Bug-class ledger
#62 strikes SIX and SEVEN this week, both by reviewer C mutations.
Pattern across all seven: anchors/replicas/dead fixtures pass without
production. Standing countermeasure now in build contracts: builders
must run the adversarial mutation and see red BEFORE finalizing —
applied in both fix-ups this cycle and it worked.

## Suite
Final: 19 failed / 8029 passed — best baseline recorded (31-test
revival + replay-guard recovery). Zero new deterministic failures.
