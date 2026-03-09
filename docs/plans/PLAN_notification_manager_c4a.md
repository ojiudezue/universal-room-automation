# PLAN: Notification Manager C4a — Core Outbound + Ack Engine

**Version:** v3.6.29
**Scope:** Notification Manager shared service — channels, persons, outbound delivery, ack/cooldown/re-fire, quiet hours, alert lights, digest mode, SQLite persistence, legacy notification deprecation, sensors
**Effort:** 5-7 hours (largest single cycle)
**Dependencies:** C0-C3 complete, Pushover integration installed, HA Companion App installed, ha-wa-bridge (WhatsApp) installed
**Deferred to C4b:** Inbound text monitoring (WhatsApp reply parsing, iMessage via BlueBubbles, challenge codes)

---

## 1. OVERVIEW

### What C4a Delivers

A centralized Notification Manager that all coordinators route alerts through. Replaces the current state where Safety/Security/Presence generate hazards and alerts that only update sensor state and log entries — nobody gets notified. All notification state (history, pending digests, cooldown tracking) persists to SQLite, surviving HA restarts.

### What It Does NOT Deliver (C4b)

- Inbound message monitoring (WhatsApp/iMessage reply parsing)
- Text-based acknowledgment ("stop", "ok", challenge codes)
- BlueBubbles iMessage integration (user still setting up hardware)
- Telegram channel

C4b ships separately once BlueBubbles is live on the Mac mini.

---

## 2. DEVICE & ENTITY PLACEMENT

### Notification Manager Device

Own device in the Coordinator Manager group, like any coordinator:

```
identifiers: {(DOMAIN, "notification_manager")}
name: "URA: Notification Manager"
model: "Notification Manager"
via_device: (DOMAIN, "coordinator_manager")
```

### Entities on the NM Device

| Entity | Type | Category | Purpose |
|--------|------|----------|---------|
| `switch.ura_notification_manager_enabled` | switch | CONFIG | Enable/disable NM |
| `sensor.ura_notification_last` | sensor | — | Last notification (state=severity, attrs=message/channel/time/coordinator) |
| `sensor.ura_notifications_today` | sensor | — | Count today (state=int, attrs=breakdown by severity/channel). Reads from DB. |
| `binary_sensor.ura_notification_active_alert` | binary_sensor | — | True when unacknowledged CRITICAL/HIGH alert exists |
| `sensor.ura_notification_cooldown_remaining` | sensor | DIAGNOSTIC | Seconds remaining in post-ack cooldown (0 when ready). Survives restart via DB. |
| `sensor.ura_notification_channel_status` | sensor | DIAGNOSTIC | Per-channel health (last success, failures) |
| `sensor.ura_notification_trigger` | sensor | — | State changes on each notification (for user HA automations) |
| `button.ura_notification_acknowledge` | button | — | Dashboard button to acknowledge active CRITICAL alert |

---

## 3. CHANNEL ARCHITECTURE

### Channel Types

| Channel | Type | Scope | HA Service | Config Needed |
|---------|------|-------|------------|---------------|
| **Pushover** | Push notification | Per-person | `notify.pushover` (or custom name) | Notify service name |
| **HA Companion App** | Push notification + action buttons | Per-person | `notify.mobile_app_<device>` | Device notify service |
| **WhatsApp** | Messaging | Per-person | `whatsapp.send_message` | Phone number |
| **TTS** | Audio | Global | `tts.speak` / `media_player.play_media` | Speaker entity list |
| **Alert Lights** | Visual | Global | `light.turn_on/off` | Light entity list |

### Channel Configuration (in NM options flow)

