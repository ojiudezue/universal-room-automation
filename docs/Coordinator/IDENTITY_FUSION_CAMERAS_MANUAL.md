# Identity, Fusion and Cameras — Operator Manual

**Audience:** the homeowner running URA, and any agent scoping work that
touches identity, camera fusion, the census, guest inference, or the
egress/perimeter pipeline.
**Scope:** the CANONICAL reference for how URA sees people. Camera
platform roles, identity sources and their real coverage, the
cross-modal fusion doctrine, the census + resolver architecture, the
egress-identity JOIN and the 6.0.0 gate that depends on it.
**Frigate MQTT (shipped v5.108.1):** URA reads Frigate events and
face names straight from MQTT on the runtime topic prefix (§1.3, §4.5).
**Current through:** URA v5.91.3 (`camera_census.py:3`); the egress-identity
PRODUCER is **built on `feature/egress-identity-producer`, shipped pending
deploy as v5.91.4** (orchestrator confirms the final version at deploy).
**Ground truth verified:** 2026-08-28 (code + memory bodies + post-ship
consumer-gap audit).

This is NOT a code walkthrough. Sibling of
`ENERGY_COORDINATOR_MANUAL.md`, `HVAC_COORDINATOR_MANUAL.md`,
`CM_MANUAL.md`, `PRESENCE_COORDINATOR.md`,
`PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`. For fusion research
context see `docs/planning/PLANNING_paper_and_oss_fusion_library.md`,
`PLANNING_room_camera_fusion.md`, `PLANNING_census_fusion_policy.md`,
`AUDIT_census_identity_supersession_and_consumers.md`.

**When in doubt, this manual is the oracle.** If some other doc or
memory contradicts what's here, verify against the live code cited
below and update this manual — do not open a new investigation.

---

## 1. Camera platforms and their roles

URA sees five camera-facing HA integrations. Roles are what the
INTEGRATION surfaces to HA, NOT what the camera hardware could do in
principle.

| Platform | Person detect | Face **name** in HA | Notes |
|---|---|---|---|
| **Frigate** (`frigate`) | `binary_sensor.<cam>_person_occupancy[_2]` | `sensor.<cam>_last_recognized_face[_2]` | **The named face-recognition source.** Also emits `sensor.<cam>_person_count[_2]`. Frigate-1 retired 2026-08-13; every survivor carries the `_2` suffix on at least SOME entities. |
| **UniFi Protect** (`unifiprotect`) | `binary_sensor.<cam>_person_detected` (+ vehicle/animal/face/license_plate smart-detect events) | **NOT exposed by the HA integration.** Protect's native face-name recognition is reachable only via the Protect Alarm Manager → HA webhook `ura_kp_face_probe`. That webhook is wired but currently **delivering empty payloads**. | NVR-style device: a single Protect `device_id` can host multiple physical cameras (see §5 F1 filter). |
| **Reolink** (`reolink`) | `binary_sensor.<cam>_person` (+ `_vehicle`, `_animal`) native AI | no | Verified live 2026-08-07. |
| **Amcrest** (custom) / **Dahua** (`amcrest` / `dahua`) | `binary_sensor.<cam>_smart_motion_human` (+ `_smart_motion_vehicle`) | no | Verified live. |

Suffix vocabularies live in
`camera_resolver.py:214-270` (`_PERSON_SUFFIXES`, `_VEHICLE_SUFFIXES`,
`_ANIMAL_SUFFIXES`, `_FACE_SUFFIXES`, `_PERSON_SWITCH_SUFFIXES`,
`_FACE_SWITCH_SUFFIXES`). Platform IDs at
`camera_resolver.py:122-127` (`PLATFORM_FRIGATE`, `PLATFORM_UNIFI`,
`PLATFORM_REOLINK`, `PLATFORM_AMCREST`, `PLATFORM_DAHUA`).

### 1.1 The `_2` suffix — permanent and camera-group-dependent

Frigate-1 was decommissioned 2026-08-13. Its entities are **fully
removed** from the registry (not "frozen unavailable" — an absent name
resolves to `None`/404). The `_2` suffix HA minted at Frigate-2's
registration is now permanent for at least SOME entity families on
every camera.

**The live-vs-dead naming is NOT uniform across cameras** — verified
2026-08-18 in the retirement audits:

| Camera group | Live F2 person leg | Live F2 non-binary (image/count) |
|---|---|---|
| Interior (family_room, master_hallway, foyer_fisheye, stairs_top, living_room…) | **bare** `_person_occupancy` (renamed at retirement) | still `_2` per-entity |
| Perimeter / PTZ (front_side_ptz, hot_tub, back_yard, g5_bullet…) | `_person_occupancy_2` | `_2` |

**Never assume `_2` = live or bare = live.** String-building a Frigate
entity id from a slug (`f"sensor.{base}_last_recognized_face"`) fails
silently against the wrong group. Every read MUST resolve via the
entity registry OR try both variants and gate on state
(`camera_census._resolve_face_entity_id`, `camera_census.py:3149`; the
state gate + `_face_lookup_missing_count` increment live in
`_first_usable_face_entity`, `:3181-3202`). The resolver's
suffix-tolerant match helper is
`camera_resolver._has_any_suffix_stripped` (`:317-327`).

**Face-NAME sources are registry-first (v5.107.1, FACE-SOURCE-REGISTRY-DISCOVERY-1).**
- Frigate face-name sensors are found by the integration-defined unique_id type token
  `<entry_id>:sensor_recognized_face:<cam>` on platform `frigate`, domain `sensor`
  (`camera_resolver._is_frigate_face_name_entry`, `:278`), indexed per device in the
  CameraResolver registry pass (`_frigate_face_entities_by_device`). `sensor_global_face`
  (per-person last_camera, server device) never matches. Order per device: bare before `_N`.
- Stem callers (`_resolve_face_entity_id`, `_resolve_face_legs`, egress, perimeter naming,
  perimeter D10.5) get `face_name_entities_for_stem` (`:698`): raw stem only, and a suffixed
  face sensor is returned only when its base equals the stem (so discovery never widens a
  stem; measured 2026-11-08: raw keys such as `garage_a_2` / `foyer` reach a device whose
  face base differs). A RENAMED face sensor (no `_last_recognized_face` suffix) is returned
  through the device. The built ids are the fallback only when the registry yields nothing.
- Person-sensor callers (census S5 `_get_face_recognized_persons`, S6
  `_get_face_recognized_persons_fresh`, S7 `_get_unrecognized_camera_count`) used to skip any
  Frigate camera whose person sensor did not end in `_person_occupancy`: **17 of 29 cameras**
  on the reference install (every `*_person_occupancy_2`; interior: playroom, upstairs_hall).
  They now join the face sensor through the person sensor's device
  (`_device_derived_face_entity_id`, `camera_census.py:3265`) after the legacy suffix test
  fails. S7 stays fail-closed (no face sensor -> whole count unrecognized) and can only go
  down (INV-4). Kill switch `FACE_SOURCE_INCLUDE_DISAMBIGUATED_PERSON_SENSORS` (rung 1, True).
- **Presence face pre-arrival (S8) is RETIRED (FACE-ARRIVAL-REBUILD-1 D5, branch
  `feature/person-sightings-p1`, NOT deployed).** `presence._get_face_for_camera`,
  `_handle_face_arrival` and `_find_person_entity_from_face` are deleted: the path fired 0 times in
  ~90 days (zone trackers had no cameras; edge race; `_N` producer disabled; no was-away test).
  `FACE_SOURCE_PRESENCE_ARRIVAL_DISAMBIGUATED` is KEEP + DOCUMENT with no reader. Faces now become
  person sightings (§4.5a) over the operator's `zone_cameras` picks, `_N` picks included; a
  `camera_face` arrival comes only from the D2 rule (interior class (i) "face before phone",
  `FACE_ARRIVAL_INTERIOR_ENABLED` False: D0-P3 failed) and access consumers still need an
  independent edge (§4.5).
- `FaceLeg.engine` is the device family (`CameraResolver.face_engine_tag`, `:737`):
  `frigate` / `protect` / ..., the hint on any miss, never `frigate2` / `unknown`. The entity
  leg and the synthetic latch leg use the same helper, so they still dedup (INV-2). Live
  `contributor_engines` read `frigate`, not `frigate2` (display only).
