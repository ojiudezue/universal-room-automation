# PLANNING — Cycle G1: Per-Room Control List Attributes (PWA M2 Prerequisite)

**Branch:** `develop` → feature branch `feature/g1-room-control-list-attrs`
**Tier classification:** **Tier 1 (Hotfix-scoped feature)** — see justification below.
**Consumers:** `~/Code/ura-dashboard-pwa` M2 (gap G1); future URA Lovelace dashboards; anyone
querying `sensor`/`binary_sensor` state via WS/REST.
**Non-goal:** no behavior change to actuation, no new entities, no options-flow additions,
no schema changes, no dispatcher signals.

---

## Problem

The PWA (see `~/Code/ura-dashboard-pwa/docs/planning/PLANNING_m2_control_completion.md`
gap G1) currently *guesses* a room's controllable entities by slugifying the room name and
pattern-matching against the entity registry. The operator has ruled this fragile and wants
it killed. Two examples where the guess breaks:

- AV Closet's actuator is `switch.switch_shelly1pmgen3_wifi_avcloset`, not
  `light.light01_light01` (per `CLAUDE.md` Troubleshooting section).
- Any room whose configured `lights` list points at a switch domain, a Shelly relay,
  or a friendly-name mismatch is unreachable by the slug heuristic.

URA already holds authoritative truth: the per-room config entry's `CONF_LIGHTS`,
`CONF_NIGHT_LIGHTS`, `CONF_FANS`, `CONF_HUMIDITY_FANS`, `CONF_COVERS`,
`CONF_CLIMATE_ENTITY` lists — the same lists URA actuates against
(`coordinator.py:831-837`). G1 publishes them as read-only attributes on an existing
per-room entity so the PWA (and every other consumer) reads the same truth URA acts on.

---

## Institutional context verified

### Prior art — attribute carrier (REUSE)

- **`custom_components/universal_room_automation/binary_sensor.py:219`** —
  `OccupiedBinarySensor` (unique_id `occupied`, one per room, always present) already
  has a live `extra_state_attributes` property at **line 363** that carries additive
  diagnostic attrs sourced live per read:
  - `fan_recheck_state`, `fan_recheck_last_outcome`, `fan_recheck_ble_ladder_layer`
    (lines 567-570) — sourced live via `hass.data[DOMAIN]["coordinator_manager"]`
    lookup with `try/except` defaults.
  - `substrate_kinds` (line 602) — v4.7.24 substrate unification cycle
    prior-art; per-tick read from the presence coordinator's substrate, per-key defaults
    on error so HA dev-tools never sees a missing key.
  This is the canonical additive-attr surface for per-room state and is the natural
  carrier for G1. **REUSE** — no new entity required.

### Prior art — live config reads (REUSE)

- **`custom_components/universal_room_automation/coordinator.py:346`** —
  `UniversalRoomCoordinator._get_config(key, default)` implements the HA-standard
  options-first-with-data-fallback pattern:
  ```python
  return self.entry.options.get(key, self.entry.data.get(key, default))
  ```
  Already the read path URA actuation uses (`coordinator.py:831-837` for
  `CONF_LIGHTS`/`CONF_FANS`/`CONF_CLIMATE_ENTITY`). **REUSE** — G1 reads through the
  same method so builder's emitted attrs cannot diverge from the actuator's ground truth.

### Prior art — options-flow live update (REUSE)

- **`custom_components/universal_room_automation/__init__.py:3599`** and multiple sites —
  `entry.async_on_unload(entry.add_update_listener(_async_update_listener))` is the
  standard reload-on-options-change path (`__init__.py:4975`).
- **`custom_components/universal_room_automation/coordinator.py:1128-1141`** — the
  coordinator also registers a direct `add_update_listener` (v4.2.24 hotfix). After an
  options-flow write, the coordinator's `entry.options` is refreshed **before** platforms
  are reloaded; because `extra_state_attributes` reads `self.entry.options` each call,
  no explicit push is needed — the next HA state poll (or the next
  `async_write_ha_state()` triggered by any tick) surfaces the new value.
- Belt-and-braces: `OccupiedBinarySensor` also gets state writes on every coordinator
  update via the standard `CoordinatorEntity` refresh, so an options edit that flips
  a light entity_id is visible on the attr within one coordinator tick (≤ dwell).

### CONFs — REUSE, all pre-existing

