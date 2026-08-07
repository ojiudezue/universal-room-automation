# AUDIT — Resolver Ground-Truth (hand-built fixture) — RESACC-1

**Date:** 2026-08-07 · read-only pull of live `core.entity_registry` + `core.device_registry`.
**Doctrine:** hand-build the mapping BY HAND once, against live values, commit it as the
acceptance fixture the resolver-accuracy suite (RESACC-1) diffs against. This is the ground
truth; `resolve_detection_legs()` / `resolve_operator_declaration()` output is measured against it.

**Scope of raw data:** 86 detection binary_sensors (person/vehicle/animal across
`_person_occupancy` frigate · `_person_detected` unifiprotect · bare `_person/_vehicle/_animal`
reolink · `_smart_motion_human/_vehicle` dahua). URA's own `*_camera_person_detected`
(`platform=universal_room_automation`, the D3 fused OUTPUT) are excluded — they are the
resolver's product, not an input leg.

## Ground truth — physical cameras with >1 engine (the fusion targets)

For each physical camera: the legs that MUST resolve to it (recall), and nothing else (precision),
plus the **canonical room**. "camera-key" is the normalized stem after
`EXTERIOR_CAMERA_KEY_ALIASES`.

| camera-key | engines (legs) | canonical room | notes |
|---|---|---|---|
| **armcrest** (pool overhead) | frigate `armcrest_person_occupancy`, frigate `armcrestash41b_person_occupancy` (**F1**), dahua `armcrestpooloverhead_smart_motion_human/_vehicle` | **pool** | 3-name / 3-source, one camera. See A-1, A-2. |
| back_yard | frigate `_person_occupancy`, protect `_person_detected` | outside_perimeter | frigate area=None (A-3) |
| hot_tub | frigate, protect | outside_perimeter | frigate area=None |
| pool_equipment | frigate, protect | outside_perimeter | frigate area=None |
| front_side_ptz | frigate, protect | outside_perimeter | frigate area=None |
| g5_bullet | frigate, protect | outside_perimeter | frigate area=None |
| rear_ptz | frigate, protect | outside_perimeter | frigate area=None |
| front_door_aerial | frigate, protect | front_porch | agree |
| doorbell_lite | frigate, protect | garage_a | frigate area=None (A-3) |
| madrone_g6_entry | frigate, protect (+ frigate `_package_*` EXCLUDED) | (unset) | both area=None |
| reolinkstudybporch | frigate `reolinkstudybporchptz_person_occupancy`, reolink `ptzcamreolinktmixpstudybporch_person/_vehicle/_animal` | patio | frigate area=None; reolink carries full family |
| foyer_fisheye | frigate, protect | entry_way | agree |
| family_room | frigate, protect | living_room | agree |
| garage_a | frigate, protect | garage_a | agree |
| garage_b | frigate, protect | garage_b | agree |
| master_hallway | frigate, protect | master_hallway | agree |
| playroom | frigate, protect | game_room | agree |
| stairs_top | frigate, protect | stairs | agree |
| upstairs_hall | frigate, protect | upstairs_hallway | agree |

Single-engine cameras (frigate-only interior person_occupancy, protect-only, etc.) resolve
trivially to their own stem; they are correct by construction and not re-listed here — the
accuracy risk lives entirely in the multi-engine fusion set above.

## Accuracy findings the resolver MUST get right (and RESACC-1 must assert)

**A-1 — armcrest is a 3-source, 3-name single camera.** F2-frigate `armcrest`, **F1-frigate
`armcrestash41b`** (the F1 host still live pre-sunset), and dahua `armcrestpooloverhead`. All the
same physical pool-overhead camera. The resolver must collapse ALL THREE to camera-key `armcrest`
(via `EXTERIOR_CAMERA_KEY_ALIASES` + the F1/F2 stem-collapse). **`armcrestash41b` is NOT currently
in the alias map** — verify it collapses via the F1/F2 disambiguation path, or it's a missed leg
(recall failure) AND, post-F1-sunset, a dangling reference. Ties directly to F1-SUNSET.

**A-2 — armcrest area conflict.** dahua leg area=`balcony`, frigate legs area=`pool`. Same camera,
two rooms. The resolver's room attribution must pick ONE canonically (pool is correct — it's the
pool overhead; `balcony` is a mis-set area on the dahua device). A resolver that takes "first
leg's area" is non-deterministic here.

**A-3 — Frigate exterior legs carry area=None; the Protect sibling carries the real area.** Every
exterior perimeter camera (back_yard, hot_tub, pool_equipment, front_side_ptz, g5_bullet, rear_ptz,
doorbell_lite) has `area=None` on its Frigate device but `outside_perimeter`/real-area on its
Protect device. If the resolver attributes room from the Frigate leg alone, **all exterior cameras
have no room** — degrading census/transit room mapping. Room attribution must fall back across
legs (prefer a non-None area) or use the `camera.*` entity's area. **This is the single highest-
impact accuracy bug in the current data.**

**Registry hygiene (not the resolver's fault, but affects area-based truth):** area_id typos
`guest_bedroom_1_clo_set`, `guest_bedoom_2_bath` — flag for operator registry cleanup.

## How RESACC-1 uses this

- **Recall test:** for each camera-key above, `resolve_detection_legs(camera, family)` must return
  a superset of the listed legs (a missing leg = lost corroboration/alert).
- **Precision test:** it must return NO leg belonging to a different camera-key (armcrest vs
  armcrestash41b vs the interior `staircase`/`stairs_top` near-miss, etc.).
- **Room test:** canonical room must match the table (A-2/A-3 are the failing cases to pin).
- **Adversarial near-miss:** `armcrest` vs `armcrestash41b`, `stairs_top` vs `staircase`,
  `back_yard` vs `back_yard`-substring interior — assert no bleed.
