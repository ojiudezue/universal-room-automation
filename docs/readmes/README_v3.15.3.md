# v3.15.3: NM Messaging Kill Switch + Live Severity Refresh

**Date:** 2026-03-13
**Branch:** develop -> main
**Tests:** 1063 passed (no regressions)

## Problem

When testing the Notification Manager at LOW severity, coordinators flooded all channels with alerts on every decision cycle. Raising the severity threshold via OptionsFlow didn't help because:
1. The NM's config dict was a snapshot from init — severity changes only took effect after HA restart
2. No way to immediately stop in-flight alerts without fully disabling the NM (which tears down webhooks, digest timers, etc.)

## Solution

### 1. Messaging Kill Switch (`switch.ura_nm_messaging_suppressed`)

New switch entity on the NM device. When turned ON:
- All outbound notifications are blocked at the top of `async_notify()`
- Active repeating alerts are cancelled (state reset to IDLE, repeat timer cancelled)
- Silence timer is cleared
- NM itself stays running — monitoring, diagnostics, inbound processing continue

When turned OFF: messaging resumes normally.

### 2. Live Config Refresh (`_refresh_config()`)

`async_notify()` and `_repeat_alert()` now re-read the coordinator manager config entry on each call. Severity threshold changes in OptionsFlow take effect immediately without restart.

### Flow
1. User changes WhatsApp severity from LOW to HIGH in OptionsFlow
2. Next `async_notify()` call re-reads config from the config entry
3. `_channel_qualifies("whatsapp", Severity.LOW)` now returns False
4. No more WhatsApp spam

### Files Changed

| File | Changes |
|------|---------|
| `notification_manager.py` | `_messaging_suppressed` flag, `async_suppress/resume_messaging()`, `_refresh_config()`, suppression checks in `async_notify` + `_repeat_alert`, diagnostics |
| `switch.py` | `NMMessagingSuppressSwitch` class + registration |
