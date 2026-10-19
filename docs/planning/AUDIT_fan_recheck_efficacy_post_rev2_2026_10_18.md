# AUDIT: fan-recheck efficacy after Rev 2 (read-only probe, 2026-10-18 ~20:30 CDT)

**VERDICT: BETTER for Study A (0 of 4 vacated verdicts undone vs 27 of 28 pre-Rev-2); SAME-ish / INCONCLUSIVE for Living Room (4 of 5 vacated verdicts were followed by occupancy returning within 700 s, but with the fan OFF, so most likely real return, not the old restore loop). The restore-loop mechanism itself is demonstrably gone (fan_restored=false on 9/9 vacated verdicts). Sample is tiny (9 post verdicts) and the pre-baseline cannot be reproduced like-for-like (see Limits).**

Read first: `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` Fan pause-recheck section (~lines 338-360, read), `docs/planning/PLANNING_fan_noise_running_rejection.md` C1 (lines 121-135, read). Prober only; no edits, no HA state changes.

## 1. Rev 2 version and deploy date
- Code: commit `05f6b1888` "fan-noise running rejection Rev 2 (C1a-C5)", 2026-10-11 13:08 CDT, plus review fix-ups through `77e5403a1` 13:31 CDT. Merge `7b650279c` 18:08 CDT.
- Released as **v5.103.51**, commit `ca698c64d` 2026-10-11 18:09:12 CDT ("Running-fan false presence fixes"; `docs/readmes/README_v5.103.51.md:3`). `git log` source.
- Exact HA restart time unknown (no log access). Corroboration: two pre-restart vacated outcomes in `ura_activity_log` (Study A 17:57:36 CDT, Living Room 18:01:00 CDT) show the OLD behaviour (fan turned back on +3 s after the verdict, recorder `fan.polyfan_dreo704s_wifi_studya` on at +3 s; `fan.towerfan_dreopilotmaxs_wifi_livingroom` on at +3 s). Every later vacated verdict shows `fan_restored:false`.
- Later confounders: v5.103.53 (10-11 20:56, capability-routing + `fan_recheck_outcome` memory writer live) and v5.103.54 (10-12 09:01, "running-fan release ignores radar motion bits"). Post window therefore bundles Rev 2 + these.

## 2. Outcomes before vs after
Sources: `memory_episodes` (episode_type `fan_recheck_outcome`, attrs_json; rows exist only since 10-12 03:18 UTC because the writer shipped in v5.103.53), `ura_activity_log` (action `fan_recheck_outcome`, from 10-11 13:54 CDT, so it covers the pre-deploy hours), HA recorder `/config/home-assistant_v2.db` (retention starts 2026-10-11 04:12 CDT, so the 10-04..10-11 window of the original probe is GONE).

Verdict rows (episodes, de-duplicated; follow-up rows with `manual_fan_on_followup` key excluded), 2026-10-11 evening to 2026-10-16:

| room | vacated | occupied_confirmed | aborted (arm_expired_ineligible / ble_l1 / motion) |
|---|---|---|---|
| Study A | 4 | 10 (9 window-complete, 1 cancel) | 6 / 8 / 0 |
| Living Room | 5 | 16 (12 + 4 cancel) | 10 / 2 / 2 |
| Kitchen | 0 | 6 | 5 / 1 / 0 |
| Jaya Bedroom | 0 rows, never armed | | |

No outcome rows after 2026-10-16 03:44 CDT. Fan-on-while-occupied minutes per day (recorder): Study A 316/492/350/17 on 10-11..14, then 0; Living Room 362/148/163/109/50/134 on 10-11..16, then 0. The silence after 10-16 is fan non-use (cooler weather), not a recheck regression. Not proven by logs (none available).

### Like-for-like "undone" metric on the 9 post-Rev-2 VACATED verdicts
Definition (from planning doc line 123): room occupied binary re-asserts on within 700 s of the release. I also report whether the fan came back on. Recorder entities: `binary_sensor.study_a_occupied`, `binary_sensor.living_room_occupied`, `fan.polyfan_dreo704s_wifi_studya`, `fan.towerfan_dreopilotmaxs_wifi_livingroom`. Verdict time = `started_at` UTC in `memory_episodes`.

