# AUDIT: pre-arrival inventory + pre-cool stand-down check

Read-only probe, 2026-11-12 ~16:55 CST. Develop @ c8c2eeb8 (code read at HEAD of working tree). HVAC STATE_OF_PLAY
(`docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md`, 740 lines) read completely before the code, including §10
(C1-C39). None of the ledger's wrong claims are re-asserted here. Paths below are under
`custom_components/universal_room_automation/` unless noted. `hvac*.py` = `domain_coordinators/`.

## Answer first

**Q1: No. Pre-arrival pre-cool never reads zone temperature.** It compares setpoint to setpoint only, and the one
check that does read a room temperature is the pre-arrival FAN path. 17 of 34 pre-arrival pre-cool writes with a
recorder-known zone temperature (50%) fired with the zone already at or below the new 75 F cool target. Details below.

**Q2: inventory** is in the second half. Short form: the signal has exactly 3 subscribers (HVAC, Security, Music).
Only HVAC acts on it live. Security's expected-arrival add is OFF, Music's handler is an intentional no-op, and the
Security lock-regime release is a live-OFF no-op (garage lockout switch off, away-lock switch off).

---

## Q1: does pre-cool stand down when the house is already cool?

### What it compares (PRODUCER check)

Producer chain for a pre-arrival pre-cool:

1. `_handle_person_arriving` (`hvac.py:7212-7281`) puts the zone in `_pre_arrival_zones` and starts an immediate
   cycle (`:7277`).
2. The cycle calls `_expire_pre_arrival_zones` (`hvac.py:2409`) then `_async_end_pre_arrival_borrows` (`:2428`),
   then `predictor.update(... pre_arrival_zones=...)` (`:2490-2495`).
3. `HVACPredictor._check_pre_conditioning` (`hvac_predict.py:422`) -> pre-arrival block `:683-707`: for each zone in
   the set, if `not is_borrow_active(zone)` it calls `_execute_zone_pre_cool(zone, offset=PRE_ARRIVAL_PRECOOL_OFFSET_F,
   reason="pre_arrival", from_baseline=True)` (`:698-701`).
4. `_execute_zone_pre_cool` (`hvac_predict.py:1259-1438`) computes:
   - `banked_high = baseline_cool + (-2.0)` where baseline = house-state target preset's configured cool from
     `get_seasonal_setpoints` (`:1284-1292`, `_resolve_baseline_range` `:918-957`; offset const
     `hvac_const.py:500`).
   - `floor = max(solar_bank_floor, zone.target_temp_low + MIN_DEADBAND)` (`:1296`); live `hvac_solar_bank_floor` = 74.0
     (CM entry options, `core.config_entries`), `MIN_DEADBAND` = 2.0 (`hvac_const.py:474`).
   - `effective_high = max(banked_high, floor)` (`:1297`).
   - Only skip test: `if effective_high >= zone.target_temp_high: return` (`:1299-1300`). `zone.target_temp_high` is the
     thermostat's current COOL SETPOINT, not the measured room temperature.
   - Other early exits: person-interrupt latch (`:1273`), egress pause (`:1276`), setpoint None (`:1281`), no baseline
     (`:1285-1291`), another live borrow owns the zone (`:1342-1358`).
5. It then writes `target_temp_low` unchanged and `target_temp_high = effective_high` (`:1406-1419`).

There is no read of `zone.current_temperature`, `avg_temperature` or any room temperature anywhere in the pre-arrival
pre-cool path. Nothing compares temperature to the heat setpoint either. The heat leg is passed through unchanged.

So per zone it compares exactly two numbers: `effective_high` (baseline cool - 2 F, floored at 74) against the zone's
current cool setpoint. For a zone sitting in Away (cool 80) that is always true, so the pre-cool is always written.

Observed live: baseline home cool = 77, so the write is 75 (every row in the DB shows `target_temp_high` 75).
`PRE_ARRIVAL_PRECOOL_OFFSET_F` is a rung-1 const with no knob (`hvac_const.py:497-500`).

