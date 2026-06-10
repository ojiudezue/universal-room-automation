# PLANNING — Routine-Awareness Next-State Forecaster

**Status:** Draft — version assigned at deploy.
**Operator framing (2026-06-09):** *"routine awareness should ABS be fixed. It's critical."* Decision: do NOT build a new Bayesian house-state model. FIX the existing routine-awareness path with CONTEXT-WIDE checking. Lean on EXISTING learned data — `house_state_log` is the substrate.

**Goal:** Replace the `placeholder_v0` stub behind `sensor.ura_presence_coordinator_next_state` with a real frequency/recency forecaster that produces P(next_state | current_state, day_type, time_bin) + median transition ETA from the historic `house_state_log` table. Keep the D1 PWA contract bit-for-bit; emit `"unknown"` honestly when support is thin. No new DB tables; bounded read-only aggregation refreshed in memory.

---

## Institutional context verified

### Code locations surveyed (read end-to-end during scoping)
- `custom_components/universal_room_automation/domain_coordinators/presence.py:1649-1688` — placeholder `get_next_state_prediction()` with TODO at L1666-1669 hooking `hass.data[DOMAIN].get("routine_forecaster")`.
- `custom_components/universal_room_automation/sensor.py:4276-4439` — `PresenceNextStateSensor` + `_NextStateVocab` (vocab: `home_day | home_night | away | sleep | guest | vacation | unknown`).
- `custom_components/universal_room_automation/database.py:892-904` — `house_state_log` schema: `(id, timestamp, state, confidence, trigger, previous_state)` with `idx_house_state_timestamp`.
- `database.py:1981-2030` — `log_house_state_change()` writer + `count_house_state_changes_since()` reader (pattern to mirror).
- `presence.py:4663-4673` — single insertion site for log rows (transition emit).
- `presence.py:1847-1867` — boot-time hydration pattern from `house_state_log` (reuse: same DB handle access).
- `bayesian_predictor.py:948-966` — REUSE `_hour_to_time_bin(hour) -> int (0..5)` and `_day_type(dt) -> int (0|1)`. Same binning used by RegimeDetector (`regime_detector.py:259-272`).
- `domain_coordinators/house_state.py:22-33` — `HouseState` vocab is BROADER than `_NextStateVocab`: includes `ARRIVING`, `HOME_EVENING`, `WAKING`. Forecaster must collapse these to PWA vocab before emitting (see Design §3).
- `domain_coordinators/signals.py:12, 166-173` — `SIGNAL_HOUSE_STATE_CHANGED` + `HouseStateChange` payload (subscribe to invalidate cache + recompute).
- `domain_coordinators/regime_detector.py:182-248, 459-477` — guest/vacation handling reference (cell-level `_is_vacation_cell`; routine_status sensors live + healthy).
- `sensor.py:11469, 11622` — existing `routine_status` per-person + household sensors (live).

### Greps run + REUSED / NEW

| Item | Verdict | Location |
|---|---|---|
| `routine_forecaster` key in `hass.data[DOMAIN]` | NEW — grep returned zero hits; TODO hook unsatisfied. Use this exact key per the placeholder docstring. | `presence.py:1667` |
| `get_next_state_prediction()` consumers | REUSED — single consumer: `PresenceNextStateSensor._get_prediction()` (`sensor.py:4358`). PWA reads sensor state + attrs. No other coordinator reads this. |
| `house_state_log` readers | REUSED — `count_house_state_changes_since()` is the existing read pattern. Add ONE sibling reader `fetch_house_state_log_since()` returning rows. |
| `_hour_to_time_bin` / `_day_type` | REUSED — `bayesian_predictor.py:948, 964`. Same bins as RegimeDetector. |
| `HouseStateChange` signal payload | REUSED — `signals.py:166`. Subscribe to invalidate cache. |
| `_NextStateVocab` PWA vocabulary | REUSED — `sensor.py:4290-4302`. Forecaster output collapses HouseState → vocab. |
| Guest / vacation detection | REUSED — `HouseState.GUEST` / `HouseState.VACATION` rows already land in `house_state_log` (presence.py:4667). No new guest hook needed. Forecaster passes through if current_state is GUEST/VACATION. |
| New CONF_* required? | NONE. No new config-flow fields. Internal-only refresh cadence + min-support constants in `const.py`. |
| New sensors / Number / Switch / Button | NONE. Existing `sensor.ura_presence_coordinator_next_state` is the sole consumer. |
| New DB table | NONE. Aggregate in-memory from existing `house_state_log`. |
| New signal | NONE. Reuse `SIGNAL_HOUSE_STATE_CHANGED`. |

