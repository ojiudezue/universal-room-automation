# Universal Room Automation v3.6.0-c2.9 — Wire Up Anomaly Detectors

**Release Date:** 2026-02-28
**Internal Reference:** C2.9
**Previous Release:** v3.6.0-c2.8
**Minimum HA Version:** 2024.1+

---

## Summary

The `AnomalyDetector` class was built in C0-diag and the anomaly sensor entities were created in C1/C2, but neither the Presence nor Safety coordinator actually instantiated an `AnomalyDetector`. Both anomaly sensors showed `not_configured` because `self.anomaly_detector` was `None`.

This release wires up the anomaly detectors for both coordinators. The sensors will now progress through: `insufficient_data` → `learning` → `nominal` (or `advisory`/`alert`/`critical` if anomalies detected).

---

## What Was Missing

The `BaseCoordinator` declares `self.anomaly_detector = None` (placeholder). Each coordinator is responsible for instantiating its own `AnomalyDetector` with coordinator-specific metrics and minimum sample sizes. Neither C1 (Presence) nor C2 (Safety) did this.

The Presence coordinator already had observation hooks wired in:
- `_run_inference` records `census_count` observations on state transitions (line 1052)
- `_check_zone_anomalies` records `zone_occupied_count` per zone (line 1084)

These hooks checked `if self.anomaly_detector is not None` and no-oped since the detector was never set.

The Safety coordinator had no hooks at all — observation recording was added to `_respond_to_hazard`.

---

## Changes

### Presence Coordinator (`presence.py`)

```python
# In async_setup(), before load_baselines:
self.anomaly_detector = AnomalyDetector(
    hass=self.hass,
    coordinator_id="presence",
    metric_names=["census_count", "zone_occupied_count", "transition_count_daily"],
    minimum_samples=24,  # ~1 day of hourly observations
)
await self.anomaly_detector.load_baselines()
```

**Metrics tracked:**
| Metric | Scope | What It Detects | Source |
|--------|-------|-----------------|--------|
| `census_count` | house | Occupancy count deviates from norm for this time/day | Census updates |
| `zone_occupied_count` | zone:{name} | Zone occupied at unusual time | Periodic inference (60s) |
| `transition_count_daily` | house | Unusually many state transitions (system instability) | State transitions |

**Activation:** After 24 observations (~24 hours). Shows `insufficient_data` until then.

### Safety Coordinator (`safety.py`)

```python
# In async_setup():
self.anomaly_detector = AnomalyDetector(
    hass=self.hass,
    coordinator_id="safety",
    metric_names=["hazard_trigger_frequency", "active_hazard_count"],
    minimum_samples=720,  # ~30 days of hourly checks
)
await self.anomaly_detector.load_baselines()
```

**Metrics tracked:**
| Metric | Scope | What It Detects | Source |
|--------|-------|-----------------|--------|
| `hazard_trigger_frequency` | per-location | Sensor fires more/less often than historical baseline | Each hazard detection |
| `active_hazard_count` | house | Unusual number of concurrent active hazards | Each hazard detection |

**Activation:** After 720 observations (~30 days). Safety events are rare — needs longer baseline.

**Observation recording** added in `_respond_to_hazard`:
- Records `hazard_trigger_frequency` = 1.0 per trigger with location scope
- Records `active_hazard_count` = current count with house scope

---

## Sensor State Progression

After this release, the anomaly sensors will show:

| Time Since Deploy | Presence Anomaly | Safety Anomaly |
|-------------------|------------------|----------------|
| 0 - first observation | `insufficient_data` | `insufficient_data` |
| After first observation | `learning` | `learning` |
| After 24 observations (~1 day) | `nominal` (or anomaly severity) | Still `learning` |
| After 720 observations (~30 days) | Active detection | `nominal` (or anomaly severity) |

Severity values when active: `nominal`, `advisory` (z > 2.0), `alert` (z > 3.0), `critical` (z > 4.0)

---

## Files Changed

| File | Change |
|------|--------|
| `domain_coordinators/presence.py` | Instantiate `AnomalyDetector` in `async_setup()` with 3 presence metrics |
| `domain_coordinators/safety.py` | Add `SAFETY_METRICS` list, instantiate `AnomalyDetector` in `async_setup()`, add observation recording in `_respond_to_hazard` |

---

## How to Verify

1. After restart, check anomaly sensors:
   - `sensor.ura_presence_coordinator_presence_anomaly` → should show `insufficient_data` (first run) or `learning` (after observations start)
   - `sensor.ura_safety_coordinator_safety_anomaly` → should show `insufficient_data` (first run) or `learning`
2. Neither should show `not_configured` anymore
3. After ~24 hours of operation, Presence anomaly should transition to `nominal`
4. Safety anomaly will remain `learning` for ~30 days (expected — safety events are rare)

---

## Version Mapping

| Version | Cycle | Description |
|---------|-------|-------------|
| 3.6.0-c0 – c0.4 | C0 | Domain coordinator infrastructure + diagnostics |
| 3.6.0-c1 | C1 | Presence Coordinator |
| 3.6.0-c2 – c2.6 | C2 | Safety Coordinator + deployment fixes |
| 3.6.0-c2.7 | C2.7 | Fix toggle switches not appearing |
| 3.6.0-c2.8 | C2.8 | Fix unsafe entity_id "all" in safety response |
| **3.6.0-c2.9** | **C2.9** | **Wire up anomaly detectors for Presence and Safety** |
