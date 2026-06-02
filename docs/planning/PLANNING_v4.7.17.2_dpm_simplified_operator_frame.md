# PLANNING v4.7.17.2 — DPM simplified operator frame

**Status:** Awaiting operator approval (replaces v4.7.17.1 climate-norm plan)
**Tier:** Tier 1 (justified in §7)
**Predecessor:** v4.7.17.1 plan REJECTED by operator framing memo 2026-06-01
**Filed:** 2026-06-01

---

## 1. Operator product intent (restated, non-negotiable)

> "On days that feel cooler outside, relax the Home and Sleep Preset ranges. On super hot days, tighten. That's it."

- Knobs map to lived experience, not internal abstractions.
- Internal math (delta, baseline, percentile, climate norm) is implementation freedom — never exposed.
- A1 winter gate pre-approved. Cooling-only logic must not fire in heating season.
- Every change must measurably improve correctness (operator-intuition alignment); engineering elegance without correctness gain is rejected.

---

## 2. The operator-facing UX (the control surface)

**Two knobs. Both house-wide. Both in °F. Both lived-experience names.**

### Knob 1 — `dpm_cool_day_relax_f`

- **Label:** "Relax cool ceiling on cool-feeling days (°F)"
- **Range:** 0.0 – 3.0 (vol.Range)
- **Default:** 1.0
- **Unit:** °F
- **What it does, in operator language:** "When today feels cooler than recent days outside, raise the upper end of Home and Sleep cool ranges by this many °F. 0 = don't relax. 1 = 70-75 becomes 70-76 on cool days."

### Knob 2 — `dpm_hot_day_tighten_f`

- **Label:** "Tighten cool ceiling on hot-feeling days (°F)"
- **Range:** 0.0 – 3.0 (vol.Range)
- **Default:** 1.0
- **Unit:** °F
- **What it does:** "When today feels hotter than recent days outside, lower the upper end of Home and Sleep cool ranges by this many °F. 0 = don't tighten. 1 = 70-75 becomes 70-74 on hot days."

### What the operator does NOT see

No "expected seasonal apparent high" fields. No "use climate norm" toggle. No `delta_*_max` boundary fields as primary surface. No "what counts as cool / hot / extreme" thresholds. No per-season floats. No bucket override tables.

The existing master switch `CONF_DYNAMIC_PRESET_ENABLED` and the existing per-zone `CONF_ZONE_DYNAMIC_PRESET_ENABLED` opt-in stay. Two new knobs join them. Everything else listed in §5 collapses to power-user-only or gets removed.

---

## 3. The internal mechanic (single recommendation)

**Rolling 14-day median of forecast `apparent_high` as the baseline.**

`relative_delta = today_apparent_high − rolling_median_apparent_high`

- `relative_delta ≤ -2.0°F` → "cool-feeling day" → apply `+dpm_cool_day_relax_f` to all DPM cool_high values.
- `-2.0°F < relative_delta < +2.0°F` → "typical day" → no override (DPM emits nothing; existing baseline ranges in effect).
- `relative_delta ≥ +2.0°F` → "hot-feeling day" → apply `−dpm_hot_day_tighten_f` to all DPM cool_high values.

### Why rolling 14-day median (and not the other options)

- **Self-tuning, no operator config.** Operator's framing memo rule #2 ("reconsider stuff we don't need") forbids exposing per-season floats. Climate-norm CONFs fail this. Hard-coded climate-zone presets require an installer "pick your climate" step which is also a new knob.
- **Adapts to climate shift without operator intervention.** A 14-day window is long enough to smooth single-day forecast noise, short enough that seasonal transitions (e.g. mid-October cooldown) carry the baseline with them. Spring/fall noise — flagged in v4.7.17.1 implications doc Area 5a as a real risk — gets damped by the median rather than amplified by a fixed seasonal-norm number.
- **Existing `cool_high` anchor (the v4.7.16.4 frame) rejected.** Operator framing explicitly rejects "delta = forecast − cool_target" semantics. Using indoor target as the baseline is what produced "91°F is HOT" in Austin (intuition: 91°F is mild for Texas summer).
- **Hard-coded climate defaults rejected.** Single-user URA, single installation, single location — but encoding a US-wide table forces operator to either pick a climate zone (= new knob) or accept misalignment.
- **±2.0°F dead zone around the median** prevents a flickering "today is 0.3°F warmer than median" condition from triggering a transition. This is hardcoded, not exposed; it lives inside the new helper.

### Storage of the 14-day rolling window

