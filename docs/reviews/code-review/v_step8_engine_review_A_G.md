# Step 8 D2-D4 engine: review A (local correctness) + G (goal fidelity)

Branch `feature/step8-d2-engine` @ f7277a07, diff `c67b8a78...HEAD`. Plan rev 3.6.1. Read only.
Read first: PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md (the new step 8 paragraph, plus the gate-relevant sections), SENSOR_FLEET_CLASSES.md,
charter goals (ARC_DRIFT_ANALYSIS), plan §1, §1.1, §5.4-§5.9, §6, §9, D0b audit §1, card fields. I did not read the whole
1151-line state-of-play doc line by line. The orchestrator did not give me the builder's list of 9 deviations, so the
rulings below cover the deviations I found myself in the diff.

## Verdict: FIX-REQUIRED (one G item needs the operator, one cheap code fix)

## Findings (ranked)

| # | Sev | Where | Finding |
|---|---|---|---|
| G-1 | HIGH (operator must hear) | const.py `ARRIVAL_OURS_ATTR = None`; music_following.py:1416-1419, 1554-1558 | With `None`, two of the five §1 promises are inert: "it stops at 15 minutes" (item 3) and "Departure pause" (item 5). Every started arrival that never reaches the room ends `wait_kept_unverified`, and the music plays on indefinitely. Every departure ends `departure_kept_unverified`. Repro: Oji arrives, never goes upstairs, master empty, idle Sonos. Result: music plays in the empty master all evening, and is still playing after he leaves the house. A phantom arrival that slips past `source_stale` is never cleaned up either, while branch T would stop it at 15 min. Plan §1.1 row #7 put D2 B0 (the live test, operator present) BEFORE the D2 build; the build went first. The withhold is the safe direction (it never stops someone else's music), but it changes what ships. Fix: run B0 and set the attribute before deploy, or get one operator line accepting "start-only until B0". |
| A-1 | MEDIUM | music_following.py:1524-1588 (`_departure_check`), spawned per tick at :1258, :1296 | Two concurrent `_arrival_tick` tasks (a PC update plus the player event that the pause itself causes) can both pass checks 0-6 before either reaches `_departure_end`, because `stamp.done` is set only after `await self._call(media_pause)`. Result: two `media_pause` calls, which breaks "exactly once" (B2). The outcome row is still written once, because `_departure_end` guards on `done`. Latent while `ARRIVAL_OURS_ATTR` is None (`ours` is None, so the check returns early). It becomes live the moment B0 sets the attribute. Fix: claim before the await (`stamp.done = True`, or an `acting` flag), then call. The window-end stop is not affected: it runs once from the timer. |
| A-2 | LOW | music_following.py:1477-1489 `_coowner_arrived` | It tests `other.music == "arrived" and other.target_room == room`, but "arrived" means "in any own room" (a bathroom counts), not "in R". Also, a co-owner who came home while R was playing ends `skipped_playing`, never `arrived`, so the case the plan names mostly reaches this check only through the stamp branch. Over-keeping is the safe direction, and the check runs after `_others_in_room` and before `_room_occupied`, so the effect is only the subtype label. Accept, or tighten to "placed in R". |
| A-3 | LOW | music_following.py:1252-1255 | `reversed_seen` fires on any non-URA-context write with state idle, paused, off or standby, so a playlist that finishes naturally inside the window counts as `reversed`. It also fires if the native entity of an MA-driven pair writes `idle` while MA plays. Both cases over-keep (no stop, no pause), so the result is safe but mislabelled. Record the native entity's state during the B0 live test. |
| A-4 | LOW | music_following.py:1115-1117 | When the room's own sleep clock is on, `resolve_slot` returns `sleep`, so `pick_media` returns None and the outcome reads `skipped_no_media`. The real cause is room sleep. The diagnostic misleads; it should be `skipped_sleep` (subtype `room`). |
| A-5 | LOW | music_following.py:1622-1641 | The ambiguity and toggle checks run before the bedroom check. So an entry into a SHARED BATHROOM (the master bath, with Oji and Ezinne both in their windows) consumes both intents' scene outcome (`scene_skipped_ambiguous`), although the plan says a bathroom returns None with no outcome. It matches the plan's literal order (1, 2, 3), so this is a plan ambiguity. The practical result is the same whenever both owners would be ambiguous at the bedroom too. Fix: move the bedroom test first. |
| A-6 | LOW | music_following.py:1119-1157 | A departure record that arrives during the 20 s verify sleep is dropped at :758 because no stamp exists yet. Under branch T the window-end stop covers it. Under None the music plays on. Narrow window. |
| A-7 | LOW (B lane, noted) | music_following.py:988 vs :1039 | The `intent_duplicate` check and the store are separated by two awaits (the gate 3b DB read and `_target_room`). Two arrival records for one person inside about 1 s cannot both pass gate 3b (the second is `short_absence`), so this is not reachable in practice. |

## Cleared, per site

