# PLANNING: camera-list options save without a parent reload (rev 1)

- **Card:** CAMERA-LIST-LIVE-REWIRE-1. Extracted from `PLANNING_perimeter_fp_build_2026_11.md` §D11 rev 2, with the fixes from `docs/reviews/code-review/d11_camera_list_plan_review_1.md`.
- **Tier:** 3. It needs two plan reviews: (1) completeness, done (FIX-PLAN-FIRST, applied here); (2) adversarial build-prediction, owed before build. The build gets four framing-disjoint code reviews (A, B, C mutation, D adversarial completeness), the orchestrator's independent re-grep plus a mutation re-run, and an operator checkpoint before deploy.
- **Base:** develop @ `b0ed5193` (v5.107.5). Line anchors are from that tree.
- **Branch:** its own branch. It does not block anything else.

## 0. Institutional context verified

**Prior art (REUSED):**

| Piece | Verdict | Where |
|---|---|---|
| Reload-suppress branch for the integration entry | REUSED | `__init__.py:8830-8886`; allowlist `INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS` at :7720; kill switch `INTEGRATION_RELOAD_SUPPRESS_ENABLED` at :7816 |
| Per-key discharge table | REUSED, with no new row | `_INTEGRATION_KEY_SIGNAL_TABLE` at :7826. The orchestrator is a direct call, not a signal (F8). |
| Fallback parent reload | REUSED | the fall-through at :8884-8900 (reseed the snapshot, then an untracked `async_reload`) |
| Transit subscription rebuild | REUSED | `TransitValidator._build_and_subscribe()` at transit_validator.py:421, called directly; `_rebuild_timer_unsub` cancelled |
| Camera discovery | REUSED body | `CameraIntegrationManager._discover_from_configured_cameras` / `_discover_full_scan` (camera_census.py:1072-1200) |
| Perimeter wiring | REUSED body | `PerimeterAlertManager.async_setup` :508-1143, split into a sync helper |
| Linker allowlist | REUSED | `ExteriorTrackLinker.set_allowed_cameras` (exterior_track_linker.py:363) |
| Follow-up discharge | REUSED | `_cancel_identity_followup` (perimeter_alert.py:5161) |
| Egress tracker teardown shape | REUSED | `EgressDirectionTracker.async_teardown` (transit_validator.py:2260) |

**New:**
- `CameraIntegrationManager.rediscover()` (sync). No equivalent exists; `async_discover` clears in place.
- `PerimeterAlertManager.rewire()` (sync). There is no reconfigure path today.
- `EgressDirectionTracker._build_and_subscribe()` (sync, extracted from `async_init`).
- `_wire_census_camera_triggers()`, extracted from __init__.py:3080-3093.
- `_camera_lists_changed(hass, entry) -> bool`, the orchestrator. There is no equivalent orchestrator.
- `SIGNAL_CAMERA_LIST_CHANGED` is NOT added; grep finds no hits, and none is needed.