In-memory ring of (day, apparent_high) on `WeatherProviderManager`. Hydrated lazily from `recorder.history.get_significant_states()` for the apparent-high probe of the active provider's daily forecast on first cold start. Persisted across HA restarts using `Store` (homeassistant.helpers.storage.Store) under key `ura_dpm_apparent_high_ring` — simple list of (date_iso, float). Cap = 14 entries; oldest evicted. Recorder is the source-of-truth for backfill; Store is the warm-restart cache.

If the ring has fewer than 7 entries (cold-install or post-purge), DPM emits NO overrides (returns the "no_forecast_delta" skip reason, reusing the existing taxonomy). After 7+ entries it begins emitting. This is safer than emitting against a 1-3 entry median which would swing wildly.

---

## 4. The exact file:line changes

Each entry: **Before** / **After** / **Notes**.

### P1 — `domain_coordinators/energy_const.py:206` (after the existing DPM tunables block, before `BUCKET_*`)

- **Before:** `DEFAULT_DYNAMIC_PRESET_NOTIFY_ON_TRANSITION: Final = False`
- **After:** Insert new block: `CONF_DPM_COOL_DAY_RELAX_F = "dpm_cool_day_relax_f"`, `CONF_DPM_HOT_DAY_TIGHTEN_F = "dpm_hot_day_tighten_f"`, `DEFAULT_DPM_COOL_DAY_RELAX_F = 1.0`, `DEFAULT_DPM_HOT_DAY_TIGHTEN_F = 1.0`, plus internal constants `DPM_RELATIVE_DELTA_DEADZONE_F = 2.0` and `DPM_ROLLING_WINDOW_DAYS = 14` and `DPM_ROLLING_WINDOW_MIN_DAYS = 7`.
- **Notes:** Two operator CONFs + three internal-only constants. Internal constants are NOT surfaced anywhere — code-only, no config_flow exposure.

### P2 — `domain_coordinators/weather_manager.py:213-228` (rewrite `baseline_delta_for_zone`)

- **Before:** Returns `forecast.apparent_high − self._get_zone_baseline_high(zone_id, preset)`.
- **After:** Returns `forecast.apparent_high − self._rolling_median_apparent_high()`. New semantics: positive = hotter than 14-day median; negative = cooler than median; zone_id and preset arguments retained for signature stability (callers unchanged) but ignored internally.
- **Notes:** Preset/zone args kept to avoid touching call sites in `sensor.py:6999` and `energy.py:2734`. The return type and contract (`float | None`) unchanged; only the semantic flips. This IS the v4.7.17.1 implications doc's "semantic frame drift" — but with simpler internal mechanic.

### P3 — `domain_coordinators/weather_manager.py:522-571` (delete `_get_zone_baseline_high`)

- **Before:** Defensive lookup of `PresetManager.get_seasonal_setpoints(preset)[0]`.
- **After:** **DELETED.** No callers remain after P2.
- **Notes:** Removes one of the v4.7.16.4 bug surface points. `PresetManager.get_seasonal_setpoints` itself is UNTOUCHED — still used by `hvac.py:1191`, `hvac_override.py:342`, `sensor.py:7385`, `dynamic_preset.py:545`.

### P4 — `domain_coordinators/weather_manager.py` (new methods, append near `baseline_delta_for_zone`)

- **Before:** (nothing)
- **After:** Three new helpers:
  - `_rolling_median_apparent_high() -> float | None` — returns median of in-memory ring; None if `< DPM_ROLLING_WINDOW_MIN_DAYS` entries.
  - `_record_daily_apparent_high(date, value)` — called once per day by `_refresh_all_providers_locked` when a fresh forecast lands and the date hasn't been recorded yet. Evicts oldest if ring full.
  - `async _hydrate_rolling_window_from_store()` — called from existing `async_setup` path. Loads `ura_dpm_apparent_high_ring` from `Store`, validates entries are within 21 days old (drop stale), populates ring.
- **Notes:** Persistence uses `homeassistant.helpers.storage.Store` (HA-standard, async-safe). Store write happens on every record (cheap — 14 entries max). No new DB table. **Verified via grep:** no existing `Store` usage in `weather_manager.py`; pattern matches `homeassistant.helpers.storage` standard HA convention (not URA-internal infra).

### P5 — `domain_coordinators/weather_manager.py:_refresh_all_providers_locked` (around :443, after `self._cached_forecast = WeatherForecast(...)`)

