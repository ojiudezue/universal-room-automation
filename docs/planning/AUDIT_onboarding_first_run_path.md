# AUDIT — URA first-run path as it exists TODAY (ONBOARDING-SIMPLIFY-1, phase 2)

**Date:** 2026-10-02 · **Card:** ONBOARDING-SIMPLIFY-1 · **Status:** read-only audit, no code changed
**Supersedes for "current state":** `AUDIT_first_run_onboarding.md` (2026-09-12). That audit
describes the PRE-v5.101.0 flow (13-screen room chain, 77-95 fields). It is no longer accurate.
**Proposals:** `PLANNING_onboarding_simplify_phase2.md`.

## 0. Headline finding — the card's groom note is wrong

The 2026-09-26 groom note says ONBOARDING-SIMPLIFY-1 was "never built; wrongly stamped shipped by
v5.101.0". **The code says otherwise.** D1-D9 of `PLANNING_onboarding_simplify.md` (2026-09-12)
are live on `develop`:

| Plan item | Evidence in code |
|---|---|
| D1 additive filters in `_get_area_entities` | `config_flow.py:1019-1047` (entity_category / hidden_by / helper-platform excludes) |
| D1 ranker `_rank_area_candidates` | `config_flow.py:1063-1156`; `AUTODETECT_NAME_DENYLIST` `const.py:1698` |
| D2 `ROOM_TYPE_FEATURE_DEFAULTS` | `const.py:1678-1689` (bathroom only: wet room, spike, presence-runtime) |
| D3 essentials chain | `room_setup:1588` -> `room_class:1685` -> `sensors_confirm:1719` -> `devices_confirm:1866` -> `room_summary:1928` |
| D4 house minted before rooms | `_mint_house_now:1341`, called at `energy_setup:1384` |
| D4 skip branch | `add_first_room:1413` menu -> `skip_rooms_later:1435` (abort `rooms_skipped`) |
| D5 weather auto-detect | `_detect_weather_entity:1191`, used as `suggested_value` at `:1282-1287` |
| D6 empty-area hint | `sensors_confirm:1784-1798` |
| P7 summary | `room_summary:1978-1991` |

So the >=50% target from the 2026-09-12 audit (room: 13 screens / 77-95 fields -> 5 / 18) was
**met** by v5.101.0. This audit re-baselines on that shipped flow and looks for the NEXT >=50%.
Recommend correcting the card note (the card's own `live_validated_2026_09_12` field agrees with
the code; the groom note is the outlier).

## 1. Institutional context verified

- **Files read for the path:** `config_flow.py:893-2010` (ConfigFlow first-run + room
  essentials), `:3199-3247` (internal `integration_create` / migration sources), `:3669-3700`
  (options `init` per entry type), `:4452-4480` (`domain_coordinators`, now unreachable),
  `:8883-8918` (`coordinator_toggles`), `:1-165` (Simple/Advanced helpers `advanced_hint`,
  `_adv`, `room_menu_hint`); `__init__.py:997-1121` (Zone Manager + Coordinator Manager auto-create),
  `:1995-2015` (call sites), `:3195`, `:3322-3411`, `:3514`, `:3821` (coordinator enable reads);
  `switch.py:240-314`, `:487-535` (coordinator switches); `const.py:1678-1710`, `:2880-2898`.
- **Prior docs:** `AUDIT_first_run_onboarding.md`, `PLANNING_onboarding_simplify.md` (both full read).
- **Card read:** `kanban.data.yaml:27397-27422`, plus sibling ROOM-CLASSIFICATION-CONSISTENCY-1.
- **Not read in this pass:** `strings.json` / `translations/en.json` wording; the
  `feature/zone-house-advanced` branch (stated by orchestrator, not inspected).

## 2. The actual first-run path, step by step

### Stage A — Install -> House entry (mandatory)

| # | Step (file:line) | Kind | Fields | Required | Defaults / auto-detect |
|---|---|---|---|---|---|
| A0 | `async_step_user:920` | router | — | — | No House entry -> `integration_config`; House exists -> `entry_type_select` menu |
| A1 | `async_step_integration_config:1241` | form | 11 | 1 (`CONF_ELECTRICITY_RATE`, has default `DEFAULT_ELECTRICITY_RATE`) | see below |
| A2 | `async_step_energy_setup:1377` | form | 4 | 0 | none |
| A2' | `_mint_house_now:1341` | internal | — | — | House "🏠 Home" created via `flow.async_init(source="integration_create")` -> `integration_create:3199` |
| A3 | `async_step_add_first_room:1413` | menu | 2 options | — | `skip_to_room` -> room chain; `skip_rooms_later` -> abort `rooms_skipped` |

A1 fields (`:1271-1334`):

