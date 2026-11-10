# AUDIT: did the 17 `_2` cameras uplift census? (v5.107.1 vs v5.108.1)

Probe date: 2026-11-10 01:05 CST (`date`). Read-only. Author: ura-prober. Scripts: scratchpad `q2.py`..`q8.py`, run as `ssh ha python3 -` with SQLite `immutable=1` (plain `mode=ro` fails on the WAL).
No STATE_OF_PLAY read was required (measurement only, no HVAC/presence change proposed). Facts about the 17 and the fix come from `README_v5.107.1.md` and `AUDIT_face_source_registry_discovery_2026_11.md` §8.

## Answer first
1. **Nothing measurable improved, and nothing measurable regressed.** The post-v5.107.1 sample is only ~14.5 h (11-09 10:33 -> 11-10 01:02 CST), one Monday, and the operator is travelling from about 11-09 (memory `project_operator_nz_travel_2026_11`). The post window holds 6 egress events and 3 named faces from the 17 cameras. That is too small to show an effect of this size.
2. **Frigate itself already produced faces on the 17 cameras before the fix** (227 named recognitions in 7 matched windows, D0 probe says the producers were live). The fix cannot change that and did not. What it changed is whether URA *looked at* them.
3. **The fix is live and wired.** `face_lookup_missing_count` stepped from 8-15 to 27 at 10:33:54 CST 11-09, the restart. That is consistent with about 14 more cameras being looked up. The count is lookups that found no usable state (state `None` counts as a miss, `camera_census.py:3188-3206`), so it rises when quiet cameras are newly polled. It does not measure Frigate output.
4. **v5.108.1 is not measurable yet.** `persons_in_house` has a restart gap at 01:03:24 CST 11-10 (the last 1-2 minutes of data), which I infer is the v5.108.1 start. `frigate_face_msg_seen_count` was 0 at the last rows. I did not verify the running version. There is zero post-108.1 face traffic in the DB.

## Q1. The 17 cameras
Derived by registry join (audit §8.1): the 29 `sensor_recognized_face` rows, each joined by `device_id` to its `occupancy_sensor:*_person` row. Seventeen have a person sensor ending `_person_occupancy_2`. Face sensors are `sensor.<cam>_last_recognized_face_2`:

playroom (interior), upstairs_hall (interior), doorbell_lite, garage_a, g5_bullet, hot_tub, madrone_g6_entry, front_door_aerial, rear_ptz, front_side_ptz, pool_equipment, reolinkstudybporchptz, utilities_ptz, armcrest, armcrestash41b, back_yard, madrone_g6_entry_package.

I cross-checked the list against recorder entities. All 17 face sensors exist. The other 6 `_2` face sensors (family_room, foyer_fisheye, master_hallway, staircase, stairs_top, garage_b) belong to cameras whose person sensor is bare `_person_occupancy`, so they were not skipped. That gives 23 `_2` face sensors in total.

## Q3. What Frigate produced (upstream) vs what URA consumed
Method: `states` rows of `sensor.*_last_recognized_face*` in the HA recorder. A "named recognition" is a row whose state is a name. I dropped `None`, `Unknown`, `unavailable` and `Default`. The first run included `Unknown` and added restart noise; this version excludes it. The recorder starts 2026-11-01 10:12 UTC.

Matched clock windows: each day D, 10:33 CST to 01:02 CST the next day. This is the same clock span as the post window. Pre = 11-02..11-08 (7 windows). Post = 11-09 10:33 -> 11-10 01:02.

(a) **Frigate-produced, the 17 cameras (named recognitions per matched window):**

| Window | 17 cams | all 23 `_2` | bare (6) |
|---|---|---|---|
| 11-02 | 8 | 209 | 3 |
| 11-03 | 96 | 210 | 6 |
| 11-04 | 26 | 58 | 0 |
| 11-05 | 12 | 74 | 2 |
| 11-06 | 21 | 74 | 4 |
| 11-07 | 21 | 46 | 0 |
| 11-08 | 43 | 171 | 29 |
| pre total / mean | 227 / 32.4 | 842 / 120 | 44 / 6.3 |
| **11-09 post** | **3** | **48** | **3** |

