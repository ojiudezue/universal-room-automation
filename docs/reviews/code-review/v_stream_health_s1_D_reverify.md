# Re-verify (framing D, spot-check of fix-up f88cc12c): camera input stream health S1

Branch `feature/camera-input-stream-health-s1`, fix-up diff `git diff bd5f4589..f88cc12c` (verified: bd5f4589 is the
review-C commit, the fix-up's direct parent). Read completely before review: `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`,
`SENSOR_FLEET_CLASSES.md`, `HVAC_ARCHITECTURE_STATE_OF_PLAY.md`. No ledger claim re-asserted; no doc/code contradiction
found (the presence doc line 7 already records the override side effect).

Targeted run: `test_camera_stream_health.py` + `test_camera_resolver.py` + `test_ble_extend_not_create.py`: 115 passed.
One drill: override filter removed (`_fusion_filter_active(...)` → raw list) → RED
`test_camera_override_not_held_by_dead_stream_input`, `test_camera_override_sensor_outside_inputs_watched_not_paged`.
Restored; `git status` clean.

## Verdict: FIX-REQUIRED (one MEDIUM, ~3 LoC) or operator acceptance of it by name

## Findings

| # | Sev | Site | Finding | Class |
|---|---|---|---|---|
| D-M1 | MEDIUM | `coordinator.py` camera override, `person_sensors = self._fusion_filter_active(self._camera_override_person_sensors())` (~:4258) | The fix for B-M1 filters the override through ALL exclusion clients (P22 continuous-on 4 h, duty-cycle, chatter, camera_stream_dead), not only the S1 client. That changes pre-existing behaviour outside S1's scope. Repro (legal config, not live today): Study A already lists `binary_sensor.study_a_panel_person_occupancy` in `presence_sensors`; add `camera.study_a_panel` to Study A's room cameras (camera manager keys `_cameras_by_area` by the configured camera's area, `camera_census.py:1104-1107`; the panel device is in area `study_a`). A person works at the desk ≥ 4 h, in frame: Frigate person occupancy stays `on`, P22 (`_p22_stuck_sensor_set`, `coordinator.py:2394`, `_stuck_sensor_hours` 4.0) excludes it, and the ZK radar is on as long and is excluded too. Before the fix-up the override read the sensor raw and held the room (source `camera`, HVAC evidence stamped); after it, the room vacates on a seated person: lights off, `hvac_occupied` releases after the tail. Live today: no room has an override sensor that is also an input (checked `.storage`: the three panel person sensors are inputs, but no panel camera is in any room's camera list), so unreachable now. Fix: filter by the S1 client only, e.g. `[s for s in sensors if "camera_stream_dead" not in self._exclusion_set.clients_for(s)]` (`sensor_exclusion.py:145`), keeping develop's override semantics for P22 / chatter / duty-cycle; drop the "Side effect" sentence from the presence doc line 7. Or the operator accepts the wider rule by name (Fix #8's comment shows the override was already meant not to defeat a stuck camera, so this is a policy call). | #53-adjacent scope creep on a sibling leg |
| D-L1 | LOW | `camera_stream_health.py` `_is_restored` | `restored: True` = no opinion with no time bound. A camera entity restored for days while its person sensor on the same device is live would never be excluded. Reaching it needs the integration to load the binary_sensor platform but not the camera platform; then the outcome is develop's behaviour (no exclusion), and P22 still backstops at 4 h. In the normal case (integration down) the input is restored `unavailable` too, so no frozen `on` exists. Accept; no fix needed. | state vocabulary |

## Closure of review A / B / C findings

| Finding | Closed? | Evidence |
|---|---|---|
| A LOW-1 continuity | yes | `_unavail_seen` + `_gap_seen`; stamp restarts only when a no-opinion reading intervened AND the last `unavailable` is > grace old. A room that simply did not tick keeps the stamp (correct: no evidence of a live reading). `test_no_opinion_stretch_longer_than_grace_restarts_stamp` (121 s / 119 / 120 boundary). |
| A LOW-2 invalidate | yes | `invalidate()` sets `_resolution_dirty`; `is_dead` keeps the old answer until the next tick rebuilds. `test_is_dead_before_first_tick_and_after_invalidate`. Stale window is at most one tick and matches the exclusion set. |
| A LOW-3 removed paged input | yes | dropped from `_paged_episode` silently. `test_input_removed_mid_episode_no_recovery_nm`. |
| B-M1 override | yes for the stream; see D-M1 for the wider filter | override sensors also feed `extra_inputs`, excluded, never paged, not shown (`if eid not in configured` at page, recover and snapshot). Two tests above, real override block executed from source. |
| B-L1 restored | yes | `_is_restored`; `test_restored_unavailable_camera_is_no_opinion_no_page`. See D-L1. |
| B-L2..L4 | accepted / validator note | unchanged, as recommended. |
| C HIGH-1 seam | yes | `test_real_registry_seam_reaches_er_async_get`. |
| C HIGH-2 lists | yes | `test_camera_backed_input_in_motion_list_excluded`, `..._occupancy_list_excluded`. |
| C HIGH-3 lifecycle | yes | three tests drive the real `async_config_entry_first_refresh` and the real `async_unload_entry` body (AST-extracted from `__init__.py`): survives clear, not duplicated on re-setup, unsubscribed on unload. |
| C MED-4..9 | yes | fail-open tick, missing state keeps stamp, recover kind asserted (`test_camera_stream_health.py:459`), prune, `is_dead` guard, resolver tests incl. no-device guard and fallback filters. |
| C LOWs | yes (except payload text, cosmetic) | raise branches, WARN silence, grace from const, sensor snapshot raise. |

## Spot checks

- **Lifecycle:** no new listener, timer or task. `_camera_override_person_sensors` is a sync O(1) read, exceptions swallowed. No leak.
- **No-op path:** with no camera manager or no area, `extra_inputs = []` and the override list is `[]`, same as develop. Kill switch off: no promote, override list unfiltered by S1 (other clients still filter, D-M1).
- **Shared stub `test_ble_extend_not_create.py`:** the three new `_FakeSelf` methods delegate to the REAL coordinator methods with a real, empty `SensorExclusionSet`; the default `_get_room_area` returns None, which yields `[]`, as develop did without a camera manager. `test_camera_block_unchanged_by_this_cycle` still sets its own area and asserts the same outcomes. Not weakened.
- **Forward trace of the override change:** override → `STATE_OCCUPIED` / source `camera` → lights, fans, `_stamp_hvac_evidence` → `hvac_occupied`. Only the D-M1 path changes it beyond S1.

## Invariant checklist

| Invariant | Status |
|---|---|
| INV-STREAM incl. override leg | PASS |
| Unresolved / killed byte-identical for the stream client | PASS |
| Override semantics unchanged outside S1 | LEAK (D-M1, legal config, not live) |
| Restored never strands a truly dead camera | PASS (no frozen `on` while restored; D-L1 edge = develop behaviour) |
| Listener lifecycle | PASS |

Must-fix: D-M1 (narrow the filter to `camera_stream_dead`) unless the operator accepts the wider rule.
