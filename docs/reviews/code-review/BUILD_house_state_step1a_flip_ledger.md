# House-state step 1a: build flip ledger

Branch `feature/house-state-step1a` (from develop 7d826060). Plan
`docs/planning/PLANNING_house_state_axes_step1.md` rev 3, Part A (D4 build H7 and D5 delta H2 require this ledger).
Every test that went RED on D4 or D5, its old expectation, its new one, and how it changed. "Rewritten" means the same
scenario with a new assertion. "Re-pointed" means the test now uses an operator trigger; that is only done where the
test's subject is an operator action. "Switch in body" means the test patches
`EXTERIOR_SEVERITY_PERSONS_HOME_FROM_RESIDENCY` True in its own body because its scenario has a resident at home. No
shared fixture or conftest sets a switch.

## D4: lock regime (taint retired, INV-LOCK)

The rig's default trigger `"t"` is unchanged. `Rig.edge` gained an optional `trigger=` argument whose default is still
`"t"`.

| Test | Old expectation | New expectation | How |
|---|---|---|---|
| `test_lock_release_arriving.py::test_body_only_arriving_does_not_release_sleep` | `arriving_hold`, taint and saw flag set, `arriving_holds` 1 | `house_edge_ignored`, `episode_saw_empty` True, `house_edges_ignored` 1 | rewritten |
| `::test_arriving_then_home_star_chain_holds_until_backstop` | `arriving_holds` 4, taint cleared by the backstop | `house_edges_ignored` 4, `saw_empty` cleared | rewritten |
| `::test_person_release_keeps_taint_later_home_star_held` | taint kept, `arriving_hold` | `saw_empty` kept, `house_edge_ignored` | rewritten |
| `::test_boot_settle_suppressed_arriving_old_state_taints` | `arriving_hold` | `house_edge_ignored` and `saw_empty` True (old side) | rewritten |
| `::test_boot_rebuild_away_locked_taints` | taint at boot, recheck `arriving_hold` | `saw_empty` at boot, recheck `house_edge_ignored` | rewritten |
| `::test_boot_rebuild_away_then_arriving_home_night_edge_held` | `arriving_hold` twice | `house_edge_ignored` twice | rewritten |
| `::test_boot_recheck_arriving_never_releases_even_resident_home` | decision `arriving_hold` | decision `house_edge_ignored` | rewritten |
| `::test_boot_recheck_arriving_taints_later_home_star_held` | store `garage_arrival_taint` | store `garage_episode_saw_empty`, decisions `house_edge_ignored` | rewritten |
| `::test_boot_recheck_sleep_vacation_rebuild_clears_taint[sleep,vacation]` | taint keys | `saw_empty` key | rewritten |
| `::test_boot_rebuild_sleep_vacation_clears_restored_taint[sleep,vacation]` | taint keys | `saw_empty` key | rewritten |
| `::test_taint_persisted_across_restart_two_rigs` | taint persisted, `arriving_hold` | `saw_empty` persisted, `house_edge_ignored` | rewritten |
| `::test_manual_unlock_memory_survives_tainted_boot_recheck` | decision `arriving_hold` | decision `house_edge_ignored` | rewritten |
| `::test_guest_clock_clears_taint` | next-morning default HOME_DAY releases | it is ignored; the 07:00 backstop releases | rewritten (behaviour change) |
| `::test_every_reason_none_site_clears_flags[5 sites]` | taint and saw keys False | `saw_empty` False, legacy key absent | rewritten |
| `::test_boot_guest_night_rebuild_keeps_taint` | taint kept, `arriving_hold` | `saw_empty` kept, `house_edge_ignored` | rewritten |
| `::test_boot_nothing_locked_clears_stale_taint` | rig 3 boot recheck releases a hand lock (home_day) | flag cleared as before; rig 3 decision `house_edge_ignored`, 0 unlocks (delta L2) | rewritten (behaviour change) |
| `::test_override_set_arriving_releases_without_taint` | no taint, `arriving_holds` 0 | release, reason none, `saw_empty` False (episode ended), `house_edges_ignored` 0 | rewritten |
| `::test_reason_none_arriving_no_unlock` | taint False | `saw_empty` False, `house_edges_ignored` 0 | rewritten |
| `::test_override_guest_night_to_home_night_from_arriving_no_taint` | an operator edge with old arriving sets no taint | `saw_empty` set (delta M2: not gated on operator; it only pages) | rewritten (expectation inverted by the plan) |
| `::test_extreme_vacation_chain_released_by_waking_after_sleep` | taint key | `saw_empty` key | rewritten |
| `::test_extreme_kill_switch_off_in_tainted_episode_releases_once` | taint key | `saw_empty` key | rewritten |
| `::test_extreme_reengage_delay_after_night_person_release_then_arriving[0,900,7200]` | taint key | `saw_empty` key | rewritten |
| `::test_extreme_arriving_away_flap_x5_then_resident_edge` | `arriving_holds` 5 | `house_edges_ignored` 5 | rewritten |
| `::test_tripwire_fires_on_house_state_unlock_when_gate_bypassed`, `::test_tripwire_silent_when_nothing_written`, `::test_tripwire_disabled_by_constant` | seam patched `_edge_decision(override=)` | seam patches `_edge_decision(operator=)`; same assertions | seam renamed (L3) |
| `::test_tripwire_silent_on_untainted_house_state_release` | default HOME_DAY releases, no page | default HOME_DAY ignored (0 unlocks, no page); `override_clear` HOME_DAY releases, no page | rewritten |
| `::test_still_locked_tainted_home_night_lock_back_after_30s` | `arriving_hold` | `house_edge_ignored` | rewritten |
| `::test_boot_recheck_waking_release_kept_no_tripwire` | store `garage_episode_saw_arriving` | store `garage_episode_saw_empty` | rewritten |
| `::test_boot_kill_switch_off_clears_restored_taint` | rig 3 boot recheck releases | flag cleared as before; rig 3 `house_edge_ignored`, 0 unlocks (delta L2) | rewritten (behaviour change) |
| `::test_boot_gap_return_pages_never_releases` | decision `arriving_hold` | decision `house_edge_ignored` | rewritten |
| `::test_boot_gap_silent_when_restored_house_not_away` | restored home_day, recheck arriving: silent | split: never-empty episode (no AWAY edge, recheck home_day) is silent; the same restore with the persisted flag pages twice (delta M3). `_gap_rigs` gained `away_edge=` | rewritten |
| `::test_boot_gap_reads_exclusion_list_live` | decision `arriving_hold` | decision `house_edge_ignored` | rewritten |
| `::test_restored_sleep_untainted_home_releases_at_recheck` | released at the boot recheck | renamed `test_restored_sleep_untainted_home_ignored_at_recheck_backstop_releases`: `house_edge_ignored` at the recheck, the 07:00 backstop releases (delta L2) | rewritten and renamed |
| `::test_restored_reason_confirmed_by_boot_window_engage_not_provisional` | decision `no_change` | decision `house_edge_ignored` | rewritten |
| `::test_restored_reason_manual_unlock_remembered_rebuilds_episode` | taint keys | `saw_empty` keys | rewritten |
| `::test_tripwire_covers_boot_recheck_channel_two_rigs` | (green) | docstring updated only | n/a |
| `test_sc_garage_lockout.py::test_boot_recheck_releases_boot_unknown_lock_in_awake_house` | released at the recheck | renamed `test_boot_recheck_ignores_boot_unknown_lock_in_awake_house_backstop_releases`: `house_edge_ignored`, the 07:00 backstop releases (delta L2) | rewritten and renamed |
| `::test_boot_recheck_holds_boot_unknown_lock_when_arriving` | decision `arriving_hold` | decision `house_edge_ignored` | rewritten |
| `::test_boot_recheck_guest_yield_hold_respected` | next default HOME_DAY releases | ignored; the 07:00 backstop releases | rewritten |
| `::test_boot_recheck_boot_unknown_but_already_unlocked_no_release` | decision `no_change` | decision `house_edge_ignored` | rewritten |
| `::test_remembered_unlock_cleared_at_episode_end_next_episode_locks[home_day]` | default HOME_DAY ends the episode | param replaced by `[backstop]`: HOME_DAY is ignored and keeps the memory, the 07:00 backstop clears it | rewritten |
| `::test_vacation_end_clears_remembered_unlock` | default HOME_EVENING clears the memory | HOME_EVENING ignored (memory kept); a resident arrival ends VACATION; the next awake edge with reason none clears it | rewritten |
| `::test_boot_recheck_home_night_outside_window_releases_boot_unknown` | released at the recheck | renamed `test_boot_recheck_home_night_outside_window_not_guest_yield`: not converted to guest_night, `house_edge_ignored`, no release | rewritten and renamed |
| `::test_override_sleep_to_home_releases` | default HOME_DAY releases | `override_set` HOME_DAY releases | re-pointed (the subject is the override) |
| `::test_arriving_does_not_release_engaged_episode` | `arriving_hold` | `house_edge_ignored` | rewritten |
| `::test_guest_exit_to_home_releases_guest_night` | default GUEST -> HOME_DAY/EVENING releases | default exit ignored, the backstop releases; `override_clear` exit releases | rewritten |
| `::test_lock_held_if_home_night_until_morning` | 06:00 HOME_DAY releases | ignored; the 07:00 backstop releases | rewritten |
| `::test_manual_sleep_to_home_night_in_window_releases` | default HOME_NIGHT releases | `override_set` HOME_NIGHT releases | re-pointed (docstring: "an override to HOME_NIGHT") |
| `::test_guest_night_home_night_outside_window_releases` | default HOME_NIGHT releases | `override_set` HOME_NIGHT releases | re-pointed (docstring: "forced") |
| `test_sc_garage_lockout_real_ha.py::test_real_ha_body_only_arriving_holds` | `arriving_hold` | `house_edge_ignored` | rewritten |

