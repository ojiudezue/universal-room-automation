# AUDIT: legacy pre-URA zone automations, lessons before retirement (2026-10-18)

Read-only review. Written 2026-10-18 13:45 CDT (`date` at start: 13:38 CDT). Nothing was changed in
`/Users/okosisi/ha-config`; the retirement is the operator's / parent agent's to do.

Read first, completely, before writing: `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`,
`docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md`, `docs/architecture/SENSOR_FLEET_CLASSES.md`.

Live-state caveat: automation / helper states below come from `.storage/core.restore_state` (last
write by HA), not a live `ha_get_state`. Treat "on/off" as last-restored. Everything else is read from
the files cited.

## 1. Answer first

- **All four legacy HVAC automations in scope are already OFF** (restore_state): `upzone_tracker_v2`
  (last triggered 2026-06-07T23:57Z), `upzone_hvac_v2` (`last_triggered: None`, i.e. it has never run),
  `1750918079582` (last 2025-09-11), `1750956584750` (last 2025-09-04). Retiring them changes no live
  behaviour. What retirement can break is **dashboards and two helper-name collisions** (section 5).
- **WORTH CARRYING: 4 small items, none urgent** (section 4). The biggest design ideas (preset-first,
  hold-by-room-type, sleep protection, transit filter, window pause, pre-arrival pre-cool, borrow
  restore) are already in URA, usually in a stronger form.
- **The still-ON counter / alert automations are inert and superseded; retire them** (section 6).
  `input_boolean.zone1_monitoring_active` / `zone3_monitoring_active` are OFF, so every counter, alert
  and the daily summary fails its condition. Only the midnight counter-reset still fires.
- **Real defects found in the legacy code** (so nobody revives it by copy): section 7.

## 2. Inventory (what each piece is)

| Piece | File:line | State (restore_state) |
|---|---|---|
| UpZone Tracker 2.0 (presence state machine, 5 states, confidence, quiet-common decay) | `packages/upzone_zone2_package.yaml:126-299` | off |
| UpZone HVAC 2.0 (preset-first, windows guard, night guard, pre-cool, people-aware fan) | `packages/upzone_zone2_package.yaml:301-468` | off, never triggered |
| `script.upzone_update_meta` (JSON merge into `input_text`, 255-char) | `packages/upzone_zone2_package.yaml:80-123` | defined |
| `input_select.upstairs_zone_presence_state` (YAML) / `input_text.upstairs_zone_meta` | `:68-78` | YAML select became `..._state_2` (collision, section 5) |
| Template: `upzone_media_room_occupied`, `upzone_windows_open` | `:54-66` | live |
| Template: `upzone2_people_count/confidence/trigger_source/last_bedroom_activity/precool_until` | `packages/upzone_zone2_template_sensors.yaml` | live, all read the meta JSON |
| Template: `upzone2_precool_active/precool_blocked/precool_status` | `packages/upzone_zone2_template_sensors_extras.yaml` | live |
| Zone 1 "Motion-Based HVAC Control with Sleep Protection" | `automations.yaml:1992-2200` (id 1750918079582) | off |
| "Zone 2 ... Smart Dwell Detection" (uses `zone3_*` helper names) | `automations.yaml:2201-2505` (id 1750956584750) | off |
| `input_text.zone1_cooling_state`, `zone3_state` | `configuration.yaml:122-131` | defined |
| Zone monitoring package (counters, inactivity alerts, daily summary, utility meters) | `packages/zone_monitoring.yaml` | see section 6 |

## 3. Idea-by-idea comparison

Legend: AIU = ALREADY IN URA, WC = WORTH CARRYING, OBS = OBSOLETE / WRONG.

### 3.1 Presence / tracker ideas (UpZone Tracker 2.0, Zone 2 dwell automation)