### Does it stand down / end early if already satisfied?

No temperature-based end. A pre-arrival borrow ends on, in order (`hvac.py:7414-7491`, `hvac_predict.py:1172-1228`):
HVAC arrival in the zone (`any_room_hvac_occupied`, hallways excluded), person interrupt, timeout/max-age at knob 35,
pre-conditioning master or ZI turned off, or coordinator off. Knob 35 live = 20 min
(`number.ura_hvac_coordinator_35_pre_arrival_window_min` = 20; range 5-110).

Measured end triggers for the 51 pre-arrival banking borrows in the last 14 days
(`hvac_excursion_events`, kind=banking, site=S12_pre_arrival):

| trigger | n | mean duration s |
|---|---|---|
| pre_arrival_arrived | 39 | 282 |
| pre_arrival_timeout | 8 | 1533 |
| pre_arrival_max_age | 2 | 1236 |
| stale_boot_release | 2 | 584 |

(52nd write is the live one at 22:44Z.)

### Does it push a cooler setpoint when the zone is already below it?

It writes a cooler setpoint than the zone had (75 vs 80 Away, or 75 vs 76 Home) regardless of room temperature. Whether
that causes extra cooling depends on the room being above 75. When the room is at or below 75 the write is inert
(no cooling demand) but still happens: it opens a borrow, stamps arrester suppression, and puts the Carrier zone into a
manual hold until the borrow returns presets-only.

The pre-cool's real overcooling mechanism is the band 75 < T <= 77: the zone already satisfies its Home target but the
pre-cool drives it down to 75 (by design, a 2 F pull). That is bounded: 2 F below the Home baseline, floor 74, and at most
knob 35 minutes.

### Live evidence (14 days, to 2026-11-12 16:49 CST)

- `ura_activity_log` `action='climate_write'` with `reason":"pre_arrival"` (site `S12_pre_cool`): **52 rows**, 52/52
  `wire_ok=true`. Zones: zone_1 35, zone_2 17, zone_3 0 (zone_3 has no `zone_persons`, so arrival never reaches it).
  Prior preset: away 45, home 6, sleep 1.
- `ura_activity_log` `action='pre_arrival'` (signal accepted by HVAC): **218 rows**; 52 led to a write. The rest were
  repeat triggers in a spent/active episode, zones with a live borrow, etc.
- Zone temperature at write time: recorder `states` for the thermostat entity, last `current_temperature` at or
  before the write timestamp (whole degrees; state age 6 s to ~1.1 h because the attribute only changes at 1 F steps).
  **The recorder starts 2026-11-05 ~08:52Z (earliest `states` row), so only 34 of the 52 writes (11-05 14:31Z onward)
  have a temperature; 18 older rows are unknown, not counted.**

| Zone temp vs write | n of 34 known | note |
|---|---|---|
| temp <= 75 (at/below the new cool target; write inert) | **17 (50%)** | `temp<=75` |
| temp < 75 (strictly below; not even a boundary case) | **5 (15%)** | all zone_2: 74, 74, 74, 72, 74 on 11-07 16:34Z, 11-08 05:43Z, 11-08 23:40Z, 11-10 00:22Z, 11-11 01:25Z |
| temp 76-77 (home target already met, pre-cool pulls to 75) | 12 | the intended pre-cool zone |
| temp > 77 | 5 | the only rows where pre-cool plainly pays off |

- temp <= 76: 26, temp <= 77: 29 (of 34).
- The prior cool setpoint is not a useful test (45 of 52 started from Away = 80, so any room is "below" it).
- Write started from Home/Sleep preset (i.e. house not away, occupied or just-occupied): 7 of 52. Of the 4 with a known
  temp, 3 were zone_1 on 11-09 (15:58, 16:51, 19:39Z), zone temp 75, home cool 76 -> 75: setpoint dropped 1 F with the
  room already at the new target. The 4th: 11-12 22:44Z zone_1 home, temp 78, 76 -> 75.