- **Before:** Forecast set; no rolling-window update.
- **After:** Add: `if self._cached_forecast and self._cached_forecast.apparent_high is not None: self._record_daily_apparent_high(date_today, self._cached_forecast.apparent_high)`.
- **Notes:** Single-line wire-up. Date dedupe lives in `_record_daily_apparent_high`.

### P6 — `domain_coordinators/dynamic_preset.py:308-348` (`evaluate_with_reason` body, around the bucket classification)

- **Before:** Builds bucket via `classify_bucket(delta, cool_max, mild_max, hot_max)`; applies per-bucket cool_high/cool_low tables.
- **After:** Replace bucket logic with a new helper `_apply_relative_delta_adjustment(home_high, sleep_high, relative_delta, relax_f, tighten_f) -> (home_high', sleep_high')` that returns adjusted highs per §3 mechanic. Buckets (COOL/MILD/HOT/EXTREME) become INTERNAL labels emitted for diagnostics only (see §5 "what we keep").
- **Notes:** This is the load-bearing change. `_BUCKET_CONF_KEYS` table is **kept** but stops being the primary lookup — see §5.

### P7 — `domain_coordinators/dynamic_preset.py` — A1 winter gate

- **Before:** No season awareness; DPM evaluates year-round whenever delta exists.
- **After:** At top of `evaluate_with_reason` after the gate-1 check, query HVAC PresetManager's `current_season` (via `manager.coordinators["hvac"]._preset_manager.current_season`). If `SEASON_WINTER`, short-circuit: `return [], "winter_season"`. New skip reason added to taxonomy.
- **Notes:** Defensive `getattr` chain matches the existing v4.7.16.4 pattern at `weather_manager.py:542-552`. Single-line short-circuit. Uses existing PresetManager state; no new accessor.

### P8 — `config_flow.py:4076-4207` (DPM Surface 1)

- **Before:** Master toggle + Advanced section (`{"collapsed": True}`) with 5 existing tuning Numbers (cool_max/mild_max/hot_max/dwell/hysteresis).
- **After:** Master toggle + 2 NEW visible Number fields (relax_f, tighten_f). Advanced section collapsed by default, contents become {dwell_minutes, hysteresis_f} only — bucket boundary CONFs removed from the form (see §5 P9). Validation block at :4089-4100 deletes the cool_max < mild_max < hot_max check.
- **Notes:** Cool/Mild/Hot delta CONFs become internal-only with hardcoded sensible defaults; they remain in `energy_const.py` to keep `classify_bucket()` callable for diagnostic-only bucket labelling.

### P9 — `sensor.py:7003-7010` (`DynamicPresetActiveBucketSensor.extra_state_attributes`)

- **Before:** Exposes `delta_f`, `apparent_high_f`, `baseline_high_f`.
- **After:** Rename `delta_f` → `relative_delta_f` (semantic accuracy). Rename `baseline_high_f` → `rolling_median_apparent_high_f`. Add new attribute `cool_high_adjustment_f` (signed float: positive on cool days, negative on hot days, 0.0 in dead zone). The bucket state-value (cool/mild/hot/extreme) stays — derived from `classify_bucket` against fixed internal thresholds, used as diagnostic label only.
- **Notes:** Attribute renames are operator-visible. The bucket label keeps showing because operators have been seeing it; it just no longer drives the override.

### P10 — `strings.json` + `translations/en.json`

- **Before:** Existing labels for 5 advanced tunables.
- **After:** Add 2 new labels + description strings for relax_f and tighten_f. Remove (or leave dead, harmless) the 3 boundary-CONF labels. Helper text for relax_f: "How many °F to raise the Home/Sleep cool ceiling on days the forecast feels cooler than the last 2 weeks. 0 = off." Mirror for tighten_f.
- **Notes:** No translation churn beyond the 4 strings (2 labels + 2 descriptions).

### P11 — Tests (NEW file `quality/tests/test_v4_7_17_2_dpm_simplified_frame.py`)

- **Before:** No test file.
- **After:** Tests for:
  - `_rolling_median_apparent_high` returns None below 7 entries
  - `_rolling_median_apparent_high` returns mathematical median at 7-14 entries
  - Date-deduped recording (same date called twice → ring size unchanged)
  - Ring eviction at 15th entry
  - Store round-trip across simulated restart
  - `baseline_delta_for_zone` byte-equality assertion REMOVED (semantic deliberately changed)
  - `evaluate_with_reason` returns ([], "winter_season") under SEASON_WINTER
  - Cool-day adjustment: relative_delta=-3.0, relax_f=1.0 → home_high += 1.0
  - Hot-day adjustment: relative_delta=+4.0, tighten_f=1.5 → home_high -= 1.5
  - Dead-zone: relative_delta=+1.5, both knobs nonzero → no adjustment
  - Migration: pre-deploy CM options with `dynamic_preset_delta_cool_max=-2.0` survive read (key not crashed on) but are not read by runtime — test asserts options dict still intact after first WPM refresh.
