# PLANNING — ONBOARDING-SIMPLIFY-1 (Tier 2-DB, elevation-to-Tier-3 recommended)

**Card:** ONBOARDING-SIMPLIFY-1 · **Date:** 2026-09-12 · **Status:** approved-to-build (plan-review REVISION applied 2026-09-12)
**Authoritative basis:** `docs/planning/AUDIT_first_run_onboarding.md`.

**Scope (approved combo):** P1 progressive disclosure · P2 area-first auto-detect-and-confirm ·
P3 room-type presets set soft feature defaults · P4 relocate tuning constants off setup path ·
P5 continuous house→room ribbon · P6 assistive house first-run (auto-detect weather) · P7 closing
summary. **Plus** the reshaped room-identity step: FUNCTION (type) + an explicit up-front
LOAD-BEARING CLASS question (wet-room / guest-room / utility-infrastructure) that reads/writes
the EXISTING flags (`CONF_WET_ROOM`, `CONF_ROOM_IS_GUEST_ROOM`, `ROOM_TYPE_UTILITY`,
`ROOM_TYPE_INFRASTRUCTURE`). No representation refactor (deferred to
**ROOM-CLASSIFICATION-CONSISTENCY-1**).

---

## Falsifiable invariants (the properties this cycle must not break)

> **INV-1 (Differential no-op round-trip).** For each existing room-shape fixture, the
> **effective** dict `entry.data ∪ entry.options` produced by opening the entry's Options,
> making NO operator change, and saving MUST be **identical on `develop` and on the cycle
> branch**. No effective key's value may change between branches; the cycle may not introduce
> a new effective key on a no-change save that develop did not also introduce.
>
> **Why differential, not byte-equal:** on develop today, room create writes ONLY `entry.data`
> (`config_flow.py:2315-2324`) and every Options step saves `{**self.config_entry.options,
> **user_input}` (merge sites: `:2933, :10170, :10426, :10601, :10703, :10863, :11083, :11143,
> :11190, :11233`), so a never-saved room's first no-change Options save ALREADY grows
> `entry.options` with the step's schema keys. A byte-equal INV-1 is false on the base branch
> — the invariant that discriminates this cycle from regression is *differential parity*.
> **Prove the develop baseline first, then diff.**
>
> **INV-2 (No silent commit).** The area-first auto-detect path MUST NEVER write an entity into
> `ConfigEntry.data` without an explicit confirmation submit from the operator. The default set
> is a *pre-filled selector value*, not a persisted assignment, until the operator advances the
> step. **Anchor bucket:** temperature / lux / door (non-required); occupancy is INTENTIONALLY
> non-skippable — the sensors step hard-rejects empty occupancy at `config_flow.py:1246-1252`
> (`no_occupancy_sensors` error) and D3 keeps that guard.
>
> **INV-3 (Deferred-field default parity — new this revision).** For every field REMOVED from
> the create path in D3, the *effective post-create* value on the cycle branch MUST equal the
> *effective post-create* value on develop for every room-type × class combination in the D9
> table. Silent default flips (schema-default ≠ consumer-fallback) are the failure mode; D2's
> seeding table + D9's parity test are how we enforce it.

All three are testable and framing-disjoint. Reviewer D (if Tier-3 elevated — recommended)
falsifies all three by adversarial enumeration.

---

## Institutional context verified

Prior-art scan per CLAUDE.md "Tier 2+ Prior-Art Scan" and "Institutional Context First."

### Code surface (`custom_components/universal_room_automation/config_flow.py` + `const.py`)

