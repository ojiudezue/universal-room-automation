# Review C (test authority, real per-site source mutation) - census deconfliction + crossing ledger (P2-D1..D3 / CD1..CD3)

Branch `feature/census-deconfliction-p2-ledger`, HEAD `ed9229c5`, diff base `3ec3f4d2` (three-dot `3ec3f4d2...HEAD`, verified as the merge-base).
Plans: `PLANNING_crossing_vision.md` P2-D1..D3, `PLANNING_census_deconfliction.md` CD1..CD3.

## Method
- One production-source site neutered at a time, in a private detached worktree of `ed9229c5` (`.claude/worktrees/review-c-census-p2`), restored byte-identically in the same Python step (sha256 verified `restore=ok` on every row), `__pycache__` purged and `PYTHONDONTWRITEBYTECODE=1` before every run, `ps -A` ~610-660 throughout.
- 221 mutations run (builder reported 107 drills): crossing_ledger.py 68, census_deconflict.py 16, camera_census.py wire-in 18 + 2 trust-leak, presence.py 12, switch.py 7, sensor.py 8, config_flow/`__init__` 2, crossing_vision.py wiring 81 (one invalid drill, CV62, discarded), plan AWAY drills + trust-view separation 7.
- Test set per row: cycle files (`test_crossing_ledger`, `test_crossing_ledger_wiring`, `test_census_trust_golden`, `test_census_deconflict`, `test_census_awareness_surface`, `test_residency_signal`, `test_crossing_vision_shadow`, `test_crossing_vision_setup_wirein`) + module siblings. Every row that stayed GREEN was re-run against the WIDE set (all `test_census_*`, `test_crossing_*`, `test_residency_*`, `test_person_awareness_read_api`, `test_camera_census`, `test_face_source_registry`, `test_guest_census_correctness`, forms tests): 3 rows (PR08/PR10/PR11) turned RED there (they live in `test_person_awareness_read_api.py`); 48 stayed GREEN.
- Baseline green: 119 passed / 1 skipped (core) and 1080 passed / 1 skipped (WIDE).

