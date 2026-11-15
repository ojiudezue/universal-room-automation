# Review C (test authority, per-site source mutation): camera input stream health S2

Branch feature/camera-input-stream-health-s2, HEAD 8fee2e47, diff base 3ec3f4d2 (merge-base with develop, three-dot verified).
Method: one production-source mutation at a time, applied and restored by a driver script that asserts
the file is byte-identical afterwards. Each run used a mixed 11-file set (s2, stream_health, camera_census,
substrate seed/lifecycle/zone-migration/room-integration, presence fan-interference layer1, fan_interference
gate, comfort_fan_away_veto x2): 218 tests, baseline all green in 1.8 s. The mixed set is the one that would
expose the const re-import issue; it never showed up (the `switch_off` fixture handles it), so no finding there.
Bytecode purged before every run. 74 mutants executed (1 skipped: pattern did not match).

Process note: in my first batch one csh mutant was left in the tree after its slot (cause not established; a
parallel agent on the same worktree is possible), contaminating later rows. I restored from HEAD, added a
restore-equality assertion to the driver, and re-ran every affected row. Tables below are from clean runs only.
Final `git status`: clean (only this file added).

## Per-site table (RED = a named test fails)

### camera_stream_health.py house getters + room getter
| Mutation | Result | Killing test |
|---|---|---|
| _room_coordinators -> [] | RED | test_zone_not_held_by_dead_stream_input, test_stream_dead_single_getter[True] |
| _room_coordinators no getattr filter | GREEN (equivalent: per-room call is inside try/except) | none |
| _fold True->return False | RED | test_stream_dead_single_getter[True] + zone tests |
| _fold False-beats-True | RED | test_house_fold_any_true_wins |
| _fold all-False->None / none->False | RED | test_house_fold_any_true_wins, test_camera_keyed_getter |
| _fold `is True` -> truthy | RED | test_house_fold_any_true_wins, comfort_fan_away_veto T4 |
| input_stream_dead empty-key guard removed | GREEN (equivalent) | none |
| input_stream_dead calls camera getter | RED | test_stream_dead_single_getter[True] |
| input_stream_dead except->raise | GREEN | none (fail-open untested) |
| camera_stream_dead prefix guard removed | GREEN (equivalent: room getter returns None) | none |
| camera_stream_dead calls input getter | RED | test_camera_keyed_getter |
| camera_stream_dead except->raise | GREEN | none (fail-open untested) |
| entity_stream_dead empty guard removed | GREEN (equivalent) | none |
| **entity_stream_dead `camera.*` branch removed** | **GREEN** | none |
| entity_stream_dead skip direct (always fallback) | RED | test_stream_dead_single_getter[True], zone camera tier |
| **entity_stream_dead direct False not returned** | **GREEN** | none |
| entity_stream_dead fallback -> None | RED | test_census_own_camera_route_for_non_input_entity |
| entity_stream_dead no-cam guard removed | GREEN (equivalent) | none |
| entity_stream_dead registry except->raise | GREEN | none |
| camera_is_dead no-watch guard removed | RED | test_camera_keyed_getter |
| camera_is_dead None-resolution guard removed | GREEN | none (house fn swallows the AttributeError) |
| camera_is_dead always False / always True | RED | test_camera_keyed_getter |
| **camera_is_dead dead-match ignores camera key** | **GREEN** | none |
| camera_is_dead watched-match ignores camera key | RED | test_camera_keyed_getter |

### coordinator.py
| Mutation | Result | Killing test |
|---|---|---|
| camera_stream_dead -> None | RED | test_camera_keyed_getter |
| flip xor->and / only-recover / call removed / key wrong / empty arg / prev_dead not updated | RED | zone tests, test_restart_rebuilds_from_first_tick, test_room_tick_notifies_substrate_on_flip_only |
| flip xor->or, no flip gate, only-dead | RED | test_room_tick_notifies_substrate_on_flip_only |
| **_notify_substrate_stream_flips swallow->raise** | **GREEN** | none |
| **_camera_stream_prev_dead initial value** | **GREEN** | none |

### occupancy_substrate.py
| Mutation | Result | Killing test |
|---|---|---|
| _kind_on_now event branch no dead check | RED | test_zone_live_event_does_not_revive_dead_input |
| _kind_on_now sibling branch no dead check | RED | test_zone_sibling_dead_input_does_not_hold_kind |
| _stream_dead -> False | RED | zone tests |
| _stream_dead `is True` -> `is not False` | RED | test_room_substrate_integration::test_room_handler_survives_signal_listener_clobber and others |
| **_stream_dead except->True (fail closed) / except->raise** | **GREEN** | none |
| **recheck_entities unmapped-entity guard removed** | **GREEN** | none |
| recheck per_entity branch disabled | RED | test_zone_sibling_dead_input_does_not_hold_kind |
| recheck else-branch dead check removed | RED | test_zone_switch_off_paths_honour_dead_stream |
| **recheck per_entity forced True** | **GREEN** | none |
| recheck bucket not updated | RED | test_restart_rebuilds_from_first_tick + zone tests |
| **recheck `prior == occupied` no-edge gate removed** | **GREEN** | none |
| **recheck boot-settle gate removed** | **GREEN** | none |
| **recheck `_last_edge_entity` not set** | **GREEN** | none |
| recheck dispatch inverted | RED | test_zone_switch_off_paths_honour_dead_stream |
| **recheck body except->raise** | **GREEN** | none |
| _handle_state_change no dead check | RED | test_zone_switch_off_paths_honour_dead_stream |
| (recheck dispatch-removed: pattern missed, not run; covered by inverted row only) | n/a | |

