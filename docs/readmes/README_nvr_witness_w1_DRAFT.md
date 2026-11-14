# NVR witness W1: Frigate object-name pairing in the camera resolver (DRAFT)

Card NVR-WITNESS-CONSOLIDATION-1. Plan `docs/planning/PLANNING_nvr_witness_layer.md` §5, §8 W1. Tier 2-DB.
Branch `feature/nvr-witness-w1-pairing`. Version to be assigned at deploy.

## What changed

`CameraResolver.resolve_capabilities` gains one acceptance path. For each Frigate input device it reads the Frigate
object name from the device's Frigate identifier (`(frigate, "<instance>:<object>")`, via the existing
`_frigate_object_name_for_device`) and compares it with HA's `slugify` of each camera device's registry name
(`name_by_user`, else `name`). No entity_id is parsed for this. The sibling is accepted only when all four hold:

1. the input device is Frigate and its object name equals the candidate's slugified registry name;
2. exactly one non-Frigate device that owns an enabled `camera.*` entity carries that slug;
3. no other Frigate device has that object name;
4. the candidate device has no Frigate identifier of its own.

Accepted sources carry `correlation_basis = "frigate_object_name"` (visible on the room fused sensor's per-source
attributes). Knob `camera_resolver.RESOLVER_FRIGATE_OBJECT_NAME_EVIDENCE` (rung 1, default True; False = the develop
resolver, byte-identical, tested over all 105 live cameras).

Residual, accepted in the plan: one Protect camera and one Frigate camera with the same name, and no other camera of
that name, pair even if they are two physical cameras. The registry cannot tell that apart from a true pair
(`test_resolver_residual_one_name_one_camera_each_side_pairs`).

## Effect on this house (measured against the live registry, 2026-11-13)

The plan expected one change (garage_a). The live registry gives seven: every Frigate camera whose HA camera entity
did not share a stem with its Protect sibling. The operator accepted all seven pairings on 2026-11-14.

| Frigate camera | Gains Protect source | Fusion key | Live consumer reached |
|---|---|---|---|
| `camera.garage_a_2` | `binary_sensor.garage_a_person_detected` | unchanged (`7c45...`) | transit egress subscription (via census `get_transit_egress_entities`) |
| `camera.upstairs_hall_2` | `binary_sensor.upstairs_hall_person_detected` | `b75c...` → `b063...` | Upstairs Hallway room fused sensor (→ fan veto); person sightings `Upstairs` pick |
| `camera.stairs_top_2` | `binary_sensor.stairs_top_person_detected` | `ebc6...` → `74f1...` | person sightings `Upstairs` pick (`binary_sensor.stairs_top_person_occupancy`) |
| `camera.foyer_fisheye` | `binary_sensor.foyer_fisheye_person_detected` | unchanged | person sightings `Entertainment` pick; its detection legs gain the Protect leg (not a perimeter camera) |
| `camera.rear_ptz_2` | `binary_sensor.rear_ptz_person_detected` | `c887...` → `c62c...` | none live (perimeter configures the Protect entity, which already paired) |
| `camera.utilities_ptz_2` | `binary_sensor.utilities_ptz_person_detected` | unchanged | none live (same) |
| `camera.garage_b_2` | `binary_sensor.garage_b_person_detected` | unchanged | perimeter leg set unchanged (see below) |

**Expected rates (review B-M1).** garage_a gains a third egress trigger (the Protect person sensor). Expect about
12 new directed crossings a week from Protect-only detections, and about 2 a week where Frigate and Protect fire in
opposite directions, giving one extra crossing row and one extra arrived/left notification. This split already happens
on the two-leg doors (28 such pairs in 14 days), so it is not new behaviour, only a new door. The proper fix is the
shared corroboration in W2, not a W1 change.

**Fan-veto consumer (review B-L3).** The Upstairs Hallway room fused sensor gains a second source. A second source
can make the room read split, and the fan-veto rebuttal is denied in AWAY / VACATION. Inert today: there is no fan in
Upstairs Hallway.

Unchanged, by test: census `get_transit_interior_entities` (the camera-person list already names the Protect cameras;
the merge dedups), transit `_path_map_context` door and exterior keys, every other camera's fusion, picks and legs.

**Perimeter Part A legs do NOT change.** The plan (§5, plan review 1 M1) says W1 changes shipped perimeter Part A input for garage_a.
Measured: it does not. Perimeter takes its legs from `resolve_detection_legs`, which on develop already reaches
garage_a's Protect leg through its own `_N`-stripped stem bridge (`camera_resolver.py` `resolve_detection_legs`,
`candidate_stems` loop). The leg sets of every live perimeter camera and of `camera.garage_a_2` are identical with the
knob on and off (`test_perimeter_resolve_legs_unchanged`). So W1 does not change perimeter `families_live` or
AgreementTracker samples on this house. (That stem bridge is itself a name guess; it belongs to REGISTRY-NOT-NAMES-1.)

## Tests

`quality/tests/test_nvr_witness_w1_resolver.py` (21), helper `quality/tests/_nvr_w1_registry.py`, fixtures
`quality/tests/fixtures/nvr_w1_live_registry_shape.json` (live registry extract) and
`nvr_w1_resolver_golden_develop.json` (develop 4b825c50 resolver output over that fixture). Every condition, the
knob, the call site, the slug function, the `name_by_user` precedence and the camera-device gate are mutation-anchored.
Fix-up: the once-per-pairing INFO log (B-L1) and slugify-import fail-closed (C-1) each have a RED-on-mutation test.

## Live validation (prospective)

- **Live:** within a day, a `person_entry_exit_events` row with `egress_camera = binary_sensor.garage_a_person_detected`,
  or a garage_a crossing with `confidence = 0.9` (Frigate and Protect both fired). Before W1 garage_a scored 0.9 on
  0 of 71 crossings in 14 days. A subscription fault would pass the resolver tests and show no such row, so this
  discriminates.
- **Live:** `binary_sensor.upstairs_hallway_camera_person_detected` (room fused sensor) lists two sources, one with
  `correlation_basis: frigate_object_name`.
- **Live:** no other camera's pairing changes beyond the table above: the fused sensor attributes of Living Room,
  Game Room and Study A list the same sources as before.
- **Live:** one INFO line `Frigate object-name pairing accepted` per accepted pairing after restart (seven expected).
- **Live:** no WARNING / ERROR from `camera_resolver` or `camera_census` cutover after restart.
