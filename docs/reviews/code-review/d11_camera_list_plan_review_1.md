# D11 camera-list live rewire: plan review 1 of 2 (completeness)

- **Subject:** `docs/planning/PLANNING_perimeter_fp_build_2026_11.md` §D11 (rev 2), card CAMERA-LIST-LIVE-REWIRE-1
- **Tier:** 3. This is the completeness review. Review 2 (adversarial build-prediction) is still owed.
- **Base:** develop @ `b0ed5193`, which includes v5.107.0 through v5.107.5. Every line anchor below was re-read against this tree.
- **Verdict:** ❌ **FIX-PLAN-FIRST.** The §D11 enumeration misses one CRITICAL consumer and has seven HIGH gaps. Fixes are applied in the extracted plan `docs/planning/PLANNING_camera_list_live_rewire_2026_11.md` (rev 1).
- **Scope verdict:** FOCUSED once the fixes are in. Two items push scope: routing `CONF_CAMERA_PERSON_ENTITIES` through the rediscover, and the egress tracker rebuild. Both are needed for the invariant to hold, so they stay in. The `door_entry_areas` wrong-object defect moves out to its own card.

**Read for this review:** the §D11 text; AUDIT_integration_options_reload_classification.md §70-150 (the parked follow-up list); the kanban card; PLANNING_frigate_mqtt_direct_2026_11.md (sequencing). Targeted greps only, not full reads: DEVICE_TREE.md (no per-camera devices, so not affected), IDENTITY_FUSION_CAMERAS_MANUAL.md, and PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md (the lock-regime entry-area claim at :79). I did NOT read the presence doc or SENSOR_FLEET_CLASSES.md completely. That is acceptable for this review because no sensor class or fusion claim is in question. The build reviewers must read both in full. The HVAC doc does not apply.

## Independent re-enumeration (today's code)

Grep: `CONF_PERIMETER_CAMERAS|CONF_EGRESS_CAMERAS|perimeter_cameras|egress_cameras` plus every reader of the derived maps (`get_cameras_for_area`, `get_person_sensor_for_area`, `get_platform_for_camera`, `get_all_*_cameras`, `has_cameras`, `_get_integration_camera_list`, `get_transit_egress_entities`, `door_entry_areas`, `_perimeter_allowlist`, `set_allowed_cameras`).