- **Notes:** ~180 LoC. Tests drive production code paths, no hand-rolled DDL.

---

## 5. What we KEEP (load-bearing infrastructure)

| Surface | Decision | Why |
|---|---|---|
| `DynamicPresetOverrideSource` class | **KEEP.** Still the single emitter of DPM overrides. | Plumbing into `PresetOverride` records, `OVERRIDE_SOURCE_DYNAMIC_PRESET`, EC tick integration all stay. |
| `_active_bucket` / `_last_transition_at` state | **KEEP** — bucket becomes a diagnostic label. | RestoreEntity-backed; cross-restart durability. Bucket transitions still drive `SIGNAL_DYNAMIC_PRESET_TRANSITIONED` for observability. |
| Dwell-window mechanism (`CONF_DYNAMIC_PRESET_DWELL_MINUTES`) | **KEEP** as power-user knob in Advanced section. | Prevents flicker when relative_delta hovers near the ±2°F dead zone boundary. Default 60 min. |
| Hysteresis (`CONF_DYNAMIC_PRESET_HYSTERESIS_F`) | **KEEP** as power-user knob in Advanced section. | Same anti-flicker rationale. Default 2.0°F. |
| `SIGNAL_DYNAMIC_PRESET_TRANSITIONED` dispatch | **KEEP** — payload `delta_f` field renamed to `relative_delta_f`. | Listeners (`sensor.py:6916, 6955`, `sensor.py:7156`) don't read the field; rename is safe. |
| `classify_bucket()` function | **KEEP** for diagnostic bucket label only. | Bucket state-value on the sensor is operator-visible familiarity; downstream not driven by it. |
| `_BUCKET_CONF_KEYS` table | **KEEP** in `energy_const.py` but unused at runtime. | Used by tests + diagnostic comparison only. Removal is a future cleanup, not this cycle. |
| `CONF_ZONE_DYNAMIC_PRESET_ENABLED` per-zone opt-in | **KEEP.** | Operator must still pick which zones DPM touches. |
| `CONF_ZONE_DYNAMIC_PRESET_SLEEP_ENABLED` per-zone | **KEEP.** | Sleep preset opt-in stays per-zone. |
| `CONF_ZONE_DYNAMIC_PRESET_OFFSET` per-zone | **KEEP.** | Zone-specific bias (e.g. Back Hallway +1°F) stays. Applied AFTER the relax/tighten adjustment. |
| `CONF_ZONE_DYNAMIC_PRESET_RESET_OFFSET_GUEST` | **KEEP.** | Guest-mode interaction unchanged. |
| `SEASONAL_DEFAULTS` in `hvac_const.py` | **KEEP UNTOUCHED.** | Still drives `PresetManager.get_seasonal_setpoints`. DPM no longer reads it directly. |
| `CONF_DYNAMIC_PRESET_ENABLED` master | **KEEP.** | Master kill switch. |
| `CONF_DYNAMIC_PRESET_NOTIFY_ON_TRANSITION` | **KEEP.** | Operator-set behavior. |
| Existing config_flow Advanced section | **KEEP, simplified.** Now holds {dwell, hysteresis} only. | Reduces visible surface; preserves power-user reach. |
| `DynamicPresetActiveBucketSensor` | **KEEP** with renamed attributes (P9). | Restored bucket label still meaningful as diagnostic. |
| `DynamicPresetRangeSensor` / `DynamicPresetOverridesAppliedSensor` | **KEEP UNTOUCHED.** | Read from `PresetOverride` records, not from delta math. |

---

## 6. What we REMOVE (engineering leaks)

