# PLANNING — ONBOARDING-SIMPLIFY-1 phase 2: rooms from areas + Simple first run

**Card:** ONBOARDING-SIMPLIFY-1 · **Date:** 2026-10-02 · **Status:** proposal, needs operator pick + plan review
**Basis:** `docs/planning/AUDIT_onboarding_first_run_path.md` (current-state trace and baseline).
**Relation to the earlier plan:** `PLANNING_onboarding_simplify.md` (2026-09-12) was BUILT and
shipped in v5.101.0 (see audit section 0). It is left untouched as the record of phase 1. This
doc is phase 2. It does not change any phase-1 invariant except where it says so (INV-2, S2).

## Falsifiable invariants

- **INV-A (no silent commit, restated for bulk):** no entity is written into a room entry unless
  it was SHOWN to the operator on a screen they submitted. A bulk-created room whose sensor list
  was not on the review screen is a failure.
- **INV-B (no behavior change for existing entries):** no existing House / room / zone / CM entry
  changes any stored key because of this cycle. All changes are on create paths.
- **INV-C (hidden = default):** every field moved behind Advanced on a create form, when left
  hidden, stores exactly what today's form stores when that field is left untouched.

## Institutional context verified

| Piece | Verdict | Evidence |
|---|---|---|
| Area -> entity discovery | REUSE | `_get_area_entities` `config_flow.py:996` |
| Ranking/dedup/denylist | REUSE | `_rank_area_candidates:1063`, `AUTODETECT_NAME_DENYLIST` `const.py:1698` |
| Type -> timeout / features | REUSE | `ROOM_TYPE_TIMEOUTS` (used `:1615`), `ROOM_TYPE_FEATURE_DEFAULTS` `const.py:1678` |
| Light capability | REUSE | `_detect_light_capabilities:1217` |
| Name collision | REUSE | `_room_name_collides:712` |
| Create an entry from inside another flow | REUSE pattern | `_mint_house_now:1341` -> `flow.async_init(source="integration_create")` -> `integration_create:3199` |
| Advanced-only field marker | REUSE | `description={"advanced": True}` via `_adv:141`; `show_advanced_options` read at `:3805` (Options). ConfigFlow has the same HA attribute — **builder to verify** it is populated for config flows in the HA version pinned by the test harness before relying on it |
| Hint text | REUSE | `advanced_hint` / `advanced_hint_for` `:62-93` |
| Weather auto-detect | REUSE | `_detect_weather_entity:1191` |
| Mobile app targets | REUSE | `_get_mobile_app_targets:962` |
| Area-name -> room-type guess table | NEW | grep of `const.py` + `config_flow.py` for keyword maps / "bath" / "closet" found only `ROOM_TYPE_CLOSET` (`const.py:438`) — no existing map |
| Bulk "rooms from areas" steps | NEW | no multi-room create exists; one flow = one room today |
| Internal source `room_bulk_create` | NEW (thin) | mirrors `integration_create:3199` |

Prior docs: `AUDIT_first_run_onboarding.md`, `PLANNING_onboarding_simplify.md`,
`AUDIT_onboarding_first_run_path.md`. Card + sibling ROOM-CLASSIFICATION-CONSISTENCY-1 (no
representation change here). Memory: label style guide, configurability clarity, extend-existing,
single-user-no-back-compat (2nd home: optional integrations must degrade; visible settings over
silent auto-detect — which is why S2 has a review screen, not a silent import).

**Producer check (auto-fill quality):** every pre-fill is only as good as the HA area
assignments in the new home. If entities are not in areas, S2 finds nothing and says so. That is
the main dependency; the operator checklist (section D) puts "assign areas" first.

## Proposals

