# Cycle 4.5 — Reconciliation: What We Left Out and Why

**Date:** 2026-02-24
**Status:** Decision Record (not a build plan)
**Context:** Cycle 4 shipped as "Slim" (v3.5.1). Cycle 6 was updated to work without per-room fusion. This document reconciles everything that was excluded and justifies each decision.

---

## How to Read This Document

Each item below was part of the original full Cycle 4 plan (`PLANNING_v3.5.1_CYCLE_4.md`) or the original Cycle 6 plan (pre-update). The slim versions shipped instead. This ledger exists so that:

1. No design work is lost — every excluded item has a clear reference to its full design
2. Future decisions about adding these features have explicit criteria, not gut feelings
3. If something breaks in production because we went slim, this document tells you exactly which excluded feature would have prevented it

---

## ITEMS CUT FROM CYCLE 4

### 4-A: Per-Room Camera-BLE Fusion Math in coordinator.py

**What it was:** ~60 lines of fusion code in `_async_update_data()`. Camera person count merged with BLE person identity per room. Camera added as a weighted signal (0.85) alongside motion (0.50), mmWave (0.60), and BLE (0.70). Produced `STATE_ROOM_IDENTIFIED_PERSONS`, `STATE_ROOM_GUEST_COUNT`, `STATE_ROOM_TOTAL_PERSONS` per room.

**What shipped instead:** Camera-extends-occupancy (~15 lines). Binary override: if camera still sees someone after motion timeout, room stays occupied. No fusion math, no per-room person count, no guest detection.

**Why it was cut:**
- coordinator.py is the hottest code path — runs every 30s for every room. Adding camera entity resolution + BLE lookup + fusion math to every cycle adds latency.
- Cameras only cover 3-4 of ~16 rooms. The fusion code does nothing for most rooms but add branches.
- Guest math (`camera_count - ble_count`) produces phantom guests during BLE transition latency (10-60s). This is worse than no guest data because it triggers false automations.
- Creates a second counting system alongside `camera_census.py`. Two systems that can disagree confuses automation writers.

**What would justify adding it back:**
- A user has cameras in >50% of their rooms (not just common areas)
- The house-level unexpected person sensor produces false positives that can only be resolved with room-level data
- BLE transition latency is reduced below 5 seconds (eliminating phantom guests)
- A clear automation use case requires knowing "how many people are in THIS specific room" (not just "is someone here")

**Full design reference:** `PLANNING_v3.5.1_CYCLE_4.md`, Section 1

---

### 4-B: Per-Room Camera Person Count Sensor

**What it was:** `sensor.{room}_camera_person_count` — raw camera count per room, readable by automations.

**What shipped instead:** Nothing. Camera data is only used for the binary occupancy override.

**Why it was cut:**
- Depends on 4-A (per-room fusion). Without fusion, there's no per-room camera count in the coordinator data.
- Most rooms have no cameras, so most instances of this sensor would show 0 permanently.
- The house-level census sensors (`sensor.ura_persons_in_house`) provide the aggregate count.

**What would justify adding it back:**
- 4-A ships first
- A concrete automation requires per-room person count (e.g., "if 3+ people in kitchen, turn on exhaust fan")

**Full design reference:** `PLANNING_v3.5.1_CYCLE_4.md`, Section 1.1 (coordinator data keys), Entity table

---

### 4-C: Camera as Weighted Occupancy Signal (0.85)

**What it was:** Camera person detection integrated into the coordinator's confidence calculation alongside motion, mmWave, and BLE. Camera weight 0.85 means a camera detection alone would produce high-confidence occupancy.

**What shipped instead:** Binary override. Camera either overrides vacancy (ON) or doesn't (OFF). No contribution to the confidence score.

**Why it was cut:**
- The confidence weighting system was designed for sensors that are always present. Camera is only present in some rooms. Adding a 0.85 signal that appears in some rooms but not others creates inconsistent confidence profiles across rooms.
- The binary override achieves the primary goal (prevent false vacancy when camera sees someone) without touching the confidence machinery.
- Changing the confidence calculation affects all downstream sensors and automations that read confidence values.

