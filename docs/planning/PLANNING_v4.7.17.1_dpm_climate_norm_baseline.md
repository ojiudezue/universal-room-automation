# PLANNING v4.7.17.1 — DPM climate-norm baseline (tuning-frame redesign)

**Status:** Plan ready for operator review
**Tier:** Tier 1 (surgical — see §3 for justification, with escalation criteria)
**Predecessor:** v4.7.16.4 (DPM baseline tuple-index fix-up — closed an off-by-one INSIDE the old frame; this cycle fixes the FRAME)
**Filed:** 2026-06-01
**Recall:** "Resume DPM climate-norm baseline" / "Plan v4.7.17.1 tuning frame"

---

## 1. Goal + Why

### Goal

Switch `WeatherProviderManager.baseline_delta_for_zone()` from comparing today's
apparent forecast high against the **operator's indoor cool setpoint** to
comparing it against a **per-zone climate-norm expectation for the current
season**. Same return type (`float | None`). Same downstream consumers
(`classify_bucket()` in `dynamic_preset.py:132`, the
`DynamicPresetBucketSensor.extra_state_attributes` exposure at `sensor.py:6995–7006`,
and `_passed_boundary_with_buffer()` hysteresis at `dynamic_preset.py:163`).

### Why now (the conflation diagnosis)

Today's formula at `weather_manager.py:213-228`:

```
delta = forecast.apparent_high − zone_home_cool_high
```

`zone_home_cool_high` comes from `PresetManager.get_seasonal_setpoints(preset)[0]`
(`hvac_preset.py:118`) — i.e. the operator's INDOOR target (summer home = 77°F
after v4.7.3 CM overrides).

That delta source conflates two unrelated questions:

1. **"How do I want the house to feel"** — operator's indoor cool target.
2. **"What counts as a typical / mild / hot OUTDOOR day for here"** — climate norm.

Live evidence (2026-06-01 Austin TX, 91°F apparent forecast high):

| Frame | Delta | Bucket | What it tells DPM |
|---|---|---|---|
| Old (indoor target as baseline) | `91 − 77 = +14°F` | **HOT** | "extreme cooling concessions" |
| Operator's intuition | "91 is a cool day for Texas summer" | COOL | "raise the setpoint, save energy" |
| New (climate norm = ~97°F) | `91 − 97 = −6°F` | **COOL** | matches intuition |

Tuning the bucket thresholds (`CONF_DYNAMIC_PRESET_DELTA_COOL_MAX/_MILD_MAX/_HOT_MAX`)
cannot fix the conflation — it just shifts the breakpoints between
always-positive summer deltas. The operator-visible knob collapses to "how
positive counts as hot" instead of "today is cooler or hotter than typical."

### What this UNLOCKS

Once the frame is intuitive, the existing bucket-classification tuning surface
(`config_flow.py:4181-4206` Advanced section) becomes tractable: an operator
who sees `delta_f = -6` on a cool day and `delta_f = +8` on a hot day can
reason about where the bucket breakpoints should fall. Under the old frame,
no amount of threshold tuning makes DPM agree with operator intuition because
the input axis itself is in the wrong reference frame. The v4.7.16.4 README
filed this as deferred work; this cycle is that work.

---

## 2. Institutional context verified

This section is the proof-of-work that the planner consulted prior art before
proposing changes (mandatory per CLAUDE.md "Institutional Context First").

### Greps run + results

