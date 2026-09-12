# PLANNING — ONBOARDING-SIMPLIFY-1 (Tier 2-DB)

**Card:** ONBOARDING-SIMPLIFY-1 · **Date:** 2026-09-12 · **Status:** approved-to-build
**Authoritative basis:** `docs/planning/AUDIT_first_run_onboarding.md` (the design is fixed there;
this plan implements it — it does not re-derive it). Kanban card carries the refinement trail,
`recommended_combo`, and `autodetect_research` notes.

**Scope (approved combo):** P1 progressive disclosure · P2 area-first auto-detect-and-confirm ·
P3 room-type presets set soft feature defaults · P4 relocate tuning constants off setup path ·
P5 continuous house→room ribbon · P6 assistive house first-run (auto-detect weather) · P7 closing
summary. **Plus** the reshaped room-identity step: (a) FUNCTION (light) + (b) an explicit up-front
LOAD-BEARING CLASS question surfacing wet-room / guest-room / utility-infrastructure with each
implication in plain words — reading the EXISTING flags (`CONF_WET_ROOM`,
`CONF_ROOM_IS_GUEST_ROOM`, `ROOM_TYPE_UTILITY`, `ROOM_TYPE_INFRASTRUCTURE`); we do NOT refactor
their representation (that is the separate audit-first card **ROOM-CLASSIFICATION-CONSISTENCY-1**).

---

## Falsifiable invariant (the property this cycle must not break)

> **INV-1 (Round-trip):** For every existing room config entry, opening the entry's Options,
> making no operator change, and saving MUST produce a `ConfigEntry.data`+`options` dict that is
> **byte-identical** to the pre-save state (no silent behavior flip, no dropped field, no
> re-defaulted knob).
>
> **INV-2 (No silent commit):** The area-first auto-detect path MUST NEVER write an entity into
> `ConfigEntry.data` without an explicit confirmation submit from the operator. The default set
> is a *pre-filled selector value*, not a persisted assignment, until the operator advances the
> step. Skipping the step MUST persist an empty value, not the guess.

Both invariants are testable and framing-disjoint (INV-1 is data-shape; INV-2 is a call-graph
property). Reviewer D falsifies both by adversarial enumeration.

---

## Institutional context verified

Prior-art scan run per CLAUDE.md "Tier 2+ Prior-Art Scan" and "Institutional Context First."
For every proposed piece: REUSED (with file:line) or NEW (with why).

### Code surface (`custom_components/universal_room_automation/config_flow.py` + `const.py`)

| Proposed piece | Verdict | Evidence |
|---|---|---|
| Area→entity discovery helper | **REUSED — extend** | `_get_area_entities` at `config_flow.py:744-788` (already area+domain+device_class, entity-then-device area fallback). Extend for `entity_category` filter, denylist, actuator-shared deprioritization, `_2`-suffix dedup. |
| Room entry creation | **REUSED** | `async_create_entry(...)` in room chain (final step `notifications` at `:2292`). ENTRY_TYPE_ROOM machinery unchanged. |
| Config flow step chain | **REUSED — restructured** | `async_step_room_setup:1110` → `sensors:1241` → `devices:1349` → …→ `notifications:2292`. Restructured: essentials-only chain that reaches `async_create_entry` in ≤4 steps. |
| Post-integration menu | **REUSED — inlined** | `async_step_post_integration_setup:945` currently creates House entry BEFORE menu (breaks ribbon per P5). Change: after House `create_entry`, route directly into `async_step_room_setup` as continuation (opt-out to menu). |
| Room-type→timeouts | **REUSED — extended** | `ROOM_TYPE_TIMEOUTS` at `const.py:1171-1180`; also read at `room_setup:1134`. Extend with a sibling `ROOM_TYPE_FEATURE_DEFAULTS` dict for P3 (soft defaults for humidity-fan / sleep-protection / wet-room flag). |
| Light capability detect | **REUSED** | `_detect_light_capabilities` at `:790-812`. No change. |
| Wet-room / guest / utility / infrastructure flags | **REUSED as-is** | `CONF_WET_ROOM:const.py:1028`, `CONF_ROOM_IS_GUEST_ROOM:386`, `ROOM_TYPE_UTILITY:426`, `ROOM_TYPE_INFRASTRUCTURE:429`. Class-question STEP reads/writes these existing keys directly. **No representation refactor** (deferred to ROOM-CLASSIFICATION-CONSISTENCY-1). |
| Options flow round-trip | **REUSED** | `UniversalRoomAutomationOptionsFlow` at `:2458`; update_listener + `async_update_entry` at `:2609`. All "Advanced" surfaces stay reachable here — nothing removed. |
| Notify-service enumeration | **REUSED** | `_get_mobile_app_targets:710`, notify enumeration at `:822-829`. |
| Weather entity auto-detect (P6) | **NEW — thin** | No existing "pick a weather entity" helper. Add small helper: pick single `weather.*` entity if exactly one exists, else present a domain-filtered selector prefilled with the first alphabetical. |
| Auto-detect ranking helper | **NEW — small module** | `_rank_area_candidates()` (ranking ladder from audit §Auto-detect design). No existing ranker. Name-denylist constant NEW (`AUTODETECT_NAME_DENYLIST` in `const.py`). |
| Class-question step | **NEW step** | `async_step_room_class` — presents wet-room/guest/utility/infrastructure with plain-word implications; writes to the EXISTING flags. No new consts. |
| Closing summary step (P7) | **NEW step** | `async_step_room_summary` — read-only recap → `async_create_entry`. |