**What would justify adding it back:**
- Confidence values are used in automations (today they're mostly diagnostic)
- A scenario where the binary override is too coarse — e.g., camera sees someone at low confidence but can't override because it only works as on/off

**Full design reference:** `PLANNING_v3.5.1_CYCLE_4.md`, Section 1.1

---

### 4-D: Per-Room Guest Count (STATE_ROOM_GUEST_COUNT)

**What it was:** `room_guest_count = max(0, camera_person_count - len(ble_identified_persons))` per room. Enabled room-specific guest detection.

**What shipped instead:** House-level guest estimate via `ZoneGuestCountSensor` (house camera total minus house BLE total).

**Why it was cut:**
- Phantom guest problem (see 4-A). Per-room is noisier than house-level because BLE transitions create per-room mismatches that average out at house level.
- Most rooms have no cameras, so per-room guest count is 0 for most rooms.
- No automation use case identified for "how many guests are in THIS room" vs "are there guests in the house."

**What would justify adding it back:**
- BLE transition latency reduced to under 5 seconds
- A use case like "if a guest is in the game room, disable personal lighting preferences" that can't be served by house-level

**Full design reference:** `PLANNING_v3.5.1_CYCLE_4.md`, Section 1.1, Section 3

---

### 4-E: Zone Sensors Reading Per-Room Fusion Data

**What it was:** `ZoneIdentifiedPersonsSensor` and `ZonePersonCountSensor` reading `STATE_ROOM_IDENTIFIED_PERSONS` and `STATE_ROOM_TOTAL_PERSONS` from each room coordinator in the zone.

**What shipped instead:** `ZoneIdentifiedPersonsSensor` reads from `person_coordinator` (BLE only). `ZoneGuestCountSensor` uses house-level census. Zone person count uses BLE-tracked data.

**Why it was cut:**
- Depends on 4-A. Without per-room fusion data, zone sensors have no room-level fusion to aggregate.
- The house-level approximation is acceptable for zones that span camera-covered and non-camera rooms.

**What would justify adding it back:**
- 4-A ships first
- Zone-level automations need per-room precision (e.g., "upstairs zone has 2 identified + 1 guest" vs "house has N guests")

**Full design reference:** `PLANNING_v3.5.1_CYCLE_4.md`, Section 2

---

## ITEMS CUT FROM CYCLE 6

### 6-A: Per-Zone Unidentified Count Using Per-Zone Camera Data

**What it was:** `sensor.{zone_name}_unidentified_count` using `census.get_zone_result(zone_id)` to get real per-zone camera counts.

**What the updated Cycle 6 does instead:** Uses house-level census (`persons_in_house - ble_identified_total`) as an approximation. The sensor is renamed to `sensor.ura_unidentified_persons` (house-level, not per-zone).

**Why it was cut:**
- `PersonCensus.get_zone_result()` doesn't exist. The census system operates at house level (interior + exterior), not per-zone.
- Without per-room fusion (4-A), there's no per-zone camera breakdown to aggregate.
- Adding per-zone census would require significant changes to `camera_census.py` — essentially building zone-level counting on top of the house-level system.

**What would justify adding it back:**
- Per-room fusion (4-A) ships, providing room-level camera counts
- A zone-level automation needs precise unidentified counts per zone (not house-level)
- `camera_census.py` is extended to support zone-level census aggregation

**Full design reference:** `PLANNING_v3.5.2_CYCLE_6.md` (original, pre-update), Section 3.4

---

### 6-B: Room-to-Room Topology for Transit Path Validation

**What it was:** `TransitValidator._get_shared_space_cameras_between(room_a, room_b)` — returns cameras that physically sit between two rooms. Uses room adjacency to compute the expected camera path.

**What the updated Cycle 6 does instead:** Option C — `_get_shared_space_cameras()` returns ALL shared-space cameras. A sighting on any shared-space camera within the checkpoint window counts as path support. Less precise but requires no topology data.

**Why it was cut:**
- No room adjacency data exists in URA. Rooms don't have neighbor relationships.
- Building a topology graph requires either hardcoded mappings (fragile) or a new config flow step (heavy).
- The any-shared-space-camera approach works "well enough" — false negatives (missed path support) are harmless (transit still records with BLE-only confidence). False positives (camera in wrong area counted as path support) slightly inflate confidence but don't break anything.

**What would justify adding it back:**
- Room adjacency data is added to URA (possibly as part of v3.6.0 domain coordinators)
- Path validation is producing too many false "path_plausible" results because unrelated camera sightings are being attributed to transits
- A security use case requires knowing the exact path someone took through the house

**Full design reference:** `PLANNING_v3.5.2_CYCLE_6.md` (original, pre-update), Section 1.1

---

### 6-C: Camera Sees Different Person Than BLE Claims (Identity Mismatch as Confidence Penalty)

**What it was:** A -0.30 confidence delta on the transition when the camera face recognition identifies a different person than BLE claims made the transit.

**What the updated Cycle 6 does instead:** Identity validation is separated from path validation. A camera-BLE identity mismatch sets `identity_status: "mismatch"` as an attribute but does NOT penalize the transition's path confidence. The two concerns are decoupled.

**Why it was cut:**
- An identity mismatch doesn't invalidate the transit. Person A's BLE device going from office to kitchen is a real transit regardless of who the camera sees on the path.
- A camera seeing person B on the hallway doesn't mean person A didn't also use the hallway — the camera may have caught a different person at a different moment.
- Mixing identity and path confidence in one number makes the confidence score uninterpretable.

**What would justify adding it back:**
- Identity confidence becomes a first-class metric in the system (not just an attribute)
- Face recognition accuracy reaches >95% (making mismatches a strong signal rather than noise)
- A security use case requires "camera says X but BLE says Y" to reduce trust in the transition

**Full design reference:** `PLANNING_v3.5.2_CYCLE_6.md` (original, pre-update), Section 1.1 delta table

---

## SUMMARY TABLE

| ID | Item | Cut From | Risk of Not Having It | Trigger to Revisit |
|----|------|----------|----------------------|-------------------|
| 4-A | Per-room camera-BLE fusion | Cycle 4 | Low — house-level census covers most cases | >50% rooms have cameras; house-level false positives |
| 4-B | Per-room camera person count sensor | Cycle 4 | Low — no identified automation use case | 4-A ships; "how many people" automation needed |
| 4-C | Camera as weighted occupancy signal | Cycle 4 | Very low — binary override works | Confidence values used in automations |
| 4-D | Per-room guest count | Cycle 4 | Low — house-level guest estimate exists | BLE latency <5s; room-specific guest automation |
| 4-E | Zone sensors from per-room fusion | Cycle 4 | Low — BLE + house-level census works | 4-A ships; zone automations need room precision |
| 6-A | Per-zone unidentified count (real data) | Cycle 6 | Low — house-level approximation exists | 4-A ships; zone-level automation needs precision |
| 6-B | Room-to-room topology for path validation | Cycle 6 | Very low — any-camera approach works | Room adjacency data added; security path tracking needed |
| 6-C | Identity mismatch as confidence penalty | Cycle 6 | None — was architecturally wrong | Identity becomes first-class metric; face reco >95% |

---

## DECISION LOG

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-02-24 | Ship Cycle 4 as Slim | Camera coverage is sparse; per-room fusion adds complexity with marginal benefit. See PLANNING_v3.5.1_CYCLE_4_SLIM.md. |
| 2026-02-24 | Update Cycle 6 to remove per-room fusion dependencies | Cycle 6 was written assuming full Cycle 4 shipped. Updated to work with house-level census and shared-space cameras only. |
| 2026-02-24 | Separate path validation from identity validation | Mixed confidence (path + identity in one number) made the score uninterpretable. Decoupled into `path_confidence_delta` and `identity_status`. |
| 2026-02-24 | Add face recognition config toggle | Allows homes without face recognition to skip identity validation cleanly. Default off. |
| 2026-02-24 | Use Option C for room topology (any shared-space camera) | No adjacency data exists; precise path validation deferred until room graph is available. |
