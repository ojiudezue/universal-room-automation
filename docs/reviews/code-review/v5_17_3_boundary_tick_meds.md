# Review record — v5.17.3: at-boundary TOU tick + deferred MEDs (D-MED-1/2)

**Commits:** a24a2d7c (build) + f911e526 (LOW fold-in). Baseline tag `pre-review-v5.17.3`.
**History note:** D1 was first specced anticipatory (-3min, synthetic now-override) at operator suggestion, then REVERTED to the plain at-boundary variant (+5s, real clock) after marginal-benefit decomposition (operator: "pause to consider this") — see CLAUDE.md "Marginal-Benefit Decomposition" coined from this episode. Anticipatory design parked; evidence trigger = boundary-lag data showing real cost.
**Protocol:** Tier 2, framings A+B on ura-reviewer-std. Both **SHIP**, LOW-only; all three LOWs folded (B2 accepted as established pattern).

| ID | Sev | Finding | Outcome |
|---|---|---|---|
| A1 | LOW | delay==0 contract untested | test added (f911e526) |
| A2/A3 | LOW | re-arm loop + DST notes — verified clean/unreachable | documented |
| B1 | LOW | silent feature-disable on hypothetical HA API rename | one-shot WARNING added |
| B2 | LOW | untracked async_create_task shape | accepted — byte-identical to 10 established peers, HA-tracked |
| B3 | LOW | exception-clears-_cycle_in_flight untested (proven by reviewer execution) | test added |

**Executed proofs:** A ran the boundary-walk helper against the real rate table (7 cases incl. midnight wrap + Sep30→Oct1 season flip) and the DST analysis; B executed the thrown-exception flag-clear (the highest-blast-radius candidate — decision-cycle permadeath — proven impossible) and verified the ImportError guard is module-level (not Bug Class #34) with a test-only None branch. Builder executed 3 on-disk mutations (re-arm strip, reset-persist drop, ledger-fallback removal) — all RED.
**D3 clamp direction verified:** overlay append raise-only guard; legitimate downward reserve moves unaffected (normal _result path).
