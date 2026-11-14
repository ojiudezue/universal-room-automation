# AUDIT: crossing-ledger empty-house checkpoint window sweep (CROSSING_VISION_LEDGER_EMPTY_RESET_S)

Read-only replay, 2026-11-14 ~01:35 local (America/Chicago, CST; DST ended 11-01, so "CDT" in the brief is CST). Not committed.
Rule replayed: `PLANNING_crossing_vision.md` P2-D2 step 2 (lines ~207-224), read first. Presence State of Play and
`SENSOR_FLEET_CLASSES.md` consulted (first 300 lines of the State of Play read in full, remainder not read; Tier-1 map taken from code,
`occupancy_substrate.py:88-90,187-274`: `motion_sensors` + `presence_sensors` + `occupancy_sensors` of every room entry).
Scripts: `.claude/tmp/ledgersweep/sweep.py`, `holders.py` (data CSVs alongside; not in repo).

## Answer
No W meets "resurfacing <= ~5% AND >= 10 checkpoints/week" on the literal definition (any interior body or Tier-1 rising edge within R min with no door
entry first). But on the reliable window (recorder, actual Tier-1 states) EVERY resurfacing is a real arrival's precursor (garage motion 0.5-55 min
before a person-home edge / door crossing / egress edge), not someone-in-the-house-all-along. With arrival-precursors excluded, unexplained resurfacing
is 0 at every W in the last 7 d, so the shortest W meeting both bars is 10 min (21 cp/wk). Recommend W = 15 min (900 s): 15 cp/wk (7 d), 12.2/wk (14 d),
4 distinct empty episodes/wk, margin for 90 s sampling; W = 10 is acceptable if more checkpoints are wanted. Separate BLOCKER found below.

## BLOCKER: a phantom Tier-1 entity makes the held rule never pass
`binary_sensor.mmwave_zigbee_gameroom_presence` is in Exercise Room `presence_sensors` (`core.config_entries`) but does not exist in HA
(REST GET `/api/states/...` -> "Entity not found."; no `states_meta` row; the live Exercise sensor is `..._hobeian_exercise_presence_2`, cf. SENSOR_FLEET_CLASSES
rule 2). The plan's rule ("missing ... has no known-good reading since setup" = held) holds it forever. Literal replay with it kept: 0 checkpoints in the last
7 d at every W (14 d: 17/10/7/2/1/0 per W=10/15/20/30/45/60, all from the pre-recorder proxy half). The numbers below DROP it. Config fix (remove the dead entity) or
a "never existed in the registry = ignored" clause is needed before ship.

## Method / data (all read-only)
- Samples: `census_snapshots` zone=house, 15,354 rows 2026-10-31 00:00Z..2026-11-14 07:25Z, one per ~90 s (the plan evaluates every 60 s; gap>300 s resets). Pass: `frigate_count+unifi_count = 0` (proxy for body total, as P2-D0),
  not dark (`sensor.universal_room_automation_persons_in_house` attr `camera_input_dark_fired`, recorder), no held Tier-1, no Tier-1 rising edge, no door entry
  (`person_entry_exit_events.direction='entry'`, 127 rows) since prior sample. Checkpoint: after W continuous passing seconds, restart clock (plan step 2).
- Held / rising edge, actual: 72 Tier-1 entities x recorder `/config/home-assistant_v2.db` (`states`/`states_meta`), level `on` = held; unavailable/unknown/missing holds if last good was on or none; rising edge = non-on -> on.
  **Recorder retention starts 2026-11-06 10:12Z (7.9 d), so actual Tier-1 data covers only that.** Before it (days 8-14 of the 14 d window) the replay.py proxy is used (room `STATE_OCCUPIED` episodes as held, any room `occupancy_events` entry as edge; over-blocks, edge set wider than Tier-1). The "last 7 d" column is fully actual.
- Fail counts (actual region): body 2703, dark 281, held 4531, edge 351, gap 28, pass 426 of 8,320 samples. Zero-body non-dark samples: 4544/5330 (85%) have >=1 held input.
- AWAY from `house_state_log` (2.1 d in window); night = 22:00-06:00 local. Guest: no `GUEST` house state in window, `guest_count` attr is null, `identified_guests_count` = 0 throughout; only `binary_sensor.ura_presence_coordinator_visitors_present` (26 on-intervals 11-10..11-14) is usable: 0 checkpoints fired while it was on.