- Right now (22:44Z live episode): zone_2 temp 78 (`sensor.ura_hvac_coordinator_zone_2_status` `current_temperature` 78,
  `target_temp_high` 75, `preset_mode` manual, `zone_presence_state` pre_arrival) vs the hvac_pre_arrival_status
  sensor `active_zones ["zone_2"]`, person.jaya, source ble, `triggers_today` 4.

Caveat on the 17/34: temps are whole degrees from the thermostat's own sensor, the last-known value could be stale by
up to the state age shown in the probe, and this is cool-season/shoulder data only (no winter rows exist). The probe is
the script embedded in this session (not saved); rerun method: join each `climate_write` row's `values_after.entity_id`
to `states`/`state_attributes` on the recorder DB, last row at or before `timestamp`.

### Falsification

What would disprove "pre-cool never checks temperature": a read of any temperature inside `_check_pre_conditioning`'s
pre-arrival block or `_execute_zone_pre_cool`. I read both end to end; the only temperatures read are
`zone.target_temp_high/low` (setpoints). The pre-arrival FAN helper is the one place a room temperature is compared
(`hvac_predict.py:1496-1527`, `room_temp < setpoint_high` -> skip reason `below_setpoint`), and it is a separate call
(`hvac_predict.py:704`) that does not feed back to the setpoint write. Observation consistent with the code: rows at
temp 72/74 still wrote 75.

### Heat side

- No pre-heat on arrival. `_execute_pre_heat` (`hvac_predict.py:1656`) is season/forecast/hour triggered
  (`:709-726`, winter, `outdoor_temp <= preheat_forecast_low`, within `PREHEAT_LEAD_HOURS` of off-peak end) for occupied
  zones, not by `SIGNAL_PERSON_ARRIVING`, and it raises the heat leg to `target_temp_low + 2` without reading room temp.
- Pre-arrival pre-cool has no season gate (the block at `hvac_predict.py:686` gates on house_state away/vacation only).
  In winter it would lower the cool leg (baseline - 2) while heat mode is in play. Inert unless the room is above that
  cool leg. **UNVERIFIED live: no winter data in the 14-day window.**
- The pre-arrival fan activation also only compares to the COOL setpoint (`setpoint_high`), nothing for heat.

### Net

Pre-cool is a fire-and-hold "set cool leg to baseline - 2 for up to knob 35 minutes or until arrival" regardless of
room temperature. It does not read zone temperature and cannot stand down on "already cool". The cheapest stand-down
that matches the code's own idiom: skip when `zone.current_temperature <= effective_high` (the fan helper already does
the equivalent on the room temperature). Not a recommendation to build; a marginal-benefit decomposition has not been
done (cost of the inert write is a manual-hold flap + one Carrier cloud write; the harm of the 12 pull-to-75 cases is up
to 2 F of cooling the arriving person arguably wants).

---

## Q2: everything triggered by pre-arrival / SIGNAL_PERSON_ARRIVING

Signal: `SIGNAL_PERSON_ARRIVING = "ura_person_arriving"` (`domain_coordinators/signals.py:25`). Payload
`{"person_entity", "source"}`. `grep ura_person_arriving` finds only the constant; subscribers are exactly the three
`async_dispatcher_connect` sites in the first table.

### Producers (who sends it)