| Surface | Decision | Rationale |
|---|---|---|
| Old delta semantic `forecast - cool_target` | **REMOVED.** | Operator framing explicitly rejects. New: `forecast - rolling_median`. |
| `CONF_DYNAMIC_PRESET_DELTA_COOL_MAX` (form field) | **REMOVED from config_flow.** CONF stays in const for diagnostic-only `classify_bucket`. | Internal threshold, not operator UX. |
| `CONF_DYNAMIC_PRESET_DELTA_MILD_MAX` (form field) | **REMOVED from config_flow.** | Same. |
| `CONF_DYNAMIC_PRESET_DELTA_HOT_MAX` (form field) | **REMOVED from config_flow.** | Same. |
| `_get_zone_baseline_high()` helper | **DELETED.** | No callers after P2. Removes a v4.7.16.4-class bug surface entirely. |
| Per-bucket bucket override tables (`CONF_ZONE_DYNAMIC_PRESET_<BUCKET>_HOME_<LOW/HIGH>` × 16 fields) | **NOT REMOVED in this cycle (data preserved); not read at runtime.** | Operator may have hand-tuned bucket cells. Leaving them in `entry.options` causes no harm; runtime ignores them. Cleanup is a future v5.0 architectural-debt sweep. |
| Climate-norm CONFs (`CONF_DPM_EXPECTED_SEASONAL_APPARENT_HIGH_*`) | **NEVER SHIPPED.** | v4.7.17.1 plan rejected pre-build. |
| `use_climate_norm_baseline` flag | **NEVER SHIPPED.** | Same. |
| Bucket-boundary validation check at `config_flow.py:4099` | **REMOVED.** | The CONFs are no longer form fields; the cross-field check is meaningless. |

---

## 7. A1 winter gate — where it lives

Lives in `dynamic_preset.py` at the top of `evaluate_with_reason`, immediately after the "gate-1 zone opted-in" check (`:378`). Single short-circuit:

```
if current_season == SEASON_WINTER:
    return [], "winter_season"
```

`current_season` is read defensively from `hass.data[DOMAIN]["coordinator_manager"].coordinators["hvac"]._preset_manager.current_season` with a `getattr`-chain fallback (matches the v4.7.16.4 pattern at `weather_manager.py:542-552`). On any chain-miss, default to NOT-winter (fail-open) — DPM proceeds and emits cooling adjustments, which is the v4.7.16.4 baseline behavior. This preserves correctness on degraded HVAC state.

**Why here (and not in `weather_manager.py`)**: putting the gate in WPM would silently zero the delta for ALL consumers of `baseline_delta_for_zone`, including the diagnostic sensor attribute. Putting it in DPM keeps the WPM frame honest (the rolling delta is meaningful year-round for observability) while preventing DPM from emitting cooling overrides in heat-mode.

**Adds skip reason "winter_season" to the taxonomy** at `dynamic_preset.py:336` docstring + the diagnostics sensor that exposes `skipped_zones_with_reason` (already wired via v4.7.7 B2).

---

## 8. Tier classification

**Tier 1.**