| # | Consumer | Anchor | Read style | In §D11? |
|---|---|---|---|---|
| 1 | `CameraIntegrationManager` maps `_cameras_by_area`, `_camera_by_entity`, `_platform_by_entity`, `_resolved_devices` | camera_census.py:1038-1070, built at __init__.py:2925-2934 | cached at setup | yes |
| 1a | Readers of (1): sensor.py:2809, presence.py:4979/5006/5014, coordinator.py:4095, camera_census.py:1241/2001/2173/2286/2805/5854 | — | live read of (1) | partly (coordinator and census readers not listed) |
| 1b | `_unresolved_by_scope` | camera_census.py:475, :795 | rebuilt on every `_get_integration_camera_list` | n/a (self-correcting) |
| 2 | Enhanced-census event triggers (`unsub_census_events`), built from `get_all_frigate/unifi_cameras()` | __init__.py:3062-3110 | **cached at setup** | **NO** |
| 3 | PerimeterAlertManager: person, egress, vehicle and animal subscriptions; `_sensor_to_camera`, `_sensor_platforms`, `_sensor_engine`, `_person_legs_by_key`, `_zone_map`, `_zoned_cameras`, `_zone_key_overrides`, `_dual_role_cameras`, `_perimeter_allowlist` | perimeter_alert.py:508-1143 | cached at setup | partly (`_person_legs_by_key`, zone maps and `_dual_role_cameras` not listed) |
| 3a | Dual-role-only listeners: `_unsub_egress_identity`, `_unsub_person_arrivals`, `_fp_setup_ts` | perimeter_alert.py:990-1007 | conditional on (3) | **NO** |
| 3b | HA_STARTED one-shot `_rescan_siblings(perimeter_infos)`, which closes over the setup-time infos | perimeter_alert.py:1159-1165, :2853 | cached closure | **NO** |
| 3c | Early return when there are no perimeter sensors: the frigate_events listener, agreement load, vehicle/animal legs, rescan and sweep are never installed | perimeter_alert.py:879-883 | structural | **NO** |
| 3d | In-flight work: `_pending_holds` (D5/D10.5), `_pending_dispatches`, `_pending_followups` (v5.107.5), D5 agreement open samples | :4617-4642, :1944-1953, :5161-5233, :4785-4811 | live | partly (claims they run on "closure state") |
| 4 | ExteriorTrackLinker `_allowed_cameras` / `_allowlist_installed` | exterior_track_linker.py:363-372, :432-450; installed at perimeter_alert.py:763-787 | cached | yes, but the empty case is wrong |
| 5 | TransitValidator subscriptions | transit_validator.py:421-504; rebuilt via signal at :357-364 with a 5 s debounce at :507-533 | cached with refresh signal | yes, but not in a fixed order (see F5) |
| 6 | **EgressDirectionTracker**: `_egress_entities`, `_interior_entities`, `_egress_count_sensors`, peak-count listeners, `_count_sensor_to_stem` | transit_validator.py:919-1110 (async_init), teardown at :2260 | **cached at init, no rebuild path** | **NO** |
| 7 | Lock regime `_entry_areas` / arrival_edges `door_entry_areas`; perimeter `_near_areas` | security_lock_regime.py:992-998, arrival_edges.py:183, perimeter_alert.py:5047-5074 | live read of `hass.data["transit_validator"]` | listed as a target, but see F9 |
| 8 | Lock regime person listener (v5.107.4) | security_lock_regime.py:496ff | keyed on persons, not cameras | n/a (unaffected) |
| 9 | Enrichment allowlist `CONF_PERIMETER_ENRICHMENT_PERSON_SENSORS` | perimeter_enrichment.py:84-124 | fresh per alert; separate key, not derived | n/a (unaffected; a stale entry for a removed camera is inert) |
| 10 | D5 agreement store (keyed by cam_key) | perimeter_alert.py:4818-4840 | persisted | n/a (a restart also reloads it, so parity holds) |
| 11 | optimization.py:2645-2649, :3295-3299 | — | fresh per call | yes (verified) |
| 12 | camera_census.py:1676, :2238-2239; transit_validator.py:476, :1002 | — | fresh reads | yes |
| 13 | Parked or planned plans: PERIMETER-FRIGATE-MQTT-DIRECT-1 replaces the perimeter `frigate_events` listener with an ingress consumer | PLANNING_frigate_mqtt_direct_2026_11.md:117-176 | — | **NO** (sequencing) |

## Findings

### CRITICAL

**F1. The EgressDirectionTracker is a cached camera-list consumer with no rebuild path. The plan never mentions it.** `async_init` (transit_validator.py:965-1110) caches `_egress_entities`, `_interior_entities`, `_egress_count_sensors` and the peak-count listeners, and subscribes once. It produces `ura_person_egress_event` (:2005). That event feeds census egress identity and perimeter D10.5 (`_on_egress_identity`, perimeter_alert.py:992). It does not listen to `SIGNAL_URA_TRANSIT_CONFIG_CHANGED`.
- **Repro:** add `camera.doorbell_lite` to egress via a live save. Perimeter and transit pick it up, but no `ura_person_egress_event` ever fires for it until the next restart. D10.5 for that door then never sees an egress identity.
- That breaks the invariant ("every consumer reflects the new list").
- **Fix:** extract a sync `_build_and_subscribe()` from `async_init`. It has no awaits today: verified at :965-1110. Have the orchestrator call it. Keep the histories (`_recent_*`, `_last_resolved`).

### HIGH

**F2. Perimeter early return at :879.** When the perimeter list is empty, setup returns before installing the frigate_events listener, the agreement load, the vehicle/animal legs, the HA_STARTED rescan and the snapshot sweep. A rewire from empty to non-empty would therefore leave all of these missing. A rewire from non-empty to empty has no setup equivalent at all.
- **Fix (simplest):** take the live path only when both the old and the new perimeter lists are non-empty. Any transition to or from empty falls back to the reload. These transitions are rare.

