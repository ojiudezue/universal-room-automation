# AUDIT: house_state=guest at 2026-10-17 21:06:46Z (16:06 CDT)

Prober run, read-only. Written ~16:50 CDT (21:50Z). Read first: PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md (complete), IDENTITY_FUSION manual (guest/census grep), cards GUEST-FALSE-POSITIVE-JAYA-ONLY-1, GUEST-FP-RESIDUALS-1, CENSUS-GUEST-FLOOR-1, GUEST-COUNT-DEDUP-MIGRATE-1, two memory files.

## VERDICT
**Can't tell whether a second person is home. The trigger was NOT the census.** It was Path B (guest-room sustained unknown occupancy), and Path B cannot tell a resident from a guest in a room where it has no BLE fix on the resident.
- "False positive" is NOT established. The evidence leans toward a real second body in the upstairs guest rooms (see Guest-home evidence), which contradicts "only Jaya is home".
- Revised after the operator update (a guest staying a month, whereabouts unknown): GUEST is plausibly CORRECT.
- The wifi-guest device list was not pulled (a query that enumerates device_tracker hostnames was declined). The camera detection pull was not done.

## 1. Producer path (exact)
- `presence.py:6060-6081`: in HOME_* states, `guest_armed = guest_room_gate_armed` ONLY (GUEST-CENSUS D2, 2026-08-16). Path A (`_guest_gate_armed`, :5537) is computed but does not arm GUEST.
- `_guest_room_gate_armed` (:5485): fires when a room flagged `is_guest_room` has `first_seen` set, no known person in it, and elapsed >= `room_guest_occupancy_threshold_min` (30).
- Guest rooms (core.config_entries, live): Guest Bedroom 1 (`binary_sensor.guest_bedroom_1_occupied`) and Guest Bedroom 2 (`binary_sensor.upstairs_guest_bedroom_occupied`), both threshold 30.
- `first_seen` is armed by `_handle_guest_room_occupancy_change` (:5337) when the room goes ON and `_is_known_person_in_room` (:5405) is False. That check only compares person_coordinator `location` strings to the room name.
- Recorder timeline (UTC):
  - 20:36:36 `upstairs_guest_bedroom_occupied` off->on. No off transition afterwards until 21:47:27, so it was continuous.
  - Jaya's `sensor.universal_room_automation_jaya_location` at that moment was "Jaya Bedroom" (20:34:00-20:38:30), not Guest Bedroom 2. So the occupant counted as unknown.
  - 21:06:36 = 20:36:36 + 30 min.
  - `house_state_log` id 8353 at 21:06:39.57, trigger=periodic, confidence 0.9 (= the room-only path confidence, :6098). Sensor updated 21:06:46. A 3 s match.
- The 15 min before the flip, `census_snapshots` (house zone), every row (20:50:24 ... 21:06:24 and after):
  - identified 1 ["jaya"], unidentified 0, total 1, confidence low.
  - `unidentified_persons` = 0 and `camera_unrecognized` = 0.
  - Same clean-census signature as the 09-15 probe on GUEST-FALSE-POSITIVE-JAYA-ONLY-1. Path A could not have armed.
- Upstream drivers of GB2 occupancy:
  - Matter mmWave `binary_sensor.mmwave_motion_lux_matter_wifi_guestbedroom2_occupancy` (a `presence_sensors` entry), continuously ON 20:36:36 -> 21:36:33 (a 54 s blip), then ON until 21:42:25.
  - Meross `..._guestbedroom2_sensor_presence_motion` pulsing off/on every few seconds to minutes.
  - GB2 has no BLE scanner of its own (`scanner_areas: ['guest_bedroom_2_closet']`). In the last 10 days Jaya's location was never "Guest Bedroom 2" (it showed GB1 18x, GB1 Bathroom 47x, GB2 Bathroom 9x, Up Guestbedroom Closet 2x).
  - So the known-person exclusion cannot protect a resident dwelling in GB2.

