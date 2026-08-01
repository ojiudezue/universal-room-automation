# Tier-3 Review Record — D2 mmWave Fan-Corroboration Demotion

Branch `feature/mmwave-fan-demotion`: build 76a2ae50e → fix-up eac707767 → D-prime fix 30a80ecd2.
Four framing-disjoint reviews + D-prime re-run + orchestrator verification. The Tier-3 "a fix reveals the N+1th site" rule fired TWICE.

## Findings ledger
| ID | Sev | Finding | Status |
|---|---|---|---|
| A-CRIT-1 / B-1 | CRIT | `_occupancy_first_detected is None` gate made D2 unreachable in production; suite green via fixture-state mismatch | FIXED (debounce-elapsed guard; sustained-production fixture; mutation-anchored) |
| D-PRIME-CRIT-1 | CRIT | Fix-up's defer-to-hold arbitration re-created unreachability (hold re-stamps every suspect tick — can never expire while D2's conditions hold) | FIXED (D2 outranks hold once its strictly-higher bar met; demote + atomic hold-clear; sustained-suspect test + drill) |
| D-CRIT-1 | CRIT | No sleep gate — D2 was the only demotion path active during SLEEP; would vacate sleeping bedrooms (2 existing code sites already refused these semantics) | FIXED (SLEEP/WAKING/HOME_NIGHT veto, both sides) |
| D-HIGH-1 | HIGH | No-PIR rooms: staleness vacuously true (leg satisfied by sensor absence) | FIXED (fail-closed; MMWAVE_NAME_PATTERN-filtered) |
| B-2 / D-HIGH-2 | HIGH | Room-tier vs zone-tier view divergence unpinned | FIXED (blast radius pinned room-tier-only + zone-view invariant test; precedence recheck > D2-outranks-hold) |
| A-MED-1 / B-3 | HIGH (promoted — Master Bedroom has 2 fans) | Multi-fan rooms lose grace stamp on partial fan-off | FIXED (live sibling-fan check) |
| D-HIGH-3 | HIGH | Primitive promoted from observation to gating without the snapshot its docstring demanded | FIXED (per-inference-tick frozen snapshot) |
| FLAP (B/C) | HIGH-consequential | Fixing A-CRIT-1 reopened re-latch oscillation (old bug incidentally prevented it) | FIXED (demotion latch: mmwave-sole cannot re-create until clean edge/PIR/BLE/fan-off; flap test + drill) |
| D-MED-1/2, A-LOWs, B-LOWs | MED/LOW | Grace floor 300 clamp, camera fail-closed, source-log capture, counter renamed since_boot, D3 kill-switch doc, "timeout" trimmed, PIR seeded at init, plan Amendment 3 | ALL FIXED |
| D-PRIME-LOW-1/2 | LOW | Latch clear PIR-latency bounded on untrusted return; RAM latch boot re-cycle | ACCEPTED-BY-DESIGN (documented) |

## Mutation verification
Builder drills: 6 per-leg (initial) + guard + latch (fix-up). Reviewer C: 6 adversarial, all legs load-bearing. Orchestrator (personal): sleep gate → 2 red; no-PIR gate → 2 red; hold-clear pop → 1 red (sustained-suspect test); all restored → 23/23.

## D-double-prime disposition (orchestrator analysis, recorded honestly)
The D-prime fix implements D-prime's own recommended option 2 with its demanded test. Residual surface of the fix itself: clearing the hold only affects the zone view when provenance is all-false, but D2 fires only under sustained mmwave provenance (source=="mmwave"), where the zone view is provenance-held — pinned by the zone-view invariant test. Decay-window behavior is pre-existing. No further enumeration deltas identified; live validation criteria carry the residual watch.

## Suite
23/23 cycle tests; full suite 7807 passed / 32 failed = exact baseline, zero drift across build + 2 fix passes.

## Bug-class notes for QUALITY_CONTEXT
- **Fixture-state authority** (new flavor of #62): mutation-anchored tests prove gates load-bearing IN THE HARNESS STATE — if the fixture's default state is unreachable in production, green means nothing. Positive tests must construct the sustained-production state.
- **Arbitration-level unreachability** (A-CRIT-1 class generalized): a gate referencing a signal that is continuously re-armed by the same condition the feature targets = feature dead. Ask "can this gate EVER pass while the trigger condition holds?"
