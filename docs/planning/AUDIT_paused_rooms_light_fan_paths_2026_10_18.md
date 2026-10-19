# AUDIT: paused rooms and the light / fan paths that ignore the room Automation switch

Date: 2026-10-18 (CDT, `date` = Sun Oct 18 21:35 at start). Read-only probe. Code at `02880ec69` (branch fix/fan-recheck-still-risk-veto-scope).
Card: ROOM-OVERRIDE-SWITCH-FORGOTTEN-1 (docs/planning/kanban.data.yaml:31062; verify_2026_10_18_overnight at :31062+..., see below).
Read first: PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md section 4 / 4.5 (room switches; `_is_automation_enabled`). No HVAC STATE_OF_PLAY edits made; I did not need to re-assert any HVAC claim, but the HVAC fan/sweep paths below are HVAC-tier writers, so a builder must read `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` completely first.

Operator ruling (2026-10-18, verbatim): "Paused rooms should stop with lights and fans automation based on occupancy. Blinds down, house state, venting are fine. I just didn't want it turning off lights when paused."

## VERDICT

The ROOM tier is already inert for occupancy-driven lights and fans when the master switch is off (entry/exit, scheduled auto-off, room temperature fan, Away leave-on sweep, actuator reconciler all sit behind `_is_automation_enabled`). The card text "Paused rooms should be inert" is therefore satisfied for the room tier.

The leaks are all in the HVAC tier and the presence fan-recheck, which iterate rooms from their own registries and never ask the room's Automation switch:

| # | Path | What it does in a paused room | Gated by master switch? | Observed in 7 days? |
|---|---|---|---|---|
| L1 | HVAC zone vacancy sweep `_execute_vacancy_sweep` (hvac.py:6713) | turns OFF every configured light (+night lights) and, if the HVAC tier owns the fans, fans, in every room of a vacant zone | NO | YES, 3 confirmed + 1 probable URA-stamped light OFFs in paused rooms |
| F1 | HVAC comfort-fan controller `FanController.update` (hvac_fans.py:569, per-room loop :635; occupancy/vacancy timer in `_evaluate_temp_fan`, hvac_fans.py:~1398-1470) | fan ON / OFF on temperature + occupancy + vacancy hold | NO (only checks `_is_room_hvac_managed`, i.e. Fan Mode) | YES, Kitchen 6 OFFs, Master Bedroom 5 OFFs + 1 ON |
| F2 | Presence fan-recheck pause (presence_fan_recheck.py:1625 -> hvac_fans.py:2079 `pause_for_recheck`) | turns the fan OFF to test whether the room is really occupied, then restores | NO | YES, Kitchen 6 recheck_pause OFFs (10-13 to 10-14) |
| F3 | HVAC sleep-onset fan activation (hvac_fans.py:986, dispatch :1121) | fan ON at sleep entry if room warm | NO | YES, Master Bedroom 1 ON (10-11 22:00 CDT) |
| L2/F4 | HVAC pre-arrival: `_activate_zone_fans` (hvac_predict.py:1440) fan ON; `_deactivate_zone_fans` (hvac.py:7375) fan OFF | fan on/off in rooms of a zone on pre-arrival | NO | no row found in paused rooms |
| L3 | HVAC `turn_off_all_managed` (hvac.py:2451 -> hvac_fans.py:532) | operator kill switch for Fan control; turns managed fans off | NO (by design, kill switch; not occupancy-driven) | n/a |

Everything else on the "must stop" list was verified GATED (table below).

Observed instances (URA-stamped light OFFs in rooms whose master switch is off): 4 in 7 days; 3 attributed to L1 by timing to the same second as the zone `vacant_past_grace` write, 1 unattributed. Fan instances: F1 11 OFFs + F3 1 ON, F2 6 OFFs. None of these were operator-driven (activity log names the trigger).

## 1. Code paths (file:line, trigger, gate)

