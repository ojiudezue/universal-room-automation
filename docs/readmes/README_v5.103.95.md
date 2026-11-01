# v5.103.95: no false "Envoy write reverted" page at the nightly Envoy drop

Card: EC-ENPHASE-CONNECTIVITY-RESILIENCE-1 (phase-2 fix-up, option A, operator-approved 2026-11-01). Plan: `docs/planning/PLANNING_ec_reserve_false_revert_fixup.md` rev 2. Tier 3: two plan reviews, four build reviews (A/B/D SHIP, C fixed), orchestrator mutation, full-suite name-diff clean. Reviews: `docs/reviews/code-review/ec_reserve_false_revert_*`. Deploy risk: LOW-MEDIUM (narrows when one CRITICAL page fires; kill switch `RESERVE_WITNESS_MEMORY_ENABLED`).

## Problem
Four false CRITICAL "Envoy write reverted" pages in 8 days, all at the nightly ~23:05 Envoy drop. The local Envoy had confirmed the commanded reserve at ~21:00; when it went unavailable, the verifier fell back to a stale cloud value (10 on 10-28/30/31) and paged.

## Fix
- When a trusted local Envoy reading confirms the commanded reserve after the command was sent, URA remembers it plus the cloud value seen at that moment (RAM only).
- A REVERTED page is skipped only while: the local reading is unavailable, the remembered value equals the current command and was seen after it, and the cloud still shows the same value as at confirmation.
- A contrary trusted local reading clears the memory (including while the record is retired); a new command invalidates it.
- One emission site changed (`energy_write_verify.py` `_sweep_surface`); `_check` and self-heal pages unchanged.

## Still pages (INV-F2)
Real revert with the Envoy up; cloud moves during an outage; never-landed command; new command during the outage; restart during the outage (memory empty, same as today). A revert to exactly the stale cloud value while the Envoy is down is paged when the Envoy returns, or lost if URA's own re-send heals the hardware first (pre-fix this was also swallowed).

## Tests
`test_ec_reserve_false_revert_fixup.py` (37). Orchestrator mutation: gate removed → 11 failed; step removed → 16 failed. Name-diff vs 8e2e9b7b7: 0 new failures.

## Live acceptance (prospective)
| Criterion | How to check |
|---|---|
| No false page at the nightly drop | Night after restart: no `write_reverted` anomaly / "reverted" NM between 23:00-23:20 while local reserve unavailable and cloud stale |
| Memory recorded | Diagnostics attributes `reserve_witness_confirm_*` set after the ~21:00 command (first ≈ command time, last refreshes until the drop) |
| Real reverts still page | In-suite (no live revert expected); replay test fallback |
| Load clean | No URA ERROR after restart |

Note: deployed 2026-11-01 without restart (operator); takes effect at the next restart.