## 2. Latch and release
- No sticky latch beyond hysteresis. GUEST holds while `_guest_room_gate_armed` stays True. In GUEST the evaluation is still the room gate (:6077-6082).
- Release:
  - First_seen is cleared when the room's URA occupied turns off (:5370-5380), or when a known person is in the room. Then `infer()` returns `_time_based_home` (:1329).
  - Exit needs the quiet condition for >= guest persistence (300 s, CM option `guest_mode_persistence_seconds`) via the `guest_exit` veto (:6745-6790), then GUEST hysteresis 300 s (house_state.py:137, already satisfied).
  - Release does not depend on who is home. It can happen with only Jaya home, because it keys on the room sensor going quiet.
- Live: GB2 URA occupied went off 21:47:27 (mmWave quiet 21:42:25 + 300 s occupancy_timeout). So the exit window started ~21:47:27 and the expected exit is ~21:52:30Z. At the last check (21:48:23Z) `house_state_log` still showed guest as the latest row. Falsifier: if the state is still guest after ~21:55Z, the model is wrong.
- Re-arm risk:
  - `guest_bedroom_1_occupied` went ON 21:43:17 (GB1 Matter mmWave). Jaya's location is "Jaya Bedroom", not GB1, so GB1 `first_seen` is armed at 21:43:17.
  - If GB1 stays occupied unbroken to ~22:13:17Z, GUEST re-arms. This is a prediction, not an observation. Falsifier: GB1 occupied off before then, or Jaya resolving to GB1.
- GUEST -> SLEEP is not a valid transition (house_state.py:116-121). GUEST exits to a HOME_* state first, then SLEEP.

## 3. What GUEST is changing (consumers)
Consumers found by grep, with what each did since 21:06Z:
- HVAC maps guest -> "home" preset (`hvac_const.py:1293`).
  - Preset writes at 21:19:43 (zone 1) and 21:19:47 (zone 3), `decision_log` situation `house_state_guest` reason `house_state_transition`, away -> home. Zone 1 went back to away at 21:39:45 (vacant_past_grace); zone 3 had no recorded change after 21:19:47 (an earlier statement that it also returned to away was incorrect). The same away/home cycling occurred under home_day (20:13, 20:40, 20:59), so there is no distinguishable guest effect.
  - Zone 2 preset manual -> home at 21:44:45 labelled house_state_transition. Not attributable to guest; I did not confirm what drove it.
  - Guest-mode actuation switch is ON, rollout zones = [zone_3]. `sensor.ura_hvac_coordinator_active_preset_overrides` at 21:35: `by_zone {}`, `resolved_ranges {}`, `house_state guest`. No guest range overrides applied; zone 3 "skipped_already_correct", last write 10-13.
  - Dynamic-preset guest offset reset (`dynamic_preset.py:861`): no offset keys in config, so moot.
- Security: `_HOUSE_STATE_TO_ARMED["guest"]=ARMED_HOME` (`security.py:173`). Live `security_armed_state` = disarmed, `state_driven_arming_last` = {}, last update 18:24:36. No state-driven arming fired. This is the highest-consequence consumer; it did not act.
- Exterior-person NM severity: guest = MEDIUM (`const.py:2295,2389`), versus LOW when someone is home in home_day. Perimeter alerts at 21:14 and 21:18 were MEDIUM. Minor.
- Bayesian predictor learning suppressed during guest (`__init__.py:3325`). Occupancy-anomaly alerts suppressed (`binary_sensor.py:3418`). Arrester holds preserved across guest (`hvac_const.py`). Routine forecaster treats guest as passthrough.
- Wall-panel brightness automation: guest 80 vs home_day 100 (`automations.yaml:8270`). Cosmetic.
- `binary_sensor.ura_presence_coordinator_guest_mode` ON since 21:07:04.

## 4. Parked-card revival triggers
- GUEST-FP-RESIDUALS-1 trigger: "revive if guest entries resume above ~1/day, or any GUEST flip with unidentified_count > 0".
  - The first clause HAS FIRED. `house_state_log` guest entries per day since 09-17: 3, 1, 1, 1, 1, 1, 4, 3, 3, 2, 5, 2, 4, 3, 1, 2, 1, 1, 1. Roughly 2.2/day, vs "zero since 09-10" at the time of closure.
  - The second clause did not fire this time (unidentified 0).
  - Caveat: a long-term guest is staying in the house, so many of these may be real.
