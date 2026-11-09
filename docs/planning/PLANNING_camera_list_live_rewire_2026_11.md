# PLANNING: camera-list options save without a parent reload (rev 2)

- **Card:** CAMERA-LIST-LIVE-REWIRE-1. Extracted from `PLANNING_perimeter_fp_build_2026_11.md` §D11 rev 2.
- **Revisions:**
  - Rev 1 applied plan review 1 (completeness): `docs/reviews/code-review/d11_camera_list_plan_review_1.md`.
  - Rev 2 applies plan review 2 (adversarial build-prediction): `docs/reviews/code-review/d11_camera_list_plan_review_2.md`, findings R2-1 to R2-15.
- **Tier:** 3. Both plan reviews are done, so the plan is ready to build. The build gets four framing-disjoint code reviews (A, B, C mutation, D adversarial completeness), the orchestrator's independent re-grep plus a mutation re-run, and an operator checkpoint before deploy.
- **Base:** develop @ `6b97e434` (v5.107.6). Line anchors are from that tree.
- **Branch:** its own branch. **Sequencing (R2-14):** build after PERIMETER-FRIGATE-MQTT-DIRECT-1 merges to develop. Both cycles edit `perimeter_alert.async_setup` around :937-985. Both ship at the arc-end restart, so the order costs nothing live.

## 0. Institutional context verified

**Prior art (REUSED):**

| Piece | Verdict | Where |
|---|---|---|
| Reload-suppress branch for the integration entry | REUSED | `__init__.py:8826-8900`; allowlist `INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS` at :7714; kill switch `INTEGRATION_RELOAD_SUPPRESS_ENABLED` at :7816 |
| Per-key discharge table | REUSED, with no new row | `_INTEGRATION_KEY_SIGNAL_TABLE` at :7825. The orchestrator is a direct call, not a signal. |
| Fallback parent reload | REUSED | the shared tail at :8885-8900 (untracked `async_reload`) |
| Transit subscription rebuild | REUSED | `TransitValidator._build_and_subscribe()` (transit_validator.py:419, sync), called directly; `_rebuild_timer_unsub` cancelled (:512-533) |
| Camera discovery | REUSED body | `CameraIntegrationManager._discover_from_configured_cameras` / `_discover_full_scan` (camera_census.py:1074-1199). They are `async def` with no await inside and become `def` builders (R2-5). |
| Device resolution cache | REUSED | `resolve_camera_entity` (:548) / `resolve_configured_cameras` (:711), gaining an optional `cache=` keyword (R2-4) |
| Perimeter wiring | REUSED body | `PerimeterAlertManager.async_setup` :508-1143, split into two sync helpers around the await at :1010 (R2-5) |
| Linker allowlist | REUSED | `ExteriorTrackLinker.set_allowed_cameras` (exterior_track_linker.py:363, sync) |
| Follow-up discharge | REUSED | `_cancel_identity_followup` (perimeter_alert.py:5164) |
| Egress tracker teardown shape | REUSED | `EgressDirectionTracker.async_teardown` (transit_validator.py:2260-2270) |
| Presence zone-camera discovery | REUSED | `PresenceCoordinator._discover_zone_cameras` (presence.py:4958, sync, already tears down its previous listener at :5034) |
| Presence lookup | REUSED | `hass.data[DOMAIN]["coordinator_manager"].coordinators.get("presence")` (pattern at __init__.py:6190) |

**New:**
- `CameraIntegrationManager.rediscover()` (sync), plus a sync `_build_maps(...)` returning a bundle. No equivalent exists: `async_discover` clears in place.
- `PerimeterAlertManager.rewire()` (sync), `_wire_person_egress_legs()`, `_wire_vehicle_animal_legs()`, and the `_started_rescan_done` flag. There is no reconfigure path today.
- `EgressDirectionTracker._build_and_subscribe()` (sync, extracted from `async_init`).
- `PresenceCoordinator.rewire_zone_cameras()` (sync; purge, then rediscover).
- `_wire_census_camera_triggers(hass)`, plus `hass.data[DOMAIN]["census_event_trigger"]` and `["unsub_census_camera_events"]`.
- `_camera_lists_changed(hass, entry, changed_keys) -> str`, the orchestrator. There is no equivalent orchestrator.
- `SIGNAL_CAMERA_LIST_CHANGED` is NOT added. Grep finds no hits, and none is needed.

**Read:**
- AUDIT_integration_options_reload_classification.md §70-150. This card is its parked follow-up #1, triggered by operator request. Follow-up #2 does not fire.
- The RELOAD-WATCHDOG-HAZARD comments at __init__.py:7699-7832.
- DEVICE_TREE.md, read completely: there are no per-camera devices or entities, so no registry surgery.
- IDENTITY_FUSION_CAMERAS_MANUAL.md and PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md, read completely for plan review 2.
- PLANNING_frigate_mqtt_direct_2026_11.md: the ingress is prefix-keyed, so it adds no camera-list consumer.
- The build reviewers must read the presence doc and SENSOR_FLEET_CLASSES.md in full.
- Memory: `feedback_parent_entry_reload_watchdog_hazard`, `feedback_suppression_needs_discharge`.

