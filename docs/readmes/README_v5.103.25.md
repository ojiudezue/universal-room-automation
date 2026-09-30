# v5.103.25: anomaly sensors stop saying "nominal" when they cannot see; "learning" now means actively collecting

**This release also carries v5.103.24 (Batch D: per-room Fan Mode, guest-fan fix, offline-thermostat hold) — see `README_v5.103.24.md`.**

**Cards:** `HVAC-ANOMALY-BLIND-1` residual A; `ANOMALY-SAVE-BASELINES-DICT-MUTATION-1` (folded in).
**Plan:** `docs/planning/PLANNING_anomaly_detector_blind_metrics.md` REV 2.1, plus the §14 Builder notes (operator rulings 2026-09-29).
**Branch:** `feature/anomaly-blind-metrics`. **Tier:** 2-DB (three framing-disjoint reviews).
**Version note:** the number may change at merge.

## 1. What changes for you

### The anomaly sensors tell you when part of them is blind
Five sensors share one detector design: HVAC, Presence, Security, Safety and Music Following anomaly. Until now each one said `nominal` as soon as about half of its measurements had enough data. It said that even when the other measurements had never received a single value.

Now all five use one shared rule, in this order:
1. **A real anomaly shows first** (`advisory`, `alert` or `critical`). This now also holds while the detector is still learning. Before, `learning` could hide a real anomaly.
2. **`learning`**, only while a measurement is actively collecting toward its minimum sample count.
3. **`partial`**, when at least one measurement cannot see:
   - it is declared but never wired;
   - it is wired but has never received data;
   - it has stopped collecting before reaching its minimum;
   - it is still learning while the rest of the detector is active.
4. **`nominal`**, only when every measurement has enough data.

`partial` is **not** an alarm. The severity, the Coordinator Summary `health_status`, and the PWA badge are unchanged. They still read severity only.

New attributes on each anomaly sensor (all additive):
- `coverage`: `full` or `partial`.
- `metrics_blind`: each blind measurement with its reason. The reasons are:
  - `not_wired`: declared on purpose, with no producer yet;
  - `never_fed`: a producer should exist but has sent nothing (a bug);
  - `learning`: collecting, not yet at its minimum;
  - `not_collecting`: below its minimum and no new value for 7 days.
- `metrics_unwired`: the measurements declared on purpose without a producer.
- `metrics_constant`: measurements with enough data that have never varied (variance exactly 0). They are **not** blind. Instead, any change on them fires at once. See the Music Following and Security notes below.
- Per measurement: `reason`, `suppressed`, `constant_baseline`, `best_scope` and `last_updated` (UTC).

### Zone-scoped measurements are counted
HVAC `short_cycle_rate` (per zone) and Presence `zone_occupied_count` (per zone) have plenty of data. The sensor used to look only at the whole-house row, which is empty, so it listed them as silent. Each measurement is now judged by its best-fed scope.

Reading a sensor also no longer creates empty "phantom" baseline rows in the database.

### "learning" means actively collecting (operator ruling 2026-09-29)
A measurement below its minimum that has had **no new value for 7 days** is now `not_collecting`, which makes the sensor `partial`. Before, it read `learning` forever.

- Safety is the example: `active_hazard_count` has 42 of 720 samples, and its last value is from 2026-09-04. It is recorded only when a hazard fires. Safety now shows `partial` with `active_hazard_count: not_collecting`, where it used to show `learning` forever.
- A detector where nothing is collecting and that is not yet active reports `learning_status: paused`.
- The 7 days is a reviewed code constant, `ANOMALY_LEARNING_STALL_DAYS`.

