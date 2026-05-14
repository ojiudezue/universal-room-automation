# URA Backlog — As of v4.2.6 (Apr 19, 2026)

## v4.6.2.3 — Review carry-overs from v4.6.2.1 + v4.6.2.2 (queued, Tier 1)

**Status:** Filed 2026-05-14 from Tier 1 reviews of v4.6.2.1 + v4.6.2.2. Both cycles shipped; these items were intentionally deferred to keep the hotfixes tight. Bundle into one short cycle.

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

1. **Config flow save timeout** — Options persist to disk but `async_reload` from options flow update listener times out. Manual reload works.
   - **Partially mitigated** in v4.2.0: try-except + debug logging on 7 room option steps. Root cause (93 entities per room causing reload timeout) remains.
   - Workaround: manually reload entry after save.

2. **Energy TOU blocking I/O** — `energy_tou.py:68` synchronous `filepath.read_text()` on event loop. HA 2026.x flags this.
   - Fix: `await hass.async_add_executor_job(filepath.read_text)`

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

**D. Stub energy/cost prediction sensors** — `aggregation.py:1710-1911`: `PredictedEnergyWeekSensor`, `PredictedEnergyMonthSensor`, `PredictedCostTodaySensor`, `PredictedCostWeekSensor`, `PredictedCostMonthSensor` are missing `async_update()`. Hotfix needs implementation + Cost variants need EC `current_effective_rate` integration (architectural decision pending).

**E. Legacy fixed-cost-rate vs EC TOU rate reconciliation** — Pre-EC code: rooms have `CONF_ELECTRICITY_RATE` static; cost calculations in `coordinator.py:1804-1811`, `aggregation.py:1813-1815` use it. EC era: `EnergyCoordinator.current_effective_rate` (`energy.py:2837`) is TOU-aware and authoritative. All cost calculations should migrate to EC's rate when EC is configured (with static config as fallback when EC not present).

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

## Appliance Scheduler (B5)

**B5: Appliance Scheduler — Cost-Reduction Deferral + Forecast-Aware Sprinklers** — New domain coordinator that defers LG ThinQ washer/dishwasher/washtower starts to off-peak TOU, and skips Rainbird sprinkler cycles based on weather forecast. Provider plugin pattern for future integrations (Bosch, SmartThings, generic power-sensor). Restart-survivable, reload-resilient. **Full plan:** `docs/planning/PLANNING_v4.4.x_APPLIANCE_SCHEDULER.md`

Phasing: D1+D2+D3+D4+D6 as v4.4.0; D5 hardening as v4.4.1; D7 sprinkler skip as v4.4.2; D8 generic provider as v4.5.0.

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

## Other Tracked Items

- **Jaya + Ziri bedrooms** — need motion sensors added via config flow (options saved, blocked by bug #1)
- **BlueBubbles webhook** — BB server webhook for inbound iMessage (operational setup, not code)
- **Dashboard v3 polish** — built, not deployed
- **Diagnostic logging downgrade** — person coordinator WARNING → DEBUG after stabilization

## Recommended Priority

1. Config flow save root cause (partially mitigated in v4.2.0, still times out on large rooms)
2. Optimizer Phase 1 (Activity Log done, no blockers remaining)
3. B3 pre-emptive actions (planned — zone/house level, see `docs/planning/PLANNING_v4.x_B3_PREEMPTIVE_ACTIONS.md`)
4. DB write queue deeper fixes (if room count grows or warmup becomes unacceptable)
