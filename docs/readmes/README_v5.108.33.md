# URA v5.108.33: arrival music, welcome scene, departure pause (arc step 8 D2-D4) + WiiM MA twin fix

Cards: ARRIVAL-ENGINE-S8-1 (this release; child of PERSON-PROFILE-PREFERENCES-1, which stays open for the live MA test,
the final ownership rule and v6.0.0), MF-MA-TWIN-WIIM-UUID-1, STUCK-SENSOR-S3B-S1-1 (boot-settle residual fix, below). Plan: `docs/planning/PLANNING_identity_actions_v6.md`
rev 3.6.1. Branch `feature/step8-d2-engine`. Tier 3: reviews A+G, B, D, then fix pass c05e2103, review C (436
mutations), test-gap pass 189509bd (76/76 drilled rows RED).

**Shipped as operator option B (2026-11-16):** arrival music and the welcome scene act now; the 15-minute stop and the
departure pause are built and active, but under the context-ownership rule a natural track change ends ownership, so
they will rarely fire until the live test sets the final rule (see Ownership). v6.0.0 is held for that complete release.

## What it does

- **Arrival music (D2).** When a resident who opted in on the People step comes home (one counted
  `person.*` arrival edge, GPS- or BLE-led), their pick starts on their own room's player and waits for
  them. Reaching any of their own rooms within 15 minutes hands the music to music following. Otherwise
  it stops at 15 minutes, unless someone else is in the room.
- **Welcome scene (D3).** Their own bedroom's entry lighting uses their scene during the arrival window.
  If that scene is missing or errors, the room's own slot scene is retried once (not per-light).
- **Departure pause (D4).** When they leave the house, music step 8 started for them pauses once the room
  is empty and nobody else is there.

## Gates (in order)

Intent: master on, music following enabled, not in observation mode; presence up; a tracked resident with
an action on and own rooms; the record is `counted`, not `source_stale`, not in the 600 s boot window; the
person's last departure is >= 900 s before the arrival (tracker `left_at`, else persisted rows, else fail
closed `departure_missing`); one intent per person.
Start: toggles; quiet / sleep / waking; room paused; another tracked person in the room; guests (house
`guest` OR >= 2 unidentified in the comfort census; a None census starts and is counted); the 480 s
backstop (skipped when the layer already places the person there); 1 h gap; the room's own sleep clock
(`skipped_sleep:room`); a pick and an AVAILABLE player (an unavailable bedroom player falls back to the next own
room); never interrupt a playing player or group; never start a grouped player (`skipped_grouped`); not inside the
music-following hazard block (`skipped_hazard`, re-checked after `play_media` and after the verify wait); one start
per room and per player at a time (`skipped_playing:inflight`). The tracked-person, backstop and (at window end /
departure) occupancy and co-owner checks cover the owners' SUITE (every own room of every owner of the target room:
for the master, the master bedroom and the master bath), plus a zone fallback player's own room.

## Ownership (fix pass 2026-11-15, orchestrator default, pending operator confirmation)

Music is "ours" from a successful start until any write to the played entity whose HA context music following did
not create (the context ids of its own calls: the start, stop, pause and every transfer call). Position-only writes
are ignored. A pause / stop / off / volume 0 from another context ends the wait as `reversed`; any other foreign write
as `wait_ended_not_ours` (after the hand-off: `stamp_cleared_reversed` / `stamp_cleared_not_ours`). With ownership
intact the window-end stop and the departure pause ACT (the old "neither" branch, `wait_kept_unverified` /
`departure_kept_unverified`, is gone). `ARRIVAL_OURS_ATTR` is an optional extra check (both must hold), default None.
**Expected live effect:** HA gives a device update that lands more than 5 s after a call a fresh context, so the
player's own next track change also ends ownership. With a multi-track pick the 15-minute stop will mostly not fire
and the departure pause will rarely fire; both fail toward leaving the music alone.

## Knobs (all rung 1, `const.py`)

