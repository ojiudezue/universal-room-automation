# AUDIT — HVAC hold sizing re-based on RAW presence (2026-09-29)

**Card:** HVAC-HOLD-SIZING-ALL-ROOMS-1 (read-only investigation; replaces the presence-truth of the 2026-09-26 run).
**Probe:** `scripts/probes/hvac_room_return_probe_raw.py` —
`ssh ha "python3 - [--end-utc 2026-09-28T23:44:00] [--days 7] [--verbose]" < scripts/probes/hvac_room_return_probe_raw.py`
**Windows:** PRE-SHIP baseline 09-21 18:44 → 09-28 18:44 CDT (7.0 d, before the v5.103.20 fast path shipped);
POST-SHIP 09-28 18:44 → 09-29 02:12 CDT (0.31 d, **INSUFFICIENT**, shown for direction only).

## Institutional context verified
- `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` read completely (§2 C18 tick latency, §3.1 evidence hold,
  §3.2 knobs 47/48/49/52, §9.3 Jaya, §9c overrides, §10 ledger).
- Prior probes read: `scripts/probes/hvac_room_return_probe.py` (flawed: lagged `hvac_occupied` truth),
  `scripts/probes/hvac_night_sleeper_probe.py`.
- Room→zone map: `hvac_zones.py:395-526` (`discover_zones`: Zone Manager `zones[*].zone_thermostat` + `zone_rooms`
  entry ids, merged per thermostat; zone id parsed from the thermostat entity, `:368-375`). Live map read from
  `.storage/core.config_entries` 2026-09-29: zone_1 = Entertainment + Master Suite (12 rooms), zone_2 = Upstairs (14),
  zone_3 = Back Hallway (14); Patio ("Outside") has no thermostat.
- Raw sensor keys: `motion_sensors`, `presence_sensors` (= `CONF_MMWAVE_SENSORS`, `const.py:454`),
  `occupancy_sensors` — the three the room coordinator reads (`coordinator.py:2915-2917`).
- Hold tables: `const.py:1229` `ROOM_TYPE_HVAC_HOLD` (evidence rule, v5.103.20), `:1248` legacy tail, `:1265` night.
  Per-room overrides `CONF_HVAC_VACANCY_HOLD[_NIGHT]` (`const.py:1287-1288`, config-flow climate step, rung 2).
- Live knobs (recorder latest, 09-28 23:40): 47 entry wait = 1, 48 vacancy delay = 5, 49 energy-saving delay = 5,
  52 return window = 10. Per-room overrides live: Jaya day 60 / night 5400; night 90 s on Kitchen, Breakfast Nook,
  Dining, Butler Pantry, Living Room, Receiving Room, Game Room, Exercise Room, Patio.

## Method
- A room is **raw-present** while any configured sensor is `on`; on-intervals ≤ `MERGE_GAP_S` = 120 s apart are joined.
- An **away write** = `ura_activity_log` `preset_change` with `new_preset=away`. Writes are collapsed into **away episodes**
  (first away write → next non-away preset write from `preset_change` or `climate_write`), so the zone_1 re-write
  churn (§9.7) is counted once.
- Each episode is classified at W (its first write). Hallways are excluded (circulation exclusion by design).
  Classes: `ENTRY-RACE` (raw onset ≤ 300 s before W), `STILL-BODY-MISSED`, `STUCK-EXCLUDED` (still-body sensor
  continuously on ≥ 4 h = P22), `MOTION-ON-MISSED`, `HOLD-TOO-SHORT` / `MOTION-ONLY-COVERAGE` (zone empty at W,
  someone back within 30 min and **stayed ≥ 5 min**), `TRANSIT-RETURN` (came back for < 5 min; not harm),
  `OVERRIDE-VACANT` (the room's Override Vacant switch was on), `POLICY-AWAY-*` (the write reason was not
  `vacant_past_grace`: a house-away transition or the energy-shed cap), `CLEAN`.
- Discriminators recorded per harm: URA's own room `occupied` / `hvac_occupied` at W; the sensors on at W; how long
  the zone stayed away after the person was back (`away_while_present_min`).

