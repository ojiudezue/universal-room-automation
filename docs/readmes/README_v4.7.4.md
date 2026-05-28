# URA v4.7.4 — DPM UI Simplification + Translation Fix

**Release date:** 2026-05-28
**Tier:** Tier 2 (two parallel staff-engineer reviews, different framings)
**Scope:** D1 Surface 1 strip, D2 advanced section collapse, D3 Surface 2 conditional rendering, D4 baseline presets UX polish, D5 translation source-contract tests

**Trigger:**
- Post-v4.7.3, the DPM HVAC control surfaces rendered ~150 knobs spread across 3 forms, making the feature functionally unusable.
- Surface 1 (`async_step_hvac_dynamic_preset`) had a structural translation bug: per-zone fields were prefixed with `<zone_name>__` at form-build time, causing HA's translation system to display raw underscore-separated keys (e.g., `Back Hallway__zone_dynamic_preset_offset`) instead of human-readable labels. This bug class was unfixable without removing the per-zone iteration from Surface 1 entirely.

---

## Headline Changes

### D1 — Strip Surface 1 to house-wide only

Surface 1 (`async_step_hvac_dynamic_preset`) now shows exclusively house-wide settings. The per-zone field iteration that produced the translation-breaking `<zone_name>__` prefixed keys has been removed.

**Reachable via:**
Settings → Devices & Services → URA Coordinator Manager → Configure → HVAC → Dynamic Preset

**Fields visible on Surface 1:**
1. `dynamic_preset_enabled` — master enable toggle for the DPM feature (visible by default)
2–6. Five house-wide tuning knobs in the "Advanced (rarely change)" collapsed section (see D2)

Per-zone editing is now exclusively routed through Surface 2 (Zone Manager → [zone] → Dynamic Preset). Surface 1's description text directs users there.

**Translation bug eliminated:** All 6 Surface 1 field keys are bare CONF names (no zone prefix), so HA's translation lookup succeeds for every field.

### D2 — Advanced section collapsing on Surface 1

The five house-wide tuning knobs (bucket boundaries + dwell + hysteresis) are wrapped in a collapsed HA `section` block labeled "Advanced (rarely change)". On first open of Surface 1, only the master enable toggle is visible. Expanding the section reveals the 5 rarely-changed values.

- `CONF_DYNAMIC_PRESET_DELTA_COOL_MAX` — maximum delta for Cool bucket
- `CONF_DYNAMIC_PRESET_DELTA_MILD_MAX` — maximum delta for Mild bucket
- `CONF_DYNAMIC_PRESET_DELTA_HOT_MAX` — maximum delta for Hot bucket
- `CONF_DYNAMIC_PRESET_DWELL_MINUTES` — minutes before preset engages
- `CONF_DYNAMIC_PRESET_HYSTERESIS_F` — hysteresis band (°F)

### D3 — Conditional rendering on Surface 2 (Zone Manager)

Surface 2 (`async_step_zone_dynamic_preset`) previously rendered 18 visible knobs per zone. After D3, the default view shows 3 settings + 2 collapsed section expanders.

**Default visible (3 fields):**
1. Zone enable toggle
2. Offset (°F)
3. Reset offset under guest mode

**Collapsed sections (opt-in):**
- "Customize Bucket Ranges" — new `zone_dynamic_preset_customize_buckets` checkbox + 8 home-preset bucket cells (4 buckets × cool_low + cool_high). When unchecked, the runtime derives bucket cell values from the house-wide baseline + per-zone offset at evaluation time (no saved bucket cells needed).
- "Sleep Preset Ranges" — sleep_enabled toggle + 8 sleep-preset bucket cells.

**New constant:** `CONF_ZONE_DYNAMIC_PRESET_CUSTOMIZE_BUCKETS` in `energy_const.py`.

**Runtime fallback:** `dynamic_preset.py:_build_overrides()` reads `customize_buckets` from `zone_data`. When False, it derives home-preset bucket values from `PresetManager.get_seasonal_setpoints("home")` + the zone offset, bypassing the need for saved per-bucket CONFs.

**Migration helper:** On first load under v4.7.4, zones with existing saved per-bucket cells get `customize_buckets = True` automatically (preserving their customizations). Zones without saved cells get `customize_buckets = False` (simplified default view). Migration is non-fatal — wrapped in try/except in `__init__.py`.

### D4 — Baseline Presets UX polish

`async_step_hvac_baseline_presets` (introduced in v4.7.3) has been restructured:

1. **3 season section blocks:** Summer (Jun–Sep), Shoulder (Mar–May, Oct–Nov), Winter (Dec–Feb). All three sections are open by default so the user sees the full structure on first render.
2. **Field ordering preserved:** Within each season, fields are ordered as Home → Sleep → Away → Vacation, each row showing cool_high then heat_low.
3. **"Reset all to defaults" action:** A `_reset_all` boolean field at the bottom of the form. Checking it and saving navigates to a new confirmation step (`async_step_hvac_baseline_presets_reset_confirm`). Confirming on that screen clears all 24 baseline CONFs from CM `entry.options`, restoring the hardcoded `SEASONAL_DEFAULTS` fallback. The action is confirmation-gated — no one-click destructive reset.

