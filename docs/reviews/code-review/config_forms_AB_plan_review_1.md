# Plan review 1 (COMPLETENESS) — FORM-CONDITIONAL-FIELDS-1

Plan: `docs/planning/PLANNING_config_forms_sections_and_conditional_fields.md` (uncommitted, develop @ bf6761c3).
Reviewer framing: completeness. Every enumeration below was re-run with grep on develop. `config_flow.py` = `custom_components/universal_room_automation/config_flow.py` (15,755 lines).
Read in full: `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` (incl. §10 ledger), the phase-2 amendment of `PLANNING_onboarding_simplify_phase2.md` (:189-281). Fetched: contributors.home-assistant.io/core/integrations/flow-steps/. HA source read: `.venv-ha/.../data_entry_flow.py:644-685, 915-940` (2026.2.3).

**Verdict: FIX-PLAN** (3 HIGH, 5 MEDIUM, 3 LOW). The direction is right and the reader count holds. But the save-path model is missing one shape, INV-1 cannot catch lost edits, and the §4 table breaks the plan's own same-level rule.

## Enumeration diff (task 1)

| Item | Plan | Re-grep | Delta |
|---|---|---|---|
| Direct `show_advanced_options` property reads | 5 | 5 (:1248, :4611, :13568, :13763, :14216) | OK |
| Context shim | 1 (:4646) | 1 | OK |
| `_show_adv()` callers | 19 | 21 hits = 19 callers + 2 defs (:1245, :4609) | OK |
| `_filter_advanced` | 16 + defs | 23 hits incl. :4390 (comment), :169/:1255/:4617 defs | OK |
| Filter-only `add_suggested_values_to_schema(…, {})` | 2 | 2 (:13760, :14209). These are the only non-comment calls in the file | OK |
| Hint helpers / callers | 3 / 17 | also :11030 (`description_placeholders={"advanced_hint": ""}`), :13770, :14223 | see L1 |
| `_hidden_advanced_defaults` | 1 + 3 | 1 + 3 | OK |
| `_adv(` / literal `{"advanced": True}` | ~70 + 11 | 75 / 11 | plus a third form, see H3 |
| Tests | 38 refs / 9 files | **50 refs / 11 files**: adds `test_night_light_rule_options_flow.py:112`, `test_room_menu_trim.py:252-253` (asserts `{advanced_hint}` is in the `options_covers` / `climate` strings) | M1 |
| Other files | config_flow only | `strings.json` + `translations/en.json` (15 `advanced_hint` placeholders; `"advanced": "Advanced (rarely change)"` section label at strings.json:1337) | covered by D3 text; name the files |

## HIGH

**H1 — The zone save path is missing from §3, and so is the sibling mirror.** Zone steps (`zone_rooms`, `zone_hvac`, `zone_energy`, `zone_media`, and others) do not use any of the three shapes. They build a payload from top-level `user_input` keys and call `_auto_mirror_to_siblings` (`config_flow.py:4140`; callers :11105, 11291, 11404, 11534, 11611, 11662, 11782). That helper writes `options["zones"][name].update(payload)` and copies `MIRROR_KEYS_*` to every house zone on the same thermostat (:4209-4277). This is the HVAC-zone ≠ house-zone fan-out from STATE_OF_PLAY / the architecture map. Two concrete failures:
- `zone_rooms` builds `CONF_ZONE_DESCRIPTION: user_input.get(CONF_ZONE_DESCRIPTION, current_zone_desc)` (:11096-11099). Move the description into an `advanced` section and the top-level `.get` misses. An edit then falls back to the stored value: the user's change is silently thrown away.
- A section dict that is not flattened lands as `zones[name]["advanced"] = {...}`, and the mirror (filtered on key names) never sends the moved keys to siblings. Sibling zones then drift on per-thermostat keys, for example the Zone → Thermostat min-gap field, which is "mirrored to zones sharing the thermostat" (STATE_OF_PLAY §header W1-C P2).

**Fix:** add shape 4, "ZM nested + mirror", to §3. D1 classifies each zone step against it. `_flatten_sections` must run before any payload is built. Add a mirror round-trip test: edit a moved mirror key on zone A and assert sibling B gets it.

**H2 — INV-1 and the D3 test only check no-edit round-trips, so a lost edit passes.** INV-1 is falsified only when a key "disappears, changes value, or appears nested" after an unedited save. The H1 failure (an edit dropped because a hand-built payload reads the flat key) stores identical options, so INV-1 holds and `test_forms_round_trip_*` stays green. The same applies to every step with a hand-built payload or explicit `user_input.get(KEY, current)` reads. Many Options steps also pop and re-shape `user_input` before the merge (e.g. climate :14376-14392).

**Fix:** add INV-1b (edit propagation). For every restructured step, changing ONE field inside the section to a non-default value stores exactly that value at the flat key, with no other key changed, and with the sibling mirror applied for zone mirror keys. Parametrize it over every moved key. This is the discriminating observation: a missing flatten or a top-level `.get` shows as the old value.

