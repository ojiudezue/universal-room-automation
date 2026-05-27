# PLANNING v4.7.x — Dynamic Preset Management (Weather-Forecast-Driven)

**Status:** Plan drafted, awaiting user open-question answers before split into v-numbered cycles
**Tier:** TWO cycles, classified separately (see below)
**Predecessor:** v4.5.10 (HVAC runtime tunables) + v4.5.9 (HVAC cover intent)
**Sibling-in-flight:** `PLANNING_v4.7.x_guest_mode_actuation_phase1.md` — OWNS the shared per-(zone, preset, range) override schema. This plan is a CONSUMER of that schema.
**Recall hint:** "Dynamic preset management"
**Filename version:** `v4.7.x` placeholder — actual numbers assigned at deploy time (likely v4.7.x for Cycle A, v4.7.x+1 for Cycle B).

---

## Feedback Round 1 — incorporated 2026-05-27

Three changes from user review (file at `~/.../Codetxfer/PLANNING_v4.7.x_dynamic_preset_management.md`):

1. **Drop the cron, piggyback on the decision cycle.** No new scheduler. See "Morning recompute trigger" section — gate becomes `now.hour >= recompute_hour AND last_recompute_date != today`, evaluated each tick.
2. **Cool bucket default high: 78 → 77.** Tighter cool-day comfort target.
3. **Sleep preset defaults: 1°F lower high per bucket than home.** Codifies user's empirical preference. See per-zone bucket table section.

No structural changes to the two-cycle phasing or shared override schema. Open Questions §B (1-6) unchanged.

---

## TL;DR

URA HVAC presets (`home`, `sleep`, `away`) carry fixed temperature RANGES per zone. One range does not fit every day — a 70–76°F `home` range that paces the AC nicely on a 78°F day forces the AC to grind all afternoon on a 98°F day. User policy: **always ranges, never absolute setpoints, never daily user fiddling.**

