# AUDIT: did raw Bermuda BLE flapping cause wrong URA actions or state? (2026-10-25)

Read-only harm check for kanban card BLE-LOCATION-QUALITY-1. Prepared by ura-prober, 2026-10-25 18:36 CDT (`date`).
Read first, completely: `docs/planning/AUDIT_ble_location_baseline_2026_10_23.md`, `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`, `docs/architecture/SENSOR_FLEET_CLASSES.md`. The HVAC state-of-play doc (700 lines) was NOT read completely; only section 9.3 (Jaya zone_2 night still-sleeper) and grep hits were read, so every HVAC statement below is limited to what the activity log shows.

## 0. Bottom line

- **Is there a real livability problem? Yes, but small and confined to one room.** BLE flapping did not light a bathroom, fire a night light, turn a fan, change house state, or move music. It did make **Jaya Bedroom read VACANT while Jaya was asleep in it**: 85 min (10-19), 71 min (10-20), and 199 min on 10-24 (outside the brief). That produced **one** downstream actuation in the window: **Upstairs (zone_2) thermostat preset sleep -> away for 24 min, 02:07-02:31 CDT 10-20** (compounded by a URA setup/restart at ~02:06). Every other episode: NO HARM.
- **Mechanism (the producer/consumer chain).** Jaya Bedroom's only radars (ZK + LD2410) read "on" ~50 of 360 night minutes even on good nights, so the room is held mostly by the BLE-extend leg (`coordinator.py` ~4066-4218: BLE can EXTEND but never CREATE occupancy, chain-only, gated on `get_persons_in_room(room)` which needs Jaya's resolved location == that room). When Bermuda says "Jaya Bathroom", the hold is withdrawn and the room vacates. Control: nights 10-22 and 10-23 had the same radar on-time (44 and 47 min) but a stable BLE location, and the bedroom stayed occupied 360/360 min.
- **Narrowest fix it points to:** not "improve BLE". Make the Jaya Bedroom BLE hold not lose to the adjacent-bathroom flap: the bedroom already borrows `scanner_areas: ['jaya_bathroom']` (config entry `01KJXMA4VRMZZ337N8YNKV7KJQ`), so the smallest change is to count a person resolved to the borrowed neighbour as a member of the bedroom for the EXTEND leg only (or a short per-room dwell/hysteresis on the resolved location for that leg). Config-first check before code: the bedroom hold knobs (`BLE_CHAIN_HOLD_ENABLED`, `CONF_BLE_HOLD_CAP_ENABLED`, `ROOM_TYPE_BLE_HOLD_CAP_DEFAULT`, night vacancy hold knob `hvac_vacancy_hold_night` named in HVAC doc 9.3) were not read live; check them first. Do not build a general Bermuda smoother: no other episode shows harm.
- Marginal-benefit note: 1 retreat of 24 min in 7 nights. The simple version (neighbour counts for extend) captures essentially all of it; anything fancier (trilateration, 3D) has no harm evidence behind it.

## 1. Method and caveats

- Recorder `/config/home-assistant_v2.db` on `ssh ha`. `mode=ro` failed for the `okosisi` user ("attempt to write a readonly database", file is root-owned, 15 GB); reads used `mode=ro&immutable=1`. Immutable on a live DB can miss the most recent pages; the windows read are 5-7 days old, so acceptable. URA DB `/config/universal_room_automation/data/universal_room_automation.db` opened `mode=ro` normally.
- Times CDT (UTC-5). URA DB `ura_activity_log`, `occupancy_events`, `house_state_log` timestamps are UTC; converted (e.g. bathroom entry 09:37:20Z = 04:37:20 CDT matches recorder PIR 04:37:20 CDT).
- Series collapsed on state change; minute sampling at midpoint; scratch files in the scratchpad `bleharm/` directory (a first set of scripts was overwritten by another agent sharing the scratchpad and re-created).
- Retention: recorder 7 days, so 10-18 onward only.
- Not done: no live thermostat temperature read, so "was the house uncomfortable for 24 min" is UNKNOWN.