- GUEST-FALSE-POSITIVE-JAYA-ONLY-1 (closed REFUTED): its mechanism finding (Path B, clean census) is reproduced exactly.
- B1 (camera room->outdoor filter): not relevant here.
- CENSUS-GUEST-FLOOR-1: its premise (wifi floor excluded from the formula) holds. `wifi_guest_floor` is diagnostic only (`camera_census.py:4531`, `sensor.py:3702`), so 3->4 at 20:12:54Z did NOT drive GUEST. The census stayed clean while the floor read 4. The recency filter is 4 h (`const.py:3779`) and the census looks at essid = guest SSID, so 4 non-family phone-like devices connected within 4 h. Which devices is unknown.
- GUEST-COUNT-DEDUP-MIGRATE-1: done (v5.83.0); `unexpected_person_detected` shows guest_count 0, camera_total 1, ble_total 4.

## 5. Guest-home evidence (operator update)
Verdict: **can't tell, leaning toward a second body present as of 20:36Z-21:43Z.**
- Occupancy: the GB2 mmWave was continuously occupied 65 min (20:36-21:42) with Jaya's phone showing Kitchen/Breakfast Nook/Patio/Jaya Bedroom. Not consistent with Jaya's phone being in GB2.
- Transit: GB2 went off at 21:42:25, one camera body was seen unidentified 21:42:46-21:43:16 (`persons_in_house` 1->2->1), and GB1 turned on 21:43:17. This looks like a single body moving GB2 -> hallway -> GB1.
- Jaya's phone "Jaya Bedroom" since 21:30:30 and static. Two readings fit:
  - (a) Jaya without her phone (phone left in her room).
  - (b) a second person upstairs.
  Cameras and sensors cannot separate the two.
- Crossings today (`person_entry_exit_events`, UTC):

  | Time | Direction | person_id | Camera | Peak |
  |---|---|---|---|---|
  | 05:11:17 | entry | jaya | doorbell_lite | 1 |
  | 11:46:23 | entry | (blank) | garage_a | 1 |
  | 11:50:22 | exit | jaya | garage_a | 1 |
  | 20:13:10 | entry | jaya | doorbell_lite | 1 |
  | 20:14:31 | exit | (blank) | doorbell_lite | 0 |
  | 20:23:10 | exit | jaya | garage_a_2 | **2** |
  | 20:39:10 | entry | (blank) | doorbell_lite_2 | 1 |
  | 20:46:15 | exit | (blank) | front_door_aerial | n/a |

  - The 11:50 exit is attributed to "jaya", not to an unnamed person. The operator-recalled guest exit at ~11:50Z is therefore not corroborated as a guest in this table.
  - The 20:23 exit with peak 2 means two people left via garage A. That fits the GB2 sensors going quiet at 20:22:42.
  - Re-entry is 20:39 (unnamed), after GB2 went ON at 20:36:36. Entry attribution is imprecise.
- The house was `away` from 19:55Z with `persons_in_house` 0 (so no guest in the house at that time per BLE/camera/occupancy) until Jaya arrived at 20:10Z. Anyone in GB2 afterwards arrived at/after 20:10Z.
- 20:45:24-20:46:46 `persons_in_house` 3 with 2 unidentified, then 0: two unidentified bodies near Foyer/Receiving Room for ~1.5 min, then an unnamed exit at 20:45:30 (front_door_aerial).
- Not done (blocked or out of scope):
  - (c) The wifi-guest device list, not run (a hostname-enumeration query was declined).
  - (b) Interior/egress camera person detections, not pulled.
  - Face/identity of the GB2 occupant, unknown.
  - Light/fan activity in GB1/GB2, not pulled.

