# PLANNING v4.7.17.1 — DPM climate-norm baseline — IMPLICATIONS REPORT

**Filed:** 2026-06-01
**Companion to:** `PLANNING_v4.7.17.1_dpm_climate_norm_baseline.md`
**Purpose:** Pre-build wider-implications inventory. Operator approves the
"precise changes the build would make" list below, or redirects.

---

## Executive summary

1. The delta semantic flip touches **2 production callers** of
   `baseline_delta_for_zone()` (`sensor.py:6999` for attribute exposure;
   `energy.py:2734` for DPM evaluation) and **1 reactive signal payload**
   (`SIGNAL_DYNAMIC_PRESET_TRANSITIONED.delta_f` at `dynamic_preset.py:455`).
   All three are downstream-passive: they consume the float, they do not assume
   its sign convention. Flipping the source of truth is invisible to them.
2. DPM in-memory state (`_active_bucket`, `_last_transition_at`) is **not
   semantically tied** to the old delta frame — it stores BUCKET LABEL, not
   delta value — so restored state survives the flip without re-classification
   penalty beyond the first WPM refresh. **No DB-persisted DPM state.**
3. Heat-mode is **not currently considered** by DPM. DPM only reads `"home"`
   preset's cool setpoint. Under the new climate-norm frame this asymmetry
   surfaces: a delta of −20 in winter means "20°F colder than typical winter
   day," but DPM's bucket labels still drive COOL→raise setpoint (i.e. cooling
   actions) overrides. Winter activation is the biggest hidden risk and the
   plan does not address it.
4. The plan's "Surface 1 Advanced section" placement is consistent with v4.7.4
   D2 precedent but loses one property: climate norm is **location-derived**
   (rarely changes when the operator moves), while the existing 5 Advanced
   tunables are **behavioural tuning knobs** (operator-adjusted to taste).
   Conflating them in the same section is workable but a future
   re-organisation would benefit from a "Location & climate" subsection.
5. Default-OFF + sentinel-None preserves byte-for-byte legacy behaviour. The
   one verified migration risk is **state restoration of the bucket label**
   when the flag is later flipped ON: the restored bucket may briefly disagree
   with the fresh climate-norm classification for one WPM refresh cycle
   (≤5 min); existing dwell logic suppresses spurious transitions. Acceptable.

**Recommendation:** Approve plan as written with **two amendments**:
(a) Add an explicit "do not classify in heating season" gate inside
`baseline_delta_for_zone()` — or document that DPM intentionally only runs
when `current_season == SEASON_SUMMER`. (b) Add D5: bump
`docs/user-manual/DYNAMIC_PRESET.md:32` formula text — currently incorrect
and will become more incorrect.

---

## Area 1 — Downstream consumers of the delta semantic

### 1a. Callers of `WeatherProviderManager.baseline_delta_for_zone()`

Grep across the integration finds **two production call sites**:

| Site | File:line | Use | Sign-convention dependency? |
|---|---|---|---|
| Bucket sensor attributes | `sensor.py:6999` | `delta_f = mgr.baseline_delta_for_zone(self._zone_id, "home")` then `baseline_high = apparent_high - delta_f` | **Yes — but downstream-passive.** Computes `baseline_high` by reversing the formula. Under the new frame `baseline_high` will surface the climate norm (e.g. 97°F) instead of the indoor target (77°F). That's actually a feature, not a bug — operator wanted this. But the attribute is **named** `baseline_high_f` which implied "indoor target" in v4.7.16.4 — the name now lies. |
| DPM tick | `energy.py:2734` | `delta = weather_mgr.baseline_delta_for_zone(zone_id, "home")` → passed to `_dynamic_preset_source.async_evaluate_with_reason(... delta=delta ...)` | **No.** DPM passes the float to `classify_bucket(delta, cool_max, mild_max, hot_max)` (`dynamic_preset.py:395`). The classifier is sign-agnostic — it just compares against thresholds. |

Test references (informational, not behavioral consumers):
`quality/tests/test_hotfix_v4_7_16_3_dpm_baseline.py:165` asserts the
function exists and references `delta_f` + `baseline_high_f` attribute names.

### 1b. Callers of `classify_bucket()`

| Site | File:line | Notes |
|---|---|---|
| `_recompute_zone` / `evaluate_with_reason` | `dynamic_preset.py:395` | Sole call site. Sign-agnostic by signature `(delta, cool_max, mild_max, hot_max)`. |

The classifier's thresholds are absolute breakpoints. Under the new frame,
the **same delta value carries different meaning** — that's the whole point —
but the classifier itself doesn't care. Threshold recalibration is correctly
deferred per plan Q4.

### 1c. Sensors exposing `delta_f` / `baseline_high_f` / `apparent_high_f`

