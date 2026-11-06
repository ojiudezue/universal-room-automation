# Plan review 2 — FORM-CONDITIONAL-FIELDS-1 (A sections + B visible=)

Plan: `docs/planning/PLANNING_config_forms_sections_and_conditional_fields.md` (uncommitted, develop).
Framing 2: adversarial build-prediction ("what will the builder get wrong?"). Completeness/enumeration is review 1's lane.
HVAC/presence docs: not read. This plan changes form layout only; the O14/O15/O17 consumer checks are D1 work and need the HVAC doc then (the plan says so in §4).

Verified against installed HA 2026.2.3 (`.venv-ha/.../homeassistant/data_entry_flow.py`) and URA `config_flow.py` on develop. **Not verified:** anything about 2026.11 `visible=` behavior beyond what the plan quotes from the docs. I did not re-fetch contributors.home-assistant.io, so the doc quotes in §1 are taken as given.

## Verdict: FIX-PLAN

There are 2 HIGH ordering/semantics gaps and 2 HIGH contradictions, and the builder will get each of them wrong. All are fixable in the plan text.

---

## HIGH

### H1. Create path: the order of flatten, backfill and merge is not specified, and `_absent_field_defaults` is not specified to descend into sections
Evidence: URA's own comment at `config_flow.py:5559-5561` says the section key can be missing from `user_input` when the operator never expands it. The section marker is `vol.Optional("<name>")` with no default (`:3522`, `:5685`, `:14180`). When the key is absent, voluptuous never runs the section's inner schema, so **none of the inner defaults are applied**. The old `_hidden_advanced_defaults` (`:178-200`) walks only top-level markers.
Build prediction: the builder renames `_hidden_advanced_defaults`, keeps its top-level walk, and moves Advanced fields into a section. On a new room, a never-expanded Advanced section then stores no Advanced keys, while today (Advanced shown) it stores their defaults. That breaks INV-1 on every create step, and the round-trip test (Options-only by design, see H4) will not catch it.
Unverified: whether the 2026.11 frontend always sends the section dict. Build the plan so the answer does not matter.
Plan fix: state the order for each path explicitly:
- **Create:** `flat = _flatten_sections(user_input, schema)`, then `flat = {**_absent_field_defaults(schema, flat), **flat}`. The helper walks into `section` values (reuse the `_collect_schema_defaults` walk at `:3939`) and fills every key that is missing from `flat`.
- **Options:** `flat = _flatten_sections(...)`, then `{**options, **flat}`. **No backfill.** If Options backfilled, it would reset hidden keys whose marker default is a factory default and not `_get_current`.
Add a test: create, submit `{}` for the section key (absent), and assert that every inner default is stored.

### H2. The "same section level" rule contradicts three §4 rows
§4's rule says the controller and its dependents must sit at the same level, and cross-section conditions are unsupported (Q2). But:
- `devices`: night-light colour/brightness are Advanced and go into the section, while their controller (night lights `exists`) is an Everyday field. That is a cross-section condition, even though the row says "(same section)".
- `climate` O4: `CONF_FAN_SPEED_*_TEMP` are listed as Advanced fields (`_adv` at `:14575-14577`) and also as conditional on `CONF_ROOM_FAN_MODE`, which is top-level. The rule also says "every `_adv` field → section *unless it has a controlling toggle*", so the same field gets two placements.
- `coordinator_presence` O17: the plan says "inside `fan_recheck_advanced`". The code has `CONF_FAN_RECHECK_ENABLED` at **top level** (`:5675-5685`) and the dependents in the section. That is cross-section today.
Build prediction: the builder puts `visible=` on fields inside a section that reference a top-level field. Per the quoted docs, conditions inside a section look only at that section's fields, so the condition reads the controller as empty: the dependents are **always hidden** and their values are never submitted again.
Plan fix: add a precedence rule: **a field with a controller lives at the controller's level (Everyday), never in the Advanced section**, OR move the controller into the section with its dependents. Pick one per row in D1 and correct the three rows. Make Q2 a D0 gate item with an explicit fallback (no `visible=` for cross-level pairs).