Gate definition: `coordinator.py:3181 _is_automation_enabled` = manual_mode OFF AND room `automation` switch not off (switch.py:5103 AutomationSwitch; resolved via `_get_room_switch_state`, coordinator.py:3028-3074). Missing switch => treated as enabled.

### Gated today (no action needed)
| Path | Site | Gate evidence |
|---|---|---|
| Entry/exit lights, fans, switches (`handle_occupancy_change`) | coordinator.py:5241 | inside `elif self._is_automation_enabled():` (coordinator.py:5235); else branch :5382 only tracks `_last_occupied_state` and runs covers |
| BLE->sensor re-trigger entry | coordinator.py:5311 | same block |
| Delayed exit verify retry `_delayed_exit_verify` | coordinator.py:5284 schedule / :5751 retry | scheduled only from the gated block. Residual: the 3 s task does not re-check the switch, so a switch flipped OFF inside that 3 s window still gets one exit retry (negligible) |
| Room temperature fan (`handle_temperature_based_fan_control`) incl. sleep-onset room-tier | coordinator.py:5326 | inside gate (comment :5318 notes the old ClimateAutomation switch retired) |
| Shared-space scheduled auto-off / warning flash | coordinator.py:5337-5338 | inside gate |
| Away leave-on sweep | automation.py:890 | explicit `_is_automation_enabled` check |
| Actuator reconciler (light/fan enforce) | actuator_reconciler.py:544 | Guard 2, records skip "manual_mode" |
| Room Lights switch / button (operator action) | switch.py:5436-5470 | operator-initiated, out of scope |

### Ungated, occupancy/vacancy-driven (operator: MUST STOP)
| ID | File:line | Trigger | Notes |
|---|---|---|---|
| L1 | hvac.py:6713 `_execute_vacancy_sweep`; callers hvac.py:3044 (row-1 `zone_vacant_past_grace`) and hvac.py:3119 (D6 stale-occupancy) | zone has no occupied room in the LIGHTING denomination (`not zone.any_room_occupied`, :3034-3040), `zone.vacancy_sweep_enabled`, once per vacancy (`vacancy_sweep_done`) | Per room: `coordinator = self._get_room_coordinator(room_name)` then `light.turn_off`/`switch.turn_off` on CONF_LIGHTS+CONF_NIGHT_LIGHTS minus leave-on minus manual holds (hvac.py:6738-6780); lights are written with the URA context stamp (`ura_ctx_kwargs`, hvac.py:6775) so they appear as `context.parent_id = URA`. Fans in the same loop only if `hvac_tier_owns_room_fans` (:6798) and no manual-ON hold. NO read of the room Automation switch anywhere in the function. `_execute_vacancy_sweep` guards only on observation mode (:6720). |
| F1 | hvac_fans.py:569 `update` (called every HVAC cycle, hvac.py:2449); per-room loop skips only `not _is_room_hvac_managed` (:635-645); decision `_evaluate_temp_fan` (occupied flag from `zone.room_conditions`, vacancy timer + hold; "Occupancy gate" ~:1409, vacancy-hold ~:1411-1470); emit `_set_fan_state` hvac_fans.py:920 -> `_emit_fan_state` :1690 | temperature vs zone setpoint + room occupancy + vacancy timer + house state | Master switch never consulted. Activity rows `hvac/fan_off ... trigger=temp_hvac`. Which rooms: any room with fans whose Fan Mode is Follow-thermostat (`room_hvac_fans_managed`). |
| F2 | presence_fan_recheck.py:1625 `_fan_pause` -> hvac_fans.py:2079 `pause_for_recheck` -> `_set_fan_state(... FAN_TRIGGER_RECHECK_PAUSE)` hvac_fans.py:2127; restore at presence_fan_recheck.py:1647 -> hvac_fans.py:2138/2324 | occupancy-confirmation probe: room looks occupied only because of fan noise risk, so URA turns the fan OFF for up to 150 s, then restores | `fan_controller._room_fans` registers EVERY zone room with fans, including rooms whose fans the room tier owns (hvac_fans.py:449-455), so a paused room is probed. presence_fan_recheck.py has no reference to the room's Automation switch (grep for "switch/automation_enabled/manual_mode" only hits its own kill switches, :539, :590). |
| F3 | hvac_fans.py:986 `_sleep_onset_activation`, dispatch :1121 | non-sleep -> sleep house-state edge, room warm (>= CONF_SLEEP_FAN_ON_TEMP_F) | Fan ON. House-state driven, but it is a fan actuation in a paused room; operator language "stop lights and fans automation based on occupancy" is about occupancy, so F3 is borderline (house-state, not occupancy). Flag for the operator ruling. |
| F4 | hvac_predict.py:1440 `_activate_zone_fans` (ON), hvac.py:7375 `_deactivate_zone_fans` (OFF) | predictive pre-arrival | gated only by `hvac_tier_owns_room_fans` (Fan Mode). Anticipatory, not occupancy-detected; no observed rows. |