Justification:
- Single-function semantic change in WPM (`baseline_delta_for_zone` body).
- One-function semantic change in DPM (`evaluate_with_reason` adjustment math).
- One winter-gate short-circuit.
- No `database.py` changes; no DAO migration; no dispatched-payload SHAPE change (the `delta_f` key in `SIGNAL_DYNAMIC_PRESET_TRANSITIONED` is renamed but no listener reads it — verified in implications doc Area 1d).
- New persistence via `Store` is HA-standard, not a URA DB migration.
- New CONFs (2) follow existing pattern; backward-compat = legacy CONFs simply unread (operator's values dormant in `entry.options`).
- Total LoC: ~120 production + ~180 tests.

Escalate to Tier 2 only if review surfaces issues with the Store hydration race against `_refresh_all_providers` (recommend a focused review pass on that interaction).

---

## 9. Open questions for operator

### OQ-1: Should the 2 new knobs be split into Home and Sleep separately?

Current proposal: one `relax_f` knob applies to BOTH home and sleep cool_high; one `tighten_f` knob applies to BOTH. The operator's verbatim language ("relax the Home and Sleep Preset ranges") uses both presets in one breath — implying one knob each suffices.

**Recommended default: keep as proposed (2 knobs, not 4).** Splitting to per-preset doubles the surface for marginal correctness gain. Sleep preset already has its own per-zone OFFSET via existing `compute_sleep_high(home_high, zone_offset)` — the operator already has per-zone fine control there. Flag for redirect if operator wants per-preset knobs.

### OQ-2: 14-day window length

Recommended default: 14 days. Shorter (7) makes the median more reactive but noisier; longer (30) lags seasonal transitions. 14 is the empirically-balanced choice for HVAC tuning literature and matches the 2-week "feels like" reference frame the operator's framing uses ("days that feel cooler"). Flag for redirect if operator has a different preferred window.

---

## 10. Acceptance hypothesis (shipwatch YAML)

```yaml
acceptance:
  - id: dpm_v4_7_17_2_cool_day_relax_correctness
    description: >
      On a day where today's forecast apparent_high is at least 2°F below the
      14-day median, and dpm_cool_day_relax_f = 1.0, every DPM-enabled zone's
      emitted home cool_high override is exactly 1.0°F above what the same
      zone's home cool_high would be with DPM master switch OFF.
    falsifiable_by:
      - "Override emitted == baseline cool_high (no adjustment applied)"
      - "Override emitted differs from baseline by something other than +1.0°F"
    measurement:
      - sensor: sensor.ura_energy_coordinator_dynamic_preset_bucket_<zone>
        attribute: cool_high_adjustment_f
        expected: 1.0
      - cross_check:
          override_engine_final_cool_high vs (PresetManager seasonal cool_high + zone_offset)
        expected_diff: 1.0
    window: first 14 days post-deploy with ≥1 cool-feeling day
  - id: dpm_v4_7_17_2_winter_gate
    description: >
      During SEASON_WINTER (Dec/Jan/Feb), DPM emits zero overrides for every
      DPM-enabled zone, regardless of forecast.
    falsifiable_by:
      - "Any PresetOverride record with source=dynamic_preset emitted during winter"
    measurement:
      - sensor_attr: skipped_zones_with_reason
        expected_contains_for_all_zones: "winter_season"
    window: any tick during current_season == winter
```

---

## 11. Migration shape

**First restart after deploy:** byte-identical visible behavior for the first 7 days, because the rolling-window ring is empty and DPM short-circuits with `skip_reason = "no_forecast_delta"` (existing taxonomy, same UX as a stale forecast). From day 7 onward, DPM begins emitting against the rolling median.

**Operator's existing CONF values for the 3 removed boundary CONFs** stay dormant in `entry.options` — unread by runtime, harmless. No migration code, no entry-version bump.

**Default values for the 2 new CONFs** are 1.0°F each (the operator's own example in the framing memo: "70-75 → 70-76 on cool day, 70-74 on hot day"). On first read of CM options post-deploy, defaults take effect immediately.

**Feature-flag-default-OFF migration NOT recommended.** Operator framing rejected the v4.7.17.1 use_climate_norm flag explicitly. The cleaner migration is the natural cold-window pause: behavior is identical to v4.7.16.4 for 7 days (no override emission), then naturally activates with sensible defaults. No flag needed.

**Rollback:** If correctness regresses, operator flips master `CONF_DYNAMIC_PRESET_ENABLED` to OFF. No restart required. To revert to v4.7.17.1's frame, redeploy that version — both knobs' CONF keys are independent of v4.7.17.1 keys so no conflict.

---

## 12. Plan completion tracking (items explicitly deferred)

1. **Removal of unused per-bucket zone tables** (16 CONFs × per-zone). Deferred to v5.0 architectural-debt sweep. Cells stay in `entry.options` dormant.
2. **Per-preset (Home vs Sleep) knob split** (see OQ-1). Backlog memo if operator picks redirect.
3. **Persistence of bucket label across format changes** (RestoreEntity already handles this; no new work).
4. **Documentation update** — `docs/user-manual/DYNAMIC_PRESET.md` formula text. Bundled with cycle deploy as a same-PR doc fix (~10 LoC). Not a separate deliverable.
5. **`DynamicPresetActiveBucketSensor` state value** — stays as bucket label for operator familiarity. Future cleanup: rename to `relative_temperature_class` or similar; defer.

---

## Executive summary

1. Two knobs, both °F, both house-wide, both lived-experience names — `dpm_cool_day_relax_f` (default 1.0) and `dpm_hot_day_tighten_f` (default 1.0). Everything else collapses to power-user or removed.
2. Internal mechanic = rolling 14-day median of forecast apparent_high (self-tuning, zero operator config, persisted via HA `Store`); climate-norm CONFs from v4.7.17.1 explicitly never ship.
3. A1 winter gate lives in `dynamic_preset.py` evaluate_with_reason as a one-line short-circuit returning skip_reason `"winter_season"`.
4. Tier 1, ~120 LoC prod + ~180 LoC tests; legacy CONFs left dormant in `entry.options` (no migration code); first 7 days post-deploy are no-op while the ring fills (clean migration without a feature flag).
5. Two open questions only: per-preset knob split (OQ-1, recommend NO) and window length (OQ-2, recommend 14). Approve as-is or redirect.