- `CONF_LIGHTS` — `const.py:481`
- `CONF_LIGHT_CAPABILITIES` — `const.py:482` (excluded from G1, opinion-only metadata)
- `CONF_FANS` — `const.py:483`
- `CONF_HUMIDITY_FANS` — `const.py:484`
- `CONF_COVERS` — `const.py:485`
- `CONF_NIGHT_LIGHTS` — `const.py:509`
- `CONF_CLIMATE_ENTITY` — `const.py:587`

**NEW additions:** ZERO. No new CONF_*, no new sensor, no new binary_sensor, no new
constant, no new signal. All prior art in place.

### Coordinator design doc

- `docs/Coordinator/COORDINATOR_ARCHITECTURE.md`, `docs/Coordinator/PRESENCE_COORDINATOR.md`
  — room-tier ownership boundary confirmed: room config entry data/options are the
  actuation source of truth; the presence coordinator does NOT own room actuator lists.
  Correct carrier is the room-owned `OccupiedBinarySensor`, not any presence-tier entity.

### Prior planning docs skimmed

- `docs/planning/` — `git status` shows no existing `PLANNING_g1_*` or `PLANNING_*pwa*`;
  glob `PLANNING_*g1*` returned zero. No naming collision.
- `docs/planning/PLANNING_zone_camera_person_only_guard.md` — unrelated, presence/camera
  scope.
- v4.7.24 substrate-unification memo (recall: "v4.7.24 substrate live") — pattern-source
  for the per-tick additive-attr with per-key defaults, adopted here verbatim.

### Memory bodies pulled

- `project_v4_7_24_substrate_unification_live` — carrier pattern (`extra_state_attributes`
  additive) and Bug Class #50 (subscription clobber). G1 does not subscribe, so #50 is
  not in the blast radius, but the pattern is the reference.
- `project_dashboarding_workstream_2026_07_13` — confirms the PWA at
  `~/Code/ura-dashboard-pwa v6.0.1` is the live consumer; custom WS client stays; HAKit
  rejected. G1 is a prerequisite for M2 control completion.

### Code locations surveyed end-to-end

- `binary_sensor.py:219-606` — `OccupiedBinarySensor` full body incl. attr assembly.
- `coordinator.py:346-356` (`_get_config`), `coordinator.py:820-840` (actuator list read
  sites we mirror).
- `const.py:478-590` — all G1-relevant CONF_ definitions.
- `__init__.py` update-listener registration sites (3105, 3255, 3491, 3599, 4975).

---

## Falsifiable invariant

> For every room R whose config entry has a non-empty configured list L
> (∈ {`lights`, `night_lights`, `fans`, `humidity_fans`, `covers`, `climate_entity`}),
> the corresponding attribute on `binary_sensor.<room_slug>_occupied` MUST equal
> exactly the list URA's actuator code path reads via `_get_config(L, ...)` at the
> same instant, byte-for-byte (order preserved, no dedup, no domain filtering).

If actuator code and attr diverge, G1 has failed its purpose (PWA would be lied to).

---

## Deliverables

### D1: Add control-list attrs to `OccupiedBinarySensor.extra_state_attributes`

**File:** `custom_components/universal_room_automation/binary_sensor.py`
**Site:** inside the existing `extra_state_attributes` property on
`OccupiedBinarySensor` (after line 605, before the final `return attrs`).

**Change (spec, not code):**

Read each list via the coordinator's `_get_config` (options-first-with-data-fallback)
and assign to a stable attr key. Wrap in `try/except` with empty-list / `None` defaults
matching v4.7.24 substrate defensive style so a malformed options blob never blanks the
whole attr dict.

Attr keys and shapes:

| Attr key                  | Source CONF                   | Shape                        | Default on error |
|---------------------------|-------------------------------|------------------------------|------------------|
| `control_lights`          | `CONF_LIGHTS`                 | `list[str]` of entity_ids    | `[]`             |
| `control_night_lights`    | `CONF_NIGHT_LIGHTS`           | `list[str]`                  | `[]`             |
| `control_fans`            | `CONF_FANS`                   | `list[str]`                  | `[]`             |
| `control_humidity_fans`   | `CONF_HUMIDITY_FANS`          | `list[str]`                  | `[]`             |
| `control_covers`          | `CONF_COVERS`                 | `list[str]`                  | `[]`             |
| `control_climate_entity`  | `CONF_CLIMATE_ENTITY`         | `str \| None`                | `None`           |

