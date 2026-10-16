# EC-RESERVE-WRITE-GOVERNOR-1 — Review C (test authority, real per-site source mutation)

Branch feature/reserve-governor 53b3ecb8f..1c5d9bc97. Method: one production-source mutation at a time, targeted files
(test_reserve_write_rows, test_reserve_governor_ab, test_reserve_write_chokepoint_lint; baseline 63 passed), PYTHONDONTWRITEBYTECODE=1,
__pycache__ purged per run, restore in finally; tree verified clean (`git diff` empty). ~115 mutations (some duplicates).

## RED (killed by a specific test) — load-bearing sites that ARE anchored
| Site | Mutation | Killing test |
|---|---|---|
| C1 call (energy.py ~9302) | `if False and ...` | test_reserve_row_on_timer_dispatch / blind_deescalation / never_awaited_on_dispatch_path |
| C1 guard target==reserve_eid | dropped | test_reserve_row_requires_configured_reserve_entity |
| C1 status FAILED branch | forced APPLIED | test_reserve_row_failed_dispatch |
| C1 path label | "evaluate" | test_reserve_row_on_timer_dispatch |
| C1 pre_state kwarg / tap kwarg / pre_state read removed | removed | test_reserve_row_first_write_after_boot_always_logged, cloud_lag_resend_is_two_rows |
| C2 call / status DEFERRED / pre_state / guard-service | removed or changed | test_reserve_row_on_evaluate_path, evaluate_path_gated_like_timer, lint test_no_unlisted_writers (service guard) |
| C3 FAILED call, APPLIED call | `if False` | test_reserve_row_on_force_redispatch_failure / _on_force_redispatch |
| C3 status/path/value swaps (APPLIED+FAILED) | swapped | test_reserve_row_on_force_redispatch(_failure), redispatch_bypasses_gate |
| C3 APPLIED own-guard (raise propagates) | `raise` | test_force_redispatch_row_call_cannot_fake_failure |
| C3 WriteStatus import replaced by fake | fake class | test_reserve_row_on_force_redispatch, status_values_come_from_the_enum |
| Helper gate: gated->False, pre_state None skip, pre_state compare dropped, DEFERRED ungated, redispatch gated | each | rows: gate_suppresses_identical_dispatch, pre_state_none_writes_row, cloud_lag_resend, evaluate_path_gated_like_timer, redispatch_ungated_even_with_equal_pre_state |
| Helper key components (path/value/hold_owner) | each dropped | test_reserve_row_failed_row_updates_memo |
| Memo never updated / set before DB-None return / FAILED not memoed | each | redispatch_ungated.., db_missing_dispatch_proceeds, failed_row_updates_memo |
| inclement_floor: no reserve_soc max, no dec floor, min/max, depth any, floor_ok inverted / always True | each | inclement_floor_expression, reads_current_tick_decision, blind_under_partial_hold_floor_ok_false, full_hold_has_no_inclement_floor_field |
| hold_owner None / re-sourced; desire=value; status .name; create_task removed / not scheduled; action name; importance; entity_id; payload pre_state/reason/evse_hold_soc | each | dp_fold_owner_and_value, records_overlay_value_not_desire, status_values_come_from_the_enum, never_awaited_on_dispatch_path, on_timer_dispatch, on_force_redispatch |
| Lint: drop/incr/decr allowlist entries, kind change | each | test_allowlist_pins_the_known_topology, test_no_unlisted_writers, test_lint_catches_second_writer_in_allowlisted_function |
| Lint injections in production source: action-dict, async_call positional, keyword form, second writer in allowlisted fn (_tap_write_verifier), writer in energy_battery | each | test_no_unlisted_writers (all 5 RED) |
| A/B golden: helper mutating _last_reserve_level, desire, _last_reserve_level_at, evse_hold_soc, issuing a service call | each | test_ab_golden_matches[*] (and/or lint) |

## GREEN on neuter = UNTESTED (findings)
| # | Sev | Site | Mutation left GREEN | Gap |
|---|---|---|---|---|
| 1 | MEDIUM | energy.py ~7432 pre_state ordering | pre_state read moved AFTER `_execute_service_action` | Entire purpose of the pre-dispatch read (state may reflect the write). No test makes the mock state change on dispatch; add a stub whose `_get_state_float` flips after service call and assert gate/pre_state uses the pre-write value. |
| 2 | MEDIUM | energy_battery.py ~6852 C3 FAILED own-guard | swallow replaced by `raise` | Only APPLIED has a "recorder raises" test (cannot_fake_failure). If `_record_reserve_dispatch` raises on the FAILED leg it escapes from inside the service-call `except` and out of force_redispatch (plan G-1). Needs a raising-recorder test on the failure path. |
| 3 | MEDIUM | helper outer `except Exception` (energy.py ~9220) | handler narrowed so any exception propagates | No test makes the helper itself raise (existing "RAISES" test stubs the helper at C3). INV "row never poisons dispatch" is unanchored for C1/C2 (C2 is not wrapped by a caller try). Drive a bad `value`/DB that raises inside the helper and assert dispatch proceeds. |
| 4 | MEDIUM | helper skip branch memo (~9174) | memo cleared/clobbered on SKIPPED | No 3-identical-sends test; the second skip would be fine, third re-logs. Add: send x3 identical with pre_state==value -> exactly 1 row. |
| 5 | MEDIUM | helper gate `status in (APPLIED, DEFERRED)` | FAILED added to gated set | R3-01 "FAILED bypasses the gate": a failed re-send of an identical value with matching pre_state would be silently dropped; no test with FAILED + equal key + equal pre_state. |
| 6 | LOW | C2 guard `target == _res_eid` | dropped | Only the service guard is tested; a non-reserve `number.set_value` in evaluate actions would produce a bogus reserve_write row. Add non-reserve-target evaluate test. |
| 7 | LOW | helper value clamp (0..100) | lower-only / upper-only / none | out-of-range value (e.g. 150, -5) untested. |
| 8 | LOW | gate `int(round(float(pre_state)))` | round -> trunc | pre_state 59.6 vs value 60 untested. |
| 9 | LOW | C3 `getattr` reach | direct `self._coord._record...` | EQUIVALENT in effect (own guard swallows AttributeError) - not a test hole in behaviour; only differs in log noise. |
| 10 | LOW | C1 guard `reserve_eid and` truthiness; pre_state guard `if True`; db-None branch; log_activity `room=` | each | Equivalent or cosmetic (pre_state read for non-reserve targets is harmless; db None caught by outer except). Noted, no action. |

Note: drill "H gate FAILED excluded precisely" duplicated #5.

## Verdict: FIX-REQUIRED (test-authority only; no production defect found)
The suite is strong: ~90% of mutations RED with specific tests, lint injection in all four shapes works, A/B golden catches helper side effects.
Must-fix before SHIP (add tests, no source change expected): #1 (pre-write ordering), #2 (FAILED-leg recorder raise), #3 (helper self-raise
swallow), #4/#5 (memo-on-skip and FAILED-bypass gate). #6-#8 should be fixed in-cycle per Fix-LOWs rule (1-10 LoC tests).

Final state: production source restored, `git diff` empty; only untracked review files remain.