- Kill switch for all discovery: `FACE_SOURCE_REGISTRY_DISCOVERY_ENABLED` (rung 1, True).
  False = the pre-cycle name-pattern path, byte-identical, incl. the suffix engine tag.
- Diagnostics on `sensor.universal_room_automation_persons_in_house` (unrecorded, per tick):
  `face_source_registry_hits` / `face_source_pattern_fallbacks` (+ `_stems`) count LOOKUPS,
  not producer health (a dead Frigate shows in `face_lookup_missing_count`);
  `face_source_device_derived_reads` / `_cameras`; `face_source_skipped_person_sensors` /
  `_cameras` (only when the skip-fix switch is off).
- Protect: the HA integration exposes no face-NAME entity. `sensor.<stem>_face_recognized[_2]`
  and the `_face_recognized` / `_face_detected` / `_smart_detect_face` / `_ai_face` suffixes
  are KEEP + DOCUMENT (dead until the parked `D1-PROTECT-FACE-BRIDGE-ADDON-1`; generic names
  for other installs).

### 1.2 One physical camera can be seen by many integrations

The pool-overhead Amcrest is watched by **four** integrations
simultaneously — UniFi Protect, Frigate-2, Dahua, custom Amcrest
(operator-accepted, coverage artifact not a role split). One
integration failing while siblings work is expected here, not a
camera fault. Do not "clean up" the redundancy.

**Area attribution trap:** the pool-overhead is assigned to the
Balcony area (its physical mount) but WATCHES the pool. Today no URA
room maps to Balcony, so it's inert. Trip-wire: if a Balcony room is
ever created, Tier-1 area discovery would adopt this camera and
attribute pool swimmers as Balcony occupancy. Exclude explicitly at
that point.

### 1.3 Frigate ghost history — cross-corroboration doctrine

Frigate-1 was retired partly because of a documented 7-night ghost
epidemic (100% of 80 night alert-hour person edges were
Frigate-1-single-witness sub-2s IR blips, zero Protect corroboration).
Operator ruling: **FP mitigation preference is cross-corroboration
(Protect agreement), NOT duration/latency gates.** Evidence chain:
`docs/planning/AUDIT_perimeter_fp_correlation.md`,
`AUDIT_frigate1_retirement_inventory.md`,
`AUDIT_frigate1_sunset.md`, `AUDIT_frigate_dead_leg_correctness.md`
(2026-08-18: zero dead-leg reads in URA). MQTT topic-collision
hypothesis ruled out live (Frigate-1 `topic_prefix: frigate`,
Frigate-2 `topic_prefix: frigate2`, client ids `frigate-f1` /
`frigate-f2`).

**Where URA gets the MQTT prefix (v5.108.1, branch
`feature/frigate-mqtt-direct`, shipped v5.108.1).** Never from a literal and never
from the Frigate config ENTRY. The entry holds no prefix key: the live
"Frigate 2" entry has only url, username, password and validate_ssl. The
prefix comes from the running integration,
`hass.data["frigate"][entry_id]["config"]["mqtt"]["topic_prefix"]`, read for
every Frigate entry. Frigate stores it at setup (frigate `__init__.py:378-381`,
v5.15.6). One helper reads it, `frigate_ingress.discover_frigate_topic_prefixes`,
and both the events ingress and the census face bridge use it. Live today:
`{frigate2}`. `frigate/` (retired Frigate-1) carries only stale retained
`state` / `snapshot` / `available` messages (D0, 2026-11-09).
**Corrected:** before this build the census face bridge subscribed to
`frigate/tracked_object_update`. Its resolver read keys that do not exist and
fell back to the literal `frigate`, so the fast face path had heard nothing
since Frigate-1 retired. The point-read path (§1.1) kept faces working
(FRIGATE-FACE-BRIDGE-DEAD-PREFIX-1).

---

## 2. Identity sources — what's reliable and what isn't

URA has three candidate identity sources. Their coverage and failure
modes are asymmetric and the plans that ignore this die.

### 2.1 Interior BLE-phone person slugs (`PersonCoordinator`)

The workhorse for interior identity. `PersonCoordinator`
(`person_coordinator.py`) fuses per-person GPS + WiFi + BLE
(`bermuda` / private-BLE trackers, source_type=`bluetooth_le`) into a
per-person state and stamps `person_visits` on room transitions
(`_log_person_room_change`).

- **Coverage:** ~100% NAMED when a tracked phone is present.
- **Failure mode:** structurally BLIND to phoneless occupants
  (children, guests without a tracked handset). No BLE = no identity
  by this path.
- **BLE fleet-liveness gate** (`BLE_FLEET_LIVENESS_WINDOW_S = 90`,
  `person_coordinator.py:67`) prevents a boot-tick with an empty
  scanner fleet from wrongly attributing BLE-silent-away to a person.

### 2.2 Frigate exterior faces (`sensor.<cam>_last_recognized_face[_2]`)

The only NAMED-face source URA can currently join to a crossing.

- **Coverage on door / garage cameras:** sparse — historical peak
  when the subsystem was healthy was ~3/day per egress camera
  (garage_a 10, doorbell_lite 3, front_door_aerial 3 over eight days
  in August). Overhead angles + people-in-motion + back-of-head views
  are the geometry.
- **Coverage on interior cameras:** structurally richer (family_room,
  master_hallway) — but every pre-2026-08-23 rate figure was
  **inflated by a probe defect** (`frigate_health_probe.py` filtered
  junk face states case-sensitively; excluded `"unknown"` but the
  live state is `"Unknown"`). Post-fix rates 08-17..08-19 were
  53/16/26 house-wide daily, not the 131/118 that circulated.
- **RECOVERED as of 2026-08-28** (operator Frigate-2 hardware re-tune
  ~08-26/27). Measured 71 named-face events / 24h across 11 cameras:
  family_room 29, master_hallway 20, staircase 7, garage_a 5,
  doorbell_lite 3, others 1–2. The 08-21..08-24 house-wide face-DOWN
  fault (daily counts 3/0/4/2 while person-detection stayed healthy)
  is resolved. **Keep the diagnostic lesson:** person-detections-normal
  + face-recognitions-zero is the signature of a face-subsystem fault
  (upstream in Frigate, not URA, and not fixed by a storage change) —
  use it next time face rate collapses while person counts hold.

### 2.3 UniFi Protect Alarm Manager webhook (`ura_kp_face_probe`)

The **second-source-in-waiting** for named face recognition. Protect's
NVR knows residents by name (`recognized_person_name`, `confidence`),
but the HA `unifiprotect` integration does NOT surface the name — only
the smart-detect `face` event. The reachable path is the Alarm Manager
rule → local HA webhook `ura_kp_face_probe`, listener
`automation.ura_kp_face_webhook_probe` which fires
`ura_kp_face_probe_received` events + logs the payload.

- **Status (verified 2026-08-28):** the Alarm Manager WEBHOOK is a dead
  end — it fires on a real crossing but POSTs an empty/unparseable body
  (live crossing 07:27:28 → `{}`). **Use the Protect API instead** (the
  `unifi-protect` MCP: `protect_list_smart_detections` /
  `protect_list_events` / `protect_get_event`), which returns
  `recognized_person_id` + `recognized_person_name` +
  `recognized_person_confidence` for enrolled Known Faces — proven live
  (Oji named 82% at 21:32). No HA-integration limit; reachable now.
- **The bottleneck is ENROLLMENT, not access** (`protect_list_known_faces`):
  only 4 named (Oji 46-det + Ziri 40-det strong; Ade/Shola marginal),
  **Jaya + Ezinne NOT enrolled**, ~90+ unnamed auto-clusters. Many real
  crossings match an unnamed cluster (the 07:27 crossing → `face_265`,
  90% conf, no name). Protect and Frigate have COMPLEMENTARY coverage
  (Frigate names Jaya/Ezinne/Oji; Protect names Oji/Ziri + stronger at
  door angles) — so the egress producer should FUSE Protect-API + Frigate
  (keyed camera+time, higher-confidence named hit), not pick one.
- **Operator-side unlock:** enroll Jaya + Ezinne; merge recurring
  unnamed clusters into the right person in the Protect app.
- **Scope (durable):** Protect face recognition is enabled on exactly
  **two cameras** — `living_room_family_room` and
  `front_porch_madrone_g6_entry` (the only two producing Protect
  `event_type: face` smart-detections; verified 2026-08-28, 38 + 2
  over 48h). Any Protect-face fusion is bounded to those two.