Only **one sensor** exposes them: `DynamicPresetActiveBucketSensor`
(`sensor.py:6873-7012`). Attributes built at `sensor.py:7003-7010`:
```
"delta_f": round(delta_f, 1) if delta_f is not None else None,
"apparent_high_f": apparent_high,
"baseline_high_f": baseline_high,
```

No other entity reads them. No automation/template-sensor consumers found.

### 1d. `SIGNAL_DYNAMIC_PRESET_TRANSITIONED` payload

Defined at `signals.py:92-93`. Payload includes `delta_f`. Dispatch site:
`dynamic_preset.py:451-457`. Listeners:

| Listener | File:line | Reads `delta_f`? |
|---|---|---|
| `DynamicPresetActiveBucketSensor._on_transition` | `sensor.py:6916,6955` | No — just triggers `async_write_ha_state()`. |
| `DynamicPresetOverridesAppliedSensor._on_signal` | `sensor.py:7156` | No — same. |

**Verdict:** the `delta_f` field is dispatched but no listener reads it. Flipping
the semantic does not break any consumer. The field is purely for log/debug
visibility.

### 1e. `_get_zone_baseline_high()` (the function the plan modifies)

Single call site: `weather_manager.py:225` inside `baseline_delta_for_zone()`.
No other reader. Contained surgical change.

---

## Area 2 — Cached state and persistence

### 2a. In-memory state in `DynamicPresetOverrideSource`

Located at `dynamic_preset.py:251-252`:
```
self._active_bucket: dict[str, str] = {}
self._last_transition_at: dict[str, datetime] = {}
```

State is **bucket label + transition timestamp** — not delta values. Under
flip, the bucket label is what gets compared against the freshly-classified
bucket from the new frame. Two scenarios:

1. **Flag flipped OFF → behaviour:** identical to v4.7.16.4. `_active_bucket`
   contents stable.
2. **Flag flipped ON → first WPM refresh after save:** `delta` now carries
   new-frame value. `fresh_bucket = classify_bucket(delta, ...)` may disagree
   with `_active_bucket[zone_id]`. The existing dwell (`dwell_min`) +
   hysteresis (`_passed_boundary_with_buffer`) gates at
   `dynamic_preset.py:419-441` **already protect against rapid flapping.**
   The transition fires once dwell elapses, which is correct behaviour — the
   operator EXPECTS the bucket to re-classify under the new frame.

### 2b. DB writes of bucket / delta state

Searched `database.py` for `dynamic_preset`, `bucket`, `delta_f`,
`baseline_delta`: **no DB persistence of DPM state.** DPM uses RestoreEntity
on the sensor (not the DAO layer) per plan Cycle B B3 design. Confirmed at
`database.py` — only references are unrelated `last_magnitude_bucket`
(anomaly DAO), `room_energy_baselines` (sensor calibration baselines —
different domain), and word matches in unrelated docstrings.

### 2c. RestoreEntity-backed sensors with stored delta semantics

`DynamicPresetActiveBucketSensor` is RestoreEntity (`sensor.py:6873`). It
restores **bucket label only** (`sensor.py:6938` reads `last_state.state`,
which is the bucket string `"cool" | "mild" | "hot" | "extreme"`), plus
`last_transition_iso` (timestamp). Neither is delta-frame-dependent.

**Restoration risk:** if HA restarts AFTER the operator flipped the flag ON,
the restored `_active_bucket = "hot"` may disagree with the post-restart
fresh-classified bucket under the new frame. This is identical to the
"first refresh after flip" scenario in 2a — same protection applies.

### 2d. Pre-flag state surviving a post-flag deploy

Operator deploys v4.7.17.1 with flag OFF default. No restored-state mismatch.
Later, operator flips flag ON and saves CM options. NO restart needed (per
plan §6 Property B). DPM tick re-evaluates against new frame on next EC
decision tick (5-min cadence). Existing dwell/hysteresis suppresses spurious
transitions. **Acceptable.**

---

## Area 3 — UX surface: where the new config lives

### 3a. Plan's choice (Surface 1 Advanced section) — verified placement

The plan puts the 4 new CONFs in `async_step_hvac_dynamic_preset`
(`config_flow.py:4057`) inside the existing `"advanced"` voluptuous section
at `config_flow.py:4181-4206`. That section is already collapsed-by-default
(`{"collapsed": True}`) and currently holds the 5 tuning knobs.

**This is consistent with v4.7.4 D2 precedent.** But it has one subtle
property mismatch:

- The existing 5 tunables (`DELTA_COOL_MAX`, `DELTA_MILD_MAX`, `DELTA_HOT_MAX`,
  `DWELL_MINUTES`, `HYSTERESIS_F`) are **behavioural taste knobs** — operator
  adjusts to make DPM more/less aggressive.
