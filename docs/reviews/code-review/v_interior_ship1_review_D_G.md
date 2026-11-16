# Interior vision ship 1: review D (adversarial completeness) and G (goal fidelity)

Branch `feature/interior-vision-d1` at 9931a001, worktree `.claude/worktrees/builder-interior-d1`, diff base `develop...HEAD`.
Plan: `docs/planning/PLANNING_vision_interior_sightings.md` (ship 1 = D1, the D5 no-model leg, D7 trip-wires).
Before reviewing, I read `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` and `SENSOR_FLEET_CLASSES.md` in full. Nothing in the §10 ledger is re-asserted here.
Live facts were checked read-only against the Samba-mounted `.storage` and `interior_paths.json`. The builder's D0(a) probe (`scripts/probes/interior_vision_d0a.py`) and a scratch root-key probe were used. Nothing in HA was called and nothing in the repo was written apart from this file.

**Verdict: FIX-REQUIRED.** There is no CRITICAL or HIGH finding. Three MEDIUM findings would make the ship-1 live acceptance pass while D5 delivers mostly empty paths on the main door, and would let a stuck camera show up as an unnamed person.

## Findings

### D-M1 (MEDIUM): on the live garage_a chain the first inward node is blind, and its children's windows open too late (#53, one missed site)
- Code: `person_sighting.py` `_ensure_interior_groups` builds groups only from `census.interior_camera_entities()`. `interior_vision.chain_windows` sets `t_of[v] = w["close"]` for an unseen node, so the child window opens at the parent's CLOSE.
- Live map (`interior_paths.json` garage_a): `garage_a_2 -> staircase_2 (63 s) -> stairs_top_2 (72) -> playroom (67) / upstairs_hall_2 (84)`, and `staircase_2 -> family_room (85)`.
- D0(a) probe on the live registry: the `staircase_2` device `02a52ec4...` is in no interior group. Its person sensor `binary_sensor.staircase_person_occupancy` is zone-only and not in the census interior list (audit `AUDIT_v5_108_25_watched_set_2026_11_15.md` §2). The only staircase group is the Protect `camera.staircase_high_resolution_channel` (`43f04c97...`, garage_hallway), which is no path node (`path_node False`). So the staircase can never be a hop, and the Garage Hallway room never gets `entered_via`.
- **Repro (pure, run on the branch):** use the live garage_a edges, with an entry at E, a stairs_top on-edge at E+50 and a playroom on-edge at E+110. The windows are T `[63, 135]`, P `[135, 202]`, U `[135, 219]`, F `[63, 148]`, and the result is **zero hops**. With stairs_top at E+70 it works. Every garage_a entrant who reaches the top of the stairs in under 63 s gets an empty path record.
- Fix: register the on-edge listener on every path-map node that has a person leg (registry-resolved: device → person binary sensor), not only on census-interior members, or open an unseen node's child window at the parent's OPEN (`[open_u, close_u + window_s]`). The plan's cumulative-window rule (§9.D5, closure N6) has this defect too, so amend the plan with the fix.

### D-M2 (MEDIUM): the `interior_path_zero` trip-wire and the ship-1 Live criterion are hollow (#62 / #53)
- Code: `_path_tick` always emits a `PathRecord` once a window closes, `hops=()` included, and `_emit_unnamed("path")` appends `_iv_paths_written`. `_check_interior_tripwires` fires only when mapped entries ≥ 3 and no path was written.
- The real failure modes produce zero-hop records: D-M1, an unbound on-edge listener, a key mismatch between group and path node, or an empty ring. A zero-hop record silences the trip-wire. The plan's Live check "≥ 1 `interior_path` row after an entry on a mapped door" also passes on an empty path.
- **Repro:** neuter `_bind_onedge_listener` (return early), then make 3 garage_a entries in 24 h. You get 3 `interior_path` rows with `hops: []`, `n: None`, and no page.
- Fix: count only paths with ≥ 1 hop as written for the trip-wire, count `paths_zero_hop` in diagnostics, and change the Live criterion to "≥ 1 row with ≥ 1 hop".