### Dashboards (applied at deploy by the orchestrator, not by this build)
- The v8 **URA Anomalies** list and the v7 anomaly list template no longer show `partial` sensors.
- The v8 Health view **Coordinators** card label gains ` · partial: …`, which names the coordinators with a blind measurement. The existing `mem …` and accuracy parts are kept.
- `learning` stays on the anomalies list (operator ruling), because it now appears only while something is really collecting.
- The legacy v4/v5 dashboards will show `partial` in red. This is accepted.
- The exact procedure and patch are in `docs/ha-config-snapshots/d6_anomaly_partial_dashboard_patch.py`:
  - back up first;
  - patch with the `config_hash`, never a whole-dashboard write;
  - locate cards by content;
  - `verify` allows exactly 3 changes.

### Diagnostic dump button now includes the anomaly summary
The **90 · Anomaly Subsystem Diagnostic Dump** button used to call a function that does not exist, so its anomaly section was always silently missing.
- It now includes `anomaly_summary`: the system summary with `coordinators_partial`, plus each coordinator's summary.
- If building that summary fails, `anomaly_summary_error` records why.

### What you will see after deploy (predicted from the 2026-09-29 measurements)

| Sensor | Before | After |
|---|---|---|
| HVAC anomaly | `nominal`, 2/5 active, short_cycle_rate "silent" | `partial`: comfort_deviation_hours and egress_pause_frequency `not_wired`; short_cycle_rate `ok` via its zones; 3/5 active |
| Security anomaly | `nominal`, 1/2 | `partial`: entry_anomaly_score `not_wired`; alert_trigger_frequency listed in `metrics_constant` |
| Presence anomaly | `nominal`, 2/3 | `nominal`, 3/3; `metrics_constant` empty |
| Safety anomaly | `learning` (42/720) | `partial`: active_hazard_count `not_collecting`; `learning_status: paused` |
| Music Following anomaly | `nominal` | `nominal`; both measurements in `metrics_constant` |

**Heads-up (not caused by this release).** Music Following's saved baseline is a legacy all-zero record from May, and Security's has never varied.
- One successful Music Following test transfer will very likely raise a **CRITICAL** Music Following anomaly (z = 10), which stays until restart.
- The same applies to Security on its first entry verdict that is not LOW.
- This is the pre-existing hair trigger. It is tracked on `MUSIC-FOLLOWING-NO-TRANSFERS-SINCE-MAY-1` and `SECURITY-ALERT-TRIGGER-METRIC-SHAPE-1`.

## 2. Measured before building
D0 probe (plan §2.3, run read-only by the orchestrator on 2026-09-29):
- HVAC: 2/5 active, 3 silent, 0 hvac `anomaly_log` rows in 30 days.
- Presence: 2/3 active. `zone_occupied_count` has 122,447 samples per zone but was listed silent.
- Security: 1/2 active. `entry_anomaly_score` was never fed. `alert_trigger_frequency` has variance 0.0 at n = 317.
- Safety: 42/720; last written 2026-09-04.
- Music Following: variance 0.0 on both measurements; last written 2026-05-12.
- Phantom rows (`sample_count = 0 AND last_updated IS NULL`): **5**.
- Presence variances: census 3.294; transitions 1358.371; zones 0.242 / 0.244 / 0.240 / 0.088 / 0.233. None is constant.

## 3. Tests
- **New:** `quality/tests/test_anomaly_coverage_blind_metrics.py` (41) and `quality/tests/test_anomaly_coverage_ctor_wiring.py` (6).
  - Every test drives the real `AnomalyDetector`, the real `native_value` of all 5 sensors, the real `CoordinatorManager`, and the real dump button.
  - The ctor tests run each coordinator's real setup up to detector construction.
  - Save/load tests use real aiosqlite with the production DDL.
- **INV-NOOP golden:**
  - `quality/fixtures/anomaly_noop_golden.json` was generated from `develop` @4233304dc **before** the build (commit `51437cf71`) by `quality/tests/_anomaly_noop_scenario.py`.
  - A house-only, all-ok detector gives byte-identical pre-existing summary keys, the same sensor state, and the same `save_baselines` rows.