| Proposed piece | Verdict | Evidence |
|---|---|---|
| Area→entity discovery | **REUSED — additive filters only** | `_get_area_entities` at `config_flow.py:744-788`. **14 live callers** consume the COMPLETE list as multi-select defaults (`:1264-1275, :1367-1370, :2049, :2269-2270`, etc.). Only ADDITIVE, non-destructive filters may be added here (`entity_category is None`, `hidden_by is None`, platform excludes). **De-dup / ranking is FORBIDDEN in this helper** — a `(device_id, device_class)` collapse on the `device_class=None` calls would shrink a 4-light device to 1 light for every existing caller. |
| Auto-detect ranker | **NEW pure helper** | `_rank_area_candidates(entity_ids, actuator_device_ids)` — called ONLY by the new `sensors_confirm` / `devices_confirm` steps. Contains ranking ladder + `_2`-suffix dedup + name denylist. Does NOT mutate `_get_area_entities`' return contract. |
| Room entry creation | **REUSED** | `async_create_entry(...)` in room chain (final step `notifications` at `:2292`; write at `:2315-2324`). ENTRY_TYPE_ROOM machinery unchanged. |
| House entry creation from ribbon | **REUSED — existing internal-init pattern** | `async_step_notifications:2296-2309` already mints the House (INTEGRATION) entry from inside a room flow via `self.hass.config_entries.flow.async_init(DOMAIN, context={"source":"integration_create"}, data={...})`, and `async_step_integration_create:2405-2411` receives it. **D4 reuses this pattern in the opposite direction** — see D4 for the corrected mechanism. |
| Config flow step chain | **REUSED — restructured** | `async_step_room_setup:1110` → `sensors:1241` → `devices:1349` → …→ `notifications:2292`. Restructured to reach `async_create_entry` in ≤4 confirmed steps. |
| Room-type→timeouts | **REUSED — extended** | `ROOM_TYPE_TIMEOUTS` at `const.py:1171-1180`; read at `room_setup:1134`. Sibling `ROOM_TYPE_FEATURE_DEFAULTS` NEW (D2). |
| Room-type default tables (prior art for D2) | **REUSED as models** | `ROOM_TYPE_BLE_HOLD_CAP_DEFAULT` at `const.py:1207`; `ROOM_TYPE_FAILSAFE_DURATIONS:1196`; `ROOM_TYPE_RECHECK_FACTOR:765`. D2 follows the same shape. |
| Live bathroom→wet_room cascade | **REUSED — must adjudicate** | `config_flow.py:2035-2042` currently sets `CONF_WET_ROOM=True` when TYPE=bathroom on a specific step. If D2's table also seeds `wet_room:True` for bathroom, that is **two producers** for one flag (Bug Class #53/#63). **Disposition (this plan):** DELETE the :2035-2042 cascade and subsume into `ROOM_TYPE_FEATURE_DEFAULTS`. Single producer. |
| Light capability detect | **REUSED** | `_detect_light_capabilities:790-812`. Unchanged. |
| Wet-room / guest / utility / infra flags | **REUSED as-is** | `CONF_WET_ROOM:const.py:1028`, `CONF_ROOM_IS_GUEST_ROOM:386` (today only set at `config_flow.py:9915-9916` — Options; NEW on the create path this cycle), `ROOM_TYPE_UTILITY:426`, `ROOM_TYPE_INFRASTRUCTURE:429`. No representation refactor. |
| Options flow round-trip | **REUSED** | `UniversalRoomAutomationOptionsFlow:2458`; update via `async_update_entry:2609`. Merge sites for options-save: `:2933, :10170, :10426, :10601, :10703, :10863, :11083, :11143, :11190, :11233`. |
| Consumer fallbacks (parity source) | **REUSED — read for D9** | `automation.py:2550` (`CONF_HUMIDITY_FAN_SPIKE_ENABLED` fallback `False`); `automation.py:2466` (`CONF_HUMIDITY_FAN_CONTROL_ENABLED` fallback matches schema); `fan_veto.py:405` (`CONF_COMFORT_FAN_AWAY_VETO_ENABLED` fallback matches schema); `coordinator.py:3811-3819` (`CONF_BLE_HOLD_CAP_ENABLED` room-type-aware fallback). |
| Notify-service enumeration | **REUSED** | `_get_mobile_app_targets:710`, `:822-829`. |
| Weather entity auto-detect (P6) | **NEW — thin** | No existing "pick a weather entity" helper. See D5 for the CONF_ name adjudication. |
| Class-question step | **NEW step** | `async_step_room_class` — writes the EXISTING flags. |
| Closing summary (P7) | **NEW step** | `async_step_room_summary` — read-only recap → `async_create_entry`. |

