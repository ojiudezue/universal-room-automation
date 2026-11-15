# Review A: person-awareness layer ship 3a (local correctness, byte identity per site)

Date 2026-11-14. Reviewer: ura-reviewer, framing A. Tier 2-DB, operator-elevated.
Branch `feature/layer-ship3a` @ 0b7d5061. Diff base `bc4f462b` (`git merge-base HEAD bc4f462b` = bc4f462b),
three-dot diff, 32 files. Plan `PLANNING_person_awareness_layer_ship3.md` rev 3.4.1 (plan/person-awareness-ship3
@ 4d6a3daf) §4-§5. Contract `CONTRACT_person_awareness_layer.md` §2-§4.3.

Read first: PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md (completely, incl. §10 ledger), SENSOR_FLEET_CLASSES.md
(completely), CONTRACT_person_awareness_layer.md (completely). HVAC_ARCHITECTURE_STATE_OF_PLAY.md: read the
ship 3a header entry and the hvac.py:1230-1242 setter it describes; the HVAC doc was not read end to end, and no
finding here depends on the rest of it. IDENTITY_FUSION_CAMERAS_MANUAL.md and QUALITY_CONTEXT.md: consulted for the
bug classes and F1-F5 vocabulary only. No §10 ledger claim is re-asserted here.

Tests run (targeted, 24 files: ship3a, guard, arrival_edges, census_trust_golden, crossing_ledger(+wiring),
crossing_vision setup/shadow, egress_display_reread, face_sighting realhass/tripwire, lock_face_arrival,
path_alpha_d2a, read_api ship1/ship2, person_sighting(+review a/b), geofence_late_person, residency x4,
sc_lock_person_sighting): **733 passed, 1 skipped**. Tree left clean.

## Verdict: SHIP

INV-3A-NOOP holds at every site I checked. The only differences are the two named exceptions. No CRITICAL, HIGH
or MEDIUM findings. Two LOWs, both plan-completion or semantics notes, not no-op breaks.

## Site-by-site (INV-3A-NOOP)

