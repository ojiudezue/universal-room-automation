# URA Backlog — As of v4.2.6 (Apr 19, 2026)

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
