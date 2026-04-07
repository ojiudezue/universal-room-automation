# URA Activity Log — Implementation Plan

**Status:** Planned (reviewed + critiqued)
**Target Version:** TBD (pre-v4.0.0 observability cycle)
**Estimated Scope:** ~400 lines production + ~200 lines tests, single focused cycle

## Motivation

URA's automated decisions are more opaque than native HA automations. HA automations show up in the logbook with "triggered by X", but URA's coordinator decisions (fan on because pre-arrival, occupancy held because motion, zone vacancy sweep, etc.) are invisible unless you dig through debug logs. This feature makes URA's actions transparent via three complementary channels.

## Approach

1. **DB-backed activity log** — `ura_activity_log` table in the existing URA SQLite database. Durable, queryable, survives restarts.
2. **HA custom events + logbook platform** — fire `ura_action` events with a `logbook.py` platform for formatted display in the native HA logbook.
3. **Diagnostic sensor** — `sensor.ura_last_activity` with rolling buffer of recent actions.

---

## What Actions to Log

**Principle:** Log state transitions and commands, not polling observations. Not every 30s cycle — only genuine state changes.

| Category | Actions | Volume |
|----------|---------|--------|
| Room Automation | Occupancy entry/exit, light on/off, fan control, cover open/close, chained automations, AI rule execution | ~30-100/day |
| HVAC | Preset changes, override arrests, AC resets, pre-arrival triggers, vacancy sweeps, fan speed changes | ~10-30/day |
| Energy | Load shedding level changes, battery strategy changes, device commands | ~5-15/day |
| House State | State transitions, security armed changes, safety hazards | ~5-10/day |
| Notifications | Alerts sent, inbound replies processed | ~5-20/day |
| Presence | Guest mode activation, person location changes | ~5-10/day |

**Estimated total:** 50-200 events/day.

---

## Schema: `ura_activity_log`

```sql
CREATE TABLE IF NOT EXISTS ura_activity_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    coordinator TEXT NOT NULL,      -- "room", "hvac", "energy", "security", "safety", "presence", "notification"
    action TEXT NOT NULL,           -- "occupancy_entry", "light_on", "preset_change", "load_shed", etc.
    room TEXT,                      -- room name (NULL for house-level actions)
    zone TEXT,                      -- HVAC zone (NULL for non-zone actions)
    importance TEXT NOT NULL DEFAULT 'info',  -- "info", "notable", "critical"
    description TEXT NOT NULL,      -- human-readable: "Turned on 3 lights (entry, dark)"
    details_json TEXT,              -- optional JSON, capped at 2KB by ActivityLogger
    entity_id TEXT                  -- primary entity affected (for HA logbook cross-reference)
);

CREATE INDEX IF NOT EXISTS idx_activity_log_timestamp ON ura_activity_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_activity_log_coordinator ON ura_activity_log(coordinator, timestamp);
```

**Note:** Only 2 indexes. `timestamp` for pruning, `coordinator+timestamp` for scoped queries. Room and importance indexes can be added later if query patterns warrant it. Table is small (~50-200 rows/day, pruned to 7-30 days).

**Timestamps:** Use `dt_util.utcnow().isoformat()` consistently (not `datetime.utcnow()` which is deprecated in Python 3.12+).

---

## ActivityLogger Class

New file: `custom_components/universal_room_automation/activity_logger.py` (~80 lines)

```python
class ActivityLogger:
    """Lightweight activity logging for URA coordinators.

    Writes to ura_activity_log table AND fires ura_action HA events.
    All writes go through the existing DB write queue.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._dedup_cache: dict[str, float] = {}  # key -> last_timestamp
        self._dedup_window: float = 30.0  # seconds

    async def log(
        self,
        coordinator: str,
        action: str,
        description: str,
        room: str | None = None,
        zone: str | None = None,
        importance: str = "info",
        details: dict | None = None,
        entity_id: str | None = None,
    ) -> None:
        """Log an activity to DB and fire an HA event. Never raises."""
```

**Key design:**
- Stored in `hass.data[DOMAIN]["activity_logger"]`, initialized once during `ENTRY_TYPE_INTEGRATION` setup, immediately after DB is stored
- Never raises — all exceptions caught and logged
- `details_json` capped at 2KB before DB write

### Dedup Strategy