| Legacy idea (source) | Class | URA today / reason |
|---|---|---|
| Dwell confirmation: stair sensor `on` arms a 2-min stair timer, person-detected arms a 2-min dwell timer, then cooling starts (`automations.yaml:2217-2224, 2273-2315`) | **AIU** | D5 ENTRY TRANSIT FILTER: an away-edge entry arms only after 60 s of persisted evidence (knob 47 default 1 min), holds the preset while pending, spell capped 600 s, return window knob 52 (HVAC SoP 3.2; code `hvac_zones.py` `_d5_update`, `transit_filtered_today` at `hvac_zones.py:371`). Stronger: persisted evidence, room-keyed, capped, with a skip-entry-wait room option. |
| Early detection from stair camera (`binary_sensor.stairs_top_person_detected/motion`) to start the fan before dwell completes (`:2217-2243`) | **OBS** (as designed), partial **AIU** | The camera sensors still exist (`stairs_top_*` unifiprotect + frigate `_2`, registry). URA's equivalent early signals are pre-arrival (BLE/geofence/face, `DEFAULT_PRE_ARRIVAL_SOURCES = [geofence, ble, camera_face]`, `hvac_const.py:350`) and camera-in-shared-space handling (`transit_validator.py:684`, `const.py:2766`). Starting a fan on a bare stair motion event is the false-positive shape URA's fan work spent weeks removing (Presence SoP section 6). |
| Confidence score 100/80/20/0 by source (mmWave 100, camera/BLE 80, quiet 20, away 0) (`upzone_package.yaml:221,256,276,292`) | **OBS** | A fixed ordinal ladder. URA's equivalents are capability-class trust (`sensor_capability.py:172`, trust classes), `check_zone_occupancy_confidence` (`hvac.py:3077`, `PresenceCoordinator.check_zone_occupancy_confidence`) and the tri-state establishment gate (`hvac_zones.py:1043-1112`). Note the legacy puts mmWave at 100 although ZV mmWave is motion-class and ZK/ZX radars are fan-susceptible (SENSOR_FLEET_CLASSES Rules 1, 3). |
| Trigger-source taxonomy: `bedroom_mmwave|camera|stairs|ble|path|quiet_common|away_confirm|window|hvac|system` (`:87`) | **AIU** (and the taxonomy was never fully implemented) | URA records evidence provenance: `occupancy_source` label (Presence SoP section 10 #10), per-tick `STATE_RADAR_SOLE_TICK`, HVAC `decision_log` / `ura_activity_log` rows with `reason`, `manual_class`, `gate_snapshot` (HVAC SoP 4.2, 9e). Only `bedroom_mmwave`, `ble`/`camera` (a broken literal, section 7), `quiet_common`, `away_confirm`, `hvac` were ever written. `stairs`, `path`, `window`, `system` never were. |
| Five-state machine arriving / likely_present / confirmed_present / pending_departure / confirmed_away | **AIU** | `HouseState` enum + inference ladder (`house_state.py:56-67`, Presence SoP 2); zone-level `ZonePresenceTracker`; per-room hvac_occupied with armed/tail states. |
| Quiet-common decay: common camera quiet 30 min -> pending_departure -> after 15 more min -> confirmed_away (`:168-172, 269-297`) | **AIU**, with a better night rule | Per-room-type evidence hold (`ROOM_TYPE_HVAC_HOLD`, day 60-240 s) plus vacancy grace knob 48 (live 5 min) and an exact-release exit timer (HVAC SoP 3.1, 3.2). Legacy 45 min total quiet vs URA ~5-10 min is a deliberate shortening: URA's evidence is per room, not a single camera group. See also 3.2 sleep protection for why the legacy decay was unsafe at night. |
| Away-confirm re-checks both camera groups are still off after the delay (`:283-288`) | **AIU** | `conditioning_retreat_ok` = established AND fused-empty (HVAC SoP 3.2, `hvac_zones.py:1085`); AWAY path alpha re-checks `unidentified_count == 0 AND face_recognized_count == 0` (`presence.py:1169-1180`). |
| People count = number of rooms with mmWave on, +1 if BLE/camera (`:190-197`) | **OBS** | A room count, not a person count. URA has census (camera_census), `person_coordinator` per-person room, `identified_people_count` sensors (e.g. `sensor.media_room_identified_people_count`, registry). |
| Media room "occupied" = native Meross numeric presence `> 1` (`:56-60`) | **AIU** | Presence SoP / SENSOR_FLEET_CLASSES "Meross MS600 (dual-homed)": Matter binary occupancy filed in `presence_sensors`, meross_lan motion bit in `motion_sensors`. The native numeric (value 2 = present per meross_lan `ms600.py:249`, UNVERIFIED on our units) cannot be wired to URA (binary-only selectors). The legacy `> 1` threshold is therefore a second, unverified reading of the same field. The live URA entity is `binary_sensor.media_room_occupied`. |
| BLE "home" plus Bermuda floor/area hint (`sensor.iphone_jaya_floor/area`) as a weak upstairs hint (`:200-203`) | **AIU** | `person_coordinator` three-tier scanner ladder, `CONF_SCANNER_AREAS` (`const.py:564`), fleet-liveness gate (`person_coordinator.py:67`). The legacy rule `'up' in jaya_area` is a substring match on an area name, exactly the name-regex class the SoP forbids ("classify by capability, never by name"). |
| Stuck-input idea: none | n/a | (Legacy had no stuck-sensor handling; URA has chatter + duty-cycle stuck, Presence SoP 4.3-4.4.) |

### 3.2 HVAC ideas

| Legacy idea (source) | Class | URA today / reason |
|---|---|---|
| Preset-first control (home 77 / away 80 / sleep 78 / wake 78, `hvac_mode heat_cool`) (`upzone_package.yaml:322-326`) | **AIU** | S1 house-state/occupancy preset (`hvac.py:2674`), Seasonal Baseline ranges per preset (`hvac_const.SEASONAL_DEFAULTS`, HVAC SoP C30), Custom Preset Ranges edit the named profile on the device. Legacy hard-codes one point value per preset, year-round, on the YAML. |
| Sleep protection Zone 1: only go `away` after 1 h no camera motion, and not if there was motion within the pre-sleep window (sleep_start minus 2 h) while inside sleep hours (`automations.yaml:2012-2041`) | **AIU** | Night tail-hold `ROOM_TYPE_HVAC_HOLD_NIGHT` (bedroom/media 30 min, `const.py:1590`), selected only in house sleep/waking (`HVAC_NIGHT_HOLD_STATES`, HVAC SoP 3.1); D7 night-trust (`hvac.py:2403`); sleep exemption on D2 sustain demotion (`coordinator.py:2190-2210`); house SLEEP state from census + sleep hours (`presence.py:1017-1025`). The legacy "pre-sleep motion" window is a poor proxy for a sleeping person; URA's pre-existing documented night failure (Jaya, HVAC SoP 9.3) is the same shape, and was fixed at the sensor and hold-knob level. |
| Still-energy guard: only go away if `sensor.bedroom_still_energy_1h_avg <= 5` (`automations.yaml:2042-2048`) | **OBS as built, idea = WC** | The entity `sensor.bedroom_still_energy_1h_avg` is **not in the entity registry** (checked), so `states(...)|float(0)` is 0 and the guard was always true: it never protected anything. The idea (use mmWave still-energy as a human-vs-phantom corroborator) is real and is already a parked URA TODO: `coordinator.py:3871-3880` (probe 2026-08-01: phantom still_energy 33-47 tight band vs human median 79) and card `MMWAVE-STILL-ENERGY-CORROBORATOR-#6` (`kanban.data.yaml` ~line 29791, "NOT ready: still_energy is recorder-EXCLUDED, per-gate needs engineering_mode"). No new card; add nothing. |
| Pre-cool on validated arrival: only if outside >= 84 F, windows closed, arrival seen within 120 s (BLE home edge or upstairs hall / playroom person), target high = preset - 1 F for up to 30 min, ends when indoor <= preset+1 (`upzone_package.yaml:366-385, 426-460`) | **AIU** for the arrival + window + window-length parts; **WC** for the outdoor-temp gate | URA pre-arrival pre-cool: person-routed (`hvac.py:7042-7080`), one write from the baseline at `PRE_ARRIVAL_PRECOOL_OFFSET_F = -2.0` (`hvac_const.py:500`, `hvac_predict.py:699`), window knob 35 (5-110 min, `hvac_const.py:360-363`), ends on arrival/timeout/interrupt (HVAC SoP 4.2 S12), skipped if egress-paused (`hvac_predict.py:1275`). URA has **no outdoor-temperature gate on a pre-arrival pre-cool** (`hvac_predict.py:1258-1340`; outdoor temp is used only by the energy pre-cool forecast, `PRECOOL_FORECAST_HIGH` 90 F, `hvac_const.py:157-160`, and zone demand, `hvac_predict.py:375-398`). See WC-1. |
| Gradual cooling: when returning from away and outside > 75 F and the preset is more than 3 F below the held setpoint, step the setpoint down 2 F then 1 F per step, one step per 45-min timer, stop when remaining diff < 2 F (`automations.yaml:2090-2124, 2150-2200`; zone 3 copy `:2330-2505`) | **WC (measure first)** | Not in URA (grep for `gradual|cooling_step|step_down` in `domain_coordinators`: none relevant). Purpose = soften the post-away recovery compressor/peak-kW spike. URA's nearest are pre-arrival pre-cool (a single -2 F step) and D5 duty-cycle coast/shed (`hvac.py` D5, HVAC SoP 8). See WC-2. |
| Windows guard: any kid-room window open >= 5 min -> HVAC off, resume 2 min after all closed (`upzone_package.yaml:396-421`) | **AIU** (and the legacy never implemented the delays) | EgressManager: pause threshold default 3 min (`hvac_const.py:1418`, range 1-15), resume delay default 1 min (`:1424`, range 1-10), per-room `CONF_IS_EGRESS_WINDOW` (`hvac_zones.py:119-123`, `:797-871`), 30 s manual-override grace + 1 h cooldown (`hvac_const.py:1429-1430`), pre-cool skipped while paused (`hvac_predict.py:1275`). Legacy bug: the notification says ">=5m" but the code reads the sensor state immediately (section 7). |
| Night guard: 22:00-07:00, plus 21:00-22:00 if any upstairs sensor changed in the last hour, do not drop to `away` on silence alone (`:329-347`) | **AIU** | House SLEEP/WAKING selects the night hold (above); `HVAC_NIGHT_HOLD_STATES`. The "primed by presence in the 21:00 hour" logic is a time-of-day heuristic URA replaced with state-machine + per-room evidence. Also the legacy `recent_any_upstairs` template is likely broken (section 7). |
| People-aware fan: 1 -> 40% (30% at night), 2 -> 60%, >=3 -> 80%, +10% if media room occupied, cap 90 (`:386-392`) | **OBS** | URA's fan model is per-room Fan Mode (Follow thermostat / Room temperature / Off, `fan_owner`, HVAC SoP 4.2b) with temperature-driven control and AWAY-veto (`fan_veto.py`). Speed scaling by head-count has no URA analogue and the head-count input is a room count (3.1). Fan percentages are knobs-by-literal, contrary to "Numbers Get Knobs". Not carried. |
| Fan on at 67% for away + outside > 75 F (`automations.yaml:2237-2243`) | **OBS** | An away-preset fan in an empty room is the behaviour `fan_veto` (comfort-fan house-AWAY veto) exists to prevent (Presence SoP 6 item 4). |
| `vacation_mode` input_boolean as a master condition (`automations.yaml:2009-2011, 2223-2225`; boolean state `off`) | **AIU** | `HouseState.VACATION` (`house_state.py:67`, min 2 h, `:138`). The `input_boolean.vacation_mode` helper is also used by `automations.yaml:1751234966076` Landscape Lighting etc.; do not remove that helper. |
| Pre-cool status chips (`active / blocked / idle`), `upzone2_precool_*` (`..._extras.yaml`) | **AIU** (better) | Pre-arrival borrows + `hvac_excursion_events`, `sensor.<room>_precool_start_time/_lead_minutes`, borrows sensor (HVAC SoP 6, 4.2). The legacy "blocked" = windows open AND warm AND arrival, which is the same state URA expresses as egress-paused. |
| Notifications with emoji taxonomy (arriving / present / pending / away / pre-cool start/done / window pause/resume) via Pushover | **OBS** | URA's NotificationManager with severity channels (companion HIGH+, rest CRITICAL per HVAC SoP 4.2 S10 latch note). Per-event "nothing broke" pushes were noise; the pattern only matters for the **HIGH latch/stuck alerts** URA already has. |
| `mode: restart` on a 15-min `delay` away-confirm | **OBS** | A delay in an automation is destroyed by any new trigger (`mode: restart`), so a `confirmed_away` can only land when no sensor fires for 15 min, and the run is also abandoned on restart. URA's exit uses a persisted exact-release timer (HVAC SoP 3.2) and rehydrates across restarts (Presence SoP 8). |
| Idempotent writes: legacy sets the preset every 10 min (`time_pattern /10`) and on every sensor change (`:316-317, 423-424`) | **OBS / lesson** | Carrier cloud calls are rate-bounded (`HVAC_DECISION_TICK` 5 min, "cloud API call-rate bound", HVAC SoP 2). Re-writing an unchanged preset also re-hits the Carrier hold/echo problems (HVAC SoP 9.1). URA gates writes: `hold_needs_reassert`, S1 skip when already at target, 60 s per-zone limiter, 6/h write ceiling. |

### 3.3 Infrastructure ideas

| Legacy idea | Class | Note |
|---|---|---|
| JSON "meta" blob in a 255-char `input_text`, merged by a parallel script (`max: 20`) | **OBS** | `input_text` caps at 255 chars; the meta keys (confidence, source, direction, bedroom activity, people, jaya{...}, precool_until) risk silent truncation, and `from_json` on a truncated string raises. URA persists state in HA Store / DB (`house_state.py:26-54`, `_zone_state_store` side-keys). Lesson only. |
| Zone cooling state machine in `input_text` + `timer` helpers (`zone1_cooling_state`, `zone3_state`, `timer.zone[13]_cooling_step`) | **OBS** | Same lesson; and a naming trap: "Zone 2" automation 1750956584750 uses `zone3_*` helper names and camera group `..._zone3`, because the camera groups are keyed by HOUSE zone 3 (upstairs) while the thermostat is HVAC zone_2 `climate.up_hallway_zone_2` (memory `project_house_zones_vs_hvac_zones`; HVAC SoP 1 lists `up_hallway_zone_2` as zone_2 "Upstairs"). |

## 4. WORTH CARRYING (URA lacks it, has value). Proposed cards, none above Tier 1-2

1. **HVAC-PREARRIVAL-OUTDOOR-GATE-1 (WC-1).** Skip (or shrink) the pre-arrival pre-cool when outdoor
   temp is below a knob (legacy used 84 F; a pre-cool at 70 F outside is wasted energy). Producer:
   existing outdoor sensor already read by `hvac_predict._get_outdoor_temp` (`hvac_predict.py:376`).
   Consumer: the `from_baseline=True` branch `hvac_predict.py:690-700`. Knob placement: rung 3 Number
   (live-tunable policy), kill switch = 0. Decompose first (Marginal-Benefit rule): the simplest
   version is a single threshold on the existing call; measure how many pre-arrival pre-cools in the
   last 30 days happened with outdoor < 80 F (`hvac_excursion_events` site `S12_pre_arrival` joined to
   the weather history) before building. If the count is near zero, PARK.
2. **HVAC-RECOVERY-STEP-DOWN-1 (WC-2, measure-first, expect PARK).** Stepped setpoint descent on
   away->home recovery (legacy: 2 F then 1 F per 45 min). Pure idea; the unknown is whether the
   Infinity systems' recovery produces a peak-kW spike worth shaving. Probe first: ODU Var % /
   energy for zone recoveries on the recorder (precedent: D5 re-ground on ODU Var %, HVAC SoP 11 W3).
   Ingredient risk is high (a new writer to the thermostat that stacks with S1, nudges, arrester
   borrows, W1-B gates), so unless the probe shows a clear spike this should be PARKED with the
   trigger "measured recovery peak > X kW and TOU on-peak overlap".
3. **FLEET-LOG: legacy-entity retirement checklist (WC-3, process, no code).** The two
   registry collisions in section 5 (bare vs `_2` helper, entity name vs unique_id) are the same
   class as DEVICE_ENTITY_DEFRAG_POSTMORTEM mistakes: add them to the retirement checklist the
   operator is using. Not a card.
4. **MONITOR-HEALTH-REPLACEMENT (WC-4, small).** The only non-obvious lesson in the monitoring package
   is the daily summary's "Reliability: Zone1 Good if motion events > 5" (`zone_monitoring.yaml`
   Multi-Zone Daily Summary). It is a crude camera-fleet-liveness canary. URA's equivalent is the
   FRIGATE-FLEET-DARK gate (`presence.py:1073-1085`, `camera_input_degraded`). No card needed; noted
   so the idea is not lost.