- The proposed 4 new CONFs (`USE_CLIMATE_NORM_BASELINE` +
  `EXPECTED_SEASONAL_APPARENT_HIGH_{SUMMER,SHOULDER,WINTER}`) are
  **location-property facts** — operator types them once and never touches
  them again unless they move house.

**Recommendation:** acceptable for v4.7.17.1 (no need to grow scope), but a
future cycle should consider a "Location & climate" sub-section. Operator
decision needed — see Open Question OQ-1.

### 3b. Is this the right architectural place? (HVAC vs Energy)

Climate norm is **location data** (Energy Coordinator owns weather), but DPM
itself migrated to HVAC ownership in v4.7.7 B3. The DPM form already lives
under HVAC (`async_step_coordinator_hvac` → `hvac_dynamic_preset`). The CONFs
are stored on the CM `entry.options` (single source of truth — same place as
the existing 5 tunables). **Correct placement.** No EC/HVAC ownership conflict.

### 3c. Other UX surfaces that may need to know

| Surface | Today | After flip | Action |
|---|---|---|---|
| `DynamicPresetActiveBucketSensor` attrs | exposes `delta_f`, `baseline_high_f`, `apparent_high_f` | values shift meaning under flag ON | **D4 in plan addresses this** — adds `baseline_source` + `expected_seasonal_high_f` attrs. Adequate. |
| `docs/user-manual/DYNAMIC_PRESET.md:32` | Documents formula `delta = apparent_forecast_high − zone_home_cool_high` | Outdated when flag is ON | **Plan does NOT update this.** Recommend new D5 deliverable. |
| `docs/user-manual/DYNAMIC_PRESET.md:120` | Documents `hysteresis_f` in delta units | Still correct (delta is delta) | No action. |
| `docs/ENERGY_MANAGEMENT_EXPLAINER.md:560` | One-liner reference to `baseline_delta_for_zone() → delta` | Vague enough to survive | Optional update. |
| Dashboard YAML | No URA-shipped dashboards reference `delta_f` (verified) | n/a | None — operator-led PWA work. |
| Observation toggles | DPM has master toggle `CONF_DYNAMIC_PRESET_ENABLED` and switch `switch.ura_energy_coordinator_dynamic_preset_overrides` | New flag is independent | None. |
| Energy reports / sensors | No EnergyReports consumer reads `delta_f` (verified by grep) | n/a | None. |

### 3d. Helper text / field shape — operator-visible UX

Plan §D3 proposes one bool + three optional floats with `vol.Range`
limits and recommended helper text. Field shape: **single number per
season.** Helper text examples: Austin TX → SUMMER ≈ 97°F. Pattern matches
existing optional-float fields elsewhere in the integration.

One nit: plan's `vol.Range(min=10.0, max=80.0)` for WINTER allows
sub-freezing values but rejects "55" if operator types it for a southern
city; the range is fine but the **helper text MUST give a few exemplar
values** so operators in different climates have an anchor. Plan's
recommended helper text covers Austin only — recommend including a colder-
climate example (e.g. "Minneapolis January ≈ 22°F").

---

## Area 4 — Migration risks

### 4a. First-restart-after-deploy with flag default OFF

Sequence:
1. HA boots, loads CM entry.options. `CONF_DPM_USE_CLIMATE_NORM_BASELINE`
   absent or False (default).
2. WPM `__init__` reads options — new CONF reads return defaults.
3. EC tick → DPM tick → `weather_mgr.baseline_delta_for_zone()` → flag-off
   branch → `pair[0]` legacy code path (`weather_manager.py:561-564`).
4. Identical behaviour to v4.7.16.4. Verified by plan's D2 byte-equality
   acceptance criterion.

**No race.** The CONF read is synchronous from `self._options` dict; no async
load.

### 4b. Operator turns flag ON without setting any climate norm CONF

Per plan §D2 pseudo:
```
if self._climate_norm_baseline_enabled():
    season = self._resolve_current_season()
    norm = self._get_climate_norm_for_season(season)
    if norm is not None:
        return norm
    # CONF flag is on but season-specific value is unset → fall through
```

Graceful fallthrough to legacy path. Single INFO log per startup.

**Verification needed:** the plan's pseudo says "fall through to legacy
path" but the legacy path returns `pair[0]` (the indoor cool target). That
means the operator who flips the flag WITHOUT setting the climate norm
sees **NO behaviour change** — confusing. The INFO log will help, but
recommend the bucket-sensor attribute `baseline_source` (plan D4) read
`"indoor_target_fallback"` instead of `"climate_norm"` so the operator can
see the fallback at a glance.

