# PLANNING v4.7.x — Dynamic Preset Management (Apparent-Temp Continuous Re-Evaluation)

**Status:** FINALIZED 2026-05-27 — ready to build
**Predecessor:** v4.5.10 (HVAC tunables) + v4.5.9 (HVAC cover intent) + v4.6.8 (EC TOU rate reconciliation)
**Sibling-in-flight:** `PLANNING_v4.7.x_guest_mode_actuation_phase1.md` — OWNS the shared per-(zone, preset, range) override schema (`preset_overrides` list on Zone Manager `zones[zone_name]`). This plan is a CONSUMER of that schema.
**Recall hint:** "Dynamic preset management"

---

## Finalize summary (what shifted from earlier drafts)

This rewrite consolidates two rounds of feedback into a single coherent plan. Key architectural moves vs the initial draft:

1. **Apparent temperature, not raw dry-bulb.** Cycle A's `WeatherProviderManager` exposes `apparent_forecast_high` (humidity-adjusted) as the primary primitive. Falls back to raw if the provider doesn't expose apparent.
2. **Delta-based bucket boundaries.** Bucket = f(apparent_forecast_high − home_baseline_high), not absolute °F. Climate-portable. Same Texas-tuned bucket table works for a Wisconsin install.
3. **Continuous re-evaluation, not morning cron.** Every EC decision cycle (5 min) re-classifies the bucket. Override emit gated by transition + **1-hour dwell hysteresis** (user-specified — weather doesn't move that fast) + ±2°F boundary buffer. Naturally handles HA restart, provider failover, day-starts-hot-cools-down.
4. **Two cycles ship INDEPENDENTLY.** Cycle A (Weather Provider Manager) has its own version, acceptance criteria, deploy, and live validation. Cycle B (Dynamic Preset Override Source) is a separate version that depends on Cycle A having shipped + stable for ≥1 cycle. Each cycle runs Tier 2-DB-style 3-parallel-reviewer protocol per CLAUDE.md (user explicitly invoked the strictest tier for this new-feature work).
5. **Observability + control surface audit.** Minimal new entities — 1 master switch, 2 runtime number knobs, 5 new sensors total across both cycles. No "force recompute now" button (continuous eval makes it redundant). No per-zone enable switch (reuse Guest Mode Phase 1's per-zone schema).
6. **Documentation deliverable in scope.** Updates to 4 existing docs (Energy + HVAC user manuals + explainers) + 1 new doc (`docs/user-manual/DYNAMIC_PRESET.md`) ship with the cycles.

---

## TL;DR

URA HVAC presets carry fixed temperature RANGES per zone. A single range doesn't fit every day — a 70–76 °F `home` that paces the AC nicely on a 78 °F day forces it to grind all afternoon on a 98 °F day with high humidity. User policy: **always ranges, never absolute setpoints, never daily user fiddling.**

Fix: every EC decision tick, classify today's thermal load into a bucket using apparent-forecast-high minus the zone's `home` baseline (climate-portable delta), and emit per-zone preset-range overrides through Guest Mode Phase 1's shared `OverrideEngine`. Overrides re-evaluate continuously but only transition between buckets after a 1-hour dwell + ±2°F boundary buffer. No new cron, no new scheduler — piggyback on the existing 5-min decision cycle.

**Hard dependency:** Cycle A (Weather Provider Manager) must ship first AND have ≥1 live-validation cycle worth of stability before Cycle B is attempted. Single-provider blind spots today (one Envoy maintenance event = whole EC degrades) need to be eliminated before adding more weather-driven logic on top.

---

## Tier classification + ship cadence

| Cycle | Scope | Tier | Ship cadence |
|---|---|---|---|
| **Cycle A — Weather Provider Manager + Apparent-Temp Primitive** | `WeatherProviderManager` with ≥2 (target 3) ranked weather providers. Failover, staleness, divergence. Exposes apparent-temp primitives. Migrates existing weather consumers (HVAC predictor, EC forecast read) through the manager. 3 new sensors. | **Tier 2-DB** (user-invoked) | Own version (e.g. v4.7.x). Own README. Own live validation. Independent deploy. No dependency on Cycle B. |
| **Cycle B — Dynamic Preset Override Source** | New override source emitting into Guest Mode Phase 1's shared schema. Per-tick bucket classification (delta-based). 1-hour dwell hysteresis. 2 new sensors + 1 master switch + 2 number knobs. | **Tier 2-DB** (user-invoked) | Own version (e.g. v4.7.x+N). Depends on Cycle A shipped + ≥1 live cycle of stability. Independent deploy. |

**Why Tier 2-DB instead of Tier 2:** user explicitly invoked the strictest tier ("use tier 2-DB review protocol since this is a new feature"). Three parallel reviewers per cycle with disjoint framings (see "Review framings" sections below). The DB-touch criteria are NOT met in the strict sense (no schema migration; the override schema lives in `entry.options`), but the user prefers more eyes for this surface-area expansion. Honoring.

---

# Cycle A — Weather Provider Manager + Apparent-Temp Primitive

**Goal:** Replace single-provider weather reliance with a ranked-list manager. Expose apparent-temperature as a first-class primitive that EC, HVAC, and future Dynamic Preset Mgmt all read from a single source. Eliminate the single-provider blind spot that an Envoy maintenance event (or any provider outage) currently exposes.

## A. Discovery — read before build (mandatory for builder)

1. **Verify HA forecast API shape.** Legacy `state.attributes["forecast"]` is deprecated. Modern path: `await hass.services.async_call("weather", "get_forecasts", {"entity_id": ..., "type": "daily"}, blocking=True, return_response=True)`. Verify against the HA dev docs (https://developers.home-assistant.io/docs/core/entity/weather) at build time. Do NOT guess between the legacy / modern path — the source is authoritative.

2. **Identify apparent-temp attribute names per provider.** Provider variation:
   - Met.no: `apparent_temperature`
   - Pirate Weather / OpenWeatherMap: `apparent_temperature` (HA mapping)
   - NWS: `temperature_feels_like` (older mapping) — verify against current `weather.nws_*` entity at build time
   - Some integrations don't expose apparent at all — manager must fall back to raw temp + a `confidence` flag indicating the fallback

3. **Enumerate every weather consumer in URA.** Verified during plan audit (2026-05-27):
   - `energy_const.py:DEFAULT_WEATHER_ENTITY = "weather.phalanxmadrone"` (single hard-coded default)
   - `energy.py:224 _weather_entity` (EC reads forecast via `weather.get_forecasts`)
   - `energy.py:298, 553, __init__.py:1733+` (CONF_ENERGY_WEATHER_ENTITY plumbing)
   - `hvac_predict.py:_outdoor_temp_entity` (HVAC's own outdoor-temp read, set via cover_controller)
   - `signals.py:EnergyConstraint.forecast_high_temp` (EC pushes forecast to HVAC via dispatch)
   - **No apparent-temp usage anywhere today.**

4. **Verify live HA `weather.*` entities** via `ha_search_entities` before the build (`No Fabrication` rule). Document the user's currently-configured set.

## A.B. Design

### A.B.1 Provider list + ranking

New CoordinatorManager CONFs (in `energy_const.py`, since EC owns the existing weather entity CONF):

| CONF | Type | Default | Range / values |
|---|---|---|---|
| `CONF_WEATHER_PROVIDERS` | list[str] (entity_ids) | empty | ordered list, max 3 |
| `CONF_WEATHER_STALENESS_MAX_HOURS` | int | 6 | 1-24 |
| `CONF_WEATHER_DIVERGENCE_THRESHOLD_F` | float | 5.0 | 1-20 |
| `CONF_WEATHER_FALLBACK_TO_RAW_WHEN_APPARENT_MISSING` | bool | True | — |

`CONF_ENERGY_WEATHER_ENTITY` (existing single-entity CONF) is preserved during the migration. **Deprecation strategy:** during Cycle A, `WeatherProviderManager._provider_order` is built from `CONF_WEATHER_PROVIDERS` if set, else falls back to `[CONF_ENERGY_WEATHER_ENTITY]` as a 1-element list. After Cycle A live-validates, a follow-up cycle (out of scope here) removes the single CONF and forces migration.

### A.B.2 Failover semantics

Provider is "healthy" if ALL:
- HA entity state ≠ `unavailable` / `unknown`
- Last state update timestamp within `staleness_max_hours`
- `weather.get_forecasts` returns ≥ 1 forecast covering today
- (Soft) Provides `apparent_temperature` attribute — if missing AND `fallback_to_raw=True`, mark as `apparent_unavailable` but still usable

Active provider = first healthy in priority list. On failover, log INFO, fire dispatcher signal `SIGNAL_WEATHER_PROVIDER_CHANGED` (new), update active-provider sensor.

**Re-evaluation cadence:** subscribe to state-change events on each provider entity via `async_track_state_change_event` (Bug #38 — capture unsub into `async_on_remove`). Health is recomputed on each state change; no polling.

### A.B.3 Divergence detection

When ≥ 2 healthy providers report `today_high`, compute `|delta|` between primary and secondary. If exceeds `divergence_threshold_f`, set `binary_sensor.ura_weather_divergence = on` + log WARNING + fire dispatcher signal `SIGNAL_WEATHER_DIVERGENCE_DETECTED`.

With 3 providers: divergence = `max - min` across all healthy providers. Returns median as the authoritative value when divergence flag is set (active provider's value otherwise).

### A.B.4 Apparent-temp primitive

`WeatherProviderManager` exposes (and the manager's API surface):

```python
async def get_today_forecast() -> WeatherForecast | None:
    # Returns dataclass with: raw_high, raw_low, apparent_high, apparent_low,
    #   provider_id, apparent_confidence, divergence_f, fetched_at
    ...

def current_apparent_temp() -> tuple[float | None, float]:
    """Live apparent temp from active provider. Returns (value, age_seconds)."""

def baseline_delta_for_zone(zone_id: str, preset: str = "home") -> float | None:
    """Returns (forecast_apparent_high - zone_home_baseline_high).
    
    Pulls the zone's home cool_high from HVAC's PresetManager via 
    SEASONAL_DEFAULTS[current_season]["home"][0]. Returns None if 
    forecast unavailable.
    """
```

The `baseline_delta_for_zone` helper is the primitive Cycle B uses. EC's existing pre-cool-likelihood logic also benefits (delta-based replaces absolute-95°F threshold).

## A.C. Cycle A Deliverables

### A1 — WeatherProviderManager module (new)

**File:** `custom_components/universal_room_automation/domain_coordinators/weather_manager.py` (new)

Responsibilities listed in §A.B.4. Singleton per integration entry, attached to `hass.data[DOMAIN]["weather_manager"]`.

**Bug class prevention checklist:**
- **#5 (startup race):** init lazily — first state-change event from a provider initializes; `get_today_forecast()` returns None until first healthy probe
- **#10 (cross-restart):** no in-memory-only state. Active provider is derived each call from current entity states.
- **#17 (unbounded retry):** failover is state-driven, not timer-driven. No retry loops.
- **#19 (untracked tasks):** all `weather.get_forecasts` service calls awaited inline within event handlers; no fire-and-forget
- **#38 (async_listen unsub):** every `async_track_state_change_event` registration captured into `self._unsub_handles` list; cleaned in `async_teardown`
- **#42 (lambda + async_create_task):** never. State-change callbacks are `@callback`-decorated bound methods, not lambdas.

**Acceptance criteria:**
- **Verify:** With 3 providers configured + all healthy, `get_today_forecast()` returns data from primary
- **Verify:** Disable primary in HA UI → next state-change event → manager flips to secondary within 5s; log shows reason
- **Verify:** All 3 stale → `active_provider` returns None; `staleness_status="all_stale"`
- **Sensor:** `sensor.ura_weather_active_provider` reports current active entity_id
- **Test:** `test_weather_manager_failover_primary_down`, `test_weather_manager_all_stale_returns_none`, `test_weather_manager_divergence_flag`, `test_weather_manager_apparent_fallback_to_raw`, `test_weather_manager_unsub_on_teardown` (Bug #38)
- **Live:** Force failover by disabling primary in HA UI; verify sensor flips + log entry; verify HVAC predictor + EC forecast read still produce values

### A2 — Sensors (3 new)

Three new entities on the CoordinatorManager device:

| Entity | Type | State | Key attributes |
|---|---|---|---|
| `sensor.ura_weather_active_provider` | sensor (string state) | active entity_id OR `none` / `all_stale` | `priority_rank`, `healthy_count`, `total_count`, `failover_reason`, `apparent_confidence` |
| `sensor.ura_weather_apparent_forecast_high` | sensor (float) | today's apparent high °F from active | `raw_high`, `apparent_low`, `provider_source`, `median_across_providers`, `confidence` (`high` / `low_divergent` / `degraded_single` / `unavailable` / `apparent_unavailable_fallback_raw`) |
| `binary_sensor.ura_weather_divergence` | binary_sensor | on / off | `divergence_f`, `threshold_f`, `provider_high_map` (dict) |

**Bug class prevention:** #29 (every status branch has a populator path tested), #32 (every CONF has runtime reader)

**Acceptance criteria:**
- **Verify:** All 3 entities visible on CM device after restart
- **Sensor:** `apparent_forecast_high` value matches `weather.<active>.attributes.apparent_temperature` (or `temperature_feels_like` per provider) within 0.5°F when fresh
- **Test:** source-contract tests per CONF; populator tests per sensor
- **Live:** Force divergence by adding a 3rd provider with intentionally-different forecast → binary sensor flips ON

### A3 — Options-flow integration

Three new fields under CM → Energy step (existing place for weather CONF):

- `CONF_WEATHER_PROVIDERS` — multi-select of `weather.*` entities, ordered (HA's `EntitySelector` with `multiple=True`; order preserved)
- `CONF_WEATHER_STALENESS_MAX_HOURS` — slider 1-24, default 6
- `CONF_WEATHER_DIVERGENCE_THRESHOLD_F` — slider 1-20, default 5.0

`CONF_ENERGY_WEATHER_ENTITY` (existing) shown as **read-only "Legacy single-provider entity"** with helper text: "Used as fallback if the provider list above is empty. Will be deprecated in a future cycle."

**Bug class prevention:** #2 (entry.options not entry.data; CONF_WEATHER_PROVIDERS is options-flow-only), #32 (each CONF has a runtime reader in WeatherProviderManager)

### A4 — Migration of existing weather consumers

Replace direct reads:
- `energy.py:224 self._weather_entity` → uses `WeatherProviderManager.active_provider` (with fallback to legacy CONF)
- `hvac_predict.py:_outdoor_temp_entity` setter → unchanged at the public API level; internally redirected to consume from WeatherProviderManager
- `signals.py:EnergyConstraint.forecast_high_temp` → **payload SHAPE unchanged for back-compat**, but value now sourced from `WeatherProviderManager.get_today_forecast().raw_high` (preserves existing HVAC consumer expectations); a NEW `apparent_forecast_high_temp: float | None = None` field is added alongside

**Bug class prevention:** #37 (payload shape change → audit every caller of `EnergyConstraint`)

**Acceptance criteria:**
- **Verify:** After Cycle A deploy, disabling the OLD `CONF_ENERGY_WEATHER_ENTITY` value's underlying entity does NOT break HVAC pre-cool (manager fails over to provider list)
- **Test:** AST regression `test_no_direct_hass_states_get_weather_in_domain_code` — no consumer reads `hass.states.get("weather.*")` directly; everything routes through WeatherProviderManager

### A5 — Tests + docs (Cycle A)

- New test file `quality/tests/test_v47x_weather_manager.py` (~300 LoC)
- Source-contract tests per Bug #32
- Failover state machine tests (5 scenarios per §A.B.2)
- Acceptance criteria for each new sensor
- `docs/readmes/README_v4.7.x.md` — Cycle A release notes
- Documentation updates (see §D Documentation Deliverable below)

## A.D. Cycle A Review Framings (Tier 2-DB — 3 parallel)

- **Reviewer A — Correctness + edge cases.** Failover state machine across all 5 scenarios (primary down / P1+P2 down / all unavail / P1 stale+P2 fresh / all healthy+divergent). Apparent-fallback-to-raw correctness when provider lacks the attribute. Divergence detection off-by-one. CONF reader coverage. Empty provider list defaults to legacy single entity. Bug classes #5, #14, #17, #22 (provider state strings as enum), #32.
- **Reviewer B — Async + lifecycle + migration.** `WeatherProviderManager` init order vs weather entity availability (Bug #5). State-change listener cleanup on entry unload (Bug #38). Update-listener handling provider list reorder (Bug #20). Consumer migration completeness — every grep-hit for `hass.states.get("weather.*")` in domain code is migrated (Bug #37). Restart resilience.
- **Reviewer C — Payload shape + test fixture authority.** `EnergyConstraint` payload shape integrity — `apparent_forecast_high_temp` added without breaking existing consumers (Bug #37). Test fixtures for weather entities use real shape (not hand-copied — Bug #39). Behavioral tests drive real code paths (Bug #40). Source-contract AST tests cover every new CONF + sensor.

## A.E. Cycle A Live Validation (Review D — post-deploy)

1. New sensors visible on CM device, populated within 60s of restart
2. Force failover (disable primary weather entity in UI) → active sensor flips + log entry within 5s; HVAC predictor + EC continue producing forecast values via fallback
3. Force divergence (manually-spoofed test weather entity with offset) → binary sensor + warn log
4. `EnergyConstraint` payload includes new `apparent_forecast_high_temp` field, value matches active provider's apparent-temp attribute
5. Zero new "untracked task" warnings in 1 hour post-restart
6. Zero new frame-helper warnings (`async_create_task from a thread other than the event loop`) — Bug #42 regression check

---

# Cycle B — Dynamic Preset Override Source

**Depends on:** Cycle A shipped + ≥ 1 live-validation cycle worth of stability + ≥ 2 weather providers configured + Guest Mode Phase 1's `OverrideEngine` shipped + stable. **Do not start Cycle B until these dependencies are confirmed.**

**Goal:** On every EC decision tick, classify the day's thermal load into a bucket using apparent-forecast-high-minus-baseline (climate-portable delta). Emit per-zone preset-range overrides through Guest Mode Phase 1's shared `OverrideEngine`. Continuous re-evaluation with 1-hour dwell hysteresis prevents flap. Naturally adapts when day starts hot then cools down (or vice versa). HA restart, provider failover, and intra-day weather shifts all handled by the same code path.

## B.A. Discovery — read before build

1. **Confirm Guest Mode Phase 1 schema is shipped and stable.** Read the FINAL `PLANNING_v4.7.x_guest_mode_actuation_phase1.md` (or whichever version shipped) and the live `OverrideEngine` implementation. Verify the `PresetOverride` dataclass has the fields this plan assumes: `source` (str), `preset` (str), `cool_low` (float | None), `cool_high` (float | None), `priority` (int).
2. **Identify the EC decision-cycle integration point.** Verified during audit: `energy.py:1986 _async_decision_cycle`. The dynamic-preset re-evaluation runs as a step within this cycle (or in a tightly-coupled sub-controller).
3. **Confirm how Cycle A exposes apparent forecast.** Verify `WeatherProviderManager.baseline_delta_for_zone(zone_id, preset="home")` returns the expected delta value and handles missing-apparent-temp fallback per Cycle A §A.B.4.
4. **Identify ALL per-zone configuration storage.** Per-zone bucket tables live in Zone Manager's `zones[zone_name]` dict alongside Guest Mode's `preset_overrides`. Reuse the existing options-flow zone-edit step (add fields; don't create a new step).

## B.B. Design

### B.B.1 Delta-based bucket boundaries

Replace absolute-temperature thresholds with **delta off home baseline**. `delta = apparent_forecast_high − zone_home_cool_high_seasonal_default`.

| Bucket | Delta range (default) | Intent |
|---|---|---|
| `cool` | δ ≤ -2°F | AC barely needed — wider range OK |
| `mild` | -2 < δ ≤ +8°F | Default range applies — no override needed |
| `hot` | +8 < δ ≤ +18°F | Narrower range — AC will work harder |
| `extreme` | δ > +18°F | Tightest range — AC at peak stress |

**Why deltas not absolutes:** climate-portable. A Texas summer day at 95°F apparent (δ ≈ +18 vs home_high=77) is roughly the same load profile as a Wisconsin summer day at 90°F apparent (δ ≈ +18 vs home_high=72). Same bucket; same response.

**Bucket boundaries are user-tunable** via CM options:
- `CONF_DYNAMIC_PRESET_DELTA_COOL_MAX` (default -2.0)
- `CONF_DYNAMIC_PRESET_DELTA_MILD_MAX` (default +8.0)
- `CONF_DYNAMIC_PRESET_DELTA_HOT_MAX` (default +18.0)

### B.B.2 Continuous re-evaluation with 1-hour dwell + ±2°F hysteresis

**No cron. No new scheduler.** Piggyback on EC's existing `_async_decision_cycle` (5-min cadence).

Each tick:

```
For each zone opted-in:
    1. fresh_bucket = classify(WeatherProviderManager.baseline_delta_for_zone(zone))
    2. If fresh_bucket == current_active_bucket[zone]:
           continue   # no transition — cheap
    3. If now() - last_transition_at[zone] < dwell_timeout:
           continue   # in dwell — refuse transition
    4. # Hysteresis: don't transition out of current bucket unless 
       # delta is firmly past the boundary by hysteresis_f
       If not _passed_boundary_with_buffer(current_bucket, fresh_bucket, delta):
           continue
    5. # Commit transition
       previous = current_active_bucket[zone]
       current_active_bucket[zone] = fresh_bucket
       last_transition_at[zone] = now()
       emit_override(zone, fresh_bucket)  # via OverrideEngine
       log INFO "DynamicPreset zone={zone} transitioned {previous} -> {fresh_bucket}, delta={delta:.1f}°F"
       fire dispatcher SIGNAL_DYNAMIC_PRESET_TRANSITIONED
```

**Tunable knobs:**
- `CONF_DYNAMIC_PRESET_DWELL_MINUTES` (default 60 = 1 hour per user spec). Range 15-240.
- `CONF_DYNAMIC_PRESET_HYSTERESIS_F` (default 2.0). Range 0.5-5.0.

**Why 1-hour dwell:** weather forecasts don't move that fast. Even when a cold front rolls through, the apparent-temp delta change manifests over ≥1 hour. The dwell prevents 5-min-tick flapping when a single forecast revision nudges across a boundary.

**Why ±2°F hysteresis:** if `hot_max` boundary is +18°F, "in HOT" stays HOT until delta drops below +16°F (hysteresis subtracts on exit); "in MILD" doesn't enter HOT until delta exceeds +18°F (the strict threshold on entry). Asymmetric on purpose — once in a tighter range, stay there until clearly warranted to relax; harder to enter tighter ranges, easier to stay in them.

### B.B.3 Cross-restart state persistence (Bug #10)

`current_active_bucket` and `last_transition_at` per zone MUST survive HA restart. Two options:
- **Option A (recommended):** RestoreEntity-backed on the `sensor.ura_dynamic_preset_active_bucket_<zone>` sensor. Standard URA pattern.
- **Option B:** URA DB table. Heavier than needed; bucket state is single-row per zone, no history needed beyond current.

Builder picks; both meet the Bug #10 requirement.

### B.B.4 Composition with shared override schema

Cycle B emits override records into Guest Mode Phase 1's `OverrideEngine` schema:

```python
{
    "source": "dynamic_preset",
    "preset": "home",          # or "sleep" if user opted-in for sleep
    "cool_low": 70.0,
    "cool_high": <bucket-tabled value>,
    "priority": <CONF_DYNAMIC_PRESET_PRIORITY default 30>,
    "active_when": predicate("dynamic_preset_zone_in_bucket", {zone, bucket}),
}
```

**Priority default 30.** Lower than `guest_mode` (50). When both guest mode + dynamic preset are active for the same zone+preset, guest mode wins via the engine's per-field highest-priority-wins composition.

**Multiple overrides per zone allowed.** A zone could have BOTH a guest_mode override AND a dynamic_preset override active simultaneously — engine resolves them.

**Override removal on bucket change:** when a transition happens, the OLD override (e.g., `dynamic_preset@hot`) is removed and the NEW override (e.g., `dynamic_preset@mild`) is added. `OverrideEngine` exposes a remove-by-source-and-predicate API call for this.

### B.B.5 Per-zone × per-bucket range table

Configured via Zone Manager → zone-edit options-flow step (extends existing step from Guest Mode Phase 1; no new step). Format per zone:

```
[ ] Enable dynamic preset adjustment for this zone

If enabled, defaults for `home` preset:
  Bucket: cool       low [70.0]  high [77.0]
  Bucket: mild       low [70.0]  high [76.0]   (defaults from current home preset baseline)
  Bucket: hot        low [70.0]  high [74.0]
  Bucket: extreme    low [70.0]  high [73.0]

[ ] Also apply to 'sleep' preset (default OFF)
  If checked, defaults are 1°F LOWER high than home per bucket:
    Bucket: cool       low [70.0]  high [76.0]
    Bucket: mild       low [70.0]  high [75.0]
    Bucket: hot        low [70.0]  high [73.0]
    Bucket: extreme    low [70.0]  high [72.0]
```

Form-save validation: all 4 buckets must be filled if zone is opted in (no partial tables). `cool_low ≤ cool_high - MIN_DEADBAND` (reuse Guest Mode Phase 1's invariant).

## B.C. Cycle B Deliverables

### B1 — `DynamicPresetOverrideSource` module (new)

**File:** `custom_components/universal_room_automation/domain_coordinators/dynamic_preset.py` (new)

Encapsulates the §B.B.2 evaluation logic. Registered with `OverrideEngine` as a source. Single entry point: `evaluate_and_emit(zone_id, now)` called per zone per EC tick.

**Bug class prevention:**
- **#10 (cross-restart):** state-restoration plan per §B.B.3
- **#11 (UTC vs local):** `last_transition_at` uses `dt_util.utcnow()` for storage; comparison ALSO uses utcnow. NO mixing with `dt_util.now()`.
- **#14 (config staleness):** `_refresh_config()` at top of `evaluate_and_emit` reads fresh CONF values; tunable knobs (dwell, hysteresis) live-tunable
- **#19 (untracked tasks):** evaluation is fully sync (returns override-emit dict); no `async_create_task` calls
- **#22 (enum mismatch):** bucket names as StrEnum (`BucketClass(StrEnum)` with `COOL`, `MILD`, `HOT`, `EXTREME`)
- **#23 (observation mode):** evaluation runs; emit gated by observation-mode check at the EC-decision-cycle level
- **#42 (lambda + async_create_task):** never. No timer callbacks introduced.

**Acceptance criteria:**
- **Verify:** With 96°F apparent forecast + zone home_high=77 → δ=+19 → extreme bucket
- **Verify:** 78°F apparent forecast + zone home_high=77 → δ=+1 → mild bucket (no override needed — mild = default)
- **Verify:** Transition from mild → hot only happens after δ stays >+8°F for `dwell_minutes`
- **Verify:** Transition from hot → mild only happens after δ drops below +6°F (8 − 2 hysteresis) for `dwell_minutes`
- **Test:** Boundary classification: δ=-2.1→cool, δ=-2.0→mild, δ=+7.9→mild, δ=+8.0→hot, δ=+17.9→hot, δ=+18.0→extreme (off-by-one coverage)
- **Test:** Mock dwell timer — δ swings hot↔mild every tick → no override change for the dwell duration
- **Test:** Source-contract: `evaluate_and_emit` reads ALL configured CONFs (Bug #32 via AST grep)

### B2 — EC decision-cycle integration

**Modify:** `energy.py:_async_decision_cycle` — add a step that walks opted-in zones and calls `DynamicPresetOverrideSource.evaluate_and_emit`.

**Bug class prevention:**
- **#23 (observation mode):** emit gated; logging happens regardless so we can see what would have been emitted
- **#37 (API contract):** `EnergyConstraint` payload unchanged by this cycle (dynamic preset doesn't push through that signal)

**Acceptance criteria:**
- **Verify:** Decision cycle log shows dynamic-preset eval entries when feature enabled
- **Test:** EC decision cycle still completes within existing duration budget (no >5s additions)

### B3 — Sensors (2 new)

| Entity | State | Key attributes |
|---|---|---|
| `sensor.ura_dynamic_preset_active_bucket` | string (`cool` / `mild` / `hot` / `extreme` / `unavailable`) | `apparent_forecast_high`, `home_baseline_high`, `delta_f`, `provider_source`, `classified_at`, `bucket_boundaries`, `confidence` |
| `sensor.ura_dynamic_preset_overrides_applied` | int count | `breakdown` (list of `{zone, preset, low, high, transitioned_at}`), `skipped_zones`, `dwell_remaining_per_zone_seconds` |

**Bug class prevention:** #29, #36 (sensors live on integration device, not per-zone, to avoid ZoneManager-dedup bypass), #32

**Acceptance criteria:**
- **Verify:** Both sensors visible on CM device after deploy
- **Sensor:** `active_bucket` reflects current classification within 5 min of state change
- **Sensor:** `overrides_applied` count = number of zones with active dynamic_preset override

### B4 — Switch + Number entities (minimal — no spam)

**1 master switch:**
- `switch.ura_energy_coordinator_dynamic_preset_enabled` — master kill-switch. Default OFF. Available only when `EnergyCoordinator` is registered (matches existing EC sub-switch pattern from `switch.py` factory).

**2 number knobs:**
- `number.ura_energy_coordinator_dynamic_preset_dwell_minutes` — runtime-tunable dwell duration. Default 60, range 15-240, step 5, unit "min".
- `number.ura_energy_coordinator_dynamic_preset_hysteresis_f` — runtime-tunable boundary buffer. Default 2.0, range 0.5-5.0, step 0.5, unit "°F".

**NOT added (intentional — observability/control surface audit per user requirement):**
- No "Force Recompute Now" button — continuous eval makes it redundant
- No per-zone enable switch — reuse the per-zone opt-in checkbox in Zone Manager options flow (consistent with Guest Mode Phase 1)
- No per-bucket-boundary number entities — bucket boundaries are CM-options-flow only (3 CONFs from §B.B.1)
- No per-zone bucket sensor — global active_bucket sensor is enough (weather is global)

**Bug class prevention:** #32 (every CONF/knob has runtime reader), #35 (no buttons → no missing-refresh-signal risk)

### B5 — Per-zone × per-bucket table options flow

Extends Zone Manager → zone-edit step (reuses Guest Mode Phase 1's existing extension). Adds the §B.B.5 form fields.

**Bug class prevention:** #2 (entry.options not entry.data), #3 (OptionsFlow), #32, #36

**Acceptance criteria:**
- **Verify:** CM options has a "Dynamic Preset Adjustment" subsection with global toggles + per-zone bucket tables
- **Verify:** Disabling a zone removes its overrides on next decision tick (via `OverrideEngine.remove_by_source`)
- **Test:** Form-save validation — bucket table low ≤ high; ranges non-empty for all 4 buckets if zone opted in
- **Live:** Reconfigure a zone via UI; verify next tick uses new table without HA restart

### B6 — Composition tests with Guest Mode

Joint integration tests (require Guest Mode Phase 1 schema shipped):
- Both sources active for same zone, dynamic_preset priority 30 + guest_mode priority 50 → guest_mode wins per-field
- Dynamic preset bucket changes mid-day while guest_mode is also active → guest_mode override unaffected, dynamic_preset override updates independently
- Dynamic preset emits then user toggles guest_mode ON → guest_mode override layers on within 1 tick

**Acceptance criteria:**
- **Verify:** All composition scenarios resolve per priority rules
- **Test:** Mock both override sources against the real `OverrideEngine`; assert winner for each scenario
- **Live:** Manually enable guest_mode while dynamic_preset override is active; observe HVAC preset reflect guest range within seconds

### B7 — Tests + docs (Cycle B)

- Test file `quality/tests/test_v47x_dynamic_preset.py` (~400 LoC)
- Source-contract tests per Bug #32
- Bucket boundary tests (off-by-one)
- Dwell + hysteresis lifecycle tests
- Composition tests with Guest Mode (B6)
- `docs/readmes/README_v4.7.x+N.md` — Cycle B release notes
- Documentation updates (see §D)

## B.D. Cycle B Review Framings (Tier 2-DB — 3 parallel)

- **Reviewer A — Correctness + edge cases + bucket math.** Bucket boundary classification off-by-one (all 5 transitions). Delta calculation against the correct seasonal baseline. Hysteresis math (asymmetric on enter vs exit). Dwell timer comparisons (Bug #11 UTC vs local). Behavior when `WeatherProviderManager.baseline_delta_for_zone()` returns None (graceful no-op). Behavior when `OverrideEngine` returns empty active list. Bug classes #5, #11, #14, #21, #22, #32.
- **Reviewer B — Async + lifecycle + cross-coordinator.** `evaluate_and_emit` invoked from EC decision cycle — re-entrancy safety. Override emit + removal atomicity through `OverrideEngine` (Bug #20). State persistence across restart (Bug #10). HA restart mid-dwell behavior — does dwell timer survive correctly? Observation-mode gating end-to-end (Bug #23). Zero new untracked tasks (Bug #19). Zero new frame-helper-violating patterns (Bug #42). Cross-coordinator: EC decision cycle duration budget not blown by added work.
- **Reviewer C — Composition + test fixture authority.** OverrideEngine composition correctness with multiple sources (dynamic + guest) — field-by-field highest-priority-wins behavior. Override removal on bucket change does NOT remove unrelated overrides from other sources. Test fixtures for `PresetOverride` records match production schema (Bug #39). Behavioral tests drive production `OverrideEngine` not a mock (Bug #40). Per-zone CONF readers exist for every form field (Bug #32). Source-contract AST tests added.

## B.E. Cycle B Live Validation (Review D — post-deploy)

1. Both sensors visible on CM device, populated within 5 min of restart
2. With 1 zone opted in + apparent forecast high producing delta > +18°F → `active_bucket=extreme`, override emitted into OverrideEngine, HVAC preset reflects extreme range within 1 decision tick (≤5 min)
3. Force a bucket boundary cross via mock weather provider — verify no transition until dwell timer + hysteresis buffer cleared
4. Toggle master switch OFF mid-day → all dynamic_preset overrides removed within 1 tick
5. Toggle a zone's opt-in OFF mid-day → that zone's override removed; other zones unaffected
6. With guest_mode override AND dynamic_preset override active on same zone → HVAC reflects guest_mode range (priority 50 > 30)
7. EC decision cycle log shows dynamic-preset eval step in every tick
8. Zero new frame-helper warnings post-deploy

---

## C. Bug-Class Compliance Matrix (both cycles)

Audited 2026-05-27 against `docs/QUALITY_CONTEXT.md` (42 bug classes):

| Bug Class | Risk | Plan-level mitigation |
|---|---|---|
| #1 Coordinator Lifecycle Confusion | LOW | WeatherProviderManager uses `async_setup` pattern; lazy init |
| #2 Config Storage Pattern | LOW | All new CONFs in `entry.options`, not `entry.data` |
| #5 Race Conditions on Startup | MEDIUM | Cycle A: state-change-driven init, returns None until first healthy probe. Cycle B: behaves correctly when manager returns None |
| #10 Cross-Restart State Loss | MEDIUM | Cycle B: `current_active_bucket` + `last_transition_at` persisted via RestoreEntity or URA DB (builder's call) |
| #11 UTC vs Local Timezone | MEDIUM | All `last_transition_at` comparisons use `dt_util.utcnow()` consistently |
| #14 Config Snapshot Staleness | LOW | `_refresh_config()` at top of evaluation; tunable knobs live-tunable |
| #17 Unbounded Retry Loops | LOW | Cycle A: state-driven failover, not timer-driven; no retry loops |
| #19 Untracked Background Tasks | LOW | All evaluation is sync code paths; no `async_create_task` in this scope |
| #20 Concurrent Reload Race | LOW | OverrideEngine emit/remove atomicity tested |
| #21 Timezone Naive/Aware Mix | MEDIUM | All datetime handling via `dt_util` helpers — no naive datetimes anywhere |
| #22 Enum Mismatch | LOW | Bucket class as `StrEnum` (`BucketClass`); provider state as `StrEnum` (`WeatherProviderHealth`) |
| #23 Observation Mode Gating | MEDIUM | Cycle B: emit gated at EC decision-cycle level; eval still runs + logs |
| #32 Form Field With No Runtime Reader | MEDIUM | Source-contract AST tests for every new CONF in both cycles |
| #35 Button Entity Missing Refresh Signal | N/A | No buttons added (intentional) |
| #36 Per-Zone Entity Bypasses ZoneManager Dedup | LOW | All new sensors live on CM/integration device; bucket tables live in Zone Manager via existing extension point |
| #37 API Contract Change | MEDIUM | `EnergyConstraint` adds `apparent_forecast_high_temp` field (additive, back-compat); audit by Reviewer B + Reviewer C |
| #38 `async_listen` Unsubscribe | MEDIUM | All `async_track_state_change_event` captures unsub into `self._unsub_handles`; cleaned in teardown |
| #39 Schema Mirror Drift in Test Fixtures | MEDIUM | Test fixtures extract `PresetOverride` shape from production `OverrideEngine`, never hand-copy |
| #40 Self-Validating Behavioral Tests | LOW | Composition tests drive real `OverrideEngine`, not a mock |
| #42 Lambda + async_create_task | LOW | No scheduler callbacks added (continuous eval inside existing decision cycle, not a new timer) |

---

## D. Documentation Deliverable (ships with each cycle)

Per CLAUDE.md, every cycle MUST update relevant user-facing docs. Specific deliverables:

### Cycle A ships:
- **Update `docs/ENERGY_MANAGEMENT_EXPLAINER.md`** — add §X "Weather Provider Manager" describing the ranked-list model + apparent-temp primitive
- **Update `docs/user-manual/ENERGY_COORDINATOR.md`** — add a section in §5 "Form fields" covering the 3 new CONFs + the migration story for the legacy single-entity CONF
- **Update `docs/HVAC_MANAGEMENT_EXPLAINER.md`** — note in §12 (Pre-Cool Likelihood) that HVAC predictor now reads from WeatherProviderManager via EnergyConstraint payload
- **No new doc** for Cycle A — it's infrastructure; folded into existing docs

### Cycle B ships:
- **NEW: `docs/user-manual/DYNAMIC_PRESET.md`** — dedicated user manual for the feature. Follows the format of `HVAC_COORDINATOR.md` (kill-switches, runtime sliders, form fields, three-layer gating, troubleshooting). ~250-350 lines.
- **Update `docs/ENERGY_MANAGEMENT_EXPLAINER.md`** — add §X "Dynamic Preset Override Source" describing the bucket classifier + dwell + hysteresis model. Brief — link out to the new dedicated doc for depth.
- **Update `docs/user-manual/HVAC_COORDINATOR.md`** — short reference in §6b (Energy Constraint integration) noting that HVAC presets may be additionally narrowed by dynamic preset overrides; user-visible via the existing `sensor.ura_active_preset_overrides` (Guest Mode Phase 1's diagnostic surface)
- **Update `README.md`** — add Dynamic Preset Management to the "What's in the box" section if it ships before/with another README refresh

---

## E. Open Questions (acceptable to defer to build time)

These are NOT blocking. The cycles can ship with builder's judgment OR a quick async ping to the user:

1. **Cycle A:** Default provider order when 3 providers configured but priorities unknown — alphabetical fallback? OR force user to drag-rank in the options flow (best practice)?
2. **Cycle A:** Should the legacy `CONF_ENERGY_WEATHER_ENTITY` be deprecated in Cycle A's release notes (with removal scheduled) or stay indefinitely for back-compat?
3. **Cycle B:** Default bucket boundaries (delta thresholds) — keep at -2/+8/+18 per this plan OR per-climate-region defaults?
4. **Cycle B:** Sleep preset auto-tracking — when user opts in for sleep, should defaults auto-derive as 1°F lower-high than home (current plan), OR require user to explicitly fill the sleep table?
5. **Cycle B:** Should the bucket transition log entry fire an NM notification (severity INFO, opt-in)? Probably no for v1 — log + sensor change is enough.
6. **Cycle B:** Override priority vs guest_mode — current default is 30 (lower); should there be a CM-level setting to flip it (e.g., during extreme heat, weather should win over comfort guests)?

---

## F. Out of Scope (explicit non-goals)

- Learning/adapting bucket boundaries from user comfort feedback. Manual config only.
- Per-zone bucket boundary overrides (zone-specific delta thresholds). House-global only.
- Multi-day rolling-average bucket classification (multi-day-weighted load smoothing). Today only — relies on Cycle A's `today_high`.
- Hourly intra-day bucket re-evaluation faster than the 5-min decision cycle. Continuous already covers it within URA's existing cadence.
- Coordinator-Manager-level override emit for `away` / `vacation` presets. Home + optionally sleep only.
- Replacing existing pre-cool / pre-heat logic. Pre-cool/pre-heat is EC's anticipatory load-shifting; dynamic preset is a different concept (per-zone range adjustment). They coexist.
- Voice/AI bucket override ("URA, make it cooler today"). Future cycle if requested.

---

## G. Ship readiness summary

| Item | Cycle A | Cycle B |
|---|---|---|
| Tier | 2-DB (user-invoked) | 2-DB (user-invoked) |
| Reviewers | 3 parallel (A/B/C) | 3 parallel (A/B/C) |
| Live validation (Review D) | required pre-Cycle-B | required pre-close |
| Test file | `test_v47x_weather_manager.py` | `test_v47x_dynamic_preset.py` |
| Docs deliverable | 3 updates | 1 new doc + 3 updates |
| Effort estimate | ~12-15h | ~15-20h |
| Dependencies | None outside this plan | Cycle A + Guest Mode Phase 1 shipped + stable |

**Ship cadence guidance:** 
- Cycle A goes first. After live validation passes, wait ≥ 1 release cycle (no other URA shipping) for stability evidence before starting Cycle B build.
- If during Cycle A's live validation a CRITICAL bug surfaces, fix-and-reship Cycle A before considering Cycle B.
- Cycle B blocks if Guest Mode Phase 1's `OverrideEngine` hasn't yet shipped or has unresolved Tier 2 findings.
