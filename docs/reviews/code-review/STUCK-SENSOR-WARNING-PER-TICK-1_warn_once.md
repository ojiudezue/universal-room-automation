# Review record: STUCK-SENSOR-WARNING-PER-TICK-1 (warn once per episode)

Tier 1 (log-level only; no behaviour ingredient). Branch `fix/stuck-sensor-warn-once`, rebased onto develop
2026-10-09 (0 behind), HEAD 33b730db4.

| # | Finding | Severity | Bug class | Status |
|---|---|---|---|---|
| 1 | Orchestrator call-neuter drill (replace the call in `_async_update_data` with `pass`) left all 37 tests green: no wire-in anchor (10-07) | HIGH (test authority) | Hollow wire-in anchor (computed-but-not-consumed, test side) | FIXED d30d5df5f: AST anchor test; re-drilled 10-09 -> 1 failed / 37 passed, restored |
| 2 | Latch comment claimed recovery on sensor clear; latch is actually cleared only at day rollover (`coordinator.py:2379`) | LOW | Stale comment | FIXED de63ff1a3 (verified against source 10-09) |
| 3 | Anchor did not pin call arguments (a wrong value would pass) | LOW | Hollow anchor | FIXED de63ff1a3 |
| 4 | After a same-day restart a still-stuck sensor logs only DEBUG, so it vanishes from the WARNING log | LOW | Observability gap | FIXED 33b730db4: boot INFO line names latched sensors |

Orchestrator verification 2026-10-09 (overnight): read the full diff. NM fire condition, latch key, exclusion
and kinds map are byte-identical to the pre-change block (moved into the helper unchanged). Targeted stuck tests
38 pass; call-neuter drill red and restored (tree clean); full-suite name-diff 0 NEW / 0 GONE (develop
149 failed baseline, unchanged).

Note on process: reviewer findings 2-4 were fixed on the branch on 10-07/08, but their review passes left no
written record. This file reconstructs them from the fix commits. Finding 1's anchor is structural (AST), not
behavioural. That is accepted for a log-level change, because the helper-level behaviour is covered separately.

| Stat | Found | Fixed | Deferred |
|---|---|---|---|
| HIGH | 1 | 1 | 0 |
| LOW | 3 | 3 | 0 |

No new QUALITY_CONTEXT bug class. Instance of the existing hollow-anchor lesson (memory `feedback_hollow_test_anchors`).
