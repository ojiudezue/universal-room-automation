# Paused rooms (67a9f7442) - Review C: test authority via per-site source mutation

Method: one mutation per run, PYTHONDONTWRITEBYTECODE=1, __pycache__ cleared, mutate+restore in one Python try/finally.
Target set: test_paused_room_gates.py + test_mmwave_fan_demotion.py (39 pass baseline); survivors re-run against the broader fan set
(test_fan_recheck_*, test_fan_manual_*, test_hvac_batch_d_fan*, test_hvac_fan_control, test_fan_sweep_trio, test_hvac_vacancy_sweep_manual_on_guard) = 341 pass baseline.

| Mutation | Result | Killing test |
|---|---|---|
| const predicate -> always False | RED | test_predicate_truth_table |
| predicate `is True` (inverted) | RED | test_predicate_truth_table |
| predicate `not check()` | RED | test_predicate_truth_table |
| `_is_automation_enabled` manual_mode ignored | RED | test_predicate_truth_table |
| `_is_automation_enabled` manual_mode inverted | RED | test_predicate_truth_table |
| hvac.py sweep gate off (~6733) | RED | test_sweep_skips_paused_room_lights_and_fans |
| hvac.py pre-arrival off gate off (~7405) | RED | test_prearrival_deactivate_skips_paused_room |
| hvac_predict.py pre-arrival on gate off (~1455) | RED | test_prearrival_activate_skips_paused_room |
| hvac_fans F1 gate off (~651) | RED | test_fan_controller_skips_paused_room |
| F1 skip without release call | RED | test_fan_controller_paused_release_level_no_write |
| release helper does not clear is_on | RED | test_fan_controller_paused_release_level_no_write |
| F3 sleep-onset gate off (~1055) | RED | test_sleep_onset_skips_paused_room |
| recheck eligibility gate off (~552) | RED | test_fan_recheck_vetoes_paused_room |
| recheck arm-delay gate off (~1230) | RED | test_fan_recheck_vetoes_paused_room (same test asserts both surfaces) |
| coordinator exit-verify gate off (~5735) | RED | test_delayed_exit_verify_skips_retry_when_paused[True] |
| exit-verify gate inverted | RED | same |
| OVERGATE recheck `_restore` on paused | RED | test_fan_recheck_paused_mid_flight_restores |
| **release helper also clears fan_recheck_suppress_until** | **GREEN (341 pass)** | none |
| **release helper also clears manual_off_cooldown_until** | **GREEN (341 pass)** | none |
| **release helper return value forced True** | **GREEN (341 pass)** | none |
| **OVERGATE turn_off_all_managed skips paused rooms** | **GREEN (341 pass)** | none |

Tree restored, `git status` clean after every run (only untracked review docs).

## Findings
- MEDIUM (untested contract, Bug Class #62-adjacent): `_release_room_tracking` docstring promises it "deliberately leaves fan_recheck_suppress_until, manual-ON hold and manual-off cooldown alone" (hvac_fans.py ~1265). Clearing suppress/cooldown inside the helper survives the whole fan suite. That is exactly the "unpause books a person's OFF as a fake cooldown" regression the plan fears. Need a test: pre-set suppress/cooldown/hold fields on a RoomFanState, release (both fan_mode and room_paused reasons), assert untouched.
- LOW: helper return value (`was_tracked`) is untested; forcing True only changes the log line (info vs debug), but a test on a fresh vs tracked state is cheap.
- MEDIUM (negative-space gap): nothing pins that a paused room is NOT excluded from `turn_off_all_managed` (kill-switch discharge). Over-gating survives. Add a paused-room test asserting the fan is still turned off.
- NOT DRILLED: smoke/CO safety stop emitter (separate emitter, hvac_fans.py ~1833 comment); no diff touches it, so no paused gate was added there. Recommend a one-line test that the safety path ignores `room_paused` only if a cheap fixture exists. Also minor: M09/M10 are both killed by a single test (assertions cover both surfaces, acceptable).

## Verdict: FIX-REQUIRED (test-only)
Must-fix: add the release-helper preservation test (suppress/cooldown/hold untouched) and the turn_off_all_managed-still-turns-off-paused-room test. No production-source defect found; all 17 load-bearing gate mutations die on a specific named test.

## Fix-up (2026-10-19)
Tests only. No production change; no test found a real bug.
- **MEDIUM (release-helper contract) FIXED.** `test_release_preserves_suppress_cooldown_and_hold` pre-sets `fan_recheck_suppress_until`, `manual_off_cooldown_until`, `manual_on_hold_until` and `manual_on_hold_paused_at`. It then drives `FanController.update` through both release callers (Fan Mode leaves Follow thermostat → `fan_mode`; Automation off → `room_paused`) and asserts that all four fields are untouched and nothing was written.
- **MEDIUM (turn_off_all_managed over-gating) FIXED.** `test_turn_off_all_managed_still_turns_off_paused_room_fan` asserts that a paused room's tracked-ON fan still gets its `turn_off`.
- LOW `was_tracked`: skipped (it only changes the log level).

| Mutation (hvac_fans.py) | Result | Killing test |
|---|---|---|
| helper also clears `fan_recheck_suppress_until` | RED | test_release_preserves_suppress_cooldown_and_hold |
| helper also clears `manual_off_cooldown_until` | RED | test_release_preserves_suppress_cooldown_and_hold |
| helper also clears `manual_on_hold_until` | RED | test_release_preserves_suppress_cooldown_and_hold |
| `turn_off_all_managed` skips paused rooms | RED | test_turn_off_all_managed_still_turns_off_paused_room_fan |

Each drill was mutated and restored in one Python try/finally, with PYTHONDONTWRITEBYTECODE=1 and `__pycache__` cleared. `git status` showed hvac_fans.py unmodified afterwards. Cycle files: 41 passed. Broader fan set + cycle files: 343 passed (341 + 2 new).
