# PLANNING: room entities resolved through the registry (ROOM-OCCUPIED-ENTITY-REGISTRY-RESOLVE-1)

Card: ROOM-OCCUPIED-ENTITY-REGISTRY-RESOLVE-1 (parent REGISTRY-NOT-NAMES-1, cluster C5 of
`AUDIT_registry_not_names_sweep_2026_11_13.md`). Priority lowered: the live harm is small (§0.2), so the plan stays lean.
Rev 2, 2026-11-14, on develop @ 3ec3f4d2 (includes read API ship 1 `person_ids.py` and stream health S1; neither
touches these sites). It folds in every finding of `docs/reviews/plan-review/PLANREVIEW_room_occupied_registry_resolve.md`
(F1-F8 and the three-build-review recommendation). Plan only, no code.

Mandatory reading done, completely: `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` (incl. §4.2b fan ownership,
§10 ledger), `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (§4.5 room-switch resolver, §10 ledger),
`docs/architecture/SENSOR_FLEET_CLASSES.md`. Nothing here re-asserts a ledger claim. The plan touches no sensor class,
occupancy producer, HVAC decision or write site. It changes how readers find a room's own entity.

## 0. Facts that shape the plan (code and live data win)

1. **10 rooms miss today.** The `hvac_fans` and memory readers slug with `memory_facade._slugify` (`memory_facade.py:247`),
   so `binary_sensor.{slug}_occupied` misses in 10 of 47 rooms (Guest Bedroom 1 Bathroom, Guest Bedroom 2, Jaya Bedroom,
   Media, Master Bath Toilet, Master Hallway, Up Guestbedroom Closet, Guest Bedroom 2 Hallway, Foyer, Master Closet).
   Re-derived by the plan review from the live registry.
2. **Live fan harm today is nil.** The occupied guard (`hvac_fans.py` OFF path, read at `:1714-1723`) only sits on HVAC-tier
   OFF writes (HVAC §4.2b: Fan Mode Follow thermostat only). Of the 10 miss rooms only Guest Bedroom 2, Jaya Bedroom and
   Media have fans, and none is HVAC-owned. The guard is armed but blind and would fail open the day one of them is set
   to Follow thermostat.
3. **The measurable live delta is the memory baseline.** Slug resolution: temperature 40/47, humidity 35/47,
   unavailable_entities 38/47. Jaya Bedroom is in `MEMORY_BASELINE_ALLOWLIST` and samples 0 of 3 signals, so it learns
   no baseline at all.

## 1. Institutional context verified

**Greps run on develop @ 3ec3f4d2 (`custom_components/universal_room_automation/`):**
`grep -rnE "f[\"'](binary_sensor|sensor|switch)\.\{[^}]*(slug|room|name|location)"`, `grep -rn async_get_entity_id`,
`grep -n unique_id entity.py`, `grep -n "_get_room_switch_state(\"" coordinator.py`, `grep -n "co2\|tvoc" sensor.py
notification_manager.py`, `grep -n BOOT_WINDOW const.py`, `grep -n metric_baselines database.py`.

**Every reader that builds or looks up a room's own entity** (re-run independently; the review's list was re-checked):

| # | Site (develop @ 3ec3f4d2) | Keys read | Holds the entry? | Consumer class | Verdict |
|---|---|---|---|---|---|
| R1 | `domain_coordinators/hvac_fans.py:1714-1723` `_read_room_occupied_state`, slug from `_resolve_room_occupied_slug` `:1621` | occupied | no today (keyed by room name, `_room_fans` `:464`); YES after D2 carries `entry_id` on `RoomFanState` | COMFORT trust: HVAC OFF guard | MIGRATE |
| R2 | `hvac_fans.py:2001-2032` `_record_actuation_conflict_if_occupied` | occupied | same as R1 | memory episode write | MIGRATE (same helper as R1) |
| R3 | `memory_baseline.py:117-140` `_room_samples` | occupied, temperature, humidity | no (memory node slug) | baseline learning | MIGRATE via slug map |
| R3b | `memory_baseline.py:56-80` `_is_room_suppressed` (quality gate, matches `coord.room_name` by slug) | none (coordinator match) | no | baseline quality gate | MIGRATE onto the SAME slug map as R3 (F7) |
| R4 | `memory_facade.py:579-600` `_resolve_live_sample` | occupied, temperature, humidity | no (node slug) | live z-score (`unusual`) | MIGRATE via slug map |
| R5 | `domain_coordinators/notification_manager.py:1802-1826` | humidity; co2, tvoc | no (hazard `location` string) | NOTIF conditioning | humidity MIGRATE via name map; co2/tvoc see D3 |
| R6 | `fan_veto.py:384-405` | camera_person_detected | caller passes `CONF_ROOM_NAME` | COMFORT (AWAY veto) | MIGRATE: drop slug fallback `:405` and the `title` match |
| R7 | `coordinator.py:3329-3375` `_resolve_room_switch_entity_id` | automation, ai_automation, cover_automation, manual_mode, override_occupied, override_vacant | YES (`self.entry`) | room switch gates | MIGRATE: delete slug fallback `:3359-3363`, pass `entry_id` |
| R8 | `switch.py:88-101` `_room_switch_entity_id` (callers `:5445`, `:5483`) | override_occupied, override_vacant | YES (`coordinator.entry`) | override mutual exclusion | MIGRATE: delete fallback `:100-101` |
| R9 | `house_status.py:408` | unavailable_entities | YES | display | ALREADY COMPLIANT (pattern to reuse) |
| R10 | `domain_coordinators/presence.py:6189-6192` `_discover_guest_rooms` | occupied | YES (entry loop) | guest D5 trust | ALREADY COMPLIANT (F4). Migrate onto D1 in the same build: one-line call, one miss rule |
| R11 | `domain_coordinators/_ble_corroboration.py:46-56` | (unique_id from caller) | YES | presence corroboration | ALREADY COMPLIANT; no slug fallback; left as is (different module owner, no behaviour gain) |

Out of scope, with owner: `music_following.py` (media player / area by name, REGISTRY-NOT-NAMES-1 C5 music),
`person_coordinator.py` (BLE-PERSON-SENSOR-REGISTRY-RESOLVE-1), `camera_census.py` / `perimeter_alert.py` /
`optimization.py` camera ids (C2 / NVR-WITNESS-CONSOLIDATION-1), `button.py:396-459` (export file names). Memory node
ids `room:<slug>` (`memory_facade.py:235-247`, `memory_writers.py:73`, `fan_veto.py:562`) are URA-owned keys, not entity
lookups: OWN.

**REUSE / NEW per piece:**
- unique_id contract: REUSED `entity.py:34` `f"{coordinator.entry.entry_id}_{entity_type}"`. Keys: occupied
  `binary_sensor.py:294`, temperature `sensor.py:735`, humidity `sensor.py:774`, unavailable_entities `sensor.py:1819`.
  Trap: Sensor Presence keeps key `presence` (`binary_sensor.py:828`), not its display name.
- Registry lookup: REUSED pattern of `house_status.py:408`, `presence.py:6189-6192`, `coordinator.py:3350`,
  `fan_veto.py:392-396`, `_ble_corroboration.py:51`.
- Room-name to entry match: REUSED shape of `hvac_fans._room_coord` `:1296` (entry scan by `CONF_ROOM_NAME`).
- **NEW** module `room_entities.py`: `resolve_room_entity_id(hass, entry_id, domain, key)`,
  `room_entry_id_for_name(hass, room_name)`, `room_entry_id_for_slug(hass, slug)`. NEW because the five registry copies
  above are private to their callers and each matches entries its own way (fan_veto also matches `title`).
- **NEW** counter `room_entity_resolve_misses` (dict `(entry_id or name, key) -> count`) in the same module, plus a
  separate `room_entity_name_fallback_reads` counter for D3's one fallback. No new entity, CONF_*, signal, sensor or DB
  column.
- Boot window: REUSED `RESIDENT_RETURN_BOOT_WINDOW_S` (`const.py:4039`, 600 s).
- Trip-wire NM: REUSED `fire_stuck_signal` (`domain_coordinators/_stuck_signal_nm.py:165`).
- Baseline store: REUSED `metric_baselines` via `upsert_memory_baseline` (`database.py:10892`).

**Prior plans / memory / design docs:** the audit above (full), card text of REGISTRY-NOT-NAMES-1 and this card, the plan
review (full), PRESENCE §4.5 + §10 #4 (ROOM-SWITCH-LOOKUP-BY-NAME-1, the precedent), HVAC §4.2b, CLAUDE.md "Registry,
never name guessing" (2026-11-13), memory `feedback_hollow_test_anchors`, `feedback_wire_in_anchor_mandatory`.

**Config-first:** no setting fixes this. Renaming 10 entity_ids in HA to the slug form is the name guessing the operator
ruled out, and breaks again at the next rename.

## 2. Falsifiable invariant

**INV-RE:** for every URA room config entry E and every key K that URA registers under unique_id `f"{E.entry_id}_{K}"`,
every reader R1-R10 that looks up E's own K entity obtains exactly
`entity_registry.async_get_entity_id(domain(K), DOMAIN, f"{E.entry_id}_{K}")`, and never an id built from the room name,
title or slug. This holds for all 47 live rooms and for a room whose entity_id or room name was changed after setup. A
registry miss yields None (each reader's existing unavailable path) and increments `room_entity_resolve_misses`; it never
yields a built id. Keys per reader:

| Reader | K |
|---|---|
| R1, R2, R10 | occupied |
| R3, R4 | occupied, temperature, humidity |
| R5 | humidity |
| R6 | camera_person_detected |
| R7 | automation, ai_automation, cover_automation, manual_mode, override_occupied, override_vacant |
| R8 | override_occupied, override_vacant |

Where the reader holds the entry (R7, R8, R10, and R1/R2 after D2), it passes `entry_id` directly; there is no name hop.
The single permitted string-built read is D3's R5 co2/tvoc fallback, which is NOT a room-owned key (no URA sensor
registers `co2` or `tvoc`) and is counted and logged.

Break it by: a reader that still formats `f"<domain>.{...}_{K}"`; a reader that matches a room by `title` where another
matches by `room_name` (Jaya: title "Jaya Bedroom (Bedroom 4)", room_name "Jaya Bedroom"); a cached id that outlives a
rename; a caller holding the entry that still resolves by name (after a rename and before reload, the old name maps to
None and the guard fails open); two rooms whose names slug the same ("Study-A", "Study A") mapped to the first match.

## 3. Producer and consumer checks

**Producer (the room's entity_id):** HA assigns it at registration from device name plus entity name, so it is not
derivable from `room_name` (double prefix on new rooms; operator renames). The durable identity is the unique_id, set by
URA (`entity.py:34`). Dependency health (live registry, re-derived by the plan review): every room has a row for all 4
learned keys (47/47); 0 duplicate room_names; options room_name never differs from data; 1 title differs from room_name
(Jaya). Name uniqueness is case-insensitive on the raw string (`config_flow.py:2197`, `:12432-12438`), not on slug output.

**Fire check (live, read-only, 2026-11-13):**
- Resolution by slug vs registry: occupied 37/47 vs 47/47; temperature 40 vs 47; humidity 35 vs 47; unavailable_entities
  38 vs 47. Switches (R7/R8) 47/47 both ways, so their fallback deletion has no live delta.
- The guard has fired: `memory_episodes` `actuation_conflict` 5,494 rows since 2026-08-03; in the 10 miss rooms the last
  row is 2026-08-11 (Jaya, under an older title slug) and 0 since. That is the zero-fire signature this fixes.
- Memory baseline: Jaya Bedroom samples 0 of 3 signals.

**Consumers (forward trace):** R1 suppresses an HVAC-tier OFF (trust); R2 writes the conflict episode; R3 learns the
baselines R4 `unusual` and R5 conditioning read; R3b decides whether a sample is kept; R6 is the comfort-fan AWAY veto;
R7/R8 gate room automation; R10 arms guest D5 rooms. Policy stays in each consumer: the resolver returns an id or None
and decides nothing.

## 4. Deliverables

### D1: `room_entities.py` resolver
- `resolve_room_entity_id(hass, entry_id, domain, key)`: one `er.async_get(hass).async_get_entity_id` call. No slug
  fallback, no cache (the registry is a dict and follows renames).
- `room_entry_id_for_name(hass, room_name)`: exact match on merged `data`+`options` `CONF_ROOM_NAME`. `title` is never
  matched. Used only by callers that hold no entry (R5).
- `room_entry_id_for_slug(hass, slug)`: matches `memory_facade._slugify(room_name)` against the memory node slug.
  **Tie rule (F7):** if two or more room entries slug to the same value, return None and count a miss keyed
  `("slug_ambiguous:" + slug, "*")`; never pick the first match. Used by R3, R3b, R4.
- Miss: counter +1; one WARN per `(entry_id, key)` on the second consecutive miss (the first-refresh race rule of
  `coordinator.py:3365-3372`). Never raises.

#### Acceptance criteria
- **Verify:** on the live fixture, resolved id == registry id for all 47 rooms x 4 learned keys (188 lookups); a slug
  oracle on the same fixture gets 37/47 occupied, so the test discriminates.
- **Verify:** a fixture room whose entity_id was renamed after setup resolves the new id; a room renamed in options
  resolves by the new name only; two rooms slugging alike return None from `room_entry_id_for_slug` and count one miss.
- **Test:** `test_room_entities.py::test_live_47_room_fixture_all_keys`, `::test_renamed_entity_id`,
  `::test_renamed_room_name`, `::test_title_not_matched`, `::test_slug_tie_returns_none`,
  `::test_miss_counts_and_warns_once`.
- **Live:** carried by D2 and D5.

### D2: HVAC fan guard and conflict observer (R1, R2)
`RoomFanState` gains `entry_id`, filled where `_room_fans` is populated (`hvac_fans.py:464`, from the room entry already
being scanned). `_read_room_occupied_state` and `_record_actuation_conflict_if_occupied` share one private helper that
calls `resolve_room_entity_id(hass, room_fan.entry_id, "binary_sensor", "occupied")`, so guard and observer cannot
disagree and a rename before reload cannot fail the guard open. Fail-open on None is unchanged.
`_resolve_room_occupied_slug` keeps only its episode `node_id` role (non-goal to rename).

#### Acceptance criteria
- **Verify:** with registry row `binary_sensor.foyer_foyer_occupied` = on and no `binary_sensor.foyer_occupied`, an
  HVAC-tier OFF for a Follow-thermostat fan in that room is suppressed and one `actuation_conflict suppressed=True` row is
  written. Old code writes the OFF and no row (discriminating).
- **Verify:** a room renamed in options with no reload yet still resolves (by `entry_id`); old code and a name-based
  resolver both fail open.
- **Verify:** registry miss leaves today's fail-open path (OFF proceeds, no row).
- **Test:** `test_occupied_fan_off_guard.py` (existing tests moved to registry fixtures) plus
  `::test_guard_uses_registry_not_slug_foyer`, `::test_observer_agrees_with_guard_jaya_title`,
  `::test_guard_survives_rename_before_reload`. Mutation: restore the slug read at `:1723` and the Foyer test fails.
- **Live (F3):** at boot the resolver logs one INFO line `room_entities: resolved occupied for N/N fan rooms` and lists
  the ids for the 10 rooms of §0.1. Pass = it names `binary_sensor.foyer_foyer_occupied`-style registry ids (old code
  would have read the slug ids, which do not exist) and N/N. No `room_entity_resolve` WARN after the boot window.

### D3: memory baseline, quality gate, live sample, NM conditioning (R3, R3b, R4, R5)
- R3, R4: map the node slug with `room_entry_id_for_slug`, then resolve occupied / temperature / humidity through D1.
- R3b: `_is_room_suppressed` finds its coordinator through the same slug map (entry_id → room coordinator), so the gate
  and the sampler always agree on which room a slug is.
- **Scope (F2):** D1 lookups cover only the learned keys {occupied, temperature, humidity}. `_resolve_live_sample` is
  never asked for `co2` / `tvoc` by D1; those signals are not URA room entities and are never counted as resolver
  misses.
- R5 humidity: map `location` with `room_entry_id_for_name`, resolve key `humidity` through D1.
- **R5 co2/tvoc and non-room locations (F6):** the existing `sensor.{location_slug}_{signal}` read stays only as a
  named last-resort fallback. Each use logs one DEBUG line with the built id and increments
  `room_entity_name_fallback_reads` (kept separate from the miss counter so it never trips D5). This is the CLAUDE.md
  "logged, counted last-resort fallback" form. Baselines for co2/tvoc are never learned today (`memory_baseline.py:117-140`),
  so `facade.baseline` returns `insufficient_history` and the fallback is in practice not reached; the counter proves that
  live. **Operator yes required before build:** keep this counted fallback, or remove it (no room → no conditioning).
  Default if no answer: keep it counted. Reading the room's configured co2/tvoc sensor from the entry is parked under
  REGISTRY-NOT-NAMES-1 C7 (NM location derivation), revival trigger: a room gets a configured co2/tvoc sensor.

#### Acceptance criteria
- **Verify:** fixture: Jaya Bedroom samples 3 of 3 signals (old code 0 of 3); Study A samples are byte-identical.
- **Verify:** a slug tie leaves both rooms unsampled and the gate unsuppressed, never cross-attributed.
- **Verify:** an NM `high_co2` hazard does not increment `room_entity_resolve_misses`; it increments
  `room_entity_name_fallback_reads` only when a co2 baseline exists.
- **Test:** `test_memory_baseline_room_resolve.py::test_jaya_samples_all_signals`, `::test_resolving_rooms_unchanged`,
  `::test_quality_gate_uses_same_slug_map`; `test_memory_facade_live_sample.py::test_registry_id_for_renamed_room`;
  `test_nm_conditioning_resolve.py::test_humidity_reads_registry_id`, `::test_co2_fallback_counted_not_missed`.
- **Live:** within two baseline write cycles after restart, `metric_baselines` holds rows for node `room:jaya_bedroom`
  with metrics occupied, temperature and humidity (zero today; old code still zero). Zero rows after two cycles = FAIL.

### D4: drop the slug fallbacks in the existing registry readers (R6, R7, R8, R10)
- R7 calls `resolve_room_entity_id(hass, self.entry.entry_id, "switch", suffix)`; it keeps its per-suffix cache only
  while `hass.states.get(cached)` exists (today's guard); slug fallback `coordinator.py:3359-3363` deleted.
- R8 delegates to R7; fallback `switch.py:100-101` deleted.
- R6: fused-sensor lookup goes through D1; `title` matching and slug fallback `fan_veto.py:399-405` deleted. Where the
  caller's room coordinator is reachable, pass its `entry_id`; otherwise `room_entry_id_for_name` (all callers pass
  `CONF_ROOM_NAME`: `actuator_reconciler.py:218-220`, `automation.py:3229-3232`, `hvac_fans.py:923`, `:2364`).
- R10: `presence.py:6189-6192` calls `resolve_room_entity_id` with the entry it already holds (same result, shared miss
  rule).

#### Acceptance criteria
- **Verify:** fixture with registry rows only: switches, fused sensor and guest occupied ids resolve; with the row absent
  each gate takes its existing None semantics and no built id is read.
- **Test:** existing `test_room_switch_lookup*`, fan-veto and guest-discovery tests re-pointed to registry fixtures;
  `::test_no_slug_fallback_on_miss` per reader.
- **Live (F3):** pick the fan_veto lookup in a miss room, which changes: for Media (or Foyer), the AWAY veto's resolved
  `camera_person_detected` id equals the registry id in the D2 boot INFO line (D2's line also lists R6 ids for the 10
  rooms). Old code produced the slug id. The R7/R8 deletion has no live discriminator (47/47 both ways) and is proven
  in-suite only.

### D5: miss trip-wire
`room_entity_resolve_misses` (total and the top 5 `(room, key)` entries) is exposed as an attribute of the existing
house-status sensor that renders the `house_status.py:400-423` block; the builder names the entity it lands on. Steady
state 0. A non-zero total that persists past `RESIDENT_RETURN_BOOT_WINDOW_S` dispatches one `fire_stuck_signal`
(`kind=room_entity_unresolved`) per local day. `room_entity_name_fallback_reads` is shown alongside and never pages.

#### Acceptance criteria
- **Verify:** a fixture with one missing registry row produces 1 NM in a day, not one per tick, and none inside the boot
  window.
- **Test:** `test_room_entities.py::test_trip_wire_once_per_day`, `::test_no_page_in_boot_window`,
  `::test_fallback_reads_never_page`.
- **Live:** the attribute reads 0 one hour after restart.

## 5. Knobs

No new behavioural number. The WARN rule (second consecutive miss) reuses `coordinator.py:3365-3372`; the boot window
reuses `RESIDENT_RETURN_BOOT_WINDOW_S` (rung 1, `const.py:4039`, 600 s); the NM is once per local day like every other
`fire_stuck_signal` caller. No kill switch: the change replaces a lookup, and a kill switch would reinstate name
guessing, which the operator ruled out.

## 6. Non-goals

- No change to occupancy, the guard's exemptions, Fan Mode ownership, HVAC decisions or any write site.
- Memory node ids `room:<slug>` and episode `node_id` values are not renamed or migrated.
- No change to how NM derives a hazard `location` (C7) or to music following (C5 music).
- No co2/tvoc room sensor resolution beyond the counted fallback (parked, D3).
- No CI AST guard (REGISTRY-NOT-NAMES-1 owns it; this cycle removes these sites from its allowlist).
- No entity_id renames in HA. `_ble_corroboration.py` is not touched.

## 7. Tier and reviews

**Tier 2, not Tier 2-DB.** No schema, DAO or payload change (`metric_baselines` gains rows for one room through the
existing writer); no state machine; no shared write primitive. The HVAC ripple is bounded by §0.2. The failure mode is
one site still building an id, so the build gets **three reviews** (plan review recommendation):
- **A, correctness and edge cases:** entry match, title vs name, slug tie, None paths, every reader R1-R10, key list per
  reader.
- **B, lifecycle and HVAC semantics:** first-refresh race, reload and rename-before-reload, `RoomFanState.entry_id`
  population, guard and observer agreement, real registry in tests (no fake coordinator, v5.8.0 incident).
- **C, per-site source mutation (`ura-reviewer-mutation`):** for each of R1-R8 and R10, restore the old slug/name read
  and confirm a named test goes red, then restore and confirm a clean `git status`.
Builder and reviewers read the HVAC state of play first (card rule).

## 8. Test fixture

`quality/tests/fixtures/room_registry_live_2026_11_13.json`: for each of the 47 room entries, `entry_id` (stable hash),
`room_name`, `title`, and the registry `entity_id` for occupied, temperature, humidity, unavailable_entities,
camera_person_detected and the six switch keys, generated read-only from `.storage/core.entity_registry` +
`core.config_entries` (no secrets; no options beyond room_name). Tests load it into a real `entity_registry` via
pytest-homeassistant-custom-component. Plus three synthetic rooms: entity_id renamed after setup, room_name changed in
options, and a slug-tie pair.

## 9. Plan completion tracking (filled at ship)

| Item | Done / deferred | Why | Tracked |
|---|---|---|---|
| D1-D5 | | | |
| R5 co2/tvoc configured-sensor read | parked | not a room-owned entity; fallback counted | REGISTRY-NOT-NAMES-1 C7 |
| Music following area_id | out of scope | not a room-owned entity | REGISTRY-NOT-NAMES-1 C5 music |
| HVAC state of play | at ship | §4.2b guard note: occupied entity resolved by registry via `RoomFanState.entry_id` | same commit |
| PRESENCE state of play §4.5 | at ship | room-switch resolver has no slug fallback | same commit |