## Smallest safe remedy (none applied)
- Do NOT touch the live state yet. If a guest is in fact staying, GUEST is correct and every consumer above was a no-op or benign.
- If the occupant turns out to be a resident: add the guest-room resident exclusion for the one gap measured, the missing GB2 BLE fix. Config-first options: give GB2 a direct scanner area, or add the resident to the occupant-known check by borrowing; neither is a code change. A code remedy would be a separate Tier 2-DB card (revive GUEST-FP-RESIDUALS-1 on the fired trigger).
- A long-term guest staying in a flagged guest room will, by design, hold or re-arm GUEST while the room is occupied; that is correct behavior.

## Re-probe (appended 2026-10-17 ~16:58 CDT / 21:58Z) — items not done above
Read-only. Sources: HA recorder (`ssh ha sqlite3 /config/home-assistant_v2.db`), URA DB `census_snapshots` / `person_entry_exit_events`. No camera images viewed. Operator approved the WiFi enumeration 2026-10-17.

### VERDICT: can't tell. Leans "guest NOT detected home right now", low confidence.
- For away: the one guest-candidate phone has been off WiFi ~36 h; no interior detection of anyone between 11:50Z and 20:12Z; the census right now reads house = 1 (jaya), unidentified 0 (rows to 21:54:55Z).
- For a second body: GB2 mmWave/bathroom activity 20:13-21:46Z and GB1 motion 21:43-21:51Z while Jaya's phone sat static in "Jaya Bedroom". Only fits a second person if Jaya was phone-less. Nothing here separates the two.

### 1. Guest WiFi
- Producer: `camera_census._get_wifi_guest_count` (camera_census.py:5649). `CONF_GUEST_VLAN_SSID` is live "Revel" (core.config_entries). Counts router-sourced device_trackers that are `home`, on essid Revel, with a non-empty hostname outside NON_GUEST/TABLET prefixes, not a family tracker/MAC, and with last_changed within 4 h (const.py:3779). Diagnostic only (`wifi_guest_floor`).
- Every Revel device with a phone-like hostname in the last 4 d (recorder, 21:55Z):
  - `device_tracker.unifi_default_0e_a8_a4_be_6d_7e`, host "MacBookAir", private MAC. Home 10-11..10-16 in bursts, not_home 10-17 03:25Z-18:24Z, **home since 20:12:52Z** (same minute Jaya arrived). It roamed APs at 20:14:44, 21:29:53 and 21:31:24Z, so it is moving with someone. **Connected now** (last update 21:31:24Z). Owner unknown: Jaya's own Mac is a different tracker (`jayas_macbook_air_4`, MAC E2:03:74:04:55:E5, no states today).
  - `device_tracker.unifi_default_02_f0_d7_b5_e4_cd`, no hostname, private MAC (02:..). Seen on Revel 10-14 00:31Z through 10-16 12:31Z (daily ~02-04Z and ~12:22-12:31Z), last home 10-16 15:15Z. **not_home now, ~36 h absent.** Persistent across days, so this is the best guest-phone candidate. It has an empty hostname, so `_get_wifi_guest_count` skips it anyway (Filter 1).
  - `device_tracker.iphone_4` (MAC 06:7b:aa:d0:af:aa): home 10-14 12:26Z-10-16 12:30Z, 2 rows only. Not home now.
  - `device_tracker.unifi_default_5a_77_3f_c6_f9_ae` "Watch": home 10-13 21:56Z-10-14 10:10Z, then off. `unifi_default_9c_b8_b4_9c_1c_52` "Watch" is still home, static (stale-looking, 18:24:38 restore row).
- Not in the formula: the empty-hostname phone. A recency window is moot for it.
- Limit: I enumerated 4 d of recorder history only. First-seen before 10-13 is unknown, so I can't prove "a month".
- 4 h count of 4 earlier (20:12:54Z) is explained by the Mac plus other family/unclassified clients, not verified per device.