Dedup key: `coordinator + action + room + description`. Including the description ensures that different transitions (e.g., "light on (entry)" vs "light on (night mode)") are NOT deduped, while truly identical repeated events within the window are.

| Level | Dedup Window |
|-------|-------------|
| `info` | 30s |
| `notable` | 60s |
| `critical` | No dedup |

Dedup cache is cleared during the daily prune callback to prevent unbounded growth.

### Calling Pattern

`ActivityLogger.log()` is `async`. From sync methods like `set_last_action()`, call via:
```python
self.hass.async_create_task(activity_logger.log(...))
```
This is safe because `set_last_action()` runs on the event loop (called from async methods in automation.py). From async methods, `await` directly.

---

## Volume Control

| Level | Examples | Retention | Dedup |
|-------|----------|-----------|-------|
| `info` | Light on/off, fan speed change, occupancy transition | 7 days | 30s |
| `notable` | HVAC preset change, load shedding, security state, vacancy sweep | 30 days | 60s |
| `critical` | Safety hazard, security breach, AI automation execution, AC reset | 30 days | None |

---

## Pruning

- **On startup:** Prune entries past retention window (in `__init__.py` after ActivityLogger init)
- **Daily at 2:00 AM:** Dedicated `async_track_time_change(hass, prune_callback, hour=2, minute=0, second=0)` registered in `__init__.py`. Also clears the dedup cache.
- **7 days** for `info`, **30 days** for `notable`/`critical`

**Note:** No centralized midnight hook exists in URA. Do NOT piggyback on coordinator-internal midnight patterns — they run at different times and some are inside observation-mode guards.

---

## Integration Points

### Room-Level Actions

`set_last_action()` (coordinator.py) is a sync method called from automation.py. It currently captures **only light entry/exit** (2 call sites). To capture all room actions, we add explicit `activity_logger.log()` calls at each action execution site in automation.py:

| # | Location | Action Logged |
|---|----------|---------------|
| 1 | `coordinator.py` `set_last_action()` | Light on/off (entry/exit) — existing 2 call sites |
| 2 | `coordinator.py` occupancy transition (~line 1416) | Room entry/exit with source |
| 3 | `automation.py` `handle_temperature_based_fan_control` | Fan on/off with temp + threshold |
| 4 | `automation.py` cover open/close on entry/exit | Cover control with reason |
| 5 | `automation.py` chained automation trigger | Trigger type + automation entity |

### Domain Coordinator Actions

| # | Location | Action Logged |
|---|----------|---------------|
| 6 | `hvac.py` preset change (~line 707) | Zone preset change with reason |
| 7 | `hvac.py` pre-arrival trigger (~line 1209) | Pre-arrival zone activation |
| 8 | `energy.py` load shedding change | Load shed level with reason |
| 9 | `house_state.py` / presence coordinator | House state transition |
| 10 | `security.py` armed state change | Security arm/disarm |
| 11 | `safety.py` hazard detection | Hazard alert |
| 12 | `notification_manager.py` notification sent | Alert delivery |

### Observation Mode

Activity logging fires at **action execution** sites, not decision sites. Observation mode suppresses execution, so there's nothing to log — the gating is inherent. Each integration point should be verified to confirm it's post-observation-mode-check.

---

## HA Logbook Integration

`hass.bus.async_fire("ura_action", ...)` alone produces generic "Event: ura_action" entries in the HA logbook. For formatted display, a `logbook.py` platform is required (~30 lines).

### D5b: `logbook.py` Platform

```python
# custom_components/universal_room_automation/logbook.py
from homeassistant.core import callback
from homeassistant.components.logbook import LOGBOOK_ENTRY_MESSAGE, LOGBOOK_ENTRY_NAME

@callback
def async_describe_events(hass, async_describe_event):
    @callback
    def async_describe_ura_action(event):
        data = event.data
        name = f"URA {data.get('coordinator', '').title()}"
        room = data.get('room')
        if room:
            name = f"URA: {room}"
        return {
            LOGBOOK_ENTRY_NAME: name,
            LOGBOOK_ENTRY_MESSAGE: data.get('description', 'action'),
        }
    async_describe_event("ura_action", async_describe_ura_action)
```

This produces formatted entries like:
- **URA: Living Room** turned on 3 lights (entry, dark)
- **URA HVAC** changed Zone 1 preset to eco (vacancy)

---