| Proposed addition | Grep | Result | Verdict |
|---|---|---|---|
| `CONF_DPM_EXPECTED_SEASONAL_APPARENT_HIGH_SUMMER` (and `_SHOULDER`, `_WINTER`) | `expected_seasonal\|climate_norm\|seasonal_apparent\|seasonal_norm\|baseline_norm\|location_climate` across `custom_components/universal_room_automation/` | **No matches.** | **NEW.** No existing CONF, helper, or sensor surfaces a per-location seasonal climate norm. |
| `CONF_DPM_USE_CLIMATE_NORM_BASELINE` (feature flag) | `dynamic_preset.*baseline\|use_climate_norm\|baseline_source` | Only matches are the v4.7.16.4 comment block in `weather_manager.py:522-571`. | **NEW.** No prior flag governing baseline source. |
| Bucket constants (reused — not added) | `BUCKET_COOL\|BUCKET_MILD\|BUCKET_HOT\|BUCKET_EXTREME` | `energy_const.py:221-225` — names + tuple already canonical. | **REUSED** at `energy_const.py:221-225`. |
| `classify_bucket()` consumer (reused — signature stable) | `classify_bucket` in `domain_coordinators/dynamic_preset.py` | `dynamic_preset.py:132` (definition), `:395` (call site inside `_recompute_zone()`). | **REUSED** — signature `(delta, cool_max, mild_max, hot_max)` is preserved; new delta semantics flow through transparently. |
| Use of `hass.config.latitude/longitude/location_name` for climate-norm derivation | `hass\.config\.latitude\|hass\.config\.longitude\|hass\.config\.location_name` | **No matches anywhere in the integration.** | URA does **not** read HA's home coordinates today. Avoiding it in this cycle preserves that property (see Open Question Q1 — derivation is operator-typed, not lat/lon-derived). |
| `PresetManager.get_seasonal_setpoints()` accessor (UNCHANGED) | `get_seasonal_setpoints` | `hvac_preset.py:118` (definition), `hvac.py:1191`, `hvac_override.py:342`, `sensor.py:7385`, `dynamic_preset.py:545`, `weather_manager.py:561` (callers). | **REUSED — not modified.** The accessor stays as-is. This cycle's change is in `_get_zone_baseline_high()` switching its baseline source AWAY from this accessor when the new flag is ON. |
| `_get_zone_baseline_high()` callers | `_get_zone_baseline_high` | Only call site is `weather_manager.py:225` inside `baseline_delta_for_zone()`. | **Single-site change.** Bug Class #49 (tuple-shape drift) risk is contained to one function. |
| `current_season` accessor (reused) | `current_season\|determine_season` | `hvac_preset.py:92` property, `hvac_preset.py:97-109` body. Already the canonical season-resolution surface. | **REUSED** at `hvac_preset.py:92`. New CONF lookup keys by season name from this accessor. |
| SEASON_* constants | `SEASON_SUMMER\|SEASON_SHOULDER\|SEASON_WINTER` | `hvac_const.py:273-276` defines the three constants. `SUMMER_MONTHS = {6,7,8,9}`, `WINTER_MONTHS = {12,1,2}`, shoulder = everything else. | **REUSED** at `hvac_const.py:273-276`. |
| Existing v4.7.3 CONF format (precedent for season×preset×dim CONFs) | `CONF_HVAC_BASELINE_` | `hvac_const.py:305-`, CM entry.options keys. | **REUSED PATTERN** — new CONFs follow the same `CONF_DPM_EXPECTED_SEASONAL_APPARENT_HIGH_<SEASON>` style and ALSO live in CM entry.options (single-source for "all DPM-shape config lives on CM"). |
| `_wpm_available()` and `_get_dynamic_preset_source()` (entity availability helpers, reused) | `_wpm_available\|_get_dynamic_preset_source` | `sensor.py:6968,6974`. | **REUSED** — bucket sensor extra_state_attributes already pulls WPM and the dynamic_preset source; new attributes just add fields. |

### Prior planning docs consulted (filename + relevance)

| Doc | Relevance |
|---|---|
| `PLANNING_v4.7.3_baseline_preset_editor.md` | **Highest relevance.** Established the pattern: per-season×per-preset CONFs persisted in CM `entry.options`, read by `PresetManager.get_seasonal_setpoints()` with `SEASONAL_DEFAULTS` fallback for graceful migration. This cycle reuses that exact pattern for climate-norm CONFs. Also tells us where the form step lives (`async_step_coordinator_hvac` menu, with `hvac_baseline_presets` sibling step). The new climate-norm fields appear on the **same** Surface 1 form rather than a new step (per Open Question Q2 recommendation). |
| `PLANNING_v4.7.4_dpm_ui_simplification.md` | **High relevance.** Surface 1 layout — house-wide settings, "Advanced (rarely change)" collapsed section. New climate-norm CONFs go in the same collapsed Advanced section to avoid cluttering the master toggle. |
| `PLANNING_v4.7.16_room_level_veto_density_weighting.md` | Sibling-cycle context only (occupancy logic, not DPM baseline). No surface overlap. |
| `PLANNING_v4.7.18_census_service_shared_refactor.md` | No DPM overlap. |
| `PLANNING_v4.7.15_universalize_bug_class_48_veto.md` | No DPM overlap. |

### Memory bodies pulled