Anything else the legacy did that I did not list is either AIU or OBS above.

## 5. What retirement breaks (consumers)

Method: grep of `/Users/okosisi/ha-config` for every entity/helper name defined by the scoped files
and by `zone_monitoring.yaml`, across `automations.yaml`, `scripts.yaml`, `scenes.yaml`, `groups.yaml`,
`configuration.yaml`, `packages/`, `.storage/lovelace*`, plus the URA code tree. Registered dashboards
from `.storage/lovelace_dashboards`.

### 5.1 Dashboards (these WILL show errors / "entity not found" after retirement)

| Dashboard (id, url_path, in sidebar) | Entities from retiring pieces | What breaks |
|---|---|---|
| **`ura_v6` (`ura-v6`, sidebar TRUE)** `.storage/lovelace.ura_v6:1506,1508` | `binary_sensor.upzone_media_room_occupied` | A "Media Room" tile (Occupied/Vacant + icon colour). **Only live-dashboard breakage.** Replace with URA's own `binary_sensor.media_room_occupied` (exists, platform `universal_room_automation`, registry). |
| `ura_v3` (`ura-v3`, hidden) `.storage/lovelace.ura_v3:312-317` | same sensor (4 refs) | same tile; hidden, old version. |
| `zone_monitor` (`zone-monitor`, hidden) | `upzone2_confidence`(5), `upzone2_people_count`(3), `upzone2_precool_status`(5), `upzone2_pre_cool_status`/`_blocked`, `upzone2_last_bedroom_activity`, `upzone2_trigger_source`, `upzone_windows_open`(3), `input_select.upstairs_zone_presence_state`(6), `counter.zone[13]_{motion,person}_events`, `input_boolean.zone[13]_monitoring_active`, `sensor.zone[13]_{motion,person}_weekly` | The whole page is the UpZone / monitoring console. Retire the dashboard with the package. |
| `master_bedroom` (`master-bedroom`, hidden) | `counter.zone[13]_*_events` (6 each), `zone[13]_monitoring_active`, `sensor.zone[13]_*_weekly` | Only the monitoring-counter widgets (a Zone Monitor section embedded in the bedroom dashboard). |
| `ura_v8`, `ura_v7`, `ura_v5`, `ura_v4`, `ura_v2`, `ura_tabbed`, `ura_diagnostics`, `dashboard_*`, energy, map | **none** (grep matched only zone_monitor, ura_v3, master_bedroom, ura_v6) | No impact. |

