# Review B: NVR witness W1 pairing (cross-coordinator ripple, forward trace, restart)

Branch `feature/nvr-witness-w1-pairing` @ d450c382. Diff base `git merge-base develop HEAD` = 4b825c50 (verified;
three-dot diff touches only `camera_resolver.py` + docs + tests). Plan `PLANNING_nvr_witness_layer.md` §5 / W1.

Read completely first: `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`, `SENSOR_FLEET_CLASSES.md`,
`IDENTITY_FUSION_CAMERAS_MANUAL.md`, and (because the brief names HVAC as a trace target)
`HVAC_ARCHITECTURE_STATE_OF_PLAY.md`. Nothing in any corrections ledger is re-asserted here.

Identity model: W1 changes the camera-pairing input under F3 (door crossing: transit egress legs, crossing
confidence) and F4 (person-sighting picks and their canonical camera key). It produces no identity fact. F1, F2
(census counts) and F5 are unchanged; see the trace below.

**Verdict: SHIP.** No CRITICAL or HIGH. One MEDIUM (an undocumented F3 behaviour change on the garage door) and
three LOWs. The MEDIUM is a README correction plus, at the operator's option, an existing-class card. It does not
need a code fix in this cycle.

## Method

- Live registry fixture (`quality/tests/fixtures/nvr_w1_live_registry_shape.json`): for every enabled camera,
  `resolve_operator_declaration`, `canonical_camera_key` and `resolve_detection_legs` (person, vehicle, animal),
  with the knob on and off, flipping the module global at call time.
- Live config read from `.storage/core.config_entries` over the Samba mount: egress, interior and perimeter lists,
  door groups, door neighbours, zone-camera picks, room cameras.
- Live data: 14 days of `person_entry_exit_events` and 7 days of recorder `on` onsets for garage_a Frigate, garage_a
  Protect and the four garage_a door neighbours (read-only `ssh ha sqlite3 -readonly`). A direction replay used the
  production rule (`_resolve_direction`: per-camera first match, closest across cameras, entry window 45 s, exit
  window 30 s).
- Targeted tests: `test_interior_paths`, `test_person_sighting*` (3 files), `test_egress_direction_aware`,
  `test_transit_protect_sourced`, `test_nvr_witness_w1_resolver`: 127 passed.
- `git merge-tree` against `feature/camera-input-stream-health-s1`: clean.

What the resolver output does on the fixture, knob on vs off: seven fusions gain the Protect source (basis
`frigate_object_name`). Each candidate Protect device hosts only its own camera's three resolution channels and one
person sensor, so the F1 multi-camera bleed cannot happen on this house. Canonical keys change for `rear_ptz_2`,
`stairs_top_2` and `upstairs_hall_2`. Detection legs change for one camera only: `camera.foyer_fisheye` gains
`binary_sensor.foyer_fisheye_person_detected`. foyer_fisheye is not a perimeter camera, and only
`perimeter_alert._resolve_legs` calls `resolve_detection_legs`, so nothing reads that change.

## Forward trace per consumer (live config)

