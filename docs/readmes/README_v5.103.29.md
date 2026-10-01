# v5.103.29 — Room lighting roles + role-vs-inventory sweep (Slices A–E)

**Status:** DRAFT, deploy HELD for operator go.
Branch: `feature/room-lighting-roles`.
Card: ROOM-LIGHTING-SETUP-REDESIGN-1.
Plan: `docs/planning/PLANNING_room_dialog_cleanup_and_lighting_roles.md` (REV 2.3 + 2.3.1 + 2.3.2).

This README is written slice-by-slice. Slice A landed first — additive,
zero behaviour change. Slice B (D1 darkness) and Slice C (D2 hold + D3
switch) follow in the same branch. Do NOT deploy until every planned
slice has either shipped or been explicitly parked.

---

## Slice A — 2026-09-29 (this commit)

D0 (blast-radius audit) + D8 (role picker inventory) + resolver +
resolver-equivalence test + role picker enumeration.

### What shipped

- `custom_components/universal_room_automation/lighting/resolver.py`
  — new module. `effective_entry_set(cfg, is_sleep_hours)` and
  `effective_exit_set(cfg)`. Additive-only. Mirrors today's inline
  derivation at `automation.py:1000-1064,1079-1082` and
  `actuator_reconciler.py:109`. No callers yet — the helper is the
  seam Slices B–D will consume through.
- `custom_components/universal_room_automation/lighting/__init__.py`
  — package init exporting the two resolver helpers.
- `quality/tests/test_lighting_resolver_equivalence.py` — 28 tests.
  Hand-authored oracles rewrite today's inline code so a regression
  in either helper fails without touching the module under test.
  Both is_dark call-site derivations are covered indirectly through
  the exit-union oracle. Sleep-with-no-night-lights fallthrough is a
  named discriminator test (matches the exact seam `automation.py:1023`
  gates on).
- `docs/planning/AUDIT_sun_fallback_blast_radius.md` — D0 audit doc.
  AFFECTED = 3 rooms at probe time (2 no-sensor + 1 currently-unavailable
  lux sensor). Operator sign-off gates D1 (Slice B) build.
- `docs/planning/AUDIT_room_dialog_role_picker_inventory.md` — D8
  enumeration. 7 role-picker sites in `config_flow.py`, tagged
  KEEP/MOVE per plan. Physical MOVE is Slice B.

### Zero-behaviour-change proof

- Slice A adds a new package (`lighting/`), a new test file, and two
  audit docs. Nothing in `automation.py`, `actuator_reconciler.py`,
  `config_flow.py`, `switch.py`, or any coordinator is touched. The
  helper has no callers yet; production code paths are byte-identical
  to develop @ `1bb5f72fa`.
- Resolver-equivalence test (28 tests) proves the helper matches the
  inline derivation on 8 config fixtures × 2 sleep states for entry,
  plus 8 fixtures for exit, plus 4 named discriminators.

### Per-site drills (Slice A load-bearing sites)

Ran on 2026-09-29, this commit, PYTHONDONTWRITEBYTECODE=1 +
`__pycache__` cleared before each run:

| Site | Mutation | Result |
|---|---|---|
| `resolver.py::effective_entry_set` day/union return | replace return with `return []` | 11 tests FAIL, tree restored, 28/28 PASS after restore |
| `resolver.py::effective_exit_set` union return | replace return with `return []` | 8 tests FAIL, tree restored, 28/28 PASS after restore |

Both helpers are load-bearing on the resolver-equivalence suite. Clean
`git status --short` after restoration verified.

### Test selection + name-diff vs develop

Selection: `-k "light or automation or reconciler or config_flow or options or strings"`.

| Run | Passed | Failed | Skipped | Deselected |
|---|---:|---:|---:|---:|
| develop @ `1bb5f72fa` baseline | 1026 | 5 (pre-existing) | 4 | 10958 |
| feature/room-lighting-roles (Slice A) | 1054 | 5 (same) | 4 | 10958 |
| Delta | **+28 (new tests)** | 0 new failures | 0 | 0 |

Pre-existing failures (unchanged on both sides, unrelated to Slice A):

- `test_census_device_switches.py::test_d4_transit_validator_reads_true_on_empty_options`
- `test_census_device_switches.py::test_d4_presence_initial_read_returns_true_on_empty_options`
- `test_d3_area_inherit.py::test_options_overrides_data_for_area`
- `test_energy_write_verification.py::test_c_med_1_h3_options_round_trip_source_anchor`
- `test_v5_7_1_energy_precool.py::TestD5Migration::test_restore_entity_off_overrides_options_true`

### Live acceptance criteria (prospective, for Slice A alone)

Because Slice A has no runtime callers, live acceptance reduces to:

- Verify: `custom_components/universal_room_automation/lighting/`
  package loads with no import error on HA start (integration reload
  clean).
- Verify: no room entry/exit lighting behaviour change post-deploy vs
  pre-deploy for any test room (baseline unchanged — nothing consumes
  the helper yet).
- Live: at least one dark-only room with a working lux sensor lights
  on entry at dusk (control observation — proves today's path is
  unaffected).

Live validation results table will be filled in post-restart per the
CLAUDE.md "Record Live Validation Back Into the README" rule.

### Slice A deferrals (tracked, not dropped)

- Physical picker MOVE (Night Lights → Lighting step, Alert Lights →
  Lighting step, Auto/Manual → behaviour Auto/Manual sub-block).
  Deferred to Slice B because MOVE without dynamic `include_entities`
  from in-flight flow state hits F5 (silent value drop on save).
- `CONF_AUTO_DEVICES` / `CONF_MANUAL_DEVICES` picker rendering not
  found in `config_flow.py`; Slice B must locate before MOVE.
- Strings / translations: no updates in Slice A because no new
  form fields. Slice B / D1 will extend `strings.json`,
  `translations/en.json`, and `quality/tests/test_room_dialog_strings.py`
  when the Lighting step is added.

---

## Slice B — 2026-09-29 (D1 darkness fallback)

Adds a sun-position fallback to `RoomAutomation.is_dark` for rooms
whose primary illuminance sensor returns None (no sensor, or state
`unavailable` / `unknown`). Per-room kill switch defaults TRUE per
operator P0 ruling.

### What shipped

- `const.py` — new keys `CONF_LIGHT_DARK_USE_SUN_FALLBACK`,
  `CONF_LIGHT_DARK_LUX_SOURCE`, and module-const safety bound
  `SUN_DARK_ELEVATION_DEG = -6.0` (civil dusk).
- `lighting/darkness.py` — new module. `is_dark_fallback(cfg, hass)`
  implements the plan §D1 order: borrowed lux → sun → False.
  Availability-only freshness (R2-3): sensor state in
  `unavailable`/`unknown`/empty is skipped, `last_updated` age is
  NEVER consulted. Fail-safe: any exception ⇒ False (never
  auto-light on error).
