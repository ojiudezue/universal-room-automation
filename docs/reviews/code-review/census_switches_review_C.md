# Review C — CENSUS-TOGGLES-TO-DEVICE-SWITCHES-1 (2026-08-18)

**Framing:** Tier 2-DB Review C — New surfaces + default-flip + TEST AUTHORITY.
**Cycle branch:** `feature/census-toggles-switches` @ `fb6f771a1`.
**Base:** `develop` (three-dot diff).
**Reviewer:** Oji Udezue.

## Verdict

**DO NOT SHIP** as-is. Two operator-visible label strings and one docstring
still say "Defaults to off" for the two toggles whose defaults have been
FLIPPED to True this cycle — the options-flow UI will actively lie to the
operator about what the switch will do until they touch it. The signal-refresh
plumbing (D2) is functionally correct in production, but three of the four
tests that claim to guard it are pure source-string grep and do not exercise
the real handler — a builder can silently delete the subscription and the
suite will stay green. Fix HIGH-1 / HIGH-2 (label truth) and MED-2 (real
D2 wiring drill) before deploy; the LOWs are safe to defer with follow-ups.

**One-line test-authority verdict:** ~9 of the 21 tests exercise real
runtime behavior (switch class instantiate → toggle → observe options +
dispatch); the remaining ~12 are AST-slice + source-anchor grep + a
mirrored-handler test that reimplements production logic in the test.
Structural, not behavioral, for D2 and D4. **Mixed authority, D2 hollow.**

---

## Findings

### HIGH-1 — Options-flow label lies: `face_recognition_enabled` "Defaults to off"

- **File:** `custom_components/universal_room_automation/strings.json:724` AND
  `custom_components/universal_room_automation/translations/en.json:724`.
- **What:** `data_description.face_recognition_enabled` reads:
  *"…Requires a camera integration that provides face recognition. **Defaults to
  off** — path validation works without it."*
- **Reality post-cycle:** `DEFAULT_FACE_RECOGNITION_ENABLED = True`
  (`const.py:99`); config-flow initializer uses it (`config_flow.py:2960`);
  first-boot merged value is True; presence + transit_validator now trust
  face-recog by default.
- **Failing scenario:** operator opens the URA options flow on the running
  house, reads "Defaults to off — path validation works without it," concludes
  face-recog is inert, deploys. In reality face-recog trust is live and
  presence attribution is happening. This is the exact class of UI-truth defect
  the "acceptance criteria must discriminate" corollary was written for
  (2026-08-16 census-double-count postmortem).
- **Bug class:** #8 doc/comment drift + user-visible surface mismatch.
- **Fix:** rewrite both descriptions to state the new default and the
  discharge behavior. Suggested (adjust wording, keep the mechanism note):
  *"When enabled, face recognition data from camera events is used to
  confirm the identity of persons during transit validation and presence
  trust. Requires a camera integration that provides face recognition.
  **Defaults to on**; the device switch `switch.ura_presence_face_matching`
  is the live kill-switch — toggling it takes effect within seconds
  without an integration reload."*

### HIGH-2 — Options-flow label lies: `egress_identity_enabled` "Defaults to off"

- **File:** `strings.json:730` AND `translations/en.json:730`.
- **What:** `data_description.egress_identity_enabled` reads:
  *"…Requires Face Recognition (above) to be working. **Defaults to off** —
  turn it on after you've confirmed faces are being recognized."*
- **Reality:** `DEFAULT_EGRESS_IDENTITY_ENABLED = True` (`const.py:87`);
  `camera_census._is_egress_identity_enabled` returns True on merged-default
  (`camera_census.py:2864–2870`); `person_id` on `ura_person_egress_event`
  is now populated by default, and the census `_egress_face_ids` set is
  no longer empty on first boot.
- **Failing scenario:** identical to HIGH-1 — operator sees the wrong
  default in the UI. The DOWNSTREAM effect is more consequential than
  HIGH-1: this feature was explicitly designed to "ship dormant" (see
  the retained rationale comment at `config_flow.py:2967–2972`). The
  strings.json language mirrors the plan's original dormant-ship intent
  — flipping the default without updating the strings inverts the
  operator's model of the system.
