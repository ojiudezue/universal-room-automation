# PLANNING: Zone Delete Flow

**Cycle:** Zone Delete Flow (post-v5.11.0)
**Branch:** develop
**Tier:** Tier 2-DB (database.py DAO surface + shared zone primitive + lifecycle reload)
**Falsifiable invariant:** After a zone is deleted and the Zone Manager entry has reloaded, NO entity registry entry, NO device registry entry, NO in-memory coordinator state, and NO DB row keyed by that zone survives; AND surviving zones are byte-identical in behavior and state to their pre-delete selves.

---

## Institutional context verified

### Anchors re-run (findings from 2026-07-10 investigation, re-checked against develop HEAD)

1. **Zones dict is the sole source of truth** — verified. Zone add path at `config_flow.py:848-870` writes into `zone_manager_entry.options["zones"][zone_name] = {...}` then calls `hass.config_entries.async_reload(zone_manager_entry.entry_id)`. Zones are NOT config entries in the Zone-Manager era (legacy `ENTRY_TYPE_ZONE` fallback still exists at `config_flow.py:874-887` for the no-ZM case; the delete flow must handle both shapes, though the operator's live house is ZM-only per v3.3.5.4 migration `__init__.py:95-159`).
2. **Zone entity unique-id enumeration is deterministic** (verified via grep of `f"{DOMAIN}_zone_"` and `f"{DOMAIN}_hvac_`):
   - **Zone-name-keyed** (aggregation.py, 13 unique_ids): `_zone_{zone}_occupied`, `_anyone`, `_safety_alert`, `_avg_temp`, `_avg_humidity`, `_temp_delta`, `_humidity_delta`, `_total_power`, `_energy_today`, `_energy_cost_today`, `_cost_per_hour`, `_active_rooms`, `_identified_people`, `_identified_people_count`, `_last_identified_person`, `_last_identified_time`.
   - **Zone-name-keyed** (select.py:297): `_{zone_slug}_presence_mode`.
   - **Zone-id-keyed** (HVAC family, keyed off thermostat-derived zone_id): `_hvac_ac_ramp_{action}_{zone_id}` (button.py:842), `_hvac_ac_kwh_threshold_{zone_id}` (number.py:2182), `_hvac_zone_{zone_id}_egress_window_open` (binary_sensor.py:2489), and HVACZoneStatus/Preset/Intelligence sensors (to enumerate in D2).
   - **Device identifier**: `(DOMAIN, f"zone_{zone_name}")` at `aggregation.py:3416`; already precedented removal at `config_flow.py:6656-6662` (rename path uses `dev_reg.async_remove_device(old_device.id)`).
3. **DB tables to purge** (verified in `database.py`): `zone_events` (col `zone TEXT`, line 471), `ac_reset_state` (PK `zone_id`, line 1218), `egress_state` (PK `zone_id`, line 1247), `fan_recheck_state` (PK `zone_id`, line 1268), `ac_ramp_events` (col `zone_id`, line 1291). No existing `async_delete_zone_*` DAO — NEW justified.
4. **Zone-id derivation is thermostat-entity-based** — verified via `_resolve_hvac_zone` docstring (`aggregation.py:3365-3395`): `ZoneManager.zones` is keyed by `zone_id` ("zone_1", "zone_2", …) *derived from the thermostat entity*, not the zone name. Delete must capture the thermostat entity from `zones[zone_name][CONF_ZONE_THERMOSTAT]` BEFORE mutating the zones dict, then reverse-map to zone_id via live `ZoneManager.zones` snapshot for DB row targeting. Husk zones (no thermostat) skip DB cleanup for zone_id-keyed tables but still purge `zone_events` (name-keyed).
5. **Reload-suppression allowlist does NOT cover the zones dict** — verified `__init__.py:4256` (`_OPTION_LIVE_APPLY_KEYS` allowlist is CM-scoped, per-CONF-key). "zones" is not in it; a zones-dict mutation falls through to `async_reload` at `__init__.py:4886-4892`. GOOD: delete → `async_update_entry(zm_entry, options={..., "zones": new})` → automatic full ZM reload. Verify in D2 the update path routes through the same listener (or explicit `async_create_task(async_reload(...))` as the add path does at line 868).
6. **`_resolve_hvac_zone` tolerates missing zones** — verified: returns `None` cleanly when zone_name absent. Confirms D3 lower-bound tolerance; individual aggregators need audit for None-handling on the returned ZoneState (spot-check the 13 unique_ids in D3).
7. **`_zone_trackers` rebuild path** — verified `presence.py:2486, 2517, 2541` inside `_update_signal_subscriptions` reassigns `self._zone_trackers[zone_name]`. Rebuild is triggered periodically AND on ZM reload; a deleted zone drops out on next rebuild. D3 must add: explicit `del self._zone_trackers[zone_name]` on the delete-dispatch path (defense-in-depth vs waiting for next rebuild) OR rely on the reload to reconstruct from scratch. Prefer reload path — simpler, matches existing invariant.
8. **HVAC `ZoneManager.zones` rebuild** — `async_discover_zones` (hvac_zones.py) reconstructs from ZM entry options on setup. Full ZM reload = full rediscovery = deleted zone drops out. No in-place mutation needed.
9. **Room entry `CONF_ZONE` field** — rooms carry the zone name string (`config_flow.py:6636`). Delete flow MUST clear this from every room that references the deleted zone (else those rooms become zombie references — same class as the "no zone assigned" case that migration at `__init__.py:111` already handles). Precedent: rename removes-then-adds at `config_flow.py:6641-6652`.
10. **Reference: Room entry deletion (native HA path)** — HA cleans up entity/device registry for a config entry automatically on `async_remove` via `async_unload_entry`. Zones have no entry → no free ride → we must sweep entity registry manually. This is the core reason the cycle is Tier 2-DB.
11. **Existing `zone_config_menu` structure** — `config_flow.py:6545-6557` renders a menu with 7 options (rooms, media, hvac, energy, persons, cameras, dynamic_preset). Delete slots in as an 8th, placed LAST and visually separated in strings.json.

### Prior planning docs consulted
- `PLANNING_v4.7.5_zone_manager_ux.md` (skim) — established zone_config_menu, banner helper, canonical resolution.
- `PLANNING_v4.7.31_*` (skim of filenames) — canonical resolver hardening; per findings, `_resolve_hvac_zone` returns None safely for missing zones (inert husk-zone tolerance).
- `PLANNING_zone_camera_person_only_guard.md` (grep) — orthogonal, no overlap.
- No prior "zone delete" planning doc found (grep of `docs/planning/` for delete/remove/purge on zones) — NEW cycle.

### Memory bodies pulled
- `project_v4_7_24_substrate_unification_live.md` — verified `OccupancySubstrate` is per-room, not per-zone; no substrate cleanup needed.
- `project_v475_live.md` — Zone Manager UX established; delete flow inherits list-mode menu pattern.
- `feedback_parent_entry_reload_watchdog_hazard.md` — **CRITICAL constraint**: NEVER reload the URA parent entry; delete flow reloads the ZM entry ONLY.

### Design docs read
- `docs/Coordinator/HVAC.md` — reviewed the ZoneManager section; discovery is idempotent from ZM options → reload is sufficient.

### Code locations surveyed end-to-end
- `config_flow.py:6379-6557` (manage_zones + zone_config_menu + banner)
- `config_flow.py:6563-6723` (zone_rooms rename precedent — save/mirror/dev_reg cleanup)
- `config_flow.py:810-887` (zone_setup ADD path — reload primitive)
- `__init__.py:95-159` (ZM migration, "zones NOT entries" invariant)
- `__init__.py:4256, 4796-4892` (options-listener allowlist + reload fallthrough)
- `aggregation.py:3365-3416, 3539-4701` (zone entity unique_ids + device identifier)
- `database.py:470-1310` (zone-keyed table DDLs)
- `presence.py:1182, 2486-2569` (`_zone_trackers` lifecycle)

---

## Deliverables

### D1: Delete step in zone_config_menu

Add "zone_delete" as the 8th menu option in `zone_config_menu` (`config_flow.py:6545-6557`). Route to a new `async_step_zone_delete_confirm`.

**Confirm screen (LABEL RULE — operator-friendly, plain language):**

- Title: **"Remove this zone?"**
- Body (rendered via `description_placeholders`, plain English, no config-key jargon):

  > You are about to remove the zone **{zone_name}** from Universal Room Automation.
  >
  > What will happen:
  > - {N_entities} sensors and controls for this zone will be deleted (temperature, occupancy, energy, HVAC controls, etc.)
  > - {N_rooms} room(s) currently assigned to this zone will become unassigned. They will keep working; you can put them in another zone later.
  > - Historical data for this zone in the URA database will be cleared ({N_db_rows} rows across {N_tables} tables).
  > - If this zone shares a thermostat with another zone, the thermostat setting is NOT changed — the other zone keeps working.
  >
  > This cannot be undone. To confirm, type the zone name below.

- Field: `vol.Required("confirm_zone_name"): str` — must match `zone_name` exactly (case-insensitive, trimmed). Wrong text → `errors["base"] = "confirm_name_mismatch"`. This guard is required for husk deletion too (protects against fat-fingering the wrong menu entry).
- Submit → invoke D2 helper → `async_abort(reason="zone_removed")`.
- The counts ({N_entities}, {N_rooms}, {N_db_rows}, {N_tables}) are computed by a read-only `_summarize_zone_deletion(zone_name)` helper that runs BEFORE the form renders so the operator sees real numbers.

#### Acceptance Criteria
- **Verify:** Menu shows "Remove this zone" as an 8th option, visually last.
- **Verify:** Confirm screen renders exact counts matching actual entities/rooms/DB rows.
- **Verify:** Typing the wrong name → form re-renders with error, no mutation occurs.
- **Verify:** Typing correct name → helper runs, ZM reloads, abort message shown.
- **Test:** `test_zone_delete_confirm_mismatch_no_mutation`, `test_zone_delete_confirm_counts_match_reality`.
- **Live:** Open the ZM options flow on the husk zone `Entertainment + Master Suite`; confirm screen shows N_rooms=0, N_entities>0 (aggregation sensors exist even for husks), N_db_rows plausible.

### D2: Deletion helper + `async_delete_zone_data` DAO

New helper `_delete_zone(hass, zm_entry, zone_name)` — one atomic path:

1. **Snapshot before mutation:** capture `zone_cfg = zones[zone_name]`, capture `thermostat_entity = zone_cfg.get(CONF_ZONE_THERMOSTAT)`, capture live `zone_id` via reverse-lookup on `hvac_coordinator.zone_manager.zones` (find the ZoneState whose `zone_name` matches; None for husks). Capture list of rooms with `CONF_ZONE == zone_name`.
2. **Entity registry sweep:** enumerate unique_ids using the deterministic patterns confirmed in institutional context §2:
   - Name-keyed: `{DOMAIN}_zone_{zone_name}_*` (16 patterns) + `{DOMAIN}_{slugify(zone_name)}_presence_mode`.
   - Id-keyed (skip if zone_id is None): `{DOMAIN}_hvac_ac_ramp_*_{zone_id}`, `{DOMAIN}_hvac_ac_kwh_threshold_{zone_id}`, `{DOMAIN}_hvac_zone_{zone_id}_*`.
   - For each match in the entity registry, call `entity_registry.async_remove(entity_id)`.
   - Enumerate by iterating `er.entities.values()` and matching the `unique_id` prefix set — do NOT hardcode entity_ids. This is the D2 durability contract.
3. **Device registry:** `dev_reg.async_remove_device` for identifier `(DOMAIN, f"zone_{zone_name}")`.
4. **Room reassignment:** for every room entry with `options[CONF_ZONE] == zone_name`, `async_update_entry(room, options={..., CONF_ZONE: ""})`. Follow rename precedent (`config_flow.py:6641-6652`).
5. **DB purge — new DAO `async_delete_zone_data(zone_name, zone_id)`** in `database.py`:
   - `DELETE FROM zone_events WHERE zone = ?` (zone_name).
   - If `zone_id` is not None: `DELETE FROM ac_reset_state WHERE zone_id = ?`, `DELETE FROM egress_state WHERE zone_id = ?`, `DELETE FROM fan_recheck_state WHERE zone_id = ?`, `DELETE FROM ac_ramp_events WHERE zone_id = ?`.
   - Returns a per-table row-count dict for logging/D1 summary reuse.
   - Routes through the existing write queue (verify against `database.py` write patterns during build — DO NOT introduce a new writer path).
6. **Options mutation + reload (LAST):** `new_zones = {k: v for k, v in zones.items() if k != zone_name}`; `async_update_entry(zm_entry, options={..., "zones": new_zones})`; then `hass.async_create_task(hass.config_entries.async_reload(zm_entry.entry_id))` — matching the add-path primitive at `config_flow.py:868-870`.
7. **RestoreEntity state:** removed entities' restored state is dropped by HA when `entity_registry.async_remove` is called. No manual `.storage` scrub needed — verify in D4 tests.

#### Acceptance Criteria
- **Verify:** Post-call, `zm_entry.options["zones"]` no longer contains `zone_name`.
- **Verify:** Entity registry contains zero entries whose unique_id matches any of the enumerated patterns for this zone.
- **Verify:** Device registry contains no device with identifier `(DOMAIN, f"zone_{zone_name}")`.
- **Verify:** DB tables: `SELECT COUNT(*) WHERE zone=?` and `WHERE zone_id=?` all return 0.
- **Verify:** Rooms that referenced this zone have `options[CONF_ZONE] == ""`.
- **Test:** `test_delete_zone_removes_options_dict_key`, `test_delete_zone_sweeps_entity_registry_deterministic`, `test_delete_zone_removes_device`, `test_delete_zone_purges_all_five_db_tables`, `test_delete_zone_clears_room_zone_field`, `test_delete_husk_zone_no_thermostat_skips_id_keyed_tables`.
- **Live:** After husk deletion, `ha_search_entities` for `zone_entertainment_master_suite` returns empty; SQL: `SELECT * FROM zone_events WHERE zone LIKE '%entertainment%'` returns 0.

### D3: Defensive hardening

- **Aggregators (`aggregation.py`):** audit the 13 zone unique_ids; each already tolerates `_resolve_hvac_zone → None`. Add `_attr_available = False` guard on `ZoneSensorBase` when the zone is not in `zm_entry.options["zones"]` — mid-reload safety window. One helper `_zone_still_configured(self)` reads from ZM entry.
- **`_resolve_hvac_zone` tolerance:** already returns None cleanly — no change needed, but add explicit test coverage (was implicit).
- **Presence `_zone_trackers`:** rely on `_update_signal_subscriptions` rebuild + full ZM reload to drop the tracker. Add ONE defensive line: at the top of `_update_signal_subscriptions`, prune any tracker whose zone_name is no longer in the current ZM zones dict snapshot. This closes the window between mutation and the next full rebuild.
- **HVAC `ZoneManager`:** full ZM reload → full `async_discover_zones` re-run → deleted zone drops out. No in-place mutation. Test the reload path in D4.
- **Anti-fabrication guard:** the helper MUST log a WARNING (not raise) for any unexpected registry residue found on post-sweep re-scan. This is the tripwire that catches a missed unique_id pattern in a future entity-family addition.

#### Acceptance Criteria
- **Verify:** During reload window, no aggregator entity throws; each shows `unavailable`.
- **Verify:** No `_zone_trackers` entry survives the delete + one signal rebuild.
- **Test:** `test_aggregator_available_false_when_zone_removed`, `test_presence_prune_stale_trackers_on_rebuild`, `test_resolve_hvac_zone_returns_none_for_missing`.
- **Live:** After delete, `ura-sqlite` shows zero rows AND `sensor.zone_entertainment_master_suite_occupied` no longer exists in the entity registry.

### D4: Tests

Behavioral test tier (not unit-mock-only) — schema extracted from `database.py` DDL per Tier 2-DB Review C authority rule:

1. `test_delete_husk_zone_end_to_end` — no thermostat, no rooms; all 6 subsystems clean.
2. `test_delete_zone_with_thermostat_and_rooms` — full-shape zone; verify thermostat entity is NOT modified, rooms become unassigned, DB purged including zone_id-keyed tables.
3. `test_delete_zone_shared_thermostat_leaves_sibling_intact` — two zones share one thermostat; deleting one preserves the sibling's HVAC entities and DB rows.
4. `test_delete_while_coordinators_running` — simulate delete under a live HVAC coordinator update tick; assert no exceptions in aggregators or presence.
5. `test_restart_after_delete_no_orphans` — write a fake config with a deleted zone, restart the ZM entry setup, assert entity registry has zero orphans.
6. `test_confirm_name_mismatch_no_mutation` — wrong text = zero side effects.
7. `test_delete_zone_dao_transaction_atomicity` — force one DELETE to fail mid-flight, assert either all-or-nothing OR the helper's per-table result dict correctly reports partial (choose one contract in build; test both).
8. `test_reload_suppression_allowlist_falls_through_for_zones_dict` — asserts zones-dict change does NOT hit the allowlist path.

#### Acceptance Criteria
- **Verify:** All 8 tests pass under `PYTHONPATH=quality python3 -m pytest quality/tests/ -v`.
- **Live:** Post-deploy, cycle these acceptance criteria into the README validation table.

### D5 (stretch — defer, with justification)

**Rename zone.** Falls out cheaply once delete infrastructure exists (rename = delete+re-add-under-new-name, or in-place options rewrite + entity re-registration). BUT: rename has its own risks (unique_id churn = HA sees old + new + history detachment; RestoreEntity migration; user's Lovelace / automations reference old entity_ids by name). These are non-trivial and orthogonal to delete's failure modes.

**DEFER** to a follow-on cycle. Track: add a stub `PLANNING_zone_rename.md` post-cycle with the enumerated risks (Lovelace break, automation entity_id references, history detachment, mirror-of-shared-thermostat implications). Do NOT bundle into this cycle — Tier 2-DB scope is already large.

---

## Tier 2-DB framings

- **Review A — Data integrity + registry cleanup completeness.** Every unique_id pattern enumerated; no orphaned entity or device registry residue; existing zones' rows in the five DB tables byte-identical pre/post. Row-rate snapshot required per Tier 2-DB protocol. Focus: did we miss a unique_id pattern? A future entity family added post-cycle would leak silently — is the WARNING tripwire (D3) durable enough?
- **Review B — Reload serialization + coordinator state coherence.** Delete-during-tick behavior; presence `_zone_trackers` prune ordering; HVAC `ZoneManager` rediscovery on reload; `_resolve_hvac_zone` None-tolerance across all 13 aggregators; no in-memory reference to the deleted zone survives past the reload boundary. Verify the zones-dict change actually falls through the allowlist to a reload (not silently absorbed as a live-apply no-op).
- **Review C — New surfaces + test authority.** New `async_delete_zone_data` DAO shape (rowcount contract, transaction atomicity, write-queue routing); new confirm-flow UI strings match LABEL RULE (plain language, no config-key jargon); tests exercise real DDL from `database.py`; confirm-name-mismatch guard is un-bypassable; restart-after-delete has no boot-time surprises.

---

## Risks

1. **Missed unique_id pattern** — a zone entity family added between cycle plan and build (or later) leaks. Mitigation: D3 WARNING tripwire on post-sweep re-scan + D4 test 5 (restart-after-delete orphan sweep). Bug Class #53 shape (computed-but-not-consumed sibling: enumerated-but-not-swept).
2. **Shared-thermostat sibling collateral damage** — deleting one of the "Entertainment + Master Suite" pair while both live. Mitigation: never delete by zone_id; delete strictly by zone_name in options dict + name-keyed registry sweep; HVAC entities keyed off zone_id survive because the sibling still owns the same zone_id post-reload. D4 test 3 covers.
3. **Mid-delete crash → half-purged state** — HA crashes between options mutation and DB purge (or vice-versa). Mitigation: options mutation LAST (step 6 above) so a crash before it re-runs cleanly on retry; DB purge is idempotent (DELETE WHERE); registry sweep is idempotent (async_remove of already-removed = safe).
4. **Parent-entry reload hazard** — reloading the URA integration entry triggers a watchdog restart (2026-06-03 incident). Mitigation: reload ONLY the ZM entry. Explicit assertion in D2: `assert zm_entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ZONE_MANAGER` before calling reload.
5. **Legacy `ENTRY_TYPE_ZONE` entry** — if any legacy zone entries survive (pre-v3.3.5.4 migration), the delete flow's ZM-only path silently skips them. Mitigation: at menu render, detect legacy-entry mode and either surface HA's native "Delete" affordance on that entry OR extend D2 to handle both shapes. Recommend: detect + refuse with a clear message pointing to HA's native delete, since the operator's house is already ZM-only.
6. **User Lovelace / automations referencing deleted entities** — HA will show unavailable entities in dashboards; not URA's job to rewrite. Mitigation: the D1 confirm-screen body should mention "Any dashboard cards or automations referencing this zone's sensors will show as unavailable and should be updated."
