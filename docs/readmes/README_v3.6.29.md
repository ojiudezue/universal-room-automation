# v3.6.29 — Notification Manager (C4a)

**Date:** 2026-03-04
**Scope:** New domain coordinator service — centralized outbound notification delivery
**Lines added:** ~1,870 across 17 files (2 new, 15 modified)

---

## Summary

Safety and Security coordinators generate hazards and alerts that update sensor state and log entries, but nobody actually gets notified. The Notification Manager (NM) closes this gap — it's a centralized outbound notification delivery service that routes alerts from any domain coordinator to the right people via the right channels at the right severity.

The NM is **not** a BaseCoordinator subclass. It doesn't manage rooms or participate in the intent/evaluate/action pipeline. It's a standalone service owned by CoordinatorManager, stored at `hass.data[DOMAIN]["notification_manager"]`. Coordinators communicate with it through the existing NotificationAction pipeline — when CoordinatorManager's `_execute_action` encounters a `NotificationAction`, it forwards to NM automatically. No coordinator code changes needed to opt in.

---

## Architecture

### Access Pattern

```
CoordinatorManager
├── safety coordinator  ─── produces NotificationAction ──┐
├── security coordinator ── produces NotificationAction ──┤
├── energy coordinator  ─── produces NotificationAction ──┤
│                                                         │
└── _execute_action() ────────────────────────────────────┘
         │
         ▼
    NotificationManager.async_notify()
         │
         ├── Severity filter ──── channel_qualifies()
         ├── Quiet hours check ── _is_quiet_hours()
         ├── Dedup check ──────── _is_deduplicated()
         │
         ▼ Per-person routing
         ├── Pushover ──── _send_pushover(user_key, priority)
         ├── Companion ─── _send_companion(service, ack button)
         ├── WhatsApp ──── _send_whatsapp(phone)
         ├── TTS ────────── _send_tts(speakers)
         └── Alert Lights ─ _trigger_alert_lights(pattern)
```

### CRITICAL Alert State Machine

```
                     ┌─────────────────────────────┐
                     │                             │
IDLE ──[CRITICAL]──► ALERTING ──► REPEATING ───────┤
                                  (every 30s)       │
                                      │             │
                                  [acknowledge]     │
                                      │             │
                                      ▼             │
                                  COOLDOWN          │
                                  (per-hazard       │
                                   configurable)    │
                                      │             │
                                  [expires]         │
                                      │             │
                                      ▼             │
                                  RE_EVALUATE       │
                                      │             │
                          ┌───────────┴──────────┐  │
                    hazard cleared         still active
                          │                      │  │
                          ▼                      └──┘
                        IDLE               (re-fires CRITICAL)
```

Key behaviors:
- **Repeat:** CRITICAL alerts re-send to all qualifying channels every 30 seconds
- **Acknowledge:** Via HA button entity (`button.ura_nm_acknowledge`) or Companion App action button (`ACKNOWLEDGE_URA` action)
- **Cooldown:** Per-hazard-type configurable duration (smoke: 15min, water: 10min, CO: 20min, intrusion: 30min, etc.)
- **Re-fire:** After cooldown expires, NM queries the source coordinator via `is_hazard_active()` — if hazard persists, the full CRITICAL cycle restarts
- **Restart recovery:** On HA restart, NM recovers state from the SQLite `notification_log` table — unacked CRITICALs resume repeating, active cooldowns resume with remaining time

---

## Notification Channels

### 1. Pushover
- Per-person user keys with `target` routing
- Priority escalation: CRITICAL → priority 1 + siren sound, HIGH → priority 1
- Service name configurable (default: `notify.pushover`)

### 2. Companion App
- Per-person service names (e.g., `notify.mobile_app_iphone`)
- CRITICAL notifications include an "Acknowledge" action button that maps to `ACKNOWLEDGE_URA`
- Critical push sound with volume 1.0

### 3. WhatsApp
- Via ha-wa-bridge integration (`whatsapp.send_message`)
- Per-person phone numbers
- Bold title formatting

### 4. TTS (Text-to-Speech)
- Configurable speaker list (`media_player.*` entities)
- Uses `tts.speak` with `media_player_entity_id`
- Non-blocking delivery