**Config-first:** no setting avoids the reload. The reload path works. This cycle exists to remove the reload's watchdog risk on an operator-requested save.

**Marginal benefit:** camera-list edits are rare. The wins:
- one fewer parent reload per edit;
- the watchdog-stall exposure removed from a security-relevant save;
- room-camera saves stop leaving the occupancy map and the presence zone cameras stale (F7, R2-2).

The marginal risk is a new writer to a shared primitive (the camera map) and a reconfigure path in perimeter. That is why every edge case falls back to today's behaviour for that save instead of growing handling.

## 1. Consumer enumeration (the surface)

This table is the result of an independent re-grep of `CONF_PERIMETER_CAMERAS|CONF_EGRESS_CAMERAS|CONF_CAMERA_PERSON_ENTITIES`, every reader of the derived maps, and every `hass.data[DOMAIN]["camera_manager"]` reader (coordinator, sensor, transit_validator, perimeter_alert, optimization, presence).

| # | Consumer | Anchor | Action in this cycle |
|---|---|---|---|
| C1 | Camera maps `_cameras_by_area`, `_camera_by_entity`, `_platform_by_entity`, plus the device cache `_resolved_devices` | camera_census.py:1058-1061; the cache is written by `resolve_camera_entity` :594, :699 | `rediscover()`: build all four into locals with a fresh cache, swap in one block |
| C1r | Per-call readers: sensor.py:2809, coordinator.py:4095, camera_census.py:210/1241/2001/2173/2286/2805/3770/3813/4350/5854, optimization.py:2943 | — | none (they read C1 on every call) |
| C2 | Enhanced-census camera trigger subscription | __init__.py:3062-3106 | rebuild the camera subscription only. The Bermuda trigger is untouched. |
| C3 | Perimeter subscriptions plus indexes (`_sensor_to_camera`, `_sensor_platforms`, `_sensor_engine`, `_person_legs_by_key`, `_zone_map`, `_zoned_cameras`, `_zone_key_overrides`, `_dual_role_cameras`, `_perimeter_allowlist`) | perimeter_alert.py:508-1143 | `rewire()`: exact rebuild |
| C3a | Dual-role listeners (`_unsub_egress_identity`, `_unsub_person_arrivals`) | :990-1007 | reconcile by set transition |
| C3b | HA_STARTED rescan closure | :1159-1165 | precondition: the rescan has run (else reload) |
| C3c | In-flight work: `_pending_holds`, `_pending_dispatches`, `_pending_followups`, agreement samples | :4617, :1944, :5164, :4785 | see §3.3 |
| C4 | Linker allowlist | perimeter_alert.py:763-787 → exterior_track_linker.py:363 | installed by `rewire()` |
| C5 | TransitValidator subscriptions | transit_validator.py:419-510 | direct `_build_and_subscribe()` |
| C6 | EgressDirectionTracker lists and subscriptions | transit_validator.py:965-1110 | new sync `_build_and_subscribe()` |
| C7 | **Presence zone cameras** (`tracker._camera_entity_ids`, `_camera_occupied`, `_camera_last_seen`, `_has_camera_sensors`, `_camera_listener_unsub`) | presence.py:4958-5080, run once at CM setup (:3030) | `rewire_zone_cameras()`: purge, then rediscover (R2-2) |
| — | Fresh reads, no action: optimization.py:2648/3298; camera_census.py:1676, :2238; perimeter `_resolve_camera_infos` :5343; the enrichment allowlist (a separate key); `_unresolved_by_scope` (self-correcting); the D5 agreement store (a restart reloads it too); the lock-regime person listener (keyed on persons) | | |
| — | `door_entry_areas` (security_lock_regime.py:997) and perimeter `_near_areas` (:5062-5070) read `hass.data["egress_tracker"]` live since v5.107.6. After a C6 rebuild they see the new lists on their next call. No action. | | |

## 2. Falsifiable invariant: INV-CAMLIST-LIVE

> After a camera-list save that the orchestrator accepts, every consumer C1-C7 reflects the new lists before control returns to the event loop. No consumer ever observes an empty or half-built camera map. If any rebuilder raises, the save falls back to today's behaviour for that save: a reload for perimeter or egress keys, signal-only for a room-camera-only save.

**Operational form (what reviewer D tries to break):**

- **(a) Parity.** When the orchestrator returns `"live"`, the structural state of C1-C7 is set-equal to what a fresh setup produces with the same options and the same entity registry:
  - the three public C1 maps, and the device cache, which is built from EMPTY and whose keys equal the devices of the configured cameras;
  - the C2 entity set;
  - the C3 subscribed entity sets per kind (person, egress, vehicle, animal) and every C3 index;
  - C3a listener presence, counted per listener (R2-15);
  - C4 `_allowed_cameras`;
  - the C5 and C6 subscribed sets and entity lists;
  - the C7 per-tracker `_camera_entity_ids` and the subscribed set.
- **(b) No observation of intermediate state.**
  - The orchestrator and everything it calls are synchronous: no `await` and no coroutine, so no loop turn falls between the first mutation and the last swap.
  - No `async_dispatcher_send` and no `bus.async_fire` happens before the final INFO log, so no inline `@callback` can observe a partial rebuild.
  - Within C1, the four maps are assigned in one block after the locals are fully built.
