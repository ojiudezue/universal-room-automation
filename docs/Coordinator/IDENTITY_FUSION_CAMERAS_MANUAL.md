# Identity, Fusion and Cameras — Operator Manual

**Audience:** the homeowner running URA, and any agent scoping work that
touches identity, camera fusion, the census, guest inference, or the
egress/perimeter pipeline.
**Scope:** the CANONICAL reference for how URA sees people. Camera
platform roles, identity sources and their real coverage, the
cross-modal fusion doctrine, the census + resolver architecture, the
egress-identity JOIN and the 6.0.0 gate that depends on it.
**Current through:** URA v5.91.3 (`camera_census.py:3`).
**Ground truth verified:** 2026-08-28 (code + memory bodies).

This is NOT a code walkthrough. Sibling of
`ENERGY_COORDINATOR_MANUAL.md`, `HVAC_COORDINATOR_MANUAL.md`,
`CM_MANUAL.md`, `PRESENCE_COORDINATOR.md`. For fusion research
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
(`camera_census._resolve_face_entity_id`, `camera_census.py:2615-2648`
— returns `None` if neither variant has a usable state, increments
`_face_lookup_missing_count` for observability). The resolver's
suffix-tolerant match helper is
`camera_resolver._has_any_suffix_stripped` (`:317-327`).

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

- **Status (verified 2026-08-28 on a live crossing):** HA receiving
  side WORKS — the probe (`ura_kp_face_probe`, enhanced to capture
  `json`/`form`/`query`/`content_type` separately) captured a synthetic
  JSON POST perfectly. But a REAL Protect Alarm Manager POST on a live
  face crossing (07:27:28) delivered an **empty payload** — Protect is
  firing the webhook but sending no parseable JSON/form body. **The fix
  is Protect-side:** the Alarm Manager rule's webhook *action* must POST
  an explicit `Content-Type: application/json` body carrying the face
  name + confidence. Until then, egress identity is Frigate-only.
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
`camera_resolver.py:1201-1224`), `enumerate_platform_cameras`.

### 4.2 `CameraIntegrationManager` + `PersonCensus` (`camera_census.py`)

The census authority. Dual-zone (interior + property), publishes
identified / unidentified / on-property counts, holds+decays after
peaks, cross-validates across BLE + face + camera-person, downgrades
on divergence. Face-name reader is
`_resolve_face_entity_id` (`camera_census.py:2615-2648`),
canonical-slug helper `_canonical_person_slug` (URA-slug namespace so
face / ble / DB / `person.<slug>` all agree).

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

Direction gating on the census union feed
(`transit_validator.py:1298-1310`):
- `entry` → register the identity into the census union.
- `exit` → EVICT any prior registration for this identity within
  `EGRESS_FACE_UNION_TTL_S`.
- `ambiguous` → neither register nor evict (matches DB-write gate).

### 4.4 `PersonCoordinator` (`person_coordinator.py`) — interior identity

Per-person GPS/WiFi/BLE fusion, `_log_person_room_change` writes to
`person_visits`. BLE fleet-liveness gate at
`person_coordinator.py:67` (`BLE_FLEET_LIVENESS_WINDOW_S = 90`).
Presence details in `PRESENCE_COORDINATOR.md`.

### 4.5 Perimeter surfaces

`perimeter_enrichment.py` / `perimeter_alert.py` — alert routing off
the DetectionLeg output of `CameraResolver.resolve_detection_legs`
(replaced three generations of hand-rolled slug helpers per the
Cycle-3 resolver-legs work, 2026-08-07). Alerts today say "person
detected" — the identity-consuming version is the card
`PERIMETER-ALERT-NAME-PERSON-1` (see §6).

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
working. It currently doesn't.

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

### 5.2 The producer redesign under design

Same-stem + 60s is too tight. Two shipped/pending elements form the
join upgrade:

- **Interior-fusion:** consult freshest interior face across all
  cameras near the crossing (family_room has the strongest Frigate
  named-face signal), not just the egress-camera stem.
- **Asymmetric signed-lag window:** allow a wider positive lag
  (interior face BEFORE egress) than negative (interior face AFTER
  egress) — reflects "person walked past family_room, then out the
  door" being much more common than the inverse.
- **Measured ceiling of the fix:** ~63% when face recognition is
  healthy.

`person_id` on `person_entry_exit_events` remains **ADVISORY** — it
is not a hard trust input. Downstream identity consumers should use
the graceful-anonymous rule (§3).

### 5.3 Observability + control surface

- **Kill switch:** `switch.ura_name_people_at_doors` (fresh-read at
  every call; `switch.py:190`, `camera_census.py:2969`).
- **Options-flow toggle:** `egress_identity_enabled` on the
  integration entry (default ON; `const.py:2175`,
  `config_flow.py:2970`).
- **Reuse the existing `confidence REAL` column** on
  `person_entry_exit_events` as the advisory score — no migration.
- **Face lookup miss counter:** `_face_lookup_missing_count`
  (`camera_census.py:2647`) increments on every fail-CLOSED lookup so
  operators can distinguish "no face" from "face resolver broken".
- **`person.<slug>` = `not_home` veto** (see §4.3) — mirrored in
  `camera_census._get_face_recognized_person_names` (~`:3346-3366`).

---

## 6. Known gaps — where the truth lives now

This manual is now the canonical reference for the domain. Open work
lives on cards:

| Card | What |
|---|---|
| **`EGRESS-IDENTITY-JOIN-GAP-1`** | Face recognition works but egress crossings carry no identity — `person_entry_exit_events.person_id` is 0 of ~7,010 rows all-time. Root cause: same-stem 60s face-join never matches (door cams rarely recognize). Fix = interior-fusion + asymmetric signed-lag window (~63% ceiling, measured). Blocks all identity consumers. |
| **`EGRESS-IDENTITY-PRODUCER-EMITS-NOTHING-1`** | Blocking parent for the eight identity-consumer cards below — the producer emits nothing to consume today. |
| **`PERIMETER-ALERT-NAME-PERSON-1`** | Perimeter alerts still say "person detected" when identity is known. |
| **`GUEST-GATE-DOOR-IDENTITY-1`** | Guest gate ignores door-identity. |
| **`ARRIVAL-DEPARTURE-NOTIFY-1`** | No arrival/departure notification consumes `person_id`. |
| **`EXTERIOR-GUEST-FACE-FASTFOLLOW-1` D2** | Protect Alarm Manager webhook `ura_kp_face_probe` receiving side verified; Protect-side rule delivering empty payloads. |
| **`EXTERIOR-GUEST-EGRESS-1`** | Face-independent approach-track FALLBACK — DEFERRED, gated on the identity path proving insufficient. Do NOT re-recommend this off the sparse-face number. |
| **`PERIMETER-PHANTOM-XCORR-1`**, **`FRIGATE-LEG-NAMING-1`** | Dead-leg / cross-corroboration hygiene. |

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