**F3. The linker allowlist cannot be emptied, and an empty install means "reject everything".** Setup installs only `if _allowed` (:774). `set_allowed_cameras(set())` flips the linker to fail-closed-all (:372, :450). A fresh restart never installs, which means allow-all. No live action matches restart parity.
- **Fix:** if the rewired allowlist is empty, raise, which falls back to the reload. F2 makes this case near-impossible, but it is still reachable when every perimeter camera fails to resolve.

**F4. A save during boot reuses stale infos.** `_unsub_started` (:1163) closes over the setup-time `perimeter_infos`. A save after setup but before `EVENT_HOMEASSISTANT_STARTED` would rewire, and then the rescan would subscribe late legs for cameras that were just removed.
- **Fix:** run the live path only when `hass.state` is running, `_unsub_started` is None, and the perimeter `_active` is True. Otherwise reload.

**F5. Dual-role listeners are conditional and not covered.** The `ura_person_egress_event` listener and the `person.*` arrival listener exist only when `_dual_role_cameras` is non-empty (:990-1007). Vehicle legs are also skipped for dual-role cameras (D10.3, :1028-1036). Adding a camera to the second list must install those listeners and drop its vehicle legs. Removing it must do the reverse. The plan's unsubscribe list (perimeter, egress, vehicle, animal) never touches the two listeners, which leaks or misses them.
- **Fix:** reconcile them explicitly. Install exactly once when the set becomes non-empty, remove when it becomes empty, and stamp `_fp_setup_ts` only on first install.

**F6. The plan's clear list is incomplete.** It clears `_sensor_to_camera`, `_sensor_platforms`, `_sensor_engine` and `_perimeter_allowlist`, but not `_person_legs_by_key` (:716, :2883). A stale leg for a removed camera key keeps counting in the D5 and D10.5 "both NVRs live" liveness check. `_build_zone_map` resets the three zone maps itself (:4344-4346), and the plan should say so. `_dual_role_cameras` must be recomputed.

**F7. A `CONF_CAMERA_PERSON_ENTITIES` save leaves the occupancy map stale today.** This is a pre-existing gap, and it is the same class as the reason this card exists.
- The key has been allowlisted since RELOAD-WATCHDOG-HAZARD. Its only discharge is the transit signal.
- `async_discover` builds `_cameras_by_area` from room, egress and perimeter cameras (__init__.py:2926-2934). A room-camera save therefore never rebuilds the map that sensor.py:2809, presence.py:5006 and coordinator.py:4095 read.
- The exclusion comment at __init__.py:7797-7803 says the camera-list keys were kept out *because* of that map. The same reasoning applies to the admitted key.
- **Fix:** route `CONF_CAMERA_PERSON_ENTITIES` through the same orchestrator. Without this, the invariant ("no consumer of the map is stale") is false on the first room-camera save.

**F8. "Fixed order" with a signal is not fixed.** Step (c) dispatches `SIGNAL_URA_TRANSIT_CONFIG_CHANGED`, and transit_validator handles it with a 5 s debounced timer (:507-533). The rebuild then lands up to 5 s after the orchestrator reports success, out of order and outside the fallback's try.
- **Fix:** call `tv._build_and_subscribe()` directly, and cancel any pending `_rebuild_timer_unsub`.

### MEDIUM

**F9 (pre-existing, card it and keep it out of this cycle). `door_entry_areas` and `_near_areas` read the wrong object.**
- `hass.data[DOMAIN]["transit_validator"]` is the `TransitValidator` (__init__.py:3454). `_egress_entities`, `_interior_neighbours_by_group` and `_door_group_for_stem` live only on `EgressDirectionTracker` (`hass.data["egress_tracker"]`; transit_validator.py:943, :955, :1178). Grep of `TransitValidator` (:194-918) finds none of them.
- Result: the lock regime's `_entry_areas()` is always empty, so the Bermuda leg never corroborates a face and a face never releases. Perimeter `_near_areas` gets only the camera's own area, because the attribute access raises and is swallowed.
- Both fail safe (no unlock, no demote), but it contradicts PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md:79 ("In practice the Bermuda leg is the one that decides").
- The unit test passes a `SimpleNamespace` carrying the attributes (test_lock_face_arrival_corroboration.py:649), which hides the defect.
- For D11 this means item 7 needs no rebuild today. Once F9 is fixed it reads the egress tracker live, and F1 covers that.
- Card: LOCK-ENTRY-AREAS-WRONG-OBJECT-1. Presence doc corrected in this commit.