- `automation.py::is_dark` — extended to route the None-illuminance
  case through `is_dark_fallback`. Because
  `actuator_reconciler.py:794` calls `automation.is_dark(...)`, both
  is_dark call sites the plan enumerated (F2 / R2-2) route through
  ONE definition and receive the fallback.
- `lighting/__init__.py` — exports `is_dark_fallback`.

### What was intentionally deferred (with reasons)

- **No new options-flow field for `CONF_LIGHT_DARK_USE_SUN_FALLBACK`.**
  The code respects the key from stored options; default TRUE per
  operator P0 ruling covers the intended behaviour for the ~3
  AFFECTED rooms. A per-room UI toggle needs `strings.json` +
  `translations/en.json` + `test_room_dialog_strings.py` extension —
  operator's guidance was "borrowed lux only if trivial, else note it
  for a later slice"; the same trivia-vs-slice-bloat calculus applies
  here. **Tracked as a Slice B' follow-up: add
  `CONF_LIGHT_DARK_USE_SUN_FALLBACK` (bool) + `CONF_LIGHT_DARK_LUX_SOURCE`
  (entity) as config-flow fields in the Lighting step once that step
  exists in Slice C or later.** Until then, operators who need a
  per-room disable set the key manually or accept default-TRUE.
- **Borrowed lux (`CONF_LIGHT_DARK_LUX_SOURCE`) code path** IS
  implemented (trivial add — 5 lines) — see step 1 of
  `is_dark_fallback`. It reads from stored options if set. Only the
  UI to set it is deferred with the kill-switch toggle.

### Behaviour change on live rooms (from the D0 audit)

For the 3 AFFECTED rooms (2 no-sensor + 1 currently-unavailable lux
sensor), `entry_light_action = turn_on_if_dark` now engages after
civil dusk instead of never engaging. All other rooms unchanged.

### Per-site drills (Slice B load-bearing sites)

Ran on 2026-09-29, this commit:

| # | Site | Mutation | Result |
|---:|---|---|---|
| 3 | `lighting/darkness.py::is_dark_fallback` sun path (`return elev < SUN_DARK_ELEVATION_DEG`) | replace with `return False` | 8 tests FAIL (7 fallback + 1 wiring); restored; 52/52 PASS |
| 4 | `automation.py::is_dark` call to `is_dark_fallback` | keep import, replace call with `return False` | 1 test FAIL uniquely (`test_none_lux_sun_below_dusk_falls_through_to_true`), proving the wiring at this site is the load-bearing path; restored; 52/52 PASS |

Drill #4 is the wiring drill required by F2 / R2-2 (both is_dark
callers must reach the new fallback). Because
`actuator_reconciler.py:794` delegates to `automation.is_dark`,
neutering the automation.py call site also breaks the reconciler
path — one drill covers both consumer surfaces.

### Test selection + name-diff vs develop (Slice A + Slice B)

Selection: `-k "light or automation or reconciler or config_flow or options or strings"`.

| Run | Passed | Failed | Skipped | Deselected |
|---|---:|---:|---:|---:|
| develop @ `1bb5f72fa` baseline | 1026 | 5 (pre-existing) | 4 | 10958 |
| feature/room-lighting-roles (Slice A) | 1054 | 5 (same) | 4 | 10958 |
| feature/room-lighting-roles (Slice A + B) | 1072 | 5 (same) | 4 | 10964 |
| Delta A→B | +18 (new fallback tests in-selection) | 0 | 0 | +6 (wiring tests, names not matched by `-k`) |
| Cumulative delta A+B | **+46 in-selection, +6 out-of-selection** | 0 new failures | 0 | +6 |

Same 5 pre-existing failures (listed under Slice A above); zero
regressions from Slice B.

### Live acceptance criteria (Slice B, prospective)

- Verify: a room with no `CONF_ILLUMINANCE_SENSOR` and
  `entry_light_action=turn_on_if_dark` lights on entry after civil
  dusk (previously never lit).
- Verify: same room during daylight (sun elevation > 0) does NOT
  light on entry.
- Verify: Garage B (currently-unavailable lux sensor) behaves the
  same as no-sensor rooms — lights at dusk, dark at day. When its
  sensor recovers, primary-lux path resumes automatically.
- Verify: any room with a working lux sensor is UNCHANGED — the
  fallback only fires when the primary read is None.
- Verify: setting `CONF_LIGHT_DARK_USE_SUN_FALLBACK: false` on a
  room's stored options (via YAML / storage edit until Slice B' UI
  lands) preserves today's `is_dark(None) == False` for that room.

Live validation results table filled in post-restart.

---

## Slice B′ — 2026-09-30 (Lighting behaviour step + role picker MOVE + outdoor-light tier)

D1 (Lighting step / role pickers) + D8 physical picker MOVE + Slice B REV 2.4
(weather-adjusted outdoor illuminance tier, integration-level Global Sensors
knobs).

### What shipped

- `const.py` — new keys: `CONF_LIGHTS_ON_ENTRY`, `CONF_LIGHTS_ON_ENTRY_DARK_ONLY`,
  `CONF_LIGHTS_LEAVE_ON_WHEN_EMPTY`, `CONF_AWAY_TURN_OFF_LEAVE_ON`,
  `CONF_OUTDOOR_LIGHT_SENSOR`, `CONF_OUTDOOR_DARK_LUX`, `DEFAULT_OUTDOOR_DARK_LUX=400.0`.
  All additive; ABSENT preserves today's resolver output.
- `lighting/resolver.py` — `effective_entry_set` gains an `is_dark`
  parameter and honours `CONF_LIGHTS_ON_ENTRY` (subset semantics) and
  `CONF_LIGHTS_ON_ENTRY_DARK_ONLY` (removed when `is_dark is False`).
  `effective_exit_set` subtracts `CONF_LIGHTS_LEAVE_ON_WHEN_EMPTY`.
  Sleep-hours night-only path unchanged.
- `automation.py::_control_lights_entry` — routes through the resolver.
  When `CONF_LIGHTS_ON_ENTRY` is set, turns on exactly the resolved set
  (domain-split); otherwise today's `_turn_on_regular_lights` +
  `_turn_on_night_lights(mode="day")` path.
- `automation.py::_control_lights_exit` — off_set now sourced from
  `effective_exit_set(self.config)` (leave-on carve-out).
- `actuator_reconciler.py::_resolve_light` — occupied branch restricts
  to `effective_entry_set(cfg, sleep, is_dark)` when
  `CONF_LIGHTS_ON_ENTRY` is set. Vacant branch off_set sourced from
  `effective_exit_set(cfg)`.