### Prior planning docs consulted
- `docs/planning/AUDIT_first_run_onboarding.md` (authoritative; sections A/B/C + Auto-detect design)
- Kanban card `ONBOARDING-SIMPLIFY-1` (`docs/planning/kanban.data.yaml`) — refinement trail,
  `recommended_combo`, `autodetect_research`.
- Adjacent card noted out-of-scope: `ROOM-CLASSIFICATION-CONSISTENCY-1`.

### Memory bodies pulled
- `feedback_extend_existing_never_rebuild` — enforced above (extend `_get_area_entities`, reuse
  option-flow round-trip, reuse existing flags).
- `feedback_tier2plus_prior_art_scan` — this section.
- `feedback_parsimonious_room_config` — knob-inventory review before deploy (see D8).
- `feedback_finish_the_job_all_pieces` — P1..P7 + class-step all in one cycle.

### Design docs
No `docs/Coordinator/<NAME>.md` applies (config flow is integration-level, not a coordinator).
`IDENTITY_FUSION_CAMERAS_MANUAL.md` not applicable — no identity/camera surface changed.

### Code locations surveyed end-to-end
`config_flow.py` (steps `user`, `entry_type_select`, `integration_config`, `energy_setup`,
`post_integration_setup`, `room_setup`, `sensors`, `devices`, `climate`, `notifications`,
`OptionsFlow.__getattr__` dispatcher); `const.py` (room-type consts + flags); `__init__.py:956-1003`
(CM auto-create — unchanged).

---

## Tier classification — Tier 2-DB (elevated per standing policy)

Config flow is a shared surface consumed by ENTRY_TYPE_ROOM + ENTRY_TYPE_ZONE_MANAGER +
Coordinator Manager; options-flow round-trip risk + RestoreEntity persistence are exactly the
"regression-prone" class from CLAUDE.md. Three framing-disjoint reviews + Live Validation +
README write-back.

### Review framings (dispatch in parallel)
- **Reviewer A — Round-trip data integrity.** For each existing room entry-shape (minimal room,
  full climate, cover-bearing, night-lights, wet-room, guest-room), open Options→save-no-change
  and diff `data|options` before/after. **INV-1 falsifier hunt.** Also: every deferred field is
  still writable via Options (no capability lost).
- **Reviewer B — Flow-graph + auto-detect correctness.** Every branch of the essentials chain
  reaches `async_create_entry` with a legal payload; class-step writes existing flags with the
  correct semantics; auto-detect ranking follows the ladder (own-area > inherited; not
  actuator-shared; denylist; enabled-default). Diagnostic/CONFIG entities excluded. `_2`-suffix
  dedup by (device_id, device_class). **INV-2 falsifier hunt** — confirm no code path writes an
  auto-detected entity without the operator submit.