Plan floor tests that stayed green, so no flip was needed: `test_lock_once_at_guest_clock_no_unlock_on_yield`,
`test_lock_toggle_off_unchanged`, `test_guest_clears_then_sleep_engages`, `test_regime_never_emits_cover_service`,
`test_arriving_with_reason_none_does_not_release_hand_lock`, the three `test_sc_garage_lockout_review_c.py` tests, and
`test_real_ha_8632_shape_person_edge_after_arriving_releases`.

## D5: exterior severity (C1)

| Test | Old expectation | New expectation | How |
|---|---|---|---|
| `test_perimeter_alert_nm_routing.py` fixture `_make_hass` | `cm.presence._tracked_persons_count_trusted = persons_home` (the C1 lie) | `cm.coordinators = {"presence": _FakeResidencyPresence(persons_home)}` with real getters and no `.presence` | fixture rule (3) |
| `::test_severity_maps_by_house_state[home_day]`, `[home_evening]` | LOW | HIGH (switch False, persons_home 0, as production) | rewritten |
| `::test_severity_maps_by_house_state[arriving]` | MEDIUM | MEDIUM: the fake reports 1 resident home, which is the evidence | unchanged value |
| `::test_guest_keep_high_through_consumer[egress-first_sighting-1]` | MEDIUM | HIGH (switch False) | rewritten |
| `::test_MUTATION_contextual_severity_load_bearing` | restore proof home_day LOW | restore proof home_day HIGH (still discriminates vs neutered CRITICAL) | rewritten |
| `perimeter/test_circling_founding_case.py` fixture `_make_hass_with_linker` | `cm.presence` fake | `coordinators` fake with real getters | fixture rule (3) |
| `perimeter/test_circling_founding_case_transition.py::test_founding_shape_produces_exactly_one_high_circling_page` | resident home via the fake: hops LOW, one HIGH | same scenario; switch in body | switch in body |
| `perimeter/test_circling_label_transition.py::test_exemption_dispatch_severity_survives_coercion`, `::test_exemption_hop_not_deduplicated_against_baseline_hop` | same | same; switch in body | switch in body |
| `test_perimeter_identity_followup.py::test_followup_not_armed_for_low_alert` | home_day LOW via `persons_home=1` | same scenario; switch in body | switch in body |
| `test_house_state_sleep_mask_ble_memory.py::test_perimeter_persons_home_counts_stale` | 2 through a fake `manager.presence` (hollow) | manager with `coordinators` only: switch False gives 0, switch True gives the residents-home count (1) | rewritten |

