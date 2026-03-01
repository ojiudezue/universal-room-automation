# v3.6.0.10 — Adaptive Rate-of-Change Detection

**Build:** 2026-03-01

## Summary

Replaces fixed rate-of-change thresholds with per-sensor adaptive baselines using the existing diagnostics framework's `MetricBaseline` (Welford's online algorithm). Eliminates false HVAC failure alerts from noisy sensors while catching real problems faster on stable sensors.

## Problem

Fixed rate-of-change thresholds (-5.0/+5.0/+10.0°F per 30min) produce false alerts because sensor noise varies dramatically between devices:
- **Noisy sensor** (e.g., in-wall outlet): rate noise ±7°F/30min → constant false alerts at -5.0 threshold
- **Stable sensor** (e.g., thermostat): rate noise ±0.5°F/30min → real problems at -3.0 go undetected

## Solution: Two-Tier Detection

### Tier 1: Absolute Safety (Unchanged, Immediate)
Life-critical hazards fire immediately on any state change — no rate, no learning, no delay:
- Smoke: binary sensor → instant
- CO ≥ 50ppm → instant
- Temperature ≤ 35°F (freeze) → instant
- Temperature ≥ 100°F (overheat) → instant

### Tier 2: Adaptive Rate-of-Change (New)
Per-sensor statistical baselines replace fixed thresholds:

1. **Full 30-min window** (`MIN_WINDOW_SECONDS = 1800`): Rate = actual delta over actual 30 minutes. No extrapolation. Noise max ±1.44°F vs signal ±5°F+.
2. **Feed each rate** into per-sensor `MetricBaseline` (Welford's online algorithm)
3. **During learning** (< 60 samples): use 2x generous fixed thresholds (±10/±20/±40) to avoid false positives while catching catastrophic events
4. **Once baseline established**: z-score detection. Alert when z ≥ 3.0σ. Severity mapping: 3σ → MEDIUM, 4σ → HIGH, 5σ → CRITICAL
5. **Persist baselines** to SQLite via existing `metric_baselines` table (coordinator_id="safety_rate"). Survives restarts.

## Files Changed

| File | Changes |
|------|---------|
| `domain_coordinators/safety.py` | RateOfChangeDetector: MetricBaseline per sensor, z-score in check_thresholds(), baseline load/save/periodic-save, diagnostics summary |
| `const.py` | Version → 3.6.0.10 |
| `manifest.json` | Version → 3.6.0.10 |

## Constants

```
MIN_WINDOW_SECONDS = 1800   # Full 30-min window
RATE_MIN_SAMPLES = 60       # ~30 min before baseline active
Z_RATE_ALERT = 3.0          # 3σ threshold
Z_RATE_HIGH = 4.0           # 4σ threshold
Z_RATE_CRITICAL = 5.0       # 5σ threshold
```

## Verification

1. No false rate alerts during learning period (generous 2x thresholds)
2. After ~30 min of data, baselines start accumulating
3. Diagnostics sensor shows rate baseline stats per sensor (mean, std, sample_count, active)
4. Noisy sensors get wider effective thresholds automatically
5. Stable sensors get tighter effective thresholds (catches problems sooner)
6. Absolute safety alerts (smoke, CO, freeze, overheat) fire immediately regardless
7. Rate baselines persist across restarts (SQLite)
