# AUDIT: Occupancy-anomaly sensor, would-be alert rate and fire quality (2026-10-20 22:30 CDT)

Card: BAYES-OCCUPANCY-ANOMALY-NEVER-EVALUATES-1. Read-only measure-before-build probe. Read in full first: `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`, `SENSOR_FLEET_CLASSES.md`.

## Answer
If the sensor were wired, it would fire constantly and most fires would be false. Recommendation: **do not wire it. Take option A (retire it).** If B is kept, do not ship the 10% threshold on this model.

- Replay over the last 14 days with the live persisted model: **~14 alerts/day across the 9 rooms where the entity is enabled** (202 per 14 d, 30-min cooldown applied). With all 46 rooms enabled it is ~42/day (590 per 14 d).
- A 15-min debounce still leaves 5.6/day (78 per 14 d); a 30-min debounce leaves 2.6/day (37 per 14 d).
- Enabled rooms with zero fires: Master Bathroom, Guest Bedroom 2 Bathroom. Their model cells sit at 0.12-0.35, above the 0.10 threshold.
- **Root cause is the model, not the wiring.** The model measures where people ARRIVE, not where they DWELL. This holds even against the data it trained on (section 3).

## 1. Producer (what the model is)
- `BayesianPredictor` is a per-person Dirichlet-Multinomial over `to_room` of **room transitions** (`bayesian_predictor.py:233-330`). Source table: `room_transitions` (90 days), plus online `update()` per transition (`:333-405`). The persisted copy is `bayesian_beliefs(person_id,time_bin,day_type,room_id,alpha,observation_count)`.
- `predict_room_occupancy` (`:466-504`) = 1 - prod over persons (1 - alpha_room/alpha_total). Persons with no alpha for the room are skipped. A room with no data for any person returns None and can never fire.
- Cells: 6 time bins x weekday/weekend, per person. `get_anomaly_score` (`:832-880`) uses threshold 0.10 hard-coded (`:866`) and "ACTIVE" = max `observation_count` over persons >= 50.
- **ACTIVE is vacuous.** Live `observation_count` per cell is 600-9700 for all 72 person cells (queried 2026-10-20, `bayesian_beliefs`). Every cell passes ACTIVE, so that gate filters nothing.
- **Key check: no mismatch.** Sensor passes `entry.data["room_name"]` (`binary_sensor.py:3401-3409`). The model's `room_id` is the `to_room` string, which is also the display `room_name` (belief room_ids include "Study A", "Living Room", "Ziri Bedroom (Bedroom 5)"). The same key is used by `__init__.py:3249-3251` and the forecast sensors. Not the cause.
- Rooms that can NEVER fire for lack of belief rows: Kitchen Pantry, Master Hallway, Staircase, Master Closet Storage, Guest Bedroom 1 Closet, Exercise Room, and "Guest Bedroom 2" (the Upstairs Guest Bedroom, whose enabled anomaly entity is `binary_sensor.upstairs_guestroom_occupancy_anomaly`). The Exercise Room has only "Exercise Room Closet" beliefs. (Guest Bedroom 2's occupied entity was also not mapped in my replay.)

## 2. Consumers
- `SIGNAL_OCCUPANCY_ANOMALY` (`signals.py:40`): **zero consumers**. Greps of `custom_components` and `quality/tests` find only the dispatch (`binary_sensor.py:3449`) and two test assertions (a constant-value check and a source check in the v4.6.1 canary test). Nothing listens.
- Real consumers are the NM alert (`async_notify`, HIGH at 22-06, else MEDIUM; the call signature was fixed on `fix/nm-notify-signature-mismatch`) and the `anomaly_log` row `bayesian.prediction_anomaly` (0 ever written, per the card).
- Evaluation: `async_update` on a non-polling CoordinatorEntity (`binary_sensor.py:3396`). The 9 enabled entities sit at `off` (20 recorder rows each).
- Intent (README_v4.0.2 line 15-16; PLANNING_v4.0.0_B2 D5; checklist test step): "walk into a room that is typically empty at night after midnight and the anomaly fires". It is an intruder / unusual-activity alarm. It was never live-validated: the checklist step is a manual walk-in, and no row was ever produced.

## 3. Replay method and results
- **Method.** Occupied episodes come from the recorder (`/config/home-assistant_v2.db`, `binary_sensor.<room>_occupied`, 2026-10-06 22:3x to 2026-10-20 22:16 CDT). Each episode is stepped every 5 min. Anomaly is true when `predict_room_occupancy(room, bin(now), daytype(now)) < 0.10`. A fire is a rising edge, and the 30-min per-entity cooldown from `binary_sensor.py:3437-3445` is applied (the 5-min startup grace is ignored).
- **Model used.** The CURRENT `bayesian_beliefs` (saved 2026-10-20 21:46 CDT). This is a hindsight replay, not the exact historical model. The per-cell values change slowly (thousands of observations), so the conclusion is robust.
- **Merging.** Episodes separated by gaps up to 5 min are merged (recorder `unavailable` blips split episodes). Local time is CDT (UTC-5) for all 14 days.
- **Scripts.** `replay.py` and `an2.py` in the session scratchpad (not committed).

Fires per 14 days for the 9 enabled rooms, by debounce (minutes the anomaly must persist before alerting):

| room | no debounce | 5 min | 15 min | 30 min |
|---|---|---|---|---|
| Living Room | 77 | 77 | 45 | 20 |
| Kitchen | 54 | 54 | 12 | 3 |
| Garage A | 39 | 39 | 5 | 1 |
| Study A | 29 | 24 | 16 | 13 |
| Ziri Bedroom (Bedroom 5) | 2 | 2 | 0 | 0 |
| Dining Room | 1 | 1 | 0 | 0 |
| Master Bathroom | 0 | 0 | 0 | 0 |
| Guest Bedroom 2 Bathroom | 0 | 0 | 0 | 0 |
| **Total (14 d)** | **202** | **197** | **78** | **37** |
| **Per day** | 14.4 | 14.1 | 5.6 | 2.6 |

- The rooms with no enabled entity add more: Kitchen Hallway (52), Garage B (71), Garage Hallway (55), Jaya Bedroom (47) and others. All-room totals are 590 / 581 / 192 / 81 per 14 d.
- The per-cell model values explain it: P(room occupied) is below 0.10 in **every** time cell for Study A (0.00-0.01), Living Room (0.00-0.03), Dining Room (0.00-0.05), Kitchen Hallway and Garage B. Kitchen falls below 0.10 at night, and on weekend mornings (0.09). Garage A is below 0.10 in 11 of 12 cells.
- **The model contradicts the house.** Oji's real 14-day dwell (`person_visits`, closed visits) is Study A 20.0 h in 601 visits, the second-longest room after Master Bedroom at 56 h. But his Study A belief share is only 1.1% (alpha 67 of 6097, weekday midday), while Study A Closet gets 18.6% and Receiving Room 18.8%. Transition counts are dominated by scanner-borrow / flapping neighbours, so a heavily used room is scored "never occupied" (predicted 0.004).
- **Independent ground truth: the model's own accuracy table.** `prediction_results` (type `bayesian_occupancy`, last 14 d): rows with actual occupied = 285, mean predicted 0.144, and **57.2% had predicted < 0.10**. Rows with actual empty = 2699, mean 0.082, 69.4% < 0.10. The model barely separates occupied from empty, so "occupied AND < 0.10" is true for more than half of all real occupancy samples.

### Context of the 202 would-be fires (enabled rooms, no debounce)
| attribute | count | note |
|---|---|---|
| house_state = sleep | 80 (40%) | night: 89 of 202 (44%) in 22:00-06:00, so 89 would page HIGH |
| home_day / evening / night | 71 / 14 / 8 | |
| away | 19 | occupied with house AWAY, probably real (or a phantom hold), not exposed by the model |
| arriving / waking | 5 / 1 | |
| guest | 4 (2%) | guest suppression removes almost nothing |
| a resident's closed `person_visits` row overlaps the fire (+-2 min) | 59 | |
| none overlaps | 143 | caveat: `person_visits` is BLE-derived and sparse (only 111 of 1004 Living Room visits fall inside an occupied episode), so "no BLE visit" does not mean "nobody there" |

### Sample of 12 fires (random, seed 7)
In nearly all, a household resident was in the room or house, so these were normal use:
- Living Room, Mon 10-19 10:46, 354 s, p=0.007, home_day (no closed visit in room; Ezinne Master Bedroom, Jaya Jaya Bedroom, Oji Study A, so likely a sensor hold or unlogged person).
- Living Room, Tue 10-13 18:30, 993 s, p=0.019, home_evening, Oji present in room.
- Living Room, Tue 10-20 11:36, 1664 s, p=0.007, home_day, no visit logged.
- Garage A, Tue 10-13 19:30, 888 s, p=0.061, home_evening, Jaya present.
- Study A, Wed 10-14 05:02, 679 s, p=0.004, sleep, Oji present (waking up and starting work).
- Study A, Mon 10-19 23:23, 697 s, p=0.002, sleep, Oji present (Oji's own Study A work).
- Kitchen, Sun 10-18 01:42, 306 s, p=0.035, sleep, no visit logged (Jaya in her bedroom).
- Study A, Tue 10-20 10:44, 453 s, p=0.012, home_day, Oji present.
- Living Room, Tue 10-20 00:46, 348 s, p=0.004, sleep, none logged.
- Kitchen, Mon 10-19 02:08, 888 s, p=0.043, sleep, none logged (the others elsewhere).
- Study A, Mon 10-19 02:13, 216 s, p=0.004, sleep, none logged (Oji at Receiving Room).
- Kitchen, Sat 10-17 05:43, 315 s, p=0.035, sleep, none logged.

Not verified: whether the unlogged night Kitchen / Living Room / Study A episodes were real people, phantom holds (Study A has known ZK stuck-hold residuals, per State of Play 9) or pets. Pets are not modelled anywhere I read. I did not cross-check fan-on state for these samples.

## 4. False-positive sources (all measured or read from code)
1. **Model validity.** Arrivals are not dwell (above). A room's "popularity" share is divided across ~40 rooms, so any room whose share of a person's transitions is below 10% is "anomalous" whenever it is occupied. This is the dominant cause.
2. **Closet / hallway / bathroom transit rooms** inflate neighbour shares and starve real destinations (Study A vs Study A Closet).
3. **Union across persons** (`1 - prod(1-p)`) ignores guests and untracked occupants. Guest suppression keys on house_state == "guest" only (`binary_sensor.py:3417-3424`); only 2% of replay fires were in guest state.
4. **Sensor holds:** phantom mmWave holds (fan, ZK stuck) would genuinely be surfaced here but are indistinguishable from real use.
5. **Night paging:** 44% of fires land at 22:00-06:00 and would page at HIGH.
6. Evaluation timing: even if wired to the coordinator tick, the rising edge re-fires after every `unavailable`/restart blip, because `_is_anomaly` is in-memory only.

## 5. Recommendation
- **Option A: retire the entity and `_fire_anomaly_alert` (KEEP-DOCUMENT or DELETE bucket).** The 10% predicted-occupancy design is the same wrong shape as its model. No consumer exists, the alert never ran, and every fix-up is a rebuild.
- **If B is chosen anyway (the operator said "make it work"), the minimum honest gate is:**
  - The threshold cannot be a tuning knob here. At 0.10 it fires on >50% of true occupancy. To make it fire only rarely (<=1/day across rooms) you would need threshold ~0.01 plus a 30-min debounce, which the numbers above (2.6/day at 0.10) say is still too many and would leave the bulk of the 0.00-0.01 rooms (Study A, Living Room) firing every time.
  - Exclude rooms by model quality, not by name: rooms whose cell max over day/time is below 0.10 (Study A, Living Room, Dining Room, Kitchen Hallway, Garage B, Garage Hallway), and bathrooms / closets / hallways (transit).
  - Restrict to house_state in {away, sleep}, drop sleep for bedrooms and bathrooms, and require debounce >= 15 min.
  - Better producer: rebuild on dwell (`person_visits` duration, or recorder minutes occupied) per room/time bin, with a room-level (not per-person) occupancy frequency. Then "occupied in a cell that is historically empty" is meaningful. Cost: a new producer, so Tier 2-DB plus a measure-before-build gate on the new model. Per the Marginal-Benefit Decomposition rule I would not build it for an alarm with no consumer.
- If the operator keeps A: all 46 anomaly entities and the 20 recorder-writing (`off`) rows each can be dropped, and the `bayesian.prediction_anomaly` type becomes unreachable.

## 6. Caveats
- Replay uses current beliefs and recorder `on` states, with 5-min steps; the real sensor would evaluate on each coordinator update, which gives the same or more rising edges.
- The sensor stays off for episodes under the 5-min startup grace after each HA restart (restarts are rare in the window); not modelled.
- House-state timestamps were assumed naive-UTC (presence doc); `person_visits` naive-local (CDT). I verified the latter by matching visit starts to occupied episodes (offset test), not by schema. The state counts are only context.
- The 14-day window (2026-10-06 to 10-20) may include atypical occupancy (memory notes an operator trip 10-14 to 10-18, not verified against the data); only 4 fires carried guest state.