**H3 — The §4 conditional column breaks §4's own same-level rule, and O4 is not a same-form pair today.**
- **O4 (climate).** The fan-speed temperatures are on a different STEP on the create path: `climate` routes to `async_step_fan_speeds` (:3437-3438, :3578). `visible=` only works within one step ("compares the value of another field of the same step", flow-steps doc). So O4 means merging `fan_speeds` into `climate`, deleting that step and its strings, and changing the create sequence. The plan does not say any of this.
- §4 also puts the temperatures in the Advanced section (they are `_adv` today) while their controller `CONF_ROOM_FAN_MODE` is top-level. That is exactly the cross-section case §4 and §8 Q2 rule out.
- The same conflict is likely in O3 (`CONF_SUNSET_OFFSET` is Advanced; `CONF_TIMED_CLOSE_ENABLED` is not), the `devices` night-light colour/brightness rows (the controller `night_lights` is probably Everyday), and O16. Only the lighting row admits the conflict ("only if same level").
- **"Same as today" is false for O4.** D4's "create path with controller off stores the dependents' defaults (same as today)" does not hold. Today a create with Fan Mode ≠ Room temperature skips `fan_speeds`, so NO temperature keys are stored. `_absent_field_defaults` would ADD them, which changes stored data on create (an INV-1 break on the create path).
- **A third value-dependent Advanced marker is missing.** `advanced_if_empty` in the create `sensors` / `devices` builders (:2446-2468, :2532-2534; e.g. `CONF_MMWAVE_SENSORS`, `CONF_DOOR_SENSORS`, `CONF_WATER_LEAK_SENSOR`, `CONF_AUTO_SWITCHES`) and `_caps_default` at :13455. The plan neither counts nor triages it. Its form `desc["advanced"] = True` (:2458) also gets past the INV-3 grep. See M2.

**Fix:** D1 gets a mandatory column "controller level / dependent level / resolution". The resolution is one of: (a) the dependent stays at the controller's level (not collapsed), (b) the controller moves into the section, or (c) section-level `visible` on a section that holds only dependents. No row may stay ambiguous. O4 gets an explicit step-merge sub-deliverable, and either drops the create-backfill claim or states the stored-key change and gets an operator ruling. Add `advanced_if_empty` and `_caps_default` to §1 and §4.

## MEDIUM

**M1 — The test inventory misses 2 files and 12 refs.** `test_night_light_rule_options_flow.py` and `test_room_menu_trim.py` both break when D3 removes `advanced_hint` from strings. **Fix:** update the §1 row to 50 refs / 11 files and list both in D3.

**M2 — The INV-3 grep is not falsifiable for all marker shapes.** The pattern `"advanced": True\|_adv(…` misses `desc["advanced"] = True` (:2458), and a `description={**x, "advanced": True}` form would also slip past it. **Fix:** state INV-3 as a test that walks every built schema (create and Options, all four families, sections included) and asserts that no marker `description` has a truthy `advanced` key. Keep the grep as a secondary check.

**M3 — `_absent_field_defaults` is under-specified.** Today's `_hidden_advanced_defaults` walks only top-level markers (:186-198). Hidden-in-section fields need recursion, and the backfilled keys must land flat. "Absent from user_input" is also not the same as "hidden": a visible Optional with no default that the user leaves empty is also absent. The phase-1 v5.37.1 clear-field hazard is commented at :2440-2445. **Fix:** define the helper as "markers whose `visible` evaluates False against the submitted values, recursing into sections". Test a cleared visible field to prove it is NOT backfilled.

**M4 — INV-2 has a known breaker the plan did not find, and INV-2 is mostly pre-existing.** Spot-check of 7 dependents:

| Dependent | Reader | Gated on controller? |
|---|---|---|
| `sleep_start_hour` / `sleep_end_hour` | `aggregation.py:885-903` `_is_sleep_hours`: reads the FIRST room's hours and ignores `CONF_SLEEP_PROTECTION_ENABLED`, and it feeds `is_sleep_hours` (:1743, :1748) | **N** |
| `sleep_bypass_motion_count` | `automation.py:1313`, behind `is_sleep_mode_active()` | Y (verify that `is_sleep_mode_active` reads the toggle) |
| `sleep_block_covers` | `automation.py:2443, 2525, 2570, 2702`, ANDed with `is_sleep_mode_active()` | Y (same caveat) |
| `close_time` | `automation.py:2769`, called at :2745 after the `CONF_TIMED_CLOSE_ENABLED` return at :2656 | Y |
| `energy_load_shedding_threshold_kw` | `energy.py:831`, cached next to `_load_shedding_enabled` | likely Y; verify at use site |
| `known_face_guests` | `camera_census.py:3782` | unverified |
| `hvac_cover_close_temp` | `__init__.py:7034` hot-apply map, `number.py:2712` | unverified; also a live Number entity (below) |