### 4c. Operator sets `climate_norm = current_cool_high` (byte-identical to legacy)

If the operator sets SUMMER=77 (i.e. same as the v4.7.3 home cool target),
`baseline_delta_for_zone` returns `forecast.apparent_high - 77.0`. Identical
to legacy. **Math verified.**

### 4d. Interaction with CM-level cool target overrides

The operator's live CM overrides summer home cool to 75°F (per the original
brief). Today's flow:
- `get_seasonal_setpoints("home")` reads CM `entry.options` for
  `CONF_HVAC_BASELINE_SUMMER_HOME_COOL` (`hvac_preset.py:162-172`).
- That value (75.0) flows into `_get_zone_baseline_high()` →
  `baseline_delta_for_zone()` returns `forecast - 75`.

Under the new flag ON:
- The legacy fall-through path STILL reads `pair[0]` and returns
  `forecast - 75` if the climate norm CONF is unset.
- If the climate norm CONF is set (e.g. SUMMER=97), the override is **bypassed**
  for DPM purposes — DPM uses 97 instead of 75.

**This is correct behavior** (climate norm should be location-derived, not
operator's indoor preference) — but operator should be aware the CM-level
indoor-target override no longer feeds DPM under the new frame. **Document
this in the helper text and/or D5 user-manual update.**

### 4e. No restart required for flip

Plan §6 Property B asserts no restart needed. Verified — the runtime branch
reads `self._options.get(CONF_DPM_USE_CLIMATE_NORM_BASELINE, False)` each
call. The `_options` dict is the live CM entry.options reference (WPM
constructor binds it). Options updates via `async_update_entry` propagate
within the same event loop. Next WPM refresh (≤5 min) picks up new flag.

---

## Area 5 — Edge cases

### 5a. Shoulder-season correctness

Operator types SHOULDER=78 for Austin. March cool day: forecast 70°F apparent,
delta = 70 − 78 = −8°F → COOL bucket → DPM raises cool_high setpoint to
encourage coasting. **Is this what the operator wants in March?**

In March a 70°F day is actually nice — AC may be off most of the day —
and DPM "raise setpoint to save energy" is a no-op when AC isn't running.
However, if DPM blindly raises `cool_high` to e.g. 80°F and the operator's
existing `home` schedule has indoor target 73°F, the operator may notice
warm-side drift.

**Risk:** the climate-norm frame assumes a roughly-symmetric weather/season
relationship. Shoulder seasons in temperate climates have wide
day-to-day variance (40-80°F range over a week is common); a single SHOULDER
norm value will produce noisy bucket transitions.

**Mitigation:** plan correctly defers threshold recalibration. Recommend
documenting that shoulder-season norm is the **median**, not the mean, and
expect more bucket churn there. **Operator decision:** OQ-2 below.

### 5b. Winter / heat mode — BIGGEST HIDDEN RISK

**DPM has NO heat-mode awareness today.** Verified:

- `dynamic_preset.py` mentions only "home" / "sleep" presets; no "heat" path
- `weather_manager.py:213` `baseline_delta_for_zone(zone_id, preset="home")`
  hardcodes preset name — `pair[0]` is the **cool** setpoint regardless of
  season
- `energy.py:2734` always calls with `preset="home"`
- DPM bucket overrides at `dynamic_preset.py:600-607` set `cool_low` /
  `cool_high` only — no heat setpoints

In winter, a 35°F apparent forecast vs WINTER norm of 55 → delta = -20 →
COOL bucket. DPM emits "raise cool_high to coast" override. The cooling
override is **meaningless** when the system is running heat mode — HA's HVAC
won't honor a cool_high override during heating.

But it gets worse under the new frame: WINTER deltas will be more
**volatile** (typical winter day variance is ±15°F), so DPM will churn
through bucket transitions all winter long, dispatching
SIGNAL_DYNAMIC_PRESET_TRANSITIONED signals, polluting logs, and consuming
the `dwell_minutes` budget.

**Plan does not address this.** Plan Q4 mentions "EXTREME" threshold for hot
days, never discusses winter.

**Recommended amendment to plan (HIGH risk):** add an explicit gate inside
`_climate_norm_baseline_enabled()` or `baseline_delta_for_zone()` that
returns None when `current_season == SEASON_WINTER`. This is a single-line
addition and preserves DPM's original implicit "summer only" assumption.
Alternatively, document that DPM is summer-only and recommend operators
disable the master `CONF_DYNAMIC_PRESET_ENABLED` switch in winter.

**See OQ-3 — operator decision.**

### 5c. Forecast staleness

Legacy code at `weather_manager.py:220-222`:
```
forecast = self._cached_forecast
if forecast is None or forecast.apparent_high is None:
    return None
```

No explicit staleness check in `baseline_delta_for_zone()`. Staleness is
handled inside `_check_provider_health()` (`weather_manager.py:282-290`) —
if provider is stale, it's filtered out before forecast is cached, so
`_cached_forecast` itself is implicitly "freshest available" or None.

**Under new frame:** same behavior. If `forecast` is None, function still
returns None before reading the new norm CONF. DPM still skips with reason
`no_forecast_delta`. **No regression.**

### 5d. Per-zone climate norm vs house-wide

Plan proposes 3 house-wide CONFs (one per season). Operator's house has
multiple HVAC zones (Upstairs, Downstairs, BackHouse, etc.). The forecast
itself is house-wide (single weather provider, single lat/lon), so a
per-zone climate norm doesn't add information — all zones share the same
outdoor forecast.

**House-wide is correct.** Per-zone climate norm would only make sense for
zones with different microclimates (e.g. detached guest cabins), which
isn't this house's configuration.

Future-proofing: if operator ever adds a true micro-climate zone, the
`_BUCKET_CONF_KEYS` pattern at `dynamic_preset.py:104` shows how per-zone
CONFs are structured. The current scope intentionally avoids that
complexity.

---

## Area 6 — Acceptance hypothesis for shipwatch

Plan §11 "Live validation steps" lists 7 verification steps. Two
falsifiable acceptance criteria stand out:

1. **D2 byte-equality** — pre-deploy snapshot of `delta_f` per bucket
   sensor, post-deploy with flag OFF must match within ±0.1°F. **Strong**.
2. **D2 91 − 97 = −6 exemplar** — with flag ON and SUMMER=97 typed,
   `delta_f` reads −6.0 on a 91°F apparent forecast day. **Strong**.

**Gap:** there is no acceptance criterion that bucket CLASSIFICATIONS align
with operator intuition. The "intuitive" frame may still produce wrong
buckets if the operator's typed norm value is off. Suggest adding:

> **Live D-extra:** After 5 days post-flip with at least one COOL day (delta
> ≤ -2) and one HOT day (delta > +8), operator reviews the bucket trajectory
> on the Recorder dashboard. If any day's bucket label disagrees with
> operator intuition, file a backlog ticket — DO NOT mutate thresholds in
> v4.7.17.1.

This is the v4.7.17.1 → backlog handoff for Q4 (deferred recalibration).

---

## Area 7 — Rollback

**Rollback is immediate, no restart required.** Operator:
1. Open CM → Configure → HVAC → Dynamic Preset → Advanced
2. Untoggle `CONF_DPM_USE_CLIMATE_NORM_BASELINE`
3. Save

Next WPM refresh (≤5 min) returns to legacy `pair[0]` indoor-target baseline.
Bucket sensor attributes show `baseline_source = "indoor_target"` again.
Existing dwell suppresses spurious flip-back transitions.

**Worst-case rollback:** flag is ON, operator types climate norm 97, then
remembers they didn't want to flip the frame yet. Flip OFF → behavior
identical to pre-flip within 5 minutes. **No data loss, no restart, no
schema concerns.**

Plan §6 Property B verified.

---

## Area 8 — Wider doc surfaces

| Doc | Today | Action needed | Priority |
|---|---|---|---|
| `docs/user-manual/DYNAMIC_PRESET.md:32` | `delta = apparent_forecast_high − zone_home_cool_high` | **UPDATE.** Add "(legacy: zone_home_cool_high; under climate-norm mode: expected_seasonal_apparent_high)" | HIGH — user-facing |
| `docs/user-manual/DYNAMIC_PRESET.md:253` | Signal payload `delta_f` documented | No change needed | n/a |
| `docs/HVAC_MANAGEMENT_EXPLAINER.md` | No DPM delta references found | None | n/a |
| `docs/ENERGY_MANAGEMENT_EXPLAINER.md:560` | One-liner `baseline_delta_for_zone() → delta` | Optional one-line clarification | LOW |
| `docs/QUALITY_CONTEXT.md` | Bug Class #49 (tuple-shape drift) is the closest related class | **Consider new bug class #50** — "Semantic Frame Drift": a function's return value retains the same Python type but the operator-facing meaning changes under a flag. Would require Bug Class #50 ADD via QUALITY_CONTEXT.md update post-v4.7.17.1. | MEDIUM |
| Dashboard YAML | No URA-shipped dashboards | None | n/a |
| `docs/Coordinator/HVAC_COORDINATOR_DESIGN.md` | DPM ownership confirmed | None | n/a |
| `docs/Coordinator/ENERGY_COORDINATOR_DESIGN.md` | n/a | None | n/a |
| `docs/readmes/README_v4.7.17.1.md` | Does not exist yet | **CREATE before deploy** per CLAUDE.md release-process rule | HIGH |

---

## Precise changes the build would make

This is the operator's approval surface. Each row: file:line, before (one
line), after (one line), notes.

