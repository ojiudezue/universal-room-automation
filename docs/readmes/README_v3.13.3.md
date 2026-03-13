# v3.13.3 — MetricBaseline Hardening + Additional EC Baselines

**Date**: 2026-03-12
**Scope**: Completes all deferred items from v3.13.2 — recency weighting, z-score dedup, busy_timeout, new baselines
**Tests**: 31 tests (test_metric_baseline_integration.py), 62 M1+M2+M3 total

---

## Summary

Finishes the 4 items deferred from v3.13.2 for stability. MetricBaseline now supports recency weighting via `max_samples` cap on Welford's algorithm. Circuit z-score alerts are deduplicated with a 30-minute cooldown. Raw aiosqlite connections get `PRAGMA busy_timeout`. Three new Energy Coordinator baselines track SOC at peak, daily import cost, and solar forecast error.

## Changes

### 1. MetricBaseline `max_samples` Recency Weighting (`coordinator_diagnostics.py`)
- New `max_samples: int = 0` field (0 = unlimited, classic Welford's)
- When `sample_count > max_samples`, caps `effective_n` in Welford's update
- Newer data carries more weight — sliding-window approximation without storing the full window
- Variance clamped to `max(0.0, ...)` to prevent negative values from capped Welford's

### 2. Circuit Z-Score Cooldown Dedup (`energy_circuits.py`)
- `CIRCUIT_ZSCORE_COOLDOWN_S = 1800` — 30-minute cooldown per circuit
- `_zscore_alerted` dict tracks last alert timestamp per entity_id
- Prevents repeated consumption_anomaly alerts for sustained high-power circuits
- Cooldown is in-memory only — resets on restart (first post-restart alert is valid)

### 3. `PRAGMA busy_timeout` on Raw aiosqlite Connections (`energy.py`)
- `_save_energy_baselines()`: `PRAGMA busy_timeout=30000` after connect
- `_restore_energy_baselines()`: same busy_timeout pragma
- Prevents `SQLITE_BUSY` under concurrent access alongside existing WAL mode

### 4. Additional EC Baselines (`energy.py`)
- `_soc_at_peak_baseline` (max_samples=365): Fed on TOU→peak transition with battery SOC. Tracks typical battery state entering peak for degradation detection.
- `_daily_import_cost_baseline` (max_samples=365): Fed at daily reset with yesterday's import cost. Establishes billing pattern baseline.
- `_solar_forecast_error_baseline` (max_samples=365): Fed at daily reset with abs(pct_error) from accuracy evaluation. Tracks forecast reliability.
- All persisted/restored alongside existing circuit + peak import baselines
- `max_samples` correctly set on restore (not stored in DB, hardcoded per metric_name)

## Review Findings Fixed (3-Review Protocol)

### Code fixes
- **M (R2)**: Added `max(0.0, ...)` guard around variance computation to prevent negative variance with aggressive max_samples cap
- **M (R1)**: Fixed misleading save log count — now tracks actually-saved baselines (skipping sample_count==0)

### Test fixes
- **H1 (R3)**: Added cooldown expiry test with mocked `time.time` — verifies re-alert after 30min
- **H2 (R3)**: Added max_samples restore test with real SQLite DB — verifies correct max_samples per metric
- **H3 (R3)**: Added feed tests for all 3 new baselines (soc, cost, forecast)
- **M1 (R3)**: Tightened zero-variance z-score assertion from `== 0.0 or < 1.0` to exact `== 0.0`
- **M2 (R3)**: Tightened z_score_beats_percentile assertion to range check `5.0 < threshold < 9.0`
- **M3 (R3)**: Added max_samples=1 degenerate case test (variance always 0.0, mean tracks last value)
- **M4 (R3)**: Added negative max_samples test (behaves as unlimited)
- **M5 (R3)**: Added variance non-negativity stress test with abrupt data shift

## Files Modified

| File | Changes |
|------|---------|
| `domain_coordinators/coordinator_diagnostics.py` | `max_samples` field, capped `effective_n`, `max(0.0, ...)` variance guard |
| `domain_coordinators/energy_circuits.py` | `CIRCUIT_ZSCORE_COOLDOWN_S`, `_zscore_alerted` dict, cooldown check in `check_anomalies()` |
| `domain_coordinators/energy.py` | 3 new baselines, busy_timeout pragma, baseline save/restore for all metrics, accurate save log count |
| `quality/tests/test_metric_baseline_integration.py` | 8 new tests (31 total): cooldown expiry, 3 baseline feeds, max_samples restore, degenerate cases |

## Test Summary

| Class | Tests | New in v3.13.3 |
|-------|-------|----------------|
| TestMetricBaselineCore | 3 | — |
| TestCircuitZScoreDetection | 5 | — |
| TestLoadSheddingZScoreThreshold | 5 | — |
| TestBaselineDBRoundTrip | 2 | — |
| TestCircuitZScoreEdgeCases | 5 | — |
| TestMaxSamplesDecay | 6 | +3 (degenerate, negative, non-negative variance) |
| TestCooldownExpiry | 1 | +1 (cooldown expiry with time mock) |
| TestNewBaselinesFeedAndRestore | 4 | +4 (soc, cost, forecast feeds + restore) |
| **Total** | **31** | **+8** |