| Memo | Relevance |
|---|---|
| `project_v4_7_x_stretch_closed.md` | DPM lineage v4.7.0 → v4.7.4.4 — confirms `dynamic_preset` is the right home; no in-flight refactor competes. |
| `project_advanced_energy_mgt_v47x.md` | WeatherProviderManager shipped in v4.7.0 — `current_apparent_forecast_high()` and the WPM cache are the foundation this cycle leans on. |
| `feedback_pre_deploy_zero_bugs_gate.md` | Pre-deploy gate (conflict markers, py_compile, suite-baseline-diff) applies to this cycle. |
| `feedback_db_sensitive_3x_targeted_reviews.md` | Verified NOT Tier 2-DB — no `database.py` changes, no DAO migrations, no dispatched-payload shape change. See §3 tier table. |

### Design doc read

`docs/Coordinator/HVAC_COORDINATOR_DESIGN.md` — confirms HVAC owns DPM post-v4.7.2, and the seasonal baseline data flows through `PresetManager`. (Note: WPM lives on the Energy Coordinator surface but is independently a hass.data singleton, NOT bound to EC's coordinator lifecycle — confirmed by `weather_manager.py:90-93`.)

### Code locations surveyed end-to-end during scoping

| File | Lines read | Why |
|---|---|---|
| `domain_coordinators/weather_manager.py` | 1-693 (entire) | The single function we're changing lives here. |
| `domain_coordinators/dynamic_preset.py` | 1-180, 380-410, 540-560 | Confirm `classify_bucket()` signature is stable, confirm downstream zone-state shape unchanged. |
| `domain_coordinators/hvac_preset.py` | 80-220 | `current_season` + `get_seasonal_setpoints` contracts. |
| `domain_coordinators/hvac_const.py` | 270-330 | `SEASONAL_DEFAULTS` shape + `CONF_HVAC_BASELINE_*` pattern. |
| `domain_coordinators/energy_const.py` | 180-260 | Where new CONFs are added — follow v4.7.1 Cycle B comment block convention at line 195. |
| `config_flow.py` | 4040-4210 | Surface 1 DPM form (`async_step_hvac_dynamic_preset`) — where new fields go. |
| `sensor.py` | 6960-7015 | `DynamicPresetBucketSensor.extra_state_attributes` — where new `baseline_source` + `expected_seasonal_high_f` attributes are added for live validation visibility. |

---

## 3. Tier classification

**Tier 1** (single staff-engineer adversarial review).

| Tier 2-DB trigger | Hit? |
|---|---|
| Touches `database.py` DAO definitions | No |
| Migrates ≥3 callers to a new DAO | No |
| Changes dispatched-payload shape | No — no signal payload changed |
| Adds behavioral test infra against real schemas | No |
| Followed by a planned schema migration | No |

| Tier 2 trigger | Hit? |
|---|---|
| New capability with multiple files / new sensors | Marginal — 3 new CONFs, 1 new feature-flag CONF, 1 modified function body, 2 new sensor attributes (added to an existing sensor). |
| Multi-file edit > 3 files | 5 files (`weather_manager.py`, `energy_const.py`, `config_flow.py`, `strings.json` + `translations/en.json`, `sensor.py`) plus the test file. |
| Cross-coordinator interaction | No — DPM signal chain, HVAC accessor surface, and EC entity tree are untouched. |

**Why Tier 1 fits:**

- The behaviour change is contained to one function (`weather_manager.py:213-228`).
- The contract is preserved: `baseline_delta_for_zone()` still returns `float | None`.
- The migration path (per Open Question Q3) makes the change opt-in behind a feature flag whose **default OFF** value reproduces v4.7.16.4 behaviour bit-for-bit.
- Bug Class #49 (tuple-shape drift) is the closest risk — but the new path doesn't read tuples at all (it reads a single `float` CONF), and the old path is preserved untouched when the flag is OFF.

**Escalate to Tier 2 if:**

- Review surfaces a need to change `classify_bucket()` thresholds in the same cycle (recommended deferral — see §6).
- Review surfaces ambiguity in how `season` is resolved when WPM and HVAC's PresetManager disagree (shouldn't happen — both go through `hvac_preset.py:92`).
- Operator's answer to Open Question Q1 picks "derived from historical weather data" — that path requires a new historical-data ingestion surface and IS Tier 2.

**Estimated size:** ~80 LoC production + ~150 LoC tests. Spread:

- `weather_manager.py`: ~25 LoC (new branch in `_get_zone_baseline_high()` + new helper `_get_climate_norm_for_season()`).
- `energy_const.py`: ~10 LoC (4 new CONFs + 4 DEFAULT_ values).
- `config_flow.py`: ~25 LoC (3 form fields + 1 feature-flag toggle, all in existing Advanced section).
- `sensor.py`: ~10 LoC (2 new attribute fields exposing `baseline_source` and `expected_seasonal_high_f`).
- `strings.json` + `translations/en.json`: ~15 LoC each (4 labels, 4 helper descriptions, 4 selector descriptions).
- Tests: ~150 LoC across `test_v4_7_17_1_dpm_climate_norm_baseline.py`.

---

## 4. Deliverables

### D1: New CONFs + defaults in `energy_const.py`

Add four CONFs and defaults under a new comment block (mirror the v4.7.1 Cycle B
header style at `energy_const.py:195`):

```python
# v4.7.17.1: Climate-norm baseline for DPM (tuning-frame redesign)
# Operator-typed per-season "typical apparent high" for the home's location.
# Used by WeatherProviderManager.baseline_delta_for_zone() when
# CONF_DPM_USE_CLIMATE_NORM_BASELINE is True. Otherwise the legacy
# indoor-cool-target baseline (v4.7.16.4 behaviour) is used.
CONF_DPM_USE_CLIMATE_NORM_BASELINE: Final = "dpm_use_climate_norm_baseline"
CONF_DPM_EXPECTED_SEASONAL_APPARENT_HIGH_SUMMER: Final = "dpm_expected_seasonal_apparent_high_summer"
CONF_DPM_EXPECTED_SEASONAL_APPARENT_HIGH_SHOULDER: Final = "dpm_expected_seasonal_apparent_high_shoulder"
CONF_DPM_EXPECTED_SEASONAL_APPARENT_HIGH_WINTER: Final = "dpm_expected_seasonal_apparent_high_winter"
# Defaults — sentinel `None` means "fall back to legacy baseline source"
# so a user who flips the flag without typing values keeps current behaviour.
DEFAULT_DPM_USE_CLIMATE_NORM_BASELINE: Final = False
DEFAULT_DPM_EXPECTED_SEASONAL_APPARENT_HIGH_SUMMER: Final = None
DEFAULT_DPM_EXPECTED_SEASONAL_APPARENT_HIGH_SHOULDER: Final = None
DEFAULT_DPM_EXPECTED_SEASONAL_APPARENT_HIGH_WINTER: Final = None
```

#### Acceptance Criteria