| Site | Holds because |
|---|---|
| 3a counted / source_stale / boot | :973-981. Each uses `is not True` / `is not False`, so a missing attribute fails closed. This matches D0b, where the stale source separated the 29 phantoms. |
| 3b left_at | :1000-1008. The key `person_slug(person)` matches residency `snapshot()` (residency.py:209-215). `left_at` is overwritten only by departures (:160), so it holds the departure that started this absence. |
| 3b persisted rows | :1010-1027. Same-type rows are filtered to P. `ts < edge_ts` excludes the current arrival row (same float). A newer arrival, or `arr >= dep`, gives `departure_missing`, which fails closed. The lookback can be 0. DAO errors are swallowed and return `[]`, which also reads `departure_missing` (state of play notes this). |
| Short absence | `edge_ts - left_at >= 900`. The 40 s flap gives `short_absence`; a four-day trip passes. |
| Rule B, tracked person | :1085, through the registry rule `tracked_person_entity_id`; the STALE location counts by name. |
| Guest threshold | :864-884. House state `guest` OR `unidentified_or_guests >= 2` (row #9, D0b 7/77). Same read for the scene gate (:1646). |
| census None fail-open | :877-878. The flag rides on every later music outcome and is counted on the scene path. The trip-wire only arms once a census has been seen (portability). |
| 480 s backstop + own placement | :1093-1103. `occupied_since()` is a datetime, so `.timestamp()` against the epoch `t_a` is consistent. `me_here` skips the backstop. A None onset passes. |
| Start | Own room = first bedroom, else first bathroom, that has a player (:1050). `pick_media(prof, room_entry_id, slot)` matches its signature. Volume = profile clamp × room-scale clamp, clamped 0-1. MA first, native fallback. Never interrupts the player or its group members (:1190). Verify within 20 s against `playing`. |
| Toggle re-reads | One helper `_toggle_off` (:898), called at start, window end (with room paused) and departure check. Departure also reads `ARRIVAL_MUSIC_DEPARTURE_PAUSE`. |
| Window end order | :1378-1444. Order is reversed / not-ours, then toggles, then the final reach read and ONE move-log read (aware datetime via `dt_util.utc_from_timestamp`; truncated means the location read decides alone), then tracked person / co-owner / occupied, then neither-branch withhold, then stop (`media_stop`, or `media_pause` when the stop feature is absent), then the 120 s reversal watch. |
| Ours T/Q/neither | `_read_ours` / `_ours_now` (:1211-1233): one helper; None while unverifiable. Branches T and Q differ only in which attribute is read, and the code is generic over it. |
| Departure arm | `departed_during_wait` ends the music slot (:1500). A second departure is ignored. Departure during the reversal watch is ignored. Wait = room timeout + 300. Return check (any arrival since; truncated fails closed) comes before everything else. The group check covers both entities. The other-entity check comes after it. |
| Scene + B2 retry | automation.py:1776-1787. The retry runs once through the same guard and is skipped when the slot scene equals the welcome scene. At most one successful activation. A hold stays per-light. |
| Restart sweep | :1704-1745. Each ref is written once (`dedup_source_ref`, terminal sets). `started_at` uses the engine's own clock on both the write and the read side. |
| Trip-wires | :1749-1810. All seven exist with knob thresholds; 0 = off. |
| Knobs | Every number is a named rung-1 const (const.py:5180-5235). No inline literals, except the internal 30 s fallback `update_interval` (:1461) and the 5 s teardown wait. |
| Clocks | Engine `_wall` (epoch), residency `edge_ts` (epoch), `dt_util` only for the count date and the move-log datetime. No naive/aware mixing found. |

## G (goal fidelity)

- "play in your room and just wait for you to arrive": delivered (start at the edge, in the own room).
- "If music following is on, yes... don't have too much state": the hand-off adds nothing to the transfer path. The state
  kept after `arrived` is the departure stamp only, as the plan sanctions. Added state beyond the plan: two new outcomes
  (`wait_kept_unverified`, `departure_kept_unverified`) and `last_arrival_action` on the profile sensor (display). Both
  are minimal and justified.
- "Long run. Let's nail the room first": the welcome scene is own-bedroom only. Follow-me (D2b) is not built, which the
  plan allows (D2b, "ships off"). Say it in the README as deferred, not silently.
- G1, any counted edge including BLE-led: honoured. No source filter exists; Jaya and Ziri arrivals (BLE-only) open intents.
- Keep the departure pause: built, but inert under None (see G-1). **This is the one thing the operator must hear before ship.**

## Rulings on the deviations I identified

| Deviation | Ruling |
|---|---|
| `ARRIVAL_OURS_ATTR = None` shipped as branch "neither", with B0 after the build | FIX-or-SIGN-OFF (G-1) |
| New outcomes `wait_kept_unverified` / `departure_kept_unverified` | Accept (needed by the neither branch) |
| `ARRIVAL_GUEST_UNIDENTIFIED_MIN = 2` (plan said >= 1) | Accept: D0b-backed, recorded as row #9, rung 1 |
| `reversed_seen` checked again inside the departure check (outcome `stamp_cleared_reversed`) | Accept |
| B2 retry implemented in automation.py with two new result constants | Accept |
| Follow-me D2b not built | Accept, but list it in the README's "not done" |
| Deleted F5 handler plus the tests that pinned it (test_low_cleanup, v5100, ship2) | Accept; the replacement is a behavioural pin |
| `ARRIVAL_WINDOW_S <= 0` folded into `skipped_master_off` | Accept (kill switch; label it in the subtype if you like) |
| Episode `started_at` set to the engine clock | Accept (sweep and trip-wires compare like with like) |

## Must-fix before deploy
1. G-1: run the live B0 test and set `ARRIVAL_OURS_ATTR`, or record an operator line accepting start-only behaviour until then.
2. A-1: claim the stamp before awaiting the departure `media_pause`, with a test of two concurrent ticks.
Recommended in-cycle LOWs: A-4 (sleep label), A-5 (bedroom test first).
