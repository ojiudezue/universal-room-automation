# v3.13.2 — MetricBaseline Integration

**Date**: 2026-03-12
**Scope**: Learned anomaly detection for circuits and load shedding via Welford's z-score baselines
**Tests**: 19 new (test_metric_baseline_integration.py), 50 M1+M2+M3 total, 960+ total passing

---

## Summary

Replaces fixed thresholds with learned baselines using Welford's online algorithm. SPAN circuit monitoring now detects unusual consumption patterns via per-circuit z-scores. Load shedding threshold auto-learns from peak import data using mean + 2*std instead of crude 90th percentile.

## Changes

### 1. Per-Circuit Z-Score Anomaly Detection (`energy_circuits.py`)
- Each SPAN circuit gets its own `MetricBaseline` tracking power consumption
- After 60+ samples (~5 hours), z-score anomaly detection activates alongside existing tripped-breaker detection
- Two-tier thresholds: z >= 3.0 = advisory (log only), z >= 4.0 = alert (generates anomaly)
- Baselines updated AFTER anomaly check to prevent self-reference
- `get_status()` now reports `baselines_tracked` and `baselines_active` counts

### 2. Load Shedding Z-Score Threshold (`energy.py`)
- `_peak_import_baseline` MetricBaseline fed during peak periods alongside existing history
- `_get_effective_shedding_threshold()` priority chain: z-score (300+ samples) > 90th percentile (30+ days) > fixed
- Z-score threshold = `mean + 2 * std` — adapts to household consumption patterns
- Replaces rigid percentile with statistically principled threshold

### 3. Baseline Persistence
- `_save_energy_baselines()`: Serializes all circuit + peak import baselines to `metric_baselines` table
- `_restore_energy_baselines()`: Restores baselines on startup, maps circuit baselines by friendly_name
- Wired into `_periodic_db_writes()` (save), `async_setup()` (restore), `async_teardown()` (save)
- `restore_baselines()` uses merge semantics (`.update()`) to preserve existing baselines

## Review Findings Fixed (3-Review Protocol)

- **H1 (R1)**: Log warning for unmatched circuit baselines during restore (renamed circuits)
- **H2 (R1)**: Changed `restore_baselines()` from dict replacement to `.update()` merge
- **H1 (R2)**: Added `discover_circuits()` guard in `_restore_energy_baselines()` before circuit lookup
- **H2 (R2)**: Moved decision timer cancellation BEFORE teardown saves to prevent concurrent DB writes
- **M1 (R1)**: Removed dead `if not all_baselines` guard
- **Test gaps**: Added 4 edge case tests (advisory z-score, zero power, unavailable state, restore merge)

## Files Modified

| File | Changes |
|------|---------|
| `domain_coordinators/energy_circuits.py` | Added MetricBaseline import, `_power_baselines` dict, `_get_power_baseline()`, z-score detection in `check_anomalies()`, `get_baselines_for_save()`, `restore_baselines()`, updated `get_status()` |
| `domain_coordinators/energy.py` | Added `_peak_import_baseline`, updated `_get_effective_shedding_threshold()` with z-score, added `_save_energy_baselines()`, `_restore_energy_baselines()`, fixed teardown ordering |
| `quality/tests/test_metric_baseline_integration.py` | 19 tests: MetricBaseline core (3), circuit z-score (5), load shedding threshold (5), DB round-trip (2), edge cases (4) |

## Deferred Items

Per plan, the following M3 items from the plan were **not implemented** (scope reduction for stability):
- **Additional EC baselines** (`battery_soc_at_peak_start`, `daily_consumption_baseline`, `daily_import_cost`, `solar_forecast_error`): These are additive and can be layered in a future cycle without affecting the core z-score infrastructure shipped here.
- **EWMA/decay for MetricBaseline**: Welford's gives equal weight to all samples. Over months, the baseline becomes slow to adapt. A future cycle should add exponential weighted moving average or periodic reset.
- **Circuit baseline deduplication**: Z-score anomalies can repeat every cycle for sustained high-power circuits. Future cycle should add per-circuit cooldown flag similar to `circuit.alerted`.
- **busy_timeout on raw aiosqlite connections**: The save/restore methods open raw connections without `PRAGMA busy_timeout`. Not urgent with WAL mode but should be added.
