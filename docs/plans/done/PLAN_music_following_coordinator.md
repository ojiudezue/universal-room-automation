# Plan: Music Following Coordinator Elevation (v3.6.22)

**Date:** 2026-03-02
**Status:** Planned (not yet implemented)

## Context

Music Following is currently a standalone class (`MusicFollowing` in `music_following.py`), instantiated in `__init__.py` line 699-710, stored at `hass.data[DOMAIN]["music_following"]`. It should be elevated to a full `BaseCoordinator` subclass registered with the `CoordinatorManager` to gain: enable/disable switch, coordinator device, config flow UI for all tuning parameters, anomaly detection, and diagnostic framework integration.

## Priority Ordering

| Coordinator | Priority |
|-------------|----------|
| Safety | 100 |
| Security | 80 |
| Presence | 60 |
| Energy | 55 |
| Music Following | 30 |

## Architecture

MusicFollowing is **event-driven** (TransitionDetector fires `_on_person_transition`), not intent-driven. `evaluate()` returns empty list — it participates in the coordinator lifecycle but doesn't use the intent/action pipeline. This is valid within the `BaseCoordinator` contract.

## Implementation Steps

### Step 1: Add Constants — `const.py`

```python
CONF_MUSIC_FOLLOWING_COORDINATOR_ENABLED: Final = "music_following_coordinator_enabled"

# Add to COORDINATOR_ENABLED_KEYS dict:
"music_following": "music_following_coordinator_enabled",

# Configurable settings (replace hardcoded values):
CONF_MF_COOLDOWN_SECONDS: Final = "mf_cooldown_seconds"       # default 8
CONF_MF_PING_PONG_WINDOW: Final = "mf_ping_pong_window"       # default 60
CONF_MF_VERIFY_DELAY: Final = "mf_verify_delay"               # default 2
CONF_MF_UNJOIN_DELAY: Final = "mf_unjoin_delay"               # default 5
CONF_MF_POSITION_OFFSET: Final = "mf_position_offset"         # default 3
CONF_MF_MIN_CONFIDENCE: Final = "mf_min_confidence"            # default 0.6
```

### Step 2: Create `domain_coordinators/music_following.py` (NEW)

- Subclass `BaseCoordinator` with `coordinator_id="music_following"`, `name="Music Following"`, `priority=30`
- Move all logic from `music_following.py` into coordinator class
- Constructor takes configurable timing parameters instead of module-level constants
- `async_setup()` subscribes to TransitionDetector + instantiates AnomalyDetector
- `evaluate()` returns empty list (event-driven, not intent-driven)
- `async_teardown()` cancels listeners, cleanup tasks, saves anomaly baselines
- Record anomaly observations in `_record_stat()`: transfer_success_rate, failure_streak, cooldown_frequency

### Step 3: Update `__init__.py`

- Add `CONF_MUSIC_FOLLOWING_COORDINATOR_ENABLED` to import block at line ~806 (**CRITICAL — regression #1**)
- Add registration block after Security, before `async_start()`
- Keep `hass.data[DOMAIN]["music_following"]` reference for backward compat
- When coordinators disabled, fall back to standalone `MusicFollowing` class

### Step 4: Update `switch.py`

- Import `CONF_MUSIC_FOLLOWING_COORDINATOR_ENABLED` (**CRITICAL — regression #2**)
- Add `CoordinatorEnabledSwitch` for music_following:
  - `coordinator_id="music_following"`
  - `icon="mdi:music-note"`
  - `device_id="coordinator_music_following"`
  - `device_name="URA: Music Following"`

### Step 5: Update `config_flow.py`

- Add `"coordinator_music_following"` to CM menu options
- Add `async_step_coordinator_music_following()` with sliders for all 7 configurable settings (cooldown, ping-pong window, verify delay, unjoin delay, position offset, min confidence, high confidence distance)
- Add `CONF_MUSIC_FOLLOWING_COORDINATOR_ENABLED` to `coordinator_toggles` step (**CRITICAL — regression #3**)

### Step 6: Update `strings.json` + `translations/en.json`

Add entries for all config fields with descriptions (**CRITICAL — regression #9**).

### Step 7: Update `sensor.py`

- Update `MusicFollowingHealthSensor` device_info to use coordinator device
- Change unique_id to `{DOMAIN}_music_following_coordinator_health`
- Add entity registry cleanup for old unique_id (**CRITICAL — regression #10**)

### Step 8: Keep old `music_following.py` unchanged

Used as backward-compat fallback when domain coordinators are disabled.

### Step 9: Tests

Create `quality/tests/test_music_following_coordinator.py`:
- Test BaseCoordinator subclass
- Test evaluate() returns empty
- Test configurable parameters respected
- Test backward compat with standalone class

## Regression Prevention Checklist

| # | What | Why | How to Verify |
|---|------|-----|---------------|
| 1 | Import `CONF_MUSIC_FOLLOWING_COORDINATOR_ENABLED` in `__init__.py` line ~806 | Missing import killed ALL coordinators in v3.6.15 | `grep CONF_MUSIC_FOLLOWING_COORDINATOR_ENABLED __init__.py` |
| 2 | Add `CoordinatorEnabledSwitch` to `switch.py` | Missing in v3.6.16 for Security | `grep music_following switch.py` |
| 3 | Add toggle to `coordinator_toggles` step | Missing in v3.6.15 | `grep CONF_MUSIC_FOLLOWING_COORDINATOR_ENABLED config_flow.py` |
| 4 | Scope unique_ids with `_music_following_coordinator_` prefix | Duplicate IDs in v3.6.0-c2.9.2 | Grep for unique_id patterns |
| 5 | Verify `Platform.SWITCH` in `INTEGRATION_PLATFORMS` | Missing in v3.6.0-c2.7 | Already present, verify don't add twice |
| 6 | Pre-stage `domain_coordinators/` before deploy.sh | Glob misses subdirs (v3.6.0.4) | `git add domain_coordinators/` |
| 7 | Options flow uses `data={**options, **user_input}` | Options wipe in v3.6.0-c2.1 | Review config_flow pattern |
| 8 | Instantiate AnomalyDetector in `async_setup()` | Never instantiated in v3.6.0-c2.9 | Check async_setup body |
| 9 | Add all strings to `strings.json` AND `translations/en.json` | Missing strings show raw keys | Verify every CONF_MF_* key has entry |
| 10 | Clean up old entity registration on unique_id change | Orphaned entities from v3.6.0-c2.9.2 | Check entity registry after upgrade |

## Files to Modify

| File | Action |
|------|--------|
| `const.py` | Add constants, update COORDINATOR_ENABLED_KEYS |
| `domain_coordinators/music_following.py` | NEW — coordinator class |
| `__init__.py` | Wire registration, import block, backward compat |
| `switch.py` | Add CoordinatorEnabledSwitch |
| `config_flow.py` | Add config step + toggle |
| `strings.json` | Add UI strings |
| `translations/en.json` | Mirror strings |
| `sensor.py` | Update device_info, unique_id, cleanup |
| `quality/tests/test_music_following_coordinator.py` | NEW — tests |
