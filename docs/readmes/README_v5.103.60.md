# URA v5.103.60: bathroom exhaust — smell rule (occupancy dwell), venting independent of the room switch, no resend spam

Card: HUMIDITY-FAN-ON-RESEND-SPAM-1. Plan: `docs/planning/PLANNING_bathroom_exhaust_occupancy_and_resend.md` (Rev 2, plan-reviewed: `docs/reviews/code-review/plan_bathroom_exhaust_review.md`). Tier 2-DB (operator: "respect the process"): three framing-disjoint reviews (A correctness, B lifecycle/cross-path, C test authority by per-site mutation), two fix-ups, C re-verify. Deploy risk: **MEDIUM** (fan domain; no presence, HVAC, safety or energy change).

## Why
- **Spam:** `automation.py` sent `homeassistant.turn_on` to the humidity fan on every humidity update while humid, even when already on: Master Bathroom 3,806 calls in 7 days, peak 652/h, with Shelly relay timeouts.
- **Room switch coupling:** venting required the room's master automation switch. Ziri Bathroom (switch off) crossed its threshold in 236 samples in 7 days with zero fan commands.
- **No smell rule:** the 2026-08 exhaust cycle ported only the post-vacancy run-on of the operator's `Guest Toilet Automation2`, not its occupancy turn-on, and the run-on only worked after humidity had turned the fan on. Rooms without a humidity sensor (Master Bath Toilet, Guest Bedroom 1 Bathroom) never vented. Operator: "if you've been in there beyond 45-60 s we assume you did a number 2 and we need the fan to run for smell reasons, not just humidity."

## What changed
- **D1:** humidity venting is gated only by the room's humidity-fan-control switch (`_humidity_gate.humidity_venting_enabled` drops the master-automation argument; `coordinator.py` caller updated). Sleep-off only turns off fans URA itself turned on (anchor), so it never fights a fan a person turned on by hand.
- **D2:** every ON/OFF write is transition-gated. If URA believes the fan is on but it reads off, it re-asserts at most every `HUMIDITY_FAN_REASSERT_INTERVAL_S` = 180 s (module constant, rung 1). A real on→off not caused by URA (context check via a `@callback` state listener; `unavailable` is a relay drop, not manual) arms a `HUMIDITY_FAN_MANUAL_OFF_RESPECT_S` = 1800 s respect window (rung 1; in memory, a restart drops it). Listeners are torn down on room unload and re-registered when the fan list changes.
- **D3 smell rule:** the fan turns on after the RAW occupancy/motion sensor has been continuously ON for `humidity_fan_occupancy_dwell_s` (default 60 s, rung 2 per-room option; ticks are ~30 s, so it fires at 60–90 s). Enabled by `humidity_fan_occupancy_dwell_enabled` (rung 2; runtime default = the room's wet_room flag, so existing bathrooms get it without a re-save). It holds while occupied, then runs the post-vacancy window min(base + per-minute × minutes, cap), with a fallback turn-off when that option is off. Works without a humidity sensor. In a room without humidity, cap suppression holds until the room has been vacant once, so a stuck-ON occupancy sensor cannot re-fire the fan forever.
- Measured basis for 60 s (raw sensor ON-runs, last 10 days): Powder 75 visits, median 40 s, p90 107 s (~25% pass 60 s); Master Toilet 179 visits, median 34 s, p90 77 s (~15%).

## Tests
- `quality/tests/test_bathroom_exhaust_occupancy_and_resend.py` (new, behavioural) plus 6 stale tests in `test_bathroom_exhaust_intelligence_cycle.py` updated without weakening. 138/138 targeted pass.
- Mutation drills: review C re-verify ran 43 single-site drills; the fix-up 2 drill table shows 13 more red, 5 green where a sibling guard makes the mutation unobservable (redundant guards, documented). Orchestrator drill: neutering the ON transition gate reddens 3 tests.
- Full-suite name-diff: see Pre-deploy gate.

## Deploy steps (orchestrator)
- Disable `automation.guest_toilet_automation2` (interim Powder fan-only remnant, id 1750820778098) at the restart that activates this release, so two writers never drive the Powder fan.
- Laundry (`01KR3V6KJZFR702TQS2W83FZ4P`): set `humidity_fan_occupancy_dwell_enabled` = false via the options flow after the restart (operator 2026-10-14: folding laundry should not start the exhaust). The field only exists once this release is running.

## Pre-deploy gate
- Full-suite name-diff of develop + feature/bathroom-exhaust (5911ca329) vs develop 3a148bbbb: **CLEAN**. 7 NEW names, all order-dependent: the 2 new listener tests (fixed after in the tracker-pin commit by pinning the lazily imported tracker per test) and 5 test_bayesian_b2 names that reproduce identically on develop in isolation (pre-existing sys.modules family); 6 GONE in the same bayesian family. collect_order_matrix seeds 1,22: 0 errors, 0 drift.

## Live acceptance
- **Live:** Master Bathroom fan `call_service` turn_on count drops from hundreds/hour while humid to ≤ a few per humid episode.
- **Live:** Powder or Master Toilet visit > ~90 s turns its fan on; a < 40 s visit does not. Fan off after the post-vacancy window.
- **Live:** Ziri Bathroom vents on a shower while `switch.ziri_bathroom_automation` stays off.
- **Live:** 0 URA ERRORs; `automation.guest_toilet_automation2` off.

## Validated 2026-10-15 (HA restart 12:44 CDT, URA up 12:46)

| Criterion | Result | Evidence |
|---|---|---|
| Master Bathroom turn_on spam gone | **PASS** | Recorder `call_service` events naming `masterbathfan` 12:46–15:06: 4 in total for one humid episode (fan on 13:01:38, off 14:02:07, humidity 64–72). Before: up to 652/h. |
| Powder / Master Toilet visit > ~90 s turns fan on | Pending organic | No fan transition on either room since restart; proven in-suite (`test_bathroom_exhaust_occupancy_and_resend.py`). |
| Ziri vents with room switch off | Pending organic | No Ziri humidity crossing since restart; proven in-suite. |
| 0 URA ERRORs; `automation.guest_toilet_automation2` off | **PASS** | system_log ERROR filter: 0. Automation `off` since 12:46:17. |
| Laundry smell rule off | **PASS** | Options flow: `humidity_fan_occupancy_dwell_enabled` = False, threshold 62 unchanged. |