- **Bug class:** #8 doc/comment drift.
- **Fix:** rewrite both descriptions in the same shape as HIGH-1's fix,
  and update the ADJACENT config-flow comment at
  `config_flow.py:2967–2972` (`# Default OFF — feature ships dormant`)
  which is now the OPPOSITE of what the code does.

### HIGH-3 — Hollow D2 signal-refresh tests

- **File:** `quality/tests/test_census_device_switches.py`, tests
  `test_d2_transit_validator_registers_signal_handler`,
  `test_d2_presence_registers_signal_handler`,
  `test_d2_handler_effect_flips_cached_flag_without_reload`.
- **What:** the first two are pure `assert "…" in TV_SRC / PRESENCE_SRC`
  substring greps against the raw source text. The third
  (`test_d2_handler_effect_…`) declares a fresh function `_handler()`
  INSIDE the test that RE-IMPLEMENTS the production handler body, then
  calls that mirror — the production
  `_on_face_recognition_changed` from `transit_validator.py:358–383`
  and `_on_face_recog_changed` from `presence.py:2482–2499` are never
  invoked.
- **Failing scenario (mutation drill, no code needed to run):** delete
  the `async_dispatcher_connect(...)` block in `transit_validator.py`
  lines 355–369 entirely, leaving the surrounding try/except and a
  single-line comment `# SIGNAL_URA_FACE_RECOGNITION_CHANGED handler
  goes here` in place. The `in TV_SRC` grep for
  `"SIGNAL_URA_FACE_RECOGNITION_CHANGED"` still passes (comment matches).
  Assertion #3 (`self._face_recog_signal_unsub = async_dispatcher_connect(`)
  fails — but the reviewer/builder can defeat it trivially by keeping
  the assignment string in a comment. `test_d2_handler_effect_…` still
  passes because its `_handler()` never touches production. Net: real
  code is neutered, suite green. This is exactly the hollow-anchor
  pattern (`feedback_hollow_test_anchors`, Bug Class #62).
- **What is therefore UNTESTED:** that a `switch.async_turn_off()`
  actually re-reads `entry.options` in the LIVE TransitValidator or
  PresenceCoordinator instance. Presence trust and transit-validator
  face-attribution behavior on toggle depend entirely on prod being
  right; the suite proves nothing about them.
- **Bug class:** #62 hollow test anchor.
- **Fix:** rewrite `test_d2_handler_effect_…` to (a) construct a real
  TransitValidator (import + light-mock, same style as the switch
  class loader in this file), (b) call its `async_init()`, (c) verify
  its `_face_recognition_enabled` flips when the switch fires — via
  the actual dispatcher subscription, not a mirrored handler. Then
  do the same for PresenceCoordinator's subscription block. If the
  runtime cost of loading either class is too high for this test
  module, at minimum write a mutation-drill fixture: temporarily
  neuter the production `async_dispatcher_connect` line to a no-op,
  assert the new test fails, restore, assert green
  (`feedback_unrestored_mutation_drill_poisons_evidence`).

### MED-1 — `camera_census._is_egress_identity_enabled` docstring stale

- **File:** `camera_census.py:2858–2860`.
- **What:** docstring reads *"Read the EGRESS_IDENTITY_ENABLED kill switch
  from options (2026-08-18). **Default False (dormant)** — see const.py
  rationale."* Actual default is True (`DEFAULT_EGRESS_IDENTITY_ENABLED`,
  which this method now reads correctly).
- **Failing scenario:** next reader (Reviewer, LLM, or human) trusts the
  docstring and mis-reasons about the census fuse behavior on a fresh
  install. Same class as HIGH-1/2 but internal.
- **Bug class:** #8.
- **Fix:** update docstring: *"Default True (post-CENSUS-TOGGLES-TO-DEVICE-SWITCHES-1
  ship); operator kill-switch is `switch.ura_name_people_at_doors`."*

### MED-2 — Same-class hollow D4 tests (default-flip parity)