- **Would unblock:** consuming Protect-named faces from those two
  cameras into the census/identity union.

---

## 3. The fusion doctrine

Cross-modal arbitration across BLE / PIR / mmWave / cam-person /
cam-face. Details in
`docs/planning/PLANNING_census_fusion_policy.md`,
`PLANNING_room_camera_fusion.md`,
`PLANNING_paper_and_oss_fusion_library.md`. Standing invariants:

1. **Face is NEVER auto-enabled** (`camera_resolver.py` module
   invariant; face-switch inventory `_FACE_SWITCH_SUFFIXES` exists so
   tests can prove no auto-enable path touches them).
2. **Face capability is tri-state:** `absent` / `usable` / `ambiguous`
   (`FACE_ABSENT` / `FACE_USABLE` / `FACE_AMBIGUOUS`,
   `camera_resolver.py:118-120`). Disabled ≠ negative evidence.
3. **Face USABLE is sticky** — once any enabled face entity is seen
   for a device, capability stays USABLE even if a later disabled
   face entity is scanned (`_scan_device_entities`, A-M4 rule at
   `camera_resolver.py:1395-1421`).
4. **Cardinality of the UNION, not sum** — the census fuses face_ids
   / ble_ids / egress-identified persons as a SET, not a total.
5. **Cross-corroboration beats latency** for FP mitigation
   (Frigate-ghost doctrine, §1.3).
6. **Graceful-anonymous downstream** — every identity consumer must
   accept "known name" OR "anonymous" and not gate its whole
   behavior on identity being present.
7. **Fresh-read the kill switch** — `switch.ura_name_people_at_doors`
   is read at every call and takes effect on the next crossing
   without an integration reload (`camera_census.py:2969`,
   `switch.py:190`).

Census / observability sensors exposed for validation include
census confidence (`HIGH` / `MEDIUM` / `LOW` / `NONE`,
`CENSUS_CONFIDENCE_*` in `const.py`) and agreement
(`CENSUS_AGREEMENT_BOTH` / `CLOSE` / `DISAGREE` / `SINGLE`),
`CONF_CENSUS_CROSS_VALIDATION`, `CONF_CENSUS_DIVERGENCE_DOWNGRADE`.

---

## 4. Architecture — the census, resolver, transit and person layers

Four modules, one line of responsibility each.

### 4.1 `CameraResolver` (`camera_resolver.py`) — platform resolution

The shared primitive that any consumer uses to go from an entity_id or
device_id to a fused per-integration capability map. Correlation
ladder (rungs, `camera_resolver.py:11-36`):

1. **same-device** (entity → device_id, F1 stem filter inside
   Protect NVR devices to prevent staircase + garagehallway bleed).
2. **device-MAC** join across integrations (Frigate carries no MAC on
   this deployment; measured zero live cross-integration MAC matches).
3. **identifiers** — full `(integration, key)` tuple overlap.
4. **network-inventory** — stub interface only, no live UniFi Network
   lookup wired.
5. **name-stem** (workhorse), with F2 Frigate-cross-host collapse
   gated by `FRIGATE_CROSS_HOST_CORROBORATION_ENABLED`
   (`camera_resolver.py:79`, gate PASSED 2026-08-04), and F3
   `_package_*` exclusion so Frigate's package-person object doesn't
   contaminate person fusion.
6. **operator-declared** — `CONF_ROOM_CAMERAS` multi-select is
   ground truth.

Key APIs: `resolve_operator_declaration`, `resolve_capabilities`,
`resolve_detection_legs` (returns `DetectionLeg` with engine tag —
`frigate`/`frigate2`/`protect`/`protect2`/`reolink`/`amcrest`/`dahua`,
`camera_resolver._engine_tag`), `enumerate_platform_cameras`. `FaceLeg.engine` no longer
uses `_engine_tag` (v5.107.1: device family via `face_engine_tag`, §1.1); `DetectionLeg`
still does.

### 4.2 `CameraIntegrationManager` + `PersonCensus` (`camera_census.py`)

The census authority. Dual-zone (interior + property), publishes
identified / unidentified / on-property counts, holds+decays after
peaks, cross-validates across BLE + face + camera-person, downgrades
on divergence. Face-name reader is
`_resolve_face_entity_id` (`camera_census.py:3149`, registry-first since v5.107.1, §1.1),
canonical-slug helper `_canonical_person_slug` (URA-slug namespace so
face / ble / DB / `person.<slug>` all agree). **Face-name aliases (v5.107.1):** the optional
`face_name_aliases` option (Camera Census, Advanced; entries `FaceName=target`, target = a
tracked slug with or without `person.`, or a `known_face_guests` name) is consulted after the
direct slug match and before first-token inference (`_face_alias_target`, `:4013`). Empty by
default (no change). Aliases are applied ONLY inside `_canonical_person_slug` (the one mapper; the presence-side
`face_alias_person_slug` / `_find_person_entity_from_face` pair was DELETED by
FACE-ARRIVAL-REBUILD-1 D5), and widen the perimeter D10.5 `known` set. Fresh-read; saving it does not reload the integration.

Cutover flag `CENSUS_USE_NEW_RESOLVER = True`
(`camera_resolver.py:102`) — the census's
`resolve_cross_platform_sensors` runs through `CameraResolver`.
Fire-axe scope note is on the constant itself: flipping it back
reverts ONLY the census merge path; the D3 per-room fused sensor,
D5 fan_veto camera leg, and D4 dry-run scan remain on the new
resolver.

### 4.3 `TransitValidator` (`transit_validator.py`) — egress crossings

Consumes egress-camera person events, dedups by camera stem (5s
window across Frigate/Protect for the same physical camera), resolves
direction (entry/exit/ambiguous) via near-door interior camera events
within `ENTRY_WINDOW_SECONDS`/`EXIT_WINDOW_SECONDS`, and stamps a
`person_id` via `_resolve_egress_face_identity`
(`transit_validator.py:1120-1226`) — the freshest recognized-face
NAME on the SAME camera stem within `FACE_MATCH_WINDOW_S` (currently
60s, `const.py:2162`), gated by:

- The kill switch (`census._is_egress_identity_enabled()` →
  `switch.ura_name_people_at_doors`, fresh-read).
- Freshness `0 <= age <= FACE_MATCH_WINDOW_S` (sign-symmetric: a
  face timestamped AFTER the crossing is treated as stale, not
  "future-fresh").
- Canonicalization to URA person-slug via `_canonical_person_slug`.
- Fail-open person-tracker veto: if `person.<slug>` state is
  `not_home`, drop the recognition even if the face sensor is
  currently reporting the name (stale-face latch guard).

Emits `ura_person_egress_event` bus event with fields `direction`,
`egress_camera`, `timestamp`, `person_id`, `confidence`. Persists to
`person_entry_exit_events` (schema below).

**Return channel, provenance key and outcome log (FACE-ARRIVAL-REBUILD-1 D8a, branch
`feature/person-sightings-p1`, NOT deployed; plan `PLANNING_person_sighting_layer.md` rev 11).**
- `_resolve_direction` (the one production caller) now calls `_resolve_egress_face_identity_ex`,
  which returns the old 3-tuple plus a frozen `EgressResolution` built fresh on EVERY return path:
  outcome label (the census deque label, plus `census_unavailable` / `resolver_error` for the two
  paths that record none), the slug considered (the vetoed slug on a veto), the tier and `synthetic`
  from the module-level PURE `egress_identity_tier` helper, the raw person state, and `provenance`
  (`face` / `ble` / `ble+face`, None when nothing attached). `_resolve_egress_face_identity` stays as a
  thin 3-tuple wrapper. The veto path calls only the pure helper, so a vetoed crossing never appends to
  the BOOST ledger or sets the synthetic stash (develop behaviour, pinned by a golden replay).
- The bus event gains one additive key, `identity_provenance`, read from that resolution (never from
  the `_egress_identity_last_attach` stash); None when `person_id` is None. The face-only attach now
  also writes `provenance: face` into the stash explicitly (the value every reader already defaulted to).
  The provenance strings are named constants `const.IDENTITY_PROVENANCE_*` (pure rename, same values).
