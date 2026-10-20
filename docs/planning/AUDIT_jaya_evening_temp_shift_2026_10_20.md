# AUDIT: Jaya Bedroom evening temp shift (probed 2026-10-20 ~11:45 CDT)

Read-only. Read the HVAC state-of-play Jaya/zone sections (9.3, C19, C27), not the whole doc.

## 1. Room memory (room:jaya_bedroom), read from URA DB tables memory_facts / memory_episodes (service not callable from here)
- memory_facts: zero facts for room:jaya_bedroom (and no zone/HVAC node facts). Nothing on temperature or comfort complaints.
- memory_episodes (room:jaya_bedroom): comfort_fan_vetoed 99 (2026-08-21..09-25), fan_transition_suppressed 11 (to 10-10), phantom_retro 4 (10-12 17:38, 10-13 06:50, 10-16 07:22, 10-20 07:14 CDT; all "fan_release_correlated", no PIR/BLE/camera). No temperature or HVAC episodes. Memory does not describe a temperature trend or the fix.

## 2. Candidate "Jaya HVAC fixes" (unclear which one the operator means)
| When (CDT) | What | Source |
|---|---|---|
| 2026-09-26 18:21Z | Jaya hvac_vacancy_hold_night 1800 -> 5400 s (config) | kanban.data.yaml:2943 |
| 2026-10-18 21:54 | v5.103.73 fan recheck by day in bedrooms (JAYA-FAN-STILL-PHANTOM-1) | README_v5.103.73 |
| 2026-10-19 04:06 | v5.103.75 paused rooms stop room lights/fans (zone HVAC still runs) | README_v5.103.75 |
| 2026-10-20 10:39 | v5.103.76 (no Jaya HVAC item) | git log |
Post-fix data exists only for 10-19 evening (and 10-20 evening is not yet happened). I used 10-19 04:06 as the break.

## 3. Measurement (17:00-23:00 CDT, HA long-term stats hourly means; Jaya sensor sensor.temp_hum_zigbee_jayabedroom_temperature)
Zone: Jaya shares climate.up_hallway_zone_2 with Ziri, Guest 2, Game, Media, Exercise, Upstairs Hallway (core.config_entries). Controls = mean of Ziri, Guest 2, Game, Upstairs Hallway.
Outdoor = thermostat upstairs outdoor sensor (it reads a flat 70.0 on 10-07..09, so weather control is rough).

| Period | Days | Jaya mean | Control mean | Jaya MINUS control |
|---|---|---|---|---|
| Pre 09-24..10-18 | 21 | ~80.6 | ~76.4 | +4.20 |
| Pre 10-05..10-18 | 13 | ~80.3 | ~76.2 | +4.09 |
| Post 10-19 | 1 | 77.3 | 73.6 | +3.67 |
Daily range pre of the difference: +2.4 to +5.9. Jaya mean/max 10-19: 77.3 / 77.8 (10-18: 77.4 / 77.6).
Regression pre (Jaya ~ outdoor): slope 0.165, int 67.5 -> predicts 79.4 for 10-19 (out 71.8); actual 77.3 (-2.1). Difference regressed on outdoor predicts +4.02; actual +3.67 (-0.35, inside daily noise).
Like-for-like: 10-16 (out 63) Jaya 77.7, 10-18 (out 67) 77.4, 10-19 (out 72) 77.3. Jaya tracks the controls; she is the warmest room both before and after.

Zone/occupancy confounds (recorder states, 10-13+): zone_2 preset was mostly "away" (cool hi 80) every evening 10-13..10-19, with "sleep" (hi 76) appearing 10-13 and 10-19 and "home" (hi 77) on 10-15..10-18. hvac_action was idle all evening 10-16..10-18 and cooling only ~24 of 124 samples on 10-19. Jaya window contact: no "on" event in any evening 10-12..10-19. Jaya radar presence minutes 17-23: jaya_3 0-79, zigbee 0-74 (noisy; 10-19: 21 and 28 min).

## 4. Verdict
- No measurable shift in Jaya's evening temp attributable to a fix: relative to the zone she is +4.2 F before and +3.7 F on the single post day, inside the pre-period spread (2.4 to 5.9).
- Absolute drop (about 80.6 -> 77.3) is weather: outdoor evening mean fell from ~85-90 to ~63-72; controls fell by the same amount (~76.4 -> 73.6).
- One post-fix evening cannot prove or disprove anything. Re-run after 3+ post-fix evenings with outdoor 80+ F (a hot day is where her +4 F gap lives); the gap is largest on hot days only weakly (outdoor slope 0.02 F/F).
- Pausing: per v5.103.75 a paused room still gets zone HVAC (it can even be marked vacant so the zone retreats), only room fan/light automation stops. Her room fan is thus off-automation since ~10-19, which could widen her gap if it was cooling her; no sign of that yet (gap 3.67).
- Caveats: the thermostat outdoor sensor is flaky; 10-20 evening and the days 10-03/04/17 lack data; the house was mostly "away" 10-13..10-19, so setpoints (80) differ from normal.