**Read:** AUDIT_integration_options_reload_classification.md §70-150 (this card is its parked follow-up #1, triggered by operator request; follow-up #2 does not fire); the RELOAD-WATCHDOG-HAZARD comments at __init__.py:7699-7832; DEVICE_TREE.md (no per-camera devices or entities, so no registry surgery); IDENTITY_FUSION_CAMERAS_MANUAL.md (egress roles); PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md:79 (lock entry areas; contradicted by code, see §8). The build reviewers must read the presence doc and SENSOR_FLEET_CLASSES.md in full. Memory read: `feedback_parent_entry_reload_watchdog_hazard`, `feedback_suppression_needs_discharge`.

**Config-first:** no setting avoids the reload. The reload path works. This cycle exists to remove the reload's watchdog risk on an operator-requested save.

**Marginal benefit:** camera-list edits are rare. The win is one fewer parent reload per edit, plus the removal of the watchdog-stall exposure on a security-relevant save. F7 adds a real correctness win: room-camera saves stop leaving the occupancy map stale. The marginal risk is a new writer to a shared primitive (the camera map) and a reconfigure path in perimeter. That is why every edge case below falls back to the existing reload instead of growing handling.

## 1. Consumer enumeration (the surface)

This table is the result of an independent re-grep of `CONF_PERIMETER_CAMERAS|CONF_EGRESS_CAMERAS|CONF_CAMERA_PERSON_ENTITIES` plus every reader of the derived maps.

| # | Consumer | Anchor | Action in this cycle |
|---|---|---|---|
| C1 | Camera maps `_cameras_by_area`, `_camera_by_entity`, `_platform_by_entity`, `_resolved_devices` | camera_census.py:1058-1061 | `rediscover()`: build into locals, swap all four |
| C1r | Readers: sensor.py:2809, presence.py:4979/5006/5014, coordinator.py:4095, camera_census.py:1241/2001/2173/2286/2805/5854 | — | none (they read C1 live) |
| C2 | Enhanced-census camera triggers (`unsub_census_events[0]`) | __init__.py:3080-3093 | rebuild the camera-trigger subscription only; the Bermuda trigger is untouched |
| C3 | Perimeter subscriptions plus indexes (`_sensor_to_camera`, `_sensor_platforms`, `_sensor_engine`, `_person_legs_by_key`, `_zone_map`, `_zoned_cameras`, `_zone_key_overrides`, `_dual_role_cameras`, `_perimeter_allowlist`) | perimeter_alert.py:508-1143 | `rewire()`: exact rebuild |
| C3a | Dual-role listeners (`_unsub_egress_identity`, `_unsub_person_arrivals`) | :990-1007 | reconcile by set transition |
| C3b | HA_STARTED rescan closure | :1159-1165 | precondition: already fired (else reload) |
| C3c | In-flight: `_pending_holds`, `_pending_dispatches`, `_pending_followups`, agreement samples | :4617, :1944, :5161, :4785 | see §3.3 |
| C4 | Linker allowlist | perimeter_alert.py:763-787 → exterior_track_linker.py:363 | installed by `rewire()`; an empty result means reload |
| C5 | TransitValidator subscriptions | transit_validator.py:421-504 | direct `_build_and_subscribe()` |
| C6 | EgressDirectionTracker lists and subscriptions | transit_validator.py:965-1110 | new sync `_build_and_subscribe()` |
| — | Fresh reads, no action: optimization.py:2648/3298; camera_census.py:1676, :2238; perimeter `_resolve_camera_infos` :5340; enrichment allowlist (a separate key); `_unresolved_by_scope` (self-correcting); D5 agreement store (a restart reloads it too); lock-regime person listener (keyed on persons) | | |
| — | `door_entry_areas` / `_near_areas` read `hass.data["transit_validator"]`. That is the wrong object, so the result is always empty or narrow (§8, carded). Live read, so no action here. | | |

## 2. Falsifiable invariant: INV-CAMLIST-LIVE

> After a camera-list save, every consumer C1-C6 reflects the new list within one rebuild, no consumer ever observes an empty or half-built camera map, and on any error the system falls back to today's full reload.

**Operational form (what reviewer D tries to break):**

- **(a) Parity.** When `_camera_lists_changed` returns True, the structural state of C1-C6 is set-equal to what a fresh setup produces with the same options and the same entity registry:
  - the C1 maps;
  - the C2 entity set;
  - the C3 subscribed entity sets per kind (person, egress, vehicle, animal) and every C3 index;
  - whether each C3a listener is present;
  - C4 `_allowed_cameras`;
  - C5 and C6 subscribed sets and entity lists.
- **(b) No observation of intermediate state.** `_camera_lists_changed` and everything it calls are synchronous: no `await` and no coroutine. There is therefore no loop turn between the first mutation and the last swap. Within C1, the four maps are assigned in one block after the locals are fully built.
- **(c) Fail to reload.** If any precondition is missed or anything raises, the function returns False. The listener then reseeds the snapshot and schedules the parent reload. "Success" is never logged for a partial run.
- **(d) Single install.** After N rewires, each listener family has exactly one registration per entity, and each of the following exists exactly once: the frigate-event intake registration, `_unsub_linker_ready`, `_unsub_snapshot_sweep`, the agreement timer, and each C3a listener when the dual-role set is non-empty.

**Divergence ledger.** These differ from a restart on purpose. Parity is NOT claimed for:
- `_last_alert` / `_last_vehicle_alert` cooldowns, `_recent_*` histories and the burst decisions;
- the Frigate id and event caches, and `_edge_captures`;
- the agreement tracker in memory;
- `_setup_time` (no new boot-settle window) and `_fp_setup_ts` (the boot exclusion is not re-armed);
- `_person_arrivals`;
- EgressDirectionTracker `_recent_*` and `_last_resolved`;
- in-flight holds and scheduled dispatches (§3.3).

Keeping this state is the point: a restart drops cooldowns and can double-alert.

## 3. Design

### 3.1 Gate (listener branch, __init__.py:8846)

```
CAMERA_LIST_KEYS = {CONF_PERIMETER_CAMERAS, CONF_EGRESS_CAMERAS, CONF_CAMERA_PERSON_ENTITIES}
```

1. `CONF_PERIMETER_CAMERAS` and `CONF_EGRESS_CAMERAS` join the allowlist only while `CAMERA_LIST_LIVE_REWIRE_ENABLED` is True. Implement this as a computed frozenset, so that False restores the exact pre-cycle allowlist. `CONF_CAMERA_PERSON_ENTITIES` stays allowlisted either way.
2. After the subset test passes:
   - If `changed_keys & CAMERA_LIST_KEYS` and the flag is True, call `ok = _camera_lists_changed(hass, entry)` BEFORE `_dispatch_integration_key_signals`.
   - If `ok` is False, reseed the snapshot to `dict(entry.options)` and fall through to the existing reload. Do NOT return.
   - If `ok` is True, continue with the existing dispatch and snapshot advance. The `CONF_CAMERA_PERSON_ENTITIES` transit-signal row stays; it causes one extra debounced rebuild of C5 5 s later, which is idempotent.
3. When the flag is False and only `CONF_CAMERA_PERSON_ENTITIES` changed, behaviour is byte-identical to today (signal only).

### 3.2 Orchestrator `_camera_lists_changed(hass, entry) -> bool`: sync, fixed order

The orchestrator reads the CURRENT `{**entry.data, **entry.options}`, not the diff, so back-to-back saves converge on the last one. The whole function body runs inside `try/except Exception → log WARNING, return False`.

**Preconditions.** Any miss means `return False`:
- P1. `hass.state is CoreState.running`.
- P2. `camera_manager` is present.
- P3. If `perimeter_alert_manager` is present: `_active` is True and `_unsub_started` is None (the HA_STARTED rescan has already fired).
- P4. Old and new `CONF_PERIMETER_CAMERAS` are either both empty or both non-empty. Old comes from the manager's last-wired list, kept as `_wired_perimeter_cameras`. When both are empty, skip the perimeter step.

**Steps, in this order:**
1. `camera_manager.rediscover(room, egress, perimeter)`. This must run first, because the perimeter (`_resolve_camera_infos` → `resolve_camera_entity`), transit and egress tracker resolve through the manager.
2. `_wire_census_camera_triggers(hass)`. Only when enhanced census is enabled and `unsub_census_events` exists.
3. `perimeter.rewire()`, if the manager exists.
4. `egress_tracker._build_and_subscribe()`, if the tracker exists.
5. Transit validator: cancel `_rebuild_timer_unsub`, then call `tv._build_and_subscribe()`, if the validator exists.
6. Log INFO with the elapsed ms and per-consumer counts. Log WARN if the elapsed time is ≥ `CAMERA_LIST_REWIRE_WARN_MS`. Return True.

There is no lock: a synchronous function cannot interleave.

### 3.3 `PerimeterAlertManager.rewire()`: sync

1. Split :508-1143 into `_wire_legs(perimeter_infos, egress_infos)`. It is synchronous and covers: the zone map, `_wire_camera` for both roles, computing the allowlist, the person and egress subscriptions, and the vehicle and animal legs and subscriptions.
   - `async_setup` calls it in the same order as today. The only exceptions are the frigate-event intake, the linker READY handler, the dual-role listeners, the agreement load, the rescan and the sweep. Those stay in `async_setup`, and their registration order relative to each other is unchanged.
   - Setup must be byte-identical: same subscriptions, same log lines. The test diffs a pre-cycle and post-cycle setup snapshot.
2. `rewire()` does the following, in order:
   - compute the new infos;
   - record `old_keys` (the camera keys currently wired);
   - unsubscribe `_unsub_perimeter` (including the rescan's late legs), `_unsub_egress`, `_unsub_vehicle` and `_unsub_animal`;
   - reset the C3 indexes to empty (`_build_zone_map` resets the zone maps itself, :4344-4346);
   - call `_wire_legs(...)`;
   - recompute `_dual_role_cameras`.
3. **C3a reconcile:**
   - If the dual-role set is non-empty and the listeners are absent, install them as setup does (:990-1007) and stamp `_fp_setup_ts` only if it is unset.
   - If the set is empty and the listeners are present, unsubscribe and set them to None.
   - Otherwise leave them alone. `_tracked_person_slugs` is a fresh read, so the arrival listener's person list does not depend on cameras.
4. **C4:** if the new allowlist is empty, raise (the caller reloads). Otherwise call `linker.set_allowed_cameras(new)` when the linker is present.
5. **In-flight work** for `removed = old_keys - new_keys`:
   - **Holds** (`_pending_holds`) and **scheduled dispatches** (`_pending_dispatches`) COMPLETE. The edge happened while the camera was configured, and silently dropping a security alert is the worse failure.
   - The builder enumerates every `_sensor_to_camera` / `_sensor_platforms` / `_sensor_engine` / `_dual_role_cameras` / `_zoned_cameras` read that is reachable after an await in `_async_handle_perimeter_trigger` and the hold paths, and proves that a missing entry degrades to the non-dual, unzoned, platform-`""` path without raising. Each site is listed with file:line in the build record.
   - **Identity follow-ups** for removed keys: `_cancel_identity_followup(k, "camera_removed")`.
   - **D5 agreement** open samples finalise normally.
   - Retained keys keep all in-flight state, keyed by the same objects.
6. Store `_wired_perimeter_cameras = list(new perimeter config)`.

### 3.4 `CameraIntegrationManager.rediscover(room, egress, perimeter)`: sync

- Same branch selection as `async_discover`: configured mode if any list is non-empty, else full scan.
- Refactor the two discover bodies so they build into a local `_Maps` bundle and return it. `async_discover` keeps its contract (clear, then build into self) by assigning the returned bundle, so setup is byte-identical.
- `rediscover` builds the bundle first, then assigns the four attributes in one block.
- If the build raises, nothing is assigned. The old maps stay, and the caller reloads.

### 3.5 `EgressDirectionTracker._build_and_subscribe()`: sync

- Move the body of `async_init` (:965-1110) into it.
- At entry it unsubscribes `_unsub` and `_peak_count_unsubs`, then clears `_count_sensor_to_stem` and `_peak_count_buffer` (as teardown does at :2262-2270).
- It keeps `_recent_egress_events`, `_recent_interior_events`, `_last_resolved` and the door-group maps.
- `async_init` calls it.

### 3.6 `_wire_census_camera_triggers(hass)`

- Extract __init__.py:3080-3093 into this helper. It stores the camera-trigger unsub under `hass.data[DOMAIN]["unsub_census_camera_events"]`, and on re-entry it unsubscribes the previous one.
- The Bermuda-count trigger stays in `unsub_census_events`.
- Unload pops and calls both.

## 4. Knobs

| Knob | Rung | Default | Kill / why |
|---|---|---|---|
| `CAMERA_LIST_LIVE_REWIRE_ENABLED` | 1 | True | False: the two keys leave the allowlist and saves reload as they do today. A fire-axe; changing it needs review. |
| `CAMERA_LIST_REWIRE_WARN_MS` | 1 | 500 | Observability only. 0 means always WARN. |
| `INTEGRATION_RELOAD_SUPPRESS_ENABLED` (existing) | 1 | True | False turns off every suppression, including this one. |

## 5. Deliverables and acceptance

### D1. Gate and orchestrator (§3.1, §3.2)
- **Verify:** a save that changes only `CONF_PERIMETER_CAMERAS` (non-empty to non-empty) does not reload the parent entry, and `_camera_lists_changed` returns True.
  - Discriminates against "reloaded anyway": `hass.config_entries.async_reload` must not be called. It is mocked and asserted not-called.
- **Verify:** for each precondition miss P1-P4 (HA not running; `_unsub_started` still armed; perimeter `_active` False; camera_manager None; perimeter list empty to non-empty and non-empty to empty), the result is False, the reload is scheduled, and the snapshot is reseeded.
- **Verify:** an exception injected at each of steps 1-5 means the reload is scheduled and no success INFO line is logged.
- **Verify:** with the flag False, a camera-list save reloads. A `CONF_CAMERA_PERSON_ENTITIES`-only save is byte-identical to today: the signal is dispatched, and the orchestrator is NOT called.
- **Verify:** a mixed save (a camera key plus a non-allowlisted key) reloads. A save that changes all three camera keys calls the orchestrator exactly once.
- **Verify:** two back-to-back saves leave the state equal to the second save's options.
- **Test:**
  - `test_camera_list_save_no_reload`
  - `test_camera_list_precondition_misses_reload` (parametrised over P1-P4)
  - `test_camera_list_step_exception_reload` (parametrised over steps 1-5)
  - `test_camera_list_kill_switch_reload`
  - `test_room_camera_save_flag_off_byte_identical`
  - `test_camera_list_mixed_save_reload`
  - `test_camera_list_back_to_back_converges`
  - `test_orchestrator_is_sync` (`inspect.iscoroutinefunction` is False for the orchestrator and all four rebuilders)

### D2. Atomic rediscover (§3.4)
- **Verify:** after `rediscover`, the maps equal those from `async_discover` on a fresh manager with the same lists.
- **Verify:** a build that raises leaves all four maps identical (by `is`) to the pre-call objects.
- **Verify:** all lists empty switches to full-scan mode, as `async_discover` does.
- **Test:** `test_rediscover_equals_fresh_discover`, `test_rediscover_exception_keeps_old_maps`, `test_rediscover_empty_lists_full_scan`, `test_async_discover_setup_byte_identical`.
- **Mutation:** assign the maps one at a time with the build interleaved, or clear before building. `test_rediscover_exception_keeps_old_maps` must go RED.

### D3. Perimeter rewire (§3.3)
- **Verify parity:** for each config pair (old, new) in the matrix below, the state after `rewire()` is set-equal to a fresh `async_setup` with the new options. This covers the subscribed sets per kind and every C3 index, C3a presence and C4.

| Case | Old to new |
|---|---|
| add | P={a} to P={a,b} |
| remove | P={a,b} to P={a} |
| dual add | P={a}, E={} to P={a}, E={a} (`a` becomes dual-role: vehicle legs dropped, C3a installed) |
| dual remove | P={a}, E={a} to P={a}, E={} (C3a removed, vehicle legs back) |
| egress emptied | P={a}, E={b} to P={a}, E={} |
| zoned camera | `a` has zone sensors: zone legs replace the Frigate legs after the rewire |

- **Verify:** after 3 rewires, each of the frigate-event intake registration, `_unsub_linker_ready`, `_unsub_snapshot_sweep`, `_unsub_agreement_timer` and the C3a listeners exists exactly once. Count via the `async_track_state_change_event` and `bus.async_listen` mocks.
- **Verify:** a removed camera's legs are unsubscribed. A state edge on them calls no handler.
- **Verify:** `_person_legs_by_key` has no key for a removed camera, so the D5 and D10.5 liveness check does not count its legs.
- **Verify, held alert:** a D5 single-source hold is active on removed camera `b` when the rewire runs. The hold completes, the dispatch path finishes without raising, `_dispatch_in_flight` is released, and the alert dispatches with the gate decision computed before the rewire. Discriminates against "dropped": an NM dispatch mock is called once.
- **Verify, D10.5 hold:** the same, on a dual-role camera that is removed from egress only. It completes. The camera is no longer dual-role, and the post-await `_is_dual_role_sensor` read returns False without raising.
- **Verify, follow-up:** a pending identity follow-up on removed key `b` is discharged with reason `camera_removed`, and no follow-up NM call happens. A follow-up on retained key `a` is the same object after the rewire and still fires.
- **Verify:** the cooldown for retained camera `a` survives the rewire. An edge within the cooldown after the rewire does not alert. Discriminates against "rewire reset state".
- **Verify:** a rewire whose allowlist resolves empty (every perimeter camera unresolvable) raises, so the caller reloads. The linker allowlist is unchanged.
- **Verify:** `async_setup` is byte-identical: the subscriptions and the INFO and WARN log lines match the pre-cycle setup on the shared fixture.
- **Test:**
  - `test_rewire_equals_fresh_setup` (parametrised over the matrix)
  - `test_rewire_no_listener_leak`
  - `test_rewire_removed_legs_unsubscribed`
  - `test_rewire_person_legs_by_key_exact`
  - `test_rewire_removed_camera_hold_completes`
  - `test_rewire_dual_role_removed_hold_completes`
  - `test_rewire_removed_followup_discharged`
  - `test_rewire_retained_cooldown_kept`
  - `test_rewire_empty_allowlist_raises`
  - `test_perimeter_setup_byte_identical`
- **Mutation, one site at a time, each must go RED:**
  - each of the four unsubscribe loops;
  - the `_person_legs_by_key` reset;
  - the C3a install and remove branches;
  - the follow-up discharge;
  - the empty-allowlist raise.

### D4. Egress tracker and transit rebuild (§3.5, step 5)
- **Verify:** add an egress camera. The tracker's `_egress_entities` includes it, and a state edge on it produces `ura_person_egress_event` through the existing direction logic. Discriminates against F1: without the rebuild, no event fires.
- **Verify:** remove an egress camera. Its tracker and transit subscriptions are gone.
- **Verify:** `_recent_*` and `_last_resolved` are kept across the rebuild.
- **Verify:** transit subscriptions equal a fresh `_build_and_subscribe`, synchronously before the orchestrator returns, and a pending debounce timer is cancelled.
- **Test:** `test_egress_tracker_rebuild_adds_camera`, `test_egress_tracker_rebuild_removes_camera`, `test_egress_tracker_rebuild_keeps_history`, `test_transit_rebuild_direct_sync`, `test_egress_tracker_async_init_byte_identical`.
- **Mutation:** skip step 4; `test_egress_tracker_rebuild_adds_camera` must go RED.

### D5. Census camera triggers (§3.6)
- **Verify:** after adding a camera, a state edge on its person sensor triggers `async_update_census` (debounced as today). The Bermuda trigger stays registered exactly once.
- **Test:** `test_census_camera_triggers_rebuilt`, `test_census_bermuda_trigger_untouched`.

### D6. Comments and docs
Update the following:
- the comments at __init__.py:88-98, :7704-7709 and :7797-7803 (the "deliberately excluded" text);
- the audit's parked follow-up #1, marked done;
- IDENTITY_FUSION_CAMERAS_MANUAL.md: one line saying camera-list saves no longer reload.

### Live (post-deploy, during awake hours, at the arc-end restart, plus one save)
1. Options save adding `camera.doorbell_lite` to egress, with the perimeter list unchanged and non-empty:
   - no `Setting up universal_room_automation` line, and no watchdog restart;
   - the orchestrator INFO line with elapsed ms below `CAMERA_LIST_REWIRE_WARN_MS`;
   - `PerimeterAlertManager: egress camera camera.doorbell_lite person-leg coverage` appears;
   - `TransitValidator subscriptions built` appears with a count one leg higher.
2. Room occupancy sensors for areas with cameras keep their state across the save (recorder: no `unavailable` or flip at the save timestamp).
3. The next real door crossing at that camera produces a `ura_person_egress_event` row or log line.
4. Remove it again with a save: the counts return to the pre-save values.

## 6. Non-goals
- No change to perimeter alert logic, gates, severities, cooldowns or the D5 agreement store.
- No live path for transitions to or from an empty perimeter list. Those reload.
- No live path during boot. A save before HA_STARTED reloads.
- No new signal. No change to `_apply_in_place` or the CM branch.
- No change to `CONF_PERIMETER_ZONE_SENSORS` (it stays structural and reloads). A later card can reuse `rewire()`.
- No fix for the `door_entry_areas` wrong-object defect (§8, its own card).
- No change to the Frigate MQTT ingress. If PERIMETER-FRIGATE-MQTT-DIRECT-1 lands first, "frigate-event intake registration" in D3 means its consumer registration, and `rewire()` must not touch it.

## 7. Tier

**Tier 3.** It changes a shared primitive (the camera map, read on the room-occupancy path by sensor.py, presence.py and coordinator.py) and adds a reconfigure path to the perimeter security alerting. The failure mode is one missed consumer (Bug Class #53). The reload path carries watchdog-outage history. Reviewer D's target is INV-CAMLIST-LIVE (a)-(d) across the D3 matrix, the precondition boundary (P1-P4) and in-flight work.

## 8. Findings outside this cycle
- **LOCK-ENTRY-AREAS-WRONG-OBJECT-1 (new card, HIGH, fail-safe).** `arrival_edges.door_entry_areas` (security_lock_regime.py:997) and perimeter `_near_areas` (:5062-5066) read `hass.data["transit_validator"]` (a `TransitValidator`). The attributes they need live on `EgressDirectionTracker` (`hass.data["egress_tracker"]`; transit_validator.py:943, :955, :1178).
  - Result: lock-regime entry areas are always empty, so a face never releases through Bermuda. Perimeter near-areas are only the camera's own area.
  - The unit test uses a `SimpleNamespace` and hides it.
  - PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md:79 is corrected in the same commit as this plan.
- **QUALITY_CONTEXT candidate:** "conditional-install asymmetry". A listener installed only under a setup-time condition must be reconciled on reconfigure (F2, F5).

## 9. Plan completion tracking
This cycle has no code yet. Next step: plan review 2 (adversarial build-prediction), then fixes, then build by `ura-super-builder`.
