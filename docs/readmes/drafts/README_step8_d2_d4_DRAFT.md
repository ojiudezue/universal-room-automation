# URA v(TBD): arrival music, welcome scene, departure pause (arc step 8 D2-D4)

**Status: DRAFT, version TBD (v6.0.0 path), not deployed.** Plan: `docs/planning/PLANNING_identity_actions_v6.md`
rev 3.6.1. Branch `feature/step8-d2-engine`. Tier 3.

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
backstop (skipped when the layer already places the person there); 1 h gap; a pick and a player; never
interrupt a playing player or group.

## Knobs (all rung 1, `const.py`)

`ARRIVAL_WINDOW_S` 900, `ARRIVAL_MIN_AWAY_S` 900, `ARRIVAL_OCCUPIED_BACKSTOP_S` 480,
`ARRIVAL_GUEST_UNIDENTIFIED_MIN` 2 (D0b), `ARRIVAL_MIN_GAP_S` 3600, `ARRIVAL_VERIFY_S` 20,
`ARRIVAL_REVERSAL_S` 120, `ARRIVAL_SCENE_CONFIRM_S` 120, `ARRIVAL_DEPARTURE_DB_LOOKBACK_S` 30 d,
`ARRIVAL_DEPARTURE_VACANCY_WAIT_S` 300, `ARRIVAL_MUSIC_DEPARTURE_PAUSE` True, `ARRIVAL_OURS_ATTR` None,
`ARRIVAL_RESTART_SWEEP_EXTRA_S` 3600, trip-wire thresholds (§7).

## Live checks after install (operator present)

1. **D2 B0, MA play on another player:** play a stored MA pick on a different MA player, on
   `media_player.jayas_room_3` and on the master Sonos. Record whether the id plays and the value shape.
2. **D2 B0, the `ours` check:** for a playlist pick and an album / station pick, read `media_content_id`
   and every queue / source attribute of the native and MA entity right after the start and after a track
   skip. Record the values here. Then set `ARRIVAL_OURS_ATTR`: `"media_content_id"` (branch T) or the
   stable attribute (branch Q). **Until it is set (branch "neither", as shipped) the window-end stop and
   the departure pause do not act**; they record `wait_kept_unverified` / `departure_kept_unverified`.
3. First opted-in arrival: `Arrival decision ... outcome=started` (or a named skip), then `arrived`,
   `wait_kept_*` or `wait_expired_stopped`; zero `stopped_then_arrived`; any GPS flap that day counted
   `skipped_not_counted_return:short_absence` with no `started`.
4. First welcome scene: one "Room entry [...]: activating ... scene=<welcome>" line, then
   `scene_confirmed`.
5. First departure after a start: `departure_paused` or a kept reason with `room_occupied` in the line.

## Validated (to be written back after install)

| Criterion | Result | Evidence |
|---|---|---|
| (pending) | | |
