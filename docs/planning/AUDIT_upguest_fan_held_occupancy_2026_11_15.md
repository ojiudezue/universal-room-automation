# AUDIT: Upstairs Guest Bedroom (Guest Bedroom 2) held occupied in an AWAY house, with a fan and light left on (read-only, 2026-11-15)

Prober: read-only. No HA state changes, no edits to code/config/board/memory, no Bermuda diagnostics. Probe window: Sun 2026-11-15 14:24-14:35 CST (`date`).
Read first, completely: `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (1146 lines incl. section 10 ledger), `docs/architecture/SENSOR_FLEET_CLASSES.md`, HVAC STATE_OF_PLAY fan sections (4.2b, 4.2c, the fan/AWAY/paused-room lines; not all 750 lines). None of the ledger's corrected claims is re-asserted. Sibling audit (read, not duplicated): `docs/planning/AUDIT_mediaroom_fan_left_on_stuck_sensors_2026_11_15.md` (same class of problem, Media Room).

Code cites are the working tree = v5.108.25 (what HA runs since the 14:19-14:20 CST restart; `/config/custom_components/universal_room_automation/manifest.json`). Times are CST; the URA DB stores UTC (CST = UTC-6).

---

## 0. Answer

1. **The room is held by one input, not by the fan, and the fan is not demonstrated as the cause.** `binary_sensor.occupancy_lux_temp_humidity_hobeian_upguestroom_presence_2` (registry: platform `mqtt`, device `HOBEIAN` model_id **ZG-204ZV**, filed in `motion_sensors`, so MOTION-class per SENSOR_FLEET_CLASSES) has read `on` continuously since 13:51:48 with only 1.5-4 s `off` pulses (14:14:08, 14:31:26, 14:32:33). The room's Occupied reads `on`, `occupancy_source: motion`, `tier1_provenance: {motion: true, mmwave: false}` (`binary_sensor.upstairs_guest_bedroom_occupied`, live 14:25). The fan-noise machinery sees no fan problem: `fan_on: true`, `fan_interference_suspect: false`, `fan_interference_hold_active: false`.
2. **Nothing was corroborating it.** Upstairs guest hallway PIR: no `on` edge 04:00-10:16, then 10:16-10:52 and 12:30-13:09 only; closet PIR: none all day; MS600 Matter radar `on` only 10:51-10:52 and 12:59-13:02; MS600 `presence_motion` only the same two. The last human-evidence edge is the hallway PIR 13:09:47. House AWAY 13:43:29. So the ZV `on` from 13:51:48 (and the long runs 05:28-10:16 with no hallway or radar edge) is a false positive.
3. **Every failsafe was blocked by a specific gate** (table in section 3). The load-bearing ones: the room's Automation switch is OFF (paused) and its Fan Mode is `off` (person-owned fan), so fan recheck, zone sweep, AWAY sweep and room exit actions all stand down; and the one stuck-sensor rule that applies to a motion-class sensor (P22, 4 h continuous-on) is **reset by every observed 1.5-4 s off pulse**, so it never matures (it did fire once, 12:51:52, released the room at 12:56:23, then a pulse seen at 13:51:48 re-armed it).
4. **The "two fans" are one physical Tuya fan seen through two integrations** (cloud `tuya` and LAN `tuya_local`), same Tuya device id. URA controls the cloud one (`fan.fan_switch_4`). Neither reports `assumed_state`. The 14:19:53 "change" is the HA restart, not a transition. This is not one of the RF/Bond fans.
5. **Who turned the fan on: a person or app, device-originated, 2026-11-13 12:49:54** (no URA action, no HA service call, no user context), one second after the light was switched off the same way. The light has been on since 11-14 09:22:44 (device-originated). Nobody turned either off because URA is paused here and the exit light action is `leave_on`.
6. **The operator's idea (stuck sensor triggers a fan recheck) would not have caught this**, for reasons independent of the sensor (section 6). The simplest capture is an AWAY-while-held trip-wire plus a P22 timer fix; the config-first step is the sensor's sensitivity (16 of 19, the fleet's joint-highest, section 5).

---

## 1. The room (Q1): registry + config, read over `ssh ha` from `.storage`

Entry `01KCYSBVA2RMB5C3F1Z90F9X72`, title "Guest Bedroom 2", room_name "Guest Bedroom 2", `room_type bedroom`, zone Upstairs, `climate_entity climate.up_hallway_zone_2`, `room_is_guest_room: true`, `is_egress_window: true`. Merged config = `{**data, **options}`, options win.

| Item | Value | Source |
|---|---|---|
| Fans | `fan.fan_switch_4` (data and options) | `core.config_entries` |
| **Fan Mode** | **`off`** (`room_fan_mode`); `select.guest_bedroom_2_guest_bedroom_2_fan_mode` = off in every recorder row since 11-08 08:24 | options; live; recorder |
| `fan_control_enabled` / `hvac_coordination_enabled` | true in data, **false in options** (legacy keys; Fan Mode governs, `const.py:1453` `fan_owner`) | options |
| Fan recheck | `room_fan_recheck_enabled: true`, `fan_recheck_l2_allowed: true`, `fan_recheck_trust_sensors_ok: true` (switch `on`) | options; live |
| **Automation switch** | **`switch.guest_bedroom_2_automation` = off in every recorder row since 11-08 08:24** (paused). Manual Mode off, Override Occupied/Vacant off | recorder; live |
| Motion (`motion_sensors`, options) | (a) `binary_sensor.mmwave_motion_lux_meross_wifi_guestbedroom2_sensor_presence_motion` (meross_lan MS600 radar-derived bit); (b) `binary_sensor.occupancy_lux_temp_humidity_hobeian_upguestroom_presence_2` (**ZG-204ZV, MOTION-class**) | options; entity+device registry (`model_id ZG-204ZV`, `model` "Millimeter wave motion detection", area guest_bedroom_2, Z2M via mqtt, ieee `0xa4c13875760e0f23`) |
| Presence radar (`presence_sensors`) | `binary_sensor.mmwave_motion_lux_matter_wifi_guestbedroom2_occupancy` (MS600 over Matter) | options |
| `occupancy_sensors` | none | options |
| Lights | `switch.switch_sonoffm4rm_matter_upguest` (platform `sonoff`, relay MINIR4M, area guest_bedroom_2); alert light `light.entry_led` (off) | options |
| Light actions | `entry_light_action: none`, `exit_light_action: leave_on` (options; data says turn_on_if_dark / turn_off) | options |
| Covers | four `cover.bedroom_shade_*_combined`; `switch.guest_bedroom_2_cover_automation` off | options; live |
| Away veto | `comfort_fan_away_veto_enabled: true` (blocks comfort-fan turn-ON in AWAY only) | options |
| BLE | no scanner in the room; `scanner_areas: [guest_bedroom_2_closet]`; `person_visits` has no Guest Bedroom 2 row | options; URA DB |
| Sensor class table | ZV = motion (cannot hold a still person, fan-immune witness by capability), MS600 Matter = still-person holder, MS600 `presence_motion` = radar-derived bit, NOT a fan-immune witness | SENSOR_FLEET_CLASSES rules 1-3 + MS600 section |

Hobeian ZV tunables (live): `fading_time_2` 30 s, `motion_detection_sensitivity_2` **16** (range 0-19), unchanged since 11-08 (recorder). Fleet comparison, same 28 Z2M sensitivity numbers read live: most ZVs sit at 3-12; the three at 16 are this room, `hobeian_exercise_*_2` and `hobeian_garagea_*` (the Exercise unit is the one SENSOR-FANINDEP-1 measured as fan-tracking, 99.9 % on with fan on).

Context shared with the sibling audit: 20 of 47 room Automation switches read off for the whole recorder window; GB2 is one. Whether that is deliberate is unknown.

---

## 2. The two fan entities (Q2): one physical fan

Resolved through the entity and device registries (no name inference):

| | `fan.fan_switch_4` | `fan.fan_switch_upguest` |
|---|---|---|
| Platform / config entry | `tuya` (cloud), entry `01JPQV1T5N76EKG5VKT0BBF7NN` (the Tuya cloud account) | `tuya_local` (LAN), entry `01M3JAFVVMFFXCN0AP7SGJTS70` "Fan Switch UpGuest", `type treatlife_ds02_fan`, `poll_only false` |
| unique_id | `tuya.ebd7a4f31a77f10913zsag` | `ebd7a4f31a77f10913zsag-fan` |
| Device | `948b2070...` "Fan Switch UpGuest ", Tuya model_id `ylonohqukwrb2lv7`, identifiers `("tuya","ebd7a4f31a77f10913zsag")` | `8310c550...` "Fan Switch UpGuest ", identifiers `("tuya_local","ebd7a4f31a77f10913zsag")` |
| Same physical device | **yes: the Tuya device id `ebd7a4f31a77f10913zsag` is the identifier of both** | |
| Speed model | `percentage_step 1.0`, reads **1 %** | `percentage_step 25.0`, reads **25 %** (4-step fan, step 1) |
| `assumed_state` | absent (live attributes) | absent |
| URA | **configured fan of Guest Bedroom 2** (`options.fans`, data.fans); only room that lists it | not configured anywhere |
| Extra entity | | `time.fan_switch_upguest_timer` = 00:00:00 (device-side timer, unset) |

- It is a WiFi Tuya fan switch (tuya_local type name `treatlife_ds02_fan`; no RF path in either integration). Not an RF/Bond fan: the RF list (Media, Game Room, Guest Bedroom 1, Master Bedroom) is in the sibling audit section 6.3. Both entities agree on `on` and moved together on 11-13 12:49:54 (local 12:49:54 then cloud within the same second), so the state is not unreliable here. Whether the physical remote/wall button is RF is unknown.
- **The 14:19:53 `last_changed` is the restart.** Recorder rows for both fans exist at 11-14 12:48, 14:39, 16:06-16:07, 22:02 and 11-15 14:19 (cloud entity ~29 s after the LAN one), identical state/attributes each time; the five times coincide with the Hobeian `fading_time_2` going `unavailable -> unknown -> 30` (HA restarts). Only one real transition exists in the recorder window: `off -> on` 11-13 12:49:54.
- Consequences of the duplicate: (a) harmless for state truth today; (b) if Fan Mode were ever turned on, URA would write speed percentages to the cloud entity whose `percentage_step` is 1.0 while the fan is a 4-step device; the percentage mapping is unverified and a cloud outage would stall actuation while the LAN twin still works; (c) side finding: the presence fan listener's `fan_on_since` re-stamps at each restart (the two 11-14 `occupancy_phantom` episodes carry `fan_on_since` 14:40:00 and 16:07:27 CST, the restart rows of this fan; real on-time since 11-13 12:49:54), so `fan_on_duration_s` under-counts across restarts. Not pursued.

---

## 3. Why the fan stays on, and the light, with the house AWAY since 13:43:29 (Q3, Q5)

### 3.1 Who turned them on
Recorder + events (read-only), window 11-13 12:49:40-12:50:10:
- 12:49:53 `switch.switch_sonoffm4rm_matter_upguest` `on -> off` and URA's mirror `switch.guest_bedroom_2_guest_bedroom_2_room_lights` off, **no user id, no parent context, no `call_service` event** (device-originated: wall switch or the vendor app).
- 12:49:54 `fan.fan_switch_upguest` and `fan.fan_switch_4` `off -> on`, same shape (no service call, no URA row; no `ura_activity_log` row for the fan or this room's light at all since 11-11).
- Who: unknown (a person; the sequence reads like leaving the room). URA could not have: Fan Mode off and room paused (section 3.2).
- Light on since **11-14 09:22:44**, device-originated again (no service call/context; the Matter radar read `on` 09:22:39, a person entering); 11-15 02:02:47 the relay went `unavailable` for 47 s and returned `on` (device power-on state, `02:03:34`), no URA action. No `light_turn_on`/`light_turn_off` activity rows for the room's light since 11-11.

### 3.2 Failsafe-by-failsafe: the gate that blocked each (state at 14:25-14:35)

| # | Failsafe | Gate that blocked it | Evidence |
|---|---|---|---|
| 1 | Room vacancy exit (lights, switches, covers; never fans) | (a) the whole occupancy-change/exit block runs only `elif self._is_automation_enabled()` and the switch is off; (b) the room never vacated (held by the ZV); (c) even enabled, `exit_light_action` is `leave_on` | `coordinator.py:5717`, `:3615-3624`; `automation.py:1432-1445` (sibling audit table row 1); options |
| 2 | Fan recheck (pause, re-measure, drop occupancy) | In code order: `fan_control_off` (Fan Mode off, `fan_owner` None); `room_paused`; then, even if both were cleared, `not_radar_sole` (the tick source is the motion-class ZV, so the capability radar-sole ring is false) | `presence_fan_recheck.py:550-551`, `:555-556`, `:618`; `const.py:1453`, `:1467`; `coordinator.py:6168-6175`, `:4078`. `sleep_state` n/a (not a FAN_TRUST_STATE now). Episodes: `memory_episodes` for `room:guest_bedroom_2` has **0** `fan_recheck_outcome`, ever |
| 3 | D2 sustain demotion | Applies to radar-sole ticks. This tick is motion-class; `_d2_motion_sensors_present()` is true here (the ZV is a fan-immune witness by capability), so D2 would not demote a hold whose witness reads `on` | `coordinator.py:2254-2286`; attrs `mmwave_fan_demoted: false` |
| 4 | P24 4 h max-occupancy failsafe | Needs a fan-immune witness (present) AND stale PIR; the freshness stamp `_last_motion_bit_time` is refreshed every tick a `motion_detected` is true, and the ZV is `on`, so never stale. `failsafe_fired: false`; `failsafe_at 18:20:19` is only session start + 4 h | `coordinator.py:4422`, `:5099-5211` (freshness `:5181-5195`) |
| 5 | P22 continuous-on stuck exclusion (4 h) | **Fired once**: `automation_health` `stuck_sensor` 12:51:52 with `on_since 08:51:22`; room timeout expired and vacated 12:56:23. Then `_sensor_on_since` is dropped on the first tick that observes the sensor off; that happened 13:51:48 (state back to `normal`), so the sensor counted again and created the present hold at 13:51:50. Next possible exclusion: 4 h after the last observed pulse (14:32:35 pulse seen at 14:32:34/36) = ~18:32 | `coordinator.py:3717-3727`, `:2375-2400`, `:401`; recorder `sensor.guest_bedroom_2_automation_health` attrs |
| 6 | D2 duty-cycle stuck | Motion-class sensors are never candidates; candidates are `mmwave_sensors + occupancy_sensors` only | `coordinator.py:2142` |
| 7 | Chatter detector | Off pulses last 1.3-4 s; `T_floor` is 1.0 s and the burst needs K = 10 sub-floor intervals in 300 s, so a pulse of 1.3 s is not an "impossibility event". The `excluded_sensors` list in `automation_health` was `[]` throughout | `const.py:6020-6026`, `:6130`; `chatter_detector.py:495-535` |
| 8 | AWAY leave-on sweep | Lights only, `lights_leave_on_when_empty` list; also returns when the room Automation is off; edge-only | `automation.py:860-925` (`:888-897` paused skip); `coordinator.py:1016-1033` |
| 9 | Comfort-fan AWAY veto | Blocks comfort-fan turn-ON only, never turn-off; and Fan Mode off means URA never drives this fan | `fan_veto.py:1-20` |
| 10 | HVAC zone vacancy sweep (lights, manual devices, Follow-thermostat fans) | `zone.any_room_occupied` is true (GB2 is the only occupied room in zone 2: `sensor.ura_hvac_coordinator_zone_2_status.occupied_rooms == ['Guest Bedroom 2']`); the room is skipped when paused; fans only in Follow mode | `hvac.py:6775`, `:6827`; HVAC doc 4.2b / 4.2c |
| 11 | `turn_off_all_managed` / HVAC fan controller | Runs only when the HVAC fan switch is off, and only over `_room_fans`; GB2 is Fan Mode off (not HVAC-managed) | `hvac.py:2479-2482`; `hvac_fans.py:533-545` |
| 12 | Stuck-signal NM | Paged: `notification_log` 27411, 12:51:52 CST, MEDIUM, channel `digest`, "Stuck signal: continuous" (per-day latch means no second page). No page names the fan, the AWAY house or the held room | URA DB |
| 13 | AWAY-time "room still held" trip-wire | **Does not exist** (`zone_hold_all_away` is the opposite direction, held out of AWAY) | STATE_OF_PLAY section 9, sibling audit S/row 12 |

So the fan and the light are left on because nothing URA owns has authority over them here (person-owned fan, paused room, `leave_on` light) and the only thing that would otherwise end the hold (P22) was reset.

### 3.3 Cost of the hold (measured, not inferred)
Zone 2 (`sensor.ura_hvac_coordinator_zone_2_status`, live 14:25): `any_room_occupied: true`, `any_room_hvac_occupied: true`, `occupied_rooms ['Guest Bedroom 2']`, `preset_mode sleep`, `away_due_at null`. A false ZV `on` in a paused guest room is therefore the only thing keeping the Upstairs HVAC zone out of its away path while the house is AWAY. The HVAC D6 4 h stale-occupancy failsafe (STATE_OF_PLAY) is not verified here.

---

## 4. Why the room reads occupied (Q4)

Timeline of the sensor (recorder `binary_sensor...upguestroom_presence_2`, all CST; "pulse" = an `off` of 1.3-4 s):

| Time | What | Corroboration at that time |
|---|---|---|
| 11-13 12:49:54 | fan turned on by a person; ZV flaps 12:55-15:39 with room occupied cycles; quiet from 15:56:50 for 2 h 55 min with the fan still on | n/a |
| 11-13 15:56 -> 11-15 05:29 | ZV mostly off for ~38 h **with the fan running** (offs of 2 h 55 min, 4 h 23 min, 9 h 52 min, 7 h 24 min; short `on` episodes only at visit times, e.g. 11-14 09:08, 15:17, 19:20) | fan steady-on does not by itself latch the ZV |
| 11-15 05:28:45 | first `on` of the morning; 05:29-07:05 flaps every ~30 s (the "136 changes/24 h" the orchestrator saw; 99 rows 05:00-07:10) | hallway PIR silent, closet PIR silent, MS600 silent: nobody there. House `sleep` (woke 06:00) |
| 11-15 07:05:59 | settles `on`; pulses at 07:27, 07:30, 07:34, 08:29, 08:51 | hallway PIR silent until 10:16 |
| 08:51:21 | `on` run begins, 4 h 28 min unbroken | hallway PIR + Matter radar real visit 10:16-10:52; second visit 12:30-13:09 |
| **12:51:52** | P22: stuck exclusion engaged (4 h from `on_since 08:51:22`); occupancy `timeout` 12:51:52, **vacated 12:56:23** | |
| 12:59:27-13:07:02 | real visit (Matter radar on 12:59:27-13:02:01, hallway PIR 12:59:25) then vacated 13:07:02 | |
| 13:19:34-36 | 1.4 s pulse **not observed by the room** (stuck flag stayed, room stayed vacant) | none |
| 13:43:29 | **house AWAY** (`house_state_log`, UTC 19:43:29) | |
| **13:51:46-48** | 1.8 s pulse **observed**: stuck flag cleared 13:51:48 (`automation_health` back to `normal`), room `on` 13:51:50 `source motion` | none (last evidence 13:09:47) |
| 14:14:08-12 | 4 s pulse; room goes `timeout` 2 s then back to `motion` | none |
| 14:19-14:20 | HA restart; room re-created `on` 14:20:19 the moment the ZV read `on` | none |
| 14:31:26, 14:32:33 | two more pulses, one minute apart | none |

Mechanism, producer to consumer:
- **Producer.** The ZV (Z2M, `fading_time` 30 s, sensitivity 16) reports `on` for a presence-like signal the room cannot attribute; it holds `on` with very short gaps. (Why the sensor sees something from 05:28 is **unknown**, see 7.)
- **Room fusion.** A motion-class sensor `on` => `motion_detected` => `data[STATE_OCCUPIED] = True`, `occupancy_source "motion"` (`coordinator.py:4014-4033`, `:4387-4425`). The room tier consults no house state, so AWAY changes nothing. Occupancy is level-held while the sensor is `on`; the 5 min timeout never starts.
- **Is it fan-noise-classified?** No. The ZV is, by capability and device model, a fan-immune witness (`fan_veto.is_fan_immune_motion_witness`, SENSOR_FLEET_CLASSES rule 3: "URA treats ZV as a fan-immune witness in steady state; the ~5 min post-fan-on transient is NOT gated, FAN-ZV-POWERON-TRANSIENT-GATE-1"). The creation gate is retired to 0.0; D2 acts on radar-sole ticks; `fan_interference_suspect` false. URA's fan-noise rejection therefore never sees this hold.
- **Is it frozen/stuck/chatter/fresh?** None of the three machines currently classify it: not frozen (it pulses off), not chatter (pulses > T_floor, K=10), not P22-stuck (timer reset at 13:51:48 and again 14:14:12, 14:32:35), not D2 duty-cycle (motion-class excluded). It is a **level hold by an uncorroborated motion-class sensor whose 4 h stuck clock is reset by short off pulses**.
- **Consumers.** Room Occupied/Motion entities -> zone 2 `any_room_occupied` -> HVAC `any_room_hvac_occupied` (`hvac_occupied` attr `source: held`, `kinds_active.motion: true`) -> zone preset stays `sleep`; no light/fan effect because the room is paused. The operator's phone shows "Motion/Occupied: Detected" from the same entities.
- **Fan link (falsification).** Observations that would show a fan cause: ZV `on` edges ~2 s after a fan edge (SENSOR-FANINDEP-1 pattern in the Exercise unit) or clearing 60-75 s after fan-off. Here: the only fan edge in the window (11-13 12:49:54) was followed by a ZV re-trigger at 12:55:30-12:56:21, not ~2 s; the ZV was mostly quiet for ~38 h with the fan running; the 11-15 flapping began with no fan edge. So the fan is **not demonstrated**. It is also **not excluded**: this unit is on record as fan-latching (SENSOR-FANINDEP-1 origin, 2026-08-13, "the Upstairs Guestroom unit of this EXACT model fan-latched twice") and sits at sensitivity 16 like the proven Exercise unit. The cheap discriminator is a fan-off test (section 7).
- Side: two `occupancy_phantom` episodes (`mmwave_sole_fan_on_no_corroboration`, 11-14 15:58 and 19:20 CST, `house_state guest`) came from the **Matter radar**, which is fan-susceptible; that sensor is quiet today.

---

## 5. The operator's idea (Q6): stuck/chattering sensor -> fan recheck

Would it have caught this case? **No**, and the reasons are independent of the idea's merit:
1. The recheck is **config-vetoed first**: Fan Mode off (`fan_control_off`) and paused room (`room_paused`) (section 3.2 row 2). The operator's own ruling (HVAC doc 4.2b, B-M1) that a probe must not turn off a person-owned fan applies; a stuck trigger does not lift it.
2. The recheck is a **radar-sole tool**: it needs the capability radar-sole ring true for N ticks (`presence_fan_recheck.py:606-618`). This hold is a motion-class ZV. A stuck trigger would also have to widen the recheck to motion-class sensors, which SENSOR-FANINDEP-1 ("motion-class is corroborator-grade for stuck, not for fan demotion") argues against.
3. **There was no "stuck" flag at the moment of the incident.** P22 engaged 12:51:52 and was cleared at 13:51:48, so from 13:51:50 to now the room is held with `stuck_sensors: []`, `excluded_sensors: []` (live `automation_health`), `chatter` unflagged. A trigger keyed on those flags would have fired at 12:51:52, when P22 was already releasing the room by itself.
4. If it had fired, the result would be wrong: a hardware or ambient ZV that does not clear on fan-off returns OCCUPIED_CONFIRMED and the room stays held; a fan restore would re-light a person's fan.

Safeguards any version needs (from the recorded rulings and the sibling audit 5.3): never act on a person-owned fan (Fan Mode off) unless the house is AWAY with zero census, never on a paused room's fan without an AWAY gate, never restore ON for a fan with untrusted state, once per episode with the existing 900 s cooldown, zero-fire trip-wire (anomaly to NM) because the path is rare. Marginal-benefit view: the large component of both incidents is "house AWAY, a room still held, no action and no page". The simplest capture is the page; the recheck adds a rare-fire path into a shared 5-state machine.

---

## 6. Minimal fixes

### 6.1 Config-first (no code)
| # | Change | Rung / why | Evidence it helps |
|---|---|---|---|
| C1 | Lower `number.occupancy_lux_temp_humidity_hobeian_upguestroom_motion_detection_sensitivity_2` from 16 to about 8-12 (fleet median ~8-12; Jaya/Ziri/Media 8) | Rung 3 live knob, device-side. Operator to apply; one-shot, reversible | 16 is joint-highest of 28 ZV units; the Exercise unit at 16 is the proven fan-tracker; the PRESENCE doc already treats on-device tuning as a first-class lever (Addendum 2026-10-11) |
| C2 | Decide whether this guest room should stay paused: Automation switch ON gives the room-tier exit actions, the zone-sweep and recheck eligibility back; `exit_light_action` options `leave_on` and `entry_light_action none` would then be the light policy | Rung 3 switch + options flow. Operator ruling needed (20 rooms are paused; deliberate or forgotten is unknown) | Rows 1, 2, 10 of section 3.2 become reachable; row 2 still needs Fan Mode off -> Follow/Room temperature |
| C3 | Fan Mode for this fan: `room_temperature` or `follow_thermostat` instead of `off` only if the operator wants URA to own it; the cloud `fan_switch_4` percentage mapping must be checked first, or reconfigure the room to the LAN entity | Rung 3 select / options. Operator ruling (person-owned vs URA-owned) | Section 2 (speed model mismatch) |
| C4 | Remove the duplicate integration of the same Tuya fan (keep one: LAN `tuya_local` or cloud `tuya`) | HA-side integration setting; operator | Section 2; removes the two-entity ambiguity before any Fan Mode change |
| C5 | One-time physical: turn the fan and light off (the operator left them for diagnosis) | Operator action; do after the fan-off discriminator (7) | |

### 6.2 Code (card-sized, in rank order, each decomposed against the simplest version)
| # | Change | Placement ladder | Note |
|---|---|---|---|
| K1 | **AWAY-while-held trip-wire**: house AWAY for N min with a room still `occupied`, the room's only corroboration absent (no BLE/camera person, no radar, hallway/closet PIR quiet), one HIGH stuck-signal NM naming the room, its input, and its lights and fans (incl. fan-state-trust note). No actuation | New knob `AWAY_ROOM_HELD_NM_AFTER_S` rung 1 (module constant) + 0 = off; reuses `fire_stuck_signal` | Same deliverable as the sibling audit's primary recommendation (section 5.4 there). Illustration only (threshold not measured): with N = 15 min it would have paged about 14:07, 15 min after AWAY plus the 13:51:50 hold start. Simplest, no new writer |
| K2 | **P22 off-pulse tolerance**: do not reset `_sensor_on_since` for an `off` shorter than a named gap `P22_OFF_GAP_TOLERANCE_S` (~10 s, rung 1) when the following `on` re-arms the same sensor; count the run as continuous | Rung 1 constant, kill switch 0 = today's behaviour | Fixes the demonstrated seam: the ZV's 1.3-4 s pulses (and the Hobeian fading blip) reset a rule that would otherwise release at ~4 h. Falsifier: a real occupant produces off gaps > 10 s (ZV drops in 30-70 s when still), so a real stay is never mistaken. Tier 2-DB (shared primitive consumed by every motion-class room) |
| K3 | AWAY-shortened stuck horizon for an uncorroborated motion-class input (STUCK-SENSOR-1 fix item 1: "sleeping-person objection does not hold when the house is away") | Rung 1 `STUCK_AWAY_HORIZON_S` | Larger blast radius (house-state coupling); do after K1 proves the rate; parked option |
| K4 | Fan-state trust class (assumed-state / unobservable fans are "unknown" to recheck, sweep, phantom writers) | per sibling audit deliverable 2 | Not needed for this fan (state is observable); noted for completeness |

Not recommended now: a stuck-triggered recheck (section 5), an AWAY blind fan-off (needs an operator ruling vs "Fan Mode off = URA writes nothing"; physically zero-regret in an AWAY house).

---

## 7. Fire checks, falsifiers, unknowns

Fire check (has it ever fired / does it reach the action), `room:guest_bedroom_2`, URA DB `memory_episodes` since 2026-09: `fan_recheck_outcome` 0; `occupancy_phantom` 3 (10-17, 11-14 x2); `phantom_retro` 1 (10-13); `comfort_fan_vetoed` 1 (09-20). P22 NM fires once per (room, sensor, day) and reaches only the digest. Nothing reaches a fan or light.

Falsifier table:
| Conclusion | Observation that would disprove it | Result |
|---|---|---|
| Room is held by the ZV, not by anything else | another kind true in `tier1_provenance`, or `ble_persons` non-empty, or a camera source | `{motion: true, mmwave: false, occupancy: false}`, `ble_persons []`, `camera_person_detected off`, `sources []` (live 14:25) |
| Nobody there | hallway/closet PIR or Matter radar edges after 13:09 | none through 14:35 |
| P22 timer reset by pulses | `stuck_sensor` flag persisting across the pulses | cleared at 13:51:48 (13:19:34 pulse not observed, flag persisted) |
| Room paused | `switch.guest_bedroom_2_automation` reading `on` | 26+ recorder rows all `off`; live off |
| One physical fan | different Tuya device ids | both identifiers carry `ebd7a4f31a77f10913zsag` |
| 14:19:53 is not a transition | a state change with different value/attrs | identical rows at each restart |

Unknown (and what would settle it):
- **Why the ZV began seeing something at 05:28 and why it pulses.** Fan not demonstrated; no HVAC action (zone 2 `off` all night), no cover rows, sensitivity unchanged. Discriminator: **a fan-off test** (operator or orchestrator, once the diagnosis window closes): with the fan off, does `presence_2` hold `off` for > 3 min (30 s fading + margin)? If yes, fan-latched (SENSOR-FANINDEP-1 confirmed on this unit); if no, ambient/sensor fault and C1 is the lever. A control read of the Z2M log around 05:28 was not attempted (not reachable read-only from HA).
- Who turned the fan and light on, and whether anyone is in the house with the room (no person evidence anywhere).
- Whether the room's Automation OFF is deliberate.
- The physical fan state now: HA reports `on` on both entities; observed physically by the operator ("1%" is the cloud entity).
- HVAC D6 behaviour on this hold: not read.

Exposure note: while building the probes, two scripts printed config-entry `data` into the tool transcript, which included a Tuya cloud token, a Tuya local key and the MQTT broker password. The scripts were fixed and the output file deleted; the values exist in this agent's transcript only (not in this doc). Treat them as seen.

---

## 8. Adjacency against the named cards (surfaces read: `docs/planning/kanban.data.yaml` cards, `AUDIT_mediaroom_fan_left_on_stuck_sensors_2026_11_15.md` sections 4-7, code greps above)

| Card | Status (board) | Verdict vs this incident |
|---|---|---|
| `MEDIAROOM-FAN-LEFT-ON-STUCK-SENSORS-1` | investigating | **ADJACENT, same class; fold this room in.** Shared facts: Fan Mode off, Automation off, house AWAY with a held room, no AWAY fan/light action, NM only to the digest. Different: Media's fan state was invisible (Bond); here the fan state is visible (Tuya) and the holder is a motion-class ZV, not an MS600 radar bit. The AWAY-while-held trip-wire (K1) is the shared primary deliverable |
| `STUCK-SENSOR-1` | parked (card text stale, shipped v5.75.0) | **ADJACENT, the defect lives here.** Its gap 1 ("stuck is detected but only graduates to exclusion with a house-state gate; exclusion should be allowed when the house is away") is K3; the observed hole is narrower and new: P22's `on_since` reset by short off pulses (K2). D2 duty-cycle never scores motion-class sensors (`coordinator.py:2142`) |
| `FAN-RECHECK-*` (`-NOT-CLEARING-1` done, `-SLEEP-VETO-SCOPE-1` parked, `-OBSERVABILITY-1` done, `-D2-DEADLOCK-1` parked) | mixed | **DUPLICATE class as before:** recheck non-arm is config/pause/radar-sole. GB2 is in the sibling's recheck-eligibility cohort (Fan Mode off, Automation off, 0 rows). Nothing new for the cards; the radar-sole precondition is the new reason it would not apply to a ZV hold |
| `FAN-MANUAL-1` | done | **RELATED, defines the limit:** a person-switched fan is URA-hands-off; the manual-ON hold is time-bounded, not a left-on failsafe. Explains why URA does not turn the fan off |
| `SENSOR-FANINDEP-1` | done | **DIRECTLY RELATED, founding room.** Its origin names this very unit ("Upstairs Guestroom unit of this EXACT model fan-latched twice 08-13") and the 08-23 probe measured a second ZV (Exercise, sensitivity 16) tracking its fan. SENSOR_FLEET_CLASSES (2026-10-11) later set ZV = fan-immune witness in steady state (Game Room). This incident neither confirms nor refutes the latch on this unit (section 4); the fan-off test settles it. If confirmed, the capability declaration for this one unit (`CONF_SENSOR_CAPABILITIES` override) is the fix the card already scoped |
| `GUEST-ROOM-FAN-HOLD-1` | parked | **OPPOSITE direction:** that card is a guest fan turning off ~5 min after the room reads empty at night. Here a guest-room fan stays on after the guest left; its open question ("two drivers for Guest Bedroom 1's fan") is not this room. No overlap beyond "guest-room fan policy" |
| `FAN-PHANTOM-RETRO-EPISODES-1` | done | **NOT FIRING:** the `phantom_retro` writer needs a fan-off edge and a ZV/radar release within 60 s. No fan-off edge in 3 days here, so zero fire is the expected, not a finding; the 11-14 `occupancy_phantom` episodes are the Matter radar |

Verdict: **ADJACENT to MEDIAROOM-FAN-LEFT-ON-STUCK-SENSORS-1 (fold in), plus one NEW defect (K2, P22 off-pulse reset) that belongs on STUCK-SENSOR-1's residual list or a new Tier 2-DB card; the config levers C1-C4 need no card.** No new card minted by this prober (read-only).

---

## 9. Files
- This doc: `/Users/okosisi/Code/universal-room-automation/docs/planning/AUDIT_upguest_fan_held_occupancy_2026_11_15.md`
- Sibling: `/Users/okosisi/Code/universal-room-automation/docs/planning/AUDIT_mediaroom_fan_left_on_stuck_sensors_2026_11_15.md`
- Probe scripts (read-only, `ugprobe_*.py`): `/Users/okosisi/Code/universal-room-automation/.claude/tmp/` (`ugprobe_cfg.py` room config, `ugprobe_reg.py` registry, `ugprobe_rec*.py` recorder, `ugprobe_live*.py` live REST GET /api/states)
- Sources: HA recorder `/config/home-assistant_v2.db` (7.5 d), URA DB `ura_activity_log` / `memory_episodes` / `occupancy_events` / `notification_log` / `house_state_log`, `.storage/core.config_entries`, `core.entity_registry`, `core.device_registry` (all read over `ssh ha`).