**F10. "A dispatch in flight finishes on its own closure state" is not true.**
- The hold and dispatch paths re-read `self._sensor_to_camera`, `_sensor_platforms` and `_sensor_engine` after their awaits. Examples: `_is_dual_role_sensor` at :4891 and the zone gate at :4648.
- After an exact rebuild, a removed camera's entries are gone.
- The plan must say what happens. Rev 1 decides that holds and scheduled dispatches for a removed camera complete, because the edge happened while the camera was configured. Identity follow-ups for removed keys are discharged.
- The builder must enumerate every post-await `_sensor_*` read and show that `""` is safe. A test must drive a hold across a removal.

**F11. Census event-trigger subscriptions (consumer 2) are cached.** After a live save, a new camera never triggers an immediate census. The periodic census still covers it, so the impact is latency only. Rebuilding it is still needed for parity.

**F12. The plan's empty-window premise is overstated.** `_discover_from_configured_cameras` and `_discover_full_scan` contain no suspension point (camera_census.py:1072-1200, no `await`). Awaiting a coroutine that never yields does not hand control back to the loop, so no reader can observe the cleared maps today. The real hazards are:
- (a) an exception midway leaves partially built maps;
- (b) any future await would open the window.

Build-then-swap is still right. Rev 1 goes further: the whole orchestrator is synchronous, so there is no interleaving point anywhere, and no lock is needed.

### LOW

**F13. Sequencing with PERIMETER-FRIGATE-MQTT-DIRECT-1.** That plan moves the perimeter `frigate_events` subscription to an ingress consumer registration (`test_single_frigate_events_listener_site`). D11's "frigate_events listener count unchanged after 3 rewires" test must target whichever site exists when D11 is built. Rev 1 states it as "the frigate-event intake registration".

**F14. Mixed saves.** The Camera Census step writes both camera keys, `CONF_CAMERA_PERSON_ENTITIES` and egress-identity keys. The subset test already sends a mixed save with a non-allowlisted key to reload. The plan should say that a save changing both camera keys plus room cameras runs the orchestrator once.

**F15. Knob for observability.** The rewire runs synchronously on the event loop. A `CAMERA_LIST_REWIRE_WARN_MS` (rung 1, 500) WARN gives a cheap trip-wire if resolution ever becomes slow.

## Checklist

- **Institutional context:** partial in §D11. Prior art cited correctly. Missing: the egress tracker, the census triggers, the `CONF_CAMERA_PERSON_ENTITIES` map gap. Fixed in rev 1.
- **Invariant falsifiable:** yes, but its scope is wrong. "Equals a fresh restart" is false by design for histories and cooldowns. Rev 1 adds a divergence ledger.
- **Emission/consumer enumeration:** re-run above. Five consumers missed.
- **Knobs:** one in the plan, one added (F15).
- **Acceptance discriminating:** missing the config extremes. Added in rev 1.
- **Non-goals:** missing. Added in rev 1.
- **Parked-plan triggers:** the audit's parked follow-up #1 IS this card, and its trigger was operator request. Follow-up #2 (async-reload redesign) does not fire. The MQTT-direct plan is a sequencing dependency (F13).

## Summary

| Severity | Found | Fixed in plan | Carded out |
|---|---|---|---|
| CRITICAL | 1 | 1 | 0 |
| HIGH | 7 | 7 | 0 |
| MEDIUM | 4 | 3 | 1 (F9) |
| LOW | 3 | 3 | 0 |

**Bug classes:**
- #53 one-missed-site / computed-but-not-consumed: F1, F2, F5, F6, F11.
- Stale cached consumer (#7): F4, F7.
- Suppression-needs-discharge: F7, F8.
- Coincidental test fixture hides a wiring defect (hollow anchor): F9.
- Conditional-install asymmetry (a listener installed only under a setup-time condition is not reconciled on reconfigure): F2, F5. Candidate new QUALITY_CONTEXT class.