## 2. Consumers of BLE person room (trust/actuation vs display)

| Consumer | file:line | Reads | Class |
|---|---|---|---|
| Room occupancy BLE EXTEND leg (chain-only, never creates; BLE-WARM-CREATE-1) | `coordinator.py:4066-4218` (`get_persons_in_room` at 4075, `ble_allowed = self._last_occupied_state` ~4164, sets `STATE_OCCUPIED`, source `ble` ~4208) | resolved location == room | **Trust / actuation** (feeds lights, fans, zone roll-up, HVAC `hvac_occupied`) |
| BLE hold cap | `coordinator.py` ~4168-4200 | `_ble_only_hold_since` | Trust (limits the above) |
| D2 mmWave-fan demotion BLE-trustworthy veto | `coordinator.py:2978` | persons in room | Trust (blocks vacating) |
| `ble_persons` populate | `coordinator.py:4258, 4624`; `sensor.py:2983, 3002, 3078` | persons in room | Display |
| Comfort-fan away veto / fan recheck L1 | `fan_veto.py:296-308`; `_ble_corroboration.py:60-95`; `presence_fan_recheck.py:1411` | persons in room/zone | Trust (fan on/off) |
| Zone persons | `aggregation.py:5286, 5315, 5425` (`get_persons_in_zone`) | zone membership | Display / zone status (not examined further) |
| Census BLE list | `camera_census.py:2680-2700` (`_get_ble_persons`) | any non-away location | Trust for AWAY/GUEST, but only "home vs away", insensitive to room flapping |
| Transition detector -> listeners | `transitions.py:190-260`, listeners `music_following.py:211`, `__init__.py:3174` (Bayesian) | room changes | MusicFollowing = actuation; others learning/display. Ping-pong return legs suppressed (`transitions.py:245-252`) |
| Transit validator | `transitions.py:228-232, 458`, `transit_validator.py` | transitions | Display / log (`Invalid transit` anomalies, confidence delta on the DB row) |

Producer: Bermuda area -> `person_coordinator` three-tier resolution (State of Play section 3). URA's resolved `sensor.universal_room_automation_<p>_location` still flaps (Jaya: 148 changes 10-19, 172 on 10-20, 00-06), so the smoothing documented in the baseline audit does not reach the bedroom extend leg.

## 3. Episode verdicts

### Episode 1: Jaya Bedroom <-> Jaya Bathroom, nights 10-19 and 10-20 (00-06 CDT) — **HARM (minor)** for the bedroom; **NO HARM** for the bathroom

Rows (recorder unless stated):

