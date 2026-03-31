# v3.20.0 — Room Resilience (Cycle A)

**Date:** 2026-03-31
**Tests:** 1318 (66 new)
**Review tier:** Feature (2 adversarial reviews + fixes)

## What Changed

Room-level automation — the foundation of URA — now survives HA restarts
without losing state, and all 5 per-room toggle switches actually work.

### D1: Room State Persistence
- `OccupiedBinarySensor` inherits `RestoreEntity` to persist critical
  coordinator state across restarts: `became_occupied_time`,
  `last_occupied_state`, `occupancy_first_detected`, `failsafe_fired`,
  cover daily dedup dates, trigger source, and lux zone.
- New `room_state` DB table as crash-resilience backup when RestoreEntity
  state is unavailable (fresh install, corrupted `.storage`).
- Throttled DB save every 5 minutes + shutdown save on unload.
- DB fallback wired into `async_added_to_hass` restore path.

### D2: Wire Orphaned Room Switches
- **ManualModeSwitch** ON now disables ALL automation (was never checked).
- **ClimateAutomationSwitch** OFF now gates climate/fan actions.
- **CoverAutomationSwitch** OFF now gates cover open/close actions.
- **OverrideOccupied** ON forces room occupied regardless of sensors.
- **OverrideVacant** ON forces room vacant regardless of sensors.
- Override switches now have `RestoreEntity` (state survives restart).
- Mutual exclusion: turning on one override turns off the other.
- Override sets `occupancy_source = "override"` and updates
  `_last_occupied_state` for correct transition detection.

### D3: Cover Automation Hardening
- `_get_available_covers()` filters unavailable/unknown entities before
  every cover command. `_are_covers_already_open/closed` also filter.
- Failed timed cover operations no longer set dedup date — allows retry
  next refresh cycle. Uses `blocking=True` for actual success detection.
- Invalid cover mode in config logs error and falls back to legacy mode.
- Missing HA location (no sunrise) defaults to NOT opening (safer).

### D4: Listener Cleanup on Fast Reload
- `async_config_entry_first_refresh` clears stale state/signal listeners
  before re-subscribing, preventing accumulation on rapid reloads.

## Review Findings Fixed
- **5 HIGH** issues fixed: untracked DB task, override `_last_occupied_state`,
  switch state ordering, DB fallback dead code, cover retry blocking
- **3 MEDIUM** issues fixed: cover already-open filter, shutdown save,
  timed cover blocking mode
- Full findings: `docs/reviews/code-review/v3.20_tech_debt_review_findings.md`

## Files Changed
- `binary_sensor.py` — RestoreEntity + DB fallback on OccupiedBinarySensor
- `coordinator.py` — switch wiring, override logic, DB backup, listener cleanup
- `automation.py` — cover hardening (validation, retry, mode, sunrise)
- `database.py` — room_state table + save/get methods
- `switch.py` — RestoreEntity on Override switches, mutual exclusion
- `__init__.py` — shutdown save on unload
