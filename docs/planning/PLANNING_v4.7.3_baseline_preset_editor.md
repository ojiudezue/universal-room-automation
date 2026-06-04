# PLANNING v4.7.3 — Baseline Preset Editor + DPM Number Entity Migration

**Status:** Plan ready for build
**Tier:** Tier 1 (single staff-engineer adversarial review)
**Predecessor:** v4.7.2 (DPM HVAC Surface + Phase 2 Feature B)
**Filed:** 2026-05-28
**Recall:** "Plan the baseline preset editor" / "Resume v4.7.3"

---

## 1. Goal + Why

**Goal:** Two related HVAC surface tidy-ups in one coherent cycle:

1. **Surface the house-wide `SEASONAL_DEFAULTS` baseline (currently hardcoded at `hvac_const.py:278`)** as editable form fields on the CM Coordinator Manager → Configure → HVAC step. Closes two gaps post-v4.7.2:
   - **Shoulder + winter baselines are not editable from UI today.** DPM's per-zone × per-bucket cells are summer-cooling-focused (delta vs `apparent_forecast_high`). Heat-season and shoulder tunability needs a separate path.
   - **"Flat baseline without DPM."** Users who don't want DPM's dynamic per-bucket adjustment still want to tweak the home/sleep/away/vacation setpoints from a single panel.

2. **MIGRATE the two DPM number entities (`DynamicPresetDwellMinutesNumber` and `DynamicPresetHysteresisFNumber`) from the EC device to the HVAC Coordinator device** — same artifact as the v4.7.2 D2 master-switch migration. Both currently have `identifiers={(DOMAIN, "energy_coordinator")}` at `number.py:1549` and `number.py:1629` respectively, which is wrong: they're DPM-feature knobs and DPM lives on HVAC Coordinator post-v4.7.2.

**Why now:** v4.7.2 closed the DPM/Guest Mode UI gaps for the master toggles but left these two number entities orphaned on the wrong device. User flagged 2026-05-28: *"the EC has some artifactual sensor that should move."* Same migration pattern as v4.7.2 D2 (preserve unique_id, change DeviceInfo.identifiers, defensive idempotent entity_registry helper). Tier 1, ~30 LoC for the migration alongside the baseline editor work.

---

## 2. Tier Classification

Tier 1 (single review pass).

| Tier 2-DB trigger | Hit? |
|---|---|
| Touches `database.py` DAO definitions | No |
| Migrates ≥3 callers to a new DAO | No |
| Changes dispatched-payload shape | No (no signal payload changed) |
| Adds behavioral test infra against real schemas | No |
| Followed by a planned schema migration | No |

| Tier 2 trigger | Hit? |
|---|---|
| New capability with multiple files / new sensors | No (1 new form step; 0 new sensors; existing `PresetManager` reader gets a thin overlay) |
| Multi-file edit > 3 files | No (estimate: 4 files but each tightly scoped) |
| New CONF keys with runtime readers | Yes — 24 new CONFs. But all read by ONE accessor (`PresetManager.get_seasonal_setpoints`) with consistent fallback semantics. |

Tier 1 fits. If review surfaces non-trivial issues, escalate.

---

## 3. Discovery — Read Before Build

| File | Lines | Why |
|---|---|---|
| `domain_coordinators/hvac_const.py` | 278-297 | `SEASONAL_DEFAULTS` structure: `{season: {preset: (cool_high, heat_low)}}` for 3 seasons × 4 presets × 2 dims = 24 numeric values |
| `domain_coordinators/hvac_preset.py` | 20, 88 | `PresetManager` imports + reads `SEASONAL_DEFAULTS.get(season)`. This is the ONE consumer that must learn to prefer entry.options overrides over the hardcoded fallback. |
| `config_flow.py` | 3293-3304 | `async_step_coordinator_hvac` — already a menu in v4.7.2 with options `coordinator_hvac_settings` and `hvac_dynamic_preset`. Add `hvac_baseline_presets` as a third menu option. |
| `config_flow.py` | 3308-3666 | `async_step_coordinator_hvac_settings` — pattern to mirror (CM step persists to `entry.options`). |
| `config_flow.py` | 3675-3939 | `async_step_hvac_dynamic_preset` (Surface 1, v4.7.2) — pattern for an HVAC sub-step. |
| `const.py` or `domain_coordinators/hvac_const.py` | (entire) | New CONFs land here. Naming convention: `CONF_HVAC_BASELINE_<SEASON>_<PRESET>_<DIM>` e.g. `CONF_HVAC_BASELINE_SUMMER_HOME_COOL` and `CONF_HVAC_BASELINE_SUMMER_HOME_HEAT`. |
| `strings.json` + `translations/en.json` | (entire) | Add menu label + step title + description + 24 field labels + 24 helper descriptions. |
| `quality/tests/` | new file | `test_v473_baseline_preset_editor.py` — ~10 tests. |
| `docs/QUALITY_CONTEXT.md` | Bug Classes #2, #14, #32 | Form-field-with-no-runtime-reader (#32) is the load-bearing class — every new CONF MUST have an AST-detectable read in `hvac_preset.py`. |