| Check | Observed | Source |
|---|---|---|
| BLE (raw) `sensor.iphone_jaya_area` 00-06 | 10-19: 620 changes, Bedroom 226.5 min / Bathroom 133.5; 10-20: 765 changes, Bedroom 239.6 / Bathroom 120.3 | recorder |
| Bathroom PIR `binary_sensor.pir_zigbee_jayabathroom_occupancy` | 10-19: ON 2.4 min (04:37:20-04:39:46); 10-20: ON 0 min (only unavailable blips 00:11, 02:06) | recorder |
| `binary_sensor.jaya_bathroom_occupied` | 10-19: ON 04:37:20-04:54:56 (17.6 min), PIR-triggered; 10-20: ON 0 min | recorder; `occupancy_events` 10-19 09:37:20Z entry source `motion` |
| Bathroom light/shower/fan (`light.minir4m_jayabath_overhead`, `switch...jayabathshower`, `...jayabathfan`) | 0 on-time both nights (light only `unavailable` 02:05:41-02:05:56 10-20) | recorder |
| Jaya Bedroom light (`switch.switch_sonoffm4rm_matter_jayabedroom`) | 0 changes both nights; fan stayed `on` all 10-20, `off` all 10-19 | recorder |
| `binary_sensor.jaya_bedroom_bedroom_4_occupied` | **OFF 84.8 min (10-19, 11 changes), 71.2 min (10-20, 12 changes)** while Jaya's phone placed her in the suite all night | recorder |
| Co-incidence of the vacate with BLE | Of 24 bedroom OFF edges on 10-19/20 and 10-24 listed, URA location at the edge was "Jaya Bathroom" in 24/24 (both radars off in every one) | recorder join |
| Control nights (same radars) | 10-22: ZK on 44.1 min, LD2410 8.7 min, URA location Bedroom 360/360, bedroom occupied 360/360. 10-23: ZK 47.1, LD 12.9, location Bedroom 359.7, occupied 359.8 | recorder |
| Bedroom HVAC occupancy | `binary_sensor.jaya_bedroom_jaya_bedroom_hvac_occupied` stayed ON all of 10-19 and, on 10-20, was OFF only 02:06:01-02:31:41 | recorder |
| zone_2 thermostat | `Upstairs preset sleep -> away` 2026-10-20 07:07:16Z (02:07 CDT), `away -> sleep` 07:31:09Z (02:31 CDT); `reason=vacant_past_grace` / `house_state_transition` | `ura_activity_log` |
| Other zone_2 sleep->away in the nights 10-16..10-25 | 1 (this one), per night count 00-06 CDT; zone_3 flips 5-11 every night regardless of BLE | `ura_activity_log` |
| House state | `sleep` unbroken 03:00Z-11:00Z both nights (10-19 night sleep 03:00Z? see log: sleep entered 10-20 03:00:03Z; no change 05Z-11Z 10-20) | `house_state_log` |
| Music following | `transfers_today` never left 0 from 10-18 06:34 to 10-25; no music rows in `ura_activity_log` | recorder `sensor.ura_music_following_coordinator_music_following_transfers_today` |
| Noise side effects | `transit` "Invalid transit" anomalies/day: 19, 44, 183, 230 (10-17..10-20), ~100-266 later; Jaya intra-Jaya `room_transitions` rows 222 (10-19), 210 (10-20) of ~330/day; no NM sent (0 notification rows mentioning transit/Jaya Bath) | `ura_activity_log`, `room_transitions` |

Verdict reasoning:
- Bathroom: NO HARM. Bathroom occupancy came only from its PIR (`motion_sensors` in its config; BLE extend cannot create); no lights/fans/night lights fired from the "2 h in bathroom".
- Bedroom: HARM. The 24/24 coincidence plus the 10-22/23 control (same radar on-time, stable BLE, no vacancy) says the vacancy is caused by the bathroom flap withdrawing the BLE hold. Consequences seen: occupied state wrong 71-199 min a night; zone_2 `away` for 24 min once. Bedroom light and fan did not change (light was off; fan kept running), so the actuation harm is the single thermostat retreat.
- Confounder: 10-20 02:05-02:06 shows a URA/device reset cluster (light, PIR, ZK, LD2410 `unavailable`; MusicFollowing anomaly `not_configured` 02:06:08; `tao_restore_evaluated` 07:06:15Z). The retreat started at 02:06:01 hvac_occupied OFF, 10 min after the bedroom had already gone OFF (01:55:58) at the instant location flipped to Bathroom. The restart removed the HVAC night tail; BLE flap supplied the vacancy. Neither alone is proven sufficient.
- Falsifier I went and got: "radar alone would also have vacated" — checked via 10-22/23 control; stands.

### Episode 2: Foyer <-> Study A (Oji, 1,285 quick flips) — **NO HARM**

