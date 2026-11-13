# AUDIT: interior path map, learned co-detections vs the operator map (D7, 2026-11-12)

Card INTERIOR-PATH-MAP-1 / FACE-ARRIVAL-REBUILD-1 D7. Read-only. Sources:
`scripts/probes/face_sighting_d0.py` (P4, declared edges) and
`scripts/probes/interior_path_learned_pairs.py` (all ordered pairs, person `on` -> `on` within 120 s,
recorder window 7.5 days to 2026-11-12 22:21 CST). The learned list is a SUGGESTION report only
(exterior-seam doctrine: co-firing measures household movement, not adjacency). Nothing here is
loaded at runtime; an edge enters the map only when the operator copies it into
`/config/universal_room_automation/interior_paths.json`.

Operator map: `FIXTURE_camera_paths_interior.md` ("Operator answers"), encoded as
`const.INTERIOR_PATH_MAP_FALLBACK` (the draft file content is identical; lags = measured p90).

## Operator edges and what the recorder shows

| Door | Edge | Kind | Hops/day | p50 / p90 s | Note |
|---|---|---|---|---|---|
| garage_a | rear_ptz -> garage_a | approach | 0.9 | 24 / 55 | |
| garage_a | g5_bullet -> garage_a | approach | 9.2 | 17 / 73 | |
| garage_a | rear_ptz -> doorbell_lite | approach | 4.9 | 14 / 36 | lag not set in the const (default 30 s window) |
| garage_a | g5_bullet -> doorbell_lite | approach | 15.1 | 2.5 / 25 | default window |
| garage_a | garage_a -> staircase | inward | 12.7 | 22 / 63 | |
| garage_a | staircase -> stairs_top | inward | 4.5 | 18 / 72 | |
| garage_a | stairs_top -> playroom | inward | 8.4 | 13 / 67 | |
| garage_a | stairs_top -> upstairs_hall | inward | 8.3 | 31 / 84 | |
| garage_a | staircase -> family_room | inward | 18.3 | 27 / 85 | |
| front | front_side_ptz -> front_door_aerial | approach | 2.4 | 14 / 38 | |
| front | utilities_ptz -> front_door_aerial | approach | **0** | - | operator edge with zero observed hops (finding) |
| front | sonoffwindow -> front_door_aerial | approach | 0.8 | 6 / 12 | |
| front | front_door_aerial -> foyer_fisheye | inward | 3.7 | 13 / 63 | |
| front | madrone_g6_entry -> foyer_fisheye | inward | 4.9 | 21 / 87 | |
| front | foyer_fisheye -> family_room | inward | 42.7 | 16 / 81 | |
| front | foyer_fisheye -> master_hallway | inward | 39.9 | 18 / 82 | |

## Learned-only pairs worth an operator look (>= 2 hops/day, short p50)

| Pair | Hops/day | p50 / p90 s | Reading |
|---|---|---|---|
| upstairs_hall <-> playroom | 13.5 / 10.3 | 9 / 68 | direct sibling hop not in the map (both are inward from stairs_top); possible adjacency or overlapping view |
| front_door_aerial -> madrone_g6_entry | 5.2 | 1.9 / 22 | the two front egress views of one crossing (never scored by design) |
| garage_a <-> doorbell_lite | 10.8 / 10.5 | 7 / 35 | the two garage egress views (never scored by design) |
| master_hallway <-> family_room, master_hallway -> foyer_fisheye | 81 / 74 | 21 / 7 | heavy everyday interior movement, not a door path |
| g5_bullet <-> doorbell_lite, rear_ptz <-> g5_bullet | 15.7 / 7.6 | 3 / 7 | exterior approach cluster; consistent with the map |

Everything else above 2/day (e.g. family_room -> staircase, doorbell_lite -> family_room) has a p50 of
30-70 s and reads as "walked through the house", not a hop.

## Differences vs the live `door_interior_neighbours` (findings, not edits)

Live neighbours: front = foyer (3 legs) + family_room (2 legs); garage_a = Protect garage hallway,
staircase, garage_hallway camera, stairs_top; garage_b = []. The path map adds the approach cameras
and the deeper interior chain (playroom, upstairs_hall, master_hallway) that the neighbour option does
not list; that is intended and does NOT change the neighbour option (pinned by
`test_door_neighbours_untouched.py`). Garage B, patio and Study B have no map entry until their door
groups exist (EGRESS-CONFIG-PATIO-STUDYB-1).
