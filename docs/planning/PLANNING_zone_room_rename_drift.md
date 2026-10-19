# PLANNING — Live room rename re-keys the zone tiers (ZONE-ROOM-NAME-DRIFT-1)

**Rev 1** (2026-10-19, ura-planner). Card: `ZONE-ROOM-NAME-DRIFT-1` (`docs/planning/kanban.data.yaml:32435`).
**Tier:** 2, operator-standing elevation to the 3-framing build review (presence ↔ house-state ↔ HVAC ripple). One adversarial plan review before build. See §8.
**Parent / prior art:** `PLANNING_room_rename_writethrough.md` (ROOM-NAME-DESYNC-1, shipped), `house_state_rev32_review_D.md` D-M2, `PLANNING_house_state_sleep_mask_ble_memory_observability.md` R1-F11.

**Mandatory reading done, completely:** `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`, `docs/architecture/SENSOR_FLEET_CLASSES.md`, `docs/reviews/URA_ARCHITECTURE_MAP.md`, and (because §2 found an HVAC site) `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md`. No §10 ledger claim is re-asserted. Code read on `develop` @ `aebe0e496` (v5.103.74).

---

## 0. The problem in one paragraph

A room rename in the options flow writes the new name to `entry.data` and `entry.options` in one call (`config_flow.py:12335-12350`) and reloads ONLY the room entry. The presence coordinator lives on the parent entry and builds its name-keyed zone maps once, in `_discover_zones` (`presence.py:2913`, map at `:3490-3494`). After the rename the zone tracker still lists the old name. The substrate refresh that the room reload triggers re-keys its buckets to the new name (`occupancy_substrate.py:497-503` reclassify diff, step-7 edges `:586-608`), so the old name's kinds are released and the new name's edges are dropped as "unknown room" (`presence.py:3664-3671`). The room stops counting for its zone until HA restarts. At night, with `ZONE_OCCUPANCY_PER_ENTITY_ENABLED` on, a sleeper in that room can be sent AWAY by nobody-home (review D-M2 repro). The overnight pass also found the same drift in the HVAC zone list and the person-coordinator area map (§2).

**Correction to prior art (record, do not re-assert):** `PLANNING_room_rename_writethrough.md:33` (I1) claims `ZonePresenceTracker.room_names` and `_room_to_zone` agree on the new name "within a single reload cycle". That is false for the presence tier: a room rename reloads only the room entry, and nothing re-runs `_discover_zones`. A naive re-run would not fix it either: `_discover_zones` skips a zone that already has a tracker (`presence.py:3439` `if zone_name in self._zone_trackers: continue`). The builder adds this to PRESENCE_ARCHITECTURE_STATE_OF_PLAY §10 in the ship commit.

---

## 1. Institutional context verified

### 1.1 Prior-art scan: REUSE-or-BUILD per piece

| Piece the fix needs | Verdict | Evidence |
|---|---|---|
| A signal fired when a room entry reloads or is renamed | **REUSE** `SIGNAL_ROOM_ENTRY_LIFECYCLE` (`signals.py:204`), payload `(entry_id, room_name, action)`. It fires `"unloaded"` (`__init__.py:6179-6186`), `"loaded"` (`__init__.py:5631-5637`), `"options_updated"` on a suppressed write (`__init__.py:8673-8680`) and `"removed"` (`__init__.py:5736-5743`). `room_name` is read from `entry.data`, which the rename has already rewritten, so **the FIRST event after a rename (`"unloaded"`) already carries the NEW name.** | read in full |
| A presence subscriber to that signal | **REUSE + EXTEND** `PresenceCoordinator._on_room_entry_lifecycle` (`presence.py:3679-3725`; subscribed `:2988-2994`). Today it only schedules `substrate.refresh_subscriptions()`. The re-key goes here, synchronously, BEFORE the refresh task is scheduled. | read |
| An HVAC subscriber to that signal | **REUSE + EXTEND** `HVACCoordinator._on_room_lifecycle` (`hvac.py:5441-5449`). Today it only attaches or releases the fast-path listener, keyed by entry_id. | read |
| `SIGNAL_ZM_ZONES_UPDATED` pattern | **NOT reused for this.** `_handle_zm_zones_updated` (`presence.py:3352-3371`) re-runs only `_prune_stale_zone_trackers`. A room rename does not change the ZM entry (zone_rooms are entry ids), so this signal never fires on a rename. Same parent-does-not-reload shape, so the fix follows its precedent: a targeted handler, not a reload. | read |
| Substrate rebuild hook | **REUSE unchanged.** `OccupancySubstrate.refresh_subscriptions` (`occupancy_substrate.py:420-620`) already re-keys its buckets to the new name, releases the old name (D4c.2 walk `:589-592`) and emits True edges for the new name. Nothing changes in the substrate. | read |
| CM reload-suppression primitive | **No interaction.** `_ROOM_SUPPRESS_KEYS` (`__init__.py:8474`) does not contain `CONF_ROOM_NAME` (prior plan §2, re-confirmed by the suppress branch `:8657`), so a rename always reloads the room entry and fires `unloaded` then `loaded`. A rename never reaches the `options_updated` branch. CM reload suppression (memory `project_cm_reload_suppression_cycle_stack`) governs the CM parent entry, which a room rename never touches. The handler must still be correct on `options_updated` (no-op unless the name changed). | read |
| An entry_id → room-name map in presence | **BUILD (small).** None exists. `_discover_zones` resolves ZM entry ids to names (`presence.py:3446-3452`) and throws the ids away. New `self._room_name_by_entry: Dict[str, str]`, filled at that resolve step and in `_build_room_area_map` (`:3187-3221`), which walks every room entry. | grep `entry_id.*room_name\|room_name_by_entry` on presence.py: no hit |
| An entry_id → room-name map in HVAC | **BUILD (promote a local).** `entry_id_to_room_name` already exists as a local in `ZoneManager.async_discover_zones` (`hvac_zones.py:462-467`); keep it on `self`. | read |
| A "rename one room in place" helper | **BUILD.** grep `def .*rename\|def .*rekey` over the integration: no hit. | grep |
| Person-coordinator map invalidation | **REUSE.** `_build_scanner_room_map` (`person_coordinator.py:928`) rebuilds fully when `_scanner_map_entry_ids` differs (`:945`). Clearing that field forces a full rebuild on the next call. | read |
| Kill switch constant | **BUILD (rung 1)**, pattern `ZONE_OCCUPANCY_PER_ENTITY_ENABLED` (`const.py:691`, attribute-read rule). grep `RENAME\|REKEY` in const.py: no hit. | grep |

