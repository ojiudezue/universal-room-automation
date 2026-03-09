# PLAN: NM BlueBubbles/iMessage Channel + Pushover Device Fix

**Version:** v3.9.8
**Date:** 2026-03-09
**Parent:** PLAN_notification_manager_c4b.md (C4b complete in v3.9.7)
**Status:** Ready to implement
**Depends on:** BlueBubbles server running, webhook API accessible

---

## OVERVIEW

Add iMessage as a 4th messaging channel to the Notification Manager via the BlueBubbles
HA integration (outbound) and BlueBubbles server webhooks (inbound). Also fix Pushover
per-device targeting — the `target` parameter in HA's Pushover notify service expects
a **device name** (e.g., "iphone", "pixel3"), not a user key.

---

## 1. PUSHOVER DEVICE TARGETING FIX

### Problem
`_send_pushover()` passes `user_key` as the `target` parameter. HA's Pushover service
expects device names for `target`. Passing an unrecognized string causes Pushover to
deliver to **all** devices (silent fallback), so it "works" but can't target a specific
phone.

### Fix

**const.py** — Add:
```python
CONF_NM_PERSON_PUSHOVER_DEVICE: Final = "nm_person_pushover_device"
```

**notification_manager.py** — `_send_pushover()`:
- Add `device: str = ""` parameter
- If device is non-empty, set `data["target"] = device`
- If device is empty, omit `target` (sends to all devices for that account)
- Keep `user_key` parameter for inbound webhook matching only

**Outbound call site** (line ~585):
```python
pushover_key = person_cfg.get(CONF_NM_PERSON_PUSHOVER_KEY, "")
pushover_device = person_cfg.get(CONF_NM_PERSON_PUSHOVER_DEVICE, "")
if pushover_key:
    await self._send_pushover(title, msg, severity, pushover_key, pushover_device)
```

**_send_reply** pushover section:
- Also pass device when replying

**config_flow.py** — Person step: add `CONF_NM_PERSON_PUSHOVER_DEVICE` TextSelector
after the existing pushover_key field.

**strings.json / en.json** — Add:
```json
"nm_person_pushover_device": {
  "name": "Pushover Device Name",
  "description": "Device name as shown in your Pushover app (Settings → Devices). Leave empty to send to all devices."
}
```

**Note on dropdown:** Pushover device names are not exposed as HA entities. A dynamic
dropdown would require querying the Pushover API (`/1/users/validate.json`) at config
flow time with the user key + app token. The app token lives in HA's Pushover config
entry, not in URA. For now, TextSelector with a clear description. Could add Pushover
API querying as a future polish if needed.

**Inbound unchanged** — Pushover webhook still sends `user` (user key), so
`_match_person_by_pushover_key` continues to work as-is.

---

## 2. BLUEBUBBLES/iMESSAGE CHANNEL

### 2.1 Architecture

```
Outbound: NM → bluebubbles.send_message service → BB server → iMessage
Inbound:  iMessage → BB server → webhook POST → HA webhook → NM._handle_bb_webhook
```

- **Outbound** uses the existing `bluebubbles.send_message` HA service (addresses + message)
- **Inbound** uses an HA-registered webhook. The BB server's webhook system POSTs
  `{"type": "new-message", "data": {...}}` to our URL when a message arrives.

### 2.2 Constants (const.py)

```python
CONF_NM_IMESSAGE_ENABLED: Final = "nm_imessage_enabled"
CONF_NM_IMESSAGE_SEVERITY: Final = "nm_imessage_severity"
DEFAULT_NM_IMESSAGE_SEVERITY: Final = "HIGH"
CONF_NM_PERSON_IMESSAGE_HANDLE: Final = "nm_person_imessage_handle"
WEBHOOK_BB_ID: Final = f"{DOMAIN}_bluebubbles_reply"
```

The person's "handle" is their iMessage address — either a phone number (+15551234567)
or an Apple ID email (user@icloud.com). This is what BB sends in inbound webhook data
and what we pass to `bluebubbles.send_message` as the `addresses` field.

### 2.3 Outbound: `_send_imessage()`

```python
async def _send_imessage(
    self, title: str, message: str, handle: str,
) -> None:
    """Send notification via BlueBubbles (iMessage)."""
    try:
        await self.hass.services.async_call(
            "bluebubbles", "send_message",
            {"addresses": handle, "message": f"{title}\n{message}"},
            blocking=True,
        )
        self._update_channel_health("imessage", True)
    except Exception as e:
        _LOGGER.error("iMessage send via BlueBubbles failed: %s", e)
        self._update_channel_health("imessage", False)
```

### 2.4 Inbound: Webhook Registration

In `async_setup()`, after the Pushover webhook block:

```python
# C4b+: Register BlueBubbles inbound webhook
if self._config.get(CONF_NM_IMESSAGE_ENABLED, False):
    try:
        webhook.async_register(
            self.hass, DOMAIN, "NM BlueBubbles Reply",
            WEBHOOK_BB_ID, self._handle_bb_webhook,
        )
        self._bb_webhook_registered = True
    except Exception:
        _LOGGER.warning("BlueBubbles webhook registration failed")
```

In `async_teardown()`:
```python
if self._bb_webhook_registered:
    webhook.async_unregister(self.hass, WEBHOOK_BB_ID)
    self._bb_webhook_registered = False
```

### 2.5 Inbound: Webhook Handler

The BB server POSTs JSON like:
```json
{
  "type": "new-message",
  "data": {
    "guid": "message-guid",
    "text": "ok",
    "handle": {
      "address": "+15551234567"
    },
    "isFromMe": false,
    "chats": [{"chatIdentifier": "iMessage;-;+15551234567"}],
    ...
  }
}
```

Handler:
```python
async def _handle_bb_webhook(
    self, hass: HomeAssistant, webhook_id: str, request,
) -> None:
    """Handle BlueBubbles new-message webhook POST."""
    try:
        data = await request.json()
    except Exception:
        return

    # Only process incoming messages (not our own outbound)
    event_type = data.get("type", "")
    if event_type != "new-message":
        return

    msg_data = data.get("data", {})

    # Skip messages sent by us
    if msg_data.get("isFromMe", False):
        return

    text = msg_data.get("text", "")
    if not text:
        return

    # Extract sender handle (phone or email)
    handle_obj = msg_data.get("handle", {})
    sender = handle_obj.get("address", "") if isinstance(handle_obj, dict) else ""

    person_id = self._match_person_by_imessage_handle(sender)
    self.hass.async_create_task(
        self._process_inbound_reply(person_id, "imessage", text)
    )
```

### 2.6 Person Matching

```python
def _match_person_by_imessage_handle(self, handle: str) -> str | None:
    """Match an iMessage handle (phone or email) to a person entity ID."""
    persons = self._config.get(CONF_NM_PERSONS, [])
    normalized = handle.strip().lower()
    for p in persons:
        p_handle = p.get(CONF_NM_PERSON_IMESSAGE_HANDLE, "").strip().lower()
        if not p_handle:
            continue
        # Email match: exact case-insensitive
        if "@" in p_handle and p_handle == normalized:
            return p.get(CONF_NM_PERSON_ENTITY)
        # Phone match: last 10 digits (same as WhatsApp)
        if "@" not in p_handle and normalized.endswith(p_handle[-10:]):
            return p.get(CONF_NM_PERSON_ENTITY)
    return None
```

### 2.7 Reply Routing

In `_send_reply()`:
```python
elif channel == "imessage":
    handle = person_cfg.get(CONF_NM_PERSON_IMESSAGE_HANDLE, "")
    if handle:
        await self._send_imessage("URA", message, handle)
```

### 2.8 Outbound Notification Routing

In `async_notify()`, after the WhatsApp block (around line 638):

```python
# iMessage (BlueBubbles)
if self._channel_qualifies("imessage", severity):
    imessage_handle = person_cfg.get(CONF_NM_PERSON_IMESSAGE_HANDLE, "")
    if imessage_handle:
        if effective_pref == NM_DELIVERY_IMMEDIATE:
            await self._send_imessage(title, message_with_dict, imessage_handle)
            channels_fired.append("imessage")
            if database:
                await database.log_notification(
                    coordinator_id, severity_str, title, message,
                    hazard_type, location, person_id, "imessage", 1,
                )
        elif effective_pref == NM_DELIVERY_DIGEST:
            if database:
                await database.log_notification(
                    coordinator_id, severity_str, title, message,
                    hazard_type, location, person_id, "imessage", 0,
                )
```

### 2.9 Channel Infrastructure Updates

**`__init__` of NotificationManager:**

Add to `_channel_health`:
```python
"imessage": {"status": "ok", "last_success": None, "failures": 0},
```

Add to `_notifications_by_channel`:
```python
"imessage": 0,
```

Add to `_inbound_by_channel`:
```python
"imessage": 0,
```

Add state tracking:
```python
self._bb_webhook_registered: bool = False
```

**`_channel_qualifies`** — Add entry:
```python
"imessage": (CONF_NM_IMESSAGE_ENABLED, CONF_NM_IMESSAGE_SEVERITY, DEFAULT_NM_IMESSAGE_SEVERITY),
```

---

## 3. CONFIG FLOW UI

### 3.1 Channel Step (`coordinator_notifications`)

