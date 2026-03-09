# PLAN: Notification Manager C4b — Inbound Text Parsing + Safe Word Ack

**Version:** v3.6.32 (target)
**Scope:** Inbound message parsing from WhatsApp/Pushover/Companion, response dictionary, safe word challenge for CRITICAL, TTS ack confirmations, BlueBubbles placeholder
**Effort:** 3-4 hours
**Dependencies:** C4a complete (v3.6.29-3.6.31), ha-wa-bridge installed, Pushover integration installed
**Deferred to C4c:** BlueBubbles iMessage (pending Mac mini setup), Telegram channel, LLM-based natural language parsing via HA Conversation API

---

## 1. OVERVIEW

### What C4b Delivers

Inbound message handling — the "reply" side of the notification system. C4a sends alerts out; C4b receives text replies back and acts on them. Three inbound channels (WhatsApp, Pushover, Companion App enhanced) plus a safe word challenge system for CRITICAL alerts.

### Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| **Ack method (CRITICAL)** | Pre-shared safe word | Family secret configured once, works from memory, gates future command processing |
| **Ack method (non-CRITICAL)** | Simple keywords (ok/stop/ack) | Low friction, no challenge needed |
| **Reply parsing** | Fixed response dictionary | Sent with each notification ("Reply: 1=Ack, 2=Status, 3=Stop"). No memorization required. LLM parsing deferred. |
| **TTS response** | Ack confirmations only | "Smoke alert acknowledged by [person]" on house speakers. Status/bidirectional deferred. |
| **BlueBubbles** | Placeholder stubs | Outbound + inbound interfaces defined but not wired. Ships when hardware is ready. |

### What It Does NOT Deliver (C4c+)

- BlueBubbles iMessage integration (outbound + inbound) — Mac mini not ready
- Telegram channel
- LLM-based natural language parsing (HA Conversation API fallback)
- Command processing beyond ack/status/stop ("lock all doors", "arm security")
- Per-person safe word overrides (household-level only for C4b)

---

## 2. RESPONSE DICTIONARY

### Standard Response Dict

Included in every notification message body:

```
Reply: 1=Acknowledge  2=Status  3=Stop alerts
```

For CRITICAL alerts, the ack option requires the safe word:

```
Reply with your safe word to acknowledge this alert.
Reply: 2=Status  3=Silence (30 min)
```

### Response Commands

| Input | Aliases | Action | CRITICAL Behavior |
|-------|---------|--------|-------------------|
| `1` or `ack` or `ok` | `acknowledge`, `a` | Acknowledge alert | Rejected — requires safe word |
| `2` or `status` | `s`, `info` | Reply with current alert summary | Same |
| `3` or `stop` | `silence`, `mute`, `quiet` | Suppress non-CRITICAL for 30 min | Same (silences repeats, does NOT ack) |
| `[safe_word]` | — | Acknowledge CRITICAL alert | Required for CRITICAL ack |
| `help` | `?`, `h` | Reply with response dict | Same |

### Parsing Rules

1. Normalize: strip whitespace, lowercase
2. Check exact match against response dict keys/aliases
3. Check safe word match (case-insensitive) for CRITICAL alerts
4. Unrecognized → reply with help text ("Unknown command. Reply: 1=Ack, 2=Status, 3=Stop")
5. Future: fall through to HA Conversation API for NL parsing (C4c)

---

## 3. SAFE WORD SYSTEM

### Configuration

Single household safe word stored in CM entry options:

```python
CONF_NM_SAFE_WORD = "nm_safe_word"  # str, configured in config flow
```

- Set in config flow step `coordinator_notifications_quiet` (or new dedicated step)
- Minimum 4 characters, no whitespace-only
- Displayed masked in UI after entry (like a password field)
- NOT sent in notifications — only the instruction "Reply with your safe word"

### Validation Flow

```
Inbound text received
  ├── Is there an active CRITICAL alert?
  │     ├── YES → Does text match safe word?
  │     │     ├── YES → Acknowledge CRITICAL, announce via TTS
  │     │     └── NO  → Check standard dict (status/stop/help only, no ack)
  │     └── NO  → Check standard response dict (ack allowed for non-CRITICAL)
  └── No active alert → Reply "No active alerts"
```

### Security Considerations

- Safe word stored in HA config entry options (encrypted at rest by HA)
- Never included in outbound notifications
- Case-insensitive comparison
- No lockout on wrong attempts (family system, not bank vault)
- Rotation: user changes it in config flow whenever needed