### 5.2 Automations / scripts / helpers (other consumers)

- `script.upzone_update_meta`: called only from the two UpZone automations (`upzone_package.yaml:219,254,275,291,434,450`). No other caller in `automations.yaml`, `scripts.yaml`, `scenes.yaml`.
- `binary_sensor.upzone_windows_open`: read by `upzone_hvac_v2` and by `upzone2_precool_blocked` template; dashboards above. No other consumer.
- **Helper-name collision to know about.** The YAML `input_select.upstairs_zone_presence_state`
  (`upzone_package.yaml:68-72`) did NOT become that entity id. The bare id belongs to a UI helper
  (`.storage/input_select`: id `zone_3_presence_state`, name "Upstairs Zone Presence State";
  registry unique_id `zone_3_presence_state`). The YAML one registered as
  `input_select.upstairs_zone_presence_state_2` (registry unique_id `upstairs_zone_presence_state`;
  restore_state `confirmed_away`). Consequences: (a) the UpZone automations and the zone_monitor
  dashboard actually read/write the **UI helper** (restore_state `pending_departure`), not their own;
  (b) the other still-defined disabled automations `1757048728795` Upstairs Zone Presence Tracker and
  `1757048975329` Upstairs Zone Enhanced HVAC (both OFF) share that UI helper. **Retire the YAML
  package only: that deletes `..._state_2`. Do NOT delete the bare UI helper if those two automations
  are being kept; delete it only with them.**