Each channel is configured with:
- **Enabled:** bool (default: false — must opt in)
- **Severity threshold:** minimum severity to trigger this channel (default varies per channel type)
- **Channel-specific settings:**
  - Pushover: HA notify service entity name (e.g., `notify.pushover`)
  - Companion App: (per-person — configured on person, not channel)
  - WhatsApp: (per-person phone — configured on person, not channel)
  - TTS: list of speaker entities (media_player.*), default = all configured
  - Alert Lights: list of light entities (migrated from Safety's `CONF_ALERT_LIGHTS`)

### Default Severity Thresholds

| Channel | Default Threshold | Rationale |
|---------|-------------------|-----------|
| Pushover | MEDIUM | Reliable push, high rate limits |
| Companion App | HIGH | Rate-limited, reserve for important |
| WhatsApp | HIGH | Personal channel, don't spam |
| TTS | CRITICAL | Audible in-home, disruptive |
| Alert Lights | HIGH | Visual, non-disruptive |

### Person Configuration (in NM options flow)

Each person entry:
- **HA Person entity:** `person.*` selector
- **Pushover user key:** string (if Pushover channel enabled)
- **Companion app notify service:** `notify.mobile_app_*` selector (if companion channel enabled)
- **WhatsApp phone:** string with country code (if WhatsApp channel enabled)
- **Low/Medium delivery preference:** Immediate / Daily Digest / Off (default: Immediate)
- **Morning digest time:** time selector, only shown if Daily Digest selected (default: 08:00)
- **Evening digest enabled:** bool, only shown if Daily Digest selected (default: false)
- **Evening digest time:** time selector, only shown if evening digest enabled (default: 18:00)
- **Auto-populate:** Pre-fill companion app service from HA person entity's linked devices where possible

Persons not configured receive no per-person notifications (TTS and lights are global and still fire).

---

## 4. NOTIFICATION ROUTING

### Flow

```
Coordinator generates alert
    → calls self.manager.notification_manager.async_notify(
        coordinator_id="safety",
        severity=Severity.CRITICAL,
        title="Smoke Detected",
        message="Smoke alarm triggered in Kitchen",
        hazard_type="fire",           # optional, for light patterns
        location="Kitchen",           # optional, for context
    )
    → NM checks: is NM enabled? → is coordinator's "integrate with NM" toggle on?
    → NM checks quiet hours (CRITICAL bypasses)
    → NM checks deduplication (same coordinator+title+location within window)
    → Record notification to SQLite (notification_log)
    → For CRITICAL/HIGH: always deliver immediately to all qualifying channels
    → For MEDIUM/LOW per-person channels:
        → If person preference = Immediate: deliver now
        → If person preference = Daily Digest: mark delivered=0 in DB (pending)
        → If person preference = Off: skip
    → For MEDIUM/LOW global channels (TTS, lights): deliver immediately (no digest for TTS/lights)
    → If severity == CRITICAL: start repeat-until-ack cycle
    → Update sensors (last, count, trigger, active_alert)
    → Notify diagnostic listeners (push sensor updates)
```

### Deduplication

Key: `(coordinator_id, title, location)`
Windows per severity:
- CRITICAL: 60 seconds (must get through, but not duplicate within 1 min)
- HIGH: 5 minutes
- MEDIUM: 15 minutes
- LOW: 60 minutes

### Quiet Hours

**Default mode:** House state — quiet when state is `SLEEP` or `HOME_NIGHT`
**Fallback mode:** Manual time window (configurable start/end time)
**Config toggle:** "Use house state for quiet hours" (default: true). When false, uses manual time window.
**CRITICAL always bypasses quiet hours.**

---

## 5. ACK / COOLDOWN / RE-FIRE ENGINE

### State Machine

```
IDLE → ALERTING (CRITICAL notification fires)
ALERTING → REPEATING (after first send, repeat every 30s)
REPEATING → COOLDOWN (user acknowledges)
COOLDOWN → RE-EVALUATE (cooldown timer expires)
RE-EVALUATE → ALERTING (hazard still active → re-fire)
RE-EVALUATE → IDLE (hazard cleared)
```

### Restart Recovery

On NM startup, query `notification_log` for rows where `acknowledged = 0` and `severity = 'critical'`. If found, resume the ALERTING/REPEATING cycle. Query for rows where `acknowledged = 1` and `cooldown_expires > now()`. If found, resume the COOLDOWN timer from the remaining time.

### Acknowledgment Methods (C4a)

1. **Service call:** `ura.acknowledge_notification` — callable from automations, scripts
2. **Dashboard button:** `button.ura_notification_acknowledge` on NM device
3. **Companion app action button:** Actionable push notification with "Acknowledge" button (uses HA `mobile_app` action events)

C4b adds: text reply via WhatsApp/iMessage

### Cooldown Configuration

Per hazard type, configurable in NM options flow with sensible defaults:

| Hazard Type | Default Cooldown | Rationale |
|-------------|-----------------|-----------|
| smoke / fire | 2 minutes | Life safety — aggressive re-check |
| carbon_monoxide | 2 minutes | Life safety |
| flooding | 5 minutes | Active mitigation expected |
| water_leak | 10 minutes | User is investigating/mopping |
| freeze_risk | 15 minutes | HVAC override takes time |
| intrusion (security) | 3 minutes | Urgent resolution expected |
| default | 10 minutes | Catch-all for unspecified types |

### Re-fire Logic

After cooldown expires:
1. Query the source coordinator: "Is this hazard still active?"
   - Safety: check `safety.active_hazards` for matching hazard type + location
   - Security: check `security.last_entry_event` for unresolved alerts
2. If still active → re-enter ALERTING state (full notification cycle)
3. If cleared → return to IDLE, update DB row (`acknowledged = 1`, clear `cooldown_expires`)

### Non-CRITICAL Acknowledgment

HIGH and MEDIUM alerts can be acknowledged but do NOT re-fire. Acknowledgment simply clears the active alert state.

---

## 6. SQLITE NOTIFICATION LOG

### Schema

```sql
CREATE TABLE IF NOT EXISTS notification_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    coordinator_id TEXT NOT NULL,
    severity TEXT NOT NULL,
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    hazard_type TEXT,
    location TEXT,
    person_id TEXT,               -- NULL for global channels (TTS, lights)
    channel TEXT,                 -- pushover, companion, whatsapp, tts, lights
    delivered INTEGER DEFAULT 0,  -- 0=pending digest, 1=sent immediately, 2=sent via digest
    acknowledged INTEGER DEFAULT 0,
    ack_time TEXT,
    cooldown_expires TEXT         -- ISO timestamp, NULL when no cooldown active
);

CREATE INDEX IF NOT EXISTS idx_notification_log_date
    ON notification_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_notification_log_pending
    ON notification_log(person_id, delivered, severity);
```

### What Goes to DB

| Data | Storage | Rationale |
|------|---------|-----------|
| Every notification sent | `notification_log` row per channel per person | History, count sensors, digest source |
| Pending digest items | Rows with `delivered = 0` | Survive restart, query at digest time |
| Cooldown state | `cooldown_expires` column | Resume cooldown timer after restart |
| Ack state | `acknowledged`, `ack_time` columns | Re-fire decision after cooldown |

### What Stays In Memory

| Data | Storage | Rationale |
|------|---------|-----------|
| Active alert state machine (IDLE/ALERTING/etc.) | Runtime | Rebuilt from DB on startup |
| Repeat timer (30s asyncio task) | Runtime | Recreated on startup if unacked CRITICAL exists in DB |
| Dedup cache (recent notification keys) | Runtime dict | Short-lived, not worth persisting |
| Light original states (for restore) | Runtime dict | Only relevant during active pattern |
| Channel health stats | Runtime dict | Transient, resets on restart is fine |

### Sensor Queries

- `sensor.ura_notifications_today`: `SELECT COUNT(*) FROM notification_log WHERE timestamp >= ? AND delivered > 0` (with severity breakdown via `GROUP BY severity`)
- `sensor.ura_notification_last`: `SELECT * FROM notification_log WHERE delivered > 0 ORDER BY timestamp DESC LIMIT 1`
- `sensor.ura_notification_cooldown_remaining`: Read `cooldown_expires` from active CRITICAL row, compute seconds remaining
- Digest query: `SELECT * FROM notification_log WHERE person_id = ? AND severity IN ('low','medium') AND delivered = 0 ORDER BY timestamp`

### Retention

Prune notifications older than 30 days on startup. Single `DELETE FROM notification_log WHERE timestamp < ?` call during `async_setup()`.

---

## 7. DAILY DIGEST

### Per-Person Delivery Preferences

| Preference | Behavior | Applies To |
|------------|----------|------------|
| **Immediate** | Each notification delivered individually as it fires | MEDIUM + LOW (CRITICAL/HIGH are always immediate) |
| **Daily Digest** | MEDIUM + LOW batched into a daily summary at configured time | Per-person messaging channels only |
| **Off** | No MEDIUM/LOW notifications (still gets CRITICAL/HIGH) | Per-person channels |

**Rules:**
- CRITICAL and HIGH are **always immediate** regardless of preference — life safety and security cannot wait
- Digest preference only applies to MEDIUM and LOW on per-person channels (Pushover, Companion, WhatsApp)
- Global channels (TTS, lights) always deliver immediately — no digest for audio/visual
- Digest delivery time is configurable per person (default: 08:00)

### Digest Format

Grouped by coordinator, sorted by severity, includes counts:

```
URA Daily Summary (March 4, 2026)

Safety (5 events):
  ⚠ 3× High humidity advisory — Master Bathroom
  ⚠ 1× Freeze risk warning — Garage
  ℹ 1× Low humidity — Study A

Energy (3 events):
  ⚠ 2× TOU transition — Off-peak → Peak
  ℹ 1× Pool speed reduced — Peak shedding
```

### Digest Delivery

- Up to two `async_track_time_change` timers per person: morning (always, default 08:00) and evening (optional, default 18:00)
- Each timer queries `notification_log` for `person_id = ? AND delivered = 0 AND severity IN ('low', 'medium')`
- Morning digest picks up overnight + previous day's remaining items
- Evening digest picks up items accumulated since morning digest (morning already marked those `delivered = 2`)
- Formats the batch message
- Sends via the person's lowest-severity configured channel (e.g., Pushover at MEDIUM → digest goes via Pushover)
- Updates all rows: `delivered = 2` (sent via digest)
- If no pending items at digest time, no message sent (no empty digests)

---

## 8. ALERT LIGHT PATTERNS

### Pattern Definitions (consolidated from Safety)

```python
LIGHT_PATTERNS: dict[str, dict] = {
    # Safety patterns
    "fire":         {"color": (255, 100, 0),   "effect": "flash",  "interval_ms": 250},
    "water_leak":   {"color": (0, 0, 255),     "effect": "pulse",  "interval_ms": 1000},
    "co":           {"color": (255, 100, 0),   "effect": "flash",  "interval_ms": 500},
    "freeze":       {"color": (100, 150, 255), "effect": "pulse",  "interval_ms": 1000},
    "warning":      {"color": (255, 255, 0),   "effect": "pulse",  "interval_ms": 1000},
    # Security patterns
    "intruder":     {"color": (255, 0, 0),     "effect": "flash",  "interval_ms": 200},
    "armed":        {"color": (255, 0, 0),     "effect": "solid",  "brightness": 30},
    "investigate":  {"color": (255, 255, 0),   "effect": "pulse",  "interval_ms": 800},
    "arriving":     {"color": (255, 180, 100), "effect": "fade",   "interval_ms": 2000},
    # Sequential blink (new) — lights turn on/off one at a time in sequence
    "sequential":   {"color": None,            "effect": "sequential", "interval_ms": 300},
}
```

### Light Effects

| Effect | Behavior |
|--------|----------|
| `flash` | All lights alternate on/off at `interval_ms` |
| `pulse` | All lights ramp brightness up/down at `interval_ms` |
| `solid` | All lights set to color at specified brightness, hold |
| `fade` | All lights warm fade in over `interval_ms` |
| `sequential` | Lights turn on/off one at a time in order at `interval_ms` (new — reacts to change, not just color) |

### Light State Management

- **Save** original light states (on/off, brightness, color, color_temp) before any alert pattern
- **Restore** original states when alert clears or is acknowledged
- **Guard:** Only one pattern active at a time. Higher severity pattern replaces lower.
- Reuse existing `_store_alert_light_states` / `_restore_alert_lights` pattern from `automation.py`

### Migration from Safety/Automation

- `CONF_ALERT_LIGHTS` and `CONF_ALERT_LIGHT_COLOR` currently live in room config (used by `automation.py`)
- Safety's `LIGHT_PATTERNS` dict stays in `safety.py` as reference data, but actual light control moves to NM
- **Migration approach:** NM gets its own `CONF_NM_ALERT_LIGHTS` in CM options. Room-level `CONF_ALERT_LIGHTS` continues to work as a legacy fallback until explicitly migrated. Safety's `_process_alerts()` calls NM when available, falls back to direct light control when NM is disabled.
- Full cleanup deferred to post-C4 once NM is proven stable.

---

## 9. LEGACY NOTIFICATION DEPRECATION

### Current State

The integration entry has a legacy notification system:
- `CONF_NOTIFY_SERVICE` — a single `notify.*` service (e.g., `notify.pushover`)
- `CONF_NOTIFY_TARGET` — a single mobile app target
- `CONF_NOTIFY_LEVEL` — off / errors / important / all
- `_process_alerts()` in `aggregation.py` — fires safety alerts through the configured service
- Already guarded: when domain coordinators are active, `_process_alerts()` returns early (line 854)

Additionally, per-room `CONF_ALERT_LIGHTS` in `automation.py` handles room-level light flashing independently.

### Deprecation Strategy

1. **Legacy `_process_alerts()` already bypassed** — no code change needed, domain coordinators are active
2. **Legacy config flow fields remain** but get a description update: "Legacy — use Notification Manager for advanced notification routing"
3. **No removal in C4a** — legacy path stays as dead code, removed in a future cleanup cycle
4. **Per-room alert lights** — continue working independently. NM's global alert lights are additive, not replacing per-room lights yet. Full consolidation is post-C4.

### Migration Path for Users

- NM is configured separately on the Coordinator Manager entry
- Users who had `CONF_NOTIFY_SERVICE` configured will see their safety alerts now routing through NM instead (if NM is enabled and Safety's notify toggle is on)
- No data migration needed — NM starts fresh with its own channel/person config

---

## 10. COORDINATOR INTEGRATION

### Toggle

Each coordinator gets a `CONF_NOTIFY_ENABLED` toggle (default: true) in its options flow section:

```python
CONF_NOTIFY_ENABLED: Final = "notify_enabled"
```

When false, the coordinator's calls to `notification_manager.async_notify()` are silently dropped.

### Coordinator Interface

Coordinators call NM through the manager reference:

```python
# In any coordinator's response handler:
if self.manager and self.manager.notification_manager:
    await self.manager.notification_manager.async_notify(
        coordinator_id=self.coordinator_id,
        severity=Severity.CRITICAL,
        title="Smoke Detected",
        message=f"Smoke alarm triggered in {room_name}",
        hazard_type="fire",
        location=room_name,
    )
```

### Re-fire Hazard Check Interface

NM needs to query coordinators to check if a hazard is still active after cooldown:

```python
# BaseCoordinator gets a new method:
def is_hazard_active(self, hazard_type: str, location: str) -> bool:
    """Check if a specific hazard is still active. Override in subclasses."""
    return False
```

Safety overrides to check `active_hazards`. Security overrides to check unresolved alerts.

---

## 11. AUTOMATION TRIGGER SENSOR

`sensor.ura_notification_trigger` — state changes each time a notification fires.

- **State:** `{coordinator_id}_{severity}` (e.g., `safety_critical`, `security_high`)
- **Attributes:** `coordinator`, `severity`, `title`, `message`, `hazard_type`, `location`, `timestamp`
- **Purpose:** Users can build HA automations that trigger on state changes, enabling extensibility beyond what NM natively supports (e.g., "when trigger changes to safety_critical, send Telegram to plumber")

---

## 12. SERVICES

| Service | Parameters | Purpose |
|---------|-----------|---------|
| `ura.acknowledge_notification` | None (clears current active alert) | Stop repeat-until-ack cycle |
| `ura.test_notification` | `severity` (default: MEDIUM), `channel` (optional, default: all) | Test notification delivery on configured channels |

---

## 13. CONFIG FLOW STRUCTURE

### NM Options Flow (on Coordinator Manager entry)

**Step 1: Notification Channels**
```
☐ Pushover enabled          Severity: [MEDIUM ▼]  Service: [notify.pushover]
☐ Companion App enabled     Severity: [HIGH ▼]    (per-person setup below)
☐ WhatsApp enabled          Severity: [HIGH ▼]    (per-person setup below)
☐ TTS enabled               Severity: [CRITICAL ▼] Speakers: [entity picker multi]
☐ Alert Lights enabled      Severity: [HIGH ▼]     Lights: [entity picker multi]
```

**Step 2: Persons** (repeatable — add/edit persons)
```
Person: [person.oji_udezue ▼]
  Pushover user key: [________]
  Companion app: [notify.mobile_app_oji_iphone ▼]
  WhatsApp phone: [+1xxxxxxxxxx]
  Low/Medium delivery: [Immediate ▼ / Daily Digest / Off]
  Morning digest: [08:00]         (shown only if Daily Digest selected)
  ☐ Evening digest enabled        (shown only if Daily Digest selected)
  Evening digest: [18:00]         (shown only if evening enabled)
```

**Step 3: Quiet Hours**
```
☑ Use house state (SLEEP + HOME_NIGHT = quiet)
☐ Use manual schedule
  Start: [22:00]  End: [07:00]
```

**Step 4: Cooldowns** (per hazard type)
```
Smoke/Fire:      [2] minutes
Carbon Monoxide: [2] minutes
Flooding:        [5] minutes
Water Leak:      [10] minutes
Freeze Risk:     [15] minutes
Intrusion:       [3] minutes
Default:         [10] minutes
```

**Note:** This is a multi-step options flow within the existing Coordinator Manager options, not a separate config entry. NM settings are stored in the CM entry's options dict under a `notification_manager` key.

---

## 14. FILE PLAN

### New Files

| File | Purpose | Est. Lines |
|------|---------|------------|
| `domain_coordinators/notification_manager.py` | NotificationManager class, channel dispatchers, ack engine, quiet hours, dedup, light patterns, repeat-until-ack, digest scheduler, DB read/write | 800 |

### Modified Files

| File | Change | Est. Lines |
|------|--------|------------|
| `domain_coordinators/manager.py` | Instantiate NM, wire to coordinators, expose via `self.notification_manager` | +30 |
| `domain_coordinators/base.py` | Add `is_hazard_active()` method, `CONF_NOTIFY_ENABLED` check | +15 |
| `domain_coordinators/safety.py` | Call NM for hazard notifications, implement `is_hazard_active()`, keep LIGHT_PATTERNS as data | +40 |
| `domain_coordinators/security.py` | Call NM for security alerts, implement `is_hazard_active()` | +25 |
| `database.py` | `notification_log` table creation, index, 30-day prune | +25 |
| `sensor.py` | 5 new sensors (last, count_today, cooldown_remaining, channel_status, trigger) — DB-backed queries | +300 |
| `binary_sensor.py` | 1 new binary sensor (active_alert) | +40 |
| `button.py` | 1 new button (acknowledge) | +30 |
| `switch.py` | NM enable/disable switch | +15 |
| `config_flow.py` | NM options steps (channels, persons, quiet hours, cooldowns, digest preferences) | +250 |
| `const.py` | NM constants (channel types, cooldown defaults, dedup windows, conf keys, digest constants) | +70 |
| `strings.json` | NM config flow strings | +90 |
| `translations/en.json` | NM config flow translations | +90 |
| `services.yaml` | `ura.acknowledge_notification`, `ura.test_notification` | +20 |
| `__init__.py` | Register NM services | +20 |

### Estimated Totals
- **New:** ~800 lines
- **Modified:** ~1,060 lines across 15 files
- **Total delta:** ~1,860 lines

---

## 15. IMPLEMENTATION ORDER

1. **Database schema** — `notification_log` table, index, prune in `database.py`
2. **Constants & data models** — `const.py` additions, channel types, cooldown defaults, digest constants
3. **NotificationManager class** — core class with channel dispatch, dedup, quiet hours, DB writes
4. **Digest engine** — per-person preference, daily timer, DB query, batch formatting, delivery
5. **Ack/cooldown/re-fire engine** — state machine, timers, `is_hazard_active()` interface, DB persistence, restart recovery
6. **Light pattern engine** — consolidated patterns, sequential blink, save/restore
7. **Manager integration** — wire NM into CoordinatorManager, expose to coordinators
8. **Coordinator callsites** — Safety and Security call `async_notify()`
9. **Config flow** — channels, persons (with digest prefs), quiet hours, cooldowns options steps
10. **Sensors & entities** — all 8 entities on NM device (DB-backed where applicable)
11. **Services** — `acknowledge_notification`, `test_notification`
12. **Strings & translations** — config flow UI text
13. **Tests**

---

## 16. VERIFICATION

### Functional
- [ ] NM device appears in Coordinator Manager group
- [ ] Enable/disable switch controls NM
- [ ] Pushover notification sends on Safety CRITICAL hazard
- [ ] Companion app notification sends with "Acknowledge" action button
- [ ] WhatsApp message sends via `whatsapp.send_message`
- [ ] TTS announces on configured speakers for CRITICAL
- [ ] Alert lights flash correct pattern per hazard type (fire=orange, water=blue, etc.)
- [ ] Sequential blink pattern works (lights on/off one at a time)
- [ ] Light states saved before alert, restored after clear/ack
- [ ] Quiet hours suppress non-CRITICAL during SLEEP/HOME_NIGHT
- [ ] Manual quiet hours fallback works when house state toggle off
- [ ] CRITICAL bypasses quiet hours
- [ ] Deduplication suppresses repeat same-message within window
- [ ] CRITICAL repeats every 30s until acknowledged
- [ ] Dashboard button acknowledges active alert
- [ ] Service call `ura.acknowledge_notification` stops repeat
- [ ] Companion app action button acknowledges
- [ ] After ack, cooldown timer starts (sensor shows countdown)
- [ ] After cooldown, re-evaluate: if hazard persists → re-fire
- [ ] After cooldown, re-evaluate: if hazard cleared → idle
- [ ] Per-coordinator notify toggle: off = no notifications from that coordinator
- [ ] `sensor.ura_notification_trigger` state changes on each notification
- [ ] User HA automation can trigger on trigger sensor state change
- [ ] `ura.test_notification` sends test to all configured channels
- [ ] Channel status sensor shows per-channel health
- [ ] All 645+ existing tests pass
- [ ] 25+ new tests

### SQLite Persistence
- [ ] `notification_log` table created on startup
- [ ] Every notification recorded to DB with correct fields
- [ ] `sensor.ura_notifications_today` reads count from DB (correct after restart)
- [ ] `sensor.ura_notification_last` reads last record from DB (correct after restart)
- [ ] Pending digest items survive HA restart
- [ ] Cooldown state survives HA restart — timer resumes from remaining time
- [ ] Unacknowledged CRITICAL alert resumes repeating after HA restart
- [ ] 30-day prune runs on startup without errors
- [ ] DB writes use `hass.async_add_executor_job` (no blocking event loop)

### Digest Mode
- [ ] Person with preference=Immediate gets LOW/MEDIUM notifications individually
- [ ] Person with preference=Daily Digest: LOW/MEDIUM queued (delivered=0 in DB), not sent immediately
- [ ] Person with preference=Off: no LOW/MEDIUM notifications at all
- [ ] CRITICAL/HIGH always sent immediately regardless of preference
- [ ] Digest fires at configured time, sends formatted summary
- [ ] Digest grouped by coordinator, sorted by severity, includes counts
- [ ] Digest marks rows as delivered=2 after sending
- [ ] No empty digests sent when no pending items
- [ ] Pending digest items survive restart, delivered at next scheduled time
- [ ] Global channels (TTS, lights) always immediate, never digested

### Legacy Deprecation
- [ ] Legacy `_process_alerts()` still bypassed when coordinators active (no regression)
- [ ] Legacy `CONF_NOTIFY_SERVICE` config fields remain visible (not removed)
- [ ] NM operates independently of legacy notification config

### Edge Cases
- [ ] NM disabled → coordinators continue functioning, just no notifications
- [ ] No persons configured → global channels (TTS, lights) still work
- [ ] No channels configured → NM accepts calls silently, no errors
- [ ] WhatsApp bridge down → graceful failure, channel_status shows error
- [ ] Multiple CRITICAL alerts simultaneously → highest severity pattern wins for lights
- [ ] Ack during cooldown from a previous alert → resets to new alert's cooldown
- [ ] HA restarts mid-cooldown → cooldown resumes from DB
- [ ] HA restarts with unacked CRITICAL → repeat cycle resumes
- [ ] HA restarts with pending digest → digest delivered at next scheduled time

---

## 17. EXTERNAL DEPENDENCIES

| Dependency | Status | Required For |
|------------|--------|-------------|
| Pushover HA integration | Installed | Pushover channel |
| HA Companion App | Installed | Companion app channel + action buttons |
| ha-wa-bridge (WhatsApp) | Installed, Docker running | WhatsApp channel (outbound only in C4a) |
| BlueBubbles | NOT YET — user setting up Mac mini | C4b only (not needed for C4a) |

---

## 18. WHAT C4a UNBLOCKS

- **C5 (Energy Coordinator):** Can send TOU alerts, load shedding notifications, battery strategy changes. Digest mode prevents Energy from spamming LOW/MEDIUM events.
- **C4b (Inbound Text Monitoring):** Builds on NM's ack engine, adds text reply parsing via WhatsApp/iMessage
- **Existing coordinators:** Safety and Security immediately start sending real notifications
- **User automations:** Trigger sensor enables extensibility via standard HA automations
- **Daily awareness:** Digest mode gives household members a morning summary without alert fatigue

---

## 19. IMPLEMENTATION PLAN

### Architecture Decision: NM Access Pattern

NM stored at `hass.data[DOMAIN]["notification_manager"]` — same pattern as `database` and `coordinator_manager`. Coordinators access via `self.hass.data[DOMAIN]["notification_manager"]`. Avoids adding back-references to BaseCoordinator.

NM is **NOT** a BaseCoordinator subclass — it doesn't manage rooms or participate in intent/evaluate/action pipeline. It's a standalone service owned by CoordinatorManager.

### Phase 1: Foundation

**Step 1.1: Constants — `const.py`**
Add after line ~887 (end of music following constants): +70 lines
- `CONF_NM_ENABLED`, all `CONF_NM_*` channel/person/quiet/cooldown keys
- Default severity thresholds, cooldown defaults, dedup windows
- `NM_DELIVERY_IMMEDIATE/DIGEST/OFF`, `NM_CRITICAL_REPEAT_INTERVAL = 30`
- `RETENTION_NOTIFICATION_LOG = 30`

**Step 1.2: Database Schema — `database.py`**
Add in `initialize()` after existing tables: +30 lines
- `notification_log` table (id, timestamp, coordinator_id, severity, title, message, hazard_type, location, person_id, channel, delivered, acknowledged, ack_time, cooldown_expires)
- Indexes: `idx_notification_log_date`, `idx_notification_log_pending`
- New methods: `log_notification()`, `get_notifications_today()`, `get_last_notification()`, `get_pending_digest()`, `mark_digest_delivered()`, `acknowledge_notification()`, `get_active_critical()`, `get_active_cooldown()`, `set_cooldown()`, `prune_notification_log()`

**Step 1.3: Signals — `domain_coordinators/signals.py`**
+3 lines: `SIGNAL_NM_ENTITIES_UPDATE`, `SIGNAL_NM_ALERT_STATE_CHANGED`

**Step 1.4: NotificationManager Class — `domain_coordinators/notification_manager.py` (NEW)**
~800 lines, structured as:

```
NotificationManager
├── Properties: device_info, enabled, alert_state, active_alert, cooldown_remaining, channel_status, last_notification, notifications_today
├── Lifecycle: async_setup(), async_teardown()
├── Core: async_notify(coordinator_id, severity, title, message, hazard_type?, location?)
├── Channel dispatchers: _send_pushover(), _send_companion(), _send_whatsapp(), _send_tts(), _trigger_alert_lights()
├── Ack engine: _enter_alerting(), _repeat_alert(), async_acknowledge(), _start_cooldown(), _cooldown_expired(), _re_evaluate_hazard()
├── Quiet hours: _is_quiet_hours()
├── Dedup: _is_deduplicated()
├── Digest: _setup_digest_timers(), _fire_digest(), _format_digest()
├── Lights: _store_alert_light_states(), _restore_alert_lights(), _run_light_pattern()
├── Recovery: _recover_state_from_db()
└── Helpers: async_refresh_today_count(), async_test_notification()
```

AlertState enum: IDLE → ALERTING → REPEATING → COOLDOWN → RE_EVALUATE → (ALERTING or IDLE)

Light patterns dict consolidated from `safety.py` LIGHT_PATTERNS + security additions (intruder, armed, investigate, arriving, sequential).

### Phase 2: Manager Integration + Coordinator Wiring

**Step 2.1: CoordinatorManager — `domain_coordinators/manager.py` (+30 lines)**
- `self._notification_manager: NotificationManager | None = None` in `__init__`
- `notification_manager` property
- `set_notification_manager()` method
- In `async_start()`: call `nm.async_setup()`, store in `hass.data[DOMAIN]["notification_manager"]`
- In `async_stop()`: call `nm.async_teardown()`, remove from `hass.data`

**Step 2.2: Integration Init — `__init__.py` (+35 lines)**
- After music following coordinator registration (~line 952): instantiate NM if `CONF_NM_ENABLED`, call `coordinator_manager.set_notification_manager(nm)`
- After line 978: `await _async_register_notification_services(hass)`
- New `_async_register_notification_services()`: register `acknowledge_notification` and `test_notification` services

**Step 2.3: Base Coordinator — `domain_coordinators/base.py` (+5 lines)**
- Add `is_hazard_active(hazard_type: str, location: str) -> bool` default returning `False`

**Step 2.4: Safety Coordinator — `domain_coordinators/safety.py` (+40 lines)**
- Override `is_hazard_active()`: check `f"{hazard_type}:{location}" in self._active_hazards`
- In `_respond_to_hazard()` after NotificationAction creation (~line 1477): call `nm.async_notify()` with hazard data
- NM call is additive — existing NotificationAction for intent pipeline stays

**Step 2.5: Security Coordinator — `domain_coordinators/security.py` (+25 lines)**
- Override `is_hazard_active()`: check `self._active_alert` for intrusion/security types
- At all 5 NotificationAction creation sites: add `nm.async_notify()` call

### Phase 3: Entities

**Step 3.1: Enable Switch — `switch.py` (+10 lines)**
Add to CM entry switch list: `CoordinatorEnabledSwitch` for `notification_manager` with `CONF_NM_ENABLED`, icon `mdi:bell-ring`, device `notification_manager`

**Step 3.2: Sensors — `sensor.py` (+300 lines)**
5 new sensor classes, all with NM DeviceInfo, subscribe to `SIGNAL_NM_ENTITIES_UPDATE`:

| Class | State | Key Attrs |
|-------|-------|-----------|
| `NMLastNotificationSensor` | severity string or `none` | message, channel, time, coordinator |
| `NMNotificationsTodaySensor` | int count | breakdown by severity/channel |
| `NMCooldownRemainingSensor` | int seconds | hazard_type, location |
| `NMChannelStatusSensor` (DIAGNOSTIC) | `ok` / `degraded` | per-channel health dict |
| `NMTriggerSensor` | `{coordinator}_{severity}` | coordinator, severity, title, message, hazard_type, location, timestamp |

Register in CM block (~line 184).

**Step 3.3: Active Alert Binary Sensor — `binary_sensor.py` (+40 lines)**
`NMActiveAlertBinarySensor`: `is_on` = `nm.active_alert`, device_class SAFETY, subscribe to `SIGNAL_NM_ALERT_STATE_CHANGED`. Register in CM block (~line 119).

**Step 3.4: Acknowledge Button — `button.py` (+35 lines)**
- Add `ENTRY_TYPE_COORDINATOR_MANAGER` check at top of `async_setup_entry` (before room entry code)
- `NMAcknowledgeButton`: calls `nm.async_acknowledge()` on press, icon `mdi:bell-check`

### Phase 4: Config Flow + UI

**Step 4.1: Config Flow — `config_flow.py` (+250 lines)**
Add `"coordinator_notifications"` to CM options menu (line ~1518).

4 new steps following `async_step_coordinator_security` pattern:

1. **`async_step_coordinator_notifications`** — Channel config (enable/severity/settings per channel)
2. **`async_step_coordinator_notifications_persons`** — Person setup (HA person entity, per-channel credentials, delivery pref, digest times)
3. **`async_step_coordinator_notifications_quiet`** — Quiet hours (house state toggle, manual start/end)
4. **`async_step_coordinator_notifications_cooldowns`** — Per-hazard-type cooldown minutes

**Step 4.2: Strings — `strings.json` + `translations/en.json` (+90 each)**
Menu label + all 4 step field labels and descriptions.

**Step 4.3: Services — `services.yaml` (+25 lines)**
`acknowledge_notification` (no params) and `test_notification` (optional severity, optional channel).

### Phase 5: Polish

**Step 5.1: Companion App Action Listener**
In `notification_manager.py` `async_setup()`: subscribe to `mobile_app_notification_action` for `ACKNOWLEDGE_URA` action. (+15 lines within existing file)

**Step 5.2: Version Bump**
`const.py` line 34: `VERSION = "3.6.29"`

**Step 5.3: Tests — `quality/tests/test_notification_manager.py` (NEW, ~300 lines)**
- NM instantiation, `async_notify()` routing, severity filtering, quiet hours, dedup
- Ack state machine transitions
- DB methods (log, query, ack, cooldown, prune)
- Digest formatting
- Restart recovery from DB

### Critical Files

| File | Action | Lines |
|------|--------|-------|
| `domain_coordinators/notification_manager.py` | NEW | ~800 |
| `quality/tests/test_notification_manager.py` | NEW | ~300 |
| `const.py` | MODIFY | +70 |
| `database.py` | MODIFY | +30 |
| `domain_coordinators/signals.py` | MODIFY | +3 |
| `domain_coordinators/manager.py` | MODIFY | +30 |
| `__init__.py` | MODIFY | +35 |
| `domain_coordinators/base.py` | MODIFY | +5 |
| `domain_coordinators/safety.py` | MODIFY | +40 |
| `domain_coordinators/security.py` | MODIFY | +25 |
| `switch.py` | MODIFY | +10 |
| `sensor.py` | MODIFY | +300 |
| `binary_sensor.py` | MODIFY | +40 |
| `button.py` | MODIFY | +35 |
| `config_flow.py` | MODIFY | +250 |
| `strings.json` + `translations/en.json` | MODIFY | +180 |
| `services.yaml` | MODIFY | +25 |