## Results — PRE-SHIP baseline (7 d, 113 away episodes)
| Class | n | Where | Reading |
|---|---|---|---|
| CLEAN | 43 | all zones | correct retreats |
| TRANSIT-RETURN | 45 | 36 zone_3 (Kitchen-led) | pass-through within 30 min, stayed < 5 min — not harm |
| **OVERRIDE-VACANT** | **14** | Kitchen (zone_3) | `switch.kitchen_override_vacant` ON 09-21 23:20 → 09-27 19:40. URA's Kitchen `occupied` = off with `occupancy_source: override` while both Kitchen radars were on for 13–41 min. Config, not hold. |
| POLICY-AWAY-PRESENT | 6 | z1 ×4, z2 ×2 | 3 house-away transitions, 2 energy-shed cap (09-25 19:32, by design), 1 house-away with a 12.6-h-on Inovelli radar (stuck). Not hold issues. |
| **STUCK-EXCLUDED** | 2 | Jaya Bedroom (zone_2), 09-25 07:05 / 07:50 | see Jaya below; ambiguous (the radar tracks the fan) |
| HOLD-TOO-SHORT | 3 | Living Room 1 (09-23 19:46, gap 29.7 min); Kitchen 2 (09-28 11:06 / 12:06, after the override was cleared) | |
| ENTRY-RACE / STILL-BODY-MISSED / MOTION-ON-MISSED / MOTION-ONLY-COVERAGE | 0 / 0 / 0 / 0 | | the earlier first-pass counts (7 / 13 / 0 / 4) were all Kitchen-under-override or transits |

Hold-related harm in 7 days: **3 HOLD-TOO-SHORT**, 0.43/day. In the zone's last-occupied room: 3 of 3.

## Results — POST-SHIP (0.31 d, INSUFFICIENT)
9 away episodes: 3 CLEAN, 3 TRANSIT-RETURN, 2 HOLD-TOO-SHORT (Kitchen, total gap 14.3 / 16.3 min),
1 ENTRY-RACE (Kitchen, radar onset in the same second as the write). **Away-while-present was 0.0–1.0 min in all three:**
the v5.103.20 fast path re-homes zone_3 within about a minute of a return. Before the ship the median was
5.3–10 min. Re-run after 2026-10-01 18:44 CDT for a ≥ 3-day read.

**Kitchen, override-free slice** (09-27 16:39 → 09-29 02:15, 1.4 d; `--end-utc 2026-09-29T07:15:00 --days 1.4`):
22 zone_3 aways with Kitchen as the last-occupied room → 7 clean, 10 transit, 4 HOLD-TOO-SHORT, 1 entry race;
total gap median 18.1 / p90 39.5 min; release delay (W − last raw presence) median 12.9 min; away-while-present
median 1.0 min.

## Jaya Bedroom — mechanism (refines state-of-play §9.3 / C19)
- `binary_sensor.jaya_3_presence` switches with `fan.fanswitch_treat_wifi_jayabedroom`, to the minute: fan off
  09-23 02:40 → radar off 02:41; fan on 03:43 → on 03:43; fan off 09-24 01:31 → off 01:32; fan on 02:56 → on 02:57;
  fan off 09-25 01:36 → off 01:37; fan on 02:40 → on 02:40. **The radar is detecting the fan, not a still sleeper.**
  URA's fan-interference defences did not flag it (`fan_interference_suspect: false`, `mmwave_fan_demoted: false`).
- URA's **P22 continuous-on exclusion** (`coordinator.py:364` `_stuck_sensor_hours = 4.0`, hard-coded, no knob;
  applied at `:2999-3017`, "stuck on … ignoring") fired on `jaya_3_presence` **9 times in 7 days**, on 5 of the 7 nights
  (`sensor.jaya_bedroom_bedroom_4_automation_health` → `stuck_sensor`: 09-22 03:23, 09-23 02:26, 09-24 01:10,
  09-25 01:22, 09-26 03:09; plus 09-23 10:50, 09-23 19:06, 09-24 06:57, 09-25 06:40). **09-24 01:10 and 09-25 01:22 are the triggers for the
  two §9.3 vacancies** (URA marked the room vacant at 01:25:53 / 01:31:18, 4 h after the radar last came on at
  21:10 / 21:22), and the fan then switched off because the room was vacant, taking the radar with it.
  So "the radars lost a still sleeper" is incomplete: this radar never saw the sleeper, and the vacancy was the
  4-hour stuck-sensor exclusion of a fan-driven signal. (The duty-cycle rule next to it explicitly refuses to
  exclude because "a sleeping person is ~100% mmWave", `coordinator.py:3066-3071`; the continuous rule has no
  such guard, but here excluding was the right call — the signal was the fan.)