---

## 4. Deliverables

### D1 — `async_step_hvac_baseline_presets()` form step

**Description:** New step on the CM Coordinator Manager → Configure → HVAC menu. Renders 24 numeric inputs organized as 12 row pairs (3 seasons × 4 presets, each row showing cool_high + heat_low side by side or stacked). Defaults read from current `SEASONAL_DEFAULTS` values so users see the baseline they're starting from. Saving writes to CM `entry.options`.

**Files touched:**
- `config_flow.py`:
  - Add `"hvac_baseline_presets"` to the menu at `async_step_coordinator_hvac` (line ~3303).
  - Add `async_step_hvac_baseline_presets()` step function with full form rendering. Reads defaults from `SEASONAL_DEFAULTS` for fresh installs; reads from `entry.options` for users who've saved before. ~120 LoC.
- `strings.json` + `translations/en.json`: menu option label `"📅 Baseline Presets (Seasonal)"` + step title + description + 24 field labels with helper text explaining season/preset combo. ~60 entries each file.

**Form layout (single page, all 24 fields):**
```
📅 Baseline Presets (Seasonal)

Edit the house-wide preset ranges per season. These are the baseline
ranges that every zone uses unless Dynamic Preset is configured per-zone.

— Summer (June–September) —
  Home:     cool_high [77]   heat_low [70]
  Sleep:    cool_high [76]   heat_low [70]
  Away:     cool_high [82]   heat_low [60]
  Vacation: cool_high [85]   heat_low [58]

— Shoulder (Mar–May + Oct–Nov) —
  Home:     cool_high [74]   heat_low [70]
  ... (4 rows)

— Winter (Dec–Feb) —
  Home:     cool_high [72]   heat_low [70]
  ... (4 rows)
```

**Validation:**
- Each `cool_high` must be > corresponding `heat_low + MIN_DEADBAND` (default 3°F).
- All values within plausible range: cool_high `[65, 95]`, heat_low `[55, 80]`.
- Form rejects save with `"baseline_preset_invalid_deadband"` error if any row fails the deadband rule.

**Out of scope:**
- No per-zone baselines (DPM covers that for summer cooling; per-zone heat-side tunability is deferred).
- No "extreme cold" or "extreme heat" presets — sticks to existing 4-preset taxonomy.
- No seasonal-boundary-date editing (which months count as summer/shoulder/winter remains hardcoded for now).

**Acceptance criteria:**
- **Verify:** Settings → Devices → URA Coordinator Manager → Configure → HVAC step shows new "📅 Baseline Presets (Seasonal)" menu option.
- **Verify:** Opening the step renders all 24 fields prefilled with current `SEASONAL_DEFAULTS` values (or saved overrides if user has saved before).
- **Verify:** Editing a Summer Home cool_high from 77 → 76 and saving persists to CM `entry.options[CONF_HVAC_BASELINE_SUMMER_HOME_COOL]`.
- **Verify:** Invalid input (e.g., cool_high=70, heat_low=70 → 0°F deadband) is rejected with the form error.
- **Test:** `test_v473_d1_form_renders_24_fields`
- **Test:** `test_v473_d1_defaults_match_seasonal_defaults`
- **Test:** `test_v473_d1_saved_override_round_trips`
- **Test:** `test_v473_d1_deadband_validation_rejects`
- **Live:** Open Configure → URA Coordinator Manager → HVAC → Baseline Presets and verify all 24 fields visible + editable.

### D2 — `PresetManager.get_seasonal_setpoints()` learns to prefer overrides

**Description:** Modify `hvac_preset.py:get_seasonal_setpoints(preset)` to check CM `entry.options` for the relevant CONFs first; fall back to `SEASONAL_DEFAULTS` if not set. ~20 LoC.