### D5 — Translation source-contract AST tests

New test file `quality/tests/test_v474_translation_coverage.py` provides:

- **No-prefix regression guard:** `test_d5_no_double_underscore_anywhere_in_schema_builders` — asserts that `vol.Optional` calls in DPM schema builders never contain `__` in a field key. This catches the v4.7.2 prefix bug class at CI time before it can ship.
- **Per-step field coverage:** Tests for Surface 1 (6 fields), Surface 2 (21 fields), and the Baseline editor (24+ fields) verify that every schema field key has a matching entry in `translations/en.json`.
- **Section key coverage:** Verifies that section wrapper keys (`advanced`, `customize_buckets_section`, `sleep_section`, `summer_section`, `shoulder_section`, `winter_section`) all have labels in `strings.json` and `translations/en.json`.

---

## TL;DR

v4.7.4 fixes the structural translation bug in Surface 1 (raw `<zone_name>__` keys visible to users), reduces Surface 2's visible knob count from 18 to 5 default fields via collapsed sections, adds a zone-level opt-in for custom bucket ranges with a runtime baseline-derived fallback, polishes the baseline presets form into 3 season sections with a guarded reset action, and adds a CI-enforced translation coverage test that catches the root cause of the v4.7.2 bug class for all future DPM form changes.

---

## What's Changed

### Modified files

| File | What changed |
|---|---|
| `config_flow.py` | D1: stripped `async_step_hvac_dynamic_preset` per-zone loop; rewrote `_build_hvac_dynamic_preset_schema` to house-wide 6-field schema. D2: wrapped 5 tunables in collapsed `section` block. D3: updated `async_step_zone_dynamic_preset` + `_build_dynamic_preset_schema` to use section-collapse pattern; added `customize_buckets` guard around `_validate_dynamic_preset_input`. D4: restructured `async_step_hvac_baseline_presets` into 3 season sections + reset trigger; added `async_step_hvac_baseline_presets_reset_confirm` confirmation step. |
| `domain_coordinators/energy_const.py` | Added `CONF_ZONE_DYNAMIC_PRESET_CUSTOMIZE_BUCKETS`. |
| `domain_coordinators/dynamic_preset.py` | D3 runtime fallback: derives home-preset bucket values from `PresetManager.get_seasonal_setpoints("home")` when `customize_buckets=False`. |
| `__init__.py` | D3 migration helper in ZM-entry path: sets `customize_buckets=True` for zones with existing per-bucket cells. |
| `strings.json` | Added `dynamic_preset_enabled` to Surface 1 data; added `sections.advanced`; added `zone_dynamic_preset_customize_buckets` to Surface 2 data; added `sections.{customize_buckets_section,sleep_section}`; added `_reset_all` to baseline presets data; added `sections.{summer,shoulder,winter}_section`; added `hvac_baseline_presets_reset_confirm` step. |
| `translations/en.json` | Mirror of all strings.json additions. |
| `quality/tests/test_v472_dpm_surfaces.py` | Dropped the `test_surface_2_calls_validate_helper` window (5000 → 9000 chars) to accommodate D3's larger function body. Updated test comments explaining which v4.7.2 sync-invariant tests are now obsolete. |
| `quality/tests/test_v473_baseline_preset_editor.py` | Updated `== 24` assertions to `>= 24` for baseline presets data/data_description counts (D4 adds `_reset_all` making total 25). Increased `async_step_hvac_baseline_presets` window from 8000 to 12000 chars. |

### New files

| File | Purpose |
|---|---|
| `quality/tests/test_v474_dpm_ui.py` | D1/D2/D3/D4 source-grep tests covering all acceptance criteria. |
| `quality/tests/test_v474_translation_coverage.py` | D5 source-contract tests: no-__ guard + per-step translation field coverage. |
| `docs/readmes/README_v4.7.4.md` | This file. |

---

## Dropped / Obsolete

The v4.7.2 sync-invariant test class (`test_v472_dpm_storage_roundtrip_both_surfaces`) — which asserted that Surface 1 + Surface 2 produce identical per-zone state — was already marked as dropped in the v4.7.2 test file and remains so. D1 makes the invariant permanently obsolete: Surface 1 no longer writes any per-zone fields.

---

## Migration Safety

- **Existing per-bucket customizations preserved:** Zones with saved per-bucket CONFs under v4.7.2/v4.7.3 automatically get `customize_buckets = True` on first v4.7.4 load. Users see their saved values in the expanded UI sections.
- **No saved customizations:** Zones without saved per-bucket CONFs get `customize_buckets = False`, showing the simplified 3-field default view. The runtime derives bucket values from the house-wide baseline + offset.
- **Entry.options merge pattern preserved:** All form steps use `{**self._config_entry.options, **save_vals}` merge (Bug Class #2 compliant).
- **Migration is non-fatal:** Wrapped in try/except. If the migration fails for any reason, the zone loads with `customize_buckets = False` (simplified view) — no crash, no data loss.
