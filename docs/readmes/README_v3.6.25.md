# URA v3.6.25 — Music Following Coordinator Elevation

**Date:** 2026-03-03
**Type:** Feature — Domain Coordinator
**Scope:** const.py, domain_coordinators/music_following.py (NEW), __init__.py, switch.py, config_flow.py, strings.json, translations/en.json, sensor.py, music_following.py, person_coordinator.py

## Summary

Elevates the standalone MusicFollowing class to a full BaseCoordinator subclass registered with CoordinatorManager. Gains enable/disable switch, coordinator device, config flow UI for 7 tuning parameters, anomaly detection hooks, and diagnostic framework integration.

## Architecture

MusicFollowing is event-driven (TransitionDetector fires `_on_person_transition`), not intent-driven. `evaluate()` returns empty list — it participates in the coordinator lifecycle but doesn't use the intent/action pipeline. The coordinator wraps the existing standalone class, delegating to it rather than duplicating code.

### Priority Table

| Coordinator | Priority |
|-------------|----------|
| Safety | 100 |
| Security | 80 |
| Presence | 60 |
| Energy | 55 |
| Music Following | 30 |

## Changes

### New: `domain_coordinators/music_following.py`
- `MusicFollowingCoordinator(BaseCoordinator)` — priority 30, event-driven
- Wraps existing `MusicFollowing` instance from `hass.data`
- Applies 7 configurable parameters from coordinator manager config
- `async_setup()` registers anomaly metrics (transfer_success_rate, cooldown_frequency)
- `get_diagnostics_summary()` includes music following transfer stats

### 7 Configurable Parameters (via Config Flow)

| Parameter | Default | Description |
|-----------|---------|-------------|
| `mf_cooldown_seconds` | 8 | Min seconds between transfers per person |
| `mf_ping_pong_window` | 60 | Seconds for A→B→A suppression |
| `mf_verify_delay` | 2 | Post-transfer verification wait |
| `mf_unjoin_delay` | 5 | Speaker group unjoin wait |
| `mf_position_offset` | 3 | Media position seek offset |
| `mf_min_confidence` | 0.6 | Minimum transition confidence |
| `mf_high_confidence_distance` | 8.0 ft | BLE distance gate for music transfers |

### High Confidence BLE Distance (7th Parameter)
- Music-specific BLE distance threshold (default 8ft), tighter than person tracking global (10ft)
- `person_coordinator.py` now stores `closest_distance` in person data during confidence calculation
- `music_following.py` checks closest BLE scanner distance against this threshold before transferring
- Prevents music transfers on BLE bleed-through from adjacent rooms

### Other Changes
- `const.py` — 8 new constants, `COORDINATOR_ENABLED_KEYS` updated (now 7 coordinators)
- `__init__.py` — Import block + registration with all 7 params
- `switch.py` — `CoordinatorEnabledSwitch` for music_following (icon: mdi:music-note)
- `config_flow.py` — CM menu entry + `async_step_coordinator_music_following()` with 7 sliders
- `sensor.py` — `MusicFollowingHealthSensor` device_info updated for coordinator device
- `strings.json` + `translations/en.json` — All field labels and descriptions

## Backward Compatibility
- Standalone `music_following.py` unchanged — used as fallback when coordinators disabled
- Existing entity unique_ids preserved (no orphaned entities)

## Regression Checklist
All 10 items from plan verified:
1. Import block in `__init__.py` ✓
2. Switch entity in `switch.py` ✓
3. Toggle in coordinator_toggles ✓ (via switch entity)
4. Scoped unique_ids ✓
5. Platform.SWITCH not duplicated ✓
6. New file pre-staged ✓
7. Options flow pattern ✓
8. AnomalyDetector in async_setup ✓
9. Both strings files updated ✓
10. Entity registry preserved ✓

## Tests
645 tests pass (23 new for music following coordinator)
