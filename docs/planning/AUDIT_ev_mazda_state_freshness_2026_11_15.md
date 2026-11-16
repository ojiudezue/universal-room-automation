# AUDIT: CX-90 PHEV (mazda_cs) state freshness vs the EVSE, for EV-VEHICLE-SOC-MAZDA-1

Probe run Sun 2026-11-15 22:45-23:05 CST. Read-only. Card: EV-VEHICLE-SOC-MAZDA-1 in
`docs/planning/kanban.data.yaml`. The refresh button was not pressed. Scripts are in
`.claude/tmp/mzd_*.py` (recorder reads over `ssh ha "python3 -"`, then offline analysis).

## Answer first

The car's data is **stale and late, not fresh**. Neither the polling cadence nor the
`vehicle_status_last_updated` stamp is a freshness guarantee. No idea earns an (a) build
for a control path.

| Idea | Verdict | Deciding numbers |
|---|---|---|
| 1. Stop charging when car reports full | **(c) not usable** | The car stops itself (0 to 100 = about 15 kWh over about 3 h, EVSE draw ends on its own). Car SOC lags EVSE draw by a median of about 2 h. `remaining_charging_time_ac` never reaches 0 at full (floor 10). |
| 2. Unblock daytime solar-only (shape 2) | **(b) needs refresh-before-read**, and it is only half the input | Snapshot now 4 h 31 m old with the car plugged in. 13% of >=12 kWh sessions never show up in the car's SOC. SOC without a departure time is still only half of "needed by departure". |
| 3. Plug-state disagreement flag | **(c) not usable as-is** (would be a standing false alarm); (b) only on a refresh | Live now: car `plugged_in` off, EVSE Connected since 19:57. Car snapshot is from 18:16. |
| 4. (card) display only | **(a) fine if it shows the snapshot age** | Display tolerates stale data if the age is shown. |

## Data coverage (how much history exists)

- The `mazda_cs` entry was created 2026-11-15 20:40 CST (`core.config_entries` `created_at`
  02:40Z; `options.enable_push_notifications: True`, modified 22:41 CST). It is `iot_class:
  cloud_polling`, integration v2.3.0 (`custom_components/mazda_cs/manifest.json`).
- **Recorder states** for the five requested entities: all `unavailable` from 2026-11-08
  08:26 to 2026-11-15 18:42. First real values at 2026-11-15 20:40:26. So **only about
  66 minutes of real state history** exist in `states` (20:40 to 21:47), and the other
  states rows from 11-15 21:46:59 are one restart rewrite of identical values.
- **Long-term statistics** (hourly, `statistics` table) exist for `charge_level` (5,459
  hourly rows) and `remaining_charging_time_ac` (5,539) under the same entity ids,
  2025-03-26 to 2025-11-30, in segments with gaps (for example 2025-09-08 to 09-13 and
  2025-11-19 to 11-20), plus one row at 2026-11-15 20:00. Only these allow a cadence and
  session comparison. Caveats: hourly granularity (so lags are +/- 1 h), and which
  integration wrote the 2025 rows is **unknown** (an older `mazda` integration also
  exists in `custom_components` and `update.mazda_update` is in the recorder).
- `binary_sensor.*_plugged_in` and `switch.*_charging` have **no long-term statistics**
  and their 2025 states are purged. A plug/charging comparison against the EVSE is possible
  only for the 11-15 evening.
- EVSE side (registry-resolved from the Coordinator Manager options): plug state
  `sensor.garage_a_evse_emporia_wifi_garagea_status` (values Disconnected/Connected/
  Charging), power `sensor.garage_a_power_minute_average` (`energy_evse_a_entity`),
  energy `sensor.garage_a_energy_today`. **Assumption, not verified in the registry:** the
  CX-90 charges on EVSE A (the car's entities carry "garage_a" in the name; the device
  registry did not give me an area link). The L1 smart plugs
  (`energy_l1_charger_entities`) would charge the car with no EVSE draw. A second vehicle on
  EVSE A is possible and cannot be excluded from this data.

## 1. Cadence and staleness

Poll: `async_update_data` fetches vehicle + EV status on a DataUpdateCoordinator with
`update_interval=timedelta(minutes=3)`, promoted to 6 minutes when push is connected
(`custom_components/mazda_cs/__init__.py:373-374`, `fcm_listener.py:257`). The refresh
button calls `refresh_vehicle_status` then `coordinator.async_request_refresh()`
(`button.py:36-40`). So HA polls the cloud every 3-6 minutes, but the cloud returns the
car's **last uploaded snapshot**; polling more does not make the data newer.

Observed:

- `vehicle_status_last_updated` = `2026-11-16T00:16:50+00:00` = **2026-11-15 18:16:50 CST**
  in all three recorded rows (20:40:26, 20:41:01, 21:46:59). It was 2 h 24 m old at the
  first read, and no newer value is recorded through the probe (4 h 31 m old at 22:48).
  Zero advances in about 2 h of polling, car parked in the garage.
- `charge_level` 0, `remaining_charging_time_ac` 130, `plugged_in` off, `charging` off:
  no changes in any of the rows, other than the initial set at 20:40:26.
- 2025 hourly stats: 410 distinct SOC values; hour-to-hour change in only **598 of 5,458**
  hours (11%); plateaus (unchanged runs) median 1 h but p90 18 h and max 755 h (a parked car).
- Session lag, 87 sessions where SOC rose: hours from EVSE draw start to first SOC rise
  (hour buckets): 0 h = 24, 1 h = 19, 2 h = 32, 3 h = 6, 4 h = 4, 5 h = 1, 6 h = 1. Median
  about 2 h. Charging while the car's data sat frozen for hours is routine.

## 2. Agreement with the EVSE

Sessions = runs of hours with EVSE mean power > 1 kW (gaps up to 2 h merged); 431 sessions
in the EVSE history, 137 with usable car data in the same window.

- **Plug state, live (the only overlap):** EVSE `Disconnected` until 18:41, `Connected`
  from 19:57:15 and at 21:47:09. Car `plugged_in` = off at 20:40 onward, from an 18:16:50
  snapshot. The disagreement is explained by the snapshot predating the plug-in (consistent
  with, not proof of, staleness): the car data lags the plug by at least 1 h 41 m and is
  still unchanged 2 h 51 m after the plug. A "disagree" flag would be on for hours after
  every plug-in.
- **SOC plausible vs kWh delivered:** 82 sessions with dSOC >= 10 points: the median is
  **15.2 kWh per 100 SOC points** (range 8.4 to 128; the high end is noisy short sessions).
  A 0 to 100 session is about 15 kWh (e.g. 04-14, 04-15, 09-20, 09-21, 09-22: 15.0-15.2 kWh).
  So the SOC scale itself is plausible when the data is fresh.
- **Not reflected:** of 77 sessions with >= 12 kWh delivered, 62 show SOC >= 80 within 12 h
  of session end, **10 (13%) never leave SOC < 20** (for example 10-23 02: 21.8 kWh, SOC 0
  before and after, remaining time stays 130). Cause not provable from this data (stale
  snapshot vs a second vehicle vs L1 on another path).

## 3. Full detection

- 975 hours at SOC 100: `remaining_charging_time_ac` min 10, max 10.4, **never 0**. Hours with
  remaining time = 0 (83) are all at SOC about 0, not full (a "no data" value). 389 hours read
  2530 (a not-charging sentinel across all SOC bands). So **remaining time 0 is not a full
  signal**; the car's "full" is SOC 100 with remaining time 10.
- Sessions ending at 100: many (about 64 sessions reach 99.5+ in the hourly max). EVSE draw ends by
  itself at about 15 kWh after a 0-100 charge (e.g. 3 h, 15.1 kWh), i.e. the car terminates
  charging; the EVSE/URA need no stop command at full.
- Residual: 24 hours with sustained EVSE draw (>1 kW, 174.7 kWh over hours where the car
  reported 100 now and the hour before). Cannot say whether that is a stale-100 reading
  after a drive, top-off, or another vehicle; **unknown**.

## Producer and consumer

- Producer: Mazda cloud snapshot, uploaded by the car when it is awake (charging/driving/
  refresh button); HA polls it every 3-6 min. Not fire-checked per update beyond the above
  (`last_updated` fired once in 2 h).
- Consumer today: none in EC (card is `inbox`). Any EC consumer would be a trust decision
  (stop/solar-only), where a 2-6 h stale value is wrong in the harmful direction (a stale
  `plugged_in=off` suppresses charging; a stale SOC 100 skips a needed charge).

## What would disprove this

- A `vehicle_status_last_updated` that advances without the button while the car sleeps
  (not seen in about 2 h; the only data is one afternoon). One more look at this entity
  tomorrow morning would settle the "never refreshes unless awake" claim.
- The refresh button's effect and cost (12 V drain / wake) were deliberately not measured.

## Recommendation

Do not build 1 or 3. Idea 2 is only worth building if the operator wants it with a
one-shot, rate-limited refresh at the charge-onset or plug-in event, and also a departure
time source; park it with that trigger. Display (idea 4) is fine with an age badge from
`vehicle_status_last_updated`.
