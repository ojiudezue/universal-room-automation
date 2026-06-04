# PLANNING v4.7.4 — DPM UI Simplification + Translation Fix

**Status:** Plan ready for build (locked after v4.7.3.1 ships)
**Tier:** Tier 2 (two parallel staff-engineer reviews, different framings)
**Predecessor:** v4.7.3.1 (HVAC bespoke switches restore hotfix)
**Filed:** 2026-05-28 after user screenshot evidence of structural translation bug on Surface 1
**Recall:** "Plan v4.7.4 — DPM UI simplification"

---

## 1. Goal + Why

**Goal:** Make the DPM control surface usable. Today (post-v4.7.3) the user sees ~150 knobs across 3 forms; Surface 1's per-zone fields render as raw underscored keys like `Back Hallway__zone_dynamic_preset_offset` because HA's translation system can't match runtime-prefixed schema field names. The form is functionally broken on Surface 1 and overwhelming everywhere.

**Root translation issue:** Surface 1 (`async_step_hvac_dynamic_preset`) iterates N canonical zones and prefixes each zone's fields with `<zone_name>__` to avoid voluptuous duplicate-key errors. HA's translation system looks up by exact field key — there's no entry for `Back Hallway__zone_dynamic_preset_enabled` (zone names are user data; not enumerable at translation-build time). HA falls back to displaying the raw key.

**Conclusion:** Surface 1's per-zone rendering is unfixable in its current shape. No amount of translation work helps. The fix is to **stop rendering per-zone fields on Surface 1** and route all per-zone editing through Surface 2 (Zone Manager), where translation keys match unmodified CONF names.

**Why now:** v4.7.3.1 closes the AC Ramp Down restore bug. The next user-blocking issue is the sprawl + translation bug — without fixing it, the DPM feature ships but is functionally unusable for normal users.

---

## 2. Tier Classification

**Tier 2.** Triggers checked against Tier 2-DB:

| Trigger | Hit? |
|---|---|
| Touches `database.py` DAO | No |
| Migrates ≥3 callers to a new DAO | No |
| Changes dispatched payload shape | No |
| Adds behavioral test infra against real schemas | No |
| Followed by planned schema migration | No |

Two parallel reviewers per CLAUDE.md Tier 2 protocol. Framings disjoint per §9.

---

## 3. Discovery — Read Before Build

| File | Lines | Why |
|---|---|---|
| `config_flow.py` | 3675-3939 (`async_step_hvac_dynamic_preset` + `_build_hvac_dynamic_preset_schema`) | Surface 1. D1 strips per-zone loop here. |
| `config_flow.py` | 5004-5274 (`async_step_zone_dynamic_preset` + `_build_dynamic_preset_schema`) | Surface 2. D3 conditional rendering happens here. |
| `config_flow.py` | 3293-3304 (`async_step_coordinator_hvac` menu) | Verify menu wiring stays clean after D1 strips. |
| `config_flow.py` | 4069 area (`async_step_hvac_baseline_presets`) | D4 UX polish (season sections + reset button). |
| `strings.json` + `translations/en.json` | (entire) | Audit existing translations for Surface 1 / Surface 2 / Baseline. D5 source-contract test verifies coverage. |
| `domain_coordinators/dynamic_preset.py` | (entire) | Verify the runtime evaluator doesn't read prefixed CONFs (it shouldn't — it reads per-zone from ZM entry options). |
| HA dev docs on `section` blocks | https://developers.home-assistant.io/docs/data_entry_flow_index/#section | Pattern for D2 advanced collapsing. |
| HA dev docs on conditional schemas | various | Pattern for D3 conditional rendering (typically achieved via schema returned by a render fn that branches on user_input state). |

---

## 4. Deliverables

### D1 — Strip Surface 1 to house-wide only

**Description:** Remove the per-zone iteration from `async_step_hvac_dynamic_preset`. Surface 1 becomes the global settings page only.

