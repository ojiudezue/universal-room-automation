# v3.6.20 — Music Following Hardening: Sub-Cycle B (Behavior Hardening)

**Date:** 2026-03-02
**Cycle:** Music Following Hardening — Sub-Cycle B of 3

## Summary

Behavior hardening for music following: ping-pong suppression, transfer cooldown, post-transfer verification, Music Assistant queue transfer, winner rules for multi-person conflicts, and speaker group cleanup.

## Changes

### B1. Ping-Pong Suppression — `transitions.py`

Tracks recent transitions per person. If A→B is followed by B→A within 60 seconds, the return leg is suppressed (not notified to listeners). The forward A→B always fires immediately — zero added latency. All transitions are still logged to DB regardless of suppression.

State: `_recent_transitions: dict[str, list[tuple[str, str, datetime]]]`
Cleanup: integrated into existing `_async_cleanup_history()`.

### B2. Transfer Cooldown — `music_following.py`

8-second cooldown per person, only blocks transfers to the **same** target room. A→B cooldown does NOT block B→C. Prevents double-fire within a BLE scan cycle (~30s).

### B3. Post-Transfer Verification — `music_following.py`

After transfer:
1. Wait 2s, check target `state == playing`
2. If not playing → send `media_player.media_play` nudge
3. Wait 1s, recheck
4. If verified → fade source
5. If NOT verified → restore source volume, log failure

Key change: source fade now happens ONLY after verification passes.

### B4. Music Assistant Queue Transfer — `music_following.py`

When both source and target are `PLATFORM_MASS`, uses `music_assistant.transfer_queue` instead of join/play_media. Transfers full queue + playback position. MASS handles source pause internally. Falls through to generic on failure.

### B5. Winner Rules — `music_following.py`

If target room speaker `state == playing`, transfer is blocked with log "active playback blocked". Handles:
- Two people arrive → first person's transfer succeeds, second blocked
- Person enters room where someone is listening → no disruption
- Person enters empty room → transfer proceeds normally

### B6. Speaker Group Cleanup — `music_following.py`

After verified transfer, schedules `media_player.unjoin` on source with 5s delay. Restores source volume after unjoin. Tracks groups in `_active_groups` dict.

## Files Modified

| File | Changes |
|------|---------|
| `transitions.py` | Ping-pong suppression, `_recent_transitions` state, cleanup |
| `music_following.py` | Cooldown, verification, MASS transfer, winner rules, group cleanup |
| `const.py` | Constants already added in v3.6.19 |

## Testing

```bash
PYTHONPATH=quality python3 -m pytest quality/tests/ -v
```