**Migration semantics:**
- Existing users (no saved overrides) → keep using hardcoded `SEASONAL_DEFAULTS`. Zero-time migration.
- New users (after editing the form) → use their saved values.
- Per-CONF granularity: if user edits only Summer Home cool_high, ONLY that field reads from entry.options; all other 23 fields still read from `SEASONAL_DEFAULTS` (no all-or-nothing override).

**Files touched:**
- `domain_coordinators/hvac_preset.py`: extend `get_seasonal_setpoints` to access CM entry options. Needs `hass` reference; verify availability at call site. ~20 LoC.

**Out of scope:**
- D2 does NOT propagate changes via signal/dispatch. Behavior takes effect at the next HVAC decision cycle (existing 5-min cadence). Acceptable per Tier 1 hotfix conventions.

**Acceptance criteria:**
- **Verify:** With no saved overrides, `get_seasonal_setpoints("home", season="summer")` returns `(77, 70)` (current `SEASONAL_DEFAULTS` value).
- **Verify:** After saving Summer Home cool_high=76 via D1 form, next call to `get_seasonal_setpoints("home", season="summer")` returns `(76, 70)`.
- **Verify:** Saving only Summer Home cool_high does NOT affect other seasons/presets (per-CONF granularity).
- **Test:** `test_v473_d2_get_seasonal_setpoints_uses_override`
- **Test:** `test_v473_d2_get_seasonal_setpoints_falls_back_to_defaults`
- **Test:** `test_v473_d2_per_conf_granularity`
- **Live:** Edit Summer Home cool_high via D1 form; wait ≤5 min for next HVAC decision cycle; verify `sensor.ura_hvac_zone_<zone>_active_preset_range_high` reflects the new value.

### D4 — MIGRATE DPM Number Entities from EC → HVAC Coordinator device

**Description:** Move `DynamicPresetDwellMinutesNumber` (`number.py:1549`) and `DynamicPresetHysteresisFNumber` (`number.py:1629`) from the Energy Coordinator device to the HVAC Coordinator device. Same migration pattern as v4.7.2 D2 (the `HVACDynamicPresetSwitch` migration):

- **PRESERVE `unique_id`** on both entities. The strings are `f"{DOMAIN}_energy_dynamic_preset_dwell_minutes"` and `f"{DOMAIN}_energy_dynamic_preset_hysteresis_f"`. Keeping unique_id stable preserves entity_id across the migration (HA looks up entity by `(platform, domain, unique_id)`).
- Change `DeviceInfo.identifiers` from `{(DOMAIN, "energy_coordinator")}` to `{(DOMAIN, "hvac_coordinator")}` on both classes.
- **Numeric prefix labels** for HVAC-Coordinator-device sort:
  - `DynamicPresetDwellMinutesNumber._attr_name` → e.g. `"03 · Dynamic Preset Dwell (minutes)"`
  - `DynamicPresetHysteresisFNumber._attr_name` → e.g. `"04 · Dynamic Preset Hysteresis (°F)"`
  - Builder MUST re-audit existing HVAC Coordinator device numeric prefixes (the v4.7.2 build already grouped `01·` and `02·`; `03·` and `04·` continue the sequence).
- **Defensive idempotent entity_registry helper** in `__init__.py` — extend the existing v4.7.2 D2 helper to also reassign these two entities. Reuse the `async_get_entity_id(domain, platform, unique_id)` lookup pattern (lesson learned 2026-05-28 from the v4.7.2 B2 spot-check fix).
- **Backing field unchanged.** `_dwell_minutes` and `_hysteresis_f` continue to live as CM `entry.options` keys read by `_get_cm_options()` on EC. D4 is purely presentational (device association); no runtime behavior change.

**Files touched:**
- `number.py`: change `DeviceInfo.identifiers` + `_attr_name` on both classes. ~6 LoC.
- `__init__.py`: extend v4.7.2 D2 helper to handle 2 more unique_ids. ~20 LoC (loop over a list of 3 unique_ids instead of single-entity inline code).
- `strings.json` + `translations/en.json`: ~6 entries (new labels for both, plus description updates if applicable).

**Out of scope:**
- D4 does NOT change number-entity behavior — they continue to write to entry.options via the v4.7.1 fix-up writeback path.
- D4 does NOT add new entities — strict relocation.
- D4 does NOT bump version separately; ships in v4.7.3 alongside the baseline editor.