- **Outcome log:** one `memory_episodes` row (`episode_type = egress_identity_outcome`, `node_id` /
  `source_ref` per crossing) per resolution, slug included on vetoed rows, written as a tracked task
  (`_outcome_log_tasks`, gathered with a 5 s bound in `async_teardown`; a `_torn_down` latch set first
  stops a late `_delayed_resolve` from writing after teardown). No decision reads it. Kill switch
  `EGRESS_OUTCOME_LOG_PERSIST` (rung 1, True); the type is in `MEMORY_WRITER_BACKED_EPISODE_TYPES`, so
  the weekly memory-writer health check pages on 0 rows in 7 days (about 15 a day expected). Weekly
  labeller `scripts/probes/egress_outcome_label_weekly.py` (read-only; snapshots raw path edges and GPS
  fixes) feeds `quality/tests/fixtures/egress_arrival_d0_labelled.json`; card
  EGRESS-OUTCOME-WEEKLY-LABEL-1. The face-only `not_home` veto itself is UNCHANGED in Phase 1.

Direction gating on the census union feed
(`transit_validator.py:1298-1310`):
- `entry` → register the identity into the census union.
- `exit` → EVICT any prior registration for this identity within
  `EGRESS_FACE_UNION_TTL_S`.
- `ambiguous` → neither register nor evict (matches DB-write gate).

### 4.3a Exit backfill (late-binding identity, v5.96.1 / v5.97.1; R1 2026-10-16)

Exit rows have a second `person_id` writer. When a resident's own
`bluetooth_le` tracker goes home→away, `camera_census._on_crossing_tracker_state_change`
schedules `_backfill_exit_identity`. After a 300 s settle and a flap re-read it
names the nearest NULL exit row in the 600 s before the edge
(`database.backfill_entry_exit_person_id`, `WHERE id=? AND person_id IS NULL`;
`confidence` column untouched). So exit identity can arrive ~5-11 min late.

- **Kill switch (R1):** `switch.ura_name_people_at_doors` is fresh-read at the edge
  handler AND right before the UPDATE. OFF means no backfill write; counted in
  `ble_exit_identity_disabled_skip_count` on the census sensor.
- **Displays:** `PersonsExitedTodaySensor` re-reads today's exits and
  `LastPersonExitSensor` (R1) re-reads the newest exit row on
  `SIGNAL_EGRESS_EXIT_BACKFILLED`. The last-exit display only takes the name
  if the newest row is the one named.
- **Never:** re-notify (backfill confidence 0.72 is below the 0.75 naming bar
  anyway), census recount/evict, or any actuation.
- Any future trust consumer of exit `person_id` must read after the backfill
  window or treat exit identity as late-binding. Validation: `AUDIT_exit_backfill_d0.md`.

### 4.4 `PersonCoordinator` (`person_coordinator.py`) — interior identity

Per-person GPS/WiFi/BLE fusion, `_log_person_room_change` writes to
`person_visits`. BLE fleet-liveness gate at
`person_coordinator.py:67` (`BLE_FLEET_LIVENESS_WINDOW_S = 90`).
Presence details in `PRESENCE_COORDINATOR.md` and
`PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`.

### 4.5 Perimeter surfaces

`perimeter_enrichment.py` / `perimeter_alert.py` — alert routing off
the DetectionLeg output of `CameraResolver.resolve_detection_legs`
(replaced three generations of hand-rolled slug helpers per the
Cycle-3 resolver-legs work, 2026-08-07). Alerts today say "person
detected" — the identity-consuming version is the card
`PERIMETER-ALERT-NAME-PERSON-1` (see §6).

**v5.107.0 (PERIMETER-FP-STREET-NOISE-1) additions** — all demote-only (floor
LOW, never silence), decisions on the exterior open-tracks diagnostic sensor
under `gate_decisions_by_camera`:
- **Zone legs (D1).** `perimeter_zone_sensors` (camera-census step, Advanced)
  maps Frigate zone person sensors (`<frigate_camera>_property`) onto a
  perimeter camera; that camera's camera-level Frigate person legs are then
  not subscribed (setup AND `_rescan_siblings`). Zone sensors collapse to the
  camera key via a runtime overlay in `_camera_key_for_sensor`.
- **NVR family, not engine string.** `perimeter_fp_gates.nvr_family`
  (frigate*/protect*) is what the burst sibling check compares; two Frigate
  legs never corroborate each other.
- **Demote reasons:** D3 `outside_property_zone` (Frigate `entered_zones`
  missed the property zone), D5 `single_source` (only one NVR family on a
  camera where both usually agree), D6 `vlm_no_person` (VLM `PERSON: NO` on a
  `frigate_event`-tier frame). D3/D5/D6 ship off/shadow.
- **Egress cameras raise perimeter alerts (D10)** when they are in BOTH camera
  lists ("dual-role"). A dual-role camera ignores egress stamps from every
  dual-role camera (INV-EGRESS-SELF); it gets no vehicle legs. Its own alerts
  pass the D10.5 gate (`switch.ura_perimeter_egress_known_xcorr_gate`, ON):
  LOW for a KNOWN person (§5.5(a): ≥ 0.9 — egress event or scored face leg
  freshness-matched to the edge; OR, operator 2026-11-08, a below-floor
  Frigate face match corroborated by an existing non-face signal for the SAME
  person showing a real ARRIVAL within `PERIMETER_EGRESS_FACE_NONFACE_WINDOW_S`
  (120 s): a live `person.<slug>` not_home → home edge, or a Bermuda move into
  the camera's own area or its configured door-interior neighbours' areas;
  transitions within 600 s of setup are ignored; interior room hops never count
  — review B-MED-2); LOW when unknown and not
  corroborated by the other NVR family while it is live; contextual severity
  otherwise. A face alone, or a latched name, never demotes.
- **"That was <name>" follow-up (v5.107.5,
  `switch.ura_perimeter_identity_followup`, ON).** When a dual-role alert was
  dispatched above LOW with D10.5 reason `egress_unknown_corroborated` or
  `xcorr_waived_single_nvr` (not demoted, no `Identified:` annotation), the
  manager re-checks `_known_identity_for` (the SAME ≥ 0.9 / face+arrival rule)
  every `PERIMETER_IDENTITY_FOLLOWUP_POLL_S` (5 s) for
  `PERIMETER_IDENTITY_FOLLOWUP_WINDOW_S` (90 s) and sends at most one
  `async_notify(..., quiet=True)` at the original severity. Annotate-only per
  §5.5(a): it never changes the original alert's severity. Discharged on
  window expiry, teardown, and any later dispatched alert on the same camera
  key (`perimeter_alert.py` `_arm_identity_followup` / `_followup_check`).

**Gate evidence (PERIMETER-GATE-EVIDENCE Part A, branch `feature/perimeter-gate-evidence`,
NOT deployed; plan `PLANNING_perimeter_gate_evidence_and_input_health.md`).**
- **Daylight-only single-source demotes (D1/D1b).** D5 `single_source` and the D10.5
  `egress_uncorroborated` branch demote only while `sun.sun` elevation ≥
  `PERIMETER_SS_DAYLIGHT_MIN_ELEVATION_DEG` (0.0). Missing / unavailable / non-numeric sun
  = night = no demote. D5 reasons `night` (no hold) and `night_after_settle` (sun set during
  the 8 s settle); D10.5 reason `egress_uncorroborated_night` (read after both holds), which
  also arms the "that was <name>" follow-up. `egress_known_person` is unchanged. Kill
  switches `PERIMETER_SS_DAYLIGHT_ONLY` / `PERIMETER_EGRESS_UNCORROBORATED_DAYLIGHT_ONLY`.
- **Persisted decisions (D2).** Every `_record_gate` call writes one `memory_episodes` row
  (`perimeter_gate_decision`, node `perimeter_gate:<cam_key>`, `window_dedup=False`) with
  sun state on every row. Writer-health checked. Reader: `scripts/probes/perimeter_gate_scorer_weekly.py`.
- **VLM location (D3) ships DARK.** `PERIMETER_VLM_LOCATION_ASK` = False after the D0-B
  replay no-go (street recall 8/26; `AUDIT_perimeter_d0_location_2026_11_13.md`). When on,
  shadow asks LOCATION and records it only; enforce keeps `_VERDICT_PROMPT` unless
  `PERIMETER_VLM_LOCATION_ASK_IN_ENFORCE`.

