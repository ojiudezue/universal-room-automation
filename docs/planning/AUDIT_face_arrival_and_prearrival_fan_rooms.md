# AUDIT: camera_face arrival source (0 firings) + pre-arrival fan room eligibility

Read-only probe, 2026-11-12 ~17:00-17:40 CST. Develop working tree (HEAD 6b324966). HA runs v5.108.x (restart 2026-11-12 15:51 CST per entity last_changed). Read first: PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md (complete), IDENTITY_FUSION_CAMERAS_MANUAL.md (lines 1-400 read; remainder not read), HVAC_ARCHITECTURE_STATE_OF_PLAY.md (fan / pre-arrival sections: header, 4.2b, vacancy sweep, pre-arrival lifetime; not all 740 lines), AUDIT_pre_arrival_inventory_and_precool_standdown.md (complete). Paths under `custom_components/universal_room_automation/`. Times CST (CDT ended 11-01).

## Answer first

**Q1 verdict: NEVER-WORKED in this install, not a regression.** `camera_face` cannot fire because **no camera is registered on any zone tracker**. The live zone sensors all read `cameras: {}` and `signal_tiers.camera_sensors: false`, and the recorder (11-05 to 11-12, 18,598 attribute rows) never shows a non-empty `cameras` dict or `camera_sensors: true`. Zero `camera_face` pre_arrival rows exist in any activity-log copy I could read: ~90 days of coverage (05-21..06-20, 09-09..11-12), against 337 geofence+ble rows in the current DB window alone. Even if registration worked, three further conditions would still make it nearly dead (below).

**Q2: only 3 rooms are eligible for pre-arrival fans today: Living Room and Study A (zone_1), Game Room (zone_2).** zone_3 has none, and also has no `zone_persons`, so a pre-arrival never reaches it.

## Q1: what must be true for `camera_face` to fire

Chain (PRODUCER): `presence._discover_zone_cameras` (`domain_coordinators/presence.py:5060`, called once at setup `:3125`) -> `tracker.register_camera(person_sensor)` (`:5123`) -> `async_track_state_change_event` on those sensors (`:5148`) -> `_handle_camera_change` (`:5444`) -> `_get_face_for_camera` (`:5487`) -> `_handle_face_arrival` (`:5581`) -> `SIGNAL_PERSON_ARRIVING(source=camera_face)` (`:5632`). CONSUMERS: HVAC `_handle_person_arriving`, Security lock-regime P2 (corroboration-gated), Music (no-op). See the sibling audit.

All must hold:
1. **The camera's person sensor is registered on a zone tracker.** Registration requires `CameraInfo.area_id` to equal a room's `CONF_AREA_ID` and that room to sit in a ZM zone and not opt out (`:5094-5123`). **FAILS here (root cause, see below).**
2. `detected` = the person sensor just went `on` (handler runs on every state event for it, acts only on `on`, `:5475`). The face is read **at that instant**, not later.
3. `face_recognition_enabled` (CM option) True. Live: `face_recognition_enabled: true` (core.config_entries). OK.
4. Census `_face_suppressed_now()` False (`:5508-5511`). Live: `face_producer_health: live`. OK.
5. Person-sensor name must end `_person_occupancy` / `_person_detected` / `_occupancy` (`:5517`). **17 of 29 cameras end `_person_occupancy_2` and take the device-join branch, which returns None because `FACE_SOURCE_PRESENCE_ARRIVAL_DISAMBIGUATED = False`** (`const.py:3511`, `presence.py:5535`). Live-registry `_2` person sensors include doorbell_lite, garage_a, front_door_aerial, madrone_g6_entry, front_side_ptz, g5_bullet, playroom, upstairs_hall. Bare (non-`_2`) person sensors that pass: family_room, master_hallway, foyer_fisheye, stairs_top, staircase, garage_b.
6. Face sensor (`sensor.<base>_last_recognized_face[_2]`, resolved by `census._resolve_face_entity_id`) state is a real name and `last_changed` within 30 s (`:5567-5574`). Frigate resets these sensors to `Unknown` between recognitions (live 17:00: nearly all `Unknown`), so the window is short.
7. `_find_person_entity_from_face` maps the name to `person.<name>` or an alias (`:5644+`). Frigate names Oji / Jaya / Ezinne / Ziri; the person entity is `person.oji_udezue`, so Oji needs a `face_name_aliases` entry (live alias list: not present in `integration` options, which I filtered by key substring `face`; `face_name_aliases` did not appear, so **UNVERIFIED-absent: treat Oji as unmapped**). Jaya, Ezinne, Ziri map directly.
8. 60 s debounce per person+zone (`:5598`); Presence observation mode off (`:5625`; live off).
9. **There is NO was-away gate.** The person need not be away or `not_home` (`presence.py:5581-5640`; STATE_OF_PLAY §1 table confirms). "Away" is not a condition; the lock regime applies it downstream.