- Other P22 hits in the window: Master Bedroom Inovelli radar 09-25 22:16 (1); Patio 5 (no thermostat).
- Consequence: Jaya's room has **no trustworthy still-body sensor while her fan runs**. The Zigbee radar
  `mmwave_zigbee_jayabedroom_presence` is reporting again (on/off transitions since 09-25) but blips briefly.
  The 5400 s night hold (set 09-26) covers a P22 drop only until the hold runs out, because the excluded radar
  stays excluded for as long as it reads on.

## Other findings
- **`switch.exercise_room_override_vacant` has been ON since 09-21 23:23 and is still on.** Exercise Room (zone_2)
  is invisible to lighting and HVAC occupancy. Probably forgotten (see the §9c "forgotten override" hazard).
- Study A has `binary_sensor.athom_presence_sensor_d93b20_mmwave_sensor` stored under the legacy key
  `mmwave_sensors`, which nothing reads (the flow and coordinator use `presence_sensors`, `const.py:454`).
  That sensor does not feed occupancy. Study A had 0 harms; low priority.
- zone_3 churn: Kitchen drives about 16 zone_3 away cycles/day, about 64 % followed by a re-entry within 30 min
  (mostly transits). After the ship this costs Carrier writes, not comfort.

## Verdicts
| Room | Verdict |
|---|---|
| Kitchen (z3) | **No hold change now.** 4 HOLD-TOO-SHORT in 1.4 d of clean data, but after the ship each costs ≈1 min away. Candidate if the ≥ 3-day re-run shows ≥ 2 HOLD-TOO-SHORT/day: per-room `hvac_vacancy_hold` (config flow, climate step, `CONF_HVAC_VACANCY_HOLD`) = 900 s (current: unset → 180 s common_area table). This would mainly cut write churn. Cost: zone_3 conditioned about 12 min longer after each real departure (about 5/day). |
| Living Room (z1) | None (1 event / 7 d). |
| Jaya Bedroom (z2) | **Coverage fix, not hold.** Re-aim or re-tune `jaya_3_presence` so it stops detecting the fan (physical/ESPHome gate config), or replace it; confirm the Zigbee radar holds a still sleeper. A longer hold cannot fix a sensor that reads the fan. A code guard (P22 continuous rule fan/bedroom awareness) is a separate card candidate and needs an adjacency sweep against STUCK-SENSOR-1 / OC-STUCK-SENSOR-GENERALIZE-1 / HVAC-NIGHT-LENIENCY-DEGRADATION-DEFENSE-1. |
| Exercise Room (z2) | **Operator action:** turn off `switch.exercise_room_override_vacant` if not intentional. |
| Kitchen override | Already cleared 09-27 19:40; no action. |
| All other rooms | None — 0 harms. |

**Overall: no broad livability problem.** After removing the forced-vacant Kitchen, pass-throughs and policy aways,
the 7-day baseline has 3 hold-related harms. The fast path now limits a premature away to about 1 minute.
The real defects are a forgotten override (Exercise Room), a sensor that reads a fan (Jaya), and a stray config
key (Study A).

## Caveats
- Sensor kind (STILL vs MOTION) is inferred from entity names; the table is printed in the probe header for audit.
  The Hobeian `occupancy_lux_temp_humidity_*_presence` devices are treated as radar.
- Raw presence is not proof of a person (the Jaya fan shows this); a returned stay of ≥ 5 min is the livability filter.
- The post-ship window is 0.31 d; do not size anything on it.
