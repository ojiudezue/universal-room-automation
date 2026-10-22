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

## Validated 2026-10-21

| Criterion | Result | Evidence |
|---|---|---|
| Fill-priority entities available | PASS | `number.ura_energy_coordinator_fill_priority_soc` = 80 (last_updated 2026-10-21 18:25:37) |
| 0 URA ERRORs after restart | NOT-YET-EVALUABLE | log-read gap |
| Mid-peak episode with SOC near 80: one resume, no re-pause while SOC >= 77, no switch chatter | PASS (partial: the 77-80 hold branch was not exercised) | `ura_activity_log` garage_a, 2026-10-16 to 10-21: exactly one `fill_priority` pause per day (12:36-12:40Z) and one resume (17:19Z-18:59Z), no pause, resume, pause cycle. Day counts of garage_a fill-priority pauses: 1 on 10-15, 16, 17, 18, 20, 21; 2 on 10-19 (the second at 18:31Z carries `pause_owners=fill_priority,dp`, a drain-protection co-owner, not SOC chatter). `sensor.envoy_482543015950_battery` crosses the 75-82 band on the way up at the resume hour (10-21 17Z min 51 max 77; 18Z min 78 max 98), one resume at 18:10:54Z, no re-pause. SOC never dipped back into 77-80 after a resume in this window, so the new hold rule was neither stressed nor contradicted. |
| Side observation (not a README criterion) | note | `ev_toggle_tripwire` (HIGH) fired 10-18 22:50Z, 10-19 18:36Z, 10-21 22:47Z for garage_a; pause owners `none` / `dp`, not `fill_priority`. 22:00Z is the daily `pause_owners=us` off/on at the peak boundary. Not caused by fill priority, but a recurring flip-flop alert worth a card if none exists. |

_Log-scan criteria are NOT-YET-EVALUABLE (no log access from the probe); source: docs/planning/AUDIT_readme_straggler_validation_2026_10_21.md._
