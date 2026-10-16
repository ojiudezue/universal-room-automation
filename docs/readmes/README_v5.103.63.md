# URA v5.103.63: EV fill-priority re-pause buffer

Card: EV-FILL-PRIORITY-SOC-CHATTER-1. Plan: `docs/planning/PLANNING_ev_fill_priority_soc_buffer.md` Rev 3 (two plan reviews). Tier 3 (operator-elevated): reviews A FIX→fixed, B FIX (same finding)→fixed, C SHIP (47/47 mutation sites red; 2 LOW fixed), D SHIP and SHIP on re-verify. Record: `docs/reviews/code-review/v5.103.63_ev_fill_priority_buffer.md`. Operator go 2026-10-15. Deploy risk: **LOW-MEDIUM**. Active after the next HA restart.

## Why
In mid-peak, with the home battery hovering at the fill-priority threshold (80%), EV chargers and smart plugs were paused and resumed repeatedly as SOC crossed 80 by tenths.

## What changed
- After fill priority resumes a charger at the threshold, it is not paused again until SOC drops below threshold − 3 (77.0 holds, 76.9 pauses). The first pause below the threshold is unchanged. Same rule for EVSE and plugs.
- RAM latch per charger, storing the threshold it was set at. Cleared on: fill priority inert (overnight/peak), a real peer steal (another rule takes the charger; proactive off-peak holds excluded — A-HIGH-1), force charge, release-all, below-floor sweep, observation mode, prune, threshold change.
- Arbitrage hand-off respects the latch per charger. Constant `DEFAULT_FILL_PRIORITY_REPAUSE_HYSTERESIS_PCT = 3` (module constant: change requires review).
- Unchanged: arbitrage, drain protection, TOU, force charge.

## Accepted side effects
- A car plugged in at 77–80% SOC can draw up to 3 points from the home battery.
- The latch is RAM only; after a restart there can be one extra pause.

## Tests
- `quality/tests/test_ev_fill_priority_repause_band.py` (new) + hygiene test updates; 156 fill-priority tests pass on merged develop.
- Orchestrator drill: re-adding off-peak holds to the steal list reddened `test_a_high_1_ev...`.

## Pre-deploy gate
- Full-suite name-diff, develop vs develop + feature: **CLEAN**, 0 NEW, 0 GONE; 119 failed / 15013 passed.

## Live acceptance
- **Live:** 0 URA ERRORs after restart; fill-priority entities available.
- **Live:** next mid-peak episode with SOC near 80: one resume, no re-pause while SOC ≥ 77 (EVSE switch history shows no toggle chatter).