### H3. "Replace-shape steps get the merge" is wrong by construction for steps that rely on dropping keys
§3.2 says any Replace step that does not start from `self._config_entry.options` "gets the merge". Replace steps (`:9024`, `:9857`, `:10333`, `:8555`) may build from scratch precisely so that a cleared field (an EntitySelector or a list emptied in the UI, which HA omits from `user_input`) disappears. A blanket merge makes clearing impossible. That is a new sticky-value bug (Bug Class #53 inverted).
Plan fix: for Replace steps, carry forward **only the keys that `visible=` hid on this submit**: the dependents whose controller evaluates hidden. Do not add a blanket `{**options}`. D1 records each Replace step's clear-semantics before choosing.

### H4. The round-trip harness (D2) emulates the wrong prefill and cannot go RED on the main failure modes
URA prefills Options forms through `default=self._get_current(...)` (e.g. `:14159-14175`, `:5573`), not `suggested_value`. `add_suggested_values_to_schema` recurses into a section **only if the section key is in `suggested_values`** (`data_entry_flow.py:670-681`), and saved options are flat, so it never would. "Submits the rendered suggested values unchanged" would therefore submit almost nothing. Then `{**options, **{}}` equals options trivially, so the test is green no matter what flatten does.
Plan fix: specify the harness precisely:
1. Build `user_input` from each marker's **default or suggested_value**, walking sections.
2. **Nest** section fields under their section key, as the frontend does. A builder who forgets `_flatten_sections` then produces a top-level `options["advanced"]` dict, and the test catches it.
3. **Omit** fields whose `visible=` evaluates false, as HA does.
4. Run the harness on create as well as Options (H1).
Also warn builders not to "simplify" prefill by switching to `add_suggested_values_to_schema(schema, options)`. That path leaves section fields unfilled (see the cited lines).

## MEDIUM

### M1. `_flatten_sections` behavior on a collision in production is unstated
"Refuses (raises in tests)" leaves the production behavior open: raise, log, or prefer one side? A raise inside a submit handler shows an "Unknown error" with nothing saved. Plan fix: in production, collisions are impossible by construction. Assert at schema-build time with a unit test that walks every step's schema for section-key vs field-key overlap and inner vs outer duplicates. The runtime helper then just merges with section-wins and logs at debug. Also specify that it ignores section keys that are absent or not a dict (`:8839-8845` already tolerates nested-or-flat).

### M2. Mixing marker types and `copy.copy(key)` under 2026.11 are D0 questions but not gate criteria
Q3 and Q4 are listed as open but are not gates. In 2026.2.3, `add_suggested_values_to_schema` replaces `new_key.description` wholesale with `{"suggested_value": ...}` (`:688-689`). If 2026.11 keeps `visible` in `description`, every suggested-value call **strips the condition**. If it keeps it in a separate attribute, it survives. I cannot verify this pre-upgrade because the class does not exist in 2026.2.3. Plan fix: make D0 verify these with a real test before D3 starts: (a) `visible` survives `add_suggested_values_to_schema`, (b) `default=` and `description` survive on `data_entry_flow.Optional`, (c) a mixed `vol.Optional`/`data_entry_flow.Optional` schema serializes through `voluptuous_serialize` with the condition present, (d) Q2 cross-section, (e) Q5 for EntitySelector `exists` and SelectSelector `eq`. If any fails, the matching §4 rows fall back to section-only.

### M3. The D0 harness has no stated fallback when the phcc pin route lags
§0 rejects fakes, which is correct. But route (b) ("phcc version closest below it" + HA 2026.11) is a known-incompatible pairing. Builders will hit fixture errors and drift toward mocks. Plan fix: state that if neither (a) nor (b) yields a green name-diff, **D4 does not build**. D3 (sections only) can ship on 2026.2.3, because `section` exists there and the 17 existing sections are already harness-tested. Q1 should be answered before the build is dispatched (it is a single PyPI check).

### M4. Is the hacs.json floor tied to the right deliverable?
The 2026.11 floor is only needed for D4 (`visible=`). D3 works on every supported HA. With the floor, **every** future URA release, hotfixes included, becomes uninstallable on any home below 2026.11. That includes Wigton, which runs an older URA (`kanban.data.yaml:32130`). Its HA version is unknown from here, and its re-enable is parked (`:32386`). Plan fix: note the consequence in the README and on the Wigton card. If D4 is deferred per M3, ship D3 without the floor. The "HACS → Marketplace migration" in the brief is **unverified**: I found nothing about it in the plan or card text I grepped, so I can't say how a floor behaves there.

### M5. INV-3 as a test is a source grep (Bug Class #62)
`test_no_show_advanced_options_readers` is fine as a lint, but it proves nothing about behavior. Plan fix: name it as a lint, and add a behavioral test that runs one restructured step under a `FlowHandler` whose `show_advanced_options` is False and asserts the full field set renders. That is the 2027.6 condition.

## LOW

- L1. §4 "One section per step at most, named `advanced` unless the step already has a named section". `climate` already has `humidity_fan_advanced` **and** `climate_backstop` (`:3522`, `:3552`). Say which one receives new fields, or allow a second section.
- L2. INV-1's "no key appears nested under a section key" needs a precise check: assert `set(stored) & set(section_names) == ∅`. "Diff-equal" alone passes if the old flat key also kept its value (the merge masks it).
- L3. D3 deletes `_hidden_advanced_defaults` and renames it in D2. Say it is a rename of the same symbol so the 3 callers (`:1597`, `:2382`, `:2511`) move together and none is left on a shim.

## Simplicity
§6 is sound: dropping the `_adv` promotion and not migrating working sections are good calls. One more simplification follows from H2: any field with a controller stays Everyday. That removes most cross-level questions, and the cost is a slightly longer top-level form only while the controller is on.

## Mutation drills for Review C (build review)
Run each against the cycle's form test files only, and confirm a named test goes RED:
1. Remove the `_flatten_sections` call in one restructured Options step (e.g. lighting behaviour). Expect a round-trip test failure on the nested `advanced` key.
2. Remove it in one create step. Expect the create round-trip test to fail.
3. Make `_absent_field_defaults` stop descending into sections. Expect the H1 create test to fail.
4. Replace `{**options, **flat}` with `flat` in one step that has a `visible=` pair. Expect `test_visible_<pair>_hidden_keeps_saved` to fail.
5. Drop the controller check in one runtime reader per B pair (sleep-protection hours, timed close, fan temps). Expect `test_<reader>_ignores_dependent_when_controller_off` to fail.
6. Change one `visible=` operator (`eq` to `not_eq`). This is only meaningful if the harness emulates hidden-omission (H4.3). A GREEN result means the harness ignores `visible`.
7. Add `{**options}` to a Replace step (H3). Expect the clear-a-field test to fail.