`ARRIVAL_WINDOW_S` 900, `ARRIVAL_MIN_AWAY_S` 900, `ARRIVAL_OCCUPIED_BACKSTOP_S` 480,
`ARRIVAL_GUEST_UNIDENTIFIED_MIN` 2 (D0b), `ARRIVAL_MIN_GAP_S` 3600, `ARRIVAL_VERIFY_S` 20,
`ARRIVAL_REVERSAL_S` 120, `ARRIVAL_SCENE_CONFIRM_S` 120, `ARRIVAL_DEPARTURE_DB_LOOKBACK_S` 30 d,
`ARRIVAL_DEPARTURE_VACANCY_WAIT_S` 300, `ARRIVAL_MUSIC_DEPARTURE_PAUSE` True, `ARRIVAL_OURS_ATTR` None (optional
extra ownership check), `ARRIVAL_OWNERSHIP_IGNORED_ATTRS` {media_position, media_position_updated_at},
`MF_URA_CONTEXT_IDS_MAX` 256, `ARRIVAL_PC_INTERVAL_FALLBACK_S` 30, `ARRIVAL_EPISODE_LOG_PERSIST` True (the arrival
rows' own switch, split from `MF_EPISODE_LOG_PERSIST`), `ARRIVAL_RESTART_SWEEP_EXTRA_S` 3600, trip-wire thresholds
(§7). `ARRIVAL_MIN_AWAY_S` 0 admits every GPS flap (and turns off the restore-edge rule). A window not longer than
`ARRIVAL_VERIFY_S` is logged at start-up; the window end then waits for the start to resolve.

## Music following: the WiiM MA twin (MF-MA-TWIN-WIIM-UUID-1)

`_ma_candidates` now also matches the WiiM provider's MA players (`wiim_uuid:<UUID>`, UUID without dashes starting
with the native device's `wiim` identifier) and orders candidates live first. The `_5` MAC twins read unavailable
all week, so before this the MA path never ran in a WiiM room. Expect `path=ma` decisions between WiiM rooms.

## Stuck-sensor pages survive NM boot-settle (STUCK-SENSOR-S3B-S1-1 residual)

Found live in v5.108.30 validation: the first act-mode chatter page (Garage B ratgdo motion) never reached
`notification_log`. NM boot-settle collapses repeat (coordinator, hazard_type) emits for `NM_BOOT_SETTLE_S` (60 s), and
every stuck kind shares `STUCK_SIGNAL_NM_HAZARD_TYPE`, so the chatter page was swallowed by a dutycycle page sent 9 s
earlier. `fire_stuck_signal` still set its per-day latch, so chatter stayed silent until the next day.

- Hazards in the new `NM_BOOT_SETTLE_LOCATION_KEYED_HAZARDS` (const.py; today only the stuck-signal hazard) key
  boot-settle on (coordinator, hazard, location), so distinct stuck kinds each send. Other hazards are unchanged.
- `async_notify` returns `False` when it drops a message before delivery and `True` at the end. `fire_stuck_signal`
  sets its latch, ledger entry and anomaly row only when the send was not dropped, so a dropped page is retried at the
  next evaluation (a quiet-hours drop now delivers in the morning instead of being lost for the day).
- A boot-settle drop of a location-keyed hazard removes the dedup stamp it had just written, so the retry is not
  deduplicated away.

Review: Tier 1, SHIP, two LOWs (a repeated INFO boot log; a drop counter can count a retried page twice),
`docs/reviews/code-review/v_nm_boot_settle_stuck_kinds_review.md`. Tests `quality/tests/test_nm_boot_settle_stuck_kinds.py`
(6), 7/7 mutations RED.

Live check: after the restart, every distinct stuck kind active at boot has its own `notification_log` row; Garage B
chatter (if still chattering) pages today.

## Writer health

`arrival_music` / `welcome_scene` are checked only while the arrival master is on and at least one profile has
`auto_music` or `auto_scene` (switch-gated, `hass.data[DOMAIN]["arrival_actions_opted_in"]`).

## Live checks after install (operator present)

1. **D2 B0, MA play on another player:** play a stored MA pick on a different MA player, on
   `media_player.jayas_room_3` and on the master Sonos. Record whether the id plays and the value shape.
2. **Ownership check:** after an engine start, let one track change happen and read the next `Arrival decision`
   line: expect `wait_ended_not_ours` (the device's own update carries a fresh context). Record whether the played
   entity writes between tracks; that decides how often the stop / pause can act (operator question).
3. First opted-in arrival: `Arrival decision ... outcome=started` (or a named skip), then `arrived`,
   `wait_kept_*` or `wait_expired_stopped`; zero `stopped_then_arrived`; any GPS flap that day counted
   `skipped_not_counted_return:short_absence` with no `started`.
4. First welcome scene: one "Room entry [...]: activating ... scene=<welcome>" line, then
   `scene_confirmed`.
5. First departure after a start: `departure_paused` or a kept reason with `room_occupied` in the line.

## Validated (to be written back after install)

## Not done (accounted)

- Follow-me (D2b): not built (plan allows; ships off).
- Review D11 (a BLE-only resident's long silence at home then a `home` edge counts as an arrival): card to mint,
  measured none in D0b (12 of 12 real); not fixed by ruling.
- Writes to other members of the played entity's group are not watched (a grouped player is never stopped or
  paused, so no decision depends on them).
- A foreign write inside the 20 s verify wait (before the ownership listener starts) is not seen.

| Criterion | Result | Evidence |
|---|---|---|
| (pending) | | |