### 1.2 Greps run

- `grep -n "_discover_zones\|_room_to_zone\|_handle_zm_zones_updated\|room_names" presence.py`: build sites `:2913`, `:3373-3500`. Every `tracker.room_names` reader is listed in §2.
- `grep -rn SIGNAL_ROOM_ENTRY_LIFECYCLE`: 4 writers in `__init__.py`; 3 subscribers (presence `:2991`, hvac `:5426`, binary_sensor `:1771` CameraPersonDetectedSensor, which is per-entry and re-resolves on its own).
- `grep -n "self\._[a-z_]*: *Dict\[str" presence.py` and the tracker ctor `presence.py:559-653`: the name-keyed fields in §2.
- `grep -n "_hvac_[a-z_]*: dict\|_room_entry_by_name" hvac_zones.py`: `:310-369`, `:397`, `:824`, `:854-857`, `:2262-2276`.
- `grep -n "_area_id_to_room\|_scanner_to_rooms\|_room_coordinators" person_coordinator.py`: `:117-119`, `:945-961`.
- Aggregation: `_get_zone_room_names` (`aggregation.py:5280-5287`) reads `coord.entry.data["room_name"]` per call. Not affected.

### 1.3 Docs, plans, memory

- Plans: `PLANNING_room_rename_writethrough.md` (full read of §1-§3 and D3; its D3a test shape is reused in §5), `AUDIT_zone_tier_divergence.md` (filename + parent role), sleep-mask plan R1-F11 / R3.1.9, review D (`house_state_rev32_review_D.md:41-58`).
- Memory: `project_cm_reload_suppression_cycle_stack`, `feedback_suppression_needs_discharge`, `feedback_context_wide_scoping`, `feedback_coincidental_equality_masks_concept_split` (D-M2 named this class), `feedback_hollow_test_anchors`, `feedback_extend_existing_never_rebuild`.
- HVAC doc §9.8 already lists "zone rooms frozen at discovery (added-room not counted until restart)". This cycle fixes the RENAME half only. A room added without a restart stays out of scope (§7).

### 1.4 Live state (read-only, 2026-10-19, `.storage/core.config_entries`)

47 room entries; 0 with `options.room_name != data.room_name`; 1 Zone Manager, 5 zones, 45 `zone_rooms` refs, **all entry ids**; 0 legacy `ENTRY_TYPE_ZONE` entries. Live exposure today is 0. The bug fires on the next rename.

### 1.5 Config-first

No setting fixes this. The only workaround is an HA restart after every rename, which is an operator action. That is the current mitigation. Put it in the README as the back-out.

---

## 2. Enumeration: every structure that keys a room by its NAME (main deliverable)

Each row says when the structure is built, what happens to it after a live rename today, and the action this cycle takes. **Move** means keep the value and change the key (old → new), so no live state is lost. **Rebuild** means a cheap idempotent re-derive. **None** means already correct.