- **(c) Fallback.** An exception that ESCAPES a rebuilder, or a missed precondition, makes the orchestrator return `"reload"` (perimeter or egress key in the save) or `"signal_only"` (room-camera-only save). "Success" is never logged for a partial run.
  - Exceptions a rebuilder swallows internally (transit, tracker, `_resolve_camera_infos`, linker install) degrade exactly as a fresh setup with the same registry would, so (a) still holds. This is parity, not a hole (R2-9).
- **(d) Single install.** After N rewires, each listener family has exactly one registration per entity, and each of the following exists exactly once:
  - the frigate-event intake registration (the bus listen today; `ingress.register_consumer("perimeter", ...)` once MQTT-direct lands);
  - `_unsub_linker_ready`;
  - `_unsub_snapshot_sweep`;
  - `_unsub_egress_identity`, iff dual-role is non-empty;
  - `_unsub_person_arrivals`, iff dual-role is non-empty AND persons are tracked;
  - the C2 camera subscription and the Bermuda subscription;
  - the C7 `_camera_listener_unsub`.

**Divergence ledger.** These differ from a restart on purpose. Parity is NOT claimed for:
- `_last_alert` / `_last_vehicle_alert` cooldowns, `_recent_*` histories and the burst decisions;
- the Frigate id and event caches, and `_edge_captures`;
- the agreement tracker in memory;
- `_setup_time` (no new boot-settle window), and `_fp_setup_ts` once it is set (the boot exclusion is not re-armed; first-ever C3a install stamps it, as setup does);
- `_person_arrivals`;
- EgressDirectionTracker `_recent_*`, `_last_resolved` and `_peak_count_buffer` (R2-7);
- C7 `_camera_occupied` / `_camera_last_seen` for retained cameras;
- in-flight holds, scheduled dispatches and egress `_delayed_resolve` timers for removed cameras, which complete (§3.3, R2-7).

Keeping this state is the point: a restart drops cooldowns and can double-alert.

## 3. Design

### 3.1 Gate (listener branch, __init__.py:8826-8900)

```
CAMERA_LIST_KEYS = {CONF_PERIMETER_CAMERAS, CONF_EGRESS_CAMERAS, CONF_CAMERA_PERSON_ENTITIES}
STRUCTURAL_CAMERA_KEYS = {CONF_PERIMETER_CAMERAS, CONF_EGRESS_CAMERAS}
```

1. `CONF_PERIMETER_CAMERAS` and `CONF_EGRESS_CAMERAS` join the allowlist only while `CAMERA_LIST_LIVE_REWIRE_ENABLED` is True. Implement this as a computed frozenset, so that False restores the exact pre-cycle allowlist. `CONF_CAMERA_PERSON_ENTITIES` stays allowlisted either way.
2. **Code shape (R2-12).** Inside the existing `if INTEGRATION_RELOAD_SUPPRESS_ENABLED and changed_keys.issubset(allowlist):` branch, before `_dispatch_integration_key_signals`:
   ```
   verdict = "skip"
   if CAMERA_LIST_LIVE_REWIRE_ENABLED and changed_keys & CAMERA_LIST_KEYS:
       verdict = _camera_lists_changed(hass, entry, changed_keys)   # "live" | "reload" | "signal_only"
   if verdict == "reload":
       reseed snapshot to dict(entry.options); fall out of the suppress branch (no return)
       -> the shared reload tail at :8885-8900 runs unchanged
   else:  # "live", "signal_only", "skip"
       existing dispatch + success-gated snapshot advance + return (unchanged)
   ```
   A `"signal_only"` verdict logs WARN `camera-list live rewire skipped (<reason>); room-camera map stays stale until restart`. That is today's behaviour for that key, made visible.
3. On `"live"` the existing `CONF_CAMERA_PERSON_ENTITIES` transit-signal row still dispatches. It causes one extra debounced C5 rebuild 5 s later, which is idempotent.
4. With the flag False, a `CONF_CAMERA_PERSON_ENTITIES`-only save is byte-identical to today: the signal is dispatched and the orchestrator is not called.

### 3.2 Orchestrator `_camera_lists_changed(hass, entry, changed_keys) -> str`: sync, fixed order

- The orchestrator reads the CURRENT `{**entry.data, **entry.options}` for the lists, with the same `[]` defaults as setup (__init__.py:2927-2929), so back-to-back saves converge on the last one.
- `changed_keys` is used only to pick the fallback: `structural = bool(changed_keys & STRUCTURAL_CAMERA_KEYS)`, and `fallback = "reload" if structural else "signal_only"`.
- The whole body runs inside `try/except Exception → log WARNING, return fallback`.

**Objects (R2-11). Fetch exactly these. There is no other key.**

| Object | Key |
|---|---|
| CameraIntegrationManager | `hass.data[DOMAIN]["camera_manager"]` |
| EgressDirectionTracker | `hass.data[DOMAIN]["egress_tracker"]` |
| TransitValidator | `hass.data[DOMAIN]["transit_validator"]` |
| PerimeterAlertManager | `hass.data[DOMAIN]["perimeter_alert_manager"]` |
| Linker | `hass.data[DOMAIN]["exterior_track_linker"]` (read inside `rewire()`) |
| Presence | `hass.data[DOMAIN]["coordinator_manager"].coordinators.get("presence")` |

