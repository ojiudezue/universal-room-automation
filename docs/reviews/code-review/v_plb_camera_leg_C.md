# Review C: PHONE-LEFT-BEHIND-CAMERA-LEG-1 (test authority via per-site source mutation)

Branch `feature/phone-left-behind-camera` at 2952aa7e. Read first, completely:
`docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`, `docs/architecture/SENSOR_FLEET_CLASSES.md`.
Method: one production-source edit per run, `PYTHONDONTWRITEBYTECODE=1`, `__pycache__` cleared before and after,
focused tests only (`test_phone_left_behind_camera_leg.py` + `test_path_alpha_d9_room_corroboration.py`, 24 pass
on the clean tree), restore in `finally`, `git status` clean afterwards. Sites picked independently from the diff
against the four invariants, not from the builder's table.

## Site x test x RED-on-neuter

| # | Mutation (one site) | Result | Named test that went red |
|---|---|---|---|
| M1 | `is_on` step 4 reads `_last_sighting()` (camera leg into verdict) | RED | `test_verdict_identity_cross_product` |
| M2 | step 4 transit-validator-missing `None` -> `True` | RED | `test_verdict_identity_cross_product` |
| M3 | step 4 transit-validator-missing `None` -> `False` | RED | `test_verdict_identity_cross_product` |
| M29 | step 3 census `total_persons > 0` veto removed | RED | `test_verdict_identity_cross_product` |
| M4 | binary sensor key hand-built `"person." + entity_id.lower()` | RED | `test_key_matches_producer_emit` |
| M5 | NextRoom key hand-built `"person." + person_id.lower()` | RED | `test_next_room_camera_attrs_from_sighting` |
| M18 | `_last_sighting` queries the display name, not `_person_entity` | RED | `test_attributes_from_last_sighting` |
| M6 | NextRoom age window disabled | RED | `test_next_room_window_applied_at_attribute_read` |
| M7 | NextRoom `<= 0` off-switch removed | RED | `test_next_room_window_zero_never_shown` |
| M28 | `NEXT_ROOM_CAMERA_SIGHTING_MAX_AGE_S` 14400 -> 1000 | RED | `test_next_room_window_applied_at_attribute_read` |
| M8 | NextRoom attributes never fetch the sighting | RED | `test_next_room_camera_attrs_from_sighting` |
| M9-M12 | each of veto / source / camera / room attribute dropped | RED | `test_attributes_from_last_sighting` |
| M13 | moving age attribute re-added (A-M1 regression) | RED | `test_attributes_from_last_sighting` |
| M14 | `camera_leg` label changed | RED | `test_attributes_from_last_sighting` |
| M15 | `last_camera_sighting_at` stamped with now instead of the sighting's ts | RED | `test_attributes_from_last_sighting` |
| M26 | `phone_left_behind_hours` attribute restored | RED | `test_attributes_from_last_sighting` |
| M19 | legacy writer reads `person_id`/`face_id`/`label` again | RED | `test_legacy_writer_ignores_name_attributes` |
| M21 | `identity_status` -> `confirmed` | RED | `test_validate_transition_golden_unidentified_only` |
| M22 | `identity_status` -> always `unavailable` | RED | `test_validate_transition_golden_unidentified_only` |
| M16 | `_sighting_attributes` malformed-`ts` guard removed | **GREEN** | none |
| M17 | `_last_sighting` `presence is None` guard removed | GREEN | none (equivalent mutant, see below) |
| M20 | `validate_transition` named-person store lookup restored | **GREEN** | none |
| M23 | `_correlate_sighting_to_transition` rule 1 (face-match) restored | **GREEN** | none |
| M24 | `get_last_camera_sighting` method re-added | GREEN | none |
| M25 | class attr `PHONE_LEFT_BEHIND_HOURS` re-added | GREEN | none |
| M27 | `TRANSIT_PHONE_LEFT_BEHIND_HOURS` re-added | GREEN | none |

## Findings

| # | Sev | Where | Finding | Bug class |
|---|---|---|---|---|
| C-M1 | MEDIUM | `transit_validator.py` `validate_transition` (named-person lookup, was ~661-668) and `_correlate_sighting_to_transition` rule 1 | Invariant "deleted transit_validator named-sighting paths gone" is protected only at the WRITER (M19 red). The two READ-side deletions are untested: M20 and M23 restore them and the suite stays green, because every test seeds only the `"unidentified"` key, which the restored code never distinguishes. Reachable only if a writer ever stores a named key again, which M19 guards, so the live risk is low, but a partial revert of the read side is invisible. Fix: one test that seeds `_camera_sightings["Oji Udezue"]` (a named, in-window, shared-camera sighting) and asserts `validate_transition` returns the no-named-sighting golden (`no_camera_data` / `identity_status` unavailable, `camera_person_id` None); a second seeding a `person_id == transition.person_id` sighting into the concurrent correlator and asserting rule 2 outcome. A behavioural seed, not a source grep (#62). | #62-adjacent (oracle only exercises the post-change key set) |
| C-L1 | LOW | `binary_sensor.py` `_sighting_attributes` `float(sighting.ts)` guard | M16 green: the malformed-`ts` branch (`AttributeError/TypeError/ValueError` -> all-None attrs) has no test; `test_presence_missing_attrs_null` covers only a `None` sighting. Without the guard a bad `ts` would raise inside `extra_state_attributes` (entity attribute error). Fix: seed a sighting object with `ts="x"` and assert the all-None shape. | untested defensive branch |
| C-L2 | LOW | symbols `get_last_camera_sighting`, `PHONE_LEFT_BEHIND_HOURS`, `TRANSIT_PHONE_LEFT_BEHIND_HOURS` | M24/M25/M27 green: resurrecting the deleted dead symbols fails nothing. They have no reader, so a resurrected copy is inert and any test asserting absence would be a source grep (#62). No test recommended. Reviewer A's repo-wide grep is the evidence they are gone. | n/a (accepted) |

M17 is an equivalent mutant: the outer `except Exception` in `_last_sighting` turns the resulting `AttributeError` into `None`, so the inner guard is redundant. Not a finding.

## Cleared (RED-confirmed load-bearing)

- Verdict byte-identity (M1-M3, M29): the 4,320-row cross-product against an independent develop-ladder oracle goes red on every neutered step-3/step-4 site and on any read of the camera store inside `is_on`. The oracle is written from the plan (review A-L2 caveat stands: it cannot see a develop-only named-sighting flip, A-L1, unreachable at 0 of 102 person entities).
- `tracked_person_entity_id` keying (M4, M5, M18): the wire-in test drives the real `async_setup_entry` loop plus the real `PersonSightingProducer._emit` store, so a hand-built key at either construction site, or the display name at the read site, is caught. The NextRoom key is covered by its own attribute test.
- Display-only attribute surface (M9-M15, M26): each published attribute and the no-age (A-M1) rule is pinned.
- NextRoom read-time window (M6-M8, M28): 14399 / 14400 / 14401 boundary plus the age-past-window-between-updates case.

## Summary

| Severity | Found | Must fix |
|---|---|---|
| CRITICAL | 0 | 0 |
| HIGH | 0 | 0 |
| MEDIUM | 1 | 1 (C-M1, add the two seeded-named-sighting tests) |
| LOW | 2 | 0 (C-L1 optional 1-test fix) |

Tree state: every mutation restored; `git status` clean apart from this file (the drill script was removed).

## Verdict

**FIX-REQUIRED (small, test-only).** Add the C-M1 tests so the read-side deletions are mutation-anchored; C-L1 is a one-line add. No production-code defect found; every verdict, key-routing and display-only site is RED on neuter.