### 2.1 Presence: per-tracker (`ZonePresenceTracker`, `presence.py:559-653`)

| # | Structure | Built | After rename today | Action |
|---|---|---|---|---|
| P1 | `tracker.room_names` (list) | `_discover_zones` `:3403-3466` | old name | **Move**, replacing in place at the same index (order is read by first-writer-wins) |
| P2 | `tracker._room_provenance[room][kind]` | substrate edges | old name's kinds released by D4c.2; new name's edges dropped | **Move** (keeps a sleeper's kinds across the rename) |
| P3 | `tracker._last_kind_per_room` | edges | stale key | **Move** |
| P4 | `tracker._entity_to_room` (entity → name) | `register_entity` `:980` via `_discover_room_sensors` | values = old name. The D-H1 night limb reads this when the switch is off | **Rewrite values** |
| P5 | `tracker._fan_on_rooms` (set) | `_handle_fan_change` | old name | **Move** |
| P6 | `tracker._fan_entity_to_room` (fan → name) | `_discover_room_fans` `:3877` | values = old name, so fan edges stamp the old room | **Rewrite values** |
| P7 | `tracker._fan_on_since`, `_fan_last_transition`, `_fan_off_at`, `_fan_interference_hold_until` | fan listener / gate | stale keys. The room-tier creation gate and D2 read these by room | **Move** (all four) |
| P8 | `tracker._camera_occupied` / `_camera_last_seen` | camera listener | keyed by **entity_id** | None |

### 2.2 Presence: coordinator (`PresenceCoordinator`)

| # | Structure | Built | After rename today | Action |
|---|---|---|---|---|
| C1 | `_room_to_zone` | `_discover_zones` `:3490-3494` | old key. `tracker_for_room(new)` misses, and the edge is dropped at `:3664-3671` | **Move** |
| C2 | `_room_area_ids` (name → area_id) | `_build_room_area_map` `:3187-3221`, setup only | old key, so BLE/scanner-area lookups for the room miss | **Move** (area_id is unchanged by a rename) |
| C3 | `_adjacency_cache` | `_rebuild_adjacency_cache` `:3238-3300`, also called at `:3309`, `:3498`, `:4639` | old name in keys and lists | **Rebuild** (existing call) |
| C4 | `_guest_room_state`, `_guest_room_entity_to_name`, `_guest_room_known_last_true` (+ `_guest_room_unsubs`) | `_discover_guest_rooms` `:5575-5720` | old name, so a guest-room gate never fires for the renamed room | **Move** state and rewrite `_entity_to_name` values. Builder: verify whether `_guest_room_unsubs` is keyed by name or entity and move it to match. Do NOT re-run discovery, which would double-subscribe without proof of idempotence |
| C5 | `_fan_interference_gated_prev` (set of names) | per tick | one tick of a stale name: diagnostic only, self-heals next tick | None (named, accepted) |
| C6 | `_v4716_zone_verdicts` | per tick, keyed by zone | — | None |
| C7 | `_zone_night_raw` / `_zone_night_rooms` (sleep-mask D1 night input) | per tick from P1/P2 + BLE + `tracker._entity_to_room` | correct once P1/P2/P4 move **and** BLE resolves to the new name (see X1) | None directly; this is the invariant's consumer |
| C8 | `_rooms_opting_out_of_camera_presence()` | lazy entry read `:3732` | correct (reads entry data per call) | None |
| C9 | Room-name memory / DB rows (`house_state_log`, episodes, `ura_activity_log`) | history | old name in history | None (non-goal: history is not rewritten) |

### 2.3 House state (sensor attributes)

| # | Structure | After rename | Action |
|---|---|---|---|
| H1 | `PresenceHouseStateSensor` per-zone `fan_on_rooms` and the D3 `guest_reason` `guest_room:<room>` (`sensor.py` ~5661 block) | derived from P5 / C4 at read time | None once P5/C4 move |
| H2 | `stale_counted_home`, `nobody_home_zone_input`, `last_away_branch`, `away_entries_today` | person- or house-keyed | None |

### 2.4 Cross-tier sites the fix must cover (Bug Class #53: one missed site)

| # | Structure | Built | After rename today | Action |
|---|---|---|---|---|
| X1 | `person_coordinator._area_id_to_room` (area → name), `_scanner_to_rooms` (scanner → [names]) | `_build_scanner_room_map` `:928-961`. A full rebuild runs ONLY when the set of room entry_ids changes (`:945`), and a rename keeps the ids | **old name stays**. A person's BLE room keeps resolving to the OLD name, so once P1 moves, the BLE limb of `_zone_night_raw`, `_l1_persons`, the fan veto `_ble_present_in_room` and the census `_ble_home_by_area` all stop matching the room | **Invalidate**: set `_scanner_map_entry_ids` to a sentinel so the next call does a full rebuild. Also **move** `_room_coordinators[old]`, which the short path adds to but never prunes |
| X2 | HVAC `ZoneManager._zones[*].rooms` (list of names) | `async_discover_zones` `hvac_zones.py:446-615`, setup only (`hvac.py:1326`) | old name. The per-pass `_room_entry_by_name` (`:854-857`) holds the NEW name, so the old name is classified `("excluded", "entry_removed")` with a degraded WARN+NM (`:2262-2276`). The zone then decides without the room and can **retreat a zone with a sleeper in it**. This is a second live hazard, not covered by the card text | **Move** in place in every zone that lists it (one HVAC zone can merge several house zones, HVAC doc §1) |
| X3 | HVAC per-room dicts `_hvac_armed`, `_hvac_tail_until`, `_hvac_prev_state_occupied`, `_hvac_arm_source`, `_hvac_output`, `_hvac_rule`, `_hvac_day_release_at`, `_hvac_shadow_release_at`, `_hvac_last_ev`, `_hvac_last_active`, `_hvac_episode_*` (5), `_hvac_pending`, `_hvac_ep_armed`, `_hvac_armed_at`, `_hvac_arm_onset`, `_hvac_arm_span_s`, `_hvac_arm_class`, `_hvac_ev_released_at`, `_hvac_exempt_reason`, `_hvac_cold`, `_hvac_dwell_s` (`hvac_zones.py:310-369`); `_room_hvac_class`, `_sticky_failed_rooms`, `_room_non_loaded_since` (`:397` ff.); `continuous_occupied_since` if room-keyed | producer | orphaned old keys. The new name starts with empty state, so a mid-tail room loses its tail | **Move** all, through ONE declared tuple of attribute names (see D2) |
| X4 | HVAC fast path `_fast_path_room_unsubs` | `hvac.py:5451-5465` | keyed by **entry_id** | None |
| X5 | `fan_policy_oracle._rooms`, `_room_locks` (`fan_policy_oracle.py:237-238`) | lazily, by room name | old record orphaned; new name gets a fresh `_RoomRecord`, so the fan hold history is lost once | **Accept, named** (LOW: one lost fan record per rename; it self-heals) unless the plan reviewer finds a trust-decision reader. Builder: grep its readers and confirm |
| X6 | `aggregation.py` zone sensors | per call from `entry.data` (`:5280-5287`) | correct | None |
| X7 | Room-tier `coordinator.py` per-room state | the room reloads and is rebuilt | correct | None |
| X8 | `binary_sensor.CameraPersonDetectedSensor` | re-resolves on its own entry's lifecycle (`binary_sensor.py:1757-1771`) | correct | None |

**Enumeration rule for the builder and Review D:** this table is a hypothesis. Re-run `grep -n "Dict\[str, \|dict\[str, \|Set\[str\]\|set\[str\]" presence.py hvac_zones.py person_coordinator.py fan_policy_oracle.py camera_census.py` and classify every hit as entity-keyed, zone-keyed, person-keyed or room-NAME-keyed. Any room-name-keyed structure not in this table is a finding.

---

## 3. Fix choice and marginal-benefit reasoning

**Chosen: re-key in place on the room-lifecycle signal (Option A).** Presence and HVAC each keep an entry_id → name map. On ANY `SIGNAL_ROOM_ENTRY_LIFECYCLE` action other than `removed`, if the payload name differs from the stored name for that entry_id, call one synchronous `rekey_room(old, new)` per tier BEFORE scheduling the substrate refresh, then update the map. The first event after a rename is `unloaded`, and its refresh already emits new-name edges, so re-keying on `loaded` alone would be too late for that refresh. The re-key is idempotent: on the `loaded` event the names already match, so it does nothing.

**Rejected B: re-run discovery.** It is a no-op for existing zones (`presence.py:3439`). Making it rebuild trackers means discarding live tracker state (provenance, overrides, fan and camera state, holds), which drops a sleeper's kinds for a tick at night: the bug in another form. It would also re-subscribe guest/fan/camera listeners with unproven idempotence.

**Rejected C: re-key every structure by entry_id.** That removes the class of bug but touches ~1,100 `room_name` occurrences across 36 modules (prior plan §2 count), DB history keyed by name, and the HVAC producer. It is a Tier-3 rewrite of the trust hierarchy to fix an event that happens a few times a year. Option A captures the whole benefit for an operator-triggered rename. Option C's extra margin (no future structure can drift) is better bought cheaply by D4's enumeration lint. **Park C** with this revival trigger: a second name-drift bug in a structure the D4 lint did not cover, or the multi-home rollout making renames routine.

**Ingredient price of A:** no synthetic time, no new writer to a shared primitive (the substrate is untouched), no new signal, and one rare-fire path. Rare-fire is why D5 drives a real rename end to end and D4 lints the enumeration.

---

## 4. Falsifiable invariants

> **INV-RENAME-1.** For any ROOM entry `e` renamed through the options flow from `A` to `B` while HA runs, once the room's reload has completed (the `loaded` lifecycle dispatch has returned and every scheduled substrate refresh has finished), **no** structure in §2 rows P1-P7, C1-C4, X1-X3 holds `A` as a key or value, AND each holds `B` wherever it held `A` before the rename, with the value it held for `A`.

> **INV-RENAME-2 (the behavioural one D-M2 broke).** Under the same rename, if a Tier-1 sensor of `e` reads `on` throughout, then at every instant from the rename to restart the room counts for its zone. That means `tracker._room_occupied[B]` is True after the barrier, `_zone_night_raw` for that zone is True during SLEEP, and nobody-home cannot fire with census 0. For HVAC, `B` is never classified `entry_removed`, and the HVAC zone's `any_room_hvac_occupied` stays True.

> **INV-RENAME-3 (no-op path).** A lifecycle event whose payload name equals the stored name, or whose entry_id is unknown, leaves every §2 structure byte-identical. A `removed` event never re-keys. With the kill switch off, behaviour is identical to `develop` @ `aebe0e496`.

**How to falsify:** find a legal config (a room in two zones; a room in an HVAC zone shared by two house zones; a rename A→B→A; a rename to a name that differs only by case; a rename while the house is in SLEEP; a rename during boot-settle; a rename while presence's substrate is still `None`) where any §2 structure still holds `A` after the barrier, or where `B`'s True edge reaches presence before the re-key ran.

---

## 5. Deliverables

### D1. Presence re-key on the room-lifecycle signal

- `self._room_name_by_entry` is filled in `_discover_zones` (ZM resolve, `:3446-3452`) and in `_build_room_area_map`.
- `_on_room_entry_lifecycle`: first statement after the `action == "removed"` skip and the kill-switch read. If `old := self._room_name_by_entry.get(entry_id)` and `room_name` and `old != room_name`, call `self._rekey_room(old, room_name)` and update the map. This runs synchronously, BEFORE the `_substrate is None` early return and before `async_create_task(refresh_subscriptions)`.
- `_rekey_room(old, new)` covers P1-P7, C1-C4 (C3 through the existing `_rebuild_adjacency_cache()`). It calls the person-coordinator invalidation (X1) through a public method on PersonCoordinator, `invalidate_room_map()`, which clears `_scanner_map_entry_ids` and moves `_room_coordinators[old]`. It logs one INFO line: `room rename re-keyed: entry=<id> '<old>' -> '<new>' (trackers=N, kinds_moved=K)`.
- Collision guard: if `new` is already present in a structure (illegal, since `_room_name_collides` rejects it at `config_flow.py:12322-12327`, but reachable through a hand-edited `.storage`), WARN once, skip that structure, and do not overwrite.

**Acceptance**
- **Verify:** after rename A→B with a ZX on, `tracker.room_names` contains B at A's index, `_room_to_zone[B] == zone`, `_room_provenance[B]` equals the pre-rename `_room_provenance[A]`, and nothing keys A.
- **Discriminates:** under the bug, `_room_to_zone` has A and B's edge logs "Substrate edge for unknown room 'B'". Under a "rebuild discovery" fix, B is present but `_room_provenance[B]` is empty for a tick. Under the chosen fix, B is present and its kinds are carried over.
- **Test:** `quality/tests/presence/test_room_rename_rekey.py::test_rename_rekeys_tracker_maps_before_substrate_refresh`, `::test_rename_noop_when_name_unchanged`, `::test_removed_action_never_rekeys`, `::test_rename_collision_warns_and_skips`, `::test_rename_before_substrate_constructed_still_rekeys`.

### D2. HVAC zone-list re-key

- `ZoneManager` keeps `self._room_name_by_entry` (promoted from the local at `hvac_zones.py:462`).
- `ZoneManager.rekey_room(old, new)` replaces in place in every `zone.rooms`, and moves every key in a module-level tuple `_HVAC_ROOM_KEYED_ATTRS` (X3) plus the `_sticky_failed_rooms` set.
- `HVACCoordinator._on_room_lifecycle` calls it under the same name-differs rule before attaching or releasing the fast path. It must not hold `_decision_cycle_lock`: the method is sync and await-free, and HA's single event loop makes it atomic with respect to a pass. The builder verifies no `await` sits between the read and the write.
- **Acceptance**
  - **Verify:** after the rename, B is in its HVAC zone's `rooms`, `_room_hvac_class[B]` is not `("excluded", "entry_removed")`, and no `entry_removed` degraded NM fires.
  - **Discriminates:** under the bug, the classification is `entry_removed` plus an NM row.
  - **Test:** `quality/tests/hvac/test_hvac_room_rename_rekey.py::test_rename_moves_zone_rooms_and_room_state`, `::test_rename_in_merged_hvac_zone_moves_all_occurrences`, `::test_no_entry_removed_nm_on_rename`.

### D3. Kill switch

`const.ROOM_RENAME_REKEY_ENABLED: Final = True`, rung 1 (module constant, attribute-read like `ZONE_OCCUPANCY_PER_ENTITY_ENABLED`). Why rung 1: it is a correctness path with no operator policy in it. False means behaviour identical to today (re-key skipped, restart needed after a rename). Test: `::test_kill_switch_off_is_byte_identical`.

### D4. Enumeration lint (keeps INV-RENAME-1 true for future fields)

A test introspects a constructed `ZonePresenceTracker`, `PresenceCoordinator` and `ZoneManager`, seeded with one room. It asserts that every attribute that is a dict/set/list containing that room's NAME (as key, element or value) is either covered by `_rekey_room` / `rekey_room` or listed in an explicit, commented `_RENAME_EXEMPT` allowlist (C5, C6, C9, X5).
- **Test:** `::test_every_room_name_keyed_attr_is_rekeyed_or_exempt` (presence + hvac).
- **Discriminates:** add a new `Dict[str, …]` keyed by room name without registering it, and the test goes red.

### D5. End-to-end rename through the options flow with a real reload barrier (the invariant test)

- Uses the real options flow `async_step_basic_setup` on a real room `MockConfigEntry`, a real `PresenceCoordinator` + `OccupancySubstrate` (reuse the sleep-mask `SubstrateWorld` fixture, `test_zone_tracker_per_entity.py`), and a real HVAC `ZoneManager`. It does not shortcut the reload.
- Barrier: `await hass.async_block_till_done()` after the flow returns, then `await asyncio.gather(*coord._substrate_refresh_tasks)`, then `async_block_till_done()` again (two barriers, per the prior plan's M2 lesson). A barrier that is only `async_block_till_done` is not acceptable.
- Scenario: Master Suite = [Master Bedroom], ZX on, ZV off, house SLEEP at 02:00, census 0, boot-settle released. Rename to "Primary Bedroom". Assert that `tracker._room_occupied["Primary Bedroom"]` is True, nobody-home does not fire (`infer()` returns SLEEP, not `away` / `nobody_home`), and HVAC `any_room_hvac_occupied` for the zone is True. This is review D-M2's repro inverted.
- Second scenario: a rename while the person's BLE room is the renamed room. After the barrier, `person_coordinator` resolves the person to the NEW name, and `_zone_night_raw` reads True from the BLE limb alone (ZX off).
- **Test:** `quality/tests/presence/test_room_rename_rekey.py::test_rename_through_options_flow_keeps_sleeper_home_after_reload_barrier`, `::test_rename_ble_limb_follows_new_name`.
- **Mutation drill targets (Review C, real per-site source edits):**
  1. Delete the `_rekey_room` call in `_on_room_entry_lifecycle`. Expected red: the D5 sleeper test and D1 test 1.
  2. Move the call AFTER `async_create_task(refresh_subscriptions)`. Expected red: D1 `before_substrate_refresh`, because the unloaded refresh edge is dropped.
  3. Drop the P2 provenance move only. Expected red: D1 test 1's provenance assertion.
  4. Drop the X1 `invalidate_room_map()` call. Expected red: `test_rename_ble_limb_follows_new_name`.
  5. Delete the `rekey_room` call in `hvac._on_room_lifecycle`. Expected red: D2 tests.
  6. Remove one name from `_HVAC_ROOM_KEYED_ATTRS`. Expected red: D4 lint.

  A drill that leaves the suite green is an untested site: do not ship. Disable `.pyc` (`PYTHONDONTWRITEBYTECODE=1`) during drills (memory `feedback_mutation_verification_pycache_staleness`).

### D6. Docs in the ship commit

- PRESENCE_ARCHITECTURE_STATE_OF_PLAY: §9 entry resolved, and a §10 correction stating that the rename-writethrough I1 claim was false for the presence tier.
- HVAC_ARCHITECTURE_STATE_OF_PLAY: §9.8, the rename half fixed; added rooms are still frozen until restart.
- A one-line correction banner in `PLANNING_room_rename_writethrough.md` §1.

### Live criterion (operator-optional, one-shot, not a soak)

When the house is awake and occupied (never during Sleep, memory `feedback_no_restart_during_sleep`; no restart is needed for this check):
1. Pick a low-stakes room with a live Tier-1 sensor (e.g. Laundry).
2. Rename it "Laundry RT" in the options flow and wait ~30 s.
3. Check (a) the log line `room rename re-keyed: … 'Laundry' -> 'Laundry RT'`, (b) no `Substrate edge for unknown room 'Laundry RT'` line, (c) no `entry_removed` HVAC degraded NM, (d) the zone presence sensor and `sensor.ura_hvac_coordinator_zone_N_status` show the room under its new name when its sensor fires.
4. Rename it back and repeat (a)-(c).

PASS = all four in both directions. **Discriminates:** under the bug, (b) and (c) appear. The operator may skip this; the D5 in-suite test is the proof of record. If skipped, mark it "proven in-suite only" in the README validation table.

---

## 6. Numbers and the knob ladder

| Number | Knob | Rung | Why |
|---|---|---|---|
| Kill switch | `ROOM_RENAME_REKEY_ENABLED` (True) | 1, module const | correctness path; a change needs review; False = today's behaviour |
| — | No timing, window, retry or threshold is introduced | — | the re-key is synchronous and event-driven; no debounce, so no "suppression needs a discharge" duty |

---

## 7. Non-goals

- Re-keying by entry_id across the codebase (Option C, parked with its trigger in §3).
- Adding a room to a zone, or creating a room, without a restart (HVAC §9.8 "added-room" half; presence has the same gap). Card it if not already carded; do not grow this cycle.
- Zone RENAME (`CONF_ZONE_NAME`): zone trackers key by zone name. This is a sibling hazard. The builder checks for an existing card and mints one if none exists. Not in this cycle.
- Rewriting history (DB rows, memory episodes, activity log) keyed by the old name.
- The fan-policy-oracle record (X5): accepted, unless the plan review shows a trust-decision reader.
- Legacy `ENTRY_TYPE_ZONE` entries that list rooms by NAME (0 live). The re-key moves names wherever trackers hold them, so it covers them by construction, but no dedicated test.
- Changing the substrate, the rename flow, or `_ROOM_SUPPRESS_KEYS`.

---

## 8. Tier and review framing

**Tier 2, elevated to three framing-disjoint build reviews** (standing policy: trust-hierarchy ripple presence ↔ house-state ↔ HVAC). It is not Tier 3: no reserve, cost or shared-primitive writer is touched. **Escalate to Tier 3 if** the builder finds a second X2-class trust site (an HVAC or energy decision reading a name-keyed structure outside §2), or if Option C is chosen.

- **Plan review (one, before build):** re-run the §2 enumeration from scratch, especially X1-X5 and anything in `camera_census.py` / `fan_policy_oracle.py`.
- **Build review A (correctness and edge cases):** move semantics, in-place list replacement, the collision guard, case-only renames, A→B→A, a room in two zones (first-writer-wins preserved).
- **Build review B (ordering, lifecycle and cross-coordinator):**
  - The re-key runs before every substrate refresh on `unloaded`, `loaded` and `options_updated`.
  - Presence-not-yet-constructed and boot-settle windows.
  - No `await` inside the re-key.
  - HVAC pass atomicity.
  - The person-coordinator rebuild races the next BLE update.
  - Restart: the maps re-derive from `entry.data`.
- **Build review C (test authority, `ura-reviewer-mutation`):** the six D5 drills.
- **Review D (adversarial completeness):** optional by the Tier-2 rules. Recommended here because the whole failure mode is one missed site. D falsifies INV-RENAME-1 and INV-RENAME-2 against the full repository, not the diff.

---

## 9. Open questions (operator / plan reviewer)

1. X2 (HVAC drops the renamed room as `entry_removed` and can retreat a zone with a sleeper in it) is outside the card text but the same class. It is folded in here. Operator: confirm the scope (it adds about 25% to the build).
2. X5, the fan-oracle record: accept the loss, or move it too? It defaults to accept, pending the reviewer's reader grep.
3. Should the zone-rename sibling (`CONF_ZONE_NAME`) be carded now, or is it already covered by an existing card?

---

## Plan review 2026-10-19 — completeness (adversarial)

Reviewer: ura-planner (completeness framing). Read completely first: PRESENCE_ARCHITECTURE_STATE_OF_PLAY, SENSOR_FLEET_CLASSES, HVAC_ARCHITECTURE_STATE_OF_PLAY, URA_ARCHITECTURE_MAP. Code read on HEAD `2b7d31e8f`. **Verdict: FIX-PLAN** (two HIGH misses on the HVAC/fan side, one ordering gap).

**Missed sites (add to §2):**
- **F1 HIGH: `hvac_fans.FanController._room_fans` (`hvac_fans.py:390`, built once in `discover_fans` `:414-463`, called `hvac.py:1569`).** Keyed by room name. Its tick looks up `rc.room_name == room_name` in `zone.room_conditions` (`hvac_fans.py:835-841`) and falls back to `occupied=False`. Once X2 moves `zone.rooms` to B, the old-name `RoomFanState` finds no condition, so the renamed room's HVAC-owned fan is driven as UNOCCUPIED, which can turn a sleeper's fan off at night. It also holds the cooldown and manual-hold ledger. Action: **Move** in `ZoneManager.rekey_room`'s HVAC companion, or re-run `discover_fans()`. Re-running is only safe if it carries state over; it does not (`.clear()` at `:420`).
- **F2 HIGH: `presence_fan_recheck.FanRecheck._rooms` (`presence_fan_recheck.py:187`, created lazily `:374-380`, rehydrated `:1767`).** Keyed by name; the DB row is keyed by entry_id (`fan_recheck_state.room_id`, `database.py:1784-1794`). After a rename, `on_room_tick` creates a SECOND IDLE ctx for B with the same entry_id, while A's ctx keeps its timers. If A's ctx was PAUSED (fan off), its restore calls `restore_after_recheck(A)`, which returns early once F1 moved `_room_fans` (`hvac_fans.py:2152-2154`), so the fan stays OFF. Two ctxs also write the same DB row. The recheck reads `fan_controller._room_fans.get(room_name)` (`presence_fan_recheck.py:1545`) as its write registry. Action: **Move** the ctx (A→B, keep timers; the ctx carries `room_name`, so update that too). Ordering: F1 and F2 must move together.
- **F3 MEDIUM: `safety.SafetyCoordinator._room_area_ids` / `_room_types` (`safety.py:1055-1057`, built `:1304-1305`) and `_sensor_locations` values (`:1406-1422`).** These are setup-only. They give stale room names in hazard alerts and location text. This is display, not a trust decision. Action: accept by name in `_RENAME_EXEMPT`, or move.
- **F4 LOW: `optimization._room_scores` (`optimization.py:601`).** Diagnostic. Exempt by name.
- `person_coordinator._direct_ble_rooms` (`:121`, rebuilt `:962-984`) is covered by the X1 full rebuild. Name it in X1 so D4 does not flag it.
- **DB:** no table uses room NAME as a lookup key that a live decision depends on. `fan_recheck_state` is keyed by entry_id (correct). The parked **REGIME-BASELINE-ROOM-RENAME-CONTAMINATION-1** (`kanban.data.yaml:9181`) is the history-side sibling. This cycle does not fire its trigger, but §7 should cite it.

**Mechanism verdict: sound with one gap.** All emit sites are verified: `unloaded` `__init__.py:6179-6186` (only on `unload_ok`), `loaded` `:5631-5637`, `removed` `:5736-5743`, `options_updated` `:8673-8680`. The payload is `entry.data["room_name"]`, which is already new because `async_update_entry` writes data before the reload (`config_flow.py:12386-12391`). Both subscribers are `@callback` (`presence.py:3678`, `hvac.py:5439`), so the re-key runs synchronously inside the dispatch, ahead of the scheduled refresh task.
- **Gap, MEDIUM:** between `async_update_entry` and the `unloaded` dispatch, the reload is a scheduled task. An HVAC pass in that window (a fast run from ANY room's refresh, or the 5-min tick) rebuilds `_room_entry_by_name` with B, while `zone.rooms` still holds A. Result: `entry_removed`, `_sticky_failed_rooms.add(A)` (`hvac_zones.py:2329`) and a degraded NM, before any lifecycle event. INV-RENAME-2's "never `entry_removed`" is falsifiable here. Fix: make `rekey_room` also drop A from `_sticky_failed_rooms` and suppress the NM. Better: HVAC derives the rename from its own per-pass entry_id→name map at the top of `update_room_conditions`, so no signal is needed for the HVAC tier.
- `_tearing_down` early return (`hvac.py:5444`): fine.
- `unload_ok=False` leaves no `unloaded` dispatch. The next `loaded`/`options_updated` re-keys (idempotent rule). Add a test.

**Tier recommendation: Tier 3.** The CLAUDE.md triggers fire:
1. A value (the room's identity) is threaded through many consumer sites across presence ↔ HVAC ↔ person ↔ fans, so the failure mode is one missed site (Bug Class #53). This review found two more HIGH sites the plan's own enumeration missed.
2. It touches comfort and safety (a sleeper AWAYed, a zone retreated, a fan left off).
§8's own escalation trigger ("a second X2-class trust site outside §2") has fired via F1/F2. Run four build reviews with D mandatory, config-extreme tests (rename during PAUSED recheck, rename in a merged HVAC zone, rename inside the update→unload window), and an operator checkpoint before deploy.
