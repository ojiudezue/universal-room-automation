# AUDIT: crossing ledger known-time vs restarts (2026-11-17 ~11:00 CST)

Read-only. Presence/HVAC STATE_OF_PLAY docs not read in full (no presence-sensor behaviour changed; Tier-1 map taken from the earlier sweep, `.claude/tmp/ledgersweep/tier1.json`, and anchor rule from `crossing_ledger.py:471-510`, `crossing_vision.py:1889-1973`, `const.py:3883-3925`).
Scripts: `.claude/tmp/ledgerknown_pull.py` (remote read-only pull), `.claude/tmp/ledgerknown_sim.py` (`strict|p22|nohold`). Data `.claude/tmp/ledgerknown/pull.json`.

## Window limit (not 14 days)
Recorder `states` starts 2026-11-10 07:02Z (min last_updated_ts 11-10 10:12Z, retention ~7 d). Tier-1 held state, doors and restarts are only recoverable from there. Window analysed: **11-10 12:11 -> 11-17 10:39 CST = 6.94 d**. The 14-day ask cannot be met from the recorder; `census_snapshots` go back further but without Tier-1/door/restart data.

## Signals used (closest recorded)
- Body total: `census_snapshots` zone=house, `frigate_count+unifi_count` (7,476 samples ~90 s). Dark: `sensor.universal_room_automation_persons_in_house` attr `camera_input_dark_fired`.
- Held: 71 Tier-1 binary_sensors (config-derived list, phantom `mmwave_zigbee_gameroom_presence` dropped) from recorder `states`; rising edge = any `on` row; door entry = `person_entry_exit_events` direction=entry. Anchor = 900 s continuous passing samples, gap >300 s resets.
- Restarts: `recorder_runs` (stop -> start). Doors resolved via `core.entity_registry`/config entries (not names): security_entry_sensors + room `door_sensor` of `door_type=egress` rooms + elkm1/zwave_js/unifi_access door entities; egress cameras = `egcams.csv` person binary_sensors.
- **Validation:** the one live anchor (DB row 11-17 08:42:32 CST) is reproduced only by the `nohold` variant (sim anchor 08:43:11). `strict` (every Tier-1 `on` holds) misses it: at 08:41:53 `screek_human_sensor_l13_2412s_presence` and `mmwave_lux_temp_hum_zigbee_livingroom_presence` are `on` (live code evidently released them via stuck-exclusion, `const.py:3896-3908`, which I cannot reconstruct from the recorder). So: strict = lower bound, nohold = calibrated to one observation (n=1, weak).

## 1. Anchor opportunities (maximal passing runs >= 900 s)
| variant | opportunities | per day (n / min) |
|---|---|---|
| strict | 2 | 11-14: 2 / 94 |
| p22 (>=4 h `on` released, not in sleep/waking/home_night) | 3 | 11-13: 1 / 17.5; 11-14: 2 / 94 |
| nohold (calibrated) | 9 | 11-13: 3 / 83; 11-14: 3 / 126; 11-16: 2 / 39; 11-17: 1 / 22; 11-10,11,12,15: 0 |
nohold detail: 6 of 9 with house state `away` + all residents `not_home` (11-13 x3, 11-14 x2, 11-17), 1 `sleep`, 2 `home_day`; lengths 17-67 min. Fail mix (strict, 7,476 samples): held 3,879, body 2,588, edge 406, dark 359, gap 27, pass 217. Ledger code only shipped 11-14 16:03 CST, so 11-13/11-14 AM opportunities pre-date it (hypothetical).

## 2. Restarts
28 recorder run boundaries in the window (4.0/day); 26 with census data both sides.
- Recorder downtime stop->start: 27-52 s (median ~31 s).
- **Ledger-blind gap** (last census snapshot before stop -> first after start): **380-491 s (median ~430 s)**. ~7 min is URA boot lag, not HA downtime.
- Time to next anchor after a restart (nohold): 4 of 26 restarts were known when they hit; known-time destroyed there = 434, 105, 1024 (to window end), 101 min (restarts 11-13 18:50, 11-14 12:47, 11-16 15:32, 11-17 08:51 CST). After the 22 restarts not known at the time, nothing was lost. Under strict, only 1 restart (11-14) ever hit a known ledger.

## 3. Restart-gap safety
Activity checked in [last snapshot before stop, first snapshot after start + 60 s]: any exterior door contact / egress person camera state differing from its pre-gap value, or a `person_entry_exit_events` entry.
- Activity found in **4 of 26 gaps (15%)**: 11-10 17:52 (garagehallway contact on, doorbell person), 11-12 13:48 (garagehallway/patiohallway contacts, garage_a person; entry row), 11-12 21:10 (elkm1_front_door on), 11-14 16:05 (front door + two egress cams, entry row). 22 gaps clean. Bedroom-door contacts: 0 hits.
- Residual: a door opened and closed entirely inside the gap and with no HA state row is invisible (not measurable here).

## 4. Simulation (known-time fraction of 6.94 d)
| variant | today | restore N=120 | N=300 | N=600 | no restarts |
|---|---|---|---|---|---|
| strict (lower bound) | 1.6% | 1.6% | 1.6% | 3.4% | 43.5% |
| p22 | 1.9% | 1.9% | 1.9% | 12.9% | 53.2% |
| nohold (calibrated) | 11.0% | 11.0% | 11.0% | 28.4% | 54.3% |
Restore applies at 0 of 26 restarts for N=120 and N=300 (the 380-491 s boot lag alone exceeds them) and 22 of 26 at N=600 (the 4 skipped = door activity). N=1800 is identical to 600.
Even with no restarts, known share is capped at 43-54% (held/edge/body, not restarts).

## Recommendation
Restore-across-restart is safe and worthwhile only with N >= ~600 s (measured by last-snapshot-to-first-snapshot, not HA downtime), plus the recorder door/egress check; it roughly 2.6x's known time (11% -> 28% calibrated). The larger lever is anchor yield (held/edge blocking): even with zero restarts, known time is only 43-54%.

## Caveats
n=1 live anchor for calibration; stuck-exclusion not reconstructable; recorder covers 6.9 d not 14; edges approximated by every `on` row; census ticks ~90 s vs 60 s eval.