### D-M3 (MEDIUM): a census-discounted stuck Frigate count still reaches the record (INV "no held, frozen or dead reading reaches a record")
- Code: `camera_census.py:2097` calls `_remember_reading(entity_id, count)` BEFORE the Stuck-Signal D1 discount `continue` at `:2105`. `area_evidence()["by_entity"]` copies `_stream_last_reading`. `group_bodies_nvr` checks only stream liveness, so a stuck-but-streaming camera is LIVE.
- **Repro:** a Frigate interior camera (e.g. the playroom count sensor) is stuck at `person_count = 1` with no interior corroboration, so the watchdog adds it to `_watchdog_discounted_cameras`. The census then excludes it, but the Game Room record reads `bodies 1`, `unnamed 1`, `unnamed_present`, and `sensor.ura_interior_awareness` counts it for as long as the stuck count lasts. This is the phantom-guest display the operator would see.
- Fix: expose the discounted set in `area_evidence` (e.g. `discounted`) and treat a discounted member as not LIVE (a new class, `stuck`). Pin it with a test.

### D-L1 (LOW, latent INV-IV-DEDUP): two groups in one room double-count on the sensor
- `InteriorAwarenessSensor.native_value` sums `unnamed` over all records. `rooms` is keyed by `str(r.room)`, so the second record overwrites the first. Two groups in one area (two physical cameras in the Living Room) give two records, each with `unnamed = bodies - |named|`. One guest seen by both cameras counts as state 2.
- This is not reachable live: D0(a) found 7 groups in 7 areas. The "two groups per area" stop is a build-time probe only, with no runtime guard, and the operator's portability rule applies. Fix: merge records per room (max of bodies, one union of named), or count and skip the extras.

### D-L2 (LOW): the group rebuild ignores room config changes, which matters for ship 2's INV-IV-SCOPE
- `_interior_sig = (interior list, id(resolver))`. A room-type change to `bedroom`/`bathroom`, or a room area change made through options, fires no registry event, so the group stays recorded until the next registry update or restart. Ship 1 makes no model call, so the only effect today is a stale display. Fix before ship 2: add the room map (or the lifecycle signal) to the signature.

### D-L3 (LOW, portability): the `interior_room_records_zero` HIGH page can false-fire
- The numerator counts any LIVE census interior entity with a reading > 0, including cameras dropped as `excluded_room_type` or `no_room`. **Repro:** an install whose interior cameras are all in bedroom-typed rooms, or in areas with no URA room. Then there are no groups and no records, the camera sees people on 20 ticks, and a HIGH page fires with nothing broken. Fix: count only entities that are members of a built group.

### D-L4 (LOW): stale docs
- `PersonSightingProducer.async_setup` docstring says "INV-NOOP: with FACE_SIGHTING_ENABLED False nothing is registered", but `_setup_interior` now registers the timer before that return (by design: the records are independent).
- The plan and docstring put `sensor.ura_interior_awareness` on the "Census device". The class inherits the Whole House device from `AggregationEntity`.