- `timer.zone1_cooling_step` / `timer.zone3_cooling_step` are UI-storage timers (not defined in
  YAML; registry platforms `timer`), referenced by `1750918079582`, `1750956584750`, and also by the
  OFF automations `1756948521652` (Zone 2 Enhanced v2) and `1757048975329`. Retire timers only with all four
  of those.
- `input_text.zone1_cooling_state` is referenced only by `1750918079582`. `input_text.zone3_state` only by
  `1750956584750`. Safe to remove with their automations (`configuration.yaml:122-131`).
- Cross-references to **non-scoped but related** things that are not removed: `input_boolean.vacation_mode`
  (many automations), `input_datetime.sleep_start_time/sleep_end_time` (exist, used by the legacy
  sleep-guard and by the other disabled automations; check before deleting), `fan.game_room_ceiling_fan`
  (the legacy HVAC fan target; registry shows two Game Room fans: bare `fan.game_room_ceiling_fan` platform `bond`, and `fan.game_room_ceiling_fan_2` platform `homekit_controller`, which SENSOR_FLEET_CLASSES names as the URA-tracked fan; the bare one has no restore_state record. Which is live: unknown, not verified), camera groups
  `binary_sensor.binarygroup_camera_*_zone[13]` (read by the legacy and by `zone_monitoring.yaml`; groups
  are in `groups.yaml`/config entries, keep).
