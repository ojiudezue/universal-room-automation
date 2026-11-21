# AI-ROOM-RULES-TRUST-REPAIR-1 — Review C (test authority via per-site source mutation)

Branch `feature/unified-room-rules` (f096b8885 + ba03f7568), diff base 09292d006 (merge-base with develop verified).
Method: one production-source edit at a time, bytecode caches cleared before each run, restore in try/finally, `git status` clean after.
Target set per run (154 tests, ~4 s): test_room_rules_executor / _flow / _observability, test_rule_compiler,
test_automation_chaining, test_ai_automation, test_v458_signal_handler_gating, test_cycle_b_config_flow. Full suite not run.
Baseline 154 passed. 79 mutations; RED = at least one named test fails.

## RED rows (site is test-anchored) — first failing test(s)

| Site | Mutation | RED test |
|---|---|---|
| coordinator `_fire_chained_automations` gate call | direct `async_call` | test_kill_switch_false_runs_legacy_paths_through_gate |
| `_run_room_rules` action call (INV-R1) | direct `async_call`, res=issued | test_rules_automation_goes_through_gate (+6) |
| `_execute_rule_action` allowlist | `if False` | test_rules_allowlist_blocked |
| climate block | `if False` | test_rules_climate_blocked |
| security cover block | `if False` | test_rules_cover_security_owned_blocked |
| manual-hold oracle | `and False` | test_rules_light_respects_manual_hold |
| kill switch forced False | `if True` | 31 failed (test_rules_automation_off_skipped, ...) |
| `_rule_switch_skip` safety/security exemption (INV-R3) | removed | test_rules_safety_fires_with_switch_off, test_rules_security_fires_with_manual_mode |
| exemption for all triggers | `return None` | test_rules_enter_skipped_with_switch_off (+6) |
| manual_mode check | `if False` | test_rules_enter_skipped_with_manual_mode |
| switch_off check | `if False` | test_rules_enter_skipped_with_switch_off, test_house_state_rule_switch_off |
| loop ignores skip result | `skip = None` | test_rules_enter_skipped_with_switch_off (+5) |
| person listener automation-tier gate | removed | test_rule_person_event_paused_room_schedules_nothing |
| person rule fires on occupancy edge (INV-R5) | `elif person_trigger: continue` removed | test_rule_person_enter_not_fired_by_occupancy_edge |
| person event slug match | removed | test_run_room_rules_person_event_other_person_not_matched |
| `person_absent` check | `if False` | test_person_scoped_signal_rule_checks_presence |
| listener enter/exit swapped | | test_rule_person_enter_fires_on_person_event |
| listener person prefilter | `and r.get("person")` | test_rule_person_other_person_no_fire |
| person_trigger widened to any trigger | | test_person_scoped_signal_rule_checks_presence |
| decision record dropped / fire-only / twice (INV-R6) | | test_rules_automation_off_skipped (+21 / +14 / +16) |
| record: log line / episode row | removed | test_rule_decision_log_line_fields / 16 tests |
| needs_parse not skipped | | test_migration_data_only_rule_is_inert_and_flagged |
| enabled not honoured | | test_disabled_rule_not_matched |
| gate_blocked not flagged | | test_rules_light_respects_manual_hold, test_rules_cover_security_owned_blocked |
| automation_off check | | test_rules_automation_off_skipped |
| conditions ignored / not-ok no skip | | test_rule_condition_after_dark_false_skips, ..._time_window_crosses_midnight |
| reversal watch not started | | test_rule_reversal_light_turned_off_by_person (+5) |
| legacy path switch gate dropped | | test_kill_switch_false_runs_legacy_paths_through_gate |
| `_actions_well_formed` (empty / always True) | | test_status_sensor_states_exact[needs_parse], test_rules_digest_section |
| validate: empty actions, domain allowlist, climate re-added, light toggle, target outside room, data-key allowlist, domain mismatch | | test_rule_form_refuses_zero_actions, test_rule_compiler_rejects_climate_and_zero_actions, ..._light_toggle, ..._entity_outside_room_set, ..._unknown_key_by_name, ..._entity_of_other_domain |
| parse_and_validate ignores errors / unsupported dropped | | 8 failed / test_rule_compiler_unsupported_named |
| condition kind + house-state validation | | test_rule_compiler_conditions_validated |
| model_unavailable split: timeout, raise, entity unavailable, service missing, timeout wrapper | -> parse_failed / removed | test_rule_compiler_timeout_is_model_unavailable, ..._ai_task_error_is_model_unavailable(_in_form) |
| flow branches: model_unavailable, unsupported, not-ok | | test_rule_compiler_ai_task_error_is_model_unavailable_in_form, test_rule_form_refuses_unsupported_and_names_it, test_rule_form_refuses_unparsed |
| D8: data_only flag, data_only->needs_parse, options-first read, save drops needs_parsing, save keeps chains | | test_migration_data_only_rule_is_inert_and_flagged, test_first_edit_copies_data_rules_to_options_still_flagged, test_delete_and_legacy_chain_fold |
| `automation_action` skip_condition forced | | test_rules_automation_goes_through_gate |
| midnight wrap or->and, wrap end inclusive, clock corruption | | test_rule_condition_time_window_crosses_midnight |
| `dark_fn` inverted, failed-kind tracking | | test_rule_condition_after_dark_false_skips |
| trip-wire: signal dropped, fires>0, age floor, exempt triggers, knob 0, fires counted for skips, lookup key, severity | | test_rule_silent_tripwire_* (5 tests) |