## Process incident (report to orchestrator)
At ~00:45 the shared tree `superbuilder-census-p2` showed `crossing_ledger.py` carrying exactly my CL03 mutation (`term_count` outcome guard removed) that I had not left behind (my driver verified restore, and `git status` was clean after my first run). A second reviewer (B) was writing to that tree at the same time. I restored the file from `git show HEAD:` (byte-identical to HEAD, `git status` clean apart from reviewer B's own untracked file), moved all further drilling to my private worktree and deleted my helper files from the shared tree. If reviewer B or anyone else ran suite evidence in that window, treat it as potentially poisoned (unrestored-drill hazard).

## Requested focus: the four AWAY drills and the trust golden (all RED, as required)

| Drill (plan section 4) | Mutation | RED test |
|---|---|---|
| (1) publish `aware_total` under `interior_count` | `camera_census.py` dispatch `"interior_count"` = `aware_total` | `test_census_existing_fields_golden_all_classes[vision50_lead]`, `test_away_tick_identical_with_vision_payload[vision50_lead]`, `test_excluded_consumers_never_read_vision[vis0]` |
| (2) `_handle_census_update` assigns awareness `.total` to `_census_count` | `presence.py` `_handle_census_update` | `test_away_tick_identical_with_vision_payload[vision50_lead]`, `test_excluded_consumers_never_read_vision[vis0/vis50]` |
| (3) vision/aware guests into `unidentified_count` in the producer | `CensusZoneResult(unidentified_count=awareness['aware_guests'])`; also LK2 (variable reassigned) | `test_awareness_entities_follow_vision_after_lead`, `test_away_tick_identical_with_vision_payload[vision50_lead]`, `test_census_existing_fields_golden_all_classes` |
| (4) boot seed from `sensor.ura_census_people_around` | `presence.py` seed fallback entity | `test_boot_seed_ignores_vision_sensors` |
| Trust-view separation neutered: `total_persons` = `aware_total` (AW6, LK1), `identified_count` = `aware_total` (AW7), trust read of `get_house_census` returns aware values (PR12), `view_for_class` untruthed (PR07/PR09) | each one site | golden `test_away_tick_identical_with_vision_payload[vision50_lead]` / `test_census_existing_fields_golden_all_classes[...]` or `test_switch_off_reads_trust[...]`, `test_get_house_census_awareness_reads_aware_fields`, `test_view_for_class_security_always_trust[...]` RED |

One adjacent site is NOT covered (finding M3): the boot seed from the census manager's `last_result` (`presence.py` `self._census_count = last.house.total_persons`).

## Per-site table (RED = a named test fails on neuter)

Abbreviations: RED rows list the first named test; full lists are in the drill log. "EQ" = equivalent mutant (explained), "GAP" = untested site.

### crossing_ledger.py (pure core)
| Site | Result | Test / note |
|---|---|---|
| term_count skip policy (CL04), peak fallback (CL05), cluster single-direction (CL07), mixed-direction per member (CL08), primary n fallback (CL09) | RED | `test_fallback_skip_policy`, `test_cluster_mixed_direction_per_member*`, `test_every_outcome_yields_one_term_or_documented_none[blank]` |
| term_count `outcome == ok` guard (CL03) | GREEN (GAP, LOW) | people_count is only non-None when outcome is ok (parse_vision_response), so unreachable via wiring, but the pure contract is unpinned |
| `_count` bool / negative (CL01, CL02), cluster usable-empty guard (CL06) | GREEN (GAP, LOW) | defensive input validation, no test with `True` / `-1` / non-entry-exit direction |
| guest_vis clamp `max(0, ...)` (CL10), apply_term `state != KNOWN` (CL23), judge `state != KNOWN` (CL60) | GREEN (EQ) | `census_tick` floors L to R and `L is None` while unknown, so each is redundant with the sibling guard |
| healthy() dark / None (CL11, CL12), set_unknown (CL13, CL14), rebase ts (CL15), floor (CL17), dark store (CL18), bodies None-as-0 (CL19), body ts (CL20) | RED | `test_dark_fleet_stops_window`, `test_none_bodies_is_failing_sample`, `test_set_unknown_forgets`, `test_anchor_zero_clock_restarts_on_enable`, `test_floor_raises_only`, `test_stale_body_value_fails_sample` |
| rebase clears anchor-zero latch (CL16) | GREEN (GAP, MED) | a re-enable after an anchor-zero page never re-arms the page |
| rising edge (CL21), exit-es record (CL22), late term (CL24), entry add (CL25), exit clamp (CL26), entry blocks window (CL27) | RED | `test_rising_edge_restarts_anchor_window`, `test_reconcile_only_without_exit_term`, `test_late_term_recorded_not_applied`, `test_exit_clamps_at_zero_raw_kept`, `test_entry_term_restarts_anchor_window` |
| terms_today counter (CL28), reset_daily_counters (CL68) | GREEN (GAP, LOW) | display counters |
| freshness (CL29), bodies==0 (CL30), dark in sample (CL31), edge (CL32), entry (CL33), empty_reset (CL34), flag clears (CL35, CL36), t_start reset (CL37) | RED | `test_stale_body_value_fails_sample`, `test_anchor_needs_zero_bodies_and_no_edge_for_window`, `test_dark_fleet_stops_window`, `test_anchor_sets_L_to_resident_term` |
| stuck-sample entry exemption (CL38), stuck re-arm on gv 0 (CL39) | RED | `test_stuck_page_resident_independent` |
| stuck_since cleared when a sample is not zero-body (CL40) | GREEN (GAP, MED) | a lit sample with bodies does not restart the stuck timer in any test: the page can fire on non-contiguous evidence |
| anchor L=R (CL41), known (CL42), last_anchor (CL43), anchor-zero latch (CL45), independent (CL46, CL47), residue (CL48) | RED | `test_anchor_sets_L_to_resident_term`, `test_anchor_zero_pages_once_and_rearms`, `test_independent_flag_on_back_to_back_anchors`, `test_residue_recorded_before_reset` |
| anchor pending-void (CL44) / judge anchor-void (CL54) | GREEN singly (EQ pair) | removing BOTH -> `test_anchor_voids_pending_reconcile` RED (verified); each layer alone is sufficient |
| note_departure known/enabled (CL49, CL50), due delay/lag (CL51, CL52), pending store (CL53), window lo (CL55), L-1 (CL57), counter (CL58), enabled (CL67) | RED | `test_reconcile_not_tracked_while_unknown`, `test_reconcile_window_zero_disables`, `test_reconcile_only_without_exit_term` |
| reconcile window HI bound (CL56), reconcile marks changed_since_anchor (CL59) | GREEN (GAP, MED) | an exit after `t_e + lag` cancelling a reconcile, and the independence bit after a reconcile, are unpinned |
| stuck latch/duration/off (CL61, CL62, CL63), anchor-zero latch/since/off (CL64, CL65, CL66) | RED | `test_stuck_ledger_pages_once`, `test_stuck_page_resident_independent`, `test_tripwire_zero_means_off[...]`, `test_anchor_zero_pages_once_and_rearms` |

### census_deconflict.py
| Site | Result | Test |
|---|---|---|
| max->sum (CD03), extra terms (CD05) | RED | `test_guest_side_max_not_sum` |
| missing term drop (CD04), lead gate (CD06, CD07), total (CD08), identified copy (CD09), case D value (CD10), agree/close thresholds (CD11, CD12), case (CD13), provenance (CD14), guest_cam source (CD15), trust passthrough (CD16) | RED | `test_awareness_equals_trust_until_lead[...]`, `test_awareness_follows_vision_once_lead[...]`, `test_flag_min_extremes`, `test_census_publishes_awareness_from_ledger` |
| `_count` bool / negative (CD01, CD02) | GREEN (GAP, LOW) | input comes from the ledger (already validated) |

### camera_census.py (wire-in)
| Site | Result | Test |
|---|---|---|
| `_compute_awareness` call (CC01), `**awareness` spread (CC02) | RED | `test_awareness_entities_equal_trust_dark`, `test_census_existing_fields_golden_all_classes` |
| R missing presence (CC04) / exception (CC05) | RED | `test_census_publishes_awareness_from_ledger`, `test_resident_term_reads_presence_residents` |
| R = max(presence, identified) (CC03) | GREEN (GAP, MED) | no test with `identified_count > residents_home`: a known-guest identified person would count as a ledger guest |
| bodies source (CC06), ledger tick exception (CC09), healthy gate (CC10), vision_leads const (CC11), flag_min (CC12), unavailable -> None (CC13, CC15), guest_cam arg (CC16) | RED | `test_camera_bodies_counts_face_labelled_person`, `test_estimate_exception_case_d`, `test_unhealthy_ledger_is_missing_not_zero`, `test_camera_bodies_none_when_all_platforms_unavailable` |
| dark latch passed to the ledger (CC07) | GREEN (GAP, HIGH) | see H1 |
| entry reset of `_last_house_camera_bodies` (CC14) | GREEN (GAP, LOW) | a failed run would hand the ledger a stale body total |
| outer `_compute_awareness` fallback (CC17) | GREEN (LOW) | effectively unreachable (inner handlers) |
| `aware_ledger_state` value (CC18) | GREEN (GAP, LOW) | display attribute never asserted for a known ledger |

### presence.py, switch.py, sensor.py, flow
| Site | Result | Test |
|---|---|---|
| SIGNAL_RESIDENCY_EVENT dispatch (PR01) | RED | `test_feed_residency_dispatches_record` |
| awareness branch (PR02-PR06), view_for_class promoted (PR07), legal set (PR08), switch off (PR09), switch missing (PR10), exception (PR11), trust-read leak (PR12) | RED | `test_get_house_census_awareness_reads_aware_fields`, `test_switch_off_reads_trust[...]`, `test_view_for_class_security_always_trust[...]`, `test_view_for_class_display_follows_class_set`, `test_view_for_class_error_reads_trust` (PR08/10/11 only in the WIDE set) |
| switch default (SW01), restore-only-off (SW02, SW03), turn on/off (SW04, SW05), registration (SW06), entity id (SW07) | RED | `test_authority_switch_default_on_restore_only_off`, `test_switch_platform_registers_authority_switch` |
| sensors registration (SN01), display class (SN02), value mapping (SN03, SN04), fallback (SN05, SN08), attrs (SN06), unrecorded (SN07) | RED | `test_sensor_platform_registers_awareness_entities`, `test_awareness_entities_*`, `test_open_tracks_sensor_carries_ledger_diag_unrecorded` |
| P2-D1 provider option form (CF01), reload-suppress key (IN01), `_provider_id` reads option (CV80), llmvision entry check (CV81) | RED | `test_house_i2_non_default_value_forces_render[...]`, `test_provider_option_on_perimeter_advanced_form`, `test_provider_override_used`, `test_provider_falls_back_when_entry_absent_on_install` |

### crossing_vision.py (P2-D3 wiring)
| Site | Result | Test |
|---|---|---|
| outcome terms: no_event (CV01), skipped_cap schedule (CV03), busy (CV04), ok term (CV07), ok count (CV08), finally fallback (CV09) | RED | `test_every_outcome_yields_one_term_or_documented_none[...]`, `test_skipped_busy_yields_camera_term`, `test_run_exception_still_applies_camera_term` |
| clustered-with-primary-gone term (CV02) | GREEN (GAP, MED) | the "primary left the request ring" branch is never driven |
| run-time cap (CV05), no_clip (CV06), finally guard (CV10), disabled `term_done` (CV18) | GREEN (EQ) | the `finally` fallback and `_request_terms`' own `term_done` check yield the identical term |
| cluster fold (CV11, CV12), late joiner (CV13, CV14), exactly-once (CV15, CV16), members (CV17), append (CV27) | RED | `test_cluster_folds_into_primary_term`, `test_late_joiner_other_direction_gets_own_term` |
| disable -> unknown at three entry points: crossing (CV21), eval/enabled gate (CV22, CV23, CV25), census_tick gate (CV29), status (CV31) | RED | `test_switch_off_sets_unknown`, `test_kill_and_cap_zero_set_unknown`, `test_switch_off_eval_tick_sets_unknown` |
| immediate unknown on disable inside `_run` (CV19, CV20), `_ledger_terms` gate (CV26) | GREEN (GAP, LOW) | the 60 s eval tick / census_tick covers them eventually |
| rebase on enable (CV24) | RED | `test_anchor_zero_clock_restarts_on_enable` |
| fallback config normalisation (CV28), census_tick dark pass-through (CV30) | GREEN (CV30 = GAP, HIGH, see H1; CV28 LOW) | |
| vision_status "dark" (CV32) | GREEN (GAP, LOW) | display attr |
| substrate edge (CV33, CV34, CV49), residency kind (CV35), supersede (CV37), judge append (CV39), timer store/delay/teardown (CV41, CV42, CV43), subscription present (CV48, CV50) | RED | `test_substrate_rising_edge_blocks_anchor`, `test_residency_departure_reconciles`, `test_superseded_departure_cancels_old_timer`, `test_teardown_unsubscribes_ledger_feeds`, `test_eval_interval_registered_and_runs` |
| substrate/residency listener UNSUB kept (CV46, CV47) | GREEN (GAP, MED) | see M1 |
| residency enabled gate (CV36), due-None return (CV38), judge torn-down guard (CV40) | GREEN (LOW) | masked by `note_departure` / cancelled timers |
| teardown flush (CV44) | GREEN (GAP, LOW) | up to 60 s of observational rows dropped on reload |
| eval: evaluate (CV51), extend (CV52), independent residue (CV53), known samples (CV54), stuck page (CV55), anchor-zero page (CV56), flush (CV57, CV58), episode type / attrs (CV60, CV61), diag (CV64) | RED | `test_anchor_independent_of_house_state`, `test_ledger_episode_per_term_batched`, `test_eval_tick_records_independent_anchor_residues`, `test_stuck_ledger_pages_once`, `test_anchor_zero_pages`, `test_open_tracks_sensor_carries_ledger_diag_unrecorded` |
| flush buffer clear (CV59) | GREEN (GAP, HIGH) | see H2 |
| daily roll resets counters (CV63) | GREEN (GAP, LOW) | display |
| CD3 disagree: record (CV65), case filter (CV66), call (CV67), latch (CV69), off (CV71), flead call/gate/latch (CV68, CV73, CV74), known-share (CV78) | RED | `test_disagree_persist_pages[...]`, `test_bar_regression_pages_only_after_flip`, `test_flead_regression_bars_hold_no_page` |
| disagree re-arm (CV70), disagree window prune (CV72), flead re-arm (CV75), drift zero-share clause (CV76), drift max-abs clause (CV77), min-anchors gate (CV79) | GREEN (GAP, MED) | see M4 |

## Findings

**H1 (HIGH, untested wire, INV-P2-DISCHARGE / "unhealthy is missing, never zero")** - `camera_census.py` `_ledger_tick` (`camera_input_dark=bool(self._camera_input_dark_latched)`, CC07) and `crossing_vision.py` `census_tick` (`camera_input_dark` argument, CV30) can each be replaced by `False` with the whole suite green (also in the WIDE set). `grep camera_input_dark` over the new tests finds only `False` literals and the harness field; no test drives a dark fleet through either hop. A regression that drops the latch lets the anchor fire on a blind fleet (bodies read 0) and reports `healthy=True`, i.e. the discharge predicate's "fleet not dark" term and the awareness case-D fallback silently die. Ledger-level `test_dark_fleet_stops_window` only proves the pure core. Fix: (a) census test with latch True asserting the fake producer received `camera_input_dark=True`; (b) `cv.census_tick(..., camera_input_dark=True)` returns `healthy False` and blocks the anchor window.

**H2 (HIGH, untested single-writer / write-queue guard, DB write-flood family)** - `_flush_ledger_events` clearing the buffer (`events, self._ledger_events = self._ledger_events, []`, CV59) can be neutered to `events = list(self._ledger_events)` with the suite green: every 60 s tick would re-write the whole accumulated buffer, unbounded. `test_ledger_episode_per_term_batched` flushes once. Fix: flush twice with one term and assert one row total (and the buffer empty).

**M1 (MEDIUM, listener unsub)** - CV46/CV47: dropping the stored unsub for the `SIGNAL_SUBSTRATE_KIND_CHANGED` and `SIGNAL_RESIDENCY_EVENT` `async_dispatcher_connect` calls leaves the suite green. `test_teardown_unsubscribes_ledger_feeds` cannot see it because both callbacks have `_torn_down` guards that mask a leaked subscription (stale listeners accumulate per reload). Fix: assert the dispatcher listener count / that the callback is not invoked at all (patch the callback with a recorder).

**M2 (MEDIUM, CC03)** - `R = max(presence, identified)`: presence-only passes all tests. A scenario with `identified_count > residents_home` (an identified non-resident) is absent; that person would then be counted as a ledger guest.

**M3 (MEDIUM, AW5, INV-P2-AWAY-LATENCY choke point 4)** - boot seed from the manager `last_result` (`presence.py` `self._census_count = last.house.total_persons`) can be pointed at `aware_total` with the suite green; `test_boot_seed_ignores_vision_sensors` only exercises the sensor fallback path. Add the manager-seed case with `aware_total != total_persons`.

**M4 (MEDIUM, CD3 / ledger trip-wire semantics)** - the page logic's time-bound clauses are each unpinned: disagree latch re-arm (CV70: a group pages once then never again), disagree window aging (CV72: stale samples never expire, so 5 disagreements over any horizon page), F-LEAD regression re-arm (CV75), the drift bar's zero-share and max-abs clauses (CV76, CV77: the fixture trips both at once, #63), min-anchors gate (CV79), and ledger `stuck_since` reset on a non-zero-body sample (CL40: page on non-contiguous evidence). Each needs a discriminating case.

**M5 (MEDIUM, ledger)** - CL56 (exit after `t_e + lag` must not cancel the reconcile), CL59 (a reconcile makes the next anchor independent), CL16 (rebase re-arms the anchor-zero page), CV02 (clustered member whose primary left the ring still gets its term).

**LOW** - CL01/02/03/06, CD01/02 (pure-function input validation), CL28/CL68/CV63 (display counters and midnight roll), CC14 (entry reset), CC18/CV32 (display attrs), CV19/CV20/CV26/CV28/CV38/CV44 (see table).

**Equivalent mutants (no action)** - CL10, CL23, CL60, the CL44+CL54 pair (RED together), CV05, CV06, CV10, CV18, CV40, CC17.

## Verdict: FIX-REQUIRED
Production code looked correct under mutation: every AWAY drill, every trust-view leak mutation, every INV-DEDUP / INV-P2-AWARE-DECONFLICT site and 170+ other sites go RED on a named test. The suite is not yet authoritative for two load-bearing wires, so tests (not production) must be added before ship:
1. H1: dark-latch pass-through at both hops.
2. H2: flush buffer clear (two flushes, one row).
3. M1-M3, M4, M5: add the discriminating cases (M1 and M3 are the cheapest and sit on the plan's own invariants; M4 and M5 can be one test each).
Re-run the listed mutations (CC07, CV30, CV59, CV46, CV47, CC03, AW5, CV70, CV72, CL40, CL56) after the fix-up; each must go RED on its new named test.