- URA code: grep of `custom_components/universal_room_automation` for `upzone`, `upstairs_zone_presence`,
  `zone1_cooling`, `zone3_state`, `zone_monitoring_active`, `zone[13]_minutes_since` returns **no hits**.
  No URA code, test or PWA reads any of these. (`pwa` path not present in the tree; grep returned
  nothing.)
- Orphans to clean in the entity registry after retirement (registry entries, not YAML): the 10 `upzone*`
  template entities, `script.upzone_update_meta`, `input_select.upstairs_zone_presence_state_2`, 2 automation entities.

### 5.3 Net list of what retiring each piece breaks

1. UpZone package + two template files: ura_v6 media tile (fix first), ura_v3 tile, zone_monitor page; nothing else live.
2. Automations 1750918079582 / 1750956584750 + `zone1_cooling_state` / `zone3_state`: nothing live (OFF since 2025). Leave the two timers and the UI select for the other disabled automations.
3. Zone monitoring package: zone_monitor page, the master_bedroom monitoring widgets, `sensor.zone[13]_*_weekly` utility meters (they have no other reader).

## 6. The still-ON automations in `packages/zone_monitoring.yaml`

Names in the brief (`zone_1/zone_3 inactivity_alert`, `motion_event_counter`, `person_event_counter`) are
entity ids `automation.zone_1_inactivity_alert`, `automation.zone_3_inactivity_alert`,
`automation.zone_[13]_motion_event_counter`, `automation.zone_[13]_person_event_counter`; they are
**YAML package automations without `id:`**, so they do not appear in `automations.yaml`.