Add after WhatsApp fields:

```python
vol.Optional(
    CONF_NM_IMESSAGE_ENABLED,
    default=self._get_current(CONF_NM_IMESSAGE_ENABLED, False),
): selector.BooleanSelector(),
vol.Optional(
    CONF_NM_IMESSAGE_SEVERITY,
    default=self._get_current(CONF_NM_IMESSAGE_SEVERITY, DEFAULT_NM_IMESSAGE_SEVERITY),
): selector.SelectSelector(
    selector.SelectSelectorConfig(
        options=severity_options,
        mode=selector.SelectSelectorMode.DROPDOWN,
    )
),
```

### 3.2 Person Step (`coordinator_notifications_persons`)

Add after WhatsApp phone field:

```python
vol.Optional(
    CONF_NM_PERSON_IMESSAGE_HANDLE,
    default="",
): selector.TextSelector(),
```

And add after Pushover key field:

```python
vol.Optional(
    CONF_NM_PERSON_PUSHOVER_DEVICE,
    default="",
): selector.TextSelector(),
```

### 3.3 Strings / Translations

**Channel labels:**
```json
"nm_imessage_enabled": {
  "name": "iMessage (BlueBubbles) Enabled",
  "description": "Enable iMessage notifications via BlueBubbles. Requires BlueBubbles server and HA integration."
},
"nm_imessage_severity": {
  "name": "iMessage Severity Threshold",
  "description": "Minimum severity to trigger iMessage. Default: HIGH."
}
```

**Person labels:**
```json
"nm_person_imessage_handle": {
  "name": "iMessage Handle",
  "description": "Apple ID email or phone number for iMessage (e.g., user@icloud.com or +15551234567). Leave empty if not using."
},
"nm_person_pushover_device": {
  "name": "Pushover Device Name",
  "description": "Device name registered in Pushover (e.g., 'iphone'). Leave empty to send to all devices."
}
```

---

## 4. WEBHOOK SETUP ON BB SERVER (One-Time, After Code Deploy)

The BlueBubbles server runs on a Mac mini on the local network. It has a built-in
webhook system that POSTs events (like incoming messages) to registered URLs.

We need to register one webhook so the BB server sends `new-message` events to
HA's webhook endpoint, where our NM code will process them.

### Prerequisites
- BlueBubbles server running on Mac mini (confirmed: v0.3.5, HA entry `01KK9TV6WECCPK3CPJX37337ZD`)
- HA integration loaded (service `bluebubbles.send_message` available)
- URA v3.9.8 deployed with the webhook handler code
- Know your BB server password (set during BB server setup)

### HA Webhook URL

Since the Mac mini and HA are on the same local network (`192.168.13.x`), use the
local URL for lowest latency and no internet dependency:

```
http://192.168.13.13:8123/api/webhook/universal_room_automation_bluebubbles_reply
```

Alternative (if you need it to work when local network is down, via Cloudflare tunnel):
```
https://madronehaos.phalanxmadrone.com/api/webhook/universal_room_automation_bluebubbles_reply
```

### Option A: Register via BlueBubbles Server UI (Recommended)

1. **Open the BlueBubbles server app** on the Mac mini
   - If you access it remotely, open the BB server's web UI (typically `http://<mac-mini-ip>:1234`)
2. **Navigate to API & Webhooks**
   - In the left sidebar, click **"API & Webhooks"**
3. **Click "Add Webhook"** (or the + button)
4. **Fill in the webhook form:**
   - **URL:** `http://192.168.13.13:8123/api/webhook/universal_room_automation_bluebubbles_reply`
   - **Events:** Select **"New Messages"** from the dropdown
     - Do NOT select "All Events" — we only need `new-message`
5. **Save** the webhook
6. **Verify** it appears in the webhooks table with status active

### Option B: Register via BB Server API (curl)

From any machine on the local network (or the Mac mini itself):

```bash
# Find the BB server IP and port (default port is 1234)
# Replace <BB_PASSWORD> with your BlueBubbles server password

curl -X POST "http://<mac-mini-ip>:1234/api/v1/webhook?password=<BB_PASSWORD>" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "http://192.168.13.13:8123/api/webhook/universal_room_automation_bluebubbles_reply",
    "events": ["new-message"]
  }'
```

Expected response:
```json
{
  "status": 200,
  "message": "Successfully created webhook!",
  "data": {
    "id": 1,
    "url": "http://192.168.13.13:8123/api/webhook/...",
    "events": ["new-message"]
  }
}
```

### Verify the webhook works

1. **Send a test iMessage** to the phone number linked to the BB server
   (from a different Apple ID / phone)