## Cleared (holds because)
- **INV-IV-AWAY:** the presence diff adds two getters and a diagnostics key only. The census diff adds `area_evidence` (a copy, no arithmetic). Nothing touches `_run_inference`, `_handle_census_update`, `_periodic_inference` or `_handle_geofence_change`. The build runs on the producer's own `async_track_time_interval`.
- **INV-IV-NO-TRUST:** a repo grep finds `get_room_sightings` / `get_last_path_records` read only by `sensor.py` InteriorAwarenessSensor and the presence delegates. `RoomSighting` / `PathRecord` are constructed only in `_emit_unnamed`.
- **INV-IV-MISSING:** `group_bodies_nvr` reads LIVE members only. No LIVE member, or no reading, gives `bodies None` and `missing`, never 0. A held or released member's frozen value is skipped. Residual (pre-existing, 3b D-L1): during the 0-120 s grace a dead camera's sensor counts as LIVE.
- **No new listener:** the only listener is a state listener on group member sensors (plan §9.D1). Crossings are pulled through `get_crossings_since`. There is no channel listener and no send on `SIGNAL_PERSON_SIGHTING`.
- **Cursor double-read and miss:** `_record_crossing` stores `ts` = event time, and resolution runs after a fixed `ENTRY_WINDOW_SECONDS` with no await before the store (`transit_validator.py:1649-1720`, `:2373-2530`), so records arrive in `ts` order. The `ts == cursor` tie is guarded by the source_ref set. Door dedup is upstream (`DOOR_STEM_DEDUP_S`).
- **Door root key:** `_egress_key` on the live egress sensors (`binary_sensor.garage_a_person_occupancy_2`, the `sensor.*_person_count` sensors) resolves to the same device key as `camera.garage_a_2` and the front anchors (scratch probe).
- **One placement per slug:** `get_room_occupants` matches one exact location per person. `ble.setdefault` keeps one room, `place_named` gives BLE precedence over faces, and faces take the newest sighting per slug (`_last_sightings` keyed by person). Face slugs come from census `tracked_person_slugs`, the same rule as `person_ids.slug_of`.
- **Registry, never names:** groups are resolved through `camera_device_for_entity`, `pure_twin_groups` / `twin_pair_for_device`, `resolve_area_id_for_entity` (entity, else device) and `frigate_member`. Ship 1 never uses the camera manager's entity-only area map, so the audit's empty area-keyed lookups do not affect it. `area_evidence()["area_contributions"]` (keyed wrong live) is exposed but never read for a record.
- **Protect-only staircase group:** `still_source None`, counted `no_still_source` and still recorded (no model in ship 1). It is the D-M1 blind node from the other side.
- **Rooms with Automation off (21):** nothing in ship 1 reads the room switch or the room coordinators. `_room_entries` reads config entries and `persons_in_room` reads person-coordinator data.
- **Room rename:** the options flow writes `CONF_ROOM_NAME` to entry.data too (`config_flow.py:12532-12575`), so `_room_area_ids` and `_room_entries` agree.

## Framing G: goal fidelity
- **What the operator asked:** "Interior vision is meant to supplement person counts sensors. And allow us to describe what is happening with people when we need it", "tight and not deferred", switch ON.
- **What ship 1 delivers against that:** per-room NVR body records with named and unnamed counts. That is the substrate for "supplement" (ship 5) and "describe" (ship 2), and it matches the operator-approved §8c order. The census is untouched by design.
- **Did a builder decision change what is delivered?** The builder's report was not available to me, so this was judged from the code and the commit message. The material change is not the builder's: the plan's §7 group source (census interior list only) plus its §9.D5 window rule give an empty first hop on the main door (D-M1). The plan's trip-wire and Live criterion then hide that (D-M2). Builder-visible choices (records independent of FACE_SIGHTING_ENABLED, the sensor on the Whole House device, `phone_trustworthy` imported rather than moved) do not change what is delivered.
- **Delivered but the operator will never see it:**
  - `switch.ura_interior_vision` reads ON and its helper text says "Let AI vision look at indoor shared-room cameras", but nothing reads it in ship 1. The operator may believe vision is running. Suggest the helper text say that ship 1 makes no vision calls, or note it in the README.
  - The `interior_path` memory rows have no reader; the sensor shows only the last path. That is accepted as display and personalization prep.
  - `entered_via` will be empty for Garage Hallway and often for the stairs rooms (D-M1).
- **Drift check:** INV-IV-AWAY and the no-trust rule hold; no hard constraint is broken. The risk to the goal is a D5 that looks shipped (rows exist, no page) while it records almost nothing on garage_a.

## Invariant checklist
| Invariant | Result |
|---|---|
| INV-IV-AWAY | PASS |
| INV-IV-MISSING (no live member means missing, never 0) | PASS (stream-dead); LEAK for a stuck-but-streaming camera (D-M3) |
| INV-IV-DEDUP (one placement per slug) | PASS for slugs; latent LEAK on two groups per room (D-L1) |
| INV-IV-NO-TRUST | PASS |
| No new listener | PASS |
| Registry, never names | PASS |
| D5 / trip-wire completeness | LEAK (D-M1, D-M2) |

## Must-fix
D-M1, D-M2, D-M3. Fix the LOWs in-cycle where they are 1-30 lines (D-L1, D-L3, D-L4); D-L2 is required before ship 2.

## Bug classes
| Class | Findings |
|---|---|
| #53 computed-but-not-consumed / one missed site | D-M1, D-M3 |
| #62 hollow anchor (trip-wire / acceptance) | D-M2 |
| Stale cache / missing invalidation | D-L2 |
| Portability (false page) | D-L3 |
