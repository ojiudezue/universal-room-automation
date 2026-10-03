# URA v5.103.36 — Thermostat profiles (W1-C P1), zone/house Simple/Advanced, rooms from areas

Three reviewed changes. Serial full-suite name-diff vs v5.103.35 (pre-5103-36): identical failing-name sets after one fix (a false-positive Bug Class #34 shadow-import flag in hvac_strategy.py, rebound via alias), +501 passing.

**Visible changes:** new 'Add rooms from areas' in the Add-entry menu; first-run House form shows 3 fields in Simple mode (People pre-filled with every person); zone/house dialogs hide rarely-used settings unless Advanced mode is on or the setting is in use.

## HVAC W1-C P1 — thermostat strategy layer (Tier 3)

- All 28 climate write sites and every 'manual' reader route through a per-thermostat strategy (`domain_coordinators/hvac_strategy.py`): Carrier and Generic profiles today.
- **Invariant:** for Carrier zones every climate service call is byte-identical to pre-P1 (domain, service, data, order, suppression). Proven by 168 goldens captured on pre-change source and replayed (independently re-verified by review C); every site drilled red.
- Lint: no raw 'manual' outside the strategy (exact-count allowlist). Diagnostics override attribution routed through the profile.
- Reviews A/B/C/D: SHIP after one test-order fix-up; operator checkpoint GO 2026-10-02.
- **Second home:** keep its HVAC coordinator off until W1-C P3. Native-ecobee 'temp' hold is not yet recognised as manual (carded for P2).

## ONBOARDING-SIMPLIFY-1 phase 2 — rooms from areas in bulk, simpler House form

**Status:** built on `feature/onboarding-phase2`, not deployed. Version number assigned at deploy
(PATCH bump unless the operator calls the bulk room path a new capability -> MINOR).
**Plan:** `docs/planning/PLANNING_onboarding_simplify_phase2.md` (BUILD-READY, plan-review findings 1-6
folded in). **Tier:** S2 = Tier 2-DB (3 framing-disjoint reviews), S1/S3 = Tier 2, S4 = Tier 1.
**Not for the Oct 3-4 install** (per plan).

### What changed

### S1 — Simple House form
- With Advanced mode off, the first screen shows 3 fields: **Weather**, **People**, **Phone for alerts**.
  The other 8 fields (outside temp, outside humidity, solar, person history days, room change window,
  electricity rate, notify service, notify level) are Advanced-only.
- Hidden fields store exactly their old untouched defaults (INV-C), including the Required electricity
  rate (merged back on submit by `_hidden_advanced_defaults`).
- **People** is now pre-filled with every `person.*` (was empty). **Phone for alerts** is pre-filled
  when exactly one `mobile_app_*` notify service exists.
- **Phone -> alert service (plan-review finding 2).** The legacy alert sender
  (`aggregation.py` `_process_alerts`, the consumer of `CONF_NOTIFY_SERVICE`; the plan's
  `__init__.py:5230` cite is the v2 migration, not a sender) only sends when the notify *service* is
  set and calls it directly; a target alone sends nothing. In Simple mode the service field is
  hidden, so a picked phone is also stored as the notify service (`notify.mobile_app_x`). Advanced
  mode does not derive (both fields visible; the operator's choice wins). This is the one deliberate
  exception to INV-C.
- The energy screen is skipped unless Advanced mode is on (same as submitting it untouched).

### S2 — Rooms from areas, in bulk
- `add_first_room` menu: **Set up rooms from areas** (new, first), **Add one room** (`skip_to_room`,
  kept live), **Skip — add rooms later**.
- **Visible change for existing installs (finding 6):** the Add-entry menu (`entry_type_select`) gains
  **Add rooms from areas**. No stored key changes (INV-B holds).
- **Set up rooms**: one multi-select of HA areas, pre-ticked for areas with a motion or occupancy
  sensor and no room of the same name.
- **Check your rooms**: read-only list per area — guessed type and every entity that will be written
  (INV-A: the list walks the exact data that is stored). Areas without motion/occupancy:
  "Not added: no motion sensor in this area." Name collisions: "Already set up."
- Submit creates each room one at a time via the internal `room_bulk_create` source.
- **One shared builder (finding 4):** `build_area_room_data` + `room_type_defaults` /
  `area_sensor_defaults` / `area_device_defaults` produce bulk data; the single-room chain reads its
  form defaults from the same helpers, and both paths finalise through `_finalize_room_data`
  (type seed, light capability, entry framing). Parity is tested structurally.
- **Type guess:** `ROOM_TYPE_AREA_KEYWORDS` (const.py, rung 1 module constant; first substring match
  wins; unknown -> generic).
- **Partial failure (finding 3a):** a room that raises is logged and listed as failed; rooms before
  and after it are still created. Re-running is safe: the skip-existing guard runs right before each
  create (and again inside `room_bulk_create`), so only missing rooms are created. Result screen:
  "Rooms created: N. Skipped: N. Failed: names."
- **Load (finding 3b):** each room's setup is awaited before the next. No parent-entry reload is
  triggered by room adds, so the parent-reload watchdog hazard does not apply. Gates below.

### S3 — Simple single-room chain
- Room setup asks **Area** first; a blank name takes the area's name.
- The room class screen is hidden unless Advanced mode (stores the type defaults: bathroom -> wet
  room on, guest room off).
- mmWave, door, water leak, humidity fans and switches are Advanced-only unless the area pre-fill
  found something for them. Hidden fields store their untouched defaults.
- Simple path: room setup -> sensors -> devices -> summary (4 screens).

### S4 — Dead ends
- "Add a Coordinator" abort text: "Turn on smart features with the Domain Coordinators switch on the
  Universal Room Automation device."
- Deleted dead `post_integration_setup`, `setup_zone`, `finish` steps + their strings and the old
  test. `skip_to_room` kept (finding 5).

### Known behaviours (by design)

- First run (Simple House form): the People field is pre-filled with
  every `person.*` in HA. Untick anyone who should not be tracked.
- Rooms from areas: the "already set up" check is by room name only
  (case-insensitive). An existing room with a different name for the same
  area is not detected, so the area would get a second room.
- The room type for each area is a keyword guess from the area name
  (e.g. "Bath" -> bathroom). The guess is shown on the review screen;
  change it later in the room's options if wrong.

### Acceptance (in-suite)

| Criterion | Test |
|---|---|
| House Simple = 3 fields, Advanced = 11 | `test_house_simple_shows_three_fields` |
| Hidden House fields store defaults (incl. rate) | `test_house_simple_hidden_fields_store_defaults` |
| People pre-fill = all persons | `test_house_people_prefill_all_persons` |
| Phone pre-fill with one mobile app | `test_house_phone_prefilled_when_one_mobile_app` |
| Energy skipped in Simple | `test_energy_setup_skipped_in_simple` |
| Simple House + phone -> real alert sender calls the phone | `test_simple_house_phone_sends_alert` |
| One entry per ticked area | `test_bulk_rooms_creates_one_entry_per_ticked_area` |
| No-motion area listed, not created | `test_bulk_rooms_skips_area_without_occupancy` |
| Bulk entry == single-chain entry (Simple + Advanced) | `test_bulk_rooms_entry_equals_single_flow_entry` |
| INV-A review lists every written entity | `test_bulk_rooms_review_lists_every_written_entity` |
| Type guess | `test_area_keyword_type_guess` |
| Name collision skipped | `test_bulk_rooms_name_collision_skipped` |
| Partial failure + safe re-run | `test_bulk_rooms_partial_failure_and_rerun` |
| N=15 URA-side work < 1.0 s (pass/fail) | `test_bulk_rooms_n15_timing` (`BULK_N15_MAX_SECONDS`) |
| Single path = 4 screens | `test_room_simple_four_screens` |
| Hidden class = type default | `test_room_hidden_class_matches_type_default` |
| Name from area | `test_room_name_prefilled_from_area` |
| Unused fields hidden / shown when in use | `test_room_simple_hides_unused_fields` |
| Coordinator abort text | `test_add_coordinator_abort_reason` |
| No route to deleted steps | `test_no_route_to_deleted_steps` |

### Live validation (prospective — replace with a Validated table after deploy)
- Fresh install (2nd home or a test instance): House screen shows 3 fields; House entry data has
  `electricity_rate` = default and `notification_service` = the picked phone.
- **N=15 timing gate (pass/fail):** the `CFLOW-TIMING: EXIT ...async_step_rooms_review elapsed_ms`
  line for a 15-room submit is **< 60000 ms**, and the `Bulk room create: ... in Xs` INFO line agrees.
  Fail = over 60 s, or any HA "Detected blocking call" / watchdog event during the submit.
- One submit creates the rooms; each room's `binary_sensor.*occupancy` tracks a walk-through within
  one timeout.
- Existing install: Add-entry menu shows "Add rooms from areas"; no existing entry's stored keys change.

### Not done from the plan
- Live checks above (need a deploy; not for the Oct 3-4 weekend per plan).
- The plan's "replace the add_first_room menu with a form" was built as a menu whose first item opens
  the area form, so "Add one room" (`skip_to_room`, finding 5) stays reachable. Costs one extra click
  on the bulk path versus the plan's screen-count table.
- Room type is not pre-guessed from the area on the single-room path (not requested).
- Pre-existing, not changed: `button.py` export notification calls `notify.<service>` with the stored
  `notify.`-prefixed value (would not resolve). Same for any Advanced user today; card if wanted.

## ZONE/HOUSE Simple/Advanced

**Cards:** ZONE-DIALOGS-CLEANUP-1 (D2) + HOUSE-DIALOGS-CLEANUP-1 (D4), tests in D6.
**Plan:** `docs/planning/PLANNING_zone_house_dialog_cleanup.md` (slice B; slice A = D1/D3/D5 shipped earlier).
**Tier:** 2 (options-flow UI only; no runtime behaviour change).
**Branch:** `feature/zone-house-advanced` (from develop).

### What changed

The Zone Manager and House option forms now hide rarely-used tuning fields unless
HA's profile **Advanced mode** is on. A form with hidden fields shows a hint line
that explains how to reveal them. This reuses the room mechanism (`_adv`,
`_filter_advanced`, `advanced_hint_for`). Nothing new was invented.

| Form | Hidden in Simple mode |
|---|---|
| Zone > Name and rooms | Description (no runtime reader) |
| Zone > Zone Media | If speaker is off (fallback mode) |
| Zone > Thermostat | AC power sensor, AC overrun fix |
| Zone > Zone Energy | Power sensors (no runtime reader) |
| Zone > Weather comfort | No offset with guests, Separate sleep ranges |
| House > Global Sensors | Dark outside below, Backup power price |
| House > Energy Sensors | Device power sensors (no runtime reader) |
| House > Person Tracking | Keep history, Room change wait (no runtime reader) |
| House > Camera Census | Cross-check, Trust the lower count, Smarter counting, Only trust live faces, Phones excuse unknown people, Turn on person detection, Indoor/Outdoor hold |
| House > Perimeter Alerting | AI service, Cameras to describe, AI model, Max reply length, AI provider ID, Snapshot delay |

The Camera Census form drops from 15 fields to 7 in Simple mode: the three camera
pickers, Face recognition, Name people at doors, Known guests and Guest Wi-Fi name.
The fields are now in this order: pickers, then switches, then the guest list and
SSID, then the Advanced tuning. Only the order changed. No key was renamed or moved.

### Invariants
- **I2: nothing stored is unreachable.** A hidden field still shows in Simple mode
  when its stored value differs from the factory default (for lists and text, when
  it is non-empty). This includes the five dead fields (operator decision O1: they
  show in Advanced mode, or when set).
- **I3: Simple saves keep hidden values.** House saves merge into the stored
  options (`{**options, **user_input}`). Zone saves merge into the zone dict, and
  the sibling mirror only copies keys that were on the form. A zone that shares a
  thermostat therefore keeps its own hidden values.
  `zone_rooms` now falls back to the stored description, where it used to write
  `""`, when the field is not submitted (ZM and legacy branches).
- **Reload safety.** A Simple-mode Camera Census or Perimeter save that changes one
  allowlisted key only changes that key, so it stays inside
  `INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS` and does not reload. An entry that
  still holds the 4 retired `perimeter_alert_*` keys reloads once on its first
  perimeter save, because the pop removes them. This is pre-existing and accepted
  (plan review finding 3).

### Shared-helper fix found in build
`_schema_has_advanced` and `_collect_schema_defaults` recursed forever on any
`vol.All` field. After schema compilation, `vol.All.schema` points back at the
parent schema. The weather-comfort form was the first Advanced-marked form with a
`vol.All` field (the offset). Both walkers now treat that back-reference as a leaf.
A regression test is included and was drill-verified.

### Not changed
- `MIRROR_KEYS_ZONE_*`: a test asserts they are unchanged.
- The reload allowlist and `_auto_mirror_to_siblings`.
- Constants. The five dead keys got one-line KEEP+DOCUMENT comments in `const.py`.
- Accepted LOW (plan review 6): a Simple-mode zone save no longer re-mirrors hidden
  keys to siblings, so it no longer heals drift between siblings.

### Tests
`quality/tests/test_zone_house_advanced_fields.py` (79 tests): classification per
key, I2 forced render per key (including entry.data and the legacy zone entry), I3
per step (zone + sibling + House), the Camera Census count and order, hint
placeholders, mirror-set identity, reload safety through the real
`_async_update_listener`, and the walker back-reference.

Mutation drills (source rewritten, then restored with hash verified):
zone helper merge→overwrite (4 fail), zone_rooms description fallback→"" (1 fail),
camera_census merge→user_input (2 fail), `_adv` never unmarks (28 fail),
census_hold_interior forced-render site (1 fail), back-reference guard removed (7 fail).

### Live validation (prospective; fill in post-restart)
- [ ] Profile Advanced mode OFF → Zone > Thermostat shows only the thermostat picker + hint.
- [ ] Advanced mode ON → all three Thermostat fields show; the hint says "Advanced settings shown."
- [ ] Advanced mode OFF → House > Camera Census shows 7 fields + hint.
- [ ] A House with a non-default `census_hold_interior` still shows it in Simple mode.
- [ ] Simple-mode Camera Census save that only edits Known guests: log shows
      "in-place apply, suppressing reload", not "scheduling reload".
- [ ] Weather comfort form opens without error (exercises the vol.All fix).

## Live validation
_Pending — results table written back after the restart._