Files: queries run via /Users/okosisi/Code/universal-room-automation/.claude/scratch/jaya_stats.py

---
# Addendum (2026-10-20): vent move, operator-stated 10-15 (Thu) or 10-16 (Fri)

Method: hourly HA long-term stats, Jaya minus mean(Ziri, Guest 2, Game Room, Upstairs Hallway), adjusted for outdoor temp (slope 0.03 F per F, i.e. weather barely moves the gap). Scripts: .claude/scratch/jaya_vent.py, jaya_cool.py. Operator was away 10-14 to 10-18, so zone preset was mostly "away" (cool hi 80) that week: setpoints and occupancy are confounded for the post period.

## (1) Change point, daily gap (F), outdoor-adjusted
| Day | Evening gap | All-day gap |
|---|---|---|
| 10-10 | 5.6 | 6.2 |
| 10-11 | 5.9 | 5.8 |
| 10-12 | 4.5 | 5.5 |
| 10-13 | 3.9 | 4.5 |
| 10-14 | 3.7 | 4.7 |
| 10-15 | 2.5 | 3.6 |
| 10-16 | 4.2 | 4.3 |
| 10-18 | 5.0 | 5.5 |
| 10-19 | 4.1 | 5.5 |
Fixed splits (before = 43-day history from 09-03 to the day before; noise sd of the adjusted gap is 0.69 evening, 0.47 all-day):
- Break 10-15: evening before ~4.5, after (10-15,16,18,19) 3.9; all-day before ~5.2, after 4.7. Effect about -0.6 evening / -0.5 all-day, about one sd. Not clean.
- Break 10-16: after (10-16,18,19) evening 4.4, all-day 5.1: no effect (about 0).
- Unconstrained best-split scan chose 10-13 (-0.7 evening, -0.5 all-day), two days BEFORE the stated move, so the scan does not agree with a 10-15/16 step. The only real dip is the single day 10-15 (lowest of 43 evenings, 2.5), then the gap returns to 4-5 by 10-16 and 10-18.
- Missing days: 10-03, 10-04, 10-17 (and 10-05 all-day) lack data.

## (2) Cooling runs of climate.up_hallway_zone_2 (hvac_action == cooling, runs >= 15 min; recorder states only exist from 10-13, so only 10-13/14 are "before")
| Day | Runs | Cool min | Jaya rate F/h | Controls rate F/h | End-of-run gap Jaya-controls | Jaya minus zone thermostat temp at run end |
|---|---|---|---|---|---|---|
| 10-13 | 7 | 341 | -0.15 | -0.33 | 4.2 | 3.0 |
| 10-14 | 18 | 901 | -0.19 | -0.14 | 4.5 | 2.8 |
| 10-15 | 18 | 783 | -0.08 | -0.27 | 3.2 | 1.2 |
| 10-16 | 6 | 122 | -0.12 | -0.53 | 2.9 | 0.6 |
| 10-17 | 2 | 41 | -2.10 | -1.57 | 4.0 | 1.7 |
| 10-19 | 1 | 32 | -1.04 | -0.86 | 3.8 | 2.2 |
- 10-15 and 10-16 show Jaya closer to controls during cooling (end gap 4.2-4.5 down to 2.9-3.2; against the zone thermostat 2.8-3.0 down to 0.6-1.2). That is the signature a colder supply would leave, and it fits a move on ~10-15.
- It did not hold: on 10-17 and 10-19 (few, short runs, cooler weather, away setpoints) the gap is back to 3.8-4.0 and 1.7-2.2 vs thermostat. Those days have 1-2 runs each, so the evidence is weak.
- Cooling rates are endpoint deltas of sparse Zigbee sensors; Jaya's rate is not faster than the controls' on any day with >2 runs (it is slower on 10-15/16). Rate is not a usable discriminator here.
- Limitation: no pre-10-13 cooling-run data (state history purged); I did not find another source for earlier hvac_action.

## (3) Verdict
- Did the vent move measurably help? Weakly, and not durably so far: a dip of about 1 to 1.7 F in her gap to the zone on 10-15 and 10-16 (cooling-run end gap 4.2-4.5 down to 2.9-3.2), which is inside the scatter of the previous 6 weeks (daily gap 3.4 to 5.9) and has reverted to ~4 by 10-17..19.
- Weather is not the explanation (gap barely depends on outdoor temp). The away week (setpoint 80, many idle hours, few cooling runs after 10-16) is a bigger confounder than any vent effect.
- Can't conclude a step change. Re-check once the family is home with several normal cooling days (>= 5 post days, runs > 15 min, outdoor above 80 F); then compare the end-of-run gap vs the 4.2-4.5 baseline.