| # | room | verdict (CDT) | occupied back <= 700 s | fan state after |
|---|---|---|---|---|
| 1 | Living Room | 10-11 22:57:37 | no (15 min watched) | off, stayed off |
| 2 | Living Room | 10-12 22:27:21 | YES at +56 s | on at +156 s |
| 3 | Study A | 10-12 22:34:23 | no | off |
| 4 | Study A | 10-13 14:20:23 | no | off |
| 5 | Living Room | 10-13 16:19:14 | YES at +201 s | on at +309 s |
| 6 | Living Room | 10-13 19:37:44 | YES at +44 s | on at +75 s |
| 7 | Study A | 10-14 00:30:57 | no | already on at verdict (manual follow-up flag true), off at +303 s |
| 8 | Study A | 10-14 04:20:50 | no | already on at verdict, off at +301 s |
| 9 | Living Room | 10-16 02:05:45 | YES at +496 s | on at +626 s |

Counts: **Study A 0/4 undone; Living Room 4/5 undone; total 4/9.**
- Before (Study A, 10-04..10-11 recorder, from planning doc line 5/123, NOT reproducible now because the recorder window is purged): 27/28 undone, median ~60 s.
- Before, in-window sample: 2 vacated verdicts pre-restart on 10-11 (Study A 17:57, Living Room 18:01). Neither bounced inside 700 s (Study A none in 870 s; Living Room re-asserted at +803 s), but the fan was restored ON at +3 s in both (old behaviour). n=2, not informative for the occupancy metric.
- In all 4 undone Living Room cases the fan was OFF when occupancy came back and the fan turned on afterwards (occupancy first, fan 30-150 s later). That is the normal fan logic reacting to returning occupancy, the opposite order of the old loop (restore-ON first, radar latches after). I cannot prove from recorder alone that these were real people (no BLE join done for Living Room); treat as "probably real returns, unverified".
- A crude recorder proxy (any occupied on->off with a fan-on in the prior 15 min, bounce <= 700 s) gave pre-restart 10-11 04:12-18:09 CDT: Living Room 11/14, Study A 2/8; post: Living Room 22/43, Study A 8/25. This is polluted by non-recheck releases and a 14 h pre window; do not use as the verdict.

## 3. Jaya Bedroom, 2026-10-12 15:28-17:38 CDT: why the recheck never armed
Facts (recorder):
- 15:27:32 `fan.fanswitch_treat_wifi_jayabedroom` -> on in the same second `binary_sensor.jaya_3_presence` went unavailable; jaya_3 -> on 15:27:52. (Looks like a device/network reconnect event; who or what turned the fan on is unknown.) `binary_sensor.mmwave_zigbee_jayabedroom_presence` went off at 15:31:23 and stayed off, so `jaya_3_presence` (ESPHome LD2410) alone held the room occupied.
- `person.jaya` not_home at 15:24:22 and 15:30:29; home again 17:46:02. `sensor.universal_room_automation_jaya_location` = "Away" for 100% of 15:28-17:38. **The room was empty. This hold was a true phantom.**
- 17:37:24 fan off; 17:38:02 `jaya_3_presence` off (38 s later) and occupied released. `memory_episodes` id 13270 phantom_retro confirms (`release_delay_s` 38.6, `hold_s` 7791.9).
- House state `home_day` (`house_state_log` id 8071 shows home_day -> home_evening at 18:00 CDT), so the bedroom sleep veto (`presence_fan_recheck.py:561-567`, FAN_TRUST_STATES = home_night/sleep/waking) did NOT apply.

Why no arm (code, config; live veto counters not readable from here, so this is an inference, not an observation):
- Jaya Bedroom config entry `01KJXMA4VRMZZ337N8YNKV7KJQ`: `room_type bedroom`, `area_id jaya_bedroom`, `scanner_areas ['jaya_bathroom']`, `room_fan_recheck_enabled True`, `fan_control_enabled True`, `fan_recheck_trust_sensors_ok True`, `fan_recheck_l2_allowed True` (`.storage/core.config_entries`).
- `person_coordinator.py:983-984`: Tier 1 only if `area_id and not scanner_areas`. Jaya Bedroom has scanner_areas, so `get_ble_tier` = 2 (`person_coordinator.py:1643+`).
- `presence_fan_recheck.py:112`: `HIGH_STILL_RISK_ROOM_TYPES = {bedroom, media_room}`. `:711-714`: on the Tier 0/2 path, `if room_type in HIGH_STILL_RISK_ROOM_TYPES: veto("high_still_risk")` is unconditional (before the trust_sensors gate). The only arm paths are Tier-1 L3 (`:677-680`) or Tier-1 L2 (also blocked for high-risk types at `:696-700`).
- **Conclusion: a bedroom with scanner_areas (Tier 2) can never arm the fan recheck, at any hour.** `get_room_attrs` veto counters (`fan_recheck_veto_counts`) would show `high_still_risk` > 0; they are `_unrecorded_attributes` (`sensor.py:17663`) and not in `core.restore_state`, so I could not read them. Zero Jaya rows in `ura_activity_log` fan_recheck_arm/outcome/cancel and zero in `memory_episodes` is consistent. Falsifier: reading `sensor.jaya_bedroom_jaya_bedroom_bedroom_4_fan_recheck_state` attribute `fan_recheck_veto_counts` live; if `high_still_risk` is 0 the inference is wrong.
- Consequence for the original card JAYA-FAN-STILL-PHANTOM-1 (commit `85fa199eb`: "enabling fan_control -> shipped pause-recheck covers"): that closure is not true for this room's configuration.
- Design note: here BLE said Away (L1 absent, whole-house `Away` for the person), so the high-still-risk guard blocked a case where the BLE evidence of emptiness was strong. The guard exists for the sleeping-still-person case; it does not distinguish "resident BLE says elsewhere/away" from "no BLE evidence". Whether to relax that is a design decision, not made here.

