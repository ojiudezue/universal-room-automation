# Tier 2-DB Review Record — Census Fusion Policy (divergence-aware confidence)

Branch `feature/census-fusion-policy`: build 2d29885dd → fix-up 1c93ef6d8. Autonomous cycle (raised mandate). Invariant: a lone uncorroborated single-source unidentified count, contradicted by a second covering source, can never alone flip house state to GUEST.

## Findings
| ID | Sev | Finding | Status |
|---|---|---|---|
| A-C1 | CRIT | Zone-corroboration limb dead code (`.name` compare vs plain-string ZonePresenceMode) — suppressed REAL occupants' census | FIXED (direct string compare + contract comment) |
| A-C2 / C-G1 | CRIT/HIGH | Bundle assembly + zone limb + raise-path fail-direction untested (compound-expression gap) | FIXED (T8/T9/T10; T8 proven red against pre-fix code) |
| B-HIGH-1 | HIGH | Stale face-ID corroborates indefinitely (no freshness gate) — would silently restore max-wins in the target evening-phantom shape (Bug Class #7) | FIXED (`_get_face_recognized_persons_fresh` wrapper, corroboration-only; T11/T12; orchestrator drill red) |
| A-H1 | HIGH | Snapshot-accessor drift silent (limb could re-die invisibly) | FIXED (once-per-instance WARN post-settle) |
| C-G2 | MED | Symmetric divergence branch unfenced (mutation D green) | FIXED (T7; both branches now via shared helper — drill proves) |
| A-M1/M3, A-L2, C-G3 | MED/LOW | Branch dedup, explicit-kwarg comment, narrowed except, drill docstring | FIXED |
| B-MED-1/2 | MED | Corroboration coarseness: house-wide BLE + mmWave-held zones can cross-corroborate phantoms | ACCEPTED-DOCUMENTED (README trade-offs; QUALITY_CONTEXT candidate) |
| A-M2, B-LOW-1 | LOW | Per-call knob read (kept for freshness), perf micro-move | DECLINED/DEFERRED with reasons |

## Trade-off (Review B enumeration, on record)
A perfectly-still single-platform-detected person with no face/BLE loses ONLY the guest-flip; unexpected-person sensor, perimeter alerting, raw person_count entities, and NM paths are all census-policy-independent (verified). A moving person self-corroborates via zone occupancy.

## Mutation verification
Builder: 3 drills (C1-revert→T8 red; helper neuter→5 tests red; freshness bypass→T11 red). Reviewer C: 5 mutations (2 gaps found→closed). Orchestrator (personal): freshness-gate neuter → `test_stale_face_does_not_corroborate` red → restored 12/12.

## Suite
12/12 cycle tests; full suite 7828 passed / 32 failed = baseline, zero drift.

## QUALITY_CONTEXT candidates
- Compound-corroboration expressions: every limb needs its own test (a dead limb in an `or`-bundle is invisible to aggregate tests).
- Plain-string constant classes vs Enum `.name` access (A-C1 class).
