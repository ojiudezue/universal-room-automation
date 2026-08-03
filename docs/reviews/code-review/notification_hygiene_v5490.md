# Notification Hygiene (v5.49.0) — Tier 2-DB Review Record

Build 8536b06f4 (5 fixes + FIX 5 mid-flight addition), fix-up 1b99e7a31.
Three framing-disjoint reviews.

| Sev | Finding | Source | Disposition |
|---|---|---|---|
| HIGH | Operator toggle during restore window misread as restore (age gate could revert a fresh toggle) | A (+B independently as MED) | FIXED — toggles clear _restore_pending + cancel pending sync |
| HIGH | Security-ack empty-list fallback resolves to persons[0] = the SPOUSE in this household; docstring claimed "the operator" | A (orchestrator pre-flagged) | FIXED — honest comment + init WARNING naming resolved person; explicit config = mandatory deploy step; fail-loud filed B-2026-08-03-6 |
| HIGH | _is_authorized_to_ack had ZERO behavioral coverage — guard neutered to always-allow left 23/23 green | C (mutation) | FIXED — exec-driven behavioral test; builder + orchestrator re-drill red |
| HIGH | _match_safe_word had ZERO behavioral coverage — accept-any-text left 23/23 green | C (mutation) | FIXED — behavioral test; re-drill red |
| MED | Age gate could be inert on NM-restore ordering | A | FIXED — suppression origin persisted on the switch itself, earliest-wins |
| MED | Stale-suppression notice at MEDIUM could be digested for hours | A | FIXED — HIGH (force-immediate) |
| MED | Companion acks carried person_id=None → silent deny on security classes | C | ADJUDICATED+FIXED — authenticated companion = operator-grade (companion_trusted); unresolvable inbound stays denied |
| MED | Meta-test misnamed (string presence ≠ load-bearing) | C | FIXED — renamed + honest docstring |
| MED/LOW | tz hardening (B verified aware end-to-end; A hypothesized fragility) | A vs B adjudicated | HARDENED — parse_datetime + coerce |
| LOW | Safe-word source not audited | A | FIXED — route_reason encodes source+authority |
| — | "20th failure" in builder report | B verified | MISCOUNT — failing sets identical at 19 on both refs |
| — | FIX3 anchor weak (severity-swap survives string check) | fix-up disclosure | ACCEPTED — behavioral demotion coverage exists; honest smoke-not-proof docstring |

## Verified-preserved (B)
Life-safety cadence unreachable by the decay ladder (branch-order
anchored + behavioral); no new timers; 8-day-alert replay = daily
cadence from boot, no storm, no burst; kill switches honored on all
paths incl. recovery.

## Orchestrator drills
Authority always-allow → 1 red; safe-word any-text → 1 red; companion
trust broken → 1 red (own mutation). Byte-restored; 32/32 clean.

## Bug-class ledger
#62 strikes 8–9 (the two zero-coverage security predicates), caught by
reviewer C's novel mutations — the builder's own five mutation-reds
were real but aimed at the wrong lines. Countermeasure refinement: the
review prompt now requires reviewers to run mutations the builder did
NOT run; that requirement is what caught both.