### Prior planning docs consulted
- `docs/planning/AUDIT_first_run_onboarding.md` (authoritative).
- Kanban card `ONBOARDING-SIMPLIFY-1` — refinement trail.
- Adjacent card noted out-of-scope: `ROOM-CLASSIFICATION-CONSISTENCY-1`.

### Memory bodies pulled
- `feedback_extend_existing_never_rebuild` — enforced (`_get_area_entities` split, not mutated).
- `feedback_tier2plus_prior_art_scan` — this section.
- `feedback_coincidental_equality_masks_concept_split` — informs the two-producer disposition for the bathroom→wet_room cascade.
- `feedback_parsimonious_room_config`, `feedback_finish_the_job_all_pieces`.

### Design docs
No `docs/Coordinator/<NAME>.md` applies (config flow is integration-level). Identity manual N/A.

### Code locations surveyed end-to-end
`config_flow.py` (steps `user`, `entry_type_select`, `integration_config`, `energy_setup`,
`post_integration_setup:945-969`, `room_setup:1110`, `sensors:1241`, `devices:1349`, `climate`,
`notifications:2292`, `integration_create:2405`, `OptionsFlow.__getattr__` dispatcher and
merge sites listed above); `const.py` (room-type tables + flags); `__init__.py:956-1003`.

---

## Tier classification — Tier 2-DB, **elevation to Tier 3 recommended**

