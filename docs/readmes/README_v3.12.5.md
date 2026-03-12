# v3.12.5 — BlueBubbles + WhatsApp Service Call Fixes

## Bugs Fixed

### BlueBubbles iMessage: `'list' object has no attribute 'strip'` (64 occurrences)
- **Root cause**: `_send_imessage()` passed `addresses` as a Python list `[handle]`, but the `bluebubbles.send_message` service expects a **string** (comma-separated addresses, e.g. `"+15558675309, a.contact@me.com"`)
- **Fix**: Changed `{"addresses": [handle], ...}` to `{"addresses": handle, ...}`

### WhatsApp: `Neither number nor group_name provided` (64 occurrences)
- **Root cause**: `_send_whatsapp()` used wrong field names — `phone` instead of `number`, `body` instead of `message`
- **Fix**: Changed `{"phone": phone, "body": ...}` to `{"number": phone, "message": ...}`

## Files Changed
- `domain_coordinators/notification_manager.py` — Fixed both service call data dicts
- `quality/tests/test_notification_manager.py` — Updated iMessage test assertion