### Production code

| # | File | Line range | Before | After | Notes |
|---|---|---|---|---|---|
| P1 | `domain_coordinators/energy_const.py` | after :214 | (end of v4.7.1 Cycle B block) | **NEW BLOCK** — 4 CONF constants + 4 DEFAULT constants for `CONF_DPM_USE_CLIMATE_NORM_BASELINE` and `CONF_DPM_EXPECTED_SEASONAL_APPARENT_HIGH_{SUMMER,SHOULDER,WINTER}` | Per plan §D1 — sentinel `None` defaults for the 3 floats |
| P2 | `domain_coordinators/weather_manager.py` | 213-228 | `baseline_delta_for_zone()` returns `forecast.apparent_high - self._get_zone_baseline_high(zone_id, preset)` | **UNCHANGED** signature; calls into a new branch in `_get_zone_baseline_high()` first | Public API stays the same |
| P3 | `domain_coordinators/weather_manager.py` | 522-571 | `_get_zone_baseline_high()` always returns `pair[0]` (indoor cool setpoint) | **Branch:** if flag ON and per-season climate norm is set → return norm float. Else → existing `pair[0]` path. Plus 3 new private helpers `_climate_norm_baseline_enabled`, `_resolve_current_season`, `_get_climate_norm_for_season` | Per plan §D2. **PLUS recommended amendment:** winter-mode gate (see OQ-3) |
| P4 | `domain_coordinators/weather_manager.py` | NEW method | n/a | **NEW** public accessor `baseline_source_for_zone(zone_id, preset) -> str` returning `"climate_norm"` or `"indoor_target"` (or `"indoor_target_fallback"` if recommended in OQ-4) | Per plan §D4 — single source of truth for the sensor attribute |
| P5 | `config_flow.py` | 4181-4206 | Advanced section has 5 fields | **+4 new fields:** 1 bool + 3 optional floats. Updated `cm_update` dict at :4104-4119 to persist them | Per plan §D3 |
| P6 | `config_flow.py` | 4076-4084 | 5 CONFs imported | **+4 CONFs imported** | Required to satisfy plan D1 AST check |
| P7 | `sensor.py` | 7003-7010 | 6 attributes returned | **+2 attributes:** `baseline_source`, `expected_seasonal_high_f` | Per plan §D4 |
| P8 | `strings.json` + `translations/en.json` | Surface 1 form section | 5 advanced labels | **+4 labels + descriptions** | Per plan §D3 |