Config flow is a shared surface consumed by ENTRY_TYPE_ROOM + ENTRY_TYPE_ZONE_MANAGER +
Coordinator Manager. **The silent-default-flip surface (D9) is exactly the Tier-3 shape**: one
missed key in a deferred-step schema can silently flip a consumer's behavior in every new room
of that type — the classic "compute-but-not-consume / consume-with-wrong-default" one-missed-site
failure mode. **Recommended:** elevate to Tier 3 (A/B/C/D framings; D re-enumerates the
deferred-field × room-type × class matrix independently of the plan's D9 table).

Standing tier if operator declines elevation: Tier 2-DB with A/B/C, where **Reviewer B is
explicitly assigned the D9 parity enumeration as a named duty** (independent re-derivation of
schema-default vs consumer-fallback for every deferred key).

### Review framings
- **Reviewer A — Round-trip data integrity + differential INV-1.** Build the develop baseline
  first (no-change Options save for each fixture on develop); diff against cycle branch. Every
  deferred field is still writable via Options (no capability lost).
- **Reviewer B — Flow-graph + auto-detect correctness + D9 parity re-derivation.** Every branch
  of the essentials chain reaches `async_create_entry` with a legal payload; ribbon uses the
  `flow.async_init(source="integration_create")` mechanism (not a menu-item post-terminate
  route); class-step writes existing flags with correct semantics; auto-detect ranking follows
  the ladder in the NEW `_rank_area_candidates` (not in `_get_area_entities`); diagnostic/CONFIG
  entities excluded; `_2` dedup on `(device_id, registry.original_device_class or
  device_class)` — live-state `device_class` only as ranking tiebreak. **INV-2 falsifier hunt**
  on the non-required buckets (temp/lux/door). **D9 duty:** independently enumerate every
  deferred key, tabulate schema-default vs consumer-fallback, flag every unequal row that D9
  did not seed via D2.
- **Reviewer C — New surfaces + test fixture authority.** New steps (`room_class`, `room_summary`,
  `sensors_confirm`, `devices_confirm`) round-trip through Options; `ROOM_TYPE_FEATURE_DEFAULTS`
  inheritance is *soft* (operator explicit choice wins on re-edit); acceptance tests drive real
  config-flow entrypoints (not private helpers); empty-area result is LEGIBLE (D6).
- **Reviewer D (Tier 3 only) — Adversarial completeness.** Restate INV-1/2/3, enumerate ALL
  persistence paths INCLUDING pre-existing code (the deferred-field surface predates this cycle),
  break them with legal-config reachable repros.

---

## Deliverables

### D1 — Additive filters in `_get_area_entities` + NEW pure ranker
**Files:** `config_flow.py`.

**Change A (in `_get_area_entities`, additive only):**
- Add `entity_category is None` filter (excludes DIAGNOSTIC + CONFIG).
- Add `hidden_by is None` filter.
- Add platform excludes (helper / template / group).
- **NO de-dup. NO `(device_id, device_class)` collapse. NO ranking.** The returned set may
  SHRINK only by the three additive filters above. All 14 existing callers (`:1264-1275,
  :1367-1370, :2049, :2269-2270`, etc.) must continue to receive the complete non-diagnostic
  set for their multi-select defaults.

**Change B (NEW helper — pure, no registry mutation):**
```
_rank_area_candidates(entity_ids: list[str],
                      actuator_device_ids: set[str]) -> list[str]
```
Implements the audit ladder: own-area > inherited; not-shared-with-actuator; name-denylist
(`AUTODETECT_NAME_DENYLIST` NEW in `const.py`); enabled-default; entity_id sort.
**De-dup key:** `(device_id, registry.original_device_class or registry.device_class)`.
Live-state `device_class` is a **ranking tiebreak only**, never a dedup key (live state may be
`unknown` at flow time — dedup must be registry-stable). Called ONLY by the new
`sensors_confirm` / `devices_confirm` steps.

**Acceptance:**
- **Test:** `test_get_area_entities_no_shrink_beyond_new_filters` — for a fixture area with
  a 4-light device (4 `light.*` entities same `device_id`), `_get_area_entities(area, "light",
  None)` returns all 4 on both develop and branch (baseline diff on the helper itself).
- **Test:** `test_area_detect_excludes_diagnostic` — `sensor.relay_chip_temperature` with
  `entity_category=DIAGNOSTIC` NOT returned.
- **Test:** `test_ranker_denylist_backstop` — same entity mis-labeled `entity_category=None`
  but name matches denylist → ranked LAST by `_rank_area_candidates`.
- **Test:** `test_ranker_actuator_shared_deprioritized` — temp entity on same `device_id` as
  a room switch ranks below temp on a dedicated device.
- **Test:** `test_ranker_dedup_2_suffix_registry_class` — `sensor.foo_temp` +
  `sensor.foo_temp_2`, same `device_id`, both `registry.original_device_class="temperature"`
  → single winner; passes even if live state has `device_class=None`.
- **Test:** `test_ranker_entity_area_beats_device_area`.
- **Verify:** `_rank_area_candidates` is pure — no registry mutation, no state writes.
- **Test (drill):** `test_sensors_confirm_calls_ranker` — behavioral anchor via
  `async_step_sensors_confirm`; neuter `_rank_area_candidates` (return input unchanged) and
  assert the test fails on a fixture where ranking discriminates.

### D2 — Room-type feature-default table (P3)
**File:** `const.py`.
**Change:** add `ROOM_TYPE_FEATURE_DEFAULTS` alongside `ROOM_TYPE_TIMEOUTS:1171-1180`, modeled
on `ROOM_TYPE_BLE_HOLD_CAP_DEFAULT:1207`, `ROOM_TYPE_FAILSAFE_DURATIONS:1196`,
`ROOM_TYPE_RECHECK_FACTOR:765`. Maps room-type → dict of soft defaults using EXISTING `CONF_*`
keys. **Two-producer disposition:** DELETE the live bathroom→`CONF_WET_ROOM=True` cascade at
`config_flow.py:2035-2042` and subsume it into this table — `CONF_WET_ROOM` gets ONE producer.

**D9 seeding requirement:** every unequal row in D9's parity table (schema-default ≠
consumer-fallback for a deferred key) MUST be seeded here OR left on the create path — no
silent flip permitted.

**Acceptance:**
- **Test:** `test_room_type_feature_defaults_soft` — bathroom without touching wet-room →
  `data[CONF_WET_ROOM] is True`; bathroom with wet-room explicitly unchecked → `False`.
- **Test:** `test_no_two_producers_wet_room` — assert the `:2035-2042` cascade is deleted (grep
  in test); creating a bathroom flows `CONF_WET_ROOM=True` exclusively via
  `ROOM_TYPE_FEATURE_DEFAULTS`.
- **Verify:** every entry cites an EXISTING `CONF_*` key.

