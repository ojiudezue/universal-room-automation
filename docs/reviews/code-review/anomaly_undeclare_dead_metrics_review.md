# Review: ANOMALY-METRIC-DISPOSITION-1 slices (a)+(b): undeclare dead anomaly metrics

- **Branch:** `fix/anomaly-undeclare-dead-metrics` @ `26b79e7c`
- **Diff base:** `develop...branch` (three-dot); merge-base = develop tip `067f97c2` (verified)
- **Tier:** 1 (hotfix, display/diagnostic only)
- **Framing:** A (local correctness + blast radius + consumers)
- **Reviewer read:** `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` read completely (mandatory for HVAC-touching work). No §10 claim is re-asserted. The new 2026-11-06 header line matches the code.
- **Verdict: SHIP**

## Scope of change

- `hvac_const.py`: `egress_pause_frequency` removed from `HVAC_METRICS` (:1300), `HVAC_SUPPRESSED_FROM_PERSISTENCE` (:1345) and `HVAC_UNWIRED_METRICS` (:1359). `HVAC_UNWIRED_METRICS` is now `{comfort_deviation_hours}`.
- `security.py`: `SECURITY_METRICS = ["alert_trigger_frequency"]` (:91). `SECURITY_SUPPRESSED_FROM_PERSISTENCE` (:111) and `SECURITY_UNWIRED_METRICS` (:121) are now empty frozensets and kept defined.
- Tests: two source-grep tests deleted, one ctor-wiring probe re-pointed, one new behavioural test file added.

## Check 1: consumers

Repo-wide grep of both names and all six constants (`custom_components`, `quality`, `scripts`):

| Consumer | file:line | Effect |
|---|---|---|
| HVAC detector ctor | `hvac.py:1825/1831/1833` | Passes the three constants. No indexing. |
| Security detector ctor | `security.py:791/794/796` | Passes the three constants. No indexing. |
| `AnomalyDetector.__init__` suppressed | `coordinator_diagnostics.py:1056-1059` | An empty frozenset is valid (it is not None, so it is used as-is). `_persisted_active_anomalies` short-circuits on empty (:1118). |
| `AnomalyDetector.__init__` unwired | `coordinator_diagnostics.py:1072-1080` | `frozenset(())` gives an empty undeclared diff, so no warning. Same shape as presence/safety/music_following, which already pass empty sets. |
| `get_learning_status` | `coordinator_diagnostics.py:1408+` | Threshold `max(1, floor(n/2))` is 1 for both n=2 (old) and n=1 (new), so the threshold does not change. |
| Hard-coded literals | none | No `SECURITY_METRICS[1]`, no `len(SECURITY_METRICS)`, no `HVAC_METRICS[i]` anywhere (grep). |
| Other literal references to the two names | none outside the diffed files | grep result: only the diffed source, tests and docs. |

Nothing breaks or changes meaning when the Security sets become empty.

## Check 2: live data and the prune

Live DB read 2026-11-06 (immutable snapshot of the Samba-mounted DB):

```
hvac|comfort_deviation_hours|house|0
hvac|egress_pause_frequency|house|0
hvac|override_frequency|house|15617
hvac|short_cycle_rate|house|0 ; zone_1/2/3|53 each
hvac|zone_call_frequency|house|15650
security|alert_trigger_frequency|house|410 (variance 0.0)
security|entry_anomaly_score|house|0
anomaly_log rows with either metric_name: 0
```

The prune (`coordinator_diagnostics.py:1716-1747`) only marks rows whose `metric_name` is not in `metric_names` as orphans. Its DELETE is `WHERE coordinator_id = ? AND metric_name IN (...)`, and the SELECT is scoped to the same `coordinator_id` (`'security'` at `security.py:537`, `HVAC_COORDINATOR_ID` for HVAC). So it deletes exactly `security|entry_anomaly_score|house` and `hvac|egress_pause_frequency|house`. `alert_trigger_frequency` is in the valid set and cannot be matched, and no other coordinator's rows are touched. `anomaly_log` has no rows for either name, so nothing is orphaned there. Both detectors call `load_baselines()` at setup (`security.py:799`, `hvac.py:1842`). The prune is one batched statement on the write queue, and a failure there is non-fatal and retried at the next load (pre-existing).

## Check 3: predicted live behaviour after restart

