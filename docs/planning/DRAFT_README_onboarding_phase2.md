# DRAFT README — ONBOARDING-SIMPLIFY-1 phase 2 (rooms from areas + Simple first run)

**Status:** built on `feature/onboarding-phase2`, not deployed. Version number assigned at deploy
(PATCH bump unless the operator calls the bulk room path a new capability -> MINOR).
**Plan:** `docs/planning/PLANNING_onboarding_simplify_phase2.md` (BUILD-READY, plan-review findings 1-6
folded in). **Tier:** S2 = Tier 2-DB (3 framing-disjoint reviews), S1/S3 = Tier 2, S4 = Tier 1.
**Not for the Oct 3-4 install** (per plan).

## What changed

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

## Known behaviours (by design)

- First run (Simple House form): the People field is pre-filled with
  every `person.*` in HA. Untick anyone who should not be tracked.
- Rooms from areas: the "already set up" check is by room name only
  (case-insensitive). An existing room with a different name for the same
  area is not detected, so the area would get a second room.
- The room type for each area is a keyword guess from the area name
  (e.g. "Bath" -> bathroom). The guess is shown on the review screen;
  change it later in the room's options if wrong.

## Acceptance (in-suite)

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

## Live validation (prospective — replace with a Validated table after deploy)
- Fresh install (2nd home or a test instance): House screen shows 3 fields; House entry data has
  `electricity_rate` = default and `notification_service` = the picked phone.
- **N=15 timing gate (pass/fail):** the `CFLOW-TIMING: EXIT ...async_step_rooms_review elapsed_ms`
  line for a 15-room submit is **< 60000 ms**, and the `Bulk room create: ... in Xs` INFO line agrees.
  Fail = over 60 s, or any HA "Detected blocking call" / watchdog event during the submit.
- One submit creates the rooms; each room's `binary_sensor.*occupancy` tracks a walk-through within
  one timeout.
- Existing install: Add-entry menu shows "Add rooms from areas"; no existing entry's stored keys change.

## Not done from the plan
- Live checks above (need a deploy; not for the Oct 3-4 weekend per plan).
- The plan's "replace the add_first_room menu with a form" was built as a menu whose first item opens
  the area form, so "Add one room" (`skip_to_room`, finding 5) stays reachable. Costs one extra click
  on the bulk path versus the plan's screen-count table.
- Room type is not pre-guessed from the area on the single-room path (not requested).
- Pre-existing, not changed: `button.py` export notification calls `notify.<service>` with the stored
  `notify.`-prefixed value (would not resolve). Same for any Advanced user today; card if wanted.
