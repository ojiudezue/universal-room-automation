# v3.6.21 — Music Following Hardening: Sub-Cycle C (Diagnostic Sensor)

**Date:** 2026-03-02
**Cycle:** Music Following Hardening — Sub-Cycle C of 3

## Summary

Diagnostic sensor for music following: transfer tracking stats with daily reset, push-based sensor updates, and a house-level `sensor.ura_music_following_health` entity.

## Changes

### C1. Transfer Tracking — `music_following.py`

Added `_transfer_stats` dict and `_state` to `MusicFollowing.__init__()`. Every transfer outcome is recorded:

- `success` — transfer verified and source faded
- `failed` — transfer service call failed
- `unverified` — transfer call succeeded but target not playing
- `cooldown_blocked` — blocked by 8s cooldown
- `active_playback_blocked` — target room already playing
- `low_confidence` — transition confidence below threshold
- `ping_pong_suppressed` — suppressed by transitions.py (tracked but not called from music_following)

Daily counters with date-based reset. Listener pattern (`add_diagnostic_listener()`) for sensor push updates.

### C2. `sensor.ura_music_following_health` — `sensor.py`

House-level sensor (AggregationEntity, ENTRY_TYPE_INTEGRATION).

**Primary state**: `idle` / `following` / `transferring` / `cooldown` / `error`

**Attributes**:

| Attribute | Type | Description |
|-----------|------|-------------|
| `active_followers` | list | Person IDs with music following enabled |
| `last_transfer_from` | str | Source room |
| `last_transfer_to` | str | Target room |
| `last_transfer_person` | str | Who triggered it |
| `last_transfer_time` | str | ISO timestamp |
| `last_transfer_result` | str | success/failed/unverified/cooldown_blocked/active_playback_blocked |
| `transfers_today` | int | Total attempts today |
| `transfer_failures_today` | int | Failures today |
| `transfer_success_rate` | float | Percentage |
| `active_groups` | dict | Current speaker group membership |

## Files Modified

| File | Changes |
|------|---------|
| `music_following.py` | `_transfer_stats`, `_state`, `_record_stat()`, `get_diagnostic_data()`, `add_diagnostic_listener()` |
| `sensor.py` | `MusicFollowingHealthSensor` class, added to ENTRY_TYPE_INTEGRATION setup |
| `const.py` | Version bump to 3.6.21 |
| `manifest.json` | Version bump to 3.6.21 |

## Testing

```bash
PYTHONPATH=quality python3 -m pytest quality/tests/ -v
```