### 5. Alert Lights
- 13 light patterns with color, effect, and timing:

| Pattern | Color | Effect | Use Case |
|---------|-------|--------|----------|
| fire | Orange | Flash 250ms | Fire/smoke hazards |
| smoke | Orange | Flash 250ms | Smoke detection |
| water_leak | Blue | Pulse 1000ms | Water leak |
| flooding | Blue | Pulse 500ms | Multi-sensor flooding |
| carbon_monoxide | Orange | Flash 500ms | CO detection |
| freeze_risk | Light blue | Pulse 1000ms | Freeze warning |
| warning | Yellow | Pulse 1000ms | Generic warnings |
| intruder | Red | Flash 200ms | Intrusion alert |
| armed | Red | Solid dim (30) | Armed state indicator |
| investigate | Yellow | Pulse 800ms | Suspicious activity |
| arriving | Warm white | Fade 2000ms | Expected arrival |
| sequential | — | Sequential 300ms | Entity-by-entity cycling |

- Saves original light states (on/off, brightness, color) before activation
- Restores original states when alert is cleared or acknowledged

---

## Severity-Based Routing

Each channel has a configurable minimum severity threshold:

| Channel | Default Threshold | Receives |
|---------|-------------------|----------|
| Pushover | MEDIUM | MEDIUM, HIGH, CRITICAL |
| Companion | MEDIUM | MEDIUM, HIGH, CRITICAL |
| WhatsApp | HIGH | HIGH, CRITICAL |
| TTS | CRITICAL | CRITICAL only |
| Alert Lights | HIGH | HIGH, CRITICAL |

Severity ordering: `LOW < MEDIUM < HIGH < CRITICAL`

**CRITICAL always bypasses quiet hours.** Non-CRITICAL notifications are suppressed during quiet hours.

---

## Per-Person Configuration

Each person entry includes:
- **HA person entity** — links to `person.*` for identity
- **Pushover user key** — individual Pushover routing
- **Companion App service** — per-device notification service
- **WhatsApp phone** — individual WhatsApp number
- **Delivery preference:** `immediate`, `digest`, or `off`
  - CRITICAL and HIGH are always immediate regardless of preference
  - Digest items are queued in the DB and delivered at configurable times

### Digest Mode
- Morning digest time (default: 08:00)
- Optional evening digest (default: 18:00)
- Notifications grouped by coordinator, sorted by severity
- Count aggregation for repeated events (e.g., "3x Humidity high — Bathroom")
- Delivered via lowest-severity qualifying channel

---

## Quiet Hours

Two modes:
1. **House state-based** (default): Suppresses non-CRITICAL during `sleep` or `home_night` states
2. **Manual schedule**: Configurable start/end times, supports overnight ranges (e.g., 22:00 → 07:00)

---

## Deduplication

Per-severity time windows prevent notification spam:

| Severity | Window |
|----------|--------|
| CRITICAL | 30 seconds |
| HIGH | 120 seconds |
| MEDIUM | 300 seconds |
| LOW | 600 seconds |

Dedup key: `{coordinator_id}:{title}:{location}` — same hazard at same location from same coordinator is suppressed within the window.

---

## Database Schema

New `notification_log` table in the URA SQLite database:

```sql
CREATE TABLE IF NOT EXISTS notification_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    coordinator_id TEXT NOT NULL,
    severity TEXT NOT NULL,
    title TEXT NOT NULL,
    message TEXT,
    hazard_type TEXT,
    location TEXT,
    person_id TEXT,
    channel TEXT NOT NULL,
    delivered INTEGER DEFAULT 1,
    acknowledged INTEGER DEFAULT 0,
    ack_time TEXT,
    cooldown_expires TEXT
)
```

Indexes: `idx_notification_log_date` (timestamp), `idx_notification_log_pending` (person_id, delivered, severity)

Database methods: `log_notification()`, `get_notifications_today()`, `get_last_notification()`, `get_pending_digest()`, `mark_digest_delivered()`, `acknowledge_notification()`, `get_active_critical()`, `get_active_cooldown()`, `set_cooldown()`, `prune_notification_log()`

30-day retention with automatic pruning on startup.

---

## Entities (8 new)

All entities use the NM device (`URA: Notification Manager`, via `coordinator_manager`):

