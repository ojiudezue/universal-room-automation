# PLANNING: Room occupancy-anomaly sensor on a dwell model

**Card:** BAYES-OCCUPANCY-ANOMALY-NEVER-EVALUATES-1 (thread: presence). **Status:** BUILT 2026-10-21 on `feat/occupancy-dwell-anomaly` (README_v5.103.83), not deployed.

**Build notes (deviations, operator decisions 2026-10-21):**
- D0 runs AFTER deploy as the live check (operator), as the committed script `scripts/probes/occupancy_dwell_backtest.py`. Knob defaults kept as §6.
- Q1 answered yes (rare-hour visit fires). Q2: signal AND row both skip in observation mode, read from the PRESENCE coordinator's `observation_mode`. §5/D3's "today the signal is sent in observation mode" was wrong: the old code skipped both, but its check read `coordinator._observation_mode`, which the room coordinator does not have (always False).
- Side finds fixed here, not carded (operator): plus `get_uncomfortable_minutes_today` (same name-key at the same sensor call sites, and a UTC midnight), and exit-row `duration` is time-since-last-motion, not episode length, so both occupancy DAOs now pair entry/exit rows.
- `occupied IS NOT NULL` in the DAO is belt-and-braces: `COUNT(occupied)` already skips NULL.
- Arithmetic finding from the build-time replay: a 56-day weekend cell holds at most 16 x 12 = 192 samples, below `OCC_ANOMALY_MIN_CELL_SAMPLES` = 200 ("40% of a weekday cell"), so weekend cells never leave `learning` and G4 ("every cell") cannot pass at these defaults.
  **Fix-up (coordinator 2026-10-21):** the gate is now `OCC_ANOMALY_MIN_CELL_DAYS` = 4 distinct local days per cell, with a sample floor `OCC_ANOMALY_MIN_CELL_SAMPLES` = 24. Replay at the new gate: G4 47/47; G1 still fails at 900 s (median 5/day).
- **Shipped setting (coordinator 2026-10-21): `OCC_ANOMALY_DEBOUNCE_S` = 1800** (§6 said 900). 7-day replay at 0.02 / 1800 s / 48-cell: G1 PASS (median 0/day, max 2 per room, 5 fires total), G2 PASS heuristic (0 of 5 overlap a resident visit), G3 PASS (0 Study A daytime fires; share 0.56), G4 PASS (47/47).
- Data depth: `environmental_data` runs from 2025-11-19 (no purge problem; URA retention 365 d). The "7 days" is HA's recorder (`purge_keep_days: 7`), which limits how far back the replay can go, not the model.
- The four "today" sensors had the same never-called `async_update`. Fixed in this branch: throttled refresh from the coordinator update (`TODAY_SENSOR_REFRESH_S` = 300) and quantized values.
- The forecast-sensors-onto-RoomDwellModel switch is the next card, not this branch.
- **Review fix-up (A/B/C, renumbered v5.103.83):** exit row always written (producer) + `OCC_EPISODE_MAX_S` 12 h episode cap and bounded look-back (readers); model build in the executor with a stop-wins guard; one 600 s retry after a failed first build; visits cap 200000; docstring cost corrected; pct uses `start_of_local_day`; 18 new drills (71 total, all RED).
**Evidence base:** `docs/planning/AUDIT_occupancy_anomaly_rate_2026_10_20.md` (the D0 audit of the old model).
**Also read:** `docs/planning/AUDIT_predictions_room_zone_house_2026_10_21.md` (landed while this plan was being written; folded into §9).

## Operator decisions (binding)

- "Make the sensor work." The operator picked option C: rebuild it on a dwell model.
- "I would not alert. The routine change is enough. It should assert in its sensor and give more information."
  - No NM alert and no notification of any kind.
  - The sensor turns on, and its attributes explain why: what is usual for this room at this hour, who is usually there, which signal made the room occupied, how long it has been occupied, learning status, and whether guest suppression applied.
  - Keep the signal and the `anomaly_log` row (card note `operator_answer_2026_10_20_b`).

## What this plan does, in one paragraph

