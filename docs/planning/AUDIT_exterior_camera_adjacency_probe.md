# AUDIT: Exterior Camera Adjacency Probe (operator ratification input)

**Date:** 2026-08-06 · **Read-only probe** over the HA recorder DB (`home-assistant_v2.db`, ro). No code changed.
**Purpose:** derive a CANDIDATE `EXTERIOR_ADJACENCY_GRAPH` for the ExteriorTrackLinker (branch `build/exterior-track`) from observed person-detection sequences. This is ratification input, not the graph of record — the operator confirms/edits before it lands in `const.py`.

## Method
- Camera set = the 9 `perimeter_cameras` + 3 `egress_cameras` from the URA integration entry (`.storage/core.config_entries`). Camera keys are the Frigate names, matching `_camera_key_for_sensor` (strip `binary_sensor.` + `_person_occupancy`).
- Events = ON-transitions of each camera's Frigate `*_person_occupancy` binary sensor (both `_person_occupancy` and `_person_occupancy_2` registry duplicates merged per camera).
- **Retention window is only ~7 days**: 2026-07-30T04:15:24.823565 → 2026-08-06T06:03:34.155340 (659 ON-events total). "Full window" ≈ 7-day window here.
- Transition matrix: for each ordered pair (A,B), count B firing within **180 s** after A, A≠B.
- **Simultaneity filter** (multi-person inflation guard): a transition A→B is DROPPED when (a) B had its own ON within 300 s before the B event (B already active — not a hand-off), or (b) ≥3 distinct cameras fired within ±60 s of the A event (multi-person burst). This is a coarse heuristic; it cannot distinguish two people walking different sides of the house at the same minute. Raw pair count 103 → filtered 48, so roughly half of raw co-firings were simultaneity, not movement.

## Camera inventory

| Camera key | Sensor entity | 7-day ON count | Full-window ON count |
|---|---|---:|---:|
| `armcrest` | `binary_sensor.armcrest_person_occupancy` | 39 | 39 |
| `back_yard` | `binary_sensor.back_yard_person_occupancy` | 28 | 28 |
| `doorbell_lite` | `binary_sensor.doorbell_lite_person_occupancy` | 33 | 33 |
| `front_door_aerial` | `binary_sensor.front_door_aerial_person_occupancy` | 34 | 34 |
| `front_side_ptz` | `binary_sensor.front_side_ptz_person_occupancy` | 96 | 96 |
| `g5_bullet` | `binary_sensor.g5_bullet_person_occupancy` | 45 | 45 |
| `hot_tub` | `binary_sensor.hot_tub_person_occupancy` | 28 | 28 |
| `madrone_g6_entry` | `binary_sensor.madrone_g6_entry_person_occupancy` | 48 | 48 |
| `pool_equipment` | `binary_sensor.pool_equipment_person_occupancy` | 93 | 101 |
| `rear_ptz` | `binary_sensor.rear_ptz_person_occupancy` | 75 | 119 |
| `reolinkstudybporchptz` | `binary_sensor.reolinkstudybporchptz_person_occupancy` | 30 | 30 |
| `utilities_ptz` | `binary_sensor.utilities_ptz_person_occupancy` | 58 | 58 |

Roles: perimeter = reolinkstudybporchptz, rear_ptz, utilities_ptz, front_side_ptz, armcrest, hot_tub, pool_equipment, g5_bullet, back_yard. Egress = madrone_g6_entry, doorbell_lite, front_door_aerial.

## Transition matrix (filtered, directed, count ≥1)