Namespaced with `control_` prefix so consumers can grep the key set and so future
control kinds (media, switch groups) extend cleanly without collision with existing
attrs (`fan_recheck_*`, `substrate_kinds`, `became_occupied_time`, etc.).

Copy-of-list is emitted (`list(...)`) so a caller mutating the attr can't corrupt the
underlying config store — cheap and matches the actuator read-path semantics.

### D2: Live options responsiveness — verify, don't build

No new listener wiring. `_get_config` reads `self.entry.options` on every attr read,
and `entry.options` is updated in-place by HA core before the update-listener fires
platform reload. Between an options-flow write and the next platform reload (typically
seconds), the attr will already reflect the new value on the next state write.

Verification is via the acceptance test in D3, not code.

### D3: Acceptance fixture — hand-built room→control table

Appendix A of this doc (below) MUST contain a hand-verified table of all 38 URA rooms
extracted **live** from `.storage/core.config_entries` on the running HA instance at
`/Users/ojiudezue/ha-config/.storage/core.config_entries` (per CLAUDE.md Data Source
Verification: use the Samba-mounted live path, not `~/.cache/ura/`).

Extraction (planner responsibility — appendix populated before build starts):

```bash
python3 -c "
import json, pathlib
p = pathlib.Path('/Users/ojiudezue/ha-config/.storage/core.config_entries')
entries = json.loads(p.read_text())['data']['entries']
rooms = [e for e in entries
         if e['domain'] == 'universal_room_automation'
         and e.get('data', {}).get('entry_type') == 'room']
for r in sorted(rooms, key=lambda e: e.get('title','')):
    d = {**r.get('data', {}), **r.get('options', {})}
    print(r.get('title'),
          d.get('lights', []),
          d.get('night_lights', []),
          d.get('fans', []),
          d.get('climate_entity'))
"
```

The builder's live test (D4) diffs `state.attributes.control_lights` etc. for each
room against this table row-for-row.

### D4: Tests

**File:** `quality/tests/test_g1_room_control_list_attrs.py` (NEW test file).

Unit tests (mock coordinator + entry):

1. `test_attrs_present_when_configured` — entry.data has `lights=[...]`,
   `fans=[...]`, `climate_entity="climate.x"` → attr surface all six keys, correct
   values.
2. `test_attrs_default_when_absent` — entry.data missing all six keys → attrs =
   `[]`/`[]`/`[]`/`[]`/`[]`/`None`, never `KeyError`.
3. `test_options_override_data` — entry.data has `lights=["a"]`, entry.options has
   `lights=["b"]` → attr = `["b"]` (mirrors `_get_config` semantics; guards against
   the PWA being served stale data-tier values after an options edit).
4. `test_attrs_are_copies_not_refs` — mutating the returned attr list does not
   mutate `entry.options["lights"]`.
5. `test_malformed_options_do_not_blank_other_attrs` — inject a mock where
   `_get_config` raises for `CONF_LIGHTS`; other attrs (`fan_recheck_*`,
   `substrate_kinds`, `control_fans`, etc.) still populate.

Live-instance test (documented, not automated): D5 acceptance table diff.

### D5: Live validation (post-deploy, mandatory)

For each of the 38 rooms in Appendix A, run:

```
ha-mcp: get_state binary_sensor.<room_slug>_occupied
```

Diff `attributes.control_lights / control_night_lights / control_fans /
control_humidity_fans / control_covers / control_climate_entity` against the
Appendix A row. Record PASS / FAIL per row in `docs/readmes/README_v<version>.md`
per CLAUDE.md "Record Live Validation Back Into the README" mandate.

Additional live check — options responsiveness (one room, operator-picked):

- Read attr, note value.
- Options-flow edit: add/remove one entity_id from `lights`.
- Save.
- Within 30s, re-read attr → reflects new list.

---

## Acceptance criteria

### D1 (attr surface)
- **Verify:** `binary_sensor.master_bedroom_occupied.attributes` includes keys
  `control_lights`, `control_night_lights`, `control_fans`, `control_humidity_fans`,
  `control_covers`, `control_climate_entity`.