**Frigate event ingress (v5.108.1, PERIMETER-FRIGATE-MQTT-DIRECT-1, branch
`feature/frigate-mqtt-direct`, shipped v5.108.1; plan
`PLANNING_frigate_mqtt_direct_2026_11.md` rev 2).** Before this build, perimeter
alerts (snapshot event ids, the D2 event cache, D3 zone gating) and the exterior
track linker heard Frigate events only through the `frigate_events` bus event.
A house automation fires that event from `frigate2/events`, so an install
without that automation got nothing. Both now register on one
`FrigateEventIngress` (`frigate_ingress.py`, at `hass.data[DOMAIN]["frigate_ingress"]`):
- **Sources.** The `frigate_events` bus, plus a direct subscription to
  `<prefix>/events` for each discovered prefix (§1.3). mqtt stays a soft
  dependency: no manifest change, the subscription is set up again when mqtt
  loads, when Frigate loads, when HA has started, and every 300 s (add-only).
- **Exactly once.** A latch per event id: the first source family to deliver
  an id owns it, the other family's copies are dropped while the owner was
  heard within 30 s (`FRIGATE_INGRESS_SOURCE_LATCH_TTL_S`, floor 10). Updates
  from the owning family are never deduped. MQTT normally wins (D0: the bus
  lags by ≤ 44 ms) and the bus is the fallback. A message with no id goes
  through MQTT only while an events subscription is live.
- **Same payload.** MQTT payloads are normalised to the bus shape
  (`before`, `after`, `type`); D0 found 1881/1881 equal. `sub_label` arrives
  as null or `[name, score]` on both paths, unchanged.
- **Retained messages are skipped** (stale on subscribe).
- **Census face bridge.** It registers a `tracked_object_update` handler on
  the same ingress, so it uses the runtime prefix (§1.3) and the same
  late-load handling.
- **Synthetic face legs do not count toward D10.5's 0.9 (review B-M1).** The
  latch leg is marked `FaceLeg.synthetic`. When the egress producer's 0.9
  (two cameras) holds only with a synthetic leg in the pair, it still reports
  0.9, so display and DB rows are unchanged, but it adds
  `identity_synthetic_corroborated: true` to `ura_person_egress_event`.
  Perimeter D10.5 then treats that identity like a below-floor face: it
  demotes only with the same-person non-face arrival edge within 120 s
  (reason `egress_synthetic+<source>`).
- **Kill switch.** `FRIGATE_INGRESS_MQTT_ENABLED` (rung 1, True). False means
  bus-only events; the face topic stays subscribed.
- **Diagnostics** (display only, on the exterior open-tracks sensor next to
  `frigate_bus_by_camera`): `frigate_ingress_prefixes`, `_mqtt_24h`,
  `_bus_24h` (received per source, before dedup), `_dedup_dropped`,
  `_mqtt_bad_payload`, `_mqtt_retained_skipped`, `_idless`. The D2 "bus
  silent" WARN now fires only when BOTH sources are silent.

**SC lock regime face arrivals (v5.107.4, LOCK-REGIME-FACE-ARRIVAL-CORROBORATION-1,
branch `feature/lock-face-arrival`, shipped v5.107.6).** (FACE-ARRIVAL-REBUILD-1 D5: the only
`camera_face` producer is now the D2 rule, interior class (i) only and off by default; egress
identity feeds no arrival.) A `SIGNAL_PERSON_ARRIVING` with
`source: camera_face` (formerly presence `_handle_face_arrival`, any zone camera) used to
release the garage lockouts and the away lock whenever the person was really away.
It now also needs the same independent same-person arrival edge as D10.5: a live
tracker `not_home → home`, or a Bermuda move into an entry area (egress camera areas
plus configured door-interior neighbours). The edge must be within 120 s and outside
the 600 s post-setup exclusion. The rule is shared code (`arrival_edges.py`). This
is the §5.5(a) doctrine applied to actuation: a face name alone never unlocks.
**One camera-derived source set, two gates (FACE-ARRIVAL-REBUILD-1 D3, branch
`feature/person-sightings-p1`, NOT deployed).** The lock regime no longer tests the literal
`source == "camera_face"`: both access gates call `arrival_edges.arrival_source_needs_corroboration`,
which returns True for any source in `const.CAMERA_DERIVED_ARRIVAL_SOURCES`
(`{"camera_face", "camera_egress"}`; `camera_egress` has no producer in Phase 1) and for any unknown
string (fail closed), and False for `NON_CAMERA_ARRIVAL_SOURCES` (`geofence`, `ble`) and for a missing
source (develop behaviour). The second gate is NEW: with `security_on_arrival_add_expected` on, the
Security Coordinator adds an expected arrival (which suppresses the entry alarm person-agnostically)
for such a source only when `SecurityLockRegime.face_input_corroborated(person, at_ts)` (public wrapper
over `_face_arrival_corroborated`, same stamps / window / boot floor) finds the independent edge;
`at_ts` is the sighting's recognition time when the payload carries one, else the regime's own now. No
lock regime (or a torn-down one) rejects; there is no held re-check. Before this, a face-only
`camera_face` arrival with the toggle on sanctioned every door for 5 minutes (latent: the toggle is
off live and the face producer never fired).
**Held edges do not corroborate (suspicious-arrival hold, branch
`feature/lock-suspicious-arrival-hold`, shipped v5.108.13; plan
`PLANNING_lock_suspicious_arrival_hold.md` rev 2).** A tracker edge whose person
`source` did not change at the edge (the 2-GPS stale-device blip) is held 5 s
(`number.ura_garage_lockout_arrival_hold`); the `_arrival_edges` stamp is written
only when the edge is processed (directly, or at confirm with the edge's own
time), so a blip cancelled inside the hold never stamps and cannot corroborate a
later face. Any `SIGNAL_PERSON_ARRIVING` (face included, and the held-face
re-check) for a person whose edge is held, or who reads home on a stale source,
is dropped in `_apply_arrival`. Details: `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`
§1 table.

**House state is not identity (LOCK-RELEASE-ON-ARRIVING, branch `feature/lock-release-arriving`, NOT
deployed; plan `PLANNING_lock_release_on_arriving.md` rev 3).** House-state ARRIVING is inferred from
`census_count > 0 or any_zone_occupied` with no name attached (68.5 % of ARRIVING edges are room-sensor occupancy
alone), so it is body evidence, the same class as an unnamed camera body. The garage lockout therefore no longer
releases on it, nor on a HOME_* edge in an episode that saw it: access needs a resident's own arrival edge (a
`person.*` -> home edge counted by `_arrival_counts`, an approach-zone / proximity crossing, or a corroborated
`SIGNAL_PERSON_ARRIVING`). Same doctrine as §5.5(a) and the face rule above: an inference with no identity never
unlocks. HOUSE-STATE step 1a D4 (branch `feature/house-state-step1a`, NOT deployed) completes it: no HOME_* / ARRIVING
house edge releases an open episode unless its trigger is an operator override (`override_set` / `override_clear`).
**Residency records use no identity (step 1a D2):** the presence residency producer's `person_arrival` /
`person_departure` records and `residents_home` read only `person.*` state (raw edges; trust level via
`person_state_for_trust`) and the phone-left-behind sensor; no face, camera or egress input.

**Exterior seam file (EXTERIOR-SEAM-LOADER, branch `feature/exterior-seam-loader`,
shipped v5.108.15; plan `PLANNING_exterior_seam_file_injection.md` D4/D5/D6).** The
exterior track linker's camera adjacency ("seams") and the egress-adjacent set
that drives `approach` classification now come from
`/config/universal_room_automation/exterior_seams.json` when it is present and
valid. `EXTERIOR_ADJACENCY_GRAPH` / `EXTERIOR_TRACK_EGRESS_ADJACENT_CAMERAS` in
`const.py` are the fallback. Before this build nothing imported
`exterior_seams.py`; the linker ran on the const only.
- **Load.** `ExteriorTrackLinker.async_setup` calls `async_load_seam_file`
  (executor read). The file is validated by `exterior_seams.validate_seam_spec`
  against the configured exterior camera keys (the linker allowlist, or the
  allowlist the PerimeterAlertManager staged before the READY signal). Valid:
  `set_adjacency(graph_from_spec)`, and the egress-adjacent set is derived from
  the file's EXTERIOR egress cameras (`derive_egress_adjacent`; if the file lists
  none, the const set is kept). Absent: the const graph. Invalid or unreadable:
  rejected whole, the previously installed graph stays (the const at boot, never
  an empty graph), one WARNING naming the first error.
- **Reload.** `button.ura_reload_exterior_seams` (Security Coordinator device)
  runs the same load with no restart. A rejected reload keeps the previous good
  graph; deleting the file and reloading reverts to the const.
