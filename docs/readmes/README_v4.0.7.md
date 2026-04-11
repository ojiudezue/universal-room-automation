# v4.0.7 — Two-Tier Sensor Tracking + Rate Limiter

## Problem
Room automations responding with 7-26 second delays. Diagnostic investigation (v4.0.6) proved event-driven listeners WERE firing — 6,509 times/hour — but the event loop was flooded with unnecessary refreshes from environmental and power sensor changes. Every temperature tick, humidity change, and power meter update across 31 rooms triggered the full `_async_update_data` pipeline (occupancy detection → energy calc → Bayesian predictions → activity logging → comfort scoring). Motion callbacks got queued behind this flood.

The system grew heavier per-refresh over time (activity log v3.23.0, Bayesian v4.0.0-v4.0.2) while refresh frequency stayed uncontrolled. The cumulative effect crossed the performance threshold.

## Fix: Two-Tier Sensor Tracking

Split sensor tracking into two tiers:

| Tier | Sensors | Trigger | Latency |
|------|---------|---------|---------|
| **Tier 1 (immediate)** | motion, mmwave, occupancy, illuminance | Event-driven `async_refresh()` | <1s |
| **Tier 2 (poll-only)** | temperature, humidity, power | 30s `update_interval` | 0-30s |

Illuminance stays in Tier 1 because lux-triggered automations (v3.10.0 `lux_dark`/`lux_bright`) need immediate response.

### Rate Limiter
Added 2-second per-room cooldown on Tier 1 callbacks. If multiple motion sensors fire within 2s (e.g., Garage B has 5 motion sources), only the first triggers a refresh. The in-flight refresh reads ALL sensor states via `hass.states.get()`, so no data is lost.

### Performance Impact
- Kitchen: 10 triggers → 5 (50% reduction)
- Study A Closet: 5 triggers → 2 (60% reduction)
- Garage B: 12 triggers → 6 (50% reduction)
- System-wide: ~6,509 callbacks/hr → estimated ~1,000-2,000 (70-85% reduction)

## What Is NOT Affected
- **Activity Log:** All logging is triggered by occupancy transitions and automation actions, not environmental data. Zero impact.
- **Bayesian:** All learning and prediction is occupancy-based. Zero impact.
- **Room automations (lights/covers):** Driven by motion/occupancy sensors — still immediate.
- **Lux-triggered automations:** Illuminance is Tier 1 — still immediate.

## What IS Affected (acceptably)
- **Fan control:** Temperature-dependent decisions run on 30s poll instead of instantly. Acceptable — thermal processes have minutes of inertia.
- **URA temp/humidity sensors:** Mirror hardware sensors with 0-30s lag. Hardware sensors available directly in HA for real-time display.
- **Comfort score:** Updates on 30s poll. Display metric only, no automation depends on it.
- **Power/energy tracking:** Updates on 30s poll. Accumulated over hours, 30s is noise.

## Diagnostic Cleanup
Removed all v4.0.6 WARNING-level diagnostic logs (EVENT-DRIVEN callback, sensors to track, async_track_state_change_event returned). Retained RESILIENCE-002 motion transition log at INFO level with O(1) set lookup instead of O(n) list concatenation.

## Acceptance Criteria
- **Verify:** Walk into a closet → light turns on within 2 seconds (was 7-18s)
- **Verify:** Temperature sensor updates appear on URA sensor within 30s (poll cycle)
- **Verify:** Lux-triggered automations still fire instantly
- **Verify:** No "EVENT-DRIVEN callback fired" WARNING messages in HA log (diagnostics removed)
- **Live:** Check HA log for "Event-driven mode — X Tier 1 sensors (immediate), Y Tier 2 sensors (30s poll)" for each room
- **Live:** Motion sensor state changes logged at INFO level ("Sensor X changed off -> on")
- **Test:** All 1670 existing tests pass (0 regressions)

## Files Changed
- `coordinator.py` — Two-tier sensor tracking, rate limiter, diagnostic cleanup

## Review
- Tier 2 feature review (two reviews + live validation)
- Reviewed against all 23 QUALITY_CONTEXT.md bug classes