| Source | Gate / condition | Site | Live |
|---|---|---|---|
| `geofence` | `person.*` state goes `not_home`/other -> `home` (`old_state` present, new not unavailable). Dispatch suppressed while Presence observation mode is on. Also calls `handle_geofence_event` which runs a house-state inference (`geofence_arrive`) - that is the real "house ARRIVING" driver, separate from the signal | `domain_coordinators/presence.py:5259-5300`; `:9460-9471` | Presence observation switch OFF (`switch.ura_presence_coordinator_presence_observation_mode` off) -> dispatches. 151 of 218 HVAC pre_arrival rows in 14 d |
| `ble` | Bermuda sees the person in a home room after being away >= `_min_away_minutes` (hard-coded 15, `person_coordinator.py:210`); needs `_pre_arrival_enabled` (synced from the HVAC `35 · Pre-Arrival Conditioning` switch, `hvac.py:1229-1241`) and Presence observation off. Also the overrule path arms `_person_was_away` | `person_coordinator.py:1096-1136`, `:750-765` | live; 67 rows in 14 d |
| `camera_face` | Frigate camera person sensor ON + fresh (<30 s) recognised face + `face_recognition_enabled` (live True) + central face-suppression checkpoint not active; 60 s debounce per person+zone. `_N`-suffixed person sensors (17 of 29 cameras) are SKIPPED because `FACE_SOURCE_PRESENCE_ARRIVAL_DISAMBIGUATED = False` (`const.py:3505-3513`) | `presence.py:5442-5480`, `:5487-5578`, `:5581-5640` | enabled but **0 camera_face rows in 14 d**; `camera_face_arrivals_today` 0 on all zones |
| lock-regime approach zone / P5 proximity | NOT the signal. Separate triggers inside `security_lock_regime` (`zone.home` approach zone, `sensor.madronehaos_*_distance` proximity) that call `_release` directly | `security_lock_regime.py:1195-1225`, `:1468-1480` | garage lockout switch off -> `_release` returns after bumping `release_gen` |

Person mapping: HVAC only reacts if the person is in some zone's `zone_persons`. Live (`core.config_entries`, zone_manager):
Entertainment + Master Suite = ezinne, oji_udezue (thermostat zone_1); Upstairs = ziri, jaya (zone_2);
Back Hallway (zone_3) = none; `sensor.ura_hvac_coordinator_hvac_pre_arrival_status` `person_zone_map` agrees. Built at
`hvac.py:7188-7198`.

### Consumers (3 subscribers)

