# House-state step 1a: Review C (test authority, per-site source mutation)

Branch `feature/house-state-step1a` @ 1c602a1b, base develop 7d826060. Plan: PLANNING_house_state_axes_step1.md rev 3 Part A (§A9 drill table).
Method: one production-source edit at a time (exact-string, count==1), then the cycle's test files plus the lock/perimeter families
(about 40 files incl. tests/perimeter/), `PYTHONDONTWRITEBYTECODE=1 -p no:cacheprovider`, restore in a try/finally, `git status` clean after every batch.
Baseline: 560 passed. Harness: scratchpad `drillC.py` (not committed).

## Result: 78 mutations run (27 plan-drilled sample + 28 hunted + 23 further sites); 70 RED, 8 GREEN

### Plan drills independently re-run (all RED, first failing test named)
| Drill | Invariant | Mutation | First RED test |
|---|---|---|---|
| A1 | INV-RULE | `>=` to `>` in really_away | test_arrival_edges_counted_return::test_lock_rule_matches_oracle[away_900] |
| A2 | INV-RULE | update_last_real always restamps | test_residency_tracker::test_attribute_event_keeps_since |
| A3 | INV-RULE | lock `_arrival_counts` inlined | test_sc_garage_lockout::test_blip_rule_applies_after_real_transition_seen |
| A4 | INV-PRODUCER | feed removed from listener | test_residency_setup_realhass::test_presence_async_setup_builds_residency |
| A6 | INV-PRODUCER | memory-row logger neutered | test_residency_wiring::test_memory_row_per_record_and_teardown_gather |
| A7 | INV-PRODUCER | writer-backed set loses person_arrival | test_residency_wiring::test_writer_health_registration_backed_and_absence_exempt |
| A8a/b | INV-RULE (trust) | phone cut / raw state read | test_exterior_severity_axes::test_arriving_phone_left_behind_critical; test_residency_wiring::test_residents_home_trust_and_phone_left_behind |
| A9 | INV-LOCK | HOME_*/ARRIVING releases without operator | test_sc_garage_lockout_real_ha::test_real_ha_8632_shape_person_edge_after_arriving_releases (plus 10 more) |
| A10 | INV-LOCK | override_clear dropped | test_sc_garage_lockout::test_guest_exit_to_home_releases_guest_night |
| A11 | INV-LOCK | ignored edge clears manual memory | test_sc_garage_lockout::test_vacation_end_clears_remembered_unlock |
| A12 | INV-PAGE | boot-gap tuple narrowed | test_lock_release_arriving::test_boot_gap_silent_when_restored_house_not_away |
| A13/13b | INV-PAGE | saw_empty set on edge / taint migration | same + test_lock_house_edges_axes::test_saw_empty_store_migration_from_taint |
| A14 | INV-LOCK | trip-wire dead | test_lock_release_arriving::test_tripwire_covers_boot_recheck_channel_two_rigs[home_day] |
| A15 | INV-REAL | S1 `_release` deleted | test_sc_garage_lockout_real_ha::test_real_ha_8632_shape... |
| A16 | INV-SEV (C1) | presence lookup reverted | test_house_state_sleep_mask_ble_memory::test_perimeter_persons_home_counts_stale |
| A17 | INV-NO-LOWER | persons_home switch ignored | test_perimeter_alert_nm_routing::test_MUTATION_contextual_severity_load_bearing |
| A18a/b/c | INV-SEV | CRITICAL arm off / include_stale / persons_home read | test_no_lower_golden; test_arriving_stale_or_boot_arrival_critical; perimeter/test_circling_severity_per_state[0] |
| A19 | INV-MACHINE | `_run_inference` closure edited | test_house_state_sleep_mask_ble_memory::test_last_away_branch_active |
| A20/A20b | INV-MACHINE | method invert / 4763 delegation | test_v4714_1_forgotten_phone_hotfix::...entity_registry; test_residency_wiring::test_fan_gate_closure_delegates |
| A21 | INV-PAGE | saw_empty set narrowed | test_lock_release_arriving::test_override_guest_night_to_home_night_from_arriving_no_taint |
| A22 | INV-PAGE | gap page ignores saw_empty | test_boot_gap_silent_when_restored_house_not_away |
| A23 | INV-LOCK | cancel_backstop added to arrival | test_lock_house_edges_axes::test_arrival_outside_window_keeps_backstop_ends_episode |
| A24 | INV-SEV | evidence try/except | test_exterior_severity_axes::test_arriving_evidence_error_resolves_critical_and_logs |

