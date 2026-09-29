# PLANNING — Anomaly detector must not say "nominal" when it cannot see (shared AnomalyDetector coverage state)

**Date:** 2026-09-29 · **Author:** ura-planner · **Status:** **REV 2.1: APPROVED for build** once the orchestrator has checked the N-1…N-5 text edits. The re-check (`docs/reviews/code-review/plan_review_anomaly_detector_blind_metrics.md` § "Re-check (REV 2)") closed every round-1 finding. No further reviewer pass is needed.
**Cards:** `HVAC-ANOMALY-BLIND-1` (residual A, operator "Fix it" 2026-09-29), `ANOMALY-SAVE-BASELINES-DICT-MUTATION-1` (folded in, D1), `HVAC-BASELINE-MAXSAMPLES-1` (considered for merge, kept separate, §7). The persistence card **`ANOMALY-BASELINES-NEVER-SAVED-ON-RESTART-1`** (`kanban.data.yaml:30363`, orchestrator-minted) is referenced here, not planned.
**Operator question answered here:** "Do other coordinators have the same problem?" Yes: Security has the same problem and Presence has a scope variant of it. See §2.

## Revision table

| Rev | Date | Finding | Change |
|---|---|---|---|
| 1 | 2026-09-29 | — | Initial plan. D0 designed, not run |
| 2 | 2026-09-29 | **HIGH-2** "degenerate ⇒ blind" is wrong: std is floored at 0.1 (`coordinator_diagnostics.py:151-157`, z_score `:182-186`), so a constant baseline is hair-triggered, not blind | The orchestrator's D0 addendum rule is **withdrawn**. A constant baseline becomes an **annotation** (`constant_baseline`, `metrics_constant`) and never a blind reason (D1, §6). Security metric shape → card; MF idle/legacy → card |
| 2 | 2026-09-29 | **HIGH-1** D0 incomplete; G-PREDICT tripped; body contradicted addendum | §2.1 filled from the D0 output; new §2.3 (D0 results, measured numbers kept); G-PREDICT / G-STALE / G-PERSIST verdicts with deciding numbers; §6, §8, §9 and §12 reconciled with INV-COVERAGE |
| 2 | 2026-09-29 | **M1** persistence mechanism was wrong | §3 corrected: teardown saves never run on an HA restart (clean or not). This is a separate card, **not planned here** |
| 2 | 2026-09-29 | **M2** learning-first can mask a real anomaly | Precedence is now severity → learning → partial → nominal; INV-SEVERITY-PRECEDENCE loses its ACTIVE precondition |
| 2 | 2026-09-29 | **M3** `save_baselines` dict-mutation race is reachable today | The `list(self._baselines.items())` snapshot is folded into D1; the parked card's false premise is corrected in §3a |
| 2 | 2026-09-29 | **M4** classifier ambiguities | Reason precedence, "best scope" tie-break and `scope`-argument semantics are specified (D1) |
| 2 | 2026-09-29 | **LOW-1** dead `get_anomaly_summary` call in the dump button (`button.py:1486-1487`); roll-ups without a live reader | Folded in (D3b): the button calls `manager.get_diagnostics_summary()` |
| 2 | 2026-09-29 | **LOW-2** dashboard census incomplete | §4 adds v2, v3, v6, ura_diagnostics and the second v7 card |
| 2 | 2026-09-29 | **LOW-3** two live checks did not discriminate | §12: phantom-row count and the post-W3 key check; the vacuous ±25% on 0 is dropped |
| 2 | 2026-09-29 | **LOW-4 / LOW-5** synthetic entry + timestamp spec | D1/D3: the synthetic entry equals a fresh unstored `MetricBaseline`; `last_updated` is normalised to aware UTC |
| 2 | 2026-09-29 | **Operator ruling (dashboard)** | New **D6**: `partial` is excluded from the v8 "URA Anomalies" list and shown on the Health-view "Coordinators" card instead |
| 2.1 | 2026-09-29 | **N-1** D6 could overwrite the live v8 edits made at 00:53 (the zone `away_due_at` and arrester `grace_until` cards); the cited snapshot was stale | D6 procedure (edits fixed in the list below): pre-D6 backup of the live config; `patch`/`python_transform` + `config_hash`, never `config=`; cards located by content and asserted with `test` ops; hero label **appended**; post-write diff against the backup. §4 cites live JSON pointers |
| 2.1 | 2026-09-29 | **N-2** MF card was a duplicate; the MF/Security live criteria were fragile | Extend the existing `MUSIC-FOLLOWING-NO-TRANSFERS-SINCE-MAY-1`; the §12 MF/Security checks are conditional on no anomaly since D0 (one `anomaly_log` query); hair-trigger warning added (§9) |
| 2.1 | 2026-09-29 | **N-3** D3b failure path was silent | `except Exception as e: dump["anomaly_summary_error"] = repr(e)` (the `db_error` style) |
| 2.1 | 2026-09-29 | **N-4** expected outcome missing for a starved sibling scope | §6 states zone_1 mature + zone_2 at 0 → `ok` / `nominal`; per-scope starvation is a §13 non-goal |
| 2.1 | 2026-09-29 | **N-5** nits | Presence constant column filled (by shape; §2.1 note); §12 Presence expects `metrics_constant == []`; G-STALE reworded to "NOT EVALUABLE"; M1 card ID cited |

---

## 0. Headline

Every URA coordinator that owns an `AnomalyDetector` projects its sensor state the same way: aggregate `learning_status`, else `get_worst_severity()`. Neither input looks at whether each declared metric has data. Three defects in the shared primitive let a blind detector print `nominal`:

1. **The floor(n/2) gate.** ACTIVE needs only `max(1, n // 2)` mature metrics (`coordinator_diagnostics.py:1138`). That is 2 of 5 for HVAC and 1 of 2 for Security.
2. **Severity only sees anomalies that fired.** `get_worst_severity` returns NOMINAL when nothing has fired (`:1156-1158`). A metric with no data can never fire.
3. **Scope blindness.** Status reads use `scope="house"` (`:1132`, `:1193`, `:1229`) through `_get_baseline`, which creates the row if it is missing (`:1030-1039`). A zone-fed metric reads as silent, and a phantom `(metric, "house", 0)` row is created and then saved (`:1392`). This hits `hvac.short_cycle_rate` and `presence.zone_occupied_count`.

The fix goes in the shared detector:
- one state projection (`get_sensor_state`);
- one per-metric coverage classifier (`get_coverage`);
- non-creating reads;
- a declared "unwired" set.

The five duplicated projections become one call. Severity semantics are untouched: `manager.py` and the PWA badge still read severity. **A constant baseline is not blindness.** It is reported as an annotation.

---

## 1. Institutional context verified

### 1.1 Prior-art scan: REUSE or BUILD, per piece