| # | Consumer | Trigger sources | Gates / knobs (live) | What it changes | Site | Live |
|---|---|---|---|---|---|---|
| 1 | **HVAC `_handle_person_arriving`** (subscribed `hvac.py:1507-1514`) | geofence, ble, camera_face (filter list `pre_arrival_sources` = all three, `hvac_const.py:349-350`, live same) | ZI switch `30 · Per-Zone HVAC Control` on; `switch.ura_hvac_coordinator_pre_arrival_conditioning` (`35 ·`) on; person in a zone map; spent-episode check (`:7236-7245`); HVAC observation mode off (`switch.ura_hvac_coordinator_hvac_observation_mode` off); window knob 35 = 20 min | Adds zone to `_pre_arrival_zones`/`_persons`/`_start`, activity-log row `action=pre_arrival` (`:7256-7268`), counters, immediate decision cycle `trigger="pre_arrival"` (`:7277`) | `hvac.py:7212-7281` | **ON** |
| 1a | HVAC pre-cool (S12, "pre-conditioning") | via 1 | `switch ..._hvac_pre_conditioning` (`28 · HVAC Predictive Conditioning`) on (master gate `hvac_predict.py:470-538`, `_is_pre_conditioning_enabled` `:822`); not away/vacation house state (`:686`); no live borrow on the zone (`:697`); not person-latched (`:1273`); not egress-paused (`:1276`); baseline resolvable; `solar_bank_floor` 74; offset -2 F (const, no knob) | Writes cool leg = max(baseline_cool - 2, floor) via `emit_set_temperature`, begin banking excursion `S12_pre_arrival`; arrester suppress; Carrier goes to manual hold until borrow returns | `hvac_predict.py:683-707`, `:1259-1438` | **ON** (52 writes / 14 d) |
| 1b | Pre-arrival borrow end / return | arrival, timeout, interrupt, inactive, max-age | knob 35 | presets-only return to S1 target; episode "spent" so a repeat trigger does not re-cool | `hvac.py:2409`, `:2428`, `:7302-7313`, `:7414-7543`; `hvac_predict.py:1172-1228` | ON |
| 1c | HVAC pre-arrival comfort fans | via 1, skipped in house_state `sleep` (`hvac_predict.py:703`) | per-room Fan Mode must be "Follow thermostat" (`hvac_fans.hvac_tier_owns_room_fans`, `:1474-1492`); room not paused (`room_automation_paused`, `:1456-1469`); room temp >= zone cool setpoint (skip `below_setpoint`, `:1515-1527`; skip `no_data` if temp None); FanPolicyOracle W12 manual-OFF cooldown DEFER (`:1529-1590`) | `fan.turn_on` / `<domain>.turn_on` for each room fan | `hvac_predict.py:1441-1643` | ON. Live: Game Room activated; Guest Bedroom 2, Ziri Bedroom, Jaya Bedroom, Media, Exercise Room, Ziri Bathroom skipped `room_paused` (`hvac_pre_arrival_status.fan_rooms_skipped`) |
| 1d | Fan turn-off on timeout / max-age | timeout, max-age | - | `_deactivate_zone_fans` (`hvac.py:7489-7490`, `:7523-7527`) | | ON (13 `fan_off` rows in 14 d, all reasons) |
| 1e | S1 preset reason tag + vacancy-sweep fan exemption + row-1 hold exemption + D5 transit-filter exemption | via `_pre_arrival_zones` membership | - | S1 `preset_change` reason `pre_arrival` (`hvac.py:3739-3740`); `_execute_vacancy_sweep` keeps fans for a pre-arrival zone (`:6806`, `:6926`, `:7075`); transient-hold eligibility (`:2987`); `_zone_away_edge` returns False (`:5539`); zone state label `pre_arrival` (`:7706-7707`) | listed | ON |
| 1f | Diagnostics | - | - | `sensor.ura_hvac_coordinator_hvac_pre_arrival_status`, zone intelligence sensor `zones_pre_arrival`, `pre_arrival_*` attrs | `sensor.py:14463-14511`, `:14418`; `hvac.py:8387`, `:8454-8460` | ON |
| 2 | **Security `_handle_person_arriving_signal`** (subscribed `security.py:817`) - feeds lock regime FIRST, above its own enabled/observation returns | all sources | see 2a/2b | see below | `security.py:2381-2425` | mixed |
| 2a | Lock regime P2 `on_person_arriving` -> `_apply_arrival` -> `_release("arriving_signal")` (garage remote-lockout locks) | geofence/ble direct; camera_face only if corroborated by an independent arrival edge for the same person (held in `_pending_faces` otherwise) | resident only (`_is_resident`), "really away" gate, suspicious-arrival hold (`arrival_hold` 5 s), `kill_switch_on()` = `switch.ura_security_coordinator_garage_lockout` **off** | `lock.unlock` on `lock.ratgdov25i_dbfe2a_lock_remotes`, `lock.konnected_f0f5bd523b00_lock` (`security_lockout_entities`) only when kill switch on; also bumps `release_gen`, stamps `releasing_set` regardless | `security_lock_regime.py:996-1062`, `:1566-1600` | **OFF (switch off); no unlock** |
| 2b | Lock regime `_away_release("arriving_signal")` (away-lock door lock) | same | `security_away_lock_persons` = ezinne, oji_udezue; really-away; `switch.ura_security_coordinator_away_lock` **off**. Not gated by the switch or observation mode, but acts only on `away_lock_owned` + in-flight engages (`:2375-2377`), i.e. locks URA itself locked | `lock.unlock` on `lock.master_bedroom_lock` | `security_lock_regime.py:1044-1053`, `:2378-2408` | effectively inert while away-lock is off and nothing owned (owned set contents: UNVERIFIED live) |
| 2c | Security expected-arrival window | all | `CONF_SECURITY_ON_ARRIVAL_ADD_EXPECTED` default False (`base.py:270-285`, config flow default False `config_flow.py:10403`); key not present in CM options; Security enabled, observation off | `add_expected_arrival(person, window_minutes=5)` + `SIGNAL_SECURITY_ENTITIES_UPDATE` | `security.py:2412-2425`; `security.py:257-261` | **OFF** (`sensor.ura_security_coordinator_security_expected_arrivals` = 0, `expected_arrivals []`) |
| 3 | **MusicFollowing `_handle_person_arriving`** (subscribed `music_following.py:281`) | all | `music_following_coordinator_enabled` true | Nothing: DEBUG log only; arrival-start "was never implemented" (comment `music_following.py:566-573`, v5.10.0 D9) | `music_following.py:549-575` | **no-op by design** |

