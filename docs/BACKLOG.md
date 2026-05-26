# URA Backlog — As of v4.6.10 (May 2026)

## v4.6.10 — Setup Telemetry + Anomaly Wiring + Deferred Polish — SHIPPED 2026-05-18

- D1 boot telemetry capture, D2 `sensor.ura_setup_duration_seconds`, D3 anomaly observation push (scaffold-only — see v4.6.11 below)
- D5a `_PERSON_LAST_STATE_SKIP_VALUES` module constant, D5b docstring typo fix
- D6 MONETARY state-class fixes on 5 sensors (3 in aggregation.py, 2 in sensor.py)
- D7 first dogfood of subagent enforcement protocol (planner → builder → validator → 2 parallel reviewers)
- Tier 2 review: 1 CRITICAL + 2 HIGH + 4 MEDIUM addressed; 3 LOW deferred to v4.6.11

## v4.6.11 — D3 Persistence + Live-Validation Carryovers + LOW Polish (Tier 2, QUEUED)

**Recall hint:** "Resume v4.6.11 — D3 persistence + live-validation carryovers"

### CRITICAL — D3 anomaly detection persistence + dispatch

From v4.6.10 Tier 2 review (convergent A C1 + B B1). The currently-shipped D3 anomaly observation push is functional code, but the detection it enables cannot fire for a structural reason: `AnomalyDetector._baselines` is an in-memory dict that resets to `{}` on every HA restart. `setup_duration_seconds` accumulates exactly ONE observation per boot. `minimum_samples=10` is therefore unreachable. The baseline can never mature.

Two paths to choose between in the planning cycle:

1. **DB-backed baseline persistence** — extend `AnomalyDetector` (or wrap it) to checkpoint baseline statistics (n, mean, variance) to a new `metric_baselines` table. Restored on init. ~80 prod LoC + schema migration + ~60 test LoC. **Tier 2-DB** (schema change → 3x parallel reviews per CLAUDE.md protocol).
2. **Query-replay baseline reconstruction** — query the last N rows from `metric_observations` (or `anomaly_log`) at init and replay them into the baseline. Avoids new schema; requires observations to be persisted in the first place (which D3 currently doesn't do). ~60 prod LoC + ~50 test LoC. Tier 2.

Either way: after baseline persistence works, ADD the missing `store_event(AnomalyEvent(...))` call after `record_observation` returns a non-None anomaly (following `safety.py:1684-1715` pattern) to actually fire the NM cascade.

Update the v4.6.10 code comment + log message that say "scaffold-only, no dispatch" once persistence + dispatch are wired. Without this update, future readers won't trust new code in the area.

### HIGH — Three MONETARY sensors missed by D6 sweep test (live-validation 2026-05-18)

Live validation post v4.6.10 deploy found THREE PredictedCost sensors still have the MONETARY + MEASUREMENT incompatibility:

- `sensor.universal_room_automation_predicted_cost_today` (state class `measurement`, device class `monetary`)
- `sensor.universal_room_automation_predicted_cost_week`
- `sensor.universal_room_automation_predicted_cost_month`

**Root cause:** these classes set `_attr_state_class = SensorStateClass.MEASUREMENT` AND `unit_of_measurement = "$"` but never explicitly declare `_attr_device_class = SensorDeviceClass.MONETARY`. HA auto-derives `device_class = MONETARY` from the dollar-sign unit. The v4.6.10 D6 sweep test (`test_no_monetary_measurement_attr_in_aggregation`) grepped for the literal string `MONETARY` in the class body, so PredictedCost classes (which only contain `"$"`) were never matched.

**Fix:**
- Change `_attr_state_class = SensorStateClass.MEASUREMENT` → either remove (predicted values are not statistically meaningful as MEASUREMENT) OR `SensorStateClass.TOTAL` if the predicted-cost values are interpreted as daily/weekly/monthly running estimates
- Decision per HA semantics: PredictedCost is a forward-projected single value per query window, not a cumulative running total → remove `_attr_state_class` entirely (no state_class)

**Test broadening (Bug Class proposal):**
- Add proposed bug class **"Sweep test with narrow detection regex"** to `docs/QUALITY_CONTEXT.md`
- Broaden the D6 sweep test to ALSO catch sensors where:
  - `unit_of_measurement` is dollar-prefixed (`"$"`, `"$/h"`, `"USD"`, `"USD/h"`, `"USD/day"`) — implicit MONETARY via HA inference
  - AND `_attr_state_class` is `MEASUREMENT` or `TOTAL_INCREASING`
  - This catches the auto-derivation path, not just explicit `_attr_device_class = MONETARY` declarations

LoC: ~10 prod (3 sensor edits) + ~30 test (broader sweep). Should also re-run the sweep across the full codebase to find any other dollar-unit + incompatible-state_class combos.

### MEDIUM — Setup duration sensor capture window is too narrow (live-validation 2026-05-18)

`sensor.ura_coordinator_manager_ura_setup_duration` reports **3.221s** post-restart. This is only the CM init block (between `CoordinatorManager(...)` construction and `coordinator_manager.async_start()` returning). It excludes:

- Person coordinator init (runs BEFORE the CM block)
- Platform setup callbacks (sensor/binary_sensor/button — runs AFTER CM init returns)
- Room/zone coordinator instantiation for all rooms
- Initial entity state reads

User-visible URA setup wall-time is closer to ~30-60s on a typical restart. The 3.221s is honest about what it measures, but the "URA Setup Duration" label overpromises.

**Fix:** Move the end waypoint OUT of `async_setup_entry`. Two options:
1. Subscribe to a coordinator-ready signal (e.g., `SIGNAL_COORDINATORS_READY` if it exists, or invent one) and capture the timestamp in the signal handler.
2. Schedule a `entry.async_create_background_task` with `await hass.async_block_till_done()` to wait for platform setup to fully complete, then capture.

Option 1 is cleaner but requires the signal infrastructure. Option 2 is mechanical but couples timing to HA's task-queue semantics.

Either way: when the wider window is shipped, `setup_duration_seconds` should report ~30-60s on a healthy boot, making the anomaly baseline (once it has persistence per the CRITICAL above) actually useful for detecting regressions.

LoC: ~30 prod (new signal handler or background-task waypoint) + ~20 test. Conditional: only ship after the D3 persistence fix lands, since the anomaly metric needs the wider window AND the persistent baseline together to be useful.

### LOW — Carryovers from v4.6.10 review

- `quality/tests/test_v4_6_10_setup_telemetry.py` uses `asyncio.get_event_loop().run_until_complete()` — deprecated since Python 3.10. Use `asyncio.run()` or pytest-asyncio.
- `_make_observation_coro()` factory in `__init__.py` is unnecessary indirection (closure-over-nothing). Simplify once persistence wiring is in.
- Pre-existing Bug Class #21 violation at `coordinator_diagnostics.py:824` (`datetime.utcnow()` — should be `dt_util.utcnow()`). Noted by Review B (L3). One-line fix.

### LOW — Carryover from v4.6.9 review

- `domain_coordinators/person_seed_helpers.py` extraction (drift-risk mitigation for inlined test bodies). ~30 prod + ~40 test LoC. Deferred from v4.6.10 per the planning doc's conditional rule (helpers reference `self.data` so pure-free-function extraction would require coupling the new module to coordinator state).

### Subagent protocol regressions discovered during v4.6.10 (file as v4.6.11 sub-deliverable)

- `ura-planner` agent missing Write tool — delivered plan inline; main thread had to save the file. **Fix:** add `Write` to ura-planner AGENT.md frontmatter tools list.
- `ura-validator` baseline-diff methodology has artifact: new test files execute against baseline production code and fail (their imports resolve against stale production). Directional result correct, absolute counts slightly inflated by ~18. **Fix:** either also stash the new test files during baseline-diff run, OR filter pytest to exclude tests added in the current branch.

### Estimated total budget v4.6.11

| Deliverable | Prod LoC | Test LoC | Tier |
|---|---|---|---|
| D3 persistence + dispatch | ~80 (DB path) or ~60 (replay path) | ~60 / ~50 | 2-DB / 2 |
| D6 PredictedCost MONETARY fix | ~10 | ~30 | 1 |
| Setup duration window widening | ~30 | ~20 | 1 |
| LOW carryovers (3 from v4.6.10) | ~10 | ~10 | — |
| LOW carryover (1 from v4.6.9) | ~30 | ~40 | — |
| Subagent protocol fixes | ~5 | 0 | — |
| **TOTAL (DB persistence path)** | **~165** | **~160** | Tier 2-DB |
| **TOTAL (replay persistence path)** | **~145** | **~150** | Tier 2 |

Tier decision deferred to planner. DB path is cleaner architecture; replay path is smaller blast radius. Either way: Tier 2 ceremony (2+ parallel reviewers).

---

# URA Backlog — As of v4.6.9 (May 2026)

## v4.6.9 — Boot-State Robustness — SHIPPED 2026-05-18

Both user-reported papercuts from v4.6.8 deploy day are resolved:

1. **Previous Location sensors stuck "Unknown" after restart** — `PersonPreviousLocationSensor` and `PersonPreviousSeenSensor` now extend `RestoreEntity`. On `async_added_to_hass`, each reads the last persisted HA state and seeds the coordinator via new idempotent `PersonTrackingCoordinator.seed_previous_location` / `seed_previous_location_time` methods. Persons who were already-away at shutdown retain their last-seen room across restarts.

2. **Four CM-device buttons greyed out at first boot** — `NMAcknowledgeButton`, `ClearBayesianBeliefsButton`, `AcknowledgeRoutineChangesButton`, `AnomalyDiagnosticDumpButton` each got `async_added_to_hass` subscribing to the relevant coordinator-ready signal (`SIGNAL_NM_READY`, `SIGNAL_BAYESIAN_READY`, `SIGNAL_DATABASE_READY`). Two new signals added to `signals.py`; dispatch sites wired in `__init__.py`.

**Bonus fix — NM latent bug:** `hass.data[DOMAIN]["notification_manager"]` was never registered (only `coordinator_manager.set_notification_manager(nm)` was called). This meant `NMAcknowledgeButton.available` always returned `False` AND the three NM service handlers always logged warnings. One-line fix at `__init__.py:1978` closes the root cause.

---

## v4.6.10 — Deferred from v4.6.9 review

Tier 1 review of v4.6.9 surfaced three items not blocking deploy. Address in a future polish cycle:

1. **MEDIUM #2 — Inlined seed-method test bodies** (`quality/tests/test_v4_6_9_boot_state_robustness.py` `TestSeedPreviousLocation*`). Tests re-implement the seed logic rather than calling `PersonTrackingCoordinator.seed_previous_location` directly, because the module imports `homeassistant.components.person` which the lightweight test env can't load. **Drift risk:** future edits to the production seed methods (e.g. tightening sentinel set, fixing tz handling) will pass the tests while production regresses. **Fix:** extract seed logic to a leaf module `domain_coordinators/person_seed_helpers.py` (no `homeassistant.components.person` imports), have `PersonTrackingCoordinator` delegate to it, and have tests import the helper directly. ~30 prod LoC + ~40 test LoC. Bug class: proposed **"Test inlines production logic (drift risk)"**.

2. **Module-level `_SKIP_STATES` constant** — currently a local in both `PersonPreviousLocationSensor.async_added_to_hass` and `PersonPreviousSeenSensor.async_added_to_hass` (`aggregation.py`). Promote to a module-level constant to share between both sensors. Cosmetic; ~5 LoC.

3. **Comment typo in `person_coordinator.py:1011-1012`** — references `self._data` but the actual attribute is `self.data`. Cosmetic; 2 LoC.

Promote when next touching either file. Not a standalone cycle unless others queue up.

---

## Quality Enforcement Hardening — ARCHIVED, build on degradation

**Status:** Shelf-ready, NOT queued. Build only if quality signals degrade per documented trigger criteria.

**Plan:** `docs/planning/archive/PLANNING_quality_enforcement_hardening.md`

Codifies enforcement for the v4.6.3 Tier 2-DB directives (CLAUDE.md Tier 2-DB, QUALITY_CONTEXT.md Bug Classes #39/#40/#41, DEVELOPMENT_CHECKLIST.md DB-Sensitive Cycle Checklist). Four layers, build in priority order: (1) `validate-deploy.sh` + post-deploy sentinel check, (2) pytest meta-tests for the new bug classes, (3) pre-deploy baseline snapshot in `deploy.sh`, (4) Claude Code PostToolUse hook on `Agent` for commit verification.

**Trigger criteria** (build when ANY fires):
- CRITICAL bug ships to production despite review
- Tier 2-DB cycle shipped with <3 independent reviews under pressure
- Behavioral test fixture drifts from production schema
- Build agent reports completion with uncommitted changes more than once in a quarter
- Dedup-mask under-refresh observed in a sensor
- Multi-developer expansion (URA gains a 2nd active contributor)

**Cost:** ~5-6 hours for full build, partial builds supported (e.g., Layer 1 alone is ~2 hours).

## Guest Mode Actuation — PLAN FILED 2026-05-24 (Tier 2, Phase 1 ready to build)

**Status:** Phase 1 planning doc landed at `docs/planning/PLANNING_v4.7.x_guest_mode_actuation_phase1.md` (2026-05-24). URA detects guest mode (v4.6.2.2 hardened the detection) but does NOTHING with it. Real opportunity — the inferred state should drive behavior, not just sit on a sensor.

**Phase 1 scope:** Shared per-(zone, preset, range) `OverrideEngine` + HVAC opt-in + CM master toggle + Zone Manager per-zone override UI + `sensor.ura_active_preset_overrides` diagnostic. ~470 prod LoC + ~350 test LoC across ~9 files. Owns the override schema that Dynamic Preset Management (parallel plan) layers onto.

**Phase 2+:** Each new coordinator opt-in is its own Tier 2 cycle reusing the engine. Likely order: (a) Arrester suppression under guest, (b) Lighting circadian suppression, (c) Music Following disable, (d) NM routing changes, (e) Cover Controller skips.

**Phase 3:** Tier 1 visibility (`guest_minutes_today` attribute, `routine_status.guest_minutes_in_recent_window`, anomaly-detector exclusion of guest periods).

### Background context (filed 2026-05-15)

### Concrete trigger (user-provided)

**HVAC zone preset overrides under guest mode.** Specifically:

| Zone | Preset | Normal range | Guest-mode range |
|---|---|---|---|
| Back Hallway | `home` | 70–77 °F | **70–75 °F** (tighter comfort band) |
| Back Hallway | `sleep` | 70–78 °F | 70–78 °F (unchanged) |
| Any zone | `away` | 65–80 °F | 65–80 °F (unchanged) |

Semantics: guests get tighter comfort during waking hours; sleep + away unchanged. Generalizes to per-(zone, preset) override tables.

### Generalized design

Per-coordinator `guest_mode_overrides` config schema. Each coordinator that opts in declares which behaviors switch under guest mode. Config-flow / options-flow exposes:

- **HVAC:** per-(zone, preset) cool_low/heat_high overrides
- Default behavior under guest mode is "use normal preset" unless an override exists
- Schema: a structured override list per zone in options, OR a single table sensor that users can edit

Bonus: a `binary_sensor.ura_guest_mode_active_overrides_count` showing how many overrides are currently in effect.

### Other guest-mode behaviors worth considering (user to triage)

**HVAC**
- Suppress the **Override Arrester** during guest mode — don't fight back when residents adjust thermostats for guests
- Suppress **pre-cool / pre-heat banking** — banking interferes with present-moment comfort
- Suppress **solar gain cover management** in occupied zones — guests don't know why blinds are closing
- Skip **vacancy auto-off** for shared spaces guests are passing through

**Lighting**
- Skip **circadian color temperature shifts** in guest bedrooms (jarring for unfamiliar guests)
- Skip **sleep protection** dimming in guest bedrooms (guests don't follow your schedule)
- Slower or disabled **motion-driven auto-off** in shared spaces
- Brighter default in shared spaces during evening

**Music Following**
- Disable entirely under guest mode (the auto-transfer pattern is for residents; guests confuse the targeting)

**Notification Manager**
- Suppress non-critical notifications to residents (don't ping during hosting)
- Different routing (critical to phones not shared Sonos)
- Extended quiet hours in shared spaces

**Security**
- Don't auto-arm based on resident geofence (guests staying after residents leave)
- Higher motion-anomaly tolerance (guests trigger more "unusual" patterns by default)

**Energy**
- Disable **TOU-aware appliance scheduling** (don't defer washer/dishwasher when guest needs them)
- Don't aggressively bank battery — keep more reserve for unpredictable load

**Bayesian Predictor / Routine Awareness**
- Already-partially-handled: suppress Bayesian learning during guest mode (per `feedback_no_fabrication` memory)
- **NEW:** also exclude guest-mode periods from regime-detection windows so guests don't trigger false drift events
- Expose `routine_status.guest_minutes_in_recent_window` for visibility

**Cover Controller**
- Skip auto-close at sunset in occupied common areas (guests may want light)
- Skip privacy mode in shared spaces during guest evenings

**Routine Awareness D5 sensors**
- Add `house_state_filter: guest` toggle so the routine_status sensors can optionally exclude guest periods from the "recent" window

### Scope phasing (suggested)

- **Phase 1** (Tier 2 feature cycle): HVAC zone preset overrides (the user's concrete ask). ~150 prod LoC + per-zone options-flow fields + tests. Validates the overrides framework.
- **Phase 2** (Tier 2): expand framework to other coordinators based on which suggestions user picks. Each new coordinator opt-in is incremental.
- **Phase 3** (Tier 1): the visibility/observability bits (override count sensor, guest_minutes attribute).

**Recall hint:** `"Resume URA roadmap — guest mode actuation"`

## Dynamic Preset Management — PLAN FILED 2026-05-24 (Tier 2, TWO cycles)

**Status:** Planning doc landed at `docs/planning/PLANNING_v4.7.x_dynamic_preset_management.md` (2026-05-24). Composes on the override schema owned by Guest Mode Actuation Phase 1 (which must ship first).

**Problem:** URA HVAC presets carry fixed temperature RANGES per zone. One range doesn't fit every day — a 70–76 °F `home` that paces the AC nicely on a 78 °F day forces it to grind all afternoon on a 98 °F day. User policy: **always ranges, never absolute setpoints, never daily user fiddling.**

**Two-cycle phasing:**

**Cycle A — Weather Forecast Redundancy (Tier 2)**
- New `WeatherProviderManager` with ≥2 (target 3) prioritized weather providers
- Failover semantics, staleness window (default 6h), divergence detection (default 5°F threshold)
- 3 new sensors: `sensor.ura_weather_active_provider`, `sensor.ura_weather_forecast_today_high`, `binary_sensor.ura_weather_divergence`
- Migrate every existing weather consumer through the manager (no direct `hass.states.get("weather.*")` in domain code)
- **Hard prerequisite** for Cycle B — single-provider outage today leaves URA blind

**Cycle B — Dynamic Preset Adjustment (Tier 2)**
- Depends on Cycle A
- New `WeatherDrivenPresetOverrideSource` plugged into shared override schema
- Morning recompute (~06:00 local, NOT midnight) classifies today into 4 buckets: `cool` (<75°F) / `mild` (75–84) / `hot` (85–94) / `extreme` (≥95)
- Per-(zone, bucket) range table configured in CM options flow
- 2 new sensors + 1 user-pressable recompute button
- Default priority 30 (lower than guest_mode=50); guest wins ties
- Overrides expire at local midnight; next morning emits fresh

**6 open user questions** (in the planning doc):
1. Bucket boundaries — Texas-tuned?
2. Per-zone preset range tables (core decision — engineering trivial once specified)
3. Which zones opt IN (south-facing master likely YES; back hallway likely NO)
4. Override priority vs guest mode
5. Recompute hour
6. Include `sleep` preset?

**Recall hint:** `"Dynamic preset management"` or `"Resume Dynamic Preset Management"`

## v4.6.3.3 — Census_count over-emit suppression — IN REVIEW 2026-05-15

**Status:** Code complete on `feature/v4.6.3.3-census-count-suppression`. Tests pass. Awaiting Tier 1 review + deploy.

**Symptom:** `sensor.ura_recent_anomalies.by_coordinator.presence = 1825` over 24h window. Top-10 dominated by `presence.census_count` emits. Same shape as v4.6.3.1 zone_occupancy bug, different metric.

**Root cause:** `census_count` (people in house) is low-cardinality int — mostly 0 during sleep/away, 1-4 when occupied. Z-score detector with `minimum_samples=24` produces high z on every "person appears" tick during mostly-empty period.

**Fix shipped (option a, mirrors v4.6.3.1 pattern):** strip the `store_event` + `activity_logger.log` branch inside the census_count anomaly handler in `presence._run_inference`. Keep `record_observation` so the in-memory per-coordinator anomaly sensor still counts. Citing comment references the 1825/24h observation and points at the proper deferred fix (Bayesian time-bin distributions per v4.6.2 routine-awareness shape).

**Tests:** new `test_presence_census_count_persistence_suppressed` (mirrors v4.6.3.1's `test_presence_zone_occupancy_persistence_suppressed`). Two stale D3/D12 tests inverted to `test_presence_no_live_store_event_or_anomaly_event` + `test_presence_no_activity_logger_anomaly_calls` — presence has zero live emit paths post v4.6.3.1 + v4.6.3.3. Net: +1 test, 0 regressions.

**Audit findings (recorded here so they aren't lost):**
- `presence.transition_count_daily` — declared in PRESENCE_METRICS since v3.6.0-c1, never actually called. Wire-up filed as v4.6.4 below.
- `safety.hazard_trigger_frequency` — always passed `1.0`, so std→0 → z-guard suppresses every emit. Dead code that *looks* like a degenerate-shape risk but actually fires nothing. Worth cleaning in v4.6.4 or v4.6.5.
- `hvac.zone_call_frequency` / `hvac.override_frequency` — currently in-memory only (no persist path). When v4.6.5 wires HVAC `save_anomaly_event`, `zone_call_frequency` is the next-most-likely degenerate-shape candidate (low int, mostly 0-3). v4.6.5 D5 meta-test should explicitly check it against real-data cardinality before shipping.
- `security.alert_trigger_frequency` / `music_following.*` — event-driven, low volume, defer.

## v4.6.4 — Polish bundle — IN REVIEW 2026-05-15

**Status:** Code complete on `feature/v4.6.4-polish-bundle`. Tests pass (3097 vs 3095 on develop, +2 net). Awaiting Tier 1 review + deploy.

**P1 SHIPPED — Wire up `presence.transition_count_daily`.** `_count_transition` is now `async` and records the daily counter on every increment. If z-score fires, emits canonical AnomalyEvent via `store_event` + `activity_logger.log(action="anomaly", ...)`. Well-shaped (monotone counter, resets at midnight) so persistence is safe. Test: `test_presence_transition_count_daily_wired_and_recorded`.

**P2 SHIPPED — Delete `safety.hazard_trigger_frequency` dead code.** Always-`1.0` observation, std→0, z-guard suppressed every emit. Dropped from `SAFETY_METRICS`, full ~50 LoC emit block removed. `active_hazard_count` (real variance) retained.

**P3 SHIPPED — Three small `automation.py` fixes from prior reviews:**
- P3a (LOW #3): sleep branch no longer clears `_humidity_cap_suppressed` (preserves post-cap suppression contract across sleep)
- P3b (LOW #4): HVAC-managing entry clears Path A anchor state (`_humidity_on_since`, `_humidity_fan_triggered_time`) so reload-seed runs cleanly on HVAC release
- P3c (LOW #5): added intent comment explaining why cap-fire clears both anchor fields

**P4 SHIPPED — Tightened `test_presence_no_activity_logger_anomaly_calls` regex.** Replaced `[^)]*` with a balanced-paren walk that tolerates nested calls. The test is now also renamed `test_presence_only_transition_count_daily_activity_logger_call` since v4.6.4 P1 added the one legitimate call path.

**Updated tests:** `test_presence_no_live_store_event_or_anomaly_event` → `test_presence_only_transition_count_daily_emits_persisted` (asserts exactly-1 emit, anchored on transition_count_daily); same shape for the activity_logger sibling.

**Deferred (NOT in this bundle):**
- LOW #8, #9 (Path A behavioral test rewrite) — separate cycle when behavioral test infra hardens
- v4.6.3 review B4 (decision-contradicted-within-N-min path), B5 (NM source_signal drift), C10 (label externalization) — separate
- v4.6.2.3 INFO #4 (sys.modules pollution) — separate infra cleanup

**Deferred from v4.6.4 Tier 1 review:**
- **M2 (file for v4.6.5):** orphan `hazard_trigger_frequency` row in `metric_baselines` table. `load_baselines` reloads every row for `coordinator_id="safety"` regardless of current `SAFETY_METRICS`. After P2 deploy, the DB row stays forever — unreferenced (nothing iterates `_baselines.keys()`, only `metric_names`) but cosmetically present. Add one-shot cleanup OR filter on load. Tier 1.
- **M3 (file for v4.6.5):** `_transitions_today` is not restored across HA restart. Counter resets to 0 on every reload — `transition_count_daily` baseline distribution skews downward, biasing future thrashy-day anomalies to fire more than they should. Fold into RestoreEntity scope when v4.6.5 touches presence persistence.
- **L2/L3/L4 (file for next polish bundle):** test-fixture limits — P4 balanced-paren walker doesn't quote-aware skip; async check is string-grep not AST; 1200-char window is wide. None blocking; all are heuristic limits with adequate defense-in-depth from sibling counts.

Tier 1 single review. ~80 LoC prod + ~50 LoC tests net. Recall hint: `"Resume URA roadmap — v4.6.4 polish"`.

## v4.6.3.2 — Thread-safety hotfix for URARecentAnomaliesSensor — SHIPPED 2026-05-15

Root cause of v4.6.3.1 deploy hang. `sensor.py:10321` `_handle_activity_logged` was calling `hass.async_create_task` from dispatcher subscriber. Dispatchers fire on whichever thread invoked `async_dispatcher_send` — recorder thread completions and sync workers triggered the call from non-event-loop threads, raising RuntimeError under ReportBehavior.ERROR for custom integrations. Cascading dispatcher exceptions starved the event loop → HA API unresponsive → memory bloat (symptom, not cause).

Fix: `hass.async_create_task` → `hass.add_job` (canonical thread-safe scheduler). 1-line change. Confirmed live: zero thread-safety warnings post-deploy, sensors refreshing correctly, memory at 5.3 GB (within normal range), load avg under 1.0.

**Lesson for QUALITY_CONTEXT:** any dispatcher subscriber that schedules async work must use `hass.add_job` not `hass.async_create_task`. Worth adding as Bug Class #42.

## v4.6.3.1 — Presence zone_occupancy persistence suppression — SHIPPING 2026-05-14

Diagnosis (deeper than originally hypothesized): not "firing on every change" — `_check_zone_anomalies` records binary 0/1 occupancy into z-score AnomalyDetector for 5 zones on every `_run_inference` trigger (9+ triggers). Rarely-occupied zones produce z >= 4 → CRITICAL on every "occupied=1.0" observation. Net: 2117 emits in 3h.

Fix: remove `store_event` + `activity_logger.log` calls inside `_check_zone_anomalies`. Keep `record_observation` so in-memory anomaly counting (per-coordinator sensor) is preserved. Code comment explains the v4.6.3.1 lesson: binary metrics don't belong in z-score persistence.

**Lesson codified** in v4.6.5 plan (D5 meta-test) — future emit additions must audit metric continuity before wiring.

## v4.6.6 — Severity Vocabulary Refactor (Tier 2-DB, queued)

**Tier 2-DB trigger:** changes payload shape of a persisted record (the `severity` column on `anomaly_log`). Existing analytics that group by `severity = 2` would see different distributions post-deploy.

**Why it's its own cycle:** the current emit pattern in every coordinator (`_NewSev.CRITICAL if anomaly.severity.value == "critical" else _NewSev.WARNING`) collapses the 4-bucket internal scale (NOMINAL / ADVISORY z=2-3 / ALERT z=3-4 / CRITICAL z>4) into a 2-bucket DB severity (WARNING / CRITICAL). ALERT becomes indistinguishable from ADVISORY at query time. Reviewer A-M2 + B-M1 both flagged this independently in v4.6.5.

**Scope:**
- Extend `AnomalySeverity` enum in `anomaly_event.py` to 4 distinct values (or 3 if NOMINAL collapses with no-emit).
- Update mapping helper to translate `AnomalyRecord.severity` → `AnomalySeverity` faithfully across all coordinator emit sites (HVAC, security, music_following, presence, safety).
- Update DAO + sensor readers to handle the expanded enum.
- Behavioral test: assert each severity bucket round-trips through `save_anomaly_event` → `anomaly_log` SELECT → `URARecentAnomaliesSensor.by_severity`.
- Migration consideration: existing rows have severity={1, 2} only. No backfill needed (semantically WARNING covers ADVISORY+ALERT in legacy rows; new rows distinguish them going forward).

**Cost:** ~40 prod LoC across 5 coordinators + ~30 test LoC + ~10 LoC for enum/DAO/sensor + 1 behavioral round-trip test.

**Tier 2-DB ceremony:** 3 parallel reviews (A: existing-analytics impact on by_severity distribution, B: every coordinator emit site updated correctly with no missed call sites, C: enum forward-compat + test fixture authority for severity round-trip).

**Recall hint:** `"Resume URA roadmap — v4.6.6 severity refactor"`

## v4.6.5.1 — Polish bundle (Tier 1, queued)

**Items folded together because they're all small, low-blast-radius cleanups deferred from v4.6.5 reviews + audit. Single Tier 1 review.**

**P1: `override_frequency` cumulative-counter fix** (v4.6.5 Review B-M2). Today's emit passes `total_overrides` (daily-cumulative) which grows monotonically until midnight reset. Late-day values produce ADVISORY just from natural accumulation. Replace with either (a) delta from previous cycle, or (b) overrides/hour over a rolling window. ~20 prod LoC + 1 behavioral test asserting the new emit fires on rate change not accumulation. The B-M2 soak note in v4.6.5 README still applies until this lands.

**P2: `SUPPRESSED_FROM_PERSISTENCE` as module-level introspectable constant + parametric metric audit** (v4.6.5 Review C-M1). Today the set lives as a local inside each coordinator's `_record_anomaly_observations()` — documentation only, not introspectable. Promote to module-level (e.g. `HVAC_SUPPRESSED_FROM_PERSISTENCE = frozenset({...})`). Add one parametric meta-test that imports each `*_METRICS` constant + its companion suppression set and asserts: `set(METRICS) == wired_metrics ∪ suppressed_metrics`. Closes the forward-compat gap so a future-added metric must be EITHER wired OR explicitly suppressed (can't slip in silently). ~30 LoC across coordinators + 1 parametric test in `test_v465_observability_gap.py`.

**P3: `tokenize` / `ast`-based comment filter** for negative test assertions (v4.6.5 Review C-M2/M4). Replace the line-level `# at start` filter with a proper tokenizer pass so docstrings + inline trailing comments don't trivially satisfy/break negative assertions like `test_safety_detector_hazard_trigger_frequency_deleted` or `test_hvac_override_frequency_wired_zone_call_frequency_suppressed`. ~20 LoC test helper.

**P4: M3 `_transitions_today` RestoreEntity hydration** (carry-over from v4.6.4 review). `_transitions_today` resets to 0 on every reload/restart, so `transition_count_daily` baseline distribution skews low — biasing future thrashy-day anomalies to fire more than they should. Restore the counter via the existing PresenceCoordinator state-hydration path (mirrors how `_face_arrivals_today` would persist, if it did). ~30 prod LoC + 1 behavioral test.

**Explicitly NOT in scope** (deferred to future or separate):
- Music Following instrumentation investigation (`transfer_success_rate` mean=0.0 over 1594 samples) — needs runtime investigation, not a code-only polish
- `recent_anomalies` sensor lazy-query / post-restart-zero behavior — needs runtime investigation
- Severity collapse refactor → **v4.6.6 (Tier 2-DB)** above

**Cost:** ~80 prod LoC + ~50 test LoC across 4-5 files. Tier 1 single review.

**Recall hint:** `"Resume URA roadmap — v4.6.5.1 polish"`

## v4.6.5 — In-Memory Anomaly Persistence — SHIPPED 2026-05-16

**Status:** Code complete on `feature/v4.6.5-in-memory-anomaly-persistence` (rebased onto develop, 1 conflict in safety.py resolved). 22 v4.6.5 tests + all 64 v4.6.3 tests pass. Cardinality audit done. Awaiting Tier 2-DB review (3 parallel) + deploy.

**Pre-deploy cardinality audit findings (live data from in-memory baselines):**
- `hvac.zone_call_frequency`: mean=0.378, std=0.678, sample_count=899 → **degenerate-shape (active_count=2 → z=2.39 ADVISORY); SUPPRESSED** from persistence in this cycle. Added to `SUPPRESSED_FROM_PERSISTENCE` set in hvac.py. record_observation kept for in-memory tracking. Same pattern as v4.6.3.1 zone_occupied_count + v4.6.3.3 census_count.
- `hvac.override_frequency`: mean=3.234, std=3.436 → well-shaped continuous. **WIRED.**
- `security.alert_trigger_frequency`: mean=1.0, std=0.1 (MIN_VARIANCE floor) → currently constant-1.0 (no higher-severity alerts observed). Will fire correctly if severity ever rises. **WIRED** (low risk).
- `music_following.transfer_success_rate`: mean=0.0, std=0.1, sample_count=1594 → zero successful transfers in 1594 cycles. **WIRED but flagged for v4.6.5.1 polish:** verify MF stats collection isn't broken; metric direction may be inverted (alerting on success rather than failure is wrong-direction signal).
- `music_following.cooldown_frequency`: mean=0.0 → directionally correct alert-on-first-cooldown. **WIRED.**
- `safety.active_hazard_count`: kept wired per v4.6.3 D2; binary-shape risk noted in code comment for monitoring.
- `safety.hazard_trigger_frequency`: **DELETED** in v4.6.4 P2 (pre-rebase). v4.6.5's D4 wire-it plan was structurally wrong; rebase resolved in favor of v4.6.4's empirical evidence. D4 test inverted to assert deletion.

**Folded into this cycle (from v4.6.4 review):**
- TBD — M2 (orphan baseline cleanup) and M3 (`_transitions_today` RestoreEntity hydration) decision still pending. Either fold or explicitly defer to v4.6.5.1.

**Filed for v4.6.5.1 polish:**
- Music Following stats instrumentation investigation (mean=0 success rate over 1594 samples is suspicious)
- Music Following metric-direction review (success-rate-up should not be anomalous)
- M3 carry-over from v4.6.4 review (`_transitions_today` RestoreEntity hydration) — NOT folded into v4.6.5
- M2 carry-over from v4.6.4 review (orphan baseline pruning) — DID fold into v4.6.5 with behavioral test
- **From v4.6.5 Tier 2-DB Review A (data integrity):** ALERT→WARNING severity collapse (M2 in A, M1 in B) — refactor all coordinator emit sites to map ADVISORY/ALERT/CRITICAL to distinct DB severity values. Also DAO `!= 0.0` sentinel ambiguity (pre-existing v4.6.3 B1 fix, worth hardening).
- **From v4.6.5 Tier 2-DB Review B (migration):** `override_frequency` cumulative-counter risk — daily-resetting sawtooth may fire ADVISORY routinely from late-day high values. Mean=3.23 std=3.43 baseline already captures the daily range so risk is bounded vs zone_call_frequency, but proper fix is delta-emit or rolling-window rate. Soak observation noted in v4.6.5 README Live Validation step 2.
- **From v4.6.5 Tier 2-DB Review C (tests):** `SUPPRESSED_FROM_PERSISTENCE` is a local set used only as documentation, not a runtime gate — convert to module-level constant introspected by meta-test (also addresses C-M1 forward-compat audit). And: line-level comment filter is fragile (docstrings would satisfy / break it) — switch to `tokenize`/`ast` walk. And: per-coordinator metric audit doesn't scale generically — add one parametric meta-test that imports each `*_METRICS` constant and asserts the union of wired + suppressed sets covers it.
- README note for soak observers: zone_call_frequency anomalies are intentionally invisible in `sensor.ura_coordinator_manager_recent_anomalies` (suppression by design — the in-memory anomaly sensor still counts them).

**Symptom:** HVAC `sensor.ura_hvac_coordinator_hvac_anomaly` shows `state=advisory, anomalies_today=3`. But `by_coordinator.hvac` in `recent_anomalies` is 0. Same shape affects security, music_following, and the safety-detector path (distinct from safety hazards which migrated in v4.6.3 D2).

**Root cause (pre-existing observability gap, NOT a v4.6.3 regression):** HVAC's `AnomalyDetector` tracks anomalies in an in-memory `_active_anomalies` list without writing to `anomaly_log`. v4.6.3's D7 wrapper deletion covered every call site that ALREADY emitted — but for coordinators that never emitted, there was nothing to migrate.

**Fix:** add a NEW `save_anomaly_event` emit at the appropriate gate inside each affected AnomalyDetector consumer (4 deliverables + meta-test for the v4.6.3.1 degenerate-metric lesson).

**Tier 1.** ~200 prod + ~200 test LoC across 4 coordinators. Recall hint: `"Resume URA roadmap — in-memory anomaly persistence v4.6.5"`.

## v4.6.2.3 — Review carry-overs from v4.6.2.1 + v4.6.2.2 — SHIPPED 2026-05-14

(retained here for historical context; remove on next BACKLOG cleanup sweep)

### From v4.6.2.1 review (`docs/reviews/code-review/v4.6.2.1_humidity_fan_hardening.md`)

1. **MEDIUM #1, #2 — Reload-mid-cycle state-anchor loss.** Both paths share the shape: on options-flow reload while a humidity fan is running, `_humidity_on_since` resets to `None`. If humidity is in the hysteresis band on next eval, neither activate nor off branch fires and the anchor never re-seeds → max-runtime cap silently disables until the fan fully cycles off→on. Reviewer's proposed 5-line patch per path: seed `humidity_on_since = now` when we observe the fan entity already on at evaluation time. Add at least one behavioral test that drives `handle_humidity_based_fan_control` end-to-end (replacing the v4.6.2.1 source-grep tests).
2. **LOW #3 — Sleep-policy clear of suppression.** Cap-fire + sleep onset within minutes leaks the "require humidity to drop before re-fire" contract. Small fix: don't reset `_humidity_cap_suppressed` in the sleep branch.
3. **LOW #4 — HVAC-managing transition leaves stale Path A state.** When HVAC stops managing later, Path A wakes with stale `_humidity_on_since`. Clear Path A state on HVAC-managing entry.
4. **LOW #5 — Cap-fire clears `_humidity_fan_triggered_time`.** Intentional but undocumented. Comment-only.
5. **LOW #8, #9 — Behavioral test gap.** Path A tests are source-grep, not behavioral. Replace with end-to-end driver tests.

### From v4.6.2.2 review (`docs/reviews/code-review/v4.6.2.2_guest_mode_hardening.md`)

6. **MEDIUM #1 — Signal-reactivity gap on confidence-only change.** `_handle_census_update` only triggers `_run_inference` on count change. Confidence upgrade (e.g. low→high) with counts unchanged waits up to one 60s periodic cycle. Fix: add `old_confidence != self._census_confidence` to the trigger condition.
7. **LOW #2 — Dead state `_census_source_agreement`.** Captured in `_handle_census_update` but never read. Either wire it into the gate (e.g. require `both_agree` for high-confidence trust) or remove the field.
8. **LOW #7 — Test-stub re-implementation of `_guest_gate_armed`.** Tests construct a stub that mirrors the production method; production-code drift risk. Refactor tests to call the real method.

### Cost (estimated)

- Production: ~30 LoC across `automation.py`, `hvac_fans.py`, `presence.py`
- Tests: ~100 LoC (behavioral tests for humidity fan + reactivity for confidence change)
- Tier 1 review

## Bugs (fix first)

3. **5 disabled HA automations use deprecated mireds** — Need `color_temp` → `color_temp_kelvin` migration when re-enabled. Tracked since v3.9.6.

## Tech Debt: DB Write Queue Startup Contention

4. **~10 minute startup warmup with transient DB write timeouts** — After v4.2.6 deferral + jitter, startup improved from 15 min to ~10 min. Remaining errors at t=5min are transient, non-destructive, self-healing. Accepted as current behavior. See `.vibememo/users/ojiudezue/entries/002_startup_warmup_accepted.json` for decision trail.

   **Possible deeper fixes (deferred):**
   - **Non-blocking fire-and-forget writes** — Callers don't await the write queue, eliminating timeouts entirely. Changes error handling model. Medium risk. ~50 lines across database.py + all callers.
   - **Write batching** — Group multiple writes into single transactions (e.g., batch all 31 room state saves into one commit). Reduces write count by ~70%. Requires coordinator-level batch timer. High risk. ~80 lines.
   - **Larger jitter window (240s)** — Spread deferred writes over 4 minutes instead of 1. Simple but some rooms would start writing during early startup. Low risk. 1 line.
   - **Revisit trigger:** Room count exceeds 40, warmup exceeds 15 min, or timeouts occur during steady-state.

## Bayesian Remaining

5. **B3: Pre-emptive Actions** — Zone + house level Bayesian pre-conditioning, prediction-aware vacancy hold, predicted departure/return transitions, battery occupancy shaping. Room-level actions (lights, music) cut — no practical value over 2-5s reactive detection. **Full plan:** `docs/planning/PLANNING_v4.x_B3_PREEMPTIVE_ACTIONS.md`

6. ~~**B4: Energy Integration**~~ — **DONE** (v4.1.0 L1, v4.1.1 L2, v4.2.0 L3). All 3 layers shipped. See `docs/planning/PLANNING_v4.x_B4_ENERGY_INTEGRATION.md`.

## Sensor Reconciliation Cycle (audit findings, May 5 2026)

**A. previous_seen / previous_location wiped after one away cycle** — `person_coordinator.py:325, 347` (and parallel home branch at 312, 313). The fallback branches overwrite `previous_location` with the literal "away"/"home" string and null `previous_location_time` after the first steady-state cycle. Result: anyone away >1 update interval shows `previous_seen=unknown`. Hotfix in flight (preserve old_data values; capture transition only when `old_location` is a real room).

**B. `likely_next_room` source=none for kids weekday afternoons** — NOT a bug. `bayesian_beliefs` confirms 0 observations for (Jaya/Ziri, MIDDAY/AFTERNOON, weekday) because they're at school. `_learning_status` correctly returns INSUFFICIENT_DATA. **See B6 below for UX enhancement** to display "away_typical" instead of "unknown" in this case.

**C. Frigate face DB undersized** — 11–17 samples per family member at recognition_threshold=0.9. 1 match in last 50 events. Not URA code — Frigate config. User handling.


## B6: "away_typical" Display + Seasonal Staleness Handling

**Goal:** When the Bayesian model has no useful data for the current (person, time_bin, day_type) cell AND geofence says away, display "away_typical" instead of "unknown" for `*_likely_next_room`.

**Display logic:**
```
if pred is None or pred.learning_status == INSUFFICIENT_DATA:
    return "away_typical" if geofence_away else "unknown"
if cell_stale (no obs in cell within `bayesian_cell_staleness_days`, default 14)
        and geofence_away:
    return "away_typical"
return pred.top_room
```

**Why staleness check matters:** Handles school↔summer transitions. Pre-summer Jaya cell is empty → "away_typical" works. Mid-summer Jaya is home → cell accumulates obs → real predictions resume. Back-to-school: cell has stale summer data + Jaya away → staleness branch correctly returns "away_typical" rather than predicting an obsolete summer room.

**Effort:** ~50 production lines (new path in `sensor.py:2400` + helper for cell staleness query) + 60 test lines + 1 config option (`bayesian_cell_staleness_days`, default 14, range 7-90).

**Tests required:**
- `test_away_typical_when_cell_empty_and_away`
- `test_unknown_when_cell_empty_and_home` (honest "we don't know")
- `test_real_prediction_when_cell_active_and_home`
- `test_away_typical_when_cell_stale_and_away` (school-resumption case)
- `test_real_prediction_when_cell_active_and_away_but_recent_obs` (school-year weekend home)

**Discovered during:** May 5 2026 sensor reconciliation cycle.

## Appliance Coordinator (B5) — v3 PLAN CURRENT

**Status:** v3 plan landed 2026-05-23 at `docs/planning/PLANNING_v4.7.x_APPLIANCE_COORDINATOR_v3.md`. Ready to build (Tier 2-DB). Supersedes v1.1 (`PLANNING_v4.7.x_APPLIANCE_SCHEDULER.md`) and v2.0 (`PLANNING_v4.7.x_APPLIANCE_SCHEDULER_v2.md`); both retained for history.

**Scope:** New domain coordinator that defers LG ThinQ washer/dishwasher/washtower starts to cheaper TOU windows, interrupts manual starts that fire in peak (when the appliance is `interruptible_at_start`), and skips Rainbird sprinkler cycles based on weather forecast. Provider plugin pattern for future brands (Bosch, SmartThings, generic power-sensor).

**v3 absorbs (since 2026-05-23):**
- Dashboard target swap — Dashboard v5.0+ HA panel → **URA PWA v6.0+ standalone** (Principle 9 rewritten; D10 sensors annotated with `useUraSensor*` hook contracts; flat-attr discipline enforced; full 14-sensor Dashboard Hooks contract table)
- v4.6.8 EC TOU rate reconciliation **(now shipped 2026-05-18)** → `savings_today_dollars` consumes `EnergyCoordinator.get_current_rate_for_period(period)` instead of local rate constants
- v4.6.7 `anomaly_log` NOT NULL relaxation → interrupt-path can write partial metric rows (no fake zeros)

**v2.0 absorbed all v1.1 user reax** (verified 2026-05-25):
- P1 interrupt-at-start caveat + EV-charging precedent → INTERRUPTED SM state + D2
- P7 per-appliance strictness (`tolerate_mid_peak`, `on_bisect`, cycle-length sensor) → Strictness Config Schema + D2 options-flow
- P8 multi-vector power (device-native + mains + 30s tolerance) → PowerSignalAggregator + D11
- P9 config-flow + device-page mirror → D10 entity slate (now PWA-grounded in v3)
- P10 hardened v4.6.x anomaly framework → Principle 10 + D6
- TOU bidirectional helper → Principle 11 + D3
- Rainbird kill switch → D8
- Coordinator dashboard surfaces → D10 + Dashboard Hooks section

**Tier 2-DB review (CLAUDE.md):** 3 parallel reviewers
- A — Data integrity + DB architecture preservation
- B — Migration correctness + signal chain integrity
- C — New surfaces + test fixture authority + PWA contract

**Effort:** ~36-46h
**Priority:** MEDIUM-HIGH

**Ship plan (per v3):**
- **v4.7.0** — D3, D11, D12, D1, D2, D4, D6, D10 (LG cost-deferral + interrupt + PWA observability)
- **v4.7.1** — D5 (reload resilience hardening)
- **v4.7.2** — D7 + D8 (sprinkler skip + Rainbird kill switch)
- **v4.8.0** — D9 (GenericPowerSensorProvider, deferred)

**Minor staleness in v3 (non-blocking):** Status line + "Why v3" §2 say v4.6.8 is "in flight" — actually shipped 2026-05-18. Open Q#7 (EC rate API name) now answerable; pin during D10 build.

**Recall hint:** `"Resume Appliance Coordinator v3"` or `"B5 appliance scheduler"`

---

## v4.7.x SLOT CONTENTION (3 plans queued, 2026-05-25)

Three independent Tier 2+ feature cycles are now `ready to build` against the v4.7.x version slot. Suggested order (warmest first, dependency-respecting):

| # | Plan | Tier | Effort | Why this order |
|---|---|---|---|---|
| 1 | **Guest Mode Actuation Phase 1** | Tier 2 | ~11h | Warmest user-driven feature per memory; smallest scope; OWNS the override schema Dynamic Preset Mgmt depends on |
| 2 | **AnomalyType discriminator** (memory item, no plan yet) | Tier 2-DB | ~90 LoC + migration | "On tap" per 2026-05-18 directive; small; clears the way for v4.8.x anomaly classification work |
| 3 | **Appliance Coordinator v3** | Tier 2-DB | ~36-46h | Largest; independent of Guest Mode + Dynamic Preset; can run in parallel after Guest Mode P1 if desired |
| 4 | **Dynamic Preset Mgmt Cycle A** (weather redundancy) | Tier 2 | TBD | Hard-blocks on no precedent dependency; useful on its own |
| 5 | **Dynamic Preset Mgmt Cycle B** (preset adjustment) | Tier 2 | TBD | Depends on Cycle A AND Guest Mode Phase 1's override schema being shipped + stable |
| 6 | **Routine Awareness Phase 2** (guest-mode-filter extensions) | Tier 1, ~120 LoC | Small | Hard-blocks on Guest Mode Phase 1; could roll into same release |

User to assign actual v-numbers at deploy time.

## B7: Routine Change Detection (paired with B6 → ship together as v4.5.0 "Routine Awareness")

**Goal:** Detect when a person's behavior pattern in a (time_bin, day_type) cell shifts significantly from historical baseline — useful for catching real-world regime changes (new job, baby, retirement, school year cycle) and surfacing them as a sensor (and optionally a notification).

### Algorithm: Jensen-Shannon divergence on cell distributions

For each (person, time_bin, day_type) cell:
1. Compute room-frequency distribution `P` over a recent window (default 14 days) from `person_visits`.
2. Compute room-frequency distribution `Q` over a reference window (default 90 days, ending where recent starts).
3. Reject if either window has fewer than `min_obs=10` observations.
4. Compute `JS(P, Q) = 0.5·KL(P‖M) + 0.5·KL(Q‖M)` where `M = (P+Q)/2`.
5. Bucket: `<0.3 = stable`, `0.3–0.5 = drifting`, `>0.5 = shifted`.
6. Require persistence — shift must be present on N consecutive nightly checks before flagging (suppresses vacation/sick-day false positives).

### Why JS over alternatives

JS handles full distributional shift (not just mean), is symmetric/direction-agnostic, bounded `[0,1]` so thresholds are interpretable without per-cell tuning, and is computationally trivial (~microseconds per cell). Considered + rejected: rolling-mean comparison (misses distributional shifts), CUSUM (univariate, direction-aware), Bayesian online change-point (BOCPD; theoretically optimal but brittle hyperparameters and heavy compute).

### Data model — share with existing `AnomalyDetector` infrastructure

URA already has rich anomaly infrastructure (`coordinator_diagnostics.py:631`):
- `AnomalyRecord` dataclass (line 112)
- `AnomalySeverity` StrEnum (line 42)
- `AnomalyDetector.store_anomaly()` for persistence
- `AnomalyDetector.get_anomaly_count(days)` for query
- Existing consumers: presence, safety, security, energy_circuits, HVAC

Existing anomalies are **point-in-time** ("current observation surprising vs prediction"). B7 detection is **distributional/temporal** ("recent window distribution differs from historical"). Different math, different time scale — but they should share storage and surface.

**B7 reuses existing infrastructure rather than inventing parallel:**
- Add `AnomalyType` discriminator to `AnomalyRecord` (`point_in_time | regime_shift`).
- Persist regime shifts via `anomaly_detector.store_anomaly(AnomalyRecord(type=regime_shift, ...))`.
- Reuse `AnomalySeverity` for magnitude buckets: `info` = drifting (JS 0.3–0.5), `warning` = shifted (JS 0.5–0.7), `critical` = major shift (JS > 0.7).
- Existing dashboards / NM hooks pick up B7 events automatically without new wiring.
- Reuse `AnomalyDetector.get_anomaly_count` and existing cleanup for retention.

**No new SQL table needed.** Schema migration is just adding a `type` column (with default `point_in_time` for backward compat). Cleanup already covered by existing `AnomalyDetector` retention.

Detection still runs from `person_visits` (already has timestamps). Verify/add index on `(person_id, entry_time, room_id)` if not present.

### Sensor surface

Per-person:
```
sensor.universal_room_automation_<person>_routine_status
  state: "stable" | "drifting" | "shifted"
  attributes:
    cells_evaluated_last_run, cells_with_recent_data, max_magnitude, max_magnitude_cell,
    top_changes (list of {cell, magnitude, top_movers}), unacknowledged_events, last_check
```

House aggregate:
```
sensor.universal_room_automation_household_routine_status
  state: worst-case across persons
  attributes: persons_stable/drifting/shifted, total_unacknowledged_events
```

Plus `button.universal_room_automation_acknowledge_routine_changes`.

### Notification surface — opt-in only, three modes

CM option `routine_change_notification_mode`: `silent` (default) | `weekly_digest` | `event` (cooldown 30d per cell). Ship with `silent` default. Privacy: notification copy must be neutral ("routine pattern shift detected") not alarming.

### Risks ranked

**Statistical (highest):**
1. Vacation/sick-day false positives → mitigation: persistence guard + skip cells where geofence-away >50% of recent window. Shares infrastructure with B6 staleness.
2. Sparse-cell noise (10-15 obs gives 30%+ variance) → `min_obs=10` floor; high-confidence band requires `min_obs=20`.
3. Threshold calibration is initially a guess → mandatory 4-6 week observation period in `silent` mode before enabling notifications.

**Implementation (medium):**
4. Query performance on `person_visits` (~100k rows, ~50-100 cells/night, all aggregating SELECTs) → must verify/add the (person_id, entry_time, room_id) index.
5. Bug #25 (unbounded query): all queries time-bounded, GROUP BY rooms (not row fetch).
6. Bug #19, #27, #29: standard prevention — track tasks, register cleanup, populator paths tested.

**Notification (medium):**
7. Notification fatigue → cooldown + opt-in only.
8. Privacy/social risk → neutral framing, default silent, user-driven escalation.

**System (low):** Standard schema migration, restart-resilient (results persisted), zero pollution of bayesian_beliefs.

### Cost (revised — shares AnomalyDetector infra)

| Component | Production | Test |
|---|---|---|
| `regime_detector.py` (algorithm + JS/KL math) | ~250 | ~200 |
| `coordinator_diagnostics.py` (add `AnomalyType` discriminator + schema migration for type column) | ~50 | ~40 |
| Sensor classes (per-person + house aggregate, query `AnomalyDetector` for type=regime_shift) | ~140 | ~80 |
| Coordinator integration (nightly run, calls `anomaly_detector.store_anomaly`) | ~60 | ~40 |
| Config flow (windows + threshold + notify) | ~70 | ~30 |
| Notification (NM hook for type=regime_shift filter) | ~40 | ~20 |
| Index migration | ~30 | — |
| **Total** | **~640** | **~410** |

(Net ~130-line reduction vs. the originally-proposed parallel infrastructure, by sharing existing `AnomalyDetector`.)

### Ship plan

**Phase 1 (silent sensor only):** algorithm + DB + sensors + nightly run. Run for 4-6 weeks calibration. ~600 prod / ~400 test.

**Phase 2 (notification surface):** add `weekly_digest` and `event` modes with NM integration. ~170 prod / ~90 test.

Share infrastructure with B6: `is_cell_stale()` helper from B6 lives in same module as `detect_regime_shift()` — both about "this cell's behavior changed". **Plan B6 + B7 to ship together as v4.5.0: Routine Awareness.**

### What B7 is NOT

- Not real-time prediction (nightly batch is sufficient and cheaper).
- Not for guests (no person tracking).
- Not for room-level patterns (would need different schema; out of scope).
- Not for energy patterns (different modality; possibly future).

## Optimization Coordinator (5 phases)

6. **Phase 1: Room Health Score** (~400 lines) — 6 dimensions per room. Dedicated sensor per room + NM alerts for critical degradation.
7. **Phase 2: Zone + House Health + Daily Digest** (~400 lines) — Aggregate scores. House summary sensor. Morning digest via NM.
8. **Phase 3: Prediction Validation + Weekly Report** (~300 lines) — Track Bayesian accuracy. Flag degradation. Weekly NM report.
9. **Phase 4: Rule-Based Optimization** (~300 lines) — Tier 1 deterministic rules. Built-in goals: energy, comfort, security.
10. **Phase 5: LLM-Assisted + Agentic Mode** (~500 lines) — Tier 2 Claude API batch analysis. User goals. Autonomous config adjustments.

## Deferred Entities (from DEFERRED_TO_BAYESIAN.md)

| Entity | Status | Target |
|--------|--------|--------|
| WeekdayMorningOccupancyProbSensor | DONE (B1) | v4.0.0 |
| WeekendEveningOccupancyProbSensor | DONE (B1) | v4.0.0 |
| OccupancyPatternDetectedSensor | DONE (B1) | v4.0.0 |
| OccupancyPercentageTodaySensor | DONE (B2) | v4.0.2 |
| TimeOccupiedTodaySensor | DONE (B2) | v4.0.2 |
| TimeUncomfortableTodaySensor | DONE (B2) | v4.0.2 |
| AvgTimeToComfortSensor | DONE (B2) | v4.0.2 |
| OccupancyAnomalyBinarySensor | DONE (B2) | v4.0.2 |
| ClearDatabaseButton | DONE (B1) | v4.0.0 |
| EnergyWasteIdleSensor | DONE (B4 L3) | v4.2.0 |
| MostExpensiveDeviceSensor | DONE (B4 L3, circuit-level) | v4.2.0 |
| OptimizationPotentialSensor | DONE (B4 L3, simple version) | v4.2.0 |
| EnergyCostPerOccupiedHourSensor | DONE (B4 L3) | v4.2.0 |
| EnergyAnomalyBinarySensor | DONE (B4 L3) | v4.2.0 |
| OptimizeNowButton | Deferred | Optimizer P4 |
| SIGNAL_COMFORT_REQUEST | Deferred | B3 |

## v4.5.12.1 — kWh-avoided House Roll-up (deferred from v4.5.12)

**Status:** Filed for next small-cycle slot. Deferred from v4.5.12 to keep that cycle focused on the slice-2 deliverables (D7/D8/D10/D11).

**Source cycle:** v4.5.12 (AC ramp observability). Discovered while rationalizing savings nomenclature on the whole-house integration device — the kWh-avoided counters belong on the house device for cross-feature savings roll-up, but should also remain on HC for HC-local consumers.

### Scope (deliberately tiny)

Duplicate 2 sensors from the HC device onto the whole-house integration device, with explicit feature-prefix names that disclose what they cover:

| New house-device sensor | Mirrors HC sensor | Naming rationale |
|---|---|---|
| `sensor.ura_house_ac_ramp_kwh_avoided_today` | `sensor.ura_hvac_ac_kwh_avoided_today` | `ac_ramp_` prefix on the house device makes coverage explicit — this is the AC-ramp feature's contribution, not "all savings everywhere". |
| `sensor.ura_house_ac_ramp_kwh_avoided_total` | `sensor.ura_hvac_ac_kwh_avoided_total` | Same — explicit feature attribution. Use `RestoreEntity` so dashboards don't blink on restart. |

**What does NOT get duplicated (and why):**
- `nudges_today` / `resets_today` — operational counters, useful for HC-local troubleshooting, not house-level savings narrative.
- `false_positive_rate` — diagnostic for HC tuning; stays HC-only.

### Why duplicate, not move

HC consumers (manual cross-refs, HC-local dashboard cards, the v4.5.12 troubleshooting recipes) already reference `sensor.ura_hvac_ac_kwh_avoided_*`. Moving would break them. Duplication is cheap (~30 LoC) and the source of truth (`OverrideArrester._impact_cache`) is identical for both — no risk of divergence as long as both sensors read the same cache.

### Why NOT renamed on HC side

Deliberate asymmetry. On HC, the device context already implies AC; the shorter `hvac_ac_kwh_avoided_*` reads naturally. On the house device, where multiple feature vectors will eventually contribute savings (battery arbitrage, load shedding, sprinkler skip), the longer `house_ac_ramp_kwh_avoided_*` prevents naming collisions with future siblings like `house_battery_kwh_avoided_*` or `house_arbitrage_kwh_avoided_*`.

### Implementation sketch

1. **Reuse the existing mixin.** `_ACRampImpactSensorMixin` in `sensor.py` already encodes the lookup path (`hass.data[DOMAIN]["coordinator_manager"].coordinators["hvac"]._override_arrester._impact_cache`). Two new sensor classes inherit from it.

2. **Unique-id discipline.** Use `f"ura_house_ac_ramp_kwh_avoided_today"` and `f"ura_house_ac_ramp_kwh_avoided_total"` — distinct from the HC unique_ids. Existing dashboards on HC sensors keep working.

3. **DeviceInfo.** `_attr_device_info = DeviceInfo(identifiers={(DOMAIN, "integration")}, ...)` — same identifier the existing PersonLikelyNextRoomSensor uses in `aggregation.py` (verify file:line during build). This registers them under the whole-house integration device, NOT HC.

4. **Registration site.** `async_setup_aggregation` in the integration setup path (verify `aggregation.py` is the right call site — look for where existing whole-house sensors register). Add the two new entities to the entity list there.

5. **Bug Class #35 (refresh signal).** Both sensors must subscribe to `SIGNAL_HVAC_ENTITIES_UPDATE` so they refresh once per 5-min decision cycle alongside the HC mirrors. Copy the pattern from the HC `HVACACKwhAvoidedTodaySensor` / `HVACACKwhAvoidedTotalSensor`.

6. **Bug Class #34 (no shadowing imports).** Module-level imports only. Add an AST regression test for `aggregation.py` matching the one in `quality/tests/test_v4512_observability.py`.

7. **Tests.** `quality/tests/test_v4512_1_house_ac_ramp_savings.py`:
   - Class existence (2 sensor classes)
   - Mixin reuse (`_ACRampImpactSensorMixin` ancestor)
   - DeviceInfo identifier = `(DOMAIN, "integration")`
   - Unique_ids distinct from HC versions
   - RestoreEntity ancestor on the `_total` variant
   - Signal subscription decoration
   - AST regression for Bug Class #34 on aggregation.py

### Cost + review

- Production: ~30 LoC across `sensor.py` (2 classes) + `aggregation.py` (registration).
- Tests: ~80 LoC.
- Review tier: Tier 1 (hotfix-shaped — 2 new sensors, single-purpose). Single staff-level review against QUALITY_CONTEXT + mental execution.

### Companion future-cycle work (not part of v4.5.12.1)

- **Cross-vector savings roll-up** — once a second savings vector exists (battery arbitrage savings, load-shed savings, sprinkler-skip savings), add `sensor.ura_house_total_kwh_avoided_today` as a sum. Tag each contributor with an `accuracy` attribute so the roll-up can disclose mixed precision. Filed as its own future cycle, separate from v4.5.12.1.
- **Nomenclature alignment audit** — sweep existing whole-house sensors for any "savings" / "avoided" / "predicted" names that don't disclose their feature scope. Roll into the cross-vector roll-up cycle.

### Reference material

- HC sensors to mirror: `custom_components/universal_room_automation/sensor.py` — `HVACACKwhAvoidedTodaySensor` + `HVACACKwhAvoidedTotalSensor`
- Cache source: `custom_components/universal_room_automation/domain_coordinators/hvac_override.py` — `OverrideArrester._impact_cache` + `_refresh_impact_cache()`
- Existing house-device sensor pattern: `custom_components/universal_room_automation/aggregation.py` — PersonLikelyNextRoomSensor registration site
- Test pattern: `quality/tests/test_v4512_observability.py` — D8 tests + AST regression
- Plan context: `docs/planning/PLANNING_v4.5.12_ac_ramp_observability.md` — Deferred section
- VibeMemo entry: `.vibememo/users/ojiudezue/entries/012_v4512_observability_and_quality_bar_reset.json`

## v4.5.16 — Duplicate-timestamp investigation (minor, after v4.5.15)

**Status:** SUPERSEDED by v4.5.18 (2026-05-12). Original narrative was incorrect — see correction below. The duplicate-timestamp metric was a REPORTING-ONLY bucket; no data was being lost from the Bayesian prior-building path. v4.5.18 shipped the reporting correction.

**Original finding (2026-05-11, post-v4.5.12 deploy):** `sensor.ura_coordinator_manager_bayesian_data_quality` reports 11,284 duplicate-timestamp "rejections" out of 133,912 total rows (8.4%). The data quality reading hovered at 90-91% for weeks.

**Narrative correction (2026-05-12, during v4.5.18 review):** `scan_data_quality`'s dedup is REPORTING-ONLY. Its `seen_timestamps` set is local to that method. `_build_priors_from_transitions` at `bayesian_predictor.py:243` iterates the SAME row set and does NOT timestamp-dedup. So the 11k rows have ALWAYS been included in priors. Nothing was "discarded." The bucket was over-counting legitimate multi-step transitions (PersonCoordinator captures `now` ONCE per cycle, so distinct A→B→C transitions in one cycle share the timestamp).

**Hypothesis (corrected):** ~~Two writers colliding~~ → Single writer pattern. PersonCoordinator's per-cycle timestamp capture is the source. Multi-step paths within one cycle (genuine user transitions or BLE re-emit at startup) produce rows sharing a second but with distinct (from, to) tuples. The OLD narrow dedup key flagged them. v4.5.18 widens the key.

### Investigation goals (do BEFORE scoping a fix)

1. **Which table?** Confirm it's `person_visits` (most likely) vs `bayesian_observations` vs `room_state_history`. Check the data quality sensor's source query to identify the table it audits.
2. **Which writers?** Grep for `INSERT INTO <table>` and `write_queue.add` call sites. Likely candidates: `person_coordinator.py`, `presence_coordinator.py`, anything firing on `state_changed` for person entities.
3. **Pattern of collisions:** Sample 50 rows of duplicates and inspect the (person, room, timestamp) tuples — same person+room same tick (true duplicate write race) vs same timestamp + different rooms (legitimate concurrent events being lost to PK constraint).
4. **Dedup-window check:** What is the current dedup window? Is it microsecond-precise or second-precise? HA dispatches typically resolve within a few ms, so a second-precise dedup will reject legitimate events.

### Promotion criteria — escalate from minor to feature cycle if:

- Investigation reveals more than 2 writer call sites colliding (architectural problem — coordinator-write protocol needs rethinking)
- Investigation reveals legitimate data is being lost (not just true duplicates) — that changes the Bayesian model's accuracy estimate and may invalidate observations the predictor has been trained on
- Fix requires a schema migration

### Otherwise — minor cycle scope (~50 LoC + 20 tests)

- Add a write-side dedup check at the single collision point
- OR widen the dedup window from second-precise to (e.g.) 5-second precise for person events
- Add a sensor attribute `duplicates_in_last_24h` so the trend is visible
- Tier 1 review

**Reference:** Bayesian Data Quality sensor at `sensor.py` (search `BayesianDataQualitySensor`). Audit query lives in `coordinator_diagnostics.py` or similar. v4.5.12 live validation found the 11k duplicate count.

## v4.5.17 — Bayesian prediction-scoring pipeline investigation (minor, after v4.5.16)

**Status:** Investigation spike, not yet scoped. Scheduled as a minor after v4.5.14 unless investigation surfaces architectural issues.

**Finding (2026-05-11, post-v4.5.12 deploy):** `sensor.ura_coordinator_manager_bayesian_prediction_accuracy` shows `state: unknown` with `total_predictions_7d: 0, brier_score: null, hit_rate_pct: null`. No predictions are being scored over 7-day windows despite 133k observation rows and 48 active belief cells.

**Hypothesis (2-3 candidates worth checking):**
- (a) Prediction-logging path was never wired — the Bayesian engine emits predictions live but nothing persists them for later validation.
- (b) Logging path exists but the scoring loop (nightly?) was never enabled or has a guard that's never true.
- (c) Both paths exist but write to a table the accuracy sensor doesn't read from (schema mismatch from a refactor).

### Investigation goals (do BEFORE scoping a fix)

1. **Find the accuracy sensor's source query.** Search `BayesianPredictionAccuracy` class — what table does it read? What predicate? (Likely a JOIN of predictions vs. actual observations within a time window.)
2. **Find the prediction-logging call site.** Where do `*_likely_next_room` sensors compute their value, and does that call site persist `(person, predicted_room, timestamp, confidence)` to a table?
3. **Find the scoring loop.** Is there a nightly task that walks predictions, looks up the actual room the person was in at `prediction_ts + horizon`, and writes a score row? If yes, when did it last run? Logs.
4. **Check for table emptiness.** Use `mcp__ura-sqlite` to count rows in any `bayesian_predictions` or `prediction_scores` table — empty? Has it ever had rows?

### Promotion criteria — escalate from minor to feature cycle if:

- The logging path doesn't exist at all (have to design persistence schema + writer + scorer from scratch)
- The scorer requires non-trivial design choices (which horizon? top-1 vs top-3 accuracy? Brier across all rooms or just predicted room?)
- Findings expose that the predictor was producing predictions all along but nobody could validate them — that's a quality narrative beat worth its own cycle

### Otherwise — minor cycle scope (~80 LoC + 25 tests)

- Wire missing call site (logger OR scorer OR both)
- Backfill nothing — 7-day rolling window will populate naturally
- Add a sensor attribute disclosing what the score actually measures so users don't misread it
- Tier 1 review

**Reference:** Bayesian Prediction Accuracy sensor at `sensor.py` (search `BayesianPredictionAccuracy`). Likely-next-room sensor logic at `sensor.py:2400` per the existing B6 BACKLOG entry. May share infrastructure with the regime-shift work proposed in B7/v4.6.0.

## v4.5.13.2 — Envoy validation startup race fix

**Status:** Filed for immediate-next hotfix slot (after v4.5.13.1 zone dedup). Tier 1.

**Finding (2026-05-12, live-validated):** On HA restart, URA's `async_setup_entry` can run BEFORE the Enphase Envoy integration finishes its own setup. URA's `validate_envoy_config` calls `hass.states.get(envoy_eid)` and gets None — V2 (`ENVOY_ERR_ENTITY_MISSING`) fires. EC refuses to start. The configured entity is correct; it just isn't registered yet.

Bootstrap log proof (2026-05-12 04:15 UTC):
```
homeassistant.bootstrap | Waiting for integrations to complete setup:
  {('enphase_envoy', '01KNYRAGVP5XESS6N8PD6BVQP2'): ...}     [04:15:30]
URA | Energy Coordinator NOT started — envoy_entity_missing    [04:15:56]
```

URA recovered when the Coordinator Manager Energy options form was opened ~37 min later, which re-ran `async_setup_entry` with Enphase fully loaded.

### Design (state-added subscription, NOT polling-retry)

Approach: keep V2 hard-fail behavior for "entity truly missing from config" but distinguish from "entity not yet registered" via async state tracking.

1. **In `__init__.py` (or extracted helper):** when `validate_envoy_config` returns V2 failure AND `_energy_enabled`, do NOT immediately log error + raise repair issue. Instead:
   - Log a single INFO-level message: "Envoy entity not yet present; waiting for Enphase integration to finish setup"
   - Subscribe via `homeassistant.helpers.event.async_track_state_added_domain` for `sensor` domain
   - When the configured `envoy_eid` shows up in the added states, fire a one-shot retry: re-run `validate_envoy_config` and on success, reload the EC entry (or directly invoke the EC registration path)
   - Set a timeout (e.g., 5 minutes) after which, if the entity never appears, fall back to the current hard-fail behavior — log ERROR + raise repair issue

2. **Preserve current behavior for V1 (unparseable) and V4 (derived entities missing).** Those are config errors, not race conditions. Hard-fail immediately remains correct.

3. **Cleanup discipline.** Track the dispatcher unsub via `entry.async_on_unload` (or `hass.bus.async_listen` if needed). Race-fix should not leak listeners on entry unload.

### Tests required

Tier 1 quality protocol:

- **Behavior test:** stub Enphase entity to NOT exist initially, then add it 2 sec later. Assert that URA's listener picks it up and re-validates successfully.
- **Behavior test:** stub Enphase entity to never appear. Assert that after the 5-min timeout, URA falls back to hard-fail (error log + repair issue raised).
- **Behavior test:** V1 (bad serial format) still hard-fails immediately, no listener subscribed.
- **Lifecycle test:** entry unload tears down the state-added listener.
- **Source-grep:** no module-level imports of `async_track_state_added_domain` that could trigger Bug Class #34. Function-local imports OK per file convention.
- **AST test:** confirm the listener is registered via `entry.async_on_unload` (not orphaned).

### Promotion criteria — escalate from Tier 1 to feature cycle if:

- Investigation reveals more than the envoy entity gates on integration-load timing (other `hass.states.get` probes early in setup_entry may have the same shape — broader audit needed)
- Fix interacts with EC restore-switch behavior (the 30-min "deferred restore exhausted retries" finding suggests EC switches also need treatment)
- Timeout design becomes contentious (5 min? 10 min? exponential? — if these decisions need user input, scope as feature cycle)

### Reference material

- Hard-fail logic: `__init__.py:1530-1593` — gate at 1593 is `if _energy_enabled and _envoy_validation_ok`
- Validation function: `domain_coordinators/energy_const.py:513` (`validate_envoy_config`)
- V2 failure code: `ENVOY_ERR_ENTITY_MISSING` at `energy_const.py:435`
- HA helper: `homeassistant.helpers.event.async_track_state_added_domain`
- v4.2.29 was the cycle that introduced the hard-fail; predecessor was silent-fallback (which had its own correctness problems)

### Cost

- Production: ~50 LoC across `__init__.py` + (optional) helper extraction to `energy_const.py`
- Tests: ~80 LoC
- Tier 1 review (1 staff-engineer pass, mental execution required)

### Companion: EC switch deferred-restore retry budget

Adjacent finding from the same incident: 5 EC switches (`grid_import_cap`, `load_shedding`, `excess_solar`, `arbitrage`, `ev_tou_management`) gave up waiting for EC after ~3 min and fell back to constructor-seeded values. When EC eventually recovered ~30 min later, switches did NOT re-restore. **Probably worth folding into v4.5.13.2:** when EC becomes available, switches should re-attempt restore-from-DB if they previously gave up. Or: their retry budget should be longer / unbounded with a backoff.

## v4.5.18 — Failsafe occupancy-freshness gate (real bug, HIGH priority — fires nightly)

**Status:** Filed during v4.5.15 live validation. Bug existed since RESILIENCE-001 was introduced; surfaced when user pushed back on the initial diagnosis. Tier 1 cycle.

**SEVERITY UPGRADED (2026-05-12 after history verification):** This fires **every night for every bedroom with continuous 4+ hour occupancy**. Verified via HA history for Ziri Bedroom (2026-05-11 night) — motion went stale at 03:55 UTC, `sensor_presence` (mmWave) remained continuously ON for the next 2.5 hours through the failsafe firing at 06:19:42. Room was correctly occupied; failsafe was wrong. Same pattern observed earlier in session for Master Bedroom. Likely affects all 4 family bedrooms nightly.

User-visible damage: brief (30-60s) vacant transition fires automation side effects (lights off, HVAC vacancy mode, security checks) which then revert. Sleep protection toggle does NOT prevent this — that toggle only throttles motion-driven automation, not the failsafe.

**Finding (2026-05-12):** Failsafe at `coordinator.py:1409` checks only `duration > failsafe_seconds` where `duration = now - _became_occupied_time`. `_became_occupied_time` is set on vacant→occupied transition and NEVER refreshed by ongoing motion. Result: a legitimately occupied room (person sleeping, motion sensor working) hits the failsafe at the duration limit.

Observed:
- `Room Ziri Bedroom (Bedroom 5) (bedroom): Forcing vacancy after 240.5 min (failsafe — limit 240 min)` — kid sleeping, motion sensors functioning
- `Room Master Bedroom: Forcing vacancy after 4.0 hours (failsafe)` — same pattern, observed earlier in session

The failsafe is meant to catch:
- Stuck motion sensor (battery dying / hardware fault)
- Forgotten light (light turned on manually, no occupancy source)
- Motion sensor false-positive from environmental factors (HVAC vents, sunlight)

In NONE of those does motion stay fresh — a stuck sensor reports its frozen state, a forgotten light has no motion at all, and false positives are intermittent.

In LEGITIMATE long occupancy (sleeping person, working-from-home all day, watching long movie), motion IS fresh because the sensor IS being triggered.

**Sleep mode interaction:** `CONF_SLEEP_PROTECTION_ENABLED` + `automation.is_sleep_mode_active()` exist to throttle motion-driven automation overnight. But the failsafe doesn't consult sleep mode. Even with sleep protection ON, the failsafe still fires and forces vacancy — disrupting any automation that depends on the room being "occupied" through the night.

### Fix design (use the existing universal-signal timestamp)

**Refined after coordinator re-read:** `_last_motion_time` is misleadingly named — it's actually the **universal Tier 1 (PIR + mmWave + occupancy sensor) "any sensor active" timestamp** at `coordinator.py:1352-1353`:

```python
elif any_sensor_active:   # any_sensor_active = motion OR mmwave OR occupancy
    self._last_motion_time = now
```

So for motion-and-mmWave rooms (most bedrooms), `_last_motion_time` already stays fresh as long as ANY Tier 1 sensor is active. The failsafe just needs to USE it.

The failsafe should require BOTH conditions to fire:
1. `duration > failsafe_seconds` (existing — total continuous occupancy)
2. **NEW:** `_last_motion_time` is stale — no signal within `2 * occupancy_timeout`

Pseudo-code at the failsafe check (`coordinator.py:1394`):

```python
if duration > failsafe_seconds:
    if self._last_motion_time:
        signal_age = (now - self._last_motion_time).total_seconds()
        stale_threshold = 2 * self._occupancy_timeout  # bedroom: 30 min
        if signal_age < stale_threshold:
            # Tier 1 sensor still firing → legitimate occupancy → skip failsafe
            _LOGGER.debug(
                "Room %s: skipping failsafe — signal fresh (%.0fs ago)",
                room_name, signal_age,
            )
            return
    # genuinely stuck → fire failsafe (preserve existing behavior)
    ...
```

### Companion clean-up — DROPPED (risk-avoidant decision 2026-05-12 CDT)

Initial sketch proposed changing camera + BLE override branches from "set `_last_motion_time = now` only if None" to "always set". Audit revealed THREE downstream risks that don't justify the limited juice (camera-only / BLE-only rooms — rare on this install):

1. **Breaks Sparse BLE hardening (`coordinator.py:1480-1483`).** The Tier 2 BLE gate requires `_last_motion_time` to be fresh as PROOF OF MOTION corroboration. If BLE override starts updating `_last_motion_time` itself, the gate becomes self-confirming — shared-scanner BLE false positives persist forever.
2. **`STATE_TIME_SINCE_MOTION` sensor (`coordinator.py:1391-1392`) becomes a lie.** Reports "0 seconds since motion" when only camera/BLE fired.
3. **Hidden behavioral drift across all downstream readers** of `_last_motion_time` — anything semantically expecting "PIR/mmWave last fired" would now sometimes mean "any-source last fired."

The right fix IF someone ever hits this edge case is a NEW `_last_occupancy_signal_time` field separate from `_last_motion_time` (preserving Tier 1 semantics for sensors / displays / Sparse BLE corroboration). **Cut for now (2026-05-12 CDT)** — juice is limited, blast radius of the always-set shortcut is real, and the proper fix is more work than the rare edge case justifies.

### Pre-fix verification (5 min)

- Confirm `_last_motion_time` IS updated by mmWave on every cycle: re-read `coordinator.py:840-870` and trace `any_sensor_active = self._evaluate_sensor_logic()` (or equivalent — verify the function returns True when mmWave alone is on)
- For Ziri Bedroom: confirm `sensor_presence` IS in the room's `CONF_MMWAVE_SENSORS` config, not some other field

No new attribute tracking needed. No new signal subscriptions. No camera/BLE branch touches. Pure logic gate.

### Edge cases to handle in design

- Room with NO motion sensor (manual switch / camera / person tracking only): `_last_motion_time` is None — check other sources first.
- Room with NO presence sensor: `_last_presence_time` is None — check motion + camera + person tracking.
- Person tracking-only room (BLE Bermuda): `_last_person_seen` is the gate.
- Truly nothing-fresh room: failsafe fires (this is the correct stuck-sensor / forgotten-light case).

### Cost (final, risk-minimized scope)

- Production: **~20 LoC** — single signal-freshness gate at coordinator.py:1394. Zero touches to camera/BLE branches, displays, or downstream consumers.
- Tests: ~30 LoC — isolated decision-helper tests mirroring v4.5.15 pattern (fresh signal + over duration = no fire; stale signal + over duration = fire; under duration regardless = no fire; missing `_last_motion_time` = treat as stale, fire)
- Tier 1 review (one staff-engineer pass)

### Promotion criteria — escalate from Tier 1 to feature cycle if:
- Adding presence-timestamp tracking requires touching multiple coordinator subscriptions (signal-listener wiring beyond a single source) — possible
- Per-room stale-threshold needs config option (don't think so for v4.5.18; defaults are fine)
- Tests need behavioral integration against full coordinator (probably should, but can pin with isolated decision-helper tests like we did in v4.5.15)

### Reference material

- Failsafe code: `coordinator.py:1394-1422`
- `_became_occupied_time` setting sites: `coordinator.py:1366, 1778, 1796`
- Sleep mode: `automation.py:486 is_sleep_mode_active()`, const `CONF_SLEEP_PROTECTION_ENABLED`
- Camera path: `coordinator.py:1395-1415` (reads `hass.states.get(person_sensor).state == "on"`, no timestamp stamped)
- Live evidence: HA history for `binary_sensor.ziri_bedroom_bedroom_5_motion` + `_sensor_presence` on 2026-05-11 21:19 CDT → 2026-05-12 01:19 CDT shows motion went stale 03:55 → 05:07 UTC (72 min) while presence stayed continuously ON. Failsafe fired at 06:19:42 UTC; presence was still ON at that moment.
- Master Bedroom also observed failsafing earlier in same session — pattern confirmed across multiple bedrooms.

## v4.5.x — Periodic-closure swallow audit (wider scope)

**Status:** Filed during v4.5.17 review, REFINED 2026-05-12 CDT after grepping `__init__.py` showed only 5 real swallow sites, all one-shot migrations/prunes (low value). The original audit scope is mostly already clean. **The actual hunt is in the OTHER files** — periodic closures elsewhere in the codebase are where the next v4.5.17-shape silent killer is most likely hiding.

### Scope (revised)

Audit periodic-closure (`async_track_time_change`, `async_track_time_interval`, `async_track_state_change`, dispatcher subscriptions in `DataUpdateCoordinator._async_update_data`) call sites in:

1. **`coordinator.py`** (room coordinator, runs every 30s — periodic)
2. **`domain_coordinators/*.py`** (each runs every 5 min — periodic)
   - hvac.py, energy.py, presence.py, safety.py, security.py, music_following.py, notification_manager.py
3. **`aggregation.py`** (whole-house sensors, may register periodic timers)
4. **`bayesian_predictor.py`** (already audited and fixed)

For each periodic closure, look for `except Exception:` blocks containing `_LOGGER.debug(...)` as the SOLE handler. That's the v4.5.17 shape — every fire that throws is invisible.

### Why this is higher value than the `__init__.py` audit

`__init__.py` is mostly setup code — it runs once at startup. A failure there is usually visible (something didn't initialize, integration won't load, etc.).

Periodic closures fire continuously for the lifetime of HA. A `_LOGGER.debug` swallow can hide a NameError, KeyError, AttributeError, ImportError, etc. that fires every cycle and silently breaks the feature for **months** (as the Bayesian eval bug did).

### Audit procedure

1. Grep each file for `async_track_time_*` and `async_dispatcher_connect` registrations
2. Trace the registered callback to its definition
3. Inside each callback, find `except` blocks
4. Classify the `_LOGGER` level in the handler:
   - `_LOGGER.error` + traceback → fine
   - `_LOGGER.warning` + exc_info → fine
   - `_LOGGER.exception` → fine (auto-traceback)
   - `_LOGGER.warning` no exc_info → recommend adding `exc_info=True`
   - `_LOGGER.info` → flag
   - **`_LOGGER.debug` → ESCALATE** (the v4.5.17 shape — silent killer)
   - no log at all (bare `pass` or `continue`) → also flag

### Expected outcome

Probably 0-5 sites needing escalation. Bayesian eval was the canonical case; URA's other periodic paths tend to use warning or error already. The audit is preventative.

If even one new silent-NameError-class bug surfaces from this audit, the cycle pays for itself.

### Cost

- Audit (read-only): ~45 min across ~10 files
- Fixes (escalations): ~20 LoC (1-3 LoC per escalation)
- Tests: AST regression asserting no periodic-closure callback has a sole `_LOGGER.debug` handler in its `except` clause. ~40 LoC.
- Tier 1 (single staff-engineer review).

**Promotion criteria:** if audit reveals more than 5 sites OR any site looks behaviorally questionable beyond log-level (e.g., the except catches too broadly, the cycle calls async-unsafe code in the except, etc.), promote to feature cycle.

### Note on the narrower `__init__.py` audit

After grepping during v4.5.18 prep, the original "~15 sites" estimate was high. Real classification:
- ~10 sites: "normal-skip" debug logs (informational; not exception swallows)
- ~4 sites: init sequence trace logs (not exception swallows)
- 2 sites: v4.5.16/17 fix sites already at WARNING + exc_info
- **0 sites: periodic closures with debug-swallow** (the dangerous shape)
- ~5 sites: one-shot migration/prune exception swallows (lower stakes — failures recur every startup or daily and eventually surface)

The 5 one-shot sites could be escalated as a low-priority polish item rolled into the next `__init__.py` touch. Not worth a standalone cycle.

## v4.5.16 Phase 2 carry-overs (after Phase 1 ships)

Filed during v4.5.16 Tier 1 review. Non-blocking; fold into Phase 2 cycle when we make the prediction-scoring fix:

1. **Demote empty-batch + success Bayesian logs** from WARNING/INFO to a quieter level once Phase 1 confirms the failure mode. Currently noisy at 6×/day per coord.
2. **Min-floor on stale-threshold** in `coordinator.py:_get_failsafe_duration_seconds` callers. A user-customized very-low `_occupancy_timeout` (e.g. 30s) collapses the failsafe gate's stale threshold to 60s — burst-detect mmWave devices with `off_delay` near 60s could legitimately silence. Suggest `max(2 * occupancy_timeout, 180)`.
3. **Max-cap on stale-threshold.** A user-customized very-high `_occupancy_timeout` (e.g. 7200s) gives a 4-hr threshold equal to the failsafe ceiling — effectively never-fires. Suggest cap at `failsafe_seconds / 2`.
4. **Parallel clock-skew clamp at `coordinator.py:1517`** — Tier 2 BLE hardening (`motion_age = (now - self._last_motion_time).total_seconds()`) has the same `negative < positive` pathology. The v4.5.16 clamp at the failsafe gate defends that one site; do the same here.

## v4.5.x — Post-v4.5.19 follow-ups (filed during Tier 2 review)

**Status:** Non-blocking carry-overs from v4.5.19 review. Both observability/hardening — small.

1. **Bayesian prior recomputation from deduplicated transitions.** v4.5.19 stops the duplicate-write bleed but the 11k existing duplicate rows in `room_transitions` continue to inflate priors until they age out of the 90-day window. Options:
   - Accept gradual decay (priors self-correct over ~90 days as fresh deduplicated rows accumulate)
   - Force a one-time prior rebuild that dedups the 90-day window (~50 LoC + DB migration)
   - Add a UNIQUE constraint on `(person_id, second_truncated_ts, from_room, to_room)` to belt-and-braces the schema (separate, larger scope)
2. **Chaotic-unload test coverage.** v4.5.19's `async_teardown` defensively handles teardown-before-init and unsub-raises-during-call, but the existing 11 tests don't explicitly exercise those paths. Add 2 small behavior tests:
   - Construct detector, do NOT call async_init, call teardown — assert no crash
   - Stub `_unsub_bus` to raise on call, call teardown — assert warning log fires and `_unsub_cleanup` still runs

Promotion: ship as part of any v4.5.x cycle that touches `transitions.py` or as a small standalone cycle when noticed.

## Anomaly sensor refresh signals (Presence + MF) — ready to ship

**Status:** Detailed plan completed during v4.5.18 prep (2026-05-12 CDT). Supersedes the prior rough sketch. Ready for a Tier 1 slot.

**Why now:** `MusicFollowingAnomalySensor.extra_state_attributes` docstring at sensor.py:4643-4645 explicitly acknowledges the gap. Anomaly status from `get_worst_severity()` / `get_learning_status()` / `get_status_summary()` can shift mid-cycle and never re-renders until HA re-queries.

### Pattern audit
- **HVAC:** `SIGNAL_HVAC_ENTITIES_UPDATE` in `domain_coordinators/hvac_const.py:333` (outlier — NOT in signals.py; mistake that already cost v4.5.10.1 ImportError). Fired at `hvac.py:606`.
- **Safety:** `SIGNAL_SAFETY_ENTITIES_UPDATE` in `signals.py:16`. Fired at `safety.py:2116` end of evaluate.
- **Security:** `SIGNAL_SECURITY_ENTITIES_UPDATE` in `signals.py:18`. Fired at ~12 state-mutation sites.
- **Subscriber pattern** (use HVACAnomalySensor at sensor.py:7378-7392): `async_added_to_hass` → function-local import of signal → `async_on_remove(async_dispatcher_connect(...))` → `_handle_update` calls `async_schedule_update_ha_state()`.

### Implementation sketch (5 steps)
1. **signals.py:** add `SIGNAL_PRESENCE_ENTITIES_UPDATE` and `SIGNAL_MUSIC_FOLLOWING_ENTITIES_UPDATE` (mirror Safety/Security convention, NOT HVAC outlier).
2. **presence.py:** at end of `_run_inference` (line ~1515, after `_check_zone_anomalies()`), add `async_dispatcher_send(self.hass, SIGNAL_PRESENCE_ENTITIES_UPDATE)`. `async_dispatcher_send` already imported.
3. **music_following.py:** at end of `_on_transfer_outcome` (line ~168, after `record_observation`), add `async_dispatcher_send(self.hass, SIGNAL_MUSIC_FOLLOWING_ENTITIES_UPDATE)`. MF is event-driven — no periodic tick — so dispatch fires on every transfer outcome.
4. **sensor.py subscribers:**
   - `PresenceAnomalySensor` (3519) → SIGNAL_PRESENCE_ENTITIES_UPDATE
   - `PresenceComplianceSensor` (3577) → SIGNAL_PRESENCE_ENTITIES_UPDATE
   - `MusicFollowingAnomalySensor` (4604) → SIGNAL_MUSIC_FOLLOWING_ENTITIES_UPDATE
   - DO NOT subscribe MF Health/TransfersToday/ActiveRooms/LastTransfer — they already use MF's internal `add_diagnostic_listener` push pattern; double-subscription would double-fire on every transfer.
5. **Cleanup:** remove the stale comment at sensor.py:4643-4645 explicitly saying "no SIGNAL_MUSIC_FOLLOWING_ENTITIES_UPDATE exists".

### Test plan
- AST: each new subscriber class defines `async_added_to_hass` + body contains `async_dispatcher_connect(..., SIGNAL_*)` for the expected constant
- Source-grep: new signal constants present in signals.py; dispatches at the expected lines
- Import-resolves test: AST-walk `from .domain_coordinators.signals import SIGNAL_*` references and assert each is defined (Bug Class #32 prevention — same shape as v4.5.10.1 footgun)
- Behavioral: stub coordinator, fire signal via `async_dispatcher_send`, assert `async_schedule_update_ha_state` invoked

### Cost
- Production: ~30 LoC (2 constants, 2 dispatches + imports, 4-6 sensor `async_added_to_hass` blocks)
- Tests: ~25 LoC
- Tier 1

### Risks
- **Symbol-collision audit (CRITICAL):** `rg "ura_presence_entities_update|ura_music_following_entities_update"` must return empty before merge. Bug Class #32 shape if either name pre-exists.
- **HVAC-outlier import temptation:** do NOT mirror HVAC by adding a `presence_const.py`. Put both new constants in `signals.py`.
- **Cleanup on reload:** use `async_on_remove(async_dispatcher_connect(...))`, never bare `async_dispatcher_connect` — same pattern as HVAC subscribers.
- **MF cold path:** if MF never fires (no transfers since startup), MF anomaly sensor never refreshes. Acceptable — its state can't have changed either.
- **Observation mode:** these dispatches do NOT need observation-mode gating (only refresh attributes; no side effects).

### Promotion criteria
- User report that an anomaly sensor "looks stuck" despite known anomaly events in DB, OR
- Bundle with any v4.5.x cycle touching presence.py or music_following.py to amortize harness work

### Files touched
- `domain_coordinators/signals.py` (+2 constants)
- `domain_coordinators/presence.py` (+1 dispatch in `_run_inference`)
- `domain_coordinators/music_following.py` (+1 dispatch in `_on_transfer_outcome`)
- `sensor.py` (+4 `async_added_to_hass` blocks; remove stale comment 4643-4645)
- `quality/tests/test_v4_5_x_anomaly_refresh_signals.py` (new)

## Device-page ordering — HC experiment plan (test → revert → sweep)

**Status:** Plan complete (2026-05-12 CDT). Ready for a small Tier 1 experimental cycle.

### Confirmed mechanism
- HA frontend sorts entities by `stateName` (friendly_name), locale-aware, within each EntityCategory cluster (CONFIG / DIAGNOSTIC / no-category). With `has_entity_name = True`, HA strips the device-name prefix → sort effectively operates on `_attr_name` alone.
- Source: `home-assistant/frontend/src/panels/config/devices/ha-config-device-page.ts` (researched earlier this session).

### Prefix scheme
- **Format:** `"NN · Name"` — two ASCII digits + space + middle-dot (U+00B7) + space + original name.
- **Rationale:** zero-padded digits → `"01" < "02" < ... < "10" < "20"` correctly under locale compare (no `"1"` vs `"10"` mis-sort). Middle-dot is the least visually ugly delimiter; comma/dot/em-dash all look worse.
- **Gap = 10** between adjacent entries; per-zone clusters use sub-gap of 1-2 so new zones slot in. Reserves room without renumber churn.

### Proposed HC scan order (3 clusters)

**Sensors cluster** (no category):
- 10 Mode · 30 Comfort Risk · 40 Pre-Cool Likelihood · 50 AC Nudges Today · 60 AC Hard Resets Today · 70 AC kWh Avoided Today · 80 AC kWh Avoided (Total)

**CONFIG cluster** (master → toggles → tunables → per-zone):
- 10 Observation Mode · 15 AC Ramp-Down · 20 Override Arrester · 25 AC Reset · 30 Per-Zone HVAC Control · 35 Pre-Arrival · 40 Fan Control · 45 Solar Cover · 50 Vacancy Auto-Off · 60-66 v4.5.10 tunables · 70-75 v4.5.11 AC tunables · 80 Zone Entry Dwell · 90 AC kWh Rate Threshold (per zone) · 95 Clear AC Ramp Lockout (per zone)

**DIAGNOSTIC cluster** (top-level health → state → per-zone → debug):
- 10 HVAC Anomaly · 15 Compliance · 20 Override Frequency · 25 Arrester State · 30 Arrester Status · 35 Zone Intelligence · 40 Pre-Arrival Status · 45 AC Nudge False-Positive Rate · 50/55 Zone Status/Preset (per zone) · 60-64 D7 (state/last_action/kwh_rate, per AC zone) · 80/82 Force/Cancel Nudge (per zone) · 90 AC Ramp Diagnostic Dump

### Test + revert procedure
1. `git tag pre-prefix-hc-v4.5.x` baseline
2. Screenshot HC device page (all clusters expanded) BEFORE
3. Apply `_attr_name` prefixes per the plan — touch only sensor.py / switch.py / number.py / button.py; **no unique_id / entity_id / device_info changes**
4. Deploy as `4.5.x` tiny cycle (~50 LoC + 30 tests)
5. After HACS download + restart, new screenshot. Compare.
6. If happy → keep, plan sweep. If unhappy → `git revert <commit>` (zero side effects since only `_attr_name` changed)

### Sweep order (after HC validates)
1. **Coordinator-Manager** (singleton, low entity count, proves pattern on another coord)
2. **House device** (~12 entities, single instance, high user visibility)
3. **Zone device** (per-zone, modest scale)
4. **Other Coordinators batched** (NM, EC, Safety, Security, Music Following)
5. **Room device LAST** (74+ × 31 rooms ≈ 2300+ entities — highest dashboard-card consumer risk; validate one room first before sweep)

### Risks
- **Voice assistants** speak friendly_name: `"10 · Override Arrester"` reads as "ten middle-dot override arrester". HA does not strip prefixes for voice. Tolerable; the user can always rename specific entities via UI for voice-heavy use.
- **Logbook + history graphs** render friendly_name; prefix appears there.
- **Lovelace cards** that read `name:` from friendly_name will display the prefix unless they override `name`.
- **Locale-compare edge case:** if HA user locale ever uses non-Western digit collation, order could break. Low-risk mitigation: stay on ASCII digits.

### Cost
- Production: ~50 LoC across 4 files (only `_attr_name =` lines for HC entities)
- Tests: ~30 LoC asserting every HC entity's `_attr_name` matches `r"^\d{2} · "` regex
- Tier 1, single deploy

### Key files
- `sensor.py` (HVAC sensor classes 6749-8200; `_hvac_device_info` helper at 6735)
- `switch.py` (9 HVAC switches at 688-1700)
- `number.py` (factories at 775, 920, 1019, 1112; ZoneEntryDwell at 250)
- `button.py` (`_ACRampButton` at 597; specs at 553; DiagnosticDumpButton at 735)

## Device-page entity ordering (UX polish, no slot)

**Status:** Filed for future UX cycle. No urgency; user-visible papercut.

**Finding (2026-05-12, research-confirmed):** HA frontend sorts entities on the device-detail page by **friendly_name** (`stateName`), locale-aware string compare — NOT by entity_id. Source: `home-assistant/frontend` `src/panels/config/devices/ha-config-device-page.ts` (`_entities` memoized function, ~lines 270-323). Fallback is `"zzz" + entity_id` so unnamed entities sink to the bottom. Confirmed via deep web research; no HA-blessed first-class ordering mechanism exists, and the HA architecture repo has no ADR on the topic.

### Workarounds, ranked

1. **Numeric prefix on `_attr_name`** (`"01 Mode"`, `"10 Battery SOC"`, `"50 …"`). The only mechanism that affects the actual device-page renderer. Visible cruft but controllable. ESPHome has a `sorting_weight` field but it doesn't propagate to HA's device page — even ESPHome's own infrastructure can't reach HA.
2. **Cluster-aware grouping by name prefix** (`"Nudge …"`, `"Reset …"`, `"Ramp …"`). Doesn't give arbitrary order, gives clustering. Often the *real* UX issue is that related entities are scattered alphabetically.
3. **Custom Lovelace card shipped via integration.** Supported HA path. Only affects dashboards, not device pages. Already a partial-solution per the v4.5.12 HC user manual.
4. **Sections-view dashboard YAML.** Modern HA (2024.03+) feature. Ship pre-built YAML files in `docs/dashboards/` for users to import.

### Workarounds that DON'T work

- Labels — filtering/grouping metadata only; not in the sort comparator
- `translation_key` — resolves to localized string but is not itself the sort key
- `EntityCategory` sub-ordering — doesn't exist
- entity_id renames — break every existing dashboard/automation/template reference

### Recommended scope for a UX cycle

**Phase 1 (cheap, internal):** Add a `_sort_prefix` field to URA's `AggregationEntity` base class (or similar). Coordinators declare order via the prefix (e.g., `"01"`, `"10"`, `"50"`). The base class prepends to `_attr_name`. One bit of cruft, controllable everywhere, no entity_id churn, no dashboard breakage. ~50 LoC + 20 tests.

**Phase 2 (richer):** Ship pre-built Sections-view dashboard YAML files for HC, EC, NM in `docs/dashboards/`. Users import them and get a curated UX bypassing the device page entirely. ~3 hours of YAML work; no code.

**Phase 3 (longest, lowest ROI):** Custom Lovelace cards shipped via the integration's frontend module. Only worth doing if Phase 2's static YAML doesn't address the need.

### Reference material

- `home-assistant/frontend` `src/panels/config/devices/ha-config-device-page.ts`
- HA community thread: https://community.home-assistant.io/t/ordering-entities-in-the-device-page-on-ha/990211
- HA Custom Card docs: https://developers.home-assistant.io/docs/frontend/custom-ui/custom-card/
- Research conducted post-v4.5.12 deploy; full research output in conversation log

**Promotion criteria:** schedule as a UX cycle when (a) the user explicitly asks for it, (b) URA gets a second user, or (c) the device-page sprawl crosses some "too much friction" threshold subjectively.

## House Energy/Cost Accounting Reconciliation (Tier 2 investigation, fork)

**Status:** Filed 2026-05-18. Do not promote until a downstream feature needs a canonical cost figure.

Two parallel accounting paths currently coexist in URA:
- **URA path:** `WholeHouseEnergySensor` (sums user-configured `whole_house_energy_sensors`) → `WholeHouseCostTodaySensor` (added v4.6.8, multiplies by TOU rate).
- **EC path:** `EnergyCoordinator.cost_today` / `cost_this_cycle` (computed from Envoy lifetime deltas × TOU rate via `CostTracker`).

Both are valid. Both use the same TOU rate after v4.6.8. They track different energy sources so they will not agree.

**Scope of investigation:**
- Document the two paths with clear semantics (URA = room-metered load, EC = grid net-import/export).
- Decide canonical path for a monthly billing dashboard or utility-meter integration.
- Determine whether `WholeHouseCostTodaySensor` (v4.6.8 D6) should become the canonical realized-cost surface and what happens to EC's `cost_today`.

**Trigger condition:** Promote only when a downstream feature (utility-meter integration, monthly billing UI, energy dashboard v3) needs a canonical realized-cost figure.

---

## AnomalyType Discriminator Promote (Tier 2-DB, active queue)

**Status:** Filed 2026-05-18 per user directive. Ready to queue when the next DB-sensitive cycle is scheduled.

**Spec (from B7 sub-spec, BACKLOG lines 435+):** Add `AnomalyType` column to `AnomalyRecord` + `anomaly_log` schema migration.
- Values: `point_in_time | regime_shift`
- Default `point_in_time` for back-compat on existing rows
- ~50 prod LoC + ~40 test LoC + migration script

**Ceremony:** Tier 2-DB (3x parallel reviews per CLAUDE.md) — touches `database.py` DAOs, migrates callers, changes payload shape.

**Recall hint:** `"Resume AnomalyType discriminator promote"`

---

## Per-Metric Z-Threshold Customization (deferred — trigger conditions below)

**Status:** Filed 2026-05-18. Do NOT queue until a trigger fires.

Currently `z_threshold` is global per coordinator (HVAC, Security, etc.).

**Promote ONLY when ANY of:**
- User reports an anomaly category flooding alerts (e.g., HVAC override_frequency hits every day even after baseline maturity)
- Cardinality audit reveals a metric's natural variance is structurally different from its siblings in the same coordinator
- Tier 3 dashboard surface needs per-metric tuning knobs (UX driving it, not algorithm)

**Estimated cost when promoted:** ~80 prod LoC + ~60 test LoC. Tier 2 (touches config flow + options flow per coordinator).

---

## Other Tracked Items

- **Jaya + Ziri bedrooms** — need motion sensors added via config flow (options saved, blocked by bug #1)
- **BlueBubbles webhook** — BB server webhook for inbound iMessage (operational setup, not code)
- **Dashboard v3 polish** — built, not deployed
- **Diagnostic logging downgrade** — person coordinator WARNING → DEBUG after stabilization

## Recommended Priority (post-v4.6.8)

1. Optimizer Phase 1 (Activity Log done, no blockers remaining)
2. AnomalyType discriminator promote (Tier 2-DB, spec complete)
3. B3 pre-emptive actions (planned — zone/house level, see `docs/planning/PLANNING_v4.x_B3_PREEMPTIVE_ACTIONS.md`)
4. DB write queue deeper fixes (if room count grows or warmup becomes unacceptable)
5. House Energy/Cost Accounting Reconciliation (when downstream feature needs canonical cost figure)
