# URA v5.103.63: safety alerts re-page after acknowledgement; repeat schedule becomes a setting

Card: SAFETY-NM-REFIRE-UNWIRED-1. Plan: `docs/planning/PLANNING_safety_nm_refire.md` Rev 4.3 (four plan-review rounds; D5 stop-on-clear withdrawn). Tier 2-DB, life-safety: reviews A (correctness) SHIP, B (lifecycle/integration) FIX-REQUIRED and fixed, C (per-site mutation, 33 sites) SHIP. Record: `docs/reviews/code-review/v5.103.63_safety_nm_refire.md`. Deploy risk: **MEDIUM** (notification behaviour of life-safety alerts). Deploy held until the operator is home (Sun 10-18).

## Why
Safety's alerts reached the notification manager without a hazard type or location, so an acknowledged smoke, CO or flood alarm was never re-paged after its cooldown, even while the detector stayed on (the re-check asked about hazard "None:None").

## What changed
- **D1:** Safety's single `NotificationAction` carries `hazard_type` and `location`, so smoke/CO/flood alarms are treated as life-safety everywhere in NM.
- **D2:** `is_hazard_active` is hold-aware: a hazard whose sensors have all recovered and whose 300 s clear hold is pending reads as cleared for the post-acknowledgement re-page check. A relapse cancels the hold and re-pages.
- **D6:** the flooding location and message sort their room list, so the hazard key is stable.
- **D7:** new Coordinator Manager setting "Smoke, CO and flood repeat schedule" (also covers water leak and freeze): **Standard** (default: every 5 min for the first hour, then every 30 min, then daily — what Safety alerts did before), **Fast start** (every minute for 10 min, then Standard), **Urgent** (every 30 s until acknowledged). Intruder alerts and operator-promoted extras keep their 30 s repeat. Saving it does not reload the Coordinator Manager; an alert already repeating switches to the new schedule at once.
- **Quiet hours:** the life-safety bypass of quiet hours, mute and rate limiting now needs severity HIGH or above (MEDIUM water leak / freeze / CO are held, as before this release).
- Unacknowledged life-safety alarms keep repeating until acknowledged (latch-until-ack); nothing in Safety's state silences them.
- Side effects of D1, intended: smoke/CO flash orange and flooding pulses blue (was a yellow warning pulse); house speakers announce smoke/CO overnight despite Do Not Disturb.
- Known pre-existing gaps, carded: Safety does not read current sensor states at startup (SAFETY-NO-INITIAL-SENSOR-PASS-1); NM tracks one active alert (NM-MULTI-ALERT-TRACKING-1); intruder re-fire key mismatch (SECURITY-REFIRE-INTRUSION-KEY-1).

## Tests
- `quality/tests/test_safety_nm_refire.py` 70 tests (fix-proving set fails on develop); 1405 pass across the NM, config, reload and safety files.
- Mutation: builder drills on every D1/D2/D6/D7 site and every review fix; review C 33/33 red; orchestrator drill (drop water_leak from the schedule set) reddened 3 tests.

## Pre-deploy gate
- Full-suite name-diff, develop 705d1808e vs the same + feature/safety-nm-refire f883a62a5: **CLEAN**, 0 NEW, 0 GONE; 119 failed / 15011 passed vs 119 / 14941. (First run had 5 NEW order-dependent extras tests; fixed in f883a62a5.) Re-run on deploy day if develop has moved.

## Live acceptance
- **Live:** after restart, a test smoke alert (Safety test service) pages with `hazard_type=smoke` and a location in `notification_log`; acknowledge it; while the test hazard stays active, one re-page row appears after the 120 s cooldown.
- **Live:** an unacknowledged test alert repeats on the Standard ladder (second page ~5 min after the first), not every 30 s.
- **Live:** the options flow shows "Smoke, CO and flood repeat schedule" = Standard; saving it does not reload the Coordinator Manager.
- **Live:** 0 URA ERRORs.
