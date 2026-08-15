# AUDIT: Is ZONE-CAM-PERSON-GUARD-1 needed? (2026-08-15)

Card proposal: add a device_class guard so a Frigate MOTION sensor in
`CONF_ZONE_CAMERAS` cannot be trusted as camera person-confirmation in the
zone occupancy-confidence scorer. Operator challenge: "we already have a
camera motion guard in room code" and "we don't use motion for almost
anything even if configured."

## Verdict: (b) config-only. Card as written is DEAD — a device_class guard would catch nothing.

Live config contains ZERO `device_class: motion` entities in
`CONF_ZONE_CAMERAS`. It DOES contain three Frigate `*_all_occupancy`
sensors (all-tracked-objects, not person-only) — and those carry
`device_class: occupancy`, identical to the legitimate person sensors. The
proposed device_class discriminator cannot separate them. The correct
discriminator is the object label encoded in the entity name (the census
suffix filters already codify this), and the fix is a config swap: each
offender has an enabled person-only sibling.

## 1. Guards that exist today

| Path | Guard | Evidence |
|---|---|---|
| Camera census / resolver (feeds room + zone discovery) | Person-only SUFFIX filter — `_person_occupancy`, `_person_detected`, `_person`, `_smart_motion_human`; explicitly excludes motion/sound/vehicle | `camera_census.py:362-386` ("to avoid including motion, sound, and other non-person binary sensors"); `camera_resolver.py:215-236` (person suffixes + vehicle/animal exclusion lists) |
| Room coordinator camera override | Consumes only census-derived person sensors via `camera_manager.get_person_sensor_for_area` | `coordinator.py:3079-3092` |
| Zone presence tracker (area-discovered cameras) | Subscribes only `camera_info.person_binary_sensor` (census output) | `domain_coordinators/presence.py:3992+` (`_discover_zone_cameras`, uses `person_binary_sensor`) |
| Zone Source-3 confidence scorer | **NO guard** — reads raw `zone.zone_cameras` (operator-configured `CONF_ZONE_CAMERAS`), any `state == "on"` counts as camera confirmation | `domain_coordinators/presence.py:2011-2019` |
| fan_veto | Uses BLE/person_coordinator + census paths; no camera-motion consumption | `fan_veto.py:16,201-229` |
| Config flow selector | Allows `device_class=["occupancy","motion"]` — motion IS selectable at config time | `config_flow.py:8427-8435` |

The operator's remembered "camera motion guard in room code" is real: the
census/resolver person-suffix filter (name/platform-based, NOT
device_class-based), consumed by the room override and the zone
tracker discovery path. The Source-3 scorer is the one consumer that
bypasses it.

## 2. What CONF_ZONE_CAMERAS feeds — blast radius is small

Consumers of `zone_cameras` (exhaustive grep):
- `hvac_zones.py:286` — loads config into `ZoneState.zone_cameras`.
- `hvac.py:3283` (`_build_camera_zone_map`) — diagnostics only.
- `presence.py:2011` — Source-3 of `check_zone_occupancy_confidence`,
  called ONLY from the D6 stale-occupancy failsafe at `hvac.py:1584-1592`:
  a zone continuously occupied > `max_occupancy_hours` gets its timer reset
  if ≥ min(2, possible) of 4 sources confirm. A false camera "on" is one
  vote among motion/BLE/multi-room; worst case it delays the stale-sensor
  force-away, it does not create occupancy.
- NOT superseded by the census cutover: the census feeds the discovery
  paths; the Source-3 scorer still reads the config list directly and is
  live.

## 3. Live config (ro read of `.storage/core.config_entries` + entity_registry, 2026-08-15)

| Zone | Configured | device_class | Person-only? |
|---|---|---|---|
| Back Hallway | `staircase_all_occupancy` | occupancy | **NO — Frigate "all" objects** |
| Back Hallway | `garage_a_camera_person_detected` (URA-derived) | occupancy | yes |
| Entertainment | `family_room_person_occupancy`, `foyer_fisheye_person_occupancy`, `master_hallway_person_occupancy` | occupancy | yes |
| Master Suite | `master_hallway_person_occupancy` | occupancy | yes |
| Upstairs | `upstairs_hall_all_occupancy` | occupancy | **NO** |
| Upstairs | `playroom_all_occupancy_2` | occupancy | **NO** |
| Upstairs | `stairs_top_person_occupancy` | occupancy | yes |

No `device_class: motion` entity present — the 2026-06-08-style motion
creep did NOT recur in device_class terms. What crept in is three `*_all_occupancy`
sensors, invisible to the card's proposed guard. Enabled person-only
siblings exist for all three: `staircase_person_occupancy`,
`upstairs_hall_person_occupancy_2`, `playroom_person_occupancy_2`.

## 4. Operator claim "we don't use motion for almost anything"

- **Camera-motion entities:** TRUE. No URA path consumes camera motion
  sensors — census filters them out, room/zone/fan paths consume census
  output only. Only `CONF_ZONE_CAMERAS` could admit one, and none is
  configured today.
- **PIR `CONF_MOTION_SENSORS`:** FALSE as a general statement — room PIR
  is a Tier-1 occupancy input (`coordinator.py:1215-1219`, occupancy
  creation, corroboration rings, D2 fail-closed guard) and feeds zone
  Source-1 recency via `_last_motion_time`. The claim only holds for
  camera-sourced motion.

## Recommended action (config-only)

In the ZM options flow, replace in `CONF_ZONE_CAMERAS`:
- `staircase_all_occupancy` → `staircase_person_occupancy` (Back Hallway)
- `upstairs_hall_all_occupancy` → `upstairs_hall_person_occupancy_2` (Upstairs)
- `playroom_all_occupancy_2` → `playroom_person_occupancy_2` (Upstairs)

Optional micro-hardening (separate LOW card, not this one): narrow the
`config_flow.py:8427` selector to `device_class=["occupancy"]` and/or
person-suffix filtering at selection time. A runtime device_class guard
remains pointless — the failure mode is label-scope, not device_class.

Close ZONE-CAM-PERSON-GUARD-1 as superseded by the config fix.
