# v4.0.11 — Configurable Motion Detection Delay + Safety Hazard Spam Fix

## Changes

### 1. Configurable Motion Detection Delay (was hardcoded 500ms, now default 150ms)

The occupancy debounce — the time URA waits after motion is detected before confirming occupancy and triggering automation — was hardcoded at 500ms. Now:

- **Default reduced from 500ms to 150ms** — shaves ~350ms off every room entry
- **Configurable per room** via Configure → Basic Setup → "Motion Detection Delay"
- **Range: 0-2000ms** in 50ms steps
- **0ms** for rooms with pre-filtered sensors (Screek, ESPHome LD2410) that handle their own noise filtering
- **500ms+** for rooms with noisy PIR sensors that need extra filtering

**UI label:** "Motion Detection Delay"
**UI description:** "Milliseconds to wait before confirming occupancy after motion is detected. Lower = faster response, higher = fewer false triggers. 0 for instant response with pre-filtered sensors."

### 2. Safety Hazard Spam Fix — Log on Transitions Only

The safety coordinator was re-firing signals, activity logs, and response actions on EVERY evaluation cycle for active hazards. With CO2 sensors hovering at threshold (1000 ppm in Study A), this generated 7,500+ activity log entries per day.

**Fix:** `_respond_to_hazard()` now tracks whether a hazard is new or a repeated evaluation:
- **New hazard or severity change:** Full response — signal dispatch, activity log, NM notification, response actions
- **Same hazard, same severity:** Increment occurrence counter, return empty (no signal, no log, no response)
- **Hazard cleared:** Counter reset, ready for next detection

This follows HA's own "First occurred / N occurrences" pattern. The occurrence count is stored in `_hazard_occurrences` and cleaned up when hazards clear.

### 3. Activity Logger Critical Dedup Window (safety net)

Changed `_DEDUP_WINDOWS["critical"]` from `0.0` (never dedup) to `300.0` (5 minutes). This is a safety net — even if a coordinator forgets transition-only gating, the activity logger won't record more than one identical critical event per 5 minutes.

## Acceptance Criteria

### Motion Detection Delay
- **Verify:** Configure → Basic Setup for any room shows "Motion Detection Delay" field with 150ms default
- **Verify:** Setting to 0ms → occupancy confirmed on first refresh (no debounce wait)
- **Verify:** Setting to 500ms → same behavior as before v4.0.11
- **Verify:** AV Closet with 150ms default responds in <800ms (was 1.1s with 500ms debounce)
- **Test:** All 1670 existing tests pass

### Safety Hazard Spam
- **Verify:** CO2 at threshold no longer generates repeated activity log entries
- **Verify:** NEW hazard detection (first time, or severity change) still fires signal + log
- **Verify:** Hazard clearance resets tracking — next detection fires normally
- **Live:** Activity log `activities_today` count drops from 7,500+ to <100

### Activity Logger
- **Verify:** Two identical critical events within 5 minutes — second is deduplicated
- **Verify:** Critical events with different descriptions are NOT deduplicated

## Files Changed
- `const.py` — CONF_OCCUPANCY_DEBOUNCE, DEFAULT_OCCUPANCY_DEBOUNCE constants
- `coordinator.py` — Read debounce from config instead of hardcoded 0.5
- `config_flow.py` — NumberSelector field in initial setup + options flow
- `strings.json` — UI labels and descriptions (both sections)
- `translations/en.json` — Same UI text
- `domain_coordinators/safety.py` — Transition-only response + occurrence counter
- `activity_logger.py` — Critical dedup window 0→300s

## Review
- Tier 2 feature review (two reviews)