| Automation | What it does | State |
|---|---|---|
| Zone N Motion Event Counter | on camera-group motion `on`: `counter.increment` + a mobile push "Motion Event #n", **only if** `input_boolean.zoneN_monitoring_active` is on (`zone_monitoring.yaml:150-170, 193-214`) | on; last_triggered 2026-08-13; counters read 0 |
| Zone N Person Event Counter | same for person detected | on; last 2026-08-13 |
| Zone N Inactivity Alert | when `sensor.zoneN_minutes_since_activity` crosses 45, push "Consider HVAC away mode?", 1-hour rate limit via `this.attributes.last_triggered`; same monitoring-active condition | on; **`last_triggered: None`**, never fired |
| Multi-Zone Daily Summary (22:00) | pushes counters + a crude "Reliability Good/Low" (motion events > 5) | on; last 2026-08-12 |
| Multi-Zone Reset Daily Counters (00:00) | resets the four counters | on; **last 2026-10-18T05:00Z, the only one still doing anything** |

- Gate: `input_boolean.zone1_monitoring_active` and `zone3_monitoring_active` are **off** in restore_state
  (the file's own comment at `zone_monitoring.yaml` records "operator turned OFF", ZONE-MON-LEAK-1,
  2026-08-12). Every counter/alert/summary therefore fails its condition. They are monitoring tooling
  for the retired Zone 1 / Zone 3 camera-motion HVAC automations: "Consider HVAC away mode?" is a human
  prompt for the decision URA now makes (vacancy grace + exit timer, HVAC SoP 3.2).