The census (`hass.data[DOMAIN]["census"]`) holds a reference to the camera manager, so `rediscover` MUTATES the existing manager. It never constructs a new one and never replaces the hass.data entry.

**Preconditions.** Any miss means `return fallback`:
- **P1.** `hass.state is CoreState.running`.
- **P2.** `camera_manager` is present.
- **P3 (R2-1, R2-3).** Let `pam` be the perimeter manager.
  - If `pam` is present and `pam._active`, then `pam._started_rescan_done` must be True.
  - If `pam` is absent or `not pam._active` and `structural`, return `"reload"`. This covers the empty to non-empty transition and an install with no perimeter cameras.
  - If `pam` is absent or `not pam._active` and not `structural`, skip step 3. Room cameras do not feed perimeter.
- P4 and `_wired_perimeter_cameras` from rev 1 are deleted. `_active` already means "the old list resolved non-empty", and the new-empty case raises inside `rewire()`.

**Steps, in this order:**
1. `camera_manager.rediscover(room, egress, perimeter)`. This runs first, because C2 and C7 read the C1 maps.
2. `_wire_census_camera_triggers(hass)`. It returns without doing anything if `census_event_trigger` is absent (enhanced census off).
3. `pam.rewire()`, if allowed by P3.
4. `egress_tracker._build_and_subscribe()`, if the tracker exists.
5. Transit validator, if it exists: cancel `_rebuild_timer_unsub` and set it to None, then call `tv._build_and_subscribe()`.
6. `presence.rewire_zone_cameras()`, if presence exists and `presence._zone_trackers` is populated. Otherwise presence's own setup will read the new map.
7. Log INFO with the elapsed ms and per-consumer counts. Log WARN if the elapsed time is ≥ `CAMERA_LIST_REWIRE_WARN_MS`. Return `"live"`.

There is no lock: a synchronous function cannot interleave.

### 3.3 `PerimeterAlertManager.rewire()`: sync

1. **Split :508-1143 around the await at :1010 (R2-5).**
   - `_wire_person_egress_legs(perimeter_infos, egress_infos) -> (perimeter_sensors, egress_sensors)` covers :508-748 (dual-role set, zone map, `_wire_camera` for both roles) and the allowlist computation :763-768.
   - `_wire_vehicle_animal_legs(perimeter_infos)` covers :1016-1143.
   - `async_setup` keeps everything else in place, in today's order: snapshot dir, legacy-key log, linker install and READY handler (:769-877), the :879 early return, the person and egress subscriptions (:892-935), frigate intake (:937-985), C3a (:990-1007), `await _async_load_agreement()`, then `_wire_vehicle_animal_legs`, the rescan, and the sweep.
   - The person and egress subscription calls (:904-935) move into a small sync `_subscribe_person_egress(perimeter_sensors, egress_sensors)`, which both setup and `rewire()` call.
   - "Byte-identical setup" means the ORDERED sequence of subscription calls and of INFO and WARN log lines matches the pre-cycle setup on the shared fixture.