### D3 — Reshaped essentials chain (P1 + P5)
**File:** `config_flow.py`.

**Linear chain for room creation (defaults from D1/D2/D9):**
1. `async_step_room_setup` — **essentials only:** NAME (default = area name), TYPE (function),
   AREA_ID. Occupancy timeout auto-derived from TYPE.
2. `async_step_room_class` — **NEW.** Wet-room / guest-room / utility-infrastructure with plain-
   word implications. Writes existing flags.
3. `async_step_sensors_confirm` — pre-filled from D1 (`_rank_area_candidates` output) across
   motion/occupancy, temperature, humidity, lux, door/window. Occupancy retains the empty-guard
   at the equivalent of `:1246-1252` (INTENTIONAL — non-skippable). Empty-area case: legible
   message (D6) + manual picker.
4. `async_step_devices_confirm` — pre-filled lights/covers/fans from area.
5. `async_step_room_summary` (P7) — read-only recap → `async_create_entry`.

**Dropped-fields table (fields on the current create path that D3 removes from essentials).**
Every one must be either seeded via D2/D9 or reachable via a NAMED Options step (M1):

| Current create-path field | Current site | Consumers (parity source) | Post-D3 home |
|---|---|---|---|
| `CONF_ZONE` | `config_flow.py:1166-1175` | zone assignment / aggregation | **Options step** — a zone-less new room IS a deliberate behavior change vs today; D3 requires operator to add it in Options post-create. Documented default = unassigned. |
| `CONF_SHARED_SPACE` | `:1180-1188` | `aggregation.py:1211, :1508` | Options step |
| `CONF_SHARED_SPACE_AUTO_OFF_HOUR` | `:1180-1188` | `automation.py:3152` | Options step |
| `CONF_SHARED_SPACE_WARNING` | `:1180-1188` | `automation.py:3152` | Options step |
| `CONF_OCCUPANCY_TIMEOUT` | `:1189` | occupancy state machine | Auto-derived from TYPE on create (existing behavior); tunable in Options |
| `CONF_OCCUPANCY_DEBOUNCE` | `:1199` | occupancy state machine | Options step (schema default retained) |
| `night_light_detail` fields | `:1458` | night-lights automation | Options step (see M5 / D9) |
| `cover_behavior` fields | `:1491` | covers automation | Options step (see M5 / D9) |

Everything currently in `night_light_detail`, `cover_behavior`, `automation_behavior`,
`init_automation_chaining`, `init_ai_rules`, `climate`, `fan_speeds`, `sleep_protection`,
`energy`, `notifications` is **moved off the create-path** and remains reachable in Options.
Mid-flow menus removed from essentials (P5). **Night-lights and covers are EXCLUDED from
essentials auto-prefill** (D9 M5 decision): defaults are set intentionally via D9, not
auto-detected on create.

**Acceptance:**
- **Verify:** creating one room ≤4 confirmed screens, ≤~12 visible fields, 0 raw entity-ID
  hunts.
- **Test:** `test_essentials_chain_reaches_create_entry_in_4_steps`.
- **Test:** `test_essentials_chain_confirm_writes_prefilled_values`.
- **Test (INV-2 anchor, non-required bucket):** `test_essentials_temperature_empty_selector_persists_empty_not_guess`
  — advancing `sensors_confirm` with the TEMPERATURE selector explicitly cleared persists `[]`,
  not the pre-filled guess. (Occupancy remains guarded per `:1246-1252`.)
- **Live:** on running HA, add a new bathroom room in ≤4 screens; verify wet-room=True,
  humidity-fan-enabled soft-defaulted, at least one motion/humidity entity pre-filled.

### D4 — Continuous house→room ribbon (P5) — **corrected mechanism**

**File:** `config_flow.py` (`async_step_energy_setup`, `async_step_post_integration_setup`,
new/adjusted routing).

**Corrected design.** The existing `async_step_post_integration_setup:945-969` creates the
House entry via `self.async_create_entry(title="🏠 Home", data=combined_data)` at
`:957-960` and then RETURNS the create result. Any menu below (`:966-969`) is DEAD on the
first-run path because `async_create_entry` **terminates the flow**. A "route into room_setup
after House create" cannot be layered onto the same flow instance — the flow no longer exists
after `:960`.

