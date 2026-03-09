# URA v3.9.7 — Notification Manager C4b: Inbound Message Handling

## Overview
Completes the Notification Manager with bidirectional messaging. Users can now reply to notifications via any channel (Companion App, WhatsApp, Pushover) to acknowledge alerts, check status, silence non-critical notifications, or acknowledge CRITICAL alerts with a safe word.

## Changes

### Notification Manager — Inbound Message Handling
- **Response dictionary**: Fixed command parsing — `1/ack/ok/a/acknowledge` → ack, `2/status/s/info` → status, `3/stop/silence/mute/quiet` → silence, `help/?/h` → help
- **Safe word system**: Household secret word (min 4 chars) stored as password in config flow, required for CRITICAL alert acknowledgment. Case-insensitive. Never sent in outbound notifications, redacted as `[safe_word]` in DB logs
- **Silence mechanism**: Reply "silence" to suppress non-CRITICAL outbound notifications for configurable duration (default 30 min). CRITICAL alerts bypass silence
- **3-channel inbound support**:
  - **Companion App**: Action buttons (Acknowledge/Status/Silence) for non-CRITICAL, text input for CRITICAL safe word entry
  - **WhatsApp**: Event bus listener for `whatsapp_message_received` events, person matching by phone number (last 10 digits)
  - **Pushover**: Webhook registration for reply callbacks, person matching by Pushover user key
- **TTS acknowledgment**: CRITICAL alert ack triggers TTS announcement on configured speakers
- **Inbound diagnostic sensor**: `sensor.ura_notification_inbound_today` — count, by_channel, by_command, safe_word_configured
- **DB persistence**: `notification_inbound` table with automatic 30-day pruning (matches notification_log retention)

### Config Flow
- Added safe word (password field) and silence duration (5-120 min) to quiet hours step
- Updated strings.json and translations/en.json

### Services
- `test_inbound`: Simulate inbound text reply for testing response dictionary and safe word system

### Test Coverage
- 80 NM tests (21 new for C4b): response dict parsing, inbound processing, safe word validation, person matching, inbound counters, silenced message handling, active alert inbound, channel handler routing
- 725 total tests passing

## Files Changed
- `domain_coordinators/notification_manager.py` — ~350 lines added for inbound handling
- `database.py` — notification_inbound table, log_inbound(), get_inbound_today(), prune_inbound_log()
- `sensor.py` — NMInboundTodaySensor
- `const.py` — CONF_NM_SAFE_WORD, CONF_NM_SILENCE_DURATION, DEFAULT_NM_SILENCE_DURATION
- `config_flow.py` — safe word + silence duration fields
- `__init__.py` — test_inbound service handler
- `services.yaml` — test_inbound service definition
- `strings.json` + `translations/en.json` — UI labels
- `quality/tests/test_notification_manager.py` — 21 new tests
