# PLANNING: Move room forecasts onto the dwell model, next-room onto the current room, and score dwell hourly

**Card:** PREDICT-MODEL-DWELL-MIGRATION-1 (thread: presence). Siblings read: PREDICT-SCORER-BASELINE-SKILL-1 (Tier 1, separate), PREDICT-PATTERN-DETECTED-ORPHANS-1 (parked, stays parked, see §8).
**Depends on:** BAYES-OCCUPANCY-ANOMALY-NEVER-EVALUATES-1, shipped v5.103.83 (`room_dwell_model.py`, live-validated `a0ce0b7df`).
**Evidence:** `AUDIT_predictions_room_zone_house_2026_10_21.md` (no prediction is both useful and correct; arrival-not-dwell is the root cause), plus the probe in §2 of this plan (run 2026-10-21, read-only).
**Also feeds:** OC vision §3b (`VISION_optimization_coordinator_self_fixing_house.md:157-160`): the `dwell_share` prediction-vs-actual record.

## In one paragraph

Three changes and one fix. (1) The per-room `bayesian_occupancy_forecast` and `bayesian_occupancy_pattern` sensors read `RoomDwellModel` instead of the Bayesian arrival model. Their `+1h` / `+4h` values blend the usual share for the target hour with the room's occupied fraction over the last hour, because the probe shows that blend beats both inputs. (2) `sensor.<person>_likely_next_room` uses the existing `PatternLearner.predict_next_room(person, current_room)` (a first-order chain from the room the person is in now) as its primary source. That code already exists and today runs only as a fallback. The probe shows it beats the always-the-usual-room baseline for every resident, while the current Bayesian source does not. (3) A new hourly producer writes one `prediction_results` row per room per hour with `prediction_type='dwell_share'`: the expected share frozen at the start of the hour, against the occupied fraction actually measured. (4) The prune of `prediction_results` stops ignoring every type except `bayesian_occupancy`, so the new rows (and the 177k unpruned `next_room` rows) age out. (5, added at plan review) The Optimization next-room accuracy finding, which D4 would otherwise flip near its fixed 35% floor, compares against baseline skill instead (D7, operator decision §13 Q5). Nothing new actuates, and the energy forecast's dormant read of the Bayesian model is left alone (operator decision §13).

---

## 1. Institutional context verified

