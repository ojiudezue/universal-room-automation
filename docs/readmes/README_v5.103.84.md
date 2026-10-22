# v5.103.84: the test safety alert actually sends

Card: SAFETY-TEST-HAZARD-SENDS-NOTHING-1. Tier 1 with Tier-2 protocol (safety path): reviews A (correctness) and B (real-path equivalence), both FIX-REQUIRED on the same MEDIUM, fixed and drilled. Deploy risk: LOW (test service path; the real hazard path is byte-identical).

## Problem

`universal_room_automation.test_safety_hazard` built a hazard, checked the deduplicator, logged, and returned. It never sent anything, although its description says it "only sends notifications". Found 2026-10-21 when an operator-approved CRITICAL test produced 0 `notification_log` rows, leaving the v5.103.65 re-page criteria unevaluable.

## Fix

- Real and test pages now share one builder, `SafetyCoordinator._hazard_notification_action`. Review B proved the real-hazard action is field-for-field identical to before.
- The test path sends through the same `manager._execute_action` → `NotificationManager.async_notify` route as a real hazard. Title "TEST safety alert: …", requested severity honoured; a CRITICAL test enters NM's repeat loop (review A traced `notification_manager.py:2007` → `_enter_alerting` → `_schedule_repeat`).
- No response actions, no `_active_hazards`, no signal, no counters.
- Own `_test_deduplicator`: previously a test could suppress a real page for the same type and location.
- Refused while a live alert is active (`NM.active_alert`), any severity: NM has one alert slot, so a test would otherwise replace a real repeating alert and acking it would stop the real one.
- Accepted on record (review B2): test pages use NM's post-boot quiet-window slot; tests are rare and operator-initiated; use location `test`.

## Tests

`quality/tests/test_safety_test_hazard_sends.py`: 6 tests; 5 mutation drills RED (send call, TEST title, separate deduplicator, real-path helper, live-alert guard).

## Live acceptance criteria (prospective)

- **Live:** with the house awake and no live alert, `test_safety_hazard` smoke / `test` / critical writes a `notification_log` row titled "TEST safety alert…" with `hazard_type=smoke`, `location=test`.
- **Live:** unacknowledged, it repeats on the life-safety schedule (rows every ~5 min on Standard); after the operator acknowledges, repeats stop. This closes README_v5.103.65's re-page criteria.
- **Discriminator:** before the fix, the same call wrote 0 rows.
