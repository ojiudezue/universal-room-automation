# v3.6.35 — Security Coordinator: NM Integration, Geofence Arrivals, New Sensors

## Summary

Three enhancements to the Security Coordinator: delegate light patterns to the
Notification Manager, auto-detect arriving household members via geofence, and
expose three new diagnostic/primary sensors.

## Changes

### Notification Manager Integration
- Added `hazard_type` and `location` fields to `NotificationAction` dataclass
- `CoordinatorManager._execute_action()` now passes these through to NM's `async_notify()`
- Security no longer does direct `light.turn_on` service calls for alerts
- Instead emits `NotificationAction(hazard_type="intruder"|"investigate")` — NM handles
  light patterns (red flash, yellow pulse), state restoration, and pattern lifecycle
- Graceful degradation: if NM is unavailable, notifications are still logged

### Geofence Arrival Detection
- Security subscribes directly to `person.*` entity state changes
- `not_home` -> `home`: adds person to expected arrivals (10-minute window)
- `not_home` -> named zone: adds person to expected arrivals (30-minute window)
- Only active when armed (no processing when disarmed)
- Prevents false INVESTIGATE/ALERT verdicts when household members arrive

### New Sensors
- `sensor.ura_security_open_entries` — count of open configured doors/windows,
  with attributes listing entity_id, opened_at, and open_minutes per entry.
  Seeded from current state on startup (handles HA restarts).
- `sensor.ura_security_last_lock_sweep` — timestamp of last lock sweep with
  attributes: found_unlocked, lock_actions_sent, unavailable, checks_today
- `sensor.ura_security_expected_arrivals` — count of active expected arrivals
  (geofence + manual), with attributes listing person_id, expiry, and authorized guests

### Bug Fixes
- SecurityAnomalySensor and SecurityComplianceSensor now subscribe to
  `SIGNAL_SECURITY_ENTITIES_UPDATE` for real-time updates (were polling-only)
- Open entries tracking handles unavailable/unknown sensor states
- Open entries seeded from current state on HA startup (no stale zero count)

## Files Changed

| File | Change |
|------|--------|
| `domain_coordinators/base.py` | Added `hazard_type`, `location` to `NotificationAction` |
| `domain_coordinators/manager.py` | Pass `hazard_type`/`location` to NM routing |
| `domain_coordinators/security.py` | NM integration, geofence listener, open entries tracking, lock sweep persistence, SanctionChecker snapshot methods |
| `sensor.py` | 3 new sensors + dispatcher subscriptions for 2 existing sensors |
| `docs/reviews/REVIEW_security_coordinator_lock_sweep.md` | New review document |