### Ungated but NOT in scope per operator (venting / blinds / house state / safety)
- Humidity venting: coordinator.py:5421 (decoupled from master by design, bathroom-exhaust D1). Operator: fine.
- Timed covers: coordinator.py:5398 / :5345 on Cover Automation switch. Operator: fine.
- AI rules / chained automations (house-state / energy): coordinator.py:955, :996, :5369, executes lights via coordinator.py:1281 (URA-stamped). Gated only by the AI switch. Operator: house-state fine. NOTE: these can still turn lights off in a paused room when the AI switch is on (AI ON in guest_bedroom_1, master_closet, staircase, master_closet_storage, study_b per card). Not observed as the cause of any of the 4 stamped OFFs below (see Section 3), but the same stamp would be produced; the operator should decide whether "house-state chained lights" count as fine.
- Safety/security light writes: domain_coordinators/manager.py:1051 (stamped), safety.py:2711, security.py:1632; alert lights aggregation.py:1510; NM light flash notification_manager.py:2396. Intentionally ungated.
- Optimizer actuation: optimization.py:4679, :4828 (stamped; shadow mode per activity log "shadow_cycle_summary", no actuation seen).
- Energy pool switches (EV chargers): energy.py:5641 etc. Not room lights/fans.

## 2. Producer / consumer notes
- Producer of "room is vacant" for L1: `zone.any_room_occupied` in the HVAC zone manager, fed by the same room occupancy that a paused room still computes (paused rooms still compute `STATE_OCCUPIED`; only the actions are gated, coordinator.py:5382 else-branch). So a paused room's lights get swept because its OWN occupancy is "vacant" together with its zone-mates.
- Producer for F1: `room_cond.occupied` from the zone's `room_conditions`; consumer `_evaluate_temp_fan`.
- Consumer of the switch: only coordinator.py `_is_automation_enabled` callers (coordinator.py:5235, automation.py:890, actuator_reconciler.py:544). `grep _is_automation_enabled|_get_room_switch_state` across `domain_coordinators/*.py` returns nothing: no HVAC or presence code reads it.

## 3. Evidence

### 3a. The 20 paused rooms (live)
Source: HA recorder `/config/home-assistant_v2.db`, latest state of every `switch.*_automation` (excluding ai/cover) = `off`, last_updated 2026-10-18 20:36 CDT (restart restore; Kitchen, Foyer, Media, Staircase rows show `off` continuously from 10-11 through now with only restart rewrites):
exercise_room, foyer, garage_a, garage_hallway, guest_bedroom_1, guest_bedroom_2, jaya_bedroom, kitchen, kitchen_hallway_garage, master_bedroom, master_closet, master_closet_storage, master_hallway, media, patio, receiving_room, staircase, study_b, ziri_bathroom, ziri_bedroom_bedroom_5. (20, matches the card.)