- A latent bug: the inactivity rate-limit does `(now() - this.attributes.last_triggered | default(now() - timedelta(hours=2)))`.
  `default()` replaces **undefined**, not `None`, so on the first run (`last_triggered: None`) the subtraction
  would error. By inspection, not executed. It is why this never mattered: it never fired.
- **Verdict: superseded and inert; retire all of them.** Replacements already live: per-room
  `sensor.<room>_time_since_motion`, `_time_occupied_today`, `_occupancy_7_days`, `binary_sensor.<room>_occupancy_anomaly`
  (registry, platform `universal_room_automation`, e.g. `sensor.media_room_closet_time_since_motion`) and the camera-fleet
  health gate (`presence.py:1073-1085`). Retire the template sensors in the same file too
  (`zone[13]_last_motion`, `_last_person`, `_presence_status`, `_minutes_since_activity`), the four
  counters, two monitoring booleans and four utility meters, and the daily summary and reset automations.
  Dependents: zone_monitor and master_bedroom dashboards only (section 5.1). The package comment
  "legacy pager" confirms the intent.

## 7. Defects in the legacy code (so nobody copies it)

All by reading; none were executed. Line numbers are in the cited file.

1. `upzone_package.yaml:257` `trigger_source: ble if is_state('device_tracker...','home') else 'camera'` is not
   a template (no `{{ }}`), so the meta would store that literal string as the trigger source.
2. `upzone_package.yaml:331-345` `recent_any_upstairs` emits `{{ true }}` once per matching entity and nothing
   otherwise; with 2+ matches the string is `TrueTrue`, which Jinja `| bool` reads as false (UNVERIFIED
   in HA; the filter accepts only specific truthy strings). The night guard's 21:00 priming likely never worked.
3. `upzone_package.yaml:396-421` windows pause comment and notification promise >=5 min open / >=2 min closed;
   there is no `for:` anywhere, so the HVAC turns off on the first open edge.
4. `upzone_package.yaml:423-424,316-317` sets the preset on every trigger and every 10 min, which also overwrites a
   running pre-cool target (the pre-cool lasts at most to the next trigger). Also, the pre-cool `precool_done`
   test compares indoor temp to the preset +1 F, but the pre-cool target is preset -1 F, so a zone already
   within the band ends immediately.
5. `upzone_package.yaml:168-172` the quiet-common decay watches only the camera group; no mmWave. A sleeping person
   under a camera-quiet hour is declared `confirmed_away`: the exact night-still-sleeper failure in HVAC SoP 9.3.
6. `automations.yaml:2042-2048` the "still energy" guard reads a non-existent entity (always passes).
7. `automations.yaml:2201` the alias says "Zone 2" while the helpers and the camera group say "zone3": see 3.3.
8. `input_text` 255-char cap on a JSON blob that stores two timestamps and a nested object.

## 8. Plan completion / accounting

- Asked: review the scoped pieces, classify ideas, list consumers, verdict on counters. Done.
- Not done: no live `ha_get_state` read (HA states are from `core.restore_state`); no execution of the
  legacy templates (defects in section 7 are by inspection); the pre-arrival pre-cool outdoor-temperature
  measurement for WC-1 and the recovery-peak probe for WC-2 are proposals, not run (Measure-Before-Build
  says run them first); no card was minted on the board (this brief was read-only; the operator or parent
  agent decides).
- Kanban: grep of `docs/planning/kanban.data.yaml` for `upzone` / `zone1_cooling` found no existing card; cards for WC-1 / WC-2 do not exist and are proposals only.
