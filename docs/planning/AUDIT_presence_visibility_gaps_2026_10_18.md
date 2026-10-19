# AUDIT: Presence / house-state visibility gaps on the URA v8 dashboard

**Date:** 2026-10-18 (probe run 11:11-11:25 CDT). **Type:** read-only audit, no version, no dashboard edits.
**Scope note (coordinator, same day):** the operator says "there is a presence tab". In v8 that is the **People** view (path `people`); it is audited as the primary surface throughout. Older dashboards (ura_v4/v5/v6/ura_tabbed) have a view titled "Presence"; section 6 passes over ura_v6's.
**Operator ask:** "Check what we have on the presence tab and find where we can plug gaps."
**Read first (completely):** `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (555 lines). Prior art read: `docs/planning/AUDIT_presence_coordinator_observability.md` (2026-08-05, entity-surface audit; this doc is the dashboard-side counterpart).

## 0. Method and caveats

- **ha-mcp tools were not available to this agent** (no ToolSearch / ha-mcp in the toolset). Substitutes, all read-only:
  - Dashboard config: `~/ha-config/.storage/lovelace.ura_v8` (the Samba-mounted storage file that `ha_config_get_dashboard` serves). Views: quick-actions, now, rooms, energy, people, security, climate, health, music. Confirmed: no `presence` view.
  - Live values: last row per entity in the HA recorder (`ssh ha sqlite3 -readonly /config/home-assistant_v2.db`, states + state_attributes), read 2026-10-18 11:11-11:12 CDT. This is the last recorded state, not an `ha_get_state` call; values below carry the recorder timestamp.
  - Transition history: URA DB `house_state_log` (`ssh ha sqlite3 -readonly /config/universal_room_automation/data/universal_room_automation.db`). Its `timestamp` column is UTC-naive (home_day row 11:01:22 equals the sensor attribute `state_since` 11:01:22+00:00 = 06:01 CDT). Day buckets below are shifted to CDT.
- "On a card" means the entity id or attribute name appears in the `lovelace.ura_v8` JSON (grep count 0 = absent from every view).

## 1. What the v8 dashboard shows today

Presence content is split between **Now** and **People** (plus fragments elsewhere). The People view is the closest thing to a presence tab.

| View | Card (type) | Reads | Shows |
|---|---|---|---|
| Now | markdown welcome | `sensor.ura_presence_coordinator_presence_house_state` (state) | "House is Home Day" |
| Now | button-card `badge_state` | `sensor.universal_room_automation_persons_in_house`, `..._rooms_occupied` | counts |
| Now | tile | `sensor.ura_presence_coordinator_next_state` (state only) | "Next House State" (live: `away`, attrs confidence 0.909, eta 28 min, model `house_state_log_freq_v1`; only the state is shown) |
| Now | button-card `hero` "House State" | presence_house_state; attrs `census_count`, `confidence` | state + "N present, X% conf" |
| Now | auto-entities + markdown | `binary_sensor.*_occupied` (filtered), `*_occupancy_timeout_remaining` | occupied rooms, vacancy countdown |
| People | heading + markdown "House Census" | `total_persons_on_property` attrs inside/outside/identified_total/unidentified_total; `census_confidence`; `occupant_count.persons_locations`; per-person `_likely_next_room`, `_current_path.recent_path`; `house_next_room_accuracy.per_person_accuracy` | inside / perimeter / on property, identified/unidentified, confidence, per-person room, next room, 4-step trail, accuracy |
| People | hero button-card x2 | `persons_in_house` (+ `unidentified_persons_in_house`), `occupant_count` (+ `rooms_occupied`) | totals |
| People | heading "Where is Everyone" + badges | `binary_sensor.ura_presence_coordinator_guest_mode` (visible only when on), `..._house_sleeping` | badges |
| People | button-card x4 | `sensor.universal_room_automation_<person>_location` (state only) | room or Away per person |
| People | auto-entities | `binary_sensor.*_phone_left_behind` (on only) | "Phone left home" list |
| People | markdown | `last_person_entry`/`last_person_exit` (+ `person_id`), `persons_entered_today`/`exited_today` | last in/out, today's counts |
| People | tile x4 "Trackers" | `person.oji_udezue/ezinne/jaya/ziri` | HA person state (home/not_home) |
| People | markdown "Zone Occupancy" | `presence_house_state` attr `zones` (`mode`, `fan_on_rooms`) | per-zone mode |
| People | tile x4 "Presence Signals" | `census_confidence`, `signal_consensus_confidence`, `person_tracking_status`, `census_mismatch`, `unexpected_person_detected`, `select.ura_presence_coordinator_house_state_override` | gauges + override select |
| Rooms | many | per-room occupied/motion, `zone_*_guest_count`, `zone_*_identified_persons`, `zone_*_person_tracking_status`, room `*_identified_people` | per-room / zone detail |
| Security | tile / markdown / picture-entity | `last_perimeter_alert`, `persons_on_property_exterior`, `ura_security_coordinator_outside_*`, ~25 camera pictures | perimeter, outside headcount, live camera frames |
| Health | conditional markdown | `sensor.ura_coordinator_manager_stuck_signal_watchdog` (+ attrs stuck_cameras/stuck_sensors) | appears only when count > 0 |
| Climate | tile | `switch.ura_hvac_coordinator_guest_mode_actuation` | HVAC guest-preset toggle (not detection) |

Absent from every card (grep count 0): `veto_path`, `lost_away_grace_remaining_s`, `excluded_persons`, `last_veto_decision`, `signal_consensus_inputs`, `state_since`, `dwell_seconds`, `previous_state`, `tracker_sources`, `face_producer_health`, `degraded_mode`, `active_platforms`, `camera_input_dark`, `egress_identity_*`, `ble_*` counters, `bermuda_global_*`, `house_state_confidence`, `presence_anomaly`, `presence_diagnostics`, `people_home_census`, `binary_sensor.ura_presence_coordinator_house_occupied`, `sensor.ura_coordinator_manager_house_state`.

## 2. What the coordinator exposes (live, recorder 2026-10-18 ~11:11 CDT)

| Entity | State | Attributes that exist | On a card? |
|---|---|---|---|
| `sensor.ura_presence_coordinator_presence_house_state` | `home_day` (since 11:01:22Z, dwell 18621 s) | inferred_state, previous_state=`waking`, state_since, dwell_seconds, is_overridden, override, confidence 0.85, census_count 1, face_recognized_count 1, path_alpha_gate_source, tracked_persons_count 4 / _trusted 4, excluded_persons {}, all_tracked_persons_away false, **veto_path `none`**, **lost_away_grace_remaining_s null**, outdoor_zones, signal_consensus 1.0 + band + inputs, consensus_low_since, last_veto_decision, wake_blocked_ticks, arriving_rearm_*, wake_backstop_fires, boot_settle_*, zones, fan_interference_active | state, `census_count`, `confidence`, `zones` only |
| `sensor.ura_coordinator_manager_house_state` / `sensor.universal_room_automation_house_state` | `home_day` | same subset: inferred_state, previous_state, state_since, dwell_seconds, is_overridden, override | no |
| `binary_sensor.ura_presence_coordinator_house_occupied` | on (since 2026-10-17 23:13:57 CDT) | device_class occupancy | no |
| `binary_sensor.ura_presence_coordinator_guest_mode` | off | none | badge, visible only when on |
| `sensor.ura_presence_coordinator_house_state_confidence` | 0.85 | none | no |
| `sensor.ura_presence_coordinator_signal_consensus_confidence` | 1.0 | consensus_band high, signal_consensus_inputs (all_tracked_persons_away, any_zone_occupied, any_stale_or_lost_tracker, camera_occupied_count 0, tier1_occupied_count 1, mmwave_occupied_count 1, tier1_provenance_breakdown), consensus_low_since | state only |
| `sensor.ura_presence_coordinator_presence_diagnostics` | `house_inference` | last_veto_decision (fired/confidence/reason/scope), signal_consensus_inputs, excluded_persons, zone_verdicts, checkpoint_cameras_by_area, protect_sourced_count 9 | no |
| `sensor.ura_presence_coordinator_presence_anomaly` | nominal | active_anomalies 0, suppressed_active_anomalies 41, anomalies_today 14, metrics, coverage full | no |
| `sensor.ura_presence_coordinator_next_state` | `away` (conf 0.909) | eta 28 min, model | state only |
| `sensor.ura_presence_coordinator_people_home_census` | 1 | none | no |
| `sensor.ura_presence_coordinator_arrival_re_alerts_muted_flap_guard` / `_skipped_real_arrivals` / `wake_safety_valve_fires` / `mornings_blocked_from_waking` | 0 / 0 / 0 / 0 | none | no |
| `switch.ura_presence_coordinator_away_confirmation_veto`, `guest_detection`, `arrival_re_alerts`, `fan_recheck`, `presence_observation_mode` | on / on / on / on / off | none | none of these switches are on a card |
| `sensor.universal_room_automation_persons_in_house` | 1 | identified_count, identified_guests_count 0, unidentified_count 0, face_producer_health `live`, frigate_count 1, unifi_count 0, degraded_mode false, camera_input_dark_fired false, active_platforms [frigate, unifiprotect], ble_by_area {kitchen:1}, ble_cancelled_count, peak_held, wifi_guest_floor, camera_unrecognized, stuck_cameras [], unresolved_configured_cameras_count 0, egress_identity_* (attach/ambiguity/abstain 24h = 0.0, last_attach, agreement_class_last `disagree`), ble_legs_* / ble_exit_* counters | state + `unidentified_count` label only |
| `sensor.universal_room_automation_census_confidence` | medium | house_confidence, house_source_agreement `close`, exterior_confidence | state only |
| `binary_sensor.universal_room_automation_census_mismatch` | off | camera_count 1, ble_count 1, mismatch_since null, threshold 2, duration_minutes 10 | state only |
| `sensor.universal_room_automation_<person>_location` | Kitchen (Jaya), Away (others) | **tracking_status, tracking_reason, tracker_sources {gps, wifi, ble}**, last_bermuda_update, recent_path, confidence, confidence_level, room_id, last_update_ago | state only |
| `sensor.universal_room_automation_person_tracking_status` | `1/4 home` | per-person `persons{location, confidence, method, bermuda_area}`, scanner_mappings_count 43, area_mappings_count 95, update_interval_seconds | state only |
| `sensor.universal_room_automation_identified_persons_in_house` | 1 | person_list, ble_confirmed [Jaya], face_confirmed [jaya] | no |
| `sensor.universal_room_automation_last_person_entry` | 2026-10-18T04:13:36Z | person_id jaya, egress_camera `doorbell_lite_person_occupancy_2` | state + person_id |
| `person.jaya` | home | source `device_tracker.iphone_jaya_bermuda_tracker` | tile |
| `person.oji_udezue` | not_home (since 07:53:38) | source `device_tracker.phalanxiphone15promaxcflare`, lat/long, gps_accuracy | tile |
| `device_tracker.*_bermuda_tracker` (x4) | Jaya home (11:11:37), others not_home | scanner `Mmwave_Lux_Wifi_EspHome_Kitchen`, area Kitchen, source_type bluetooth_le | no |
| `sensor.bermuda_global_*` | 55 proxies active of 55, 218 of 258 devices visible | n/a (upstream Bermuda) | no |
| `binary_sensor.ura_coordinator_manager_camera_input_dark` | off | none | no |
| `sensor.ura_coordinator_manager_stuck_signal_watchdog` | 0 | stuck_cameras, stuck_sensors, last_fired, fires_today | conditional card (Health) |
| `house_state_log` (URA DB table, not an entity) | n/a | id, timestamp, state, confidence, trigger, previous_state | nothing |

Producer notes (from state-of-play doc): `veto_path` is set by the inference engine (`presence.py:1177-1277`) and mirrored at `presence.py:6518`, exposed at `sensor.py:5661`; values `alpha_starved` / `alpha_denies` / `beta_only` / `none`. `tracker_sources` and `tracking_reason` come from `person_coordinator.py` (matrix rows incl. `away_gps_only`, `away_ble_silent_only`; fleet liveness window `BLE_FLEET_LIVENESS_WINDOW_S = 90`, `person_coordinator.py:67`). Consumers of all of these today: code only, no dashboard card.

## 3. Operator questions vs. coverage

| # | Question | Answered today? | Where | Data exists as entity/attribute? |
|---|---|---|---|---|
| 1 | Why is the house Away/Home now, which branch decided? | **Not at all** (state word only) | Now hero shows state + count + confidence | **Yes**, dashboard-only: `veto_path`, `last_veto_decision`, `all_tracked_persons_away`, `excluded_persons`, `lost_away_grace_remaining_s`, `signal_consensus_inputs`, `previous_state`, `state_since`/`dwell_seconds`. Caveat: `veto_path` is a veto-limb label (what blocked AWAY), and the DB log `trigger` column (`census_update` / `deferred_retry` / `periodic`) says what drove the last transition; neither names "branch alpha vs beta" for a transition INTO away. A true "AWAY decided by branch X" field needs new code (small). |
| 2 | Who is home, where, from which source (GPS / BLE / Bermuda / camera)? | **Partially** | People: per-person room + trail + next room; identified/unidentified split | Source: **yes**, dashboard-only: `<person>_location.tracking_reason`, `tracker_sources {gps,wifi,ble}`, `tracking_status`, `persons_in_house.ble_by_area`, `identified_persons_in_house.ble_confirmed` vs `face_confirmed`. Not shown anywhere. |
| 3 | When did each tracker last change, and does it disagree with BLE? | **Not at all** (tile shows home/not_home only) | Trackers tiles | Last-change: yes, `states.person.x.last_changed` is reachable from a markdown template (dashboard-only). Disagreement: yes, derivable from `tracker_sources` (gps `away` vs ble `visible`) and `device_tracker.*_bermuda_tracker` vs `person.*` state; `last_bermuda_update` attr gives BLE staleness. A single explicit "tracker disagrees with BLE" flag does not exist (new code, optional). |
| 4 | How many Away flips today? | **Not at all** | none | Not an entity. Data is in `house_state_log`; `sensor.ura_presence_coordinator_presence_anomaly.anomalies_today` (14) is anomaly count, not flips. Needs new code: a `house_state_changes_today` / `away_entries_today` counter sensor (precedent: `persons_entered_today`). Measured from the DB: CDT days 10-12..10-17 had 5 / 4 / 33 / 11 / 42 / 10 AWAY entries; 0 so far on 10-18. |
| 5 | Is a guest detected, and why? | **Partially** | guest_mode badge (only when on), Rooms `zone_*_guest_count` | "Detected": yes. "Why": partially in attributes: `persons_in_house` `unidentified_count`, `identified_guests_count`, `camera_unrecognized`, `wifi_guest_floor`, `census_mismatch` attrs, `last_person_entry.person_id`. The guest-gate reason (threshold / persistence / Path B room state) is not a published attribute (the 2026-08-05 audit lists guest gate as attr-only internals); a `guest_reason` attribute would need new code. Guest-state entries in `house_state_log`: 1,2,1,0,0,1,1 per UTC day 10-11..10-17. |
| 6 | Are the camera fleet and BLE scanners healthy? | **Partially** | Health conditional (stuck cameras), Security shows camera pictures | Cameras: yes, dashboard-only: `persons_in_house` `face_producer_health`, `degraded_mode`, `active_platforms`, `frigate_count`/`unifi_count`, `unresolved_configured_cameras_count`, `stuck_cameras`; `binary_sensor.ura_coordinator_manager_camera_input_dark`. BLE: partial: `sensor.bermuda_global_active_proxy_count` / `total_proxy_count` (upstream), `scanner_mappings_count`, `last_bermuda_update`. No per-scanner liveness entity found in this probe (unknown whether one exists; not searched in code). |

## 4. Recommendation

**Build a "Presence" section as a new Presence view (or a second section block on People).** Reason: People already carries ~7 cards and a wide section; the new content is diagnostic ("why", "from where", "healthy?") rather than status, and mirrors the Energy tab splitting Storm Readiness out of the main flow. Marginal-benefit note: the dashboard-only set below answers questions 1, 2, 3 and 6 with zero code and zero deploy risk; do these first, then decide on code items from what the dashboard shows.

Style reference (Energy > Storm Readiness section): `grid` section `column_span 2` with a `heading` card (`heading_style: title`, mdi icon), one `custom:button-card` `template: hero` with `entity`, `custom_fields.pv` for the headline word, a computed `label` string joining parts with " · ", state-dependent colour (blue normal, red abnormal), `grid_options.columns: full`; then one `markdown` card with `entity_id` list and a two-column `| | |` table of bold-label rows built from `state_attr` lookups with `or {}` guards and plain-English mappings.

### 4a. Dashboard-only (no code, ship first)

1. **"Why this state" hero + table.** Hero on `sensor.ura_presence_coordinator_presence_house_state`: pv = state; label = `previous_state -> state · for Xh Ym (dwell_seconds) · veto_path`. Markdown table rows: Decided by (`veto_path` mapped: alpha_starved / alpha_denies / beta_only / none), Trackers away (`all_tracked_persons_away`, `tracked_persons_count_trusted`), Excluded (`excluded_persons`), Grace remaining (`lost_away_grace_remaining_s`), Last veto (`last_veto_decision.reason/confidence`), Signal consensus (`signal_consensus`, `band`, and `signal_consensus_inputs`: camera_occupied_count, tier1_occupied_count, mmwave_occupied_count, any_stale_or_lost_tracker), Census (`census_count`, `face_recognized_count`, `path_alpha_gate_source`), Boot settle / wake blocks (`wake_blocked_ticks`, `boot_settle_done`).
2. **"Who, where, from what" table** (replaces nothing; sits beside the existing location buttons). Per person row from `<person>_location`: room, `tracking_status`, `tracking_reason`, `tracker_sources` (gps / wifi / ble), `last_bermuda_update` age, confidence. Add `identified_persons_in_house` `ble_confirmed` vs `face_confirmed` line and `persons_in_house.ble_by_area`.
3. **Tracker freshness and disagreement table.** Per person: `person.x` state + `as_relative(last_changed)`, source device_tracker, Bermuda tracker state, and a computed flag when GPS says away while BLE is `visible` (or the reverse). All template-only.
4. **Fleet health row.** Hero or markdown: camera side (`face_producer_health`, `degraded_mode`, `active_platforms`, `unresolved_configured_cameras_count`, `stuck_cameras`, `camera_input_dark`), BLE side (`bermuda_global_active_proxy_count` of `total_proxy_count`, visible devices, `scanner_mappings_count`), plus the stuck-signal watchdog fires today (`fires_today`).
5. **Guest "why" markdown.** `guest_mode` state, `identified_guests_count`, `unidentified_count`, `camera_unrecognized`, `wifi_guest_floor`, `guest_detection` switch state, Rooms guest counts. Shows the evidence even though the gate's own reason is not published.
6. **Small surfacing fixes:** show `next_state` attributes (eta, confidence) on the Now tile; add `binary_sensor.ura_presence_coordinator_house_occupied` and the presence-coordinator switches (`away_confirmation_veto`, `guest_detection`, `arrival_re_alerts`, `presence_observation_mode`) to the section so kill-switch state is visible; show recent `house_state_log` via no new code only if an SQL-capable card is already available (not verified; skip otherwise).

### 4b. Needs new code (small, card each after the dashboard items land)

| Item | What | Why dashboard-only cannot do it | Size |
|---|---|---|---|
| Away/state flips today | `sensor.ura_presence_coordinator_house_state_changes_today` (and `away_entries_today`), RestoreEntity-style daily counter like `persons_entered_today`; attrs last 5 transitions with `trigger` | Recorder history cards cannot count attribute-free state transitions into a single "today" number, and `house_state_log` is not an entity. Today's pattern (5..42 AWAY entries/day over the last week, from `house_state_log`) says this is the single most-wanted counter. | S |
| AWAY decided-by field | attribute `away_decided_by` (path alpha / path beta / boot / override) on the transition INTO away | `veto_path` describes blocking, not the winning branch | S |
| Guest reason | attribute `guest_reason` / `guest_gate_state` on `binary_sensor.ura_presence_coordinator_guest_mode` | gate threshold/persistence/room-state internals are not published | S-M |
| Tracker-vs-BLE disagreement flag | optional binary sensor per person; only if the template flag in 4a.3 proves too noisy | derivable today, so defer | S |
| Per-scanner liveness | only if Bermuda's own entities do not already give it (unknown) | not probed | unknown |

### 4c. Observations noticed while probing (not asked, flagged)

- `sensor.ura_presence_coordinator_next_state` read `away` (0.909, eta 28 min) at 11:11 CDT while Jaya is home, tracked at Kitchen, confidence 0.7. It is a log-frequency model (`house_state_log_freq_v1`), so this may just be a routine-based prediction; not a bug claim.
- `egress_identity_agreement_class_last = "disagree"` on `persons_in_house`, with last attach Jaya single_source: only visible by reading attributes.
- `sensor.universal_room_automation_persons_in_house` = 1 while `total_persons_on_property` = 2 (1 inside + 1 exterior unidentified); the People hero already labels the first as "Persons in House", so the exterior person only shows in the census markdown.

## 5. Falsification checks run

- "No presence view": view paths read from the storage file (9 views, none `presence`). Disproving observation would have been a `presence` path; not found.
- "Attribute X is on no card": grep count 0 in `lovelace.ura_v8` for each name listed in section 1 (`census_mismatch` count 1, `guest_mode` 3, `stuck_signal_watchdog` 3 are the only presence hits among the names tried).
- "Away flips not an entity": searched recorder last-state list for `%away%`, `%presence_coordinator%`, `%house_state%`, `%census%`, `%ura_coordinator_manager%`, `sensor.universal_room_automation_*`; no flips-counter entity. Code grep for `away_flip|flips_today|house_state_transitions|transitions_today|guest_reason|scanner_health|fleet_health|tracker_last_changed` returned no match (the grep command itself errored on the `--include` glob under zsh; the veto_path portion of that command did run). Treat the "no counter exists in code" claim as not fully re-verified; re-run with a corrected command before carding.
- Live values are recorder last-state, not `ha_get_state`, as stated in section 0.

## 6. ura_v6 "Presence" view: cards worth carrying forward into v8

Source: `~/ha-config/.storage/lovelace.ura_v6`, view path `presence` (mushroom cards, one section). Checked by grep whether v8 already references each entity or attribute.

| v6 card | Reads | In v8 already? | Carry forward? |
|---|---|---|---|
| Header mushroom-template | `ura_coordinator_manager_house_state`, `presence_house_state`, `house_state_confidence`, `census_confidence`, `occupant_count`, `unidentified_persons` | state, census_confidence, occupant_count yes; **`house_state_confidence` no** | Yes, fold confidence into the section 4a.1 hero (it is also in `presence_house_state.confidence`, which v8 Now already uses, so low value). |
| Per-person block (person card + current_path + location + likely_next_room + **`previous_location`**) | `<person>_previous_location` | `previous_location` **no** | Yes, add "came from" to the 4a.2 table (live example: Ezinne/Oji previous = Butler Pantry, Ziri = Garage A, as of 2026-10-17 18:01 CDT). Cheap, existing entity. |
| Census Cross-Confirmation | `persons_in_house`, `persons_on_property_exterior`, `total_persons_on_property`, `unidentified_persons_in_house`, outside_people_being_tracked/outside_unidentified | mostly yes (People census markdown, Security) | Already covered. |
| Census freshness tile | **`census_validation_age`** (live 0) plus entered/exited today | age **no**; entered/exited yes | Yes, one line in the 4a.4 fleet-health row (is the census being revalidated). |
| Unexpected Person / Census Mismatch tiles | binary sensors | yes | Already covered. |
| Bayesian Predictions | **`bayesian_data_quality`** (live "99% quality"), `bayesian_prediction_accuracy` (0.0785) | quality **no**; accuracy appears only in Health hero label | Optional; low priority (prediction quality, not presence visibility). |
| Anomaly tile | **`presence_anomaly`** (live nominal; attrs active 0, suppressed 41, today 14) | **no** | Yes, add to 4a.4; v8 Health only lists non-nominal `sensor.ura_*_anomaly`, so a nominal-but-suppressing state (41 suppressed) is invisible. |
| Zone Status markdown | `presence_house_state.zones`: `mode`, **`cameras_active`**, **`last_face_recognized`**, **`signal_tiers`** | v8 shows `mode` + `fan_on_rooms` only; those three attrs **no** | Yes, extend the v8 Zone Occupancy markdown with per-zone camera/face/signal-tier evidence (answers "from which source" per zone). |
| Music Rooms / Transfers | `music_following_active_rooms`, `transfers_today` | **no** (v8 has a Music view) | Not presence; leave to the Music view. |
| Phone Status | auto-entities `*phone_left_behind*` (all states) | v8 lists only `state: on` under "Phone left home" | Optional: showing all phones (including off) confirms the sensors exist and are healthy; low value. |
| Hallways & Transitions / Bathrooms / Closets grids | `binary_sensor.<room>_occupied` for 11 minor rooms | v8 `Occupied Now` auto-entities already lists every occupied room | Skip; redundant with Now. |

Net carry-forward set (all dashboard-only, existing entities): `previous_location`, `census_validation_age`, `presence_anomaly` (with suppressed count), and the zone `cameras_active` / `last_face_recognized` / `signal_tiers` attributes. These slot into 4a.2, 4a.4 and the existing Zone Occupancy card; they do not change the gap table in section 3.