- **Provenance** (on the exterior open-tracks diagnostic sensor): `seam_source`
  (`exterior_seams.json (schema 1, N seams)` or `built-in const`), `seam_count`,
  `seam_validation` (`ok`, `ok (N warning(s): ...)`, `file absent`, or
  `rejected: <first error>`), `seam_file_sha256`, `seam_egress_adjacent`.
- **Live file vs const (2026-11-12).** The ratified rev-2 file and the const are
  identical: same 21 undirected seams, same 13 cameras, same egress-adjacent set
  (armcrest, front_side_ptz, g5_bullet, rear_ptz, utilities_ptz). The takeover
  changes no behaviour. Expect one validator warning: `sonoffwindow` is a
  configured perimeter camera that is not in the ring.
- **Rejection risk.** Validator rule 1 rejects the WHOLE file if the ring names a
  camera key missing from the allowlist (e.g. a camera whose person legs did not
  resolve at setup). The fallback is the identical const graph, so the house
  behaves the same; `seam_validation` names the camera.
- No upload UI yet (plan D3 is spiked only). Edit the file over Samba/SSH, then
  press the reload button.

**Interior path map (FACE-ARRIVAL-REBUILD-1 D7 / INTERIOR-PATH-MAP-1, branch
`feature/person-sightings-p1`, NOT deployed).** `/config/universal_room_automation/interior_paths.json`
(primary) or `const.INTERIOR_PATH_MAP_FALLBACK` (shipped `None`: no house entity id in code, so with no
valid file there is no map, `path_map_source: none`) is
loaded by `EgressDirectionTracker.async_load_path_map` through the shared
`json_file_loader.load_validated_json` (read, sha, parse, validate; never installs; the seam loader
now calls it too, behaviour pinned by `test_seam_sha_on_rejected_file_unchanged`). Validated by the
HA-free `interior_paths.validate` (rules 1-10; nodes = physical cameras via
`canonical_camera_key`; whole-file rejection; rule 10: a detached door, `INTERIOR_PATH_DETACHED_DOORS`
= {garage_b}, may not point inward into a house camera). Outcomes: valid file -> file; absent ->
validated const or none (none with the shipped `None`); invalid at first load -> validated const or
none; invalid later -> previous kept. **This house's map** (operator fixture
`FIXTURE_camera_paths_interior.md` answers 2026-11-12, `lag_p90_s` from D0-P4; 19 edges, doors
`garage_a` + `front`) is the committed example `docs/examples/interior_paths.example.json`. Install
it: copy it to `/config/universal_room_automation/interior_paths.json` (Samba/SSH), then press
`button.ura_reload_interior_paths` (or restart); `path_map_source` should read
`interior_paths.json (schema 1, 19 edges)` (pinned by
`test_interior_paths.py::test_example_file_installs_on_this_house`). Until it is installed the house
has no path map (no runtime reader in Phase 1, so no behaviour change). First load at `EVENT_HOMEASSISTANT_STARTED` (or at once on an entry reload); re-validated on
`entity_registry_updated` (debounced `INTERIOR_PATH_MAP_REVALIDATE_DEBOUNCE_S`, 30 s) while the file
is not installed; `button.ura_reload_interior_paths` reloads. Provenance on the Outside: Open Tracks
sensor: `path_map_source`, `path_map_validation`, `path_map_sha256` (installed file only),
`path_map_doors`. Phase 1 has NO runtime reader; `door_interior_neighbours` and its readers are
untouched. The pure scorer `interior_paths.score_path` is shared with offline scripts. Learned
co-detections are a report only: `AUDIT_interior_path_map_learned_vs_operator.md`.

### 4.5a Person sightings (FACE-ARRIVAL-REBUILD-1 D1 + D4, branch `feature/person-sightings-p1`, NOT deployed)

**CORRECTION 2026-11-13: the rule "the census and sightings never feed each other" (person-sighting plan §2A) is
RETIRED** (operator, CLAUDE.md d1d7b387: "past its usefulness"). Replacement: sightings, interior vision included, MAY
feed F2 (`PersonCensus`), but only through ONE deconfliction function that dedups by evidence source, so no face or
body is counted twice. The function and the plans that feed it: `docs/planning/ARC_identity_vision_census_map.md` §3.
Code wins: no sighting-to-census path exists in code today; the census face legs dedup synthetic legs by
`(canonical_slug, engine, base_stem)` (`camera_census.py:3576-3588`) and the identified union canonicalises names
(`camera_census.py:2533-2540`). Unchanged: a crossing is not a sighting; access never acts on F4 alone.

`person_sighting.PersonSightingProducer` (built by `PresenceCoordinator._setup_person_sightings` in
`async_setup`, ticked from `_periodic_inference`, torn down in `async_teardown`) emits
`SIGNAL_PERSON_SIGHTING` with a frozen `PersonSighting`: "P was seen at camera/room/house zones at
`ts` (recognition time), provenance, confidence". ONE emit function, three sources:
- **(a)** the census MQTT face bridge: `_on_frigate_face_msg` calls `_after_face_latch` once per message
  after the latch loop, which appends the D4 ring entry and calls every callback in
  `hass.data[DOMAIN]["face_latch_callbacks"]` (read per message, so a census rebuild keeps the
  registration). `synthetic = True`.
