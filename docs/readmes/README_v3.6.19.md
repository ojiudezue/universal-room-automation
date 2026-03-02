# v3.6.19 — Music Following Hardening: Sub-Cycle A (Foundation Fixes)

**Date:** 2026-03-02
**Cycle:** Music Following Hardening — Sub-Cycle A of 3

## Summary

Foundation fixes for music following: concurrency lock, volume save/restore, exact room matching, and improved Bermuda sensor discovery. These are prerequisite fixes for the behavior hardening in v3.6.20.

## Changes

### A1. Concurrency Lock — `music_following.py`

Added `asyncio.Lock` to `MusicFollowing.__init__`. The `_on_person_transition()` handler wraps its entire transfer logic in `async with self._transfer_lock`. If the lock is already held (concurrent transition), the call is skipped with a log message. Prevents race conditions when multiple transitions fire simultaneously.

### A2. Volume Save/Restore — `music_following.py`

- Added `_saved_volumes: dict[str, float]` to track pre-fade volume per player
- Source volume is saved BEFORE any fade attempt
- **Source fade is now gated behind `if transfer_success`** — the old code faded unconditionally (line 560-570), which permanently reduced source volume to 10% even on failed transfers
- Added `_restore_volume(entity_id)` method that pops from `_saved_volumes` and restores via `SERVICE_VOLUME_SET`

### A3. Fix Substring Matching — `person_coordinator.py:811-817`

Replaced 5-way fuzzy match with exact match only:
```python
is_match = (room_lower == location_lower)
```
The three-tier room resolution (Tier 1/2/3) already maps Bermuda areas to canonical room names. The fuzzy matching was a v3.2.0 workaround that caused false positives like "den" matching "garden".

### A4. Private BLE Bermuda Discovery — `person_coordinator.py:492-529`

Replaced 8 hardcoded iPhone patterns with a smarter discovery strategy:
1. **Config override** — optional `bermuda_area_sensors` dict per person (new `CONF_BERMUDA_AREA_SENSORS` constant)
2. **Private BLE derivation** — find `device_tracker.*` from `private_ble_device` platform, derive `sensor.{object_id}_area`
3. **Minimal fallback** — 2 patterns (`sensor.{first_name}_iphone_area`, `sensor.{normalized}_area`)
4. **Registry fallback** — existing Bermuda entity registry search (last resort)

### Constants Added — `const.py`

| Constant | Value | Purpose |
|----------|-------|---------|
| `CONF_BERMUDA_AREA_SENSORS` | `"bermuda_area_sensors"` | Config override for Bermuda sensors per person |
| `MUSIC_TRANSFER_COOLDOWN_SECONDS` | `8` | Transfer cooldown (Sub-Cycle B) |
| `PING_PONG_WINDOW_SECONDS` | `60` | Ping-pong suppression window (Sub-Cycle B) |
| `TRANSFER_VERIFY_DELAY_SECONDS` | `2` | Post-transfer verification delay (Sub-Cycle B) |
| `GROUP_UNJOIN_DELAY_SECONDS` | `5` | Speaker group cleanup delay (Sub-Cycle B) |

## Files Modified

| File | Changes |
|------|---------|
| `music_following.py` | asyncio.Lock, volume save/restore, gate fade behind success |
| `person_coordinator.py` | Exact match (811-817), private BLE discovery (492-529) |
| `const.py` | New constants for music following hardening |
| `manifest.json` | Version bump to 3.6.19 |

## Testing

```bash
PYTHONPATH=quality python3 -m pytest quality/tests/ -v
```

## Risk Assessment

- **A1 (Lock):** Zero risk — only adds protection, no behavioral change
- **A2 (Volume):** Low risk — fixes a known bug (unconditional fade). Worst case: source doesn't fade on success (investigate log)
- **A3 (Exact match):** Medium risk — removes fuzzy matching. Mitigated by three-tier resolution already producing canonical names
- **A4 (BLE discovery):** Low risk — adds new strategies before existing fallback. Existing registry search remains as last resort