**Acceptance criteria:**
- **Verify:** Both number entities appear on the HVAC Coordinator device card post-deploy + restart.
- **Verify:** Entity IDs preserved: `number.ura_energy_dynamic_preset_dwell_minutes` and `number.ura_energy_dynamic_preset_hysteresis_f` (or whatever HA assigned originally) unchanged.
- **Verify:** Both numbers sort below `01·` and `02·` switches on the HVAC Coordinator device page.
- **Verify:** Changing either slider still propagates to CM `entry.options` (regression check — the v4.7.1 fix-up writeback path is unaffected).
- **Test:** `test_v473_d4_dwell_entity_on_hvac_device` — assert `DeviceInfo.identifiers == {(DOMAIN, "hvac_coordinator")}` for `DynamicPresetDwellMinutesNumber`.
- **Test:** `test_v473_d4_hysteresis_entity_on_hvac_device` — same for `DynamicPresetHysteresisFNumber`.
- **Test:** `test_v473_d4_unique_ids_preserved` — assert both unique_id strings match v4.7.2 values byte-for-byte.
- **Test:** `test_v473_d4_migration_helper_handles_all_three_entities` — verify the extended `__init__.py` helper iterates over the switch + 2 number entities and reassigns each.
- **Live:** Settings → Devices → URA HVAC Coordinator → see `03 · Dynamic Preset Dwell (minutes)` and `04 · Dynamic Preset Hysteresis (°F)` near the top with the master toggles.

### D3 — 24 new CONF keys + defaults

**Description:** Add 24 string CONF constants to `hvac_const.py` with corresponding `DEFAULT_HVAC_BASELINE_*` integer defaults matching the current `SEASONAL_DEFAULTS` values.

**Naming convention:** `CONF_HVAC_BASELINE_<SEASON>_<PRESET>_<DIM>` where:
- `<SEASON>`: `SUMMER`, `SHOULDER`, `WINTER`
- `<PRESET>`: `HOME`, `SLEEP`, `AWAY`, `VACATION`
- `<DIM>`: `COOL` (cool_high), `HEAT` (heat_low)

Example: `CONF_HVAC_BASELINE_SUMMER_HOME_COOL = "hvac_baseline_summer_home_cool"` with `DEFAULT_HVAC_BASELINE_SUMMER_HOME_COOL = 77`.

**Files touched:**
- `domain_coordinators/hvac_const.py`: 24 CONF + 24 DEFAULT constants. ~50 LoC.

**Source-contract regression test:** `test_v473_d3_every_conf_has_default` walks `hvac_const.py` AST to assert every `CONF_HVAC_BASELINE_*` has a corresponding `DEFAULT_HVAC_BASELINE_*` constant. Catches typos before runtime.

**Acceptance criteria:**
- **Verify:** All 24 CONF strings importable from `hvac_const.py`.
- **Verify:** All 24 DEFAULT integers match the current `SEASONAL_DEFAULTS` tuple values.
- **Test:** `test_v473_d3_conf_count_matches_seasonal_defaults_shape` — assert exactly 3 × 4 × 2 = 24 CONFs.
- **Test:** `test_v473_d3_every_conf_has_default` (source contract AST).

---

## 5. Bug Class Compliance Matrix

| Class | Risk | Addressed |
|---|---|---|
| #2 Config Storage Pattern | LOW | D1 uses `entry.options` merge pattern matching existing CM steps. |
| #14 Config Snapshot Staleness | LOW | D2 reads from `entry.options` fresh on every `get_seasonal_setpoints` call (per-decision-cycle). |
| #22 Enum Mismatch | LOW | Reuses existing `SEASON_SUMMER`/`SEASON_SHOULDER`/`SEASON_WINTER` string constants. No new enum. |
| #32 Form Field With No Runtime Reader | **HIGH** | The single shared accessor `get_seasonal_setpoints` is the runtime reader for ALL 24 CONFs. **Source-contract test D3 verifies AST-detectable read at `hvac_preset.py:get_seasonal_setpoints`.** |
| #36 Per-Zone Entity Bypasses ZoneManager Dedup | N/A | House-wide; not per-zone. |
| #38 Listener Cleanup | N/A | No new listeners. |
| #45 Lambda Closure Captures Stale Local | N/A | No new closures. |

---

## 6. Tier 1 Review Framing

