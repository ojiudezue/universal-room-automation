# Interior vision ship 1 (VISION-INTERIOR-SIGHTINGS-1 D1/D5): Review C, test authority by per-site source mutation

Branch feature/interior-vision-d1 at 9931a001 (parent 7b818ce1). Tier 3, framing C. Reviewer: ura-reviewer-mutation.
Method: ONE site edited per run in production source (or the guard engine), `__pycache__` purged, `python -B`, `PYTHONDONTWRITEBYTECODE=1`, restored in a `finally`, tracked tree confirmed clean after each batch.
Core set per mutation (`-x`): test_interior_vision_records, test_interior_vision_surfaces, test_person_awareness_layer_guard, test_census_trust_golden, test_reload_watchdog_hazard. Every core-GREEN mutant was re-run against the touched module's own test files (person_sighting x3, sc_lock_person_sighting, person_awareness_read_api / layer_ship3a, interior_paths, test_camera_census / census_v2 / awareness_surface, person_coordinator_setup_wirein / presence_coordinator, egress_direction_aware, census_device_switches / cycle_b_config_flow / cm_reload_suppression, memory_writer_health / memory_writers). The builder's drill script was not used for the site list.

## Result

| | count |
|---|---|
| mutants run | 240 |
| RED (a named test fails) | 136 |
| GREEN, equivalent mutant | 18 (4 of them latent: ship 2 makes them real) |
| GREEN, test gap | 85 (39 MEDIUM, 46 LOW), plus 1 duplicate (CO16 = CO15) |
| production defects found | 0 |

No mutation exposed a production bug; every GREEN is a missing or weak test. Per the Tier 3 rule every GREEN row is a finding.

Note: `quality/tests/test_room_options_reload_suppression.py` fails 34 of 42 on the UNMUTATED branch tree (checked on this worktree; not run against the parent). It was excluded from the sensor/switch/config_flow/__init__ module set because it turns every mutation there RED for a reason unrelated to the mutant. Flagged for the validator's name-diff against the parent.

## Priority sites

| Priority site | Verdict |
|---|---|
| INV-IV-AWAY, no inference path, golden equality | HOLDS. Poisoning the census from the interior tick (AW1 clear / AW3 zero `_stream_last_reading`) fails `test_census_trust_golden.py::test_away_tick_identical_with_vision_payload[interior_records_on]` on its own (golden-only run). AW2 (`_last_count_as_of` reset) is not golden-visible but is caught by the guard (`test_guard_matches_provisional_allowlist`, R2). CC01-CC05 area_evidence copy/fields RED. Guard R15/R6/R7 drills RED on the right rule. |
| guard R15 PINNED_READERS and store owners | HOLDS with one hole: GE01-GE04, GE06, GE08-GE10, GE15-GE17 RED. GE07 (class-prefix wildcard `InteriorAwarenessSensor.*` degenerates to "any class in sensor.py") is GREEN, MEDIUM. GE05, GE11, GE12, GE13 LOW. |
| setup/teardown wiring | Timer and wiring RED (PS10, PS11, PS12, PS14, PS16, PS19). Defence-in-depth is untested: torn_down flag (PS15/PS28/PS39/PS76), task cancel and tracking (PS17/PS77), listener rebind unsub (PS29): MEDIUM. |
| LIVE filter | Member classes and non-LIVE exclusion RED (IV01-IV04, PS42b). GAP: `census=True` flag (PS41) MEDIUM. |
| missing-not-zero | HOLDS: IV18, IV19c, PS-status RED (`test_no_live_member_is_missing_not_empty`). |
| one placement per slug | BLE-over-face RED (IV11); NEWEST face wins (IV13) GREEN, MEDIUM. |
| chain window arithmetic | Cumulative / hi / lo / max_hops / missed-camera RED. GAPS: close pad (PS62, CO07), latest close (PS63), closed path re-emitted (PS64), hop with no on-edge (PS68), cycle/visited exclusion (IV31, IV31b). |
| trip-wire numerators | Fire / silent / threshold / severity / name RED. GAPS: latch discharge and re-arm (PS03, PS07), paths_written stamp and denominator (PS06, PS87), path latch set (PS88), numerator `>0`, LIVE and one-per-tick (PS43, PS43b, PS43c), window prune (PS79), MIN_TICKS=0 off (PS80), window and min-ticks consts (CO10, CO12, PS92). |
| switch restore | Restore, stored-wins, exact on/off, turn_off, entity id, platform registration all RED. GAP: default read from the integration entry only (SW04) MEDIUM; options-over-data and fallback (SW05, SW06) LOW. |
| reload-suppress key | HOLDS: IN01 RED (`test_camera_census_form_has_interior_vision_field_default_on`; the `test_reload_watchdog_hazard` allowlist test also pins the key). |

## MEDIUM gaps (tests to add; all are test-only, no production change)

1. SE01 sensor platform wire-in: no test that `sensor.async_setup_entry` adds `InteriorAwarenessSensor` (the existing test constructs the class directly). Mirror `test_switch_platform_registers_interior_vision`.
2. Teardown lifecycle: torn_down flag (PS15/PS28/PS39/PS76), in-flight path-row task cancelled and tracked (PS17/PS77), second `_ensure_interior_groups` unsubs the old on-edge listener (PS29).
3. On-edge listener handler `_on_interior_person_state` has no direct test: X->on only (PS30), on->on ignored (PS31), unknown entity ignored (PS32), ts from `last_changed` (PS33).
4. Path close: pad (PS62/CO07), latest close (PS63), single emission per path (PS64), chain with a silent camera in the path tick (PS68), same-ts second crossing (PS55), DB kwargs `dedup_source_ref=True` (PS75).
5. Trip-wires: re-arm after discharge (PS03/PS07), path denominators and latch (PS06/PS87/PS88), numerator semantics (PS43/PS43b/PS43c), window prune and consts (PS79/CO10/CO12), MIN_TICKS=0 with records absent (PS80).
6. Privacy: CO04, `bathroom` is in INTERIOR_VISION_EXCLUDED_ROOM_TYPES but the exclusion test only exercises `bedroom`. Parametrize over both (INV-IV-SCOPE).
7. LIVE filter census flag (PS41), newest-face-wins (IV13), chain cycle/visited (IV31/IV31b), tick-never-raises (PS40b), switch default scope (SW04), guard class-prefix pin (GE07).