2. **`_on_started` (R2-1):** after `_rescan_siblings(perimeter_infos)`, set `self._started_rescan_done = True` and `self._unsub_started = None`. Initialise the flag to False in `__init__`. Teardown is unchanged: it already guards on None.
3. `rewire()` does the following, in order. Steps (a) and (b) mutate nothing.
   - (a) Compute the new infos with `_resolve_camera_infos` for both keys.
   - (b) Compute the resolved perimeter sensors with a dry pass (or wire into scratch indexes). If there are none, raise. This is the :879 condition (R2-6). Raising here leaves the old wiring untouched, and the caller reloads.
   - (c) Capture `old_keys = set(self._person_legs_by_key)` and `old_dual = set(self._dual_role_cameras)` (R2-10).
   - (d) Unsubscribe `_unsub_perimeter` (including the rescan's late legs, :2884), `_unsub_egress`, `_unsub_vehicle` and `_unsub_animal`, and clear the lists.
   - (e) Reset `_sensor_to_camera`, `_sensor_platforms`, `_sensor_engine` and `_person_legs_by_key` to empty. `_build_zone_map` resets the zone maps itself (:4345-4347).
   - (f) Call `_wire_person_egress_legs(...)`, `_subscribe_person_egress(...)`, then `_wire_vehicle_animal_legs(...)`.
   - (g) Set `new_keys = set(self._person_legs_by_key)`.
   - The simplest way to satisfy (b) is to run (c) to (g) and keep a full copy of the old indexes and subscription lists to restore on raise. The builder must instead do the dry resolution first. Restoring unsubscribed listeners is not possible.
4. **C3a reconcile, per listener (R2-15):**
   - If dual-role is non-empty and `_unsub_egress_identity` is None, install it as setup does (:991-997). If `_fp_setup_ts` is None, stamp it. This opens the same 600 s arrival exclusion a fresh setup would.
   - If dual-role is non-empty, `_unsub_person_arrivals` is None, and `_tracked_person_slugs()` is non-empty, install it (:1003-1007).
   - If dual-role is empty, unsubscribe both listeners and set them to None.
   - Otherwise leave them alone. `_tracked_person_slugs` is a fresh read, so the arrival listener's person list does not depend on cameras.
5. **C4:** `self._perimeter_allowlist` is set by `_wire_person_egress_legs`. If a linker is present, call `linker.set_allowed_cameras(self._perimeter_allowlist)`. The allowlist is non-empty here, because (b) guarantees perimeter sensors. The READY handler reads `_perimeter_allowlist` live and needs no change.
6. **In-flight work.** Let `removed = old_keys - new_keys` (camera keys, not entity ids) and `lost_dual = (old_dual - self._dual_role_cameras)` mapped to their camera keys.
   - **Holds** (`_pending_holds`) and **scheduled dispatches** (`_pending_dispatches`) COMPLETE. The edge happened while the camera was configured, and silently dropping a security alert is the worse failure.
   - The builder enumerates every `_sensor_to_camera` / `_sensor_platforms` / `_sensor_engine` / `_dual_role_cameras` / `_zoned_cameras` read that is reachable after an await in `_async_handle_perimeter_trigger` and the hold paths. Each site must be shown to degrade, when its entry is missing, to the non-dual, unzoned, platform-`""` path without raising. Each site is listed with file:line in the build record.
   - **Identity follow-ups:** `_cancel_identity_followup(k, "camera_removed")` for k in `removed`, and `_cancel_identity_followup(k, "camera_not_dual_role")` for k in `lost_dual - removed`.
   - **D5 agreement** open samples finalise normally.
   - Retained keys keep all in-flight state, keyed by the same objects.

### 3.4 `CameraIntegrationManager.rediscover(room, egress, perimeter)`: sync (R2-4, R2-5)

- `resolve_camera_entity(camera_entity_id, *, cache=None)` and `resolve_configured_cameras(ids, *, cache=None)` take an optional cache that defaults to `self._resolved_devices`. Every existing caller is unchanged.
- `_discover_from_configured_cameras` and `_discover_full_scan` become `def _build_maps_configured(...) -> _Maps` and `def _build_maps_full_scan() -> _Maps`. `_Maps` holds `cameras_by_area`, `camera_by_entity`, `platform_by_entity` and `resolved_devices`, all built from fresh locals. The configured builder passes its fresh `resolved_devices` as `cache=`. The INFO log lines stay as they are.
- `async_discover` keeps its signature and contract: it builds the bundle and assigns it, so setup is byte-identical (log line included).
- `rediscover` uses the same branch selection (configured if any list is non-empty, else full scan), builds the bundle, then assigns all four attributes in one block. If the build raises, nothing is assigned and the caller falls back.
- Never temporarily swap `self._resolved_devices`, and never construct a new manager.

### 3.5 `EgressDirectionTracker._build_and_subscribe()`: sync (R2-7)

- Move the body of `async_init` (:972-1110) into it. `async_init` stays `async def` and calls it.
- At entry:
  - Iterate `_unsub` ONLY and call each remover; it already contains the peak-count unsubs (:1096).
  - Clear `_unsub` and `_peak_count_unsubs`, as teardown does at :2262-2268.
  - Reset `_egress_entities`, `_egress_count_sensors`, `_interior_entities` and `_count_sensor_to_stem` to empty. The fallback path never sets `_egress_count_sensors`, and both early returns (:1008, :1011) would otherwise leave stale lists.
- It keeps `_recent_egress_events`, `_recent_interior_events`, `_last_resolved` and `_peak_count_buffer`.
- The door-group maps are re-read by the existing `_load_door_config()` call: a fresh read, the same as setup.

### 3.6 `_wire_census_camera_triggers(hass)` (R2-8)

- At setup, store `_event_census_trigger` as `hass.data[DOMAIN]["census_event_trigger"]`, so the camera and Bermuda subscriptions share one debounce state.
- Move the camera-entity collection and subscription (:3080-3095) into the helper, which stores its unsub under `hass.data[DOMAIN]["unsub_census_camera_events"]`. On re-entry it calls and replaces the previous unsub. With no camera entities it stores None.
- The Bermuda subscription stays in `unsub_census_events`. Never index into that list.
- Setup order is unchanged: camera subscription first, then Bermuda.
- Unload (:5813) also pops and calls `unsub_census_camera_events`, and pops `census_event_trigger`.

### 3.7 `PresenceCoordinator.rewire_zone_cameras()`: sync (R2-2)

1. Compute `new_ids`: the person sensors `_discover_zone_cameras` would register, with opt-outs applied. Simplest: let discovery run, then diff.
2. For every tracker, for every eid in `tracker._camera_entity_ids - new_ids`:
   - discard it from `_camera_entity_ids`;
   - pop it from `_camera_occupied` and `_camera_last_seen`;
   - recompute `_has_camera_sensors = bool(_camera_entity_ids)`.

   This purge comes FIRST. Without it, a removed camera that read `on` at save time stays True forever in the zone-wide `any(_camera_occupied.values())` reads (presence.py:4519, :7708).
3. Call `_discover_zone_cameras()`. It already tears down `_camera_listener_unsub` (:5034-5046), re-registers and seeds.
4. Retained cameras keep their `_camera_occupied` / `_camera_last_seen` entries.

## 4. Knobs

| Knob | Rung | Default | Kill / why |
|---|---|---|---|
| `CAMERA_LIST_LIVE_REWIRE_ENABLED` | 1 | True | False: the two structural keys leave the allowlist and saves reload as today; a room-only save is signal-only as today. A fire-axe; changing it needs review. |
| `CAMERA_LIST_REWIRE_WARN_MS` | 1 | 500 | Observability only. 0 means always WARN. |
| `INTEGRATION_RELOAD_SUPPRESS_ENABLED` (existing) | 1 | True | False turns off every suppression, including this one. |

## 5. Deliverables and acceptance

**Test rules for this cycle (R2-5, R2-11):**
- The D1, D4, D5 and D7 tests build the production `CameraIntegrationManager`, `PersonCensus`, `EgressDirectionTracker`, `TransitValidator`, `PerimeterAlertManager` and `PresenceCoordinator`, and register them under the §3.2 keys. No `SimpleNamespace` or `MagicMock` stands in for these objects. That substitution is what hid LOCK-ENTRY-AREAS-WRONG-OBJECT-1.
- The cycle test modules run with `-W error::RuntimeWarning`, so an un-awaited coroutine fails the test.

### D1. Gate and orchestrator (§3.1, §3.2)
- **Verify:** a save that changes only `CONF_PERIMETER_CAMERAS` (non-empty to non-empty) after a REAL `async_setup` and a REAL `EVENT_HOMEASSISTANT_STARTED` does not reload the parent entry, and the verdict is `"live"`.
  - Discriminates against "reloaded anyway": `hass.config_entries.async_reload` is mocked and asserted not-called.
  - Discriminates against "P3 never true" (R2-1): the test does not assign `_unsub_started` or `_started_rescan_done` by hand.
- **Verify:** each precondition miss on a structural save means a reload is scheduled and the snapshot is reseeded. The misses: HA not running; rescan not yet run; `_active` False with a perimeter or egress change; camera_manager None.
- **Verify (R2-3):**
  - A room-only save on an install with NO perimeter cameras is `"live"` and does not reload.
  - A room-only save with a precondition miss is `"signal_only"`: no reload, the transit signal is dispatched, and the WARN is logged.
- **Verify:** an exception injected at the boundary of each of steps 1-6 means the fallback for that save happens, and no success INFO line is logged.
- **Verify:** with the flag False, a structural save reloads, and a `CONF_CAMERA_PERSON_ENTITIES`-only save is byte-identical to today (signal dispatched, orchestrator not called).
- **Verify:** a mixed save (a camera key plus a non-allowlisted key) reloads. A save changing all three camera keys calls the orchestrator exactly once.
- **Verify:** two back-to-back saves leave the state equal to the second save's options.
- **Test:**
  - `test_camera_list_live_after_real_ha_started`
  - `test_camera_list_save_no_reload`
  - `test_camera_list_precondition_misses_reload` (parametrised)
  - `test_room_camera_save_no_perimeter_install_no_reload`
  - `test_room_camera_save_precondition_miss_signal_only`
  - `test_camera_list_step_exception_fallback` (parametrised over steps 1-6, structural and room-only)
  - `test_camera_list_kill_switch_reload`
  - `test_room_camera_save_flag_off_byte_identical`
  - `test_camera_list_mixed_save_reload`
  - `test_camera_list_back_to_back_converges`
  - `test_orchestrator_is_sync` (`inspect.iscoroutinefunction` is False for the orchestrator, every rebuilder, and both `_build_maps_*` builders)
- **Mutation:**
  - delete the `_started_rescan_done = True` assignment, and `test_camera_list_live_after_real_ha_started` goes RED;
  - swap the step-4 and step-5 hass.data keys, and `test_egress_tracker_rebuild_adds_camera` goes RED.

### D2. Atomic rediscover (§3.4)
- **Verify:** after `rediscover`, the maps equal those from `async_discover` on a fresh manager with the same lists.
- **Verify:** a build that raises leaves all four maps identical (by `is`) to the pre-call objects, AND their contents unchanged, cache included.
- **Verify (R2-4):** a camera device that gains a person leg in the registry between setup and the save shows the new leg after `rediscover`.
- **Verify:** all lists empty switches to full-scan mode, as `async_discover` does.
- **Test:** `test_rediscover_equals_fresh_discover`, `test_rediscover_exception_keeps_old_maps`, `test_rediscover_rebuilds_device_cache`, `test_rediscover_empty_lists_full_scan`, `test_async_discover_setup_byte_identical`.
- **Mutation:**
  - assign the maps one at a time with the build interleaved, or clear before building: `test_rediscover_exception_keeps_old_maps` must go RED;
  - pass `self._resolved_devices` instead of the fresh cache: `test_rediscover_rebuilds_device_cache` must go RED.

### D3. Perimeter rewire (§3.3)
- **Verify parity:** for each config pair (old, new) in the matrix below, the state after `rewire()` is set-equal to a fresh `async_setup` with the new options. This covers the subscribed sets per kind, every C3 index, C3a per listener, and C4.

| Case | Old to new |
|---|---|
| add | P={a} to P={a,b} |
| remove | P={a,b} to P={a} |
| dual add | P={a}, E={} to P={a}, E={a} (`a` becomes dual-role: vehicle legs dropped, C3a installed) |
| dual remove | P={a}, E={a} to P={a}, E={} (C3a removed, vehicle legs back) |
| egress emptied | P={a}, E={b} to P={a}, E={} |
| zoned camera | `a` has zone sensors: zone legs replace the Frigate legs after the rewire |
| no tracked persons | dual add with no tracked persons: `_unsub_egress_identity` installed, `_unsub_person_arrivals` stays None |

- **Verify:** after 3 rewires, each item in INV (d) exists exactly once. Count via the `async_track_state_change_event`, `bus.async_listen` (or ingress `register_consumer`) and dispatcher mocks.
- **Verify:** a removed camera's legs are unsubscribed. A state edge on them calls no handler.
- **Verify:** `_person_legs_by_key` has no key for a removed camera, so the D5 and D10.5 liveness check does not count its legs.
- **Verify, held alert:** a D5 single-source hold is active on removed camera `b` when the rewire runs. The hold completes, the dispatch path finishes without raising, `_dispatch_in_flight` is released, and the alert dispatches with the gate decision computed before the rewire.
  - Discriminates against "dropped": an NM dispatch mock is called once.
- **Verify, D10.5 hold:** the same, on a dual-role camera that is removed from egress only. It completes. The camera is no longer dual-role, and the post-await `_is_dual_role_sensor` read returns False without raising.
- **Verify, follow-up (R2-10):** the fixture camera's entity id differs from its camera key (`camera.front_door_aerial_2` → key `front_door_aerial`).
  - A pending follow-up on removed key `b` is discharged with reason `camera_removed`, and no follow-up NM call happens.
  - A follow-up on a camera removed from egress only is discharged with reason `camera_not_dual_role`.
  - A follow-up on retained dual-role key `a` is the same object after the rewire and still fires.
- **Verify:** the cooldown for retained camera `a` survives the rewire. An edge within the cooldown after the rewire does not alert.
  - Discriminates against "rewire reset state".
- **Verify (R2-6):** a rewire whose perimeter cameras all fail to resolve raises BEFORE any mutation, in both cases: egress resolvable, and egress empty. Subscriptions, indexes and the linker allowlist are unchanged (same objects, same contents).
- **Verify (R2-15):** the first C3a install on a rewire stamps `_fp_setup_ts` only if it is None. A second dual add after a dual remove does not re-stamp it.
- **Verify:** `async_setup` is byte-identical: the ORDERED subscription calls and the ordered INFO and WARN log lines match the pre-cycle setup on the shared fixture, generated on the post-MQTT-direct base.
- **Test:**
  - `test_rewire_equals_fresh_setup` (parametrised over the matrix)
  - `test_rewire_no_listener_leak`
  - `test_rewire_removed_legs_unsubscribed`
  - `test_rewire_person_legs_by_key_exact`
  - `test_rewire_removed_camera_hold_completes`
  - `test_rewire_dual_role_removed_hold_completes`
  - `test_rewire_removed_followup_discharged`
  - `test_rewire_retained_cooldown_kept`
  - `test_rewire_unresolvable_perimeter_raises_untouched` (parametrised: egress resolvable / empty)
  - `test_rewire_fp_setup_ts_stamped_once`
  - `test_perimeter_setup_byte_identical`
- **Mutation, one site at a time, each must go RED:**
  - each of the four unsubscribe loops;
  - the `_person_legs_by_key` reset;
  - each C3a install and remove branch;
  - both follow-up discharge calls;
  - the unresolvable-perimeter raise;
  - moving the raise after the unsubscribe.

### D4. Egress tracker and transit rebuild (§3.5, step 5)
- **Verify:** add an egress camera. The tracker's `_egress_entities` includes it, and a state edge on it produces `ura_person_egress_event` through the existing direction logic.
  - Discriminates against F1: without the rebuild, no event fires.
  - Discriminates against a TV/tracker swap: TransitValidator never emits this event.
- **Verify:** remove an egress camera. Its tracker and transit subscriptions are gone.
- **Verify:** after the rebuild, `arrival_edges.door_entry_areas(hass.data[DOMAIN]["egress_tracker"], ...)` includes the added camera's area. This is the v5.107.6 reader.
- **Verify:** `_recent_*`, `_last_resolved` and `_peak_count_buffer` are kept across the rebuild.
- **Verify (R2-7):**
  - every peak-count remover is called exactly once per rebuild;
  - with the census path raising, the fallback path leaves `_egress_count_sensors` empty, not stale.
- **Verify:** transit subscriptions equal a fresh `_build_and_subscribe`, synchronously before the orchestrator returns, and a pending debounce timer is cancelled.
- **Test:**
  - `test_egress_tracker_rebuild_adds_camera`
  - `test_egress_tracker_rebuild_removes_camera`
  - `test_egress_tracker_rebuild_keeps_history`
  - `test_egress_tracker_rebuild_entry_areas_follow`
  - `test_egress_tracker_rebuild_no_double_unsub`
  - `test_egress_tracker_rebuild_fallback_resets_lists`
  - `test_transit_rebuild_direct_sync`
  - `test_egress_tracker_async_init_byte_identical`
- **Mutation:** skip step 4, and `test_egress_tracker_rebuild_adds_camera` must go RED.

### D5. Census camera triggers (§3.6)
- **Verify:** after adding a camera, a state edge on its person sensor triggers `async_update_census` (debounced as today). The Bermuda trigger stays registered exactly once.
- **Verify (R2-8):**
  - with NO cameras at setup, the first rewire installs the camera subscription and does not touch the Bermuda subscription;
  - a camera edge and a Bermuda edge inside one debounce window trigger one census.
- **Test:** `test_census_camera_triggers_rebuilt`, `test_census_bermuda_trigger_untouched`, `test_census_camera_triggers_rebuilt_no_cameras_at_setup`, `test_census_trigger_shares_debounce`.

### D7. Presence zone cameras (§3.7)
- **Verify:** add a room camera in a zoned room's area. The zone tracker registers its person sensor, and an `on` edge sets `_camera_occupied`.
- **Verify:** remove a camera while its person sensor reads `on`. After the rewire, no tracker holds it in `_camera_entity_ids` or `_camera_occupied`, and the zone-wide camera read is False when no other camera is on.
  - Discriminates against "re-ran discovery without purge": the zone stays camera-occupied.
- **Verify:** a camera in an opted-out room (`CONF_DISABLE_CAMERA_PRESENCE`) is not registered after the rewire, the same as at setup.
- **Verify:** with presence absent, step 6 is skipped and the verdict is still `"live"`.
- **Test:** `test_presence_zone_camera_added`, `test_presence_zone_camera_removed_while_on_not_latched`, `test_presence_zone_camera_opt_out_respected`, `test_presence_absent_step_skipped`.
- **Mutation:** drop the purge, and `test_presence_zone_camera_removed_while_on_not_latched` must go RED.

### D6. Comments and docs
Update the following:
- the comments at __init__.py:88-98, :7704-7709 and :7797-7803 (the "deliberately excluded" text);
- the audit's parked follow-up #1, marked done;
- IDENTITY_FUSION_CAMERAS_MANUAL.md: one line saying camera-list saves no longer reload;
- PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md: one line saying zone cameras follow camera-list saves (C7).

### Live (post-deploy, during awake hours, at the arc-end restart, plus one save)
1. An options save adding `camera.doorbell_lite` to egress, with the perimeter list unchanged and non-empty:
   - no `Setting up universal_room_automation` line, and no watchdog restart;
   - the orchestrator INFO line, verdict `live`, with elapsed ms below `CAMERA_LIST_REWIRE_WARN_MS`;
   - `PerimeterAlertManager: egress camera camera.doorbell_lite person-leg coverage` appears;
   - `EgressDirectionTracker initialized` appears with an egress count one higher;
   - `TransitValidator subscriptions built` appears with a count one leg higher.
   - Discriminates against "P3 dead": a reload would show the setup line instead.
2. Room occupancy sensors for areas with cameras keep their state across the save (recorder: no `unavailable` or flip at the save timestamp).
3. The next real door crossing at that camera produces a `ura_person_egress_event` row or log line.
4. Remove it again with a save: the counts return to the pre-save values.

## 6. Non-goals
- No change to perimeter alert logic, gates, severities, cooldowns or the D5 agreement store.
- No live path for perimeter transitions to or from an empty list. Those reload.
- No live path for structural saves during boot (before the rescan). Those reload. A room-only save during boot stays signal-only, as today.
- No new signal. No change to `_apply_in_place` or the CM branch.
- No change to `CONF_PERIMETER_ZONE_SENSORS` (it stays structural and reloads). A later card can reuse `rewire()`.
- No change to the Frigate MQTT ingress. After PERIMETER-FRIGATE-MQTT-DIRECT-1 lands, `rewire()` must not touch the perimeter's `register_consumer` registration.
- No fix for the pre-existing overwrite of `unsub_census_events` at __init__.py:3106. It drops the HA_STARTED BLE-refresh unsub, which `entry.async_on_unload` still covers.

## 7. Tier

**Tier 3.** It changes a shared primitive (the camera map, read on the room-occupancy path by sensor.py and coordinator.py, and cached by presence) and adds a reconfigure path to the perimeter security alerting. The failure mode is one missed consumer (Bug Class #53). The reload path carries watchdog-outage history. Reviewer D's target is INV-CAMLIST-LIVE (a)-(d) across:
- the D3 matrix;
- the precondition and fallback table (structural vs room-only, `_active` False);
- in-flight work;
- the C7 latch.

## 8. Findings outside this cycle
- **LOCK-ENTRY-AREAS-WRONG-OBJECT-1:** SHIPPED in v5.107.6 (b70e3a2f). The readers now use `egress_tracker`, and D4 checks they follow a rebuild.
- **QUALITY_CONTEXT candidates:**
  - "conditional-install asymmetry" (review 1). A listener installed only under a setup-time condition must be reconciled on reconfigure.
  - "fired-once handle never cleared" (review 2, R2-1). An `async_listen_once` handle kept after it fires reads as "pending" forever.

## 9. Plan completion tracking
No code yet. Both plan reviews are done (review 1 and review 2, both FIX-PLAN-FIRST, both applied). Next: wait for PERIMETER-FRIGATE-MQTT-DIRECT-1 to merge, then build with `ura-super-builder`.