### Things you might expect that are NOT consumers of the signal

Verified by `grep` of every `.py` for the signal name and `person_arriving` (only the files above):

- **House state (ARRIVING / HOME_*)**: not driven by the signal. Presence infers it from the geofence event
  (`presence.py:5282` -> `handle_geofence_event` -> `_run_inference("geofence_arrive")` `:9460-9471`) plus census/BLE;
  ARRIVING re-arm cooldown `ARRIVING_REARM_COOLDOWN_S = 900` (`presence.py:225`). HVAC S1 does nothing while the house
  reads `arriving` (`hvac.py:2843-2848`), then uses `arriving -> home` preset mapping (`hvac_const.py:1330`).
- **Census**, **lights**, **NM notifications**, **music start**, **scenes**: no subscriber. No arrival notification is
  sent by any code path found; the activity-log row `pre_arrival` is the only operator-visible record besides the status
  sensor. (Carded gap territory: see IDENTITY manual / the 6.0.0 "consumers actually using person_id" milestone.)
- **Security `SC lock sweep` / armed-state**: only via house state (`security.py:192` `"arriving": DISARMED`), not the signal.
- **Garage lockout approach zone / proximity crossing / P1 person-> home**: independent release paths in the same lock
  regime (listed under producers); they also have the garage kill switch off live.

### On/off summary (live, 2026-11-12 ~16:50 CST)

ON and acting: HVAC pre-arrival intake (geofence + ble), S12 pre-cool, pre-arrival comfort fans, borrow reconciliation,
S1 reason tagging and sweep/hold exemptions, activity log + status sensor.
ON but unproven: camera_face source (0 firings in 14 d).
OFF / inert: Security expected-arrival add (default off), lock-regime garage release (kill switch off), away-lock
release (switch off), Music arrival start (not implemented).

### Producer / consumer notes on the numbers used here

- `pre_arrival` rows, 14 d by person/source: ezinne ble 28 / geofence 30; jaya ble 19 / geofence 20; oji_udezue ble 15
  / geofence 94; ziri ble 5 / geofence 7. Per day: 11-09 36, 11-07 41, 11-08 21; quiet days 2-8.
- Geofence is 151/218 (69%) of intake, and it fires on any person-entity change to `home`, not only after the
  BLE-style 15-minute absence guard. This is the dominant pre-cool trigger source, and Oji's geofence alone is 94 rows.
  (Whether that is a flap problem or real is not established here.)

### Files

- Code read: `domain_coordinators/hvac.py`, `hvac_predict.py`, `hvac_const.py`, `presence.py`, `security.py`,
  `security_lock_regime.py`, `music_following.py`, `base.py`; `person_coordinator.py`, `const.py`, `sensor.py`.
- Live: HA REST states (token not printed), `ssh ha` sqlite3 on `ura_activity_log`, `hvac_excursion_events`,
  `home-assistant_v2.db` `states`; `/config/.storage/core.config_entries` (read-only).