### Root cause: no zone tracker has a camera (checks)

- Live `sensor.zone_*_presence_status` (5 zones: Back Hallway, Entertainment, Master Suite, Outside, Upstairs): all `cameras: {}`, `signal_tiers.camera_sensors: false`, `face_arrivals_today: 0`, `last_face_recognized: ""` (HA REST, 17:2x CST).
- Recorder: 18,598 `state_attributes` rows containing `signal_tiers` (11-05 04:12 to now): 0 with `camera_sensors:true`, 0 with a non-empty `cameras` dict.
- Mechanism (code + registry, not log-verified; HA journald is unreadable from `ssh ha` and `/api/error_log` 404s): `camera_census.resolve_camera_entity` builds `CameraInfo.area_id = bs_entity.area_id or camera_entry.area_id` (`camera_census.py:661`), the ENTITY registry area only; the configured-camera path (`async_discover` -> `_discover_from_configured_cameras` `:1068-1111`) and the legacy full scan (`:1144`, `:1172`) do the same. Live registry: of 655 camera-platform entities (frigate / unifiprotect / reolink / amcrest / dahua), **0 have an entity-level `area_id`; every area lives on the DEVICE** (e.g. `binary_sensor.family_room_person_occupancy` device_area living_room, entity_area None). So `CameraInfo.area_id` is None for all, they land under `_cameras_by_area[""]`, and `get_cameras_for_area(<room area>)` returns `[]` for every room. Corroboration: live census `area_contributions: {}` and `area_raw_max_pre_cancel: {}` (census skips area-less cameras, `camera_census.py:2884`). The device-fallback helper `resolve_area_id_for_entity` is used only in the legacy cross-platform path (`:899`), not here.
- Falsifier I could not run: the setup INFO line `Subscribed to N zone camera entities` (`presence.py:5157`). If it appears with N>0 in the boot log, my mechanism is wrong. The live `cameras: {}` observation does not depend on the mechanism.

### Even if registered, why it would still barely fire (measured)

1. **Exterior/entry cameras are mostly outside any zone.** Entry/exterior person sensors map to areas `front_porch`, `outside_perimeter`, `garage_a`, `garage_b`, `pool`; no ZM zone contains those rooms (Garage A/B appear in no zone `rooms` list; only `Patio` is in the Outside zone). Interior cameras (family_room, master_hallway, foyer_fisheye, stairs_top, staircase, upstairs_hall, playroom) would register.
2. **Edge race.** The face is read only when the person sensor turns on. Recorder 11-05..11-12, person ON edges with a resident name already fresh (<=30 s old) at the edge vs followed by a resident name within 60 s: doorbell_lite 8 vs 31 (of 116 edges), garage_a 9 vs 23 (74), madrone_g6_entry 4 vs 11 (48), front_door_aerial 1 vs 6 (23), family_room 22 vs 89 (578), master_hallway 29 vs 127 (448). The name usually arrives after the edge, so the handler sees nothing; nothing re-reads on the face change (Protect names back-fill ~1-2 min, memory `reference_protect_face_latency_async`).
3. Interior hits would count interior faces as "arrivals" (STATE_OF_PLAY §1: "fires for a recognised face on ANY zone camera, interior included").

### Resident face recognitions, 11-05 04:12 to 11-12 17:00 CST (recorder only; 14-day figure not obtainable)

