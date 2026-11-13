# v5.108.16 — Person sightings, phase 1

Card: FACE-ARRIVAL-REBUILD-1 (main card, stays open for phase 2), INTERIOR-PATH-MAP-1. Plan:
`docs/planning/PLANNING_person_sighting_layer.md` rev 11 (§0A phase split, §9A anchors, §25 builder corrections). Tier 3.
Reviews: `docs/reviews/code-review/v_person_sightings_p1_{A,B,C,D}.md` (A and C fix-required, B and D ship; all
findings fixed in three fix-up rounds).

## What changed

One identity-at-place layer shared with egress and the census.

- **Sightings.** A face on one of the operator's zone camera picks (resolved through Frigate, Protect and the URA room
  camera lists to one canonical camera key) or a face-named egress crossing becomes a person sighting: person, camera,
  room, zone, time, confidence, provenance. Gated by the Face Recognition switch (interior) and a 600 s boot window. A
  last-sighting accessor is exposed for later consumers.
- **No new actuation.** `FACE_ARRIVAL_INTERIOR_ENABLED` stays False: the D0-P3 probe found only 2% of face-before-phone
  cases were real arrivals (Jaya's tracker reads away while she is home). The v3.19 face-arrival path, which never fired,
  is retired.
- **Access needs a second signal.** One camera-derived arrival-source set is shared by the lock regime and security.
  A camera-derived arrival is held until an independent edge for the same person arrives; security does not add it to
  expected arrivals without one and fails closed with no lock regime.
- **Egress outcome log.** Every resolved door crossing writes one `egress_identity_outcome` memory row, including vetoed
  names (previously lost after Frigate's 14-day retention). Provenance (`face` / `ble`) is stamped on egress identity.
- **Interior path map.** `/config/universal_room_automation/interior_paths.json` loads through a shared validated JSON
  loader (whole-file reject, previous map kept), reload button `button.ura_reload_interior_paths`, provenance attributes.
  The built-in fallback is empty (portability); this house's map ships as `docs/examples/interior_paths.example.json`.
  Phase 1 has no runtime reader.
- **Trip-wire.** `face_sighting_zero` pages HIGH when faces the producer could have emitted arrived and it emitted none
  in 24 h. The weekly memory-writer health check skips `egress_identity_outcome` only when the house log proves the house
  was away or on vacation for the whole week.
- HVAC face counter matches zones by membership. Zone pick rebinds on room camera-list changes.

## Effect on the house

None on locks, security, HVAC or music. New diagnostics on the house-state sensor; new memory rows per crossing.

## Tests

Full suite 20979 passed, 0 failed (develop baseline 20815, 0 failed); every changed test file passes in isolation.
`URA_SOURCE_MUTATION=1` and `URA_D7_HYGIENE=1` green (review C). Review C ran 92 per-site source mutations; all
load-bearing sites go RED on a named test after fix-up 3.

## Validated 2026-11-13 (restart 01:44 CST on operator instruction, house sleep)

| Criterion | Result | Evidence |
|---|---|---|
| Installed | PASS | `update.universal_room_automation_update` installed_version v5.108.16 via `update.install` version pin |
| House state survives restart | PASS | `sensor.ura_coordinator_manager_house_state` sleep before and after |
| L1 picks resolved | PASS | `face_sighting_picks_resolved` 7 (family room, foyer, master hallway, playroom, staircase, stairs top, upstairs hall) = D0-P1; Garage A pick unresolved `room_cameras_empty`, as expected |
| L7 no access effect | PASS (at boot) | security `expected_arrivals` [], lock regime last actions {} |
| L10 path map | PASS | first load `none` / `file absent`; after installing `interior_paths.json` and pressing reload: `interior_paths.json (schema 1, 19 edges)`, validation `ok`, sha c13b38b7… equals the file, doors [front, garage_a]. First file named `camera.rear_ptz_2` (not a configured exterior camera, rule-7 warning); example corrected to `camera.rear_ptz_high_resolution_channel` and reloaded clean |
| No URA ERROR | PASS | system_log: URA WARNINGs only (boot holds, coverage re-anchor, deprecation notices) |
| L9 setup INFO line | n/a | INFO not in the logged window; the picks attributes carry the same data |
| L1b, L2, L3, L4, L5, L14, L19 | PENDING | need real door crossings and a waking house; checked after the morning crossings |

## Not done

- HVAC pre-arrival filter (`pre_arrival_sources`) unchanged and not driven by any test in this cycle.
- D0 P4 propagation yield not measured.
- Interior path map file not installed on HA (operator copies the example, then presses reload).
- Phase 2 (direction-aware egress identity, provisional naming, `camera_egress` HVAC source): gated on labels.
