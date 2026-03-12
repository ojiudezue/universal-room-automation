# v3.11.0 — Non-Energy DB Table Wiring

**Status**: Implemented
**Date**: 2026-03-11
**Scope**: Wire 5 existing database tables that had write methods with zero callers

---

## Context

The URA database (`database.py`) has 7 tables with write methods that were never called by any coordinator. Phases D1-D2 (energy_history, external_conditions) are covered in `PLANNING_v3.11.0_ENERGY_REFINEMENT.md`. This document covers the remaining 5 tables wired to their natural callers in the presence, census, and person tracking coordinators.

---

## D3: `log_house_state_change()` → `presence.py`

### Table
```sql
house_state_log (timestamp, state, confidence, trigger, previous_state)
```

### Hook Point
Inside `_run_inference()` in `presence.py`, immediately after `_log_state_transition()` is called (when a house state transition is accepted).

### Data Sources
- `state`: New house state from inference engine result
- `confidence`: Inference confidence score
- `trigger`: Trigger source (e.g., "geofence", "door", "motion_timeout")
- `previous_state`: State before transition

### Pattern
```python
db = self.hass.data.get(DOMAIN, {}).get("database")
if db is not None:
    self.hass.async_create_task(
        db.log_house_state_change(
            state=new_state,
            confidence=confidence,
            trigger=trigger,
            previous_state=old_state,
        )
    )
```

---

## D4: `log_zone_event()` → `presence.py`

### Table
```sql
zone_events (zone, timestamp, event_type, room_count, rooms)
```

### Hook Point
End of `_run_inference()` in `presence.py`, after inference completes. Captures zone modes before inference (dict snapshot), compares after, logs any changes.

### Data Sources
- `zone`: Zone name from zone manager
- `event_type`: New zone mode (e.g., "occupied", "vacant", "partial")
- `room_count`: Number of occupied rooms in the zone
- `rooms`: Comma-separated list of occupied room names

### Implementation
A snapshot of zone modes is taken at the start of `_run_inference()`. After inference completes, current zone modes are compared to the snapshot. Any zone whose mode changed gets a `log_zone_event()` call.

---

## D5: `log_census()` → `camera_census.py`

### Table
```sql
census_snapshots (timestamp, zone, identified_count, identified_persons,
                  unidentified_count, total_persons, confidence,
                  source_agreement, frigate_count, unifi_count)
```

### Hook Point
Inside `_async_update_census_locked()` in `camera_census.py`, right after the census signal dispatch (`SIGNAL_CENSUS_UPDATED`).

### Data Sources
- Two calls per census cycle: one for `house_result` (zone="house") and one for `property_result` (zone="property")
- Each result contains identified persons, unidentified count, confidence, source agreement scores

### Implementation
```python
db = self.hass.data.get(DOMAIN, {}).get("database")
if db is not None:
    for zone, result in [("house", house_result), ("property", property_result)]:
        self.hass.async_create_task(db.log_census(zone, result))
```

---

## D6: `log_person_entry()` / `log_person_exit()` → `person_coordinator.py`

### Table
```sql
person_visits (person_id, room_id, entry_time, exit_time, duration_seconds,
               entry_method, exit_method, confidence)
```

### Hook Point
Inside `_async_update_data()` in `person_coordinator.py`, right after the `ura_person_location_change` event is fired (when `location_changed` is detected).

### Implementation
New helper method `_log_person_room_change()` manages visit lifecycle:
1. If person had an active visit (tracked in `_active_visit_ids: dict[str, int]`), call `log_person_exit()` to close it
2. If new location is a room (not "away", "unknown", "home"), call `log_person_entry()` to open a new visit
3. Store returned visit ID in `_active_visit_ids` for future exit

### Data Sources
- `person_id`: Person entity ID
- `room_id`: Room config entry ID (or None for non-room locations)
- `entry_method` / `exit_method`: Detection method (e.g., "ble", "motion", "door")
- `confidence`: Location confidence from person data

---

## D7: `log_person_snapshot()` → `person_coordinator.py`

### Table
```sql
person_presence_snapshots (timestamp, person_id, location, confidence,
                          method, room_count, persons_home)
```

### Hook Point
End of `_async_update_data()` in `person_coordinator.py`, after all person data is computed.

### Throttle
Uses `_last_snapshot_time` with 900-second (15-minute) interval to avoid excessive writes. Each snapshot logs all tracked persons' current location, confidence, and detection method.

### Implementation
```python
now = time.time()
if now - self._last_snapshot_time >= 900:
    self._last_snapshot_time = now
    for person_id, data in self._person_data.items():
        self.hass.async_create_task(
            db.log_person_snapshot(
                person_id=person_id,
                location=data.get("location", "unknown"),
                confidence=data.get("confidence", 0.0),
                method=data.get("method", "unknown"),
            )
        )
```

---

## Common Patterns

All DB wiring follows these patterns:

1. **Null-safe DB access**: `db = self.hass.data.get(DOMAIN, {}).get("database")` — never crashes if DB not initialized
2. **Fire-and-forget**: `self.hass.async_create_task(db.log_xxx(...))` — DB writes don't block the coordinator's main loop
3. **Natural hook points**: Logging calls placed at existing state transition points, not added as separate steps
4. **No new imports**: Uses existing `DOMAIN` constant already imported in each file

---

## Cleanup

Daily cleanup methods added to `database.py`:
- `cleanup_energy_history(retention_days=180)` — called from `energy.py._maybe_reset_daily()`
- `cleanup_external_conditions(retention_days=90)` — called from same
- `cleanup_census(retention_days=90)` — already existed
- Person visits cleanup already existed at 365 days

---

## Verification

### DB Queries (via ura-sqlite MCP or direct)
After running for 1 hour:
```sql
SELECT COUNT(*) FROM energy_history;        -- ~4 rows
SELECT COUNT(*) FROM external_conditions;   -- ~4 rows
SELECT COUNT(*) FROM house_state_log;       -- 0+ (event-driven)
SELECT COUNT(*) FROM zone_events;           -- 0+ (event-driven)
SELECT COUNT(*) FROM census_snapshots;      -- ~60 rows (every 60s)
SELECT COUNT(*) FROM person_visits;         -- 0+ (event-driven)
SELECT COUNT(*) FROM person_presence_snapshots; -- ~4 rows per person
```
