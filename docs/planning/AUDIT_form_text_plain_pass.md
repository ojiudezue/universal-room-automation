# AUDIT — Form text plain pass (labels and helper text)

Card: **FORM-TEXT-PLAIN-PASS-1** (Tier 2, sibling of FORM-CONDITIONAL-FIELDS-1). Read-only audit; proposes text, changes no code.
Rev 2 (2026-11-11): fix-ups from plan review 3 (`docs/reviews/code-review/config_forms_AB_plan_review_rev3.md`, M2, M3, M4, M5, L-T1..L-T6) and operator context on geofence (P3). Plan §15 has the per-finding table.
Ships with: FORM-CONDITIONAL-FIELDS-1 **D3** (same `strings.json` + `translations/en.json` edits; plan §14).

Operator ask (verbatim, 2026-11-11): *"scan form text and prep usable and simple text and explainer labels where they don't exist. Coordinators are especially bad examples. I went into the Presence coordinator today and that part is a bit of a mess."*

---

## 0. Institutional context verified

| Source | Use here |
|---|---|
| memory `feedback_label_style_guide.md` (read in full) | Config-flow label = short phrase; helper text (`data_description`) = plain sentence(s); no nerd words (hysteresis, debounce, provenance, substrate, tier, failsafe); keep-but-gloss mmWave / BLE / PIR / lux |
| memory `feedback_configurability_clarity.md` (read in full) | Technical knobs as named buckets with one-sentence consequences; default = recommended middle |
| `docs/planning/PLANNING_dpm_cleanup_and_room_label_pass.md` §D2.2-D2.6 | REUSED: the denylist + gloss policy, rules of engagement (never rename keys / entity ids; both files in one commit; value-parity test), operator sign-off on the table before build |
| `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (read COMPLETELY) | Presence semantics: guest split (§2 step 3, §10 #30/#31), path β, fan recheck Rev 2 (§6 item 3), sleep window consumers |
| `docs/architecture/SENSOR_FLEET_CLASSES.md` (read COMPLETELY) | Sensor-list wording: `motion_sensors` = motion-class incl. ZV; `presence_sensors` = still-holding radar; `occupancy_sensors` = combined |
| `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` (read COMPLETELY) | HVAC rows (arrester night window, Carrier freshness, immune persons, cover temps); no §10 ledger claim is re-asserted |
| `strings.json` vs `translations/en.json` | Same keys and values; differ only in the order of two lines (`hvac_solar_bank_enabled`, `hvac_pre_conditioning_enabled`, strings.json:1298-1299 vs en.json:1294-1295) |

Method (reproducible): an AST scan of `config_flow.py` collects every `vol.Optional/Required` key per `async_step_*` (two helper levels deep, CONF names resolved from `const.py` + `domain_coordinators/*_const.py`) and diffs it against that step's `data` / `data_description` / `sections` in `strings.json`. Every "no label" hit below was then confirmed by `grep -c '"<key>"' strings.json` = 0 or by reading the step's strings block. Rev 2 (M5): the first scan did not follow keys passed as arguments into local builders (`_multi(KEY)`, `_opt_single(KEY)` in `_sensors_confirm_schema` / `_devices_confirm_schema`), so it missed two raw-key fields on create `sensors_confirm`. The re-run resolves helper-argument keys; only those two were new. Scan false positives (dynamic loop keys `?key`, `?cool_key`, `?_field_key`, and the zone DPM step whose builder takes the keys as arguments) are excluded from the counts. Every proposed description names the runtime reader it was checked against.

Config-first: not applicable (text only).

---

## 1. Counts

94 steps (config + options), ~690 labelled fields. Every step has a title and a description.

| Gap | Count | Where |
|---|---|---|
| **Field shown with its raw key** (no label, no description) | **41** (rev 2: +2, create `sensors_confirm` `presence_sensors` + `door_sensor`, M5) | create `sensors_confirm` 2, options `coordinator_hvac_settings` 7, options `devices` 7, options `coordinator_energy` 5, create `cover_behavior` 5, options `coordinator_presence` 3, create `devices` 3, options `coordinator_notifications_persons` 2, `sensors` create + options 1 each (`room_cameras`), create `zone_setup` 1, options `coordinator_safety` / `coordinator_security` / `coordinator_music_following` / `coordinator_notifications_quiet` 1 each |
| Labelled field with no description | 1 live | options `coordinator_energy` `energy_envoy_entity` |
| Dead strings (no form uses them) | 24 (rev 2: + create `sensors_confirm` `mmwave_sensors`, `door_sensors`, M5) | options `automation_behavior` (16 keys; no options step of that name, only a create step at `config_flow.py:2968`); create `cover_behavior` 6 legacy keys (`close_time`, `close_timing_mode`, `entry_cover_action`, `open_time_end`, `open_time_start`, `open_timing_mode`) while the form asks `cover_open_mode`, `cover_open_time_source`, `cover_open_hour`, `cover_close_time_source`, `cover_close_hour` with no labels |
| **Helper text that is wrong about what the code does** | **8** (+2 over-claiming / wrong found in review: C11, P6) | §3 table, rows marked WRONG |
| Labels or helper text using denylist / engineering words | 36 labels, ~50 descriptions (after removing scan noise) | worst: options `coordinator_energy` (11 labels, ~36 descriptions, 18 over 220 characters), `coordinator_presence`, `coordinator_hvac_settings`, `coordinator_notifications_volume`, `coordinator_optimization` |
| Title Case Every Word labels of 3+ words (inconsistent with the sentence-case labels next to them) | 143 | all coordinator steps; worst `coordinator_hvac_settings` 15, `coordinator_energy` 13, `coordinator_notifications` 10 |

**Worst steps** (raw keys x3 + missing text x2 + jargon): 1 `coordinator_energy` (113 fields), 2 `coordinator_hvac_settings` (38), 3 options `devices` (19), 4 **`coordinator_presence` (17)**, 5 create `cover_behavior` (17), 6 `coordinator_security` (18), 7 `coordinator_notifications_*` (5 sub-steps).

Inconsistent terms across steps:
- "Guest mode" / "Guest Mode" / "guest signal": three spellings, and two of the meanings are out of date (row P5, R4).
- "Sleep Start Hour" labels two different values: the house sleep window (CM Presence step) and each room's sleep protection hours. They also share the stored key name `sleep_start_hour`. The first room's hours are also read house-wide (`aggregation.py:885` `_is_sleep_hours`).
- Sensor names: "Presence sensors" (room step) vs "mmWave" (fan recheck text) vs "radar" (family scaling text) for the same list.
- "Entities" as a label suffix (`Camera Entities`, `Alert Light Entities`) next to plain labels (`Lights`, `Fans`).
- Engineer notes in user text: "Mode-2", "(master)", "kill-switch", "flip ON after live validation", "STUCK-SENSOR-1 D1 rung-2", "v1 references — v1 commands none".

---

## 2. Rules for the build (REUSED from the DPM label pass §D2.3)

1. Never rename a CONF key, translation key or entity id. Text only.
2. Edit `strings.json` and `translations/en.json` in the same commit; extend the value-parity test to every step touched.
3. Label: short phrase, sentence case, unit in brackets when the field is a number. Description: one or two plain sentences: what it does, then when to change it, then the default.
4. Load-bearing hardware words stay with a gloss (mmWave, Bluetooth, PIR, lux). Denylist words leave labels and descriptions.
5. Operator signs off this table before the build edits strings.
6. A field the audit finds has **no runtime reader** gets honest text ("Not used") now; removing the field is a separate card (§5), not this text pass.

---

## 3. Proposed text

Columns: step · key · current label · current description (shortened) · proposed label · proposed description · reader checked (file:line). **WRONG** = current text contradicts the code.

### 3.1 Presence coordinator (options `coordinator_presence`, `config_flow.py:5546`) — full detail

Step title: "👥 Presence Settings" → **"👥 Presence"**. Step description, current: "Configure the Presence Coordinator. Sleep hours determine when the house transitions to sleep/waking states. Geofence trackers detect arrivals and departures." (the second claim is WRONG, row P3). Proposed (rev 2): **"How the house decides who is home, when it sleeps, and when a running fan is fooling a room sensor. Who is home comes from each person in Home Assistant (Settings → People: the device trackers set for each person, read against your Home zone). Saving restarts the house coordinators."** (none of these keys is in `OPTIONS_RELOAD_SUPPRESS_KEYS`, `__init__.py:7526`, so a save reloads the CM entry.)

| # | Key | Current label | Current description (short) | Proposed label | Proposed description | Reader checked |
|---|---|---|---|---|---|---|
| P1 | `sleep_start_hour` | Sleep Start Hour | Hour when the house enters sleep mode. Default 23 | House sleep starts (hour) | Hour (0-23) from which the house can switch to Sleep while people are home. It also sets the night used for guest-stay detection and the garage lockout. Default 23. | `__init__.py:3759` → `presence.py:1060`, `:1465` `_is_sleep_hour`; `security_lock_regime.py:390` |
| P2 | `sleep_end_hour` | Sleep End Hour | Hour when the house exits sleep mode. Default 6 | House sleep ends (hour) | Hour (0-23) when the house night ends and Sleep can turn into Waking. Default 6. | `__init__.py:3765`; `presence.py:1465` |
| P3 | `geofence_entities` | Geofence Device Trackers | Device trackers used for geofence-based arrival/departure detection… **WRONG** | Phone trackers (not used) | Not used, and will be removed. Arrivals and departures come from every person in Home Assistant. Each person's location comes from the device trackers set for them under Settings → People, compared with your Home zone. To change what counts, edit the person there. Leave this empty. | No reader: the key is imported at `__init__.py:3608` but never passed on; `presence.py:5187-5213` `_subscribe_geofence` listens to every `person.*` entity (HA's person state = its device trackers vs `zone.home`). Removal: card PRESENCE-GEOFENCE-FIELD-DEAD-1 |
| P4 | `guest_mode_persistence_seconds` | Guest Mode Persistence (seconds) | How long an unidentified person must persist before the house enters Guest mode… **WRONG** | Guest mode exit wait (s) | How long Guest mode must look finished before the house leaves it, so a short camera miss does not end it. Also how long an unknown person must stay in view to show as a visitor. 0 = no wait. Default 300. | exit hold `presence.py:2265-2276`, `:7962-8003`; visitor leg `:6657` → `:7208`, `:7303` (`cam=` on Visitors Present only) |
| P5 | `guest_mode_require_confidence` | Guest Mode Min Census Confidence | Minimum census confidence required to trigger Guest mode… **WRONG** | Camera agreement for visitors | How sure the camera count must be before an unknown person shows on the Visitors Present sensor. It does not turn on Guest mode; a day and a night in a guest room does. Default medium. | `presence.py:6648` inside `_guest_gate_armed`; its result feeds only `guest_reason` (`:7261`), confidence (`:7276`) and Visitors Present (`:7303`); GUEST arms through `_compose_guest_gate` (`:7215-7225`) |
| P6 | `lost_away_grace_min` | (raw key) | (none) | Silent-phone wait (min) | When a resident's phone has gone silent, how long to wait before the house may switch to Away without them, unless the cameras and every room have read empty for a few updates in a row. 0 = no wait. Default 60. | `presence.py:7502-7509` → path β grace `:1255-1265`; skipped by `immediate_engage_empty_house` after `CONF_LOST_AWAY_INDOOR_CLEAR_TICKS` (3) empty ticks (`:1302-1316`, `:7585-7598`) (rev 2, M3: rev 1 over-claimed) |
| P7 | `lost_away_sleep_exempt` | (raw key) | (none) | No Away at night on a silent phone | At night (from Home Night through Waking, or inside the house sleep hours), a silent phone never lets the house switch to Away. Keep on so a phone that dies overnight cannot mark a sleeper away. Default on. | `presence.py:7512-7516` → `:1267-1270`, `:1315`; sleep-hour union `:7600-7608` (L-T2) |
| P8 | `presence_anomaly_sensitivity` | (raw key; options already have plain bucket labels) | (none) | Unusual-activity sensitivity | How readily presence patterns that look unusual are flagged. Normal suits most homes. | `presence.py:2792` → `const.py:3833` `ANOMALY_SENSITIVITY_MULTIPLIERS` |
| P9 | `fan_recheck_enabled` | Fan Recheck (master) | Master kill-switch for the fan-noise Mode-2 BLE-gated fan-pause+recheck. Default OFF; flip ON after live validation… | Fan recheck | When a ceiling fan may be fooling a room's presence radar, pause the fan briefly and see whether the room is really empty. Off = fans are never paused. The Fan Recheck switch on the Presence device controls the same thing; use the switch to change it. Default off. | `presence_fan_recheck.py:540-542` (`master_off` veto), `:1221`; `switch.py:5976`. Rev 2 (M4): no "same as" claim; the switch restores its last state over the option on (re)load (`switch.py:6040-6046`), so a form edit may be undone after the CM reload. Not tested here; card candidate FAN-RECHECK-FORM-RESTORE-REVERT-1. Label uses the switch's name ("Fan recheck") so one control has one name |
| P10 | section `fan_recheck_advanced` | Fan Recheck Timing (Advanced — rarely change) | Timing knobs for the fan-noise Mode-2 recheck state machine… | Fan recheck timing (rarely change) | The defaults suit most rooms. | — |
| P11 | `fan_recheck_arm_delay_s` | Arm Delay (s) | Delay between trigger eligibility and arming the recheck… | Wait before a check (s) | How long the signs of fan noise must last before the fan is paused. Default 60. | `presence_fan_recheck.py:1293-1335` `_timing_config`; `_enter_armed` `:735-745`, `_still_armed_eligible` `:1218` (L-T1) |
| P12 | `fan_recheck_spindown_s` | Fan Spindown (s) | How long airflow takes to stop… | Fan stop time (s) | How long the fan needs to stop after it is paused. The radar is ignored during this time. Default 30. | `_timing_config` |
| P13 | `fan_recheck_window_s` | Recheck Window (s) | Observation window after spindown… | Listening time (s) | How long the radar is watched with the fan stopped. If it goes quiet, the room is marked empty and the fan stays off. Default 60. | `_timing_config`; VACATED leaves the fan off (Presence STATE_OF_PLAY §6 item 3, `restore_after_recheck(leave_off=True)`) |
| P14 | `fan_recheck_cooldown_s` | Cooldown After Recheck (s) | Wait time between rechecks per room… | Time between checks (s) | Shortest time between two checks in the same room. Default 900 (15 min). | `_timing_config` |
| P15 | `fan_recheck_max_per_hour` | Max Rechecks Per Hour | Hard cap… 0 disables the cap… | Checks per hour (max) | Most checks one room can run in an hour. 0 = no limit. Default 2. | `presence_fan_recheck.py:659-668` |
| P16 | `fan_recheck_hvac_suppress_s` | HVAC Suppression Window (s) | How long HVAC fan-routing stays suppressed… | Keep HVAC off the fan (s) | After a check pauses a fan, how long HVAC fan control leaves that fan alone. Default 600 (10 min). | `_timing_config` |
| P17 | `fan_recheck_mmwave_history_ticks` | mmWave-Sole Consecutive Ticks | Number of consecutive presence ticks that must be mmWave-only… | Radar-only readings needed | How many room updates in a row must come from the presence radar alone (no motion, camera or other sensor) before a check can start. Default 3. | `presence_fan_recheck.py:588-589` |
| P18 | `fan_recheck_family_scaling_enabled` | Longer wait for slow radars | …(Hobeian presence radars x2, LD2410/LD2412 x3, other radars x1.5)… | Longer wait for slow radars (keep) | Give radar models that are slow to clear more listening time, up to 3x. Off = the same listening time in every room. Default on. | `sensor_capability.py:418-423` |

Presence fields that live on **room** steps:

| # | Step · key | Current label | Current description (short) | Proposed label | Proposed description | Reader checked |
|---|---|---|---|---|---|---|
| R1 | create + options `devices` · `room_fan_recheck_enabled` | (raw key) | (none) | Fan recheck in this room | Let the fan recheck (Presence settings) pause this room's fan. Needs Fan recheck on there too. This room's Fan Recheck switch controls the same thing; use the switch to change it. Default on. | `presence_fan_recheck.py:543-546`, `:1223-1225`; `switch.py:6065` (same restore shape as P9, M4) |
| R2 | create + options `devices` · `fan_recheck_l2_allowed` | (raw key) | (none) | Check when someone is next door | In a room with its own Bluetooth scanner, allow a check while people are home in this part of the house if a phone places them in a neighbouring room. Off = skip the check whenever anyone is in this part of the house. Default on. | `presence_fan_recheck.py:700-713` (L-T4); `switch.py:6123` |
| R3 | create + options `devices` · `fan_recheck_trust_sensors_ok` | (raw key) | (none) | Check without Bluetooth | In a room without its own Bluetooth scanner, allow a check on room sensors alone. Off = only rooms with a scanner are checked. Default on. | `presence_fan_recheck.py:720-727` |
| R4 | options `basic_setup` · `room_guest_occupancy_threshold_min` | Minutes of Unknown Occupancy Before Guest Mode | Minutes of continuous unknown occupancy before Guest Mode is triggered… **WRONG** | Visitor time in guest room (min) | Minutes someone not recognised must stay in this guest room before the house shows a visitor. Guest mode itself needs a day and a night here. Default 30. | `presence.py:5768-5778` → `_guest_room_gate_armed`; GUEST from the night-stay latch (`_compose_guest_gate`, STATE_OF_PLAY §2 step 3) |
| R5 | options `basic_setup` · `room_is_guest_room` | Is Guest Room | …will arm the guest signal… | Guest room | Mark rooms where guests sleep. A day and a night here turns on Guest mode; a shorter visit only shows a visitor. | `presence.py:5768` (`_discover_guest_rooms`); night-stay producer reads the same flag; entry needs a qualifying night plus ≥ 0.10 of the day window (`GUEST_STAY_DAY_MIN_FRACTION`, STATE_OF_PLAY §2 step 3) (L-T3) |
| R6 | create + options `sensors` · `presence_sensors` | Presence sensors | See people sitting still. | Presence sensors (keep) | Radar sensors that still see a person who is sitting or sleeping (mmWave presence models). Motion-only radars belong in Motion sensors. | `sensor_capability.py:125`; SENSOR_FLEET_CLASSES Rule 1 |
| R6b | create `sensors_confirm` · `presence_sensors` (strings key is wrongly `mmwave_sensors`) | (raw key) | (none) | Presence sensors | Same text as R6. Rename the strings key `mmwave_sensors` → `presence_sensors` (both files); the key `presence_sensors` is `CONF_MMWAVE_SENSORS` (`const.py:627`) | M5; `strings.json` `config.step.sensors_confirm.data` |
| R13 | create `sensors_confirm` · `door_sensor` (strings key is wrongly `door_sensors`) | (raw key) | (none) | Door sensor | Same text as the options `sensors` door field. Rename the strings key `door_sensors` → `door_sensor` (both files); `CONF_DOOR_SENSORS` = `door_sensor` (`const.py:1111`) | M5 |
| R7 | create + options `sensors` · `motion_sensors` | Motion sensors | See movement only. | Motion sensors (keep) | Sensors that see movement only: PIR, and mmWave motion models that lose a person who sits still. | SENSOR_FLEET_CLASSES table (ZV = motion-class) |
| R8 | create + options `sensors` · `occupancy_sensors` | Combined sensors | Radar and motion reported as one signal. | keep | keep | SENSOR_FLEET_CLASSES "Rule (corrected 2026-10-11)" |
| R9 | create + options `sensors` · `room_cameras` | (raw key) | (none) | Room cameras | Cameras that look into this room. They override the camera-to-room match from Home Assistant areas. | `camera_resolver.py:34` (operator-declared = ground truth); `fan_veto.py:368` |
| R10 | create + options `sleep_protection` · `sleep_start_hour` / `sleep_end_hour` | Sleep Start Hour / Sleep End Hour | Hour when sleep mode starts / ends | Room sleep starts (hour) / Room sleep ends (hour) | Hours this room's sleep protection is active. The house sleep window is set in Presence settings. | `automation.py:1297-1308`; note `aggregation.py:885` reads the first room's hours house-wide (plan INV-2; not changed by this pass) |
| R11 | options `person_tracking` · `person_data_retention_days`, `transition_detection_window` | Keep history (days) / Room change wait (s) | "Not used yet…" | keep | keep (accurate: zero readers outside `config_flow.py`; `const.py:183-184` say so) | grep: no reader |
| R12 | options `camera_census` · `main_entry_door` | Main entry door | …Used for arrival estimates… **WRONG** | Main entry door (not used) | Not used yet. Leave blank. | No reader outside `config_flow.py:5031-5032`, `:5293` |

### 3.2 Other coordinators (raw-key fields first, then the worst text)

| # | Step · key | Current label | Current description (short) | Proposed label | Proposed description | Reader checked |
|---|---|---|---|---|---|---|
| C1 | `coordinator_safety` · `safety_anomaly_sensitivity` | (raw key) | (none) | Unusual-reading sensitivity | How readily safety readings that look unusual are flagged. Normal suits most homes. | `safety.py:1238` |
| C2 | `coordinator_security` · `security_anomaly_sensitivity` | (raw key) | (none) | Unusual-activity sensitivity | Same choice for security events. | `security.py:853` |
| C3 | `coordinator_music_following` · `music_anomaly_sensitivity` | (raw key) | (none) | Unusual-activity sensitivity | Same choice for music following. | `music_following.py:241` |
| C4 | `coordinator_hvac_settings` · `hvac_anomaly_sensitivity` | (raw key) | (none) | Unusual-activity sensitivity | Same choice for heating and cooling. | `hvac.py:1817` |
| C5 | `coordinator_hvac_settings` · `hvac_ac_night_start_hhmm` / `hvac_ac_night_end_hhmm` | (raw keys) | (none) | AC reset night starts / ends | Clock times (HH:MM) of the night window for AC resets; the night has its own reset budget. | `hvac_override.py:2447-2460` `_is_night_now`; hot-applied `__init__.py:7108`, `:7126` |
| C6 | `coordinator_hvac_settings` · `hvac_arrester_immune_persons` | (raw key) | (none) | People whose thermostat changes stick | When one of these people changes a thermostat, URA keeps their change instead of putting the preset back (for a few hours). | `__init__.py:4503`, `:4536`; HVAC STATE_OF_PLAY §7 immune hold, §9e gate (a/b) |
| C7 | `coordinator_hvac_settings` · `hvac_carrier_stale_require_blind_corroboration` | (raw key) | (none) | Confirm before reloading Carrier | Before reloading a Carrier thermostat that has gone quiet, also require that it reads idle while its circuit draws power. Off = quiet time alone is enough. Default on. | `hvac.py:8548-8566`, `:8666`; `hvac_strategy.py:860-875`; `hvac_const.py:1510-1518` |
| C8 | `coordinator_hvac_settings` · `sleep_fan_on_temp_f` | (raw key) | (none) | Bedroom fan on at sleep above (°F) | When the house goes to Sleep, turn on an occupied bedroom's fan once if the room is at or above this temperature. 0 = off. Default 72. | `automation.py:4239-4276` (default 72.0, `:4241-4243`, L-T5); `fan_veto.py:615` |
| C9 | `coordinator_hvac_settings` · `energy_precool_enabled` | (raw key) | (none) | Energy saver pre-cool | Turn on the solar-aware pre-cool run by the energy coordinator (same as its switch on the Energy device). Default on. | `energy.py:1007-1008` → `HVACPredictor._is_energy_precool_enabled` (`energy.py:13865`); `hvac_const.py:87-99` (name + "unified PV-aware pre-cool", default ON) |
| C10 | `coordinator_hvac_settings` · `hvac_cover_open_temp` | Cover Open Temp | …(hysteresis with Cover Close Temp)… | Reopen blinds below (°F) | Outdoor temperature at which blinds URA closed for sun are opened again. Keep it at least 3 °F below the close temperature. | `hvac_covers.py:458-464` |
| C11 | `coordinator_hvac_settings` · `hvac_cover_entities` | Cover Entities | Cover entities for solar gain management… | Blinds for sun control | Extra blinds to close on hot, sunny days, on top of the covers in HVAC-zone rooms (a room can opt out on its Covers step). | `hvac_covers.py:170-189` `discover_covers`: room covers first (per-room `CONF_COVER_HVAC_MANAGED` opt-out), then this list adds covers not already found (rev 2, M2: rev 1 said "Empty = use each room's covers", which is wrong; the list never replaces room covers) |
| C12 | `coordinator_energy` · `energy_billing_source` | (raw key) | (none) | Cost from | How daily cost is worked out: Meter totals (kWh counters), Power readings, or Auto (meter totals when the grid sensors report kWh). | `energy.py:750`; `energy_billing.py:194-205` |
| C13 | `coordinator_energy` · `energy_offpeak_drain_very_poor` | (raw key; four siblings are labelled "Drain Target: …") | (none) | Overnight battery target: very poor solar | Battery level to drain to overnight when tomorrow's solar looks very poor. Same scale as the other four targets. | `number.py:1392`, `:1449`; `__init__.py:7364` |
| C14 | `coordinator_energy` · `energy_solar_follow_grid_entity` / `_fallback_entity` | (raw keys) | (none) | Grid power sensor for solar charging / Backup grid power sensor | The grid power reading used to match EV charging to spare solar; the backup is used when the first is unavailable. | `energy.py:686-705` (`SolarFollowController`) |
| C15 | `coordinator_energy` · `energy_solar_nameplate_w` | (raw key) | (none) | Solar system size (W) | Your solar system's peak output in watts. Used to bound what an old solar reading could mean. Empty = built-in default. | `energy.py:4952-4961` → `energy_battery.py:3730` |
| C16 | `coordinator_energy` · `energy_envoy_entity` | (label only) | (none) | keep | The Enphase gateway's status entity. Required for battery control; a repair appears if it is missing. Picking it fills in the other Enphase entities from its serial number. | `energy_const.py:2184-2188`; `repairs.py:73`; `repairs.py:79-83` `derive_envoy_config` (L-T6) |
| C17 | `coordinator_notifications_persons` · `nm_person_safe_word` | (raw key) | (none) | Safe word | This person's own safe word. Empty = use the house safe word. | `notification_manager.py:3262-3275` |
| C18 | `coordinator_notifications_persons` · `nm_person_digest_channels` | (raw key) | (none) | Digest channels | Which of this person's channels get the digest. Empty = the first channel set up for them (Pushover, then app, WhatsApp, iMessage). | `notification_manager.py:5530-5545` |
| C19 | `coordinator_notifications_quiet` · `nm_security_ack_persons` | (raw key) | (none) | Who can clear security alerts | Only these people can acknowledge a security alert. Empty = the first person in the notification list. Other alerts can be cleared by anyone who got them. | `notification_manager.py:3305-3322` |
| C20 | `coordinator_notifications_volume` · `stuck_sensor_exclusion_enabled` | (label) | …(STUCK-SENSOR-1 D1 rung-2 kill switch). | keep label | When on, a sensor stuck on is ignored when working out how busy a room is. | text only; ticket names removed |
| C21 | `coordinator_notifications_volume` · `nm_a1_tripped_breaker_route_nm` / `stuck_signal_nm_enabled` | Route Tripped-Breaker Alerts to NM / Stuck-Signal Watchdog NM Alerts | — | Alert on tripped breakers / Alert on stuck sensors | (keep descriptions; drop "NM") | text only |
| C22 | `coordinator_optimization` · `optimizer_kill_switch`, `optimizer_llm_task_entity`, `optimizer_llm_triage_entity` | Kill switch (pause everything) / LLM primary entity / LLM triage entity | — | Pause the optimizer / AI model for decisions / AI model for sorting | keep descriptions, drop "entity" | text only |
| C23 | `coordinator_security` · `security_camera_entities`, `security_light_entities`, `security_garage_entities`, `security_alarm_panel` | … Entities | — | Cameras / Security lights / Garage doors / Alarm panel | keep descriptions | text only |
| C24 | `coordinator_energy` (whole step) | 11 jargon labels (SOC, arbitrage, pp, kW guard) and 18 descriptions over 220 characters | — | **Deferred to a second energy sub-pass** | Energy wording is a money surface; the parked energy O9-O13 consumer audit (FORM-CONDITIONAL-FIELDS-1 §10) reads the same readers. Do the energy text with that audit, not here. | — |

### 3.3 Room and zone steps

| # | Step · key | Current label | Current description (short) | Proposed label | Proposed description | Reader checked |
|---|---|---|---|---|---|---|
| Z1 | create `zone_setup` · `zone_is_outdoor` | (raw key) | (none) | Outdoor zone | REUSE options `zone_rooms` text: "Turn on for patios, yards and pool areas. Safety uses outdoor limits and the house count ignores people here." | `presence.py:1979-1990`, `:7085-7093` |
| Z2 | options `devices` · `night_light_sleep_brightness`, `_sleep_color`, `_day_brightness`, `_day_color` | (raw keys) | (none) | REUSE create `night_light_detail` labels ("Night Light Brightness (Sleep)" …), sentence-cased | REUSE its descriptions | `lighting/resolver.py:206-235`; `switch.py:5668-5670` |
| Z3 | create `cover_behavior` · `cover_open_mode`, `cover_open_time_source`, `cover_open_hour`, `cover_close_time_source`, `cover_close_hour` | (raw keys) | (none) | REUSE options `options_covers` labels | REUSE its descriptions, with the Z4 fix | `automation.py:2181`, `:2253-2263`, `:2733-2745` |
| Z4 | create + options covers · `cover_close_time_source` / `cover_close_hour` | Close Time Source / Close Hour | Use sunset or a specific hour for timed close **WRONG (incomplete)** | Close time from / Close hour | When the covers' day ends (sunset or a set hour). Used by timed close and by sun control, which treats covers as meant to be open only before this time. | `automation.py:2733-2770`; also read by the open-intent check `:2233-2246` regardless of Timed close |
| Z5 | create `cover_behavior` · 6 legacy keys | stale | — | delete from both files | — | not on the form (§1) |
| Z6 | options `automation_behavior` · 16 keys | stale | — | delete from both files | — | no options step `automation_behavior` |
| Z7 | create + options `climate` · `climate_entity` | Climate/Thermostat Entity (fallback) | — | Thermostat | keep description | text only |
| Z8 | options `sensors` · `sensor_capabilities_json` | Sensor Capabilities (advanced) | Advanced JSON that tags each sensor with its kind and trust class… | Sensor types (advanced) | Only for sensors the lists above get wrong. Leave as is unless asked to change it. | converted to `sensor_capabilities` at `config_flow.py:13216` |
| Z9 | options `basic_setup` · `shared_space_auto_off_hour` / `_cutoff_hour` | Auto-Off Hour / Auto-Off Give-Up Hour | "…the night failsafe starts…" | keep | replace "failsafe" with "night clean-up" | text only |
| Z10 | options `options_lighting_behaviour` · `light_dark_lux_source` | Borrow another room's light sensor | — | keep | keep | — |

---

## 4. Acceptance criteria (for the D3 build that carries this text)

- **Verify:** every key the AST scan finds on a form has a label in its step; a field inside a section is resolved against `sections.<name>.data` / `.data_description`, not the step's `data` (rev 2, plan review 3 M1; the scan also follows helper-argument keys, M5) (scan reports 0 raw-key fields, excluding the documented dynamic-key steps). **Test:** `test_every_form_field_has_label` (walks the real step schemas, as the D2 harness does).
- **Verify:** every labelled field has a `data_description`, except fields in an explicit, commented allowlist. **Test:** `test_every_form_field_has_description`.
- **Verify:** no label contains a denylist word; no description contains a ticket id (`[A-Z]+-[A-Z0-9-]+-\d`), "rung", "Mode-2" or "kill-switch". **Test:** `test_form_text_denylist` (extends the DPM label-pass test).
- **Verify:** `strings.json` and `translations/en.json` equal for every touched step (keys and values). **Test:** extend the existing parity test.
- **Verify (discriminating):** the eight WRONG rows are replaced. A test pins P3, P4, P5, R4, R12, and (rev 2) C11 and P6 text to the absence of the old claims ("enters Guest mode", "arrival estimates", "geofence-based", "Empty = use each room's covers", and P6 without its "unless the cameras" clause), so a revert to the old text fails, while a pure re-wording passes.
- **Live:** open Presence settings, a room's Devices step, and the create flow's Cover step: no field shows a raw key; Presence fan-recheck fields read as in §3.1.

## 5. Findings that are not text (card, do not fix in this pass)

| Finding | Evidence | Suggested card |
|---|---|---|
| `geofence_entities` is stored but never read | `__init__.py:3608` imports it, nothing passes it; `presence.py:5187-5213` subscribes to every `person.*` (location from HA People settings + `zone.home`) | PRESENCE-GEOFENCE-FIELD-DEAD-1 (removal candidate; wiring it as a filter would duplicate HA's per-person tracker choice) |
| Fan Recheck form field vs switch: the switch restores its last state over the option after a reload, so a form edit may be undone at runtime | `switch.py:6040-6046`; key not in `OPTIONS_RELOAD_SUPPRESS_KEYS` | FAN-RECHECK-FORM-RESTORE-REVERT-1 (verify with one test through the reload; same for the per-room switch `switch.py:6065`) |
| `main_entry_door` has no reader | only `config_flow.py` | CAMERA-MAIN-ENTRY-DOOR-DEAD-1 |
| Fan-check timing knobs are read live (`_timing_config` reads CM options per call) but are not in `OPTIONS_RELOAD_SUPPRESS_KEYS`, so each save reloads the CM entry | `presence_fan_recheck.py:1293-1335`; `__init__.py:7526` | candidate for the reload-suppress allowlist (performance; out of FORM-CONDITIONAL-FIELDS-1 scope by its §10) |
| Room fan speeds are read in Follow-thermostat rooms too (room-tier fallback), but the create flow asks for them only in Room-temperature mode | `automation.py:2789-2801`, `:3204-3206`; create `fan_speeds` step | note on FORM-CONDITIONAL-FIELDS-1 O4 (plan §13) |