- **(b)** face-name sensor state changes on the operator's `zone_cameras` picks, resolved with
  `CameraResolver.resolve_pick_to_fusions` (camera-integration pick -> device ladder; URA fused room
  pick -> that room's `CONF_ROOM_CAMERAS` -> ladder) and `face_name_entities_for_device` per fusion
  source. A restore edge (`old_state` None or HA `unavailable`/`unknown`) is not a recognition;
  Frigate's own `Unknown` -> name is. `_N` picks resolve (no flag).
- **(c)** `ura_person_egress_event` with `person_id` and `identity_provenance` in face / ble+face
  (projected, never re-decided; `ble` / missing provenance / ambiguous never; exit backfill never).
**Face Recognition switch (review A2 fix-up):** with the operator's Face Recognition switch OFF
(presence `_face_recognition_enabled`, kept current by its `SIGNAL_URA_FACE_RECOGNITION_CHANGED`
handler) sources (a) and (b) emit nothing (counted `face_recognition_off`), so no `camera_face`
arrival, and no sighting writes the zone last-face display fields (develop gated the v3.19 path the
same way). Source (c) egress sightings still emit (the transit validator's identity, not this
switch's). A same-state face-sensor update (attributes only) is ignored (A3).
Filters are evidence-only: `_face_suppressed_now()`, sentinel names, the boot drop
(`ts < presence setup + PERIMETER_EGRESS_ARRIVAL_BOOT_EXCLUDE_S`, all sources), the ONE mapper
`_canonical_person_slug` with an explicit tracked-slug membership test (`guest:*` and passthrough
names are counted, never emitted). Dedup key `(slug, canonical_camera_key)`; fixed 60 s window
(`FACE_SIGHTING_DEBOUNCE_S`) across sources; a later non-synthetic copy only upgrades the
last-sighting store. `camera_resolver.canonical_camera_key(fusion)` = min device_id over the
fusion's full source set, so a Protect pick and its Frigate egress twin are ONE camera. Interior
confidence `CONFIDENCE_MEDIUM` (0.6); egress copies the producer's tier. Each sighting carries
`person_state_at_emit` and `census_would_veto` (the census's own predicate,
`face_person_would_be_vetoed` -> `_face_latch_veto_source`, extracted from
`_get_face_recognized_person_names` unchanged): a face of an away resident IS a sighting but not a
census identity (named concept split). Readers: `PresenceCoordinator.get_last_person_sighting(s)`
(RAM; display consumers since PHONE-LEFT-BEHIND-CAMERA-LEG-1, branch `feature/phone-left-behind-camera`,
NOT deployed: the `*_phone_left_behind` attributes `last_camera_sighting_at` / `last_sighting_*` and the
`*_likely_next_room` `camera_last_seen` / `camera_last_room` attributes; neither verdict nor prediction
reads them), the tracker display fields `_last_face_recognized` (now the slug) / `_last_face_time`, and the
D4 diagnostics on `sensor.ura_presence_house_state` (all unrecorded): `face_sightings_today`,
`face_sightings_by_source`, `face_sighting_last`, `face_sighting_unmapped_names`,
`egress_non_face_skipped`, `multi_pick_messages`, `face_sighting_picks_resolved` /
`_unresolved` (with reason). Sightings feed NO census, inference, guest gate or NM, and no access
consumer may act on one alone. Re-resolution: a rebuilt resolver or a changed pick set (next tick),
`EVENT_HOMEASSISTANT_STARTED`, and an add-only retry of unresolved picks every
`FACE_SIGHTING_PICK_RERESOLVE_S` (300 s).
**D4 trip-wire `face_sighting_zero` (HIGH):** denominator = the census ring
`_frigate_face_named_ring` (post-sentinel, created only while `FACE_SIGHTING_ENABLED`) entries in the
last `FACE_SIGHTING_ZERO_WINDOW_H` (24) AND at or after this producer's setup +
`PERIMETER_EGRESS_ARRIVAL_BOOT_EXCLUDE_S` (600 s; the ring survives a restart's boot drop and a presence
re-setup, review A1) whose name maps to a tracked resident, whose stems join a
resolved pick, and that were not appended under face suppression; numerator = interior sightings.
Denominator >= `FACE_SIGHTING_ZERO_MIN_FACES` (10) with 0 sightings pages once (RAM latch, re-armed
when sightings resume; silent while the Face Recognition switch is OFF). `face_arrival_zero` (LOW) is armed only with interior arrivals on. Kill
switch for the whole producer: `FACE_SIGHTING_ENABLED` (rung 1). Live (D0, 2026-11-12): 7 of 8 picks
resolve; Garage A's fused pick is `room_cameras_empty` until the operator sets its room cameras.

### 4.6 DB tables (from `database.py`)

`person_entry_exit_events` (`database.py:793-808`) — the egress
crossing record:

```
id INTEGER PRIMARY KEY AUTOINCREMENT
timestamp DATETIME NOT NULL
person_id TEXT              -- NULL when no fresh face joined
event_type TEXT NOT NULL
direction TEXT NOT NULL     -- entry / exit / ambiguous
egress_camera TEXT NOT NULL
confidence REAL NOT NULL
-- indexes: idx_entry_exit_timestamp, idx_entry_exit_person(person_id, timestamp)
```

`person_visits` (`database.py:703-719`) — interior room-visit ledger,
written by `PersonCoordinator._log_person_room_change`:

```
id, person_id NOT NULL, room_id NOT NULL,
entry_time NOT NULL, exit_time, duration_seconds,
confidence REAL, detection_method TEXT, transition_from TEXT
-- indexes: person+time, room+time
```

The `confidence REAL` column already exists on
`person_entry_exit_events` — reused as the ADVISORY score for the
egress-identity JOIN work (§5), no schema change required.

---

## 5. The egress-identity JOIN and the 6.0.0 gate

`v6.0.0 IDENTITY-DRIVEN AUTONOMY` (the census/identity arc reaching
real actuation — guest gate consuming door-identity, arrival/departure
keyed to `person_id`, egress identity) is anchored on this JOIN
working. The PRODUCER is now BUILT (§5.2, v5.91.4 pending deploy);
consumer wiring stays coverage-gated on the measured post-deploy yield
(§5.5).

### 5.1 The measured reality (as of 2026-08-28)

- `person_entry_exit_events`: **7,010 rows all-time, 0 with a
  populated `person_id`** (was 6,883 on 08-24; grew, still 0/all).
  Never once populated since 2026-03-04. The signed-lag measure-first
  probe (2026-08-28) put the achievable attach rate at **~63%** under
  an interior-fusion + asymmetric window (exit `[-30,+180s]`, entry
  `[-300,+60s]`) with abstain-on-ambiguity (~28% of attaches have ≥2
  in-window names) — vs today's ~0. `person_id` stays ADVISORY.
- Post-arm (2026-08-18+): **112 crossings, zero with a face inside
  the 60s match window** — no opportunity to stamp even once.
- **This is not a wiring bug.** `egress_identity_enabled = True` on
  the integration entry; `switch.ura_name_people_at_doors` has been
  ON since 08-18; registry resolution of all five egress cameras is
  correct (including garage_b's unsuffixed person entity). There are
  simply no faces to match at the crossing site inside the window.

Two producer facts explain it:
1. **Geometry:** door/garage cameras produce named faces
   infrequently (~3/day per camera when healthy) — sparse, but NOT
   a structural zero (the "bad on door cameras" story was refuted
   2026-08-24; see the second amendment to
   `reference_egress_face_coverage_7pct_not_a_ceiling`).
2. **Current fault:** Frigate face recognition is down house-wide
   since ~2026-08-21 (see §2.2). Person detections stayed healthy —
   this is a face-subsystem fault, not storage/ingest.

### 5.2 The producer redesign — BUILT (v5.91.4, pending deploy)

Same-stem + 60s was too tight. The producer is now built on
`feature/egress-identity-producer` (ships as v5.91.4, "shipped pending
deploy" — orchestrator confirms the version). It stamps `person_id`
(canonical URA slug via `_canonical_person_slug`) **plus an advisory
identity confidence** on both `person_entry_exit_events` (the DB row,
reusing the existing `confidence REAL` column — no migration) and the
`ura_person_egress_event` bus event. The capability:

- **Interior-fusion:** consults the freshest interior recognized-face
  across cameras near the crossing (family_room has the strongest
  Frigate named-face signal), not just the egress-camera stem.
- **Direction-keyed asymmetric window:** a wider positive lag (interior
  face BEFORE egress) than negative — "person walked past family_room,
  then out the door" is far more common than the inverse (probe:
  exits face-lead median +53s, entries face-trail median −14s).
  Measured window exit `[-30,+180s]`, entry `[-300,+60s]`.
- **`base_stem` independence predicate:** two legs count as
  independent corroboration only when they resolve to DIFFERENT
  physical cameras (distinct base stem), so two engines on ONE camera
  do not masquerade as two witnesses.
- **Abstain on conflicting names:** when ≥2 distinct resident names sit
  in-window (~28% of attaches), the producer emits NO identity rather
  than guess (nearest-in-time + confidence-margin tie-break, else
  abstain). This ABSTAIN is load-bearing.
- **Measured ceiling of the fix:** ~63% attach when face recognition is
  healthy (7d floor ~27–31%, 48h re-tuned ceiling ~63%).

`person_id` remains **ADVISORY** — not a hard trust input. Downstream
identity consumers MUST accept NULL and use the graceful-anonymous rule
(§3), and MUST honor the confidence thresholds in §5.5.

### 5.3 The confidence model (v5.91.4)

The advisory confidence stamped alongside `person_id` encodes HOW the
identity was corroborated:

| Constant | Value | Meaning |
|---|---|---|
| `CONFIDENCE_HIGH` | **0.9** | ≥2 legs resolving to the SAME canonical slug on DIFFERENT physical cameras (distinct `base_stem`) — genuine multi-camera corroboration. |
| `FACE_MATCH_CORRELATED_BOOST` | **0.75** | Same physical camera, two engines agree (e.g. Frigate + Protect leg on one camera). Correlated evidence, not independent. |
| `CONFIDENCE_MEDIUM` | **0.6** | A single leg — one recognizer, no corroboration. |

`person_id` is ADVISORY at every level; even 0.9 is not authoritative
(consumers still accept NULL and degrade gracefully).

### 5.4 Observability + control surface

- **Kill switch:** `switch.ura_name_people_at_doors` (fresh-read at
  every call; `switch.py:190`, `camera_census.py:2969`).
- **Options-flow toggle:** `egress_identity_enabled` on the
  integration entry (default ON; `const.py:2175`,
  `config_flow.py:2970`).
- **Reuse the existing `confidence REAL` column** on
  `person_entry_exit_events` as the advisory score — no migration.
- **Face lookup miss counter:** `_face_lookup_missing_count`
  (`camera_census.py:3201`) increments on every fail-CLOSED lookup so
  operators can distinguish "no face" from "face resolver broken".
- **`person.<slug>` = `not_home` veto** (see §4.3) — mirrored in
  `camera_census._get_face_recognized_person_names` (~`camera_census.py:5893-5940`).
  Since CENSUS-BLE-OVER-FACE-1 (branch `fix/census-ble-over-face`, shipped v5.103.91) that interior
  latch also drops a face for a GPS+BLE adult the BLE-leads rule overruled
  (`person_coordinator.person_state_for_trust` → `not_home`), while switch BLE Leads Home/Away is on
  and rung-1 `CENSUS_FACE_LATCH_FOLLOWS_BLE_LEADS` is True. BLE decides presence; face confirms.
  The egress face-leg veto and `transit_validator` stay on raw state; a mislabelled entry crossing
  can still register a slug via the egress union.

### 5.5 Consumer map + doctrine

Post-ship consumer-gap audit 2026-08-28 (`AUDIT_census_identity_supersession_and_consumers.md`).

**The REAL consumers today (v5.91.4):** exactly four DISPLAY sensors read
`person_id` off the `ura_person_egress_event` bus event, each falling
back to `"unidentified"` when it is NULL:

| Sensor | file:line | Reads |
|---|---|---|
| `PersonsEnteredTodaySensor` | `sensor.py:4268` | `person_id` → entries list / count |
| `PersonsExitedTodaySensor` | `sensor.py:4386` | `person_id` → exits list / count |
| `LastPersonEntrySensor` | `sensor.py:4464` | `person_id` → last-entry name |
| `LastPersonExitSensor` | `sensor.py:4512` | `person_id` → last-exit name |

**CORRECTED (FACE-ARRIVAL-REBUILD-1 D5, code wins): `identity_confidence` HAS a live reader.**
`EgressDirectionTracker._arrival_departure_notify` (`transit_validator.py:2603`; the class is `EgressDirectionTracker` at `:1007`, not `TransitValidator`, corrected 2026-11-13; called from
`_resolve_direction`) names the person in "X arrived / left" only at `identity_confidence >=
ARRIVAL_NAME_CONFIDENCE_THRESHOLD` (0.75), else "Someone" (notification-naming class, (b) below).
It is the ONE arrival/departure notification site. Since D1 the person-sighting producer (§4.5a)
also reads the bus `identity_confidence` / `identity_provenance` (display-class: it copies them
into an egress sighting). `agreement_class` still has no decision reader. Egress identity feeds no
arrival, and the security expected-arrival suppression is done by an independent non-face edge
(`face_input_corroborated`), never by the face (F7 resolved without a doctrine change).

**(a) SAFETY DOCTRINE — the invariant for any identity consumer.**
Egress identity may only **DE-ESCALATE or ANNOTATE** a security
decision, and only at confidence **≥0.9**. It may NEVER **escalate or
actuate** from identity, and NEVER **suppress** a security action at
0.6/0.75. Rationale: `person_id` is advisory and coverage-sparse; a
wrong-but-confident name that could arm, lock, or unlock is a footgun
(the arc's own double-count history). Naming a KNOWN resident to soften
an alert is safe; acting because a name appeared is not.

**(b) Confidence-threshold-by-consumer-class:**

| Consumer class | Min confidence to act | Direction of effect |
|---|---|---|
| **Security suppress / de-escalate** | **≥0.9** | de-escalate/annotate only — never escalate, never suppress below 0.9 |
| **Notification naming** | **≥0.75** | name the person in the message; anonymous below |
| **Display** | **none** | show name-or-"unidentified"; never a trust decision |

**(c) MEASURE-BEFORE-BUILD gate.** Before building ANY new consumer,
re-measure the REAL production rate of `person_id` on the live
producer (garage / family-room entry path, per the signed-lag probe),
NOT the old front-door figure. A sparse producer caps every consumer's
value and may argue for a better producer, not more consumers. Every
consumer card carries this gate.

---

## 6. Known gaps — where the truth lives now

This manual is now the canonical reference for the domain. Open work
lives on cards:

| Card | What |
|---|---|
| **`EGRESS-IDENTITY-JOIN-GAP-1`** | Face recognition works but egress crossings carry no identity — `person_entry_exit_events.person_id` is 0 of ~7,010 rows all-time. Root cause: same-stem 60s face-join never matches (door cams rarely recognize). Fix = interior-fusion + asymmetric signed-lag window (~63% ceiling, measured). Blocks all identity consumers. |
| **`EGRESS-IDENTITY-PRODUCER-EMITS-NOTHING-1`** | Blocking parent for the eight identity-consumer cards below — the producer emits nothing to consume today. |
| **`PERIMETER-ALERT-NAME-PERSON-1`** | Perimeter alerts still say "person detected" when identity is known. |
| **`GUEST-GATE-DOOR-IDENTITY-1`** | Guest gate ignores door-identity. Stays parked. Since GUEST-MODE-SPLIT-VISITORS-1 (shipped v5.108.0, branch `feature/guest-mode-split`) GUEST no longer reads instantaneous evidence at all: it follows a night-stay latch over the URA DB: one night with ≥ 0.25 non-resident occupancy of a guest room plus ≥ 0.10 of that room's day before (residents subtracted by BLE), exit after min(2, n) straight empty nights, a 7-day one-night re-entry grace after a stay ends by empty nights, and a "Guest left" button that ends the stay (see `docs/Coordinator/GUEST_MODE.md`). Faces, Path A and WiFi never enter GUEST; Path A feeds only `visitors_present` (display). Door identity could later shorten the arrival-day gap (same revival trigger as plan §2.4). |
| **`ARRIVAL-DEPARTURE-NOTIFY-1`** | No arrival/departure notification consumes `person_id`. |
| **`EXTERIOR-GUEST-FACE-FASTFOLLOW-1` D2** | Protect Alarm Manager webhook `ura_kp_face_probe` receiving side verified; Protect-side rule delivering empty payloads. |
| **`EXTERIOR-GUEST-EGRESS-1`** | Face-independent approach-track FALLBACK — DEFERRED, gated on the identity path proving insufficient. Do NOT re-recommend this off the sparse-face number. |
| **`PERIMETER-PHANTOM-XCORR-1`**, **`FRIGATE-LEG-NAMING-1`** | Dead-leg / cross-corroboration hygiene. |
| **`PERIMETER-FRIGATE-MQTT-DIRECT-1`** + **`FRIGATE-FACE-BRIDGE-DEAD-PREFIX-1`** | Shipped v5.108.1: Frigate events and the face bridge read MQTT directly on the runtime prefix (§1.3, §4.5). Live check: L1-L5 in `README_v5.108.1.md`. |

Audit / research trail:
`docs/planning/AUDIT_census_identity_supersession_and_consumers.md`,
`AUDIT_census_accuracy_regression.md`,
`AUDIT_frigate_face_resolution.md`,
`AUDIT_frigate1_sunset.md`,
`AUDIT_frigate1_retirement_inventory.md`,
`AUDIT_frigate_dead_leg_correctness.md`,
`AUDIT_perimeter_fp_correlation.md`,
`AUDIT_exterior_census_supersession.md`,
`PLANNING_room_camera_fusion.md`,
`PLANNING_census_fusion_policy.md`,
`PLANNING_paper_and_oss_fusion_library.md`,
`PLANNING_v4.7.18_census_service_shared_refactor.md`,
`PLANNING_census_overcount_dedup_decay.md`,
`PLANNING_census_accuracy.md`,
`RESEARCH_guest_actuation_and_census.md`,
`RESEARCH_census_vs_guest_separation.md`.

Memory bodies (verify before quoting — memories are point-in-time):
`reference_frigate1_retired_2suffix_permanent`,
`reference_frigate_ghost_evidence_chain`,
`project_frigate_mqtt_topic_collision`,
`reference_pooloverhead_four_integrations`,
`reference_egress_face_coverage_7pct_not_a_ceiling`
(READ THE AMENDMENTS — the original conclusion was refuted twice),
`feedback_read_consumers_before_asserting_function`.

---

## 7. Sibling: Presence state of play

For the non-identity side of how URA sees people — room-level occupancy, BLE / Bermuda /
`private_ble_device` / IRK, the person_coordinator and `CONF_SCANNER_AREAS` scanner
ladder, the room coordinator's chatter / duty-cycle / fan-transition CREATION gate, D2
sustain demotion, fan pause-recheck, comfort-fan house-AWAY veto, `StateInferenceEngine`
(path α / path β / guest / sleep / arriving), the `_skip_first_automation` + boot-settle
gates, the room-switch resolver (v5.103.48 registry lookup) and the fan-noise mechanism
efficacy numbers measured 2026-10-11 — the canonical doc is
**`docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`**. It is the sibling of this
manual: identity / camera / census / fusion / egress stays HERE; everything else about how
presence is produced and consumed lives THERE. Agents touching presence-adjacent code read
it first, completely, before planning or building — and if the two docs ever disagree,
verify against the cited code and fix the stale one in the same turn.