2. **Check HA logs** for:
   ```
   DEBUG [universal_room_automation.notification_manager] BlueBubbles inbound: ...
   ```
3. Or use the URA `test_inbound` service to verify the NM processes commands correctly

### Troubleshooting

- **Webhook not firing?** Check BB server logs (View → Logs in the BB app). It logs
  each webhook dispatch attempt and failures.
- **HA not receiving?** Verify the URL is reachable from the Mac mini:
  `curl -X POST http://192.168.13.13:8123/api/webhook/universal_room_automation_bluebubbles_reply -d '{"type":"test"}'`
- **BB server IP changed?** Check the BB server's network settings or your router's
  DHCP leases. Consider assigning a static IP to the Mac mini.
- **Webhook registered but wrong events?** List existing webhooks:
  `curl "http://<mac-mini-ip>:1234/api/v1/webhook?password=<BB_PASSWORD>"`
  Delete and re-create if needed:
  `curl -X DELETE "http://<mac-mini-ip>:1234/api/v1/webhook/<webhook_id>?password=<BB_PASSWORD>"`

---

## 5. TESTS

### 5.1 New Test Cases

Add to `test_notification_manager.py`:

**TestBlueBubblesOutbound:**
- `test_send_imessage_calls_service` — verify `bluebubbles.send_message` called with correct addresses/message
- `test_send_imessage_failure_updates_health` — verify channel health degrades on exception

**TestBlueBubblesInbound:**
- `test_bb_webhook_routes_new_message` — POST with `{"type": "new-message", "data": {"text": "ok", "handle": {"address": "+15551234567"}, "isFromMe": false}}` → routes to `_process_inbound_reply`
- `test_bb_webhook_skips_from_me` — `isFromMe: true` → no processing
- `test_bb_webhook_skips_non_new_message` — `type: "updated-message"` → no processing
- `test_bb_webhook_skips_empty_text` — empty text → no processing

**TestImessagePersonMatching:**
- `test_match_by_email` — `user@icloud.com` matches configured handle
- `test_match_by_phone_last_10` — `+15551234567` matches `5551234567`
- `test_no_match_returns_none`

**TestPushoverDeviceTargeting:**
- `test_send_pushover_with_device` — verify `target` is device name when configured
- `test_send_pushover_no_device_omits_target` — verify no `target` when device empty

**TestImessageChannelQualifies:**
- `test_imessage_channel_qualifies` — enabled + severity met → True
- `test_imessage_channel_not_enabled` → False

### 5.2 Update Existing Tests

- Update `_make_config()` helper to include iMessage defaults
- Update channel health assertions to include "imessage" key
- Update inbound_by_channel assertions to include "imessage" key

---

## 6. FILES TO MODIFY

| File | Changes |
|------|---------|
| `const.py` | Add 5 new constants (CONF_NM_IMESSAGE_*, CONF_NM_PERSON_IMESSAGE_HANDLE, CONF_NM_PERSON_PUSHOVER_DEVICE, WEBHOOK_BB_ID, DEFAULT_NM_IMESSAGE_SEVERITY) |
| `notification_manager.py` | Add `_send_imessage()`, `_handle_bb_webhook()`, `_match_person_by_imessage_handle()`, webhook registration/teardown, outbound routing block, channel infrastructure (health, counters, qualifies), fix `_send_pushover()` target param |
| `config_flow.py` | Add iMessage enable/severity in channel step, iMessage handle + Pushover device in person step |
| `strings.json` | Add labels for 4 new fields |
| `translations/en.json` | Mirror strings.json |
| `test_notification_manager.py` | ~12 new tests, update helpers |

---

## 7. IMPLEMENTATION ORDER

1. **const.py** — Add all new constants
2. **notification_manager.py** — Pushover device fix first (small, isolated)
3. **notification_manager.py** — BlueBubbles outbound (`_send_imessage`, outbound routing, channel infra)
4. **notification_manager.py** — BlueBubbles inbound (webhook handler, person matching, reply routing, registration/teardown)
5. **config_flow.py** — UI fields for iMessage + Pushover device
6. **strings.json + en.json** — Translations
7. **Tests** — All new + updated tests
8. **Run test suite** — Verify 0 regressions
9. **Deploy & configure** — Register BB server webhook, configure person handles in UI

---

## 8. NAMING CONVENTION

Use "imessage" (not "bluebubbles") as the internal channel name throughout:
- Channel health key: `"imessage"`
- Inbound by channel: `"imessage"`
- Channel qualifies key: `"imessage"`
- Log entries: channel = `"imessage"`

This is user-facing terminology. BlueBubbles is the transport layer; iMessage is what
the user thinks of. Config labels use "iMessage (BlueBubbles)" to clarify both.
