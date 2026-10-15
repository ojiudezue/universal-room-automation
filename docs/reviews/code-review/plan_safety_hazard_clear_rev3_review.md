# Plan re-review: PLANNING_safety_hazard_clear_on_recovery.md rev 3

Date: 2026-10-14. Base: develop @ bfbfb53f7. Card: SAFETY-HAZARD-NEVER-CLEARS-1 (scope widening approved 2026-10-14).
Verdict: **FIX-REQUIRED** (one HIGH, four MEDIUM. All are plan edits; the design holds up.)

Site enumeration was re-run independently. Every `_active_hazards` write on develop is in §4-site-table: safety.py:1773, 1904, 1946, 2327, 2704, 2773, 2779, 3155. The junk-floor branch is merged, so develop lines now match the plan's "branch" cites. The stacking header (L9-13) is stale and should be fixed.

## Findings

**HIGH-1: the hold suppresses re-raise response actions for life-safety hazards.** Plan §4-site-table row 1 and §4-0. Today, a leak that dries pops the key (safety.py:1773). If it re-wets, `is_new` is True at :2326, so the HIGH response runs again (valve close, :2650-2661). Under rev 3 the key is still held for 300 s. A re-wet inside that window takes the `not is_new` early return at :2329 and the response does not run again. CO has the same problem through the relapse path. That is a suppressed real alert/response. Fix: for SMOKE, CARBON_MONOXIDE and WATER_LEAK, treat a raise that arrives while `_hazard_clear_pending[key]` is set as `is_new`. Notifications stay gated by the existing `SafetyDeduplicator` (:900). Alternatively, keep the binary smoke/leak clear immediate with no hold. Add test `test_safety_leak_rewet_during_hold_reissues_response`.

**MEDIUM-2: NM re-fire is already inert, so the D4 "NM consumer" criterion proves nothing.** Safety's `NotificationAction` (:2413-2420) sets no `hazard_type` or `location`. manager.py:1079 then passes None, and NM calls `is_hazard_active("", "")` (notification_manager.py:3039), which always returns False. The §4-G exact-match rewrite therefore cannot suppress a CO re-page, because nothing reaches it today. But §3's claim that this is a "Trust" consumer is false, and the D4 test does not discriminate. Fix: correct §3 and card the gap (SAFETY-NM-REFIRE-UNWIRED). Keep it out of this cycle's scope.

**MEDIUM-3: the ROC clear criterion is undefined in z-score mode.** `check_thresholds` (:727) raises by z-score once baselined, so there is no fixed `raise_rate`. Also, `get_rate` returns None when no sample falls inside the window (:676-689). It does not return a "stale rate forever" as §4-H-rev3 says. Fix: store the raise rate or z on the Hazard and clear when the rate is None or below the fraction. Correct the rationale.

**MEDIUM-4: §4-J has no writer for `_sensor_unavailable_since`.** The state handler returns early on unavailable (:1538). Fix: say where the value is stamped, either at that early return or by the sweep polling `hass.states`.

**MEDIUM-5: the known failing test is not in the plan.** `test_tvoc_detection` lives at quality/tests/test_safety_coordinator.py:804. The brief's path (test_restart_safety_doctrine_1.py) is wrong. The test seeds a naive `datetime.utcnow()`, while production uses aware `dt_util.utcnow()` (:1924). This is a test defect, so production does not change. Add it to D6: fix the test to use `dt_util.utcnow()`.

**LOW:** the §4-site-table should name SMOKE explicitly, since it shares the :1773 clear.

## Passing checks
- The invariant is falsifiable and has a negation set.
- Knobs are rung 1 with a clear rationale.
- Restart: all dicts are ephemeral and cleared in teardown.
- The zone chip reads live state (no change needed).
- The CO2 log-only race (NEW-H1) is addressed.
