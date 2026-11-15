# Review B — Music Following repair (async / lifecycle / race / restart)

Branch `feature/music-following-repair`, diff base `0ac39b2a...HEAD` (three-dot, verified).
Framing B only. Targeted tests: `test_music_following_repair.py` + `test_music_following_coordinator.py` = 110 passed.

## Findings

| # | Sev | Class | Site | Finding / repro |
|---|---|---|---|---|
| B1 | MEDIUM | Cross-person starvation (lock scope) | music_following.py:763 (`async with self._transfer_lock` wraps the whole `_pipeline`), :1236, :1270 | The house-wide lock is held through the verify sleep AND the release sleep. A second person queued behind it is aged at lock acquire (:805) against `stale_transition_seconds`. Legal repro: verify_delay=10, release_delay=10 (flow allows 0-30 each), stale=15 (default). Person A moves Kitchen→Living (music plays), Person B moves Office→Den 1 s later with music in Office. B acquires the lock ~21 s later → `stale_transition`, B's music never follows. At release_delay=30 every concurrent second mover is dropped. Fix: release the lock after the outcome is booked (run the release step outside the lock, it is per-person and already cancel-safe), or age from transition time minus queue wait. |
| B2 | MEDIUM | Hazard stop vs in-flight transfer (cross-coordinator) | domain_coordinators/music_following.py:673-697; music_following.py:1209, :1243 | `_stop_all_playback` does not cancel or gate in-flight MF transfers. Repro: transfer in phase `calling` (play_media / transfer_queue in flight) when a critical smoke hazard fires: hazard stops the configured players, then MF's call lands and the target starts playing during the hazard; or the generic `success_nudged` branch issues `media_play` after the stop. Fix: on hazard, cancel `_transfer_tasks` (their cleanup undoes the target) and gate `_on_person_transition` while the hazard is active. Also the hazard stop runs without the URA context, so the reversal watch (:1501) books it as `target_stopped_by_hand` and pollutes accuracy (LOW, same fix area). |
| B3 | MEDIUM | Restart safety (volume left at fade level) | music_following.py:205, :1224-1226 | `_saved_volumes` is memory only. Fade to `MF_FADE_TARGET_VOLUME` happens before verify + release (~7 s default, up to 60 s at knob max). A restart or crash in that window leaves the source speaker at 10 % with nothing to restore it on boot. HA's stop stage normally waits on tracked tasks, so a clean restart likely completes; a crash, watchdog restart (known hazard, memory `feedback_parent_entry_reload_watchdog_hazard`) or OOM does not. Operator ruling "never stuck at 10 %" is not met on that path. Fix: persist pending restores (small Store or RestoreEntity attr) and replay on init, or fade only after verify. |
| B4 | LOW | Double-cancel aborts cleanup | music_following.py:769-771 vs :455-466, :487 | Bounce cancels A's task; its `except CancelledError` awaits `_cleanup_superseded`. If `async_teardown` (CM reload) lands during that cleanup, the second `cancel()` interrupts the restore at its await, then teardown clears `_saved_volumes` (:487): source left faded. Narrow window (one service call). Fix: shield the cleanup (`asyncio.shield`) or run `_restore_saved` for all `_saved_volumes` in teardown before clearing. |
| B5 | LOW | Bounce mid-release can silence both rooms | music_following.py:1364-1367 with :1331 | Cancel delivered while `_release_source` is awaiting `media_stop` on the source, and the newer change is back to the source room: `_cleanup_superseded` sees phase `releasing`, `new_to == source_room` → `_undo_target` stops the target too. The new record then finds source stopped (→ `source_not_playing`). Window = one blocking service call. Fix: set a `source_released` flag before the stop and branch on it. |
| B6 | LOW | Uncertain cancel during blocking call | music_following.py:1278-1303 | `rec.target_started = True` is set only after the start call returns. A cancel delivered while `play_media`/`join`/`transfer_queue` is awaited skips `_undo_target`, but the call may still take effect in the integration → target plays while source keeps playing (two queues). I did not verify how HA propagates cancellation into a blocking service handler; set `target_started` before the await to make cleanup conservative. |
| B7 | LOW | Trip-wire window resets on restart | music_following.py:1590-1596 | `_recent_decisions` is memory only; any restart in the 24 h window under-counts candidates, so the zero-success trip-wire cannot fire on days with a restart. False-negative only. The candidate decisions are already persisted (`mf_decision` episodes); count from the DB like the 7-day roll-up. |
| B8 | LOW | Parent unload leaves MF un-torn-down | __init__.py:5812 | Parent unload pops `music_following` without `async_teardown`; relies on the CM coordinator teardown running first. New reversal-watch listeners (`async_track_state_change_event` + `async_call_later`, :1518-1519) outlive it up to 120 s if the order differs. Pre-existing pattern; call `async_teardown` before the pop. |

## Cleared

- Listener-leak fix holds: `add_diagnostic_listener` returns an unsub, stored at domain_coordinators/music_following.py:284 and called in teardown :709-714.
- Options live apply: `_apply_in_place` → `apply_config` with only changed MF keys (__init__.py:8449-8463); `_MF_LIVE_KEYS` covers all 13 flow knobs incl. `mf_unjoin_delay` (= `CONF_MF_RELEASE_DELAY`). Live reads (`_verify_delay_s`, `_release_delay_s`, `_bonus_joins`) are read at use; `follow_mode` is captured per record at :580 (correct: a mid-transfer mode change cannot flip move/extend halfway). Ping-pong window pushed live to the detector.
- Per-person supersede: newer change cancels the old task, new task awaits the old one's cleanup before taking the lock (:717-724, :761-763). `_on_done` books `superseded` for a task cancelled before its first step. Every room change gets one outcome (`_finish` idempotent).
- Mid-fade / mid-seek cancel: saved volume is recorded before the fade await (:1224-1225), seek is inside `_start_target` after `target_started`, so cleanup undoes target and restores source.
- Two persons into the same room: serialized by the lock; second sees the source stopped and skips cleanly; `_saved_volumes` is keyed by entity and never interleaves across persons under the lock.
- Arrival music: `music_on_arrival_start` is options-only, marked applied, no consumer; `set_preference_provider` is called synchronously and wrapped (:441-453).
- DB writes: episode writes are tracked tasks flushed in teardown (:1575-1580, :479-486). They use the existing `log_memory_episode` DAO (direct `_db()` per row, not the batch queue); rate is one row per candidate decision, acceptable, noted.

## Verdict

**FIX-REQUIRED** — B1, B2, B3 (MEDIUM; B2 and B3 each break an operator ruling: hazard stop must hold, no room stuck at 10 %). LOWs B4-B8 fix in-cycle per the fix-LOWs rule where cheap (B4, B5, B6 are a few lines each).

## Bug-class tally

| Class | Count |
|---|---|
| Lock scope / cross-person starvation | 1 |
| Cross-coordinator race (hazard) | 1 |
| Restart safety / volatile restore state | 2 (B3, B7) |
| Cancellation ordering | 3 (B4, B5, B6) |
| Teardown ordering | 1 |