HVAC zone membership of paused rooms (sensor.ura_hvac_coordinator_zone_N_status `live_rooms`): zone_1 = Receiving Room, Foyer, Study B, Master Bedroom, Master Hallway, Master Closet, Master Closet Storage; zone_2 = Guest Bedroom 2, Ziri Bedroom, Jaya Bedroom, Media, Exercise Room, Ziri Bathroom; zone_3 = Guest Bedroom 1, Kitchen, Garage Hallway, Kitchen Hallway Garage, Staircase. (Garage A, Patio not in an HVAC zone.)

### 3b. Room-tier silence confirms the gate works
URA DB `/config/universal_room_automation/data/universal_room_automation.db`, `ura_activity_log`, 2026-09-19 to 2026-10-19 02:36 UTC, rows with `room` in the paused list and last 7 days: only `Guest Bedroom 2 occupancy_entry 1`, `Media occupancy_entry 1`, `Garage A hazard_detected 4`, `Kitchen hazard_detected 40`, plus the HVAC/recheck fan rows below. Zero `light_turn_off`, `light_turn_on`, `light_reconcile`, `shared_space_auto_off` rows for any paused room (these actions are logged for the unpaused rooms: 749 light_turn_off rooms-wide). So room-tier actuation is gated, as designed.

### 3c. URA-stamped light OFFs in paused rooms (HA recorder, last 7 days)
Method: python over `states` joined to `states_meta`, matching `context_parent_id_bin` = ULID `01K6RAWR1TE0000000000000A1` (ura_context.py:55 `URA_WRITE_CONTEXT_PARENT_ID`), on every configured light/switch of the paused rooms (config from `.storage/core.config_entries`), only real on<->off transitions. Fans are NOT stamped (ura_context.py:78 stamps light/switch/scene only), so fan attribution uses the activity log instead.

| Time (CDT) | Room | Entity | Transition | Path |
|---|---|---|---|---|
| 10-14 06:51:16 | Exercise Room (zone_2) | switch.switch_sonoffm4rm_matter_exercise | on -> off | L1 (zone vacancy sweep). activity log: hvac `climate_write zone_2 S1_reason_ladder reason=vacant_past_grace` at 11:51:15.456 UTC and Jaya Bathroom vacated 11:51:04 UTC; same second as the sweep call |
| 10-17 00:38:55 | Study B (zone_1) | light.dimmer_shellyplus_wifi_studyb1 (night light) | on -> off | L1. hvac `climate_write zone_1 ... vacant_past_grace` 05:38:55.444 UTC, same second; sweep deliberately includes night lights (hvac.py:6742-6750 comment) |
| 10-18 00:23:06 | Garage Hallway (zone_3) | light.dimmer_tapo_wifi_matter_hallwaycabinet (night light) | on -> off | L1. hvac `climate_write zone_3 ... vacant_past_grace` 05:23:05.649 UTC, same second |
| 10-16 12:02:12 | Guest Bedroom 2 (zone_2) | switch.switch_sonoffm4rm_matter_upguest | on -> off | NOT PROVEN. URA-stamped (so a URA writer, not a person). Coincides within 1 s with the house-state change `arriving -> home_day` at 17:02:11.6 UTC (house then flapped back to away at 17:04:12). No zone_2 `vacant_past_grace` write at that second, no room-tier row (room tier is gated and would log `light_turn_off`). AI switch for Guest Bedroom 2 is off (so not AI rule). Remaining stamped candidates: L1 sweep (preset already away => no climate_write row), hvac.py:3119 stale branch. Cannot confirm because the per-sweep INFO log "HVAC: Vacancy sweep for zone ... swept N entities" (hvac.py:6905) is not retrievable (journalctl absent on the HA host; no sweep row in activity log) |

