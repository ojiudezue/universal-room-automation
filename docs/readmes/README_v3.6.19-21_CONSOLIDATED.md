# v3.6.19–3.6.21 — Music Following Hardening (Complete)

**Date:** 2026-03-02
**Scope:** 3 sub-cycles, 18 changes across 7 files, 32 new tests

## Problem Statement

Music following transfers music between speakers as people move rooms. The BLE tracking chain (Bermuda → PersonCoordinator → TransitionDetector → MusicFollowing) had critical UX failures:

1. **Speaker bouncing** — BLE signal flickering at room boundaries caused rapid back-and-forth transfers
2. **Permanent volume loss** — Source speaker volume faded to 10% unconditionally, even on failed transfers, and was never restored
3. **No transfer verification** — Transfer was fire-and-forget; if target speaker didn't actually start playing, nobody knew
4. **No conflict resolution** — Two people arriving in a room could trigger competing transfers
5. **Speaker groups grew forever** — Joined speakers were never unjoined after transfer
6. **False room matching** — Substring matching caused "den" to match "garden", "bed" to match "bedroom"
7. **Hardcoded device discovery** — 8 iPhone-specific patterns for Bermuda sensor lookup
8. **No diagnostics** — No visibility into transfer success/failure rates

## Architecture

Music following is configured **per-room** — each room opts in with `CONF_MUSIC_FOLLOWING_ENABLED` and specifies its `CONF_ROOM_MEDIA_PLAYER`. A single global `MusicFollowing` coordinator (stored at `hass.data[DOMAIN]["music_following"]`) processes all transfers across rooms.

The distance threshold (`person_high_confidence_distance`) is configurable via the integration-level config entry data but is **not yet exposed in the UI config flow**. Default is 10ft; the "very close" threshold is derived as half that value.

---

## Sub-Cycle A: Foundation Fixes (v3.6.19)

### A1. Concurrency Lock — `music_following.py`

`asyncio.Lock` wraps the entire transfer path in `_on_person_transition()`. If a second transition fires while a transfer is in progress, it's skipped with a log message. Prevents race conditions from simultaneous BLE updates.

### A2. Volume Save/Restore — `music_following.py`

| Before | After |
|--------|-------|
| Source faded to 10% unconditionally | Volume saved before fade, restored on failure |
| Failed transfer = permanent 10% volume | Source only fades after verified success |
| No way to recover without manual intervention | `_restore_volume()` pops from `_saved_volumes` dict |

### A3. Exact Room Matching — `person_coordinator.py`

Replaced 5-way fuzzy substring matching with exact match:
```python
is_match = (room_lower == location_lower)
```

The three-tier room resolution (direct area → scanner override → occupancy disambiguation) already produces canonical room names. Fuzzy matching was a v3.2.0 workaround that caused:
- "den" matching "garden" (substring "den" in "gar**den**")
- "bed" matching "bedroom"
- "master" matching "master_bedroom" and "master_bathroom"

### A4. Private BLE Bermuda Discovery — `person_coordinator.py`

Replaced 8 hardcoded iPhone patterns with a cascading discovery strategy:

1. **Config override** — `bermuda_area_sensors` dict per person (optional)
2. **Private BLE derivation** — finds `device_tracker.*` from `private_ble_device` platform → derives `sensor.{object_id}_area`
3. **Minimal fallback** — 2 patterns: `sensor.{first_name}_iphone_area`, `sensor.{normalized}_area`
4. **Registry fallback** — existing Bermuda entity registry search (unchanged, last resort)

Works with any BLE device (Android, Apple Watch, tiles), not just iPhones.

---

## Sub-Cycle B: Behavior Hardening (v3.6.20)

### B1. Ping-Pong Suppression — `transitions.py`

Tracks recent transitions per person. If A→B is followed by B→A within 60 seconds, the return leg is suppressed.

| Scenario | Behavior |
|----------|----------|
| Walk kitchen→living | Instant transfer (unchanged) |
| BLE flickers at boundary | First transfer fires, return suppressed |
| Genuine quick return (<60s) | Suppressed (music still in original room) |
| Walk kitchen→living→bedroom | All fire — different destinations, no suppression |

The forward leg A→B always fires immediately — zero added latency. All transitions are logged to DB regardless of suppression. Cleanup integrated into existing `_async_cleanup_history()`.

### B2. Transfer Cooldown — `music_following.py`

8-second cooldown per person, **same-target only**. A→B cooldown does NOT block B→C.

Why 8s: BLE scan cycle is ~30s. 8s prevents double-fire within a cycle while allowing rapid multi-room walks (kitchen→living→bedroom all fire independently).

### B3. Post-Transfer Verification — `music_following.py`

The core behavioral change — transfer is no longer fire-and-forget:

```
1. Execute transfer (join/play_media/MASS)
2. Wait 2s → check target state == playing
3. If not playing → send media_player.media_play nudge
4. Wait 1s → recheck
5. If verified → fade source
6. If NOT verified → restore source volume, log failure
```

Source fade moved from **unconditional** to **after verification only**.

### B4. Music Assistant Queue Transfer — `music_following.py`