| Entity | Type | State | Key Attributes |
|--------|------|-------|----------------|
| `switch.ura_notification_manager_enabled` | Switch | on/off | Enable/disable NM |
| `sensor.ura_nm_last_notification` | Sensor | severity or `none` | message, channel, time, coordinator |
| `sensor.ura_nm_notifications_today` | Sensor | int count | breakdown by severity/channel |
| `sensor.ura_nm_cooldown_remaining` | Sensor | seconds (int) | hazard_type, location |
| `sensor.ura_nm_channel_status` | Sensor (diagnostic) | `ok` / `degraded` | per-channel health dict |
| `sensor.ura_nm_trigger` | Sensor | `{coordinator}_{severity}` | coordinator, severity, title, message, hazard_type, location, timestamp |
| `binary_sensor.ura_nm_active_alert` | Binary (safety) | on = active alert | alert_state, hazard_type, location |
| `button.ura_nm_acknowledge` | Button | — | Acknowledges active CRITICAL alert |

### Channel Health Tracking
Each channel tracks:
- `status`: `ok` or `degraded` (after 3 consecutive failures)
- `last_success`: ISO timestamp of last successful delivery
- `failures`: consecutive failure count

A single success resets the failure counter and status to `ok`.

---

## Config Flow

4 new options steps added to the Coordinator Manager options menu:

### 1. Notifications — Channel Config
- Enable/disable each of the 5 channels
- Set severity threshold per channel
- Pushover service name
- TTS speaker entities
- Alert light entities

### 2. Notifications — Person Setup
- HA person entity selector
- Per-person Pushover user key, Companion App service, WhatsApp phone
- Delivery preference (immediate/digest/off)
- Morning and evening digest times

### 3. Notifications — Quiet Hours
- House state-based toggle (uses sleep/home_night)
- Manual start/end times for custom quiet windows

### 4. Notifications — Cooldowns
- Per-hazard-type cooldown durations (minutes):
  - Smoke/fire, Carbon monoxide, Water leak, Flooding, Freeze risk, Intrusion
  - Default fallback for unlisted hazard types

---

## Services

### `universal_room_automation.acknowledge_notification`
Acknowledge the active CRITICAL alert, stopping repeat notifications and starting the cooldown timer. No parameters.

### `universal_room_automation.test_notification`
Send a test notification to verify channel configuration.

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| severity | No | MEDIUM | Severity level (LOW/MEDIUM/HIGH/CRITICAL) |
| channel | No | all | Specific channel to test (pushover/companion/whatsapp/tts/lights) |

---

## Integration Points

### Manager-Level Routing
NotificationAction routing is handled centrally in `CoordinatorManager._execute_action()`. When a coordinator produces a `NotificationAction`, the manager forwards it to NM:

```python
elif action.action_type == ActionType.NOTIFICATION:
    if isinstance(action, NotificationAction) and self._notification_manager:
        await self._notification_manager.async_notify(
            coordinator_id=coordinator.coordinator_id,
            severity=action.severity,
            title=action.description,
            message=action.message,
        )
```

### Hazard Re-evaluation
BaseCoordinator now has `is_hazard_active(hazard_type, location) -> bool` (default `False`). Overridden in:
- **SafetyCoordinator:** Checks `_active_hazards` dict with fuzzy matching on hazard type
- **SecurityCoordinator:** Checks `_active_alert` for intrusion/security types

### Companion App Action
NM subscribes to `mobile_app_notification_action` events. When action `ACKNOWLEDGE_URA` is received, it triggers `async_acknowledge()`.

---

## Code Review Findings (Fixed)

An Opus-level code review was conducted before release. All CRITICAL and HIGH issues were resolved:

| Priority | Issue | Fix |
|----------|-------|-----|
| CRITICAL | Pushover `user_key` never sent to API | Added `"target": user_key` to service data |
| CRITICAL | Overlapping CRITICALs corrupt state machine (old cooldown not cancelled) | `_enter_alerting` now cancels existing cooldown/countdown |
| CRITICAL | `_countdown_tick` tasks unsupervised (no cancel, concurrent duplicates) | Task reference stored, cancelled in teardown and before new cooldowns |
| HIGH | `acknowledge_notification` SQL acked ALL unacked CRITICALs | Subquery `LIMIT 1` targets most recent only |
| HIGH | TTS used wrong parameter name | `entity_id` → `media_player_entity_id` |
| HIGH | `_repeat_alert` ignored `enabled` flag | Added `enabled` guard |
| MEDIUM | Dead `_repeat_task` field | Removed, replaced with `_countdown_task` |
| MEDIUM | `async_test_notification` ignored `channel` param | Now routes to specific channel when provided |
| MEDIUM | Light pattern task not awaited after cancel | Properly awaited in teardown |

---

## Files Changed

| File | Action | Lines |
|------|--------|-------|
| `domain_coordinators/notification_manager.py` | **NEW** | ~850 |
| `quality/tests/test_notification_manager.py` | **NEW** | ~580 |
| `const.py` | MODIFY | +70 (NM constants, COORDINATOR_ENABLED_KEYS entry) |
| `database.py` | MODIFY | +80 (notification_log table, 10 new methods) |
| `domain_coordinators/signals.py` | MODIFY | +2 (SIGNAL_NM_ENTITIES_UPDATE, SIGNAL_NM_ALERT_STATE_CHANGED) |
| `domain_coordinators/manager.py` | MODIFY | +30 (NM property, lifecycle, NotificationAction routing) |
| `__init__.py` | MODIFY | +35 (NM instantiation, service registration) |
| `domain_coordinators/base.py` | MODIFY | +5 (is_hazard_active method) |
| `domain_coordinators/safety.py` | MODIFY | +15 (is_hazard_active override) |
| `domain_coordinators/security.py` | MODIFY | +10 (is_hazard_active override) |
| `switch.py` | MODIFY | +5 (NM toggle switch) |
| `sensor.py` | MODIFY | +300 (5 NM sensor classes) |
| `binary_sensor.py` | MODIFY | +40 (NMActiveAlertBinarySensor) |
| `button.py` | MODIFY | +35 (NMAcknowledgeButton) |
| `config_flow.py` | MODIFY | +250 (4 config steps) |
| `strings.json` | MODIFY | +90 (menu + step labels) |
| `translations/en.json` | MODIFY | +90 (menu + step labels) |
| `services.yaml` | MODIFY | +25 (2 new services) |

---

## Testing

34 new tests across 12 test classes:

| Test Class | Tests | Coverage |
|------------|-------|----------|
| `TestNotificationManagerInit` | 3 | Instantiation, disabled state, device info |
| `TestChannelQualification` | 4 | Severity thresholds, disabled channels, unknown channels |
| `TestQuietHours` | 3 | Manual overnight, house state sleep, house state day |
| `TestDeduplication` | 4 | First notification, within window, different location, different coordinator |
| `TestAckStateMachine` | 4 | Initial idle, critical enters repeating, ack moves to cooldown, idle no-op |
| `TestDigestFormatting` | 2 | Grouped by coordinator, empty digest |
| `TestLightPatterns` | 2 | Key patterns exist, all have effect field |
| `TestSeverityMap` | 2 | All levels mapped, correct ordering |
| `TestDedupWindows` | 1 | CRITICAL shortest window |
| `TestChannelHealth` | 3 | Initial ok, 3 failures degrade, success resets |
| `TestNotifyRouting` | 5 | Disabled NM, medium fires pushover, low suppressed, quiet hours suppress, critical bypasses |
| `TestTestNotification` | 1 | Default medium severity |

**Full suite: 679 tests passing, 0 failures.**

---

## Verification Checklist

1. Deploy → HACS → restart → verify NM device with 8 entities
2. Expected initial states: last=`none`, today=`0`, cooldown=`0`, channels=`ok`, trigger=`none`, active_alert=off
3. Test: `ura.test_notification` sends to all configured channels
4. Safety hazard → Pushover/Companion/WhatsApp/TTS/lights fire based on severity
5. CRITICAL → repeats every 30s → ack button stops repeat → cooldown starts → re-evaluate
6. Digest: LOW/MEDIUM queued, delivered at morning digest time
7. Quiet hours: non-CRITICAL suppressed during SLEEP/HOME_NIGHT
8. HA restart: unacked CRITICAL resumes, cooldown resumes, pending digest survives