**Read completely first** (presence rule): `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (all 728 lines) and `docs/architecture/SENSOR_FLEET_CLASSES.md` (all 50 lines). Nothing in the State-of-Play §10 corrections ledger is re-asserted. What applies here:
- Room `STATE_OCCUPIED` includes known phantom holds (Study A ZK hold, the Jaya LD2410 fan loop, MS600-only rooms; §6, §9). The dwell model learns from that same signal, and the `dwell_share` actual is measured from it, so a phantom hold is "usual" and "accurate" here. That is accepted (as in the anomaly plan §8): these predictions describe the room-occupancy signal, not ground-truth bodies.
- §1 consumer table: `environmental_data.occupied` → room dwell model, display only. This cycle adds a second display consumer (forecast sensors) and one write (the `dwell_share` row). §1 and §9 are updated in the same commit (D6).
- Sensor classes are not touched; nothing here classifies a sensor.
- The HVAC state-of-play and the identity manual were not needed: no HVAC, identity, camera or census value is read or changed. The HVAC "pre-arrival" path does not read any of these predictions (audit row 4, re-confirmed by grep below).

### 1.1 Prior-art scan: code (REUSE or BUILD per piece)

| Piece | Verdict | Where (file:line) | Note |
|---|---|---|---|
| Dwell share by room × local hour × day type | **REUSE** | `RoomDwellModel.lookup` `room_dwell_model.py:219-225`; `cell_days` `:227`; `usual_hours` `:235` | Already general (no anomaly logic inside, `:13-14`). |
| Model owner, nightly + setup refresh, unload | **REUSE + EXTEND** | `RoomDwellModelRunner` `room_dwell_model.py:290-414`; created `__init__.py:4850-4853`, `entry.async_on_unload` | The hourly tick (D3) goes on this runner: same lifecycle, one more unsub attribute. |
| Training window ends at start of today | **REUSE (relied on)** | `training_window` `room_dwell_model.py:270-278` | Today is never in the model. D1 exposes the end as `trained_until_utc` so D3 can assert it. |
| Hourly occupied fraction (actual) | **REUSE** | DAO `database.get_room_occupied_share_by_hour(since_utc, until_utc)` `database.py:8129` | The same grouped read the model trains on, over one hour. Same signal, same samples, so predicted and actual are measured the same way. No new DAO. |
| Batched `prediction_results` write | **REUSE** | `database.save_prediction_results_batch(rows)` `database.py:7917-7938` (one `executemany`, one commit) | Write-flood rule: one batch per hour, never per row. |
| `prediction_results` table, no schema change | **REUSE** | DDL `database.py:1691-1707`; `person_id` column `database.py:2239-2253` | `dwell_share` is a new `prediction_type` value only. |
| Prune | **EXTEND (one filter)** | `prune_prediction_results` `database.py:7983-8020`, filter `AND prediction_type = 'bayesian_occupancy'` at `:8004`; called nightly `nightly_maintenance.py:39` (`days=30`) | Today only `bayesian_occupancy` is pruned: live `next_room` rows go back to 2026-05-13 (177,291 rows, probe P4). D5. |
| Next-room conditioned on current room | **REUSE (promote from fallback)** | `PatternLearner.predict_next_room(person_id, current_room)` `pattern_learning.py:143-254` (from→to counts over 30 days, hourly cache `:304-321`); called as the LAST fallback at `sensor.py:3455-3468` | This is the audit's "condition on current room". It already exists; it loses to the Bayesian source whenever the Bayesian cell has data, which is nearly always. |
| Current room of a person | **REUSE** | `person_coordinator.data[person]["location"]`, already read at `sensor.py:3460-3463` | Same read, same exclusions (`unknown`, `away`, `home`). |
| Next-room prediction cache + scorer | **REUSE + EXTEND** | cache write `sensor.py:3475-3505` (`hass.data[DOMAIN]["next_room_predictions"]`); scorer `transitions._score_prediction` `transitions.py:482-545` (30-min staleness gate `:509`) | D4 adds `current_room` to the cache and a from-room match gate in the scorer. |
| Forecast sensor entities | **REUSE (re-source internals)** | `BayesianOccupancyForecastSensor` `sensor.py:15199-15257`, `BayesianOccupancyPatternSensor` `sensor.py:15061-15108`, created `sensor.py:692,697` | Keep class, unique_id, disabled-by-default, so the 4 + 2 enabled entities stay enabled and keep their entity_ids. |
| Persistence input for `+1h`/`+4h` | **BUILD (tiny)** | none: no in-memory "last hour occupied fraction" exists | D3 already computes it each hour; D3 keeps the last value per room in memory and D2 reads it. No new read. |
| Bayesian occupancy accuracy writer | **NOT TOUCHED** | `__init__.py:3203-3318` (`bayesian_occupancy`, 6 × per day at bin boundaries, `room_id = room_name`) | Keeps scoring the Bayesian model, which `energy_forecast` still reads. Triage §9. |
| Energy forecast's occupancy read | **NOT TOUCHED (operator decision §13 Q1)** | `energy_forecast.py:445,499` via `predict_room_occupancy`, gated by `occupancy_enabled_fn` `energy_forecast.py:412-415,659-663` ← `switch.ura_energy_coordinator_occupancy_weighted_prediction` (`switch.py:1578-1582`, `energy.py:727,740`) | Live state **off** (read 2026-10-21 via ha-mcp), config value `False`. Dormant consumer. |
| Pattern-detected sensor | **NOT BUILT** | unique_id `<entry>_occupancy_pattern_detected`, class removed v3.20.2; `STATE_OCCUPANCY_PATTERN` `const.py:1969` unused | See §8; PREDICT-PATTERN-DETECTED-ORPHANS-1 stays parked. |
| New constants | **BUILD** | grep of `const.py` for `DWELL_SHARE`, `FORECAST_`, `PERSISTENCE`, `PREDICTION_RESULTS_RETENTION`, `NEXT_ROOM_` found none in this sense (only `OCC_ANOMALY_*` `const.py:2129-2177`) | §6. Not reusing `OCC_ANOMALY_*` for forecast semantics: same numbers today would be a coincidental equality hiding two concepts (memory `feedback_coincidental_equality_masks_concept_split`). |

Greps run (from `custom_components/universal_room_automation/` unless noted):
```
grep -rn "predict_room_occupancy\|predict_room_at_time\|prediction_results\|room_dwell_model\|dwell_share" .
grep -rn "bayesian_occupancy'\|\"bayesian_occupancy\"\|get_accuracy_stats\|prediction_type" .
grep -rn "next_room_predictions" .
grep -rn "occupancy_forecast\|predicted_occup\|expected_share\|occupied_fraction\|occupied_share" .
grep -n "_occupancy_weighted_estimate\|_remaining_occupancy_weighted_consumption\|_room_ids\|occupancy_enabled" domain_coordinators/energy_forecast.py domain_coordinators/energy.py
grep -n "occupancy_weighted" switch.py domain_coordinators/energy.py const.py config_flow.py
grep -n "OCC_ANOMALY_\|TODAY_SENSOR_REFRESH_S\|OCC_EPISODE_MAX_S" const.py
grep -n "DEFAULT_LEARNING_DAYS\|MIN_SAMPLES_" pattern_learning.py
ssh ha "grep -o '…(bayesian_occupancy_forecast|bayesian_occupancy_pattern|likely_next_room)…' /config/.storage/lovelace.ura_v8"
```

**Consumer finds from the greps (beyond the audit):**
- `sensor.<person>_likely_next_room` is on the ura_v8 dashboard (all four persons). Display.
- `regime_detector.py:385-420` (D7 accuracy drop) compares `predicted_value = actual_value` on `next_room` rows, but `predicted_value` is JSON (`transitions.py:520-532`). Live: **0 matches in 3,109 rows (7 d)**, so that check can never see a drop. Pre-existing defect, not this card (side find, §10).
- `optimization.py:3693-3760` reads `next_room` rows (display/advisory pillar); `optimization.py:3865-3876` reads `get_accuracy_stats` (`bayesian_occupancy`). Neither filter matches `dwell_share`, so the new type is invisible to them until a consumer opts in.
- **Optimization accuracy thresholds (added after plan review H1).** `const.py:4269-4285`: `OPTIMIZER_PREDICTION_ACCURACY_TOP1_FLOOR_PCT = 35.0` (`:4272`), `_BRIER_CEILING = 0.30`, `_MIN_SAMPLES = 50`, `_WINDOW_DAYS = 7`. The floor is compared at `optimization.py:3914-3926` against `_read_next_room_accuracy` (`optimization.py:3705-3795`), which pools **all persons' `next_room` rows** in the window into one top-1 rate (`json top == actual_value`). This IS a consumer whose behaviour D4 changes (§5.4, E12, D7).

### 1.2 Prior-art scan: plans

- `PLANNING_occupancy_anomaly_dwell_model.md` §9: explicitly built `RoomDwellModel` general so the forecast sensors could switch "in a later card without a rebuild"; that is this card. Its §4.1 producer check (writer health, NULL handling, DST per bucket) applies unchanged.
- `PLANNING_v4.6.0_likely_next_room_accuracy.md`: the scoring pipeline (cache, score-on-transition, Option X = immediate next transition). Its existing-state map lists the frequency fallback as live. Kept as is, plus the from-room gate.
- `PLANNING_routine_awareness_next_state_forecaster.md`: house-state forecaster (different question). Not touched.
- `VISION_optimization_coordinator_self_fixing_house.md` §3b and `AUDIT_room_memory_and_coordinator_request_apis_2026_10_21.md:70`: `dwell_share` row shape and the in-sample caveat ("must use the expected_share frozen BEFORE the hour"). D3 implements exactly that, with the check made explicit (I1).
- `PLANNING_v4.0.0_B1_BAYESIAN_CORE.md`, `PLANNING_OPTIMIZATION_COORDINATOR.md` (prediction-validation pillar): readers of the tables; unchanged.

### 1.3 Memory bodies

`feedback_measure_before_build` (probe first, §2), `feedback_marginal_benefit_pushback` (§3), `feedback_extend_existing_never_rebuild` (PatternLearner promotion instead of a new next-room model), `project_optimizer_db_write_flood_incident_2026_06_09` (one batch per hour, §7), `feedback_read_consumers_before_asserting_function` (energy switch read live, not assumed), `feedback_tier2plus_prior_art_scan`, `reference_presence_state_of_play`, `reference_sensor_fleet_classes`.

### 1.4 Config-first

No setting fixes it. The forecast sensors have no source option; the next-room source order is code (`sensor.py:3366-3468`); `prediction_results` has no producer for dwell. The only relevant knob, the energy occupancy-weighting switch, is off and stays off.

---

## 2. Measurement (done before this spec; read-only, 2026-10-21)

Script: session scratchpad `predict_dwell_probe.py`, run `ssh ha "python3 -" < …` against the URA DB in read-only mode. D0 commits a cleaned copy. Window: last 14 local days tested; each test day's dwell model is trained only on the 56 days before it (no hindsight). `environmental_data` producer health: 14,294 rows in the last day ≈ 50 rooms × 288, so the writer is healthy.

**P1. Room-hour occupancy forecast** (15,460 room-hours; actual = that hour's occupied fraction):

| Predictor | MSE (lower is better) |
|---|---|
| Global base rate | 0.0400 |
| Per-room constant | 0.0299 |
| **Dwell share of the hour's cell** | **0.0273** |

AUC for "hour mostly occupied" (fraction ≥ 0.5): 0.901.

| Horizon | cell share | persistence (last full hour's fraction) | 50/50 blend | per-room constant |
|---|---|---|---|---|
| +1 h | 0.0273 | 0.0200 | **0.0165** | 0.0299 |
| +4 h | 0.0273 | 0.0378 | **0.0240** | 0.0299 |

So the cell share alone is a modest improvement over a per-room constant (about 9%). Adding the last hour's fraction gives the real gain. **But this table used the wrong alignment** (plan review M1): persistence was hour T−h predicting T, i.e. a lag of exactly h. The runtime cannot see that. Superseded by P1-R below; the −40% figure is withdrawn.

**P1-R. Blend sweep on the runtime alignment** (re-run 2026-10-21, read-only, `predict_dwell_probe_runtime.py` in the session scratchpad, same 15,460 room-hours, same no-hindsight models). Alignment exactly as the runtime will have it: the forecast target is the cell of `now + h` (hour T); `now` is uniform within hour H = T − h; persistence is the last completed hour at `now`, i.e. H−1 when the minute ≥ `DWELL_SHARE_TICK_MINUTE` (2) and H−2 before it (weighted 58/60 and 2/60). Effective lag is h+1 hours (h+2 in the first two minutes). MSE:

| Horizon | w = 0 (cell only) | 0.25 | 0.5 | 0.75 | 1 (persistence only) |
|---|---|---|---|---|---|
| +1 h, all 14 d | 0.0273 | 0.0220 | **0.0205** | 0.0229 | 0.0290 |
| +1 h, first 7 d (selection) | 0.0280 | **0.0246** | 0.0252 | 0.0298 | 0.0383 |
| +1 h, last 7 d (held out) | 0.0265 | 0.0195 | **0.0160** | 0.0162 | 0.0201 |
| +4 h, all 14 d | 0.0273 | **0.0239** | 0.0251 | 0.0308 | 0.0410 |
| +4 h, first 7 d (selection) | 0.0280 | **0.0274** | 0.0316 | 0.0406 | 0.0546 |
| +4 h, last 7 d (held out) | 0.0265 | 0.0206 | **0.0189** | 0.0214 | 0.0280 |

Chosen: **w(+1 h) = 0.5, w(+4 h) = 0.25** (§6). Honest gains on the runtime alignment: **−25% at +1 h** (0.0205 vs 0.0273), **−12% at +4 h** (0.0239 vs 0.0273). Held-out check (L2): selecting on the first week alone picks 0.25 at both horizons; on the held-out week that choice scores 0.0195 (+1 h, −26% vs cell) and 0.0206 (+4 h, −22%). So the gain survives out of sample; the exact w is weakly identified (0.25 and 0.5 are within ~0.003 of each other in every column), which is why it is a constant and not a learned value. The two weeks differ a lot (persistence alone: 0.0383 vs 0.0201 at +1 h), so the size of the gain varies by week; the sign does not. Persistence alone still loses at +4 h, so a blend is needed.

**P2. Head-to-head on the live `bayesian_occupancy` samples** (same 2,950 room-instants, base rate 0.096):

| | AUC | Brier |
|---|---|---|
| Bayesian (live rows) | 0.603 | 0.0874 |
| Constant (base rate) | n/a | 0.0867 |
| **Dwell share** | **0.835** | **0.0693** |

The Bayesian number matches the audit (0.605). The dwell model has real skill on identical samples (Brier −20% vs constant).

**P3. Next room, top-1 / top-3 %** (train = 30 days before the test window, test = 14 days; "dedup" drops a transition when the person's next transition comes < 60 s later):

| Person | n (raw / dedup) | constant (usual room) | time-bin arrival (Bayesian-shaped) | **from current room** (PatternLearner) | current room × time bin |
|---|---|---|---|---|---|
| Oji | 6,959 / 2,527 | 19.2/37.3 · 27.9/45.7 | 17.1/38.0 · 23.5/43.6 | **34.8/56.3 · 38.3/65.7** | 33.0/56.7 · 37.6/64.3 |
| Jaya | 3,091 / 1,340 | 26.1/57.8 · 11.0/70.4 | 26.9/66.1 · 18.6/69.4 | **56.9/78.3 · 61.9/84.0** | 55.7/75.8 · 61.0/83.5 |
| Ezinne | 3,126 / 1,296 | 26.4/42.8 · 43.5/54.1 | 25.1/46.5 · 42.5/56.9 | **39.6/64.7 · 50.5/79.8** | 38.4/63.2 · 48.2/72.8 |
| Ziri | 0 transitions in 14 d | – | – | – | – |

Pooled projection for the Optimization finding (H1): the finding pools all persons. Weighting P3 raw top-1 by the live 7-day row mix (Oji 1,561, Jaya 1,410, Ezinne 138; live pooled top-1 today **15.1%**, read 2026-10-21) gives about **45%** after D4, not 34.8% (that is Oji alone). The reviewer's "sits on the floor" is too strong for the pooled rate, but the margin (~10 points) depends on the person mix and on how many rows the I4 gate drops, so H1's fix stands (§5.4).

The time-bin arrival model (what the sensor uses today) is at or below the constant. Conditioning on the current room beats the constant for every resident, raw and deduplicated. Adding the time bin on top adds nothing (slightly worse everywhere). Ziri has no transitions in the window, which explains the audit's "Ziri 0 predictions": there is nothing to score, not a pipeline fault (not traced further).

**P4. Volumes:** 47 room entries; `prediction_results`: `bayesian_occupancy` 6,195 rows (oldest 2026-09-21, pruned), `next_room` 177,291 rows (oldest **2026-05-13**, never pruned).

**Go / no-go.** Go for D2 (dwell forecast with blend), D3 (dwell_share producer) and D4 (PatternLearner primary). **No-go for a time-conditioned next-room model** (P3 last column) and for persistence-only forecasts (P1-R, w = 1 loses at both horizons). Blend weights are set from P1-R; D0 re-runs the sweep in the committed script and must reproduce P1-R.

**What D0 cannot measure (plan review H2).** The backtest scores `room_transitions` against itself, so the prediction's room is the transition's `from_room` by construction. It gives an **upper bound** on live from-room agreement (100%), not the live skip rate. The live skip rate is measured only after deploy (D4 skip counter, Live criterion).

---

## 3. Marginal-benefit check

- **Simplest version that captures most of the value:** re-point the two sensors at an existing model, swap the order of two existing next-room sources, and write one batched row per room per hour. That is this plan. No new model, table or entity.
- **Rejected on the numbers:** next-room × time bin (no gain, P3); per-person dwell forecasts (needs identity per tick; BLE `person_visits` is sparse, anomaly plan §2); a learned blend (fit per room): the fixed blend already captures the gain, and a fitted coefficient per room is config combinatorics with no measured margin. Revival trigger for the learned blend: the D3 rows show the fixed-blend `+1h` error worse than persistence alone in ≥ 1/3 of rooms over 14 days.
- **Rejected as creep:** zone- and house-level occupancy forecasts. None exists today (audit table, grep `occupancy_forecast`), and nothing would read one. Parked with trigger in §8.
- **Ingredient risk:** one new periodic writer to a shared table (bounded, batched, kill-switched); no actuation; no synthetic time; no cross-coordinator state. The energy read (the one trust-shaped consumer) is deliberately left on the old source.

---

## 4. Falsifiable invariants

> **I1 (out-of-sample).** Every `dwell_share` row for room R and local hour H has `predicted_value` equal to `RoomDwellModel.lookup(R, H)` taken from a model whose `trained_until_utc ≤ start(H)`, captured at the first producer tick inside H, and no row is written for H if that capture did not happen (restart, kill switch, no model, empty cell) or if the hour has fewer than `DWELL_SHARE_MIN_ACTUAL_SAMPLES` samples. No row's predicted value is ever computed after H has ended.

> **I2 (bounded writes).** At most one `dwell_share` row per (room, hour) and at most one `prediction_results` batch write per producer tick; zero rows while `DWELL_SHARE_PRODUCER_ENABLED` is False.

> **I3 (no trust change).** No actuation or decision path reads a value this cycle changes. `energy_forecast` keeps calling `predict_room_occupancy`; with the energy switch in either state, its output is byte-identical before and after this cycle.

> **I4 (next-room scoring is honest).** A `next_room` row is written only when the cached prediction was made from the room the transition left (`cache.current_room == transition.from_room`) or the cache predates this cycle's field (absent `current_room` → old behaviour), and when it is at most 1800 s old. **Every gated-out transition is counted visibly** (`skipped_room_mismatch`, D4), and the accuracy gain is accepted as evidence only while `skipped / (skipped + scored) ≤ NEXT_ROOM_MAX_SKIP_RATIO`. A gate that drops most rows silently would score only the easy cases and make the sensors look better for the wrong reason (plan review H2).

> **I5 (no Optimization flap from this cycle).** With the default chosen in §13 Q5, the Optimization prediction-accuracy finding's next-room clause does not change state on consecutive evaluations because the pooled top-1 moved by less than `OPTIMIZER_PREDICTION_ACCURACY_TOP1_HYSTERESIS_PCT` across a fixed floor.

How to break them: a `dwell_share` row with a timestamp in a day whose nightly refresh preceded the capture and included that day (in-sample leak, e.g. a restart-time refresh at 00:01 used to score hour 23 of the previous day); two rows for one (room, hour) after a restart inside the tick; a `dwell_share` row with sentinel values (all predicted 0.0 or all equal); an energy forecast value that changes with this branch while the switch is on; a `next_room` row whose `current_room` differs from the transition's `from_room`.

---

## 5. Producer and consumer checks

### 5.1 `expected_share(room, local hour, day type)` (existing value, new readers)
- **Producer:** `RoomDwellModel` (§1.1). `share = Σ occupied / count` over `environmental_data` for the cell, 56 days ending at the start of today. Dependencies: the 5-min writer (healthy, §2), the nightly refresh (status `ok` on the live anomaly sensors, README v5.103.83 validation), retention 365 d. Ground truth: P1/P2 above score it against the realised hourly fraction and against the Bayesian model; it has skill.
- **Consumers after this cycle:**

| Reader | file:line | Trust or display |
|---|---|---|
| Occupancy-anomaly sensor | `binary_sensor.py:3432-3530` | display (unchanged) |
| Forecast sensor state + `forecast_now` | `sensor.py:15199-15257` (D2) | display |
| Forecast `+1h`/`+4h` (blended) | same (D2) | display |
| Pattern sensor (peak cell) | `sensor.py:15061-15108` (D2) | display |
| `dwell_share.predicted_value` | D3 producer | record (OC evidence later; display-class) |

### 5.2 `actual_fraction(room, hour)` (new value)
- **Producer:** `get_room_occupied_share_by_hour(start_utc(H), end_utc(H))` → `Σ occupied / count` for the hour. Same rows the model trains on. Dependencies: same writer; samples land every ~300 s per room with jitter, so the read runs at minute `DWELL_SHARE_TICK_MINUTE` (2) of H+1 to include the last sample. A room with < 6 of 12 samples (HA down, coordinator stalled) is skipped, not scored as empty. Ground truth check (D0 step 3): the hourly fraction for 4 rooms over one day agrees with the recorder history of `binary_sensor.<room>_occupied` time-weighted over the same hours, within 0.1 per hour.
- **Consumers:** the `dwell_share.actual_value` column (record); the in-memory `last_hour_fraction[room]` used by D2's blend (display). No other reader. OC is a future reader (vision slice 1); it must read with `prediction_type = 'dwell_share'`.

### 5.3 `dwell_share` row (new record)
- **Shape:** `room_id = entry_id` (rename-stable, matches `environmental_data`; the other two types use room names, which is the mismatch the anomaly cycle had to fix), `prediction_timestamp = start of the UTC hour H as an aware ISO string with offset, e.g. "2026-10-21T15:00:00+00:00"` (M2: this is the format both existing writers use, `dt_util.utcnow().isoformat()` at `__init__.py:3231` for `bayesian_occupancy` and at `sensor.py:3502` for the `next_room` cache timestamp that `transitions.py:534` writes; the prune cutoff is the same `isoformat()`. Not the naive `"YYYY-MM-DD HH:MM:SS"` the dwell DAO uses for `environmental_data`. Side note, pre-existing and not changed here: `optimization.py:3723-3725` builds its cutoff as `"%Y-%m-%d %H:%M:%S"`; because `'T' > ' '`, every row on the cutoff date passes whatever its time, so its window is up to one day longer than 7 d. The D3 Live query uses the aware format), `prediction_type = 'dwell_share'`, `predicted_value = str(round(share, 4))`, `actual_value = str(round(fraction, 4))`, `error_value = round(share − fraction, 4)` (signed: positive = room was emptier than usual; square it for Brier), `confidence = cell sample count n` (support for the prediction), `person_id = NULL`. **L1 decision:** `confidence` holds a count for this type, not a 0-1 probability. Every reader filters by type, so nothing breaks, but a docstring on `save_prediction_results_batch` and a note in the presence state-of-play §1 row say "for `dwell_share`, `confidence` is the cell's sample count". `cell_days` was considered and rejected: the count is what a reader needs to weight rows.
- **Consumers in code today:** none. Re-grep at plan review that no reader of `prediction_results` lacks a `prediction_type` filter: today every reader filters (`sensor.py:15416,15427,15609,15619`, `regime_detector.py:392,409`, `optimization.py:3740`, `database.py:7960`). If one is found without a filter, it is a finding.

### 5.4 `likely_next_room` (re-sourced value)
- **Producer after D4:** if the person's `location` is a real room → `PatternLearner.predict_next_room` (from→to counts over 30 days, raw transitions, 1 h cache). Else the existing chain (Bayesian, then `away_typical`, unchanged). Dependencies: `room_transitions` writer (healthy: 435 rows in the last day); `person_coordinator` location (BLE; LOST/away handled by the existing exclusions). Ground truth: P3.
- **Consumers:** the entity state (ura_v8 dashboard, display); the cache → `transitions._score_prediction` → `next_room` rows → `*_next_room_accuracy` sensors (display), Optimization pillar (advisory, read-only), `regime_detector` D7 (already inert, §1.1). Nothing actuates on it.
- **Consumer-side effect to expect:** the accuracy sensors' top-1 rate rises (P3: Oji ~13 → ~35%, Jaya ~15 → ~57% raw; live 7-day rates 13.4 / 15.4%).
- **Consumer row (plan review H1): Optimization prediction-accuracy finding.**

| Reader | file:line | Aggregation | Before | Expected after D4 | Trust or display |
|---|---|---|---|---|---|
| `_evaluate_prediction_accuracy_dimension` next-room clause | `optimization.py:3914-3926`, reading `_read_next_room_accuracy` `optimization.py:3705-3795` | all persons pooled, 7 days, ≥ 50 rows, `json top == actual_value` | 15.1% pooled → issue "below 35% floor" fires every evaluation | ~45% pooled (§2 projection), Oji alone ~35% | advisory finding (no actuation), but it is an operator-facing issue list, so a flapping finding is a real defect |

The earlier claim "no threshold is tuned for the old level" was wrong: the 35% absolute floor was set when the model had no skill, and an absolute hit-rate floor is the wrong yardstick anyway (it rewards a household with one dominant room). **Default (operator decision §13 Q5):** D7 changes the clause to compare against the baseline-skill measure that PREDICT-SCORER-BASELINE-SKILL-1 adds in the same release: the finding fires when pooled top-1 skill over the always-the-usual-room baseline (same rows, same window) is ≤ `OPTIMIZER_PREDICTION_ACCURACY_MIN_SKILL_PCT` (default 0 points: no better than the constant). If the operator instead keeps an absolute floor, D7 adds hysteresis: fire below 35.0, clear only above 35.0 + `OPTIMIZER_PREDICTION_ACCURACY_TOP1_HYSTERESIS_PCT` (default 5.0).

### 5.5 `predict_room_occupancy` (old value, kept)
- **Readers that stay:** `energy_forecast.py:445,499` (switch off), `__init__.py:3251` (the `bayesian_occupancy` writer), `get_top_time_bin_for_room` (only reader was the pattern sensor, which moves). After D2 the forecast sensors no longer call `predict_room_occupancy_at_time` (`sensor.py:15227,15244`); `predict_room_occupancy_at_time` has no other reader (KEEP + DOCUMENT, §9).

---

## 6. Knobs

All rung 1 (module constants, reviewed code change), including the three added after plan review (the Optimization constants sit with their siblings at `const.py:4269-4285`, which are rung 1 by design: "Module constants only"). These are display/record mechanics on a diagnostic surface; the parsimony rule says not to put them on the options flow.

| Knob | Value | Why | Kill / edge |
|---|---|---|---|
| `FORECAST_DWELL_SOURCE_ENABLED` | `True` | Kill switch for D2 | `False`: both sensors read the Bayesian model exactly as before (byte-identical code path kept behind the flag) |
| `FORECAST_PERSISTENCE_WEIGHT_1H` | `0.5` (P1-R) | weight of last-hour fraction at +1 h | `0.0` = cell share only; `1.0` = persistence only |
| `FORECAST_PERSISTENCE_WEIGHT_4H` | `0.25` (P1-R) | same at +4 h | same |
| `FORECAST_TOP_CELLS_COUNT` | `5` | number of cells in the pattern sensor's `top_cells` attribute (L5); 5 cells × (label, share) is ~150 bytes, far under the recorder's 16 KB attribute limit | `0` = attribute omitted |
| `DWELL_SHARE_PRODUCER_ENABLED` | `True` | Kill switch for D3 | `False`: no tick registered, no read, no write; D2 blend falls back to weight 0 |
| `DWELL_SHARE_TICK_MINUTE` | `2` | read the finished hour after its last 5-min sample is committed | valid range 0-14 (I1 needs the capture inside H). **L3:** an out-of-range value is clamped to 2 by the runner at registration with one WARNING; it never raises at import (an import error would break setup) |
| `NEXT_ROOM_MAX_SKIP_RATIO` | `0.30` | H2: the share of transitions the I4 from-room gate may drop before the top-1 gain stops counting as evidence | **evidence bound only, not a behaviour gate**: it is read by the D4 Live check and the D4 sensor attribute `skip_ratio_ok`; it changes no scoring. `1.0` = never flags |
| `OPTIMIZER_PREDICTION_ACCURACY_MIN_SKILL_PCT` | `0.0` | H1 default (§13 Q5): next-room finding fires when pooled top-1 minus the always-usual-room top-1 on the same rows is ≤ this many points | lives next to `OPTIMIZER_PREDICTION_ACCURACY_TOP1_FLOOR_PCT` in `const.py`; negative = never fires on skill |
| `OPTIMIZER_PREDICTION_ACCURACY_TOP1_HYSTERESIS_PCT` | `5.0` | H1 fallback only (if Q5 keeps the absolute floor): clear threshold = floor + this | `0.0` = today's behaviour (no hysteresis) |
| `DWELL_SHARE_MIN_ACTUAL_SAMPLES` | `6` | an hour with half its samples missing is not evidence | `0` = score any hour with ≥ 1 sample |
| `NEXT_ROOM_CURRENT_ROOM_PRIMARY` | `True` | Kill switch for D4 order | `False`: old order (Bayesian → away_typical → frequency), byte-identical |
| `PREDICTION_RESULTS_RETENTION_DAYS` | `45` | ≥ the 37-day `next_room` window `regime_detector` reads (`regime_detector.py` 30 + 7) | replaces the `days=30` literal at `nightly_maintenance.py:39` |

Promote the two blend weights to rung 3 only if the operator later wants to tune by observation; there is no reason to today.

---

## 7. DB write volume

| Writer | Rate | Notes |
|---|---|---|
| `dwell_share` (new) | 47 rows/hour = **1,128 rows/day**, one `executemany` + commit per hour (24 transactions/day) | steady state at 45 d retention ≈ 51k rows (a few MB) |
| `dwell_share` reads (new) | one grouped indexed read of ~560 `environmental_data` rows per hour via `_db_read()` | negligible next to the nightly 56-day read |
| `next_room` | unchanged (~450/day live); D4's from-room gate can only lower it | |
| `bayesian_occupancy` | unchanged (~280/day) | |
| Prune (D5) | first run deletes ~150k old `next_room` rows in the existing 1,000-row batches with 0.1 s sleeps (~150 batches); then ~1.8k rows/day | one-off WAL growth; nightly incremental vacuum reclaims |

**Pre-deploy snapshot (Tier 2-DB rule):** `SELECT prediction_type, count(*), min(prediction_timestamp) FROM prediction_results GROUP BY 1` and rows/day per type for the last 7 days, recorded in the README.

---

## 8. Deliverables

### D0: Backtest script (committed, run before build; read-only)

`scripts/probes/predict_dwell_backtest.py`, stdlib only, `ssh ha "python3 - [--days N] [--json]"`. Built from the §2 probe plus:
1. The blend-weight sweep w ∈ {0, 0.25, 0.5, 0.75, 1} at +1 h and +4 h **on the runtime alignment of P1-R** (target = cell of `now + h`, `now` uniform in the hour, persistence = last completed hour at `now`, H−2 before the tick minute), reported for the full window, the first week (selection) and the second week (held out). It must reproduce P1-R; the §6 weights are already set from it.
2. A producer-agreement check (§5.2): hourly fraction from `environmental_data` vs time-weighted recorder `binary_sensor.<room>_occupied` for 4 rooms × 1 day.
3. An assertion that every model used for day D has `max(training timestamp) < D 00:00`.
4. The P3 table. Its from-room agreement is 100% by construction and is labelled "**upper bound on agreement**; the live skip rate is measured by D4's counter, not here" (H2 d).

**Acceptance criteria**
- **Verify:** the script reproduces §2 (P1-R, P2, P3) within rounding on the same window.
- **Verify (discriminating, M1):** run with `--align probe` (lag h) and default runtime alignment; the +1 h w = 0.5 MSE differs (0.0165 vs 0.0205 on the §2 window). If both modes print the same number, the alignment switch is not wired.
- **Verify (discriminating):** the no-hindsight assertion fails if the training end is moved past the day start (the script's own self-test flag `--leak-test` shows a lower, in-sample error and a failed assert).
- **Live:** none (read-only).

### D1: `RoomDwellModel` small extensions

- `trained_until_utc` (aware UTC of the training-window end), set in `apply` from the runner's `training_window` end. `None` before the first refresh.
- `forecast(entry_id, now_local, horizon_h, last_hour_fraction, weight) -> float | None`: `w × last_hour_fraction + (1 − w) × lookup(now + horizon)`; returns the cell share alone when `last_hour_fraction` is None; None when the cell has no samples. Pure. The target cell is looked up from the **local time of `now_utc + horizon`** (aware arithmetic in UTC, then converted), so a horizon across a DST change lands on the right local hour (M3).
- `peak_cell(entry_id) -> (Cell, share) | None` and `top_cells(entry_id, k) -> list[(Cell, share)]` for the pattern sensor.

**Acceptance criteria**
- **Verify:** `trained_until_utc` equals the start of the local refresh day in UTC, across a DST boundary.
- **Verify:** `forecast` with weight 0 equals `lookup`; with weight 1 equals the persistence input; None-safe.
- **Test:** `test_room_dwell_model.py::test_trained_until_is_start_of_refresh_day`, `::test_trained_until_dst`, `::test_forecast_blend_bounds`, `::test_forecast_without_persistence`, `::test_forecast_horizon_across_dst`, `::test_peak_cell`, `::test_top_cells_count_knob`.
- **Live:** covered by D2/D3.

### D2: Forecast and pattern sensors read the dwell model

- `BayesianOccupancyForecastSensor`: with `FORECAST_DWELL_SOURCE_ENABLED`, state = `round(100 × lookup(entry_id, now), 1)` (the usual share for this hour). Attributes: `forecast_now`, `forecast_+1h`, `forecast_+4h` (blended via D1 with `runner.last_hour_fraction(entry_id)`), `model: "dwell"`, `cell`, `cell_days`, `last_hour_fraction`, `model_status`, `model_refreshed_at`. Keep `room`. Drop the Bayesian `learning_status` loop (`sensor.py:15247-15255`) in the new branch. There is no learning gate: the sensor publishes `cell_days` and leaves the judgement to the reader (`OCC_ANOMALY_MIN_CELL_DAYS` is not reused).
- **After a restart (M5):** `last_hour_fraction` is in memory only, so until the first D3 tick after restart (minute 2 of the next hour) it is `None`. The sensor then publishes attribute `last_hour_fraction: null` and `forecast_+1h` / `forecast_+4h` equal the cell share of their target hours (blend weight effectively 0). When the tick fills it, the `+1h`/`+4h` values step to the blended value; that step is expected and is not a fault. Same when `DWELL_SHARE_PRODUCER_ENABLED` is False (permanently weight 0).
- **Update cadence (M6):** both classes are `UniversalRoomEntity` → `CoordinatorEntity` (`entity.py:19`) and do not override polling, so they recompute on every room-coordinator refresh (`coordinator.py:685`, 30 s + jitter). `forecast_now` therefore changes cell within about 30 s of an hour boundary. The occupancy-anomaly binary sensor reads the same model on its own refresh; the two can disagree for up to one refresh across a boundary, so the D2 Live comparison is made "within the same cell" (both attributes report `cell`).
- `BayesianOccupancyPatternSensor`: state = `cell_label(peak_cell)` (e.g. `"weekday 14:00"`), attributes `peak_share`, `top_cells` (the `FORECAST_TOP_CELLS_COUNT` highest-share cells with their shares), `model: "dwell"`. It does not call `usual_hours`, because that takes the anomaly threshold and would tie this display to an anomaly knob.
- Before the first model refresh: state `None` (unknown), `model_status: never_refreshed`. Not 0.
- unique_ids, names, device, category, disabled-by-default: unchanged.

**Acceptance criteria**
- **Verify (discriminating):** a room whose cell share is 0.6 shows state 60.0. Under the Bayesian source the same fixture shows its arrival probability (the fixture's Study A cell: Bayesian ≈ 1%), so the test fails if the sensor still reads `predict_room_occupancy_at_time`.
- **Verify:** `forecast_+1h` ≠ `forecast_now` when `last_hour_fraction` differs from the cell share and weight > 0; equal when weight = 0.
- **Verify:** kill switch False → attribute set and value identical to the pre-change sensor on the same predictor fixture.
- **Verify (M5):** with `last_hour_fraction` None, `forecast_+1h` equals the +1 h cell share and the attribute is `null`, not 0.
- **Test:** `test_predict_dwell_sensors.py::test_forecast_state_is_dwell_share`, `::test_forecast_blend_uses_last_hour`, `::test_forecast_after_restart_no_persistence`, `::test_forecast_unknown_before_model`, `::test_forecast_kill_switch_byte_identical`, `::test_pattern_state_is_peak_cell`, `::test_pattern_kill_switch_byte_identical`.
- **Live:** `sensor.study_a_bayesian_occupancy_forecast` (or the live entity_id of an enabled forecast sensor) on a weekday between 10:00 and 16:00 reads > 20 with `model: dwell` (the audit read ~1% under the Bayesian source for the same room). When both report the same `cell`, its `forecast_now` equals the Study A occupancy-anomaly sensor's `expected_share` × 100 (same model, same cell). Read at least 2 minutes after an hour boundary.

### D3: Hourly `dwell_share` producer

- On `RoomDwellModelRunner`: one `async_track_time_change(minute=DWELL_SHARE_TICK_MINUTE, second=0)` on its own unsub attribute, cancelled in `async_stop` (Bug Classes #19/#50). Registered only when the producer flag is on.
- **Hour keys are UTC (M3).** H is the UTC hour start containing the tick (`dt_util.utcnow()` floored to the hour). `frozen` is keyed by that aware UTC datetime, and `prediction_timestamp` is its ISO string. The cell is looked up from the local time of that UTC start. At fall-back the two local 01:00 hours are two distinct UTC keys, so two distinct rows; at spring-forward there is no missing key in UTC.
- **Same-hour guard (M4).** The runner records `_last_scored_utc_hour`. A tick whose H−1 equals it does nothing (no read, no write). This covers the reachable double-fire cases: the time-change callback firing twice in one minute after a clock adjustment, and a reload overlap in which a stopping runner's callback fires once more. `async_stop` cancels the tick before the new runner registers (the runner is created in parent setup and stopped by `entry.async_on_unload`, `__init__.py:4850-4853`).
- Each tick, in this order:
  1. **Score H−1.** If `frozen[H−1]` exists and H−1 ≠ `_last_scored_utc_hour`: one `get_room_occupied_share_by_hour(start(H−1), start(H))`; for each room in `frozen[H−1]` with ≥ `DWELL_SHARE_MIN_ACTUAL_SAMPLES` samples, build the §5.3 row; store `last_hour_fraction[room]`; one `save_prediction_results_batch`; set `_last_scored_utc_hour = H−1`. Drop `frozen[H−1]` whether or not the write succeeded (no retry, no backfill).
  2. **Freeze H.** If `model.has_model` and `model.trained_until_utc ≤ start(H)`: `frozen[H] = {entry_id: (share, n)}` for every room entry with a non-empty cell. Otherwise freeze nothing and increment `skipped_freeze` (a counter on the runner, logged at DEBUG; no entity).
- Room set: the room config entries at freeze time (`entry_type == "room"`). A room removed during the hour is still scored (its env rows exist); a room added mid-hour starts at the next freeze.
- The tick is async and awaits the read and the write; it never runs the write inside the model refresh. Exceptions are caught and logged at WARNING once per tick.
- `frozen` is in memory only. A restart loses at most the current hour and the previous one.

**Acceptance criteria**
- **Verify (I1, discriminating):** with a model whose `trained_until_utc` is after `start(H)` (simulated restart refresh), no row is written for H. Under a broken check the row appears with an in-sample value.
- **Verify (I1):** a freeze at H followed by a model refresh during H still writes the frozen value, not the new lookup.
- **Verify (I2, M4):** the same tick callback invoked twice for the same H writes at most one row per room for H−1 (the second call hits `_last_scored_utc_hour`). One `executemany` per tick. (A real restart cannot reach this: `frozen` is empty after restart, so there is nothing to score.)
- **Verify (I2, M4):** after `async_stop`, firing the old callback writes nothing, and a new runner's first tick writes once.
- **Verify (M3):** on the fall-back day the two local-01:00 hours produce two rows with distinct UTC `prediction_timestamp`s; on the spring-forward day no tick raises and no hour key is skipped in UTC.
- **Verify (M2):** `prediction_timestamp` matches `^\d{4}-\d\d-\d\dT\d\d:00:00\+00:00$`.
- **Verify:** an hour with 5 samples is skipped at the default; 6 is scored.
- **Verify:** row shape exactly §5.3; `error_value` signed.
- **Verify:** flag False → no tick registered, zero writes, zero reads.
- **Test:** `test_dwell_share_producer.py::test_scores_previous_hour_with_frozen_value`, `::test_no_row_when_model_trained_past_hour_start`, `::test_refresh_mid_hour_keeps_frozen`, `::test_same_tick_twice_one_row` (renamed from `test_one_row_per_room_hour_after_double_tick`), `::test_stopped_runner_callback_writes_nothing`, `::test_fall_back_hour_two_rows_distinct_utc`, `::test_spring_forward_no_gap_error`, `::test_tick_minute_out_of_range_clamped`, `::test_min_samples_gate`, `::test_row_shape` (asserts the M2 timestamp format and `confidence = n`), `::test_flag_off_no_tick`, `::test_unsub_on_stop`, `::test_dao_against_production_schema` (DDL from `database.py`, real DAO + real batch writer, not hand-written INSERTs).
- **Live:** within 2 h of restart, `SELECT count(*), count(DISTINCT room_id), min(predicted_value), max(predicted_value) FROM prediction_results WHERE prediction_type='dwell_share' AND prediction_timestamp >= <restart hour>` returns ≥ 40 rows per scored hour, ≥ 40 distinct rooms, and predicted values that are not all equal (sentinel check). No hour has two rows for one room (`GROUP BY room_id, prediction_timestamp HAVING count(*) > 1` returns nothing).
- **Live (disposition query, at the organic window, not a soak):** over the first 7 full days, `avg(error_value²)` for `dwell_share` is within ±30% of the backtest 0.0273 (the D3 row scores the cell share at the start of H, i.e. w = 0, so the comparable backtest number is the cell-only one, not the blended one) and below the per-room-constant MSE computed from the same rows. A value far below the backtest (< 0.015) indicates an in-sample leak, not a better model.

### D4: Next room from the current room

- `PersonLikelyNextRoomSensor.async_update` (`sensor.py:3362`): when `NEXT_ROOM_CURRENT_ROOM_PRIMARY` and the person's `location` is a real room (same exclusions as `sensor.py:3463`), call `pattern_learner.predict_next_room(person, current_room)` first; if it returns a prediction, skip the Bayesian and `away_typical` steps. Otherwise run the existing chain unchanged.
- Cache entry (`sensor.py:3497-3503`) gains `current_room` (the room the prediction was made from; `None` for the Bayesian / away paths). The `current_room` attribute of the sensor carries the same value.
- `transitions._score_prediction` (`transitions.py:482`): if the cache has a non-None `current_room` and it differs from the transition's `from_room`, do not write a row; increment a **per-person** counter `skipped_room_mismatch` held in `hass.data[DOMAIN]["next_room_scoring_stats"][person]` alongside `scored` (incremented when a row is written). Requires passing `from_room` into `_score_prediction` from `_log_transition` (`transitions.py:476`). Comparison is on the same naming the cache and the transition use; if they differ in form (display name vs slug), both are normalised with the existing room-name normaliser before comparing, and the builder must cite the normaliser it reuses (no new one).
- **Visible skip counter (H2 a).** The existing per-person next-room accuracy sensor (`*_next_room_accuracy`) gains attributes `scored_since_start`, `skipped_room_mismatch_since_start`, `skip_ratio` (= skipped / (skipped + scored), `null` when both are 0) and `skip_ratio_ok` (`skip_ratio ≤ NEXT_ROOM_MAX_SKIP_RATIO`). In-memory since HA start, so the Live check reads them after a known uptime. Not DEBUG-only. The scorer also logs one INFO line per 100 skips per person with the running ratio, so the ratio survives in the journal across restarts.
- **Discriminating rule (H2 c).** If `skip_ratio > NEXT_ROOM_MAX_SKIP_RATIO` for a person, that person's top-1 gain is **not accepted** as evidence for D4, whatever its value; the Live check reports FAIL-INCONCLUSIVE and a card is opened for the name/timing mismatch.
- `source` stays `"frequency"` for this path (existing value; the accuracy sensors and OC read it as a label only).

**Acceptance criteria**
- **Verify (discriminating):** with Bayesian and PatternLearner both returning predictions, the sensor reports PatternLearner's room and `source: frequency`; with the flag False it reports the Bayesian room (old behaviour).
- **Verify:** person `away` → existing `away_typical` path still wins (regression guard).
- **Verify (I4):** a cached prediction from room A scored on a transition B → C writes no row; A → C writes one.
- **Verify (H2):** a mismatch increments `skipped_room_mismatch` and `skip_ratio` on the accuracy sensor; a match increments `scored`; a legacy cache (no `current_room`) increments `scored`, never `skipped`.
- **Test:** `test_next_room_current_room.py::test_current_room_primary`, `::test_flag_off_bayesian_first`, `::test_away_keeps_away_typical`, `::test_cache_carries_current_room`, `::test_scorer_skips_room_mismatch`, `::test_scorer_legacy_cache_without_room`, `::test_skip_counter_exposed_on_accuracy_sensor`, `::test_skip_ratio_ok_uses_knob`, `::test_room_names_normalised_before_compare`.
- **Live:** `sensor.universal_room_automation_jaya_likely_next_room` attribute `current_room` equals Jaya's current room (`person_coordinator` location / `sensor.jaya_room`) at read time.
- **Live (H2 b, skip ratio, read first):** after ≥ 24 h uptime, each resident's accuracy sensor shows `skip_ratio ≤ 0.30` (`skip_ratio_ok: true`) with `scored_since_start + skipped_room_mismatch_since_start ≥ 50`. Under a name or timing mismatch the ratio is near 1 and the scored count is small; under a working gate it is low. If this fails, the next criterion is not evaluated.
- **Live (accuracy):** after 3 days, the one-shot query of `next_room` rows since deploy shows Jaya's top-1 (`json_extract(predicted_value,'$.top') = actual_value`) ≥ 40% and above her always-the-usual-room rate on the same rows. Under the old source the same query gives 15.4% (live 7-day, read 2026-10-21), so the observation discriminates, provided the skip-ratio check passed.

### D5: Prune all prediction types

- `prune_prediction_results`: remove the `AND prediction_type = 'bayesian_occupancy'` filter (`database.py:8004`); `nightly_maintenance.py:39` passes `PREDICTION_RESULTS_RETENTION_DAYS`.

**Acceptance criteria**
- **Verify:** a fixture with old rows of all three types → all three pruned; recent rows kept.
- **Verify:** batching unchanged (1,000-row batches, 500-batch cap).
- **Test:** `test_prediction_results_prune.py::test_prunes_all_types`, `::test_keeps_rows_inside_retention`.
- **Live:** the morning after the first nightly maintenance, `min(prediction_timestamp)` for `next_room` is within 46 days of now (was 2026-05-13), and the HA journal for that night has no line matching `DB write queue peak:` (`database.py:410-413`, logged when the queue exceeds 10) and no `worker backlog` / `event-loop stall` wait-episode WARNING (`database.py:254-275`) (L4).

### D7: Optimization next-room finding compares against baseline skill (H1)

Default per §13 Q5; if the operator picks the fallback, D7 is the hysteresis variant below instead.
- **Default (skill):** `_read_next_room_accuracy` (`optimization.py:3705-3795`) additionally computes, over the same rows, the top-1 rate of the always-the-usual-room baseline using the same definition PREDICT-SCORER-BASELINE-SKILL-1 ships (the builder reuses that card's helper; it does not write a second baseline). It returns `skill_pct = top1 − baseline_top1`. The clause at `optimization.py:3914-3926` fires when `skill_pct ≤ OPTIMIZER_PREDICTION_ACCURACY_MIN_SKILL_PCT`. The issue string and payload carry both rates and the skill. `OPTIMIZER_PREDICTION_ACCURACY_TOP1_FLOOR_PCT` stays defined (KEEP + DOCUMENT: no reader after D7, kept for the fallback).
- **Fallback (absolute + hysteresis):** keep the floor; persist the last clause state on the coordinator; fire below `TOP1_FLOOR_PCT`, clear only above `TOP1_FLOOR_PCT + TOP1_HYSTERESIS_PCT`.
- **Ordering:** D7 depends on PREDICT-SCORER-BASELINE-SKILL-1 landing in the same release. If that card slips, ship the fallback, not the skill variant.

**Acceptance criteria**
- **Verify (discriminating):** pooled top-1 45% with baseline 45% → fires (no skill); top-1 30% with baseline 15% → does not fire. Under the old absolute floor the outcomes are reversed (45% clears, 30% fires), so the test tells the two rules apart.
- **Verify (fallback):** 34 → fire, 37 → still firing, 41 → clear, 37 → still clear.
- **Test:** `test_optimization_prediction_accuracy.py::test_next_room_fires_on_no_skill`, `::test_next_room_quiet_with_skill_below_old_floor`, `::test_hysteresis_fallback_no_flap`, `::test_under_learned_gate_unchanged`.
- **Live:** for the first 7 days, the prediction-accuracy dimension's issue list read once per day contains the next-room clause on a day if and only if that day's one-shot pooled query (same 7-day window, same rows) gives skill ≤ 0. Recorded per day in the README table; under the old code the clause would appear on every day with top-1 < 35% instead.

### D6: Docs

- Presence state-of-play §1 consumer table (`environmental_data.occupied` → forecast sensors + `dwell_share` producer) and §9 (this card), same commit.
- `PLANNING_occupancy_anomaly_dwell_model.md` §9: note that the forecast switch shipped.
- README with the Live table, written back after validation.

---

## 9. Supersession triage (pre-existing code this makes redundant)

| Item | file:line | Bucket | Reason |
|---|---|---|---|
| `predict_room_occupancy_at_time` | `bayesian_predictor.py:814-830` | KEEP + DOCUMENT | No reader after D2 (flag on). The kill-switch path still calls it, so not dead while the flag exists. |
| `get_top_time_bin_for_room` | `bayesian_predictor.py:506-` | KEEP + DOCUMENT | Same: only the pattern sensor's kill-switch path reads it. |
| `bayesian_occupancy` writer + `get_accuracy_stats` + `sensor.ura_bayesian_prediction_accuracy` | `__init__.py:3203-3318`, `bayesian_predictor.py:912-955`, `sensor.py:15262` | KEEP + DOCUMENT | Still scores the model `energy_forecast` would use. Revisit with §13 Q1. The sensor's 94.4% headline is PREDICT-SCORER-BASELINE-SKILL-1's subject. |
| Bayesian first step in `PersonLikelyNextRoomSensor` | `sensor.py:3366-3392` | KEEP (now the fallback) | Used when no current room is known. |
| `get_anomaly_score` | `bayesian_predictor.py:832-880` | DELETE candidate (already carded by the anomaly cycle) | Unchanged here. |
| `regime_detector` D7 next-room accuracy drop | `regime_detector.py:356-420` | KEEP + WIRE (side find, card) | Compares JSON to a room name; 0 of 3,109 matches. Should use `json_extract(predicted_value,'$.top')`. Not this card. |

Zero DELETE items in this cycle (expected; deletion waits for live validation).

---

## 10. Emission / decision sites (all)

| # | Site | Value | Change |
|---|---|---|---|
| E1 | `sensor.py:15212-15230` forecast `native_value` | state | D2 |
| E2 | `sensor.py:15232-15257` forecast attributes | +1h/+4h | D2 |
| E3 | `sensor.py:15078-15108` pattern state/attrs | peak | D2 |
| E4 | `sensor.py:3362-3468` next-room source order | next room | D4 |
| E5 | `sensor.py:3475-3505` next-room cache | cache | D4 (+`current_room`) |
| E6 | `transitions.py:482-545` scorer | `next_room` row | D4 (gate) |
| E7 | runner tick (new) | `dwell_share` row | D3 |
| E8 | `database.py:7983-8020` prune | retention | D5 |
| E9 | `__init__.py:3251` `bayesian_occupancy` writer | row | unchanged |
| E10 | `energy_forecast.py:445,499` | energy | unchanged (I3) |
| E11 | `binary_sensor.py:3432+` anomaly sensor | dwell lookup | unchanged |
| E12 | `optimization.py:3914-3926` next-room accuracy clause (reads `optimization.py:3705-3795`) | Optimization issue list | D7 (skill comparison, or hysteresis fallback) |
| E13 | per-person `*_next_room_accuracy` sensor attributes | skip counter / ratio | D4 (new attributes) |

Side finds recorded, not fixed here: regime D7 JSON compare (above); Ziri has no transitions in 14 d (no fault traced).

---

## 11. Non-goals

- No change to the energy forecast's occupancy read (I3), the Bayesian beliefs, `room_transitions`, or the `bayesian_occupancy` writer.
- No zone- or house-level occupancy forecast. None exists and nothing would read one. Revival trigger: a consumer is proposed (for example HVAC pre-conditioning per zone) with a backtest showing a zone forecast beats per-room aggregation.
- No pattern-detection sensor; PREDICT-PATTERN-DETECTED-ORPHANS-1 stays parked (its trigger is not fired: this plan re-sources the existing `bayesian_occupancy_pattern` entity, which has its own unique_id).
- No skill-vs-baseline attribute on the accuracy sensors (that is PREDICT-SCORER-BASELINE-SKILL-1; see Q2). D7 consumes that card's baseline; it does not build its own.
- No change to the other `OPTIMIZER_PREDICTION_ACCURACY_*` thresholds (Brier ceiling, min samples, data-quality floor, window). Only the next-room clause changes (D7).
- No flap dedupe in PatternLearner training (P3 shows the raw chain already beats the constant; revival trigger: live top-1 below the constant for any resident over 7 days).
- No time-of-day conditioning of next room (P3), no learned blend (§3), no new options-flow fields, entities, tables or migrations.
- No notifications.

---

## 12. Tier

**Tier 2-DB** (three framing-disjoint reviews + live validation; one adversarial plan review before build). Triggers: a new persisted record shape in `prediction_results` (`dwell_share`), a changed DAO behaviour (prune), and a new periodic writer to a shared table. Not Tier 3: no actuation, no cost/safety path, and the one trust-shaped consumer (energy) is explicitly untouched (I3). If the operator answers Q1 "re-source energy now", the energy read becomes a cost-path consumer and this goes to Tier 3 with the energy reference skill.

Suggested framings: **A** model and arithmetic (blend, DST, empty cells, signed error, room-set changes); **B** lifecycle, DB and restart (tick registration/unsub, double tick, refresh-during-hour, prune batch on 150k rows, write-queue under the hourly batch); **C** test authority (each I1 clause and the D4 gate mutation-anchored; DAO tests on production DDL; kill switches proven byte-identical).

---

## 13. Decisions for the operator

1. **Energy forecast read (Q1).** `energy_forecast` uses the Bayesian occupancy probability when `switch.ura_energy_coordinator_occupancy_weighted_prediction` is on. It is **off** today. Recommendation: leave it on the old model this cycle and card "re-source energy occupancy weighting onto the dwell model", triggered by you wanting the switch on. Re-sourcing now would put a cost-path consumer in this cycle and make it Tier 3.
2. **Ship the scorer card with this one (Q2)?** After D4 the next-room accuracy sensors will jump (about 13 → 35% for Oji). Without PREDICT-SCORER-BASELINE-SKILL-1's "vs baseline" attribute nobody can tell that from noise on the dashboard. Recommendation: build it in the same release (Tier 1, small). **This is now load-bearing:** D7's default depends on it; a "no" here forces the Q5 fallback.
3. **Zone and house forecasts (Q3).** The card says room/zone/house; only room-level forecasts exist. Recommendation: room only, zone/house parked (§11). Say if you want them.
4. **One-off prune (Q4).** D5 deletes about 150k `next_room` rows older than 45 days on the first night. Recommendation: yes. If you want them kept for analysis, export first or set the retention higher.
5. **Optimization next-room finding (Q5, from plan review H1).** Today it fires every evaluation (pooled top-1 15.1% < 35% floor). After D4 the pooled rate is projected near 45%, with Oji alone near 35%; a person-mix shift or the I4 gate could move the pooled rate toward the floor. **Default: compare against baseline skill** (fire when pooled top-1 is no better than always guessing the usual room, `OPTIMIZER_PREDICTION_ACCURACY_MIN_SKILL_PCT = 0`), using PREDICT-SCORER-BASELINE-SKILL-1's baseline from the same release. Alternative: keep the absolute 35% floor with 5-point hysteresis (`OPTIMIZER_PREDICTION_ACCURACY_TOP1_HYSTERESIS_PCT`). Not recommended: leave it alone and accept a display-only flap.

---

## 14. Plan review disposition

Review: `docs/planning/REVIEW_plan_predict_dwell_migration.md` (FIX-PLAN-FIRST, 2 HIGH, 6 MEDIUM, 5 LOW). Each finding was checked against code before acting. None rejected; one partly corrected.

| ID | Verified against | Disposition | Where |
|---|---|---|---|
| H1 | `const.py:4272`; `optimization.py:3705-3795, 3914-3926` | **Accepted, with a correction.** The floor is a real consumer and the plan's "no threshold is tuned" claim was wrong. Correction: the clause pools all persons, so the projected post-D4 rate is ~45% (live mix weighting), not Oji's 34.8%; flap risk is lower than stated but real. Default: skill-vs-baseline (D7), hysteresis fallback; operator decision Q5. | §1.1, §2 P3 note, §4 I5, §5.4, §6, D7, E12, §11, §13 Q5 |
| H2 | `sensor.py:3460-3463` (BLE location), `transitions.py:476-482` | **Accepted.** Per-person visible counters + `skip_ratio` attributes, INFO log every 100 skips, `NEXT_ROOM_MAX_SKIP_RATIO = 0.30` (rung 1, evidence bound), Live skip-ratio criterion that gates the accuracy criterion, D0 item 4 reworded to "upper bound". Added name normalisation before compare. | §2 note, §4 I4, §6, D0, D4, E13 |
| M1 | probe source (persistence = hour T−h) | **Accepted; sweep re-run on runtime alignment.** +1 h gain drops from −40% to −25%; +4 h stays −12%. Weights 0.5 / 0.25. | §2 P1-R, §6, D0 |
| M2 | `__init__.py:3231`, `sensor.py:3502`, `transitions.py:534` (all `utcnow().isoformat()`) | **Accepted.** Aware ISO with `+00:00`, asserted in `test_row_shape`. | §5.3, D3 |
| M3 | — (design) | **Accepted.** UTC hour keys, local cell lookup, two DST tests, D1 horizon-across-DST test. | D1, D3 |
| M4 | `__init__.py:4850-4853` | **Accepted.** Test reworded; `_last_scored_utc_hour` guard; stopped-runner test. | D3 |
| M5 | — (design) | **Accepted.** `last_hour_fraction: null` → weight 0 until first tick; test added. | D2 |
| M6 | `entity.py:19` (`CoordinatorEntity`), `coordinator.py:685` (30 s + jitter) | **Accepted.** Cadence stated; Live check made "same cell, ≥ 2 min after boundary". | D2 |
| L1 | `database.py:7917-7938` | **Accepted.** Keep `n`; docstring + state-of-play note. | §5.3 |
| L2 | — | **Accepted.** First-week selection / second-week held-out columns reported. | §2 P1-R, D0 |
| L3 | — | **Accepted.** Clamp + WARNING at registration, never raise at import. | §6, D3 test |
| L4 | `database.py:254-275, 410-413` | **Accepted.** Log strings named. | D5 |
| L5 | — | **Accepted.** `FORECAST_TOP_CELLS_COUNT = 5` (rung 1), size stated. | §6, D1, D2 |

Scope after fixes: D7 is new (one clause + one constant pair, gated on the sibling card). Under the ~20% split threshold; kept in this plan because it is the consumer side of D4's value change.

## Operator decisions (2026-10-21)
Operator: "1 - rec" — all §13 recommendations taken: Q1 energy forecast stays on the old model (card later); Q2 PREDICT-SCORER-BASELINE-SKILL-1 ships in the same release; Q3 room level only; Q4 one-off prune of ~150k old `next_room` rows: YES (permanent deletion approved); Q5 optimizer next-room finding compares against baseline skill.
