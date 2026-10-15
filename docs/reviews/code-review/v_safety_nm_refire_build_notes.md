# Build notes — SAFETY-NM-REFIRE-UNWIRED-1 (plan Rev 4 + 4.1)

Branch `feature/safety-nm-refire` (from develop `1ddadfbfb`). Builder: ura-super-builder, 2026-10-15.
Scope built: D1, D2, D4 (docs), D6, tests. D5 withdrawn: `notification_manager.py` is untouched
(`git diff develop -- .../notification_manager.py` is empty), so `_repeat_alert` is byte-identical.

## Invariant (plan §1, INV-REFIRE Rev 4, post-ACK path)
For Safety CRITICAL `{smoke, carbon_monoxide, flooding}`: (1) still active at cooldown expiry, with no
pending clear: exactly one `_re_evaluate_hazard` re-page carrying the same `hazard_type`/`location`.
(2) Clear hold pending with no raising sensor at expiry: zero re-pages, NM goes IDLE. (3) A relapse
cancels the hold, so the re-page happens at expiry. (4) Unacked alerts latch until acked
(no Safety-side silencing).

## Sites (re-grepped)
| Site | file:line (post-build) | Notes |
|---|---|---|
| D1 sole `NotificationAction(` in safety | `safety.py:2580-2591` | `rg 'NotificationAction\('` gives one match |
| D2 `is_hazard_active` | `safety.py:3403-3435` | sole caller `notification_manager.py:3039` (`rg is_hazard_active custom_components/`: defs base:237, safety, security:825) |
| D6 flooding location | `safety.py:1920` | `location=` |
| D6 flooding message | `safety.py:1927` | message string |
| Manager forward (unchanged) | `manager.py:1070-1081` | driven by T6/T7 via the real `_execute_action` |

## Tests — `quality/tests/test_safety_nm_refire.py`
The plan's `quality/tests/safety/` and `quality/tests/notification_manager/` directories do not exist (the
suite is flat), so all tests live in one flat file.

| Plan id | Test | Class | develop |
|---|---|---|---|
| T1 | `test_safety_notification_action_carries_hazard_type_location` | F | FAILED |
| T2 | `test_safety_is_hazard_active_true_when_active` | R | PASSED |
| T2b (conjunct drills) | `test_safety_is_hazard_active_hold_branch_needs_both_conjuncts` | F | FAILED |
| T2c (roc + hold) | `test_safety_is_hazard_active_roc_key_pending_is_inactive` | F | FAILED |
| T3 | `test_safety_is_hazard_active_false_when_cleared` | R | PASSED |
| T4 | `test_safety_is_hazard_active_false_during_clear_hold[300/86400]` (hold extremes) | F | FAILED x2 |
| T5 | `test_safety_is_hazard_active_true_on_relapse_during_hold` | R | PASSED |
| T6 | `test_safety_smoke_repeat_phase_is_life_safety` | F | FAILED |
| T7 | `test_nm_re_evaluates_safety_hazard_round_trip` | F | FAILED (`600 == 120`) |
| T7-neg | `test_nm_re_evaluate_no_refire_during_pending_clear` | R / intermediate | PASSED |
| T9 | `test_safety_flooding_location_is_deterministic` | F | FAILED (`'Kitchen, Garage'`) |

develop run (tests applied, source unpatched): **8 failed, 4 passed**. Post-build: 12 passed.
T7 uses a pass-through spy on `async_notify`, has pushover enabled for one person, and asserts the new
per-channel `log_notification` rows (`hazard_type='smoke'`, `location='Garage'`, `severity='CRITICAL'`).
T9 runs the real `_check_flooding_escalation` in subprocesses with `PYTHONHASHSEED=0` and `=1`.

Targeted siblings (post-build, together with the new file): test_safety_coordinator,
test_safety_hazard_clear_on_recovery, test_safety_humidity_junk_floor, test_v4_6_9_safety_recent_events,
test_zone_safety_alert, test_notification_manager, test_nm_cycle_b_safety_rails,
test_nm_cycle_c2_life_safety_union, test_nm_recovery_agebound, test_restart_safety_doctrine_1:
**596 passed** (includes the new file's 12).
Order robustness: 5 orderings with test_safety_coordinator / test_notification_manager /
test_safety_hazard_clear_on_recovery / test_nm_cycle_* before and after; all green. The manager
base-class reconciliation is scoped through monkeypatch.

## Per-site mutation drills
Method: one Python step per mutant (write mutant, clear `__pycache__`, `PYTHONDONTWRITEBYTECODE=1`,
run the new file + test_safety_hazard_clear_on_recovery + test_safety_coordinator, restore in
`finally`). `git status` was clean apart from the intended changes afterwards.

| Mutant (one site) | RED tests |
|---|---|
| D1a drop `hazard_type=` kwarg | T1, T6, T7 |
| D1b drop `location=` kwarg | T1, T6, T7 |
| D2 revert hold branch (whole) | T2b, T2c, T4[300], T4[86400], T7-neg |
| D2 drop `in _hazard_clear_pending` conjunct | T2b, T2c, `test_safety_is_hazard_active_ignores_roc_suffix` |
| D2 drop `not raising` conjunct | T2b |
| D2 drop `:roc` strip | T2c, `test_safety_is_hazard_active_ignores_roc_suffix` |
| D6a revert location `sorted` | T9 |
| D6b revert message `sorted` | T9 |

Wire-in: D1 is the call-site kwarg itself. T6/T7 drive it end to end through `evaluate` →
`_respond_to_hazard` → `CoordinatorManager._execute_action` → `NotificationManager.async_notify` →
`async_acknowledge` → `_cooldown_expired` → `_re_evaluate_hazard` → `is_hazard_active`.

## Plan discrepancy (reported, not improvised)
- Plan §9C says "revert D2 → T7 fails". It does not: T7's detector stays ON with no pending clear, so
  `is_hazard_active` is True with or without D2. At the NM level, D2 is anchored by T7-neg (RED on
  D1-with-D2-reverted, as the drill shows), and at the Safety level by T4/T2b/T2c. T7 anchors D1 only,
  through two failure modes: hazard_type missing fails the 120 s cooldown assertion; location missing
  fails the re-fire count.
- Tests added beyond the plan's list (T2b, T2c, and the T4 hold-extreme parameter): coverage only, no
  source scope added.

## Deferrals
None from D1/D2/D4/D6/tests. D5 withdrawn per plan. Carded follow-ups unchanged:
SAFETY-UNACKED-REPEAT-CADENCE-KNOB-1, SAFETY-NO-INITIAL-SENSOR-PASS-1, NM-MULTI-ALERT-TRACKING-1,
SECURITY-REFIRE-INTRUSION-KEY-1. Deploy hold (plan Rev 4.1): until the operator is home (Sun 10-18) or
Jaya has been shown how to ack.