- **Extended:** `test_v465_observability_gap.py::test_every_metric_is_wired_or_suppressed`. Each `*_UNWIRED_METRICS` must be a frozenset, a subset of the suppression set, and have no `record_observation` site.
- **Per-site mutation drills: 33 sites, 33 RED.** Each site was neutered alone, with `PYTHONDONTWRITEBYTECODE=1`, `__pycache__` cleared, the file restored, and `git status` confirmed clean. The sites cover:
  - the 5 sensor projections;
  - 3 roll-ups;
  - 5 ctor kwargs;
  - 3 non-creating read sites;
  - the `list(...)` save snapshot;
  - 2 dump-button drills;
  - 8 classifier/projection internals;
  - 2 meta-test drills;
  - 4 stall-rule drills.

  The table is in the build report.
- **Name-diff vs `develop`:**
  - `--isolate` over 255 files that touch a changed surface: **CLEAN, 0 new, 0 gone**.
  - Full suite: **CLEAN, 0 new, 0 gone** (153 pre-existing failing names on both sides).
- **Suite-order hygiene:** the first full run found 7 order-dependent failures in `test_house_state_rung2a.py`. That file stubs HA and imports `security.py` fresh, so it broke when the new test files had already imported the real module. The new files now import production modules in isolation and re-install them only while their own tests run (`_anomaly_noop_scenario.import_isolated`).

## 4. Live acceptance criteria (prospective — write the observed results back after the restart)

**Precondition query (run once at validation time).** Its result decides which branch of the MF and Security checks applies:
```sql
SELECT coordinator_id, metric_name, severity, timestamp FROM anomaly_log
WHERE coordinator_id IN ('music_following','security') AND timestamp >= '2026-09-29'
```

**`sensor.ura_hvac_coordinator_hvac_anomaly`**
- **Expected:**
  - state `partial`;
  - `metrics_blind == {comfort_deviation_hours: not_wired, egress_pause_frequency: not_wired}`;
  - `short_cycle_rate` not in `metrics_silent`, and its `reason` is `ok` with a `zone_*` `best_scope`;
  - `metrics_active_ratio == "3/5"`;
  - `metrics_unwired == ["comfort_deviation_hours", "egress_pause_frequency"]`.
- **Old code:** `nominal`, `2/5`, short_cycle_rate silent.
- **Half-fix:** `partial` with `short_cycle_rate: never_fed`.

**`sensor.ura_security_coordinator_security_anomaly`**
- **If there is no security row since D0:**
  - state `partial`;
  - `metrics_blind == {entry_anomaly_score: not_wired}` exactly;
  - `metrics_constant == ["alert_trigger_frequency"]`;
  - `metrics_unwired == ["entry_anomaly_score"]`.
- **If a row exists:**
  - state == that row's severity;
  - `alert_trigger_frequency.constant_baseline == false`;
  - `metrics_blind` unchanged.

**`sensor.ura_music_following_coordinator_music_following_anomaly`**
- **If there is no MF row since D0:** `nominal`; `metrics_constant` lists both measurements; `metrics_blind == {}`.
- **If the test transfer landed:** state == the persisted severity (expected `critical`); `transfer_success_rate.constant_baseline == false`; `metrics_blind == {}`.

**`sensor.ura_presence_coordinator_presence_anomaly`**
- **Expected:**
  - `nominal`;
  - `metrics_active_ratio == "3/3"`;
  - `zone_occupied_count` has `reason: ok` and a `zone:` `best_scope`;
  - `metrics_constant == []`.
- **Old code:** `2/3`, with zone_occupied_count silent.

**`sensor.ura_safety_coordinator_safety_anomaly`** *(operator ruling)*
- **Expected:**
  - `partial`;
  - `metrics_blind == {active_hazard_count: not_collecting}`;
  - `learning_status == "paused"`.