### 2. Cameras after 11:50Z (detection state only)
- **11:50Z-20:12Z: no interior person detection at all** (staircase, stairs_top, upstairs_hall, playroom, family_room, living_room, foyer: all off). Exterior only: hot_tub 12:54-15:05Z (many), utilities_ptz 13:06/15:31/17:05/19:45Z, rear_ptz 13:27/15:30Z, front_side_ptz 18:49-19:42Z (many), madrone entry/front_door_aerial 16:13Z, reolink porch PTZ 15:58-17:3xZ. Consistent with the house being empty indoors and someone outside. (Whether those outdoor people are the guest is not determinable from state.)
- From 20:12Z: doorbell/garage_a/g5_bullet 20:12-20:14 (Jaya entry, person_id jaya), garage_a 20:22 (exit peak 2 at 20:23, jaya + one unnamed), doorbell 20:38 (unnamed entry), family_room/living_room/foyer/master_hallway 20:44-20:46 (census: 2 unidentified + jaya = 3, then exit 20:46:15 unnamed via front_door_aerial; `unexpected_person_detected` ON 20:45-20:46).
- Upstairs: stairs_top/upstairs_hall/staircase/playroom detections at 20:13, 21:21, 21:26, 21:30, 21:35-37, 21:41-42, then staircase + garage-hallway 21:42-21:52Z (latest 21:52). `unexpected_person_detected` ON 21:42:xx-21:43.
- Unrecognized faces: none persisted. `census_snapshots` (house) 21:49-21:54Z = identified ["jaya"], unidentified 0, total 1. Unidentified > 0 rows today: property zone 20:08-20:42Z and 21:19-21:23Z (exterior bodies), house zone 20:45Z (2).
- Crossings since 20:46:15Z: none (`person_entry_exit_events` max id 8640). The 11:50:22Z exit is named "jaya".

### 3. Guest rooms 1 and 2 (UTC, today)
- GB2 (`upstairs_guest_bedroom_occupied`): on 20:14, off 20:27, on 20:36:36, off 21:47:27. Matter mmWave on 20:13-20:22, 20:36-21:36, 21:37-21:42:25. GB2 bathroom occupied 20:22-20:41 and 21:35-21:46, with its room-lights switch on 20:22-20:32, 20:33-20:41 and 21:35-21:46 (the lights are URA-actuated; they show the room sensor, not a manual switch).
- GB1 (`guest_bedroom_1_occupied`): **ON now** since 21:43:xx (mmWave on 21:43, off 21:44, on 21:44-21:51:06; URA occupied still on 21:51:30). Motion 21:43-21:51Z. No GB1 activity before 21:43Z today.
- Lights, fans, covers: nothing turned on by hand. All bedroom lights/fans/ceiling fans off; the only "on" is the URA-driven GB2 bathroom lights. Covers closed (unavailable blips at 13:4x/14:0x Z are the restart). No manual-mode or override changes visible.
- Door contacts `openclose_aquara_zigbee_dnguestbedroom_contact` / `_2`: unavailable, no usable data.
- Nothing from 11:50Z to 20:13Z in either room: both rooms were quiet while the house was empty.

### 4. Verdict: see top. The decisive missing input is whose the MacBookAir is, which can only come from the operator.
- A single falsifier: if the "MacBookAir" disconnects/reconnects with Jaya's phone moving in sync, it is Jaya's. If it moves while her phone is static (as at 21:31Z vs phone static since 21:30:30Z), it is not hers.
- That timing already points to the Mac belonging to someone other than the phone carrier, or to Jaya having left the phone. I did not verify which.

### 5. Does `sensor.universal_room_automation_last_person_entry` re-read person_id after an entry is named later?
**No.** `LastPersonEntrySensor` (sensor.py:4837-4893) subscribes only to the bus event `ura_person_egress_event` (sensor.py:4855) and sets `_last_person_id = event.data.get("person_id") or "unidentified"` once at event time (sensor.py:4857-4868). It has no dispatcher subscription and no DB re-read. By contrast `LastPersonExitSensor` subscribes to `SIGNAL_EGRESS_EXIT_BACKFILLED` and re-reads the newest exit row (sensor.py:4913-4935). `SIGNAL_EGRESS_EXIT_BACKFILLED` has a single producer (camera_census.py:4698-4702), and `grep SIGNAL_EGRESS_ENTRY` finds nothing, so there is no entry-side backfill signal to listen to either. A late-named entry stays "unidentified" on the sensor. Consistent with the unnamed entries at 20:39:10Z (id 8639) in `person_entry_exit_events`.