**Finding the circling flips expose (pre-existing, not caused by 1a):** with the live default (switch False,
`persons_home` 0, which is what production always resolved), every HOME_DAY / HOME_EVENING exterior hop is already
HIGH. The circling-transition design's "hop 1 and hop 3 differ in severity, so the NM dedup key cannot collide" (MED-2
pin) therefore does not hold in production: hop 1 (pass_by, HIGH) and hop 3 (circling, HIGH) share a severity. The
tests only passed because their fake claimed a resident at home. Card candidate.

## D2: residency

| Test | Old | New | How |
|---|---|---|---|
| `test_v4714_1_forgotten_phone_hotfix.py::TestH2PhoneLeftBehindExclusion::test_h2_filter_uses_entity_registry` | source-text window over the first `def _phone_trustworthy` | behavioural test of `PresenceCoordinator._phone_left_behind_on` (registry lookup by unique id, no bare-slug read) | converted (Bug Class #62, DoD 7) |

Pre-existing, order-dependent and unchanged by this build: `test_house_state_attr_unrecorded.py::test_churny_keys_unrecorded`
and `::test_low_churn_diagnostics_stay_recorded` fail in the same multi-file run on develop 7d826060. Running
`test_v4714_1_forgotten_phone_hotfix.py` on its own fails at collection on develop too.

## Review fix-up (A-H1/B-H1/D HIGH-1, A-M1, A-M2, B-L1, C-1..C-3, D LOW-2)

| Test | Old | New | How |
|---|---|---|---|
| `test_residency_wiring.py` fixture `_coord` default and the `_PC` / resident-set fakes | `tracked_persons` in entity-id form (`person.oji_udezue`), a shape production never has | display names (`"Oji Udezue"`, `"Ezinne Udezue"`), the live integration-entry shape | fixture rule (production shape) |
| `test_lock_house_edges_axes.py::test_boot_gap_page_on_saw_empty_vacation` (rig3 discriminator) | restored vacation lock, stored flag False, house home_day at boot -> no page | same scenario -> flag set at the boot rebuild, 2 boot-gap pages, no unlock | D LOW-2 behaviour change (operator-requested) |