Fix: each morning (~06:00 local, AFTER the day's forecast updates — explicitly NOT midnight), URA reads the day's weather forecast, classifies into a condition bucket (`cool`/`mild`/`hot`/`extreme`), and emits per-zone preset-range overrides into the shared override schema (owned by Guest Mode Phase 1). Override has lower priority than guest mode by default, decays at midnight, fully observable via two new sensors.

**Hard dependency:** weather forecast redundancy must ship FIRST. Single-provider outage today leaves URA blind. **Cycle A delivers ≥2 (target 3) forecast providers with priority order, failover, staleness, divergence detection.** **Cycle B builds dynamic preset adjustment on top.**

---

## Tier classification

| Cycle | Scope | Tier | Why |
|---|---|---|---|
| **Cycle A — Weather Forecast Redundancy** | New `WeatherProviderManager`, 3 new sensors, divergence detection, options-flow provider list. No DAO changes. | **Tier 2** | Multi-file feature; new sensors; failover state machine. Not DB-sensitive. |
| **Cycle B — Dynamic Preset Adjustment** | New `WeatherDrivenPresetOverrideSource` plugged into shared schema, bucket classification, morning recompute scheduler, 2 sensors + 1 button, per-zone opt-in + bucket-table CONFs. | **Tier 2** | Multi-file; depends on Cycle A; composes with Guest Mode schema (cross-cycle integration risk). |

Two reviewer framings per CLAUDE.md Tier 2.

---

## Goal + Why

### Goal
Per-zone HVAC preset RANGES adapt automatically each morning to the day's weather forecast, with zero user touch on a normal day. User retains control via per-zone opt-in, per-bucket range table customization, and a global kill switch.

### Why
1. **Comfort drift on extreme days** — cool-day-tuned ranges undershoot on hot days
2. **User policy: ranges, not setpoints** — eliminate day-by-day fiddling
3. **Forecast-driven preconditioning already in URA** (v4.5.10 `CONF_HVAC_PRECOOL_FORECAST_HIGH`) — range adjustment is the natural next step
4. **Composability with Guest Mode** — Phase 1 establishes the override schema; weather is the second-most-natural source

### Non-goals
- Changing the preset model (no new presets)
- Per-room (vs per-zone) adjustment
- ML-learned ranges (user authors once)
- Multi-day planning (today only)
- Hourly intra-day re-selection

---

# Cycle A — Weather Forecast Redundancy

**Goal:** Replace any single-provider weather-forecast reliance with a prioritized provider list (≥2, target 3), failover, staleness window, divergence detection.

## Discovery / read-before-build

1. **Enumerate every weather consumer in `custom_components/universal_room_automation/`.** Likely: HVAC predictor (`hvac_predict.py` — `CONF_HVAC_PRECOOL_FORECAST_HIGH`, `CONF_HVAC_PREHEAT_FORECAST_LOW`), HVAC cover controller, energy coordinator (verify if weather or Enphase-native).
2. **Verify HA forecast API shape.** Legacy `state.attributes["forecast"]` is deprecated. Modern: `weather.get_forecasts` service OR `async_forecast_daily()`/`async_forecast_hourly()` methods. Verify against HA dev docs at build time.
3. **Verify live HA `weather.*` entities.** Use `ha-mcp` to list. Common: `weather.home`, `weather.pirateweather`, `weather.openweathermap`, `weather.nws_*`.
4. **Confirm whether URA has centralized weather read today.** If no, Cycle A migrates every consumer through the manager.

## Design

### Provider list + priority
- New CM CONF `CONF_WEATHER_PROVIDERS` — ordered list of weather entity IDs
- Default: empty (Cycle B requires ≥2 to activate)
- Active = first healthy in list (primary → secondary → tertiary)

### Failover semantics
- Healthy if: state ≠ unavailable/unknown; last forecast update within `CONF_WEATHER_STALENESS_MAX_HOURS` (default 6h); `async_forecast_daily` returns ≥1 entry for today
- On failover: log INFO + emit `ura_weather_active_provider_changed` event

### Staleness window
- `CONF_WEATHER_STALENESS_MAX_HOURS` (default 6)
- All stale → `staleness_degraded` flag; Cycle B refuses new overrides (falls back to last-applied OR base preset)

### Divergence detection
- ≥2 healthy providers → compute |today_high_A − today_high_B|
- Threshold `CONF_WEATHER_DIVERGENCE_THRESHOLD_F` (default 5°F)
- Exceeded → divergence flag sensor + WARNING + `ura_weather_divergence_detected` event; Cycle B uses primary, flags low-confidence
- 3 providers: use median; flag when max−min > threshold

## Deliverables

### A1 — `WeatherProviderManager` module
New file `weather_manager.py` (or wire into existing diagnostics module).

Responsibilities:
- Ordered provider list
- `async def get_today_forecast() -> WeatherForecast | None`
- Properties: `active_provider`, `healthy_providers`, `divergence_f`, `staleness_status`
- Subscribe to state changes on every provider; recompute health
- Dispatcher signals on provider change + divergence threshold

**Acceptance**
- **Verify:** With 3 providers, disable primary → log "Active weather provider: weather.X → weather.Y (reason: primary unavailable)" within 1 update cycle
- **Verify:** All 3 unavailable → `active_provider` None; `staleness_status="all_stale"`
- **Sensor:** `sensor.ura_weather_active_provider` shows entity_id (or `none`/`all_stale`)
- **Test:** Mock 3 weather entities; drive 5 failover scenarios (P1 unavail, P1+P2 unavail, all unavail, all healthy+divergent, P1 stale+P2 fresh)
- **Test:** AST/source-contract — `get_today_forecast` returns active provider's value, NOT first-in-list
- **Live:** Log shows manager init with provider count = configured; `sensor.ura_weather_active_provider` shows expected primary

### A2 — Sensors
Three new on CM device:

| Sensor | State | Attributes |
|---|---|---|
| `sensor.ura_weather_active_provider` | entity_id or `none` | `priority_rank`, `healthy_providers_count`, `total_providers_count`, `failover_reason` |
| `sensor.ura_weather_forecast_today_high` | float °F | `provider_source`, `forecast_low`, `median_high_across_providers`, `confidence` (`high`/`low_divergent`/`degraded_single`/`unavailable`) |
| `binary_sensor.ura_weather_divergence` | on/off | `divergence_f`, `threshold_f`, `provider_high_map` |

**Acceptance**
- **Verify:** All three visible on CM device after restart
- **Sensor:** `forecast_today_high` matches active provider's today's high within 0.5°F
- **Sensor:** divergence ON when providers > threshold apart
- **Test:** Source-contract per sensor (Bug Class #32)
- **Live:** Mock provider with fixed offset → divergence flips ON

### A3 — CM options-flow integration
- `CONF_WEATHER_PROVIDERS` — multi-select of `weather.*`, ordered
- `CONF_WEATHER_STALENESS_MAX_HOURS` — int 1–24, default 6
- `CONF_WEATHER_DIVERGENCE_THRESHOLD_F` — float 1–20, default 5

**Acceptance**
- **Verify:** All three fields visible; provider ordering persists across reconfig
- **Test:** Source-contract per CONF (Bug Class #32)
- **Live:** Add/remove provider via UI; manager reflects without restart

### A4 — Migration of existing weather consumers
Every consumer identified in Discovery routes through `WeatherProviderManager.get_today_forecast()`.

**Acceptance**
- **Verify:** With Cycle A deployed, disabling hardcoded weather entity does NOT break HVAC pre-cool (manager fails over)
- **Test:** Grep/AST — NO direct `hass.states.get("weather.*")` calls in HVAC predictor
- **Live:** HVAC predictor log shows "weather source: weather.<active>"

### A5 — Tests + docs
- `quality/tests/test_v47x_weather_redundancy.py`
- Source-contract per CONF + sensor (Bug Class #32)
- Behavior tests for 5 scenarios in A1
- README_v4.7.x.md
- QUALITY_CONTEXT.md — new bug class candidate "Single-Provider Forecast Dependency" if v4.5.x consumer found that broke silently

## Out of scope (Cycle A)
- Per-zone weather (multi-microclimate)
- Hourly forecast plumbing
- Provider-quality scoring / accuracy tracking
- Forecast caching across restarts

## Open questions (Cycle A)
1. Default staleness window — 6h plausible?
2. Divergence threshold — 5°F default? Per-season tunable?
3. All providers stale → (a) Cycle B uses last-known + flags low-confidence, OR (b) HVAC reverts to base?
4. OK installing a 3rd weather integration? PirateWeather needs API key; Met.no free+keyless; NWS US-only+free.

## Risks (Cycle A)
1. **Forecast API shape drift** — verify at build, don't bake in either path
2. **Provider entity_ids changing** — mutable via options flow; update_listener
3. **Async init race** — manager init before weather populated; lazy-init via state-change listener
4. **Divergence false positives on transition days** — evaluate on today's daily high, not raw observations

---

# Cycle B — Dynamic Preset Adjustment

**Depends on:** Cycle A shipped + ≥2 providers configured + `WeatherProviderManager.get_today_forecast()` returning valid data.

**Goal:** Each morning, classify today's forecast into a condition bucket and emit per-zone preset-range overrides into the shared override schema.

## Discovery / read-before-build

1. **Confirm Guest Mode Phase 1 override schema shipped + stable.** Cycle B blocks until then.
2. **Identify morning recompute integration point.** Candidates: existing HVAC schedule helper, new `async_track_time_change` in HVAC at 06:30, routine-awareness sensor (v4.6.0) if it fires "morning_started".
3. **Verify current per-zone preset storage** — runtime structure for `(zone, preset_name, low, high)` tuples.

## Design

### Bucket classification (default)

| Bucket | Forecast high (°F) | Intent |
|---|---|---|
| `cool` | < 75 | AC barely needed; wider OK; `home` ≈ 70–78 |
| `mild` | 75–84 | Default; no override |
| `hot` | 85–94 | Narrower; `home` ≈ 70–74 |
| `extreme` | ≥ 95 | Tightest; `home` ≈ 70–73; bias earlier pre-cool |

**User-configurable boundaries** (see Open Q1).

### Composition with shared override schema
- New override source `weather_driven` (or `dynamic_preset_weather` — finalize with Guest Mode naming)
- Each morning, per opted-in zone, emit one record per applicable preset:
  ```python
  {
    "source": "weather_driven",
    "zone_id": "<zone>",
    "preset": "home",  # + "sleep" if opted in
    "low": 70.0, "high": 74.0,
    "priority": <see below>,
    "expires_at": <local midnight tonight>,
    "reason": "bucket=hot (forecast_high=89.2°F, provider=weather.pirateweather)"
  }
  ```
- Priority: **default LOWER than guest mode** (guest=50, weather=30). User-configurable via `CONF_DYNAMIC_PRESET_PRIORITY` (1–100, default 30).
- Expiry: local midnight tonight. Next morning's recompute emits fresh override.
- Composition rule (owned by Guest Mode schema): highest-priority active wins; tie → most-recent. NOT re-designed here.

### Morning recompute trigger

**No separate scheduler.** Piggyback on URA's existing 5-min decision cycle (Feedback Round 1, 2026-05-27 — "Why a special Cron? Why not a normal decision cycle that coincides with the morning? No new tools if we don't need it.").

Mechanism:
- On every decision tick, check: `now.hour >= CONF_DYNAMIC_PRESET_RECOMPUTE_HOUR AND last_recompute_date != today`
- If true, recompute; set `last_recompute_date = today`
- 5-min granularity is plenty for a once-per-day morning recompute (worst-case 5-min skew from configured hour; no user impact)
- Persist `last_recompute_date` to URA's existing storage so HA restart at, say, 10:00 with the day's compute not yet done still triggers correctly

`CONF_DYNAMIC_PRESET_RECOMPUTE_HOUR` (1–12, default 6) — not midnight, because many weather providers don't publish tomorrow's forecast until early morning.

Read `get_today_forecast()` when the gate fires:
- Unhealthy/stale → log WARNING, fire `ura_dynamic_preset_skipped`, no-op
- Healthy → classify bucket → emit overrides

Also fire on:
- HA startup catch-up (just covered by the gate logic — first cycle after startup hits the condition if it's past the recompute hour and today's date hasn't been stamped)
- User button press (B5)
- Provider failover where today's high jumps >2°F (handled in B2)

### Per-zone × per-bucket range table
**Configuration: options flow per zone (NOT YAML).** Reasons: URA pattern is options-flow (v4.5.10 enforced); options flow reloads on save; consistent UX; small data (~40 numbers across 5 zones).

Form layout per zone (in CM options, under existing zone subsection):
```
[ ] Enable dynamic preset adjustment for this zone

If enabled (defaults for `home` preset — Feedback Round 1 2026-05-27 reduced cool 78 → 77):
  Bucket: cool       low [70.0]  high [77.0]
  Bucket: mild       low [70.0]  high [76.0]   (defaults from current home preset)
  Bucket: hot        low [70.0]  high [74.0]
  Bucket: extreme    low [70.0]  high [73.0]

[ ] Also apply to 'sleep' preset (default OFF)
  If checked, defaults are 1°F LOWER high than home per bucket
  (Feedback Round 1 2026-05-27 — "Usually sleep is one degree lower on
  the high range than home"):
    Bucket: cool       low [70.0]  high [76.0]
    Bucket: mild       low [70.0]  high [75.0]
    Bucket: hot        low [70.0]  high [73.0]
    Bucket: extreme    low [70.0]  high [72.0]
```

Defaults: `mild` matches current `home`; others placeholder until user fills (form-validate all 4 rows filled before save). Not opted in → no override.

## Deliverables

### B1 — `WeatherDrivenPresetOverrideSource` module
New file `dynamic_preset_overrides.py`. Holds per-zone × per-bucket × per-preset table, classifies today's bucket from `WeatherProviderManager`, emits overrides into shared schema, re-evaluates on provider failover crossing bucket boundary.

**Acceptance**
- **Verify:** 96°F forecast → opted-in zones receive `extreme` at 06:00; sensor shows bucket
- **Verify:** 78°F forecast → `mild` overrides emitted (no effective change but record visible)
- **Test:** Boundary classification: 74.9→cool, 75.0→mild, 84.9→mild, 85.0→hot, 94.9→hot, 95.0→extreme
- **Test:** 3 zones (2 opted in, 1 not) → only 2 overrides emitted
- **Test:** Source-contract — records carry `source="weather_driven"`, `priority=<configured>`, `expires_at=<midnight>`
- **Live:** URA log at 06:00 — "DynamicPreset: bucket=<X> for N zones, emitted N overrides"

### B2 — Morning recompute scheduler
- `async_track_time_change` at configured hour daily
- Startup catch-up: if last recompute < today's hour, fire immediately
- Subscribe to `ura_weather_active_provider_changed`; re-emit if new bucket

**Acceptance**
- **Verify:** Restart at 14:00 → immediate catch-up (log at startup, not next 06:00)
- **Verify:** Failover at 11:00, new provider reports 92°F (still hot) → no re-emit. New provider 96°F (extreme) → re-emit
- **Test:** Time-mock; handler fires once per day at hour
- **Live:** Set hour to 1 minute future via UI; observe fire in log

### B3 — Sensors
Two on CM device:

| Sensor | State | Attributes |
|---|---|---|
| `sensor.ura_dynamic_preset_active_bucket` | `cool`/`mild`/`hot`/`extreme`/`unavailable` | `forecast_high_f`, `forecast_low_f`, `provider_source`, `classified_at`, `bucket_boundaries`, `confidence` |
| `sensor.ura_dynamic_preset_overrides_applied` | int count | `breakdown` (list of `{zone,preset,low,high}`), `expires_at`, `skipped_zones`, `last_recompute_at` |

**Acceptance**
- **Verify:** Both visible after deploy
- **Sensor:** bucket sensor matches today's classification; updates on next morning or failover-driven re-eval
- **Sensor:** count = opted-in zones × presets emitted
- **Test:** Source-contract per sensor (Bug Class #32)
- **Live:** Sensor populated within 1 minute post-deploy (startup catch-up)

### B4 — Per-zone opt-in CONF + bucket table
- `CONF_DYNAMIC_PRESET_ENABLED_PER_ZONE` — dict[zone_id, bool] OR per-zone field
- `CONF_DYNAMIC_PRESET_BUCKET_TABLE_PER_ZONE` — nested `{zone: {bucket: {low, high}}}`
- `CONF_DYNAMIC_PRESET_INCLUDE_SLEEP_PER_ZONE` — dict[zone_id, bool], default False
- `CONF_DYNAMIC_PRESET_BUCKET_BOUNDARIES` — global; default `{cool:75, mild:85, hot:95}`
- `CONF_DYNAMIC_PRESET_PRIORITY` — int 1–100, default 30
- `CONF_DYNAMIC_PRESET_RECOMPUTE_HOUR` — int 1–12, default 6 (gate on existing decision cycle; no separate scheduler)

**Acceptance**
- **Verify:** CM options has "Dynamic Preset Adjustment" subsection
- **Verify:** Disabling a zone removes overrides on next recompute
- **Test:** Source-contract per CONF (Bug Class #32)
- **Test:** Form validation — low ≤ high; all 4 buckets filled if opted in
- **Live:** Reconfigure zone via UI; next recompute uses new table without restart

### B5 — `button.ura_dynamic_preset_recompute_now`
User-pressable button forces immediate recompute.

**Acceptance**
- **Verify:** Button visible on CM device
- **Verify:** Press → log "manual recompute requested"; sensors update within seconds
- **Test:** Press handler calls same recompute path as cron (no divergent code)
- **Live:** Press; observe sensor refresh + override count change

### B6 — Composition tests with Guest Mode
Joint integration (requires Guest Mode Phase 1):
- Weather priority 30 + guest priority 50, both active → guest wins
- Weather priority 60 + guest priority 50 → weather wins
- Weather active, guest toggles ON → guest layered on top within 1 update
- Weather expires at midnight → guest remains; new weather at 06:00

**Acceptance**
- **Verify:** All scenarios resolve per priority
- **Test:** Mock both sources against shared resolver; assert winner per scenario
- **Live:** Enable guest while weather active; HVAC reflects guest range within seconds

### B7 — Tests + docs
- `quality/tests/test_v47x_dynamic_preset_management.py`
- Source-contract per CONF + sensor + button
- Bucket boundary tests (off-by-one at 75.0, 85.0, 95.0)
- Override emit/expire lifecycle
- Composition tests with Guest Mode (B6)
- README_v4.7.x+1.md
- QUALITY_CONTEXT.md candidate: "Override Source Without Priority Declaration"

## Out of scope (Cycle B)
- Learning/adapting bucket boundaries from feedback
- Per-zone bucket boundary overrides (use per-zone tables instead)
- Multi-day rolling averages
- CM-level `away` preset overrides
- Hourly bucket re-evaluation

## Open questions (Cycle B)
1. **Bucket boundaries.** Defaults: cool < 75 / mild 75–84 / hot 85–94 / extreme ≥ 95. Texas climate need different scale?
2. **Default per-zone preset ranges per bucket** — core decision. Suggested for Master south-facing: cool 70–78, mild 70–76, hot 70–74, extreme 70–73.
3. **Which zones opt IN?** South-facing master/family → YES; back hallway/utility → NO.
4. **Override priority vs guest mode** — default weather=30, guest=50 (guest wins). Or extreme weather should win?
5. **Recompute hour** — 06:00 OK with morning forecast availability?
6. **Include `sleep` preset?** Default OFF.

## Risks (Cycle B)
1. **Shared schema drift** — integration tests against actual schema module (not mock); CI catches changes
2. **Override priority bug** — wrong comparator (<vs>); explicit test matrix in B6
3. **Bucket flapping on boundary days** — morning forecast only; intra-day re-emit only if NEW bucket differs
4. **Opt-in zone with empty table** — form rejects save; runtime skips with WARNING if corrupted
5. **Cycle A degraded but B active** — all providers stale → no new overrides; yesterday's expire at midnight; HVAC reverts to base. NM notification when skipped.
6. **Cross-cycle ordering** — Cycle A live-validated + stable ≥1 cycle before B starts; B's discovery explicitly checks

---

## Tier 2 review plan

Tag `pre-review-v<version>` before applying ANY fixes.

### Cycle A reviewers (parallel)
- **A:** failover state machine across 5 scenarios; staleness math; divergence off-by-one; sensor attr completeness; Bug Classes #1, #28, #32
- **B:** init order vs weather availability; state-change listener cleanup on entry unload; update_listener handling provider reorder; consumer migration completeness (no leftover direct `weather.*` reads); restart resilience

### Cycle B reviewers (parallel)
- **A:** bucket boundary classification; override shape matching shared contract; priority comparator; expiry math at DST; per-zone opt-in semantics
- **B:** morning cron + startup catch-up + failover re-eval interleavings; override-source registration; composition edge cases; recompute idempotency (multiple triggers same minute → no duplicates)

### Live validation (Review 3)
- **A:** force failover; verify sensor flip + log. Force divergence with mock; verify sensor + event
- **B:** verify 06:00 cron; verify overrides emit; verify Guest+Weather composition; verify expiry at midnight; verify next-morning recompute

---

## Acceptance criteria (cross-cycle)

### Cycle A done when:
- `WeatherProviderManager` shipped with ≥3-scenario failover
- 3 sensors visible + populated
- Options flow accepts provider list, staleness, divergence
- ALL weather consumers migrated through manager (no direct `hass.states.get("weather.*")` in domain code)
- Tier 2 review docs written; CRITICAL/HIGH fixed
- Live validation: failover + divergence + sensor population observed

### Cycle B done when:
- `WeatherDrivenPresetOverrideSource` emits valid overrides into shared schema
- Morning cron + startup catch-up + failover re-eval functioning
- 2 sensors + 1 button on CM device, populated
- Per-zone opt-in + bucket table options flow accepts and validates
- Cross-source composition tests pass (weather + guest priority resolution)
- Tier 2 review docs written; CRITICAL/HIGH fixed
- Live validation: morning recompute fires + sensors update + composition resolves

---

## Deliberately deferred

- Version numbers — assigned at deploy
- Whether Cycle A and B share a single release — default separate for clean Tier 2 review burn-down
- Bucket boundary defaults beyond placeholder — awaits user (Open Q1)
- Per-zone preset range table contents — awaits user (Open Q2)
- Final override priority — awaits Guest Mode Phase 1 published default
- `sleep` preset inclusion default — awaits user (Open Q6)