---

## 4. INBOUND CHANNELS

### 4.1 WhatsApp (ha-wa-bridge)

**Mechanism:** ha-wa-bridge fires `whatsapp_message_received` event on HA event bus when a reply comes in.

```python
# In async_setup():
self._unsub_wa = hass.bus.async_listen(
    "whatsapp_message_received", self._handle_whatsapp_reply
)
```

**Event data expected:**
```python
{
    "phone": "+1234567890",    # Sender phone
    "message": "ok",           # Reply text
    "timestamp": "...",
}
```

**Person matching:** Match `phone` against `CONF_NM_PERSON_WHATSAPP_PHONE` in persons list to identify who replied.

### 4.2 Pushover Reply Callbacks

**Mechanism:** Pushover supports supplementary URLs — when a user replies to a notification, Pushover POSTs the reply to a callback URL.

**Setup:**
1. NM sends notifications with `supplementary_url` pointing to an HA webhook
2. Register webhook in `async_setup()`:
   ```python
   webhook.async_register(
       hass, DOMAIN, "NM Pushover Reply",
       f"{DOMAIN}_pushover_reply",
       self._handle_pushover_webhook,
   )
   ```
3. Pushover POSTs reply text to the webhook

**Webhook payload:**
```python
{
    "user": "<user_key>",      # Pushover user key
    "message": "ok",           # Reply text
}
```

**Person matching:** Match `user` against `CONF_NM_PERSON_PUSHOVER_KEY` in persons list.

### 4.3 Companion App Enhanced

**C4a baseline:** Simple `ACKNOWLEDGE_URA` action button — tap to ack (no text input).

**C4b enhancement:** Add reply-capable notification actions:

```python
# In _send_companion():
data["actions"] = [
    {"action": "ACKNOWLEDGE_URA", "title": "Acknowledge"},
    {"action": "STATUS_URA", "title": "Status"},
    {"action": "SILENCE_URA", "title": "Silence 30min"},
]

# For CRITICAL, replace Acknowledge with a text input action:
data["actions"] = [
    {
        "action": "ACKNOWLEDGE_URA_CRITICAL",
        "title": "Acknowledge (safe word)",
        "behavior": "textInput",
        "textInputPlaceholder": "Enter safe word",
        "textInputButtonTitle": "Submit",
    },
    {"action": "STATUS_URA", "title": "Status"},
    {"action": "SILENCE_URA", "title": "Silence 30min"},
]
```

**Event listener:**
```python
# In async_setup():
self._unsub_companion = hass.bus.async_listen(
    "mobile_app_notification_action", self._handle_companion_action
)
```

### 4.4 BlueBubbles (Placeholder)

**Status:** Mac mini not yet set up. Interfaces defined, not wired.

**Outbound stub:**
```python
async def _send_imessage(self, person, title, message, severity):
    """Send via BlueBubbles iMessage. Placeholder — requires Mac mini setup."""
    _LOGGER.warning("iMessage channel not available — BlueBubbles not configured")
    return False
```

**Inbound stub:**
```python
async def _handle_imessage_reply(self, event):
    """Handle inbound iMessage via BlueBubbles. Placeholder."""
    pass

# In async_setup(), commented out:
# self._unsub_bb = hass.bus.async_listen(
#     "bluebubbles_message_received", self._handle_imessage_reply
# )
```

**Config flow:** Add `CONF_NM_IMESSAGE_ENABLED` toggle (default False, hidden behind advanced flag or simply non-functional until BB is live).

---

## 5. INBOUND MESSAGE HANDLER

### Core Processing

Single entry point for all inbound channels:

```python
async def _process_inbound_reply(
    self,
    person_id: str | None,
    channel: str,          # "whatsapp" | "pushover" | "companion" | "imessage"
    raw_text: str,
    metadata: dict | None = None,
) -> str:
    """Process an inbound text reply. Returns response text."""
```

### Flow