- `lighting/darkness.py` — `is_dark_fallback` tier order:
  1. Borrowed lux (room-scale threshold).
  2. Outdoor illuminance from the OPERATOR-CONFIGURED
     `CONF_OUTDOOR_LIGHT_SENSOR` at integration level, compared against
     `CONF_OUTDOOR_DARK_LUX` (default 400). No silent auto-discovery.
  3. Sun elevation < `SUN_DARK_ELEVATION_DEG`.
  4. False.
  Same `CONF_LIGHT_DARK_USE_SUN_FALLBACK` kill switch disables tiers 3
  AND 4. New helper `discover_outdoor_illuminance_suggestion(hass)` is
  used ONLY by the form (visible pre-fill).
- `config_flow.py` room options — new `async_step_options_lighting_behaviour`
  step added to the room options menu. Fields (in order): on-entry
  picker, dark-only subset, night lights, leave-on-when-empty,
  `CONF_AWAY_TURN_OFF_LEAVE_ON` (default TRUE), alert lights,
  `CONF_LIGHT_DARK_USE_SUN_FALLBACK`, `CONF_LIGHT_DARK_LUX_SOURCE`,
  collapsed Auto/Manual sub-block. Picker `include_entities` built from
  in-flight state (`LIGHTS ∪ NIGHT_LIGHTS ∪ ALERT_LIGHTS ∪ stored value`)
  so a saved entity outside `CONF_LIGHTS` is never dropped on save (F5
  round-trip guarantee). Read-only per-light feature summary from
  `state.attributes.supported_color_modes`.
- `config_flow.py` options `async_step_devices` — Night Lights entity
  picker + Auto/Manual switch pickers REMOVED (moved to the new step).
  Night brightness/color fields stay in Devices (value tunables, not
  role pickers). Same keys, no stored-data migration.
- `config_flow.py` options `async_step_notifications` — Alert Lights
  entity picker REMOVED (moved); `CONF_ALERT_LIGHT_COLOR` stays.
- `config_flow.py` options `async_step_global_sensors` — new
  `CONF_OUTDOOR_LIGHT_SENSOR` (illuminance-device-class entity picker,
  visible suggested pre-fill from `illuminance` platform when unset)
  and `CONF_OUTDOOR_DARK_LUX` (Number, default 400).
- `strings.json` + `translations/en.json` — new step + Global Sensors
  fields. Labels plain (≤4 words, no nerd terms).
- `quality/tests/test_lighting_slice_b_prime.py` — 19 tests: resolver
  new-key semantics + darkness tier ordering + threshold discrimination
  (399/401) + kill switch + form-prefill discovery + disabled entries.
- `quality/tests/test_room_dialog_strings.py` — extended
  `ROOM_OPTIONS_STEPS` with `options_lighting_behaviour`; 257/257 pass
  (30 new field assertions).

### Per-site mutation drills

Ran 2026-09-30, PYTHONDONTWRITEBYTECODE=1 + `__pycache__` cleared before
each run. Each mutation restored in Python (rewrite saved source);
`git status --short` clean after the drill loop (only intended edits
remain).

| # | Site | Mutation | Result |
|---:|---|---|---|
| 1 | `resolver.py::effective_entry_set` on_entry branch | `if False and on_entry:` | 1 test FAIL (`test_on_entry_present_restricts_set`), 3 unrelated PASS; restored |
| 2 | `resolver.py::effective_entry_set` dark-only carve-out | neuter block | 1 test FAIL (`test_on_entry_dark_only_removed_when_not_dark`); restored |
| 3 | `resolver.py::effective_exit_set` leave-on carve-out | neuter block | 1 test FAIL (`test_leave_on_carves_out_exit`); restored |
| 4 | `darkness.py::is_dark_fallback` outdoor tier branch | `if False and outdoor_eid:` | 1 test FAIL (`test_outdoor_configured_and_available_below_threshold`); restored |
| 5 | `actuator_reconciler.py` exit `effective_exit_set` wiring | replace with inline union | 0 FAIL (equivalence-only when leave-on empty; no in-suite reconciler-with-leave-on harness — noted as coverage gap for Slice C behavioural harness); restored |

Drills 1-4 are load-bearing on the Slice B' resolver suite. Drill 5 is
noted: the reconciler wiring is byte-identical to the old union when
`CONF_LIGHTS_LEAVE_ON_WHEN_EMPTY` is absent, so a mutation to the old
union passes all in-suite tests. Coverage of the reconciler-with-leave-on
path is deferred to the Slice C behavioural harness (D2 hold suite),
which already needs an actuator-reconciler test rig.

### Test selection + name-diff vs develop

Selection: `-k "light or automation or reconciler or config_flow or options or strings"`.

| Run | Passed | Failed | Skipped | Deselected |
|---|---:|---:|---:|---:|
| develop @ `1bb5f72fa` baseline | 1026 | 5 (pre-existing) | 4 | 10958 |
| Slice A + B (per prior section) | 1072 | 5 (same) | 4 | 10964 |
| Slice A + B + B′ (this ship) | 1102 | 5 (same) | 4 | 10964 |
| Delta B → B′ | **+30 (new B′ tests + 11 new B′ options-flow field asserts in strings test)** | 0 new failures | 0 | 0 |

Same 5 pre-existing failures (listed in Slice A). Zero regressions.

### Live acceptance criteria (Slice B′, prospective — deploy HELD)

- Verify: Room options menu shows a new "Lighting behaviour" step
  between "Lighting Automation" and "Cover Automation".
- Verify: Room options → Devices no longer lists Night Lights picker
  (brightness/color still there); no Auto/Manual switch pickers.
- Verify: Room options → Notifications no longer lists Alert Lights
  picker; Alert Light Color still there.
- Verify: Integration options → Global Sensors shows "Outdoor light
  sensor" (pre-filled with `sensor.phalanxmadrone_illuminance` because
  that entity's platform is `illuminance`) and "Dark outside below" (400).
- Verify: with `CONF_LIGHTS_ON_ENTRY = [light.a]` set on a room whose
  `CONF_LIGHTS = [light.a, light.b]`, entry turns on ONLY `light.a`.
- Verify: with `CONF_LIGHTS_LEAVE_ON_WHEN_EMPTY = [light.a]` set, exit
  leaves `light.a` on and sweeps `light.b` off.
- Verify: darkness tier — with the outdoor sensor configured and
  reading < 400, no-lux room lights on entry (dark). Above 400: no.
- Verify: with outdoor sensor unset, previous sun-elevation behaviour
  preserved.
- Verify: Round-trip — save a night light outside `CONF_LIGHTS` in the
  new step, close, reopen: value preserved (F5 guard).

Post-restart validation table filled per CLAUDE.md rule.

### Slice B′ deferrals (tracked)

- Night light brightness/color fields MOVE (plan REV 2.3 producer/consumer map
  says these MOVE too). Kept in Devices this ship — value tunables, not role
  pickers; scope minimisation. Follow-up card.
