# AUDIT: which other cameras need a Protect smart-detect exclusion zone (2026-11-13)

Read-only probe, run 2026-11-13 ~11:25-11:35 CST. Nothing changed in HA, Protect or Frigate. Frigate was not logged into. I did not read the HVAC/presence state-of-play docs (not relevant). Inputs: `PLAN_perimeter_fp_joint_2026_11.md` (Phase 2 = lines on rear_ptz and g5_bullet only, still PROPOSED), `.claude/worktrees/superbuilder-house-state-1a/docs/planning/AUDIT_perimeter_path_alert_2026_11_13.md`.

## Answer first
rear_ptz is done by the operator. Add, in this order:
1. **g5_bullet** (already in joint plan Phase 2): exclude the top-right corner, the street and sidewalk.
2. **utilities_ptz** (NOT in the plan's Phase 2; it appears only in Phase 1 Frigate work): exclude the far road and bank across the lawn.
3. **Nothing else justified by the data.** back_yard, hot_tub, pool_equipment, front_side_ptz have too few Protect-only alerts or show real people; do not add zones.

Caveat that matters: a Protect zone only stops the Protect leg. On g5_bullet and utilities_ptz, Frigate-2 also alerts on the same street walkers (no Frigate masks there), so the Frigate road masks (Phase 1) are still needed or the alert just arrives via `_2`.

## Method
- Source: `notification_log` in `/config/universal_room_automation/data/universal_room_automation.db` on HA (`ssh ha`), rows `coordinator_id='perimeter_alert' AND hazard_type='exterior_person'`, window = last 14 days (to 2026-11-13 ~11:25 CST). One alert = distinct (location, first message line), collapsing the 4 channel rows. 120 alerts.
- Leg: `location` is the triggering sensor. `*_person_detected` (or no `_2`) = Protect; `*_person_occupancy_2` = Frigate-2.
- Corroboration: an ON edge of the other leg's sensor (`binary_sensor.<cam>_person_occupancy_2` or `_person_detected`) in the HA recorder (`home-assistant_v2.db` `states`) within +/-180 s of the alert. "Alone" = none found. This is a proxy (the sibling may fire for a different reason), so "alone" counts are solid and "corroborated" counts are an upper bound.
- Snapshots: `/media/ura/snapshots` on HA; matched by epoch in filename (+/-12 s). I viewed 10 Protect-alone frames and 4 corroborated frames (details below). 2 alone alerts (rear_ptz 10-30, g5_bullet 10-30, utilities_ptz 10-30) were already purged (7-day retention).

## Per-camera counts (14 days)
| Camera | Protect alerts | Protect alone (no F2 within 3 min) | Protect corroborated | F2 alerts | Viewed |
|---|---|---|---|---|---|
| rear_ptz | 25 | **17** | 8 | 6 | 7 |
| g5_bullet | 21 | **7** | 14 | 19 | 6 |
| utilities_ptz | 8 | **3** | 5 | 1 | 4 |
| back_yard | 5 | 5 | 0 | 1 | 2 |
| hot_tub | 4 | 1 | 3 | 7 | 0 |
| pool_equipment | 3 | 1 | 2 | 9 | 0 |
| front_side_ptz | 3 | 1 | 2 | 3 | 0 |
| armcrestpooloverhead, ptzcam study B, sonoffwindow | 1 each | 1 each | 0 | n/a | 0 |

## Recommended Protect zones

### rear_ptz: DONE by operator (verify it covers this)
- 17 of 25 Protect alerts uncorroborated (68%); 11-13 08:56 CRITICAL is one.
- Exclude: everything above the road's near edge, about the top 60% of the parked frame (y < ~0.62): the road, the far sidewalk, neighbouring lawns, houses and driveways. Own property starts at the near lawn and paver path in the bottom ~40%.
- Evidence: frames `rear_ptz_1794411429_d5ad32` (walker on far road y~0.47), `_1794330428_6c426c` (person beside a truck, neighbour driveway, x~0.95 y~0.50), `_1794513496_b2c02d` (woman with two dogs on the road y~0.50), `_1794581776_0feb7c` (11-13 CRITICAL, road pedestrian). Corroborated ones are also street walkers (`_1794355493_01e45f`, night, person on road y~0.55), so the F2 road mask (y<0.62) is doing its job on that leg; this zone matches it.
- Caveat: PTZ; zone only holds at the parked view. All samples above show the same framing, so it is parked.

### g5_bullet: ADD (plan Phase 2 already lists it)
- 7 Protect-alone alerts, all 11-09..11-12 plus one 10-30 (frame purged). Includes one CRITICAL (11-11 14:01 UTC).
- Exclude: the top-right corner above a line from top-middle (x~0.55,y=0) to right edge at y~0.22: the curving road, the far sidewalk and the neighbour house beyond it, plus a thin top strip (timestamp overlay and eave, y<0.07). Keep the driveway mouth.
- Evidence (all 1280x720, alert frame has the person here): `g5_bullet_1794405716_f41da1` (walker + dog at x~0.85 y~0.08), `_1794320136_f0afcd`/`_1794331489_53bc90` (person at x~0.90 y~0.10), `_1794527640_e37e0d` (person at x~0.80 y~0.10), all on the road/verge above the lawn, nothing on the property.
- Do NOT over-extend the zone: the 14 corroborated alerts are real residents at the garage door/driveway (`g5_bullet_1794407152.926276-1qd2m5`, `_1794439985.317657-2ud13a`, boxed person at x~0.40 y~0.1-0.2). That area is below the diagonal and must stay live.
- Note: F2 raised 19 alerts on this camera and has no mask there, so also do the Frigate object mask (joint plan Phase 1) or street walkers still alert via `_2`.

### utilities_ptz: ADD (gap in plan; Phase 2 does not list it)
- 3 Protect-alone out of 8 (38%), 5 more corroborated; 11-11 13:48 UTC alert was CRITICAL.
- Exclude: everything above the lawn edge, about y < 0.42-0.47 sloping from y~0.47 (left) to ~0.41 (right) per HomeLab's polygon `0,0.47 0.5,0.43 1,0.41 1,1 0,1` in the plan: the gravel road, far bank, treeline, and the neighbouring side at the right edge.
- Evidence: `utilities_ptz_1794347355_24690a` (person on the far road at x~0.95 y~0.35, beside parked truck/trash bin), `_1794189929_540665` (night, figure on the road/berm top, y~0.28 near x~0.55), corroborated `_1794404888_059bbe` (walker on the gravel road y~0.33). In all frames the near lawn is empty.
- PTZ caveat: parked view only. Confirm it stays parked (joint plan says "if it roams").

### Not recommended (evidence too thin or people are real)
- **back_yard**: 5 Protect alerts, all alone, but the 2 frames I viewed (`back_yard_1794428219_7baf29`, `_1794513275_a022fa`) show a real person at the far-left edge (x<0.07, y~0.28-0.36) next to a paved ledge. Cannot tell from the frame if that strip is own side-yard or the neighbour's; the frames are real people, not empty. Operator to say; I would not add a zone from this. (The Frigate-side empty-frame noise from the 11-08 audit is a different leg and is handled by Phase 1 filters.)
- **hot_tub, pool_equipment, front_side_ptz, study B porch, sonoffwindow, armcrestpooloverhead**: 1 Protect-alone each in 14 days. Below the bar; no snapshots inspected. Revisit if the count grows.

## Cross-check against the joint plan
| Camera | Joint plan Phase 2 | This audit |
|---|---|---|
| rear_ptz | listed | confirmed (17 alone) |
| g5_bullet | listed | confirmed (7 alone, geometry matches Phase 1b polygon) |
| utilities_ptz | not listed (Phase 1 Frigate zone only) | **add** (3 alone + street frames) |
| front_side_ptz, door/garage cams | not listed | no evidence; none needed |

## Falsification
- If a Protect zone drop does not reduce Protect-only alerts on that camera next week, the above assumption (street walkers are the source) is wrong. Observable: recount `notification_log` Protect-only alerts on that camera after the zone is in.
- Claim "alone = Protect-only" would be wrong if the F2 sensor was unavailable at the time; I did not check `_2` sensor availability per alert. Rear_ptz's 11-13 08:56 case was verified in the earlier audit.
- Samples are small (14 frames) and mostly daytime; 11 of 14 alerts were at 08:00-17:00 local.

## Not verified
- The live Protect zone config (API does not expose zones); whether the operator's rear_ptz zone matches y<~0.62.
- Live Frigate-2 masks (not logged in).
- Counts cover only alerts that reached the notification log (dispatched), not all Protect detections.

## Files
- Report: `/Users/okosisi/Code/universal-room-automation/docs/planning/AUDIT_protect_zone_additions_2026_11_13.md`
- Scratch frames: `/private/tmp/claude-501/-Users-okosisi-Code-universal-room-automation/75cc297f-1426-4620-b7aa-da058bc0fab0/scratchpad/snaps/` and `.../c/`
