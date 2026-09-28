# Code review — SAFETY-HUMIDITY-JUNK-READING-1 (humidity plausibility floor)

_Tier 1 (single file family, fail-safe direction), run under the overnight contract: built and reviewed to the `review` lane, **not merged or deployed**. The version gets assigned when the operator merges it into a release._

Branch `feature/safety-humidity-junk-floor`, rebased onto develop `37a66b0e7` on 2026-09-28 (0 commits behind).
Commits: `63bfb65c6` build, `dc513cac4` fix-up, `79a10d403` README section draft (`docs/planning/DRAFT_README_safety_humidity_junk_floor.md`).

## Reviews
| Review | Framing | Verdict |
|---|---|---|
| A | local correctness, edge cases, consumers | SHIP + M1 + L1 + L2 |
| B | state, lifecycle, cross-coordinator ripple | SHIP (four out-of-scope findings carded) |
| Orchestrator (09-27) | independent re-drill of the `_handle_humidity` guard | 4 named tests red, restored green |
| Orchestrator (09-28, post-rebase) | 18/18 green on the rebased branch; re-drilled the fix-up site `aggregation.py` `SafetyAlertBinarySensor._get_alerts` (guard neutered, so the value is kept) | `test_junk_humidity_no_house_alert` red; restored 18/18 green; `git status` clean |

## Findings
| ID | Severity | Bug class | Finding | Status |
|---|---|---|---|---|
| M1 | MEDIUM | Missed emission site (#53 computed-but-not-consumed, a sibling site) | The whole-house `SafetyAlertBinarySensor` (aggregation.py) had its own hard-coded `humidity < 25` check that bypassed the floor | FIXED in `dc513cac4` and drilled |
| L1 | LOW | Snapshot semantics | The zone chip blips off for about 1 s on a real trip that is followed by a junk sample | ACCEPTED (snapshot semantics) |
| L2 | LOW | Test gap: boundary | No 5.0 boundary tests at the chip / `_process_sensor` sites | FIXED in `dc513cac4` |
| Obs | LOW | Observability | No log when a value is dropped | FIXED (debug log at the early returns) |
| Out of scope | — | — | SAFETY-HAZARD-NEVER-CLEARS-1, SAFETY-RATE-DETECTOR-DEAD-WINDOW-1, SAFETY-RECONNECT-ZERO-SIBLINGS-1 | Carded |

## Summary
| Severity | Found | Fixed | Accepted/deferred |
|---|---|---|---|
| CRITICAL | 0 | 0 | 0 |
| HIGH | 0 | 0 | 0 |
| MEDIUM | 1 | 1 | 0 |
| LOW | 3 | 2 | 1 |

## Bug-class frequency / QUALITY_CONTEXT
- Missed sibling site: 1. This is the recurring "one more read site" shape, so no new class is needed.
- Candidate note (from the card's links): the **reconnect-zero** artifact, where a device emits a junk 0 while reconnecting, now appears in both humidity safety and ENVOY-STREAM-SOC-TIER-1 constraint 3.8. Worth a QUALITY_CONTEXT line once a third instance shows up.

## Not done
- The garage policy mismatch (the chip exempts garages, the coordinator still alerts) is a separate operator policy call; see `open_question_garage` on the card.
- Full-suite name-diff: run by the overnight validator. The result is recorded on the card.
