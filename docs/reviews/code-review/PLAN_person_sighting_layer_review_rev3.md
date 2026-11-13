# Plan review: PERSON-SIGHTING-LAYER-1 rev 3 (harmonization + reuse completeness)

Plan: `docs/planning/PLANNING_person_sighting_layer.md` @ `b77b5b6f` (branch `plan/face-arrival-rebuild`).
Framing: harmonization with egress and census, reuse completeness, rev-2 fixes retained, access invariant
coverage, vision gating. Read completely first: `IDENTITY_FUSION_CAMERAS_MANUAL.md`,
`PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`, `SENSOR_FLEET_CLASSES.md`, both rev-1 plan reviews. No §10 ledger
claim is re-asserted here. Every finding below was checked against code in the worktree (paths relative to
`custom_components/universal_room_automation/`) or the live `.storage/core.config_entries` (read-only).

**Verdict: FIX-PLAN.** 1 HIGH, 6 MEDIUM, 7 LOW. All are plan text fixes; none needs new design.

## HIGH

**H1. The egress provenance key is ambiguous, and the plain reading drops every face-only egress sighting.**
The face-only attach path writes `_egress_identity_last_attach` with NO `provenance` key
(`transit_validator.py:1908-1916`). Only the BLE paths set it (`:1668` `ble`, `:1716` `ble+face`, `:1777` `ble`).
The existing reader gets `face` only through a default: `.get("provenance", "face")` (`:2086-2087`). The plan
says the new bus key is "taken from `census._egress_identity_last_attach["provenance"]`" (§3.2 (c)), and that
"`ble`, missing provenance and `ambiguous` give nothing". A builder who copies the key as written puts `None`
on every face-only crossing, so the most common face case never becomes a sighting. The tests in D1 stamp the
key by hand (`test_egress_face_provenance_sighting`), so they pass while live produces nothing (Bug Class #62,
hollow anchor; #53 at the producer).
Fix in the plan: either (preferred) the face-only attach at `:1908` writes `provenance: IDENTITY_PROVENANCE_FACE`
explicitly as part of the constant rename (one line, value already implied), or the bus key is defined as
`last_attach.get("provenance", IDENTITY_PROVENANCE_FACE)` when `person_id` is not None. Add a test that drives
the real `_resolve_egress_face_identity` face-only path (no BLE leg) and asserts `identity_provenance == "face"`
on the fired event, plus a mutation drill (remove the default / explicit write -> that test RED).

## MEDIUM

**M1. The "one physical-camera key" is not canonical in the resolver (§1.2a row, §2A checklist, §3.1).**
`resolve_capabilities` sets `physical_camera_id = sorted(device_ids)[0]` over its INPUT device list
(`camera_resolver.py:1029`), and `resolve_operator_declaration` passes one input device per call
(`:785-797`). So the id is the device of whichever entity was resolved: a Protect entity gives the Protect
device id, the Frigate twin of the same camera gives the Frigate device id. The egress camera id on the bus is
the egress person ENTITY that fired (`_resolve_direction(entity_id, ...)`, `transit_validator.py:1272, :1323`),
which may be the Frigate or the Protect leg. Legal repro: a house zone picks Protect
`binary_sensor.<door>_person_detected`; the door is also an egress camera whose crossing fires on Frigate
`binary_sensor.<door>_person_occupancy_2`. One recognition gives two keys and two sightings in one window, so the
F8 dedup fails (Bug Class #63: the ids are equal only when the same leg happens to be the input). §3.1 also gives
a second definition ("the pick's device id"). Fix: one helper, e.g. `canonical_camera_key(fusion) =
min(s.device_id for s in fusion.sources)` (or the frozenset of source device ids), used for interior and egress;
test with a Protect pick + Frigate egress leg. Not live today (no Protect picks; see M2), so MEDIUM.

**M2. The Garage A fused pick resolves to nothing on the live config.** Garage A's `room_cameras` is `[]`
(live entry, 2026-11-12). `CameraPersonDetectedSensor` reads only `CONF_ROOM_CAMERAS` and is permanently off
when it is empty (`binary_sensor.py:1529`, `:1582-1586`). So `resolve_pick_to_fusions` on that pick returns no
fusion, the §7 P1 expectation "reaches `sensor.garage_a_last_recognized_face_2` through its Frigate fusion" is
false, the D1 Verify "the URA fused `garage_a_camera_person_detected` emits exactly one sighting" cannot pass
live, and the F8 Garage A + egress double case does not occur today. Fix: add unresolved reason
`room_cameras_empty`; restate D1/L1 for Garage A as "reported unresolved with that reason"; add operator action
(config-first): either set Garage A's room cameras or replace that pick with the Garage A camera's own person
sensor. Keep the fused-pick test (the path is real for other rooms).

**M3. Egress sightings have no boot guard; the plan says they inherit one that does not exist.** §3.2 Filters:
"egress inherits the transit validator's own boot handling". `transit_validator.py` has no boot window (grep for
boot/startup/setup timestamp finds only a comment at `:271`). L3 ("no sighting in the first 600 s after
restart") would then fail on any crossing in that window. Fix: apply the same
`PERIMETER_EGRESS_ARRIVAL_BOOT_EXCLUDE_S` drop to source (c), and add an egress case to
`test_boot_restore_not_a_sighting`.

**M4. §2A says sightings and census "agree by construction" through the same veto primitives; they do not.**
The census face path drops a face for a `not_home` person and, under BLE Leads, for an overruled adult
(`_get_face_recognized_person_names`, `camera_census.py:6205-6240`; manual §5.4). The sighting producer
deliberately keeps those faces (§3.2 Filters: "raw `not_home` does NOT drop an interior sighting", the class (i)
candidate). So a Frigate mislabel of an away resident (the 10-24 Jaya-as-Oji case) is a sighting but not a
census identity. That split is legitimate, but it is a named concept split (Bug Class #63), not agreement. Fix:
reword §2A, and stamp the tracker verdict on the payload (e.g. `person_state_at_emit` raw, plus
`census_would_veto: bool`) so later consumers (personalization, FACE-SIGHTING-CONSUMERS-1) can apply the census
rule without re-deriving it.

**M5. INV-ACCESS is widened in words only; the consumer gates match the literal `"camera_face"`.** The lock
regime gates `source == "camera_face"` (`security_lock_regime.py:1017`) and the planned security gate keys on the
same string (§3.4). INV-ACCESS's own definition bullet still says "Face-derived input = ... whose `source` is
`camera_face`" (§2, line 268). A later camera-derived arrival with any other source string (`camera_vision`,
`interior_track`) passes both gates untouched. Fix: one constant set, e.g. `CAMERA_DERIVED_ARRIVAL_SOURCES =
frozenset({"camera_face"})`, tested by membership in the lock regime and security gates (or invert: only
`geofence` / `ble` skip corroboration, anything else needs it). Update the bullet to match the header. Pin with
a test that dispatches an unknown source and expects the corroboration path.

**M6. Egress arrival/departure notification already exists and is missing from the identity model.**
`TransitValidator._arrival_departure_notify` (`transit_validator.py:2047`, `:2140`), live since 2026-09, names the
person at `identity_confidence >= ARRIVAL_NAME_CONFIDENCE_THRESHOLD` and sends an NM "X arrived / left". §2A F3's
reader list omits it, §8 lists "No arrival/departure notifications (ARRIVAL-DEPARTURE-NOTIFY-1)" as if none
exists, and §12 FACE-SIGHTING-CONSUMERS-1 proposes that "notifications read `get_last_person_sighting`", which
would create a second arrival-notification producer. The manual §5.5 ("NOTHING reads `identity_confidence`") is
stale for the same reason. Fix: add it to F3 readers and to the no-duplicates checklist ("arrival/departure
notification: `_arrival_departure_notify`, one site"); FACE-SIGHTING-CONSUMERS-1 extends that site, it does not
add one; D5 corrects manual §5.5 (code wins).

## LOW

- **L1. INV-PROVENANCE contradicts §15.3.** INV-PROVENANCE says a sighting exists "only for real face evidence";
  §15.3 item 5 lets vision emit a `PersonSighting` at 0.3. Reword INV-PROVENANCE now ("face evidence, or vision
  evidence under the sibling plan's rules") or state that the sibling plan amends it.
- **L2. Provenance literal list incomplete.** `camera_census.py:4772` (`provenance="ble"`) is not in the §1.2a
  rename list. The defaults at `transit_validator.py:2087` and `camera_census.py:4197` also become constants.
- **L3. `edge_in_window` is a window helper, not a boot guard.** It returns `ts >= boot_end and abs(at_ts - ts)
  <= window_s` (`arrival_edges.py:85-87`). Say the call form (e.g. `ts >= boot_end` via the helper with
  `at_ts=ts`, or reuse only the constant). `test_boot_exclusion_uses_shared_edge_helper` reads like a
  call-was-made assertion (Bug Class #62); make it behavioural (ts = boot_end - 1 dropped, boot_end + 1 kept).
- **L4. "Unmapped" needs an explicit membership test.** `_canonical_person_slug` passes unmapped names through
  lowercased (`camera_census.py:3903-3990`), so "unmapped" = result not in `_get_tracked_person_slugs()` and not
  `guest:*`, and `""` (ambiguous head) is also unmapped. State it.
- **L5. INV-NOOP vs the census ring.** The post-sentinel ring (§3.5) is a census-side change; INV-NOOP says the
  only change outside presence is the bus key. Gate the ring on `FACE_SIGHTING_ENABLED` or list it in INV-NOOP.
- **L6. §15 should cite `FrigateEventIngress`** (`frigate_ingress.py:147`, `register_consumer` `:175`) as the
  source of the crossing camera's Frigate event id, not a new listener.
- **L7. D7 prior art.** The live `door_interior_neighbours` option already encodes door-to-interior adjacency
  (garage_a: garagehallway, staircase, stairs_top). If D7 revives, extend that before minting
  `INTERIOR_CAMERA_ADJACENCY`.

## Verified (holds)

- **§1.2a reuse table:** every cited symbol exists at or within a few lines of the cited line: `FaceLeg :349`,
  `_resolve_face_legs :3312`, `_canonical_person_slug :3903`, `_face_suppressed_now :4458`, `_on_frigate_face_msg
  :5459`, `_compute_face_latch_stems :5348`, `_device_derived_face_entity_id :3274`, `_resolver_dirty :454`,
  `CONFIDENCE_* const.py:315-317`, `FACE_MATCH_CORRELATED_BOOST :3345`, `BLE_TRANSITION_ONLY_CONFIDENCE :3378`,
  `PERIMETER_EGRESS_ARRIVAL_BOOT_EXCLUDE_S :2679`, `PERIMETER_SNAPSHOT_DIR :3136`, resolver `:131/:189/:427/:680/
  :698/:752/:767/:801`, `_camera_sightings :214`, writer `:797`, reader `:653`, consumers `binary_sensor.py:2196,
  :2217`, `sensor.py:3559`, `_get_interior_cameras_near :2203`, `adjacent_cameras :919`,
  `_capture_at_detection_snapshot :3690`, `_try_capture_live_grab :3893`, `_prune_snapshot_dir :4102` (plan says
  `:4113`, inside the function; cite drift only), `enrich_dispatched_alert :127`, `enrich_with_verdict :272`,
  `edge_in_window :85`, `nonface_arrival_source :168`, `_face_arrival_corroborated :1374`. `register_egress_face`
  is defined at `camera_census.py:4139` (plan cites `:4175`, a line inside it).
- **No NEW where a REUSE exists**, apart from M1 (the key exists but is not canonical) and M6 (notification).
  The `_camera_sightings` KEEP + CARD decision is sound: its only consumer is a house-state trust input.
- **§2A ownership:** F1, F2, F5 owners match code (`SIGNAL_PERSON_ARRIVING` producers `presence.py:5297`,
  `person_coordinator.py:1132`, `presence.py:5634`; consumers `hvac.py:1511`, `security.py:817`,
  `music_following.py:281`). Census does not read sightings and sightings do not feed census (no double count).
  Crossing -> sighting copies `person_id`, `identity_confidence` and `identity_synthetic_corroborated` from the
  bus event; the last is reset per call (`transit_validator.py:1394`), so no stale copy. Subject to H1 for
  provenance.
- **§5 sinks:** `add_expected_arrival` callers `security.py:2276, :2286, :2419, :2511` (service via
  `__init__.py:6613-6621`); `handle_disarm` callers `security.py:1452`, `__init__.py:6595`. Matches.
- **Rev-2 fixes all present after the restructure:** H1 (§0, §3.3 rule 2, L5), H2 (§3.2 (b) guard + boot),
  M1 (`PickBinding`, four triggers), M2 (post-sentinel ring), M3 (`face_input_corroborated`, fail closed),
  M4 (§3.3 rule 3), M5 (`_last_home_edge_ts`), M6 (fixed window, multi-stem rule), M7 (class iii dropped),
  F1-F11 (§14 table, each locatable), and the operator's pick -> physical camera -> every integration's entities
  walk (§3.2 steps 1-2). Mutation drills M1-M15 and L1-L9 unchanged.
- **§15 vision** is gated and non-access: builds nothing (§8, §15 header), D0-V needs operator approval and gates
  only the sibling plan, never sets `person_id`, never access-class, capped at 0.3, interior frames behind a
  separate default-off toggle. Only L1 and M5 touch it.

## Must-fix before operator APPROVE

H1, M1, M2, M3, M4, M5, M6. LOWs in the same edit (each is a sentence or a cite).

| Severity | Count | Bug classes |
|---|---|---|
| HIGH | 1 | #53 / #62 |
| MEDIUM | 6 | #63 (M1, M4), #53 (M3, M6), config premise (M2), invariant scope (M5) |
| LOW | 7 | #62 (L3), cite/text |