| Check | Observed | Source |
|---|---|---|
| Flap timing | Daytime, Oji stationary in Study A: peak hours 10-21 12:00 (124 flips), 10-19 10:00 (117), 10-20 13:00 (103) | recorder `sensor.iphone_oji_area` |
| Foyer occupancy | 16 intervals in 7 days, 15-24 min each (= motion timeout), PIR `binary_sensor.occupancy_lux_temp_humidity_hobeian_entry_presence` on 0.5-3.5 min inside each; 0 min occupied during any of the flap peaks | recorder |
| Foyer light `switch.minir4m_foyer_sonoff_100219a71a_1` | 3 changes, 0 on-time in 7 days | recorder |
| Foyer room config | no scanner_areas, no lights_on_entry; `occupancy_events` Foyer 18 entries, all source `motion` | config entries; `occupancy_events` |
| Study A during flap peaks | occupied 150/150 min (10-19 09:30-12:00), 357/360 (10-21 09-15), 117/120 (10-20 12-14); lights unchanged | recorder |
| Study A vacates attributable to BLE | 48 OFF edges in window; none with URA location Study A except 10-21 16:46:39 (a URA setup at 16:46:47, MF `not_initialized`); two with location Foyer (10-20 11:45, 12:03) re-occupied in 14 and 3 min, cannot be separated from real walking: UNKNOWN, at most 2 events | recorder |

### Episode 3: Cross-floor Garage A <-> Jaya Bedroom — **NO HARM**

| Check | Observed | Source |
|---|---|---|
| Oji/Ezinne phones resolved to Jaya Bedroom | 122 min (Oji) and 41 min (Ezinne) over 6.5 days | recorder |
| Bedroom occupied with no radar on and only Oji's phone (not Jaya's) in the room | 7 min total (1 more minute with a radar on) | recorder join |
| Bedroom entry actions | `entry_light_action none`; lights unchanged | config; recorder |
| Why it cannot create | BLE extend is chain-only (`coordinator.py` ~4164, BLE-WARM-CREATE-1) | code |

### Episode 4: Oji night drift 10-20 (Kitchen / Receiving Room ~3.4 h) — **NO HARM** (truth of location UNKNOWN)

| Check | Observed | Source |
|---|---|---|
| BLE 00-06 | Kitchen 110.2 min, Receiving Room 91.7, Master Bedroom 38.1, Study A 36.1, Jaya Bedroom 22.1 | recorder |
| House state | `sensor.universal_room_automation_house_state` `sleep` 360/360 min; `house_state_log` shows no change 05Z-11Z | recorder; `house_state_log` |
| Kitchen occupied | ON 164.6 min of 360, largest 02:17-03:07 (50 min, PIR 8 min, BLE in room 48.5 min), i.e. BLE-extended | recorder join |
| Kitchen actuation | night-light switch `switch.shelly2pmg3_28372f239274_switch_1` OFF 360/360; overhead `light.dimmer_tapo_wifi_matter_kitchenoverhead` ON 7.3 min (01:06-01:13) during a 18-min PIR-active entry (PIR ON 11 min of it) | recorder |
| Receiving Room | occupied 0 min; lights off | recorder |
| Other rooms | Living Room night light (sleep), Kitchen Hallway, Guest Bedroom 2 Hallway, Study A entries all source `mmwave`/`motion`, none `ble` | `ura_activity_log` 05Z-11Z |
| zone_3 (Kitchen's zone) | sleep->away 6 on 10-20 vs 5-11 every other night, so not BLE-correlated | `ura_activity_log` |

Whether Oji was truly wandering (radars and PIRs show real house activity that night) or the phone was moved: UNKNOWN; but no URA action depended on it.

## 4. Bug class / follow-ups (no changes made)

- Class: trust decision keyed to a flapping resolved location (consumer reads exact-room match with no neighbour tolerance). Related to Bug Class "stale/flaky data source" (#7) and the BLE-extend design in BLE-WARM-CREATE-1.
- Card BLE-LOCATION-QUALITY-1 should be scoped to the Jaya Bedroom extend leg; its idea 1 was already "not supported" per kanban.
- Optional: the 10-24 night (199 min bedroom vacant, URA location Bathroom 275.6 min) is an extra, unexamined instance with no zone_2 retreat; confirms recurrence but no extra actuation.
- Not examined: `Invalid transit` log volume and Jaya intra-room `room_transitions` rows polluting next-room learning (display/learning only).

## 5. Files

- `/Users/okosisi/Code/universal-room-automation/docs/planning/AUDIT_ble_flap_harm_2026_10_25.md` (this file)
