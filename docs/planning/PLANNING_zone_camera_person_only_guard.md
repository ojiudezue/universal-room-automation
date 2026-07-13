# Plan — Zone-camera person-only guard (enforce CONF_ZONE_CAMERAS person-detection invariant)

**Status:** Backlog, LOW priority. No version assigned (stamp at deploy per versioning convention).
**Origin:** 2026-06-08 live finding. Operator spotted `binary_sensor.family_room_motion_3`
(a Frigate camera *motion* sensor, `device_class=motion`) in zone_1's `camera_zone_map`.
Operator removed it from the Zone Cameras config live (immediate issue resolved). This plan
covers the durable CODE guard so it can't recur regardless of config.

## Problem
`zone.zone_cameras` (per-zone list, fed from `CONF_ZONE_CAMERAS`) is documented as
*"Camera person-detection sensors (Frigate person_occupancy, UniFi person_detected)"*
(strings.json:560). But the occupancy-confidence scorer trusts **any** entity in that list
being `on` as a camera **person** confirmation — with **no `device_class` filter**:

- Consumer: `PresenceCoordinator.check_zone_occupancy_confidence` (`presence.py:1543`),
  "Source 3: Camera person detection" at `presence.py:1623-1631`.
- That score feeds the **>max-occupancy-hours stale-sensor guard** in
  `hvac.py:1095-1100`: if `confirmed >= threshold`, the zone's occupancy timer resets
  (treated as real); else it retreats to `away` + vacancy sweep.
- Net effect of a noisy camera-motion sensor in the list: pets / blinds / background motion
  trip it → false "person" confirmation → can keep the zone (here zone_1, master suite)
  "confirmed occupied" past the stuck-sensor check, weakening the retreat. Bounded (it's a
  secondary confirmation source, not the primary occupancy driver) but contradicts the
  documented person-only contract and the operator's expectation.

## Institutional context verified (2026-06-08)
- `CONF_ZONE_CAMERAS` = `hvac_const.py:100`. Built into `zone.zone_cameras` from config at
  `hvac_zones.py:286,311,344` (config is the only population path; the diagnostic
  `camera_zone_map` is derived from it at `hvac.py:1726-1735`, exposed `hvac.py:2131`).
- Consumed for presence confidence at `presence.py:1623-1631` — **no device_class filter**.
- The **tracker** auto-discovery path (`_discover_zone_cameras`, `presence.py:3040`)
  correctly registers `camera_info.person_binary_sensor` (`presence.py:3100`) and honors
  `CONF_DISABLE_CAMERA_PRESENCE` (v4.7.16, `presence.py:3087`). That opt-out does **NOT**
  cover this `zone_cameras` confidence path — separate gap.
- Live confirm: `binary_sensor.family_room_motion_3` is `platform=frigate`,
  `original_device_class=motion`, unique_id `...motion_sensor:family_room`. The other 7
  entries in zone_1's map are `*_person_occupancy` / `*_person_detected` / `*_all_occupancy`.

## Deliverables

### D1: Person-only filter at the consumer (primary)
In `check_zone_occupancy_confidence` Source 3 (`presence.py:1627`), skip camera entities
whose `device_class == "motion"` (resolve via the entity's state attributes /
`original_device_class` in the entity registry). Only `occupancy` / person-detection
camera sensors count toward `confirmed`.
- **Verify:** a `device_class=motion` entity in `zone_cameras` no longer increments `confirmed`.
- **Test:** unit test feeding one motion-class + one occupancy-class camera; only the
  occupancy one counts.

### D2: Ingestion warning (optional, surfaces config mistakes)
At `hvac_zones.py:286` (zone build), log a WARNING naming any `CONF_ZONE_CAMERAS` entity
that resolves to `device_class=motion`, and exclude it from `zone.zone_cameras`.
- **Verify:** boot log warns when a motion sensor is configured as a zone camera; it then
  does not appear in `camera_zone_map`.

### D3: Config-flow picker filter (optional, prevents the mistake)
Check `async_step_zone_cameras` (`config_flow.py:6320`) — ensure the selector offers only
person/occupancy camera binary_sensors, not raw `device_class=motion`. If it already
filters, D3 is a no-op; if not, tighten the selector.

## Tier
Tier 1 / focused — a single confined path. May elevate to Tier 2 since it touches presence
confidence (consumed by the HVAC stale-sensor guard). LOW priority — operator has already
neutralized the live instance via config.

## Live
- After fix: `camera_zone_map` / `zone.zone_cameras` contains no `device_class=motion`
  entities; the confidence scorer ignores any that slip in.