Full local days (CST 00-24) for the 17: 11-02 22, 11-03 117, 11-04 33, 11-05 27, 11-06 27, 11-07 23, 11-08 80, 11-09 4.
The 11-09 post count of 3 is below every pre window (min 8), but weekday windows were 12-26, and the house composition changed. Treat it as unproven either way. Per sensor, pre (7 windows) -> post: playroom 104 -> 1, doorbell_lite 26 -> 0, garage_a 18 -> 0, g5_bullet 16 -> 0, upstairs_hall 16 -> 0, madrone_g6_entry 15 -> 1, front_door_aerial 8 -> 1; the rest are 0-9 -> 0; the four zero-name sensors (armcrest, armcrestash41b, back_yard, madrone_g6_entry_package) plus utilities_ptz are 0 -> 0. The pre total is 227, which is about 2x what the D0 probe counted (327 states over 7.6 days with other windows included; that probe used full days, this one uses matched windows, so the two are not directly comparable).

(b) **URA-consumed.** `sensor.universal_room_automation_persons_in_house` attributes are recorded per tick:

| | pre (7 windows) | post (11-09) |
|---|---|---|
| ticks | 18,765 | 2,602 |
| ticks with `face_recognized_persons` non-empty | 8,398 (44.7%) | 442 (17.0%) |
| mean `identified_count` / tick | 1.53 | 1.39 |
| `face_lookup_missing_count` typical | 12-15 | 27-28 |

The attribute drop (44.7% -> 17.0%) tracks the drop in Frigate output (a). The ticks fall under the face freshness window of 1800 s (`const.py:3964`), so a quiet producer empties the set. It is confounded with household presence and is not evidence the fix hurt.

I could not separate "consumed because of the fix". The new diagnostics (`face_source_registry_hits`, `face_source_device_derived_cameras`, `face_source_skipped_person_sensors`) are unrecorded (None in every recorded row), so only a live read of the entity attributes can show L1/L2. I did not read the live attributes (the recorder holds none).

## Q2. Census performance (before vs after)
Table `census_snapshots` (`zone='house'`, UTC timestamps; columns `identified_count`, `unidentified_count`, `total_persons`, `confidence`, `source_agreement`, `frigate_count`, `unifi_count`). Same matched windows as above:

| Window (CST) | rows | rows with unid>0 | sum identified | sum unid |
|---|---|---|---|---|
| 11-02 | 658 | 9 | 1452 | 9 |
| 11-03 | 683 | 58 | 1333 | 71 |
| 11-04 | 650 | 18 | 744 | 21 |
| 11-05 | 654 | 8 | 703 | 8 |
| 11-06 | 661 | 9 | 973 | 11 |
| 11-07 | 637 | 2 | 834 | 2 |
| 11-08 | 644 | 1 | 997 | 1 |
| pre total | 4587 | 105 (2.3%) | 7036 (1.53/row) | 123 (0.027/row) |
| **11-09 post** | **636** | **36 (5.7%)** | **885 (1.39/row)** | **38 (0.060/row)** |

The post unidentified rows are not scattered. 24 of the 36 sit in one episode, 11-09 11:15-11:41 CST, then 12 more rows later. In the episode `identified_persons=["ezinne"]`, `unidentified_count=1`, `total=2`, `source_agreement=close`, `frigate_count=2`, `unifi_count=0`. Pre day 11-03 had a similar single-day spike (58 rows). I cannot say whether the episode is a visitor or an unrecognised resident. The `_2` Frigate faces for those minutes show Jaya/Ezinne/Oji at family_room at 10:55-11:46, which are interior cameras that were never skipped. The 17-camera fix could therefore not have lowered it; I did not trace it further.

Verdict: post identified-per-row and unidentified-rate are inside the pre day-to-day range (identified 0.88-2.2 per row on 11-04..11-06, unid rate 0.2-8.5%). No signal.