**Correct mechanism (already in the repo, opposite direction):**
`async_step_notifications:2296-2309` mints the House entry from inside the room flow via
`self.hass.config_entries.flow.async_init(DOMAIN, context={"source":"integration_create"},
data={...})` — received by `async_step_integration_create:2405-2411`. **D4 inverts this:** the
first-run flow ends in the ROOM `async_create_entry`; the HOUSE entry is spawned mid-room via
the same `flow.async_init(source="integration_create")` pattern. Concretely:

- **Remove** the House `async_create_entry` from `async_step_post_integration_setup` (that
  step's House-create block at `:948-963` is deleted; the step now only shows the
  menu).
- **After `async_step_energy_setup`**, route DIRECTLY into `async_step_room_setup` for
  first-run, carrying `self._integration_data` + `self._energy_data` on the flow instance.
- **Inside the room flow**, at the point of room `async_create_entry` (`:2321-2324`), REUSE
  the existing pattern (`:2298-2312`): if `_integration_data` is present, spawn the House
  entry via `flow.async_init(source="integration_create")` and link the room to it
  (`CONF_INTEGRATION_ENTRY_ID`) — this code already exists and works.
- **Add a visible "Skip — add rooms later" branch** off `async_step_energy_setup` that, when
  chosen, spawns the House entry via `flow.async_init(source="integration_create")` from
  `energy_setup` itself and then aborts the current flow cleanly.
- **Existing "Add Room" from the entry-type menu** continues to work unchanged (backward
  compatibility — that path already uses `flow.async_init` for the House when needed).

**Acceptance:**
- **Test:** `test_first_run_house_to_room_ribbon` — simulate first install; assert the flow
  progresses `integration_config → energy_setup → room_setup → … → room create_entry`, with
  the House entry created via `flow.async_init(source="integration_create")` (not via a
  post-terminate menu route).
- **Test:** `test_first_run_skip_rooms_still_creates_house` — the Skip branch creates a
  House entry and no room entry.
- **Test:** `test_add_room_from_entry_type_menu_backward_compat`.
- **Live:** fresh install → after House rate + optional energy submit, next screen is
  `room_setup`, not a menu; House entry exists in `.storage/core.config_entries` after room
  create.

### D5 — Assistive House first-run (P6)
**File:** `config_flow.py` (`async_step_integration_config`).
**Change:** auto-detect weather entity — pick sole `weather.*` if exactly one exists; else
domain-filtered selector prefilled with alphabetical-first. Defer everything else to Options.

**CONF adjudication (L1):** the existing House field for weather is
`CONF_WEATHER_ENTITY` if present in `const.py` (grep pending in builder — REUSE if found).
**If absent after builder grep, add `CONF_WEATHER_ENTITY` NEW** in `const.py` and cite the
grep result in the build brief. **Do not proceed with an unnamed key.**

**Acceptance:**
- **Verify:** first-run integration step ≤2 visible fields (rate + weather).
- **Test:** `test_house_first_run_weather_autodetect` — single `weather.home` present →
  default = `weather.home`.
- **Test:** `test_house_first_run_electricity_rate_still_required`.
- **Live:** fresh install shows exactly the essentials.

### D6 — Empty-area legibility
**File:** `config_flow.py` (`async_step_sensors_confirm`, `async_step_devices_confirm`).
**Change:** when auto-detect returns 0 candidates for a NON-REQUIRED bucket (temperature /
humidity / lux / door / lights / covers / fans), render an explanatory description string —
never silent. **Occupancy retains its hard guard (`no_occupancy_sensors`, `:1246-1252`)** —
empty area on occupancy still errors, correctly; the guidance string tells the operator why
and how to fix (assign entities to the area in HA).

**Acceptance:**
- **Test:** `test_area_detect_empty_temperature_bucket_message` — sensors step with empty
  temperature bucket in the area shows the guidance string AND allows submit with `[]`.
- **Test:** `test_area_detect_empty_occupancy_still_errors` — empty occupancy in the area
  produces `no_occupancy_sensors` (guard preserved).