## 4. phantom_retro labels on Jaya overnight holds (10-13, 10-16)
`memory_writers.py:150-210` writes phantom_retro whenever fan-off is followed by mmwave-off within a window and hold >= min hold; `room_capabilities` stored is `has_ble:false, has_pir:false, has_camera:false` (it does not consult person location).

| ep | hold ended (CDT) | hold_s | release delay | Jaya location during hold | verdict |
|---|---|---|---|---|---|
| 13270 | 10-12 17:38 | 7792 | 38.6 s | Away 100% (15:28-17:38) | TRUE phantom |
| 13368 | 10-13 06:50 | 33438 (~9.3 h) | 47.7 s | `universal_room_automation_jaya_location`: Jaya Bedroom 98%, Jaya Bathroom 2% (21:33-06:50); `person.jaya` home 20:16 -> not_home 07:10; `sensor.iphone_jaya_area` Jaya Bedroom 99% | WRONG label: she was in the room; hold was legitimate |
| 14133 | 10-16 07:22 | 29176 (~8.1 h) | 25.7 s | location: Jaya Bedroom 97% (23:16-07:22); iphone area Bedroom 97%; `person.jaya` home 22:59 -> not_home 07:35 | WRONG label |

In the two overnight cases `binary_sensor.mmwave_zigbee_jayabedroom_presence` cycled on/off all night (body motion, not a fan signature) and the final release came 25-48 s after fan off, which is simply her leaving in the morning around the time the fan was switched off. "Fan off then release shortly after" is a weak correlate at wake-up. phantom_retro should be gated on person location (not at home / in another room) before labelling `phantom`; this would have separated 13270 (Away) from 13368/14133 (in bed). Note the location history for 10-13 and later is retained in the recorder only from 10-11 04:12.

## Limits
- No HA log access (no journalctl on the HA host, `docker logs` permission denied, `ha core logs` 401, `home-assistant.log` absent), so "FanRecheck" log lines were not mined.
- Recorder retention begins 2026-10-11 04:12 CDT; the 7-day pre-deploy window used for 27/28 is gone. Pre-baseline is therefore the quoted figure only.
- Sample sizes are small (9 post verdicts, 4 Study A). Study A 0/4 vs 27/28 is strongly suggestive, not statistically tight. Living Room had no pre-Rev-2 measurement.
- Post window mixes Rev 2 with v5.103.53/54.

## Queries (reproducible)
- `ssh ha "sqlite3 -readonly /config/universal_room_automation/data/universal_room_automation.db \"select node_id, json_extract(attrs_json,'$.verdict'), json_extract(attrs_json,'$.reason'), count(*) from memory_episodes where episode_type='fan_recheck_outcome' and json_extract(attrs_json,'$.manual_fan_on_followup') is null group by 1,2,3\""`
- `... "select timestamp,room,description,details_json from ura_activity_log where action='fan_recheck_outcome' order by id"`
- `ssh ha "sqlite3 -readonly /config/home-assistant_v2.db \"select m.entity_id,s.state,s.last_updated_ts from states s join states_meta m using(metadata_id) where m.entity_id in (<room occupied + fan + person.jaya + sensor.universal_room_automation_jaya_location>) order by s.last_updated_ts\""`, then bounce/duration analysis in a local script (scratchpad `an.py`).