All six invariant groups are covered by at least 2 RED rows each. Builder claim "A1-A24 red" is confirmed on the 22 sites sampled here.

### Sites the builder did not drill (hunted): RED
source_stale threshold/flag (U1/U25), recent_arrival filters counted/boot/age/unresolved (U3a-d), departure UNREAL guard (U4),
pre-update-ledger ordering (U5), resident gating (U5b), evidence arms (U7/U7b), persist guard/knob (U9/U10), `_end_episode_flags` at
house release/engage (U11/U12), saw_empty persistence and both boot sets (U13/U15/U16), uncounted-page saw_empty arm (U14),
boot-window arg in `_arrival_counts` (U18), waking release (U19), guest yield (U20), restore-path feed (U22), house_state stamp
into severity log (U27), lock restore stamp / S5 ledger / uncounted page / boot-gap home filter / HOME-reason-NONE / vacation engage
(L2,L3,L5,L7-L10), persons_home count (P1/P2), teardown/flag/setup/boot window/unload (T1-T5), approach zone (L4, RED once the
review_c file is in the target set; pre-existing, unchanged by the diff).

### GREEN rows (untested or equivalent)
| # | Site | Mutation | Verdict |
|---|---|---|---|
| B1 | binary_sensor.py `ura_house_occupied` via `get_house_occupancy()` | getter result ignored (`return True`) | **MEDIUM, untested.** The rewired user-facing sensor has no test at all (no test references the entity). "Byte-identical" for AWAY/VACATION is claimed, never pinned. U17 (GREEN too) shows `get_house_occupancy` itself is unpinned for `vacation`: dropping vacation from the empty set leaves the suite green. Bug class #62 (claim without anchor). |
| L1 | lock `_really_away` call site | `in_boot_window=False` | **LOW/MEDIUM.** Away-lock P1/P2 boot semantics through the delegated helper not pinned at that call site (shared function is pinned via counted_return tests). Checked with the away-lock family added to the target set; still GREEN. |
| S1 | `ResidentsHomeSensor.native_value` | returns 0 | LOW, display-only new entity, no test of state or attributes. |
| L6 | `_uncounted_return_pages` house-state `away/arriving` arm | removed | LOW. Arm is redundant with saw_empty set at edge/boot (reachability needs kill-switch toggled mid-episode); consider deleting or pinning. |
| U26 | house_state passed into the record | `None` | LOW, display attribute only. |
| U8 | evidence computed outside ARRIVING | gate removed | Equivalent for behaviour (resolver reads evidence only in the ARRIVING arm); only adds a presence read and an INFO line per non-arriving alert. LOW, optional test. |
| U2, U3e, U23 | unresolved residents guard, `within_s <= 0`, phone `unavailable` guard | | Equivalent mutants (downstream logic yields the same result); no finding. |
| U24 | `_cancel_backstop` in house-release branch | removed | Pre-existing line, not in the diff; `_on_backstop` is inert when reason is NONE. No finding. |

## Findings
- MEDIUM (C-1): `ura_house_occupied` rewiring and `get_house_occupancy` vacation arm have no authoritative test (B1, U17). Add one test: state `away`/`vacation` -> off, others -> on, through the real binary sensor and through the getter; neuter-and-confirm RED.
- LOW (C-2): L1 away-lock `in_boot_window` wiring unpinned.
- LOW (C-3): `ResidentsHomeSensor` state/attributes unpinned (S1).
- LOW (C-4): L6 redundant arm; U8 stray evidence compute.

No GREEN row touches an INV-LOCK, INV-PAGE, INV-RULE, INV-PRODUCER, INV-SEV/NO-LOWER or INV-MACHINE load-bearing site that matters
to paging or unlocking; every such site flipped RED. The one MEDIUM is a user-visible sensor in the D2 surface.

Tree left clean (`git status --short` empty before this doc).

## Verdict: FIX-REQUIRED (narrow)
Must-fix: add the C-1 test pair (binary sensor + getter, vacation included) with its own drill. C-2..C-4 may ride in the same fix-up (each about 10 LoC). Everything else is SHIP-quality on test authority.