**Field set (post-D1):**
- Master enable toggle (mirrors `EnergyCoordinator._dynamic_preset_enabled`)
- Bucket boundaries: `CONF_DYNAMIC_PRESET_DELTA_COOL_MAX`, `_MILD_MAX`, `_HOT_MAX`
- Dwell minutes
- Hysteresis °F

**Total fields visible:** 6 (will become 1 by default after D2's Advanced collapsing).

**Per-zone editing:** routed exclusively to Surface 2 (Zone Manager → zone → 🌤️ Dynamic Preset). Add a help text on Surface 1's description that points users there: "Per-zone settings live under Zone Manager → [zone] → Dynamic Preset."

**Sync invariant simplification:**
- v4.7.2's `_validate_dynamic_preset_input` helper still exists for shared house-wide validation.
- v4.7.2's `test_v472_dpm_storage_roundtrip_both_surfaces` test (which asserted Surface 1 + Surface 2 produce identical per-zone state) becomes IRRELEVANT — DROP it. Replace with a simpler test asserting Surface 1 writes house-wide CONFs to CM `entry.options` only.

**Acceptance criteria:**
- **Verify:** Surface 1 renders with at most 6 visible fields (master enable + 5 house-wide).
- **Verify:** NO per-zone fields visible on Surface 1.
- **Verify:** All Surface 1 fields render with clean labels + helper text from translations.
- **Verify:** Surface 1's description mentions where per-zone editing lives.
- **Test:** `test_v474_d1_surface1_has_no_per_zone_fields` — schema contains no field whose key contains `__` prefix.
- **Test:** `test_v474_d1_surface1_field_count_is_6` — exactly 6 fields after schema build.
- **Test:** `test_v474_d1_surface1_field_keys_match_translations` — every field key has a matching entry in `data` block of `translations/en.json`.
- **Test:** `test_v474_d1_drop_sync_roundtrip_test` — assert the obsolete `test_v472_dpm_storage_roundtrip_both_surfaces` is deleted.
- **Live:** Open HVAC Coordinator → Configure → Dynamic Preset. See 1 visible knob ("Enable Dynamic Preset"); expand Advanced to see the 5 house-wide tunables. NO zone names visible.

### D2 — Advanced section collapsing on Surface 1

**Description:** Wrap bucket boundaries + dwell + hysteresis behind HA's `section` block with `{"collapsed": True}` flag.

**Visible by default:** Master enable toggle only.

**On expand:** "Advanced (rarely change)" section reveals 5 tuning knobs.

**Files touched:**
- `config_flow.py:async_step_hvac_dynamic_preset` — wrap subset of schema in `section` block.
- `strings.json` + `translations/en.json` — add `section.advanced` title + description.

**Acceptance criteria:**
- **Verify:** On first open of Surface 1, only "Enable Dynamic Preset" is visible.
- **Verify:** "Advanced (rarely change)" expander is closed by default.
- **Verify:** Expanding reveals exactly 5 fields (bucket boundaries + dwell + hysteresis).
- **Test:** `test_v474_d2_advanced_section_marked_collapsed`
- **Test:** `test_v474_d2_advanced_section_contains_5_fields`
- **Test:** `test_v474_d2_strings_have_advanced_title`
- **Live:** Open Surface 1, confirm single-knob default visibility.

### D3 — Conditional rendering on Surface 2

**Description:** Reduce Surface 2's per-zone visible knob count from 18 → 3 by hiding cells behind opt-in checkboxes.

**Default-visible fields (3):**
1. `zone_dynamic_preset_enabled` (master toggle for this zone)
2. `zone_dynamic_preset_offset` (offset °F)
3. `zone_dynamic_preset_reset_offset_guest` (reset under guest)

**Conditionally rendered:**
- `zone_dynamic_preset_sleep_enabled` checkbox always visible. When checked, render 8 sleep-preset cells (4 buckets × cool_low + cool_high).
- NEW field `zone_dynamic_preset_customize_buckets` checkbox always visible. When checked, render 8 home-preset bucket cells. When unchecked, the source uses computed defaults derived from baseline + offset; placeholder text shows the computed values.

**Implementation pattern:** HA options-flow steps can't naturally conditionally render different schemas in one round-trip — but we can split into 2 sub-steps:
- Sub-step 1: render the 3 default fields + 2 customization checkboxes.
- Sub-step 2: if either customization checkbox is set, render the relevant cells and submit.

**Alternative pattern (simpler if HA supports it):** use `section` blocks with `{"collapsed": True}` for the bucket cells + sleep cells. User clicks expander to see + edit.

**Builder picks** the implementation pattern; report which in the build PR. Section-collapse is the leaner option.

**Files touched:**
- `config_flow.py:async_step_zone_dynamic_preset` and `_build_dynamic_preset_schema`.
- New CONF: `CONF_ZONE_DYNAMIC_PRESET_CUSTOMIZE_BUCKETS` (default False).
- `domain_coordinators/dynamic_preset.py` — handle the case where `customize_buckets=False`: derive bucket cell values from baseline + offset at runtime instead of reading from entry.options.
- `strings.json` + `translations/en.json` — labels for the new checkbox + advanced section titles.

**Acceptance criteria:**
- **Verify:** Surface 2 renders 3 fields by default (enable + offset + reset-guest) + 2 expander/checkbox controls (customize buckets + sleep).
- **Verify:** Unchecking customize_buckets removes the saved per-bucket CONFs from `entry.options` (or never wrote them); source falls back to computed defaults at evaluation time.
- **Verify:** Checking customize_buckets reveals 8 home-preset cells; saving writes per-bucket CONFs.
- **Verify:** Sleep_enabled checkbox reveals 8 sleep cells when checked.
- **Test:** `test_v474_d3_default_visible_field_count_is_3_plus_2_controls`
- **Test:** `test_v474_d3_customize_buckets_unchecked_falls_back_to_derived`
- **Test:** `test_v474_d3_customize_buckets_checked_persists_cells`
- **Test:** `test_v474_d3_sleep_cells_only_when_enabled`
- **Live:** Open Zone Manager → Back Hallway → Dynamic Preset. See 3 fields + 2 checkboxes. Adjust offset to 1.0. Don't customize buckets. Save. Verify thermostat moves to (baseline + 1) range on next decision cycle.

### D4 — Baseline Presets UX polish

**Description:** Improve the v4.7.3 Baseline Presets form (`async_step_hvac_baseline_presets`):

1. **Group by season with `section` headers:** Summer / Shoulder / Winter sections. Section titles include the months ("Summer (Jun-Sep)").
2. **Pair Cool + Heat side-by-side:** within each preset row, show cool_high and heat_low as adjacent fields, not stacked. (HA's options-flow renderer respects field ordering in the schema; two fields per row is the natural visual layout.)
3. **Add "Reset all to defaults" button:** a separate sub-step that clears all 24 baseline CONFs from CM `entry.options`, restoring hardcoded `SEASONAL_DEFAULTS` fallback. Confirmation step required (one-click destructive action otherwise).

**Files touched:**
- `config_flow.py:async_step_hvac_baseline_presets` — restructure schema into 3 `section` blocks.
- New step `async_step_hvac_baseline_presets_reset_confirm` for the destructive action.
- `strings.json` + `translations/en.json` — section titles + reset button label + confirmation text.

**Acceptance criteria:**
- **Verify:** Form shows 3 section headers: Summer / Shoulder / Winter.
- **Verify:** Within each section, 4 preset rows (home / sleep / away / vacation) each with cool_high + heat_low side-by-side.
- **Verify:** "Reset all to defaults" link/button visible at form bottom.
- **Verify:** Clicking reset opens confirmation; confirming clears all 24 CONFs from entry.options.
- **Test:** `test_v474_d4_schema_has_3_section_blocks`
- **Test:** `test_v474_d4_section_titles_have_month_ranges`
- **Test:** `test_v474_d4_reset_confirm_step_exists`
- **Test:** `test_v474_d4_reset_action_clears_all_24_confs`
- **Live:** Open Baseline Presets, verify visual structure. Click reset, confirm, observe defaults restored.

### D5 — Translation source-contract AST test

**Description:** Add a source-contract test that walks every voluptuous schema in DPM-related steps + Baseline editor and asserts each field key has a matching `data` entry in `translations/en.json`. Catches the v4.7.2 prefix bug class at CI time.

**Files touched:**
- `quality/tests/test_v474_translation_coverage.py` — new file.

**Test logic:**
- Parse `config_flow.py` AST.
- Identify each `async_step_*` function whose name matches DPM/baseline patterns.
- Extract the voluptuous schema fields (via AST or by importing + calling the schema builder).
- For each field key, assert presence in `translations/en.json`'s `options.step.<step_id>.data` dict.
- Soft-warn for missing `data_description` (recommend but not required for build pass).

**Acceptance criteria:**
- **Test:** `test_v474_d5_surface1_field_coverage` — Surface 1's 6 fields all have translations.
- **Test:** `test_v474_d5_surface2_field_coverage` — Surface 2's per-zone fields all have translations.
- **Test:** `test_v474_d5_baseline_field_coverage` — Baseline editor's 24 fields all have translations.
- **Test:** `test_v474_d5_no_prefixed_field_keys` — assert no schema field has `__` in its key (Surface 1's prefix bug regression guard).

---

## 5. Bug Class Compliance Matrix

| Class | Risk | Addressed |
|---|---|---|
| #2 Config Storage Pattern | LOW | D1-D4 keep `entry.options` merge pattern. D3 introduces customize_buckets gating; runtime source handles absent CONFs gracefully. |
| #14 Config Snapshot Staleness | LOW | No changes to read paths. |
| #19 Untracked Tasks | N/A | No new listeners or tasks. |
| #22 Enum Mismatch | LOW | No new enums. |
| #32 Form Field With No Runtime Reader | **MEDIUM** | D3's new `CONF_ZONE_DYNAMIC_PRESET_CUSTOMIZE_BUCKETS` has a runtime reader in `dynamic_preset.py`. D5 source-contract test verifies. |
| #36 Per-Zone Entity Dedup | LOW | No new per-zone entities. |
| #38 Listener Cleanup | N/A | No new listeners. |
| #42 Lambda + async_create_task | N/A | No new scheduler callbacks. |
| #45 Lambda Closure Stale Local | LOW | D3 schema builder is a method, not a closure. |

---

## 6. Tier 2 Review Framings — Two Parallel Reviews

### Reviewer A — Correctness + UX coherence + form structure

**Scope:** D1, D2, D4 (form structure and visible UX).

**Focus areas:**
- D1's strip is COMPLETE — no per-zone fields slip through Surface 1.
- D1's translations cover the 6 remaining Surface 1 fields (Reviewer A audits the actual JSON).
- D2's `section` collapsed-by-default flag set correctly per HA dev docs.
- D2's Advanced section contains EXACTLY the 5 tuning knobs (no leak; no extras).
- D4's section blocks correctly group by season; field ordering within section is `home / sleep / away / vacation` × `cool / heat`.
- D4's reset action is confirmation-gated (no one-click destructive).
- D4's reset correctly removes ALL 24 CONFs from entry.options (not partial).
- The v4.7.2 sync-invariant test (`test_v472_dpm_storage_roundtrip_both_surfaces`) is correctly DROPPED, with a documentation note in the PR explaining why.
- Translation-key coverage: every voluptuous schema field key has a matching `data` entry. D5's source-contract test verifies this.

**Bug classes targeted:** #2, #32.

**Deliverable:** `docs/reviews/code-review/v4.7.4_reviewerA_correctness.md`.

### Reviewer B — Conditional rendering + storage semantics + runtime fallback

**Scope:** D3 (conditional rendering + runtime fallback semantics), D5 (test coverage).

**Focus areas:**
- D3's two-sub-step OR section-collapse pattern: which did the builder pick and is the implementation correct per HA's options-flow API?
- D3's runtime fallback in `dynamic_preset.py`: when `customize_buckets=False`, source MUST derive bucket cell values from baseline + offset at evaluation time. Verify the derivation is correct + matches the historical default values.
- D3's storage semantics: unchecking customize_buckets MUST NOT leave stale per-bucket CONFs in entry.options. If they're there, the runtime path could ambiguously read them.
- D3's sleep-enabled toggle: unchecking removes saved sleep cells from entry.options? Or preserved (in case user toggles back on)? Document the chosen semantics.
- D5's AST walker handles `section`-wrapped schemas correctly (sections introduce nested structure; walker must descend).
- D5's no-prefix invariant test catches the v4.7.2 regression class — verify by intentionally adding a `Back Hallway__` key in a test fixture and asserting the test fails.
- Backward compat: existing users with saved per-bucket cells under v4.7.2/v4.7.3 — when their entry loads under v4.7.4, do the cells survive? Does `customize_buckets` default to TRUE for them (so they don't lose their tuning), or default to FALSE (so they see the simplified UI and have to opt back in)?
  - **Recommendation: migration helper sets `customize_buckets = True` for any zone with saved per-bucket cells, so existing customization is preserved.** Reviewer B verifies the migration is implemented or proposes its addition.

**Bug classes targeted:** #2, #14, #32.

**Deliverable:** `docs/reviews/code-review/v4.7.4_reviewerB_conditional_rendering.md`.

---

## 7. Live Validation (Post-Deploy)

1. **Surface 1 cleanup:** Open Settings → Devices → URA Coordinator Manager → Configure → HVAC → Dynamic Preset. See 1 visible field (Enable Dynamic Preset). Expand Advanced (rarely change) — see 5 fields. NO zone names anywhere on this page.
2. **Surface 2 simplification:** Open Settings → Devices → URA Zone Manager → Back Hallway → Configure → Dynamic Preset. See 3 fields + 2 checkboxes (Customize buckets + Enable sleep preset ranges). All field labels are clean (no underscores). Helper text under each field.
3. **Per-zone editing works:** Check "Enable DPM for this zone"; set Offset to 1.0; ensure "Reset offset during Guest Mode" stays checked. Don't customize buckets. Save. Within ≤5 min, `sensor.ura_hvac_coordinator_active_preset_overrides` shows 1; `climate.back_hallway.target_temp_high` reflects `baseline + 1°F` for current bucket.
4. **Customize buckets opt-in:** Re-open the zone form; check "Customize buckets for this zone." See 8 home-preset cells with current computed values as placeholders. Edit one (e.g., Hot bucket Home High from 75 → 76). Save. Verify thermostat reflects the override on next decision cycle.
5. **Sleep cells opt-in:** Check "Enable sleep preset ranges." See 8 sleep cells. Save unchanged. Verify sleep ranges match home (no behavior change since unchanged).
6. **Baseline Presets UX:** Open Baseline Presets. Verify 3 season sections (Summer / Shoulder / Winter). Pair structure (cool + heat side by side). Click Reset → confirmation step → confirm → defaults restored.
7. **Translation regression check:** No raw underscored keys visible on ANY DPM form.
8. **No new ERRORs:** `ha_get_logs(source="system_service", slug="core", search="universal_room_automation", level="ERROR")` shows zero new entries.

---

## 8. File Touch List (Estimated LoC)

| File | Add | Modify | Delete | Notes |
|---|---|---|---|---|
| `config_flow.py` | ~80 | ~120 | ~150 | D1 strip Surface 1 per-zone (-150); D2 section wrap (+10); D3 conditional rendering (+100); D4 baseline UX polish (+80) |
| `domain_coordinators/dynamic_preset.py` | ~40 | ~10 | 0 | D3 runtime fallback (baseline + offset derivation when customize_buckets=False) |
| `domain_coordinators/energy_const.py` | ~2 | 0 | 0 | New CONF_ZONE_DYNAMIC_PRESET_CUSTOMIZE_BUCKETS |
| `strings.json` | ~30 | ~10 | ~5 | Section titles, new checkbox labels, reset button text |
| `translations/en.json` | ~30 | ~10 | ~5 | mirror |
| `quality/tests/test_v474_dpm_ui.py` (NEW) | ~200 | 0 | 0 | D1/D2/D3/D4 tests |
| `quality/tests/test_v474_translation_coverage.py` (NEW) | ~120 | 0 | 0 | D5 source contract |
| `quality/tests/test_v472_dpm_surfaces.py` | 0 | ~10 | ~30 | DROP `test_v472_dpm_storage_roundtrip_both_surfaces` and sibling sync-invariant tests; sync no longer applicable |
| `docs/readmes/README_v4.7.4.md` (NEW) | ~130 | 0 | 0 | Release notes |

**Total estimated LoC:** ~610 new + ~150 modified − ~190 deleted across 9 files.

---

## 9. Pre-Deploy Tags

```
git tag pre-review-v4.7.4 -m "Pre-review baseline for v4.7.4"
git tag pre-fixup-v4.7.4 -m "Pre-fixup baseline before applying reviewer findings"
git tag post-fixup-v4.7.4 -m "Post-fixup, ready for deploy"
```

---

## 10. Migration Safety

**Backward compatibility:** Existing users have entry.options with per-bucket cell values saved (from v4.7.2/v4.7.3 era). When they load under v4.7.4:

- Saved per-bucket cells are preserved in entry.options regardless of `customize_buckets` flag.
- One-shot migration on first v4.7.4 load: for any zone where saved per-bucket CONFs exist, set `customize_buckets = True` so the user sees their saved values in the UI and doesn't think they were lost.
- If user later unchecks customize_buckets, saved cells stay in entry.options (silent fallback to derived); re-checking restores visibility without data loss.

Migration helper in `__init__.py:async_setup_entry` ZM-entry path:
```python
# v4.7.4 migration: zones with saved per-bucket cells get customize_buckets=True
for zone_name, zone_data in zm_entry.options.get("zones", {}).items():
    if zone_data.get(CONF_ZONE_DYNAMIC_PRESET_CUSTOMIZE_BUCKETS) is None:  # not yet set
        has_saved_cells = any(
            zone_data.get(f"zone_dynamic_preset_{bucket}_home_low") is not None
            for bucket in ["cool", "mild", "hot", "extreme"]
        )
        zone_data[CONF_ZONE_DYNAMIC_PRESET_CUSTOMIZE_BUCKETS] = has_saved_cells
```

---

## 11. What This Cycle Does NOT Do

v4.7.4 simplifies the DPM UI control surface and fixes the structural translation bug on Surface 1. It does NOT change the DPM evaluation logic, does NOT change OverrideEngine semantics, does NOT touch the v4.7.2 D5 sustained-occupancy guest signal, does NOT migrate the DPM backing field across coordinators, does NOT add new actuators, and does NOT change the Baseline Presets data model (D4 is pure UX polish on existing fields).

---

## 12. Acceptance Criteria Summary

Release is "done" when:

- Surface 1 renders exactly 6 house-wide fields (1 visible by default + 5 in Advanced expander). NO per-zone fields visible.
- Surface 2 renders 3 default fields + 2 opt-in controls. Conditional cells appear/disappear correctly.
- Baseline editor groups by season; reset action confirmation-gated.
- Translation coverage AST test passes for ALL DPM form fields.
- Both pytest orderings clean (Bug Class #44 invariant).
- Tier 2 reviewer verdicts SAFE TO COMMIT (or COMMIT WITH FIXES with all CRITICAL+HIGH addressed).
- Migration helper preserves existing per-bucket customizations.
- Live validation §7 all-green.
- `docs/readmes/README_v4.7.4.md` describes user-visible changes.
