# PLANNING — Config forms: collapsed Advanced sections (A) + fields shown only when relevant (B)

Card: **FORM-CONDITIONAL-FIELDS-1** (joint A+B; A's form half moved here from HA-2027-DEPRECATIONS-URA-1, whose device-registry half stays separate).
Status: plan **rev 2** (after two plan reviews, see §12). Tier: **2-DB, operator-set** (§9).

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

Sequencing: D0 → D1 → D2 → D3 → D4 → D5 on one branch. One release if D0 is green; otherwise D3 ships, D4+D5 wait for the harness.

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
1. Q1: phcc release for HA ≥ 2026.11? (PyPI, before dispatch.)
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
- Rewriting existing working sections; new fields or knobs; label rewrites beyond section titles and removing hint text; menu-trim changes; dual code paths for HA < 2026.11.

## 11. Plan completion tracking (fill at close)
| Item | Done / deferred | Why | Tracked at |
|---|---|---|---|
| D0 harness + gate tests | | | |
| D1 per-key triage | | | |
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