- **Verify:** All four CONFs are imported by at least one of `weather_manager.py` and `config_flow.py` (AST check — prevents Bug Class #32 dangling form field).
- **Test:** `test_v4_7_17_1_dpm_climate_norm_baseline.py::test_new_confs_are_imported_by_runtime_readers` walks AST of `weather_manager.py` and `config_flow.py` and asserts each new CONF name appears as an imported identifier.
- **Live:** `grep CONF_DPM_EXPECTED_SEASONAL_APPARENT_HIGH custom_components/` returns matches in BOTH `weather_manager.py` and `config_flow.py`.

---

### D2: Switch baseline source in `WeatherProviderManager._get_zone_baseline_high()`

Modify `weather_manager.py:522-571`. When `CONF_DPM_USE_CLIMATE_NORM_BASELINE`
is True AND the per-season climate-norm CONF for the current season is set
(not None) — return that float. Otherwise fall through to the existing
`PresetManager.get_seasonal_setpoints(preset)[0]` path (v4.7.16.4 behaviour).

Pseudocode (DO NOT write code in plan — shape only):

```
def _get_zone_baseline_high(zone_id, preset):
    if self._climate_norm_baseline_enabled():
        season = self._resolve_current_season()  # via hvac PresetManager
        norm = self._get_climate_norm_for_season(season)
        if norm is not None:
            return norm
        # CONF flag is on but season-specific value is unset → fall through
        # to legacy path. Logs once-per-startup at INFO level.
    # Legacy path (v4.7.16.4 behaviour, byte-for-byte preserved):
    ... existing pair[0] code ...
```

Three internal helpers (private):

- `_climate_norm_baseline_enabled() -> bool` — reads `self._options.get(CONF_DPM_USE_CLIMATE_NORM_BASELINE, False)`.
- `_resolve_current_season() -> str | None` — pulls the HVAC `PresetManager` instance and returns `current_season`. Returns None on missing PresetManager (matches existing `_get_zone_baseline_high` defensive None-return pattern).
- `_get_climate_norm_for_season(season) -> float | None` — maps `SEASON_SUMMER/SHOULDER/WINTER` to the right CONF key and returns `float | None`. Returns None on (a) unknown season, (b) CONF unset, (c) CONF set to a non-numeric value.

Add an explanatory comment block above `_get_zone_baseline_high()` modelled on
the v4.7.16.3-fix-up comment style at `weather_manager.py:526-543` so future
sessions don't have to re-derive the rationale.

#### Acceptance Criteria

- **Verify:** When `CONF_DPM_USE_CLIMATE_NORM_BASELINE = False` (default), `baseline_delta_for_zone()` returns the same value as v4.7.16.4 for the same forecast — confirmed by byte-equality on `delta_f` attribute across a deploy cycle. (Pre-deploy snapshot: capture today's `delta_f` BEFORE flipping the flag.)
- **Verify:** When flag is True and `CONF_DPM_EXPECTED_SEASONAL_APPARENT_HIGH_SUMMER = 97.0` and forecast `apparent_high = 91.0` and current season is summer, `baseline_delta_for_zone(zone_id, "home") == -6.0`.
- **Verify:** When flag is True but the per-season CONF is unset, the function transparently falls through to the legacy path (no exception, no None where the legacy path would return a value). Single INFO log line per startup confirms this branch fired.
- **Test:** `test_v4_7_17_1_dpm_climate_norm_baseline.py` includes:
  - `test_flag_off_preserves_v4_7_16_4_behaviour` — parameterised across summer/shoulder/winter seasons.
  - `test_flag_on_with_norm_returns_forecast_minus_norm` — exemplar: 91 − 97 = −6.
  - `test_flag_on_with_unset_norm_falls_through_to_legacy` — INFO log presence asserted via caplog.
  - `test_unknown_season_returns_none` — defensive.
  - `test_get_climate_norm_for_season_handles_non_numeric_conf` — defensive type coercion.
- **Live:** With flag OFF: `delta_f` attribute on `sensor.ura_energy_coordinator_dynamic_preset_bucket_<zone>` matches its pre-deploy value within ±0.1°F. With flag ON: `delta_f` shows the new frame's value (negative on a cool day in summer).

---

### D3: Surface 1 form fields in `config_flow.py`

Add the four new fields to the existing Advanced collapsed section in
`async_step_hvac_dynamic_preset` (`config_flow.py:4181-4206`). One bool, three
optional floats (defaults rendered from `_f_cm()` returning the existing
operator-set value, or empty placeholder when None).

Layout intent (top-to-bottom inside the Advanced section, after the existing
five tunables):

1. `CONF_DPM_USE_CLIMATE_NORM_BASELINE` — bool, default False.
2. `CONF_DPM_EXPECTED_SEASONAL_APPARENT_HIGH_SUMMER` — optional float, vol.Range(min=60.0, max=130.0).
3. `CONF_DPM_EXPECTED_SEASONAL_APPARENT_HIGH_SHOULDER` — optional float, vol.Range(min=40.0, max=110.0).
4. `CONF_DPM_EXPECTED_SEASONAL_APPARENT_HIGH_WINTER` — optional float, vol.Range(min=10.0, max=80.0).

Persist into CM `entry.options` (same pattern as v4.7.3) inside the existing
`cm_update` dict at `config_flow.py:4104-4119`.

`strings.json` + `translations/en.json` get labels + descriptions. Recommended
helper text for `CONF_DPM_EXPECTED_SEASONAL_APPARENT_HIGH_SUMMER`:

> "Typical outdoor apparent high temperature for a normal summer day at your
> location, in °F. For Austin TX this is around 97°F. Used by Dynamic Preset
> to compare today's forecast against the seasonal norm — a forecast at this
> value gives delta_f = 0 (MILD bucket), below gives COOL, above gives HOT."

(Mirror for SHOULDER ≈ 78°F and WINTER ≈ 55°F as illustrative defaults in helper
copy — but DO NOT ship those numbers as the CONF defaults; defaults remain None
to preserve graceful migration semantics.)

#### Acceptance Criteria

- **Verify:** Opening CM entry → Configure → HVAC → Dynamic Preset → Advanced shows the four new fields in the order specified, with helper text rendered.
- **Verify:** Submitting the form with only the flag toggled (no numbers) persists `CONF_DPM_USE_CLIMATE_NORM_BASELINE = True` and leaves the three norms absent from `entry.options`. Round-trip: re-opening the form shows the flag still True and the three numeric fields empty.
- **Verify:** Submitting with `SUMMER = 97`, `SHOULDER = 78`, `WINTER = 55` and the flag True persists all four. Reload of HA reads them back identically.
- **Test:** Config-flow runtime smoke test (per `project_config_flow_runtime_tests_backlog.md` precedent — closed in v4.7.5 D5; reuse the harness): `test_climate_norm_baseline_round_trips_through_options_flow`.
- **Test:** `test_form_field_widget_is_optional_float_with_range` — voluptuous schema introspection.
- **Live:** After save, query CM entry options via MCP `ha-mcp` config-entry-options surface and verify the four keys appear.

---

### D4: Bucket sensor attribute additions for observability

Modify `DynamicPresetBucketSensor.extra_state_attributes` at `sensor.py:6982-7012`
to add two attributes that make the active baseline source legible at a glance:

- `baseline_source`: `"climate_norm"` when the new path produced the baseline this tick; `"indoor_target"` otherwise (legacy path). Sentinel-free — never None.
- `expected_seasonal_high_f`: the float that was used as the baseline (climate-norm value when flag is on and CONF is set; indoor cool target otherwise). Same value as `baseline_high_f`. Kept as a separate attribute so the operator can see WHICH frame is active without having to consult the flag in CM options.

Implementation: add a public WPM accessor `baseline_source_for_zone(zone_id, preset) -> str`
returning the same `"climate_norm" | "indoor_target"` string. Single source of truth.

#### Acceptance Criteria

- **Verify:** `sensor.ura_energy_coordinator_dynamic_preset_bucket_<zone>` attributes show `baseline_source = "indoor_target"` when flag is OFF.
- **Verify:** After flipping flag ON with `SUMMER = 97`, attribute shows `baseline_source = "climate_norm"` and `expected_seasonal_high_f = 97.0`.
- **Test:** `test_bucket_sensor_exposes_baseline_source_attribute` — parameterised across flag-on and flag-off.
- **Live:** `ha_get_state("sensor.ura_energy_coordinator_dynamic_preset_bucket_upstairs", attribute_keys=["baseline_source", "expected_seasonal_high_f", "delta_f"])` shows the three attributes consistently.

---

## 5. Open questions for operator

These need operator answers before build starts. Best-guess defaults are
provided in italics so the build can proceed under Auto Mode if no operator
response lands, but each answer materially affects scope.

### Q1: How is the climate norm value sourced?

Three plausible mechanisms:

1. **Operator-typed per-season CONF** (3 numbers, one per season). The build
   plan above assumes this. Smallest scope. Operator picks values once based
   on their own intuition or a quick climate-data lookup.
2. **Derived from historical weather data the integration ingests over time**
   (rolling 365-day apparent-high median per month, surfaced through a new
   historical store).
3. **Derived from a third-party climate API** (e.g. Open-Meteo climate API),
   read at HA startup.

*Best-guess default: option 1.* Aligns with single-user URA philosophy
(`feedback_single_user_no_backcompat.md` — no migration ceremony), is bounded
in scope (Tier 1 stays Tier 1), and the operator already knows their own
locale better than any API. Options 2 and 3 are good Tier 2 follow-ups once
the frame is proven.

### Q2: Where in the UI does the new field live?

Two plausible homes:

1. **Inside the existing Surface 1 Advanced section** (`config_flow.py:4181-4206`).
   The build plan above assumes this. Smallest change; matches v4.7.4 D2
   layout philosophy (rare-change knobs are collapsed by default).
2. **A new dedicated CM step** (`async_step_dpm_climate_norms`) reached from
   the HVAC menu in `async_step_coordinator_hvac`.

*Best-guess default: option 1.* The four new fields are clearly tuning knobs
that share the same "rarely change, advanced" semantics as the existing five.
Adding a new step costs UX surface for marginal organisational benefit.

### Q3: What's the default when the operator hasn't configured a climate norm?

Three plausible behaviours:

1. **Fall through to legacy baseline silently** (the build plan above).
   Operator who flips the master flag but doesn't type values keeps v4.7.16.4
   behaviour — no surprise regression.
2. **Use a hardcoded continental-US default per season** (e.g. SUMMER=90,
   SHOULDER=70, WINTER=45). Risk: misleading deltas on someone's first run.
3. **Refuse to enable the flag until at least one CONF is typed** — config-flow
   validation error.

*Best-guess default: option 1.* This is the "graceful migration" property
called out in the original task brief. Operators experiment with the flag, see
that it has no effect until they type a value, type one for the current season,
and only then does the frame switch. No data loss, no regression.

### Q4: Are the existing bucket thresholds (`cool_max=-2, mild_max=8, hot_max=18`) still right under the new frame?

Almost certainly not. Under the new frame:

- `delta = -2` means "2°F cooler than typical" — that should probably still
  feel like MILD, not COOL.
- `delta = +18` means "18°F hotter than typical" — for Austin that's a 115°F
  apparent day. Should be EXTREME; current threshold says exactly EXTREME. OK.

But recalibration is a SEPARATE cycle. We need to see real `delta_f` values
under the new frame for ~1-2 weeks before tuning the thresholds with any
confidence. The current frame's thresholds remain in place for v4.7.17.1.

*Best-guess default: do not change thresholds in this cycle.* File a follow-up
backlog memo "DPM bucket-threshold recalibration under climate-norm frame"
gated on having ≥10 days of post-flag-flip `delta_f` data in the
`dynamic_preset_bucket` sensor's recorder history.

---

## 6. Migration shape

The "single-user, no-backcompat" project posture
(`feedback_single_user_no_backcompat.md`) reduces migration ceremony to the
minimum, but two properties must hold:

### Property A: Default OFF preserves v4.7.16.4 behaviour bit-for-bit

`DEFAULT_DPM_USE_CLIMATE_NORM_BASELINE = False`. With the flag absent or False
in CM `entry.options`, `_get_zone_baseline_high()` runs the exact code path
that ships in v4.7.16.4 — the `pair[0]` indexing, the same exception handling,
the same None returns on missing PresetManager.

**Verification:** D2 acceptance criterion "byte-equality on `delta_f` across
the deploy cycle when the flag stays OFF."

### Property B: Opt-in flip is monotonic and reversible

Operator flips the flag ON via Surface 1 → save → behaviour changes on the
NEXT WPM refresh cycle (≤5 minutes — bounded by WPM's state-change-driven
refresh; no special invalidation needed). Operator can flip OFF and immediately
revert to legacy behaviour. No persistent state diverges between the two
modes (the new CONFs are never read when the flag is OFF; the old path is
never modified when the flag is ON).

**Verification:** D3 acceptance criterion "flag flip + form save round-trip."

### Future deprecation path (NOT this cycle)

Once the operator has confirmed the new frame matches their intuition for a
few weeks of varied weather, a future cycle (~v4.7.20 or later) can flip the
default to True and add a deprecation INFO log on the legacy path. Eventually
(probably v5.0 at the architectural-debt sweep) the legacy path can be removed
entirely. Out of scope for v4.7.17.1.

---

## 7. What this fix UNLOCKS

(Restating §1 explicitly because §6 sits between them and this is the bottom-line
benefit reviewers should remember.)

1. **Operator-tractable threshold tuning.** Once `delta_f` carries
   "today vs typical" semantics, the existing
   `CONF_DPM_DELTA_COOL_MAX/_MILD_MAX/_HOT_MAX` knobs become operator-tunable
   in a meaningful way. Under the old frame they could not.

2. **Climate-norm sensors as first-class observability.** D4's
   `baseline_source` attribute makes the active frame legible without having
   to consult CM options — and gives the operator a Lovelace-ready field to
   pin on the DPM dashboard.

3. **Foundation for Option 2 (historical-data-derived norms)** if the operator
   later picks that path in Q1. The wiring (per-season CONF, runtime accessor,
   downstream consumers) is identical; the only new piece is the data
   producer.

4. **Cleaner mental model in incident response.** A `delta_f = +14` under the
   new frame unambiguously means "14°F hotter than typical day for this
   location" — no need to mentally subtract operator indoor preferences.

---

## 8. Plan completion tracking

Per CLAUDE.md "Plan Completion Tracking" — items explicitly deferred from this
cycle:

1. **Bucket-threshold recalibration under the new frame.** Deferred per Q4
   answer. File backlog memo upon ship of v4.7.17.1 — gated on ≥10 days of
   `delta_f` observations.
2. **Historical-weather-data ingestion path (Q1 option 2)** — Tier 2 follow-up
   if operator ever picks it. Not in scope here.
3. **Third-party climate API integration (Q1 option 3)** — same. Not in scope.
4. **Legacy-path removal / flag-default flip** — explicit v5.0 (or later)
   architectural-debt item, NOT shipped in v4.7.17.1.
5. **Lovelace card / dashboard surfacing of `baseline_source`** — operator-led
   work outside the integration repo.
6. **AC Nudge 30% false-positive rate** (the OTHER deferred item from
   v4.7.16.4) — separate investigation cycle, NOT consolidated here. Tracked
   independently in v4.7.16.4 README §"What v4.7.16.4 does NOT fix" item 2.

---

## 9. Test plan summary

New test file: `quality/tests/test_v4_7_17_1_dpm_climate_norm_baseline.py`.

| Test | Deliverable | Asserts |
|---|---|---|
| `test_new_confs_are_imported_by_runtime_readers` | D1 | AST walk catches dangling-CONF Bug Class #32 |
| `test_flag_off_preserves_v4_7_16_4_behaviour` | D2 | Byte-equal delta across summer/shoulder/winter |
| `test_flag_on_with_norm_returns_forecast_minus_norm` | D2 | 91 − 97 = −6 exemplar |
| `test_flag_on_with_unset_norm_falls_through_to_legacy` | D2 | Single INFO log + legacy delta |
| `test_unknown_season_returns_none` | D2 | Defensive |
| `test_get_climate_norm_for_season_handles_non_numeric_conf` | D2 | Defensive |
| `test_climate_norm_baseline_round_trips_through_options_flow` | D3 | Config-flow runtime smoke |
| `test_form_field_widget_is_optional_float_with_range` | D3 | voluptuous schema introspection |
| `test_bucket_sensor_exposes_baseline_source_attribute` | D4 | Attribute parity |
| `test_baseline_source_for_zone_returns_indoor_target_when_flag_off` | D4 | WPM accessor |
| `test_baseline_source_for_zone_returns_climate_norm_when_active` | D4 | WPM accessor |
| `test_tuple_shape_drift_protection_via_canonical_contract` | D2 | Bug Class #49 (pin to `hvac.py:1194` destructure) |

Total: ~150 LoC. Pattern mirrors the v4.7.16.4 `TestTupleShapeAgreement`
parallel-pinning approach to lock the canonical contract in tandem.

---

## 10. Pre-deploy gate checklist (per `feedback_pre_deploy_zero_bugs_gate.md`)

- [ ] `grep -rn '<<<<<<<\|=======\|>>>>>>>' custom_components/universal_room_automation/` returns nothing
- [ ] `python -m py_compile` on every modified file
- [ ] `PYTHONPATH=quality python3 -m pytest quality/tests/test_v4_7_17_1_dpm_climate_norm_baseline.py -v` is green
- [ ] Full-suite baseline diff against `pre-review-v4.7.17.1` tag shows zero unrelated regressions
- [ ] Pre-deploy snapshot: capture `delta_f` value of every DPM bucket sensor BEFORE deploy (operator-runnable MCP `ha-mcp` query). Required for D2 byte-equality verification.

---

## 11. Live validation steps (post-deploy)

1. Restart confirms no boot errors related to `weather_manager.py` or
   `_get_zone_baseline_high`.
2. With flag still OFF (default): `delta_f` attribute on each DPM bucket
   sensor matches its pre-deploy snapshot value within ±0.1°F. (Per D2
   acceptance.)
3. Flip the flag ON in CM → Configure → HVAC → Dynamic Preset → Advanced.
   Type `SUMMER = 97` (operator-chosen for Austin TX). Save.
4. Within 5 minutes (WPM refresh cycle): `delta_f` attribute updates to the
   new-frame value. `baseline_source` attribute switches from `"indoor_target"`
   to `"climate_norm"`. `expected_seasonal_high_f` reads `97.0`.
5. On a 91°F apparent-high day, `delta_f` should read approximately `-6.0`
   and `bucket` should resolve to `cool`.
6. No URA ERROR logs. INFO log line "DPM baseline source: climate_norm
   (season=summer, norm=97.0°F)" appears at most once per WPM refresh.
7. If anything looks off: flip the flag OFF, save — system returns to
   v4.7.16.4 baseline behaviour on the next WPM refresh. Zero data loss; no
   restart required.

---

## 12. Recall keys

- "Resume DPM climate-norm baseline"
- "Plan v4.7.17.1 tuning frame"
- "What unlocks DPM threshold tuning"