- **Reviewer C — New surfaces + test fixture authority.** New steps (`room_class`,
  `room_summary`) round-trip through Options; `ROOM_TYPE_FEATURE_DEFAULTS` inheritance is *soft*
  (operator explicit choice always wins on re-edit); acceptance tests drive real config-flow
  entrypoints (not private helpers); empty-area result is LEGIBLE (D6 acceptance).
- **Reviewer D (if elevated to Tier 3 by operator) — Adversarial completeness.** Restate INV-1
  and INV-2, enumerate ALL persistence paths, break them. Deferred unless operator elevates;
  standing tier is 2-DB with A/B/C.

---

## Deliverables

### D1 — Extend `_get_area_entities` with the auto-detect guard set
**File:** `config_flow.py` (`_get_area_entities` + new `_rank_area_candidates`).
**Change:** add filters — `entity_category is None` (excludes DIAGNOSTIC + CONFIG),
`hidden_by is None`, exclude helper/template/group platforms; and a companion
`_rank_area_candidates(entity_ids, actuator_device_ids)` implementing the audit ladder
(own-area > inherited; not-shared-with-actuator; name-denylist; enabled-default;
entity_id sort). De-dup by `(device_id, device_class)` to collapse `_2` siblings.

**Acceptance criteria:**
- **Test:** `test_area_detect_excludes_diagnostic` — a `sensor.relay_chip_temperature` with
  `entity_category=DIAGNOSTIC` in the target area is NOT returned.
- **Test:** `test_area_detect_denylist_backstop` — same entity mis-labeled `entity_category=None`
  but name matches denylist (`chip`, `internal`, `rssi`, `battery`, `uptime`) → ranked LAST.
- **Test:** `test_area_detect_actuator_shared_deprioritized` — a temp entity on the same
  `device_id` as a switch in the room is ranked below a temp entity on a dedicated device.
- **Test:** `test_area_detect_dedup_2_suffix` — `sensor.foo_temp` and `sensor.foo_temp_2` on same
  `device_id`+`device_class` → single winner via ranking.
- **Test:** `test_area_detect_entity_area_override_beats_device_area` — entity with own `area_id`
  in room A wins over an entity whose device is in room A.
- **Verify:** function is pure and read-only (no side effects on registry).

### D2 — Room-type feature-default table (`ROOM_TYPE_FEATURE_DEFAULTS`) — P3
**File:** `const.py`.
**Change:** add dict alongside `ROOM_TYPE_TIMEOUTS` mapping room-type → dict of soft defaults
(e.g. bathroom → `{humidity_fan_enabled: True, wet_room: True}`; bedroom →
`{sleep_protection_enabled: True}`; closet → `{}`). Applied ONLY when the operator has not
explicitly set the corresponding key (soft, not overriding).

**Acceptance:**
- **Test:** `test_room_type_feature_defaults_soft` — creating a bathroom room without touching
  the wet-room toggle → `data[CONF_WET_ROOM] is True`. Creating a bathroom with wet-room
  explicitly unchecked → `data[CONF_WET_ROOM] is False` (operator wins).
- **Verify:** every soft default cites an EXISTING `CONF_*` key (no new flag introduced).

### D3 — Reshaped essentials chain (P1 + P5)
**File:** `config_flow.py`.
**New linear chain for room creation, all defaults from D1/D2:**
1. `async_step_room_setup` — **essentials only:** NAME (default = area name), TYPE (function),
   AREA_ID. Occupancy timeout auto-derived from TYPE (existing behavior).
2. `async_step_room_class` — **NEW.** Class question (wet-room / guest-room / utility-infra) with
   plain-word implications shown inline. Writes existing flags (`CONF_WET_ROOM`,
   `CONF_ROOM_IS_GUEST_ROOM`; utility/infrastructure implied by TYPE).
