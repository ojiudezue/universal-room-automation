# v3.15.3: NM Messaging Kill Switch + Live Severity Refresh + Inbound Spam Fix

**Date:** 2026-03-13
**Branch:** develop -> main
**Tests:** 1064 passed (1 new test, no regressions)

## Problem

Three NM issues discovered during testing:

1. **Severity changes ignored at runtime**: NM config was a snapshot from init. Raising severity from LOW to HIGH didn't stop in-flight alerts without HA restart.
2. **No way to stop outbound spam**: The only option was fully disabling the NM, which tears down webhooks, digest timers, and monitoring.
3. **Inbound spam from all iMessages**: BlueBubbles webhook fired for ALL incoming iMessages (from anyone), not just NM reply threads. Unknown senders got "Unknown command" replies, and even known persons' random texts triggered the reply bot.

## Solution

### 1. Messaging Kill Switch (`switch.ura_notification_manager_messaging_suppressed`)

New switch entity on the NM device. When turned ON:
- All outbound notifications blocked at top of `async_notify()`
- Active repeating alerts cancelled (state reset to IDLE, repeat timer cancelled)
- Inbound reply processing blocked
- NM itself stays running — monitoring, diagnostics, webhooks remain active

When turned OFF: messaging resumes normally.

### 2. Live Config Refresh (`_refresh_config()`)

`async_notify()` and `_repeat_alert()` now re-read the coordinator manager config entry on each call. Severity threshold changes in OptionsFlow take effect immediately without restart.

### 3. Inbound Message Filtering

Three layers of protection against inbound spam:

- **Unknown sender guard**: All 3 inbound handlers (BB, WhatsApp, Pushover) now silently ignore messages from senders that don't match a configured person handle. Previously, `person_id=None` was passed through and processed.
- **Unrecognized command context check**: "Unknown command" replies are only sent when there's an active alert or recent notification (`_notifications_today_count > 0`). Random texts from known persons are silently ignored when there's no NM context.
- **Kill switch blocks replies**: When messaging is suppressed, `_process_inbound_reply` returns immediately.

### Files Changed

| File | Changes |
|------|---------|
| `notification_manager.py` | `_messaging_suppressed` flag, `async_suppress/resume_messaging()`, `_refresh_config()`, suppression checks in `async_notify` + `_repeat_alert` + `_process_inbound_reply`, unknown sender guards on all 3 inbound handlers, context-gated unknown command replies, diagnostics |
| `switch.py` | `NMMessagingSuppressSwitch` class + registration |
| `test_notification_manager.py` | Updated unknown command tests for context requirement, new test for contextless ignore |