When both source and target are Music Assistant (`PLATFORM_MASS`) speakers, uses `music_assistant.transfer_queue` instead of join/play_media. This transfers the full queue + playback position, and MASS handles source pause internally. Falls through to generic transfer on failure.

Transfer method priority:
1. `music_assistant.transfer_queue` (if both MASS)
2. `media_player.join` (speaker grouping)
3. `media_player.play_media` (generic, with 3s position offset)

### B5. Winner Rules — `music_following.py`

If target room speaker `state == playing`, transfer is blocked with "active playback blocked" log.

| Scenario | Result |
|----------|--------|
| Two people arrive simultaneously | First transfer wins, second blocked |
| Enter room where someone is listening | No disruption |
| Enter empty room | Transfer proceeds |

No priority ranking needed. Override via manual `media_player` service calls.

### B6. Speaker Group Cleanup — `music_following.py`

After verified transfer, schedules `media_player.unjoin` on source with 5-second delay. Restores source volume after unjoin. Tracks active groups in `_active_groups` dict. Cleanup tasks are stored and cancelled on teardown.

---

## Sub-Cycle C: Diagnostic Sensor (v3.6.21)

### C1. Transfer Tracking — `music_following.py`

Every transfer outcome is recorded in `_transfer_stats` with daily auto-reset:

| Outcome | Description |
|---------|-------------|
| `success` | Transfer verified, source faded |
| `failed` | Transfer service call threw exception |
| `unverified` | Call succeeded but target not playing after verification |
| `cooldown_blocked` | Blocked by 8s same-target cooldown |
| `active_playback_blocked` | Target room already playing (winner rules) |
| `low_confidence` | Transition confidence below threshold |
| `ping_pong_suppressed` | Return leg suppressed by transitions.py |

Listener pattern (`add_diagnostic_listener()`) pushes updates to the sensor entity.

### C2. `sensor.ura_music_following_health` — `sensor.py`

House-level diagnostic sensor (AggregationEntity, ENTRY_TYPE_INTEGRATION).

**Primary state**: `idle` / `following` / `transferring` / `cooldown` / `error`

**Attributes**:

| Attribute | Type | Description |
|-----------|------|-------------|
| `active_followers` | list | Person IDs with music following enabled |
| `last_transfer_from` | str | Source room |
| `last_transfer_to` | str | Target room |
| `last_transfer_person` | str | Who triggered transfer |
| `last_transfer_time` | str | ISO timestamp |
| `last_transfer_result` | str | Outcome from table above |
| `transfers_today` | int | Total attempts today |
| `transfer_failures_today` | int | Failures today |
| `transfer_success_rate` | float | Success percentage |
| `active_groups` | dict | Current speaker group membership |

---

## Additional Fixes from Code Review

These fixes address items from `REVIEW_MUSIC_PEOPLE_FOLLOWING.md`:

| ID | Fix | File |
|----|-----|------|
| P0-4 | Exact match replaces substring matching | `person_coordinator.py` |
| P2-13 | Scanner map caching — only rebuilds `_build_scanner_room_map` when room entry IDs change (was rebuilding every update cycle) | `person_coordinator.py` |
| P2-14 | Distance threshold now derived from configurable `high_confidence_distance` instead of hardcoded `5.0` | `person_coordinator.py` |
| P2-15 | Removed Sonos preference in area speaker discovery — picks first alphabetically | `music_following.py` |
| P2-16 | Added 3-second media position offset for generic transfers (compensates for transfer delay) | `music_following.py` |
| P2-18 | Cross-platform failure logging — logs platform, service, and entity on transfer failure | `music_following.py` |

---

## Files Modified

| File | Lines Changed | Sub-cycles |
|------|--------------|------------|
| `music_following.py` | +400 | A, B, C |
| `transitions.py` | +80 | B |
| `person_coordinator.py` | +60 | A |
| `sensor.py` | +50 | C |
| `const.py` | +10 | A |
| `manifest.json` | version bump | — |
| `quality/tests/test_music_following.py` | +250 (new) | — |

## New Constants

| Constant | Value | Purpose |
|----------|-------|---------|
| `CONF_BERMUDA_AREA_SENSORS` | `"bermuda_area_sensors"` | Per-person Bermuda sensor config override |
| `MUSIC_TRANSFER_COOLDOWN_SECONDS` | `8` | Same-target transfer cooldown |
| `PING_PONG_WINDOW_SECONDS` | `60` | A→B→A suppression window |
| `TRANSFER_VERIFY_DELAY_SECONDS` | `2` | Post-transfer state check delay |
| `GROUP_UNJOIN_DELAY_SECONDS` | `5` | Source unjoin delay after verified transfer |

## Testing

32 new tests covering ping-pong suppression, confidence calculation, path classification, cooldown logic, winner rules, media position offset, and exact match logic. Full suite: 622 passed, 0 failed.

```bash
PYTHONPATH=quality python3 -m pytest quality/tests/ -v
```

## Known Gaps

1. **Distance threshold not in UI** — `person_high_confidence_distance` is configurable in the config entry data but not exposed in the config flow UI. Must be set manually or via service call.
2. **Ping-pong window not configurable** — hardcoded at 60s. Could be made a constant in config if users need different values.
3. **No per-person transfer priority** — winner rules use simple "first wins" with no priority ranking between people.