### S1 — Simple House form (Tier 2)
`integration_config:1241`: show only **Weather** (pre-filled), **People** (pre-filled with every
`person.*` — NEW default, operator can untick), **Phone for alerts** (pre-filled when exactly one
`mobile_app_*`). Mark the other 8 fields Advanced (outside temp, outside humidity, solar,
retention, transition window, rate, notify service, notify level). Skip `energy_setup:1377` unless
Advanced mode is on (its 4 fields are optional and empty by default — INV-C holds).
- **Labels:** "Weather", "People", "Phone for alerts". Helper: "Used for alerts. You can change
  this later."
- **Knob rung:** none new; the people default is a behavior of the form (rung 2, config flow).
- **Watch:** `CONF_ELECTRICITY_RATE` is `vol.Required` with a default — hidden it still stores the
  default (INV-C); confirm in test.
- **Acceptance:**
  - **Test:** `test_house_simple_shows_three_fields` (Advanced off -> 3 fields; on -> 11).
  - **Test:** `test_house_simple_hidden_fields_store_defaults` (INV-C, incl. rate).
  - **Test:** `test_house_people_prefill_all_persons`.
  - **Test:** `test_energy_setup_skipped_in_simple`.
  - **Live:** fresh-install screenshot shows 3 fields; House entry data has rate = default.

### S2 — Rooms from areas, in bulk (Tier 2-DB; biggest lever)
Replace the `add_first_room:1413` menu with a form **"Set up rooms"**: one multi-select of HA
areas, pre-ticked for areas that have at least one motion or occupancy sensor, plus a "Skip for
now" choice. Also add it to `entry_type_select:933` as "Add rooms from areas" for later use.
Next screen **"Check your rooms"**: read-only list per area — guessed type, motion/occupancy
sensors, lights, temp/humidity sensor. Areas with no motion/occupancy are listed as "Not added:
no motion sensor in this area." One submit creates every room, each via
`flow.async_init(source="room_bulk_create")` with the same data the single-room chain would build
(type timeout, type features, light capability, area pre-fill rules incl. single-bucket dedup).
- **Type guess:** NEW `ROOM_TYPE_AREA_KEYWORDS` in `const.py` (rung 1 module constant — a table
  of words like bath, bed, closet, garage, hall, laundry -> type; changing it should be reviewed,
  not tuned live). Unknown -> generic.
- **Names:** room name = area name; collisions skipped and listed ("Already set up").
- **Load risk:** N entries set up back to back. Given the reload/restart-storm history, create
  sequentially and test N=15 for event-loop time (CONFIG-FLOW-SLOW-ONBOARDING-1 timing
  instrumentation is already live — use it as the measurement).