| Site | Old | New | Verdict |
|---|---|---|---|
| F5 geofence `presence.py:5686-5695` | `async_dispatcher_send(hass, SIG, {"person_entity", "source": "geofence"})` in the `else` of the observation-mode check, after `handle_geofence_event` | `dispatch_person_arriving(PersonArrivingPayload(entity_id, "geofence"))`, same branch, same position | Holds. `to_signal` (`signals.py:47-62`) emits exactly 2 keys in order; same sync call; trigger first. Pinned by `test_dispatch_person_arriving_payload_equal[geofence]` (key order asserted) and `test_geofence_inference_trigger_order_unchanged` |
| F5 camera_face `presence.py:5950-5959` | 4-key dict, `sighting` object, `zone = house_zones[0] or ""` | payload with the same 4 fields | Holds. `sighting` is never None on this path (`sighting.person_entity` is read above), so `to_signal` emits all 4 keys in the old order and the same object (no `asdict` copy). Observation-mode `_skip` at `:5916` is unchanged |
| F5 BLE `person_coordinator.py:1207-1219` | in-block import + 2-key dict inside `if person_entity`, in the observation-mode `else` | same guard, same branch | Holds |
| `dispatch_person_arriving` `signals.py:156-170` | n/a | raises ValueError only on None/"" source (all three sources are literals); counter after the send | Holds. The counter writes only `hass.data[DOMAIN]["person_awareness_layer_counters"]`. I checked the six `hass.data[DOMAIN]` value scanners (`aggregation.py:852, 878`, `energy.py:11222, 11269`, `notification_manager.py:6257`, `memory_baseline.py:214`): every one filters by isinstance / callable `_get_room_area` / dict, so the new `LayerCounters` value is ignored |
| Face latch register `person_sighting.py:150-152`, teardown `:201-206` | `setdefault(DOMAIN).setdefault(key, []).append(cb)`; teardown removed the first equal cb | `register_face_latch_callback` (same list, same key, same append); unsub removes the first equal cb | Holds. Double-setup without teardown behaves the same: two entries, one removed |
| Face latch read `camera_census.py:5917-5920` | `list(hass.data.get(DOMAIN,{}).get(key) or ())` in try | `face_latch_callbacks` = tuple snapshot, same get-without-setdefault, try inside | Holds. Same order, same per-message read |
| `note_face` `presence.py:671-676`, `person_sighting.py:670` | two private assignments | the same two assignments | Holds. `test_note_face_equal` |
| Exit backfill `camera_census.py:5301-5313` | `SIGNAL_EGRESS_EXIT_BACKFILLED {row_id, person_id}` | `amend_crossing(hass, None, {}, ..., role="exit_backfilled", row_id, payload_extra={"person_id": slug})` | Named exception 2, as specified. With a tracker: `attach_crossing_attribute`, `source_ref` None, so no ring access and no aged-out count, one send. Without a tracker: `_check_crossing_changes({})` then one send. Payload `{role, source_ref: None, row_id, person_id: slug, egress_camera: None}` (extra wins). Inside the existing `try`. Readers `sensor.py:5092-5094, 5231-5233` return early unless `role == "exit_backfilled"`, then schedule the same re-read. Old readers ignored the payload, so the end state is identical with a tracker, without one, and without presence. `test_exit_backfill_display_equal[tracker|no_tracker|no_presence]`, `test_exit_backfill_ring_untouched`, `test_exit_backfill_reader_ignores_other_roles`. No other sender of the new signal exists in 3a (git grep) |
| Lock entry areas `arrival_edges.py:338-344` | `_egress_entities` then every group's neighbours, in dict order | `tracker.door_entry_entities()` (`transit_validator.py:1301-1308`): same list, same order; a non-tracker object gives `[]` as before | Holds. Same set |
| Perimeter `_near_areas` `perimeter_alert.py:6002-6011` | `_door_group_for_stem` then `nb[group]` if present, inside try | `door_neighbours_for_stem` (`transit_validator.py:1310-1317`): same group lookup, `.get(group) or ()` | Holds. Same set, same exception swallow. `test_door_entry_areas_unchanged[lock|perimeter|no_presence]` |
| HVAC setter `hvac.py:1239-1242` | `pc._pre_arrival_enabled = value` | `pc.set_pre_arrival_enabled(value)` = the same assignment (`person_coordinator.py:2265-2270`) | Holds. The only writer of `hass.data[DOMAIN]["person_coordinator"]` is `__init__.py:3170` (a real `PersonTrackingCoordinator`), so the method always exists |
| PLB census reads `binary_sensor.py:2220, 2270` | `house_census_view(hass, "trust")` | `cls="house_state"` | Holds in every switch state: `house_state` is not in `CROSSING_VISION_CONSUMER_CLASSES` = {display} (`const.py:6641`), so `view_for_class` returns trust before it reads the switch. `test_census_view_cls_house_state_is_trust`, `test_phone_left_behind_reads_house_state_class` |
| `_CensusAwarenessSensor` `sensor.py:4222-4224` | `get_house_census(view_for_class("display"))` | `get_house_census(cls="display")`, so `house_census_view(view=view_for_class(hass,"display"))` | Holds. The rule moved verbatim to `census_view.view_for_class` (`census_view.py:58-81`; same 4 gates, same `hass.states` read, same fail-to-trust). `view_for_class` never raises, so calling it outside the `try` is safe. `test_census_view_positional_and_cls_equal[on|off|None]`, `test_census_awareness_sensor_reads_display_class_golden[on|off]` |
| Crossing vision onto G1 `crossing_vision.py:417-427` | `async_dispatcher_connect(SIGNAL_RESIDENCY_EVENT, self._on_residency_event)` | `subscribe_person_edges(..., kinds=EDGE_KINDS)` | Holds. `_on_residency_event` is already `@callback` (`crossing_vision.py:1204`), and the closure is `@callback` with no person filter. Every residency record has kind arrival or departure (the only two `KIND_*` in `residency.py:32-33`), so delivery is identical, inline, in the same connect order. `test_crossing_vision_residency_delivery_equal` |

## New surfaces against the plan

- **Ring** (`transit_validator.py:1153-1177`): appended after the two pointer assignments, inside the existing
  store `try` (`:2506-2522`); the bus fire comes before it, as before. Pruned by count then age on append and every
  read. A naive/aware `TypeError` is swallowed (the count bound still holds). `crossing_store_failed` is counted in
  the except (`:2523`).
- **`get_crossings_since`**: `ts >= t` (inclusive), oldest first, merged with a stable sort, plain tuple. Matches
  §4.3.
- **G3** (`:1225-1279`): forbidden and unknown keys raise before anything happens. The record is replaced in place
  at the same index. Pointers move only when they hold the same `source_ref`. With `source_ref` None the ring is
  untouched and nothing is counted. Not found is counted `crossing_record_aged_out`. Exactly one send per call,
  found or not, payload base keys then extra. `provenance` is a real `CrossingRecord` field (`:957`), so
  `dataclasses.replace` accepts it. The `nameable` default `MappingProxyType` is excluded from the hash
  (`hash=False`) on the frozen dataclass. `test_g3_forbidden_keys[x6]`, `test_g3_fires_once_found_or_not`,
  `test_ring_amend_does_not_clobber_newer`.
