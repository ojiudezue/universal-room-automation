# Tier-2 Review Record — Exterior-Person Escalation (NM class + house-state severity + snapshots)

Branch `feature/exterior-person-escalation`: build 6bc9f1d10 → fix-up 312fb329c → orchestrator fixes 459ea6cec + e1f35a581.

## Findings
| ID | Sev | Finding | Status |
|---|---|---|---|
| A-H1 | HIGH | Relative snapshot URLs — Pushover/WhatsApp attachments 404 (they fetch from their servers) | FIXED (external_url→internal_url normalization at source) |
| B-HIGH-1 / A-M3 | HIGH | Delayed dispatch untracked; teardown/shutdown race | FIXED (tracked handles + active/stopping guards) |
| B-HIGH-2 | HIGH | Boot first-state fire (old_state=None) → spurious CRITICAL page every restart during live detection | FIXED (rising-edge only + 30s perimeter settle gate) |
| A-M1 / B-MED-1 / C-a | MED | Cooldown reserved before dispatch success → failed dispatch mutes camera 5 min (wrong direction for security) | FIXED (reserve-after-success + in-flight burst guard + concurrency test) |
| A-M2 | MED | Frigate event cache unfiltered by label → car snapshot on person alert | FIXED (person-label filter + end-event clear) |
| C-mut-d | MED | Severity-resolver exception DROPPED the alert (docstring claimed fail-safe CRITICAL) | FIXED (try/except → CRITICAL + WARN) |
| ORCH-62 | HIGH (test-infra) | B-HIGH-2 tests drove a TEST-FILE REPLICA of the gate — production mutation stayed green (Bug Class #62, 4th strike this week) | FIXED (gate extracted to production `_on_perimeter_event`; replica deleted; mutation now 2 red) |
| ORCH-dt | MED (test-infra) | Full-suite dt-mock pollution swallowed real-method dispatches | FIXED (module-pinned clock + clock-derived fixtures) |
| B-MED-2 | MED | home_evening=LOW is DND-suppressible at quiet-hours overlap | ACCEPTED-DOCUMENTED (README) |
| A-L1 | LOW | Camera-name string-strip may miss renamed entities (graceful degradation) | DEFERRED (CameraResolver subsumes) |

## Cleared by review (load-bearing)
CRITICAL bypasses DND (2am case intact); NM dedup keyed per-camera (no cross-camera eating); all 15+ async_notify callers back-compat; severity map complete over all 9 states + unknown→CRITICAL; egress suppression byte-preserved.

## Mutation verification
Builder: 5 drills. Reviewer C: 5 adversarial (2 gaps → closed). Orchestrator: boot-gate neuter (caught the #62 replica: 0 red pre-fix → 2 red post-fix).

## Suite
41/41 cycle tests (isolated AND in-suite, both orders); full suite 7869 passed / 32 failed = baseline, zero drift.
