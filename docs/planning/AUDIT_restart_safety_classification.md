# AUDIT — Restart Safety Classification

**Card:** `RESTART-SAFETY-DOCTRINE-1`
**Date:** 2026-08-21
**Scope:** custom_components/universal_room_automation/{domain_coordinators/*.py, coordinator.py, __init__.py, camera_census.py, bayesian_predictor.py, hvac_zones.py}
**Read-only audit.** No production code changed.

---

## Doctrine (frame — do not restate elsewhere)

Every coordinator instance attribute is exactly one of **PERSIST / RESET / REBUILD**.
`RESET` is a legitimate choice **only when a reason is stated AND the dropped
engagement is surfaced somewhere operator-visible** (exemplar:
`OverrideArrester._temp_arrester_override_active`, `hvac_override.py:292-306`).
**UNDECLARED is the bug.**

Hazard classes for the findings below:
- **(a) ACCUMULATOR** — needs N samples / event count / daily counter; restart resets the count.
- **(b) PENDING RETURN** — a timer that owes a restore; restart drops the debt.
- **(c) LIVE SUPPRESSION / LOCK** — a flag gating behaviour; fails in BOTH directions, correct answer differs per case.

---

## Two of the four cited instances are already correct — cite them

Before enumerating gaps, correct the audit brief on two of its four instances so
the doctrine generalises real defects rather than mislabelled correct code.

### Instance #2 (bayesian_accuracy) — **REFUTED at the persistence layer.**
- Beliefs restore path: `bayesian_predictor.py:163-197` (`initialize()` → `load_bayesian_beliefs` → `_restore_from_saved` at 199-224).
- Eval writes rows to DB: `__init__.py:2544-2547` calls `database.save_prediction_results_batch(batch_rows)` (schema at `database.py:6953`). Six fixed-time bins/day (`hour=[0,6,9,12,17,21]`, `__init__.py:2586-2593`).
- Sensor reads a rolling SQL window (README_v4.5.16.md:70).
- LLM optimizer's `bayesian_accuracy` field pulls from in-memory summary (`optimization_llm.py:755-770 _read_bayesian_summary`) rebuilt from the DB-restored beliefs → **REBUILD**.
- Classification: **PERSIST (rows) + REBUILD (in-memory summary)** — correctly wired end-to-end.
- The 2026-08-21 NM "empty" alert is **not** a restart-safety issue. The eval closure already warns "produced 0 rows" (`__init__.py:2560-2566`); root cause is downstream (room_id mismatch OR no predictions resolved at bin boundaries), **not** in-memory reset. **Do not fold into this doctrine's fix list.**

### Instance #3 (AC-ramp nudge restore) — **REFUTED.**
- In-flight nudge is written to `ac_reset_state` BEFORE the climate service call (schema at `database.py:1439-1441`: `in_flight_nudge_original_target`, `_started_ts`, `_duration_s`; save at `hvac_override.py:3134`).
- Startup audit at `hvac_override.py:3925-4080` (`async_startup_ramp_audit`) reads in-flight rows, restores immediately if `elapsed >= duration`, else reschedules `async_call_later` for `duration - elapsed`. Also guards against operator re-set during outage (HIGH-A2 second guard, 3980-4013) and against Temp-Arrester-suppressed writes (HIGH-A2 first guard, 3964-3978).
- Wired at `hvac.py` (per test `quality/tests/test_v4511_ac_energy_aware_ramp_down.py:740`).
- Documented in README_v4.5.11.md:47. Classification: **PERSIST (row) + REBUILD (timer)** — correctly wired. **Exemplar; not a defect.**

The AC-ramp path is the model the rest of the codebase should be measured against.

---

## Restart-interval denominator — UNVERIFIED

The audit brief asks for median restart interval via
`ssh ha "sqlite3 … ura_activity_log …"`. **I do not have shell access from this
environment**; the query cannot be executed here. What would settle it:

```
ssh ha "sqlite3 /config/universal_room_automation/data/universal_room_automation.db \"SELECT timestamp,description FROM ura_activity_log WHERE lower(description) LIKE '%boot%' OR lower(action) LIKE '%startup%' ORDER BY timestamp DESC LIMIT 40;\""
```

Complement with the HA `homeassistant_started` event history (recorder DB).

**Fallback proxy (not a substitute):** `docs/readmes/` shows 30 released
versions v5.64.0 → v5.85.1 by mtime; memory note dated 2026-07-29 records
"v5.31.1→v5.35.3 (12 deploys)" — a rate near 3-4 deploys/week. Each deploy
triggers HA restart via HACS install path. **Order-of-magnitude estimate: median
restart interval ≈ 1-3 days.** Treat as inference until the ssh query is run.

**Consequence for accumulators:**
- Metrics sampled at fast cadence (e.g. every decision cycle ~5 min) reach `MINIMUM_SAMPLES=24` in 2h → **FINE** under a 1-3 day median.
- Metrics sampled only on rare events (per-zone override, per-camera face arrival, per-house-state transition) can take days-to-weeks to reach 24 → **MARGINAL / UNREACHABLE**. Per-metric sample-cadence measurement (recorder DB) is required to sort each metric into a bucket — flagged as a follow-up probe below.

The audit-brief claim "3 of 5 HVAC anomaly metrics have never received a sample"
sits in this UNREACHABLE bucket **but is a `record_observation` wiring gap on
the metrics, not a restart-reset of `_baselines` per se** — `_baselines` IS
saved for the HVAC detector (see finding F1). Fixing the doctrine won't heal
those three metrics; a call-site audit will. Distinct card.

---

## What is already right (cite so the fix generalises existing good work)

| Item | File:line | Pattern |
|---|---|---|
| `ac_reset_state` — daily counters + in-flight nudge + lockout | `database.py:1439`, `hvac_override.py:3134`, `3925` (startup audit) | Per-zone-per-day row; startup restore |
| `DrainPrecedenceState` — snapshot/restore | `energy_drain_precedence.py` (`restore_from_blob`/`serialize_for_kv`) | KV blob |
| `EnergyBilling` daily rollups | `energy_billing.py:126-130` (attrs), `342-346` (restore) | Snapshot restore |
| `PeakAvoidance` PA-today | `energy_billing.py:474-476`, `702-704` | Snapshot restore |
| `HVACZones.restore_state_snapshot` | `hvac_zones.py:634-706` | Per-zone snapshot with 4h staleness gate |
| `AnomalyDetector.load_baselines / save_baselines` (base class) | `coordinator_diagnostics.py:1064`, `1144` | DB table `metric_baselines` |
| `OverrideArrester._temp_arrester_override_active` — **declared RESET** | `hvac_override.py:292-306` | Correct RESET decision with stated reason (default-OFF is safe); operator-facing switch surfaces engagement |
| Dedicated per-domain state tables | `egress_state`, `fan_recheck_state`, `regime_cell_state`, `energy_state`, `room_state` (grep `save_*_state` returns 27 sites across 8 files) | Table-per-domain snapshot |
| `BayesianPredictor` beliefs restore | `bayesian_predictor.py:163-197` | `load_bayesian_beliefs` → `_restore_from_saved` |
| `async_startup_ramp_audit` (AC nudge) | `hvac_override.py:3925` | Restore-on-boot with elapsed-time arithmetic |

The mechanism inventory is rich. What is missing is a **declaration convention**, not another persistence library.

---

## Findings — classification table

Only items where **current ≠ should-be**, or where the classification is
**undeclared**, are listed. Items that persist correctly are not repeated
(see "What is already right").

| # | Item | File:line | Current | Should be | Hazard | Persistence evidence |
|---|---|---|---|---|---|---|
| F1 | `AnomalyDetector._baselines` — **safety coordinator only** | `safety.py:1176` (load), no save call found (`rg 'save_baselines' safety.py` returns 0) | RESET (silently) | PERSIST | (a) | Base helper `save_baselines()` exists at `coordinator_diagnostics.py:1144`; safety.py loads but never calls save. Restart wipes every accumulator the safety detector has built. |
| F2 | `AnomalyDetector._baselines` — **setup detector** | `manager.py:428` (load), no save call in `manager.py` | RESET (silently) | PERSIST | (a) | Same shape as F1. |
| F3 | `AnomalyDetector._anomalies_today` | `coordinator_diagnostics.py:798` | RESET (in-memory, undeclared) | PERSIST if counter feeds a cap/rate-limit; else RESET WITH REASON | (a) | None. |
| F4 | `AnomalyDetector._anomaly_reset_date` | `coordinator_diagnostics.py:799` | RESET (undeclared) | PERSIST paired with F3 | (a) | None. Pairs with F3 — a restart makes the first sample of the day pointlessly reset F3 to 0 again. |
| F5 | `OverrideArrester._immune_holds` | `hvac_override.py:290` | RESET (in-memory, **code comment at 316-319 acknowledges "RESTART GAP" as documented, not persisted**) | PERSIST | (c) | None. The dropped ledger silently returns arrester jurisdiction over holds the operator explicitly marked immune. Real incident referenced in audit brief. |
| F6 | `OverrideArrester._temp_arrester_override_deferred_sunset` (pending flag, `hvac_override.py:307-319`) | RESET (**declared** in code comment: "obligation is lost and the override survives to max-age (6h)") | PERSIST | (b) | Declared-but-wrong: the acknowledged consequence ("override survives to max-age") is a real hazard because the invalidating transition already happened. A tri-state (`pending_sunset_state`) row in a small KV would close it. |
| F7 | `OverrideArrester._nudge_post_restore_ts` | `hvac_override.py:234` | RESET (**declared** in code comment: "known gap ... silently dropped from FP statistics") | PERSIST | (b) | Should ride alongside the in-flight-nudge row (F-related-exemplar: same table). Currently the ac_reset_state row survives restart but the post-restore timestamp used by the FP evaluator does not, so evaluator can't tell whether a restored nudge already discharged. |
| F8 | `ZoneState.override_count_today` | `hvac_zones.py:82`; snapshot at `hvac_zones.py:634-648` **excludes** it | RESET (in-memory, undeclared) | PERSIST | (a) | Consumed by `sensor.py:1451,1534,1574,11721` (override_penalty scoring + `overrides_today` sensor). Restart → penalty score jumps back to 100, "overrides_today" reads 0 across all zones. Sibling attrs also excluded: `ac_reset_count_today`, `camera_face_arrivals_today`, `last_override_direction`, `last_stuck_detected`. |
| F9 | `HVACPredict._pre_cool_triggered_today` / `_pre_heat_triggered_today` | `hvac_predict.py:107-108`; day-gate at 713 | RESET (undeclared) | PERSIST | (a) | Single-fire day-gate: after a restart the gate re-opens same day → duplicate pre-cool trigger possible. |
| F10 | `HVACPredict._pre_cool_active` | `hvac_predict.py:713` region | RESET (undeclared) | PERSIST or REBUILD from thermostat state | (b) | Mid-pre-cool restart leaves the "active" flag off while the setpoint change is still applied. |
| F11 | `SecurityCoordinator._alerts_today`, `_lock_checks_today` | `security.py:566-567`; reset at 2477-2478 | RESET (undeclared) | PERSIST if either feeds a rate-cap; else declare RESET | (a) | None. |
| F12 | `SecurityCoordinator._entry_history` (defaultdict(list) of datetimes) | `security.py:456` | RESET (undeclared) | REBUILD from recorder OR PERSIST as ring-buffer | (a) | Sliding-window entry pattern detection is inert immediately after restart. |
| F13 | `ManagerCoordinator._conflicts_resolved_today`, `_decisions_today` | `manager.py:190-191`; reset at 370-371 | RESET (undeclared) | RESET WITH REASON (display-only counters — probably safe) | (a) | None. If these ever feed an alert cap, promote to PERSIST. |
| F14 | `HVACCoordinator._d6_deferrals_today`, `_vacancy_sweeps_today`, `_pre_arrival_triggers_today` | `hvac.py:426,459,492`; reset at 1227-1228 | RESET (undeclared) | RESET WITH REASON (metric-y); PERSIST if consumed by cap | (a) | None. `_zone_state_save_counter` (499) is a cycle throttle — RESET is fine, declare. |
| F15 | `Optimization._action_dispatch_history: deque` | `optimization.py:525` | RESET (undeclared) | PERSIST OR REBUILD from `activity_log` | (a) | Dedupe / rate-limit window; if window > median restart interval the guard is effectively disabled after restart. |
| F16 | `HVACEgress._nm_emitted_today` (dedupe dict) | `hvac_egress.py:97` | RESET (undeclared) | PERSIST | (a) | Restart same-day → duplicate NM alerts possible for events already notified pre-restart. |
| F17 | `EnergyBattery._attain_soc_history` | `energy_battery.py:589`; capped at 3359 | RESET (undeclared) | PERSIST OR REBUILD from recorder | (a) | Trend detector empty immediately after restart; attain-eval degraded until list refills. |
| F18 | `EnergyCoordinator._peak_import_history` | `energy.py:587,1308,7044,8513` | Partial REBUILD (from recorder at 1308) but undeclared | Declare REBUILD explicitly + assert the recorder read is reached before any consumer | (a) | Good pattern, just undeclared. |
| F19 | `EnergyPool._power_sensor_unavail_count` (dict per evse) | `energy_pool.py:249` | RESET (undeclared) | RESET WITH REASON (consecutive-miss counter — transient signal, restart clears staleness) | (a) | Likely correct to reset; needs the declaration + one-line rationale. |
| F20 | `DynamicPreset._relax_ceiling_blocked_count` (dict per zone) | `dynamic_preset.py:366` | RESET (undeclared) | RESET WITH REASON OR PERSIST if feeds cap | (a) | None. |
| F21 | `Optimization._open_findings_count` | `optimization.py:575`, refill at 4393 | REBUILD (undeclared) | Declare REBUILD; assert refill runs pre-consumer | — | Correct pattern, just undeclared. |
| F22 | Pending-timer sweep (representative — see note below) | `hvac_override.py:{1395, 1817, 2292, 2359, 2446, 2785, 3166, 4080}`; `notification_manager.py:{2542, 2974, 4924}`; `perimeter_alert.py:{1538, 2859}`; `coordinator.py:{1317, 3444}` | Mix: some cancel on unload (correct); none persist their "owed restore" | Each needs one of: (i) RESET-safe by construction (short debounce/coalesce) — declare; (ii) PENDING-RETURN → PERSIST the pending obligation (see AC-ramp for the model) | (b) | Two clean models to replicate: `ac_reset_state` for typed obligations; the ARREST-SUNSET-1 comment (F6) already lays out the design shape. |

### Timer-handle sweep — representative, not exhaustive (per audit-brief permission)

- **Total `async_call_later` sites in the coordinator subtree: 60+ across 15 files** (from grep). Full enumeration deferred.
- Sample above is the load-bearing set (HVAC arrester grace/compromise/reset/comfort/nudge timers; NM repeat/cooldown; perimeter dispatch; coordinator debounce). Verdict pattern is uniform: **timer handles are cancelled on unload but the owed obligation is not persisted**. This is defensible for short-fuse debounces (5-30s) and indefensible for long-fuse obligations (grace timers minutes-hours; deferred sunsets; NM cooldowns).
- Recommendation: the declaration convention (below) forces per-timer classification; timers that survive as `RESET — short-fuse debounce, restart re-arms via <trigger>` need one comment line; timers that survive as `PERSIST via <table>` need the AC-ramp pattern.

---

## Counts

- **Findings:** 22 documented items + one representative timer-handle sweep row (F22) standing in for ~60 sites.
- **By hazard:** (a) ACCUMULATOR = 13 (F1, F2, F3, F4, F8, F9, F11, F12, F13, F14, F15, F16, F17, F19, F20 — 15 counting the declared-correct-but-undeclared cases; core-defect subset = F1, F2, F3, F8, F9, F12, F15, F16, F17 = **9**). (b) PENDING RETURN = 4 (F6, F7, F10, plus the F22 long-fuse subset). (c) LIVE SUPPRESSION / LOCK = 1 (F5).
- **Instances from the audit brief:** #1 (AnomalyDetector `_baselines`) → **partially correct** (HVAC/presence/music/security save; safety/manager do not: F1, F2). #2 (bayesian_accuracy) → **REFUTED** (persisted end-to-end). #3 (AC-ramp nudge) → **REFUTED** (exemplar). #4 (OverrideArrester) → **CONFIRMED** (F5 `_immune_holds` + F6 pending sunset + F8 `override_count_today`).
- **UNREACHABLE accumulators** (time-to-N > estimated median restart interval): **cannot classify per-metric without the recorder-cadence probe** (see follow-up below). Structurally at-risk given a 1-3 day median: F1 (safety detector metrics that fire only on safety events), F12 (`_entry_history` sliding window), F15 (`_action_dispatch_history` if the dedup window is >24h), and per-metric HVAC anomaly metrics the backlog already flags as never-sampled.

---

## Prioritised recommendation

**Priority 1 — CONFIRMED defects with operator-visible impact:**
1. **F5** `OverrideArrester._immune_holds` — real incident already occurred; the acknowledged RESTART GAP comment in the code is documentation of a defect, not a design.
2. **F8** `ZoneState.override_count_today` — silently zeros the override-penalty scoring and the `overrides_today` sensor on every deploy; misleads the operator into thinking arrester load dropped.
3. **F1 + F2** — safety and setup anomaly detectors: no save = accumulators never build; the whole detector is inert.
4. **F16** `_nm_emitted_today` — same-day post-restart duplicate NM alerts.

**Priority 2 — undeclared PENDING-RETURN with real discharge cost:**
5. **F6** deferred-sunset pending flag; **F7** nudge post-restore timestamp; **F10** pre-cool active flag.

**Priority 3 — declaration hygiene** (large but cheap):
6. All remaining rows: add a one-line `# restart: RESET — <reason>` OR `PERSIST via <table>` OR `REBUILD from <source>` next to the attribute.

---

## Primitive vs checklist — recommendation

**Argument from the evidence, not from taste.**

- The inventory of persistence mechanisms already present is diverse and each choice is fitted to shape: per-zone-per-day DB rows (`ac_reset_state`), snapshot-in-KV (`DrainPrecedenceState`), snapshot-dict-restore (`hvac_zones`), RestoreEntity (switches), `entry.options` write-through (Number entities), dedicated per-domain tables (5 of them). A single shared persistence primitive would be a rewrite that flattens correct fit-to-shape choices.
- The failures above are not caused by lack of a library. They are caused by **absence of a classification requirement at the attribute-declaration site**. Half the defects are one comment line and a one-line save.
- One narrow slice does merit a shared primitive: **the daily-counter cluster** (F3, F8, F11, F13, F14, F16 — six sites, all following the same rollover-at-midnight, reset-to-0 pattern). A `DailyCounter(name, persist: Literal["persist","reset"], reason: str)` helper on a mixin (or in `coordinator_diagnostics.py`, alongside `AnomalyDetector`) would (i) force the declaration at construction, (ii) collapse ~6 hand-rolled rollover routines into one, (iii) route the persistent variant through `ac_reset_state` or an analogous table so the AC-ramp pattern is reused, not re-implemented.

**Recommendation: CHECKLIST + one narrow primitive.**

1. **Doctrine repo-wide (CHECKLIST):** every `self._*` attribute in a coordinator `__init__` body MUST carry a `# restart: PERSIST via <table> | RESET — <reason> [surfaced via <entity>] | REBUILD from <source>` tag on the declaration line. A CI grep (`quality/tests/test_restart_declaration_coverage.py`) fails the build on any undeclared attribute in `domain_coordinators/*.py`. This is the minimum change that would have prevented every finding above from shipping silently.
2. **One shared primitive (DailyCounter):** collapse the daily-counter cluster into a helper that takes `persist=True|False` and `reason` at construction. Backfill the six confirmed sites to use it. Do NOT expand its scope beyond daily counters — the diversity of the other patterns is correct.
3. **Per-case cards** for F1, F2, F5, F6, F7, F8, F10, F16 — each is a small, targeted fix, not a doctrine cycle.

---

## Follow-up probes (not part of this audit, but named so they aren't lost)

- **P1** — Run the `ura_activity_log` restart-interval query. Attach the median + p90 to this doc.
- **P2** — Recorder cadence per accumulator: for each hazard-(a) attribute above, measure real sample rate (per hour) over 14d. Sort into FINE / MARGINAL / UNREACHABLE against P1's denominator. Only P2 can promote "structurally at-risk" (this doc) to "confirmed inert" (a defect).
- **P3** — Independent audit of `record_observation` call-site coverage on the HVAC AnomalyDetector to explain the backlog's "3 of 5 metrics never sampled" claim; this is a wiring gap, not a restart gap.