### presence.py
| Mutation | Result | Killing test |
|---|---|---|
| _any_camera_occupied dead skip removed | RED | test_zone_camera_tier_ignores_dead_stream |
| radar_sole on_set no dead check | RED | test_presence_radar_sole_gate_ignores_dead_input |
| _zone_night_rooms no dead check | RED | test_night_raw_switch_off_limb_ignores_dead_input |
| _input_stream_dead -> False / `is not False` | RED | zone/radar/night tests; test_presence_fan_interference_layer1 |
| **_input_stream_dead except->True** | **GREEN** | none |
| _camera_entity_stream_dead -> False | RED | test_zone_camera_tier_ignores_dead_stream |
| **_camera_entity_stream_dead except->True** | **GREEN** | none |
| **_camera_entity_stream_dead uses input getter instead of entity getter** | **GREEN** | none |

### fan_veto.py
| Mutation | Result | Killing test |
|---|---|---|
| motion-input dead skip removed | RED | test_fan_veto_motion_ignores_dead_stream_input |
| camera-leg dead check removed | RED | test_fan_veto_camera_leg_ignores_dead_stream |
| _stream_dead -> False / `is not False` | RED | s2 fan tests; comfort_fan_away_veto_behavioral |
| **_stream_dead except->True** | **GREEN** | none |

### camera_census.py
| Mutation | Result | Killing test |
|---|---|---|
| _stream_dead_interior -> empty | RED | test_census_dead_stream_is_missing_not_zero |
| site 1 (raw frigate/binary sums) skip removed | RED | test_census_dead_stream_is_missing_not_zero |
| site 2 (cross-validation) skip removed | RED | test_census_cross_validation_off_skips_dead_stream |
| site 3 (unrecognized count) skip removed | RED | test_census_unrecognized_count_skips_dead_stream |
| **_stream_dead_interior `is True` -> `is not False`** | **GREEN** | none |
| **_stream_dead_interior per-entity except->raise / import except->raise** | **GREEN** | none |

## Findings (every GREEN row that is not equivalent)

1. MEDIUM (test gap, consequence HIGH) camera_census.py `_stream_dead_interior`: `is True` -> `is not False`
   leaves the suite green. That makes "no opinion" (None: unresolved camera, kill switch/no room) a dead
   stream, so the census would drop every unresolved camera. The byte-identical-for-unresolved invariant is
   unprotected at the census, although the same mutation is killed at substrate, presence and fan_veto.
   Add a census test where the getter answers None for a camera that has a nonzero count and assert it is counted.
2. MEDIUM `camera_is_dead` dead-match ignores the camera key: a room watching two cameras, one dead, reports
   the other dead (cross-camera bleed through camera_stream_dead, the future NVR witness getter). Add a
   two-camera test (one dead, one live) asserting the live one is False.
3. MEDIUM `entity_stream_dead` `camera.*` branch, and presence `_camera_entity_stream_dead` routed to the input
   getter: both GREEN. A zone tracker camera key that IS a `camera.*` entity is untested end to end; only the
   non-camera (panel sensor) route is driven.
4. MEDIUM `recheck_entities` guards: unmapped-entity guard (without it `room_name, kind = mapping` raises
   TypeError and aborts the remaining sorted entities of the flip batch), `prior == occupied` dedupe (a flip of
   a sibling input would re-dispatch an unchanged kind), and `_boot_settle_done` gate are all untested.
   `_last_edge_entity` and per_entity-vs-switch-off branch equivalence also untested (LOW).
5. LOW/MEDIUM fail-open contract: every `except Exception` fail-open (substrate, presence x2, fan_veto, census x2,
   house getters, entity registry) can be flipped to fail-closed or to raise with the suite green. A
   getter that raises would then drop real presence (fail-closed) with no test noticing. One parametrized test
   (getter raises -> reader counts the input as before) covers all.
6. LOW `_notify_substrate_stream_flips` never-raise path untested; `_camera_stream_prev_dead` initial value
   untested; `entity_stream_dead` direct-False-return and `camera_is_dead` pre-first-tick (None resolution) untested.

Equivalent mutants (no action): _room_coordinators filter, empty-key guards, camera. prefix guard in
camera_stream_dead, no-cam guard.

## Verdict: FIX-REQUIRED (test-only)

Production sites are all load-bearing at the happy path: every S2 reader site, the three house getters and
the flip notify have a RED row. Must-fix before ship, tests only: findings 1, 2, 3, 4 (dedupe + unmapped guard)
and 5 (single parametrized fail-open test). Finding 6 and the LOWs may ride. No production-code defect found.
