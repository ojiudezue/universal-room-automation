# D11 camera-list live rewire: plan review 2 of 2 (adversarial build-prediction)

- **Subject:** `docs/planning/PLANNING_camera_list_live_rewire_2026_11.md` rev 1 (commit 50460792), card CAMERA-LIST-LIVE-REWIRE-1. Read together with plan review 1 (`d11_camera_list_plan_review_1.md`).
- **Tier:** 3. This is the second plan review. Framing: "what will the builder get wrong reading this?"
- **Base:** develop @ `6b97e434` (v5.107.0 to v5.107.6). Every anchor below was re-read on this tree. v5.107.6 changed `perimeter_alert.py` near :5047-5070 only, so perimeter anchors after :5050 moved by +3.
- **Read completely first:** IDENTITY_FUSION_CAMERAS_MANUAL.md, PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md, DEVICE_TREE.md. Also PLANNING_frigate_mqtt_direct_2026_11.md §0-§6. The HVAC doc does not apply.
- **Verdict:** ❌ **FIX-PLAN-FIRST.** One CRITICAL and five HIGH. The CRITICAL makes the live path unreachable in production while the test plan stays green. Fixes are applied as rev 2 in the plan. With them applied, the plan is ready to BUILD with no further plan review needed.
- **Scope verdict:** FOCUSED. One consumer is added (C7, presence zone cameras). Everything else is a clarification or a narrowing.

## Hidden-await audit (the "synchronous orchestrator" claim)

| Piece | Today | Verdict |
|---|---|---|
| `CameraIntegrationManager.async_discover` | `async def`; awaits `_discover_from_configured_cameras` and `_discover_full_scan` (camera_census.py:1066, :1072) | Both bodies are `async def` with no await inside (:1074-1199). They must become plain `def` builders. A sync `rediscover` that calls them as they stand gets an un-awaited coroutine and builds nothing (R2-5). |
| `resolve_configured_cameras` / `resolve_camera_entity` | sync | Sync, but `resolve_camera_entity` WRITES `self._resolved_devices[device_id]` as a side effect (:594-595, :699). See R2-4. |
| `EgressDirectionTracker.async_init` | `async def`, no await in :965-1110 | Extractable as is. `_load_door_config` and `_protect_sourced_checkpoint_entities` are sync. |
| `TransitValidator._build_and_subscribe` | sync (:419) | OK. It swallows its own exceptions at DEBUG (R2-9). |
| `ExteriorTrackLinker.set_allowed_cameras` | sync (:363) | OK. |
| `PerimeterAlertManager.async_setup` :508-1143 | contains `await self._async_load_agreement()` at :1010, between the person/egress/intake/C3a block (:508-1007) and the vehicle/animal block (:1012-1143) | One `_wire_legs` helper cannot keep setup order. It needs two helpers (R2-5). |
| `_resolve_camera_infos`, `_resolve_legs`, `_build_zone_map`, `_rescan_siblings`, `_cancel_identity_followup` | sync | OK. |
| `PresenceCoordinator._discover_zone_cameras` | sync (presence.py:4958) | OK. New consumer C7 (R2-2). |
| Census camera trigger block | sync (__init__.py:3062-3106) | OK. Index and closure traps (R2-8). |

No step really awaits once R2-5 is applied. The orchestrator can be synchronous.

## Findings

### CRITICAL

**R2-1. Precondition P3 can never pass in production, so the live path never runs.** P3 requires `_unsub_started is None`. `_unsub_started` is assigned by `async_listen_once` at perimeter_alert.py:1163, and the only place that sets it back to None is teardown (:1214-1219). `_on_started` (:1160-1161) runs the rescan and leaves the handle set. So after boot `_unsub_started` is always non-None. Every camera-list save fails P3 and reloads, which is exactly today's behaviour.
- **Why the plan's tests would not catch it:** `test_camera_list_save_no_reload` and the P1-P4 parametrisation will set up the manager by hand (a fixture, or `_unsub_started = None` assigned directly). The suite goes green and the feature is inert live. This is the hollow-anchor class.
- **Fix (rev 2 §3.2 P3):** `_on_started` sets `self._started_rescan_done = True` and `self._unsub_started = None` after the rescan. The teardown path is unchanged (it already guards on None). P3 reads `_started_rescan_done`.
- **Test:** `test_camera_list_live_after_real_ha_started`. It runs the real `async_setup`, fires `EVENT_HOMEASSISTANT_STARTED` on the bus, then saves. It must not reload. Mutation: delete the flag assignment, and the test must go RED.