Falsifier I checked: if these were room-tier writes, `ura_activity_log` would carry `light_turn_off`/`light_reconcile` rows for those rooms at those seconds. It has none (3b), and the room-tier code path is gated at :5235/:544.
Limitation: unstamped OFFs (device-local, person, Zigbee binding) are the large 'other'/'user' majority in the recorder summary (e.g. Master Closet 39 on/off pairs, Staircase 31, Jaya Bedroom 20) and are not URA writes; I did not attribute them.

### 3d. Fan actions in paused rooms (activity log, last 7 days)
`ura_activity_log`, coordinator hvac / room, rooms Kitchen and Master Bedroom (the only paused rooms with fan rows):
- Kitchen (`fan.151732606487193_fan`), zone_3, 12 `fan_off`:
  - F1 `trigger=temp_hvac`: 10-12 17:46:46 (home_day), 10-12 22:46:13 (sleep), 10-14 21:38:54 (home_night), 10-14 23:38:54 (sleep), 10-15 23:21:09 and 23:51:08 (sleep). 6 rows.
  - F2 `trigger=recheck_pause`: 10-13 16:57:52, 17:14:52, 18:01:55, 18:18:56, 20:10:57; 10-14 14:14:13. 6 rows. Each followed by `fan_recheck_outcome occupied_confirmed` (the probe confirmed the room was occupied; the person's fan was switched off during the probe window up to 150 s).
- Master Bedroom (`fan.polyfan_508s_wifi_masterbedroom`), zone_1: 5 `fan_off trigger=temp_hvac` (10-12 10:45 and 19:39, 10-13 07:19 and 12:38, 10-14 05:31) and 1 F3 `Sleep-onset fan on` at 10-11 22:00:26 CDT (73.4 F >= 72.0 F, trigger sleep_onset).
- No fan rows in the paused rooms since 10-15 23:51 CDT.
- Recorder fan transitions for the same entities show context 'other' (fans not stamped), consistent with HVAC-tier writes with no HA user.

## 4. Options for the build (not decided here; Tier/gate per kanban skill)
Config-first check: there is no setting that makes the HVAC tier skip a room. The room Automation switch is the knob the operator is using; the HVAC tier needs to read it.
Smallest consistent shape: one shared predicate (reuse `coordinator._is_automation_enabled`, coordinator.py:3181, via `_get_room_coordinator`) consulted at each ungated writer: hvac.py `_execute_vacancy_sweep` per-room loop (lights and fans), hvac_fans.py `update` per-room loop (skip like `_is_room_hvac_managed`), `pause_for_recheck` / fan-recheck eligibility, `_sleep_onset_activation`, hvac.py `_deactivate_zone_fans`, hvac_predict.py `_activate_zone_fans`. Expect the change to be Tier 2-DB class (shared HVAC primitives, cross-coordinator). Do NOT gate safety stops (`_stop_all_fans_safety`, hvac.py:6585) or `turn_off_all_managed`, humidity, covers, house-state blinds.
Operator questions: (1) is F3 (sleep-onset fan ON, house-state-triggered) in or out; (2) should a paused room still be probed by fan-recheck F2 (probe turns the fan OFF; a paused room's fan should presumably be left alone); (3) chained house-state lights via AI switch stay as-is (per ruling "house state fine").
Note a side effect to size: with HVAC comfort-fan skipped in paused rooms, a paused room's running fan has no one to turn it off at vacancy; this is the intended "inert" behaviour.

## 5. Not done / unknown
- Guest Bedroom 2 10-16 12:02:12 attribution: unknown (see 3c).
- Sweep log lines not retrievable; no journal on host. A per-sweep activity row would make this auditable (not carded here).
- Did not check any room-config `lights_leave_on_when_empty`; sweep exemptions would only reduce counts.
- Recorder summary counts are from `states` transitions only (events table not used).
- Card's `verify_2026_10_18_overnight` correctly lists three "still act" paths (covers, AI/house-state, humidity) but missed all HVAC-tier and fan-recheck paths above; it should be updated with this audit.