- **Old code:** `learning`.
- **Caveat:** if a hazard fired since the last boot, `metrics.active_hazard_count.last_updated` is recent and `learning` is the correct result.

**`sensor.ura_coordinator_manager_coordinator_summary`**
- **Expected:**
  - `status_per_coordinator.hvac.status == "nominal"` (severity) and `.hvac.coverage == "partial"`;
  - `.presence.coverage == "full"`;
  - `.safety.coverage == "partial"`;
  - `health_status` unchanged by coverage.

**DB (one-shot, after the next HVAC rollover save)**
- **Expected:** `SELECT count(*) FROM metric_baselines WHERE sample_count=0 AND last_updated IS NULL` stays **≤ 5** (the D0 value; it never grows).
- **If W3 has shipped:** no `(hvac, compressor_short_cycle_rate, house)` row ever exists.

**Dump button**
- Press **90 · Anomaly Subsystem Diagnostic Dump** once.
- **Expected:** the logged JSON contains `anomaly_summary.system_anomaly.coordinators_partial` whose set is `{"hvac", "safety", "security"}`, and there is **no** `anomaly_summary_error`.
- **Old code:** the section was absent.

**D6 (after the orchestrator applies it)**
- The pre-D6 backups are committed before the write.
- The `verify` diff shows exactly 3 changes.
- "URA Anomalies" does not list the HVAC, Security or Safety anomaly sensors while they are `partial`.
- The Coordinators label still begins with `mem ` and contains `partial: ` naming hvac, safety and security.
- The v5.103.22 zone `away_due_at` and arrester `grace_until` cards are still in live v8.

**Log scan**
- **Expected:** no new WARNING/ERROR from `coordinator_diagnostics`.
- A one-time "declared unwired but has data" warning would mean a declaration is stale. None is expected.

**Proven in-suite only:** the severity path is untouched (INV-NOOP golden and the precedence matrix). A live `anomaly_log` rate check is not used, because hvac has 0 rows in 30 days.

## 5. Not done / parked (accounted for)
- **D5, staleness of mature measurements:** parked. G-STALE could not be evaluated, because the D0 Q3 gap values were not recorded. The revival trigger is in plan §5 D5. The 2026-09-29 stall rule covers only below-minimum measurements.
- **Non-goals (plan §13), with their owning cards:**
  - wiring comfort_deviation_hours, egress_pause_frequency and entry_anomaly_score (`HVAC-COMFORT-DEVIATION-PRODUCER-1`, `ANOMALY-UNWIRED-METRIC-DISPOSITION-1`);
  - reshaping alert_trigger_frequency (`SECURITY-ALERT-TRIGGER-METRIC-SHAPE-1`);
  - Music Following revival and baseline reset (`MUSIC-FOLLOWING-NO-TRANSFERS-SINCE-MAY-1`);
  - Safety's unreachable 720 minimum (`SAFETY-ANOMALY-STRUCTURALLY-INERT-1`);
  - per-scope starvation detection;
  - saving baselines on restart (`ANOMALY-BASELINES-NEVER-SAVED-ON-RESTART-1`);
  - `max_samples` forgetting (`HVAC-BASELINE-MAXSAMPLES-1`, re-parked);
  - the PWA badge (`DASH-ANOMALY-COVERAGE-BADGE-1`);
  - a Coordinator Manager setup-detector sensor.
- **Known interplay (owned by `ANOMALY-BASELINES-NEVER-SAVED-ON-RESTART-1`).** Presence, Security, Safety and Music Following baselines are saved only when their config entry unloads, never on an HA restart. After a restart, a slow below-minimum measurement's last value reverts to its database time. It can therefore read `not_collecting` (and the sensor `partial`) until its next value arrives.
- **Cards to mint or update at dispatch (plan §9):** not done by the builder (no board edits). This covers the 5 new cards, the Music Following card extension, the dict-mutation card marked folded, and the MAXSAMPLES re-park.