### Optional/recommended amendments (subject to operator approval)

| # | File | Change | Rationale |
|---|---|---|---|
| A1 | `domain_coordinators/weather_manager.py` | Add winter gate inside `_climate_norm_baseline_enabled()` OR `baseline_delta_for_zone()` — return None when `current_season == SEASON_WINTER` AND flag is ON | Prevents DPM churn in heating season; preserves "summer-only" implicit assumption (see Area 5b) |
| A2 | `docs/user-manual/DYNAMIC_PRESET.md:32` | Update delta formula text | User-facing accuracy |
| A3 | `domain_coordinators/weather_manager.py` | Refine fallback return path for `baseline_source_for_zone()` to surface `"indoor_target_fallback"` when flag ON but norm unset, distinct from `"indoor_target"` when flag OFF | Operator observability (see Area 4b) |
| A4 | `docs/QUALITY_CONTEXT.md` | Add Bug Class #50 "Semantic Frame Drift" post-deploy | Institutional memory |
| A5 | `docs/readmes/README_v4.7.17.1.md` | Create per CLAUDE.md release-process rule | Pre-deploy gate |

### Tests

| # | File | Description | LoC |
|---|---|---|---|
| T1 | `quality/tests/test_v4_7_17_1_dpm_climate_norm_baseline.py` (NEW) | 12 tests per plan §9 | ~150 |
| T2 | (same file) | **+1 recommended:** `test_winter_season_returns_none_when_flag_on` if A1 amendment is accepted | ~15 |
| T3 | (same file) | **+1 recommended:** `test_baseline_source_distinguishes_fallback_from_explicit_off` if A3 amendment is accepted | ~15 |

---

## Open questions for operator decision

Only items that materially change the plan are listed.

### OQ-1: Sub-section the new fields under a "Location & climate" heading?

The 4 new CONFs are location-property facts (climate norm); the existing 5
are behavioural taste knobs. Mixing them in the same `"advanced"` section
works but loses semantic grouping.

