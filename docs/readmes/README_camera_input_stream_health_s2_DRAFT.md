# DRAFT: Camera input stream health S2 (zone tier, night reads, fan readers, census)

Card: CAMERA-STREAM-DEAD-ZONE-AND-CENSUS-1. Plan: `docs/planning/PLANNING_camera_input_stream_health.md` S2.
Tier 2-DB (regression-prone: zone occupancy feeds house state; census feeds AWAY / GUEST). Version: set at release.
Fix-up after reviews A / B / C (2026-11-14), including the operator ruling on review B-M2; fix-up round 2 after the
framing-D re-verify (measured caps, hold-release page, D-M1, D-L1, D-L2, D-L3).

## What changed

S1 stopped a dead camera's frozen input from holding its ROOM. S2 makes the readers outside the room follow the same
answer, through the same getter, under one rule for occupancy readers.

**A dead input holds (operator ruling 2026-11-14):** "A dead input holds instead of releasing. A dead camera is not a
presence or absence of signal. Its faulty equipment." Outside the room a dead-stream input is unknown: it cannot create
occupancy and it cannot end it. The zone keeps its level until one of three things happens:

1. a live input of the same room goes `on` -> `off`;
2. the camera streams again;
3. the hold cap passes from the camera's first `unavailable` room tick: `CAMERA_INPUT_STREAM_DEAD_HOLD_MAX_S` (zone,
   900 s) or `CAMERA_INPUT_STREAM_DEAD_CENSUS_HOLD_MAX_S` (census, 900 s). Past the first cap the camera's inputs are
   released and ONE HIGH page names the camera and how long it has been dead ("hardware or host failure, not a normal
   outage"; kind `camera_stream_hold_released`, key = the camera, LOW on recovery, once per outage).

The caps are measured (`docs/planning/AUDIT_camera_outage_durations_2026_11_14.md`, 7.9 days, restarts excluded):
every ordinary outage, fleet-wide or one stream, ended within 6.3 min; nothing lasted 6.3-39 min; the long ones
(438 min Frigate/MQTT down, a 39 h panel stream death, a dead Protect device) were real failures. The operator chose
15 min for both ("make both 15 mins"); they are separate constants so they can diverge. The earlier 4 h had no basis.

**Unavailable together with its camera (review D-M1).** UniFi Protect marks every entity of a disconnected device
unavailable at once, so the input read `unavailable` (off) before its camera's grace ran. Now a resolved input that
reads `unavailable` is held from t0 (zone tier, zone camera tier, census) until a room tick sees its camera LIVE in that
same unavailable episode; then it is an ordinary sensor outage and counts as off (the tick's discharge re-reads it,
<= one 30 s poll later than develop). If the camera reads `unavailable` too, the camera turns dead at the grace and the
caps above end the hold. The census keeps the entity's last available reading while it is held (RAM; after a restart
there is none, so it is a missing term as before). Write order does not matter (input before or after the camera).

**Quarantined sensors (review D-L2).** A sensor its room quarantines (chatter, stuck, duty-cycle, P22) is not working
equipment either: its `on -> off` no longer ends a dead-camera hold.

So a camera dying cannot, by itself, empty a zone or move the house from Sleep or Home to Away.