## Sensor: `sensor.ura_last_activity`

- **Device:** URA: Coordinator Manager (via `AggregationEntity` base, `identifiers={(DOMAIN, "coordinator_manager")}`)
- **State:** Description of most recent action
- **Attributes:**
  - `coordinator`, `action`, `room`, `importance`, `timestamp`, `time_ago`
  - `recent_activities`: list of last 10 activities
  - `activities_today`: count
  - `notable_today`: count
- Updates via `SIGNAL_ACTIVITY_LOGGED` signal
- Seeds from DB on startup (last 10 entries via `get_recent_activities()`)

---

## Deliverables

### D1: DB Table + Methods
Create `ura_activity_log` table in `database.py` using `_create_table_safe()`, add `log_activity()`, `prune_activity_log()`, `get_recent_activities()`.

**Acceptance Criteria:**
- **Verify:** Table created on fresh DB with correct schema (2 indexes)
- **Verify:** `log_activity()` writes through write queue via `async with self._db()`
- **Verify:** Pruning respects importance-based retention (7d info, 30d notable/critical)
- **Test:** `test_activity_log_write`, `test_activity_log_prune_info_7d`, `test_activity_log_prune_notable_30d`
- **Live:** `SELECT count(*) FROM ura_activity_log` via MCP shows rows accumulating

### D2: ActivityLogger Class
New `activity_logger.py` with description-aware dedup, DB write, HA event fire, signal dispatch.

**Acceptance Criteria:**
- **Verify:** `log()` writes to DB and fires `ura_action` event
- **Verify:** Dedup on `coordinator+action+room+description` prevents true duplicates
- **Verify:** Different descriptions for same action are NOT deduped
- **Verify:** `critical` importance bypasses dedup entirely
- **Verify:** Never raises — all exceptions caught
- **Verify:** `details_json` capped at 2KB
- **Test:** `test_dedup_same_description`, `test_dedup_different_description_passes`, `test_critical_no_dedup`, `test_fires_event`, `test_db_failure_swallowed`, `test_details_json_capped`
- **Live:** HA Developer Tools > Events > Listen for `ura_action`

### D3: Integration Wiring
Initialize in `__init__.py` (inside `ENTRY_TYPE_INTEGRATION`, after DB store). Wire into `set_last_action()` + explicit calls at 12 action sites. Register daily prune timer at 2 AM.

**Acceptance Criteria:**
- **Verify:** Room entry/exit produces activity log entries
- **Verify:** Light on/off, fan on/off, cover open/close produce entries
- **Verify:** HVAC preset change, house state transition produce entries
- **Verify:** Pruning runs on startup and daily at 2 AM
- **Verify:** All integration points are post-observation-mode-check
- **Test:** `test_room_entry_logs_activity`, `test_fan_control_logs_activity`, `test_hvac_preset_logs_activity`
- **Live:** Walk into room -> check `ura_action` events in HA logbook

### D4: Diagnostic Sensor
`sensor.ura_last_activity` on Coordinator Manager device.

**Acceptance Criteria:**
- **Sensor:** Shows most recent action description
- **Verify:** `recent_activities` attribute has last 10 entries
- **Verify:** Counts are accurate
- **Verify:** Seeds from DB on startup
- **Test:** `test_sensor_state`, `test_sensor_recent_buffer`, `test_sensor_counts`, `test_sensor_db_seed`
- **Live:** Entity card shows live activity stream

### D5: Signal + Logbook Platform
Add `SIGNAL_ACTIVITY_LOGGED` to signals.py. Add `logbook.py` for formatted HA logbook display.

**Acceptance Criteria:**
- **Verify:** Signal defined and importable
- **Verify:** `ura_action` events appear formatted in HA logbook (not generic "Event: ura_action")
- **Verify:** Entries show "URA: {Room}" or "URA {Coordinator}" with description
- **Test:** `test_logbook_describe_event`
- **Live:** HA logbook shows formatted URA entries inline with native automations

---

## File Changes Summary