Every room coordinator already writes a 5-minute sample of `occupied` into `environmental_data`, which is kept for 365 days. Averaging those samples by room, local hour and weekday/weekend gives "what share of the time is this room usually occupied at this hour". That is dwell, not arrivals, which is exactly what the old Bayesian path got wrong (Study A, Oji's second-longest-dwell room, scored 0.004). The sensor turns on when the room is occupied, the room's usual share for this hour is below a threshold, the cell has enough history, the occupancy has lasted past a debounce, and the house is not in GUEST. Evaluation moves from the dead `async_update` onto the coordinator-update callback. The model is rebuilt once a night from one bounded `GROUP BY` read; nothing new is written except one `anomaly_log` row per rising edge. A D0 backtest over 14 days, trained only on data before each replayed day, decides whether it ships.

---

## 1. Institutional context verified

Read completely first, as the presence rule requires: `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (all 725 lines) and `docs/architecture/SENSOR_FLEET_CLASSES.md`. Nothing in the State-of-Play §10 corrections ledger is re-asserted here. Relevant points taken from them:
- Room occupancy (`binary_sensor.<room>_occupied`, `coordinator.py` STATE_OCCUPIED) includes phantom holds: Study A ZK still-holds, the Jaya LD2410 fan loop, and fan-on radar rooms with no fan-immune witness (Media, GB1, GB2). The dwell model learns from that same signal, so a room that is regularly held by a phantom will learn that hold as "usual". That is accepted and named in §8.
- The occupancy-source string is a list label, not a capability. Trust questions read `STATE_RADAR_SOLE_TICK` (§10 #10). This plan only displays them.
- Classify sensors by capability, never by entity name (SENSOR_FLEET_CLASSES Rule 3). This plan classifies no sensors.

The identity manual and the HVAC state-of-play doc were not needed: no identity, camera, census or HVAC value is touched.

### 1.1 Prior-art scan: code

| Piece | Verdict | Where (file:line) | Note |
|---|---|---|---|
| Dwell data source | **REUSE** | `coordinator.py:5461-5472` writes `environmental_data(room_id=entry_id, timestamp=utcnow, occupied)` every 300 s; table `database.py:852-862`, index `idx_env_room_time(room_id, timestamp)` | Kept 365 days: `const.RETENTION_ROOM_HISTORY_DAYS = 365` (`const.py:2114`), pruned by `cleanup_room_history` (`database.py:5233`, UTC clock, `database.py:5215`). No new writer. |
| "Each env row = ~5 min of dwell" precedent | **REUSE (pattern)** | `database.get_uncomfortable_minutes_today` `database.py:8049-8075` | The same table is already read as time-in-state. |
| Periodic in-memory aggregate from a bounded read, no writes | **REUSE (pattern)** | `domain_coordinators/routine_forecaster.py:1-60` (refresh interval, bounded rows, unsub kept on a dedicated attribute, cleaned up in shutdown) | Copy its lifecycle shape. Not its data (it reads `house_state_log`). |
| Per-room occupied baseline by hour | **NOT REUSED (adjacent)** | `memory_baseline.py` Welford fold into `metric_baselines`; allowlist of 5 rooms (`const.py:5159`); 3-hour bins keyed by **house-state family** (`memory_facade.build_metric_key` / `utc_to_local_hour_bin` `memory_facade.py:290-328`); capped at 2000 samples (`const.py:5168`) | Wrong for this job in three ways: 5 rooms only; conditioning on house state partly answers the question (a SLEEP family cell already "expects" night quiet); cap 2000 at 5 min ≈ 7 days of memory. Kept as is. Its `unusual_today` attribute on `binary_sensor.<room>_occupied` (`binary_sensor.py:784-795`) is a separate surface and stays. |
| Old anomaly model | **SUPERSEDED for this sensor** | `bayesian_predictor.get_anomaly_score` `bayesian_predictor.py:832-880` (threshold literal 0.10 at :866) | Triage in §9. |
| Shared Bayesian occupancy probability | **NOT TOUCHED** | `predict_room_occupancy` `bayesian_predictor.py:466`; live readers `energy_forecast.py:445,499`, `__init__.py:3251`, `sensor.py:15227,15244` | Live consumers outside this card. Non-goal. |
| Arrival-count helpers | **NOT REUSED** | `database.get_peak_occupancy_hour` `database.py:3572`, `get_next_occupancy_prediction` `:3609` (count `occupancy_events` entries, arrival-shaped) | Same flaw as the old model. Out of scope. |
| Sensor entity | **REUSE (rewrite internals)** | `binary_sensor.OccupancyAnomalyBinarySensor` `binary_sensor.py:3358-3513`, created at `binary_sensor.py:228`, unique id suffix `occupancy_anomaly` | Keep the class, the unique_id and the disabled-by-default flag, so the 9 operator-enabled entities stay enabled. |
| Evaluation hook | **REUSE** | `UniversalRoomEntity(CoordinatorEntity)` `entity.py:19`; room coordinator `update_interval` 30 s + jitter (`coordinator.py:685`) | Evaluate in `_handle_coordinator_update`, which is pure in-memory. The current `async_update` is never called (D0 §2). |
| Occupied-since | **REUSE** | `coordinator.get_became_occupied_time()` `coordinator.py:5832`; field `_became_occupied_time` `coordinator.py:320`, set `:3974` | Feeds `occupied_for_s` and the debounce. |
| Which signal made the room occupied | **REUSE (display only)** | `STATE_OCCUPANCY_SOURCE` `const.py:1913`; `STATE_RADAR_SOLE_TICK` `const.py:1918`; `STATE_BLE_PERSONS` `const.py:1912` | All on `coordinator.data`. |
| House state for guest suppression | **REUSE** | `coordinator_manager.house_state` property `domain_coordinators/manager.py:325`, already read by the sensor `binary_sensor.py:3415-3420` | |
| Observation mode gate | **REUSE** | `coordinator._observation_mode`, already checked `binary_sensor.py:3427` (Bug Class #23) | Gates the `anomaly_log` write. |
| Durable record | **REUSE (new type value)** | `_store_bayesian_anomaly_event` `binary_sensor.py:3482-3513` → `db.save_anomaly_event` | New `type="occupancy.dwell_anomaly"`; see D3. |
| Signal | **REUSE (KEEP + DOCUMENT)** | `SIGNAL_OCCUPANCY_ANOMALY` `domain_coordinators/signals.py:40`; zero consumers (D0 §2) | Still sent on the rising edge; payload documented in D3. |
| "Who is usually here" | **REUSE** | `person_visits(person_id, room_id, entry_time, exit_time, duration_seconds)` `database.py:961-975`, index `idx_person_visits_room_time` | BLE-derived and sparse (D0 §3: 111 of 1004 Living Room visits inside an occupied episode). Display only. |
| New `RoomDwellModel` (aggregate + lookup) | **BUILD** | none found after grep of `const.py`, `config_flow.py`, entity platforms, `domain_coordinators/*`, `memory_*.py`, `bayesian_predictor.py` for `dwell`, `occupancy_share`, `hour_of_week`, `occupied_rate` | Small pure class plus one DAO read. |
| New DAO `get_room_occupied_share_by_hour` | **BUILD** | no existing grouped read of `environmental_data.occupied` | Read-only, via `_db_read()`. |
| Dead constant `STATE_OCCUPANCY_PATTERN` | out of scope | `const.py:1969`, no readers | Noted for the supersession audit, not touched. |

Greps run (repo root `custom_components/universal_room_automation/`):
```
grep -n "class OccupancyAnomalyBinarySensor" -A 140 binary_sensor.py
grep -rn "get_anomaly_score\|predict_room_occupancy\|SIGNAL_OCCUPANCY_ANOMALY\|OccupancyAnomaly" . ../../quality/tests
grep -n "CREATE TABLE IF NOT EXISTS" database.py
grep -rn "log_occupancy_event\|log_environmental_data\|get_occupancy_percentage\|get_peak_occupancy_hour\|get_occupancy_time_today" .
grep -n "RETENTION" const.py
grep -rln "metric_baselines" .
grep -n "MEMORY_BASELINE" const.py
grep -n "STATE_OCCUPANCY_SOURCE\|STATE_RADAR_SOLE_TICK\|STATE_BLE_PERSONS\|became_occupied_time" const.py coordinator.py
grep -rn "STATE_OCCUPANCY_PATTERN\|STATE_OCCUPANCY_CONFIDENCE" .
```

Side finds (not this card; record only): `get_occupancy_time_today` is called with `room_name` (`sensor.py:16107`) while `occupancy_events` is keyed by `entry_id` (`coordinator.py:5444`), and it counts `event_type='occupied'` when the writer uses `entry`/`exit`. `get_occupancy_percentage` mixes a local `dt_util.now()` cutoff with UTC timestamps. Both are candidates for a card at the plan review.

### 1.2 Prior-art scan: plans

- `PLANNING_v4.0.0_B2_PREDICTION_SENSORS.md` (D5): the original anomaly design. Intent was "walk into a typically-empty room at night and it fires". Kept as the intent; replaced the model.
- `PLANNING_routine_awareness_next_state_forecaster.md`: source of the in-memory refresh pattern.
- `PLANNING_v4.6.1_anomaly_reconciliation_then_v4.6.2_routine_awareness.md` and `PLANNING_v4.6.3_anomaly_migration_and_smoke_test_infra.md`: the `anomaly_log` canary. Its payload test is in `quality/tests/test_v461_canary_migrations.py:267`.
- `MVP_hierarchical_memory.md` / `PLANNING_memory_writers.md` / `AUDIT_memory_handbuild_study_a.md`: the `memory_baseline` writer and its allowlist (adjacent, see §1.1).
- `regime_detector.py` header (v4.6.2 D4): per-person routine shift by Jensen-Shannon divergence over room visits. A different question (has the routine changed this fortnight), feeding ROUTINE-CARE-DASHBOARD-1.
- Card ROUTINE-CARE-DASHBOARD-1 (`kanban.data.yaml:9204`): "unusual for this person", dashboard-only, no notifications. Per-person and routine-shift; this card is per-room and right-now. They do not overlap; both stay.

### 1.3 Memory bodies

- `feedback_measure_before_build`: the D0 backtest is a gate, not a runtime feature.
- `feedback_marginal_benefit_pushback`: see §2.
- `project_optimizer_db_write_flood_incident_2026_06_09`: the model is read-only at refresh time; one `anomaly_log` row per rising edge only.
- `reference_sensor_fleet_classes`, `reference_presence_state_of_play`: read.
- `feedback_parsimonious_room_config`: no new options-flow fields (§6).

### 1.4 Config-first

No setting fixes this. The old sensor cannot evaluate (no polling), and its model is wrong (D0 §3). There is no knob for either.

---

## 2. Marginal-benefit check (done before the spec)

- **Simplest version that captures most of the value:** room-level share by local hour × weekday/weekend from the existing 5-minute samples, a threshold, a debounce and the guest gate. That is this plan.
- **Considered and parked:**
  - Per-person dwell model ("Oji in Study A is normal, Jaya in Study A at 03:00 is not"). It needs identity per occupied tick, and BLE `person_visits` is too sparse (D0 §3). Revival trigger: BLE room attach rate inside occupied episodes above 60% for a week.
  - Hour-of-week (168 cells) instead of hour × day type (48 cells). It cuts the support per cell by 3.5×. D0 reports both. Revival trigger: D0 shows the 48-cell model fires on a weekday-specific routine (for example a weekly cleaner) that the 168-cell model would learn.
  - Conditioning on house state. It partly answers the question (SLEEP already means a quiet room), and it is what `memory_baseline` does.
- **Ingredient risk:** no synthetic time, no new writer to a shared primitive, no actuation, no new consumer. The new pieces are one grouped read (DB contention, bounded in D1) and one entity-callback change. Low.

---

## 3. Falsifiable invariant

> **I1.** In any reachable state, `binary_sensor.<room>_occupancy_anomaly` is `on` only when ALL of these hold at that instant: (a) the room coordinator's `STATE_OCCUPIED` is true; (b) the room's learned share for the current local (hour, day type) is strictly below `OCC_ANOMALY_SHARE_THRESHOLD`; (c) that cell's sample count is at least `OCC_ANOMALY_MIN_CELL_SAMPLES`; (d) the room has been continuously occupied for at least `OCC_ANOMALY_DEBOUNCE_S`; (e) house state is not GUEST; (f) the model has completed at least one successful refresh. It turns `off` on the first coordinator update where any of these fails (in particular, the first vacant tick).

> **I2.** The cycle sends no notification on any path: no `async_notify`, no NM call, no persistent notification, from this entity or the model.

> **I3.** Writes are bounded: at most one `anomaly_log` row per rising edge per room, never more than one per room per `OCC_ANOMALY_LOG_COOLDOWN_S`, and none in observation mode. The model refresh writes nothing.

What breaking them looks like: the sensor `on` while the room is vacant, or after a restart before the first refresh; `on` in a cell with 3 samples; any NM row from `coordinator_id` `bayesian_predictor` or `occupancy_anomaly`; two `occupancy.dwell_anomaly` rows for one room within the cooldown.

---

## 4. Producer and consumer checks

### 4.1 Value: learned share `share(room, hour, day_type)`

**Producer.**
- **Arithmetic:** `share = sum(occupied) / count(rows)` over `environmental_data` rows for `room_id = entry_id` in the last `OCC_ANOMALY_WINDOW_DAYS` days, grouped by local hour (0-23) and day type (weekday Mon-Fri / weekend Sat-Sun), excluding today (no self-training on the episode being judged). The SQL groups by `room_id, substr(timestamp, 1, 13)` (UTC hour), which keeps the database work to one indexed range scan. Python converts each UTC hour bucket to local hour and day type with HA's time zone, so DST is handled per bucket, not with a fixed offset.
- **Cell support:** `n = count(rows)`. A full weekday cell over 56 days has about 40 × 12 = 480 samples. Missing rows (HA down, coordinator not ticking) lower `n` and do not bias the share.
- **Dependencies and health:**
  - The writer at `coordinator.py:5461` runs inside `_async_update_data` on every room. Its health is **UNVERIFIED live**: the Samba-mounted DB could not be opened read-only from this workstation (WAL access error 14). D0 step 1 measures rows per room per day before anything else.
  - Known first-sample bias: `occupied` is `None` before the first tick and `log_environmental_data` stores it as NULL. NULL rows are excluded from both sums.
  - Retention 365 days covers any window up to 365.
  - Room identity is `entry_id`, so a room rename (ZONE-ROOM-NAME-DRIFT-1) does not split its history.
- **External ground truth:** D0 compares the learned share against `person_visits` dwell for the four residents' main rooms (for example Study A should show a weekday-daytime share well above the threshold; the old model gave 0.004).
- **One derivation only.** The old Bayesian number is no longer read by this sensor.

**Consumers.**
| Reader | file:line (planned) | Trust or display |
|---|---|---|
| `OccupancyAnomalyBinarySensor._handle_coordinator_update` (state) | `binary_sensor.py` ~3358 | Decides the sensor's on/off. A diagnostic, not a control input. |
| Same entity, attributes `expected_share`, `cell_samples` | same | Display |
| Nothing else. `predict_room_occupancy` and its four consumers are untouched. | | |

### 4.2 Value: sensor state `occupancy_anomaly`

**Producer:** I1 above. **Consumers:** none in code (grep shows zero readers of the entity or the signal). The operator reads it on the dashboard. The `anomaly_log` row is read by the anomaly views (`coordinator_diagnostics.py`, the AnomalyDetector tables). The plan review must re-grep `anomaly_log` readers for any filter that would choke on a new `type` string.

### 4.3 Value: `usual_people` (display)

**Producer:** `person_visits` closed visits in the same window, by `room_id` (the display room name; D0 §1 confirms belief `room_id` matches `entry.data["room_name"]`; the plan review must verify `person_visits.room_id` uses the same string). Sum `duration_seconds` that overlap the current (hour, day type) cell, per person; report the top 3 with their share of the cell's occupied minutes. **Consumer:** attribute only. Sparse by design; the attribute says `source: ble_visits` so nobody mistakes it for ground truth.

---

## 5. Emission and decision sites (all of them)

Every site where the anomaly state, alert or record is produced today (from the greps in §1.1):

| # | Site | Today | After |
|---|---|---|---|
| S1 | `binary_sensor.py:3396` `async_update` | dead (never called) | removed; logic moves to S2 |
| S2 | `_handle_coordinator_update` (new override on this entity) | n/a | evaluates I1, then `async_write_ha_state()` |
| S3 | `binary_sensor.py:3447` `async_dispatcher_send(SIGNAL_OCCUPANCY_ANOMALY)` | in `_fire_anomaly_alert` | kept, on rising edge, new payload |
| S4 | `binary_sensor.py:3460` `_store_bayesian_anomaly_event` | old payload | renamed `_store_dwell_anomaly_event`, new type and payload, cooldown-gated |
| S5 | `binary_sensor.py:3467-3480` `nm.async_notify` | dead path | **deleted** (operator ruling; I2) |
| S6 | `bayesian_predictor.py:832` `get_anomaly_score` | only reader is S1 | no production reader; §9 |
| S7 | `binary_sensor.py:228` entity construction | per room | unchanged |

The rising-edge actions (S3, S4) run from S2 via `hass.async_create_task` tracked on the entity and cancelled in `async_will_remove_from_hass` (Bug Class #19). They must not block the callback.

---

## 6. Knobs

All are rung 1 (module constants in `const.py`), reviewed code changes only. Reason: this is a diagnostic with no consumer, and the parsimony rule says not to expose its timing on the options flow. Every value except the window is set from the D0 result before build; the numbers below are starting points for D0, not commitments.

| Knob | Start value | Why | Kill / edge semantics |
|---|---|---|---|
| `OCC_ANOMALY_DWELL_ENABLED` | `True` | Kill switch for the whole new path | `False`: the sensor stays `off` with attribute `status: disabled`; no model refresh, no DB read |
| `OCC_ANOMALY_WINDOW_DAYS` | 56 | 8 weeks: about 8 weekend days per weekend cell, enough to learn without dragging last season along | must be ≤ `RETENTION_ROOM_HISTORY_DAYS`; clamped |
| `OCC_ANOMALY_SHARE_THRESHOLD` | 0.02 (D0 sweeps 0.01 / 0.02 / 0.05) | "this room is occupied less than 2% of the time at this hour" | `0.0` disables firing (nothing is strictly below 0) |
| `OCC_ANOMALY_MIN_CELL_SAMPLES` | 200 | about 40% of a full weekday cell; protects new rooms and outage-heavy weeks | below it the sensor is `off` with `learning_status: learning` |
| `OCC_ANOMALY_DEBOUNCE_S` | 900 (D0 sweeps 0 / 300 / 900 / 1800) | a pass-through or a short visit is not an anomaly | `0` = fire on the first qualifying tick |
| `OCC_ANOMALY_REFRESH_LOCAL_TIME` | `"03:40"` | one nightly read off the busy hours | also runs once 120 s after setup |
| `OCC_ANOMALY_SETUP_REFRESH_DELAY_S` | 120 | keeps the read out of the boot storm | |
| `OCC_ANOMALY_LOG_COOLDOWN_S` | 1800 (was the literal at `binary_sensor.py:3442`) | caps `anomaly_log` rows per room | `0` = one row per rising edge |
| `OCC_ANOMALY_STARTUP_GRACE_S` | 300 (was the literal at `binary_sensor.py:3437`) | no record in the first 5 min after setup | sensor state still evaluates; only the record is held |

Promote to rung 3 (Number entity) only if the operator later asks to tune the threshold by observation.

---

## 7. Deliverables

### D0: Backtest gate (read-only probe, runs first; no code in the integration)

A one-shot script (`ssh ha "python3 -" < script.py`, read-only on the URA DB and the HA recorder; saved in the scratchpad, results in a new `docs/planning/AUDIT_occupancy_anomaly_dwell_backtest.md`).

Steps:
1. **Producer health.** Rows per room per day in `environmental_data` for the last 70 days; share of NULL `occupied`; rooms with fewer than 200 rows/day flagged. If the writer is broken (most rooms under 200/day), STOP: the plan goes back for a different producer (recorder history of `binary_sensor.<room>_occupied`).
2. **No-hindsight replay.** For each day D in the last 14 days, build the model from `[D − 56, D − 1]` only. Replay D with the recorder's `binary_sensor.<room>_occupied` history and house-state history, stepping every 60 s, applying I1 exactly (threshold, min samples, debounce, guest).
3. **Sweep** threshold {0.01, 0.02, 0.05} × debounce {0, 300, 900, 1800} s, both 48-cell and 168-cell models. Report fires per room per day for all 46 rooms, and for the 9 currently enabled rooms.
4. **Ground-truth check of the model.** For Study A, Master Bedroom, Jaya Bedroom and Living Room, print the learned weekday and weekend share by hour next to the residents' `person_visits` dwell for the same cells. Study A weekday 09:00-17:00 must be above the threshold.
5. **Fire sample.** For the chosen setting, list up to 20 fires (all if fewer), each with room, local time, duration, house state, occupancy source, radar-sole flag, fan state for the room, BLE persons in the room, and any resident `person_visits` overlap. Judge each as *plausible-unusual* (nobody whose usual room this is, odd hour, guest-like), *normal use* (a resident doing something they do), or *phantom* (a known hold: fan on and radar-sole, or Study A ZK hold).

**Go / no-go (all must hold for the chosen setting):**
- **G1 rate:** median fires per day across all 46 rooms ≤ 1.0, and no single room above 4 fires in the 14 days.
- **G2 quality:** in the fire sample, *normal use* is at most 1/3 of fires. Phantom fires count as acceptable (surfacing a phantom hold is useful information), but are reported separately.
- **G3 discrimination:** zero fires during Oji's weekday-daytime Study A visits. This is the case that broke the old model (old model: 29 fires/14 d in Study A). If G3 fails, the model is not measuring dwell and the plan is wrong.
- **G4 learning:** at least 40 of 46 rooms have every cell at or above `OCC_ANOMALY_MIN_CELL_SAMPLES` (otherwise the threshold is mostly "learning" and the sensor is inert).

If G1 or G2 fails at every setting, the card goes back to the operator with the numbers and option A (retire the entity) as the recommendation. If they pass, the chosen threshold and debounce are written into §6 before build.

**Acceptance criteria**
- **Verify:** the audit doc exists, with the sweep table, the four-room share-vs-visits table and the judged fire sample.
- **Verify:** the replay trains only on days before each replayed day (the script asserts `max(train_ts) < day_start`).
- **Verify:** a discriminating check is in the report. Under a working dwell model Study A weekday-daytime share is > 0.2. Under an arrival-shaped model it would be < 0.05, as the old one was (0.004).
- **Live:** none (read-only probe).

### D1: `RoomDwellModel` and its DAO

- New module `custom_components/universal_room_automation/room_dwell_model.py`: pure class, no HA imports in the lookup path. `RoomDwellModel.refresh(rows, tz)` builds `{entry_id: {(hour, day_type): (share, n)}}`; `lookup(entry_id, local_dt) -> (share | None, n)`; `status -> "never_refreshed" | "ok" | "refresh_failed"`; `last_refresh_utc`. A failed refresh keeps the previous model (coherent-old).
- New DAO `database.get_room_occupied_share_by_hour(since_utc, until_utc) -> list[(room_id, utc_hour_str, occupied_sum, n)]`: one `SELECT room_id, substr(timestamp,1,13), SUM(occupied), COUNT(occupied) FROM environmental_data WHERE timestamp >= ? AND timestamp < ? AND occupied IS NOT NULL GROUP BY 1, 2`, via `_db_read()`. Expected size about 46 × 24 × 56 ≈ 62k rows. The plan review must measure the query time once on a copy of the live DB; if over 5 s, split by room.
- Owner: one instance in `hass.data[DOMAIN]["room_dwell_model"]`, created in `__init__.py` setup of the integration-level entry, refreshed by `async_track_time_change` at `OCC_ANOMALY_REFRESH_LOCAL_TIME` plus once after `OCC_ANOMALY_SETUP_REFRESH_DELAY_S`. Unsub stored on a dedicated attribute and called on unload (Bug Classes #19, #50).
- `usual_people` pre-computed in the same refresh from one `person_visits` read over the same window.

**Acceptance criteria**
- **Verify:** a fixture with 56 days of synthetic rows (room R occupied weekdays 09-17 only) gives share ≈ 1.0 at weekday 10:00 and 0.0 at weekend 10:00 and weekday 03:00.
- **Verify:** DST: rows stamped across the November fall-back map to the right local hour (two 01:00 buckets both land in local hour 1).
- **Verify:** a refresh that raises keeps the old model and sets `status=refresh_failed`.
- **Test:** `test_room_dwell_model.py::test_share_by_local_hour_daytype`, `::test_dst_fallback_buckets`, `::test_refresh_failure_keeps_previous`, `::test_null_occupied_excluded`, `::test_today_excluded_from_training`.
- **Test:** `test_room_dwell_model.py::test_dao_against_production_schema`, which builds the table from `database.py`'s own DDL (not hand-copied) and runs the real DAO.
- **Live:** `sensor.ura_*` not added; instead, the anomaly entity's attribute `model_status: ok` and `model_refreshed_at` within 24 h on at least one enabled room.

### D2: Sensor rewrite

- `OccupancyAnomalyBinarySensor`: delete `async_update`; add `_handle_coordinator_update` that evaluates I1 from `coordinator.data`, `coordinator.get_became_occupied_time()`, the model lookup and `manager.house_state`, then writes state.
- Debounce reads `occupied_for_s = now − became_occupied_time`. If `became_occupied_time` is `None` while occupied, treat it as just occupied (no fire until the debounce runs from this entity's first occupied tick).
- Attributes (all always present; `None` when not applicable):
  - `expected_share` (this cell), `threshold`, `cell_samples`, `cell` (`"weekday 03:00"`), `usual_hours` (the hours where the share is above the threshold, as text, e.g. `"weekdays 08-18, weekends 10-14"`).
  - `occupied`, `occupied_since`, `occupied_for_min`, `debounce_remaining_s`.
  - `occupancy_source` (from `STATE_OCCUPANCY_SOURCE`, labelled as a list name), `radar_sole` (from `STATE_RADAR_SOLE_TICK`), `ble_persons` (from `STATE_BLE_PERSONS`).
  - `usual_people` (top 3 with share, `source: ble_visits`).
  - `learning_status` (`ok` / `learning` / `no_model` / `disabled`), `model_status`, `model_refreshed_at`, `model_window_days`.
  - `suppressed_reason` (`guest_mode`, `debouncing`, `learning`, or `None`), `last_anomaly_at`.
- Mark the churny attributes (`occupied_for_min`, `debounce_remaining_s`) unrecorded (`_unrecorded_attributes`), following HOUSE-STATE-SENSOR-ATTR-CHURN-1, so the 9 enabled entities do not add recorder churn.
- Keep the class name, unique_id suffix, `PROBLEM` device class, diagnostic category and disabled-by-default.

**Acceptance criteria**
- **Verify (I1, each clause negated alone):** occupied + low share + enough samples + debounced + not guest → `on`; flip each condition alone → `off`. Six tests, one per clause.
- **Verify:** the first vacant coordinator update after an `on` turns it `off` (discharge).
- **Verify:** before the first model refresh, the sensor is `off` with `learning_status: no_model`.
- **Verify (discriminating):** a room with share 0.6 at the current cell and occupied for 2 h stays `off`. Under the old model wired as-is it would be `on` (old score 0.004 for Study A), so this test fails if anyone routes back to `get_anomaly_score`.
- **Test:** `test_occupancy_anomaly_dwell.py::test_fires_when_all_clauses_hold`, `::test_clause_a_vacant_off` … `::test_clause_f_no_model_off`, `::test_discharges_on_vacant_tick`, `::test_usual_room_never_fires`, `::test_evaluates_on_coordinator_update` (drives the real `CoordinatorEntity` callback, not a direct method call; the defect was that nothing called the method).
- **Live:** `binary_sensor.study_a_occupancy_anomaly` attributes show `expected_share` > threshold during a weekday daytime with Study A occupied, and `last_changed` moves within 24 h on at least one enabled room OR every enabled room shows `suppressed_reason`/`learning_status` that explains `off`. Its state is no longer frozen: the attribute `occupied` matches `binary_sensor.study_a_occupied` at read time.

### D3: Remove the alert, keep the record and the signal

- Delete the `nm.async_notify` block (S5).
- On the rising edge (after the startup grace, outside observation mode, outside `OCC_ANOMALY_LOG_COOLDOWN_S`): send `SIGNAL_OCCUPANCY_ANOMALY` with payload `{room, entry_id, expected_share, threshold, cell, occupied_since, occupancy_source, radar_sole}`, and write one `anomaly_log` row: `coordinator="occupancy"`, `type="occupancy.dwell_anomaly"`, severity INFO, `anomaly_type=POINT_IN_TIME`, payload as the signal plus `cell_samples` and `ble_persons`.
- Update the canary test `test_v461_canary_migrations.py:267` and `test_nm_notify_signature_sites.py:14,120` (which name this NM site) to the new shape. Removing the NM site from the signature-sites test is expected, not a regression.

**Acceptance criteria**
- **Verify (I2):** grep test: `binary_sensor.py`'s anomaly class contains no `async_notify` / `notification_manager`; a behavioural test fires a rising edge with a mock NM in `hass.data` and asserts zero calls.
- **Verify (I3):** two rising edges 10 min apart produce one row; in observation mode, zero rows; the signal is still sent in both cases. (Decide at plan review whether the signal also respects observation mode; today it does not.)
- **Test:** `test_occupancy_anomaly_dwell.py::test_no_notification_on_rising_edge`, `::test_anomaly_log_row_shape`, `::test_log_cooldown`, `::test_observation_mode_no_row`.
- **Live:** after the first `on`, one `anomaly_log` row with `type='occupancy.dwell_anomaly'` and non-NULL `expected_share` in its payload (not sentinels; Tier 2-DB Review D rule). `notification_log` has no row from this source.

### D4: Docs

- State-of-Play presence doc: one paragraph in §1 consumer table and §9 (new sensor semantics, branch, not deployed), same commit.
- `docs/readmes/README_v<version>.md` with the Live table (written at deploy).

---

## 8. Non-goals

- No notification, alert, NM, announcement or dashboard tile in this cycle.
- No change to `predict_room_occupancy`, the Bayesian beliefs, `room_transitions`, or the energy/forecast consumers of the Bayesian model.
- No change to room occupancy, phantom-hold handling or fan rejection. A room regularly held by a phantom learns that hold as usual; a phantom that starts at a new hour shows as an anomaly. Both are accepted and surfaced, not fixed here.
- No per-person model, no hour-of-week model unless D0 picks it, no house-state conditioning (§2).
- No zone- or house-level anomaly.
- No options-flow fields and no Number entities (§6).
- No new table, no new writer, no migration.
- Not fixing `get_occupancy_time_today` / `get_occupancy_percentage` (§1.1 side finds; card them).
- Not deleting `get_anomaly_score` in this cycle (§9).

---

## 9. Supersession triage of the old Bayesian anomaly path

| Item | file:line | Bucket | Reason |
|---|---|---|---|
| `OccupancyAnomalyBinarySensor.async_update` | `binary_sensor.py:3396` | DELETE (in D2) | Never called; replaced by the callback |
| NM block in `_fire_anomaly_alert` | `binary_sensor.py:3467-3480` | DELETE (in D3) | Operator ruling: no alert |
| `_store_bayesian_anomaly_event` | `binary_sensor.py:3482` | KEEP + REWIRE | Renamed, new type/payload |
| `SIGNAL_OCCUPANCY_ANOMALY` | `signals.py:40` | KEEP + DOCUMENT | Zero consumers today; cheap; operator asked to keep it |
| `BayesianPredictor.get_anomaly_score` | `bayesian_predictor.py:832-880` | KEEP + DOCUMENT now → DELETE candidate after live validation | No production reader after D2. It is a footgun (arrival model used as an anomaly score), so it qualifies for DELETE, but per the supersession rule deletion waits until the new sensor is live-validated. Add a docstring line "retired for the occupancy-anomaly sensor; superseded by room_dwell_model". Card the delete. Its tests in `test_bayesian_b2_prediction_sensors.py` (classes around :384-:496, :736-:800, :1014, :1085) go with it. |
| `predict_room_occupancy`, `predict_room_occupancy_at_time` | `bayesian_predictor.py:466, 814` | Not a triage subject (live consumers) | See the predictions audit (pending) for whether the same arrival bias hurts the energy forecast and the forecast sensors. |
| `LearningStatus` ACTIVE ≥ 50 | `bayesian_predictor.py:645-652` | Not touched | D0 showed it is vacuous for anomaly use; other readers may rely on it |

**Predictions audit (landed 2026-10-21, `AUDIT_predictions_room_zone_house_2026_10_21.md`).** It confirms the root cause independently and widens it:
- The same arrival-count model feeds `sensor.<person>_likely_next_room`, the per-room `bayesian_occupancy_forecast` / `_pattern` sensors and this anomaly sensor ("shared root cause 1", audit line 97). Backtested, the room occupancy forecast has no skill over a constant: AUC 0.605, Brier 0.0854 against 0.0847 for always-the-base-rate (14 d, 3,127 samples). The "94.4% hit rate" headline is the empty-room base rate.
- The audit lists all those as display-only. It did not enumerate the energy-forecast use of `predict_room_occupancy` (`energy_forecast.py:445,499`); this plan does not either. That stays a non-goal here.
- Its suggested card 3 ("dwell-based occupancy") is the same producer as D1. **Decision for this plan:** build `RoomDwellModel` as a general room-level component (no anomaly-specific logic inside it), so the forecast sensors can switch to it in a later card without a rebuild. Switching them is NOT in this cycle; card it as a sibling (adjacent to the audit's suggested card 3) with the D0 backtest as its evidence.
  - **Update 2026-10-21:** the forecast switch was built as PREDICT-MODEL-DWELL-MIGRATION-1 (`docs/planning/PLANNING_predict_dwell_migration.md`, branch `feature/predict-dwell-migration`): both forecast sensors read `RoomDwellModel` (D1 added `trained_until_utc`, `forecast`, `peak_cell`, `top_cells`), with no change to the anomaly path.
- The audit's "no skill baseline anywhere" point applies here: D0 G3 (Study A weekday daytime) and the share-vs-visits table are this plan's skill checks.

---

## 10. Tier

**Tier 2-DB (three framing-disjoint reviews + live validation).** Triggers: a new DAO in `database.py` and a changed persisted payload shape (`anomaly_log` type and payload). It is not Tier 3: no actuation, no shared primitive, no cost or safety path, and nothing consumes the value. One adversarial plan review before build (Tier 2 rule).

Suggested review framings: A = model arithmetic and edge cases (DST, NULLs, empty cells, rename, new room); B = lifecycle and DB (refresh scheduling and unload, query cost on the live DB, callback cost, restart and observation mode); C = test authority (each I1 clause mutation-anchored, the DAO test on production DDL, the "evaluates on coordinator update" test drives the real callback).

---

## 11. Open questions for the operator / plan review

1. **Night in your own bedroom vs. anywhere else at night.** With a room-level model, Ziri up at 03:00 in the kitchen will turn the Kitchen sensor on if that is rare. That is the intended behaviour ("routine change"). Confirm.
2. **Signal in observation mode.** Today the signal is sent even in observation mode; the record is not. Keep that split?
3. **Which rooms to enable.** The 9 enabled entities stay enabled. Enable more after D0, or leave it to you?
4. **Shared producer.** OK to card "switch the occupancy forecast sensors to `RoomDwellModel`" as a sibling once this ships (§9)?
5. **Side finds.** Card the `get_occupancy_time_today` key/event-type mismatch and the `get_occupancy_percentage` time-zone mix?