- Reconciler-with-leave-on behavioural harness (drill #5 coverage gap).
  To be added alongside Slice C D2 hold suite.
- D2 manual hold + D3 room-light switch: Slice C, not built.
- Away-turn-off-leave-on ACTUATION (the boolean is stored + shown but
  the Away-branch sweep in `automation.py` exit is not yet gated by
  house-state=Away; that's D4). Boolean is inert until D4 lands.

---

## Slice C — 2026-09-30 (D2 light manual hold + URA write mark + D3 Room lights switch)

### Falsifiable invariant
**No URA write ever opens a manual hold; a person's change to a room light
during occupancy is never undone by URA until the room empties.**
Falsifier: any URA light write whose `state_changed` lands in the D2 listener
unmarked, or any URA OFF (ON) path that moves a light under a live person
ON-hold (OFF-cooldown) while the room is occupied.

### What shipped
- `ura_context.py` — the URA write mark. HA Context API verified in the installed
  HA 2026.2.3 (`core.py:1208-1224` Context; `core.py:2712-2737` async_call
  `context`; `helpers/service.py:838,868,888` `async_set_context(call.context)`;
  `helpers/entity.py:82,932-935,1235-1248` context kept 5 s and written onto the
  state). **Deviation from plan R2-1:** the mark rides `Context.parent_id` (a fixed
  valid ULID, `URA_WRITE_CONTEXT_PARENT_ID`) with a fresh ULID `id` — a shared
  non-ULID `id` would be stored NULL by the recorder (`db_schema.py:319-323`) and
  merge all URA writes into one logbook context. Only `light.*` / `switch.*`
  writes carry the mark (`URA_LIGHT_WRITE_DOMAINS`); every other domain
  (climate, cover, fan, number…) is byte-identical.
- `domain_coordinators/light_policy_oracle.py` — per-room, per-light ledger
  (fan-oracle shape): `note_manual`, `may_turn_on/off`, `allowed`,
  `release_on_vacancy` (ON holds only), `release`. RAM-only; any error allows the
  URA write (today's behaviour). Room key = room entry_id.
- Listener: the reconciler's existing room-light subscription (reuses its
  rebuild + teardown lifecycle) books a change only if: room light, real on↔off
  edge, not URA-marked, room occupied.
- Hold respected at: entry on-entry branch, `_turn_on_regular_lights`,
  `_turn_on_night_lights`, `_turn_off_non_night_lights` (sleep entry),
  shared-space scheduled auto-off, reconciler `_reconcile_one`, HVAC zone
  vacancy sweep (lights).
- Hold ends when the room counts as empty: `handle_occupancy_change(False)` calls
  `release_light_holds_on_vacancy()` before the sleep gate and the exit sweep.
  OFF cooldowns survive vacancy (plan).
- Knobs (rung 2, Lighting behaviour step): `light_manual_on_hold_s` "Keep lights I
  turn on (seconds)" default 3600; `light_manual_off_cooldown_s` "Keep lights I
  turn off (seconds)" default 900; 0 = that kind off.
- D3 `RoomLightsSwitch` ("Room lights", `switch.<room>_room_lights`): ON = resolver
  `effective_entry_set` for the current mode; OFF = every room light incl. leave-on;
  both call `note_manual_light` directly; writes go through the stamped
  `_safe_service_call`. State = any room light on.

### Writer inventory (plan table + surfaced writers)
| # | Writer | Stamp site | Hold verdict |
|---|---|---|---|
| 1-4 | Room entry / exit / reconciler (primary) / D3 switch / room alert lights / warning flash / shared-space off | `automation._safe_service_call` | entry+sleep+shared-space respect; exit after release |
| 2b | Reconciler fallback direct call | `actuator_reconciler._safe_service_call` | respects (`_reconcile_one`) |
| 5 | NM alert pattern + restore (9 calls) | `NotificationManager._ura_light_call` | exempt |
| 6 | Aggregation alert flash (3 calls) | `_flash_light` | exempt |
| 7-8 | Safety emergency lights, Security lights | `CoordinatorManager._execute_action` | exempt |
| 9 | Security delegate switch | writes nothing itself (config toggle) — see deferrals | — |
| 11 (NEW) | HVAC zone vacancy sweep (lights) | `hvac._execute_vacancy_sweep` | respects |
| 12 (NEW) | Optimizer L2 device/config dispatch | `optimization._dispatch_*_action` | stamped only (question below) |
| 13 (NEW) | Per-room AI rule action | `coordinator._execute_rule_action` | stamped only (question below) |

### Per-site mutation drills (2026-09-30; PYTHONDONTWRITEBYTECODE=1, `__pycache__` cleared, source restored in Python, `git status` clean after)
| Site | Test that goes RED |
|---|---|
| S1 room-tier stamp | `test_w1_room_tier_write_is_ura_stamped`, `test_listener_ura_write_opens_no_hold`, `test_d3_turn_on_equals_effective_entry_set[*]` |
| S2 reconciler fallback stamp | `test_w2_reconciler_fallback_write_is_ura_stamped` |
| S3 NM helper stamp | `test_w3_nm_alert_flash_and_restore_are_ura_stamped`, `test_listener_alert_flash_opens_no_hold_R2_1` |
| S3b NM restore-off routed via helper | same two |
| S4 aggregation stamp | `test_w4_aggregation_alert_flash_is_ura_stamped` |
| S5 manager (safety + security) stamp | `test_w5_safety_security_light_actions_are_ura_stamped` |
| S6 HVAC zone-sweep stamp | `test_slice_c_zone_sweep_light_write_is_ura_stamped` |
| S7 optimizer device stamp | `test_optimizer_light_dispatch_is_ura_stamped` |
| S8 AI-rule stamp | `test_w8_ai_rule_light_action_is_ura_stamped` |
| S10a/b D3 note_manual on/off | `test_d3_turn_on_opens_hold_via_note_manual_only` / `test_d3_turn_off_includes_leave_on_and_notes_manual` |
| L1 listener URA filter | `test_listener_ura_write_opens_no_hold`, R2_1 |
| L2 listener occupied gate | `test_listener_vacant_room_opens_no_hold` |
| L3 listener on/off edge gate | `test_listener_availability_edge_opens_no_hold` |
| L4 listener entity gate | `test_listener_foreign_entity_ignored` |
| L5 listener wire-in call | `test_listener_person_on_while_occupied_opens_hold` (+12) |
| H1-H5 automation hold sites | `test_h1_on_entry…`, `test_h2_regular…`, `test_h3_night…`, `test_h4_sleep…`, `test_h5_shared…` |
| H6 reconciler hold | `test_h6_reconciler_does_not_undo_person_on`, `test_h6_reconciler_respects_off_cooldown`, `test_manual_mode_and_hold_are_disjunctive` |
| H7 HVAC sweep hold | `test_slice_c_zone_sweep_spares_person_held_light` |
| C1 hold-clear-on-empty seam | `test_c_hold_cleared_on_vacancy_then_sleep_entry_turns_off` |
| O1 oracle compare / O2 knob-0 | `test_oracle_boundaries_literal` / `test_knob_zero_disables_hold_and_cooldown` |
| R1 reconciler vacant leave-on (Slice B′ drill #5 gap) | `test_reconciler_vacant_leave_on_carve_out` |

Every site RED; none green. Optimizer config-action stamp is inert by construction
(targets `number.*`, not a light domain) — not drilled.

### Name-diff vs develop (separate worktree at develop 4db79ff51 = merge-base code)
`-k "light or automation or reconciler or notification or security or safety or switch"`:
develop 12 failed / 1506 passed; branch 12 failed / 1622 passed. **New failures: 0; fixed: 0**
(same 12 pre-existing names). Order-robustness: the new file passes run before and
after `test_night_light_off_path` / `test_reconcile_on_return` / `test_nm_cycle_b_safety_rails`
(its real-HA modules live in a module-scoped fixture that restores `sys.modules`).
Updated stale stubs: `test_hvac_vacancy_sweep_manual_on_guard.py` and
`test_optimization_coordinator.py` fake `async_call` now accept `**kw`.

### Deferrals / open questions (tracked, not dropped)
- **Security delegate `release()` hook:** `SecurityDelegateLightsSwitch` (switch.py) is
  a config toggle with no seize/release window; security writes are stamped so they
  can never open a hold, and the plan's "seize + release ⇒ no residual hold" holds by
  construction. No release hook built — operator question: is one wanted?
- **Late device echo > 5 s:** HA drops the call context after 5 s
  (`entity.py:1235-1240`); an echo arriving later looks like a person and opens a
  hold (bounded by vacancy + window). A value-matched last-write guard would close it — not in plan.
- **Optimizer / AI-rule light writes** are stamped but do not consult the hold
  (plan inventory had no verdict). Question: should they respect it?
- **HA automations chained by URA** (`automation.trigger`, scenes, scripts) run under
  their own child contexts and count as a person's change.
- Manual Mode ON: the vacancy transition is not observed (coordinator skips the
  handler), so a hold lives until its window; harmless while URA is not acting.
- Holds are RAM-only (fan-oracle precedent); a restart forgets them.
- Plan live criterion `sensor.<room>_light_manual_hold_remaining_s` NOT built
  (conflicts with the plan non-goal "only new entity is the switch").
- D3 uses the room's real darkness for the dark-only subset (plan silent).

---

---

## Slice D — 2026-09-30 (D4 house-state awareness for lights)

### Falsifiable invariant
**On the Home→Away edge, a room turns OFF exactly the entities in its
`CONF_LIGHTS_LEAVE_ON_WHEN_EMPTY` list (or none, when the per-room
`CONF_AWAY_TURN_OFF_LEAVE_ON` boolean is False, or when the list is
empty, or during boot-settle). It touches nothing else. A repeated Away
signal without a state edge is a no-op.** Everywhere else (entry / exit
/ reconciler / HVAC-zone sweep / D3 switch) the Slice C manual-hold
still vetoes URA — the Away sweep is the sole documented exception,
gated by the operator opt-in.

### What shipped

- `automation.py::handle_away_leave_on_sweep` — new async method. Reads
  `CONF_LIGHTS_LEAVE_ON_WHEN_EMPTY` + per-room `CONF_AWAY_TURN_OFF_LEAVE_ON`
  (default True), splits into `light.*` / `switch.*` and issues a
  URA-stamped `turn_off`. Gated by `_away_boot_settle_done()` which reuses
  the presence coordinator's existing `_boot_settle_done` primitive
  (`fan_veto._boot_settle_done` idiom) — no new listener or timer.
  Documentation-constant `AWAY_LEAVE_ON_BOOT_SETTLE_S=60` retained in
  `const.py` for the plan-D4 60 s bound.
- `automation.py::is_sleep_mode_active` — plan D4 precedence: HouseState
  == "sleep" ⇒ True even outside the per-room sleep clock. Reads through
  the same `_read_current_house_state()` primitive the fan-onset path
  uses; fails open (no state read ⇒ clock alone, today's behaviour).
- `coordinator.py::_on_house_state_changed` — edge-only Away dispatch.
  Tracks `_last_house_state_for_away` per room-coordinator; on the
  transition INTO `away` schedules `handle_away_leave_on_sweep()` via
  the entry-scoped background task (`eager_start=False`, matches the
  existing chained-automation dispatch). A repeat Away signal without a
  state change is a no-op — the no-flap contract.
- `coordinator.py::_execute_rule_action` — AI-rule light writes now
  RESPECT the manual hold. For `light.turn_on/off` and
  `switch.turn_on/off`, the target entity_ids are filtered through
  `LightPolicyOracle.allowed(room_key=entry_id, …)` before the call
  reaches HA. Fully-suppressed target ⇒ no-op; partial ⇒ narrowed
  entity list. Stamped writes still never open a hold (Slice C
  invariant preserved — the URA context mark is applied after the
  filter). Non-light domains are byte-identical.
- `automation.py::note_manual_light` — reads `CONF_LIGHT_MANUAL_ON_HOLD_S`
  / `CONF_LIGHT_MANUAL_OFF_COOLDOWN_S` from the room config (advanced
  override) and falls back to the rung-1 module constants
  `DEFAULT_LIGHT_MANUAL_ON_HOLD_S=3600` / `DEFAULT_LIGHT_MANUAL_OFF_COOLDOWN_S=900`.
- `config_flow.py::async_step_options_lighting_behaviour` — the two
  manual-hold-window fields Slice C added are now ADVANCED-only, each
  marked `description={"advanced": True}`. The step's return routes
  through `self.add_suggested_values_to_schema(vol.Schema(schema_dict), {})`
  so HA hides them unless the user profile has Advanced mode on
  (verified: `homeassistant/data_entry_flow.py:660-666` in installed HA
  2026.2.3; empty suggested-values mapping still runs the filter).
  Defaults are the module constants; 0 = that kind off; stored values
  are still honoured at runtime when hidden.
- `strings.json` + `translations/en.json` — helper text for the two
  hold-window fields prefixed with "Advanced. " so operators who see
  them in Advanced mode know why they are hidden by default.
- `const.py` — `AWAY_LEAVE_ON_BOOT_SETTLE_S=60` added as documentation
  constant; `CONF_LIGHT_MANUAL_*` and `DEFAULT_LIGHT_MANUAL_*` retained.

### Guest — deferred (documented, code unchanged)
Plan D4 enumerates `CONF_LIGHTS_GUEST_MODE ∈ {normal, off, night_lights_only}`
with default `normal` = today. Per operator ruling to keep this slice tight,
the Guest gate is not implemented in v5.103.29 — today's behaviour is
preserved (GUEST ⇒ same as HOME for lights). Follow-up card required
before ROADMAP_v12 6.0.0 (IDENTITY-DRIVEN AUTONOMY) closes.

### Per-site mutation drills (2026-09-30; PYTHONDONTWRITEBYTECODE=1, `__pycache__` cleared, source restored via Python rewrite, `git status` clean after each drill)

| # | Site | Mutation | Test that goes RED |
|---:|---|---|---|
| 1 | `automation.py::handle_away_leave_on_sweep` off-emit for leave-on | replace the two `_safe_service_call` awaits with `return` | `test_away_sweep_off_leave_on_only_when_boolean_true_and_list_nonempty`, `test_away_sweep_splits_domains`, `test_away_sweep_writes_are_ura_stamped`, `test_away_sweep_ignores_manual_hold_for_leave_on`, `test_home_away_home_no_double_emit` |
| 2 | `automation.py::handle_away_leave_on_sweep` `CONF_AWAY_TURN_OFF_LEAVE_ON` gate | force branch to `if False:` | `test_away_sweep_inert_when_boolean_false` |
| 3 | `automation.py::_away_boot_settle_done` gate | replace body with `return True` | `test_away_sweep_boot_settle_gate_suppresses` |
| 4 | `automation.py::is_sleep_mode_active` HouseState precedence branch | remove the HouseState=="sleep" check | `test_sleep_house_state_forces_sleep_semantics_outside_clock` |
| 5 | `coordinator.py::_execute_rule_action` AI-rule hold filter | short-circuit the `if domain in ("light","switch")` block with `if False:` | `test_ai_rule_light_write_suppressed_by_on_hold`, `test_ai_rule_light_write_partial_pass_when_only_some_held` |
| 6 | `coordinator.py::_on_house_state_changed` edge dispatch | replace `if str(new_state).lower() == "away" …:` with `if False:` | `test_away_dispatch_edge_only_no_flap`, `test_home_away_home_no_double_emit` |

All 6 mutations turn a NAMED test red; source restored by Python rewrite;
`shutil.rmtree(__pycache__)` executed between drills; `git status --short`
clean after each restoration.

### Test selection + name-diff vs develop

Selection: `-k "light or automation or reconciler or house_state or presence or switch or ai_rule"`.
Baseline worktree: `.claude/worktrees/validator-develop-0930` (develop @ `1d1625480`).

| Run | Passed | Failed | Skipped |
|---|---:|---:|---:|
| develop @ `1d1625480` baseline | 1213 | 17 (pre-existing) | — |
| feature/room-lighting-roles (Slices A + B + B′ + C + D) | 1347 | 16 (all subset of develop's) | — |
| Delta | **+134 new tests** | **0 new failures**; 1 develop-only pre-existing failure not present in the branch's selected set (`test_chatter_tick_helper::test_apply_chatter_tick_b_low_4_kill_switch_flip_discharges_latch`) | — |

Slice D adds 17 new tests (`test_lighting_slice_d_house_state.py`); the
remaining +117 are cumulative from Slices A/B/B'/C.

### Live acceptance criteria (Slice D, prospective — deploy HELD)

- Verify: with `CONF_LIGHTS_LEAVE_ON_WHEN_EMPTY=[light.porch]` and
  `CONF_AWAY_TURN_OFF_LEAVE_ON=True` on a test room, forcing house state
  to `away` turns off `light.porch` and leaves every other room light
  untouched.
- Verify: with `CONF_AWAY_TURN_OFF_LEAVE_ON=False`, forcing house state
  to `away` leaves the leave-on list untouched (opt-in inert).
- Verify: within ~60 s of `homeassistant_started`, a house_state=away
  boot pulse does NOT sweep the leave-on list (boot-settle gate).
- Verify: firing house_state=away twice in succession (no intervening
  edge) emits the sweep ONCE (no-flap).
- Verify: with the house state forced to `sleep` OUTSIDE the room's
  sleep clock window, entry lights up the night-lights set (Sleep
  precedence).
- Verify: after a person turns `light.a` ON in a room, an AI-rule that
  targets `light.a.turn_off` does NOT dispatch (fully suppressed);
  targeting `[light.a, light.b].turn_on` narrows to `[light.b]`.
- Verify: room-options Lighting behaviour step no longer shows the two
  "Keep lights I turn on/off (seconds)" fields to a default user
  profile; enabling Advanced mode in the user profile reveals both.
- Verify: an operator who previously set a non-default hold window (via
  Slice C) still sees that value applied at runtime even while the
  field is hidden (round-trip preserved).

Post-restart validation table filled per CLAUDE.md rule.

### Slice D deferrals (tracked)

- `CONF_LIGHTS_GUEST_MODE` (plan D4 Guest semantics) — code not wired;
  today's behaviour preserved. Requires follow-up card before 6.0.0.
- Away sweep works on the coordinator-received `SIGNAL_HOUSE_STATE_CHANGED`
  dispatch; a room whose coordinator is not `loaded` at the moment of
  the edge misses the sweep for that transition. Recovery is the next
  Away edge, or a manual dashboard action. Not a new gap (same as
  every other signal handler on that coordinator).
- Manual-hold-window ADVANCED fields render only inside the
  `options_lighting_behaviour` step; the room-device dashboard exposes
  no entity for them (operator ruling: "not on the room device").


---

## Slice E — 2026-09-30 (D5 time-of-day slots + D6 scenes + Advanced hint)

### Falsifiable invariant
**Absent every new Slice E key ⇒ byte-identical to Slice D behaviour
(resolver-equivalence still green; entry writes the same
brightness/colour/entities). Present ⇒ (1) `resolve_slot(is_sleep,
is_dark)` returns `sleep`/`evening`/`day` in that precedence, (2) the
Evening slot may override regular-light and night-light
brightness/colour, and (3) an operator-configured per-slot scene
short-circuits the per-light path via `scene.turn_on` while the URA
context still propagates to the constituent lights (verified against
installed HA 2026.2.3, so the D2 manual-hold listener still ignores
them — no separate quiet-window needed).**
Falsifier: any config with no Slice E keys whose entry set / brightness
/ colour differs from Slice D; any Evening entry that fails to use an
override that was set; any scene-configured entry that keeps calling
`light.turn_on` under the per-light path.

### What shipped

- `const.py` — new keys `CONF_LIGHT_EVENING_BRIGHTNESS_PCT`,
  `CONF_LIGHT_EVENING_COLOR_KELVIN`, `CONF_NIGHT_LIGHT_EVENING_BRIGHTNESS`,
  `CONF_NIGHT_LIGHT_EVENING_COLOR`, `CONF_LIGHT_SCENE_DAY`,
  `CONF_LIGHT_SCENE_EVENING`, `CONF_LIGHT_SCENE_SLEEP` + slot-name
  constants `LIGHT_SLOT_DAY`/`_EVENING`/`_SLEEP`. Slot BOUNDARIES REUSE
  existing URA time notions with zero new timers or clock reads: sleep =
  `RoomAutomation.is_sleep_mode_active()` (already fuses per-room sleep
  clock + HouseState=="sleep" precedence from Slice D); evening = NOT
  sleep AND `is_dark == True` (already the room→borrowed→outdoor→sun
  ladder Slice B/B′ built); day = otherwise.
- `lighting/resolver.py` — new pure helpers `resolve_slot`, `slot_scene`,
  `slot_regular_light_overrides`, `slot_night_light_overrides`. Clock is
  INJECTED via the two bool arguments — no `datetime.now()` inside the
  module; tests set both directly.
- `ura_context.py` — `URA_LIGHT_WRITE_DOMAINS` now includes `"scene"` so
  a URA-issued `scene.turn_on` carries the URA parent_id. Verified
  against installed HA 2026.2.3 that `homeassistant.scene.async_activate`
  propagates the caller context through
  `async_reproduce_state(context=self._context)` (scene.py:369) and
  `apply` service does the same (scene.py:224); the child light.* /
  switch.* state_changed events therefore arrive at the D2 listener
  already carrying the URA parent_id and the existing `is_ura_context`
  filter drops them. No separate quiet-window infrastructure was
  needed; the fallback path is documented in `const.py` for the case
  where a future HA change stops propagating context.
- `automation.py::_control_lights_entry` — resolves the current slot
  after the sleep branch, then checks `_maybe_activate_slot_scene(slot,
  entry_set)`; on hit, dispatches `scene.turn_on` (URA-stamped) and
  records `set_last_action("turn_on", "Activated <slot> scene", ...)`.
  On miss, runs today's per-light path with the slot passed down.
- `automation.py::_control_lights_entry` (sleep branch) — same scene
  short-circuit before `_turn_on_night_lights(mode="sleep")`. The
  non-night sweep still runs afterwards so the sleep contract ("only
  night lights on") holds even when a scene is used.
- `automation.py::_maybe_activate_slot_scene` — new helper. Returns
  False on no scene / unavailable scene entity / any exception (fail-open
  to today's per-light path). Uses `_safe_service_call` which now stamps
  URA context on scene calls.
- `automation.py::_turn_on_regular_lights(slot=LIGHT_SLOT_DAY)` — new
  keyword parameter. Applies `slot_regular_light_overrides` for
  brightness (all capabilities) and colour (FULL only). Day path is
  byte-identical to pre-Slice-E when no evening keys are set.
- `automation.py::_turn_on_night_lights(mode=...)` — accepts `"evening"`
  as a third mode. Evening REUSES the existing day defaults for any key
  the operator did not override (no duplicated defaults).
- `config_flow.py::async_step_options_lighting_behaviour` — adds seven
  Advanced-only fields for evening brightness/colour + three per-slot
  scene pickers (`scene`-domain EntitySelector each). Step description
  now interpolates `{advanced_hint}` (per operator instruction 2026-09-30).
- `config_flow.py::lighting_advanced_hint(show_advanced_options)` — new
  helper. Returns `LIGHTING_ADVANCED_HINT_HIDDEN` (long form, plain
  words, HA-profile path verified: "click your name at the bottom left
  → Advanced mode") when the profile is NOT in Advanced mode, else the
  short `LIGHTING_ADVANCED_HINT_SHOWN` ("Advanced settings shown.").
  Wired into `async_show_form(description_placeholders=...)` for the
  Lighting behaviour step.
- `strings.json` + `translations/en.json` — 7 new field labels + helpers
  (Advanced tag on every helper), and step `description` gains
  `\n\n{advanced_hint}` so the hint renders inline. All field labels are
  ≤4 words, plain wording, no nerd terms.
- `quality/tests/test_lighting_slice_e_slots_scenes.py` — 23 new tests
  covering: `resolve_slot` precedence (sleep > evening > day); slot
  getters absent/present; absent-keys resolver-equivalence; scene domain
  in URA_LIGHT_WRITE_DOMAINS + parent_id verification; wire-in tests for
  `_turn_on_regular_lights` (evening overrides + day identity) and
  `_turn_on_night_lights(mode="evening")` (evening falls back to day
  defaults, and uses overrides when set); `_maybe_activate_slot_scene`
  three branches (no scene, unavailable, dispatched); Advanced-hint
  variants + helper + strings placeholder assertion.

### What was intentionally deferred

- **No day/sleep-specific per-slot color/brightness for regular lights.**
  Regular lights still have only `CONF_LIGHT_BRIGHTNESS_PCT` (no colour)
  outside evening. Rationale: minimises visible surface; today's
  regular-light path had no colour by design; if operators want to add
  a "day colour" or "sleep brightness" for regular lights, that is a
  follow-up card and needs its own strings block.
- **No scene quiet-window `LIGHT_SCENE_URA_QUIET_S` constant.** The
  installed HA source shows context propagates from `scene.turn_on`
  through `async_reproduce_state` to the child light/switch writes, so
  the D2 filter already covers scene-fanned changes. Documented in
  `const.py` with the file:line citation; revisit only if a future HA
  version breaks propagation.
- **Custom slot boundaries (per-room "evening starts at" time field).**
  The plan said "Boundaries per-room time fields (defaults sunset /
  sleep-clock window)" — Slice E reuses the sunset-equivalent
  (`is_dark`) and sleep-clock unchanged. Adding a per-room override
  time field introduces a new timer / clock read and per-operator
  guidance was "no new timers"; if operators want to shift the evening
  boundary later, revisit as a Numbers-Get-Knobs Number entity.
- **Absent `evening` mode for `_turn_off_non_night_lights` / exit.** Exit
  path is unchanged; slots only affect entry brightness/colour/scene.

### Per-site mutation drills

Ran 2026-09-30, `PYTHONDONTWRITEBYTECODE=1`, `__pycache__` cleared
(`shutil.rmtree`) before AND after every drill; source restored via
Python rewrite; `git status --short` clean after the loop.

| # | Site | Mutation | Test that went RED |
|---:|---|---|---|
| S1 | `resolver.py::resolve_slot` sleep branch | `if False and is_sleep_hours:` | 1 test (`resolve_slot_sleep_wins_over_dark`) |
| S2 | `resolver.py::resolve_slot` evening branch | `if False and is_dark is True:` | 1 test (`resolve_slot_evening_when_dark_and_not_sleep`) |
| S3 | `resolver.py::slot_scene` cfg lookup | force `value = None` | 2 tests (present + scene-dispatch wiring) |
| S4 | `resolver.py::slot_regular_light_overrides` evening read | force `b = None` | 1 test (evening overrides brightness) |
| S5 | `resolver.py::slot_night_light_overrides` evening read | force `b = None` | 1 test (evening night uses overrides) |
| S6 | `automation.py::_maybe_activate_slot_scene` dispatch | early `return False` | 1 test (scene dispatch happy path) |
| S7 | `config_flow.py::lighting_advanced_hint` variant picker | always return HIDDEN | 1 test (helper picks variant) |
| S8 | `ura_context.py::URA_LIGHT_WRITE_DOMAINS` | drop `"scene"` | 1 test (domains include scene) |
| S9 | `resolver.py::slot_regular_light_overrides` slot gate | leak into day/sleep | 1 test (evening-only invariant) |

All 9 drills turn a NAMED Slice E test red; tree restored; `git status
--short` clean after the loop.

### Test selection + name-diff vs develop

Selection: `-k "light or automation or reconciler or house_state or presence or switch or ai_rule"`.
Baseline: `.claude/worktrees/validator-develop-0930` (develop @ `1d1625480`) — same worktree Slice D name-diffed against.

| Run | Passed | Failed |
|---|---:|---:|
| develop @ `1d1625480` baseline | 1213 | 17 (pre-existing) |
| Slices A + B + B′ + C + D (prior) | 1347 | 16 (subset of develop's) |
| Slices A + B + B′ + C + D + E (this ship) | 1377 | 16 (same subset) |
| Delta E over D | **+30 new (23 Slice E + 7 Slice E strings-field asserts extending `test_room_dialog_strings.py`)** | **0 new** |

Name-diff cross-check: `comm -23 dev.fail branch.fail` shows exactly one
develop-only failure not in the branch's selected set
(`test_chatter_tick_helper::test_apply_chatter_tick_b_low_4_kill_switch_flip_discharges_latch`,
same as Slice D). `comm -13` empty ⇒ zero new failures introduced.

### Live acceptance criteria (Slice E, prospective — deploy HELD)

- Verify: with no Slice E keys set on any room, entry brightness/colour
  is identical to Slice D (visual regression: dim living-room lights on
  entry at dusk are the same as before).
- Verify: with `CONF_LIGHT_EVENING_BRIGHTNESS_PCT=40` +
  `CONF_LIGHT_EVENING_COLOR_KELVIN=2400` on a FULL-capability room, a
  dark-but-not-sleep entry sets brightness_pct=40 + color_kelvin=2400
  (developer-tools state history on the light shows those attributes).
- Verify: with `CONF_LIGHT_SCENE_EVENING=scene.sunset` on a room, entry
  during evening dispatches `scene.turn_on` for `scene.sunset` and does
  NOT dispatch a `light.turn_on` for that room's lights.
- Verify: a scene-triggered light change during occupancy does NOT open
  a D2 manual hold (URA context propagates through the scene).
- Verify: unsetting the scene reverts to per-light behaviour next entry.
- Verify: the Lighting behaviour step description shows the
  `LIGHTING_ADVANCED_HINT_HIDDEN` phrase when the user profile is NOT
  in Advanced mode; toggling Advanced mode on shows the short
  `LIGHTING_ADVANCED_HINT_SHOWN` phrase; the seven Advanced fields
  appear only when Advanced mode is on.
- Verify: activating the Sleep scene during a sleep entry still sweeps
  non-night lights off (`_turn_off_non_night_lights` runs after the
  scene dispatch).

Post-restart validation table filled per CLAUDE.md rule.

---

## Whole-branch summary of deferrals (Slices A → E)

Consolidated from each slice's "deferrals" section for a single planning
pass BEFORE deploy.

### Deferred within scope of the plan (Slice E-adjacent)
- **Custom evening boundary time knob** — Slice E boundaries reuse
  `is_dark` (sunset-equivalent) + `is_sleep_mode_active()`; no per-room
  "evening starts at" field. Follow-up card only if operators ask to
  shift boundaries.
- **Day / Sleep colour + brightness for regular lights** — Slice E
  added Evening only; today's Day/Sleep for regular lights use
  `CONF_LIGHT_BRIGHTNESS_PCT` + no colour. Follow-up card.
- **Scene URA quiet-window backstop** — not built; installed HA verified
  to propagate context; documented in `const.py` with revisit trigger.

### Deferred from Slice D
- `CONF_LIGHTS_GUEST_MODE` (plan D4 Guest semantics) — code not wired;
  today's HOME-equivalent behaviour preserved. Required before ROADMAP
  v12 6.0.0 (IDENTITY-DRIVEN AUTONOMY).
- Away sweep depends on the coordinator being `loaded` at the Home→Away
  edge (not a new gap — every signal handler).
- No room-device dashboard entity for manual-hold window knobs.

### Deferred from Slice C
- SecurityDelegate `release()` hook (operator question open — is one
  wanted?).
- Late device echo > 5 s residual (HA drops context after 5 s;
  value-matched last-write guard not in plan).
- Optimizer / AI-rule light writes stamped but do not consult hold
  (open question).
- Manual Mode ON: vacancy transition unobserved so hold lives its full
  window (harmless).
- Holds are RAM-only; restart forgets them (fan-oracle precedent).
- `sensor.<room>_light_manual_hold_remaining_s` NOT built (conflicts
  with plan non-goal "only new entity is the switch").
- D3 uses the room's real darkness for the dark-only subset (plan
  silent — treated as an implementation decision).

### Deferred from Slice B′
- Night light brightness/colour field MOVE from Devices → Lighting
  behaviour step (value tunables, not role pickers).
- Reconciler-with-leave-on behavioural harness (Slice B′ drill #5 gap;
  Slice C harness covers the D2 hold surface but not the
  reconciler-vacant-leave-on carve-out explicitly).
- Away-turn-off-leave-on ACTUATION was inert in Slice B′; Slice D
  activated it.

### Deferred from Slice B
- Per-room `CONF_LIGHT_DARK_USE_SUN_FALLBACK` UI toggle — Slice B set
  code to respect the key from stored options; Slice B′ added the UI.

### Plan items NOT built (broad)
- **D7 — Walk-through rooms.** Dropped by REV 2.3.2 (operator: no new
  timers; still needs a 15 s exit cap). Revive on operator request.
- **Stored-data migration (F4).** Not built by design — absent new
  keys ⇒ today's behaviour, so no migration needed.
- **Zone / House dialog cleanups** — separate cards (ZONE-DIALOGS-CLEANUP-1,
  HOUSE-DIALOGS-CLEANUP-1).
- **Adaptive-lighting integration** — plan non-goal.
- **D5 slot count > 3** — plan non-goal.

None of the deferrals block the ship; each is either an operator
question, a follow-up card triggered by post-deploy behaviour, or an
explicit plan non-goal.