### HIGH

**R2-2. A missed consumer: presence zone cameras (C7). A naive fix would latch a zone occupied.**
- `PresenceCoordinator._discover_zone_cameras` (presence.py:4958-5080) runs once at CM setup (:3030). It walks `camera_manager.get_cameras_for_area` and calls `tracker.register_camera(person_sensor)` (adds to `_camera_entity_ids`). It subscribes one `async_track_state_change_event` (`_camera_listener_unsub`) and seeds `_camera_occupied`.
- Rev 1 §1 lists presence.py:4979/5006/5014 as "C1r, read C1 live, no action". That is wrong: they run at discovery time, and the result is cached in the trackers and in the listener.
- Effect today: a camera added to a room area never feeds zone occupancy or the house-state camera tier until a restart. After a fresh setup it would, so INV (a) fails.
- **Trap:** the function already has re-entry teardown (the H2 fix-up comment at :5034). A builder will simply call it again. `register_camera` only adds, though, and the new subscription drops a removed camera. If that camera reads `on` at save time, its `_camera_occupied[eid] = True` never clears. The zone-wide reads at presence.py:4519 and :7708 (`any(_camera_occupied.values())`, no timeout) then hold the zone occupied until restart.
- **Fix (rev 2 §3.7):** a sync `PresenceCoordinator.rewire_zone_cameras()`. It purges every removed entity from each tracker's `_camera_entity_ids`, `_camera_occupied` and `_camera_last_seen`, recomputes `_has_camera_sensors`, then calls `_discover_zone_cameras()`. Reach presence via `hass.data[DOMAIN]["coordinator_manager"].coordinators.get("presence")` (the pattern at __init__.py:6190). There is no `hass.data[DOMAIN]["presence"]`. If presence is absent or has not discovered yet, skip the step: its own setup will read the new map.
- **Tests:** `test_presence_zone_camera_added`, `test_presence_zone_camera_removed_while_on_not_latched`. Mutation: drop the purge, and the second test must go RED.