**face_recognized_count:** it is not a recorded attribute of `persons_in_house` (the identified-count attribute is `identified_count`; `face_recognized_persons` is the set above). I did not find a `face_recognized_count` series.

**Egress `person_id` attach** (`person_entry_exit_events`; `timestamp` is local-naive, checked against `date`):

| | events | attached | rate |
|---|---|---|---|
| pre 11-02 10:33 -> 11-09 10:33 | 107 | 55 | 51.4% |
| of which on `binary_sensor.*_person_occupancy_2` cameras | 39 | 22 | 56.4% |
| of which other cameras | 68 | 33 | 48.5% |
| post 11-09 10:33 -> 11-10 01:05 | 6 | 3 | 50.0% |
| post on `_person_occupancy_2` | 2 | 0 | 0% |

Per-day attach 11-02..11-09: 66.7, 50.0, 45.5, 46.7, 50.0, 53.3, 52.0, 71.4%.
Notable: egress identity already attached on `_2` cameras *before* v5.107.1 (garage_a `_occupancy_2` 17/25). That is expected, because the egress join goes through `_resolve_face_legs` (device-based, D2b of the earlier cycle), not through the skipped paths. So v5.107.1 was never going to lift egress attach. Its scope was S5/S6/S7 (raw face union, corroboration, guest count) and presence pre-arrival (held off). Post n=6 cannot show a change; the two `_occupancy_2` events were at 00:23 (doorbell_lite entry/exit, no person_id).

## Q4. What v5.107.1 delivered vs what awaits v5.108.1
| Item | State | Evidence |
|---|---|---|
| 17 face sensors looked up by the census | **delivered** (10:33:54 CST 11-09) | `face_lookup_missing_count` 8-15 -> 27 |
| More Frigate faces | **not caused by either release** | the 17 cameras produced 227 named faces pre-fix; producer is upstream |
| S7 guest count `-1` on a fresh interior face | possible only for playroom (upstairs_hall's sensor is not in the interior list, README); not observed. Post playroom named faces: 1 | `guest count` effect unmeasured |
| Egress attach on `_2` cameras | unchanged (already attached) | 56% pre |
| Presence pre-arrival on the 17 | **held OFF by design** (`FACE_SOURCE_PRESENCE_ARRIVAL_DISAMBIGUATED`) | README |
| Face bridge on the live MQTT prefix | **awaits v5.108.1** (just started ~01:03 CST) | `frigate_face_msg_seen_count` 0, `frigate_face_latch_size` 0 at 01:01 and after |

Data that will answer it: `frigate_face_msg_seen_count > 0` and `frigate_face_latch_size > 0` on `persons_in_house`; `frigate_face_msg_face_count`, `frigate_face_last_latched`. Run the same matched windows over 11-10 onward, ideally 7 days, and slice by Oji at home vs away.

## Confounds and caveats
- Post window is 14.5 h and one weekday; 11-09 is the day the operator left for NZ (memory entry says "~11-09 -> 11-16"; I did not verify his departure time). Fewer people means fewer faces and less egress. Pre windows include a weekend.
- The face sensor row counts depend on whether the sensor wrote a row; a repeated name with an unchanged state would not add a row. Only rows whose state is a name count, so each `Jaya` row is one recognition; the `None` rows between them are dropped.
- Recorder retention begins 11-01 10:12 UTC, so no pre-11-02 baseline exists for faces; the census table goes back to 08-11 but identified counts are dominated by BLE (not face).
- `unavailable`/`Unknown` restart rows were excluded from face counts.
- I could not read live attributes of the new diagnostics; they are unrecorded.
- I did not attribute the 11:15-11:41 unidentified episode.

## Recommended next step
One-shot rerun of `q5.py`/`q7.py` after 11-17 (7 post-108.1 matched windows) and a live read of `face_source_device_derived_cameras` and `face_source_skipped_person_sensors` on `persons_in_house` to close L1/L2.