- **Verify:** manual entity picker remains available in the same step (no dead-end for
  non-required buckets).

### D7 — Options flow parity (INV-1 anchor, DIFFERENTIAL)
**File:** `config_flow.py` (`UniversalRoomAutomationOptionsFlow`).
**Change:** confirm every deferred setup field remains editable in an Options step. No
representation change to existing flags.

**Acceptance:**
- **Test:** `test_round_trip_existing_room_differential_parity` (INV-1) — for each room-shape
  fixture (minimal, wet-room, guest-room, cover-bearing, climate, night-lights): compute
  effective dict `data ∪ options` after a no-change Options save on `develop` AND on cycle
  branch; assert the two effective dicts are equal. **NOT** byte-equality of the raw
  `entry.options` (that is false on develop today because of the merge sites at `:2933,
  :10170, :10426, :10601, :10703, :10863, :11083, :11143, :11190, :11233`).
- **Test:** `test_all_deferred_fields_reachable_in_options` — enumerates every field removed
  from the essentials chain (D3 dropped-fields table) and asserts it appears in a named
  Options step schema.
- **Live:** open Options on an existing production room, save no-change → effective dict
  differential-equal vs the pre-cycle capture. (The prospective bullet "no diff in
  `.storage/core.config_entries`" is WITHDRAWN — it contradicts the develop baseline; the
  validated observation is the differential-parity check.)

### D8 — Knob inventory + Numbers-Get-Knobs relocation (P4)
**Change:** no new knobs on the setup path. Enumerate every value that was a "tuning constant"
in the old `climate` / `fan_speeds` / `cover_behavior` first-run steps. Each documented with
its knob rung.