| File | Change | Lines |
|------|--------|-------|
| `activity_logger.py` (NEW) | ActivityLogger class with dedup, DB write, event fire | ~80 |
| `logbook.py` (NEW) | HA logbook platform for formatted `ura_action` display | ~30 |
| `database.py` | Table creation (`_create_table_safe`) + `log_activity()` + `prune_activity_log()` + `get_recent_activities()` | ~80 |
| `domain_coordinators/signals.py` | `SIGNAL_ACTIVITY_LOGGED` | 1 |
| `coordinator.py` | Wire in `set_last_action()` via `async_create_task` + occupancy transition | ~20 |
| `automation.py` | Add `activity_logger.log()` at fan control, cover control, chain trigger sites | ~40 |
| `__init__.py` | Initialize after DB store, register 2 AM prune timer, teardown | ~15 |
| `sensor.py` | `URALastActivitySensor` class (lean, ~100 lines) | ~100 |
| `hvac.py` | Log preset changes + pre-arrival | ~10 |
| `energy.py` | Log load shedding changes | ~10 |
| `house_state.py` | Log house state transitions | ~10 |
| `security.py` | Log armed state changes | ~5 |
| `safety.py` | Log hazard detections | ~5 |
| `notification_manager.py` | Log notifications sent | ~5 |
| **Total production** | | **~410** |
| `quality/tests/test_activity_logger.py` (NEW) | ~20 tests | ~200 |
| **Grand total** | | **~610** |

---

## Test Plan

New file: `quality/tests/test_activity_logger.py` (~20 tests)

**DB tests:**
- `test_activity_log_table_created` — `_create_table_safe` creates table
- `test_log_activity_write` — writes row with correct columns
- `test_log_activity_query` — `get_recent_activities()` returns correct data
- `test_prune_info_7d` — info entries older than 7 days removed
- `test_prune_notable_30d` — notable entries older than 30 days removed
- `test_prune_keeps_recent` — entries within retention kept

**ActivityLogger tests:**
- `test_dedup_same_description` — rapid identical events suppressed
- `test_dedup_different_description_passes` — different descriptions NOT suppressed
- `test_dedup_different_room_passes` — same action in different rooms NOT suppressed
- `test_critical_bypasses_dedup` — critical importance never deduped
- `test_fires_ha_event` — `ura_action` event fired with correct data
- `test_db_failure_no_raise` — DB error doesn't propagate to caller
- `test_no_db_no_crash` — works when database is None
- `test_details_json_capped` — details over 2KB truncated

**Sensor tests:**
- `test_sensor_initial_state` — shows "None" before first activity
- `test_sensor_updates_on_activity` — state changes after activity
- `test_sensor_recent_buffer` — last 10 activities in attributes
- `test_sensor_counts` — activities_today and notable_today correct
- `test_sensor_db_seed_on_startup` — loads last 10 from DB on init

**Logbook test:**
- `test_logbook_describe_event` — formats name and message correctly

---

## Risks

| Risk | Mitigation |
|------|------------|
| Write queue congestion | 30s dedup + ~1-2 writes/min peak. Write queue tested at high throughput in v3.22.8. |
| HA logbook flooding | Dedup window + HA logbook's own filtering. |
| Sensor attribute size | Capped at 10 entries (~1KB). Well within limits. |
| Dedup cache unbounded growth | Cleared during daily 2 AM prune callback. ~50-200 unique keys/day max. |
| `set_last_action` is sync | Use `hass.async_create_task()` for the async `log()` call. Safe — runs on event loop. |
| `details_json` bloat | Capped at 2KB in ActivityLogger before DB write. |
| Observation mode bypass | All integration points are at execution sites (post-observation-mode-check), not decision sites. Verified per-site. |

---

## Review Findings Applied

This plan incorporates fixes from a staff-engineer critique:

1. **Schema indexes reduced** from 4 to 2 (timestamp + coordinator only)
2. **`set_last_action` chokepoint corrected** — only covers light entry/exit. Plan now adds explicit calls at fan, cover, chain sites in automation.py
3. **Dedup key fixed** — now includes description to prevent suppressing legitimate different transitions
4. **`logbook.py` promoted** from optional to required deliverable (D5)
5. **Pruning timing fixed** — dedicated 2 AM timer, not piggyback on nonexistent midnight hook
6. **Line estimate corrected** — 280 → ~410 production + ~200 tests
7. **`async_create_task` pattern documented** for calling async `log()` from sync `set_last_action()`
8. **Observation mode addressed** — execution-site wiring self-gates; verified per integration point
9. **`details_json` size cap** added (2KB) to prevent DB bloat
10. **`dt_util.utcnow()` standardized** — no deprecated `datetime.utcnow()`