| Field | Required | Default | Auto-detect |
|---|---|---|---|
| `CONF_OUTSIDE_TEMP_SENSOR` | opt | none | none (selector filtered to temperature) |
| `CONF_OUTSIDE_HUMIDITY_SENSOR` | opt | none | none |
| `CONF_WEATHER_ENTITY` | opt | suggested | **yes** — sole/alpha-first `weather.*` (`:1191`) |
| `CONF_SOLAR_PRODUCTION_SENSOR` | opt | none | none |
| `CONF_TRACKED_PERSONS` | opt | `[]` | **none** — every `person.*` picked by hand |
| `CONF_PERSON_DATA_RETENTION` | opt | `DEFAULT_PERSON_DATA_RETENTION` days | — (tuning) |
| `CONF_TRANSITION_DETECTION_WINDOW` | opt | `DEFAULT_TRANSITION_WINDOW` s | — (tuning) |
| `CONF_ELECTRICITY_RATE` | **req** | `DEFAULT_ELECTRICITY_RATE` | — |
| `CONF_NOTIFY_SERVICE` | opt | none | lists all notify services |
| `CONF_NOTIFY_TARGET` | opt | none | lists `mobile_app_*` |
| `CONF_NOTIFY_LEVEL` | opt | `errors` | — |

A2 fields (`:1391-1406`): whole-house power, whole-house energy, device power, device energy — all
optional multi-pickers, no auto-detect.

**Behind the scenes, no form:** when the House entry sets up, `__init__.py:1995-2015` runs
`_migrate_zones_to_zone_manager` (`:997`) — which creates the **Zone Manager** entry even with zero
zones (empty `zones_data`) — and `_ensure_coordinator_manager_entry` (`:1073`), which creates the
**Coordinator Manager** entry. Neither asks anything.

### Stage B — First room (optional, same flow via A3 `skip_to_room`; later rooms via A0 menu)

| # | Step (file:line) | Fields | Required | Defaults / auto-detect |
|---|---|---|---|---|
| B1 | `room_setup:1588` | 3 (+1 `CONF_ZONE` only if zones exist, `:1649`) | `CONF_ROOM_NAME` (no default); `CONF_ROOM_TYPE` (default generic) | Name NOT pre-filled from area. Timeout derived from type (`:1614-1617`). Area optional — **all later auto-fill needs Area picked here** |
| B2 | `room_class:1685` | 2 (wet room, guest room) | 0 | wet room soft-default from `ROOM_TYPE_FEATURE_DEFAULTS` |
| B3 | `sensors_confirm:1719` | 8 (motion, mmWave, occupancy, temp, humidity, lux, door, water leak) | >=1 of motion/mmWave/occupancy (`:1735-1736`) | area pre-fill for 7 of 8 (mmWave never, `:1835`) |
| B4 | `devices_confirm:1866` | 5 (lights, auto switches, fans, humidity fans, covers) | 0 | area pre-fill for 4 of 5 (humidity fans never); light capability detected on submit |
| B5 | `room_summary:1928` | 0 | — | soft seed of type defaults (`:1948-1953`); name race re-check; `async_create_entry` |

Every other room setting (behavior, chaining, AI rules, climate, fan speeds, sleep, energy,
notifications, night lights, covers) is off the create path and lives in the room's Options,
which on `develop` already has the trimmed menu + Simple/Advanced (`_adv:141`, `room_menu_hint:112`).

### Stage C — Zones (optional, separate re-entered flow)

`async_step_user` -> `entry_type_select:933` menu -> `add_zone:944` -> `zone_setup:1461`.
Fields: zone name (**required**, no default), description, outdoor flag (default off), rooms
(only if rooms exist). Writes into Zone Manager options and reloads it (`:1499-1522`), abort
`zone_added`. Thermostat, persons, cameras, media per zone live in Zone Manager Options
(`init:3688` -> `manage_zones`). Zone Simple/Advanced is on `feature/zone-house-advanced`
(not inspected).

### Stage D — Coordinators (optional, no flow at all)

- `entry_type_select` -> `add_coordinator:948` **aborts** (`coordinator_use_options`). The menu
  item is a dead end.
- The master on/off is the **"Domain Coordinators" switch** on the Universal Room Automation
  device (`switch.py:487-534`, default **off** at `:518`; read at `__init__.py:3195`). Turning it on
  writes the option and reloads the House entry. The old options step `domain_coordinators:4452`
  is unreachable (removed from the menu, comment at `:3684`).
- Per-coordinator switches (`switch.py:240-314`): presence, safety, security, music following
  default **on** (`__init__.py:3322-3411`); appliance on (comment `switch.py:281`); energy
  default **off** (`__init__.py:3514`); **HVAC default off** (`__init__.py:3821`, `CONF_HVAC_ENABLED`).
- Coordinator settings are in Coordinator Manager Options (energy ~89 fields, HVAC submenu
  `coordinator_hvac:6326`).

### Dead code found on the path (supersession triage)