- **Security:** `alert_trigger_frequency` has n=410, which is at least the default gate of 24 (`MINIMUM_SAMPLES`, :988), so its coverage reason is `ok`. Variance 0.0 makes `constant_baseline` True, which is an annotation only (:1291) and not a blind reason. There are no blind metrics, so `get_coverage_state` returns `full`. In `get_sensor_state` (:1314), severity is nominal (absent an active anomaly) and learning is ACTIVE, so the state is `nominal`. **The prediction is correct.**
- **HVAC:** `comfort_deviation_hours` has n=0 and is declared unwired, so its reason is `not_wired`. `short_cycle_rate` has n=53 at its best (zone) scope and is ok under its 14-day override. `override_frequency` and `zone_call_frequency` are ok. The sensor reads `partial`, and its only blind metric is `comfort_deviation_hours` (not_wired). **The prediction is correct.**
- **Downstream of partial to nominal/full:**
  - `manager.py:1196` adds a `coverage` key to the per-coordinator summary. The comment there says it is additive and that the PWA badge and `health_status` key off severity, not coverage.
  - `manager.py:1349` builds a `coordinators_partial` list. It is display only, and `security` drops out of it.
  - `base.py:262` passes coverage through to diagnostics.
  - `sensor.py:7777` (`== "partial"`) is the security *armed-aggregator* icon. It is a different value domain and is not affected.
  - No NM, optimizer or decision path reads the coverage or partial state.

## Check 4: tests

- **Deleted tests:** `test_security_metrics_entry_anomaly_score_suppressed` and `test_v478_fixup_C_M1_egress_pause_frequency_in_suppressed_set` were source greps (Bug Class #62, hollow anchors). Their purpose (each declared metric is either wired or suppressed and unwired) has no subject left now that the metrics are gone. The structural meta-tests in `test_v465_observability_gap.py` (unwired is a subset of suppressed, no `record_observation` site) still run over the remaining sets and pass. The new declaration tests pin the removal behaviourally. **Nothing of value was lost.**
- **New tests drive the real prune:** `_run_prune` builds a real `AnomalyDetector` from the coordinator's own METRICS constant over a real `UniversalRoomDatabase` (initialize, start the write worker, seed rows) and calls the production `load_baselines()`. It is not a re-implementation, and it asserts both deletion and survival of the kept metric.
- **Ctor-wiring probe re-point** (`entry_anomaly_score` → `alert_trigger_frequency`): this is correct and follows the existing pattern for empty-set coordinators, where a real metric is the non-empty probe (Bug Class #63 guard, file comment :88-92).
- **Run:** the four target files gave `103 passed`.
- **Drill:** I re-added `entry_anomaly_score` to `SECURITY_METRICS`, which turned three tests RED (`test_security_declared_metrics_exclude_entry_anomaly_score`, `test_security_prune_drops_entry_anomaly_score_row`, `test_security_coverage_no_longer_lists_entry_anomaly_score`). I then restored the file and confirmed with `git status` that the tree is clean.

## Findings

| # | Sev | Class | file:line | Finding | Disposition |
|---|---|---|---|---|---|
| A-L1 | LOW (pre-existing, informational) | #63 coincidental equality / hair-trigger | live `security|alert_trigger_frequency` variance 0.0; `coordinator_diagnostics.py:1291` | Security's only remaining metric has a constant baseline: all 410 samples are the same severity. Any different severity z-scores against the 0.1 std floor and raises an anomaly. Undeclaring the dead metric does not change this, but the sensor now reads `nominal` with no `partial` cue. The hair-trigger stays visible only in `metrics_constant`. | No fix in this cycle. Already tracked: `SECURITY-ALERT-TRIGGER-METRIC-SHAPE-1` (plan `PLANNING_anomaly_detector_blind_metrics.md` :170). This change makes that card the only remaining Security anomaly gap. |

No CRITICAL, HIGH or MEDIUM findings.

## Summary

| Severity | Found | Fixed | Deferred |
|---|---|---|---|
| CRITICAL | 0 | 0 | 0 |
| HIGH | 0 | 0 | 0 |
| MEDIUM | 0 | 0 | 0 |
| LOW | 1 (pre-existing) | 0 | 1 (note on card) |

| Bug class | Count |
|---|---|
| #63 coincidental equality / constant baseline | 1 (pre-existing) |

No new bug class is needed for QUALITY_CONTEXT.md.

**Verdict: SHIP.**