Two further points:
- **The update listener is a consumer.** `__init__.py:7034` (reload-suppression / hot-apply allowlist) and `__init__.py:7694-7729` (merged-per-lookup lists) consume option diffs. A nested section key that is not on the allowlist would trigger a full reload, which is the parent-reload watchdog hazard in memory. §3 must name these as consumers.
- **INV-2 is mostly pre-existing.** These values are stored and readable today with the controller off. B only hides them. So INV-2 is a pre-existing gap that B makes invisible to the operator, not a new risk.

**Fix:** D1 records `_is_sleep_hours` as an N row and decides: gate it on the room's toggle (a behaviour change, so it needs a ruling) or drop O2's hour fields from `visible`. Restate INV-2 so it covers only readers whose behaviour would differ from today. Add the update-listener allowlist to §3's consumer list and to the D3 test (no section key ever reaches `options`).

**M5 — The energy rows O9-O13 contradict the prior plan's recommendation, and they are a money path.** Amendment :278-280 says: *"take O9-O13 (energy) as a separate cycle after a consumer audit, because a missed parent gate on an energy knob is a money path."* The plan pulls them in and only drops O10. Several sit inside the existing `baec` / `inclement` / `cloud_verification` sections, which the plan says it will not rewrite (§6/§10). That makes them doubly constrained. **Fix:** move O9-O13 to a parked follow-up with a consumer-audit trigger, or justify the reversal explicitly. Simplicity argues for parking: the operator's value is in room/zone/house forms.

## LOW

**L1 — The hint-caller list misses** :11030 (`description_placeholders={"advanced_hint": ""}`) and the placeholder assignments at :13770 and :14223. **Fix:** add them to the §1 table.

**L2 — Name the section key, and note the existing one.** A section key `advanced` already exists in `_build_hvac_dynamic_preset_schema` (:8701, flattened at :8502). The §4 "named `advanced`" rule is fine. D2's collision check must allow a step whose existing section is already called `advanced`, so it does not raise in that legitimate case. Also, `options["advanced"]` absent is part of INV-1. **Fix:** one sentence in D2.

**L3 — The HVAC rows check out against STATE_OF_PLAY, with one omission.** I read the doc completely. O14 (`hvac_solar_gain_cover_enabled` → `hvac_cover_close_temp`) and O15 (dynamic preset) touch no write site in §4.1/§4.2 and assert nothing in the §10 ledger. However:
- `hvac_cover_close_temp` is also a live Number entity (`number.py:2712`) and is hot-applied (`__init__.py:7034`). Hiding the form field does not hide the knob, so the form and the dashboard can disagree about relevance.
- The arrester → "carrier reload/stale knobs" pair: since W1-C P2, freshness/reload are adapter verbs (`freshness_row` / `remediate_stale`, STATE_OF_PLAY §header P2 bullet "Freshness / reload are adapter verbs"). So the dependency is "Carrier profile", not "arrester enabled". Disabling the arrester puts it in passive mode (gate (d), §9e) and does not stop the freshness test. Hiding those knobs on arrester-off would be wrong.

**Fix:** drop the arrester → carrier-knob pair, or have D1 prove the reader gating. Note the Number-entity duplication.

## External API claims (task 7)
Verified against flow-steps: the deprecation text, "Sections cannot be nested", the nested-dict input, section-level `visible`, the operators list, the `data_entry_flow` import path, hidden = "left out of user_input, default included", "inside a section, conditions look at the fields of that section", and that the doc names no selectors. HA source 2026.2.3 also matches the plan's quotes:
- the property reads `context` (:644-647);
- the advanced filter applies to top-level markers only and recurses into a section only when its key is in the suggested values (:658-680);
- `section.__call__` validates the nested dict (:915-940).

No unsupported claim found. The open questions Q2-Q5 are correctly marked unverified.

## Parked triggers (task 5)
- Phase-2 amendment: O1 is excluded (fine). O5 is parked with a trigger (fine). O6/O7 are folded in (fine). Quiet-hours and notifications pairs are "not surveyed" in the amendment, and D1 should say whether it absorbs them.
- The O9-O13 separate-cycle recommendation was overridden; see M5.
- `AUDIT_device_tree_vs_ha_2026_11_child_devices.md` stays on HA-2027-DEPRECATIONS-URA-1 (correct).

## Judgement
- **Invariants:** INV-1 is falsifiable but too weak (H2). INV-2 is falsifiable, and one breaker already exists (M4). INV-3 needs the schema-walk form (M2).
- **Acceptance criteria:** testable, apart from H2's missing edit case.
- **Scope vs simplicity:** sections (A) plus room/house conditionals serve the goal. The energy rows (M5), the O4 step merge (H3) and the arrester/carrier pair (L3) add risk for little visible simplicity.

Must-fix before build: H1, H2, H3, M1-M5.
