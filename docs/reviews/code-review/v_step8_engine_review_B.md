# Arc step 8 engine (D2-D4), Tier 3 review B: integration, lifecycle, async, restart

Branch `feature/step8-d2-engine` @ f7277a07, worktree `.claude/worktrees/builder-step8-d2`, diff `git diff c67b8a78...HEAD`.
I read `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` and `SENSOR_FLEET_CLASSES.md` in full first. I re-assert no §10 claim.
This was a read-only pass and ran no tests. Line numbers are `music_following.py` on the branch unless another file is named.

## Verdict: FIX-REQUIRED (1 HIGH, 2 MEDIUM)

| # | Sev | Site | Finding | Class |
|---|---|---|---|---|
| B-H1 | HIGH | `_music_start` 1068-1140 | The arrival start ignores the music-following hazard block. | cross-coordinator gate miss (#53) |
| B-M1 | MEDIUM | `_open_intent` 1029-1047, `_music_start` 1128-1140 | Two co-owners arriving together can both call `play_media` on one player and create two stamps. | race / no in-flight guard |
| B-M2 | MEDIUM | `const.py` 6763-6768 (writer-backed), 6810 (absence-exempt) | Builder note 9: writer-health raises a false page every week when no resident opts in. | observation gating (#23) |
| B-L1 | LOW | `_arrival_sync_pc_listener` 1274 | The PC listener stays registered for a handed-off stamp's whole life. | plan deviation |
| B-L2 | LOW | `_arrival_teardown` 706-728, `_arrival_spawn` 730 | Teardown releases listeners and timers only after the cancelled tasks are awaited; nothing stops spawns after teardown. | untracked background task |
| B-L3 | LOW | `_window_end_music` 1420-1445 vs `_async_departure` 1493-1501 | A departure during the window-end stop is labelled `departed_during_wait`, and a watch timer is left on an ended stamp. | race / mislabel |
| B-L4 | LOW | `_arrival_outcome` 943 | `_notify_listeners()` feeds `_on_transfer_outcome`, so each arrival outcome re-records the MF anomaly metrics. | signal pollution |
| B-L5 | LOW (latent) | `_window_end_music` 1420-1445 | The window-end stop has no group check. This is latent while `ARRIVAL_OURS_ATTR` is None. | missing site vs departure |
| B-L6 | LOW | `_write_episode` 2959-2961 | Arrival episodes are gated by `MF_EPISODE_LOG_PERSIST`. | coincidental coupling (#63) |

### B-H1 (HIGH): the arrival start plays music inside a hazard block
`async_hazard_stop` (3261) sets `_hazard_until` to now + `MF_HAZARD_BLOCK_S`, which is 1800 s (`const.py:4478`). The MF transfer paths check `hazard_active()` at 2100 and 3421. `_music_start` never does, and the plan has no hazard gate either. A hazard stop also leaves an in-flight arrival task running.

**Repro:**
1. Smoke is detected, `SIGNAL_SAFETY_HAZARD` fires, and the hazard stop runs.
2. Ten minutes later Oji gets home after 1 h out. The return is counted, the source is not stale, it is outside the boot window, and `auto_music` is on.
3. Every gate passes. `play_media` reaches the master bedroom player while the hazard block is still active, and the music can mask the alarm.

A start already waiting in its 20 s verify also survives the stop. If its `play_media` lands just after the stop, the music plays.

**Fix:** add `if self.hazard_active(): skipped_hazard` (terminal) before step 7, and re-check it straight after the `play_media` await. The new outcome has to be added to `_MUSIC_TERMINALS`.

### B-M1 (MEDIUM): a joint arrival races to the player
Two things allow the race:
- `_open_intent` awaits `_target_room` before it inserts the intent.
- `_music_start` checks `_any_playing` (1129) and then awaits a blocking `play_media` (1133-1140).

Nothing guards a room that has a start in flight.

**Repro:** Oji and Ezinne both own the master bedroom and both have `auto_music` on. Their phones' geofences go home about 1 s apart. B's `_any_playing` runs while A's blocking `play_media` is still in flight, so it reads not playing.

What follows:
- Both intents call `play_media`, and B's pick and volume replace A's.
- Two `started` rows are written.
- Two stamps point at one player, so the departure and window-end logic runs twice.

The existing test `test_two_owner_intents_music_once_coowner_arrived` uses arrivals 1100 s apart, so it does not cover this.

**Fix:** keep a per-room in-flight set, filled before the first await of a start. A second start in that room ends `skipped_playing` (subtype `inflight`).

### B-M2 (MEDIUM): weekly writer-health false page (builder note 9)
`arrival_music` and `welcome_scene` are in `MEMORY_WRITER_BACKED_EPISODE_TYPES`. Rows are written only from `intent_opened` onwards, and every skip before that is a counter only (`_arrival_count`). So with no resident opted in, or with the master off, the check sees 0 rows in 7 days. The absence exemption suppresses the page only when `house_state_log` proves the house was AWAY or VACATION for the whole week. An ordinary week at home therefore pages every week. That is a false alarm: the configuration is valid and the writer is fine.

**Recommendation:** gate the check on opt-in rather than exempting it. The mechanism exists: `MEMORY_WRITER_HEALTH_SWITCH_GATED_TYPES` (`const.py:6822`, read at `database.py:11595`). Add both types under a `hass.data[DOMAIN]` key that the engine keeps True only while the master is on and at least one profile has `auto_music` or `auto_scene`.

Do not use `MEMORY_WRITER_HEALTH_EXEMPT_TYPES`. With an exemption, an opted-in resident whose arrivals never open an intent would go unpaged, and `arrival_action_zero` cannot catch that case because it needs 10 or more intents.

### B-L1: the PC listener outlives the waits
The plan (§5.5.2) says the listener is "removed when the last [wait / departure wait] closes". The code computes `needed` as true while any stamp is not done (1274). A handed-off stamp stays live until the person departs or reverses the music, which can be hours. For that whole time every PC update (about 30 s) spawns an `_arrival_tick` task. That tick only re-checks reversed / not-ours, and the player listener could do that itself.

`test_listener_removed_when_no_waits_and_at_teardown` checks teardown only.

**Fix:** don't count a handed-off stamp with no departure wait in `needed`.

### B-L2: teardown ordering
Teardown does these steps in order:
1. Unsubscribes the edge.
2. Cancels the tasks.
3. Awaits them for up to 5 s.
4. Clears the task set.
5. Cancels the intent timers and the stamp listeners.
6. Releases the PC listener.

During the step 3 await, any of these can spawn a task: a PC update, a player event, a window timer (`_on_window_timer` still finds the intent), or a departure timer. Step 4 then drops that task from tracking. The task runs after teardown against tables that are cleared or being cleared, and it can write episodes. A `_window_end` that runs in this gap could also issue `media_stop` once B0 sets `ARRIVAL_OURS_ATTR`. The await is normally near-instant, so the exposure is small.

**Fix:**
- Set a torn-down flag first, and make `_arrival_spawn`, `_on_window_timer` and `_on_pc_update` return when it is set.
- Cancel timers and listeners before the await.
- Clear the flag in `async_start_arrival_actions`.

### B-L3: window-end stop vs departure in the same tick
Order of events:
1. `_window_end_music` awaits `media_stop` (around 1436).
2. During that await, `_async_departure` runs. The stamp's `watch_until` is not set yet, so it ends the music with `departed_during_wait` and arms the departure wait.
3. The stop's own `wait_expired_stopped` is then a no-op, so the row says a stop never happened.
4. `departure_check` reads not-ours and ends the stamp.
5. `_window_end_music` then schedules `watch_unsub` (1441) on a stamp that has ended and is no longer in the table, so teardown cannot cancel it. It is harmless because `_end_watch` returns on `done`.

**Fix:** set `stamp.watch_until` (or a stopping flag) before the stop await, and skip the watch when the stamp has ended.

### B-L4: anomaly-metric pollution
Each `_arrival_outcome` calls `_notify_listeners()` (943). The listeners include `MusicFollowingCoordinator._on_transfer_outcome` (`domain_coordinators/music_following.py:278`, 321-400). That callback records `transfer_success_rate` and `cooldown_frequency` from the cumulative transfer stats, which have not changed. A started-and-arrived arrival therefore adds about 3 to 5 identical samples, and the restart sweep adds more.

This matches the existing pattern, in which `_record_stat` notifies on rejections too, so it is LOW. It still lets non-transfer events narrow the baseline.

**Fix:** notify only the display listeners, or add a separate listener hook for display.

### B-L5 (latent): the window-end stop has no group check
`_departure_check` skips a grouped player (`departure_kept_group`), but the window-end path does not. MF joins with the source as leader (2676-2677: `join` with `entity_id = source`), so a `media_stop` on a stamped leader would stop every joined member.

It can't happen today: `_ours_now` returns None, so step 5 always ends `wait_kept_unverified`. Reaching it after B0 also needs MF to have joined the stamped leader before hand-off, which is rare. Add the same group test before `ARRIVAL_OURS_ATTR` is set.

### B-L6: one kill switch covers two writers
`_write_episode` returns early when `MF_EPISODE_LOG_PERSIST` is False. The arrival rows serve the restart sweep, the trip-wires and writer health, so with that switch off the sweep and trip-wires cannot see anything and writer health pages every week. The two writers should be split, or the coupling documented on the constant.

## Focus areas cleared
1. **Subscription lifecycle.** The subscription is made in `async_start_arrival_actions`, called by `async_init` (`__init__.py:3432`) and by the coordinator's setup (`domain_coordinators/music_following.py:291-299`). It is idempotent through the `_edge_unsub` guard. The coordinator's `async_teardown` (653-680) calls `engine.async_teardown`, which calls `_arrival_teardown` first, so a CM reload unsubscribes and then re-subscribes once. Parent unload goes through `_async_teardown_music_following` (`__init__.py:5742`), and a second teardown is a no-op. `_on_person_edge` is sync and only schedules work; `subscribe_person_edges` rejects a coroutine callback (`residency.py:253`) and wraps the callback in `@callback`. All timers go through `_schedule_later`, which wraps a sync callback in `callback`, and are cancelled on terminal outcomes and at teardown. Arrival tasks are tracked in `_arrival_tasks`; the residual is B-L2.
2. **Deleted F5 handler.** The removed `_handle_person_arriving` did nothing but write a DEBUG log line (diff). `SIGNAL_PERSON_ARRIVING` is still connected by HVAC (`hvac.py:1512`) and security (`security.py:819`, which also feeds the lock regime). The diff touches neither `hvac.py`, `presence.py` nor `security*.py`. HVAC pre-arrival and the guest gate are unchanged, and no consumer lost behaviour.
3. **Music-following interaction.**
   - MF's `_call` uses `ura_write_context` (2534-2541), so an MF transfer that pauses or unjoins the stamped player does not set `reversed_seen`.
   - With `ours` None, the departure and window-end paths only record outcomes and issue no stop or pause, so the two cannot fight today.
   - `departure_kept_group` protects a grouped player at departure.
   - Adding the arrival players to `_started_players` widens only the hazard-stop scope (3237), which is the right direction.
   - There is no double stop. The gaps are B-H1 and B-L5.
4. **`automation.py` B2 retry.** It runs only inside `if welcome:` (`automation.py:1776-1787`). With no profile or welcome scene, `welcome` is None and the path is byte-identical. HOLD is checked before availability inside `_activate_scene_checked` (around 1851 vs 1866), so a hold never triggers the retry. The sleep caller (`automation.py:1490`) passes no `arrival_override` and is untouched.
5. **Restart.**
   - The sweep (`_arrival_restart_sweep`) writes episodes only and makes no service call, so it cannot stop music.
   - `wait_lost_restart`, `intent_lost_restart`, `scene_lost_restart` and `departure_stamp_lost_restart` are each in their own terminal set, and the writes are deduped on `{ref}:{outcome}`, so the sweep is idempotent across restarts.
   - The DB is created in the integration branch (`__init__.py:2735`) before MF is initialised (3432), so the sweep has a database at boot.
   - The boot window fails closed: the `source_stale` and `in_boot_window` getattrs default to True, and `counted` must be True.
   - The persisted-row away test fails closed: the DAO swallows errors and returns `[]`, which reads `departure_missing`. The `departure_read_failed` subtype can therefore never fire.
6. **DB.**
   - `started_at` and `ended_at` are set from the engine clock as tz-aware ISO strings, which compare consistently with the `since` bounds the readers use.
   - Writes go through `log_memory_episode` in `_episode_tasks` tasks, which teardown flushes. They are per row, matching MF's existing pattern, and the volume is low.
   - The types are registered in the writer-backed set and in the absence-exempt set; see B-M2 for the recommendation.

## Must-fix before ship
- **B-H1:** add a hazard gate and re-check it after `play_media`.
- **B-M1:** add a per-room in-flight start guard.
- **B-M2:** switch-gate the writer-health check on opt-in.

Fix the LOWs in the same fix-up pass. Fix B-L5 before B0 sets `ARRIVAL_OURS_ATTR`.