## Sweep table (last 7 d / 14 d). cp = checkpoints; epi = first checkpoint of an empty episode (rest are repeat fires)
| W | cp 7d (=/wk) | cp 14d (/wk) | epi 7d/14d | AWAY share 7d/14d | night 7d/14d | resurf R30 7d/14d | resurf R60 7d/14d | R60 loose 7d/14d | R60 arrival-precursors excluded: unexplained 7d/14d* | R60 excl. Garage A/B rises 7d |
|---|---|---|---|---|---|---|---|---|---|---|
| 10 | 21 | 38 (18.6) | 5/13 | 100%/74% | 0/3 | 8/24 | 12/29 (57%/76%) | 10/27 | 0/10 | 1 |
| 15 | 15 | 25 (12.2) | 4/11 | 100%/76% | 0/2 | 5/14 | 8/18 (53%/72%) | 7/17 | 0/6 | 0 |
| 20 | 9 | 16 (7.8) | 3/9 | 100%/75% | 0/2 | 3/10 | 4/11 (44%/69%) | 4/11 | 0/4 | 0 |
| 30 | 6 | 8 (3.9) | 3/5 | 100%/75% | 0/0 | 2/4 | 3/5 (50%/63%) | 2/4 | 0/2 | 0 |
| 45 | 4 | 5 (2.5) | 2/3 | 100%/80% | 0/0 | 2/3 | 3/4 (75%/80%) | 2/3 | 0/1 | 0 |
| 60 | 2 | 2 (1.0) | 1/1 | 100%/100% | 0/0 | 1/1 | 1/1 | 1/1 | 0/0 | 0 |
Night resurfacing (14 d, proxy half): W10 3 of 3 night checkpoints, W15 2 of 2, W20 2 of 2; none at W>=30. 7 d: no night checkpoint at any W. "loose" = an egress-camera person on-edge also counts as an entry crossing (`eg.csv`, 515 edges, 7.9 d only); it barely changes anything.
*Unexplained = resurfacing event with NO arrival evidence (door entry, egress person edge, `person.*` non-home->home edge, house state `arriving`) in the 60 min after it. The 14 d figure is an upper bound: its first half has no person/egress evidence and uses the all-rooms proxy (unexplained there: Living Room entries, camera body>0, Garage B).

## What resurfaced (7 d, actual Tier-1, W=10 R=60: 12 events)
11 = `binary_sensor.occupancy_lux_temp_humidity_garagea_presence` (Garage A, filed `motion_sensors`, motion-class), 1 = Garage B `ratgdov25i_dbfe2a_motion`. Each was followed by a real arrival: person edge +8..54 min, door crossing +1.6..29 min, egress edge +0.5..28 min (11-08 09:51..13:45 sequence = one empty episode, repeated checkpoints, one arrival 13:45; 11-09 17:30 Garage B then person home +8 min). Garage motion leads the door crossing: the garage is the arrival side-door, a vehicle/door precursor, not a hidden resident. Other Tier-1 rooms resurfaced 0 times in 7 d (one Master Bedroom radar edge at W=10 when Garage excluded). In the proxy half the repeat offenders are Living Room, Garage A/B, Study B room entries and camera body>0 (3), unverified as arrivals (no person data).
Blind-spot read: no Tier-1 room produced a "someone was in all along" resurfacing in 7 d; the motion-class-only concern (ZV rooms) would show as rising edges after a checkpoint with no arrival, and none occurred. Absence over 7 d and ~21 checkpoints (4-5 episodes) is thin evidence, not proof.

## Why checkpoints are scarce (held rule), 5,330 zero-body non-dark samples
Held share: Master Bedroom bed `..bed_occupied_right_slow` 50%; Jaya Bedroom mmwave 33%; **Upstairs Hallway panel `binary_sensor.up_hallway_panel_person_occupancy` 31%, 287 samples during AWAY** (a camera-panel person sensor reading on while away: frozen-panel shape, the S1/S2 case, which also blocks the anchor); Master Bedroom radars 22%/18%/10%; Jaya `jaya_3` 9.5%; Ziri 9%. Bed/radar holds are real sleepers, so night checkpoints are structurally absent (0 in 7 d). All 7-d checkpoints are in AWAY (100%), where "zero guests" is independently true.

## Caveats
1. Sampling ~90 s vs 60 s planned; a body or pulse between samples is missed (the substrate rising-edge subscription covers pulses in the real build, not here: rising edges here come from recorder state changes, which do capture pulses; bodies between census ticks are not captured).
2. Body proxy `frigate_count+unifi_count` of the `house` zone; interior-only membership unverified; blind camera rooms are invisible to it by construction.
3. Actual Tier-1 history is 7.9 d only; the 14 d column is hybrid and over-blocks/over-resurfaces in its first half. Recorder retention bounded this, not a choice.
4. Initial states at recorder start taken as the opposite of each entity's first row; first 2 h skipped. "Dead" hold uses unavailable/unknown rows; no live dead-stream signal (S2 not built).
5. Counts are small (7 d: 2-21 checkpoints, 1-5 episodes); repeat checkpoints inside one empty period inflate cp/week and flatter resurfacing rates. The >=10/week bar is met only by repeat fires (W=10: 21 cp from 5 episodes; W=15: 15 from 4).
6. Guest-present test is weak (visitors_present only; no guest count attribute populated).
7. Resurfacing proxy counts a house that was truly empty and then re-entered via an undetected door (blind crossing) as a false checkpoint unless later evidence exists; the "explained" column is the discriminating version. A falsifier for "checkpoint fine": a rising edge/body after a checkpoint with no arrival evidence within 60 min; found 0 times in the actual window.