- **INV-A:** the review screen must list every entity that will be written.
- **Acceptance:**
  - **Test:** `test_bulk_rooms_creates_one_entry_per_ticked_area`.
  - **Test:** `test_bulk_rooms_skips_area_without_occupancy` (listed, not created).
  - **Test:** `test_bulk_rooms_entry_equals_single_flow_entry` — same area through bulk and
    through the 5-step chain with no edits -> identical `entry.data` (discriminates "bulk built
    its own data" from reuse).
  - **Test:** `test_bulk_rooms_review_lists_every_written_entity` (INV-A).
  - **Test:** `test_area_keyword_type_guess` (incl. "Guest Bath" -> bathroom, "Office" -> generic).
  - **Test:** `test_bulk_rooms_name_collision_skipped`.
  - **Live:** on the 2nd home, one submit creates the rooms; each room's `binary_sensor.*occupancy`
    tracks a walk-through within one timeout.

### S3 — Simple single-room chain (Tier 2)
For the one-at-a-time path: ask **Area first** and pre-fill the name from it; hide `room_class`
(wet room already follows type via `ROOM_TYPE_FEATURE_DEFAULTS`; guest room default off) unless
Advanced; mark mmWave, door, water leak, humidity fans, auto switches Advanced unless the area
pre-fill found something (same "shown when in use" rule as `_adv:141`).
- **Acceptance:** **Test** `test_room_simple_four_screens`; **Test**
  `test_room_hidden_class_matches_type_default` (INV-C: bathroom -> wet room true, guest false);
  **Test** `test_room_name_prefilled_from_area`; **Live:** add one room in 4 screens.

### S4 — Fix dead ends (Tier 1)
`add_coordinator:948` aborts with jargon. Change the abort text to point at the "Domain
Coordinators" switch (plain words: "Turn on smart features with the Domain Coordinators switch on
the Universal Room Automation device."). Delete dead `post_integration_setup:1424`,
`setup_zone:1449`, `finish:1457` after a strings/test grep.
- **Acceptance:** **Test** `test_add_coordinator_abort_reason`; grep proves no route to deleted steps.

### Rejected / parked
- **Derive outside temp/humidity from the weather entity** — needs a consumer check of every
  `CONF_OUTSIDE_TEMP_SENSOR` reader first (not done here). Hiding the fields (S1) gets the
  screen-count win with zero behavior change; park the derive.
- **Auto-create zones from HA floors** — attractive, but zones drive HVAC; with HVAC off for the
  2nd home there is no payoff yet. Park until W1-C P3.
- **Silent import with no review screen** — violates INV-A and the "visible over silent" rule.

## Target vs baseline

| Journey | Today: screens / visible fields / must pick | After S1-S4 |
|---|---|---|
| House only | 3 / 15 / 0 | **2 / 3 / 0** (form + rooms screen) |
| Fresh install -> first room (single path) | 8 / 33 / 2 | **6 / ~15 / 1** (-25% screens, -55% fields) |
| Fresh install -> house + 10 rooms | ~63 / ~195 / ~20 | **3 / ~4 / ~1** (-95% screens, -98% fields) |
| Each later room (single path) | 6 / 18 / 2 | 5 / ~10 / 1 |

The >=50% bar is cleared by S2 alone for any home with more than one room; S1+S3 clear it for
fields on the single-room path. Screen count on the single-room path drops only 25% — the honest
answer is that the single-room chain is already lean; bulk is where the win is.

## Tier
- S1, S3: Tier 2 (create-path forms only; INV-C test is the guard).
- **S2: Tier 2-DB** — new entry-creation path that writes N entries in one action, reuses
  phase-1 helpers that multiple callers depend on, and sits next to the reload-storm history.
  One adversarial plan review before build. Framings: A = data parity (bulk vs single-flow
  entries, INV-C), B = lifecycle/load (N sequential setups, ZM room sync, restart mid-bulk),
  C = surfaces + test authority (review screen lists, labels, Advanced round-trip).
- S4: Tier 1.
- **Not for this weekend.** None of this should ship before the Oct 3-4 install.

## Non-goals
No change to Options flows, zone flows, coordinator settings, or stored keys of existing entries.
No representation change to room class flags.

## Plan review (2026-10-02, one adversarial pass, Tier 2-DB)

**Verdict: BUILD-READY with the fixes below folded into the build brief** (none needs a re-plan).

Verified by re-grep:
- Phase 1 shipped: `room_setup:1588`, `room_class:1685`, `sensors_confirm:1719`, `devices_confirm:1866`,
  `room_summary:1928` all present; `docs/readmes/README_v5.101.0.md` carries the live write-back
  (commit 8cd4af2ef). Line cites in the institutional table match `config_flow.py` today.
- House form has 11 fields (`config_flow.py:1273-1333`); S1's "3 shown / 8 hidden" count holds.
- `show_advanced_options` IS populated for initial config flows: HA's
  `ConfigManagerFlowIndexView.post` accepts it (`homeassistant/components/config/config_entries.py:180`)
  and `get_context` copies it into the flow context (`helpers/data_entry_flow.py:98`);
  `FlowHandler.show_advanced_options` reads it (`data_entry_flow.py:645`). The "builder to verify"
  caveat is resolved. Internal `flow.async_init(...)` children get no key -> False (fine for S2).

Findings (fix in build brief):
1. **MEDIUM — Advanced fields are NOT hidden by HA automatically on `async_show_form`.** HA only drops
   `{"advanced": True}` keys inside `add_suggested_values_to_schema` (`data_entry_flow.py:660-667`).
   S1/S3 must route schemas through the existing `_filter_advanced` (`config_flow.py:3807`), not just
   add markers. Tests must assert the rendered schema, not the marker.
2. **MEDIUM — S1 "Phone for alerts" vs hidden notify service.** `CONF_NOTIFY_TARGET` (`:1328`) is shown
   but `CONF_NOTIFY_SERVICE` (`:1325`) goes Advanced. Builder must read the consumer at
   `__init__.py:5230` and decide: derive the service from the mobile_app target, or show both. Add a
   test that a Simple-mode House with a phone actually sends a test notification path.
3. **MEDIUM — S2 runs N full entry setups inside one HTTP submit.** `async_init` -> `async_create_entry`
   -> `ConfigEntries.async_add` awaits `async_setup` (`homeassistant/config_entries.py:2112-2122`), so
   15 rooms = 15 serial setups before the form returns. Not a loop stall per se (awaited), but the
   request can run long. Plan must state: (a) partial-failure behavior (an exception at room k leaves
   k-1 created; re-run is safe because collisions are skipped — say so and test it); (b) the N=15
   timing gate number (pass/fail threshold), not just "measure". No parent-entry reload is triggered
   by room adds (only options-change reload at `__init__.py:8210`), so the watchdog-reload hazard
   does not apply.
4. **LOW — parity test needs a shared builder.** `test_bulk_rooms_entry_equals_single_flow_entry` is the
   right discriminator; require the build to extract one pure "area -> room data" function used by both
   paths, so parity is structural, not coincidental (Bug Class #63).
5. **LOW — S4 deletion scope.** `skip_to_room` is live (used by `add_first_room:1421`) — do not delete it.
   `post_integration_setup` has a test (`quality/tests/test_onboarding_simplify_slice2.py:336`) and
   strings in `strings.json` + `translations/en.json`; delete those with the steps. `setup_zone` /
   `finish` are only reachable from `post_integration_setup`.
6. **LOW — INV-B wording:** S2 adds `room_bulk_create` to `entry_type_select:933` menu options — a menu
   change for existing installs. Not a stored-key change, so INV-B holds; note it as a visible change.

## Amendment 2026-11-04: HA 2026.11 + further opportunities

**Gate:** the house runs HA **2026.10.4**. Anything marked *gated* needs the 2026.11 upgrade AND a
`homeassistant` minimum in `hacs.json` (today it has none — `hacs.json` carries only name /
content_in_root / render_readme), because a second home on an older core would get a form that
shows every field (or fails to build the schema).

**API, as read (No Fabrication):** source = release notes
(home-assistant.io/blog/2026/11/04/release-202611, "Forms that ask only what they need") and the
contributor post https://contributors.home-assistant.io/blog/2026/10/21/form-fields-visible/.
The post shows `data_entry_flow.Required(KEY, default=..., visible={"field": OTHER, "value": X})`
(also `Optional`). Stated behavior: a hidden field "is not required, and its value is not
saved." Only the equality form is shown; the post defers other conditions to the Flow steps dev
doc, which was NOT read. The post's code sample mixes an unimported `probatio` module with
`data_entry_flow` — the builder must check the real import path against the installed 2026.11
core before writing any code. Per-integration live logs: a "Show logs" button on the integration
page while debug logging is on, filtered to that integration plus its libraries. No code needed.

**Hazard the plan must carry (gated items):** "hidden = not saved" meets URA's options merge
`{**self._config_entry.options, **user_input}` (`config_flow.py:4711`, `:4808`, `:4905`). A
hidden dependent is absent from `user_input`, so its OLD value survives. That is safe only if
every consumer gates on the parent toggle. Each gated item below needs a consumer check that the
dependent is never read when the parent is off. On create paths (no merge) a hidden field lands
on the consumer fallback, so INV-C (hidden = default) must be re-proved per field.

### Ranked opportunities

| # | Opportunity | Value | Risk | Tier | Gated on 2026.11 | REUSED / NEW |
|---|---|---|---|---|---|---|
| O1 | Config-first: use 2026.11 per-integration live logs for config-flow and setup debugging; record in the debugging playbook; no code | M | none | — | yes (upgrade only) | REUSED: `_cflow_timing.py` stays as the timing source |
| O2 | Sleep protection: show start/end hour, bypass count, block covers only when `CONF_SLEEP_PROTECTION_ENABLED` is on (create `:3610-3620`, Options `:14750`) | M | L | 2 | yes | REUSED keys; NEW `visible=` use |
| O3 | Covers: show close-time source / hour / sunset offset only when `CONF_TIMED_CLOSE_ENABLED` is on (create `:2943-2952`, Options `:14309`); hour only when source = fixed time, offset only when source = sunset | M | L-M | 2 | yes | REUSED keys |
| O4 | Fan: replace the hand-rolled `CONF_ROOM_FAN_MODE == FAN_MODE_ROOM_TEMPERATURE` re-routing (`:3435`, `:14373-14377`) with `visible=` on the dependent temperature fields | M | M (changes saved-value semantics) | 2 | yes | REUSED |
| O5 | Shared schema builders for the 7 step names defined on BOTH create and Options paths (`add_coordinator`, `climate`, `devices`, `energy`, `notifications`, `sensors`, `sleep_protection`); one builder, two defaults sources. Prereq for O2-O4 so each `visible=` lands once | H (halves edit sites, kills create/Options drift — Bug Class #53 shape) | M | 2-DB (INV-1 round-trip) | no | NEW helper per pair; REUSE `_get_current` |
| O6 | Sweep the remaining 105 of 108 `BooleanSelector()` toggles (`grep -c`) for parent→dependent pairs; table only, no code | M | none | 1 (audit) | no | — |
| O7 | Retire `advanced`-flag hiding where a `visible=` parent toggle expresses the intent better (keep `_adv:141` for true tuning knobs) | L | L | 2 | yes | REUSED `_adv`, `advanced_hint_for:93` |
| O8 | Add `"homeassistant": "2026.11.0"` to `hacs.json` when the first gated item ships | prereq | L | 1 | yes | NEW key |

**Recommendation (marginal-benefit):** O1 now (free). O5 and O6 now (not gated; O5 is the
real simplification and makes O2-O4 one-site edits). O2-O4 after the 2026.11 upgrade, bundled
into one Tier-2 cycle with O8. O7 last; low margin.

### Acceptance criteria (top items)

**O5 — shared builders**
- **Verify:** each of the 7 pairs builds its schema from one function; create passes defaults,
  Options passes `_get_current`.
- **Test:** `test_options_create_schema_key_parity` (same key set per pair) and the phase-1 INV-1
  round-trip suite stays green; a mutation that drops a key from the builder turns both RED.
- **Live:** open Options on one room for each step; same fields as before (screenshot diff).

**O2 / O3 / O4 — conditional fields (after upgrade)**
- **Verify:** with the parent off, dependents are not rendered; turning it on shows them without
  a resubmit.
- **Verify (discriminating):** enable → set hour 22 → disable → save → re-open. The stored
  hour is still 22 (merge kept it) AND the consumer does not act on it. A missing parent gate in a
  consumer shows up as action at 22 with the toggle off. That is the failure this test catches.
- **Test:** `test_sleep_dependents_hidden_not_required`, `test_timed_close_dependents_ignored_when_disabled`,
  `test_fan_mode_visible_replaces_reroute`.
- **Live:** on 2026.11, Options → sleep protection on a room with it off shows one toggle only.

**O8:** `hacs.json` carries the minimum; HACS on 2026.10.x refuses the update rather than
installing a degraded form.

### House / zone / coordinator opportunities (survey 2026-11-05)

Survey of the Coordinator Manager and Zone Manager options steps for parent toggle → dependent
pairs. Lines are in `config_flow.py` at the time of the survey. All are **gated on 2026.11 + O8**,
and every row carries the merge hazard above: a hidden dependent keeps its old stored value, so
each row needs a consumer check that the dependent is never read while the parent is off.
Energy and HVAC rows sit on the highest-blast-radius surfaces (Tier 3 behaviour behind them), so
the form change is Tier 2 only if the consumer check proves the parent gate at every read site;
otherwise that row is dropped, not escalated.

| # | Step | Parent → dependents | Lines |
|---|---|---|---|
| O9 | `coordinator_energy` | `CONF_ENERGY_LOAD_SHEDDING_ENABLED` → `_MODE`, `_THRESHOLD`, `_SUSTAINED_MINUTES` | ~7005-7030 |
| O10 | `coordinator_energy` | `CONF_ENERGY_ARBITRAGE_ENABLED` → `_ARBITRAGE_SOC_TARGET` (NOT `PEAK_BUFFER_TARGET`, which is read outside arbitrage — verify before including) | ~7140-7160 |
| O11 | `coordinator_energy` | `CONF_ENERGY_EXCESS_SOLAR_ENABLED` → `_EXCESS_SOLAR_SOC`, `_EXCESS_SOLAR_KWH` | ~7178-7195 |
| O12 | `coordinator_energy` | `CONF_ENERGY_GRID_IMPORT_CAP_ENABLED` → `_GRID_IMPORT_CAP_KW`; `CONF_ENERGY_ARBITRAGE_GRID_IMPORT_GUARD_ENABLED` → `_GUARD_KW` | ~7225-7270 |
| O13 | `coordinator_energy` | `CONF_ENERGY_TOU_RATE_FILE_ENABLED` → `CONF_ENERGY_TOU_RATE_FILE`; `CONF_ENERGY_EVSE_CHARGE_ONSET_ENABLED` → `_ONSET_TIME` | ~6640-6665, ~7300-7320 |
| O14 | `coordinator_hvac_settings` | `CONF_HVAC_SOLAR_GAIN_COVER_ENABLED` → `CONF_HVAC_COVER_CLOSE_TEMP` (+ cover entities); `CONF_HVAC_ARRESTER_ENABLED` → carrier reload/stale knobs | ~8080-8100, ~8225-8250 |
| O15 | `hvac_dynamic_preset` / `zone_dynamic_preset` | `CONF_DYNAMIC_PRESET_ENABLED` → relax-ceiling mode and offsets; zone `CONF_ENABLED` → `CONF_OFFSET`, `CONF_SLEEP_ENABLED` | ~8486-8576, ~12440-12460 |
| O16 | `camera_census` | `CONF_FACE_RECOGNITION_ENABLED` → `CONF_KNOWN_FACE_GUESTS`; `CONF_PERIMETER_ENRICHMENT_ENABLED` → `_PROVIDER` | ~5100-5130, ~5350-5370 |
| O17 | `coordinator_presence` | `CONF_FAN_RECHECK_ENABLED` → `CONF_FAN_RECHECK_FAMILY_SCALING_ENABLED` (+ its numbers) | ~5682-5781 |

Not surveyed line-by-line: security, music following, notifications sub-steps (quiet hours have
an obvious enable → window pair; check in O6), optimization, appliance. O6's table should absorb
these rows and finish the sweep. Recommendation: ship O14-O17 with O2-O4 (comfort/identity only);
take O9-O13 (energy) as a separate cycle after a consumer audit, because a missed parent gate on
an energy knob is a money path.

### Non-goals (amendment)
No `visible=` use before the house upgrades. No change to stored keys. No new knobs.