```
_process_inbound_reply(person, channel, text)
  │
  ├── Normalize text (strip, lowercase)
  ├── Identify person from channel metadata
  │     └── Unknown person → "Unknown sender. Reply ignored."
  ├── Parse against response dict
  │     ├── "help" / "?" → Return response dict text
  │     ├── "status" / "2" → Return current alert summary
  │     ├── "stop" / "3" → Silence non-CRITICAL 30 min, confirm
  │     ├── "ack" / "1" / "ok"
  │     │     ├── Active CRITICAL? → "CRITICAL alert requires safe word."
  │     │     ├── Active non-CRITICAL? → Acknowledge, confirm
  │     │     └── No active alert? → "No active alerts."
  │     ├── Safe word match?
  │     │     ├── Active CRITICAL? → Acknowledge CRITICAL, TTS announce, confirm
  │     │     └── No CRITICAL? → "No critical alert to acknowledge."
  │     └── Unrecognized → "Unknown command. Reply: 1=Ack, 2=Status, 3=Stop"
  │
  ├── Log inbound to DB (new table or column in notification_log)
  └── Send response back via same channel
```

### Response Sending

Reply back through the same channel the message came from:

```python
async def _send_reply(self, person_id: str, channel: str, message: str):
    """Send a text response back via the originating channel."""
    if channel == "whatsapp":
        await self._send_whatsapp_reply(person_id, message)
    elif channel == "pushover":
        await self._send_pushover_reply(person_id, message)
    elif channel == "companion":
        # Companion replies via persistent notification update
        await self._send_companion_reply(person_id, message)
```

---

## 6. TTS ACK ANNOUNCEMENTS

### Behavior

When a CRITICAL alert is acknowledged via text (safe word), NM announces on configured TTS speakers:

```python
async def _announce_ack(self, person_name: str, hazard_type: str, location: str):
    """Announce acknowledgment on house speakers."""
    message = f"{hazard_type} alert acknowledged by {person_name}"
    if location:
        message += f" in {location}"

    for speaker in self._tts_speakers:
        await self.hass.services.async_call(
            "tts", "speak",
            {
                "entity_id": speaker,
                "message": message,
            },
        )
```

### Scope (C4b)

- CRITICAL ack confirmations only
- Uses existing `CONF_NM_TTS_SPEAKERS` from C4a config
- No status announcements or bidirectional text-to-voice (deferred)

---

## 7. DATABASE CHANGES

### New Table: `notification_inbound`

```sql
CREATE TABLE IF NOT EXISTS notification_inbound (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL DEFAULT (datetime('now')),
    person_id TEXT,
    channel TEXT NOT NULL,
    raw_text TEXT NOT NULL,
    parsed_command TEXT,
    response_text TEXT,
    alert_id INTEGER REFERENCES notification_log(id),
    success INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_notification_inbound_date
    ON notification_inbound(timestamp);
```

### New database.py Methods

```python
def log_inbound(self, person_id, channel, raw_text, parsed_command, response_text, alert_id, success): ...
def get_inbound_today(self) -> int: ...
```

---

## 8. CONFIG FLOW CHANGES

### Existing Step Modification: `coordinator_notifications_persons`

Add per-person WhatsApp phone (already exists from C4a) — no change needed.

### Existing Step Modification: `coordinator_notifications_quiet`

Add safe word field to the quiet hours step (natural grouping with security-related settings):

```python
vol.Optional(
    CONF_NM_SAFE_WORD,
    default=self._get_current(CONF_NM_SAFE_WORD, ""),
): selector.TextSelector(
    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
),
```

### New Constants

```python
# Safe word
CONF_NM_SAFE_WORD = "nm_safe_word"

# BlueBubbles placeholder
CONF_NM_IMESSAGE_ENABLED = "nm_imessage_enabled"

# Inbound settings
CONF_NM_INBOUND_WHATSAPP_ENABLED = "nm_inbound_whatsapp_enabled"
CONF_NM_INBOUND_PUSHOVER_ENABLED = "nm_inbound_pushover_enabled"
CONF_NM_SILENCE_DURATION = "nm_silence_duration"  # minutes, default 30
DEFAULT_NM_SILENCE_DURATION = 30
```

---

## 9. NOTIFICATION MESSAGE FORMATTING

### Non-CRITICAL Template

```
[SEVERITY] [Title]

[Message]

Reply: 1=Ack  2=Status  3=Silence
```

### CRITICAL Template

```
CRITICAL: [Title]

[Message]

Reply with your safe word to acknowledge.
Reply: 2=Status  3=Silence repeats (30 min)
```

### Status Response Template