| Value | Current site | Rung | Target Options step (L2) |
|---|---|---|---|
| Humidity-fan EMA alpha/base/per-min/cap | `climate` step | Options step | `async_step_climate:10823` |
| `CONF_BLE_HOLD_CAP_ENABLED` | `climate` step | Options step | `async_step_climate:10823` |
| `CONF_COMFORT_FAN_AWAY_VETO_ENABLED` | `climate` step | Options step | `async_step_climate:10823` |
| Cover open-mode / offsets | `cover_behavior` step | Options step | `async_step_options_covers:10696` |
| Fan-speed temp thresholds | `fan_speeds` step | Options step | `async_step_options_lighting:10587` OR a dedicated fan-speeds Options step (builder to confirm — cite the target step's file:line in the build brief; do NOT write "Options (Advanced)" abstractly). |

No new module constants. No new Number entities this cycle.

**Acceptance:**
- **Verify:** grep `async_step_climate`, `async_step_fan_speeds`, `async_step_cover_behavior`
  step schemas; every `vol.Optional` accounted for in the table above (or explicitly kept on
  essentials with justification).
- **Test:** `test_no_tuning_constant_on_essentials_path` — enumerate schemas of D3 steps 1-5;
  assert none of the enumerated tuning keys appear.

### D9 — Deferred-field default-parity table (**NEW deliverable — H3**)
**Files:** planning-doc artifact + `config_flow.py` (seeding) + `const.py` (D2 seed rows) +
test suite.

**Change:** for EVERY key removed from the create path in D3, produce a table with columns
`(CONF_key, schema_default_on_develop, consumer_fallback_on_develop, equal?,
disposition)`. Every UNEQUAL row must have a disposition — either **SEED via D2's
`ROOM_TYPE_FEATURE_DEFAULTS`** (preferred for room-type-conditioned defaults) or **KEEP on
essentials path** (last resort). No unequal row may ship without a disposition.

**Verified rows (starter set — builder + Reviewer B extend to complete):**

| CONF key | Schema default (site) | Consumer fallback (site) | Equal? | Disposition |
|---|---|---|---|---|
| `CONF_HUMIDITY_FAN_SPIKE_ENABLED` | `wet_default(TYPE)` — True for bathroom (`config_flow.py:2079` / defaulted at :2049) | `False` (`automation.py:2550`) | **NO** | **SEED via D2** for bathroom → `True`. Otherwise every new bathroom silently loses humidity-spike detection. |
| `CONF_HUMIDITY_FAN_CONTROL_ENABLED` | schema default (`const.py:1023`) | matches (`automation.py:2466`) | YES | No action — deferring is safe. |
| `CONF_COMFORT_FAN_AWAY_VETO_ENABLED` | schema default (`const.py:989`) | matches (`fan_veto.py:405`) | YES | No action. |
| `CONF_BLE_HOLD_CAP_ENABLED` | room-type-aware via `ROOM_TYPE_BLE_HOLD_CAP_DEFAULT:1207` | room-type-aware (`coordinator.py:3811-3819`) | YES | No action — both sides read the same table. |

**Acceptance:**
- **Verify:** the D9 table is COMPLETE — every key in D3's dropped-fields table appears with
  its parity row.
- **Test (per unequal key):** `test_deferred_parity_<CONF_key>` — create a new room of the
  relevant type on the cycle branch; assert effective post-create value equals develop's
  effective post-create value.
- **Test:** `test_d9_table_complete` — enumerate D3-removed keys; assert every one has a
  corresponding parity test.
- **Reviewer B duty (explicit):** independently re-derive the parity table by grepping schema
  defaults vs consumer sites; any row Reviewer B adds that D9 missed is a plan-review finding.

---

## Numbers Get Knobs — new knobs introduced this cycle
- `ROOM_TYPE_FEATURE_DEFAULTS` (D2) — module constant (Rung 1); mapping table, not
  operator-tunable directly; operator override is per-entry via the existing flags.
- `AUTODETECT_NAME_DENYLIST` (D1) — module constant (Rung 1); safety/quality bound; not
  operator-tunable.
- `CONF_WEATHER_ENTITY` (D5, if not already present) — config field (Rung 2); operator-settable.

## Non-goals (explicit)
- **No capability removal.** Everything deferred is still reachable in Options.
- **No representation change** to `CONF_WET_ROOM` / `CONF_ROOM_IS_GUEST_ROOM` / `ROOM_TYPE_*`
  (that is ROOM-CLASSIFICATION-CONSISTENCY-1).
- **No Number/Select entity** added to expose relocated tuning constants live.
- **No coordinator-options changes.** No zone flow changes.
- **`_get_area_entities` will NOT gain de-dup or ranking.** Those live in `_rank_area_candidates`
  (see D1).

## Plan completion / explicit deferrals
- Live Number/Switch entities for relocated tuning constants — deferred.
- Class flag representation refactor — ROOM-CLASSIFICATION-CONSISTENCY-1.
- Coordinator Options simplification — out of scope.
- Zone-flow simplification — out of scope.

## Acceptance target (from audit §C)
| Metric | Target |
|---|---|
| Screens to one working room | ≤4 |
| Visible fields to one working room | ≤~12 |
| Raw entity-ID pickers operator fills | 0 (confirm auto-detect) |
| Tuning constants on essentials path | 0 |
| Mid-flow menu interruptions on essentials | 0 |
| Capability lost | 0 (INV-1 differential) |
| Silent auto-commits | 0 (INV-2, non-required buckets) |
| Silent default flips | 0 (INV-3 / D9) |

## Live Validation (write results back into README per CLAUDE.md)
- Fresh install: House rate submit → room chain (D4 — verify House minted via
  `flow.async_init(source="integration_create")`, not via a post-terminate menu route) →
  one-room-in-≤4-screens (D3).
- Add a room in a real HA area with mixed diagnostic + real sensors — verify chip-temperature
  NOT pre-filled (D1).
- Open Options on an existing production room, save no-change — effective-dict differential
  parity vs pre-cycle capture (INV-1).
- Advance sensors step with an empty TEMPERATURE selector — persisted `[]`, not the guess
  (INV-2, non-required bucket). Empty OCCUPANCY still errors (guard preserved).
- Create a fresh bathroom room — assert `CONF_HUMIDITY_FAN_SPIKE_ENABLED=True` post-create
  (INV-3 / D9 anchor row).

Cycle closes when `README_v<version>.md` carries the post-restart validation table with each
acceptance row marked PASS with concrete evidence.
