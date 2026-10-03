# URA v5.103.35 — Battery ladder floor, trimmed room menu, pure sensor getters, zone/house wording

Four reviewed changes. Serial full-suite name-diff vs v5.103.34 (003b42d6f): 151 failed / 3 errors identical name sets, +383 passing — CLEAN.

**Visible changes:** room settings show only the sections a room type usually needs (plus any section you have set); turn on Advanced mode in your HA profile to see everything. Zone and House dialogs have plain labels for every field.

## EC-SOC-LADDER-FULL-WIRING-1 (split) — drain targets and inclement floor never below reserve

Draft for the release README (version to be assigned at deploy; PATCH bump).
Plan: `docs/planning/PLANNING_ec_soc_ladder_full_wiring.md` (split: D1 + D3 + D4, Tier 2-DB).

### What changed

- **Drain targets can no longer be written below the battery reserve (#1).**
  `BatteryStrategy._get_offpeak_drain_target` (the single drain-target decision seam)
  now returns the *effective* target: the five ordered classes
  (excellent → very_poor) are a running max anchored at `reserve_soc`; `unknown`
  (and any stray class) is floored at `reserve_soc` but not monotonised; all capped
  at 100. Every drain consumer (drain-fallback emission, DP value stamp, EV/plug
  release floor → pool, status/narration) already routes through this seam.
  Before: `reserve 10, drain_excellent 5` (legal on Number bounds) emitted an
  Enphase reserve of 5%. After: 10%.
- **Inclement recoverability uses the same floor the hold uses (#6).**
  `InclementFusion.decide` now passes `_partial_floor_value()` (= `max(reserve, floor)`)
  into `compute_solar_horizon`, so an inverted floor < reserve can no longer
  overstate permitted discharge and pick partial over full hold.
- **New status attribute** `drain_targets_effective` on
  `sensor.ura_energy_coordinator_battery_strategy`, beside the raw `drain_targets`.
- **Detection is not swallowed.** The raw `_drain_targets` dict, the inclement option,
  and `peak_buffer_target` are still what `validate_threshold_ladder` /
  `_check_threshold_ladder` / `get_status()["threshold_warning"]` read, so an inverted
  ladder still raises `threshold_ladder_violation`.
- **#2 (peak buffer > top drain) stays detect-only.** Design parked in the plan §D2.
  Revival trigger: any `threshold_ladder_violation` with code
  `peak_buffer_target_at_or_below_drain_poor` in `anomaly_log`.
- Docs: `safely_ordered_ladder` docstring, `energy_const.py` ladder comment and
  `ENERGY_COORDINATOR_MANUAL.md` point at the actual enforcement seams. No claim that
  inversions are impossible.

No new knobs, entities, CONF keys or DB changes. On the live (valid) ladder
10/15/20/30/30, reserve 10, every effective value equals its raw value.

### Invariants
- I-1: the off_peak drain-fallback DRAIN leg and the DP stamp `_offpeak_drain_branch_target`
  are never below `reserve_soc`. (HOLD leg `hold_reserve = int(soc)` is out of scope, unchanged.)
- I-2: validator/anomaly readers stay raw.
- I-3: identity on a valid ladder (incl. `excellent == reserve`, `poor == very_poor`).

### Tests
`quality/tests/test_ec_soc_ladder_split.py` (142 cases) drives `determine_mode` through the
drain-fallback across summer / shoulder / winter with the real `TOURateEngine`,
over matrix rows X1, X2, X3 (drains), X6, X9, X10, X11 × all six classes, asserting
the dispatched Enphase reserve value, the DP stamp, raw-dict preservation, the status
attr and the anomaly code. Plus `compose_release_floor` (pool path) and InclementFusion
recoverability.

### Live validation (prospective)
- `sensor.ura_energy_coordinator_battery_strategy` attr `drain_targets_effective` ==
  `drain_targets` (healthy live ladder).
- No `threshold_ladder_violation` rows after restart.
- Inclement `hold_depth` = `allow_discharge` on clear weather (no regression).

### Plan completion
| Item | Status |
|---|---|
| D0 measurement | done in plan §9 (pre-build) |
| D1 drain seam + `drain_targets_effective` | done |
| D3 inclement recoverability floor | done |
| D4 docs (#2 detect-only, parked) | done |
| D2 peak-buffer property + `peak_buffer_target_operator` | NOT built — out of split scope; parked in plan §D2 with revival trigger |
| Matrix rows X4, X5, X7, X8 and peak parts of X3/X11 | dropped — D2-only (plan review finding 3) |
| §6 shoulder 17:30 attain-dormancy test | not added — concerns the D2 peak-buffer path, untouched here |
| Review record `docs/reviews/code-review/v<ver>_ec_soc_ladder_full_wiring.md` | pending review phase |

## ROOM-TYPE-TRIMMED-MENU-1 — room menu trimmed by room type, Simple/Advanced

**Status:** built on `feature/room-trimmed-menu`, deploy HELD for operator.
Version number assigned at deploy (PATCH bump).
Plan: `docs/planning/PLANNING_room_type_trimmed_menu.md` (REV 4, BUILD-READY).

### What changes for you

When you open a room's settings (Settings -> Devices & services -> Universal
Room Automation -> a room -> Configure), the menu now shows only the sections
that room type usually needs.

| Room type | Sections shown |
|---|---|
| Bedroom, Common area, Media room, Generic | all 12 (unchanged) |
| Bathroom | Basic, Sensors, Devices, Lighting, Covers, Climate & Fans, Notifications |
| Garage | Basic, Sensors, Devices, Lighting, Energy, Notifications |
| Infrastructure | Basic, Sensors, Devices, Lighting, Climate & Fans, Energy, Notifications |
| Closet, Hallway | Basic, Sensors, Devices, Lighting, Covers |
| Utility | Basic, Sensors, Devices, Lighting |

- **Nothing you have set is ever hidden.** If a hidden section holds a value
  you changed from the default, that section stays in the menu.
- **More settings…** at the bottom of a trimmed menu shows every section for
  that visit. The next time you open the menu it is trimmed again.
- The hint line at the top of the menu says which room type the list is for.

### A few rarely-used fields are now Advanced-only

| Section | Fields now Advanced-only |
|---|---|
| Cover Automation | Sunrise offset, Sunset offset |
| Climate & Fans | Fan low / medium / high speed temperatures, Humidity fan max runtime |
| Lighting | (unchanged — manual-hold windows, evening brightness/colour, scenes were already Advanced-only) |

If one of these fields holds a value you changed, it is still shown, even when
Advanced mode is off. Hidden fields keep working with their current values,
and saving the form without them does not erase them.

### How to turn on Advanced mode

1. In Home Assistant, click your name at the bottom left of the sidebar (your
   profile page).
2. Turn on **Advanced mode**.
3. Re-open the room's Configure dialog.

With Advanced mode on, the room menu always shows all 12 sections (no "More
settings…"), and the hint says "Advanced settings shown." Advanced mode is a
per-user setting, so other users in the house see their own view.

### Under the hood

- `const.py`: `ROOM_MENU_STEPS_ALL`, `ROOM_MENU_STEPS_BY_TYPE` (rung-1 constants).
- `config_flow.py`, room branch of `async_step_init`: Simple mode = room-type
  steps + any hidden step that holds a non-default value + "More settings…";
  Advanced mode = full menu. New `async_step_show_all_settings`.
- In-use check compares stored values (`{**data, **options}`) with the
  **factory default**, which comes from rendering the step on a separate shim
  flow whose stub entry carries only entry type + room type (plan R1). The
  live flow is never touched; the shim render has no side effects (tested).
  If that render fails, the step is shown (fails open).
- `_adv()` marks Advanced-only fields, but leaves a field unmarked when it holds
  a non-default value. Covers and Climate now go through HA's
  `add_suggested_values_to_schema` (as Lighting already did), so the marker
  takes effect.
- Hint helper renamed: `lighting_advanced_hint` -> `advanced_hint`,
  `LIGHTING_ADVANCED_HINT_*` -> `ADVANCED_HINT_*` (same text). New
  `room_menu_hint`.
- No runtime behaviour change, no migration, no new entities.

### Live checks (post-restart)

- **Closet, Advanced mode off:** menu shows 5 items (Basic, Sensors, Devices,
  Lighting, Covers) + "More settings…"; the hint names "closet rooms" and
  explains Profile -> Advanced mode. "More settings…" -> 12 items; re-open -> 5.
- **Same closet, Advanced mode on:** 12 items, no "More settings…", hint
  "Advanced settings shown."; Climate & Fans shows the fan-speed temperatures;
  Covers shows sunrise/sunset offsets.
- **Garage:** Covers not in the menu; "More settings…" shows it.
- **Legacy room:** a trimmed-type room with energy or notification values only
  in `entry.data` shows those sections without "More settings…".
- **Any room with a changed sunrise offset, Advanced off:** Covers shows the
  sunrise offset field.
- **Integration / Coordinator Manager menus:** description reads normally (no
  literal `{menu_hint}`).

### Validated <date>

(To be filled after deploy + restart, per the README write-back rule.)

## PROPERTY-GETTER-SIDE-EFFECT-TASKS-1 — sensor getters no longer start background work

Version: TBD (PATCH). Tier 2. Branch `fix/property-getter-pure-2`. Build to review only, no deploy.

### What changed
Three entity property getters started background work every time anything read them (recorder,
UI, templates, possibly from a thread other than the event loop). Each getter now only returns a
value. The work moved to an update path that HA runs on the event loop.

| Site | Before (in getter) | Now (discharge) |
|---|---|---|
| `aggregation.py` `SafetyAlertBinarySensor.is_on` | `async_create_task(_process_alerts)` on every read while alerts exist | `async_update` (HA poll, once per scan interval). Task tracked in `_alert_task`, re-entry guarded, cancelled in `async_will_remove_from_hass`. `_process_alerts` keeps its coordinator-manager guard and 60s debounce (operator call B, 09-26: fallback kept, trigger moved). |
| `sensor.py` `UnavailableEntitiesSensor.native_value` | `sensor_dropout` memory episode logged on an empty-to-non-empty transition, detected inside the getter | `_handle_coordinator_update` (@callback) calls `_check_dropout_episode()`, then the normal state write. Same transition logic and payload. |
| `sensor.py` `SafetyEventsSummarySensor.native_value` | 24h cache refresh task spawned when stale | `async_update` (HA poll). Same TTL, re-entry guard and cancel-on-remove. |

Displayed values are unchanged: `is_on` = any alert, `native_value` = unavailable count / cached
24h count. Attributes untouched.

### Behaviour notes
- Legacy alert processing now runs at most once per poll (30s default) instead of once per read.
  On this house it remains a no-op (coordinator manager present). On an install without the
  coordinator manager, the first alert action can come up to one poll later than before.
- The dropout episode fires on a coordinator refresh, not on a read. A transition that happens and
  clears between refreshes is not logged. Before, it was only logged if something read the entity
  inside that window, so this case was never reliable.

### Not done (deliberate)
- The hardcoded 85/55/70/25 bands in `_get_alerts` (card's adjacent finding). Under option B they
  are live again only on a no-coordinator-manager install. Not in this card's scope. Needs a
  follow-up card if knobs are wanted.
- The other ~134 `@callback`/timer task sites (card constraint: out of scope).

### Acceptance
- **Test:** `quality/tests/test_property_getter_pure.py` (9 tests, real entity classes).
- **Drills:** four call-neuter drills, each fails exactly one named test (see the review record).
- **Live:** `binary_sensor.universal_room_automation_safety_alert` and
  `sensor.ura_safety_events_summary` show the same state/attributes as before restart.
  No "calls hass.async_create_task from a thread other than the event loop" lines naming
  aggregation.py/sensor.py in the core log.

## ZONE/HOUSE dialog wording — raw-key labels, retired strings, restart notices

Cards: ZONE-DIALOGS-CLEANUP-1 + HOUSE-DIALOGS-CLEANUP-1 (slice A = D1, D3, D5).
Plan: `docs/planning/PLANNING_zone_house_dialog_cleanup.md`.
Branch: `feature/zone-house-wording`. Version: set at deploy (PATCH).

### What changed (wording only, no behaviour change)

**Raw-key bugs fixed** (the form showed the internal key name):
- House > Perimeter Alerting: all 9 fields now labelled (vehicle hours, AI descriptions, snapshot delay). The description now says it is about vehicles.
- House > Camera Census: `known_face_guests`, `egress_identity_failsafe_strict`, `auto_enable_person_detection` now labelled.
- Zone > Name and rooms: `zone_is_outdoor` now shows "Outdoor zone".
- House > Person Tracking: `person_data_retention_days` now labelled (string key renamed to match the schema key).

**Dead strings removed:** 6 energy fields retired in v4.2.0, the 4 retired `perimeter_alert_*` fields, the `manage_zones` form fields (it is a menu now).

**Label-style pass:** shorter labels, plain helpers of 220 characters or fewer, no version tags, no "DPM" / "RAW" / entity ids. Zone menu: "Name and rooms", "Thermostat", "Person sensors" (O3), "Weather comfort".

**Restart notices:** Global Sensors, Energy Sensors, Person Tracking and Default Notifications say "Saving briefly restarts URA." Camera Census says "Some changes here briefly restart URA." Zone Thermostat says "Zones sharing this thermostat get the same settings."

**CM menu:** "Alert noise" and "Who gets which alerts". The volume description loses "Rung-2 controls (NM Cycle A-2)" and "Fields left at defaults do not persist". The HVAC weather-preset description says "Weather comfort" instead of "DPM".

**Code:** `async_step_person_tracking` drops two unused `description_placeholders`. Nothing else.

### Not done in this slice
- D2 + D4 (Simple/Advanced markers, camera_census reorder, dead-field hiding): slice B, waits for `feature/room-trimmed-menu` (`advanced_hint`, `_adv`).
- O4 (House "Default Notifications" relabelled as room alert fallback): left for an operator decision. Only the restart notice was added.
- HVAC-VACANCY-SWEEP-KNOB-UNWIRED-1: out of scope (behaviour), needs carding.

### Tests
- New `quality/tests/test_zone_house_dialog_strings.py` (94 cases): label + helper for every rendered zone/house field in both files, no orphan field strings, no jargon, zone and CM menu labels, restart notices, CM descriptions.
- `test_dpm_cleanup_and_labels.py`: allow-list extended for the intentionally removed keys.
- Mutation drills: re-inserting "(v4.5.11)" fails `test_no_jargon_in_zone_house_strings[zone_hvac]`; restoring a `perimeter_alert_notify_service` string fails `test_zone_house_strings_have_no_orphan_field_labels[perimeter_alerting]`.

### Live validation (to fill in after restart)
- Zone Manager > any zone > Name and rooms: outdoor toggle reads "Outdoor zone".
- House > Perimeter Alerting: 9 readable labels, no raw keys.
- House > Camera Census: no raw keys; "Smarter counting" without "(v2)".
- CM > Configure: rows "Alert noise" and "Who gets which alerts".

## Live validation
### Validated 2026-10-03

| Criterion | Status | Evidence |
|---|---|---|
| `drain_targets_effective` == raw on healthy ladder | PASS | Live `{10,15,20,30,30,unknown 40}` identical. |
| No `threshold_ladder_violation` after restart | PASS | 0 rows. |
| Inclement hold_depth on clear night | PASS | `allow_discharge`, tier none. |
| Pure sensor getters | PASS | `sensor.ura_safety_coordinator_safety_events_summary` clean; no off-loop task log lines; 0 URA ERRORs. |
| Room menu trim / Zone-House wording | pending operator UI | Code live, no config-flow exceptions. |
