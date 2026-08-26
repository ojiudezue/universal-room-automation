# Code Review — ARBITRAGE-GATE-D2-OFFBYONE-1 (Tier 2-DB, 3 framing-disjoint)

Branch: feature/arbitrage-gate-d2-offbyone @ f9825f833 (off develop 772b0c887).
Reviewers: A (correctness+completeness), B (cross-coordinator+day-boundary), C (test-authority via mutation).
**Verdict: SHIP (all three).**

## The fix
The arbitrage gate paired the peak-anchored target day with a HARDCODED `classify_solar_day_n(2)` for
its multi-day broadening leg → at offset 0 (target day = today, post-midnight) it compared today vs
day-after-tomorrow and SKIPPED tomorrow. Fixed at 3 sites via `_resolve_target_day(now)` offset + 1,
mirroring the shipped+validated DRAIN-TARGET-DAY-STALENESS-1 precedent.

## Site enumeration (A + B + C independently re-grepped — complete, no 4th site)
- energy_battery.py:2591 `_recheck_forecast_on_charge_entry` — FIXED, mutation-anchored (C site 1 RED).
- energy_battery.py:3017 `_gate_is_open` — FIXED, mutation-anchored (C site 2 RED).
- energy_battery.py:6119 `get_status` d2_class (DISPLAY) — FIXED; anchored by fix-up (was the one gap).
- Pre-existing-correct: :1765 / :5463 (drain, already offset+1). :2539 in-resolver. No hardcoded n=2 remains.

## Convergent findings
- **Correctness: all invariants PASS.** No decision threshold moved (B1); offset==1 byte-identical (A, C
  confirmed by mutation staying GREEN — 1+1==2); day-boundary seam REMOVED not relocated (B4); drain and
  gate agree on the target day every tick (B3); restart-safe, no stale second-day cache (B5).
- **Test-modification audit CLEARED (C, the decisive check).** The 4 modified MultiDay tests (shifted
  09:00->22:00) were NOT a cover-up: reverting to 09:00 fails exactly the 4 D+2-load-bearing rows, because
  those tests only reached the day_3 fixture BECAUSE of the off-by-one — they were asserting the bug. The
  relaxed assertion (==CHARGE -> in{CHARGE,HOLD,WAIT}) still goes RED when its leg is neutered (not hollow).
- Name-diff vs develop: 12->12 identical pre-existing failures (DP/EVSE/presence families), +3 passed
  (new file). Zero new failures.

## Fixed in-cycle (fix-up)
- get_status d2_class display anchor (B9/C LOW) — new test with RED-on-neuter drill.
- test_d2_alone_opens_gate tightened to == WAIT (C LOW).

## Carded follow-ups (LOW, not blocking)
- ARBITRAGE-DRAIN-TODAY-UNKNOWN-DEGENERATE-PAIR-1 (B6) — degenerate d1==d2 pairing under transient
  today-unknown; shared with the drain path, fix both together.
- ARBITRAGE-D2CLASS-ATTR-SEMANTICS-1 (B7) — d2_class attr now "D+1-of-target"; add d2_offset or doc note.
- A LOW (optional): thread the offset through _gate_is_open's signature for structural (not coincidental)
  class<->offset pairing.
