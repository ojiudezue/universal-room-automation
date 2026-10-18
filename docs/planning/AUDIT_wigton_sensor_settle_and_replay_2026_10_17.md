# Wigton sensor settle + "would-have" replay (read-only) - 2026-10-17

Generated 2026-10-17 21:16 CDT by ura-prober. Nothing was enabled, changed or restarted on Wigton. (One transient helper script was written to the SSH add-on's /tmp and removed again; no HA state touched.)

## Answer first

- **G4 (fleet tuned): FAIL, 12 of 17 units pass.** Failing: Chinenye (anti-interference OFF), Gym (static 10, anti-int OFF), Living Room (anti-int OFF), Master Bath (fading 60 not 120, anti-int OFF), Master Bedroom (motion 8). Three of these were changed after the 10-10 tuning (Gym 10-14 08:53, Master Bath 10-14 12:56, Master Bedroom 10-12 17:06) - looks like deliberate manual retuning, not drift; the runbook targets just don't match them any more.
- **G5 (flicker down): PASS on the substantive measures, borderline on the median wording.** Settled days 10-11..10-16 have a fleet median of 37.5 transitions/unit/day vs 84.2 for the pre-tune window (ratio 0.45, target <= 0.5). Counting the whole post-tune window including the noisy afternoon of 10-10 gives 45.6 vs 84.2 = 0.54 (just misses). Against the 10-10-morning-only window (167/day) it is 0.2. No unit exceeds 5 sub-5 s flaps/day (target 20). No unit is on > 5.2 h continuously (target 12 h).
- **Would-have replay:** 12 of 17 rooms behave well, flicker is gone everywhere after tuning (off->on pairs < 10 s over 10-11..10-17 total only 8: Grandma 4, Master Bath 2, Living Room 1, Master Bedroom 1). The real risk is **phantom occupancy from the three Ecobee `*_occupancy` binary sensors** (Study Hallway, Game Room, Down Guest Bedroom Hallway) which sit "on" for up to 24 h, and moderate overnight on-time in Study / Grandma / Kelechi (needs household ground truth).
- **Important config fact:** every room has `entry_light_action = "none"` and `exit_light_action = "turn_off"`. Real URA would issue **zero light-on actions** on entry; "light-on" counts below are what it would do if entry-on were enabled. Only exit-off actions would be real.

## How I accessed Wigton

- `ssh wigton` (alias in ~/.ssh/config: 192.168.17.243, user wigtonhaos, key ~/.ssh/ha_okosisi). Reachable now (`date` returned 2026-10-17 21:15 CDT).
- Recorder read directly: `sqlite3/python sqlite3` opened `file:/config/home-assistant_v2.db?mode=ro` (states + states_meta). No HA token was needed or used. `.storage/core.config_entries`, `core.entity_registry` copied by `cat`.
- Recorder span: 2026-10-07 04:12 CDT to now, so 3.4 pre-tune days + 7.3 post-tune days.
- **Not found:** the original 2026-10-10 fleet audit script and its baseline numbers (searched repo docs, KANBAN, worklog, .claude/scratch, /tmp on Wigton - only /tmp/remote_tune.py, the tuning script, exists). I rebuilt the metrics from the recorder; the baseline below is **recomputed by me**, not the quoted 10-10 figure. Definitions: transition = on<->off change (unknown/unavailable ignored); sub-5 s flap = two consecutive transitions < 5 s apart; longest-on = longest continuous `on` stretch.
- Tuning time: the number entities were last set 2026-10-10 13:32-13:33 CDT (nums_hist). Post-tune window = 10-10 13:35 to 10-17 21:16.

## G4 - live number.* values (recorder last value; all 17 room-bound units)

Targets (RUNBOOK_wigton_ura_reenable.md:18): motion <= 6, static <= 6, fading = 120 s, distance <= 4 m except Master Bedroom + Living Room, anti_interference ON. Source: `number.<unit>_{motion_detection_sensitivity,static_detection_sensitivity,fading_time,detection_distance}` and `switch.<unit>_anti_interference` last recorded state (all numerics, none unavailable; last-change times in nums_hist, latest 10-14 12:56).

| unit | room | motion | static | fading | dist | anti-int | G4 |
|---|---|---|---|---|---|---|---|
| 0xa4c138422c672df2 | Down Guest Bedroom | 6 | 6 | 120 | 3.5 | on | PASS |
| 0xa4c138500115ac92 | Up Guest Bedroom | 5 | 6 | 120 | 4 | on | PASS |
| 0xa4c1386323f3a289 | Kelechi room | 5 | 6 | 120 | 4 | on | PASS |
| 0xa4c138a55ceaf91b | Chinenye Room | 5 | 6 | 120 | 4 | off | **FAIL**: anti-int OFF |
| 0xa4c138e339839ae6 | Grandma Room | 5 | 6 | 120 | 4 | on | PASS |
| mmwave_..._fdining | Formal Dining | 5 | 6 | 120 | 4 | on | PASS |
| mmwave_..._gameroom | Game room | 5 | 6 | 120 | 4 | on | PASS |
| mmwave_..._gym | Gym | 5 | 10 | 120 | 4 | off | **FAIL**: static>6, anti-int OFF |
| mmwave_..._kitchen | Kitchen | 5 | 6 | 120 | 4 | on | PASS |
| mmwave_..._laundry | Laundry | 5 | 6 | 120 | 4 | on | PASS |
| mmwave_..._livingroom | Living Room | 6 | 6 | 120 | 5 (exempt) | off | **FAIL**: anti-int OFF |
| mmwave_..._masterbath | Master Bathroom | 5 | 5 | 60 | 3 | off | **FAIL**: fading!=120, anti-int OFF |
| mmwave_..._masterbathshower | Master Bathroom (shower) | 5 | 6 | 120 | 4 | on | PASS |
| mmwave_..._masterbedroom | Master Bedroom | 8 | 6 | 120 | 5 (exempt) | on | **FAIL**: motion>6 |
| mmwave_..._mediaroom | Media Room | 5 | 6 | 120 | 4 | on | PASS |
| mmwave_..._receivingroom | Receiving Room | 5 | 6 | 120 | 4 | on | PASS |
| mmwave_..._study | Study | 5 | 6 | 120 | 4 | on | PASS |

Not in the 17 (not bound to any URA room, all fail the targets, informational only): `0xa4c1381877a8b9d2` (motion 5, static 8, fading 60, dist 5), `0xa4c1381baa464a8c` (same), `0xa4c138c23b3f9433` (motion 10, static 10, fading **26322**, dist 5 - garbage fading value, possibly a different device type; unknown).

## G5 - flicker audit

Per unit: transitions/day, sub-5 s flaps/day, longest continuous on (h). Baseline = 10-07 04:15 to 10-10 13:30 (3.4 d, recomputed). Post = 10-10 13:35 to 10-17 21:16 (7.3 d).

| unit (presence) | base tr/d | base flaps/d | base max-on h | post tr/d | post flaps/d | post max-on h |
|---|---|---|---|---|---|---|
| 0xa4c138422c672df2_presence | 320 | 158.6 | 2.8 | 46 | 1.5 | 1.4 |
| 0xa4c138500115ac92_presence | 128 | 1.2 | 1.8 | 31 | 0.0 | 0.4 |
| 0xa4c1386323f3a289_presence | 19 | 0.3 | 4.6 | 49 | 0.8 | 2.2 |
| 0xa4c138a55ceaf91b_presence | 170 | 2.1 | 0.7 | 61 | 0.4 | 0.3 |
| 0xa4c138e339839ae6_presence | 103 | 1.5 | 1.1 | 162 | 3.7 | 2.9 |
| fdining_presence | 78 | 0.3 | 1.5 | 30 | 0.0 | 1.2 |
| gameroom_presence | 185 | 18.9 | 1.6 | 32 | 1.1 | 0.8 |
| gym_presence | 84 | 0.3 | 1.2 | 51 | 0.4 | 3.1 |
| kitchen_presence | 132 | 1.8 | 1.3 | 60 | 0.1 | 1.7 |
| laundry_presence | 70 | 0.0 | 0.6 | 17 | 0.0 | 0.3 |
| livingroom_presence | 133 | 1.5 | 1.2 | 73 | 0.7 | 1.1 |
| masterbath_presence | 43 | 0.6 | 17.7 | 60 | 1.4 | 0.4 |
| masterbathshower_presence | 62 | 0.3 | 1.0 | 21 | 0.0 | 0.5 |
| masterbedroom_presence | 123 | 1.2 | 1.7 | 136 | 4.9 | 4.7 |
| mediaroom_presence | 12 | 0.0 | 0.0 | 1 | 0.0 | 0.1 |
| receivingroom_presence | 5 | 0.0 | 0.0 | 0 | 0.0 | 0.0 |
| study_presence | 56 | 0.0 | 2.2 | 31 | 0.0 | 5.2 |

Fleet median transitions/day: **84.2 pre -> 45.6 post (0.54)**; settled days only (10-11..10-16): 37.5 (0.45); 10-14..now: 32.9 (0.39); vs the pre-tune morning of 10-10 alone (167/day): 0.2 to 0.27. Max sub-5 s flaps/day post-tune: 4.9 (Master Bedroom). Max longest-on post-tune: 5.2 h (Study). The two big pre-tune offenders were Down Guest Bedroom (320 tr/d, 159 flaps/d) and Game Room (185 tr/d, 19 flaps/d); both are now 46 and 32 tr/d, 1.5 and 1.1 flaps/d. Master Bath had an 17.7 h stuck-on pre-tune; now 0.4 h.

Regressions to watch: Grandma Room (103 -> 162 tr/d), Master Bedroom (123 -> 136 tr/d; flaps 1.2 -> 4.9/d, motion sensitivity raised to 8 on 10-12 17:06 - plausible cause, unproven), Kelechi (19 -> 49).

### Trend by day (all 17 units; fleet median raw transitions per unit, total sub-5 s flaps, worst longest-on)

| day | median tr/unit | fleet flaps<5s | worst longest-on h |
|---|---|---|---|
| 10-07 (partial from 04:15) | 54 | 148 | 2.4 |
| 10-08  | 61 | 247 | 10.6 |
| 10-09  | 67 | 186 | 17.7 |
| 10-10 (tuned 13:33 (mixed)) | 121 | 63 | 4.4 |
| 10-11  | 34 | 19 | 2.2 |
| 10-12  | 38 | 10 | 1.8 |
| 10-13  | 36 | 15 | 4.3 |
| 10-14  | 24 | 21 | 3.1 |
| 10-15  | 26 | 14 | 1.9 |
| 10-16  | 30 | 15 | 3.5 |
| 10-17 (partial to 21:16) | 22 | 10 | 2.9 |

Settled: flaps fell from 63-247/day fleet-wide to 10-21/day on 10-11 and stayed there; median transitions fell 54-121 -> 22-38.

## Would-have replay

**Model (simplified):** room occupied = union of every configured `occupancy_sensors` + `motion_sensors` entity being `on` (unavailable/unknown treated as not-on); vacant once all are off for the room's `occupancy_timeout` (read from the entry options, listed below). Enter edge = hypothetical light-on, vacate edge = light-off. Source: `.storage/core.config_entries` (disabled entries still hold config; the 17 rooms; "House" room excluded). **Ignored:** presence/BLE/camera/census fusion, house state and sleep mode, lux/darkness gating, manual-on-hold (3600 s) and manual-off-cooldown (900 s) from light_manual_*, away mode, the real timeout logic (`coordinator.py` has extra mmWave/BLE/PIR staleness multipliers, e.g. coordinator.py:4091, 4317), actuator state and the fact that people hand-operate lights, and the zone/house gating. Treat counts as an upper-bound of sensor-driven edges, not a prediction of lamp behaviour. Also: `entry_light_action="none"` in every room (read from the entries), so real entry-on is a no-op; I report enter edges anyway because the brief asked.

Configured timeouts (s) and sources:

| room | timeout | sources | lights configured |
|---|---|---|---|
| Chinenye Room | 300 | 0xa4c138a55ceaf91b_presence | 1 |
| Down Guest Bedroom | 900 | 0xa4c138422c672df2_presence | 1 |
| Down Guest bedroom hallway | 900 | master_closet_ecobee_downstairs_occupancy, master_closet_ecobee_downstairs_motion | 0 |
| Formal Dining | 900 | mmwave_lux_temp_humidity_zigbee_fdining_presence | 0 |
| Game room | 300 | game_room_ecobee_upstairs_occupancy, mmwave_lux_temp_humidity_zigbee_gameroom_presence, game_room_ecobee_upstairs_motion | 1 |
| Grandma Room | 300 | 0xa4c138e339839ae6_presence | 1 |
| Gym | 300 | mmwave_lux_temp_humidity_zigbee_gym_presence | 1 |
| Kelechi room | 300 | 0xa4c1386323f3a289_presence | 1 |
| Kitchen | 900 | mmwave_lux_temp_humidity_zigbee_kitchen_presence | 2 |
| Laundry | 600 | mmwave_lux_temp_humidity_zigbee_laundry_presence | 1 |
| Living Room | 900 | mmwave_lux_temp_humidity_zigbee_livingroom_presence | 0 |
| Master Bathroom | 300 | mmwave_lux_temp_humidity_zigbee_masterbath_presence, mmwave_lux_temp_humidity_zigbee_masterbathshower_presence | 0 |
| Master Bedroom | 900 | mmwave_lux_temp_humidity_zigbee_masterbedroom_presence | 1 |
| Media Room | 1800 | mmwave_lux_temp_humidity_zigbee_mediaroom_presence | 1 |
| Receiving Room | 300 | mmwave_lux_temp_humidity_zigbee_receivingroom_presence | 0 |
| Study | 300 | mmwave_lux_temp_zigbee_study_presence | 0 |
| Study Hallway | 120 | study_hallway_ecobee_master_suite_occupancy, study_hallway_ecobee_master_suite_motion | 0 |
| Up Guest Bedroom | 900 | 0xa4c138500115ac92_presence | 1 |

Per-day table, columns `on/off/pairs<10s/longest-occupied-h/overnight-min(00-06)`. 10-07..10-09 and the morning of 10-10 are pre-tune (sensors still noisy); 10-11..10-17 are post-tune. The G9 off->on pair (vacate then re-enter < 10 s) cannot occur with timeouts >= 120 s unless a re-trigger lands right after the timeout; the nonzero pre-tune values are exactly that.

| room | 10-07 | 10-08 | 10-09 | 10-10 | 10-11 | 10-12 | 10-13 | 10-14 | 10-15 | 10-16 | 10-17 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Chinenye Room | 20/20/0/1.2/34 | 29/28/0/1.0/59 | 41/41/3/1.2/72 | 65/65/30/0.9/355 | 23/24/0/0.7/30 | 15/15/0/0.4/0 | 17/16/0/0.7/40 | 18/18/0/0.5/16 | 15/16/0/0.3/29 | 17/17/0/0.4/25 | 21/21/0/0.6/7 |
| Down Guest Bedroom | 1/0/0/19.8/108 | 0/0/0/24.0/360 | 0/0/0/24.0/360 | 2/3/0/9.4/360 | 4/4/0/1.4/0 | 4/4/0/2.2/13 | 9/9/0/1.8/0 | 3/3/0/1.4/0 | 1/1/0/4.1/197 | 3/3/0/3.8/215 | 2/2/0/2.9/0 |
| Down Guest bedroom hallway | 5/5/0/4.2/0 | 3/3/0/5.9/0 | 7/6/0/7.8/8 | 8/9/0/2.6/98 | 3/2/0/9.8/229 | 10/10/0/5.5/325 | 7/8/0/3.2/63 | 3/2/0/11.1/0 | 4/5/0/8.7/360 | 5/5/0/5.5/0 | 3/3/0/5.1/0 |
| Formal Dining | 10/10/0/0.8/37 | 9/9/0/1.7/0 | 14/13/1/2.5/6 | 30/31/16/1.3/358 | 9/9/0/0.6/0 | 9/9/0/0.7/0 | 8/8/0/0.9/0 | 8/8/0/0.7/0 | 9/9/0/0.5/0 | 5/5/0/2.1/0 | 10/10/0/0.7/0 |
| Game room | 22/21/0/0.9/10 | 32/33/4/2.2/280 | 17/16/1/6.3/314 | 18/19/3/1.5/321 | 7/6/0/4.0/80 | 5/5/0/6.9/131 | 15/15/0/2.3/171 | 8/8/0/16.2/103 | 4/5/0/7.9/360 | 6/6/0/4.1/85 | 7/6/0/4.4/25 |
| Grandma Room | 8/8/0/2.4/0 | 8/8/0/0.8/61 | 12/11/1/1.3/0 | 31/32/14/1.3/358 | 24/24/0/2.9/117 | 24/23/0/2.7/153 | 27/27/2/3.4/211 | 31/32/0/3.8/274 | 25/24/0/3.3/203 | 26/26/1/2.4/163 | 25/26/1/4.3/224 |
| Gym | 15/15/0/1.3/0 | 16/16/0/0.3/0 | 26/25/3/1.1/0 | 77/78/52/1.1/355 | 5/5/0/1.5/0 | 11/11/0/4.4/0 | 9/9/0/0.8/0 | 21/21/0/3.4/161 | 7/7/0/2.0/0 | 14/14/0/1.5/0 | 7/7/0/1.6/0 |
| Kelechi room | 1/1/0/0.2/0 | 1/1/0/0.2/12 | 9/8/0/0.4/0 | 25/25/0/11.8/360 | 23/24/0/4.5/322 | 23/23/0/1.4/79 | 14/14/0/2.0/229 | 1/1/0/0.1/0 | 0/0/0/0.0/0 | 7/7/0/0.3/0 | 1/1/0/0.1/0 |
| Kitchen | 15/15/0/1.0/0 | 13/13/0/2.5/16 | 14/13/0/3.5/10 | 20/21/7/3.2/358 | 7/7/0/1.9/18 | 13/13/0/2.2/49 | 13/13/0/1.7/39 | 8/8/0/1.9/0 | 11/11/0/2.0/0 | 10/10/0/2.9/0 | 7/7/0/4.3/0 |
| Laundry | 9/9/0/1.4/0 | 10/10/0/0.4/0 | 15/14/0/0.7/8 | 19/20/5/4.9/359 | 6/6/0/0.2/0 | 11/11/0/0.5/39 | 3/3/0/0.3/0 | 7/7/0/0.5/0 | 6/6/0/0.7/25 | 6/6/0/0.9/0 | 7/7/0/0.2/0 |
| Living Room | 18/18/1/1.0/31 | 13/13/0/4.0/21 | 17/16/0/1.8/26 | 19/20/8/6.7/358 | 8/8/0/1.9/17 | 13/13/0/2.2/42 | 16/16/0/2.0/35 | 13/13/0/1.1/0 | 12/12/0/0.8/0 | 12/12/0/1.7/0 | 9/9/1/2.5/0 |
| Master Bathroom | 9/9/1/0.5/8 | 1/0/0/19.2/73 | 1/1/1/24.0/360 | 55/56/28/1.1/354 | 12/12/0/0.4/0 | 12/12/0/0.5/0 | 7/7/0/0.4/9 | 10/10/0/0.7/13 | 8/8/0/1.1/0 | 26/26/0/1.4/123 | 10/10/2/0.5/30 |
| Master Bedroom | 11/10/0/1.9/99 | 8/8/0/6.4/317 | 12/12/1/2.0/250 | 13/14/1/3.4/359 | 14/14/0/3.6/225 | 8/7/0/3.9/0 | 13/13/1/4.6/354 | 10/11/0/3.6/312 | 7/6/0/5.0/17 | 8/8/0/7.0/360 | 8/9/0/3.1/324 |
| Media Room | 0/0/0/0.0/0 | 0/0/0/0.0/0 | 2/1/0/0.7/0 | 2/3/0/8.8/360 | 1/1/0/0.6/0 | 2/2/0/0.6/34 | 1/1/0/0.5/0 | 0/0/0/0.0/0 | 0/0/0/0.0/0 | 0/0/0/0.0/0 | 0/0/0/0.0/0 |
| Receiving Room | 1/1/0/0.1/0 | 1/1/0/0.1/0 | 3/3/0/0.3/0 | 2/2/0/0.1/0 | 0/0/0/0.0/0 | 0/0/0/0.0/0 | 0/0/0/0.0/0 | 0/0/0/0.0/0 | 0/0/0/0.0/0 | 0/0/0/0.0/0 | 1/1/0/0.1/0 |
| Study | 8/8/0/0.9/51 | 18/17/0/0.5/13 | 16/16/0/1.4/167 | 19/19/6/5.1/360 | 15/16/0/3.1/278 | 23/22/0/1.6/40 | 13/13/0/4.4/300 | 10/11/0/2.0/299 | 3/3/0/0.8/53 | 8/8/0/1.0/111 | 5/5/0/0.2/0 |
| Study Hallway | 3/3/0/1.0/0 | 5/5/0/2.7/39 | 8/7/0/2.0/10 | 7/8/0/2.2/91 | 5/5/0/8.3/313 | 5/5/0/1.4/0 | 6/5/0/3.6/0 | 4/5/0/9.1/360 | 6/6/0/1.2/0 | 4/3/0/5.6/0 | 5/6/0/8.0/360 |
| Up Guest Bedroom | 14/14/0/2.9/91 | 15/15/0/2.8/277 | 16/15/0/3.0/249 | 30/30/7/1.0/354 | 10/11/0/1.0/27 | 12/12/0/0.6/68 | 8/8/0/0.8/0 | 6/6/0/0.6/0 | 5/5/0/0.6/0 | 8/8/0/0.6/0 | 12/12/0/1.0/0 |

## Verdicts (post-tune days 10-11..10-17 drive the call)

Overnight-attribution for 10-11..10-17 (sensor: on-hours, overnight minutes, longest-on) from the same recorder pull:
Study mmWave 44.3 h / 986 min / 5.2 h; Study Hallway Ecobee occupancy 66.7 h / 1033 min / **12.6 h** (Ecobee motion 10.7 h / 5 min); Game Room Ecobee occupancy 59.0 h / 584 min / **24.0 h** (mmWave 14.5 h / 254 min); Down Guest Hallway Ecobee occupancy 89.8 h / 932 min / **19.6 h** (motion 18.2 h / 42 min); Master Bedroom 45.5 h / 872 min / 4.7 h; Grandma 76.0 h / 820 min / 2.9 h; Kelechi 19.9 h / 548 min / 2.2 h.

| room | verdict | driver / note |
|---|---|---|
| Chinenye Room | well-behaved | 15-23 cycles/day, <= 0.7 h stretches, 0 short pairs. anti-int OFF (G4) but flaps ~0 |
| Down Guest Bedroom | well-behaved (watch) | was the worst flapper (159 flaps/d), now 0-1; 1-3 h stretches. Overnight 197-215 min on 10-15/16 is probably real occupancy; needs ground truth |
| Down Guest Hallway | **phantom risk** | Ecobee `master_closet_ecobee_downstairs_occupancy` stays on up to 19.6 h; 360 overnight min on 10-15; motion sensor itself is fine (42 overnight min) |
| Formal Dining | well-behaved | 5-10 cycles/day, 0 overnight |
| Game room | **phantom risk** | Ecobee `game_room_ecobee_upstairs_occupancy` on up to 24.0 h; occupied 16.2 h on 10-14 and 360 overnight min on 10-15. mmWave itself is clean (1.1 flaps/d) |
| Grandma Room | flicker risk (mild) | highest post-tune rate (162 tr/d, 3.7 flaps/d, 24-31 cycles/day, pairs <10 s: 2 on 10-13, 1 on 10-16, 1 on 10-17). anti-int on. Overnight 117-274 min likely real sleep |
| Gym | well-behaved | static 10 and anti-int OFF but flaps 0.4/d, 3.4 h max; one 161-min overnight on 10-14 (the day static was changed to 10) |
| Kelechi room | well-behaved | low, bursty; 322 overnight min on 10-11 only. Little use |
| Kitchen | well-behaved | |
| Laundry | well-behaved | |
| Living Room | well-behaved | anti-int OFF but 0.7 flaps/d; 17-42 overnight min 10-11..13 only |
| Master Bathroom | well-behaved now | pre-tune 17.7-24 h stuck-on (10-08/09), now <= 1.4 h. fading 60 / dist 3 retune looks fine. 26 cycles on 10-16 worth a glance |
| Master Bedroom | flicker risk (mild) | 4.9 flaps/d (fleet worst), motion 8 since 10-12; long stretches 3-7 h and 225-360 overnight min nightly are plausibly true sleep but a still sleeper is the case mmWave motion-class units miss, so the vacate risk is the *opposite* (lights off on a sleeper) - model cannot judge |
| Media Room | well-behaved / unobservable | 0-2 events/day; sensor produced 1 event after 10-13 08:37 (56 recorder rows total) - effectively silent, may be offline or unused. Unknown |
| Receiving Room | well-behaved / unobservable | 0-1 events/day (26 rows total); silent. Unknown if sensor is healthy |
| Study | phantom risk (needs ground truth) | mmWave on 278-300 overnight min on 10-11, 10-13, 10-14, 5.2 h longest; sole sensor, so no cross-check. Could be a person working late |
| Study Hallway | **phantom risk** | Ecobee occupancy on up to 12.6 h; 313/360/360 overnight min on 10-11/14/17; timeout only 120 s so it follows the sensor directly |
| Up Guest Bedroom | well-behaved | flaps 0, 5-12 cycles/day |

Recommendations are outside the brief (read-only), but the evidence points to: (1) decide whether the three Ecobee `occupancy` binary sensors should be in `occupancy_sensors` at all - they are the whole phantom story (the Ecobee `motion` sensors track real movement); how Ecobee produces its occupancy flag is not verified here; (2) record the intentional G4 drift (Gym static 10, Master Bath fading 60, Master Bedroom motion 8, anti-int OFF on four units) in the runbook or revert it; (3) G5 as worded passes on all absolute criteria and on settled-day median.

## What I could not verify
- Original 10-10 baseline figures (script not found; recomputed instead).
- Whether overnight occupancy is real people (no ground truth); the bedrooms in particular.
- Real behaviour of URA on these rooms (model is simplified, see above).
- Why the 3 extra Zigbee units are off-target or what device `0xa4c138c23b3f9433` is.
