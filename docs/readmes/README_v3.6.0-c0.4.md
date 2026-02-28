# Universal Room Automation v3.6.0-c0.4 — Coordinator Diagnostics Framework

**Release Date:** 2026-02-28
**Internal Reference:** C0-diag (Domain Coordinators — Diagnostics Infrastructure)
**Previous Release:** v3.6.0-c0.3
**Minimum HA Version:** 2024.1+
**Depends on:** v3.6.0-c0.3
**Design Document:** COORDINATOR_DIAGNOSTICS_FRAMEWORK_v2.md

---

## Summary

v3.6.0-c0.4 adds the diagnostics infrastructure that all domain coordinators will use. This is a foundational cycle — it ships reusable classes and database schema that subsequent coordinator cycles (C1-C7) will integrate.

### What's New

1. **`coordinator_diagnostics.py`** — New module with four reusable diagnostics classes:
   - **DecisionLogger** — Logs every coordinator decision with full context and scope
   - **ComplianceTracker** — Checks whether devices followed commands, detects user overrides (delayed check 2 minutes after action)
   - **AnomalyDetector** — Statistical anomaly detection using Welford's online algorithm for running mean/variance, z-score-based severity classification (advisory/alert/critical), per-metric per-scope baselines with configurable minimum sample sizes
   - **OutcomeMeasurer** — Records coordinator effectiveness measurements

2. **Anomaly Detection Architecture** — Bayesian-inspired statistical deviation detection:
   - Anomaly = "given historical data, a statistically significant deviation from normal behavior"
   - Not sensor disagreements (data quality), not rule violations (compliance)
   - Per-coordinator minimum sample requirements before activation (prevents false positives during learning)
   - Scope-aware: house, zone, or room level baselines tracked independently
   - Consistent severity vocabulary: `nominal`, `advisory`, `alert`, `critical`
   - Consistent learning vocabulary: `insufficient_data`, `learning`, `active`, `paused`

3. **Database Schema** — New tables and columns:
   - `anomaly_log` — Stores detected anomalies with z-scores, baselines, and context
   - `metric_baselines` — Persists running statistics for anomaly detection across restarts
   - `outcome_log` — Generalized outcome measurement (coordinator-specific metrics in JSON)
   - `parameter_beliefs` — Bayesian parameter learning storage
   - `parameter_history` — Audit trail for parameter changes
   - `scope` column added to `decision_log` and `compliance_log` (with migration for existing data)

4. **Coordinator Enable/Disable** — Any coordinator can be disabled without deletion:
   - Manager is the authority via `async_set_coordinator_enabled()`
   - Disabled coordinators: `evaluate()` skipped, listeners unsubscribed, sensors show "disabled"
   - Re-enabling calls `async_setup()` to restore listeners and load baselines
   - Per-coordinator config keys: `CONF_{ID}_ENABLED` (presence, safety, security, energy, hvac, comfort)

5. **BaseCoordinator Enhancements**:
   - `decision_logger`, `compliance_tracker`, `anomaly_detector` attributes (injected by Manager)
   - `get_diagnostics_summary()` method returns anomaly status and learning progress

6. **CoordinatorManager Enhancements**:
   - Shared `DecisionLogger` and `ComplianceTracker` instances injected into all coordinators at registration
   - `get_system_anomaly_status()` — Aggregates worst severity, active anomaly count, learning status across all coordinators
   - `get_diagnostics_summary()` — Full diagnostics report for all coordinators
   - `get_coordinator_status()` — Per-coordinator enabled/disabled status

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `domain_coordinators/coordinator_diagnostics.py` | **New** | DecisionLogger, ComplianceTracker, AnomalyDetector, OutcomeMeasurer, MetricBaseline, data classes (~630 lines) |
| `domain_coordinators/base.py` | Modified | Added diagnostics attributes (decision_logger, compliance_tracker, anomaly_detector), `get_diagnostics_summary()` method |
| `domain_coordinators/manager.py` | Modified | Added diagnostics injection at registration, `async_set_coordinator_enabled()`, `get_system_anomaly_status()`, `get_diagnostics_summary()`, `get_coordinator_status()` |
| `database.py` | Modified | Added anomaly_log, metric_baselines, outcome_log, parameter_beliefs, parameter_history tables. Added scope column to decision_log and compliance_log with PRAGMA-based migration. Updated `log_compliance_check()` with scope parameter. |
| `const.py` | Modified | Added enable/disable config keys (CONF_{ID}_ENABLED), COORDINATOR_ENABLED_KEYS mapping, retention constants, DIAGNOSTICS_SCOPE_HOUSE. Version bump to 3.6.0-c0.4. |