One staff-engineer adversarial pass. Focus areas:
- D3 source contract: every CONF readable via `get_seasonal_setpoints`. AST grep verifies. No dead CONFs.
- D2 fallback correctness: missing CONF → returns hardcoded default (not None, not error).
- Form-save validation rejects bad inputs with intelligible error strings.
- D1 form layout doesn't crash with 24 fields (HA frontend handles long forms; verify scroll behavior in live validation).
- Per-CONF granularity (D2): saving only ONE field does not silently override the other 23.
- Backward compatibility: existing users (no saved overrides) see ZERO behavior change.

**Bug classes targeted:** #32 (primarily), #2, #14.

**Deliverable:** `docs/reviews/code-review/v4.7.3_baseline_preset_editor_review.md`.

---

## 7. File Touch List (Estimated LoC)

| File | Add | Modify | Notes |
|---|---|---|---|
| `config_flow.py` | ~120 | ~3 (menu option) | D1 form step + menu addition |
| `domain_coordinators/hvac_preset.py` | ~20 | ~3 | D2 fallback logic |
| `domain_coordinators/hvac_const.py` | ~50 | 0 | D3 CONF + DEFAULT constants |
| `number.py` | 0 | ~6 | D4 DeviceInfo + label changes on 2 classes |
| `__init__.py` | ~20 | ~5 | D4 extend v4.7.2 D2 migration helper to cover 3 entities |
| `strings.json` | ~60 | ~6 | menu label + step title + 24 field labels + 24 helpers + D4 number-entity labels |
| `translations/en.json` | ~60 | ~6 | mirror of strings.json |
| `quality/tests/test_v473_baseline_preset_editor.py` (NEW) | ~150 | 0 | ~10 D1/D2/D3 tests |
| `quality/tests/test_v473_dpm_number_migration.py` (NEW) | ~80 | 0 | ~5 D4 tests |
| `docs/readmes/README_v4.7.3.md` (NEW) | ~100 | 0 | release notes |

**Total estimated LoC:** ~660 new + ~26 modified across 8 files (excluding plan + README).

---

## 8. Pre-Deploy Tags

```
git tag pre-review-v4.7.3 -m "Pre-review baseline for v4.7.3"
git tag pre-fixup-v4.7.3 -m "Pre-fixup baseline before applying reviewer findings"
```

---

## 9. Live Validation (Post-Deploy)

1. **Menu visibility:** Settings → Devices → URA Coordinator Manager → Configure → HVAC → "📅 Baseline Presets (Seasonal)" option visible.
2. **Form renders:** Opening the step shows all 24 fields with current `SEASONAL_DEFAULTS` values pre-filled.
3. **Save round-trip:** Edit one field (e.g., Summer Home cool_high 77 → 76), save, reopen — value persists.
4. **Runtime effect:** Within ≤5 min of save, `sensor.ura_hvac_zone_<zone>_active_preset_range_high` reflects the new value when house_state="home" and season=summer.
5. **No regression:** Existing users with no overrides see no behavior change (verified via test, also live by checking a user whose baseline-preset CONFs are absent from `entry.options`).
6. **No new HA-core warnings:** `ha_get_logs(source="system_service", slug="core", search="universal_room_automation")` zero new ERRORs.

---

## 10. What This Cycle Does NOT Do

v4.7.3 adds editable house-wide baseline presets via a single CM HVAC sub-step. It does NOT add per-zone baseline editing (DPM's per-bucket cells cover summer cooling; per-zone heat tunability deferred), does NOT change the seasonal-boundary-date logic (which months count as summer/shoulder/winter remains hardcoded), does NOT introduce a new dispatcher signal (changes take effect at next 5-min HVAC decision cycle, not real-time), does NOT propagate changes to existing OverrideEngine resolved-range cache (next decision cycle re-resolves from the updated baseline).

---

## 11. Acceptance Criteria Summary

Release is "done" when:

- All v4.7.3 tests pass (target: ~10 new tests).
- Both pytest orderings clean (Bug Class #44 invariant).
- Tier 1 reviewer verdict SAFE TO COMMIT (or COMMIT WITH FIXES with all CRITICAL+HIGH addressed).
- Live validation §9 all-green.
- `docs/readmes/README_v4.7.3.md` describes user-visible changes.
- Backlog item Task #103 / `project_baseline_preset_editor_backlog.md` removed from durable memory's active backlog (mark as shipped).