- **File:** `test_census_device_switches.py`, tests
  `test_d4_camera_census_reads_default_egress_identity`,
  `test_d4_config_flow_default_uses_new_constant`,
  `test_d4_transit_validator_uses_new_default_constant`,
  `test_d4_presence_uses_new_default_constant`.
- **What:** all four are `assert "DEFAULT_…" in <SRC>` string presence
  checks. A consumer could import `DEFAULT_FACE_RECOGNITION_ENABLED`,
  never use it, and hardcode `merged.get(CONF_..., False)` alongside —
  the tests all pass.
- **Failing scenario (specific):** if a future edit to `presence.py:2456`
  reverts to `merged.get(CONF_FACE_RECOGNITION_ENABLED, False)` (a
  merge-conflict resolution slip is the realistic vector), the
  presence-side default silently reverts to False on fresh install even
  though the switch-side and transit-validator-side defaults are True.
  Cached-consumer split-brain. `test_d4_presence_uses_new_default_constant`
  still passes because the string `DEFAULT_FACE_RECOGNITION_ENABLED` still
  appears in the import line at 2449.
- **Bug class:** #62 hollow test anchor.
- **Fix:** at minimum, replace each `in <SRC>` grep with a REAL
  read-and-assert: construct the consumer with an empty options dict,
  read its cached flag, assert True. For `config_flow.py` this means
  building the schema and reading the vol.Optional default; for
  `camera_census.py` this means calling `_is_egress_identity_enabled()`
  on a stubbed hass with an integration entry that has empty options.

### MED-3 — `_attr_name` + `_attr_translation_key` both set

- **File:** `switch.py:322–324` (both `_IntegrationOptionsSwitch`
  instantiations pass `fallback_name` → `self._attr_name`, plus
  `translation_key`).
- **What:** HA's entity-name resolution when
  `_attr_has_entity_name=True` gives precedence to `translation_key`
  IF the translation exists; if translations fail to load (locale
  missing, JSON parse error), `_attr_name` becomes the visible name.
  With both set, the intent isn't documented; if the translation ever
  drifts from the fallback, the operator sees two different names in
  two contexts.
- **Failing scenario:** low probability — depends on translations file
  failing to load or being edited to a different string.
- **Bug class:** minor HA-pattern hygiene.
- **Fix:** either drop `_attr_name` (rely on translation), or comment
  that it's an explicit fallback for translation-load failure.

### LOW-1 — Stale `config_flow.py` comment: `# Default OFF — feature ships dormant`

- **File:** `config_flow.py:2967–2972`.
- **What:** the multi-line comment above the `CONF_EGRESS_IDENTITY_ENABLED`
  `vol.Optional` still declares the feature as "ships dormant" and
  describes what happens "when False" as if False were the default.
- **Fix:** rewrite comment to match the new default and point to the
  device-switch kill path. Covered under HIGH-2's fix.

### LOW-2 — Docstring on `_IntegrationOptionsSwitch` describes the listener side of belt-and-suspenders but tests only prove the switch side

- **File:** `switch.py:290–299`.
- **What:** the docstring correctly documents that the dispatch fires
  from BOTH `switch._write` AND `_dispatch_integration_key_signals`.
  `test_d3_dual_fire_is_idempotent` simulates the listener's second
  fire by hand-calling `_DISPATCHER.async_dispatcher_send(...)` from
  the test, not by triggering the real `_async_update_listener`.
  Not a defect in production — but the dual-fire safety net is
  functionally UNTESTED.
- **Bug class:** #62 hollow anchor (secondary).
- **Fix:** either accept (the switch-side dispatch is proven, the
  listener side is proven separately in
  `test_reload_watchdog_hazard.py::test_egress_perimeter_keys_not_in_allowlist_v1`
  by construction) or add a test that mocks the update listener path.

### LOW-3 — `test_reload_watchdog_hazard.py` size-guard pins to 3 explicit keys

- **File:** `test_reload_watchdog_hazard.py:433–1038` (the assertion
  updated is `assert allow == {"camera_person_entities",
  "face_recognition_enabled", "egress_identity_enabled"}`).