| A → B | count | rate (per A-event) |
|---|---:|---:|
| utilities_ptz->front_side_ptz | 19 | 0.33 |
| utilities_ptz->rear_ptz | 15 | 0.26 |
| front_side_ptz->rear_ptz | 14 | 0.15 |
| madrone_g6_entry->front_door_aerial | 11 | 0.23 |
| pool_equipment->rear_ptz | 6 | 0.06 |
| utilities_ptz->madrone_g6_entry | 6 | 0.10 |
| rear_ptz->front_side_ptz | 5 | 0.04 |
| front_side_ptz->hot_tub | 4 | 0.04 |
| g5_bullet->front_side_ptz | 4 | 0.09 |
| front_side_ptz->utilities_ptz | 4 | 0.04 |
| g5_bullet->madrone_g6_entry | 3 | 0.07 |
| front_side_ptz->back_yard | 3 | 0.03 |
| front_side_ptz->reolinkstudybporchptz | 3 | 0.03 |
| back_yard->armcrest | 3 | 0.11 |
| doorbell_lite->g5_bullet | 3 | 0.09 |
| doorbell_lite->armcrest | 3 | 0.09 |
| madrone_g6_entry->front_side_ptz | 3 | 0.06 |
| front_door_aerial->hot_tub | 3 | 0.09 |
| armcrest->reolinkstudybporchptz | 3 | 0.08 |
| armcrest->hot_tub | 3 | 0.08 |
| front_side_ptz->front_door_aerial | 2 | 0.02 |
| g5_bullet->rear_ptz | 2 | 0.04 |
| rear_ptz->utilities_ptz | 2 | 0.02 |
| g5_bullet->doorbell_lite | 2 | 0.04 |
| reolinkstudybporchptz->armcrest | 2 | 0.07 |
| back_yard->hot_tub | 2 | 0.07 |
| doorbell_lite->rear_ptz | 2 | 0.06 |
| front_door_aerial->rear_ptz | 2 | 0.06 |
| madrone_g6_entry->rear_ptz | 2 | 0.04 |
| armcrest->back_yard | 2 | 0.05 |
| armcrest->g5_bullet | 2 | 0.05 |
| armcrest->doorbell_lite | 2 | 0.05 |
| pool_equipment->armcrest | 1 | 0.01 |
| rear_ptz->armcrest | 1 | 0.01 |
| g5_bullet->utilities_ptz | 1 | 0.02 |
| doorbell_lite->madrone_g6_entry | 1 | 0.03 |
| rear_ptz->back_yard | 1 | 0.01 |
| front_side_ptz->g5_bullet | 1 | 0.01 |
| reolinkstudybporchptz->rear_ptz | 1 | 0.03 |
| reolinkstudybporchptz->g5_bullet | 1 | 0.03 |
| rear_ptz->doorbell_lite | 1 | 0.01 |
| doorbell_lite->front_side_ptz | 1 | 0.03 |
| rear_ptz->g5_bullet | 1 | 0.01 |
| madrone_g6_entry->hot_tub | 1 | 0.02 |
| front_door_aerial->front_side_ptz | 1 | 0.03 |
| rear_ptz->front_door_aerial | 1 | 0.01 |
| rear_ptz->madrone_g6_entry | 1 | 0.01 |
| g5_bullet->armcrest | 1 | 0.02 |

## PROPOSED adjacency graph

Threshold: symmetric (A↔B summed) filtered count **≥3**, chosen because below 3 a single multi-person afternoon can fabricate a pair. Every 2026-08-02 walker-sequence hop clears it (g5_bullet↔rear_ptz sits exactly at the threshold — see sanity check).

| Pair | filtered (sym) | raw (sym) |
|---|---:|---:|
| front_side_ptz ↔ utilities_ptz | 23 | 96 |
| front_side_ptz ↔ rear_ptz | 19 | 78 |
| rear_ptz ↔ utilities_ptz | 17 | 26 |
| front_door_aerial ↔ madrone_g6_entry | 11 | 73 |
| pool_equipment ↔ rear_ptz | 6 | 33 |
| madrone_g6_entry ↔ utilities_ptz | 6 | 34 |
| front_side_ptz ↔ g5_bullet | 5 | 37 |
| armcrest ↔ back_yard | 5 | 34 |
| doorbell_lite ↔ g5_bullet | 5 | 60 |
| armcrest ↔ doorbell_lite | 5 | 27 |
| armcrest ↔ reolinkstudybporchptz | 5 | 67 |
| front_side_ptz ↔ hot_tub | 4 | 23 |
| g5_bullet ↔ madrone_g6_entry | 3 | 3 |
| back_yard ↔ front_side_ptz | 3 | 14 |
| front_side_ptz ↔ reolinkstudybporchptz | 3 | 17 |
| front_side_ptz ↔ madrone_g6_entry | 3 | 31 |
| front_door_aerial ↔ hot_tub | 3 | 8 |
| armcrest ↔ hot_tub | 3 | 37 |
| front_door_aerial ↔ front_side_ptz | 3 | 9 |
| g5_bullet ↔ rear_ptz | 3 | 62 |
| doorbell_lite ↔ rear_ptz | 3 | 21 |
| front_door_aerial ↔ rear_ptz | 3 | 4 |
| madrone_g6_entry ↔ rear_ptz | 3 | 4 |
| armcrest ↔ g5_bullet | 3 | 44 |

Paste-ready for `EXTERIOR_ADJACENCY_GRAPH` in `const.py` (symmetric, tuple values):

```python
EXTERIOR_ADJACENCY_GRAPH: Final[dict[str, tuple[str, ...]]] = {
    "armcrest": ('back_yard', 'doorbell_lite', 'g5_bullet', 'hot_tub', 'reolinkstudybporchptz'),
    "back_yard": ('armcrest', 'front_side_ptz'),
    "doorbell_lite": ('armcrest', 'g5_bullet', 'rear_ptz'),
    "front_door_aerial": ('front_side_ptz', 'hot_tub', 'madrone_g6_entry', 'rear_ptz'),
    "front_side_ptz": ('back_yard', 'front_door_aerial', 'g5_bullet', 'hot_tub', 'madrone_g6_entry', 'rear_ptz', 'reolinkstudybporchptz', 'utilities_ptz'),
    "g5_bullet": ('armcrest', 'doorbell_lite', 'front_side_ptz', 'madrone_g6_entry', 'rear_ptz'),
    "hot_tub": ('armcrest', 'front_door_aerial', 'front_side_ptz'),
    "madrone_g6_entry": ('front_door_aerial', 'front_side_ptz', 'g5_bullet', 'rear_ptz', 'utilities_ptz'),
    "pool_equipment": ("rear_ptz",),
    "rear_ptz": ('doorbell_lite', 'front_door_aerial', 'front_side_ptz', 'g5_bullet', 'madrone_g6_entry', 'pool_equipment', 'utilities_ptz'),
    "reolinkstudybporchptz": ('armcrest', 'front_side_ptz'),
    "utilities_ptz": ('front_side_ptz', 'madrone_g6_entry', 'rear_ptz'),
}
```

