# Camera input stream health S1: a dead camera's inputs stop holding the room (DRAFT, version not assigned)

Cards: PANEL-KS-HEALTH-AS-INPUT-1 (S1). S2 (zone tier, fan recheck, census) is CAMERA-STREAM-DEAD-ZONE-AND-CENSUS-1 and
is NOT in this ship. Plan: `docs/planning/PLANNING_camera_input_stream_health.md`. Tier 2-DB (room occupancy ripples into
lights, fans, HVAC).

## What changed

- A room input (motion / presence / occupancy list) whose own camera entity has read `unavailable` for 120 s no longer
  counts in that room's occupancy. "Own camera" means the input's device carries exactly one enabled `camera.*` entity.
  Devices with no camera, a disabled camera, or two or more cameras (NVR devices) are left alone.
- The rule keys on the camera entity's availability only. It does not look at camera names, the kiosk app or the NVR brand.
  The 120 s must be continuous: if the camera reads `unknown` / nothing for longer than 120 s between two `unavailable`
  readings, the clock restarts. A camera reading `unavailable` with `restored: True` (its integration has not loaded it,
  e.g. Frigate in setup retry) is "no opinion": it excludes nothing and pages nothing.
- The room's camera override (a camera in the room's area whose person sensor reads `on` keeps the room occupied after
  the sensors time out) now skips a person sensor whose own camera is dead, so it can no longer hold the room that way
  (review B-M1). Only the dead-stream exclusion applies here; stuck / chattering exclusions do not, as before (review
  D-M1). An override person sensor that is not a room input is watched and excluded the same way,
  but it is not paged and not shown on the sensor.
- If the exclusion lasts 30 min, one HIGH notification says which input stopped counting and which camera is down, once
  per room input per day. A LOW "counts again" notification follows when the camera returns.
- `sensor.<room>_unavailable_entities` gains two display attributes (not recorded): `camera_stream_dead_inputs` and
  `camera_stream_inputs_resolved`.
- New public getter `camera_input_stream_dead(input_eid)` on the room coordinator (for S2 and a later NVR-witness layer).

## Knobs (all rung 1, `const.py`)

| Knob | Default | Effect |
|---|---|---|
| `CAMERA_INPUT_STREAM_HEALTH_ENABLED` | True | False = no exclusion, no notification (pre-S1 behaviour) |
| `CAMERA_INPUT_STREAM_DEAD_GRACE_S` | 120 | seconds of `unavailable` before inputs stop counting |
| `CAMERA_INPUT_STREAM_DEAD_NM_AFTER_S` | 1800 | seconds of exclusion before the HIGH page; 0 = no page |

## Not in this ship

- S2: the zone tracker, fan recheck and census still count a frozen dead-camera `on` (they never honoured room
  exclusions). Until S2 ships, the Upstairs Hallway zone can still be held by the frozen panel input until the 4 h
  stuck-sensor rule.
- Kiosk app health (`foreground_app`) and kiosk restarts (homelab watchdog), per plan §8 non-goals.

## Acceptance (prospective; replace with a `Validated <date>` table after restart)

- **Live:** `sensor.study_a_unavailable_entities`, `sensor.kitchen_unavailable_entities` and
  `sensor.upstairs_hallway_unavailable_entities` each show `camera_stream_inputs_resolved = 1` and an empty
  `camera_stream_dead_inputs` while the panels stream. The sensor is disabled by default
  (`_attr_entity_registry_enabled_default = False`); on Upstairs Hallway it is `disabled_by: integration` today, so
  enable it before reading (review B-L4).
- **Live:** no `camera-derived input(s) ... have no single camera entity` WARNING in the log for those three rooms after
  restart (a WARNING there means the panel's device did not resolve to one camera).
- **Organic:** the next panel outage lists the panel person input under `camera_stream_dead_inputs` within about 2.5 min
  (120 s grace + one 30 s room poll), and the room is not held occupied by it. Discriminator: under the fix the room's
  `binary_sensor.<room>_occupied` drops one room-timeout after the input is listed; under the old behaviour it stays `on`
  until the 4 h stuck-sensor rule.
- **Organic:** if that outage lasts 30 min, exactly one HIGH `Camera stream dead: <room>` notification, and one LOW
  recovered notification when the camera returns.
- **In-suite only:** the byte-identical cases (unresolved camera, kill switch off) and the grace / NM boundaries are
  proven in `quality/tests/test_camera_stream_health.py`; they cannot be forced live without breaking a camera.