| Consumer | Reads | W1 effect live | Verdict |
|---|---|---|---|
| Transit `EgressDirectionTracker` egress subscription (`transit_validator.py:1093`, via `camera_census.resolve_cross_platform_sensors` :857) | `CONF_EGRESS_CAMERAS` = madrone_g6_entry, doorbell_lite, front_door_aerial, garage_a_2 | `binary_sensor.garage_a_person_detected` joins `_egress_entities`. It is NOT in the garage_a door neighbours (`camera_protect_garagehallway_person_detected`, `staircase_person_occupancy`, `garage_hallway_camera_person_detected`, `stairs_top_person_occupancy`), so the door cannot confirm its own direction. Stems match (`garage_a` for all three garage_a legs), so `_count_platforms_fired` (:2689) now reaches 2 and directed crossings score 0.9. See B-M1 for the new rows. | MEDIUM B-M1 |
| `TransitValidator` path-validation subscriptions (:546) | same egress list | one more subscribed sensor, garage_a Protect, used only as a transition sighting | inert |
| Crossing face/identity attach (`_resolve_egress_face_identity_ex`) | stem of the egress camera | Protect leg has stem `garage_a`, the same face legs as the Frigate leg | unchanged |
| Census counts and `_cross_validate_platforms` (`camera_census.py:2148`, :2330) | `resolve_configured_cameras` (:720, same-device only; via `_get_integration_camera_list` :2616) | none. The census count path never calls the resolver. Frigate and binary platform counts, agreement and the divergence downgrade are unchanged. | holds |
| Census egress union (register on entry, evict on exit) | `ura_person_egress_event` with `person_id` | only via B-M1's extra rows, and only when a face attaches | LOW, inside B-M1 |
| Upstairs Hallway fused sensor (`binary_sensor.py:1591-1886`) | `room_cameras` = `camera.upstairs_hall_2` | two sources now. `is_on` is the OR of both, so a Protect-only detection reads on. Agreement can be `split`. | display; see fan veto |
| fan_veto camera rebuttal (`fan_veto.py:424-441`) | that fused sensor's `agreement` / `confidence` | Frigate on with Protect off is now `split`, so the rebuttal is denied (before: `single_source`, granted). Upstairs Hallway has `room_fan_mode: off` and no fan, and the veto only runs in AWAY/VACATION. | inert live (LOW B-L3 for other installs) |
| Room occupancy, lights, HVAC | — | The fused sensor is not a room input: Upstairs Hallway uses `motion_sensors` ZV + `presence_sensors` panel radar. No `hvac*.py` file references cameras, `camera_person` or the resolver (grep). | unchanged |
| Person sightings picks (`person_sighting.py:300-345`, :503) | Upstairs: `upstairs_hall_person_occupancy_2`, `playroom_person_occupancy_2`, `stairs_top_person_occupancy`; Entertainment: `foyer_fisheye_person_occupancy`, ... | fusions gain the Protect device. `face_name_entities_for_device` on a Protect device returns nothing (Protect exposes no face-name entity, manual §1.1), so the subscribed faces are unchanged. The canonical key changes for upstairs_hall and stairs_top; it is RAM-only (debounce and last-sighting store), rebuilt at rebind. Egress copy (c) keys garage_a by `canonical_camera_key` = 7c45 from either leg. Before W1, a Protect and a Frigate pick of the same upstairs camera got different keys; now they get one. | holds (improves) |
| Interior path map (`transit_validator.py:2387-2430`) | example file names only Frigate entities (`camera.garage_a_2`, `stairs_top_2`, `upstairs_hall_2`, `foyer_fisheye`) | keys are derived live at load, never persisted; `test_interior_paths` passes | holds |
| Perimeter legs (`perimeter_alert.py:2341`) | `resolve_detection_legs` | identical for every perimeter camera (rear_ptz HR, utilities_ptz HR, garage_b_2, ...): the device set was already reached by the `_N`-stripped stem bridge (`camera_resolver.py:1239-1256`) | holds; builder's claim verified |
| Camera auto-enable scan (`__init__.py:638`) | room fusions | three more person switches enter the would-enable list; dry run only (`CAMERA_AUTOENABLE_DRY_RUN` True); face switches are inventory only | inert |
| Stream health S1 (`own_camera_entity_for_input`, other branch) | a static method on the entity registry, no shared index | no shared state; textual merge clean | holds |

**AWAY / house state.** No reachable path. Inference reads census counts (unchanged path), zone occupancy (the fused
sensor is not a room input) and person trackers. The one indirect path is the egress union: a split exit with a
face attached could evict an identity its own entry registered seconds earlier. That lowers `identified_count`, but
the body stays in the camera total, so `unidentified_count` rises and path alpha is blocked. Nobody-home needs
census 0 and no occupied zone, and a person who just came in from the garage trips the Back Hallway zone. GUEST
follows the night-stay latch over DB nights, so it never reads this.

## Findings

