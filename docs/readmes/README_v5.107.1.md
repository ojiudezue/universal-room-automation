# v5.107.1 — Face sources found in the registry; census reads faces on the 17 `_2` Frigate cameras

**Card:** FACE-SOURCE-REGISTRY-DISCOVERY-1 (FACE-SOURCE-SKIP-FIX-FLIP-1 folded in).
**Tier:** 2-DB review protocol (three framing-disjoint reviews), no DB schema change.
**Plan:** `docs/planning/PLANNING_face_source_registry_discovery_2026_11.md` rev 2 (plan review 1 applied; D0 gate
PASS, `AUDIT_face_source_registry_discovery_2026_11.md` §8).
**Version:** PATCH.

## Why
URA found Frigate face-name sensors by building entity ids from names. On this house 17 of the 29 Frigate cameras
have a person sensor ending `_person_occupancy_2`, and four census and presence readers skipped those cameras
silently, so the doorbell, garage and entry cameras never fed a face into the census. Another house with renamed
entities would lose face sources the same way.

## What changed
| Item | What | Default |
|---|---|---|
| D2 | Frigate face-name sensors are found by their unique_id type token (`sensor_recognized_face`) and device, in the same registry pass `CameraResolver` already makes. Built names are the fallback when the registry has nothing for a camera. A stem never resolves to a face sensor the old path would not name; a renamed face sensor now resolves. | on (`FACE_SOURCE_REGISTRY_DISCOVERY_ENABLED`) |
| D3 | Census face reads of a `_2` / renamed Frigate person sensor go through its device. Scope per reader: **S7 guest count** (interior cameras only, as before) can only go down: a fresh named face makes it `count - 1`; no face sensor keeps the whole count unrecognized. On this house that is playroom only (upstairs_hall's Frigate sensor is not in the interior list). **S6 corroboration** (the freshness-gated face set that can block the uncorroborated-divergence downgrade) takes the device join for INTERIOR cameras only (review B-1): an exterior / egress / perimeter `_2` face (garage_a, doorbell_lite, ...) still does not corroborate, so it cannot keep a playroom phantom count alive. Interior `_2` faces (playroom) can now corroborate, which can keep a divergent count instead of downgrading it (the upward direction, interior evidence only). **S5 raw face union** reads every `_2` Frigate camera; it is overwritten by the enhanced census (on here) and only feeds identity on non-enhanced installs. | on (`FACE_SOURCE_INCLUDE_DISAMBIGUATED_PERSON_SENSORS`) |
| D3 / S8 | Presence face pre-arrival on those 17 cameras is held OFF (see Operator decision). | off (`FACE_SOURCE_PRESENCE_ARRIVAL_DISAMBIGUATED`) |
| D4 | `FaceLeg.engine` comes from the device family: `frigate` for every Frigate face, never `frigate2`. Entity and latch legs use the same helper, so they still merge into one leg. | with D2 |
| D5 | Camera Census → Advanced → **Face name aliases**: `FaceName=person` entries. Saving it does not reload the integration. | empty |
| D6 | The per-person `last_camera` map keys on the unique_id token only, so a renamed sensor stays in it. | with D2 |
| Diagnostics | New unrecorded attributes on `sensor.universal_room_automation_persons_in_house`: `face_source_registry_hits`, `face_source_pattern_fallbacks`, `face_source_pattern_fallback_stems`, `face_source_device_derived_reads`, `face_source_device_derived_cameras`, `face_source_skipped_person_sensors`, `face_source_skipped_cameras`. Hits and fallbacks count lookups, not whether Frigate is producing; a dead producer shows in `face_lookup_missing_count`. | always |

Display change: the egress last-attach `contributor_engines` reads `frigate` instead of `frigate2`.
The alias field widens the perimeter D10.5 known-person set when an alias is set.
F-5 (the guest count subtracts one for a known guest's face) is not folded: making it resident-only would raise the
guest count, which is the opposite direction of this release's invariant, and it needs its own measurement. It stays
a card.

## Operator decision needed
1. **S8 face pre-arrival on the 17 cameras.** Presence face pre-arrival sends `SIGNAL_PERSON_ARRIVING
   (source=camera_face)`. Every consumer of that signal:
   - **SC lock regime** (`security_lock_regime.on_person_arriving`): for a resident who was away 15 min or more it
     releases the garage lockouts (`lock.ratgdov25i_dbfe2a_lock_remotes`, `lock.konnected_f0f5bd523b00_lock`) and,
     for the away-lock persons (Ezinne, Oji), unlocks `lock.master_bedroom_lock`.
     LOCK-REGIME-FACE-ARRIVAL-CORROBORATION-1 (v5.107.4, in build) gates this consumer.
   - **Security expected arrival** (`security.py:2282`): adds the person to the expected-arrival list (5-min
     sanction window), when `security_on_arrival_add_expected` is on.
   - **HVAC pre-arrival** (`hvac.py:881`): starts pre-arrival conditioning for the person's zone.
   - **Music following** (`music_following.py:281`). The 17 cameras include doorbell_lite,
   garage_a, madrone_g6_entry and front_door_aerial. A Frigate misrecognition there would unlock. The plan review
   treated S8 as a pre-arrival accelerator and did not see this consumer. The same path already runs on the 12 bare
   cameras (including exterior madroneptultra and reolinkpatio). To turn S8 on: set
   `FACE_SOURCE_PRESENCE_ARRIVAL_DISAMBIGUATED = True` (reviewed change). A safer alternative is a separate card to
   make the lock regime ignore `camera_face` arrivals.
2. **Alias for Oji.** The option value is `Oji=oji_udezue` (Camera Census → Advanced → Face name aliases). It does
   not change census identity (the canonicalizer already maps "Oji" to `oji_udezue`). Its only effect is that
   presence face pre-arrival maps "Oji" to `person.oji_udezue`, which feeds every consumer listed above (lock-regime
   release and away-lock unlock, security expected arrival, HVAC pre-arrival, music following) on every camera that
   already does face pre-arrival (the 12 bare cameras today). Oji is an away-lock person.
   Frigate labelled Jaya as "Oji" on 2026-10-24 while Oji was abroad (presence state-of-play §10 #28). Setting it is
   your call; I did not set it.

## Live validation (prospective)
| # | Criterion | How |
|---|---|---|
| L1 | Registry discovery is in use | `sensor.universal_room_automation_persons_in_house` attribute `face_source_registry_hits > 0` on a census tick. Broken index: hits 0 and `face_source_pattern_fallback_stems` lists Frigate face stems (e.g. `family_room`). Fallback stems that are Protect-only or non-Frigate are expected. |
| L2 | Skip fix is live | `face_source_device_derived_cameras` lists only `*_person_occupancy_2` ids (up to the 17 from the plan §1), `face_source_skipped_person_sensors == 0`. Not wired: derived empty and skipped > 0. Join broken for all: a bare `_person_occupancy` id appears in the derived list. |
| L3a | S6 scope | With `binary_sensor.*_person_occupancy_2` exterior cameras (garage_a, doorbell_lite) showing a fresh face and BLE all away, a lone playroom Frigate count with Protect 0 still reads `source_agreement: disagree` on the house census (downgrade fired). |
| L3 | Guest count lowers only with a fresh face | When playroom shows a person and `sensor.playroom_last_recognized_face_2` is fresh, `area_raw_max_pre_cancel` for playroom's area is `count - 1`, not `count`. |
| L4 | Engine label | After a named crossing, `contributor_engines` on the egress last-attach contains `frigate`, not `frigate2`. `person_entry_exit_events.confidence` for new rows only takes values seen before (0.6 / 0.72 / 0.75 / 0.9); a 0.75 on a single-camera crossing with no Protect leg is the INV-2 break. |
| L5 | last_camera map | INFO log `D2 frigate last_camera map built: 6 entries` at the first build after restart. |
| L6 | Alias field | Camera Census options show Face name aliases (Advanced), empty. With none set, `person_entry_exit_events.person_id` values in the 24 h after deploy are a subset of those seen before. |
| L7 | S8 held | No `Camera face arrival:` INFO log naming one of the 17 `_person_occupancy_2` cameras. |

## Tests
`quality/tests/test_face_source_registry.py` (43 tests, every load-bearing site mutation-anchored; 37 per-site drills
RED, tree restored). Updated: `test_egress_identity_producer_d2b.py::test_face_legs_2_engine_tagging`,
`test_census_ble_over_face.py::test_counter_kept_out_of_recorder` (exact set moved to the new file),
`test_reload_watchdog_hazard.py`, `test_room_options_reload_suppression.py`, `test_zone_house_advanced_fields.py`
(round-trip row for the alias field; Advanced count 19 → 20).
