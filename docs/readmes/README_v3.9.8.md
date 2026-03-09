# URA v3.9.8 — iMessage/BlueBubbles Channel + Pushover Device Fix + Review Protocol Fixes

## Overview
Adds iMessage (via BlueBubbles) as the 6th notification channel, fixes Pushover device targeting, and addresses 10 issues found by the 2-review protocol across secondary codepaths (repeat alerts, digest, test service, diagnostics).

## Changes

### iMessage (BlueBubbles) Channel
- **Outbound**: `bluebubbles.send_message` service with `addresses` (list) + `message` fields
- **Inbound**: HA webhook receives BlueBubbles server `new-message` webhook POSTs, skips `isFromMe` echoes
- **Person matching**: Apple ID email (case-insensitive exact) or phone (last 10 digits)
- **Config flow**: iMessage enable toggle + severity threshold at channel level, iMessage handle per person
- **Channel integration**: Included in severity routing, digest delivery cascade, test_notification, repeat alerts, diagnostics

### Pushover Device Targeting Fix
- `target` parameter now correctly sends device name (e.g., "iphone"), not user key
- Config flow: Pushover device name text field per person
- Device param propagated through all codepaths: async_notify, _repeat_alert, _fire_digest, async_test_notification, _send_reply

### Review Protocol Fixes (10 issues)
- **C1**: Safe word ack captures `hazard_type`/`location` before calling `async_acknowledge()` — prevents race condition crash
- **C2**: `_repeat_alert` passes Pushover `device` param — CRITICAL repeats now target configured device
- **H1**: `_repeat_alert` includes WhatsApp and iMessage channels — CRITICAL repeats no longer silent on text channels
- **H2**: `async_test_notification` adds iMessage branch + Pushover device
- **H3**: `_fire_digest` adds iMessage to cascade + Pushover device
- **H4**: `diagnostics_summary` reports iMessage inbound status
- **H5**: `test_inbound` service accepts `"imessage"` channel (services.yaml + __init__.py vol.In)
- **M2**: `color_temp` → `color_temp_kelvin` in alert light save/restore (HA 2026.3 compliance)
- **M4**: BB webhook handler uses direct `await` instead of `async_create_task` (proper error propagation)
- **M5**: `addresses` param sent as list `[handle]` for BlueBubbles schema correctness

### Config Flow
- Channel step: iMessage enable + severity threshold
- Person step: Pushover device name, iMessage handle
- All new fields have safe `.get()` defaults for backward compatibility

### Test Coverage
- 93 NM tests (13 new): BB webhook routing, person matching, Pushover device targeting, iMessage channel qualification, iMessage outbound
- 738 total tests passing

## Files Changed
- `domain_coordinators/notification_manager.py` — iMessage send/receive, review fixes (~175 lines)
- `const.py` — 6 new constants (iMessage config, Pushover device, BB webhook ID)
- `config_flow.py` — iMessage + Pushover device fields in channel and person steps
- `__init__.py` — `"imessage"` added to test_inbound vol.In validation
- `services.yaml` — `"imessage"` option for test_inbound channel selector
- `strings.json` + `translations/en.json` — UI labels and descriptions
- `quality/tests/test_notification_manager.py` — 13 new tests

## Post-Deploy Setup
1. Register BlueBubbles server webhook (see `docs/PLAN_nm_bluebubbles_imessage.md` Section 4)
2. Configure person iMessage handles in URA config flow
3. Configure Pushover device names per person