LOW gaps and the equivalent mutants are in the table, each with the exact test needed or the reason it is equivalent.

## Verdict: FIX-REQUIRED

Test-authority only. 39 MEDIUM sites survive mutation, concentrated in the lifecycle, path-close and trip-wire arithmetic that the Tier 3 invariants lean on. Add the tests above (an estimated 12 to 15 small tests, most extend existing fixtures: the `rig`, `_DB`, `_Tracker`, `_PC`), then re-run only the affected rows. No production edit is required by this review.

## Full table

| id | file | mutation | RED test (first failing) | result |
|---|---|---|---|---|
| IV01 | interior_vision.py | held view class | test_interior_vision_records.py::test_no_live_member_is_missing_not_empty | RED |
| IV02 | interior_vision.py | released view class | test_interior_vision_records.py::test_member_liveness_table | RED |
| IV03 | interior_vision.py | no-state/unavailable -> no_reading | test_interior_vision_records.py::test_member_liveness_table | RED |
| IV03b | interior_vision.py | None state treated LIVE | test_interior_vision_records.py::test_member_liveness_table | RED |
| IV04 | interior_vision.py | bodies reads non-LIVE member | test_interior_vision_records.py::test_no_live_member_is_missing_not_empty | RED |
| IV05 | interior_vision.py | None reading -> TypeError path | none (core+module files) | GREEN: equivalent mutant: int(None) raises TypeError, caught by the same `continue` path |
| IV06 | interior_vision.py | negative reading clamp | none (core+module files) | GREEN: equivalent mutant: readings are counts, never negative; clamp only defends a sensor that cannot emit one |
| IV07 | interior_vision.py | max over LIVE members | test_interior_vision_records.py::test_room_records_statuses | RED |
| IV08 | interior_vision.py | group liveness live | test_interior_vision_records.py::test_room_records_statuses | RED |
| IV09 | interior_vision.py | lost class | test_interior_vision_records.py::test_no_live_member_is_missing_not_empty | RED |
| IV10 | interior_vision.py | not-live order | none (core+module files) | GREEN: GAP LOW: group_liveness with mixed held+released+no_reading members asserts the reported class order |
| IV11 | interior_vision.py | ONE placement per slug: face overrides BLE | test_interior_vision_records.py::test_named_union_dedups_ble_and_face | RED |
| IV12 | interior_vision.py | face fresh upper bound | test_interior_vision_records.py::test_face_older_than_fresh_window_not_named | RED |
| IV12b | interior_vision.py | face future-ts guard | none (core+module files) | GREEN: GAP LOW: face sighting with ts in the future (> 1 s) is not placed |
| IV13 | interior_vision.py | newest face wins | none (core+module files) | GREEN: GAP MEDIUM: two fresh faces for one slug in different rooms: the NEWEST room wins (one placement per slug) |
| IV14 | interior_vision.py | empty slug/room BLE filter | none (core+module files) | GREEN: equivalent mutant: producer already filters empty slug/room before place_named (`if slug:`); duplicate guard |
| IV15 | interior_vision.py | vision count with no NVR reading | none (core+module files) | GREEN: equivalent mutant: vision is {} in ship 1; the `nvr is None` branch runs first, so the value is unreachable even if non-empty |
| IV16 | interior_vision.py | vision replaces never adds | test_interior_vision_records.py::test_vision_count_replaces_never_adds | RED |
| IV17 | interior_vision.py | agree provenance | test_interior_vision_records.py::test_vision_count_replaces_never_adds | RED |
| IV18 | interior_vision.py | missing-not-zero (bodies) | test_interior_vision_records.py::test_no_live_member_is_missing_not_empty | RED |
| IV19 | interior_vision.py | unnamed floor | test_interior_vision_records.py::test_room_records_statuses | RED |
| IV19b | interior_vision.py | unnamed subtracts named | test_interior_vision_records.py::test_room_records_statuses | RED |
| IV19c | interior_vision.py | missing-not-zero (unnamed) | test_interior_vision_records.py::test_no_live_member_is_missing_not_empty | RED |
| IV20 | interior_vision.py | status missing | test_interior_vision_records.py::test_live_twin_carries_the_record | RED |
| IV21 | interior_vision.py | unnamed_present threshold | test_interior_vision_records.py::test_room_records_statuses | RED |
| IV22 | interior_vision.py | confirmed threshold | test_interior_vision_records.py::test_named_union_dedups_ble_and_face | RED |
| IV23 | interior_vision.py | ble_unconfirmed needs BLE not face | test_interior_vision_records.py::test_face_only_name_with_no_body_is_empty_not_ble_unconfirmed | RED |
| IV23b | interior_vision.py | ble_unconfirmed never | test_interior_vision_records.py::test_room_records_statuses | RED |
| IV24 | interior_vision.py | census_as_of | none (core+module files) | GREEN: GAP LOW: record carries census_as_of from evidence['as_of'] |
| IV25 | interior_vision.py | bodies_vision field | test_interior_vision_records.py::test_vision_count_replaces_never_adds | RED |
| IV26 | interior_vision.py | entered_via passthrough | test_interior_vision_records.py::test_path_record_hops_rows_and_entered_via_ttl | RED |
| IV27 | interior_vision.py | named tuple | test_interior_vision_records.py::test_room_records_statuses | RED |
| IV28 | interior_vision.py | named_sources | test_interior_vision_records.py::test_named_union_dedups_ble_and_face | RED |
| IV29 | interior_vision.py | chain window cumulative | test_interior_vision_records.py::test_path_windows_cumulative_on_live_chain | RED |
| IV29b | interior_vision.py | hi off-by-one | test_interior_vision_records.py::test_path_windows_cumulative_on_live_chain | RED |
| IV29c | interior_vision.py | lo off-by-one | test_interior_vision_records.py::test_path_windows_cumulative_on_live_chain | RED |
| IV30 | interior_vision.py | chain continues past missed camera | test_interior_vision_records.py::test_path_chain_continues_past_missed_camera | RED |
| IV30b | interior_vision.py | t_of uses first_on | test_interior_vision_records.py::test_path_windows_cumulative_on_live_chain | RED |
| IV31 | interior_vision.py | root excluded | none (core+module files) | GREEN: GAP MEDIUM: chain over a graph with an edge back to the door: door never appears as a hop |
| IV31b | interior_vision.py | visited excluded | none (core+module files) | GREEN: GAP MEDIUM: chain over a graph with a cycle / two-depth reachability: a node keeps its first (shallowest) window |
| IV32 | interior_vision.py | max_hops bound | test_interior_vision_records.py::test_path_chain_continues_past_missed_camera | RED |
| IV33 | interior_vision.py | union open | none (core+module files) | GREEN: GAP LOW: diamond graph (two parents, same depth): union open = min |
| IV33b | interior_vision.py | union close | none (core+module files) | GREEN: GAP LOW: diamond graph: union close = max |
| IV34 | interior_vision.py | first_on upper bound | test_interior_vision_records.py::test_path_window_from_edge_window_s | RED |
| IV34b | interior_vision.py | first_on lower bound | test_interior_vision_records.py::test_path_window_from_edge_window_s | RED |
| IV35 | interior_vision.py | ring boundary | none (core+module files) | GREEN: GAP LOW: on-edge exactly at `since` is included |
| IV36 | interior_vision.py | ring bound | none (core+module files) | GREEN: GAP LOW: ring evicts oldest past INTERIOR_ONEDGE_RING_MAX (append maxlen+1, assert len) |
| IV37 | interior_vision.py | frontier all nodes | test_interior_vision_records.py::test_path_windows_cumulative_on_live_chain | RED |
| IV38 | interior_vision.py | assign all nodes | test_interior_vision_records.py::test_path_windows_cumulative_on_live_chain | RED |
| PS01 | person_sighting.py | room store write | test_interior_vision_records.py::test_room_records_statuses | RED |
| PS02 | person_sighting.py | records_written stamp | test_interior_vision_records.py::test_records_zero_silent_when_records_built | RED |
| PS03 | person_sighting.py | records latch discharge | none (core+module files) | GREEN: GAP MEDIUM: trip-wire re-arm: fire, build a record, drop the numerator window below min again, assert it can fire a second time |
| PS03b | person_sighting.py | written only if records | test_interior_vision_records.py::test_records_zero_tripwire_fires_at_min_ticks | RED |
| PS04 | person_sighting.py | path ring append | test_interior_vision_records.py::test_path_record_hops_rows_and_entered_via_ttl | RED |
| PS05 | person_sighting.py | path counter | none (core+module files) | GREEN: GAP LOW: path_records counter increments (diagnostics) |
| PS06 | person_sighting.py | paths_written stamp | none (core+module files) | GREEN: GAP MEDIUM: path written then entries>=min within window: interior_path_zero stays silent (needs the paths_written stamp) |
| PS07 | person_sighting.py | path latch discharge | none (core+module files) | GREEN: GAP MEDIUM: path_zero re-arms after a path record is later written |
| PS08 | person_sighting.py | unknown kind raises | test_interior_vision_records.py::test_emit_unnamed_sends_no_sighting_signal | RED |
| PS09 | person_sighting.py | record_builds counter | test_interior_vision_records.py::test_timer_builds_records_and_teardown_cancels | RED |
| PS10 | person_sighting.py | setup wiring | test_interior_vision_records.py::test_kill_no_records | RED |
| PS11 | person_sighting.py | teardown wiring | 1 passed, 1 error in 1.15s | RED |
| PS12 | person_sighting.py | kill const at setup | test_interior_vision_records.py::test_kill_no_records | RED |
| PS13 | person_sighting.py | timer interval | none (core+module files) | GREEN: GAP LOW: timer registered with the INTERIOR_ROOM_RECORD_INTERVAL_S period (capture async_track_time_interval arg) |
| PS14 | person_sighting.py | timer callback | test_interior_vision_records.py::test_timer_builds_records_and_teardown_cancels | RED |
| PS15 | person_sighting.py | torn_down flag set | none (core+module files) | GREEN: GAP MEDIUM: after teardown, interior_tick() returns the old store and builds nothing (torn_down flag) |
| PS16 | person_sighting.py | teardown unsub calls | 1 passed, 1 error in 1.14s | RED |
| PS16b | person_sighting.py | teardown unsub clears ref | none (core+module files) | GREEN: GAP LOW: double teardown is a no-op (unsub refs cleared) |
| PS17 | person_sighting.py | task cancel | none (core+module files) | GREEN: GAP MEDIUM: teardown cancels an in-flight _log_path_row task (task.cancelled()) |
| PS18 | person_sighting.py | open_paths clear at teardown | none (core+module files) | GREEN: GAP LOW: teardown clears _open_paths |
| PS19 | person_sighting.py | interval callback ticks | test_interior_vision_records.py::test_timer_builds_records_and_teardown_cancels | RED |
| PS20 | person_sighting.py | group sig cache | none (core+module files) | GREEN: GAP LOW: second tick with unchanged census list does not rebuild groups / rebind listener (perf; or declare equivalent) |
| PS21 | person_sighting.py | sig includes resolver | none (core+module files) | GREEN: GAP LOW: resolver identity change triggers a group rebuild |
| PS22 | person_sighting.py | bind listener after build | test_interior_vision_records.py::test_path_record_hops_rows_and_entered_via_ttl | RED |
| PS23 | person_sighting.py | group key min device id | test_interior_vision_records.py::test_group_key_equals_canonical_key | RED |
| PS24 | person_sighting.py | excluded room types | test_interior_vision_records.py::test_excluded_room_type_no_record | RED |
| PS25 | person_sighting.py | no room skipped | none (core+module files) | GREEN: GAP LOW: interior group whose area maps to no URA room gets no record and counts excluded['no_room'] |
| PS26 | person_sighting.py | area first hit | none (core+module files) | GREEN: GAP LOW: area resolved from the first member that has one |
| PS27 | person_sighting.py | no camera device | none (core+module files) | GREEN: GAP LOW: interior entity with no camera device counts excluded['no_camera_device'] and builds no group |
| PS28 | person_sighting.py | no bind after teardown | none (core+module files) | GREEN: GAP MEDIUM: listener bind after teardown is refused (_bind_onedge_listener with torn_down True) |
| PS29 | person_sighting.py | rebind unsubs old listener | none (core+module files) | GREEN: GAP MEDIUM: rebuild of groups unsubs the previous on-edge listener (count live subscriptions == 1) |
| PS30 | person_sighting.py | on-edge to on only | none (core+module files) | GREEN: GAP MEDIUM: fire state events: on->off and unavailable->off do not stamp the ring; only X->on |
| PS31 | person_sighting.py | on-edge from not-on | none (core+module files) | GREEN: GAP MEDIUM: on->on attribute-only update does not stamp the ring |
| PS32 | person_sighting.py | unknown entity ignored | none (core+module files) | GREEN: GAP MEDIUM: state event for a non-interior entity does not stamp the ring |
| PS33 | person_sighting.py | on-edge ts from last_changed | none (core+module files) | GREEN: GAP MEDIUM: on-edge timestamp is new_state.last_changed, not wall-clock now (event with past last_changed) |
| PS34 | person_sighting.py | active_only | test_interior_vision_records.py::test_stale_resident_does_not_confirm | RED |
| PS35 | person_sighting.py | face veto filter | test_interior_vision_records.py::test_vetoed_face_not_named | RED |
| PS36 | person_sighting.py | face source interior filter | none (core+module files) | GREEN: GAP LOW: non-interior-source sighting with a room is not placed as a named face |
| PS37 | person_sighting.py | BLE first room wins | none (core+module files) | GREEN: GAP LOW: slug in two rooms by BLE: the first (sorted) room wins, stable |
| PS38 | person_sighting.py | face fresh const consumed | test_interior_vision_records.py::test_face_older_than_fresh_window_not_named | RED |
| PS39 | person_sighting.py | tick after teardown | none (core+module files) | GREEN: GAP MEDIUM: interior_tick after teardown (alias of PS15) |
| PS39b | person_sighting.py | tick kill const | test_interior_vision_records.py::test_kill_no_records | RED |
| PS40 | person_sighting.py | tick_errors counter | none (core+module files) | GREEN: GAP LOW: tick_errors counter increments on a raising tick |
| PS40b | person_sighting.py | tick never raises | none (core+module files) | GREEN: GAP MEDIUM: tick that raises inside _interior_tick (patch _named_by_room to raise) does not propagate out of the timer callback and bumps tick_errors |
| PS41 | person_sighting.py | census view flag | none (core+module files) | GREEN: GAP MEDIUM: LIVE filter: entity_stream_view is called with census=True (spy), and a census-held member classifies HELD (current held test passes under census=False) |
| PS42 | person_sighting.py | physical_dead only when no live | none (core+module files) | GREEN: GAP LOW: physical_camera_dead not consulted when a LIVE member exists (spy) |
| PS42b | person_sighting.py | physical dead read | test_interior_vision_records.py::test_no_live_member_is_missing_not_empty | RED |
| PS43 | person_sighting.py | numerator >0 | none (core+module files) | GREEN: GAP MEDIUM: trip-wire numerator: a tick with every interior reading == 0 must NOT stamp (with no records written, 20 zero ticks stay silent) |
| PS43b | person_sighting.py | numerator live | none (core+module files) | GREEN: GAP MEDIUM: numerator: a non-LIVE (unavailable) interior entity with a stale positive last reading must NOT stamp |
| PS43c | person_sighting.py | numerator one per tick | none (core+module files) | GREEN: GAP MEDIUM: numerator: two interior entities > 0 on one tick count ONE tick |
| PS43d | person_sighting.py | numerator append | test_interior_vision_records.py::test_records_zero_tripwire_fires_at_min_ticks | RED |
| PS44 | person_sighting.py | path tick called | test_interior_vision_records.py::test_path_record_hops_rows_and_entered_via_ttl | RED |
| PS45 | person_sighting.py | entered_via expiry | test_interior_vision_records.py::test_path_record_hops_rows_and_entered_via_ttl | RED |
| PS46 | person_sighting.py | entered_via delete | test_interior_vision_records.py::test_path_record_hops_rows_and_entered_via_ttl | RED |
| PS47 | person_sighting.py | entered_via on group | test_interior_vision_records.py::test_path_record_hops_rows_and_entered_via_ttl | RED |
| PS48 | person_sighting.py | tripwires called | test_interior_vision_records.py::test_records_zero_tripwire_fires_at_min_ticks | RED |
| PS49 | person_sighting.py | vision counts passed | none (core+module files) | GREEN: equivalent mutant: LATENT (ship 2): _vision_counts is always empty in ship 1, `{}` and `dict(self._vision_counts)` are identical today |
| PS50 | person_sighting.py | hist nvr | none (core+module files) | GREEN: equivalent mutant: LATENT (ship 2): bodies == bodies_nvr while vision is empty |
| PS50b | person_sighting.py | hist_len max hops | none (core+module files) | GREEN: GAP LOW: bodies history length scales with INTERIOR_TIMELAPSE_MAX_HOPS |
| PS50c | person_sighting.py | hist_len rebind | none (core+module files) | GREEN: GAP LOW: history deque re-sized when the const changes |
| PS51 | person_sighting.py | door with no edges | none (core+module files) | GREEN: equivalent mutant: an empty edge tuple never matches `any(e.from_key == root ...)` |
| PS52 | person_sighting.py | cursor None | none (core+module files) | GREEN: equivalent mutant: only reached when dt_util.utcnow() raised at setup |
| PS53 | person_sighting.py | crossing dedup | test_interior_vision_records.py::test_crossing_read_once | RED |
| PS54 | person_sighting.py | cursor advance | none (core+module files) | GREEN: equivalent mutant: functionally equivalent: seen-set accumulates instead; growth only (perf), no duplicate path |
| PS55 | person_sighting.py | seen set accumulates | none (core+module files) | GREEN: GAP MEDIUM: two entry crossings with an identical ts arriving on different ticks yield two path records, not a repeat of the first |
| PS56 | person_sighting.py | seen set at top | test_interior_vision_records.py::test_crossing_read_once | RED |
| PS57 | person_sighting.py | entries only | test_interior_vision_records.py::test_no_inward_edges_no_record | RED |
| PS58 | person_sighting.py | door matches root | test_interior_vision_records.py::test_no_inward_edges_no_record | RED |
| PS59 | person_sighting.py | first door only | none (core+module files) | GREEN: GAP LOW: an entry whose root camera appears on two mapped doors opens ONE path on the first door (sorted) and counts entries_mapped once |
| PS60 | person_sighting.py | entries_mapped numerator | test_interior_vision_records.py::test_path_zero_tripwire | RED |
| PS61 | person_sighting.py | entries_unmapped | test_interior_vision_records.py::test_no_inward_edges_no_record | RED |
| PS62 | person_sighting.py | close pad | none (core+module files) | GREEN: GAP MEDIUM: chain window arithmetic: path record is NOT emitted at close_at, only at close_at + INTERIOR_TIMELAPSE_CLOSE_PAD_S (tick at close_at+PAD-1 vs +PAD) |
| PS62b | person_sighting.py | never wait | test_interior_vision_records.py::test_path_record_hops_rows_and_entered_via_ttl | RED |
| PS63 | person_sighting.py | latest window close | none (core+module files) | GREEN: GAP MEDIUM: chain window arithmetic: two-hop chain closes at the LATEST window close, not the earliest (tick between the two closes emits nothing) |
| PS64 | person_sighting.py | open path removed on close | none (core+module files) | GREEN: GAP MEDIUM: a closed path is not emitted again: tick twice past close, assert get_last_path_records length 1 and one DB row |
| PS65 | person_sighting.py | hops earliest first | test_interior_vision_records.py::test_path_record_hops_rows_and_entered_via_ttl | RED |
| PS66 | person_sighting.py | seed ttl | test_interior_vision_records.py::test_path_record_hops_rows_and_entered_via_ttl | RED |
| PS66b | person_sighting.py | seed only with first_on | test_interior_vision_records.py::test_path_record_hops_rows_and_entered_via_ttl | RED |
| PS67 | person_sighting.py | ring since entry | none (core+module files) | GREEN: equivalent mutant: chain_windows already filters on-edges to [open, close]; `since` is redundant |
| PS68 | person_sighting.py | hops need first_on | none (core+module files) | GREEN: GAP MEDIUM: path tick over a chain where a window saw no on-edge: record emitted with only the hop that fired, no tick_errors |
| PS70 | person_sighting.py | bodies_at boundary | none (core+module files) | GREEN: GAP LOW: bodies_at: reading at exactly ts is used (history sample t == first_on) |
| PS70b | person_sighting.py | bodies_at fallback last | none (core+module files) | GREEN: GAP LOW: bodies_at: first_on after the newest history sample returns the last sample |
| PS71 | person_sighting.py | n_source crossing | test_interior_vision_records.py::test_n_source_order | RED |
| PS72 | person_sighting.py | arrival record source_ref match | test_interior_vision_records.py::test_n_source_order | RED |
| PS73 | person_sighting.py | first_hop label | test_interior_vision_records.py::test_path_record_hops_rows_and_entered_via_ttl | RED |
| PS74 | person_sighting.py | bool people_count | none (core+module files) | GREEN: GAP LOW: people_count True (bool) is not accepted as n |
| PS75 | person_sighting.py | db dedup | none (core+module files) | GREEN: GAP MEDIUM: log_memory_episode called with dedup_source_ref=True, window_dedup=False (capture kwargs in the existing _DB fake) |
| PS76 | person_sighting.py | no row after teardown | none (core+module files) | GREEN: GAP MEDIUM: a path closing after teardown writes no DB row (alias of PS15 for the DB leg) |
| PS77 | person_sighting.py | task tracked | none (core+module files) | GREEN: GAP MEDIUM: path-row task is held in _interior_tasks while pending and discarded when done |
| PS78 | person_sighting.py | episode type | test_interior_vision_records.py::test_path_record_hops_rows_and_entered_via_ttl | RED |
| PS79 | person_sighting.py | numerator window prune | none (core+module files) | GREEN: GAP MEDIUM: numerator prune: stamps older than INTERIOR_ZERO_WINDOW_H fall out (tick at now+25 h with 19 stale stamps + 1 fresh stays silent) |
| PS80 | person_sighting.py | min_ticks 0 = off | none (core+module files) | GREEN: GAP MEDIUM: INTERIOR_ZERO_MIN_TICKS = 0 with ticks_with_bodies empty and no records: stays silent (the existing knobs-zero test never reaches the records branch with records absent) |
| PS81 | person_sighting.py | min_ticks boundary | test_interior_vision_records.py::test_records_zero_tripwire_fires_at_min_ticks | RED |
| PS82 | person_sighting.py | records written denominator | test_interior_vision_records.py::test_records_zero_silent_when_records_built | RED |
| PS83 | person_sighting.py | records latch set | test_interior_vision_records.py::test_records_zero_tripwire_fires_at_min_ticks | RED |
| PS84 | person_sighting.py | records severity HIGH | test_interior_vision_records.py::test_records_zero_tripwire_fires_at_min_ticks | RED |
| PS85 | person_sighting.py | min_entries 0 = off | test_interior_vision_records.py::test_tripwire_knobs_zero_are_off | RED |
| PS86 | person_sighting.py | min_entries boundary | test_interior_vision_records.py::test_path_zero_tripwire | RED |
| PS87 | person_sighting.py | paths written denominator | none (core+module files) | GREEN: GAP MEDIUM: path_zero silent when a path record was written in the window (denominator) |
| PS88 | person_sighting.py | path latch set | none (core+module files) | GREEN: GAP MEDIUM: path_zero fires once, not on every subsequent tick (latch set) |
| PS89 | person_sighting.py | path severity LOW | test_interior_vision_records.py::test_path_zero_tripwire | RED |
| PS90 | person_sighting.py | path tripwire name | test_interior_vision_records.py::test_path_zero_tripwire | RED |
| PS91 | person_sighting.py | records tripwire name | test_interior_vision_records.py::test_records_zero_tripwire_fires_at_min_ticks | RED |
| PS92 | person_sighting.py | window hours | none (core+module files) | GREEN: GAP LOW: INTERIOR_ZERO_WINDOW_H scales the prune horizon |
| PS93 | person_sighting.py | diag liveness | test_interior_vision_records.py::test_presence_delegates_and_diagnostics | RED |
| PS94 | person_sighting.py | diag excluded | none (core+module files) | GREEN: GAP LOW: diagnostics groups_excluded_by_reason carries the counter |
| PS95 | person_sighting.py | excluded stored | test_interior_vision_records.py::test_excluded_room_type_no_record | RED |
| PS96 | person_sighting.py | no still source still recorded | none (core+module files) | GREEN: GAP LOW: group with no Frigate still source still gets a record and counts excluded['no_still_source'] |
| PR01 | presence.py | presence get_room_sightings | test_interior_vision_records.py::test_presence_delegates_and_diagnostics | RED |
| PR02 | presence.py | presence get_last_path_records | test_person_awareness_layer_guard.py::test_iv_pinned_readers_clean_on_real_tree_and_pins_are_real | RED |
| PR03 | presence.py | layer diag interior_vision | test_interior_vision_records.py::test_presence_delegates_and_diagnostics | RED |
| CC01 | camera_census.py | by_entity copy | test_interior_vision_records.py::test_area_evidence_copies | RED |
| CC02 | camera_census.py | by_entity empty | test_interior_vision_records.py::test_room_records_statuses | RED |
| CC03 | camera_census.py | area_contributions | test_interior_vision_records.py::test_area_evidence_copies | RED |
| CC04 | camera_census.py | house bodies | test_interior_vision_records.py::test_area_evidence_copies | RED |
| CC05 | camera_census.py | as_of | test_interior_vision_records.py::test_area_evidence_copies | RED |
| CC06 | camera_census.py | never raises | none (core+module files) | GREEN: GAP LOW: area_evidence returns the empty shape when the census attrs raise |
| PCO01 | person_coordinator.py | persons_in_room empty room | none (core+module files) | GREEN: equivalent mutant: get_room_occupants('') returns [] -> () anyway |
| PCO02 | person_coordinator.py | persons_in_room active_only | test_interior_vision_records.py::test_stale_resident_does_not_confirm | RED |
| PCO03 | person_coordinator.py | phone-left-behind filter | test_interior_vision_records.py::test_phone_left_behind_person_not_named | RED |
| PCO04 | person_coordinator.py | persons_in_room never raises | none (core+module files) | GREEN: GAP LOW: persons_in_room returns () when get_room_occupants raises |
| PCO05 | person_coordinator.py | active_only off | test_interior_vision_records.py::test_stale_resident_does_not_confirm | RED |
| TV01 | transit_validator.py | inward only | test_interior_vision_records.py::test_inward_path_edges_excludes_approach | RED |
| TV02 | transit_validator.py | unknown door | none (core+module files) | GREEN: equivalent mutant: dm None -> AttributeError swallowed by the blanket except -> () |
| TV03 | transit_validator.py | no map | none (core+module files) | GREEN: equivalent mutant: pmap None -> AttributeError swallowed by the blanket except -> () |
| SE01 | sensor.py | sensor registered | none (core+module files) | GREEN: GAP MEDIUM: wire-in anchor: sensor platform async_setup_entry adds an InteriorAwarenessSensor (mirror test_switch_platform_registers_interior_vision) |
| SE02 | sensor.py | state ignores missing (equiv?) | none (core+module files) | GREEN: equivalent mutant: unnamed is None exactly when bodies is None, and `int(None or 0)` = 0 |
| SE02b | sensor.py | state = unnamed | test_interior_vision_surfaces.py::test_interior_awareness_sensor_reads_records | RED |
| SE03 | sensor.py | unrecorded attrs | test_interior_vision_surfaces.py::test_interior_awareness_sensor_reads_records | RED |
| SE04 | sensor.py | entity id | test_interior_vision_surfaces.py::test_interior_awareness_sensor_reads_records | RED |
| SE05 | sensor.py | entered_via attr | test_interior_vision_surfaces.py::test_interior_awareness_sensor_reads_records | RED |
| SE06 | sensor.py | named_count attr | none (core+module files) | GREEN: GAP LOW: sensor attribute named_count equals len(named) |
| SE07 | sensor.py | last_path attr | test_interior_vision_surfaces.py::test_interior_awareness_sensor_reads_records | RED |
| SE08 | sensor.py | records_as_of | none (core+module files) | GREEN: GAP LOW: sensor attribute records_as_of is the ISO of records[0].as_of |
| SE09 | sensor.py | sensor never raises | none (core+module files) | GREEN: GAP LOW: sensor state/attributes never raise when presence.get_room_sightings raises |
| SW01 | switch.py | switch registered | test_interior_vision_surfaces.py::test_switch_platform_registers_interior_vision | RED |
| SW02 | switch.py | restore: unknown takes default | test_interior_vision_surfaces.py::test_interior_vision_switch_restore_and_default[unavailable-None-True] | RED |
| SW02b | switch.py | restore: stored wins | test_interior_vision_surfaces.py::test_interior_vision_switch_restore_and_default[on-False-True] | RED |
| SW02c | switch.py | restore on/off exact | test_interior_vision_surfaces.py::test_interior_vision_switch_restore_and_default[unknown-False-False] | RED |
| SW03 | switch.py | is_on stored | test_interior_vision_surfaces.py::test_interior_vision_switch_restore_and_default[on-False-True] | RED |
| SW04 | switch.py | default from integration entry | none (core+module files) | GREEN: GAP MEDIUM: switch default read only from the INTEGRATION entry (a room entry carrying CONF_INTERIOR_VISION_ENABLED must not change it) |
| SW05 | switch.py | options+data merge | none (core+module files) | GREEN: GAP LOW: default honors entry.options over entry.data (options False, data True -> off) |
| SW06 | switch.py | fallback default | none (core+module files) | GREEN: GAP LOW: no integration entry at all -> DEFAULT_INTERIOR_VISION_ENABLED |
| SW07 | switch.py | apply writes hass.data | test_interior_vision_surfaces.py::test_interior_vision_switch_restore_and_default[on-False-True] | RED |
| SW08 | switch.py | turn_off | test_interior_vision_surfaces.py::test_interior_vision_switch_restore_and_default[on-False-True] | RED |
| SW09 | switch.py | entity id | test_interior_vision_surfaces.py::test_interior_vision_switch_restore_and_default[on-False-True] | RED |
| SW10 | switch.py | entity category | none (core+module files) | GREEN: GAP LOW: switch entity_category is CONFIG |
| IN01 | __init__.py | reload-suppress key | test_interior_vision_surfaces.py::test_camera_census_form_has_interior_vision_field_default_on | RED |
| CF01 | config_flow.py | config flow field | test_interior_vision_surfaces.py::test_camera_census_form_has_interior_vision_field_default_on | RED |
| CF02 | config_flow.py | config flow default | test_interior_vision_surfaces.py::test_camera_census_form_has_interior_vision_field_default_on | RED |
| CO01 | const.py | kill const default | test_interior_vision_records.py::test_group_key_equals_canonical_key | RED |
| CO02 | const.py | interval | test_interior_vision_records.py::test_timer_builds_records_and_teardown_cancels | RED |
| CO03 | const.py | face fresh | test_interior_vision_records.py::test_face_older_than_fresh_window_not_named | RED |
| CO04 | const.py | excluded bathroom | none (core+module files) | GREEN: GAP MEDIUM: INV-IV-SCOPE privacy: parametrize test_excluded_room_type_no_record over BOTH 'bedroom' and 'bathroom' (only bedroom is exercised) |
| CO04b | const.py | excluded bedroom | test_interior_vision_records.py::test_excluded_room_type_no_record | RED |
| CO05 | const.py | ring max | none (core+module files) | GREEN: GAP LOW: ring max const consumed (alias of IV36) |
| CO06 | const.py | max hops | test_interior_vision_records.py::test_path_record_hops_rows_and_entered_via_ttl | RED |
| CO07 | const.py | close pad | none (core+module files) | GREEN: GAP MEDIUM: close pad const consumed (alias of PS62) |
| CO08 | const.py | path ring | none (core+module files) | GREEN: GAP LOW: path ring const consumed (append RING+1 records, assert RING kept) |
| CO09 | const.py | seed ttl | test_interior_vision_records.py::test_path_record_hops_rows_and_entered_via_ttl | RED |
| CO10 | const.py | min ticks | none (core+module files) | GREEN: GAP MEDIUM: INTERIOR_ZERO_MIN_TICKS consumed by the trip-wire (monkeypatch to 3, fire at 3 ticks) |
| CO11 | const.py | min entries | test_interior_vision_records.py::test_path_zero_tripwire | RED |
| CO12 | const.py | window h | none (core+module files) | GREEN: GAP MEDIUM: INTERIOR_ZERO_WINDOW_H consumed (alias of PS79/PS92) |
| CO13 | const.py | default vision | test_interior_vision_surfaces.py::test_interior_vision_switch_restore_and_default[unavailable-None-True] | RED |
| CO14 | const.py | hass key (equiv) | none (core+module files) | GREEN: equivalent mutant: hass key string only has to match between writer and (future) reader; no reader in ship 1 |
| CO15 | const.py | episode type registered | none (core+module files) | GREEN: GAP LOW: 'interior_path' in MEMORY_EPISODE_TYPES (registration pin) |
| CO16 | const.py | episode type (alt) | none (core+module files) | GREEN: GAP --: duplicate of CO15 (same line) |
| GE01 | _layer_guard_engine.py | pinned get_room_sightings dropped | test_person_awareness_layer_guard.py::test_iv_drill_trips_its_rule[iv_trust_reader] | RED |
| GE02 | _layer_guard_engine.py | pinned get_last_path_records dropped | test_person_awareness_layer_guard.py::test_iv_pinned_readers_clean_on_real_tree_and_pins_are_real | RED |
| GE03 | _layer_guard_engine.py | R15 scan | test_person_awareness_layer_guard.py::test_iv_drill_trips_its_rule[iv_census_feed] | RED |
| GE04 | _layer_guard_engine.py | R15 getattr form | test_person_awareness_layer_guard.py::test_iv_engine_shapes[def f(p):\n    return getattr(p, 'get_room_sightings')()\n-R15] | RED |
| GE05 | _layer_guard_engine.py | compare reports unpinned | none (core+module files) | GREEN: GAP LOW: engine.compare reports `unpinned reader` even if a hit were allowlisted (allowlist an R15 hit, assert problem) |
| GE06 | _layer_guard_engine.py | pinned_ok module | test_person_awareness_layer_guard.py::test_iv_drill_trips_its_rule[iv_trust_reader] | RED |
| GE07 | _layer_guard_engine.py | pinned_ok class prefix | none (core+module files) | GREEN: GAP MEDIUM: pinned_ok class prefix: a different class in sensor.py calling get_room_sightings is an R15 hit |
| GE08 | _layer_guard_engine.py | STORE_ATTRS_OWNER | test_person_awareness_layer_guard.py::test_iv_drill_trips_its_rule[iv_direct_store_write] | RED |
| GE09 | _layer_guard_engine.py | RECORD_OWNERS | test_person_awareness_layer_guard.py::test_iv_drill_trips_its_rule[iv_record_built_outside_owner] | RED |
| GE10 | _layer_guard_engine.py | R2_STORE_OWNERS | test_person_awareness_layer_guard.py::test_iv_engine_shapes[def f(prod):\n    prod._path_records.append(1)\n    return prod._vision_counts\n-R2] | RED |
| GE11 | _layer_guard_engine.py | R2_PRIVATE_STORES | none (core+module files) | GREEN: GAP LOW: R2_PRIVATE_STORES membership of the three new stores (read of _room_sightings from presence.py is an R2 hit) |
| GE12 | _layer_guard_engine.py | READ_LIST | none (core+module files) | GREEN: GAP LOW: READ_LIST entry for the two reads (assert a PRESENCE-class read of them is classified, not unknown) |
| GE13 | _layer_guard_engine.py | LAYER_NON_PERSON_PUBLIC inward_path_edges | none (core+module files) | GREEN: GAP LOW: LAYER_NON_PERSON_PUBLIC: inward_path_edges on EgressDirectionTracker is not reported as an unclassified public person read |
| GE14 | _layer_guard_engine.py | MEMBER_CLASSES | none (core+module files) | GREEN: equivalent mutant: InteriorVisionSampler does not exist yet (ship 2+) |
| GE15 | _layer_guard_engine.py | pin presence get_room_sightings | test_person_awareness_layer_guard.py::test_guard_matches_provisional_allowlist | RED |
| GE16 | _layer_guard_engine.py | pin presence get_last_path_records | test_person_awareness_layer_guard.py::test_guard_matches_provisional_allowlist | RED |
| GE17 | _layer_guard_engine.py | pin interior_census_tick | test_person_awareness_layer_guard.py::test_iv_drill_trips_its_rule[iv_census_feed] | RED |
| GE18 | _layer_guard_engine.py | pin request_room_description | none (core+module files) | GREEN: equivalent mutant: pinned method does not exist yet (ship 2) |
| GE19 | _layer_guard_engine.py | pin get_room_description | none (core+module files) | GREEN: equivalent mutant: pinned method does not exist yet (ship 2) |
| AW1 | person_sighting.py | AWAY: interior tick clears census last readings | test_interior_vision_records.py::test_room_records_statuses | RED |
| AW2 | person_sighting.py | AWAY: interior tick resets census count time | test_person_awareness_layer_guard.py::test_guard_matches_provisional_allowlist | RED |
| AW3 | person_sighting.py | AWAY: interior tick zeroes census last readings | test_interior_vision_records.py::test_room_records_statuses | RED |
| CO17 | const.py | writer-backed registration | none (core+module files) | GREEN: GAP LOW: 'interior_path' in MEMORY_WRITER_BACKED_EPISODE_TYPES (registration pin) |
| CO18 | const.py | absence-exempt registration | none (core+module files) | GREEN: GAP LOW: 'interior_path' in MEMORY_WRITER_HEALTH_ABSENCE_EXEMPT_TYPES (registration pin) |
