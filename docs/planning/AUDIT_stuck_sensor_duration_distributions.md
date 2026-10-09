# AUDIT: per-device-class state-duration distributions (OC-STUCK-SENSOR-GENERALIZE-1, step 2)

Measured 2026-10-09 ~02:20 CDT by the overnight pass. Read-only, one shot, over the HA recorder (last 7 days,
binary_sensor only, device_class from core.entity_registry; disabled entities excluded).
Script: `scripts/probes/stuck_sensor_duration_probe.py` (run as `ssh ha "python3 -" < script`).

Method: each entity's states are collapsed to transitions, with `unavailable`/`unknown` kept as a separate
state (a break). Per entity: the longest continuous ON run and the longest continuous OFF run inside the window
(clipped to the 7-day window, so ~162-168 h means "the whole window"). Per class: p50 / p90 / max across entities.
"never changed" = exactly one state across the whole window.

CAVEAT 1: a first pass that dropped unavailable rows produced a false 60.3 h ON cluster across six camera motion
sensors (the offline gap was counted as ON). The table below is the corrected run. Any stuck detector must
treat unavailable as a break, or it will reproduce this artifact.
CAVEAT 2: `occupancy` includes URA's OWN derived sensors (anyone_home, zone_*_anyone, presence house_occupied),
which top the longest-ON list legitimately. A stuck-sensor check must key on raw device sensors, not URA aggregates.

```
class | n | p50/p90/max longest-ON h | p50/p90/max longest-OFF h | sensors never changed in 7d
problem | 390 | 0.0/8.4/65.4 | 33.8/147.4/168.0 | 47
occupancy | 382 | 0.1/3.2/52.9 | 30.6/162.3/168.0 | 67
connectivity | 146 | 8.1/45.0/162.3 | 0.0/19.2/162.3 | 32
motion | 128 | 0.0/9.7/26.1 | 16.5/119.8/162.3 | 16
sound | 121 | 0.0/0.0/0.4 | 45.0/45.0/162.3 | 11
power | 73 | 5.6/32.9/110.2 | 9.5/33.1/45.8 | 9
opening | 51 | 0.0/0.0/8.1 | 0.0/151.5/162.3 | 44
running | 46 | 142.3/142.3/162.3 | 0.0/39.4/142.1 | 5
update | 31 | 0.0/0.0/142.3 | 142.1/142.1/162.3 | 1
door | 30 | 0.0/6.2/102.7 | 15.3/44.9/130.4 | 11
battery | 23 | 0.0/0.0/130.4 | 21.2/44.9/44.9 | 10
carbon_monoxide | 18 | 0.0/0.0/0.0 | 44.9/44.9/44.9 | 0
safety | 18 | 0.0/50.2/162.3 | 162.3/162.3/162.3 | 13
moisture | 15 | 0.0/2.8/129.2 | 39.7/162.3/162.3 | 8
tamper | 9 | 0.0/39.7/39.7 | 9.0/44.9/44.9 | 3
cold | 7 | 1.8/5.4/5.4 | 27.9/162.3/162.3 | 3
heat | 5 | 0.0/0.0/0.0 | 59.8/162.3/162.3 | 2
battery_charging | 4 | 21.4/44.9/44.9 | 40.3/130.4/130.4 | 0
plug | 3 | 31.4/142.8/142.8 | 0.0/0.1/0.1 | 1
presence | 2 | 0.1/0.1/0.1 | 162.3/162.3/162.3 | 1
smoke | 1 | 0.0/0.0/0.0 | 0.0/0.0/0.0 | 1
gas | 1 | 0.0/0.0/0.0 | 39.8/39.8/39.8 | 0
top longest-ON motion: [('pool_equipment_motion_3', 26.1), ('madroneptultra_motion', 21.9), ('reolinkstudybporchptz_motion_2', 21.2), ('g5_bullet_motion_3', 17.2), ('staircase_motion_2', 16.0), ('master_hallway_motion_3', 14.9)]
top longest-ON occupancy: [('universal_room_automation_anyone_home', 52.9), ('zone_master_suite_anyone', 34.7), ('ura_presence_coordinator_house_occupied', 31.8), ('mmwave_zigbee_gameroom_presence', 26.6), ('zone_entertainment_entertainment_anyone', 24.2), ('zone_upstairs_anyone', 19.1)]
top longest-ON presence: [('binarygroup_camera_motion_zone3', 0.1), ('balcony_armcrestpooloverhead_authorized_vehic', 0.0)]
```

## Reading for the plan (not a design)
- motion: p90 longest-ON 9.7 h; raw outliers 21-26 h (pool_equipment_motion_3 26.1, madroneptultra_motion 21.9,
  reolinkstudybporchptz_motion_2 21.2): candidate stuck-ON events for camera-motion sensors.
- occupancy (raw devices): mmwave_zigbee_gameroom_presence 26.6 h ON is the top raw device; the rest of the top 6 are URA aggregates.
- never-fires: classes with many legitimately static members (problem 47, opening 44, safety 13) show "never
  changed in 7 d" is not a defect signal on its own; it needs a per-class expectation (e.g. a motion sensor in an
  occupied room), as the card already says.
