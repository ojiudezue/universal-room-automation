# Security Coordinator Review: Lock Sweep & Sensor Gaps

**Date:** 2026-03-05
**Reviewer:** Claude (prompted by user)
**Code reviewed:** `domain_coordinators/security.py`
**Plan reference:** `docs/plans/PLANNING_v3.6.0_REVISED.md` (Cycle 3)

---

## 1. How the Lock Sweep Works (Plain English)

The Security Coordinator has a "periodic lock check" (lock sweep) that runs on a timer, independently of whether the system is armed or disarmed.

1. **A timer fires every 30 minutes** (configurable via `lock_check_interval`). This is set up in `async_setup()` using `async_track_time_interval()` (line 498-508).

2. **When the timer fires**, it queues an intent (`periodic_lock_check`) through the Coordinator Manager's intent queue, which routes it back to SecurityCoordinator's `evaluate()` method (line 545-546).

3. **`_evaluate_lock_check()`** (line 881) walks through every configured lock and garage door entity:
   - Reads the current HA state of each entity via `hass.states.get()`
   - **"unlocked"** lock -> generates a `ServiceCallAction` to call `lock.lock`
   - **"open"** garage door -> generates a `ServiceCallAction` to call `cover.close_cover`
   - **"unavailable"/"unknown"** device -> logs a warning + sends a notification that devices are offline

4. **After checking everything**, if any locks were found unlocked:
   - Sends a notification listing which doors it locked
   - Schedules a compliance check via `ComplianceTracker` to verify locks actually engaged
   - Dispatches `SIGNAL_SECURITY_ENTITIES_UPDATE` to refresh sensors

5. **Daily counters** (`_lock_checks_today`, `_alerts_today`) reset at midnight via `_maybe_reset_daily_counters()`.

**Summary:** Every 30 minutes, it checks all configured locks and garage doors. If anything is unlocked/open, it locks/closes it and notifies you.

---

## 2. Code vs Plan Comparison

| Plan Requirement | Code Status | Notes |
|---|---|---|
| Armed states (DISARMED/HOME/AWAY/VACATION) | Implemented | `ArmedState` enum, line 77 |
| Auto-follow house state (configurable) | Implemented | Off by default (req #6) |
| Entry sensor monitoring (sanctioned vs unsanctioned) | Implemented | `EntryProcessor` + `SanctionChecker` |
| Census integration (known/unknown persons) | Implemented | Census freshness check (5min), unknown->ALERT_HIGH |
| Geofence integration (approaching = expected) | **Partial** | `add_expected_arrival` service exists but no auto-wiring from presence geofence events |
| Anomaly detection (unusual time/entry point) | Implemented | `SecurityPatternLearner`, 30-day min, hour-of-day ratio |
| 6 verdict levels | Implemented | SANCTIONED through ALERT_HIGH |
| Camera recording on HIGH/CRITICAL | Implemented | Platform-aware: Frigate, UniFi Protect, Reolink, generic |
| Security light patterns (red flash, dim red, yellow pulse) | **Partial** | Lights turn on at brightness 255 only. No color/flash. Plan specifies distinct patterns. |
| Scheduled entry support (recurring visitors) | **Not implemented** | Plan mentions `_scheduled_entries: list[ScheduledEntry]` |
| Services: arm, disarm, authorize_guest, add_expected_arrival | Implemented | Lines 1043-1108 |
| Periodic lock check (armed-independent, configurable) | Implemented | Lines 498-508, 881-968 |
| Compliance tracking (locks engaged after arm) | Implemented | `get_compliance_summary()`, `ComplianceTracker` |

### Gaps vs Plan

1. **Scheduled entries** (cleaning service, recurring visitors) -- not implemented
2. **Security light patterns** -- no color/effect differentiation, just full brightness on all configured lights
3. **Geofence auto-wiring** -- the `add_expected_arrival` service exists but nothing connects geofence proximity events to it automatically

---

## 3. Geofence-to-Security Bridge

### How Presence Detects Arrivals

The Presence Coordinator detects arrivals through two paths:

- **Geofence:** Subscribes to `person.*` entity state changes. When `not_home` -> `home`, triggers `_run_inference("geofence_arrive")` to transition house state AWAY -> ARRIVING.
- **Census:** Listens for `SIGNAL_CENSUS_UPDATED`. When `interior_count > 0` during AWAY, transitions to ARRIVING.

### Missing Bridge

There is NO automatic wiring between the Presence Coordinator's geofence arrival detection and the Security Coordinator's `add_expected_arrival()`.

When Presence detects a person arriving via geofence, it fires `SIGNAL_HOUSE_STATE_CHANGED` (AWAY -> ARRIVING). The Security Coordinator listens for house state changes only if `auto_follow_house_state` is enabled, and even then it only adjusts the armed state -- it doesn't add the person to expected arrivals.

**Implemented:** Security now subscribes directly to `person.*` entity state changes via `_setup_geofence_listener()`. When a person transitions `not_home` -> `home`, Security auto-calls `add_expected_arrival(person_id, 10)`. When a person enters a named zone (approaching), it adds a 30-minute window. No Presence Coordinator changes needed.

---

## 4. Notification Manager Integration

### Changes Made

Security previously did direct `ServiceCallAction` calls for lights (`light.turn_on`, brightness 255). This bypassed the Notification Manager which has 12 named light patterns, state restoration, and pattern lifecycle management.

**Implemented:**
1. `NotificationAction` dataclass now includes `hazard_type` and `location` fields (`base.py`)
2. `CoordinatorManager._execute_action()` passes `hazard_type`/`location` through to `async_notify()` (`manager.py`)
3. Security emits `NotificationAction(hazard_type="intruder"|"investigate")` instead of direct light service calls
4. Unknown person detection also uses `hazard_type="intruder"` via NM
5. If NM is unavailable, the notification is still logged by the manager (graceful degradation)

---

## 5. Missing Sensors

### Currently Exposed

| Sensor | Type | What it shows |
|---|---|---|
| `sensor.ura_security_armed_state` | Primary | Armed state |
| `sensor.ura_security_last_entry` | Primary | Last entry event details |
| `binary_sensor.ura_security_alert` | Primary | Active alert |
| `sensor.ura_security_anomaly` | Diagnostic | Anomaly detection status |
| `sensor.ura_security_compliance` | Diagnostic | Lock compliance rate % |

### Additions (Implemented)

1. **`sensor.ura_security_open_entries`** -- count of open configured doors/windows. Attributes: `count`, `entries` (list with `entity_id`, `opened_at`, `open_minutes`). Dynamic icon: door-open / door-closed-lock.

2. **`sensor.ura_security_last_lock_sweep`** -- timestamp of last sweep (device_class=TIMESTAMP). Attributes: `found_unlocked`, `lock_actions_sent`, `unavailable`, `checks_today`. Diagnostic category.

Both subscribe to `SIGNAL_SECURITY_ENTITIES_UPDATE` for reactive updates.