- **`door_camera_device_ids`** (`:1283-1298`): reads only the entity-registry `device_id`. No name inference.
- **`location_moves_since` / `_truncated_since`** (`person_coordinator.py:2306-2330`): logged at the one move site
  under the same condition as the `ura_person_location_change` fire (`:1137-1140`, inside the same
  `location_changed and old_location not in ("unknown", "")` block). Same `now`. Unresolved person = not logged and
  counted. Inclusive, oldest first, truncation = (full and oldest > t) or t < creation, as plan D4 line 378 says.
- **`get_person_edges_since` / `person_edges_truncated_since`** (`presence.py:6060-6085`, `residency.py:301-326`):
  `edge_ts >= t`, float epoch, plain tuple. Truncation = (full and oldest > t) or t < `created_ts`. No tracker =
  True. Every True is counted. Matches plan D2.
- **diagnostics.py**: returns only `{"person_awareness_layer": get_layer_diagnostics()}` for the CM entry and `{}`
  for every other entry. It reads `entry.data` only to compare the entry type. It writes nothing.
  `get_layer_diagnostics` (`presence.py:6145-6176`) holds only ints and dicts of ints keyed by source/role/camera.
  **Its tests can fail. I drilled this with real source mutation, then restored the file and saw `git status`
  clean:** (1) adding `entry.data` / `entry.options` to the returned dict failed both
  `test_diagnostics_download_contains_layer` and `test_diagnostics_download_has_no_config_entry_data`; (2) merging
  `entry.options` into the layer dict failed `test_diagnostics_download_has_no_config_entry_data`. One note: HA's
  diagnostics handler wraps this dict in its standard envelope (HA version, installed custom components, manifest).
  That is outside URA's control and contains no config-entry data.
- **Registry rule**: `git diff ... -- custom_components` has no added `startswith` / `endswith` / `split(` /
  `.replace(` / `f"person.` / `lower()` in production code. The BLE move log reuses `_find_person_entity`
  (`person_coordinator.py:1807-1821`), the BLE F5 producer's own pre-existing derivation, as the plan requires.

## Findings

| # | Sev | Where | Finding | Class |
|---|---|---|---|---|
| A-L1 | LOW | `person_coordinator.py:2306-2330`; plan D4 line 379 | The plan says "presence delegates for both" `location_moves_since` / `location_moves_truncated_since`. No presence delegate exists (`git grep` finds only the owner methods). Contract §4.1 places them on `PersonTrackingCoordinator`, so the plan and the contract disagree. No 3a consumer, no behaviour change. Fix: add the two never-raising delegates, or record the drop in plan §15 and fix plan line 379 | Plan-completion (silent drop) |
| A-L2 | LOW | `person_coordinator.py:2313-2324` | `location_moves_truncated_since(t)` answers False for `t` older than `PERSON_LOCATION_MOVES_MAX_AGE_S` (1800 s) while the log is not full, yet moves in `[t, now-1800 s]` were age-pruned. Repro: one move at now-2400 s, log size 1 then 0 after prune, `t = now-3600` gives `since() == ()` and `truncated == False`. This matches the plan's two literal conditions, but not the read's stated purpose ("may be missing moves"). The residency read has no age prune, so it is not affected. Fix (one line): also return True when `t < now - MAX_AGE_S`. A caller with naive `t` raises `TypeError` (no try); the documented type is `datetime`, so this is acceptable | Semantics gap (#63-adjacent: two bounds, one reported) |

## Invariant checklist

| Invariant | Result |
|---|---|
| INV-3A-NOOP: F5 payloads (keys, order, count, timing, obs-mode) | PASS |
| INV-3A-NOOP: face latch typed register / read | PASS |
| INV-3A-NOOP: exit backfill end state (tracker / none / no presence); ring untouched | PASS (named exception) |
| INV-3A-NOOP: lock entry areas, perimeter neighbours | PASS |
| INV-3A-NOOP: HVAC setter, note_face | PASS |
| INV-3A-NOOP: census view, PLB `house_state`, awareness sensor `display`, every switch state | PASS |
| INV-3A-NOOP: crossing vision on G1 (equality, order, sync) | PASS |
| New reads: shapes, inclusivity, truncation vs plan | PASS (A-L1, A-L2) |
| diagnostics: counters only; test can fail | PASS (mutation-drilled) |
| Registry rule in new code | PASS |
| Only two no-op exceptions | PASS |

## Statistics

| Severity | Found | Fixed | Deferred |
|---|---|---|---|
| CRITICAL | 0 | - | - |
| HIGH | 0 | - | - |
| MEDIUM | 0 | - | - |
| LOW | 2 | 0 | 2 (orchestrator's call; both 1-10 LoC, in-cycle fixable) |

Bug classes: plan-completion silent drop (1), concept split between two bounds with one reported (1). No new bug
class for QUALITY_CONTEXT.md.
