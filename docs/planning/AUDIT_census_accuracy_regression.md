# AUDIT: House Census Accuracy Regression (extends CENSUS-GUEST-FLOOR-1)

**Date:** 2026-08-15 · **Mode:** read-only (recorder + registry ro, code inspection)
**Symptom:** census reads 4 with ~10 people in the house. Operator: "used to be
more or less accurate given decay."

## Verdict

**H1 CONFIRMED — F2 (Frigate second-host) migration broke person-COUNT sensor
mapping.** The regression onset is exactly the F1 retirement (2026-08-13, entities
unavailable 11:37; entry deleted 08-15, FRIGATE-RETIRE-1 commit 49d54f381). All
surviving Frigate count sensors carry HA's `_2` disambiguation suffix
(`sensor.<cam>_person_count_2`), which every count-sensor matcher in the codebase
misses via strict `endswith("_person_count")`. Census silently degraded from true
per-camera counts to the binary fallback (max 1 person per camera), so
`unrecognized = max(0, camera_total − identified)` pins at ~0 and the census can
never exceed the identified (BLE/face) count. H2 partially explanatory of the same
event, H3 and H4 refuted (details below).

## Timeline (recorder, mode=ro)

| Date | census daily max | Note |
|---|---|---|
| 08-08 | 6 | F2 host added 08:16 (`_2` entities born); F1 count sensors still live |
| 08-09 → 08-12 | 7 / 6 / 6 / 6 | dual-host; F1 non-`_2` count sensors valid until 08-12 23:35 |
| 08-13 | **4** | F1 entities → `unavailable` 11:37; census high-water collapses |
| 08-14 → now | 4 | pinned at identified count |

Live cross-check (orchestrator, 08-15 01:51–02:32 UTC): `playroom_person_count_2=4`,
`master_hallway_person_count_2=4`, `staircase_person_count_2=3` near-simultaneously,
yet census 24h distribution was 0/2/3/4 — never above identified. Mathematically
impossible unless the camera leg was counting ≤1 per camera (binary fallback) or
skipping cameras entirely.

## H1 — CONFIRMED (mechanism, file:line)

1. **Resolver count matching is `_2`-blind.**
   `camera_resolver.py:272` `_PERSON_COUNT_SUFFIX = "_person_count"`;
   `_scan_device_entities` (`camera_resolver.py:1288`, sensor branch) matches
   `_entity_name(eid).endswith(_PERSON_COUNT_SUFFIX)` — `sensor.X_person_count_2`
   fails. `_strip_disambiguation_suffix` (`camera_resolver.py:291`) exists but is
   NOT applied on this path. Result: `count_s=None` → `FusionSource.person_count_sensor=None`
   (`camera_resolver.py:806`) → census `CameraInfo.person_count_sensor=None`
   (`camera_census.py:582`).
2. **Person BINARY matching is equally `_2`-blind** (`_PERSON_SUFFIXES`,
   `camera_resolver.py:214`; strict `_has_any_suffix`, :313). Devices whose person
   occupancy binary is `_2`-only (live registry: 17 cameras incl. interior
   `playroom`, `upstairs_hall`) get `person_bs=None` AND `count_s=None` → "device
   contributes nothing to the fusion — skip" (`camera_resolver.py:796`) →
   **invisible to census entirely**, worse than binary fallback.
3. **Legacy census paths have the same blindness**: constructed id
   `sensor.{base}_person_count` (`camera_census.py:400-403`, :793-806) and fallback
   `endswith("_person_count")` (:407) — no `_2` variant exists to construct/match.
4. **Consumption site**: `camera_census.py:1404` — with `person_count_sensor` set,
   real integer counts flow; unset → binary on/off = max 1 per camera.
5. **Live registry (ssh, 08-15):** ALL 21 live Frigate `person_count` sensors are
   `_2`-suffixed; zero non-`_2` count sensors remain. Six devices (family_room,
   foyer_fisheye, garage_b, master_hallway, staircase, stairs_top) have a non-`_2`
   binary + `_2` count sensor: person detected but count unmapped → binary fallback.

Why it "used to be accurate": until 08-12 the F1 devices' non-`_2` count sensors
existed, matched, and reported real counts (recorder shows values up to 3 in the
08-08→08-12 window; census tracked 6-7).

## H2 — Cross-validation platform loss: NOT the regression driver

`house_source_agreement` logic at `camera_census.py:1556-1573`. The single-source
condition reflects the UniFi Protect leg's non-contribution, but the census total
collapse dates exactly to the F1 count-sensor loss, not to any Protect change in the
window. No fix to the Protect leg would restore >4 counts; H2 is a standing
diagnostic condition, not the 08-13 regression. (Not further pursued; re-open only
if counts stay low after the H1 fix.)

## H3 — F1 deletion removed still-referenced entities: REFUTED for census

Checked every URA config entry's camera/census/person keys against the live entity
registry: `camera_person_entities` (12) all present; `tracked_persons`,
`perimeter_cameras`, `room_cameras` all present. **Secondary finding (non-census):**
`egress_cameras` references `camera.garage_a` and `camera.garage_b`, both deleted
with the F1 entry — transit/egress consumers should be re-pointed to the F2 camera
entities.

## H4 — Shipped cycle changed hold/decay or unrecognized computation: REFUTED

`git log -L` on `_apply_hold_decay`: last touched v5.9.0 (same-area dedup/hold
re-tune) — months before onset. `_get_unrecognized_camera_count`: last touched
2026-07-13 (BLE-cancel, commits 2f864ac79/dcd6fe2c0), a full month before onset, and
census was demonstrably accurate 08-08→08-12 with BLE-cancel live. No counting-
semantics change in the regression window.

## Secondary findings

- `sensor.foyer_fisheye_person_count_2`: 1 sample in 24h, max ever 0 (24 rows total)
  — near-dead detector; check Frigate F2 config for that camera.
- `egress_cameras` dangling refs (H3 above).
- `binary_sensor.madrone_g6_entry_package_person_occupancy_2` exists; package-
  detector filter (`_is_package_detector`) must keep excluding it post-fix.

## Minimal fix (recommendation)

**Primary — config-only, zero code:** F1 is deleted, so the canonical entity_ids
(`sensor.<cam>_person_count`, `binary_sensor.<cam>_person_occupancy`) are now FREE.
Rename the `_2` entities to drop the suffix (entity registry rename; unique_ids
untouched). This restores every strict-suffix consumer at once (census resolver,
legacy paths, perimeter/transit consumers) with no deploy. ~38 renames (21 count +
17 binary).

**Hardening follow-up (small code change):** apply `_strip_disambiguation_suffix`
to the entity name before suffix matching in `_scan_device_entities`
(`camera_resolver.py:1288` — both the `_PERSON_COUNT_SUFFIX` sensor branch and the
`_PERSON_SUFFIXES` binary branch via `_has_any_suffix`), so a future `_N`
registration can never silently degrade the census again. Add a mutation-anchored
test: a device with only `_person_count_2` must still resolve a count sensor.

**Acceptance:** after rename, census must exceed identified count during a
multi-person traversal (recorder: census > 4 while any `person_count` sensor ≥ 2);
`house_source_agreement` re-checked.