| Item | file:line | Bucket | Reason |
|---|---|---|---|
| `async_step_post_integration_setup` | `config_flow.py:1424` | DELETE (after strings/test grep) | Nothing routes to it (grep: only its own def + step_id) |
| `async_step_setup_zone`, `async_step_finish` | `:1449`, `:1457` | DELETE with the above | Only reachable from that dead menu |
| `add_coordinator` menu item | `:948`, menu `:937` | KEEP + WIRE | Should point the operator at the switch, not abort with jargon |
| `async_step_domain_coordinators` | `:4452` | operator call: DOCUMENT or DELETE | Replaced by the switch |
| Old room chain `sensors:2011` ... `notifications:3067` | various | KEEP | Still live as Options-flow handlers (plan D7) |

## 3. Baseline numbers (shipped flow on `develop`)

"Visible" = fields rendered. "Must pick" = no default and no auto-fill on a typical install
(sensors assigned to HA areas).

| Journey | Screens | Visible fields | Must pick | Notes |
|---|---|---|---|---|
| A. House only (mandatory) | 3 (2 forms + menu) | 15 | 0 (rate has a default) | persons, notify, outside sensors hand-picked if wanted |
| B. One room | 5 | 18 (19 with zones) | 2: name + area (area unlocks all auto-fill) | +1 if no occupancy sensor in the area |
| A+B. Fresh install to first room | **8** | **33** | **2** | |
| Each further room | 6 (menu + 5) | 18 | 2 | 10 rooms = **60 screens, 180 fields** |
| C. One zone | 2 (menu + form) | 3-4 | 1 (name) | rooms must exist first |
| D. Coordinators on, HVAC off | 0 flow screens; 1 switch | — | 1 toggle | HVAC already off by default |
| **Typical 2nd home: house + 10 rooms + 2 zones + coordinators** | **~67** | **~195** | **~23** | dominated by per-room repetition |

**Where the load is now:** not in any single form — in **repetition** (6 screens per room) and in
fields with an obvious answer but no auto-fill (room name = area name, persons = all `person.*`,
single phone = the alert target).

## 4. What auto-detection exists today

| Detection | Where | Gap |
|---|---|---|
| Weather entity | `_detect_weather_entity:1191` | outside temp/humidity not derived from it |
| Area -> motion/occupancy/temp/humidity/lux/door/leak | `sensors_confirm:1773-1782` | needs Area picked at B1; mmWave never filled |
| Area -> lights/switches/fans/covers | `devices_confirm:1895-1901` | humidity fans never filled |
| Ranking + dedup + chip-temp denylist | `_rank_area_candidates:1063` | — |
| Light capability | `_detect_light_capabilities:1217` | — |
| Room type -> timeout | `room_setup:1614` | type not guessed from area name |
| Room type -> features | `ROOM_TYPE_FEATURE_DEFAULTS` `const.py:1678` | bathroom only |
| Mobile app notify targets | `_get_mobile_app_targets:962` | not pre-selected when there is exactly one |
| Persons | — | **none** |
| Rooms from areas | — | **none** — one flow per room |

## 5. Second home this weekend (Oct 3-4) — operator checklist with TODAY's flow

Nothing in the phase-2 plan ships before then. Do this with the current flow:

1. **Before installing URA: assign HA areas.** Put every motion/occupancy sensor, light, fan,
   cover and temp/humidity sensor in its HA area (entity or device area). URA's room auto-fill
   reads areas only; unassigned entities will not be suggested.
2. **Create `person.*` entries** for the residents (with their phones as trackers) so they can be
   picked on the House form.
3. **Install + House form:** Weather is pre-filled — check it. Tick the People. Pick the notify
   service/phone and set level to "Errors only" or "Important". Set the electricity rate (or
   accept the default). Leave outside temp/humidity/solar empty unless the home has them.
4. **Energy meters screen:** leave empty unless the home has whole-house meters. Submit.
5. **"Add first room" menu:** pick a room or "add rooms later" (the House is already saved).
6. **Each room (5 screens):** type name, pick type, **pick the Area** (this is what fills the
   rest). Wet room is already on for bathrooms. Check the pre-filled sensors (at least one
   motion/occupancy is required) and devices. Submit the summary. Repeat via "Add entry" for
   every room. Budget ~1-2 min per room.
7. **Zones: skip for now.** With HVAC off they add little. Add later if wanted.
8. **Do not set a thermostat on any zone and do not turn on HVAC.** On the Coordinator Manager
   device, confirm the **HVAC Coordinator** switch is **off** (its default) and the **Energy
   Coordinator** switch is **off** (its default; no Envoy/battery there). HVAC stays off until
   W1-C P3 — the ecobee-over-HomeKit path is untested with URA's HVAC coordinator.
9. **Turn on the "Domain Coordinators" switch** on the Universal Room Automation device when you
   want presence/safety/security. This reloads the House entry. Presence, safety, security, music
   following and appliance come on by default; switch off any the home doesn't need (e.g. music
   following with no media players).
10. **Check after setup:** each room's occupancy entity follows a walk-through; no URA errors in
    the HA log; the HVAC Coordinator switch still reads off after the reload.
11. **Restart timing:** do HA restarts while the household is awake (restarts drop Sleep mode).
