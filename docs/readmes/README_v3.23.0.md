# v3.23.0 — Activity Log + HVAC Pre-Arrival Fan Fix

## HVAC Pre-Arrival Fan Temperature Gate

**Problem:** HVAC pre-arrival fan activation blindly turned on fans in ALL rooms of a zone, regardless of room temperature. Master Bedroom at 71.8°F got fans activated when the cooling setpoint was 76°F.

**Fix:** `_activate_zone_fans` now compares each room's temperature to the zone cooling setpoint. Rooms below setpoint are skipped. Rooms with no temperature data are also skipped (safe default). `_deactivate_zone_fans` scoped to only turn off fans the predictor actually activated.

**Visibility:** `sensor.ura_hvac_pre_arrival_status` enriched with `fan_rooms_activated` and `fan_rooms_skipped` attributes. Per-room INFO logs show temperature vs setpoint decisions.

**Review:** 2x adversarial review. Fixed 1 HIGH (inverted None gate), 3 MEDIUM (multi-zone overwrite, silent exceptions, deactivation scope).

## URA Activity Log

**Problem:** URA's automated decisions were more opaque than native HA automations. No way to see what URA specifically did without digging through debug logs.

**Solution:** Three complementary channels:

1. **DB-backed activity log** — `ura_activity_log` table with 50-200 events/day. 7-day retention for info, 30-day for notable/critical. Auto-prunes at 2 AM.

2. **HA logbook integration** — `ura_action` events + `logbook.py` platform for formatted display. Shows "URA: Living Room turned on 3 lights (entry, dark)" inline in the HA logbook.

3. **Diagnostic sensor** — `sensor.ura_last_activity` shows most recent action with `recent_activities` (last 10), `activities_today`, `notable_today` attributes. Seeds from DB on startup.

### Actions Logged (14 integration points)

| Coordinator | Actions | Importance |
|-------------|---------|------------|
| Room | Occupancy entry/exit, light on/off, fan on/off, cover open/close, chained automations | info |
| HVAC | Preset changes, pre-arrival triggers | notable |
| Energy | Load shedding escalation/de-escalation | notable |
| Presence | House state transitions | notable |
| Security | Armed state changes | notable |
| Safety | Hazard detections | critical |
| Notification | Alerts sent | notable/critical |

### Key Design Decisions

- **ActivityLogger class** (`activity_logger.py`) as single chokepoint — never raises, dedup cache with description-aware keys, 2KB details_json cap
- **Fire-and-forget** at all wiring sites via `hass.async_create_task()` — never blocks coordinator update cycles
- **Observation mode safe** — all integration points at execution sites (post-observation-mode-check)
- **Midnight counter reset** — `activities_today`/`notable_today` reset on day boundary change

### Review Findings Fixed

| Finding | Severity | Fix |
|---------|----------|-----|
| `activities_today` never resets at midnight | HIGH | Day-boundary check in `_handle_activity` |
| `details_json` truncation produces invalid JSON | HIGH | Store `{"truncated": true}` marker when oversized |
| Dedup cache unbounded growth | MEDIUM | Auto-eviction when cache > 500 entries |
| `automation.py` awaits log() directly | LOW | Changed to `async_create_task` fire-and-forget |
| DB log_activity error level too high | MEDIUM | Changed to debug (non-critical write) |

## Files Changed

### New Files
- `activity_logger.py` — ActivityLogger class (~160 lines)
- `logbook.py` — HA logbook platform (~35 lines)
- `quality/tests/test_activity_logger.py` — 19 tests

### Edited Files
- `database.py` — `ura_activity_log` table + 3 methods
- `__init__.py` — ActivityLogger init + 2 AM prune timer
- `coordinator.py` — set_last_action + occupancy + chained automation wiring
- `automation.py` — fan control + cover control wiring
- `sensor.py` — URALastActivitySensor + HVAC pre-arrival fan attributes
- `domain_coordinators/signals.py` — SIGNAL_ACTIVITY_LOGGED
- `domain_coordinators/hvac.py` — preset change + pre-arrival wiring + fan temperature gate
- `domain_coordinators/hvac_predict.py` — _activate_zone_fans rewrite + tracking state
- `domain_coordinators/energy.py` — load shedding wiring
- `domain_coordinators/presence.py` — house state transition wiring
- `domain_coordinators/security.py` — armed state wiring
- `domain_coordinators/safety.py` — hazard detection wiring
- `domain_coordinators/notification_manager.py` — notification sent wiring
- `manifest.json` — logbook dependency

## Test Results
- 19 new activity logger tests pass
- 1573 existing tests pass (56 pre-existing failures unchanged)
- 0 regressions
