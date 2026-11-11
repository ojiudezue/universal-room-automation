# PLANNING — Config forms: collapsed Advanced sections (A) + fields shown only when relevant (B)

Card: **FORM-CONDITIONAL-FIELDS-1** (joint A+B; A's form half moved here from HA-2027-DEPRECATIONS-URA-1, whose device-registry half stays separate).
Status: plan **rev 3** (rev 2 after two plan reviews, §12; rev 3 = D0 harness result §0, D1 per-key triage §13, text pass §14). Tier: **2-DB, operator-set** (§9).
**Release split decided by D0 (2026-11-11): A (D2 + D3, sections) builds and ships now on the 2026.2.3 harness; B (D4 + D5, `visible=`) waits for a pytest-homeassistant-custom-component release that pins HA 2026.11.** One design, two releases (§0 fallback, now in force).

Operator goal (verbatim): *"The ultimate goal is simplicity + power when you need it."*
Operator scope (verbatim): *"Plan A and B together. I don't want them to diverge. Same customer goal and we won't do it till I upgrade."*
Operator goal added in rev 2 (verbatim): *"Performance should also be a goal. Fast loading, as few reloads as possible etc."* (INV-P, §2.)

---

## 0. Gate

Nothing builds until the house runs an HA **2026.11.x** point release (the `visible=` API starts in Core 2026.11, dev blog 2026-10-21) — operator condition.

Test harness: `.venv-ha` runs HA **2026.2.3** (`homeassistant.const.__version__`), pinned by pytest-homeassistant-custom-component 0.13.316 (TEST-HARNESS-REAL-HA-DEFAULT-1, HARNESS_VS_PRODUCTION_DRIFT_2026_09_15). 2026.2.3's `data_entry_flow.py` has no `Required`/`Optional` marker classes and no `visible`. Routes, decided in D0 (Q1 is one PyPI check and is answered **before** the build is dispatched):
- (a) a phcc release pinning `homeassistant>=2026.11` exists → bump `.venv-ha`.
- (b) else `.venv-ha-2611` with `homeassistant==2026.11.x` + nearest phcc, used for the form test files only. Accepted only if its name-diff vs the 2026.2.3 baseline is green for those files.
- **Fallback (R2-M3):** if neither (a) nor (b) is green, **D4 (B) does not build**. D3 (A, sections) ships on its own: `section` exists in 2026.2.3 and the ~17 existing sections are already harness-tested. B waits for the harness. A and B stay one design; only the release splits.
- Rejected: version-guarded `visible=` code tested against fakes (the suite would test only the fake branch — the reason the device-registry half was parked).

**D0 result (2026-11-11). The fallback is in force.** The house is moving to HA Core 2026.11.1 now.
- **Route (a) — not available.** No pytest-homeassistant-custom-component release pins HA 2026.11. Latest is 0.13.375 → `homeassistant==2026.10.4` (uploaded 2026-10-25).
- **Route (b) — tried, not green.** `.venv-ha-2611` (python 3.14, phcc 0.13.375 + `homeassistant==2026.11.1`). `from homeassistant.data_entry_flow import Optional, Required, section` imports. pytest does not start:
  1. HA 2026.11 calls `httpx2.alias_httpx()` in `homeassistant/__init__.py:12`; phcc's plugin imports `httpx` first → `RuntimeError`. Importing `homeassistant` before `pytest.main` gets past it.
  2. Then phcc `common.py:54` imports `_clear_logger_overwrites` from `homeassistant.components.logger`, which no longer exists in 2026.11.1.
  Patching phcc to get past (2) would test against a harness no release ships, the fake-harness case rejected above. Not done.
- **Consequence.** `section` exists in the 2026.2.3 harness, so **D2 + D3 (A) build and test now** and ship alone (no `hacs.json` floor, D5). **D4 + D5 (B) wait** for a phcc release pinning HA ≥ 2026.11. Revival trigger: a phcc release on PyPI whose `homeassistant` pin is ≥ 2026.11; then re-run D0 gate tests (a)-(f) in that venv before dispatching D4.
- D0 gate tests (a)-(f) are therefore not run yet; the §4/§13 B rows keep their D0 dependency.

---

## 1. Institutional context verified

### External API (fetched)
| Source | Load-bearing content |
|---|---|
| contributors.home-assistant.io/core/integrations/flow-steps/ (developers.home-assistant.io/docs/data_entry_flow_index/ 301s here) | `show_advanced_options` "is deprecated and will be removed in Home Assistant 2027.6. Until then it always returns `True`." Use a collapsed section instead. `section(schema, {"collapsed": True})`; "the fields of a section arrive in a nested dictionary"; "Sections cannot be nested." `visible`: `Required`/`Optional` **from `homeassistant.data_entry_flow`**, `visible={"field","value","operator"}`; operators `eq` (default), `not_eq`, `in`, `not_in`, `exists`, `not_exists`; a list = AND; `True`/`False` allowed. "A hidden field is not shown, not required, and left out of `user_input`, default included." Hidden counts as empty for other conditions. "Inside a section, conditions look at the fields of that section." Hide a whole section with `visible` on the section's marker. Read with `.get(key, fallback)`. No selector list. |
| contributors…/blog/2026/10/21/form-fields-visible/ | Starts Core 2026.11. "While it is hidden, it is not required and its value is not saved." Examples: `BooleanSelector` only. |
| contributors…/blog/2026/05/26/advanced-mode-config-flow-deprecation/ | Property returns True during deprecation, removed 2027.6. "There is no longer a `show_advanced_options` key in `FlowHandler.context`." |
| home-assistant.io/blog/2026/11/04/release-202611/ ("Forms that ask only what they need") | "While a field is hidden, it isn't required, and its value isn't saved." First 100k of 186k chars read. |
| contributors…/core/integrations/options-flow/ | `async_create_entry(data=…)` "stores `data` as the new options" — replace; URA's `{**options, **user_input}` is what preserves keys. |

### Installed HA source (2026.2.3)
- `data_entry_flow.py:645-647` property reads `context`; `:649-689` `add_suggested_values_to_schema` drops top-level `description["advanced"]` markers when the flag is False, recurses into a section **only when the section key is in `suggested_values`** (`:670-681`), and replaces `description` wholesale with `{"suggested_value": …}` (`:688-689`).
- `:915-934` `section.__call__` validates the nested dict; a `vol.Optional("<section>")` with no default that is absent from input never runs its inner schema, so **no inner defaults are applied** (URA's own comment `config_flow.py:5559-5561`).
- `helpers/config_validation.py:1189-1201` serializer: `expandable`, `expanded = not collapsed`, nesting raises.

### show_advanced_options readers — re-enumerated (`config_flow.py`, develop)
| Kind | Sites | Count |
|---|---|---|
| Direct property reads | :1248, :4611, :13568, :13763, :14216 | **5** |
| Dead context injection | :4646 `shim.context = {"show_advanced_options": True}` | 1 |
| `_show_adv()` callers | :1594, 2333, 2376, 2512, 4391, 4603, 4792, 4852, 4958, 5285, 5454, 11255, 11346, 11490, 11580, 11804, 13965, 14363, 14746 | 19 |
| `_filter_advanced(...)` callers (implicit reader via HA filter) | :1621, 2420, 2523, 4789, 4849, 4955, 5282, 5451, 11252, 11343, 11487, 11577, 11800, 13559, 14359, 14741 (defs :169, :1252, :4613) | 16 |
| Filter-only `add_suggested_values_to_schema(…, {})` | :13760, :14209 | 2 |
| Hint helpers / callers | `advanced_hint` :63, `advanced_hint_for` :93, `room_menu_hint` :117; callers :4415, 4603, 4791, 4851, 4957, 5284, 5453, 11254, 11345, 11489, 11579, 11803, 13566, 13761, 14214, 14362, 14745; placeholder sites :11030, :13770, :14223 (R1-L1) | 3 / 17 + 3 |
| Default backfill on the flag | `_hidden_advanced_defaults` :178; callers :1597, :2382, :2511 | 1 / 3 |
| Advanced markers, form 1 | `_adv(...)` :149 — 74 field uses | 74 |
| Advanced markers, form 2 | literal `{"advanced": True}` | 11 |
| Advanced markers, form 3 (R1-H3, missed in rev 1) | `advanced_if_empty` in create `sensors`/`devices` builders: `desc["advanced"] = True` :2458, `_multi` :2468, callers to :2534 (e.g. `CONF_MMWAVE_SENSORS`, `CONF_DOOR_SENSORS`, `CONF_WATER_LEAK_SENSOR`, `CONF_AUTO_SWITCHES`); `_caps_default` conditional marker :13450-13456 | ~10 |
| Strings | `strings.json` + `translations/en.json`: 15 `advanced_hint` placeholders; section label `"advanced": "Advanced (rarely change)"` strings.json:1337 | 15 |
| Tests | **50 refs / 11 files** (R1-M1; my rev-1 grep used a narrower pattern): `test_room_advanced_fields.py`, `test_zone_house_advanced_fields.py`, `test_onboarding_simplify_phase2.py`, `test_onboarding_simplify_slice2.py`, `test_lighting_slice_e_slots_scenes.py`, `test_lighting_slice_d_house_state.py`, `test_sensor_form_plain_text.py`, `test_energy_write_verification.py`, `_room_menu_helpers.py`, `test_night_light_rule_options_flow.py:112`, `test_room_menu_trim.py:252-253` | 50 |

**Rev 3 recount (D1 AST scan, 2026-11-11, line numbers on this branch):** field markers are **67**, not 74 + 11 + ~10: `_adv(...)` as a field `description` **53** (the "74" above counted `_show_adv`/`_adv_key` lines too), the `adv` variable in `_integration_config_schema` **8** (`config_flow.py:1688-1728`), `advanced_if_empty=True` **5** (`:2478`, `:2493`, `:2498`, `:2546`, `:2552`), the literal on `sensor_capabilities_json` **1** (`:13606`). Plus two non-field uses: the create `room_class` step is **skipped whole** unless Advanced (`:2336-2341`, 2 fields), and the lighting-behaviour clearable list reads `_adv` (`:14116`). All are rows in §13.

No other file reads the flag. Today (2026.10.x) the property returns True, so every Advanced field shows. At 2027.6 the `getattr(..., False)` readers flip to hiding everything with no toggle to reveal it.

### Prior art, REUSE vs BUILD
| Piece | Verdict | Evidence |
|---|---|---|
| Collapsed `section()` | REUSED (~17 existing) | :3522, 3552, 5685, 6762, 7493, 7664, 7687, 8355, 8701, 8946-8952, 10687, 10690, 13840, 14180, 14614, 14653; shim `_ha_section` :30-39 |
| Flatten-on-save | REUSED pattern, BUILD `_flatten_sections` | ad-hoc pops :6145-6192, :8839-8845, :10503, :13863, :13938, :14373-14378. No `def _flatten` exists. Existing working sites are not migrated unless their step is restructured |
| Section-aware default walk | REUSED | `_collect_schema_defaults` :3939 |
| Options merge | REUSED | `{**options, **user_input}` ~25 sites (:4709, 4806, 5303, 7972, 8876, 9055 …) |
| Zone save + sibling mirror | REUSED, must be fed flat keys (R1-H1) | `_auto_mirror_to_siblings` :4140 (callers :11105, 11291, 11404, 11534, 11611, 11662, 11782; mirror writes :4209-4277); `zone_rooms` reads `user_input.get(CONF_ZONE_DESCRIPTION, current)` :11096-11099 |
| Create backfill | REUSED symbol, **renamed + extended** (R2-L3) | `_hidden_advanced_defaults` :178 → `_absent_field_defaults`; same 3 callers move together, no shim |
| Trimmed room menu | REUSED, integrated | `_value_is_non_default` :129, `ROOM_MENU_STEPS_*` const.py:510-521, `room_menu_hint` :117. Trim stays; Advanced sentence + :4646 go |
| `_adv` non-default promotion (D8.2/I2) and `advanced_if_empty` / `_caps_default` | RETIRE | Only needed because Advanced mode hid fields entirely; a collapsed section shows saved values one click away (§6) |
| Hint helpers | DELETE | explain a profile toggle that no longer exists |
| `visible=` markers | NEW HA API use | replaces hand-rolled fan-mode routing (Options climate) |
| Update-listener hot-apply / reload allowlist | REUSED, consumer (R1-M4) | `__init__.py:7034` `_HVAC_TUNABLE_DISPATCH`, merged-per-lookup lists `__init__.py:7694-7729`. Must only ever see flat keys; a section key reaching `options` would force a full reload (parent-reload watchdog hazard) |
| Reload-vs-live-apply decision (performance goal) | REUSED, verified | `_async_update_listener` `__init__.py:8395`. ROOM branch :8612: `changed_keys` = value compare `old.get(k) != new.get(k)` against a last-applied snapshot; suppress only if ⊆ `_ROOM_SUPPRESS_KEYS` (:8439), else reload. CM branch :8661: normalised value compare (`_norm_cm_opt`), empty → no-op, ⊆ `OPTIONS_RELOAD_SUPPRESS_KEYS` (:7477) → apply in place. INTEGRATION branch :8769: ⊆ `INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS` (:7667), kill switch `INTEGRATION_RELOAD_SUPPRESS_ENABLED` (:7755). ZONE_MANAGER: no branch → any change reloads. All compares are by value, so key order never counts; a key that appears with a value (absent → default) **does** count as changed |
| Render timing | REUSED | `_cflow_timing.py` wraps every `async_step_*`; WARNING when `elapsed_ms > CFLOW_SLOW_MS` (:65, = 250, :116). Baseline: `docs/planning/AUDIT_config_flow_performance.md` §1 — every options step < 20 ms live (slowest: room `climate` 16 ms). Audit §2 hot spots on render paths: `_get_area_entities` full-registry scan (create flow, 17 sites) and the menu factory-render shim :4639-4660 that builds hidden steps' schemas on every menu render |

### Prior plans, docs, memory
- `PLANNING_onboarding_simplify_phase2.md` — full; amendment O1-O17 (:189-281), incl. **:278-280 "take O9-O13 (energy) as a separate cycle after a consumer audit — a missed parent gate on an energy knob is a money path"** (now honored, §10).
- `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` — **read in full by plan review 1** (`docs/reviews/code-review/config_forms_AB_plan_review_1.md`, L3), not by this author. Findings used here: O14/O15 touch no HVAC write site (§4.1/§4.2) and assert nothing in the §10 ledger. Since W1-C P2, freshness/reload are adapter verbs (`freshness_row` / `remediate_stale`), and arrester-off is passive mode (gate (d), §9e), so the arrester → carrier-knob pair is **not** a real dependency (dropped). `hvac_cover_close_temp` is also a live Number entity (`number.py:2712`) and hot-applied (`__init__.py:7034`). The D1 builder must read the doc in full before touching O14/O15 rows (CLAUDE.md 5b).
- `AUDIT_device_tree_vs_ha_2026_11_child_devices.md` — skimmed; out of scope.
- `ONBOARDING_SIMPLIFY_D8_knob_inventory.md`, `PLANNING_onboarding_simplify.md` — headers.
- Kanban: FORM-CONDITIONAL-FIELDS-1, HA-2027-DEPRECATIONS-URA-1 (DEDUPE_2026_11_05), TEST-HARNESS-REAL-HA-DEFAULT-1, ROOM-TYPE-TRIMMED-MENU-1.
- Memory: `feedback_parsimonious_room_config`, `feedback_configurability_clarity`, `feedback_extend_existing_never_rebuild`, `feedback_hollow_test_anchors`, `feedback_parent_entry_reload_watchdog_hazard`.

Config-first: no setting fixes this; the profile toggle is what HA removed.

---

## 2. Falsifiable invariants

**INV-1a (unedited round-trip).** For every restructured step, create and Options, all four families: submitting what the frontend would submit with no edits (§5 D2 harness) stores a dict equal to the pre-change dict for every key, and `set(stored) & set(section_keys) == ∅`. Falsified by any key that disappears, changes, or appears as a section name. One stated exception, Options only: a key that was never stored and whose section was not expanded stays unstored (today it would have been written with its default). The runtime value is the same because readers use `.get(key, default)` (D1 verifies each), and leaving it out avoids adding a key that the listener would read as a change (INV-P).

**INV-1b (edit propagation, R1-H2).** For every moved key: changing that one field (inside its section or behind `visible`) to a non-default value stores exactly that value at the flat key, changes no other key, and — for zone mirror keys — the same value appears on every sibling zone sharing the thermostat. Falsified by the old value persisting (missed flatten, or a hand-built `user_input.get(KEY, current)` reading the top level) or a sibling not updated.

**INV-2 (no hidden live value, restated per R1-M4).** B never hides a field whose stored value affects runtime behaviour while its controller is in the hiding state. Falsified by any hidden dependent with a runtime reader that does not gate on the controller. B itself changes no runtime behaviour (the merge keeps values); the risk is an operator who can no longer see a value that is still acting. Known breaker found: `aggregation.py:885-903` `_is_sleep_hours` reads the first room's sleep hours regardless of `CONF_SLEEP_PROTECTION_ENABLED` → sleep hours are **not** made conditional (§4).

**INV-3 (flag-free, R1-M2 + R2-M5).** (i) A schema-walk test builds every step schema (create + Options, all families, descending into sections) and asserts no marker `description` has a truthy `advanced` key. (ii) A behavioural test renders each restructured step under a `FlowHandler` whose `show_advanced_options` is False (the 2027.6 condition) and asserts the full field set renders. A source grep for `show_advanced_options|_show_adv|advanced_hint|_adv\(` is kept as a lint only.

**INV-P (performance, operator goal).**
- (i) **Zero reloads on a move-only save.** Saving any restructured step with no value edits causes zero `async_reload` calls for any entry type. Mechanism: INV-1a makes the stored options equal, so HA's `async_update_entry` short-circuits and the listener does not run. Falsified by a backfilled default key, a section-named key, or a normalisation change (e.g. `None` → `""`) appearing in Options: the ROOM/ZM/INTEGRATION compares are plain `!=`, so each of those reads as a change and reloads. That is why Options paths never backfill (§3).
- (ii) **A live-apply knob stays live-apply.** Editing a moved key that is in its entry's existing suppress set today (`_ROOM_SUPPRESS_KEYS`, `OPTIONS_RELOAD_SUPPRESS_KEYS`, `INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS`) causes zero reloads after the move. Falsified by any extra key riding along in the save (a carried-forward or backfilled key the compare sees as changed). This cycle neither adds nor removes allowlist keys.
- (iii) **No render regression.** No restructured step's `CFLOW-TIMING` EXIT exceeds the audit baseline by more than noise, and none crosses `CFLOW_SLOW_MS`. Schema building adds no registry or state scans: sections and `visible=` are static schema; the `visible` evaluator runs only on submit.

---

## 3. Producer / consumer of saved options

**Producer shapes.** D1 classifies every restructured step into exactly one:
1. **Options merge** `{**options, **user_input}`.
2. **Options replace** (builds `new_opts` from scratch, e.g. :8555, :9024, :9857, :10333).
3. **Create** (ConfigFlow, no saved options).
4. **ZM nested + mirror** (R1-H1): zone steps build a payload from top-level `user_input` keys, write `options["zones"][name].update(payload)`, then `_auto_mirror_to_siblings` copies `MIRROR_KEYS_*` to house zones on the same thermostat.

**Fixed ordering per shape (R2-H1, R2-H3).** The first line of every submit handler on a restructured step is `flat = _flatten_sections(user_input, schema)`; nothing reads `user_input` after that.
1. Merge: `flat` → `{**options, **flat}`. **No backfill** (would reset hidden keys to factory defaults).
2. Replace: `flat` → build `new_opts` as today → carry forward from `options` **only the keys that `visible=` hid on this submit** (dependents whose condition evaluates False against `flat`). No blanket `{**options}`: replace steps rely on dropping cleared fields.
3. Create: `flat` → `{**_absent_field_defaults(schema, flat), **flat}`.
4. ZM: `flat` → build payload from `flat` → existing update + mirror. Hand-built `user_input.get(K, current)` reads become `flat.get(K, current)`.

**`_absent_field_defaults(schema, flat)` (R1-M3, R2-H1).** Returns marker defaults for exactly two cases: (a) every inner field of a section whose key was absent or not a dict in the raw `user_input` (never expanded), recursing via the `_collect_schema_defaults` walk; (b) every field whose `visible` condition evaluates False against `flat`. It does **not** fill a visible field the user cleared (v5.37.1 clear-field hazard, comment :2440-2445). Evaluating `visible` needs a small evaluator for the six operators; D0 checks whether 2026.11 exposes HA's own evaluator to reuse instead.

**`_flatten_sections(user_input, schema)` (R2-M1, R1-L2).** Pops every key whose schema value is a `section`; ignores a section key that is absent or not a dict; merges inner keys up (section wins). Collisions are prevented at build time, not at submit: a unit test walks every step schema and fails on a section key equal to a field key or a duplicate inner/outer key. The existing `advanced` section key in `_build_hvac_dynamic_preset_schema` (:8701) is legitimate. Runtime collisions log at debug; the helper never raises in a submit handler.

**Consumers.**
- Runtime readers of each moved key (coordinators, entity platforms) — per-key in D1, columns `.get` vs `[]` and gated-on-controller.
- Update listener: `__init__.py:7034` hot-apply allowlist and `:7694-7729` merged lookups — must only see flat keys (covered by INV-1a's section-key check). Reload decision `__init__.py:8395` compares values, so key order is irrelevant, but any key that newly appears counts as a change: replace-step carry-forward must copy the **stored** value (never a default), and Options paths never backfill (INV-P).
- Sibling mirror `_auto_mirror_to_siblings` :4140 — keyed on flat names (INV-1b).
- Number entities that duplicate a form knob (e.g. `hvac_cover_close_temp`, `number.py:2712`) — not hidden by B; noted, accepted.

---

## 4. Per-form field triage

**Placement rules (precedence, R1-H3, R2-H2):**
1. A field with a controller lives at its **controller's level**, never inside a different section. Default: Everyday with `visible=`.
2. If all of a section's fields depend on one top-level controller, put `visible` on the **section marker** (documented; the marker is top-level, so the condition sees the controller).
3. Every other Advanced field goes into the step's collapsed section.
4. New fields go into one new section keyed `advanced` per step; existing sections stay as they are and keep their own fields.
5. A field with no default and no saved value that the step needs stays Everyday.

D1 records, per row: controller level, dependent level, resolution (rule 1, 2 or 3). No row ships ambiguous.

### Room forms
| Step (flow) | → Advanced section | → Conditional (controller → dependents, resolution) |
|---|---|---|
| `room_class` (create) | 1 field | — |
| `sensors` / `sensors_confirm` (create), `sensors` (Options) | `sensor_capabilities_json`; the `advanced_if_empty` sensors (`CONF_MMWAVE_SENSORS`, `CONF_DOOR_SENSORS`, `CONF_WATER_LEAK_SENSOR`, …) | — |
| `devices` / `devices_confirm` (create), `devices` (Options) | `CONF_AUTO_SWITCHES` and other `advanced_if_empty` / `_adv` fields without a controller | night lights `exists` → 5 night-light colour/brightness fields: **rule 1**, they move out of Advanced to Everyday with `visible=` |
| `climate` (Options) | humidity runtime stays in existing `humidity_fan_advanced` | O4: `CONF_ROOM_FAN_MODE eq room_temperature` → `CONF_FAN_SPEED_LOW/MED/HIGH_TEMP` (both top-level today, :14575-14577): **rule 1**, Everyday + `visible=`, replacing the hand-rolled re-routing |
| `climate` → `fan_speeds` (create) | — | **Unchanged.** The temps are a separate create step today (:3437-3438, :3588), shown only for room-temperature mode, so the create path already asks only when relevant. Merging the steps would change stored keys on create (today no temp keys are stored when the step is skipped). Not worth it |
| `options_lighting_behaviour` | 13 tuning fields (hold/cooldown, scenes, dark-only, evening brightness/colour) | — (evening fields stay in section; no same-level controller) |
| `options_covers` | `CONF_SUNRISE_OFFSET` | O3: `CONF_TIMED_CLOSE_ENABLED` → close-time source; source `eq fixed` → hour; source `eq sunset` → `CONF_SUNSET_OFFSET`: **rule 1**, all Everyday + `visible=` |
| `sleep_protection` (create + Options) | — | O2 **narrowed**: `CONF_SLEEP_PROTECTION_ENABLED` → bypass count, block covers (readers gate via `is_sleep_mode_active`, `automation.py:1284-1292`). Start/end hours **stay always visible**: `_is_sleep_hours` reads them house-wide regardless of the toggle (INV-2) |
| `init` menu / `show_all_settings` | — | trim kept; drop Advanced sentence; delete :4646 |

### Zone forms (all shape 4)
| Step | → Advanced section | Conditional |
|---|---|---|
| `zone_rooms` | `CONF_ZONE_DESCRIPTION` +1 | — |
| `zone_hvac` | `CONF_HVAC_AC_LOAD_SENSOR` +3 | — |
| `zone_energy` | `CONF_ZONE_POWER_SENSORS` +1 | — |
| `zone_media` | 2 | — |
| `zone_dynamic_preset` | `CONF_RESET_GUEST` +1 | O15 zone: `CONF_ENABLED` → `CONF_OFFSET`, `CONF_SLEEP_ENABLED` — rule 1 (Everyday + `visible=`); D1 confirms readers gate on `CONF_ENABLED` |

### House / integration forms
| Step | → Advanced section | Conditional |
|---|---|---|
| `integration_config` (create + Options) | 1-2 | — |
| `global_sensors` | 3 | — |
| `energy_sensors` | `CONF_HOUSE_DEVICE_POWER_SENSORS` +1 | — |
| `person_tracking` | 3 | — |
| `camera_census` | 12 | O16: `CONF_FACE_RECOGNITION_ENABLED` → `CONF_KNOWN_FACE_GUESTS` — rule 1; D1 verifies `camera_census.py:3782` gates on the toggle, else drop |
| `perimeter_alerting` | 7 | O16: `CONF_PERIMETER_ENRICHMENT_ENABLED` → provider — rule 1, same D1 check |

### Coordinator manager forms (B only)
| Step | Conditional |
|---|---|
| `coordinator_hvac_settings` | O14: `CONF_HVAC_SOLAR_GAIN_COVER_ENABLED` → `CONF_HVAC_COVER_CLOSE_TEMP` (+ cover entities), rule 1. Note: the same value is a live Number entity and hot-applied, so the dashboard still shows it when the form hides it — accepted, no change. **Arrester → carrier knobs dropped** (not a dependency since W1-C P2) |
| `hvac_dynamic_preset` | O15: `CONF_DYNAMIC_PRESET_ENABLED` → relax-ceiling mode and offsets; same level as controller verified in D1 (existing `advanced` section :8701 — if dependents are inside it, rule 2 on that section's marker) |
| `coordinator_presence` | O17: `CONF_FAN_RECHECK_ENABLED` (top-level, :5675-5681) → whole `fan_recheck_advanced` section: **rule 2** (`visible` on the section marker) |
| `coordinator_energy` | **O9-O13 parked** (§10) |

Quiet-hours / notifications pairs (unsurveyed in the amendment) are out of scope; not absorbed by D1.

**Rev 3 corrections from D1 (§13; each is an INV-2 reader check, code wins over the rows above):**
- **O3 narrowed.** `CONF_TIMED_CLOSE_ENABLED` is **not** a controller for close source / close hour / sunset offset: `_is_cover_close_time` (`automation.py:2733-2770`) is also read by the cover open-intent check used by HVAC sun control (`automation.py:2233-2246`), with no Timed-close gate. Only the source pairs stay conditional: close source `eq` fixed → close hour, close source `eq` sunset → sunset offset (both gated by the source branch, `:2739-2745`).
- **O4 re-specified.** `eq room_temperature` would hide live values: in Follow-thermostat rooms the room tier still runs the temperature path when HVAC is not running the room (`automation.py:2789-2801`), and that path reads the three speed temperatures (`:3204-3206`). The correct condition is `CONF_ROOM_FAN_MODE not_eq off` (`fan_owner` None → return, `:2789-2791`). Still B; D0(e) must cover `not_eq` on a SelectSelector.
- **O16 known guests dropped.** `known_face_guests` is read by the perimeter known-person demote with no face-recognition gate (`perimeter_alert.py:4977-4980`) and by name canonicalisation (`camera_census.py:3993`, `:4069`). It stays always visible. O16 enrichment → provider (+ model, max tokens, provider id) is kept: all four are read only after `_is_enabled_for_camera` (`perimeter_enrichment.py:147-190`).
- **Create `room_class`** (2 fields) is a whole-step skip, not a marker. A drops the skip: the step always shows (it shows today because the property returns True). No stored-key change: an untouched form stores the same two type defaults (`:2337-2341`).
- **Night lights (options `devices`)** are 5 `_adv` markers (`:13770-13821`), all B rows (rule 1, `visible` on `CONF_NIGHT_LIGHTS exists`). Until B ships they go into the step's `advanced` section (A), then move up when D4 lands. Same for the three climate fan-speed temperatures (`:14725-14739`).

---

## 5. Deliverables

### D0 — Harness + API gate tests (before D3)
Answer Q1 (PyPI). Build the venv per §0. In it, write and run gate tests:
(a) `visible` survives `add_suggested_values_to_schema(schema, options)`; (b) `data_entry_flow.Optional` keeps `default=` and `description` suggested values; (c) a mixed `vol.Optional` / `data_entry_flow.Optional` schema serializes through `voluptuous_serialize` with the condition present; (d) a condition inside a section referencing a top-level field (Q2); (e) EntitySelector `exists` and SelectSelector `eq` as controllers (Q5); (f) whether HA exposes a `visible` evaluator to reuse.
- **Verify:** each gate test passes, or the matching §4 rows fall back to section-only / always-visible, recorded here.
- **Verify:** name-diff vs the 2026.2.3 baseline recorded; HA-drift failures carded, not fixed here.
- **Test:** `test_gate_visible_*` (kept in the suite). **Live:** `ha_get_system_health` shows 2026.11.x.

### D1 — Per-key triage (doc)
Expand §4 per key: key, file:line, step, flow, producer shape (1-4), target, controller level / dependent level / resolution rule, runtime readers (file:line), `.get` vs `[]`, gated on controller (Y/N), mirror key (Y/N), **save effect: live-apply / reload**, read from the existing suppress set for that entry type (`_ROOM_SUPPRESS_KEYS` :8439, `OPTIONS_RELOAD_SUPPRESS_KEYS` :7477, `INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS` :7667; zone manager = always reload). No parallel list is created. Replace steps: record clear-semantics. Any N in gated-on-controller → that field is not made conditional.
- **Verify:** every Advanced marker (all three forms) has a row; every kept O-pair has reader rows.
- **Test:** none. **Live:** none.

### D2 — Helpers + harness
`_flatten_sections`, `_absent_field_defaults` (renamed from `_hidden_advanced_defaults`), a `visible` evaluator if D0(f) finds none, and the round-trip harness (R2-H4):
1. build `user_input` from each marker's `default` or `suggested_value`, walking sections (URA prefills Options with `default=self._get_current(...)`, e.g. :5573, :14159-14175);
2. **nest** section fields under their section key, as the frontend does;
3. **omit** fields whose `visible` evaluates False, as HA does;
4. run on **create and Options** for every restructured step; for INV-1b, set one key to a non-default value and assert propagation (and sibling mirror for zones).
Builders must not switch prefill to `add_suggested_values_to_schema(schema, options)`: it leaves section fields unfilled (`data_entry_flow.py:670-681`).
- **Verify:** flatten ignores absent/non-dict section keys; build-time collision test fails on an injected collision and passes on the real schemas (incl. :8701 `advanced`).
- **Verify:** `_absent_field_defaults` fills an un-expanded section's defaults and does **not** fill a cleared visible field.
- **Test:** `test_flatten_sections_*`, `test_section_key_collisions_none`, `test_absent_field_defaults_unexpanded_section`, `test_absent_field_defaults_cleared_visible_field_not_filled`.
- **Live:** none.

### D3 — A: sections replace Advanced mode
Per §4: Advanced fields into each step's `advanced` section; ordering per §3; delete `_adv`, `advanced_if_empty`, `_caps_default` marker, `_filter_advanced(_schema)`, the two filter-only `add_suggested_values_to_schema(…,{})` calls, `_show_adv`, hint helpers, :4646, hint placeholders in `strings.json` + `translations/en.json`; section label strings added per new section. Update all 11 test files (§1).
- **Verify:** INV-1a and INV-1b on every restructured step; INV-3 (i) and (ii).
- **Verify (discriminating):** a missing flatten shows as a section-named key (INV-1a) or the old value after an edit (INV-1b); a missing create backfill shows as absent inner defaults on a never-expanded section; a zone step missing flatten shows as sibling not updated.
- **Verify (INV-P):** a move-only save of each restructured Options step triggers zero reloads; editing one moved key that is on its entry's suppress set triggers zero reloads; editing one that is not triggers exactly one (the discriminator: zero would mean the save never reached the listener).
- **Test:** `test_forms_round_trip_<family>_<step>_{create,options}`, `test_forms_edit_propagates_<family>_<step>` (parametrized over moved keys), `test_zone_moved_mirror_key_reaches_sibling`, `test_create_unexpanded_section_stores_defaults`, `test_no_advanced_markers_schema_walk`, `test_full_fields_render_without_advanced_mode`, lint `test_no_show_advanced_options_source`, `test_move_only_save_zero_reloads_<family>` and `test_live_apply_key_stays_live_after_move` (both count `hass.config_entries.async_reload` calls through the real `_async_update_listener`), `test_step_render_no_extra_registry_scans` (counts `_get_area_entities` / `ent_reg.entities` reads per render, before vs after).
- **Live (INV-P):** with `CFLOW-TIMING` logs, open each restructured step once; EXIT `elapsed_ms` within noise of the audit §1 numbers and below 250. Save a lighting-behaviour step unchanged: no "scheduling reload" log line for that entry and its room entities do not blink.
- **Live:** open one room's lighting behaviour, one zone's HVAC, house camera census: section collapsed; Save with no edits; the entry's options in `.storage/core.config_entries` equal a pre-save copy and contain no `advanced` key. Edit one zone knob that is mirrored; the sibling zone shows the same value.

### D4 — B: `visible=` (only if D0 green)
Per §4 conditional column (O2 narrowed, O3, O4 Options-only, O14 cover temp, O15, O16 after D1 check, O17 rule 2).
- **Verify:** controller off hides dependents; save with it off keeps the old values (merge/ZM) or carries them forward (replace); create stores defaults (same keys as today, since today these fields are shown and their defaults submitted).
- **Verify (discriminating):** a replace step with a blanket merge fails the clear-a-field test; a replace step with no carry-forward fails `hidden_keeps_saved`.
- **Verify (INV-P):** saving with a controller off (dependents hidden, values kept) and nothing else changed triggers zero reloads; toggling a controller triggers whatever that key does today (reload or live-apply per D1), never more.
- **Test:** `test_visible_<pair>_hidden_keeps_saved`, `test_visible_<pair>_create_backfills_default`, `test_replace_step_clear_field_still_clears`, `test_<reader>_ignores_dependent_when_controller_off` (drives the real consumer), `test_hidden_dependents_save_zero_reloads`.
- **Live:** sleep protection off on one room → bypass count and block covers hidden, hours still shown; re-enable → previous values pre-filled. Presence fan recheck off → its Advanced section disappears.

### D5 — `hacs.json` floor + README (ships with D4 only)
Add `"homeassistant": "2026.11.0"`. Decision (R2-M4): the floor is **required** with D4, because `from homeassistant.data_entry_flow import Optional` fails to import on older HA and the integration would not load; a guarded import with a fallback is the rejected dual path. If D3 ships alone, no floor. Consequence: every URA release from D4 on needs HA ≥ 2026.11 at Wigton (runs an older URA; its HA version unknown here). README states it; a note goes on the Wigton card: upgrade Wigton HA before taking that release.
- **Verify:** HACS shows the floor. **Live:** HACS install succeeds on the house.

Sequencing: D0 → D1 → D2 → D3 → D4 → D5 on one branch. One release if D0 is green; otherwise D3 ships, D4+D5 wait for the harness. **Rev 3: D0 was not green (§0). Release 1 = D2 + D3 + the §14 text pass, on the 2026.2.3 harness, no floor. Release 2 = D4 + D5 after the phcc trigger fires.** The B rows' fields sit in each step's `advanced` section in release 1 and move up to Everyday with `visible=` in release 2 (a layout move only; stored keys are unchanged, INV-1a covers both).

---

## 6. Simplicity

- Retire the non-default promotion (`_adv` I2, `advanced_if_empty`, `_caps_default`): a collapsed section shows saved values; keeping it would give each form two layouts depending on saved data.
- Fields with a controller stay Everyday (rule 1). Slightly longer top level while the controller is on; removes nearly every cross-level question.
- Keep the create `fan_speeds` step: it already asks only when relevant.
- Don't migrate untouched working sections.
- No O5 shared builders; energy rows parked; arrester pair dropped; sleep hours not conditional.

## 7. Knobs
No behavioural numbers added or changed. Moved fields keep their names and rungs. `collapsed=True` is a fixed UI choice.

## 8. Open questions (all resolved or gated in D0 unless noted)
1. Q1: phcc release for HA ≥ 2026.11? **Answered 2026-11-11: no** (latest 0.13.375 pins 2026.10.4); route (b) fails at harness start-up (§0). A ships now, B waits.
2. Q2: cross-section `visible` — D0(d). Plan does not depend on it.
3. Q3: `visible` survives `add_suggested_values_to_schema` (2026.2.3 replaces `description` wholesale, :688-689) — D0(a).
4. Q4: mixed marker classes, `default=` retention — D0(b),(c).
5. Q5: selectors as controllers — D0(e).
6. Q6: does the 2026.11 frontend always send a section dict? Plan is built to not care (§3 backfill case a).
7. Q7: Wigton HA version — operator.
8. The 2026.11 release blog was read to 100k of 186k characters.

## 9. Tier
**Tier 2-DB, operator-set** (2026-11-06; no DB trigger fires). Every form for every entry type is restructured; the failure is silent value loss, a lost edit, or sibling drift through one missed save path. Three build reviews:
- **A — save-path correctness:** the four shapes and their ordering; INV-1a/1b.
- **B — consumers:** runtime gating (INV-2), update-listener allowlist, sibling mirror, trimmed menu.
- **C — test authority by mutation** (drills below).
Plan reviews done (2, §12). Live validation written back to the README.

Review C drills (each must turn a named test RED): remove `_flatten_sections` from one Options step and from one create step; stop `_absent_field_defaults` recursing into sections; replace `{**options, **flat}` with `flat` in a step with a `visible` pair; drop one reader's controller gate; flip one `visible` operator `eq`→`not_eq` (GREEN means the harness ignores `visible`); add `{**options}` to a replace step; remove flatten from one zone step (mirror test).

## 10. Non-goals
- Device-registry deprecations (HA-2027-DEPRECATIONS-URA-1).
- **Energy O9-O13** — parked per phase-2 amendment :278-280 (money path; needs its own consumer audit). Revival trigger: this cycle ships and a consumer audit of the energy parent toggles is carded.
- O1, O5, O6/O7 as standalone work; quiet-hours/notifications pairs.
- Arrester → carrier knobs.
- Merging create `fan_speeds` into `climate`.
- Performance work beyond not regressing: no allowlist expansion (zone manager stays always-reload), no fix for the audit's `_get_area_entities` scan or the menu factory-render shim (both pre-existing, both under 20 ms live), no new profiling code. Measurement = existing `CFLOW-TIMING` logs + reload-count tests.
- Rewriting existing working sections; new fields or knobs; menu-trim changes; dual code paths for HA < 2026.11. (Rev 3: label and helper-text rewrites are now IN scope, but only as the reviewed table in §14 / `AUDIT_form_text_plain_pass.md`; no rewording outside that table.)

## 11. Plan completion tracking (fill at close)
| Item | Done / deferred | Why | Tracked at |
|---|---|---|---|
| D0 harness + gate tests | partial | Q1 answered, route (b) not green; gate tests (a)-(f) wait for a phcc 2026.11 pin | §0 revival trigger |
| D1 per-key triage | done (rev 3) | §13 | — |
| D2 helpers + harness | | | |
| D3 sections (A) | | | |
| D4 visible (B) | | | |
| D5 floor + README | | | |
| O9-O13 energy | parked | §10 | revival trigger §10 |
| O5 shared builders | parked | §6 | revisit if create/Options drift found |

---

## 12. Plan review fix-ups (rev 2)

Reviews: `docs/reviews/code-review/config_forms_AB_plan_review_1.md` (completeness), `…_review_2.md` (build-prediction). Each claim was checked against code before acceptance.

Summary: 23 findings (11 + 12) plus the operator's performance goal. 20 were accepted as written, 3 changed (R1-H3 option, R1-M4 option, R2-M4 scope; see below), and none dismissed.

| ID | Finding | Checked | Resolution |
|---|---|---|---|
| R1-H1 | Zone save + sibling mirror missing | confirmed :4140, :11096-11099 | §3 shape 4 + ordering; INV-1b mirror clause; `test_zone_moved_mirror_key_reaches_sibling` |
| R1-H2 | No-edit round-trip can't catch lost edits | agreed | INV-1b; edit-propagation tests parametrized over moved keys |
| R1-H3 | Cross-level rows, O4 separate create step, missed `advanced_if_empty`/`_caps_default` | confirmed :3437-3438, :2458, :13450-13456 | §4 placement rules + per-row resolution; O4 Options-only, create `fan_speeds` unchanged (no create-key change); markers added to §1/§4 and retired |
| R1-M1 | Tests 50/11 | accepted (my narrower grep gave 38) | §1 table + D3 |
| R1-M2 | INV-3 grep not falsifiable | agreed | INV-3 (i) schema walk, (ii) render test; grep = lint |
| R1-M3 | backfill under-specified; cleared-field hazard | agreed | §3 `_absent_field_defaults` definition (unexpanded sections + visible-false only); cleared-field test |
| R1-M4 | INV-2 breaker `_is_sleep_hours`; listener consumer | confirmed aggregation.py:885-903, `__init__.py:7034` | INV-2 restated; sleep hours stay visible (no behaviour ruling needed); listener in §3 consumers |
| R1-M5 | Energy O9-O13 contradict prior plan | agreed | parked §10 with trigger |
| R1-L1 | Missing hint sites | confirmed | §1 |
| R1-L2 | Existing `advanced` section key :8701 | agreed | §3 collision rule allows it |
| R1-L3 | Arrester pair wrong; cover temp Number entity | accepted on review 1's HVAC-doc reading | arrester dropped; note in §4 |
| R2-H1 | Create ordering / section-blind backfill | agreed (:5559-5561) | §3 fixed ordering per shape; recursive backfill; `test_create_unexpanded_section_stores_defaults` |
| R2-H2 | Same-level rule contradicted by 3 rows | agreed (:5675-5685 confirmed) | night lights rule 1; fan temps rule 1 Options-only; fan recheck rule 2 |
| R2-H3 | Blanket merge breaks clearing on replace steps | agreed | carry forward only visible-hidden keys; clear-field test |
| R2-H4 | Harness emulates wrong prefill | agreed | D2 harness spec (defaults, nesting, omission, both paths) + prefill warning |
| R2-M1 | Collision behaviour in production | agreed | build-time collision test; runtime section-wins, debug log, never raise |
| R2-M2 | D0 questions not gates | agreed | D0 gate tests (a)-(f) with per-row fallback |
| R2-M3 | No harness fallback | agreed | §0 fallback: A ships on 2026.2.3, B waits |
| R2-M4 | `hacs.json` floor scope | agreed in part | floor only with D4, and required there (import fails otherwise); Wigton note |
| R2-M5 | INV-3 test is a grep | agreed | INV-3 (ii) render test |
| R2-L1 | climate has two sections | agreed | rule 4: new fields → new `advanced` section, existing sections keep theirs |
| R2-L2 | precise section-key check | agreed | INV-1a `set(stored) & set(section_keys) == ∅` |
| R2-L3 | rename, not shim | agreed | §1 + D2 |
| OP-PERF (operator-added goal) | "Fast loading, as few reloads as possible" | verified `_async_update_listener` :8395 branches, suppress sets :7477/:7667/:8439, `CFLOW_SLOW_MS` :65, audit baseline < 20 ms | INV-P (i)-(iii); D1 save-effect column from existing allowlists; D3/D4 reload-count + render tests and Live timing check; Options never backfill and carry-forward copies stored values only (a new key = a reload); perf fixes beyond no-regression are non-goals |

Rejected or changed from the reviews' suggestions:
- **R1-H3 option "merge `fan_speeds` into `climate`"** — rejected. The separate create step already shows the temperatures only when relevant, and merging changes stored keys on create.
- **R1-M4 option "gate `_is_sleep_hours` on the toggle"** — rejected for this cycle. It is a runtime behaviour change outside a form-layout cycle; leaving the hours visible satisfies INV-2 without one. Whether `_is_sleep_hours` should honour the toggle is a separate question for the operator, not carded here.
- **R2-M4 "ship D3 without the floor"** — accepted only when D3 ships alone; with D4 the floor is mandatory, not optional.

---

## 13. D1 — per-key triage (rev 3, 2026-11-11)

Built from an AST scan of `config_flow.py` on this branch (every `vol.Optional/Required` whose `description` is `_adv(...)`, the `adv` variable, an `{"advanced": True}` literal, or an `advanced_if_empty=True` builder call), CONF names resolved from `const.py` + `domain_coordinators/*_const.py`, then a reader grep over the package (excluding `config_flow.py` and the const modules; multi-line `.get(` calls followed). Save effect is read from the existing allowlists only: `_ROOM_SUPPRESS_KEYS` (`__init__.py:8519`), `OPTIONS_RELOAD_SUPPRESS_KEYS` (`:7526`, including its `*_HVAC_TUNABLE_DISPATCH.keys()`, `*_NM_A2_KEYS`, `*_NM_C_KEYS` members), `INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS` (`:7733`); zone manager = always reload. Producer shapes per §3: 1 merge, 2 replace, 3 create, 4 ZM nested + mirror. No restructured step is shape 2 (every Options save here is `{**options, **…}`). The HVAC state-of-play doc was read in full for the zone_hvac / O14 / O15 rows; nothing here re-asserts a §10 ledger claim.

**Counts.** 67 marker rows + 1 step-skip row (2 fields) + 17 non-marker B dependents. **A-now: 55 fields** (53 marker rows + the 2 `room_class` fields). **B-later: 31 dependent fields** (14 marker rows: 5 night-light, 3 fan-speed, sunset offset, 4 enrichment, zone DPM sleep; + 17 non-marker dependents in table 13.2). Until release 2, B marker rows sit in the step's `advanced` section like A rows. **Dropped from B: 2 pairs** (O16 known guests; O3 Timed-close as controller), **re-specified: 1** (O4 condition). Rows whose readers do not gate on the controller are never made conditional (INV-2).

### 13.1 Advanced markers (all three forms)

| # | Key | Marker | Step | Flow | Shape | Target | Controller (rule) | Runtime readers | Access | Gated | Mirror | Save effect | Release |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `outside_temp_sensor` | `config_flow.py:1688` (adv) | integration_config | create | 3 | `advanced` section of `integration_config` | — | `domain_coordinators/hvac_covers.py:202`, `aggregation.py:1234`, `__init__.py:5646` | .get | — | N | create (n/a) | A-now |
| 2 | `outside_humidity_sensor` | `config_flow.py:1691` (adv) | integration_config | create | 3 | `advanced` section of `integration_config` | — | `aggregation.py:1246`, `__init__.py:5647` | .get | — | N | create (n/a) | A-now |
| 3 | `solar_production_sensor` | `config_flow.py:1694` (adv) | integration_config | create | 3 | `advanced` section of `integration_config` | — | `aggregation.py:3041`, `__init__.py:5649` | .get | — | N | create (n/a) | A-now |
| 4 | `person_data_retention_days` | `config_flow.py:1697` (adv) | integration_config | create | 3 | `advanced` section of `integration_config` | — | no reader (const.py:183); keep, text says "Not used" | .get | — | N | create (n/a) | A-now |
| 5 | `transition_detection_window` | `config_flow.py:1706` (adv) | integration_config | create | 3 | `advanced` section of `integration_config` | — | no reader (const.py:184) | .get | — | N | create (n/a) | A-now |
| 6 | `electricity_rate` | `config_flow.py:1717` (adv) | integration_config | create | 3 | `advanced` section of `integration_config` | — | `domain_coordinators/energy_billing.py:48`, `domain_coordinators/energy_billing.py:80`, `domain_coordinators/energy_billing.py:82` (+1) | .get | — | N | create (n/a) | A-now |
| 7 | `notification_service` | `config_flow.py:1725` (adv) | integration_config | create | 3 | `advanced` section of `integration_config` | — | `aggregation.py:1596`, `__init__.py:5651`, `button.py:462` | .get | — | N | create (n/a) | A-now |
| 8 | `notification_level` | `config_flow.py:1728` (adv) | integration_config | create | 3 | `advanced` section of `integration_config` | — | `aggregation.py:1598`, `__init__.py:5653` | .get | — | N | create (n/a) | A-now |
| 9 | `presence_sensors` | `config_flow.py:2478` (advanced_if_empty) | sensors_confirm | create | 3 | `advanced` section of `sensors_confirm` | — | 28 readers (`sensor_capability.py:125`, `chatter_detector.py:80`, `optimization.py` ×6 …), all list reads | .get | — | N | create (n/a) | A-now |
| 10 | `door_sensor` | `config_flow.py:2493` (advanced_if_empty) | sensors_confirm | create | 3 | `advanced` section of `sensors_confirm` | — | `aggregation.py:1767`, `binary_sensor.py:1410`, `binary_sensor.py:1446` | .get | — | N | create (n/a) | A-now |
| 11 | `water_leak_sensor` | `config_flow.py:2498` (advanced_if_empty) | sensors_confirm | create | 3 | `advanced` section of `sensors_confirm` | — | `domain_coordinators/safety.py:1347`, `domain_coordinators/safety.py:1422`, `aggregation.py:1563` (+5) | `[]` after `in` check | — | N | create (n/a) | A-now |
| 12 | `auto_switches` | `config_flow.py:2546` (advanced_if_empty) | devices_confirm | create | 3 | `advanced` section of `devices_confirm` | — | `coordinator.py:1451`, `sensor.py:2267`, `sensor.py:2293` (+6) | .get | — | N | create (n/a) | A-now |
| 13 | `humidity_fans` | `config_flow.py:2552` (advanced_if_empty) | devices_confirm | create | 3 | `advanced` section of `devices_confirm` | — | `domain_coordinators/appliance_const.py:101`, `domain_coordinators/appliance_const.py:116`, `actuator_reconciler.py:1012` (+10) | .get | — | N | create (n/a) | A-now |
| 14 | `outdoor_dark_lux` | `config_flow.py:4755` (_adv) | global_sensors | options | 1 | `advanced` section of `global_sensors` | — | `lighting/darkness.py:161` | .get | — | N | reload | A-now |
| 15 | `electricity_rate` | `config_flow.py:4775` (_adv) | global_sensors | options | 1 | `advanced` section of `global_sensors` | — | `domain_coordinators/energy_billing.py:48`, `domain_coordinators/energy_billing.py:80`, `domain_coordinators/energy_billing.py:82` (+1) | .get | — | N | reload | A-now |
| 16 | `house_device_power_sensors` | `config_flow.py:4835` (_adv) | energy_sensors | options | 1 | `advanced` section of `energy_sensors` | — | no reader (const.py:377) | .get | — | N | reload | A-now |
| 17 | `person_data_retention_days` | `config_flow.py:4922` (_adv) | person_tracking | options | 1 | `advanced` section of `person_tracking` | — | no reader (const.py:183); keep, text says "Not used" | .get | — | N | reload | A-now |
| 18 | `transition_detection_window` | `config_flow.py:4938` (_adv) | person_tracking | options | 1 | `advanced` section of `person_tracking` | — | no reader (const.py:184) | .get | — | N | reload | A-now |
| 19 | `census_cross_validation` | `config_flow.py:5166` (_adv) | camera_census | options | 1 (`cleaned`, :5027-5064) | `advanced` section of `camera_census` | — | `camera_census.py:1298`, `camera_census.py:2585` | .get | — | N | live-apply (INTEGRATION_OPTIONS) | A-now |
| 20 | `census_divergence_downgrade` | `config_flow.py:5174` (_adv) | camera_census | options | 1 (`cleaned`, :5027-5064) | `advanced` section of `camera_census` | — | `camera_census.py:2468` | .get | — | N | reload | A-now |
| 21 | `enhanced_census` | `config_flow.py:5186` (_adv) | camera_census | options | 1 (`cleaned`, :5027-5064) | `advanced` section of `camera_census` | — | `sensor.py:3797`, `sensor.py:3818`, `camera_census.py:5632` (+2) | `[]` after `in` check | — | N | reload | A-now |
| 22 | `egress_identity_failsafe_strict` | `config_flow.py:5197` (_adv) | camera_census | options | 1 (`cleaned`, :5027-5064) | `advanced` section of `camera_census` | — | `camera_census.py:4314`, `switch.py:927` | .get | — | N | live-apply (INTEGRATION_OPTIONS) | A-now |
| 23 | `census_ble_cancel_enabled` | `config_flow.py:5212` (_adv) | camera_census | options | 1 (`cleaned`, :5027-5064) | `advanced` section of `camera_census` | — | `camera_census.py:5649` | .get | — | N | live-apply (INTEGRATION_OPTIONS) | A-now |
| 24 | `auto_enable_person_detection` | `config_flow.py:5225` (_adv) | camera_census | options | 1 (`cleaned`, :5027-5064) | `advanced` section of `camera_census` | — | `__init__.py:622` | .get | — | N | reload | A-now |
| 25 | `census_hold_interior` | `config_flow.py:5236` (_adv) | camera_census | options | 1 (`cleaned`, :5027-5064) | `advanced` section of `camera_census` | — | `camera_census.py:5662` | .get | — | N | reload | A-now |
| 26 | `census_hold_exterior` | `config_flow.py:5251` (_adv) | camera_census | options | 1 (`cleaned`, :5027-5064) | `advanced` section of `camera_census` | — | `camera_census.py:5667` | .get | — | N | reload | A-now |
| 27 | `door_groups` | `config_flow.py:5273` (_adv) | camera_census | options | 1 (`cleaned`, :5027-5064) | `advanced` section of `camera_census` | — | `transit_validator.py:1123` | .get | — | N | reload | A-now |
| 28 | `door_interior_neighbours` | `config_flow.py:5280` (_adv) | camera_census | options | 1 (`cleaned`, :5027-5064) | `advanced` section of `camera_census` | — | `transit_validator.py:1124` | .get | — | N | reload | A-now |
| 29 | `main_entry_door` | `config_flow.py:5291` (_adv) | camera_census | options | 1 (`cleaned`, :5027-5064) | `advanced` section of `camera_census` | — | no reader outside config_flow (text pass R12; card candidate) | — | — | N | reload | A-now |
| 30 | `perimeter_zone_sensors` | `config_flow.py:5300` (_adv) | camera_census | options | 1 (`cleaned`, :5027-5064) | `advanced` section of `camera_census` | — | `perimeter_alert.py:4359` | .get | — | N | reload | A-now |
| 31 | `face_name_aliases` | `config_flow.py:5314` (_adv) | camera_census | options | 1 (`cleaned`, :5027-5064) | `advanced` section of `camera_census` | — | `camera_census.py:4034` | .get | — | N | live-apply (INTEGRATION_OPTIONS) | A-now |
| 32 | `perimeter_enrichment_provider` | `config_flow.py:5410` (_adv) | perimeter_alerting | options | 1 (+ strips 4 retired keys, :5356-5364) | section now → Everyday + `visible` (B) | `perimeter_enrichment_enabled` (1) | `perimeter_enrichment.py:178` | .get | Y (after `_is_enabled_for_camera`, `perimeter_enrichment.py:147-158`) | N | live-apply (INTEGRATION_OPTIONS) | B-later |
| 33 | `perimeter_enrichment_person_sensors` | `config_flow.py:5423` (_adv) | perimeter_alerting | options | 1 (+ strips 4 retired keys, :5356-5364) | `advanced` section of `perimeter_alerting` | — | `perimeter_enrichment.py:35`, `perimeter_enrichment.py:121`, `perimeter_enrichment.py:156` (+2) | .get | — | N | live-apply (INTEGRATION_OPTIONS) | A-now |
| 34 | `perimeter_enrichment_model` | `config_flow.py:5438` (_adv) | perimeter_alerting | options | 1 (+ strips 4 retired keys, :5356-5364) | section now → Everyday + `visible` (B) | `perimeter_enrichment_enabled` (1) | `perimeter_enrichment.py:182` | .get | Y (after `_is_enabled_for_camera`, `perimeter_enrichment.py:147-158`) | N | live-apply (INTEGRATION_OPTIONS) | B-later |
| 35 | `perimeter_enrichment_max_tokens` | `config_flow.py:5451` (_adv) | perimeter_alerting | options | 1 (+ strips 4 retired keys, :5356-5364) | section now → Everyday + `visible` (B) | `perimeter_enrichment_enabled` (1) | `perimeter_enrichment.py:186` | .get | Y (after `_is_enabled_for_camera`, `perimeter_enrichment.py:147-158`) | N | live-apply (INTEGRATION_OPTIONS) | B-later |
| 36 | `perimeter_enrichment_provider_id` | `config_flow.py:5467` (_adv) | perimeter_alerting | options | 1 (+ strips 4 retired keys, :5356-5364) | section now → Everyday + `visible` (B) | `perimeter_enrichment_enabled` (1) | `perimeter_enrichment.py:190` | .get | Y (after `_is_enabled_for_camera`, `perimeter_enrichment.py:147-158`) | N | live-apply (INTEGRATION_OPTIONS) | B-later |
| 37 | `exterior_snapshot_offset_s` | `config_flow.py:5482` (_adv) | perimeter_alerting | options | 1 (+ strips 4 retired keys, :5356-5364) | `advanced` section of `perimeter_alerting` | — | `perimeter_alert.py:28`, `perimeter_alert.py:4170` | .get | — | N | live-apply (INTEGRATION_OPTIONS) | A-now |
| 38 | `zone_description` | `config_flow.py:11370` (_adv) | zone_rooms | options | 4 | `advanced` section of `zone_rooms` | — | `__init__.py:59`, `__init__.py:455`, `__init__.py:1376` | .get | — | N | reload (ZM: always) | A-now |
| 39 | `zone_player_mode` | `config_flow.py:11475` (_adv) | zone_media | options | 4 (legacy zone entry: 1, :11450) | `advanced` section of `zone_media` | — | `__init__.py:1383`, `__init__.py:1384`, `music_following.py:1331` (+1) | `[]` after `in` check | — | N | reload (ZM: always) | A-now |
| 40 | `hvac_ac_load_sensor` | `config_flow.py:11589` (_adv) | zone_hvac | options | 4 (legacy zone entry: 1, :11565) | `advanced` section of `zone_hvac` | — | `domain_coordinators/hvac_zones.py:544`, `domain_coordinators/hvac_zones.py:664`, `domain_coordinators/hvac_zones.py:3256` | .get | — | Y | reload (ZM: always) | A-now |
| 41 | `hvac_ac_ramp_zone_enabled` | `config_flow.py:11599` (_adv) | zone_hvac | options | 4 (legacy zone entry: 1, :11565) | `advanced` section of `zone_hvac` | — | `domain_coordinators/hvac_zones.py:545`, `domain_coordinators/hvac_zones.py:666`, `domain_coordinators/hvac_zones.py:3257` | .get | — | Y | reload (ZM: always) | A-now |
| 42 | `hvac_thermostat_min_delta_f` | `config_flow.py:11613` (_adv) | zone_hvac | options | 4 (legacy zone entry: 1, :11565) | `advanced` section of `zone_hvac` | — | `domain_coordinators/hvac_zones.py:51` | .get | — | Y | reload (ZM: always) | A-now |
| 43 | `zone_power_sensors` | `config_flow.py:11708` (_adv) | zone_energy | options | 4 (legacy zone entry: 1, :11695) | `advanced` section of `zone_energy` | — | `aggregation.py:4493`, `aggregation.py:4499` | .get | — | Y | reload (ZM: always) | A-now |
| 44 | `zone_dynamic_preset_reset_offset_guest` | `config_flow.py:12603` (_adv) | zone_dynamic_preset | options | 4 | `advanced` section of `zone_dynamic_preset` | — | `domain_coordinators/dynamic_preset.py:860` | .get | — | Y | reload (ZM: always) | A-now |
| 45 | `zone_dynamic_preset_sleep_enabled` | `config_flow.py:12608` (_adv) | zone_dynamic_preset | options | 4 | section now → Everyday + `visible` (B) | `zone_dynamic_preset_enabled` (1) | `domain_coordinators/dynamic_preset.py:940` | .get | Y (gate 1 `dynamic_preset.py:581`) | Y | reload (ZM: always) | B-later |
| 46 | `sensor_capabilities_json` | `config_flow.py:13590` (literal) | sensors | options | 1 | `advanced` section of `sensors` | — | form-only; saved as `sensor_capabilities` (:13213-13218); read by `sensor_capability.py` | .get | — | N | reload | A-now |
| 47 | `night_light_sleep_brightness` | `config_flow.py:13770` (_adv) | devices | options | 1 | section now → Everyday + `visible` (B) | `night_lights exists` (1) | `switch.py:5668`, `lighting/resolver.py:206` | .get | Y (applied only to night-light entities, `lighting/resolver.py:206-256`, `switch.py:5661`) | N | reload | B-later |
| 48 | `night_light_sleep_hue` | `config_flow.py:13781` (_adv) | devices | options | 1 | section now → Everyday + `visible` (B) | `night_lights exists` (1) | `lighting/resolver.py:256` | .get | Y (applied only to night-light entities, `lighting/resolver.py:206-256`, `switch.py:5661`) | N | reload | B-later |
| 49 | `night_light_sleep_color` | `config_flow.py:13796` (_adv) | devices | options | 1 | section now → Everyday + `visible` (B) | `night_lights exists` (1) | `lighting/resolver.py:210` | .get | Y (applied only to night-light entities, `lighting/resolver.py:206-256`, `switch.py:5661`) | N | reload | B-later |
| 50 | `night_light_day_brightness` | `config_flow.py:13807` (_adv) | devices | options | 1 | section now → Everyday + `visible` (B) | `night_lights exists` (1) | `switch.py:5670`, `lighting/resolver.py:218`, `lighting/resolver.py:231` | .get | Y (applied only to night-light entities, `lighting/resolver.py:206-256`, `switch.py:5661`) | N | reload | B-later |
| 51 | `night_light_day_color` | `config_flow.py:13818` (_adv) | devices | options | 1 | section now → Everyday + `visible` (B) | `night_lights exists` (1) | `lighting/resolver.py:225`, `lighting/resolver.py:235` | .get | Y (applied only to night-light entities, `lighting/resolver.py:206-256`, `switch.py:5661`) | N | reload | B-later |
| 52 | `lights_on_entry_dark_only` | `config_flow.py:14165` (_adv) | options_lighting_behaviour | options | 1 (+ clearable pops, :14100-14121) | `advanced` section of `options_lighting_behaviour` | — | `automation.py:1826`, `lighting/resolver.py:117` | .get | — | N | reload | A-now |
| 53 | `light_manual_on_hold_s` | `config_flow.py:14228` (_adv) | options_lighting_behaviour | options | 1 (+ clearable pops, :14100-14121) | `advanced` section of `options_lighting_behaviour` | — | `automation.py:825` | .get | — | N | reload | A-now |
| 54 | `light_manual_off_cooldown_s` | `config_flow.py:14240` (_adv) | options_lighting_behaviour | options | 1 (+ clearable pops, :14100-14121) | `advanced` section of `options_lighting_behaviour` | — | `automation.py:827` | .get | — | N | reload | A-now |
| 55 | `light_evening_brightness_pct` | `config_flow.py:14267` (_adv) | options_lighting_behaviour | options | 1 (+ clearable pops, :14100-14121) | `advanced` section of `options_lighting_behaviour` | — | `lighting/resolver.py:349` | .get | — | N | reload | A-now |
| 56 | `light_evening_color_kelvin` | `config_flow.py:14278` (_adv) | options_lighting_behaviour | options | 1 (+ clearable pops, :14100-14121) | `advanced` section of `options_lighting_behaviour` | — | `lighting/resolver.py:355` | .get | — | N | reload | A-now |
| 57 | `night_light_evening_brightness` | `config_flow.py:14286` (_adv) | options_lighting_behaviour | options | 1 (+ clearable pops, :14100-14121) | `advanced` section of `options_lighting_behaviour` | — | `lighting/resolver.py:374` | .get | — | N | reload | A-now |
| 58 | `night_light_evening_color` | `config_flow.py:14297` (_adv) | options_lighting_behaviour | options | 1 (+ clearable pops, :14100-14121) | `advanced` section of `options_lighting_behaviour` | — | `lighting/resolver.py:380` | .get | — | N | reload | A-now |
| 59 | `light_scene_day` | `config_flow.py:14309` (_adv) | options_lighting_behaviour | options | 1 (+ clearable pops, :14100-14121) | `advanced` section of `options_lighting_behaviour` | — | `lighting/resolver.py:303` | .get | — | N | reload | A-now |
| 60 | `light_scene_evening` | `config_flow.py:14316` (_adv) | options_lighting_behaviour | options | 1 (+ clearable pops, :14100-14121) | `advanced` section of `options_lighting_behaviour` | — | `lighting/resolver.py:304` | .get | — | N | reload | A-now |
| 61 | `light_scene_sleep` | `config_flow.py:14323` (_adv) | options_lighting_behaviour | options | 1 (+ clearable pops, :14100-14121) | `advanced` section of `options_lighting_behaviour` | — | `lighting/resolver.py:305` | .get | — | N | reload | A-now |
| 62 | `sunrise_offset` | `config_flow.py:14460` (_adv) | options_covers | options | 1 | `advanced` section of `options_covers` | — | `automation.py:2282` | .get | — | N | reload | A-now |
| 63 | `sunset_offset` | `config_flow.py:14490` (_adv) | options_covers | options | 1 | section now → Everyday + `visible` (B) | `cover_close_time_source eq sunset` (1) | `automation.py:2763` | .get | Y (`automation.py:2741` → `:2763`; legacy branch only when source unset) | N | reload | B-later |
| 64 | `fan_speed_low_temp` | `config_flow.py:14725` (_adv) | climate | options | 1 (flattens 2 existing sections, :14526-14529) | section now → Everyday + `visible` (B) | `room_fan_mode not_eq off` (1, §4 rev 3) | `automation.py:3204` | .get | Y (`automation.py:2789-2791`) | N | live-apply (_ROOM) | B-later |
| 65 | `fan_speed_med_temp` | `config_flow.py:14732` (_adv) | climate | options | 1 (flattens 2 existing sections, :14526-14529) | section now → Everyday + `visible` (B) | `room_fan_mode not_eq off` (1, §4 rev 3) | `automation.py:3205` | .get | Y (`automation.py:2789-2791`) | N | live-apply (_ROOM) | B-later |
| 66 | `fan_speed_high_temp` | `config_flow.py:14739` (_adv) | climate | options | 1 (flattens 2 existing sections, :14526-14529) | section now → Everyday + `visible` (B) | `room_fan_mode not_eq off` (1, §4 rev 3) | `automation.py:3206` | .get | Y (`automation.py:2789-2791`) | N | live-apply (_ROOM) | B-later |
| 67 | `humidity_fan_max_runtime` | `config_flow.py:14758` (_adv) | climate | options | 1 (flattens 2 existing sections, :14526-14529) | `advanced` section of `climate` | — | `automation.py:3528`, `automation.py:3621` | .get | — | N | live-apply (_ROOM) | A-now |
| 68 | `wet_room`, `room_is_guest_room` | whole-step skip `config_flow.py:2336-2341` | room_class | create | 3 | step always shown (drop the skip; fields Everyday) | — | `room_classification.py:132`; presence `_discover_guest_rooms` `presence.py:5768` | .get | — | N | create (n/a) | A-now |

Notes on 13.1:
- `water_leak_sensor` readers use `options[...]` only after an `in options` check (`aggregation.py:1563-1564`, `:5043-5044`); every other reader is `.get` with a fallback, so an unstored (never-expanded, Options) key reads its default (INV-1a exception holds).
- `person_data_retention_days`, `transition_detection_window`, `house_device_power_sensors`, `main_entry_door` have no runtime reader. They move into the section like any other row; removal is a separate card (text pass §5).
- `hvac_cover_close_temp` is not a marker; it is on the HVAC settings form and is hot-applied (`OPTIONS_RELOAD_SUPPRESS_KEYS` via `_HVAC_TUNABLE_DISPATCH`, `__init__.py:7068`) and a live Number (`number.py:2712`).

### 13.2 Conditional dependents that are not markers (B-later)

| # | Controller → dependent | Step / flow | Shape | Controller level / dependent level / rule | Runtime readers | Access | Gated on controller | Mirror | Save effect | Release |
|---|---|---|---|---|---|---|---|---|---|---|
| B1 | `sleep_protection_enabled` → `sleep_bypass_motion_count` | sleep_protection, create + options | 3 / 1 | top / top / 1 | `automation.py:1318` | .get | Y — `can_bypass_sleep_mode` returns early unless `is_sleep_mode_active` (`:1312-1313`), which checks the toggle (`:1297`) | N | reload | B-later |
| B2 | `sleep_protection_enabled` → `sleep_block_covers` | same | 3 / 1 | top / top / 1 | `automation.py:2448`, `:2530`, `:2575`, `:2707` | .get | Y — every read is ANDed with `is_sleep_mode_active()` | N | reload | B-later |
| — | `sleep_protection_enabled` → start/end hour | same | — | — | `aggregation.py:885` `_is_sleep_hours` | .get | **N** (rev 2, unchanged) | — | — | stays visible |
| B3 | `cover_close_time_source eq fixed` → `cover_close_hour` | options_covers (+ create cover_behavior) | 1 / 3 | top / top / 1 | `automation.py:2739-2745` | .get | Y — read only on the non-sunset branch | N | reload | B-later |
| (13.1 #63) | `cover_close_time_source eq sunset` → `sunset_offset` | same | 1 / 3 | top / section→top / 1 | see 13.1 | .get | Y | N | reload | B-later (counted in 13.1) |
| — | `timed_close_enabled` → close source / hour / offset | same | — | — | `automation.py:2240` (cover open-intent, read by HVAC sun control) | — | **N** — DROPPED as controller (§4 rev 3) | — | — | stays visible |
| B5-B7 | `room_fan_mode not_eq off` → 3 fan-speed temps | climate, options | 1 | top / top / 1 | 13.1 rows 64-66 | .get | Y (`fan_owner` None → return, `automation.py:2789-2791`) | N | live-apply (_ROOM) | B-later (counted in 13.1) |
| B8 | `hvac_solar_gain_cover_enabled` → `hvac_cover_close_temp` | coordinator_hvac_settings | 1 | top / top / 1 | `hvac_covers.py:462` | attr | Y — `update` returns at `:428` first; the Number entity still shows it (accepted, §4) | N | live-apply (OPTIONS) | B-later |
| B9 | same → `hvac_cover_entities` | same | 1 | top / top / 1 | `hvac_covers.py:170-279` discovery, `:309-322` listeners, `:811-836` status | .get | Y for actuation (`:428`); discovery, listeners and the status display still read it (display only) | N | reload | B-later |
| B10-B12 | `dynamic_preset_enabled` (CM) → `dpm_relax_ceiling_mode`, `dpm_cool_day_relax_f`, `dpm_hot_day_tighten_f` | hvac_dynamic_preset | 1 | top / top or existing `advanced` section (:8701) — rule 2 on that section if all its fields depend; else rule 1 | `dynamic_preset.py:639-653`; display `sensor.py:10237-10250` | .get | Y — evaluation returns while the master is off (`energy.py:9300-9302`); the sensor still shows them (display) | N | reload | B-later |
| B13 (+13.1 sleep row) | `zone_dynamic_preset_enabled` → `zone_dynamic_preset_offset` (and the sleep marker row) | zone_dynamic_preset | 4 | top / top / 1 | `dynamic_preset.py:859`, `:940` | .get | Y — gate 1 returns at `:581`; `_build_overrides` (`:806`) has no caller | Y | reload (ZM) | B-later |
| (13.1 enrichment rows) | `perimeter_enrichment_enabled` → provider, model, max tokens, provider id | perimeter_alerting | 1 | top / section→top / 1 | `perimeter_enrichment.py:178-190` | .get | Y — after `_is_enabled_for_camera` (`:147-158`) | N | live-apply (INTEGRATION) | B-later (counted in 13.1) |
| — | `face_recognition_enabled` → `known_face_guests` | camera_census | — | — | `perimeter_alert.py:4977-4980`; `camera_census.py:3993`, `:4069` | .get | **N** — DROPPED (§4 rev 3) | — | — | stays visible |
| B19-B26 | `fan_recheck_enabled` → section `fan_recheck_advanced` (8 fields) | coordinator_presence | 1 | top / existing section / **2** | `presence_fan_recheck.py:1293-1335` `_timing_config`; `:588`, `:659` | .get | Y — `master_off` veto before use (`:537-542`, `:1221`); a PAUSED/COOLDOWN rehydrate after restart reads the window/cooldown once to finish (discharge, `:1785`, `:1846`) | N | reload (not in any allowlist) | B-later |
| B27 | `night_lights exists` → 5 night-light fields | devices, options | 1 | top / section→top / 1 | 13.1 rows 47-51 | .get | Y | N | reload | B-later (counted in 13.1) |

B-later dependent fields: 14 marker rows (13.1) + B1, B2, B3, B8, B9, B10-B12, B13, B19-B26 (17) = **31**.

### 13.3 D1 verify
- Every marker of all three forms has a row: 53 `_adv` + 8 `adv` + 5 `advanced_if_empty` + 1 literal = 67 (13.1), plus the `room_class` skip (row 68). `_caps_default` (§1 form 3) is the literal row 46 (`sensor_capabilities_json`).
- Every kept O-pair has reader rows (13.2). Dropped pairs carry the reader that breaks INV-2.

---

## 14. Text pass — ships with D3 (FORM-TEXT-PLAIN-PASS-1)

Operator, 2026-11-11: *"scan form text and prep usable and simple text and explainer labels where they don't exist. Coordinators are especially bad examples. I went into the Presence coordinator today and that part is a bit of a mess."*

The proposed text, with each description checked against its reader, is `docs/planning/AUDIT_form_text_plain_pass.md`. It ships **in the D3 release**, because D3 already edits the same `strings.json` + `translations/en.json` blocks (section labels, hint removal), and two string edits to one step in two releases would collide.

- **Scope in D3:** the audit's §3.1 (Presence, 18 coordinator rows + 12 room rows), §3.2 C1-C23, §3.3 Z1-Z10; the 22 dead strings removed. Energy step wording (C24) is deferred to the energy consumer audit (§10 non-goal, money path).
- **Highest-value fixes:** 39 fields that show raw keys today, and 8 helper texts that are wrong about what the code does (Presence geofence trackers, guest persistence, guest confidence, room guest threshold and guest-room flag, camera main entry door, cover close time).
- **Gate:** operator signs off the audit table before the builder edits strings (DPM label-pass rule).
- **Tests (added to D3):** `test_every_form_field_has_label`, `test_every_form_field_has_description` (allowlist), `test_form_text_denylist`, extended value parity, and the discriminating old-claim pins (audit §4).
- **Tier:** unchanged (2-DB for the joint cycle); review framing C adds the label-coverage test to its drill list (remove one label → the coverage test must go RED).
- Findings that need code (dead `geofence_entities`, dead `main_entry_door`, fan-check timing knobs reloading the CM entry, create-flow fan speeds only asked in Room-temperature mode) are cards, not part of this cycle (audit §5).