### Prior planning docs consulted
- `docs/planning/PLANNING_v4.6.9_DASHBOARD_SENSOR_SWEEP.md` — D1 sensor wiring + `_NextStateVocab` origin; PWA contract shape.
- `docs/planning/PLANNING_v4.6.9_boot_state_robustness.md` — boot-state restoration discipline (forecaster must tolerate boot AWAY state).
- `docs/planning/PLANNING_v4.6.1_anomaly_reconciliation_then_v4.6.2_routine_awareness.md` — B6/B7 design — RegimeDetector is **detection** only, no forward prediction (gap this cycle closes).
- `docs/planning/PLANNING_v4.6.0_likely_next_room_accuracy.md` — Bayesian per-room next-room prediction (cousin, not parent).

### Memory bodies pulled
- `project_optimizer_db_write_flood_incident_2026_06_09.md` — DB write-flood constraint: **NO new per-cycle DB writes**. Forecaster reads only; bounded query frequency.
- `feedback_parsimonious_room_config.md` — no new runtime knobs for internal mechanics.
- `feedback_no_fabrication_dhcp_incident.md` — sample-support thresholds must be measured from data, not stated.

### Design docs read
- `docs/Coordinator/PRESENCE_COORDINATOR.md` — coordinator surface; forecaster is read-only attachment.

---

## Tier classification

**Tier 2** (NOT 2-DB). Justification:
- Single read-only consumer (the existing sensor); no cross-coordinator actuation; no shared primitive change; no new schema; no new signal payload; no migration.
- The operator's "regression-prone → 3 framings" standing policy elevates *strategy / decision-logic* and *shared primitive* changes. This is neither — the forecaster is additive output behind an existing TODO hook with a single read consumer.
- However: **two framings must be disjoint** — Reviewer A = correctness + edge cases + vocab collapse; Reviewer B = lifecycle + DB-read budget + boot/restart resilience + signal-subscription cleanup.
- Live validation (Review 3) is mandatory; written back into README per CLAUDE.md "Record Live Validation Back Into the README" rule.

If reviewers find cross-coordinator coupling I missed (e.g., HVAC or Optimization reading the predicted state), elevate to Tier 2-DB and add Reviewer C = consumer-ripple.

---

## Design

### 1. Model — frequency over `house_state_log`

For each new-row insert into `house_state_log` the rest of URA already produces, the forecaster maintains an in-memory aggregate:

```
counts[(prev_state, day_type, time_bin)][next_state] = N
etas[(prev_state, day_type, time_bin)][next_state]   = list[seconds_between_rows]
```

- `prev_state`, `next_state` are HouseState string values (raw from log).
- `day_type` = `_day_type(timestamp_local)` (0=weekday, 1=weekend).
- `time_bin` = `_hour_to_time_bin(timestamp_local.hour)` (0..5).
- For a transition row at time `t` whose `previous_state = A` and `state = B`, the prior row in the log (same chain) gave us when A *began*. The dwell `t - t_prev` is the observed ETA for A→B from cell (A, day_type(t_prev), time_bin(t_prev)).

**At prediction time** with current state = C and now = T:
1. Compute cell `(C, _day_type(T_local), _hour_to_time_bin(T_local.hour))`.
2. Pull `counts[cell]`. If `sum(counts[cell]) < MIN_SUPPORT`, fall back to (C, day_type, *) (collapse time_bin); if still thin, fall back to (C, *, *). If still thin → return `unknown / 0.0`.
3. `predicted_next = argmax counts[cell]`; `confidence = N_argmax / sum(N)` clipped to `[0.0, 1.0]`.
4. `transition_eta_minutes = median(etas[cell][predicted_next]) / 60`, rounded to int; `None` if etas list empty.
5. Collapse `predicted_next` (HouseState) → `_NextStateVocab` (PWA vocab) — see §3.