## GREEN rows (mutation survived = untested site)

| # | Site | Mutation | Sev | Note |
|---|---|---|---|---|
| G1 | rule_compiler `adapt_rules` `or r.get("needs_parsing")` (D8c) | flag ignored | HIGH | D8 "inert until re-checked" is pinned only for empty-action rules (flow:204, executor:474 use `"actions": []`). A rule copied to options with `needs_parsing: True` and well-formed actions goes live after the first save. Need a test: well-formed actions + needs_parsing -> not matched, status needs_parse. |
| G2 | coordinator `_rule_is_dark` except->False, `auto is None`->False (D2, D3) and `evaluate_conditions` except->False (D1) | flipped to True | MEDIUM | is_dark fail-closed has no test at all; only the happy `after_dark=False` path (executor:283). |
| G3 | `evaluate_conditions` unknown kind (D5), `house_state` None (D6) | pass | MEDIUM | both fail-closed paths unpinned; None house state passing `house_state_in` is a fail-open. |
| G4 | `evaluate_conditions` unparsable time (T6), `s == e` runtime guard (T5), `validate_conditions` s==e (K14) | fail-open / guard removed | MEDIUM | a zero-width or garbled window is always-true via `in_time_window` (`now>=start or now<end`). Both layers independently unpinned. |
| G5 | `in_time_window` non-wrap boundaries (T2 start excl, T3 end incl) | | LOW | boundary semantics unpinned; only wrap case tested. |
| G6 | `validate_actions` "no target entity" (K7) | removed | MEDIUM | loop over empty ids no-ops; a target-less non-automation action validates. Runtime gate would catch some, not a clean rejection. |
| G7 | `_run_room_rules` action `rule_id` stamp (X6) | removed | LOW | stamp feeds climate-block log / attribution only. |
| G8 | `_record_rule_decision` `evaluations += 1` (R6c) | removed | MEDIUM | INV-R6 stats leg (log + episode are pinned; stats counter is not). |
| G9 | legacy `_execute_ai_rules` direct call (R1c) | gate bypass | MEDIUM | kill-switch path only (const True ships), but INV-R1 "no rule-derived call outside the gate" is not pinned on this site; test_kill_switch_false... covers chain path and switch gate, not the AI-rule action call. |
| G10 | `_on_person_location_change` `prev != room` guard (R5g) | removed | LOW | same-room event would fire enter; PersonCoordinator only emits on change. |
| G11 | person event vs non-person rule (R5b) | check removed | LOW | near-equivalent (slug mismatch falls through) except an event with empty person_id vs a rule with no person; untested edge. |
| G12 | `adapt_rules` non-list conditions -> needs_parse (D8g) | removed | LOW | |
| G13 | `adapt_rules` legacy-chain record `skip_condition` field (D8h) | True | LOW | informational field; the action payload (X1) is pinned. |
| G14 | room_rules_health skip of needs_parse/disabled rules (W6) | removed | LOW | a disabled rule with past decisions could page `room_rule_silent`. |

Equivalent / redundant mutants (no finding): R6l sort (adapt_rules already orders automation first), K11/K12 (downstream "no actions" still rejects), W3 (outer try swallows the TypeError; note the single outer try means one bad rule aborts paging for all remaining rooms — B's lane).
W9/X3 string matched 3 sites and was skipped; X4 (lookup key) is RED, reader key untested individually (LOW).

## Verdict: FIX-REQUIRED

Must-fix before ship: G1 (HIGH, inert-until-recheck read site). Should-fix in the same pass: G2, G3, G4, G6, G8, G9 (each a one-test addition; the listed fail-closed invariants are the cycle's stated trust properties).
Tree clean after every drill (verified via `git status --short`).