- **What:** pinning the FULL SET rather than just the size is
  actually STRONGER than a count guard (a silent WRONG-key addition
  would fail the equality). Correct.
- **Not a bug.** Called out because the review brief asked whether
  the size-pin masks wrong-key additions — it doesn't, because it's
  a set-equality pin, not a `len(allow) == 3` pin. Acceptable.

### LOW-4 — Enhanced-census confirmed not exposed

- Verified via grep: `CONF_ENHANCED_CENSUS` appears only in
  `config_flow.py` (options-flow field) and `const.py`; no switch
  wiring, no orphaned import in `switch.py`. `test_enhanced_census_not_exposed_as_switch`
  guards this correctly via AST (real test — checks the actual
  `async_setup_entry` body, not a raw grep).

---

## What is actually tested (positive)

For the record, the following behaviors ARE genuinely covered by
runtime-exercising tests:

1. Const values and default flips (`test_d0_defaults_flipped_on`,
   `test_d1_signal_constant_defined`).
2. Allowlist frozenset shape (`test_d0_allowlist_contains_new_keys` +
   `test_d0_signal_table_has_face_recog_only` — AST-slice, but exec's
   real literals).
3. `_IntegrationOptionsSwitch` entity_id + unique_id pinning
   (`test_d3_*_pinned`).
4. Initial `is_on` reads True from empty options
   (`test_d3_initial_is_on_reads_default_true_when_options_unset`).
5. `async_turn_off / on` writes back to `entry.options` and `is_on`
   reflects it (`test_d3_toggle_writes_back_to_options`).
6. Face switch dispatches signal via
   `homeassistant.helpers.dispatcher.async_dispatcher_send`
   (`test_d3_face_toggle_fires_signal_from_switch`).
7. Egress switch does NOT dispatch a signal
   (`test_d3_egress_toggle_does_not_fire_any_signal`).
8. Switch does NOT call `async_reload`
   (`test_d3_switch_does_not_call_async_reload` — has a real
   behavioral assertion + a belt source-anchor).
9. Persistence-across-restart via re-instantiation on the same
   entry (`test_d5_switch_state_survives_restart` — real given that
   the switch is options-backed, not RestoreEntity).

## Suggested fix-up ordering

1. HIGH-1 + HIGH-2 + MED-1 + LOW-1 in one string-edit pass.
2. HIGH-3 rewrite: replace mirrored-handler test with a real
   TransitValidator subscription drill, and add a mutation-drill
   fixture that flips a production line and asserts the specific
   test fails.
3. MED-2 rewrite: replace the four D4 `in <SRC>` greps with
   read-and-assert-consumer-value tests.
4. Re-run the cycle test file. Then consider re-verifying the
   Review-D live-validation entry table shape (D2 in the
   README-of-record).

---

## Files consulted

- `custom_components/universal_room_automation/__init__.py`
  (rows 5917–6702 — allowlist + signal table + update listener).
- `custom_components/universal_room_automation/switch.py`
  (rows 33–378 — new switch class + wiring).
- `custom_components/universal_room_automation/const.py`
  (rows 2170–2205 — const defs + default flip).
- `custom_components/universal_room_automation/transit_validator.py`
  (rows 240–470 + 875–890 — cache read, subscribe, teardown).
- `custom_components/universal_room_automation/domain_coordinators/presence.py`
  (rows 2430–2515 — cache read + subscribe).
- `custom_components/universal_room_automation/camera_census.py`
  (rows 60–70 + 1880–1895 + 2855–2875 + 3650–3660 — fresh-read
  consumer sites).
- `custom_components/universal_room_automation/config_flow.py`
  (rows 340–366 + 2955–2985 — options-flow schema).
- `custom_components/universal_room_automation/strings.json` (705–732)
  and `translations/en.json` (mirror).
- `quality/tests/test_census_device_switches.py` (full file).
- `quality/tests/test_reload_watchdog_hazard.py` (rows 150–160 +
  425–450).
- `docs/planning/PLANNING_census_toggles_to_device_switches.md`
  (headers + tier + acceptance criteria).