```
URA Alert Status:
- Active: [hazard_type] in [location] ([severity])
- State: [ALERTING/REPEATING/COOLDOWN]
- Duration: [time since first alert]
- Acked: [Yes/No] by [person] at [time]
```

---

## 10. ENTITIES (NEW/MODIFIED)

### New Sensor: `sensor.ura_notification_inbound_today`

| Field | Value |
|-------|-------|
| State | int count of inbound messages today |
| Attributes | by_channel (dict), by_command (dict), unknown_count |
| Category | DIAGNOSTIC |

### Modified: `sensor.ura_notification_diagnostics`

Add to attributes: `inbound_today`, `safe_word_configured` (bool), `inbound_channels_active` (list).

---

## 11. FILES CHANGED

| File | Action | Est. Lines |
|------|--------|------------|
| `domain_coordinators/notification_manager.py` | MODIFY | +350 (inbound handler, response dict, safe word validation, channel listeners, reply sending, TTS ack) |
| `const.py` | MODIFY | +15 (new CONF_NM_* constants) |
| `database.py` | MODIFY | +25 (notification_inbound table, log_inbound, get_inbound_today) |
| `config_flow.py` | MODIFY | +15 (safe word field in quiet step, inbound toggles) |
| `sensor.py` | MODIFY | +60 (NMInboundTodaySensor, update diagnostics sensor) |
| `strings.json` + `translations/en.json` | MODIFY | +20 (safe word label, inbound field labels) |
| `services.yaml` | MODIFY | +10 (test_inbound service for debugging) |
| `quality/tests/test_notification_manager.py` | MODIFY | +150 (inbound parsing, safe word validation, response dict, channel routing) |
| **Total** | | **~645 lines** |

---

## 12. TESTING PLAN

### Unit Tests (~15 new tests)

1. **Response dict parsing** — each command + aliases resolve correctly
2. **Safe word validation** — correct word acks CRITICAL, wrong word rejected
3. **Non-CRITICAL ack** — simple "ok" works without safe word
4. **CRITICAL ack rejected without safe word** — "ok"/"ack" returns challenge prompt
5. **Unknown command** — returns help text
6. **Person matching** — WhatsApp phone → person, Pushover key → person, unknown → rejected
7. **Inbound logging** — DB records created correctly
8. **Status response** — correct format with active alert details
9. **Silence command** — suppresses non-CRITICAL for configured duration
10. **TTS ack announcement** — service called with correct message
11. **Reply sending** — response routed back to originating channel
12. **No active alert** — all commands return "No active alerts" gracefully
13. **Companion action parsing** — ACKNOWLEDGE_URA_CRITICAL with text input
14. **Safe word not configured** — CRITICAL ack falls back to standard ack (or rejects?)
15. **Inbound today sensor** — correct count and breakdown

### Integration Tests (manual, post-deploy)

1. WhatsApp: send "1" → ack non-CRITICAL → TTS announces
2. WhatsApp: send safe word → ack CRITICAL → TTS announces
3. WhatsApp: send "status" → receive alert summary reply
4. Pushover: reply to notification → webhook fires → ack processed
5. Companion: tap "Acknowledge" action → ack processed
6. Companion: CRITICAL → text input → enter safe word → ack processed
7. Unknown person texts → rejected gracefully

---

## 13. VERIFICATION CHECKLIST

1. `PYTHONPATH=quality python3 -m pytest quality/tests/ -v` — all tests pass
2. Deploy → HACS → restart → verify new sensor appears
3. Configure safe word in config flow (quiet hours step)
4. Trigger safety hazard → verify notification includes response dict
5. Trigger CRITICAL → verify notification asks for safe word (no dict ack option)
6. Reply via WhatsApp with safe word → verify ack + TTS announcement
7. Reply via WhatsApp with "status" → verify status reply received
8. Reply with unknown text → verify help text reply
9. HA restart → verify inbound listeners re-register
10. Check `sensor.ura_notification_inbound_today` shows correct count

---

## 14. OPEN QUESTIONS / FUTURE (C4c+)

1. **Per-person safe words** — household-level for C4b, per-person overrides later
2. **Command processing** — "[safe_word] lock all doors" pattern, requires command registry
3. **LLM fallback** — unrecognized text → HA Conversation API for intent classification
4. **Rate limiting inbound** — prevent spam/loops (probably not needed for family system)
5. **BlueBubbles activation** — flip the stubs live once Mac mini is running
6. **Telegram** — new outbound + inbound channel