| Reader | Before (develop) | After |
|---|---|---|
| Zone substrate (`OccupancySubstrate`, the zone tracker's Tier-1 view) | a frozen panel `on` held the zone until the 4 h stuck rule, indefinitely at the zone tier | held while unknown (cannot create, cannot end); released by a live, unquarantined input's `on -> off` in the room, by the camera streaming again, or at 900 s; the room tick tells the substrate when an input flips dead / live / released (`recheck_entities`) |
| Zone camera tier (`_any_camera_occupied`) | a frozen detection held the zone | held until 900 s or recovery; a detection change from a dead camera is ignored and resynced when it streams again |
| `_zone_night_rooms` switch-off live limb (night / nobody-home) | counted the frozen `on` | counts it until 900 s or recovery |
| Census interior counts (both branches) + unrecognised (guest) count | the frozen count was counted forever | counted while held (900 s census cap; an unavailable-with-camera entity counts its last reading); then a MISSING term (as if unavailable), never a zero |
| HVAC D6 stale-occupancy confirmation (`check_zone_occupancy_confidence` Source 3) | a dead camera's frozen `on` confirmed presence, so D6 kept resetting | a dead camera confirms nothing, so D6 can release |
| Presence fan-interference gate (`_room_radar_sole_capable`) | the frozen panel made the room radar-sole | dropped from the live on-set (the gate only extends occupancy, so this can never end it) |
| Comfort-fan AWAY veto (`fan_veto` motion leg + legacy camera leg) | a frozen camera-derived `on` was trusted presence | not trusted. The legacy camera leg runs only when the room's fused `camera_person_detected` sensor has no state, so in production the fan veto's camera leg is NOT stream-health aware (carded) |
| Fan pause-recheck | already followed the room (S1) | unchanged |

New public getters for later consumers (NVR witness W2 / W6b): `camera_stream_health.camera_stream_dead(hass,
camera_entity)` → True / False / None (no room watches that camera), and `entity_stream_view` / `input_stream_view` →
None / `held` / `released`.

New knobs (rung 1): `CAMERA_INPUT_STREAM_DEAD_HOLD_MAX_S` (zone, 900 s) and `CAMERA_INPUT_STREAM_DEAD_CENSUS_HOLD_MAX_S`
(census, 900 s); 0 = no hold (a dead input counts as off as soon as it is dead, no hold page). No new entity, no DB change. Kill switch `CAMERA_INPUT_STREAM_HEALTH_ENABLED` False = every reader
byte-identical to develop.

AWAY for a real departure is unchanged: it goes through path alpha, which reads neither zone occupancy nor the
substrate. What the hold can delay, by up to the cap (900 s + one room poll + one census run), is an AWAY that depends
on empty zones (nobody-home, path beta's indoor guard) or on a body a dead census camera last saw (alpha reads the
census unidentified count; pinned `test_departure_with_frozen_census_body_bounded_by_census_cap`). Review D-L1: alpha
can also see the ZONE hold, indirectly: census divergence corroboration (`_any_zone_occupied_snapshot`) treats a zone
held by a dead camera as corroboration and keeps the higher of two divergent platform counts, so a held zone can keep
`unidentified_count >= 1` (needs a second, live platform reading a non-zero count); bounded by the 900 s zone cap.

## Not covered (carded)

- The room-tier fused `binary_sensor.<room>_camera_person_detected` (CONF_ROOM_CAMERAS fusion), which fan_veto's live
  camera leg reads.
- Census face reads and the stuck-camera watchdog.
- `camera_stream_dead` returns None for cameras that no room input watches (perimeter ring cameras), so W6b cannot bridge
  them until they are watched.
- D-M1 for a census sensor that is NOT a room input: before its camera's grace it reads as unavailable (missing term);
  after the grace its camera is dead and it is held with its last reading. Cameras no room watches get no hold page.
- (Fixed in release/batch-2.) The S1 per-input page (`camera_stream_dead`, after 1800 s) no longer fires for an input
  whose camera already sent the hold-release page in the same outage: one HIGH page per outage. With both caps 0 (no hold
  page) the S1 page fires as before. If the caps are ever raised above 1800 s the S1 page comes first and the hold page
  still follows (not de-duplicated in that order).

Named residuals: the zone camera tier and the census have no live-input release (cap and recovery only); with
`ZONE_OCCUPANCY_PER_ENTITY_ENABLED` False the night live limb holds until the cap or recovery even after a live end, and
does not count an unavailable-with-camera input (it reads only `on`); a restart or a room reload restarts the grace and
the cap clock.

## Acceptance (prospective)

- **Test:** `quality/tests/test_camera_stream_health_s2.py` (every load-bearing site is anchored by a single-site source
  mutation that turned a named test red).
- **Live, panel outage (organic, the next KS panel outage; judged at the ZONE, not the census):** the panel inputs
  (`binary_sensor.{study_a,kitchen,up_hallway}_panel_person_occupancy`) are room `presence_sensors` only; no census
  interior camera is a panel. Within ~2.5 min of the panel camera reading `unavailable`,
  `sensor.<room>_unavailable_entities` lists the input under `camera_stream_dead_inputs`, and the panel room's zone
  (`sensor.zone_<z>_presence_status` / its tracker room view) does NOT change at that moment (held). Discriminates:
  develop also holds, but without the cap; the first S2 build dropped the zone at ~2.5 min. The zone releases at
  the first `on -> off` of a live sensor in that room, or 900 s after the room first saw the camera `unavailable`,
  whichever is first, with one HIGH `Camera dead 15 min: camera.<x>` page. Fail = the zone drops within minutes of the
  outage with no live sensor going off, or stays held past ~16 min, or no page.
- **Live, census (only on an outage of an INTERIOR census camera, i.e. one in `camera_person_entities`):** for 900 s the
  dead camera keeps its frozen count in `sensor.universal_room_automation_persons_in_house` `area_contributions`; after
  900 s it is absent from `area_contributions` (missing term) while `camera_input_dark` is unchanged. A panel outage is not
  evidence either way.
- **Live, HVAC D6:** not observable on demand; proven in-suite (`test_source3_dead_zone_camera_confirms_nothing`).
- **Live (now):** no change while the panels stream (the substrate kinds and census counts match develop).

## Validated

Pending deploy.