- **Sensor:** `binary_sensor.av_closet_occupied.attributes.control_lights` contains
  `"switch.switch_shelly1pmgen3_wifi_avcloset"` (per Appendix A — the exact case that
  breaks the PWA's slug heuristic today).
- **Test:** `test_attrs_present_when_configured`, `test_attrs_default_when_absent`
  in `quality/tests/test_g1_room_control_list_attrs.py`.
- **Live:** Appendix A diff table in the README shows PASS for all 38 rooms.

### D2 (live options responsiveness)
- **Verify:** `_get_config` reads through `entry.options` each call — proven by
  `test_options_override_data`.
- **Live:** operator-driven options edit (one room, add one light) surfaces on the
  attr within one coordinator tick / one HA state poll, no HA restart required.

### D3 (fixture ground truth)
- **Verify:** Appendix A is populated from live `.storage/core.config_entries` at plan
  time; the row for each room lists the four columns (lights / night_lights / fans /
  climate_entity). Optional covers/humidity_fans columns for rooms that configure them.
- **Test:** none — the fixture IS the test oracle for D5.

### D4 (unit tests)
- **Verify:** all 5 tests pass:
  `PYTHONPATH=quality python3 -m pytest quality/tests/test_g1_room_control_list_attrs.py -v`
- **Test:** no regression in the existing `OccupiedBinarySensor` test suite.

### D5 (live validation, post-deploy)
- **Live:** Appendix A diff PASS for 38/38 rooms.
- **Live:** operator options-edit round-trip proven (one room).
- **README:** `docs/readmes/README_v<version>.md` carries the "Validated <date>" table
  with per-row PASS/FAIL evidence (entity_id + observed attr value).

---

## Tier classification — Tier 1 justification

**Choice:** Tier 1 (single hotfix-style review).

**Why NOT Tier 2 / Tier 2-DB / Tier 3:**

- No behavior change to actuation, presence, HVAC, or any coordinator. Attr reads are
  a leaf side effect; no upstream code consumes them.
- No new persistence, no DB migration, no signal-bus change, no schema change — Tier
  2-DB triggers all absent.
- No trust-hierarchy ripple (Bug Class #48/#53 sensitivity): attrs are pure additive
  read-only projections of pre-existing config keys.
- No shared primitive changed; the read helper (`_get_config`) is reused as-is.
- Blast radius: `OccupiedBinarySensor.extra_state_attributes` is called by HA state
  machinery only; adding six keys can only fail by raising, and the outer `try/except`
  wraps each read.

**Tier 1 review framing (single pass):**

- Correctness of the six attr reads (right CONF for each, right default shape).
- Defensive style matches `substrate_kinds` prior art (per-attr try/except; never let
  one bad read blank the whole attrs dict).
- No accidental behavior coupling (attr reads MUST NOT mutate coordinator state or
  trigger actuation).
- Test coverage matches D4.

**Elevation trigger:** if review finds the attr surface can be misused by a consumer
(e.g., a dashboard action wiring the attr into a service call before URA has
finished setup), elevate to Tier 2 and add a startup gate. Not expected — attrs are
consumed by the PWA read-only.

---

## Files touched

| File | Change |
|---|---|
| `custom_components/universal_room_automation/binary_sensor.py` | D1 — extend `OccupiedBinarySensor.extra_state_attributes` (single method edit, ~20 lines added between line 605 and the `return attrs` on line 606). No new imports beyond `CONF_*` already available. |
| `quality/tests/test_g1_room_control_list_attrs.py` | D4 — new test file, 5 tests. |
| `docs/readmes/README_v<version>.md` | D5 — new README pre-deploy; post-deploy write-back per CLAUDE.md. |

**Files NOT touched (verified):** `const.py`, `config_flow.py`, `options_flow.py`,
`coordinator.py`, `sensor.py`, `__init__.py`, all `domain_coordinators/*.py`, all DAO
files, `manifest.json` (except version bump via `deploy.sh`).

---

## Verification steps (builder → validator → reviewer)

1. Builder makes the D1 edit, adds D4 tests, runs
   `PYTHONPATH=quality python3 -m pytest quality/tests/ -v` (expect green + 5 new passes).
2. Builder tags `pre-review-v<version>` per CLAUDE.md.
3. Reviewer (Tier 1): single adversarial pass against QUALITY_CONTEXT.md, focus areas
   above.
4. Deploy via `./scripts/deploy.sh <version> "..." "..."`.
5. Post-restart: run D5 live diff across all 38 rooms, one operator options-edit
   round-trip, write results into `docs/readmes/README_v<version>.md`.
6. Signal PWA repo (~/Code/ura-dashboard-pwa) that G1 has landed and M2 unblocks.

---

## Plan completion tracking (fill in post-build)

- [ ] D1 built
- [ ] D2 verification (options responsiveness live test)
- [ ] D3 fixture populated (Appendix A below)
- [ ] D4 tests added + green
- [ ] D5 live validation + README write-back
- [ ] Deferred items: none anticipated. Anything cut goes here with a "why" and a
      tracker location.

---

## Appendix A — Room → Control-Entity Fixture (populate before build)

> **PLANNER TODO before handoff to builder:** re-derive from the live
> `/Users/ojiudezue/ha-config/.storage/core.config_entries` (per CLAUDE.md — do NOT trust
> a session-cached extract). Fill this table. This is the acceptance oracle for D5.
> Do NOT let the builder run without this appendix populated — the fixture-before-
> automation discipline is what makes the live diff meaningful.

| Room title | control_lights | control_night_lights | control_fans | control_humidity_fans | control_covers | control_climate_entity |
|---|---|---|---|---|---|---|
| _(row per room, 38 total)_ | | | | | | |

Extraction command (planner runs and pastes results):

```bash
python3 -c "
import json, pathlib
p = pathlib.Path('/Users/ojiudezue/ha-config/.storage/core.config_entries')
entries = json.loads(p.read_text())['data']['entries']
rooms = [e for e in entries
         if e['domain'] == 'universal_room_automation'
         and e.get('data', {}).get('entry_type') == 'room']
print(f'{len(rooms)} rooms')
for r in sorted(rooms, key=lambda e: (e.get('title') or '').lower()):
    d = {**r.get('data', {}), **r.get('options', {})}
    print('|', r.get('title'),
          '|', d.get('lights', []),
          '|', d.get('night_lights', []),
          '|', d.get('fans', []),
          '|', d.get('humidity_fans', []),
          '|', d.get('covers', []),
          '|', d.get('climate_entity'), '|')
"
```

Sanity checks the planner MUST apply to the extracted table before handing to builder:

- Row count = 38 (matches operator's known room count; if not, investigate before
  proceeding — a mismatch means either a room was added/removed or the extract read
  the wrong storage path).
- **AV Closet** row's `control_lights` includes the Shelly switch entity, not the
  friendly-name light (per CLAUDE.md Troubleshooting canonical example). If it doesn't,
  the extract is wrong OR the config is wrong — resolve before build.
- At least one room has a non-empty `covers` list AND at least one room has a
  non-empty `humidity_fans` list (so the D5 diff exercises those columns).
- `climate_entity` is a string (or None), never a list.

## Appendix A — POPULATED fixture (extracted live 2026-07-13 ~22:35 CDT from /config/.storage/core.config_entries, options-over-data merge)

Canary row verified: AV Closet lights = the Shelly relay switch, not the light friendly name. ✓

| Room | control_lights | control_night_lights | control_fans | control_humidity_fans | control_covers | control_climate_entity |
|---|---|---|---|---|---|---|
| AV Closet | switch.switch_shelly1pmgen3_wifi_avcloset | — | — | — | — | climate.thermostat_bryant_wifi_studyb_zone_1 |
| Breakfast Nook | switch.shelly2pmg3_28372f239274_switch_0, switch.switch_shelly2pmgen3_wifi_breakfast_chandelier, switch.switch_shelly2pmgen3_wifi_breakfast_overhead | switch.shelly2pmg3_28372f239274_switch_0 | fan.151732606487193_fan | — | cover.breakfast_blinds | climate.back_hallway_zone_3 |
| Butler Pantry | switch.switch_shelly2pmgen3_wifi_butlerpantry_overheadlights, switch.switch_shelly2pmgen3_wifi_butlerpantry_pucks | switch.switch_shelly2pmgen3_wifi_butlerpantry_pucks | — | — | cover.ptry | — |
| Dining Room | — | — | — | — | cover.dining_right, cover.dining_center, cover.dining_left | — |
| Down Guest Bathroom | switch.switch_shelly2pmg3_wifi_dnguestbathrooom1_overheadlights, switch.switch_shelly2pmg3_wifi_dnguestbathrooom1_wallsconce | — | — | fan.switch_shelly2pmg3_wifi_dnguestbathrooom2_humidityfan | — | — |
| Exercise Room | switch.switch_sonoffm4rm_matter_exercise, light.rgbw_motion_lux_3rd_zigbee_exercise | light.rgbw_motion_lux_3rd_zigbee_exercise | fan.fan_switch_3 | — | cover.1_combined, cover.2_combined, cover.3_combined, cover.4_combined, cover.5_combined, cover.6_combined | — |
| Exercise Room Closet | switch.switch_shelly1pmgen3_wifi_exerciseroomcloset | — | — | — | — | — |
| Game Room | switch.switch_shelly1pmgen3_wifi_gamedeskoverhead | switch.switch_shelly1pmgen3_wifi_gamedeskoverhead | fan.game_room_ceiling_fan | — | cover.shade | climate.up_hallway_zone_2 |
| Garage A | switch.switch_shelly1pmgen3_wifi_garageaoverhead | — | — | — | — | — |
| Garage B | light.ratgdov25i_dbfe2a_light, switch.switch_sonoffduo_zigbee_garageboverhead | — | — | — | cover.ratgdov25i_dbfe2a_door | — |
| Garage Hallway | light.levds_dimmer_c26a_light | light.dimmer_tapo_wifi_matter_hallwaycabinet | — | — | cover.hallway_shade | climate.back_hallway_zone_3 |
| Guest Bedroom 1 | switch.switch_shelly2pmgen3_wifi_dnguestroom_light | — | fan.guest_room_down_ceiling_fan | — | cover.guest_1_combined, cover.guest_2_combined, cover.guest_3_combined, cover.guest_4_combined | climate.back_hallway_zone_3 |
| Guest Bedroom 1 Closet | switch.switch_shelly1pmgen3_wifi_dnguest_closet | — | — | — | — | — |
| Guest Bedroom 2 Bathroom | switch.switch_shelly2pmgen3_wifi_upguestbathroom_sconce | — | — | — | — | — |
| Jaya Bathroom | light.minir4m_jayabath_overhead, switch.switch_shelly2pmg3_wifi_jayabathshower, light.rgbw_motion_lux_3rdr_wifi_matter_jayabath_2 | light.rgbw_motion_lux_3rdr_wifi_matter_jayabath_2 | — | — | — | — |
| Jaya Bedroom (Bedroom 4) | switch.switch_sonoffm4rm_matter_jayabedroom | — | — | — | cover.jaya_shade_right_combined, cover.jaya_shade_left_combined | climate.up_hallway_zone_2 |
| Kitchen | switch.shelly2pmg3_28372f239274_switch_1 | switch.switch_tapo_wifi_kitchenrange | fan.151732606487193_fan | — | — | climate.back_hallway_zone_3 |
| Kitchen Hallway | light.dimmer_tapo_wifi_matter_khallway | light.dimmer_tapo_wifi_matter_khallway | — | — | — | — |
| Kitchen Hallway Garage | light.dimmer_tapo_wifi_matter_garagekitchenhallway | light.dimmer_tapo_wifi_matter_garagekitchenhallway | — | — | — | climate.back_hallway_zone_3 |
| Kitchen Pantry | light.dimmer_inovelli_zigbee_pantryoverhead, light.rgbw_motion_lux_3rdr_wifi_matter_pantry | light.rgbw_motion_lux_3rdr_wifi_matter_pantry | — | — | — | — |
| Laundry | light.rgbw_lux_motion_3rdr_wifi_matter_laundry, switch.switch_shelly2pmgen3_wifi_laundry1_sw1, switch.switch_shelly2pmgen3_wifi_laundry1_sw2 | light.rgbw_lux_motion_3rdr_wifi_matter_laundry, switch.switch_shelly2pmgen3_wifi_laundry1_sw2 | — | fan.laundry_switch_shelly2pmgen3_wifi_laundry2_sw2 | cover.laundry_shade | climate.back_hallway_zone_3 |
| Laundry Closet | switch.switch_shelly2pmgen3_wifi_laundry2_sw1 | — | — | — | — | — |
| Living Room | — | — | fan.towerfan_dreopilotmaxs_wifi_livingroom | — | cover.living_bot_1, cover.living_bot_2, cover.living_bot_3, cover.living_bot_4, cover.living_top_left, cover.living_top_center, cover.living_top_right | climate.thermostat_bryant_wifi_studyb_zone_1 |
| Master Bath Toilet | light.rgbw_motion_lux_3rdr_wifi_matter_mastertoilet, switch.switch_sonoffmini4rm_matter_mastertoilet | light.rgbw_motion_lux_3rdr_wifi_matter_mastertoilet | — | fan.master_toilet_switch_sonoffm4rm_matter_mastertoiletfan_minir4m_masterbathclosetfan | — | — |
| Master Bathroom | switch.shelly2pmg3_34cdb07765dc_switch_0, switch.shelly2pmg3_34cdb07765dc_switch_1 | switch.sonoff_1002197ef7_1 | — | fan.switch_shelly1pmminig3_wifi_masterbathfan | cover.master_bath_1, cover.master_bath_2 | — |
| Master Bedroom | — | light.shellydimmer2_24d7ebe93470 | fan.polyfan_508s_wifi_masterbedroom, fan.ceilingfan_fanimaton_rf_masterbedroom | — | cover.mb_shade | climate.thermostat_bryant_wifi_studyb_zone_1 |
| Media | — | — | fan.media_room_ceiling_fan | — | cover.media_center, cover.media_left, cover.media_right | climate.up_hallway_zone_2 |
| Media Room Closet | switch.switch_shelly1pmgen3_wifi_mediacloset | — | — | — | — | — |
| Oji Vanity | switch.switch_shelly1pmgen3_wifi_ojivanity, switch.shelly2pmg3_34cdb07765dc_switch_1 | — | — | — | — | — |
| Patio | switch.switch_sonoffm4rm_matter_patiolights, light.rgbw_light_jullison_wifi_patio1, light.rgbw_light_jullison_wifi_patio2, light.rgbw_light_jullison_wifi_patio3, light.rgbw_light_jullison_wifi_patio4 | light.rgbw_light_jullison_wifi_patio2, light.rgbw_light_jullison_wifi_patio3 | — | — | cover.patio_1, cover.patio_2, cover.patio_3, cover.patio_4, cover.patio_5 | — |
| Receiving Room | light.dimmer_shellyplus_wifi_receiving2, switch.switch_shelly1pmgen4_wifi_receivingroom | light.dimmer_shellyplus_wifi_receiving2 | — | — | cover.receiving_center, cover.receiving_left, cover.receiving_right | climate.thermostat_bryant_wifi_studyb_zone_1 |
| Stair Closet | switch.switch_shelly1pmminig3_wifi_staircloset, light.rgbw_motion_lux_3rdr_wifi_matter_staircloset | light.rgbw_motion_lux_3rdr_wifi_matter_staircloset | — | — | — | — |
| Study A | light.smart_light_23031714641167590a0248e1e9c00955, light.switch_leviton_thread_studya_pucks, light.switch_leviton_thread_studya_fancyoverhead | light.smart_light_23031714641167590a0248e1e9c00955 | fan.polyfan_dreo704s_wifi_studya | — | cover.study_a_blinds | climate.thermostat_bryant_wifi_studyb_zone_1 |
| Study A Closet | switch.switch_shelly1pmminigen3_wifi_studyacloset | — | — | — | — | climate.thermostat_bryant_wifi_studyb_zone_1 |
| Study B | light.dimmer_shellyplus_wifi_studyb | light.dimmer_shellyplus_wifi_studyb1 | — | — | cover.study_b_shade | climate.thermostat_bryant_wifi_studyb_zone_1 |
| Upstairs Guestroom | switch.switch_sonoffm4rm_matter_upguest | — | fan.fan_switch_4 | — | cover.bedroom_shade_2_combined, cover.bedroom_shade_1_combined, cover.bedroom_shade_3_combined, cover.bedroom_shade_4_combined | climate.up_hallway_zone_2 |
| Ziri Bathroom | light.rgbw_motion_lux_3rdr_wifi_matter_ziribath, switch.switch_shelly2pmg3_wifi_ziribathsconce, switch.switch_shelly2pmg3_wifi_zirioverhead | light.rgbw_motion_lux_3rdr_wifi_matter_ziribath | — | fan.minir4m_sonoff_ziribathfan | — | — |
| Ziri Bedroom (Bedroom 5) | switch.switch_sonoffm4rm_matter_ziribedroom | — | fan.fanswitch_treat_wifi_ziribedroom | — | — | climate.up_hallway_zone_2 |

38 rows. This table is the D5 live-validation diff target: post-deploy, every room's `control_*` attrs must match its row exactly.