---

## Tests

- **51 new tests** in `quality/tests/test_coordinator_diagnostics.py`
- Tests cover: MetricBaseline (Welford's algorithm, z-score), AnomalySeverity/LearningStatus enums, AnomalyDetector (observation recording, severity classification, learning status, scope isolation, baseline management), ComplianceTracker (state comparison for climate/light/fan/cover/switch), data classes (DecisionLog, ComplianceRecord, AnomalyRecord, OutcomeMeasurement), BaseCoordinator diagnostics integration, CoordinatorManager diagnostics injection and enable/disable, new constants
- **Full suite: 426 tests pass, 0 failures, 0 regressions**

---

## How to Deploy

```bash
./scripts/deploy.sh "3.6.0-c0.4" "Add coordinator diagnostics framework" \
  "- DecisionLogger, ComplianceTracker, AnomalyDetector, OutcomeMeasurer
- Anomaly detection via statistical deviations from learned baselines (z-score)
- New DB tables: anomaly_log, metric_baselines, outcome_log, parameter_beliefs/history
- Scope columns added to decision_log and compliance_log
- Per-coordinator enable/disable via CoordinatorManager
- BaseCoordinator diagnostics attributes and summary
- 51 new tests, 426 total passing"
```

---

## How to Verify It Works

### 1. Database schema created

After restart, check that new tables exist:

```sql
-- In HA SQLite browser or Developer Tools
SELECT name FROM sqlite_master WHERE type='table' AND name IN (
  'anomaly_log', 'metric_baselines', 'outcome_log',
  'parameter_beliefs', 'parameter_history'
);
```

### 2. Scope migration applied

```sql
-- Verify scope column exists on decision_log
PRAGMA table_info(decision_log);
-- Should show 'scope' column

-- Verify scope column exists on compliance_log
PRAGMA table_info(compliance_log);
-- Should show 'scope' column
```

### 3. No regressions

- All existing coordinator entities (`sensor.ura_coordinator_manager`, `sensor.ura_house_state`, `sensor.ura_coordinator_summary`) remain functional
- Integration page shows same devices as before
- Room automation continues working normally

---

## Architecture Notes

### How Diagnostics Will Be Used by Future Coordinators

Each coordinator cycle (C1-C7) will:
1. Create a coordinator-specific `AnomalyDetector` subclass with domain metrics
2. Manager injects shared `DecisionLogger` and `ComplianceTracker` at registration
3. During `evaluate()`, coordinator logs decisions and records metric observations
4. AnomalyDetector checks observations against learned baselines and flags deviations
5. On `async_setup()`, baselines are loaded from DB; on `async_teardown()`, they're persisted

### Minimum Sample Requirements by Domain

| Coordinator | Minimum Samples | Rationale |
|-------------|----------------|-----------|
| Presence | 24 (1 day hourly) | Occupancy patterns repeat daily |
| Energy | 48 (2 days hourly) | Need full daily cycles |
| Security | 168 (1 week hourly) | Security events are sparse |
| Comfort | 48 (2 days hourly) | Comfort preferences stabilize quickly |
| HVAC | 48 (2 days hourly) | Need heating and cooling cycle data |

---

## Version Mapping

| Version | Cycle | Description |
|---------|-------|-------------|
| 3.6.0-c0 | C0 | Domain coordinator base infrastructure |
| 3.6.0-c0.1 | C0.1 | Integration page organization (separate config entries) |
| 3.6.0-c0.2 | C0.2 | Census graceful degradation fix |
| 3.6.0-c0.3 | C0.3 | Coordinator entity unavailability fix |
| **3.6.0-c0.4** | **C0-diag** | **Coordinator diagnostics framework** |