| Piece | Verdict | Evidence |
|---|---|---|
| Per-metric silence data (`metrics_silent`, `metrics_active_ratio`) | **REUSE + FIX (scope-aware)** | `coordinator_diagnostics.py:1182-1197` (v4.5.14) |
| Per-metric maturation gate | **REUSE** `_min_samples_for` | `:999-1008` |
| Suppression registry (fed but muted) | **REUSE** `suppressed_metric_names` / `_persisted_active_anomalies` | `:934`, `:983-986`, `:1010-1023`; `hvac_const.py:1282`, `security.py:94`, `presence.py:159`, `safety.py:86`, `music_following.py:63` |
| Nested per-scope surface | **REUSE** D1b `scopes` pattern | `:1228-1255` (iterates existing keys only) |
| Variance floor, used to reason about constant baselines | **REUSE** `MetricBaseline._MIN_VARIANCE` / `.std` | `:151-157`. The annotation reads raw `variance == 0.0`, never `.std` (`.std` is ≥ 0.1, so a `.std == 0` test would never fire; Bug Class #53) |
| Sensor state projection | **BUILD** `AnomalyDetector.get_sensor_state()`, replacing 5 duplicates | `sensor.py:6213-6216`, `:6828-6831`, `:7791-7794`, `hvac.py:6820-6830`, `security.py:2478-2488`. Byte-identical logic, confirmed by the plan review; no existing helper |
| Per-metric coverage classifier | **BUILD** `AnomalyDetector.get_coverage()` | Grep `coverage\|blind\|unwired` in `coordinator_diagnostics.py`, `sensor.py`, `manager.py`, `base.py`: none |
| "Deliberately unwired" declaration | **BUILD** ctor `unwired_metric_names` + `*_UNWIRED_METRICS` | Today it lives inside `*_SUPPRESSED_FROM_PERSISTENCE` alongside "fed but degenerate shape" (`hvac_const.py:1254-1286`): two concepts under one name (Bug Class #63) |
| Non-mutating baseline lookup | **BUILD** `_scopes_for(metric)` | `_get_baseline` (`:1030`) creates rows on read |
| `save_baselines` snapshot | **REUSE** fix already specified on `ANOMALY-SAVE-BASELINES-DICT-MUTATION-1` | One line at `:1392` |
| Manager roll-up | **REUSE + additive key** | `manager.get_summary` (`manager.py:743-808`) is the live reader via `sensor.py:5426`. `get_system_anomaly_status` (`:888`) and `get_diagnostics_summary` (`:941`) get a reader through D3b |
| Diagnostic dump button | **KEEP + WIRE** | `button.py:1483-1489` calls the non-existent `manager.get_anomaly_summary` behind `hasattr`, so that section is silently empty today |
| Staleness | **PARKED** (G-STALE not evaluable, §2.3) | — |
| Baseline forgetting (`max_samples`) | **NOT MERGED** (§7) | — |
| Baseline persistence cadence | **NOT HERE**. `ANOMALY-BASELINES-NEVER-SAVED-ON-RESTART-1` | §3 |

### 1.2 Prior planning docs consulted
- `PLANNING_hvac_short_cycle_producer.md` (skim): the D1a/D1b/D1c detector edits and plan-review F6 (surfaces are not scope-aware).
- `PLANNING_hvac_w3_energy_aware.md` §5.4 / G0-Q10 (read): the `short_cycle_rate` → `compressor_short_cycle_rate` rename, about 14 days of learning, and orphan prune of the old rows.
- `AUDIT_restart_safety_classification.md` (via the RESTART-SAFETY-DOCTRINE-1 body): "in-memory AND event-driven".
- `PLANNING_v4.6.5_in_memory_anomaly_persistence.md` (header): the suppression doctrine.
- `README_v4.5.14.md`: the origin of `metrics_silent`.

### 1.3 Card / memory bodies pulled
- `HVAC-ANOMALY-BLIND-1` (full), `HVAC-BASELINE-MAXSAMPLES-1` (full), `ANOMALY-SAVE-BASELINES-DICT-MUTATION-1` (full), `RESTART-SAFETY-DOCTRINE-1` (instances, doctrine, DENOMINATOR_MEASURED).
- Memory: marginal-benefit pushback, measure-before-build, coincidental-equality split, hollow anchors, wire-in anchors.

### 1.4 Design docs read
- `HVAC_ARCHITECTURE_STATE_OF_PLAY.md`: not read end-to-end by the planner. **The plan reviewer read it completely (lines 1-552) and found no §10 claim about the anomaly sensor.** Its §11 W4 lists `ANOMALY-SAVE-BASELINES-DICT-MUTATION-1`, which is folded in here, so **the builder must update §11 in the same commit.** The builder still reads it in full before touching `hvac.py` / `hvac_const.py` (CLAUDE.md 5b).

### 1.5 Code surveyed
- `coordinator_diagnostics.py:43-58, 133-186, 915-1457`.
- The 6 AnomalyDetector construction sites.
- Every `record_observation` and `save_baselines` site (§2, §3).
- `sensor.py:6180-6240, 6800-6850, 7051-7094, 7765-7815, 12291-12335`; `base.py:241-265`; `manager.py:743-808, 888-953`; `button.py:1354-1494`.
- Live `.storage/lovelace.ura_v8` (Health view and anomalies card).

---

## 2. Step 1 — Measurement: every AnomalyDetector, every metric

### 2.0 Method
- Code: every producer site at file:line.
- D0 probe (§5 D0), run read-only by the orchestrator on 2026-09-29.
- DB freshness split from the plan review (`immutable=1` read, 2026-09-29).
- Dashboard census over the live `.storage` (Samba, text only).

### 2.1 Table (D0-filled)

| Coordinator | Metric | Producer, scope, cadence | Fed? | sample_count (live, 2026-09-29) | DB last_updated | Constant baseline (raw variance 0, n ≥ gate)? | Sensor state / attrs today |
|---|---|---|---|---|---|---|---|
| **hvac** | zone_call_frequency | `hvac.py:6716`, house, 5-min tick | YES | 4624 | 2026-09-29 04:55 (rollover save) | no | **`nominal`**, active **2/5**, silent: short_cycle_rate, comfort_deviation_hours, egress_pause_frequency. **0** hvac rows in `anomaly_log` in 30 d |
| hvac | override_frequency | `hvac.py:6760`, house, tick | YES | 4616 | ″ | no | ″ |
| hvac | short_cycle_rate | `hvac.py:6547`, zone_1/2/3, daily | YES (zone); house = 0 phantom | 15 / 15 / 15 zone; house 0 | ″ | no | listed silent: the scope bug |
| hvac | comfort_deviation_hours | none | **NEVER** | 0 | NULL (phantom-shaped row) | — | silent |
| hvac | egress_pause_frequency | none | **NEVER** | 0 | NULL | — | silent |
| **presence** | census_count | `presence.py:6810`, house, on house-state change | YES | 535 (DB 528) | **2026-09-14** | **no** (by shape: a varying head count; see note) | **`nominal`**, active **2/3** |
| presence | zone_occupied_count | `presence.py:7140`, `zone:<name>` | YES (zone); house = 0 phantom | 122,447 per zone | 2026-09-14 | **no** (by shape: 0/1 occupancy) | listed silent: the scope bug |
| presence | transition_count_daily | `presence.py:7215`, house, per transition | YES | mature (counted in 2/3) | 2026-09-14 | **no** (by shape: 1..N within a day) | the only severity-capable metric |
| **security** | alert_trigger_frequency | `security.py:916`, house, per entry intent | YES | 317 (DB 315) | **2026-09-04** | **YES**: mean 1.0, variance 0.0 (every verdict LOW) | **`nominal`**, active **1/2** |
| security | entry_anomaly_score | none | **NEVER** | 0 | NULL | — | silent |
| **safety** | active_hazard_count | `safety.py:2412`, only in `_respond_to_hazard`; gate 720 | rare-event | 42 / 720 | **2026-09-04** | not yet (n < gate; mean 1.0, variance 0.0) | **`learning`** |
| **music_following** | transfer_success_rate | `music_following.py:354`, per transfer (needs `music_attempts > 0`, `:339`) | **idle since 2026-05-12** | 1572 | **2026-05-12T04:48:24** (naive, pre-A-M2) | YES (mean 0.0, variance 0.0) | **`nominal`**, active **2/2** |
| music_following | cooldown_frequency | `music_following.py:383` | idle | 1572 | 2026-05-12 | YES (mean 0.0, variance 0.0) | ″ |
| **coordinator_manager** | setup_duration_seconds | `__init__.py:4226`, per boot, saved each time | YES | 367 | 2026-09-29 08:06 | no | **no sensor**. 27 `anomaly_log` rows in 30 d (restart storm): the only detector that fires |

**Note (N-5):** the D0 Q1 output printed raw variance for every Presence row, but the orchestrator's transcription in §2.3 did not carry those values. The Presence "no" entries are **derived from input shape**: none of the three producers can emit a single repeated value across hundreds of samples. §12 turns that into a discriminating live check (`metrics_constant == []`). **Orchestrator:** paste the three Presence variances from the D0 output here when checking these edits. If any is exactly 0.0, fix §8/§12 for Presence before build.

**Not AnomalyDetector-backed (out of scope):**
- the NM heuristic `notification_manager.py:845-867`;
- energy `MetricBaseline`s (`energy.py:876-895`, `energy_circuits.py:260`);
- the safety rate detector (`safety.py:681`);
- the Bayesian occupancy anomaly (`binary_sensor.py:3107-3239`).

### 2.2 Answer: do other coordinators have the same problem?
**Yes, so the fix goes in the shared detector.**
- **Security:** the HVAC laundering exactly. 1 of 2 metrics has never been fed and it still reads `nominal`.
- **Presence:** the scope variant. `zone_occupied_count` (122k samples per zone) is listed silent.
- **Safety:** honestly `learning` (42/720), but it will never finish (card).
- **Music following:** not a coverage problem. Its metrics have data, but the **feature has been idle since 2026-05-12** and its baselines are legacy pre-v4.6.5.2 (mean 0 over the old denominator). That is a **feature** problem, tracked on the existing `MUSIC-FOLLOWING-NO-TRANSFERS-SINCE-MAY-1` and kept out of the coverage logic.
- **CM:** no sensor.

### 2.3 D0 results (measured 2026-09-29 by the orchestrator; probe = §5 D0; numbers verbatim)
- **HVAC:** state `nominal`, active 2/5. Silent: short_cycle_rate (15 per zone; house row 0), comfort_deviation_hours 0, egress_pause_frequency 0. zone_call / override live 4624 / 4616. 0 hvac `anomaly_log` rows in 30 d.
- **Presence:** `nominal`, active 2/3. zone_occupied_count 122,447 per zone live, yet listed silent. DB baselines last written **2026-09-14**; census live 535 vs DB 528.
- **Security:** `nominal`, active 1/2. entry_anomaly_score never fed. alert_trigger_frequency: mean 1.0, **variance** 0.0, n = 317.
- **Safety:** `learning` 42/720; mean 1.0, variance 0.0; recorded only on hazard response.
- **Music following:** `nominal` 2/2; both metrics mean 0.0, variance 0.0, n = 1572, DB last updated 2026-05-12.
- **Coordinator manager:** setup_duration_seconds n = 367; 27 `anomaly_log` rows in 30 d.
- **Phantom-shaped rows** (`sample_count = 0 AND last_updated IS NULL`): **5**. hvac ×3 (short_cycle_rate@house, comfort_deviation_hours, egress_pause_frequency), presence ×1 (zone_occupied_count@house), security ×1 (entry_anomaly_score).

**WITHDRAWN: the addendum's "degenerate ⇒ blind" implication (HIGH-2).** "std 0.0" in the addendum is the raw `variance` column. The live `.std` property is floored at 0.1 (`:151-157`), so z = |d| / 0.1.
- For Security, the first non-LOW verdict records a score ≥ 2, giving z ≥ 10 → CRITICAL (the CRITICAL threshold is z ≥ 4 at sensitivity 1.0, `:923-925`). The metric is **hair-triggered, not blind**.
- Treating it as blind would pin Security to `partial` for good, even after `entry_anomaly_score` is disposed of. That kills the §8 forcing function and repeats the permanent-false-state failure GATE_2026_09_15 rejected.
- **Resolution:** annotate (`constant_baseline`), and card the real per-metric problems (§3).

**Gate verdicts:**

| Gate | Verdict | Deciding number |
|---|---|---|
| **G-PREDICT** | **Re-planned (fired under REV 1 because of the addendum).** With the annotation design, no sensor goes `partial` for a reason outside §3. Predictions in §8 | MF would have been `partial (degenerate)` under the addendum. Under REV 2 it is `nominal` + `metrics_constant: [transfer_success_rate, cooldown_frequency]` |
| **G-STALE** | **NOT EVALUABLE → D5 stays parked.** Q3 per-metric max-gap values were **not recorded** in the D0 output, so the gate had no input (not a "no-fire" result). The re-run probe now prints Q3 even when empty. The one cadence number available points at persistence loss, not at a producer stop: hvac zone_call_frequency went 2675 (09-16) → 4624 (09-29), i.e. **+1949 in about 13 days ≈ 150/day against about 288/day** for a 5-min tick. hvac saves only at the daily rollover, so in-RAM samples since that save are lost at every restart (≈2.9/day). That is consistent with `ANOMALY-BASELINES-NEVER-SAVED-ON-RESTART-1` (inference, not proof), and it is handed to that card | Q3 absent; 150/288 = 52% accrual |
| **G-PERSIST** | **FIRED.** Mechanism corrected (§3). Card: `ANOMALY-BASELINES-NEVER-SAVED-ON-RESTART-1` | Presence DB last_updated 2026-09-14 (15 d > 24 h); security and safety 2026-09-04 (25 d); vs hvac 09-29 04:55 and CM 09-29 08:06 (non-teardown save paths) |

---

## 3. Why each unfed metric is unfed, and whether it needs its own card

| Metric | Why | Class | Own card? |
|---|---|---|---|
| hvac.short_cycle_rate @house | Zone-scoped by design; the house row is a phantom created by `_get_baseline` on read | Projection bug | **No.** Fixed here (D1) |
| presence.zone_occupied_count @house | Same (zone scope `zone:<name>`) | Projection bug | **No.** Fixed here |
| hvac.comfort_deviation_hours | No producer ever built. The input (zone temp vs setpoint) exists. The daily per-zone emit + rollover-save pattern (short_cycle_rate) answers the "rare event-driven" objection | Producer absent, input present | **Yes, NEW** `HVAC-COMFORT-DEVIATION-PRODUCER-1` (Tier 2). This is the trip-wire for the zone-2 212-min +8°F excursion |
| hvac.egress_pause_frequency | Deferred in v4.7.8 §13 and never built; the input is a rare event | Producer absent; rare input | **Yes**, `ANOMALY-UNWIRED-METRIC-DISPOSITION-1` (with entry_anomaly_score). Recommendation: undeclare; the orphan prune `:1351-1372` cleans the row |
| security.entry_anomaly_score | Declared since v3.6.0, no producer; the entry verdicts already feed alert_trigger_frequency | Producer absent; redundant | Same disposition card. Recommendation: undeclare |
| **Not unfed, but a wrong shape:** security.alert_trigger_frequency | Records an ordinal per-event verdict score (`security.py:914-917`). A quiet house gives all-LOW, so variance is 0 and the next non-LOW verdict scores z ≥ 10 (CRITICAL). The first real alert is guaranteed to fire at CRITICAL, but the z-score only says "not LOW", which the verdict already says | Wrong input for a z-score model | **Yes, NEW** `SECURITY-ALERT-TRIGGER-METRIC-SHAPE-1`: e.g. a daily count of non-LOW verdicts. Annotated `constant_baseline` meanwhile |
| **Not a coverage issue:** music_following (both metrics) | No music transfer attempts since 2026-05-12 (the emit requires `music_attempts > 0`, `:339`); baselines are legacy pre-v4.6.5.2 (the docstring `:320-325` predicted the mean-0 drift). **Hair trigger (N-2):** MF metrics are not suppressed (`music_following.py:63`). One successful test transfer records `transfer_success_rate = 1.0` against mean 0 / variance 0, giving z = 1.0/0.1 = **10 → CRITICAL**. That writes a persisted `anomaly_log` row and the sensor reads `critical` until restart. **The legacy baseline causes this, not this cycle** | Feature idle / legacy baseline | **No new card: EXTEND the existing `MUSIC-FOLLOWING-NO-TRANSFERS-SINCE-MAY-1`** (`kanban.data.yaml:30379`, investigating; operator 2026-09-29: "Rarely use it. But will test today"). Add: legacy mean-0 baseline + hair-trigger → baseline reset as part of its resolution. Kept **out** of the coverage logic |
| safety.active_hazard_count | Only on hazard response; gate 720; 42 samples; constant 1.0 at record time | Accumulator unreachable, and a constant-shaped input | **Yes** `SAFETY-ANOMALY-STRUCTURALLY-INERT-1`: sample on the periodic check (`safety.py:2645`) so the value takes 0..N, or retire the metric |
| Teardown-only savers (presence, security, safety, MF, CM teardown) | **Corrected mechanism (M1).** HA does not unload config entries on stop: `ConfigEntries._async_shutdown` → `entry.async_shutdown()` only cancels a retry (per the review, venv HA 2026.2.3). URA registers no `EVENT_HOMEASSISTANT_STOP` / `FINAL_WRITE` listener. So `save_baselines` at `presence.py:7470`, `security.py:840`, `safety.py:3092`, `music_following.py:687`, `manager.py:488` runs **only on an entry unload/reload, never on an HA restart, clean or not**. The 2026-09-16 "21 s-apart freeze" is therefore more likely an entry reload than a clean shutdown (re-check it on that card) | Persistence lag, not unfed | **Separate card `ANOMALY-BASELINES-NEVER-SAVED-ON-RESTART-1` (`kanban.data.yaml:30363`). Not planned here.** Interplay: a slow metric on a teardown-only saver that matures in RAM reverts to `learning` at each boot, which is a nominal→partial flap per restart. This is not reachable today but it is reachable for a new event-driven metric. That card owns it |

### 3a. Correction to `ANOMALY-SAVE-BASELINES-DICT-MUTATION-1` (folded into D1)
- **The card's `why` says:** "NOT reachable from the new rollover save, because every place that adds a baseline in the HVAC coordinator runs under the decision-cycle lock."
- **That premise is false.** The sensor properties call `get_learning_status` / `get_status_summary` → `_get_baseline` (`:1132`, `:1193`, `:1229`) **outside the lock**, on `SIGNAL_HVAC_ENTITIES_UPDATE`-driven state writes, and create a key for any metric without a row.
- **Concrete repro after W3's rename:**
  1. The orphan prune drops the old rows.
  2. The rollover `record_observation` creates zone keys.
  3. A sensor read during the save's `await` creates `(compressor_short_cycle_rate, house)`.
  4. `RuntimeError: dictionary changed size during iteration` is swallowed (`:1412-1413`), and the save is partial.
- **What closes it:** D1's non-creating peek removes that trigger. The one-line snapshot closes the class against any future creator.
- The orchestrator should mark the card folded, with this corrected `why` (no board edits by the planner).

---

## 4. Consumers of the sensor state (producer / consumer check)

**Producers (all replaced by one shared call):** `sensor.py:6202-6216` (Presence), `:6818-6831` (Safety), `:7070-7078` → `security.py:2478-2488`, `:7781-7794` (MF), `:12309-12316` → `hvac.py:6820-6830`.

Live Lovelace locations are given as **JSON pointers into the live config** (N-1). The committed snapshot `docs/ha-config-snapshots/lovelace_ura_v8_backup_2026_09_29.json` (00:51) is **stale** against live v8 (00:53) and must not be used as a write base.

| Consumer | Location | Reads | Trust / display | Effect of `partial` |
|---|---|---|---|---|
| PWA Security / Presence / Safety tabs | `dashboard-v3/src/components/tabs/Security.tsx:44-45, 85, 331`; `Presence.tsx:49, 382`; `Safety.tsx:45, 59-72, 311` | raw state text (Safety `safetyCardCls`: unknown → no class) | display | Renders text; no breakage |
| PWA Diagnostics / Home | `Diagnostics.tsx:81-90`, `Home.tsx:570-575`, `data/statusColors.ts:22-52` | `status_per_coordinator[*].status` = **severity** (`manager.py:779`) | display | Unchanged. The badge change is carded (`DASH-ANOMALY-COVERAGE-BADGE-1`) |
| Coordinator summary sensor | `sensor.py:5426` → `manager.get_summary` | `status_per_coordinator` | display | Gains `coverage` (D3) and feeds D6 |
| **v8 "URA Anomalies"** auto-entities | live v8 `/views/6/sections/3/cards/1` (`custom:auto-entities`, title "URA Anomalies") | `sensor.ura_*_anomaly`, exclude `nominal` | display | **Operator ruling: `partial` is not an anomaly.** D6 adds the exclude |
| **v8 Health view "Coordinators"** hero | live v8 `/views/6/sections/1/cards/0` (`custom:button-card`, name "Coordinators") | `sensor.ura_coordinator_manager_coordinator_summary` | display | **D6 appends the partial-coverage field** |
| v8 tile | "HVAC Anomaly" tile in live v8 | state | display | Shows `partial` (intended) |
| v7 anomaly list | live v7 `/decluttering_templates/ura_anomaly_list/card` (exclude `nominal`) | — | display | D6 adds the same exclude |
| v7 auto-entities (2) | `.storage/lovelace.ura_v7:4022-4040` (no exclude) | lists all | display | Already lists nominal sensors; no change |
| v6 (sidebar) | `.storage/lovelace.ura_v6:1093, 2347` (entity rows), `:2809, 2823` (raw-text templates) | raw | display | Text only |
| v2 / v3 / ura_diagnostics | `lovelace.ura_v2:892`; `ura_v3:678, 834, 844`; `ura_diagnostics:630, 717, 786` | raw | display | Text only |
| Legacy v4 / v5 | `lovelace.ura_v4:3458, 3469, 3480, 3507`; `ura_v5:3431, 3442, 3453, 3480` | Jinja: `nominal`/`learning` → green, else red | display | `partial` shows **red**. Accepted (legacy); README notes it |
| HA automations / scripts / template helpers | `/Users/okosisi/ha-config/*.yaml` + `.storage` grep | none | — | None |
| NM / coordinators | `domain_coordinators/*` | `manager.py` reads `get_worst_severity()` | trust (roll-up) | Unchanged |
| Tests | `test_v4514_anomaly_visibility.py`, `test_v465_observability_gap.py:835, 1312` | summary keys / ctor | test | Updated (§5) |

**Conclusion:** no trust consumer reads the state string. `partial` is safe as long as severity stays untouched.

---

## 5. Deliverables

### D0 — Read-only measurement gate: **DONE 2026-09-29** (results §2.3)
The probe is kept for re-runs (this is the post-deploy baseline). **Change for re-runs:** print the Q3 gap dict even when empty, so a missing G-STALE input is visible. Q5 is added for the N-2 conditional checks in §12.

```python
import sqlite3, json
URA = "file:/config/universal_room_automation/data/universal_room_automation.db?mode=ro"
HA  = "file:/config/home-assistant_v2.db?mode=ro"
COORDS = ("hvac","presence","security","safety","music_following","coordinator_manager")
u = sqlite3.connect(URA, uri=True)
print("== Q1 metric_baselines")
for r in u.execute("SELECT coordinator_id,metric_name,scope,sample_count,round(mean,3),"
                   "variance,last_updated FROM metric_baselines WHERE coordinator_id IN "
                   "(%s) ORDER BY 1,2,3" % ",".join("?"*len(COORDS)), COORDS): print(r)
print("== Q1b phantom-shaped rows:", u.execute(
      "SELECT count(*) FROM metric_baselines WHERE sample_count=0 AND last_updated IS NULL").fetchone())
print("== Q4 anomaly_log 30d")
for r in u.execute("SELECT coordinator_id,metric_name,count(*),max(timestamp) FROM anomaly_log "
                   "WHERE timestamp>=datetime('now','-30 days') AND coordinator_id IN (%s) "
                   "GROUP BY 1,2" % ",".join("?"*len(COORDS)), COORDS): print(r)
print("== Q5 MF/security anomalies since D0 (2026-09-29)")
for r in u.execute("SELECT coordinator_id,metric_name,severity,timestamp FROM anomaly_log "
                   "WHERE coordinator_id IN ('music_following','security') "
                   "AND timestamp>='2026-09-29' ORDER BY timestamp"): print(r)
ENT = ["sensor.ura_hvac_coordinator_hvac_anomaly","sensor.ura_presence_coordinator_presence_anomaly",
       "sensor.ura_security_coordinator_security_anomaly","sensor.ura_safety_coordinator_safety_anomaly",
       "sensor.ura_music_following_coordinator_music_following_anomaly"]
h = sqlite3.connect(HA, uri=True)
Q = ("SELECT s.state,a.shared_attrs,s.last_updated_ts FROM states s JOIN states_meta m "
     "ON s.metadata_id=m.metadata_id LEFT JOIN state_attributes a ON s.attributes_id=a.attributes_id "
     "WHERE m.entity_id=? AND s.last_updated_ts>=strftime('%s','now','-7 days') ORDER BY s.last_updated_ts")
for e in ENT:
    rows = h.execute(Q,(e,)).fetchall()
    print("==", e, "rows7d", len(rows), "states", sorted({r[0] for r in rows}))
    if not rows: continue
    st, attrs, ts = rows[-1]; a = json.loads(attrs or "{}")
    print("  Q2 latest", st, a.get("learning_status"), a.get("metrics_active_ratio"), a.get("metrics_silent"),
          a.get("coverage"), a.get("metrics_blind"), a.get("metrics_constant"))
    for m, d in (a.get("metrics") or {}).items():
        print("   ", m, d.get("sample_count"), d.get("minimum_samples"), d.get("reason"),
              {k: v.get("sample_count") for k, v in (d.get("scopes") or {}).items()})
    last = {}; gap = {}
    for st, attrs, ts in rows:
        for m, d in (json.loads(attrs or "{}").get("metrics") or {}).items():
            n = d.get("sample_count")
            if m in last and n is not None and n != last[m][0]:
                gap[m] = max(gap.get(m, 0), ts - last[m][1]); last[m] = (n, ts)
            elif m not in last: last[m] = (n, ts)
    print("  Q3 max-gap-s", {m: round(g) for m, g in gap.items()} or "NONE (no increments seen)")
```

### D1 — Shared coverage classifier, non-mutating reads, save snapshot (`coordinator_diagnostics.py`)

**`_scopes_for(metric_name) -> dict[str, MetricBaseline]`**
- Returns the existing `self._baselines` entries for that metric. It **never creates**.

**Best scope (M4b)**
- The best scope is the existing scope with the **highest `sample_count`**. Ties go to the lexicographically smallest scope name (deterministic).
- If no scope exists, n = 0.
- A loaded phantom `(metric, house, 0)` row can never win over a fed zone row.
- **Consequence, by design (N-4):** a starved sibling scope (zone_1 mature, zone_2 at 0) is invisible at the top level. It shows only in the nested `scopes` detail (see §6 and §13).

**`get_coverage() -> dict`** (takes no `scope` argument and always aggregates across scopes). Per declared metric it returns `reason`, `suppressed`, `constant_baseline`, `best_scope`, `sample_count` (best) and `last_updated`.

- **Reasons (M4a).** Evaluate these top to bottom; the **first match wins**:
  1. `stale`: reserved; only if D5 ships.
  2. `ok`: best n ≥ `_min_samples_for(metric)`.
  3. `learning`: 0 < best n < gate.
  4. `not_wired`: best n == 0 and the metric is in `unwired_metric_names`.
  5. `never_fed`: best n == 0 and the metric is not declared unwired (a wired producer is starved, i.e. a bug).
- **Data-derived reasons win over the declaration.** If a metric is declared unwired but has data, its reason is `ok` / `learning`, and a **one-time WARNING** names the stale declaration (a per-detector flag, so there is no log spam). The D4 meta-test catches it in CI.
- **Annotations** (never a reason, never in the blind set):
  - `suppressed: bool` (fed but muted).
  - **`constant_baseline: bool`**: best-scope n ≥ gate **AND raw `variance == 0.0` exactly**. It reads the stored field, never `.std`. Exact zero cannot flap, because variance never returns to exactly 0 after a deviation. There is no ε and no knob.
- **Blind set** = reason ∈ {`learning`, `never_fed`, `not_wired`, `stale`}. Blindness is about **data**. Suppressed = muted; constant = hair-triggered. Neither is blind.

**Constructor**
- Adds `unwired_metric_names: Optional[frozenset[str]] = None` (empty by default).
- Entries not in `metric_names` are dropped with a WARNING at init.

**`scope` argument semantics (M4b)**
- `get_learning_status(scope)` and `get_status_summary(scope)`: when `scope == "house"` (the default, and the only value any production caller passes), `metrics_active_ratio`, `metrics_silent` and the ACTIVE/LEARNING count use **best-scope aggregation**.
- For any other explicit scope, they peek exactly that scope (pre-existing semantics, minus row creation).
- Every read path switches from `_get_baseline` to a peek.

**Synthetic entry (LOW-4)**
- When the requested-scope row is absent, the per-metric entry is built from a **fresh `MetricBaseline(metric, coordinator_id, scope)` that is not stored** (mean 0.0, std 1.0 from default variance 1.0, sample_count 0). This is exactly today's output, minus the insert.
- Per-metric `active` stays **requested-scope**. So `short_cycle_rate` shows `active: False` at the top level while `metrics_active_ratio` counts it; the per-metric `reason: ok` explains the difference.

**Other changes**
- `get_worst_metric` (`:1172-1177`) → `_persisted_active_anomalies()`. This is visible only to tests and the D3b dump (LOW-1).
- **`save_baselines`** (`:1392`) → `for _key, baseline in list(self._baselines.items()):` (M3; no happy-path behaviour change).
- **No change** to `record_observation`, `MetricBaseline.update`, `load_baselines`, `_classify_severity` or `get_worst_severity`.

#### Acceptance Criteria
- **Test:** `test_coverage_reasons_each_class`. A real detector with metrics covering ok / learning / never_fed / not_wired / suppressed-with-data / constant-mature. The oracle is an independently authored dict literal.
- **Test:** `test_declared_unwired_but_fed_reports_data_reason_and_warns_once`.
- **Test:** `test_constant_baseline_is_annotation_not_blind`. A real detector, one metric fed 30× the constant 1.0 (n ≥ gate=24). Assert: `reason == "ok"`, `constant_baseline is True`, the metric is not in `metrics_blind`, `get_sensor_state() == "nominal"`. Then record 3.0: assert an anomaly with severity CRITICAL (z = 20; the hair-trigger is documented in-test), `constant_baseline` becomes False, and the state becomes `critical`. **Discriminates** the withdrawn rule (which gives `partial`) from the adopted one.
- **Test:** `test_zone_scoped_metric_not_reported_silent`, including a loaded `(m, house, 0)` phantom alongside `(m, zone_1, ≥gate)`: the reason is `ok`, the best scope is `zone_1`.
- **Test:** `test_starved_sibling_scope_is_ok_by_design`. `(m, zone_1, ≥gate)` + `(m, zone_2, 0)` → reason `ok`, state `nominal`, and `scopes.zone_2.sample_count == 0` is visible in the summary (N-4).
- **Test:** `test_best_scope_tie_break_is_deterministic`.
- **Test:** `test_status_reads_do_not_create_baselines`. Call every read path, then assert `set(det._baselines)` is unchanged. **Drill:** revert any one read site to `_get_baseline` → RED.
- **Test:** `test_house_only_detector_summary_byte_identical`. The golden (pre-change output) is a committed fixture JSON generated from `develop` before the build. Covers pre-existing keys only.
- **Test:** `test_save_baselines_survives_concurrent_key_insert`. A real detector and an aiosqlite-backed fake whose `execute` inserts a new baseline key on its first await; assert every original row is written. **Drill:** remove `list(...)` → RED.
- **Test:** `test_worst_metric_excludes_suppressed`; `test_unwired_names_must_be_declared`.

### D2 — Shared sensor-state projection; replace the 5 duplicates

**`AnomalyDetector.get_sensor_state() -> str`**. Precedence (M2), top to bottom:
1. `get_worst_severity()` ≠ nominal → the severity.
2. `get_learning_status()` ∈ {insufficient_data, learning} → that value.
3. Blind set non-empty → **`partial`**.
4. Otherwise → `nominal`.

**Why severity-first is safe:**
- A persisted anomaly can only come from a mature metric (`record_observation` gates at `:1069`), so it is never a learning artifact.
- `_active_anomalies` latches until restart; the only clear site is `hvac.py:6538`.
- This ordering is byte-identical on the INV-NOOP domain.
- It is a behaviour change **only** where the aggregate says learning while a mature metric has a persisted anomaly. Today that state reads `learning` and masks the anomaly; now it shows the severity.

**The `partial` constant**
- `COVERAGE_PARTIAL = "partial"` is a module constant, **not** an `AnomalySeverity` member (Bug Class #22: it must stay out of `_SEVERITY_RANK` / `map_diag_severity`).

**Replace the duplicates**
- `sensor.py:6213-6216`, `:6828-6831`, `:7791-7794` → `…anomaly_detector.get_sensor_state()`.
- `hvac.py:6820-6830` and `security.py:2478-2488` keep their names (their callers are `sensor.py:12316` / `:7078`) and delegate.
- `not_configured` / `disabled` / `not_initialized` stay in their current layer.

#### Acceptance Criteria
- **Test:** `test_sensor_state_precedence_matrix` (real detector):

  | Situation | Expected state |
  |---|---|
  | aggregate learning + persisted advisory from a mature metric | `advisory` (M2) |
  | aggregate learning, no anomaly | `learning` |
  | active + advisory + blind | `advisory` |
  | active + blind only | `partial` |
  | active + constant-mature only | `nominal` |
  | all ok | `nominal` |
  | active + only a suppressed anomaly + blind | `partial` |

- **Test:** `test_all_five_sensors_route_through_get_sensor_state`. Behavioural: each sensor is built with a manager stub carrying a real blind-only detector, and `native_value == "partial"` for all 5. **Drill:** restore the old body at any ONE site → exactly that case goes RED.
- **Verify:** `grep -n "get_worst_severity().value" sensor.py hvac.py security.py` → 0 hits. Supplementary only.

### D3 — Additive attributes and roll-ups; dump-button wire (D3b)

**New `get_status_summary` keys** (all additive):
- `coverage` ("full" | "partial");
- `metrics_blind` ({metric: reason});
- `metrics_unwired` (list);
- `metrics_constant` (list);
- per-metric `reason`, `suppressed`, `constant_baseline`, `last_updated`.

**`last_updated` (LOW-5):** each scope's value is parsed with `dt_util.parse_datetime`. Naive values are treated as UTC. Unparseable or None values are skipped. The **max by parsed value** is emitted as an aware ISO `+00:00` string, or None. It is display only; no clock comparison.

**Roll-ups:**
- `manager.get_summary` → `status_per_coordinator[coord]["coverage"]`. This is **the live reader**, via `sensor.py:5426`. `status` stays severity.
- `manager.get_system_anomaly_status` → `coordinators_partial`.
- `base.get_diagnostics_summary` → `anomaly["coverage"]`, `anomaly["metrics_blind"]`.

**D3b.** Change `button.py:1484-1489`:
- Replace the dead `hasattr(manager, "get_anomaly_summary")` branch with `dump["anomaly_summary"] = manager.get_diagnostics_summary()` (it exists at `manager.py:941`).
- **Replace the silent `except Exception: pass` with `except Exception as e: dump["anomaly_summary_error"] = repr(e)`** (N-3). This follows the existing `db_error` capture pattern at `button.py:1463-1464`. D3b makes `get_diagnostics_summary` the first production reader of `get_system_anomaly_status`, `base.get_diagnostics_summary` and three subclass overrides (`presence.py:7707`, `safety.py:2743`, `music_following.py:698`), so a latent exception there must be visible in the dump.
- D3b must land with D1: its read paths are non-creating only after D1. They ship in the same cycle.

#### Acceptance Criteria
- **Test:** `test_manager_summary_status_unchanged_coverage_added`: blind-only → `status == "nominal"`, `coverage == "partial"`.
- **Test:** `test_system_anomaly_lists_partial_coordinators`.
- **Test:** `test_last_updated_mixed_naive_aware_normalised` (a naive `2026-05-12T04:48:24.220732` scope and an aware `+00:00` scope → the aware max is emitted).
- **Test:** `test_anomaly_dump_includes_diagnostics_summary`. Press the button with a real manager holding one detector; assert the logged JSON has `anomaly_summary.system_anomaly.coordinators_partial`. **Drill:** restore the dead `get_anomaly_summary` branch → RED.
- **Test:** `test_anomaly_dump_records_summary_error`. A coordinator whose `get_diagnostics_summary` raises; assert the logged JSON has `anomaly_summary_error` containing the exception repr. **Drill:** restore `pass` → RED.

### D4 — Declare the deliberately unwired metrics

**Constants:**
- `HVAC_UNWIRED_METRICS: Final = frozenset({"comfort_deviation_hours", "egress_pause_frequency"})` in `hvac_const.py`.
- `SECURITY_UNWIRED_METRICS = frozenset({"entry_anomaly_score"})` in `security.py`.
- Presence / Safety / MF: empty frozensets, declared explicitly.

**Ctor wiring:** pass `unwired_metric_names=` at `hvac.py:1670`, `security.py:765`, `safety.py:1166`, `music_following.py:238` and `presence.py:2369`. The CM detector (`manager.py:232`) gets none.

**Meta-tests:**
- Extend `test_every_metric_is_wired_or_suppressed` (`test_v465_observability_gap.py:835`) to check both: UNWIRED ⊆ SUPPRESSED, and no UNWIRED metric has a `record_observation` site.
- Add a behavioural ctor twin next to `:1312`, asserting `det._unwired_metric_names == CONST` per coordinator. **Drill:** delete the kwarg at one site → that case RED.

#### Acceptance Criteria
- **Test:** the two meta-tests + the drill result recorded in the build report.
- **Live:** HVAC `metrics_unwired == ["comfort_deviation_hours", "egress_pause_frequency"]`; Security `["entry_anomaly_score"]`.

### D5 — Staleness: **PARKED** (G-STALE not evaluable, §2.3)
Revival trigger (for the card): *"a D0 re-run records a Q3 max-gap > 3× cadence on a tick-driven metric that no `homeassistant_start` explains."*

If it is ever built:
- the spec is the REV 1 design: `max_silence_s_by_metric`;
- the boot grace is `detector_started_at`;
- tick metrics only;
- knob `HVAC_ANOMALY_TICK_MAX_SILENCE_S = 900`, rung 1.

### D6 — Dashboard: `partial` off the anomalies list, onto the health card (operator ruling; HA-side config, applied at deploy after the code ships)
**Operator ruling (2026-09-29):** `partial` is not an anomaly. It is shown on the coordinator health card instead. Default unless the operator objects.

**Procedure (N-1: the live v8 was edited at 00:53 today, after the 00:51 snapshot, with the zone `away_due_at` and arrester `grace_until` / `compromise_until` cards; a whole-dashboard write would silently revert them):**

1. **Back up the live configs first.**
   - `ha_config_get_dashboard(url_path="ura-v8")` and the same for v7. Use the live url_paths; confirm them from the dashboard list.
   - Save each verbatim as `docs/ha-config-snapshots/lovelace_ura_v8_backup_<date>_pre_d6.json` / `…_v7_…_pre_d6.json`.
   - **Commit both before any write.**
   - Keep the `config_hash` returned by each read.
2. **Write with `patch` (or `python_transform`) plus that `config_hash`.** **Never use `config=`**, which replaces the whole dashboard. The hash gives optimistic locking: if the dashboard changed since the read, the write fails and the procedure restarts at step 1.
3. **Locate the target cards by content, not by index or line number,** and assert them with `test` ops before any `add`/`replace`:
   - **v8 anomalies:** the `custom:auto-entities` card whose `card.title == "URA Anomalies"` (today `/views/6/sections/3/cards/1`). Test `type` + title, then **add** `{"state": "partial"}` to `filter.exclude` (append; the existing entries stay).
   - **v8 health hero:** the `custom:button-card` with `name == "Coordinators"` and `entity == "sensor.ura_coordinator_manager_coordinator_summary"` (today `/views/6/sections/1/cards/0`). Test `name` + `entity` + the current `label` string.
   - **v7 anomalies:** `/decluttering_templates/ura_anomaly_list/card`. Test its type and exclude list, then append the same `{"state": "partial"}` entry.
4. **Append the partial segment to the hero label. Do not replace the label.**
   - The current label returns `'mem '+…+ba` (the memory value plus Bayesian accuracy). The edit keeps that expression unchanged and adds one segment to the returned value: `… return 'mem '+(…)+ba+partialSeg;`
   - It declares before the return: `var s=(entity.attributes.status_per_coordinator)||{}; var p=Object.keys(s).filter(function(k){return (s[k]||{}).coverage==='partial';}); var partialSeg=p.length?' · partial: '+p.join(', '):'';`
   - The label uses plain words per the label style guide.
5. **Verify after the write.**
   - Re-read both dashboards and diff them semantically against the pre-D6 backups.
   - **The only differences allowed:** the v8 exclude entry, the v7 exclude entry and the v8 hero `label`.
   - If anything else differs, restore from the backup (with the fresh `config_hash`) and stop.
   - Then refresh the regular snapshot files.

The PWA badge stays a separate card (`DASH-ANOMALY-COVERAGE-BADGE-1`).

**Also for the operator (pre-existing, not changed here):** the v8 anomalies exclude has no `learning`, so Safety (`learning`, 42/720) is already listed there today. Is `learning` an anomaly? Decide alongside this ruling.

#### Acceptance Criteria
- **Verify:** the pre-D6 backups are committed before the write (git log shows the backup commit precedes any dashboard change).
- **Verify:** the post-write semantic diff against the backup shows exactly 3 changes (2 exclude entries, 1 label); it is recorded in the README.
- **Live:** the "URA Anomalies" card does **not** list `sensor.ura_hvac_coordinator_hvac_anomaly` while it is `partial`.
- **Live:** the Coordinators hero label still begins with `mem ` and contains `partial: hvac, security`.
- **Live:** the v5.103.22 zone `away_due_at` and arrester `grace_until` cards are still present in live v8.
- **Discriminates:** without D6 the Anomalies card lists both sensors. A label replace instead of append drops the `mem`/accuracy segments. A `config=` write from the stale snapshot drops the 00:53 cards.

---

## 6. Falsifiable invariants

> **INV-COVERAGE.** For every AnomalyDetector-backed anomaly sensor, in any reachable state, the sensor reports `nominal` **only if** every declared metric has a best-scope `sample_count ≥ _min_samples_for(metric)` (and is not `stale`, if D5 exists). If any declared metric fails that, the state ∈ {insufficient_data, learning, partial, advisory, alert, critical}, and `metrics_blind` names every such metric with its reason. **`constant_baseline` and `suppressed` never affect the state.**

> **INV-SEVERITY-PRECEDENCE.** If `get_worst_severity() ≠ nominal`, the state equals that severity, **whatever the learning status or coverage.**

> **INV-NOOP.** For a detector whose metrics are all house-scoped and all `ok` with an empty unwired set:
> - `get_sensor_state()` and every pre-existing `get_status_summary()` key/value equal the pre-change output;
> - no read path adds a key to `_baselines`;
> - `save_baselines` writes the same rows.

**Legal configurations for the build reviewer to try to break these with**, and the expected result:
- a metric declared unwired but fed → data reason plus a one-time warning;
- **zone_1 mature, zone_2 at 0 → expected `ok` / `nominal`.** The coverage unit is the metric, evaluated at its best scope. A starved sibling scope is visible only in the nested `scopes` detail, and **it is not an INV-COVERAGE leak** (per-scope starvation is a §13 non-goal);
- a `minimum_samples_by_metric` override lower than the scalar;
- a phantom `(metric, house, 0)` row loaded from the DB → it never wins the best scope;
- aggregate learning plus a persisted anomaly → the severity;
- a mature constant metric followed by a deviation → the severity, never `partial`;
- two scopes tied on `sample_count` → deterministic name tie-break;
- naive plus aware `last_updated` across the scopes of one metric → the aware max.

---

## 7. HVAC-BASELINE-MAXSAMPLES-1: **KEEP SEPARATE. Re-park with a new trigger.** (unchanged from REV 1; reviewer agreed)
- **Different accumulator path.** This plan touches no Welford/`update()` math. The only write-path edit is the M3 snapshot, which changes no behaviour.
- **The seasonal victim resets anyway.** W3's rename orphan-prunes the cooling-season short-cycle baseline.
- **New trigger:** *"after W3 ships, compressor_short_cycle_rate matures (≥14 per zone) and then crosses a heating↔cooling mode boundary, OR an hvac anomaly is traced to a baseline dominated by >90-day-old samples."*
- **Precondition to record on the card:** `load_baselines` does not restore `max_samples` (`:1340-1347`), so any cap must come from ctor config at both creation sites.

## 8. Predicted post-ship states (G-PREDICT, from D0)

| Sensor | Predicted state | Attributes that matter | Ends when |
|---|---|---|---|
| HVAC | **`partial`** | `metrics_blind {comfort_deviation_hours: not_wired, egress_pause_frequency: not_wired}`; short_cycle_rate `ok` via zone scope; active ratio **3/5**. After W3: plus `compressor_short_cycle_rate: learning` for about 14 days | `HVAC-COMFORT-DEVIATION-PRODUCER-1` + disposition card act |
| Security | **`partial`** (or its persisted severity if a non-LOW verdict has occurred since D0) | `metrics_blind {entry_anomaly_score: not_wired}`; `metrics_constant [alert_trigger_frequency]` | Disposition card undeclares entry_anomaly_score → **`nominal`** + constant annotation |
| Presence | **`nominal`** | active **3/3**; zone_occupied_count `ok` (122k, zone scope); `metrics_constant []` | — |
| Safety | **`learning`** (42/720) | unchanged | `SAFETY-ANOMALY-STRUCTURALLY-INERT-1` |
| MF | **`nominal`** (or **`critical`** if the operator's test transfer today lands; see §3 hair trigger) | `metrics_constant [transfer_success_rate, cooldown_frequency]` | `MUSIC-FOLLOWING-NO-TRANSFERS-SINCE-MAY-1` (feature decision + baseline reset) |

**Why `partial` on HVAC/Security is right:**
- It is truthful, and it has an exit: each has one card that ends it.
- It is **not** an alarm: severity, the manager roll-up and the PWA badge are unchanged, and D6 keeps it off the anomalies list.

**Rejected alternatives:**
- Excluding `not_wired` from the blind set would re-launder `nominal` (v4.5.14).
- Counting constant baselines as blind is the withdrawn addendum (HIGH-2).

## 9. Config-first / operator actions
- **Config-first:** no knob changes the projection. `CONF_*_ANOMALY_SENSITIVITY` only scales z-thresholds (`:963-966`). Code is required.
- **Operator:** D6 is the default per the ruling. Object before deploy if the Health-card placement is not wanted. Legacy v4/v5 dashboards will show `partial` in red; this is accepted and noted in the README. Also decide whether `learning` belongs on the anomalies list (§5 D6).
- **Warning to operator (N-2):** a Music Following test transfer today will very likely raise a **CRITICAL** MF anomaly (z = 10 against the legacy mean-0 / variance-0 baseline), persisted to `anomaly_log`, with the MF sensor showing `critical` until restart. That comes from the pre-existing hair trigger, **not from this cycle**. It is evidence for `MUSIC-FOLLOWING-NO-TRANSFERS-SINCE-MAY-1`, not a regression.
- **Cards to mint at build dispatch** (after the adjacency sweep):
  - `HVAC-COMFORT-DEVIATION-PRODUCER-1`
  - `ANOMALY-UNWIRED-METRIC-DISPOSITION-1`
  - `SAFETY-ANOMALY-STRUCTURALLY-INERT-1`
  - `SECURITY-ALERT-TRIGGER-METRIC-SHAPE-1`
  - `DASH-ANOMALY-COVERAGE-BADGE-1`
- **Card updates:**
  - **Extend** `MUSIC-FOLLOWING-NO-TRANSFERS-SINCE-MAY-1` with the legacy baseline + hair-trigger finding (no new MF card).
  - Mark `ANOMALY-SAVE-BASELINES-DICT-MUTATION-1` folded, with the corrected `why` (§3a).
  - Re-park `HVAC-BASELINE-MAXSAMPLES-1` with the §7 trigger.
  - Close HVAC-ANOMALY-BLIND-1 residual A on ship.
- `ANOMALY-BASELINES-NEVER-SAVED-ON-RESTART-1` (orchestrator-minted) is cross-referenced from the MF / Safety / Security cards.

## 10. Knob ladder
**No new behavioural number:**
- The blind rule is "any blind metric".
- `constant_baseline` is exact `variance == 0.0`. There is no ε, so no knob.
- The frozensets are declarations.
- The D5 constant exists only if D5 is ever built (rung 1).

## 11. Tier: **Tier 2-DB** (a shared primitive across 6 detectors; a state vocabulary change on 5 sensors and live dashboards; a summary payload shape change; plus the M3 one-line write-path snapshot)
- **Plan review:** done (round 1 FIX-PLAN-FIRST; re-check FIX-PLAN-FIRST text-only → REV 2.1 edits; APPROVE once the orchestrator has checked them).
- **Build reviews (3, disjoint):**
  - **A:** classifier correctness, reason precedence, best-scope tie-break, the constant annotation, and the §6 configs with their stated expectations.
  - **B:** shape/back-compat. The INV-NOOP golden; roll-ups; D3b dump + error capture; W3 interplay; no new phantom rows; the M3 snapshot is behaviour-neutral.
  - **C:** test authority. Real-detector anchors; per-site mutation at the 5 projection sites, 5 ctor kwargs, each read-site peek, the `list(...)` snapshot and D3b (both drills).
- **Not Tier 3:** no actuation, cost or safety path. Severity is unchanged by construction.
- **W3 sequencing:** tests use synthetic metric names, not `short_cycle_rate`. Whichever ships second rebases. Worktree `.claude/worktrees/<agent-id>-anomaly-coverage`.
- **HVAC state-of-play §11** is updated in the same commit (the M3 fold).

## 12. Live validation (feeds the README `Validated <date>` table)
Each check discriminates the fix from the old code and from a plausible half-fix.

**Precondition query (N-2), run once at validation time:**

```sql
SELECT coordinator_id, metric_name, severity, timestamp FROM anomaly_log
WHERE coordinator_id IN ('music_following','security') AND timestamp >= '2026-09-29'
```

(This is D0 Q5.) Its result decides which branch of the MF and Security checks below applies.

- **Live:** `sensor.ura_hvac_coordinator_hvac_anomaly`:
  - **Expected:** state `partial`; `metrics_blind == {comfort_deviation_hours: not_wired, egress_pause_frequency: not_wired}`; `short_cycle_rate` not in `metrics_silent`; `metrics_active_ratio == "3/5"`.
  - Old code: `nominal` / `2/5` / short_cycle_rate silent.
  - Half-fix (projection without the scope fix): `partial` + `short_cycle_rate: never_fed`.
- **Live:** `sensor.ura_security_coordinator_security_anomaly`:
  - **If no security row since D0:** state `partial`; `metrics_blind == {entry_anomaly_score: not_wired}` **exactly**; `metrics_constant == ["alert_trigger_frequency"]`. (The withdrawn degenerate rule would also put alert_trigger_frequency in `metrics_blind`.)
  - **If a non-LOW verdict has occurred (a row exists):** state == that row's persisted severity (INV-SEVERITY-PRECEDENCE); `alert_trigger_frequency.constant_baseline == false`; `metrics_blind` still `== {entry_anomaly_score: not_wired}`.
- **Live:** `sensor.ura_music_following_coordinator_music_following_anomaly`:
  - **If no MF row since D0:** state `nominal`; `metrics_constant` lists both metrics; `metrics_blind == {}`. (The withdrawn rule gives `partial`.)
  - **If the operator's test transfer landed (a row exists):** state == the persisted severity (expected `critical`, z = 10); `constant_baseline == false` on `transfer_success_rate`; `metrics_blind == {}`.
- **Live:** `sensor.ura_presence_coordinator_presence_anomaly`:
  - **Expected:** `nominal`; `metrics_active_ratio == "3/3"`; zone_occupied_count `reason: ok`, `best_scope` a `zone:` scope; **`metrics_constant == []`** (N-5).
  - Old code: `2/3` + silent.
- **Live:** `sensor.ura_safety_coordinator_safety_anomaly`: **expected** `learning` (unchanged).
- **Live:** `sensor.ura_coordinator_manager_coordinator_summary`:
  - **Expected:** `status_per_coordinator.hvac.status == "nominal"` (severity) and `.coverage == "partial"`; `.presence.coverage == "full"`.
- **Live (DB, one-shot, after the next HVAC rollover save):**
  - **Expected:** `SELECT count(*) FROM metric_baselines WHERE sample_count=0 AND last_updated IS NULL` is **≤ 5** (the D0 baseline; it never grows).
  - **If W3 has shipped:** no `(hvac, compressor_short_cycle_rate, house)` row ever exists. The old code creates it on the first sensor read and saves it at rollover.
- **Live:** the D6 checks (§5 D6), including that the 00:53 v8 cards survived.
- **Live:** press the Anomaly Subsystem Diagnostic Dump button once; the logged JSON contains `anomaly_summary.system_anomaly.coordinators_partial` = `["hvac", "security"]`, and **no** `anomaly_summary_error` key. Today that section is silently absent.
- **Proven in-suite only:** the severity path is untouched (INV-NOOP golden + precedence matrix). A live `anomaly_log` rate check is not used: hvac has 0 rows in 30 d, so ±25% of 0 is vacuous.
- **Log scan:** no new WARNING/ERROR from `coordinator_diagnostics`, except any one-time "declared unwired but fed" warning. **Expected: zero.**

## 13. Non-goals (explicit)
- Wiring comfort_deviation_hours / egress_pause_frequency / entry_anomaly_score.
- Reshaping alert_trigger_frequency.
- MF feature revival (`MUSIC-FOLLOWING-NO-TRANSFERS-SINCE-MAY-1`).
- Safety's unreachable gate.
- **Per-scope starvation detection** (N-4): a starved sibling scope of a metric that is mature elsewhere does not make the sensor `partial`. It is visible only in the nested `scopes` detail. Revisit only if a zone-level producer outage is ever missed because of it.
- **Baseline save cadence on restart (`ANOMALY-BASELINES-NEVER-SAVED-ON-RESTART-1`).**
- `max_samples` forgetting.
- The PWA badge / `status_per_coordinator.status` semantics.
- A CM setup-detector sensor.
- Whether `learning` belongs on the v8 anomalies list (operator question, §9).