## Sanity check: 2026-08-02 walker sequence

The clearest single-walker traversal on 2026-08-02 is 14:21–14:23 local:

| t | camera |
|---|---|
| 14:21:25 | g5_bullet |
| 14:21:28 | rear_ptz |
| 14:22:24 | rear_ptz |
| 14:22:48 | front_side_ptz |
| 14:23:11 | front_side_ptz |
| 14:23:35 | front_side_ptz |
| 14:23:36 | utilities_ptz |

Hops: g5_bullet→rear_ptz (3 s), rear_ptz→front_side_ptz (24 s), front_side_ptz→utilities_ptz (48 s). Under the proposal: rear_ptz↔front_side_ptz and front_side_ptz↔utilities_ptz are strongly adjacent; **g5_bullet↔rear_ptz has exactly 3 filtered observations** — it clears the threshold, but only just; treat it as marginal and worth an operator glance. All three walker hops are proposed-adjacent — sanity check PASSES.

## Thin pairs — OPERATOR-CONFIRM (<3 observations, NOT proposed)

- back_yard ↔ hot_tub — 2 filtered obs
- armcrest ↔ pool_equipment — 1 filtered obs
- armcrest ↔ rear_ptz — 1 filtered obs
- g5_bullet ↔ utilities_ptz — 1 filtered obs
- doorbell_lite ↔ madrone_g6_entry — 1 filtered obs
- back_yard ↔ rear_ptz — 1 filtered obs
- rear_ptz ↔ reolinkstudybporchptz — 1 filtered obs
- g5_bullet ↔ reolinkstudybporchptz — 1 filtered obs
- doorbell_lite ↔ front_side_ptz — 1 filtered obs
- hot_tub ↔ madrone_g6_entry — 1 filtered obs

Operator should confirm from physical layout whether any of these are genuinely adjacent (data too thin to decide), and whether any high-count pair is a two-person artifact rather than a walkable hand-off (e.g. utilities_ptz↔madrone_g6_entry: are these physically contiguous?).

## Limitations & open questions
- **7-day retention only.** The recorder purges; a longer baseline would firm up thin pairs. The URA DB has NO frigate/perimeter event tables (checked `.tables` — occupancy/zone tables are interior), so no richer label data was available.
- The simultaneity filter is heuristic (see Method). Pairs whose raw count vastly exceeds filtered (e.g. many were halved) were dominated by concurrent activity — treat their ranking with care.
- Directionality is discarded (graph is symmetric); the linker only needs adjacency.
- No pool_equipment↔hot_tub or back_yard↔pool_equipment edges emerged despite plausible physical adjacency — pool_equipment's 93 weekly events co-fire mainly with rear_ptz. Worth an operator look: is pool_equipment's person detector picking up pool service activity that never crosses other cameras?

---

## Operator ratification (2026-08-06)

Ratified with corrections. Physical truth overrides transition counts in
both directions:

1. **back_yard ↔ hot_tub: CONFIRMED adjacent** (data was thin at 2 obs;
   operator confirms).
2. **Pool service chain declared** (explains the pool_equipment oddity):
   service enters via rear_ptz and/or g5_bullet → picked up by the pool
   overhead camera (armcrest — operator CONFIRMED 2026-08-06) and back_yard → traverses
   hot_tub → then pool_equipment. Edges added: rear_ptz↔armcrest,
   rear_ptz↔back_yard, g5_bullet↔armcrest, g5_bullet↔back_yard,
   armcrest↔hot_tub, back_yard↔hot_tub, hot_tub↔pool_equipment.
3. **pool_equipment ↔ rear_ptz: REMOVED** (6 obs were missed-intermediate
   artifacts of the chain above, not direct adjacency).
4. **rear_ptz ↔ utilities_ptz: REMOVED** (17 obs; physically impossible
   directly — back route runs through the pool chain, front route
   through front_side_ptz).

Accepted residual (recorded): removed-but-co-firing pairs mean a missed
intermediate detection splits a real track into two threads —
over-alerting, the safe direction. If splits at these seams recur, fix
camera detection reliability, do NOT re-add false edges.

RATIFIED GRAPH (paste target for EXTERIOR_ADJACENCY_GRAPH; symmetrize in
code): all probe-proposed pairs EXCEPT the two removals above, PLUS the
chain edges in (2).
