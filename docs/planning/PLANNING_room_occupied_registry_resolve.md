# PLANNING: room entities resolved through the registry (ROOM-OCCUPIED-ENTITY-REGISTRY-RESOLVE-1)

Card: ROOM-OCCUPIED-ENTITY-REGISTRY-RESOLVE-1 (parent REGISTRY-NOT-NAMES-1, cluster C5 of
`AUDIT_registry_not_names_sweep_2026_11_13.md`). Written 2026-11-13 on develop @ ce226e25. Plan only, no code.

Mandatory reading done, completely: `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` (incl. §4.2b fan ownership,
§10 ledger), `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (incl. §4.5 room-switch resolver, §10 ledger),
`docs/architecture/SENSOR_FLEET_CLASSES.md`. Nothing here re-asserts a ledger claim. This plan touches no sensor class,
occupancy producer, HVAC decision or write site; it changes how readers FIND a room's own entity.

## 0. Contradictions with the brief (code and live data win)

1. **10 rooms miss today, not 11.** The audit's 11 counted the plain `lower().replace(" ","_")` slug. The two
   `binary_sensor.*_occupied` readers in `hvac_fans.py` use `memory_facade._slugify` (punctuation-safe since v5.51.0
   M-1), so Ziri Bedroom (Bedroom 5) resolves and 10 rooms miss for them. `memory_baseline` / `memory_facade` use the
   same slug. Either way the defect class is the same.
2. **"Fan-off guard holds in Foyer" cannot be a Live criterion.** Foyer has no fan (room options `fans` empty,
   Fan Mode Off, hallway). Of the 10 miss rooms only Guest Bedroom 2, Jaya Bedroom and Media have fans, and none is
   HVAC-owned (Fan Modes: off, room_temperature, off). The guard at `hvac_fans.py:1886` only sits on HVAC-tier OFF
   writes, so **today's live fan harm in the 10 rooms is nil**; the guard is armed-but-blind and would fail open the
   day one of them is set to Follow thermostat. The live fan criterion is therefore a resolution check plus an
   in-suite guard test, and the measurable live delta is the memory baseline (Jaya, below).
3. **The blind spot reaches temperature and humidity too.** Live registry: 7 rooms' `sensor.*_temperature` and 12
   rooms' `sensor.*_humidity` differ from the slug, and 9 rooms' `sensor.*_unavailable_entities`. Jaya Bedroom is in
   `MEMORY_BASELINE_ALLOWLIST` (`const.py:6013-6019`) and misses all three signals, so it learns no baseline at all.

## 1. Institutional context verified

**Greps run (develop, `custom_components/universal_room_automation/`):**
`grep -rnE "f[\"'](binary_sensor|sensor|switch|select|number|button|fan|light|media_player)\.\{[^}]*(slug|room|name|location|area|rid)"`,
`grep -rn "_occupied\"|_unavailable_entities|_hvac_occupied\"|_presence\")"`, `grep -n unique_id entity.py`,
`grep -rn _resolve_room_switch_entity_id`, `grep -rn _read_room_occupied_state`.

**Independent enumeration: every reader that builds a ROOM-derived entity id** (the brief's list was a hypothesis):

| # | Site | Builds | Consumer class | Verdict |
|---|---|---|---|---|
| R1 | `domain_coordinators/hvac_fans.py:1714-1730` `_read_room_occupied_state` via `_resolve_room_occupied_slug` `:1621` | `binary_sensor.{slug}_occupied` | COMFORT trust: OFF guard `:1886` | MIGRATE |
| R2 | `hvac_fans.py:2025-2034` `_record_actuation_conflict_if_occupied` | same | memory episode write | MIGRATE (same call as R1) |
| R3 | `memory_baseline.py:117-140` `_room_samples` | `_occupied`, `sensor.{slug}_temperature`, `_humidity` | baseline learning (feeds NM conditioning) | MIGRATE |
| R4 | `memory_facade.py:580-600` `_resolve_live_sample` | `_occupied`, `sensor.{slug}_{signal}` | live z-score (`unusual`) | MIGRATE |
| R5 | `domain_coordinators/notification_manager.py:1820-1826` | `sensor.{location_slug}_{signal}` (humidity/co2/tvoc) | NOTIF conditioning | MIGRATE when `location` names a room; else unchanged |
| R6 | `fan_veto.py:384-405` | registry first (room matched by `room_name` or `title`), slug fallback `:405` | COMFORT (AWAY veto) | MIGRATE: drop slug fallback, use shared resolver |
| R7 | `coordinator.py:3168-3214` `_resolve_room_switch_entity_id` | registry first, slug fallback `:3197-3198` | room switch gates | MIGRATE fallback only |
| R8 | `switch.py:90-101` `_room_switch_entity_id` | delegates to R7, slug fallback `:100-101` | override mutual exclusion | MIGRATE fallback only |
| R9 | `house_status.py:400-412` | `async_get_entity_id("sensor", DOMAIN, f"{entry_id}_unavailable_entities")` | display | ALREADY COMPLIANT (pattern to reuse) |
| R10 | `__init__.py:704` `uid.endswith("_hvac_occupied")` | unique_id test on own registry rows | migration | OWN (reads unique_id, not a guess) |

Out of scope with owner: `music_following.py:1166,1220,1265` (media player and area by name, not a room-owned entity;
REGISTRY-NOT-NAMES-1 C5 music, use `area_id`), `person_coordinator.py:1797-1853` (BLE-PERSON-SENSOR-REGISTRY-RESOLVE-1),
`camera_census.py` / `perimeter_alert.py:5318` (NVR-WITNESS-CONSOLIDATION-1 / C2). Node ids `room:<slug>` in
memory writers (`memory_facade.py:235-247`, `memory_writers.py:73`) are URA-owned KEYS, not entity lookups: OWN.

**REUSE / NEW per piece:**
- unique_id contract: REUSED `entity.py:34` `f"{coordinator.entry.entry_id}_{entity_type}"`; occupied key REUSED
  `binary_sensor.py:294` (`"occupied"`), temperature/humidity `sensor.py:735`, `:774`.
- Registry lookup pattern: REUSED `coordinator.py:3184-3195`, `house_status.py:408`, `fan_veto.py:390-398`.
- Room-name to entry match: REUSED shape of `hvac_fans._room_coord` `:1296-1310` (entry scan by `CONF_ROOM_NAME`).
- **NEW** module `room_entities.py` with `room_entry_id_for_name(hass, room_name)`, `room_entry_id_for_slug(hass, slug)`,
  `resolve_room_entity_id(hass, entry_id, domain, key)`. NEW because the three registry copies above are private to
  their callers and each re-implements entry matching (fan_veto also matches `title`, coordinator matches nothing).
- **NEW** counter `room_entity_resolve_misses` (dict `(entry_id, key) -> count`) in the same module; no new entity.
- No new CONF_*, signal, sensor or DB column.

**Prior plans / memory / design docs:** `AUDIT_registry_not_names_sweep_2026_11_13.md` (full), card text of
REGISTRY-NOT-NAMES-1 and this card, PRESENCE §4.5 + §10 #4 (ROOM-SWITCH-LOOKUP-BY-NAME-1, 2026-10-10, the precedent),
HVAC §4.2b (Fan Mode owner rule), v5.51.0 M-1 note in `memory_facade.py:247-258`. Memory: Registry-not-names rule in
CLAUDE.md, `feedback_hollow_test_anchors`, `feedback_wire_in_anchor_mandatory`.

**Config-first:** no setting fixes this. Renaming 10 entity_ids in HA to the slug form would "fix" it until the next
rename and is the name-guessing the operator ruled out.

## 2. Falsifiable invariant

**INV-RE:** for every URA room config entry E and every key K in {occupied, temperature, humidity,
unavailable_entities}, every reader in §1 (R1-R8) that looks up E's own K entity obtains exactly
`entity_registry.async_get_entity_id(domain(K), DOMAIN, f"{E.entry_id}_{K}")`, and never an id built from the room
name, for all 47 live rooms and for a room whose entity_id or room name was changed after setup. A registry miss
yields None (the reader's existing unavailable path) and increments the miss counter; it never yields a built id.

Break it by: a reader that still formats `f"<domain>.{...}_{K}"`; a reader that matches the room by `title` where
another matches by `room_name` (Jaya: title "Jaya Bedroom (Bedroom 4)", room_name "Jaya Bedroom"); a cache that keeps
an old id after a rename.

## 3. Producer and consumer checks

**Producer (the room's entity_id):** HA assigns it at registration from the device name plus the entity name, so it
is not derivable from `room_name` (double-prefix on new rooms; operator renames). The durable identity is the
unique_id, set by URA (`entity.py:34`). Dependency health: all 47 rooms have a registry row for `_occupied`
(0 missing, read from `.storage/core.entity_registry` 2026-11-13); `room_name` in options never differs from data
(0 of 47); one room's title differs from its room_name (Jaya).

**Fire check (live, read-only, 2026-11-13):**
- Resolution today vs after: `_occupied` by slug 37/47, by registry 47/47; temperature 40/47 vs 47/47; humidity 35/47
  vs 47/47; unavailable_entities 38/47 vs 47/47.
- The guard has fired: `memory_episodes` `actuation_conflict` 5,494 rows since 2026-08-03 (master_bedroom 2,746,
  study_a 1,438, living_room 697, ...). For the 10 miss rooms the last row is `room:jaya_bedroom_bedroom_4` on
  2026-08-11 (9 rows, written under an older title-based slug); 0 rows since in any miss room. This is the
  zero-fire signature the plan fixes.
- Memory baseline: Jaya Bedroom (allowlisted) samples 0 of 3 signals today.

**Consumers (forward trace):** R1 suppresses an HVAC-tier OFF (`hvac_fans.py:1886-1895`, trust); R2 writes the
conflict episode (observability); R3 learns the baselines that R5 conditioning and R4 `unusual` read (NOTIF trust,
display); R6 is the comfort-fan AWAY veto (trust); R7/R8 gate room automation (trust). Policy stays in each consumer:
the resolver returns an id or None and decides nothing.

## 4. Deliverables

### D1: `room_entities.py` resolver
Pure HA-registry helpers as named in §1. `resolve_room_entity_id` does one `er.async_get(hass).async_get_entity_id`
call, no slug fallback, no cache (the registry is a dict lookup and is updated on rename, so no cache means no stale
id). `room_entry_id_for_name` matches merged `data`+`options` `CONF_ROOM_NAME` exactly (one rule, used by every
caller; `title` is NOT matched). `room_entry_id_for_slug` matches `memory_facade._slugify(room_name)` against the
memory node slug (URA-owned key). Miss: counter +1 and one WARN per `(entry_id, key)` on the second consecutive miss
(the first-refresh race rule of `coordinator.py:3203-3208`). Never raises.
#### Acceptance Criteria
- **Verify:** for the live fixture, resolved id == registry id for all 47 rooms x 4 keys (188 lookups); a slug
  oracle on the same fixture gets 37/47 occupied, so the test discriminates.
- **Verify:** a fixture room whose entity_id was renamed after setup resolves the new id; a room whose room_name was
  changed in options resolves by the new name and not the old.
- **Test:** `test_room_entities.py::test_live_47_room_fixture_all_keys`, `::test_renamed_entity_id`,
  `::test_renamed_room_name`, `::test_title_not_matched`, `::test_miss_counts_and_warns_once`.
- **Live:** none on its own (D2-D4 carry it).

### D2: HVAC fan guard and conflict observer (R1, R2)
`_read_room_occupied_state` and `_record_actuation_conflict_if_occupied` resolve via D1 (`room_entry_id_for_name` then
key `occupied`), sharing one private helper so guard and observer cannot disagree. Fail-open on None is unchanged.
`_resolve_room_occupied_slug` keeps only its node-id role (episode `node_id` unchanged: non-goal).
#### Acceptance Criteria
- **Verify:** with a registry row `binary_sensor.foyer_foyer_occupied` = on and NO `binary_sensor.foyer_occupied`, an
  HVAC-tier OFF for a Follow-thermostat fan in that room is suppressed and one `actuation_conflict suppressed=True`
  row is written; under the old code the same fixture writes the OFF (discriminating).
- **Verify:** registry miss leaves today's fail-open path (OFF proceeds, no row).
- **Test:** `test_occupied_fan_off_guard.py` (existing tests move to registry fixtures; add
  `::test_guard_uses_registry_not_slug_foyer`, `::test_observer_agrees_with_guard_jaya_title`). Mutation: restore the
  slug read at `:1723` and the Foyer test must fail.
- **Live:** for Jaya Bedroom, Guest Bedroom 2, Media and Foyer, an HA template / `ha_eval_template` call of the
  resolver path (or the diagnostics dump in D5) returns the registry id and its live state; no `room_entity_resolve`
  WARN in the log after boot.

### D3: memory baseline, live sample and NM conditioning (R3, R4, R5)
`_room_samples` and `_resolve_live_sample` take the node slug, map it with `room_entry_id_for_slug`, and resolve
`occupied` / `temperature` / `humidity` (and `{signal}` for R4) through D1. R5 maps `location` with
`room_entry_id_for_name`; a location that names no room keeps today's path (location derivation belongs to C7).
#### Acceptance Criteria
- **Verify:** fixture: Jaya Bedroom samples 3 of 3 signals (old code 0 of 3); Study A unchanged (byte-identical
  samples).
- **Test:** `test_memory_baseline_room_resolve.py::test_jaya_samples_all_signals`, `::test_resolving_rooms_unchanged`;
  `test_memory_facade_live_sample.py::test_registry_id_for_renamed_room`; NM: `::test_conditioning_reads_registry_humidity`.
- **Live:** within one baseline write cycle after restart, the memory baseline store shows rows for node
  `room:jaya_bedroom` with signals occupied, temperature, humidity (zero today). Query the URA DB baselines table for
  that node; zero rows after two cycles = FAIL.

### D4: drop the slug fallbacks in the existing registry readers (R6, R7, R8)
`fan_veto` fused-sensor lookup, `coordinator._resolve_room_switch_entity_id` and `switch._room_switch_entity_id` call
D1. R7 keeps its own per-suffix cache only while `hass.states.get(cached)` exists (today's guard); the slug fallback
lines `coordinator.py:3196-3202`, `switch.py:100-101`, `fan_veto.py:399-405` are deleted. R6 stops matching `title`.
#### Acceptance Criteria
- **Verify:** fixture with registry rows only: switches, fused sensor resolve; with the registry row absent the gate
  takes its existing None semantics (no built id read).
- **Test:** existing `test_room_switch_lookup*` and fan-veto tests re-pointed to registry fixtures;
  `::test_no_slug_fallback_on_miss`.
- **Live:** every room's Automation switch OFF still pauses the room (spot check one double-prefix room, e.g. Master
  Closet, by toggling its switch off and seeing `skipped_paused` in the log, then back on).

### D5: miss trip-wire
`room_entity_resolve_misses` is surfaced as an attribute of the existing house-status Field list
(`house_status.py:400-423`, the "rooms reporting" block); builder verifies the entity it renders on. Steady state is 0.
A non-zero value that persists past the boot window (600 s) dispatches one stuck-signal NM per day (REUSE
`fire_stuck_signal`, `kind=room_entity_unresolved`).
#### Acceptance Criteria
- **Verify:** a fixture with one missing registry row produces 1 NM in a day, not one per tick.
- **Test:** `test_room_entities.py::test_trip_wire_once_per_day`, `::test_no_page_in_boot_window`.
- **Live:** attribute reads 0 one hour after restart.

## 5. Knobs

None new. No behavioural number is introduced: the WARN threshold (second miss) and boot window reuse
`coordinator.py:3206-3208` and the existing 600 s boot window constant used by presence. Kill switch: none; the
change replaces a lookup and a kill switch would reinstate name guessing, which the operator ruled out.

## 6. Non-goals

- No change to occupancy, the guard's exemptions, Fan Mode ownership, HVAC decisions or any write site.
- Memory node ids `room:<slug>` and episode `node_id` values are not renamed or migrated.
- No change to how NM derives a hazard `location` (C7) or to music following (C5 music, sibling card).
- No CI AST guard here (REGISTRY-NOT-NAMES-1 owns it; this plan only removes these sites from its allowlist).
- No entity_id renames in HA.

## 7. Tier

**Tier 2, not Tier 2-DB.** No schema, DAO or payload change; no state machine; no shared write primitive; the only
behaviour change is that readers find the right entity. The HVAC ripple is bounded by fact §0.2: no miss room is
HVAC-fan-owned today, so the guard change has no live actuation delta at ship; the risk is regression in the 37
rooms that resolve today, which D2's byte-identical test covers. Reviews: one plan review (completeness + goal
fidelity G), then two build reviews, A = correctness and edge cases (entry match, title vs name, None paths, all 8
sites), B = lifecycle and HVAC semantics (first-refresh race, reload, guard and observer agreement, tests on a real
registry, no fake coordinator). Builder and reviewers read the HVAC state of play first (card rule).

## 8. Test fixture

`quality/tests/fixtures/room_registry_live_2026_11_13.json`: for each of the 47 room entries, `entry_id` (redacted to
a stable hash), `room_name`, `title`, and the registry `entity_id` for the 4 keys, generated read-only from
`.storage/core.entity_registry` + `core.config_entries` (no secrets; no options beyond room_name). Tests load it into a
real `entity_registry` via pytest-homeassistant-custom-component, never a fake coordinator (v5.8.0 incident). Plus
two synthetic rooms: entity_id renamed after setup, and room_name changed in options.

## 9. Plan completion tracking (filled at ship)

| Item | Done / deferred | Why | Tracked |
|---|---|---|---|
| D1-D5 | | | |
| Music following area_id (out of scope) | deferred | not a room-owned entity | REGISTRY-NOT-NAMES-1 C5 |
| HVAC state of play update | at ship | §4.2b guard note gains "occupied entity resolved by registry" | same commit |
| PRESENCE state of play §4.5 | at ship | resolver no longer has a slug fallback | same commit |