The recorder holds 7.5 days; the earlier 6.5 days are unknown. Counts are `sensor.<cam>_last_recognized_face*` state changes to a resident name (same face re-posted on several cameras counts per camera). "Not home" = the matching `person.*` state at or before the change was not `home` (Oji = `person.oji_udezue`; Ziri's person history starts later, 2 rows read `?`).

| Camera set | Resident face events | Person not home at the time |
|---|---|---|
| Exterior/entry (doorbell_lite, front_door_aerial, madrone_g6_entry, garage_a/b, front_side_ptz, g5_bullet, hot_tub, pool_equipment, rear_ptz, utilities_ptz) | 121 (Jaya 76, Oji 41, Ziri 2, Ezinne 2) | 51 (Jaya 39, Oji 10, Ziri 2) |
| Interior (family_room, master_hallway, foyer_fisheye, staircase, stairs_top, playroom, upstairs_hall) | 609 (Jaya 351, Oji 206, Ezinne 46, Ziri 6) | 292 (Jaya 220, Oji 58, Ezinne 13, Ziri 1) |

Reading: opportunities existed (51 exterior events while the person read away: arrivals/departures at the door, plus phone-state lag; e.g. Jaya at doorbell_lite 11-11 11:33, 6 min after `not_home` began), but the source structurally cannot see them. Many "not home" interior rows are not arrivals (the person entity lagging, or a mislabelled face; 10-24 Jaya-labelled-as-Oji precedent, STATE_OF_PLAY §1). Whether each was a true arrival is not established here.

### When did it ever fire? Did a release/rename break it?

- `ura_activity_log`, `pre_arrival` rows by `source`: current DB (10-13..11-12) ble 117 / geofence 220 / camera_face 0; `ura_pre_backfill_2026-10-09.db` (09-09..10-09) ble 108 / geofence 115 / 0; `universal_room_automation.db.prevacuum.bak` (05-21..06-20) ble 92 / geofence 116 / 0. Gaps (06-20..09-09, and before 05-21) are unread, so "never in all of history" is UNVERIFIED; absent in every window I could read.
- Git: handler added in v3.19.0 (`00530801`, 2026-03-27). Registration depends on entity-level area, unchanged in `camera_census.py` since v3.4.4 (`be023166`). The Frigate-1 retirement (2026-08-13) and `_2` rename are NOT the cause: registration fails before any face read, and `0` rows exist in the 05-21..06-20 window, before the retirement. The later FACE-SOURCE flag (`const.py:3511`) only removed `_2` cameras, which were already unregistered.
- No release changed this; I did not find a commit that turned a working path off.

### Verdict and what would disprove it

NEVER-WORKED (structural, area lookup uses entity-level area while this install's areas are device-level). To disprove: show one `camera_face` row or INFO `Camera face arrival:` log line, or a non-empty zone `cameras` dict at any time. I found none in the recorder or in 3 activity-log copies.

Not recommended / not decomposed here: a fix (device-area fallback in `CameraInfo`) would also change census area math (`area_contributions` would suddenly populate, ripple into census BLE cancel). Marginal-benefit decomposition not done; the source feeds the lock-regime release (corroboration-gated) and HVAC pre-cool, and geofence+ble already supply 337 of 337 live triggers.

## Q2: HVAC zone rooms and pre-arrival fan eligibility

Rule (code): `hvac_predict._activate_zone_fans` (`domain_coordinators/hvac_predict.py:1441-1643`) per room in `zone.rooms`: skip if `room_automation_paused` (automation switch off, manual mode on, or either switch unavailable/unknown; `const.room_automation_paused`), skip if no fans, skip if Fan Mode is not Follow thermostat (`hvac_tier_owns_room_fans`), skip `no_data` / `below_setpoint` (room temp < zone cool setpoint), skip on FanPolicyOracle manual-OFF cooldown. Pre-arrival is also skipped in house state `sleep` (`:703`). A zone only gets a pre-arrival if a person in `zone_persons` triggers it.

Live source: config entries `core.config_entries` (room options `fans`, `room_fan_mode`), `sensor.ura_hvac_coordinator_zone_N_status` room lists, and live `select.<room>_..._fan_mode` / `switch.<room>_automation` / `switch.<room>_manual_mode` states (HA REST 17:2x CST). Stored `room_fan_mode` equals live select state in every fan room. Zone persons: zone_1 ezinne, oji_udezue; zone_2 ziri, jaya; zone_3 none.

Rooms with a fan (all other rooms in each zone have none and are never eligible; 14 / 14 / 16 rooms in zone_1 / 2 / 3, 44 total):

| Zone | Room | Fans | Fan Mode (live) | Automation switch | Manual Mode | Paused? | Eligible for pre-arrival fans |
|---|---|---|---|---|---|---|---|
| zone_1 | Living Room | 1 | Follow thermostat | on | off | no | **YES** |
| zone_1 | Study A | 1 | Follow thermostat | on | off | no | **YES** |
| zone_1 | Master Bedroom | 2 | Follow thermostat | **off** | off | **yes** | no (`room_paused`) |
| zone_2 | Game Room | 1 | Follow thermostat | on | off | no | **YES** |
| zone_2 | Jaya Bedroom | 1 | Room temperature | off | off | yes | no (paused; also not Follow) |
| zone_2 | Guest Bedroom 2 | 1 | Off | off | off | yes | no |
| zone_2 | Ziri Bedroom (Bedroom 5) | 1 | Off | off | off | yes | no |
| zone_2 | Media | 1 | Off | off | entity disabled | yes | no |
| zone_2 | Exercise Room | 1 | Off | off | entity disabled | yes | no |
| zone_3 | Kitchen | 1 | Follow thermostat | **off** | off | **yes** | no (and zone_3 has no persons) |
| zone_3 | Guest Bedroom 1 | 1 | Room temperature | off | off | yes | no |
| zone_3 | Breakfast Nook | 1 | Off | on | off | no | no (Fan Mode Off) |

Notes. Master Bedroom and Kitchen are the two Follow-thermostat rooms excluded only by the Automation switch being off. Media and Exercise Room Manual Mode entities are `disabled_by: integration` (no state); treated as not manual; their Automation switches are off anyway. Eligible-yes also needs room temp >= zone cool setpoint and no manual-OFF cooldown at trigger time (not evaluable now). Paused fan-less rooms (e.g. Ziri Bathroom) still show `room_paused` in `fan_rooms_skipped` because the pause test precedes the fan test (live `hvac_pre_arrival_status`).

### Pre-arrival fan turn-ons

The activity log has no `fan_on` action (only `fan_off` 13, `fan_recheck_*`), so turn-ons come from the recorder: an off->on edge of the room's fan within 120 s after a `pre_arrival` row naming the room's zone. **Coverage 11-05 04:12 to 11-12 only (7.5 days), not 14.** Cross-checked against distinct `fan_rooms_activated` values in `sensor.ura_hvac_coordinator_hvac_pre_arrival_status` history (Study A 13, Living Room 5, Game Room 9 changes, a looser count). Counts below are the edge method:

| Room | Fan entity | Pre-arrival-attributed turn-ons (11-05..11-12) | All off->on edges in window |
|---|---|---|---|
| Study A | `fan.polyfan_dreo704s_wifi_studya` | 10 | 39 |
| Game Room | `fan.game_room_ceiling_fan_2` | 5 | 7 |
| Living Room | `fan.towerfan_dreopilotmaxs_wifi_livingroom` | 4 | 9 |
| Master Bedroom | `fan.polyfan_508s_wifi_masterbedroom` | 0 | 3 |
| Kitchen | `fan.151732606487193_fan` | 0 | 0 |

All other fan rooms: 0 possible (paused / Fan Mode Off); Jaya Bedroom, Guest Bedroom 1/2, Ziri Bedroom, Media, Exercise Room fans not queried (no path). Attribution is by timing, not by the URA context id; a within-120 s coincidence with a user turn-on is possible (Study A shows 39 edges, 10 attributed). Days 10-29..11-04 are unknown (recorder starts 11-05).

## Producer / consumer notes

- `fan_rooms_activated` / `fan_rooms_skipped`: produced in `_activate_zone_fans` (`hvac_predict.py:1441`), read by `sensor.ura_hvac_coordinator_hvac_pre_arrival_status` (display only).
- Face-arrival counters `face_arrivals_today` / `camera_face_arrivals_today`: produced only in `_handle_face_arrival`; display only. The 0 reading is consistent with, not independent evidence of, the registration failure (it would also read 0 if registration worked but nothing recognised).

## Files

Code: `domain_coordinators/presence.py` (:3125, :5060-5200, :5444-5480, :5487-5578, :5581-5669), `domain_coordinators/hvac_predict.py` (:1441-1645), `camera_census.py` (:561-777, :1044-1209, :2884), `const.py` (:3505-3513). Live data: HA REST states, `core.config_entries` / `core.entity_registry` / `core.device_registry` (read-only), `home-assistant_v2.db`, `universal_room_automation.db` plus the two older copies via read-only sqlite. Scratch scripts in the session scratchpad (not saved to the repo).