**Constants (NEW in `const.py`):**
- `ROUTINE_FORECAST_MIN_SUPPORT: Final = 5` — min observations per cell before we trust the argmax (else cascade to coarser cell).
- `ROUTINE_FORECAST_HISTORY_DAYS: Final = 60` — aggregation window (matches RegimeDetector 56d baseline order of magnitude).
- `ROUTINE_FORECAST_REFRESH_SECONDS: Final = 3600` — full re-aggregation cadence (in addition to incremental update on each signal).
- `ROUTINE_FORECAST_MAX_ROWS: Final = 5000` — hard cap on rows fetched per refresh (bounded read, post-write-flood discipline).
- `ROUTINE_FORECAST_MODEL_ID: Final = "house_state_log_freq_v1"` — emitted in `prediction["model"]`.

### 2. Wiring — direct on PresenceCoordinator, not `hass.data` hook

The TODO comment proposes `hass.data[DOMAIN]["routine_forecaster"]`. **REJECT** that path (parsimony memo): single consumer, no other coordinator reads the forecaster. Put it on the coordinator.

- New attribute: `PresenceCoordinator._routine_forecaster: RoutineForecaster | None = None`.
- Instantiated in `async_setup()` right after the existing `_transitions_today` hydration (`presence.py:1867`) — same `db` handle, same lifecycle.
- `get_next_state_prediction()` delegates to `self._routine_forecaster.predict(self.house_state)` when present; else returns the existing placeholder shape (graceful degrade if DB is down).
- Subscribe to `SIGNAL_HOUSE_STATE_CHANGED` inside the forecaster to do *incremental* updates (single row appended) — does NOT re-read the DB on every signal.
- Periodic refresh (`ROUTINE_FORECAST_REFRESH_SECONDS`) re-reads the bounded window via `async_track_time_interval`, tracked + cancelled on coordinator shutdown (Bug Class #19).

### 3. Vocabulary collapse (HouseState → `_NextStateVocab`)

PWA vocab lacks `ARRIVING`, `HOME_EVENING`, `WAKING`. Collapse rules (deterministic, in forecaster):

| HouseState | `_NextStateVocab` emitted |
|---|---|
| `away` | `away` |
| `arriving` | `home_day` |
| `home_day` | `home_day` |
| `home_evening` | `home_night` |
| `home_night` | `home_night` |
| `sleep` | `sleep` |
| `waking` | `home_day` |
| `guest` | `guest` |
| `vacation` | `vacation` |

Collapse is applied to the argmax result, NOT to the histogram (so we keep the granular dwell data for ETA). If the argmax collapses to the same vocab as the current state (e.g., `home_evening` while currently `home_night`), the forecaster returns the **second-place** transition as the prediction (avoids "next state = current state" UX bug). If no off-diagonal candidate exists with enough support, return `unknown / 0.0`.

### 4. Guest / vacation handling

- If `current_state in {GUEST, VACATION}`: data is sparse and unreliable (guest events transient). Predict by passing through current vocab with `confidence = 0.3` and `transition_eta_minutes = None`, model = `house_state_log_freq_v1+guest_passthrough`. Document this in the docstring + `_NextStateVocab` validator already accepts it.
- Mirror RegimeDetector's "skip cell on vacation contamination" defensive posture (`regime_detector.py:219-228`): when aggregating, if the prev_state of a row is GUEST or VACATION, EXCLUDE that row from cells whose key starts with a non-guest state (prevents bleed-through during long guest runs).

### 5. Boot/restart resilience

- HouseStateMachine boots AWAY (per memo, persistence dropped). Forecaster handles by:
  - Treating the first post-boot prediction as cell `(AWAY, dt, tb)` — that cell has rich data.
  - Suppressing emission of high-confidence non-AWAY predictions for `60s` after coordinator setup (boot-settle gate) to avoid showing a "going to home_day in 5 min" prompt before presence sensors have re-established truth. Reuse the existing `_boot_settle_done` flag (`presence.py:1701-1705`) — gate forecaster output on it.
- Aggregation refresh deferred until after boot-settle release.

### 6. DB-read budget

- Per refresh: 1 query, `SELECT timestamp, state, previous_state FROM house_state_log WHERE timestamp >= ? ORDER BY timestamp ASC LIMIT ?` with `cutoff = now - 60d` and `LIMIT = ROUTINE_FORECAST_MAX_ROWS`.
- Per signal (`SIGNAL_HOUSE_STATE_CHANGED`): zero queries; incremental update from the payload only.
- Refresh interval: 1 hour. Worst-case daily query load: 24 × 1 = 24 reads. Compare to optimizer pre-rollback rate that triggered write-flood — this is read-only and trivially within budget.

---

## Files changed

| File | Change |
|---|---|
| `custom_components/universal_room_automation/domain_coordinators/routine_forecaster.py` | NEW. `RoutineForecaster` class: aggregate, predict, subscribe, refresh. ~150-200 LoC. |
| `custom_components/universal_room_automation/domain_coordinators/presence.py` | Instantiate + own lifecycle of `RoutineForecaster`; delegate `get_next_state_prediction()`. ~30 LoC delta. |
| `custom_components/universal_room_automation/database.py` | Add `fetch_house_state_log_since(since_iso, limit) -> list[Row]`. ~25 LoC. Mirror `count_house_state_changes_since()` style. |
| `custom_components/universal_room_automation/const.py` | 5 new constants (above). |
| `quality/tests/test_routine_forecaster.py` | NEW. Aggregation, vocab-collapse, min-support fallback, guest passthrough, boot-settle gating, signal-subscription cleanup. |
| `quality/tests/test_v4_6_9_next_state_sensor.py` | Update placeholder-shape assertions to allow forecaster output (still emits the same KEYS; only the `model` value + `state`/`confidence` change). |

NO changes to: `sensor.py` (PWA contract unchanged), `signals.py`, `config_flow.py`, `options_flow.py`, any other coordinator.

---

## Deliverables

### D1: `RoutineForecaster` class
New module `domain_coordinators/routine_forecaster.py`. Owns aggregation dict, exposes `predict(current_state: HouseState) -> dict`, subscribes to signal, schedules refresh.

**Acceptance Criteria**
- **Verify:** aggregator keyed by `(prev_state_str, day_type, time_bin)` — type-annotated dict.
- **Verify:** `predict()` returns exactly the D1 contract keys: `state, confidence, predicted_at_iso, model, current_state, transition_eta_minutes`.
- **Verify:** insufficient support (< `ROUTINE_FORECAST_MIN_SUPPORT`) → `state="unknown", confidence=0.0` (NEVER fabricate).
- **Verify:** vocab collapse table (§3) applied at output boundary only.
- **Verify:** guest/vacation passthrough: current_state GUEST → output GUEST + 0.3 + None.
- **Test:** `test_routine_forecaster.py::test_argmax_with_sufficient_support` — seed 10 transitions, assert correct argmax + confidence within 0.05 of empirical fraction.
- **Test:** `test_routine_forecaster.py::test_thin_cell_falls_back_then_unknown` — cell with 2 obs falls back to (state,*,*); empty DB returns unknown/0.0.
- **Test:** `test_routine_forecaster.py::test_vocab_collapse` — home_evening + waking + arriving collapse correctly; off-diagonal preferred when argmax == current.
- **Test:** `test_routine_forecaster.py::test_guest_vacation_excluded_from_non_guest_cells` — aggregation skip.
- **Live:** `sensor.ura_presence_coordinator_next_state` shows a non-`unknown` state with `confidence > 0.0` within `ROUTINE_FORECAST_REFRESH_SECONDS + 60s` of restart (post-boot-settle).
- **Live:** `model` attribute equals `"house_state_log_freq_v1"` (or `"…+guest_passthrough"` during guest_mode).

### D2: `database.py` reader
New `fetch_house_state_log_since(since_iso: str, limit: int) -> list[dict]` returning rows with `timestamp, state, previous_state, confidence`.

**Acceptance Criteria**
- **Verify:** uses existing `_db()` async context; `ORDER BY timestamp ASC`; `LIMIT ?` parameterized.
- **Verify:** returns `[]` on exception (matches `count_house_state_changes_since` failure mode).
- **Test:** `test_routine_forecaster.py::test_db_reader_bounded` — seed 6000 rows, fetch with limit=5000 returns 5000 oldest-in-window.
- **Test:** asserts no `INSERT`/`UPDATE`/`DELETE` in the new method (read-only invariant — grep test).
- **Live:** zero new rows written to any table by forecaster (verify via row-count delta on `house_state_log` matches transition count from presence, unchanged from pre-deploy baseline).

### D3: PresenceCoordinator wiring
Instantiate `RoutineForecaster` in `async_setup()` after L1867 hydration; delegate `get_next_state_prediction()` to it; cancel refresh timer in coordinator shutdown.

**Acceptance Criteria**
- **Verify:** `self._routine_forecaster` is `None` until `async_setup()` completes; placeholder shape returned in interim.
- **Verify:** `async_track_time_interval` callback registered with `async_on_remove`-equivalent cancellation; no untracked tasks (Bug Class #19).
- **Verify:** boot-settle gate (`self._boot_settle_done`) consulted before emitting non-AWAY confident prediction.
- **Test:** `test_routine_forecaster.py::test_coordinator_lifecycle_cancels_refresh` — mock `async_track_time_interval`, assert cancel called on shutdown.
- **Test:** `test_routine_forecaster.py::test_boot_settle_suppresses_high_confidence` — `_boot_settle_done=False` returns `unknown` regardless of aggregate state.
- **Live:** HA restart → no `ERROR ... routine_forecaster` in `home-assistant.log` for 30 min post-restart.
- **Live:** parent integration reload does NOT leak a second time-interval task (HA dev-tools: count of pending `async_track_time_interval` callbacks stable across reload).

### D4: PWA contract preservation
Existing `PresenceNextStateSensor` must continue to validate state via `_NextStateVocab` and present stable attribute keys.

**Acceptance Criteria**
- **Verify:** `_NextStateVocab(predicted_state)` never raises (every output of forecaster collapse table is in vocab).
- **Test:** `test_v4_6_9_next_state_sensor.py` continues passing; assertions updated only for `model` value, not shape.
- **Live:** PWA "Next State" tile renders non-`unknown` value within 1 refresh cycle post-deploy with no `"—"`/null/raw HouseState leakage.
- **Live (day-after):** `transition_eta_minutes` is a plausible int in the range 5..720 (5min..12h) for at least one prediction observed in a 24h window — sanity check that we're not emitting microsecond-converted nonsense or hours-converted minutes confusion.

### D5: Documentation
Strike the TODO at `presence.py:1666-1669`; replace with a paragraph pointing to `routine_forecaster.py` + the model id + the fallback contract. Update `docs/Coordinator/PRESENCE_COORDINATOR.md` with a "Next-state forecaster" subsection.

**Acceptance Criteria**
- **Verify:** no remaining `TODO(v4.7.x)` for routine_forecaster.
- **Verify:** `placeholder_v0` string remains ONLY as fallback in `get_next_state_prediction()` for the `self._routine_forecaster is None` branch (graceful degrade).

---

## Edge cases / QUALITY_CONTEXT.md classes considered

- **#1 coordinator lifecycle:** `async_setup()` order + shutdown timer cancellation (D3).
- **#7 stale data source:** refresh cadence + signal-driven incremental update; never serve a prediction from cache older than refresh interval + 1 (timestamp-check in `predict()` — returns `unknown` if last refresh > 2× cadence ago).
- **#14 config staleness:** no config — constants only.
- **#19 untracked background tasks:** `async_track_time_interval` cancel path + asserted in test.
- **#22 enum mismatch:** vocab collapse table is exhaustive over HouseState; `_NextStateVocab` validates on sensor side.
- **#23 observation mode gating:** if observation_mode is active, suppress signal-driven incremental update? — **No**: forecaster is read-only and the sensor is observation-safe; no actuation. Document explicitly.
- **#29 stable null:** `unknown / 0.0 / None` for thin cells; never `""` / `"—"` / `STATE_UNAVAILABLE`.
- **#34 function-local imports:** all `datetime`, `dt_util`, `_hour_to_time_bin` imports at module top of new file.
- **#37 stable attribute shape:** sensor side already handles; forecaster output keys are fixed.
- **#46 lazy derivation:** aggregation eagerly computed at refresh; argmax cached per cell; recomputed only when counts change.

---

## Non-goals (explicitly deferred)

- New Bayesian house-state model (operator vetoed 2026-06-09).
- Persisting HouseStateMachine across restart (separately decided-dropped).
- Per-person personalization (forecaster is household-level; per-person regime_status already exists).
- Optimization Coordinator consumption of the prediction (Phase 5+ work; this cycle only feeds the PWA sensor).

---

## Plan completion tracking

At end of cycle, document in `docs/readmes/README_v<version>.md`:
- Each acceptance criterion → PASS/FAIL/deferred with concrete evidence (entity attr, log line, DB row read).
- Any deferred LOWs per "Fix LOWs In-Cycle" feedback memo.
- D4 day-after `transition_eta_minutes` sanity criterion lands in the README only after the post-deploy 24h window — schedule the README write-back at that point per CLAUDE.md's "Record Live Validation Back Into the README" rule.
