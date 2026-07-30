# URA v5.36.1 — DND digest-row fix + never-zero stuck rule + D1 test authority

Tier-1, two evidence-driven fixes on this week's surfaces + a test-authority repair.

## Fixes
1. **DND no longer drops digest rows.** The per-recipient quiet-hours veto ran BEFORE
   digest queueing → any sub-HIGH alert during DND (22:00–07:00) was LOST, not
   deferred (evidence: the watchdog's 00:00 camera_stuck emit → 0 notification_log
   rows → two mornings of empty digests). Digest-pref recipients now queue rows
   through DND (queue-writes interrupt nobody); immediate-pref DND skip unchanged;
   CRITICAL/HIGH + life-safety semantics byte-identical. Mutation-anchored.
2. **D1 "never-zero" sibling rule.** The unchanged-≥3h rule resets on ANY value
   change — an oscillating phantom evades it indefinitely (evidence: playroom
   count toggling 1↔2 held GUEST for 30h; A-MED-1 accept-note now cashed in).
   New rule: count continuously >0 for ≥ STUCK_CAMera_NEVERZERO_HOURS (6.0, rung-1;
   longer than 3h because sustained legit occupancy can legally hold non-zero) with
   zero interior corroboration → same discount+notify path, `rule` tagged in
   diag/NM, corroboration resets the window. Mutation-anchored.

## Test-authority repair (Bug Class #62, 3rd recurrence — found in orchestrator verification)
All D1 tests (v5.35.0 originals AND the new ones) drove test-file REIMPLEMENTATIONS.
Replaced with `_run_real_d1`: AST-extracts the production `_watchdog_stuck_cameras`
source at test time and drives it against a stub self — **verified by mutating
production** (never_zero branch → test fails; restored → 124/124 pass). QUALITY_CONTEXT
recommendation: #62 checklist line is now load-bearing ("does each behavioral test
import/extract the production symbol it claims to test?").

## Live Validation
- H1: clean boot; digest_channels un-stales on this restart (first multi-channel
  digest → WhatsApp + iMessage at next flush WITH content).
- H2: next sub-HIGH alert during DND appears in the morning digest (not lost).
- H3: an oscillating stuck camera (if recurring) is caught ≤6h by rule=never_zero.
