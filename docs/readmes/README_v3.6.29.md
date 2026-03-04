# v3.6.29 — Notification Manager (C4a)

**Date:** 2026-03-04
**Scope:** New domain coordinator service — centralized outbound notification delivery

## Summary

Safety and Security coordinators generate hazards and alerts that update sensor state and log entries, but nobody actually gets notified. The Notification Manager (NM) centralizes outbound notification delivery across 5 channel types with severity-based routing, per-person configuration, and a full ack/cooldown/re-fire state machine for CRITICAL alerts.

## What's New

### Notification Manager Service
- **5 channel types:** Pushover, Companion App, WhatsApp, TTS, Alert Lights
- **Severity-based routing:** Per-channel minimum severity thresholds (LOW/MEDIUM/HIGH/CRITICAL)
- **Per-person config:** Individual Pushover keys, Companion App services, WhatsApp phones
- **Delivery preferences:** Immediate, Daily Digest, or Off — per person
- **Quiet hours:** House state-based (sleep/home_night) or manual time window
- **Deduplication:** Per-severity time windows prevent notification spam
- **SQLite persistence:** Full notification log with 30-day retention

### CRITICAL Alert State Machine
- **AlertState:** IDLE -> ALERTING -> REPEATING -> COOLDOWN -> RE_EVALUATE -> (ALERTING or IDLE)
- **Repeat:** CRITICAL alerts repeat every 30 seconds until acknowledged
- **Acknowledge:** Via HA button entity or Companion App action button
- **Cooldown:** Per-hazard-type configurable cooldown after acknowledgement
- **Re-fire:** After cooldown, queries source coordinator — re-fires if hazard still active
- **Restart recovery:** Unacked CRITICALs resume repeating, cooldowns resume timing

### Alert Lights
- 13 light patterns: fire, smoke, water_leak, flooding, CO, freeze, warning, intruder, armed, investigate, arriving, sequential, fade
- Saves/restores original light states around alert patterns

### Entities (8 new)
- **Switch:** `switch.ura_notification_manager_enabled` — enable/disable toggle
- **Sensors:** Last notification, notifications today, cooldown remaining, channel status (diagnostic), trigger
- **Binary sensor:** Active alert (safety device class)
- **Button:** Acknowledge alert

### Config Flow
- 4 new options steps: Channel config, Person setup, Quiet hours, Per-hazard cooldowns
- Accessible from Coordinator Manager options menu

### Services
- `ura.acknowledge_notification` — Acknowledge active CRITICAL alert
- `ura.test_notification` — Test notification with optional severity and channel filter

## Files Changed

| File | Action |
|------|--------|
| `domain_coordinators/notification_manager.py` | NEW (~850 lines) |
| `quality/tests/test_notification_manager.py` | NEW (~580 lines) |
| `const.py` | +70 lines (NM constants) |
| `database.py` | +30 lines (notification_log table + methods) |
| `domain_coordinators/signals.py` | +2 lines |
| `domain_coordinators/manager.py` | +30 lines (NM lifecycle + NotificationAction routing) |
| `__init__.py` | +35 lines (NM instantiation + service registration) |
| `domain_coordinators/base.py` | +5 lines (is_hazard_active) |
| `domain_coordinators/safety.py` | +15 lines (is_hazard_active override) |
| `domain_coordinators/security.py` | +10 lines (is_hazard_active override) |
| `switch.py` | +5 lines |
| `sensor.py` | +300 lines (5 NM sensors) |
| `binary_sensor.py` | +40 lines |
| `button.py` | +35 lines |
| `config_flow.py` | +250 lines (4 config steps) |
| `strings.json` / `translations/en.json` | +90 lines each |
| `services.yaml` | +25 lines |

## Testing

- 34 new tests covering: init, channel qualification, quiet hours, deduplication, ack state machine, digest formatting, light patterns, severity ordering, channel health, notify routing, test notification
- Full suite: 679 tests passing
