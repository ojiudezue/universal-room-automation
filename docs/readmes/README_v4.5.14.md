# v4.5.14 — Anomaly Sensor Visibility

**Date:** 2026-05-12
**Type:** Tier 1 cycle
**Predecessor:** v4.5.13.1.1 (live-validated)

## Summary

Directly addresses the user's "did we mask something instead of fix it?" concern from v4.5.13. The gate relaxation in v4.5.13 allowed `learning_status: active` when only some metrics had complete baselines — useful, but the aggregate label hid the fact that several metrics were silently dead. v4.5.14 surfaces that reality at first glance via new `metrics_active_ratio` and `metrics_silent` summary fields, plus extends `extra_state_attributes` to four previously bare anomaly sensors.

11 new tests, single Tier 1 staff-engineer review. 0 CRITICAL/HIGH/MEDIUM, 4 LOW (2 fixed inline, 2 deferred/filed).

## What's new

### `get_status_summary()` enhancement (coordinator_diagnostics.py)

Two new top-level fields:

```python
{
    "metrics_active_ratio": "2/4",        # human-readable coverage
    "metrics_silent": ["short_cycle_rate", "comfort_deviation_hours"],
    # ... existing fields preserved
}
```

- `metrics_active_ratio` — count of metrics meeting the minimum-samples threshold over total declared metrics. Read this and the masking concern is gone.
- `metrics_silent` — names of metrics with **zero** observations (distinct from "learning", which means some samples but below minimum).

### Anomaly sensor `extra_state_attributes` (sensor.py)

Four sensors that previously had no attrs (state only) now expose the full `get_status_summary()` payload:

- `sensor.ura_presence_anomaly`
- `sensor.ura_safety_anomaly`
- `sensor.ura_security_anomaly`
- `sensor.ura_music_following_anomaly`

`sensor.ura_hvac_coordinator_hvac_anomaly` already had this surface; it auto-inherits the new ratio + silent-list fields with zero code change.

### `SafetyAnomalySensor` refresh subscription (sensor.py)

Previously bare — no `async_added_to_hass`. Now subscribes to `SIGNAL_SAFETY_ENTITIES_UPDATE` so the attrs refresh on each safety coordinator decision cycle. Matches HVAC + Security pattern.

### `NMAnomalySensor` intentionally unchanged

Different code path (uses `nm.anomaly_status`, not `AnomalyDetector`). Already has informative attrs (`dedup_suppressions`, `notifications_today`, etc.). No change needed for v4.5.14 scope.

### `PresenceAnomalySensor` + `MusicFollowingAnomalySensor` refresh gap

Filed in BACKLOG ("Anomaly sensor refresh signals"). No `SIGNAL_PRESENCE_ENTITIES_UPDATE` or `SIGNAL_MUSIC_FOLLOWING_ENTITIES_UPDATE` exists today. The attrs render correctly on first registration but only refresh when HA naturally re-queries `native_value`. A future cycle adds the missing signals.

## What's NOT changed

- No DB schema changes
- No config keys
- No behavioral changes to anomaly raising (per-metric gate at `record_observation:696` unchanged)
- v4.5.13's gate relaxation still in effect
- Existing per-metric details in `metrics` dict unchanged — purely additive

## Tier 1 Review

Single staff-engineer review per CLAUDE.md hotfix protocol. Mental execution:
- Backward compatibility of `get_status_summary()` change (verified at base.py:252, manager.py:623 — all consumers use `.get()` on specific keys, two additive fields safe)
- None-handling in each new attrs property (4 sensors mentally executed)
- `SafetyAnomalySensor` `async_added_to_hass` super-chain reaches Entity correctly
- All 5 coords confirmed to have `anomaly_detector` attribute via BaseCoordinator init

| Severity | Found | Fixed | Accepted |
|---|---|---|---|
| CRITICAL | 0 | — | — |
| HIGH | 0 | — | — |
| MEDIUM | 0 | — | — |
| LOW | 4 | 2 | 2 documented |

**LOW findings:**
- ✅ Fixed: defensive `getattr` on Security → use direct attribute access for consistency
- ✅ Fixed: guard against `len(metric_names) == 0` → `len(...) or 1` to avoid "0/0"
- Accepted: `metrics_active_ratio` is a string, not numeric. Human-readable form is the primary intent; consumers can split if needed.
- Accepted/filed: MusicFollowing refresh gap. BACKLOG entry covers it.

Full review verdict: APPROVED-WITH-FIXES.

## Test count

- v4.5.13.1.1: 368 tests
- **v4.5.14: 379** (+11 from `test_v4514_anomaly_visibility.py`)

Breakdown:
- 5 behavior tests for `get_status_summary` enhancements
- 4 AST tests asserting `extra_state_attributes` on each anomaly sensor
- 1 AST test for SafetyAnomaly refresh subscription
- 1 source-grep test routing all 4 sensors through `get_status_summary()`

## Live validation plan (post-restart)

1. **`metrics_active_ratio` visible in HVAC anomaly attrs:**
   - `ha_get_state sensor.ura_hvac_coordinator_hvac_anomaly` → attrs include `metrics_active_ratio: "2/4"` and `metrics_silent: ["short_cycle_rate", "comfort_deviation_hours"]`. Confirms the masking is now disclosed.

2. **New attrs on the 4 previously-bare sensors:**
   - `ha_get_state sensor.ura_presence_anomaly` → attrs no longer empty
   - Same for safety, security, music_following

3. **Dead-metric reality check:**
   - For each coord's anomaly sensor, inspect `metrics_silent`. For Safety, expect both metrics (`hazard_trigger_frequency`, `active_hazard_count`) — these don't fire on this install. That's the actionable signal for the future "wire dead metrics" investigation.

4. **No new URA errors:**
   - `ha_get_logs source=system level=ERROR search=universal_room_automation` empty

5. **Carry-over: v4.5.13.x fixes still working:**
   - kwh_rate sensors still live, kWh threshold sliders still at 0.8, zone count still 3

## Deploy notes

- 2 files touched (sensor.py, coordinator_diagnostics.py)
- HACS download required after deploy.sh
- HA restart required
- No new entity unique_ids (only attributes added to existing sensors)
- No orphaned entities introduced

## Documents

- BACKLOG: v4.5.13.2 envoy race (deferred), Anomaly sensor refresh signals (filed)
- v4.5.13.2 is parked; will pick up if envoy race recurs

## Next

- **v4.5.15** — Closet + bathroom lazy auto-off (60-min fail-safe)
- **v4.5.16** — Duplicate-timestamp investigation
- **v4.5.17** — Bayesian prediction-scoring pipeline investigation
- **v4.6.0** — Routine Awareness Phase 1