3. `async_step_sensors_confirm` — pre-filled from D1 auto-detect ranked candidates
   (motion/occupancy, temperature, humidity, lux, door/window). Empty-area case: shows a legible
   message ("found 0 entities in area X — assign entities to this area in HA if the list looks
   short"). Operator confirms or edits.
4. `async_step_devices_confirm` — pre-filled lights/covers/fans from area. Operator confirms.
5. `async_step_room_summary` (P7) — read-only recap → `async_create_entry`.

Everything currently in `night_light_detail`, `cover_behavior`, `automation_behavior`,
`init_automation_chaining`, `init_ai_rules`, `climate`, `fan_speeds`, `sleep_protection`,
`energy`, `notifications` is **moved off the create-path** and remains fully reachable in the
Options flow (no removal). Mid-flow menus removed from essentials (P5).

**Acceptance:**
- **Verify:** creating one room on a fresh install ≤4 screens, ≤~12 visible fields, 0 raw
  entity-ID hunts (operator only confirms pre-fills).
- **Test:** `test_essentials_chain_reaches_create_entry_in_4_steps` — trace step count from
  `room_setup` submit to `async_create_entry`.
- **Test:** `test_essentials_chain_confirm_writes_prefilled_values` — auto-detected entities
  survive confirm-submit into `data`.
- **Test:** `test_essentials_skip_persists_empty_not_guess` (INV-2 anchor) — advancing the
  sensors step with an empty selector (operator cleared it) persists `[]`, NOT the pre-filled
  guess.
- **Live:** on the running HA, add a new bathroom room in ≤4 screens; verify created entry has
  wet-room=True, humidity-fan-enabled soft-defaulted, at least one motion/humidity entity
  pre-filled from area.

### D4 — Continuous house→room ribbon (P5)
**File:** `config_flow.py` (`async_step_post_integration_setup` + house creation).
**Change:** after `async_step_energy_setup` creates the House entry, route the flow directly
into `async_step_room_setup` for continuation (with a visible "Skip — add rooms later" option
that returns to Home). The menu is REACHED, not the default.

**Acceptance:**
- **Test:** `test_first_run_house_to_room_ribbon` — simulate first-install; House create is
  followed by room chain without menu interruption.
- **Verify:** existing "Add Room" from the entry-type menu still works (backward compatibility).
- **Live:** fresh install → after House rate submit + optional energy meters, next screen is
  room setup, not a menu.

### D5 — Assistive House first-run (P6)
**File:** `config_flow.py` (`async_step_integration_config`).
**Change:** auto-detect `WEATHER_ENTITY` (pick sole `weather.*` if exactly one exists; else
selector prefilled with alphabetical-first). Defer outside-temp/humidity/solar/tracked-persons
to Options (they remain fully editable there). Required field remains `ELECTRICITY_RATE`.

**Acceptance:**
- **Verify:** first-run integration step presents ≤2 visible fields (rate + auto-detected
  weather) — everything else is in Options.
- **Test:** `test_house_first_run_weather_autodetect` — single `weather.home` present → default
  = `weather.home`.
- **Test:** `test_house_first_run_electricity_rate_still_required`.
- **Live:** fresh install shows exactly the essentials.

### D6 — Empty-area legibility
**File:** `config_flow.py` (`async_step_sensors_confirm` + `_devices_confirm`).
**Change:** when auto-detect returns 0 candidates for a bucket, render an explanatory
description string (see D3 step 3) — never silent.

**Acceptance:**
- **Test:** `test_area_detect_empty_bucket_message` — sensors step with empty area shows the
  guidance string.
- **Verify:** manual entity picker remains available in the same step (no dead-end).

### D7 — Options flow parity (INV-1 anchor)
**File:** `config_flow.py` (`UniversalRoomAutomationOptionsFlow`).
**Change:** confirm every deferred setup field remains editable in Options; add missing entries
if any (there should be none — all these fields already lived in Options). No representation
change to the existing flags.

**Acceptance:**
- **Test:** `test_round_trip_existing_room_unchanged` (INV-1) — for each room-shape fixture
  (minimal, wet-room, guest-room, cover-bearing, climate, night-lights), open Options and save
  with no change; assert `entry.data == pre_data and entry.options == pre_options` byte-equal.
- **Test:** `test_all_deferred_fields_reachable_in_options` — enumerates every field removed
  from the essentials chain and asserts it appears in an Options step schema.
- **Live:** open Options on an existing production room, save with no change → entry version
  bumps but no field flips (verified via `.storage/core.config_entries` diff).

### D8 — Knob inventory + Numbers-Get-Knobs relocation (P4)
**Change:** no new knobs on the setup path. Enumerate every value that was a "tuning constant"
in the old `climate` / `fan_speeds` / `cover_behavior` first-run steps (humidity-fan EMA/base/
per-min/cap, `BLE_HOLD_CAP_ENABLED`, `COMFORT_FAN_AWAY_VETO_ENABLED`, cover offsets, fan-speed
temps). Each documented with its knob rung per the ladder:

| Value | Current site | Rung | Rationale |
|---|---|---|---|
| Humidity-fan EMA alpha/base/per-min/cap | `climate` step | **Options (Advanced)** or **Number entity** | Operator-tunable by observation; keep out of first-run. |
| `BLE_HOLD_CAP_ENABLED` | `climate` step | **Options (Advanced)** | Rare toggle; not first-run. |
| `COMFORT_FAN_AWAY_VETO_ENABLED` | `climate` step | **Options (Advanced)** | Behavior policy, infrequent flip. |
| Cover open-mode / offsets | `cover_behavior` step | **Options (Advanced)** | Presentation only; unchanged mechanics. |
| Fan-speed temp thresholds | `fan_speeds` step | **Options (Advanced)** | Kept as options; unchanged. |

No new module constants. No new Number entities in this cycle (would be a separate NEW; can
follow if operator wants live-tuning). This deliverable is a **relocation**, not a redefinition.

**Acceptance:**
- **Verify:** knob-inventory table above is complete (grep `climate`/`fan_speeds`/`cover_behavior`
  step schemas; every `vol.Optional` accounted for).
- **Test:** `test_no_tuning_constant_on_essentials_path` — enumerate schemas of the essentials
  chain (D3 steps 1-5); assert none of the enumerated tuning keys appear.

---

## Numbers Get Knobs — new knobs introduced this cycle
**None.** D8 is a relocation. `ROOM_TYPE_FEATURE_DEFAULTS` (D2) is a module constant (Rung 1)
because it is a mapping table, not an operator-tunable value (individual rooms override
per-entry via the existing flags, which is the operator surface).

## Non-goals (explicit)
- **No capability removal.** Everything deferred is still reachable in Options.
- **No representation change** to `CONF_WET_ROOM` / `CONF_ROOM_IS_GUEST_ROOM` / `ROOM_TYPE_*`.
  That is **ROOM-CLASSIFICATION-CONSISTENCY-1** (separate audit-first card).
- **No Number/Select entity added** to expose the relocated tuning constants live. Follow-on if
  operator wants dashboard tunability.
- **No coordinator-options changes.** `coordinator_energy` (~89 fields) is untouched.
- **No zone flow changes.** Only ENTRY_TYPE_ROOM + House first-run are in scope.

## Plan completion / explicit deferrals
- Live Number/Switch entities for relocated tuning constants — deferred (see D8 note).
- Class flag representation refactor — deferred to ROOM-CLASSIFICATION-CONSISTENCY-1.
- Coordinator Options simplification — out of scope (audit §Phase 3).
- Zone-flow simplification — out of scope.

## Acceptance target (from audit §C)
| Metric | Target |
|---|---|
| Screens to one working room | ≤4 |
| Visible fields to one working room | ≤~12 |
| Raw entity-ID pickers operator fills | 0 (confirm auto-detect) |
| Tuning constants on essentials path | 0 |
| Mid-flow menu interruptions on essentials | 0 |
| Capability lost | 0 (INV-1) |
| Silent auto-commits | 0 (INV-2) |

## Live Validation (Review D — write results back into README per CLAUDE.md)
- Fresh install: House rate submit → room chain (D4) → one-room-in-≤4-screens (D3).
- Add a room in a real HA area with mixed diagnostic + real sensors — verify chip-temperature
  NOT pre-filled (D1).
- Open Options on an existing production room, save no-change — no diff in `.storage/core.config_entries` (INV-1).
- Advance the sensors step with an empty selector — persisted `[]`, not the guess (INV-2).

Cycle closes when README `README_v<version>.md` carries the post-restart validation table with
each acceptance row marked PASS with concrete evidence.
