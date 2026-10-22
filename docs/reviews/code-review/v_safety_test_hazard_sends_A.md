# Review A (local correctness + edge cases) — SAFETY-TEST-HAZARD-SENDS-NOTHING-1

Branch `fix/safety-test-hazard-sends` @ e6889329f. Diff base verified: `git diff develop...HEAD`
(merge-base ab9245c3e; develop has moved to 7c131712b but the three-dot diff is limited to
safety.py + the new test file).

## Findings

| # | Sev | Site | Finding | Bug class |
|---|---|---|---|---|
| A1 | MEDIUM | safety.py `handle_test_hazard` (new send) → notification_manager.py:2007-2013 → `_enter_alerting` :2502-2553 | A CRITICAL test page enters NM's ack/repeat engine (YES, see trace). NM has ONE alert slot: `_enter_alerting` cancels any cooldown (:2514-2519) and OVERWRITES `_active_episode_id` / `_active_alert_data` (:2526-2550). Repro: a real CRITICAL smoke in `kitchen` is REPEATING unacked; operator runs `test_safety_hazard` with severity=critical → the repeat loop now re-pages "TEST ... in test", and acking the test (`async_acknowledge` :2911) ends the only repeat loop — the real kitchen smoke stops re-paging. Before this branch the test sent nothing, so this is newly reachable. Fix: in `handle_test_hazard`, refuse (log + return) when severity is CRITICAL and `nm.is_alerting` (:748) is true, or downgrade the test to HIGH in that case. | Cross-talk / shared single-slot state |
| A2 | LOW | NM `_emit_nm_dispatch_anomaly` (:2000-2010), audit rows, activity log | Test pages write real-looking rows (hazard_type=`smoke`, location=`test`). Only the `location="test"` default and the "TEST" title separate them in analytics. Acceptable; note for any life-safety rate query. | Observation/analytics pollution |
| A3 | LOW | NM token bucket `_bucket_take` :587 | Non-life-safety test pages take tokens from the shared per-channel bucket, same as any notify. A life-safety CRITICAL bypasses the bucket (:3956-3960), so a test cannot rate-limit a real smoke/CO page. Holds. | — |

## Checks that hold

- **Same dispatch path:** `manager._execute_action(self, action)` → manager.py:1072-1081 → `NM.async_notify(severity, title=description, message, hazard_type, location)`. The action comes from the shared `_hazard_notification_action` builder, also used at the real site (safety.py ~2582). Shape is identical apart from the title prefix.
- **TEST marking:** title `"TEST safety alert: TEST: <type> in <loc> ..."`, message `"TEST: ..."`. Holds.
- **Severity mapping:** `Severity[severity.upper()]`, falling back to MEDIUM on a bad value. The real enum reaches NM. LOW → channels `[]`, but NM routes by severity and ignores `action.channels`, so the channels list is log-only. Holds.
- **Separate `_test_deduplicator`:** a fresh `AlertDeduplicator` with the same key `type:location` (:954). A test cannot stamp the real dedup, and the test file covers this (`test_test_hazard_does_not_suppress_real_page`). It also means a test is not suppressed by a recent real page. Intended.
- **No side effects:** no `_active_hazards` write, no signal, no response actions, no `_alerts_sent_24h` bump. Holds.
- **Missing manager:** `hass.data[DOMAIN].get("coordinator_manager")` None → warning + return. `_execute_action` itself checks for a None NM (:1072). Holds.
- **NM keyed state:** the episode id includes location (:2526), so a test in `test` never matches a real episode's ack registry key. The DND bypass is keyed on hazard_type only (:4253), so a test smoke at HIGH+ bypasses quiet hours exactly like a real one. That is the purpose of a pipeline test, but the operator should know a night-time test will speak/flash.

## Life-safety repeat trace (answer: YES)
`handle_test_hazard` → `_execute_action` → `async_notify` → :2007 `if severity == CRITICAL: await self._enter_alerting(...)` → :2552 REPEATING + `_schedule_repeat` :2557 → `async_call_later(interval, _repeat_alert)`. With hazard_type smoke/co/flood the interval comes from the life-safety schedule (:2591-2602). The urgent schedule repeats every 30 s; other life-safety types use a flat 30 s. The loop runs until acked. That is correct for testing the ack path; A1 is the only problem.

## Verdict: FIX-REQUIRED
Must fix: A1 (guard the CRITICAL test page while NM is already alerting). A2 and A3 need no change.

B2 accepted: tests are operator-initiated and rare; use location 'test'.