- **Option A (plan as written):** add to existing Advanced section. Single
  collapsed section, 9 fields. Cheap.
- **Option B:** add a NEW collapsed sub-section `"location_and_climate"`
  inside Advanced, holding the 4 new fields. Existing 5 stay in
  `"advanced"`. Two collapsibles instead of one.

**Recommendation:** A (don't grow scope). Material impact: cosmetic.

### OQ-2: Shoulder-season norm volatility — accept noise, or restrict DPM to summer only?

Shoulder seasons have wide day-to-day variance. A single SHOULDER norm
value will produce frequent bucket transitions.

- **Option A (plan as written):** ship 3 seasons of CONF; accept noise.
- **Option B:** ship only SUMMER CONF; gate DPM off in shoulder + winter.
- **Option C:** ship 3 seasons CONF; add docs caveat about shoulder noise;
  observe ≥4 weeks; decide if a separate gate is needed.

**Recommendation:** C. Material impact: medium — bucket dwell-cycle log
volume may rise in spring/fall.

### OQ-3: Winter / heat-mode gate (HIGH-RISK amendment)

DPM has no heat-mode awareness today. Under new frame, winter deltas will
be more volatile and bucket transitions will be active even though the
emitted `cool_high` overrides are meaningless in heat mode.

- **Option A (plan as written):** ignore — DPM stays active all winter,
  spurious overrides emitted but ignored by HVAC layer.
- **Option B (recommended):** add a gate that returns None from
  `baseline_delta_for_zone()` when current_season == winter. Single-line
  addition. Preserves DPM's implicit "summer-only" assumption.
- **Option C:** document the limitation in user-manual and recommend
  operators disable the DPM master switch in winter.

**Recommendation:** B. Material impact: prevents winter log churn and
prevents the operator from chasing phantom "DPM transitioned" notifications
in heating season.

### OQ-4: Distinct `baseline_source` value for the "flag ON but norm unset" fallback?

Plan's D4 returns `"climate_norm"` or `"indoor_target"`. The fallback path
(flag ON, norm unset) returns the indoor target — same string as flag OFF.
Operator can't distinguish "I haven't flipped the flag yet" from "I flipped
the flag but forgot to type a norm."

- **Option A (plan as written):** 2 values. Operator must consult CM
  options to confirm flag state.
- **Option B (recommended):** 3 values: `"climate_norm"`, `"indoor_target"`,
  `"indoor_target_fallback"`. ~3 extra LoC.

**Recommendation:** B. Material impact: minor, observability win.

---

## Estimated total LoC delta (with confidence interval)

| Component | Plan estimate | Implications-adjusted estimate | Notes |
|---|---|---|---|
| `weather_manager.py` | ~25 | **~30-35** | +5 LoC if OQ-3/A1 winter gate accepted; +3 LoC if OQ-4/A3 fallback string accepted |
| `energy_const.py` | ~10 | ~10 | unchanged |
| `config_flow.py` | ~25 | ~25 | unchanged |
| `sensor.py` | ~10 | ~10 | unchanged |
| `strings.json` + `translations/en.json` | ~15 each | ~15 each | unchanged |
| Tests | ~150 | **~170-180** | +1 winter gate test, +1 fallback string test |
| `docs/user-manual/DYNAMIC_PRESET.md` | 0 | **~10** | A2 amendment |
| `docs/readmes/README_v4.7.17.1.md` | 0 | **~100** | CLAUDE.md mandate |

**Total production code:** ~90 LoC (vs plan's 80). **Total tests:** ~180 LoC
(vs plan's 150). **Total docs:** ~110 LoC.

**Grand total: ~380 LoC** (vs plan's ~250) with all recommended amendments;
~250 LoC if plan is accepted as-is.

**Confidence:** HIGH on production code, MEDIUM on tests (depends on which
edge cases are explicitly covered), HIGH on docs.

---

## Risks ranked

### HIGH

1. **Winter-mode DPM churn under new frame.** Bucket transitions emitted
   all winter long; cool-mode overrides ignored by HVAC; logs noisy;
   operator surprised by transition notifications when heating.
   **Mitigation:** OQ-3 Option B (winter gate). Single-line code + 1 test.
2. **Bucket-threshold staleness.** Existing thresholds
   (`cool_max=-2, mild_max=8, hot_max=18`) were tuned for the indoor-target
   frame. Under the climate-norm frame, classifications may
   counterintuitively land. Plan correctly defers recalibration.
   **Mitigation:** plan's Q4 explicit deferral + backlog memo; operator
   observability via D4 attributes.

### MEDIUM

3. **Documentation drift.** `docs/user-manual/DYNAMIC_PRESET.md:32` formula
   text becomes wrong when flag is ON.
   **Mitigation:** A2 amendment (1-line doc update).
4. **Operator confusion: "flag ON, no behavior change".** If operator flips
   the flag without typing a climate norm, behavior is identical to flag
   OFF (legacy fallback). The `baseline_source` attribute will read
   `"indoor_target"` — same as flag OFF — operator can't see why.
   **Mitigation:** OQ-4 / A3 amendment (distinct `"indoor_target_fallback"`
   value).
5. **CM-level cool-target override silently bypassed for DPM.** When the
   operator has `CONF_HVAC_BASELINE_SUMMER_HOME_COOL = 75` set AND flips
   the new climate-norm flag with SUMMER=97 typed, the 75 indoor override
   no longer feeds DPM — DPM uses 97 instead. This is the correct semantic
   but operator may be surprised.
   **Mitigation:** D3 helper text + A2 user-manual update should explicitly
   call out this independence.

### LOW

6. **Shoulder-season noise.** Wider day-to-day forecast variance in
   shoulder seasons may increase bucket-transition frequency.
   **Mitigation:** observe ≥4 weeks post-deploy per OQ-2 Option C; file a
   backlog ticket if noise is excessive.
7. **Restored bucket label disagreement on first WPM refresh after flip.**
   Brief (≤5 min) window where `_active_bucket` disagrees with the freshly
   classified bucket. Dwell logic handles this gracefully — at worst, one
   transition fires after `dwell_minutes` elapses.
   **Mitigation:** none needed; existing dwell + hysteresis already correct.
8. **Test fixture coverage of `_get_climate_norm_for_season` edge cases.**
   Plan covers happy path + unset CONF + unknown season + non-numeric
   value. Implicit edge case: CONF set to negative number (operator typo).
   `vol.Range(min=10.0, ...)` should catch this at config-flow time but
   defensive coercion in runtime is cheap insurance.
   **Mitigation:** add one parameterised test for negative/None/string
   inputs (~10 LoC).

---

## Verification trail (for reviewer)

Files read end-to-end:
- `docs/planning/PLANNING_v4.7.17.1_dpm_climate_norm_baseline.md` (full)
- `custom_components/universal_room_automation/domain_coordinators/weather_manager.py:200-571` (target function + surrounding context)
- `custom_components/universal_room_automation/domain_coordinators/dynamic_preset.py:100-666` (DPM source, state machine, eval path)
- `custom_components/universal_room_automation/domain_coordinators/hvac_preset.py:80-220` (PresetManager accessor)
- `custom_components/universal_room_automation/sensor.py:6873-7245` (DPM sensors)
- `custom_components/universal_room_automation/config_flow.py:4040-4210` (DPM Surface 1 form)

Greps run:
- `baseline_delta_for_zone` / `classify_bucket` / `delta_f` / `baseline_high_f` /
  `apparent_high_f` / `SIGNAL_DYNAMIC_PRESET_TRANSITIONED` across `custom_components/`
- `_active_bucket` / `_last_transition_at` / `_dwell_until` in `dynamic_preset.py`
- `dynamic_preset` / `bucket` / `delta` in `database.py`
- `winter` / `heat` / `hvac_mode` in `dynamic_preset.py` + `weather_manager.py`
- All `docs/user-manual/`, `docs/HVAC_MANAGEMENT_EXPLAINER.md`,
  `docs/ENERGY_MANAGEMENT_EXPLAINER.md` for delta/baseline references
- `docs/QUALITY_CONTEXT.md` for related bug classes (#47, #48, #49)

Not pursued (out of scope):
- Live HA state inspection via MCP — operator can do this for D2
  pre-deploy snapshot
- Graphify wiki — per CLAUDE.md revised graphify rule, existence/consumer
  questions use grep, not the graph navigation report

---

## Bottom line for the operator

**Approve plan as written** if you accept LOW priority risks 6-8.
**Approve with amendments OQ-3 (winter gate) + OQ-4 (fallback string) + A2
(doc update)** if you want to retire the HIGH+MEDIUM risks before they
materialize.

The plan itself is correct, surgical, and matches CLAUDE.md tier
classification. The 4 amendments above are not "build creep" — they close
gaps the plan implicitly inherited from the v4.7.16.4 frame and would
otherwise surface as backlog tickets within 1-2 weeks of deploy.

Final ask: **OQ-3 is the only material decision.** The other three are
quality-of-life. If OQ-3 = Option B (winter gate), I would recommend
elevating to a quick second review pass focused purely on the winter
gate's interaction with `current_season` resolution (since
`hvac_preset.py:92` reads from instance state and not `dt_util.now()` —
there's a stale-season risk if PresetManager's `determine_season()`
hasn't been called recently). Otherwise plan stays Tier 1.