**R2-3. P3/P4 contradict each other on installs with no perimeter cameras, and the room-camera key regresses.**
- The perimeter manager is created unconditionally (__init__.py:3491). Its `_active` is False whenever setup returned early at :879-883 (no perimeter sensors).
- P3 says "if the manager is present, `_active` must be True, else reload". P4 says "both empty means skip the perimeter step". On an install with no perimeter cameras, P3 fires first and every camera save reloads.
- That includes a `CONF_CAMERA_PERSON_ENTITIES`-only save, which is reload-suppressed today (allowlisted since RELOAD-WATCHDOG-HAZARD). With the flag True, rev 1 also turns any precondition miss on a room-only save (for example a save during boot) into a NEW parent reload. That reintroduces the watchdog exposure this cycle exists to remove.
- **Fix (rev 2 §3.1 and §3.2):** the fallback is "today's behaviour for this save". For a save that touches `CONF_PERIMETER_CAMERAS` or `CONF_EGRESS_CAMERAS`, that means reload. For a room-only save, it means signal-only (today's path) plus a WARN. The perimeter step runs only when `_active` is True. If `_active` is False, a perimeter or egress change returns "reload", and a room-only change skips the perimeter step. P4 and `_wired_perimeter_cameras` are deleted: `_active` already means "old resolved non-empty", and the new-empty case is caught in `rewire()` (R2-6).
- **Tests:** `test_room_camera_save_no_perimeter_install_no_reload`, `test_room_camera_save_precondition_miss_signal_only`.

**R2-4. "Build into locals, then swap" cannot be done as written: the device cache is written by the resolver.** `_discover_from_configured_cameras` → `resolve_configured_cameras` → `resolve_camera_entity` reads and writes `self._resolved_devices` (camera_census.py:594-595, :699). This is a per-device result cache, and setup starts it empty (:1061).
- A builder who builds the three public maps into locals while leaving the cache live has two problems:
  - (a) Parity breaks. A device whose entities changed since boot keeps its stale `CameraInfo` list. Example: the operator's `camera.garage_a` → `camera.garage_a_2` swap flow, or a new `_2` leg.
  - (b) D2's "exception keeps the old maps identical" is violated silently: `is` still holds, but the old cache dict was mutated.
- **Fix (rev 2 §3.4):** `resolve_camera_entity` and `resolve_configured_cameras` take an optional keyword `cache: dict | None = None`, which defaults to `self._resolved_devices`. Existing callers are unchanged. The bundle builder passes a fresh local dict. `rediscover` assigns it as the fourth map. Do NOT swap `self._resolved_devices` temporarily.
- **Tests:** `test_rediscover_rebuilds_device_cache` (a registry change between setup and save is reflected); `test_rediscover_exception_keeps_old_maps` also compares cache CONTENTS, not only identity.

**R2-5. The two awaits that rev 1 hides.**
- (a) The discover bodies are `async def`. Rev 1 §3.4 says "refactor so they build into a local bundle" but never says to make them `def`. If they stay async, `rediscover` gets a coroutine back.
  - `test_orchestrator_is_sync` checks only the top-level functions, so it passes.
  - D2's equality test would catch it only if the fresh side is built through the same helper. Rev 2 makes both builders `def` and adds `-W error::RuntimeWarning` to the cycle test module.
- (b) `await self._async_load_agreement()` (:1010) sits between the person/egress block and the vehicle/animal block. Rev 1's single `_wire_legs` would move vehicle/animal subscription ahead of the await and change setup order. That contradicts the plan's own "byte-identical setup" criterion.
  - Rev 2 splits it into `_wire_person_egress_legs(perimeter_infos, egress_infos) -> tuple[list, list]` (:508-748 plus the allowlist computation :763-768) and `_wire_vehicle_animal_legs(perimeter_infos)` (:1016-1143).
  - `async_setup` calls them on either side of the unchanged await. `rewire()` calls both back to back.
  - "Byte-identical" means the ORDERED sequence of subscription calls and log lines.

**R2-6. The emptiness check is on the wrong set.** Rev 1 §3.3 item 4 raises when the new ALLOWLIST is empty. The allowlist is built from `perimeter_sensors + egress_sensors` (:764). A new perimeter list whose cameras all fail to resolve, with egress non-empty, passes the check. `rewire()` then leaves the intake, sweep and dual-role listeners installed with zero perimeter legs. A fresh setup in that state returns at :879 with none of those, not even the egress subscriptions (:912-935 are below the return). Parity fails.
- **Fix:** `rewire()` raises when the resolved `perimeter_sensors` list is empty: the :879 condition, checked before any mutation. The allowlist check is then implied.
- **Test:** the `test_rewire_empty_allowlist_raises` parametrisation gains a case "perimeter unresolvable, egress resolvable".

### MEDIUM

**R2-7. Egress tracker rebuild traps.**
- `_peak_count_unsubs` is a subset of `_unsub`: every peak unsub is appended to both (:1095-1096). Rev 1 says "unsubscribe `_unsub` and `_peak_count_unsubs`", which calls each peak remover twice. Use teardown's shape: iterate `_unsub` only, then clear both lists (:2262-2268).
- The fallback path (:999-1008) never resets `_egress_count_sensors`, and its exception path returns early. On a rebuild, the list from the previous run survives. Reset `_egress_entities`, `_egress_count_sensors`, `_interior_entities` and `_count_sensor_to_stem` at entry.
- Rev 1 says "keeps the door-group maps". The body calls `_load_door_config()`, which re-reads them. That is correct (fresh-read parity), and rev 2 says so.
- `_peak_count_buffer` is short history like `_recent_*`. It is kept (stale stems are inert) and added to the divergence ledger. Rev 1 cleared it.
- Pending `_delayed_resolve` timers (:1266, :1317) for a removed egress camera still fire and may emit one `ura_person_egress_event`. The crossing happened while the camera was configured. This is added to the ledger, consistent with perimeter holds completing.

**R2-8. Census trigger extraction traps.**
- Rev 1 §1 C2 says `unsub_census_events[0]`. Index 0 is the camera trigger only when `_person_detection_entities` was non-empty at setup (:3091-3095). Otherwise index 0 is the Bermuda trigger.
- The closure `_event_census_trigger` carries `nonlocal _last_event_census_time`. A helper that builds its own closure creates a second debounce state.
- **Fix:** at setup, store the trigger callable as `hass.data[DOMAIN]["census_event_trigger"]`. Register the camera subscription through `_wire_census_camera_triggers(hass)`, stored under `unsub_census_camera_events`. The helper reuses the stored callable and returns early if it is absent (enhanced census off). Setup order is unchanged: camera subscription first, Bermuda second.
- Pre-existing, noted only: :3106 overwrites `unsub_census_events`, which drops the HA_STARTED BLE-refresh unsub that :3032 appended. `entry.async_on_unload` still covers it. Not fixed here.

**R2-9. Invariant (c) promises more than the code can deliver.** `TransitValidator._build_and_subscribe`, the tracker body, `_resolve_camera_infos` (per-camera DEBUG + continue) and the linker install all swallow their own exceptions. The orchestrator's `try` never sees them, so "on any error the system falls back to reload" is false by construction.
- **Restated (rev 2 §2 (c)):** an exception that ESCAPES a rebuilder falls back. An exception a rebuilder swallows degrades exactly as a fresh setup with the same registry would, so parity holds.
- Step-exception tests inject at the rebuilder boundary, not inside it.

**R2-10. "Removed" is ambiguous: entity ids or camera keys.**
- `_pending_followups` and `_person_legs_by_key` are keyed by camera key (`_camera_key_for_sensor`), not by `camera.*` entity id. Rev 1 defines `removed = old_keys - new_keys` without saying which.
- **Rev 2:** `old_keys = set(self._person_legs_by_key)` captured before the reset, `new_keys = set(self._person_legs_by_key)` after `_wire_*`.
- A follow-up on a camera that stays perimeter but stops being dual-role is also discharged (`camera_not_dual_role`), because follow-ups exist only for dual-role alerts.
- The fixture uses a camera whose entity id differs from its key (`camera.front_door_aerial_2` → key `front_door_aerial`), so a mix-up goes RED.

**R2-11. Wrong-object risk (the v5.107.6 class).** Five objects, five keys. Rev 2 §3.2 lists them:

| Object | Key |
|---|---|
| CameraIntegrationManager | `hass.data[DOMAIN]["camera_manager"]` |
| PersonCensus | `hass.data[DOMAIN]["census"]` (holds a reference to the camera manager, so `rediscover` must MUTATE the existing manager, never replace it) |
| EgressDirectionTracker | `hass.data[DOMAIN]["egress_tracker"]` |
| TransitValidator | `hass.data[DOMAIN]["transit_validator"]` |
| Exterior track linker | `hass.data[DOMAIN]["exterior_track_linker"]` |
| Presence | `hass.data[DOMAIN]["coordinator_manager"].coordinators["presence"]` |

- TransitValidator also subscribes egress cameras, so a step-4 call on the wrong object "works" for subscription counts. D4's discriminator (a `ura_person_egress_event` fires) catches it only with real objects.
- Rev 2 requires that the D1/D4/D5/C7 tests build the production classes and fetch them through these keys. No `SimpleNamespace` or `MagicMock` stands in for these objects, which is what hid LOCK-ENTRY-AREAS-WRONG-OBJECT-1.
- Mutation: swap the step-4 and step-5 keys, and `test_egress_tracker_rebuild_adds_camera` must go RED.

### LOW

**R2-12. Gate code shape.** Today the allowlist branch is `if ...: dispatch; advance snapshot; return` (__init__.py:8846-8878). "Fall through to the reload, do NOT return" needs a stated shape. Rev 2 §3.1 gives it: compute `ok` first; on a reload verdict, reseed and skip the suppress block; the shared reload tail at :8885-8900 is reached unchanged.

**R2-13. Stale after v5.107.6.** Rev 1 §1's last row and §8 describe `door_entry_areas` / `_near_areas` reading `transit_validator`. Since v5.107.6 they read `egress_tracker` live (arrival_edges.py:183; security_lock_regime.py:997; perimeter_alert.py:5065). After a C6 rebuild they see the new lists on their next call, so no action is needed, but the plan text must say this. Base and anchors are updated: `_resolve_camera_infos` is now :5343, `_cancel_identity_followup` :5164.

**R2-14. Sequencing with PERIMETER-FRIGATE-MQTT-DIRECT-1 (planned, rev 2, not built).**
- Both cycles edit `async_setup` around :937-985. MQTT-direct replaces the bus listen at :983 with `ingress.register_consumer("perimeter", ...)`, and D11 moves the code around it.
- The ingress is prefix-keyed, not camera-keyed, so it adds no camera-list consumer. Grep of the MQTT plan: no allowlist or camera-list read.
- **Rev 2:** build D11 after MQTT-direct merges to develop. The D3 setup-snapshot fixture is generated on that base, and INV (d)'s "intake registration" counts `register_consumer("perimeter", ...)` calls. If D11 lands first, the MQTT builder must re-anchor and keep the registration inside `async_setup`. Both ship at the arc-end restart, so the order costs nothing live.

**R2-15. C3a details.**
- `_unsub_person_arrivals` stays None when `_tracked_person_slugs()` is empty, even with dual-role cameras (:1004). INV (d) is counted per listener: `_unsub_egress_identity` present iff dual-role is non-empty; `_unsub_person_arrivals` present iff dual-role is non-empty and persons are tracked.
- A first install of C3a at rewire stamps `_fp_setup_ts = now`. That opens a 600 s window in which D10.5's face + arrival corroboration ignores arrivals. Fresh setup does the same, so this is parity. It is stated, with a test.
- The orchestrator must not `async_dispatcher_send` or `bus.async_fire` before its final INFO log. Synchronous `@callback` targets would run inline and observe a half-rebuilt state.

## Test-plan coverage of predicted builder mistakes

| Predicted mistake | Caught by rev 1 tests? | Rev 2 test |
|---|---|---|
| P3 never true live | No (fixture sets None) | `test_camera_list_live_after_real_ha_started` + mutation |
| Discover bodies left async | Partly | `-W error::RuntimeWarning` + `test_rediscover_equals_fresh_discover` through the shared builder |
| Device cache stale or mutated | No | `test_rediscover_rebuilds_device_cache`, contents check |
| Setup reordered across the await | Only if the snapshot is ordered | `test_perimeter_setup_byte_identical` compares ORDERED calls and logs |
| Presence zone camera missed or latched | No | `test_presence_zone_camera_added`, `..._removed_while_on_not_latched` |
| Room-only save reloads | No (rev 1 asserted the opposite) | `test_room_camera_save_no_perimeter_install_no_reload`, `..._precondition_miss_signal_only` |
| Empty check on the allowlist | No | new `test_rewire_empty_allowlist_raises` case |
| TV/tracker swapped | Only with real objects | real-object rule + key-swap mutation |
| Tracker double unsub or stale lists | No | `test_egress_tracker_rebuild_fallback_resets_lists`, `..._no_double_unsub` |
| Census index or closure | No | `test_census_camera_triggers_rebuilt_no_cameras_at_setup`, `test_census_trigger_shares_debounce` |
| Entity id used as camera key | No | follow-up fixture with id ≠ key |

## Invariant falsifiability

Rev 1 (a), (b) and (d) can be falsified. (c) could not be satisfied (R2-9). (a) named a cache whose parity was undefined (`_resolved_devices` grows per tick); rev 2 limits it to "built from an empty cache, keys equal on configured devices". The consumer set is now C1-C7. Reviewer D's target: INV-CAMLIST-LIVE (a)-(d) across the D3 matrix, the precondition table, the room-only fallback, and in-flight work.

## Summary

| Severity | Found | Fixed in plan | Deferred |
|---|---|---|---|
| CRITICAL | 1 | 1 | 0 |
| HIGH | 5 | 5 | 0 |
| MEDIUM | 5 | 5 | 0 |
| LOW | 4 | 4 | 0 |

**Bug classes:**
- Hollow test anchor (a fixture sets the state production never reaches): R2-1, R2-11.
- #53 one-missed-site: R2-2.
- Stale cached consumer (#7): R2-2, R2-4.
- Conditional-install asymmetry (review 1 candidate class): R2-3, R2-6, R2-15.
- Suppression-needs-discharge, inverted (a suppression path turned into a reload): R2-3.
- Wrong-object read (the v5.107.6 class): R2-11.
- Hidden suspension point: R2-5.

**QUALITY_CONTEXT candidate:** "fired-once handle never cleared". A `async_listen_once` handle kept after it fires reads as "pending" forever. Any gate on `handle is None` is then dead (R2-1).