### B-M1 (MEDIUM): garage_a gains a third egress leg; extra crossing rows and notifications are not in the README
Class: computed-but-not-consumed in reverse (an unaccounted new consumer path, #53), plus the existing
direction-keyed-dedup split.
`transit_validator.py:2118-2160`: each egress leg schedules its own `_resolve_direction`, and the dedup key is
`group|direction` (`DOOR_STEM_DEDUP_S` 30). Two legs of one crossing that resolve to different directions both emit.
That already happens on dual-leg doors (14 days: 28 opposite-direction pairs within 30 s inside one door group,
e.g. 11-05 13:26:42 exit `garage_a_person_occupancy_2` then 13:26:59 entry `doorbell_lite_person_detected`). W1 adds
`garage_a_person_detected` as a new trigger on the busiest door.
Replay over 7 days of recorder onsets (98 Frigate, 89 Protect): 76 crossings have both legs within 30 s
(lag p10/p50/p90 = -9.9 / +0.3 / +5.3 s). In 71 they resolve to the same direction and dedup collapses them. 2 split
exit/entry, which adds an opposite-direction row and a "Someone arrived/left" notification. 3 have one leg
ambiguous: an extra bus event, no DB row, no notify. 17 Protect onsets have no Frigate onset within 30 s; they become
NEW directed crossings (7 entry, 5 exit, 5 ambiguous), either real Frigate misses or Protect false positives.
The README says only "confidence 0.9". Fix: add the expected new-row rate (~12 new directed rows per week, ~2 split
pairs) to the README's live section, so the live check can tell a fault from expected behaviour. The split is
pre-existing and design-level (direction-keyed dedup, review B3 of the census-inputs cycle). Card it or adjoin an
existing dedup card. No code change in W1.

### B-L1 (LOW): a device rename is not seen by most consumers until restart
Class: stale cache across a registry update. The W1 index is built in `CameraResolver.__init__`
(`camera_resolver.py:729-735`) from device names. The census resolver is marked dirty on DEVICE and ENTITY registry
updates (`camera_census.py:515-518`), so person sightings (rebind on resolver identity) and the path map follow a
rename. Three consumers do not:
- `EgressDirectionTracker` subscribes once in `async_init` and has no registry listener.
- `TransitValidator`'s rescan (`transit_validator.py:405-419`) fires only on ENTITY updates of `unifiprotect`
  entities, never on a device rename.
- The room fused sensor builds its own resolver at add, at HA start and on room lifecycle.

Repro: rename the Protect device "Garage A" to "Garage A Door" in the UI. The census resolver loses the pairing
(the slug no longer equals `garage_a`), transit keeps the Protect leg until restart, and after the restart garage_a
silently returns to a single leg with no log or trip-wire. Direction: fails toward the pre-W1 behaviour, so it is
safe, but silent. Boot is safe: the registry loads from storage before integrations set up. Suggest one INFO line
per accepted `frigate_object_name` pairing at resolver build, so a lost pairing shows in the log.

### B-L2 (LOW): a W1 sibling is scanned without the F1 stem filter
Class: inherited guard gap. `device_stems` covers input devices only (`camera_resolver.py:1009`, :1119), so a
sibling Protect device is scanned unfiltered. On a multi-camera Protect device (the staircase + garagehallway shape
in manual §5 F1), `_prefer_canonical` could take the other camera's person sensor. The rung-5 stem siblings have the
same exposure. Not reachable here: all seven candidates are single-camera devices (fixture). Portability note only.

### B-L3 (LOW): a second source turns a granted fan-veto rebuttal into a denied one
`fan_veto.py:436-441`. In a room whose only camera was Frigate, a Frigate-only `on` used to be `single_source` and
was granted. Now it is `split` (Protect off) and denied. That is the doctrine working as designed (a dissenting
second witness), but it changes AWAY-state comfort-fan behaviour wherever W1 pairs a room camera. Live it is inert:
only Upstairs Hallway is affected, and it has no fan. Name it in the README's consumer table.

## Cleared

- No untracked tasks, timers or listeners added; W1 is pure and synchronous at construction and per resolve.
- Knob off: the W1 block is skipped and the extra index is unused, byte-identical (builder's golden test, and my
  knob-off diff matches develop).
- No change to F2 collapse, face tri-state or face auto-enable: no face switch is touched; face capability on the
  Protect siblings reads `absent`.
- Live acceptance criterion ("garage_a crossing at confidence 0.9") discriminates: the replay predicts about 71 per
  week.

## Checklist

| Item | Result |
|---|---|
| garage_a egress subscription + 0.9 confidence | PASS (plus B-M1 extra rows) |
| Other doors | unchanged (doorbell_lite / madrone / front_door_aerial fusions unchanged) |
| Upstairs Hallway fused sensor / fan veto / occupancy / lights / HVAC | display change; fan veto inert live; no occupancy or HVAC path |
| Person sightings (Upstairs, Entertainment) | PASS; keys unified, faces unchanged |
| Census counts, cross-validation, guest | unchanged (no resolver on the count path) |
| Perimeter legs | unchanged (verified) |
| Stream health S1 | no conflict |
| Restart | boot safe; rename not tracked by transit or the fused sensor (B-L1) |
| AWAY / house state | no reachable path |

Must-fix before ship: none. Recommended in-cycle: the B-M1 README rows and the B-L3 README row; the B-L1 INFO log
(2-5 lines).
