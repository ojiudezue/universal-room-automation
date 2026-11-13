# PLANNING: person sightings — identity at a place, one model with crossings and the census

Card: **FACE-ARRIVAL-REBUILD-1** (main card, tier 3, thread identity, batch person-sightings; the board kept this id).
Connected: INTERIOR-PATH-MAP-1, EGRESS-DIRECTION-AWARE-IDENTITY-1, EXTERIOR-SEAM-FILE-LOADER-1,
VISION-CROSSING-ANALYSIS-1, PHONE-LEFT-BEHIND-CAMERA-LEG-1, DEPARTURE-ACTIONS-1. Related: ZONE-CAMERA-DISCOVERY-DEVICE-AREA-1,
PERSON-PROFILE-PREFERENCES-1, FRIGATE-DOOR-FACE-TUNING-1, EGRESS-IDENTITY-JOIN-GAP-1 (egress producer, shipped),
HVAC-PRECOOL-STANDDOWN-WHEN-COOL-1 (sibling). File renamed with `git mv` from `PLANNING_face_arrival_rebuild.md`.

**Rev 10, 2026-11-12, ura-planner. The plan is now TWO PHASES (§0A).** Phase 1 is built now and ships the
operator-approved arc complete: D0 probes (incl. P7 data collection), D8a persisted egress outcome log, D3 access gates
with the shared camera-derived source set, D1 sightings, D4 trip-wires, D2 interior arrival rule + HVAC face counter
fix, D5 retirement + doc fixes, D6 real-hass test, D7 interior path map. Phase 2 (direction-aware candidates,
provisional naming, the confirmation waiter, HVAC `camera_egress`) keeps its design, with every rev-9 review finding
fixed in it (§2B.7), and needs its own go decision after 28 days of persisted log AND an operator review of labels.
Why the split: after nine revisions the open risk sits in the candidate/confirmation machinery, and no measured data
yet says it pays (§0A). Rev 10 applies both rev-9 plan reviews
(`docs/reviews/code-review/PLAN_person_sighting_layer_review_rev9_buildprediction.md` 3 H / 6 M / 4 L and
`..._rev9_completeness.md` 2 H / 6 M / 11 L) and the operator's camera-map answers
(`FIXTURE_camera_paths_interior.md` "Operator answers", develop 2026-11-12). Develop merged (v5.108.14 HVAC pre-arrival
stand-down + arrival pre-heat; v5.108.15 seam loader as `ExteriorTrackLinker.async_load_seam_file`). Read for rev 10,
completely: both rev-9 reviews, IDENTITY_FUSION_CAMERAS_MANUAL.md, PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md,
SENSOR_FLEET_CLASSES.md, HVAC_ARCHITECTURE_STATE_OF_PLAY.md. Nothing here re-asserts an HVAC §10 or presence §10 ledger
claim. Rev-10 changelog: §23.

**Rev 9, 2026-11-12, ura-planner. Operator APPROVED rev 8 on 2026-11-12** ("capture everything and main card,
connected cards and drive to finish. And for it to be actually complete"). Rev 9 applies both rev-8 plan reviews
(`docs/reviews/code-review/PLAN_person_sighting_layer_review_rev8_buildprediction.md`, 3 H / 6 M / 4 L, and
`..._rev8_completeness.md`, 3 H / 7 M / 5 L) under the operator's fix direction. What changed:
1. **Arrival candidates are PROVISIONAL (completeness H3).** At the crossing a candidate's name goes nowhere: bus and DB
   `person_id` stay None, the notification says "Someone arrived", the census, perimeter, displays and sightings see no
   name. A per-candidate waiter names the person only when a non-face edge for that person lands AFTER the crossing
   (tracker home edge, Bermuda placing the phone in the house, or a near-home GPS fix): DB backfill (the exit-backfill
   DAO), a quiet "That was X" follow-up, one sighting, and the D2 egress branch (§2B.3a). §2B.3 now says honestly what
   discriminates a misnamed person and what does not.
2. **D7 path map is its own validated file** `interior_paths.json` with a const fallback, on the same loader
   EXTERIOR-SEAM-FILE-LOADER-1 is building, as a DAG; `door_interior_neighbours` and its four readers are not touched
   (build H3, completeness H2). The learned map is an offline diff report only. Fixture names are reconciled with the
   live egress config, and the gaps are operator questions (§13.4).
3. **HVAC accepts `camera_egress`** (both H1): default list, options selector, one-shot migration of the live option.
4. **G3 is an implied-speed rule** on the freshest GPS `device_tracker`'s own `last_updated` (build M3, completeness H3).
5. **`path_score` has a named decision time, named event sources and the same horizon in D0-P7** (build H2, completeness M4).
6. **The egress outcome log is persisted** (memory_episodes, every resolution, switch-independent) so P7 has data
   (completeness M7); P7's gate uses a Wilson bound with a minimum n.
7. Every other MEDIUM and LOW: rule-1 split by branch, named zones, attach rate, `last_attach`, DB column meaning,
   stale-section contradictions, kill-switch byte-identity incl. `identity_role`, resolver return channel, follow-up
   waiter mechanics, perimeter test, G2 knob semantics, portability inventory.
Board ids: main **FACE-ARRIVAL-REBUILD-1**; connected **INTERIOR-PATH-MAP-1** (D7), **EGRESS-DIRECTION-AWARE-IDENTITY-1**
(D8), **EXTERIOR-SEAM-FILE-LOADER-1** (in build; D7 reuses its loader), **VISION-CROSSING-ANALYSIS-1** (§15),
**PHONE-LEFT-BEHIND-CAMERA-LEG-1**, **DEPARTURE-ACTIONS-1**. Read for rev 9 (completely):
IDENTITY_FUSION_CAMERAS_MANUAL.md, PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md (incl. the §1 line-88 SUPERSEDED note: entry
areas are real since b70e3a2f, which is why D7 must not widen `door_interior_neighbours`), SENSOR_FLEET_CLASSES.md,
HVAC_ARCHITECTURE_STATE_OF_PLAY.md (rev 9 changes the pre-arrival source set), `FIXTURE_camera_paths_interior.md`,
`PLANNING_exterior_seam_file_injection.md`, `exterior_seams.py`. Live config re-read from `.storage` 2026-11-12. Rev-9
changelog: §22.

**Rev 8, 2026-11-12, ura-planner.** Operator 2026-11-12, on "egress only names people already home, so it can't
catch an arrival": "Who made this rule? I didn't. It doesn't make sense. It should do both especially since we have a
direction detector, which the path I outlined should improve." Rev 8 makes the egress identity rule DIRECTION-AWARE
(§2B): an entry naming a `not_home` person is an ARRIVAL CANDIDATE (name kept), an exit naming a `home` person is a
DEPARTURE CANDIDATE. The veto's protection against misrecognition is replaced by named, measurable guards (path
corroboration from the operator's camera-path fixture, face confidence, GPS plausibility, and for access consumers the
unchanged independent-second-signal rule). Egress arrivals return as a source (FACE-EGRESS-ARRIVAL-1 un-parked,
D0-gated). D7 becomes a prerequisite built from the operator map. New portability section (§20) and D0-P7 (vetoed
would-be arrivals). Rev-8 changelog: §21. Read for rev 8 (completely): IDENTITY_FUSION_CAMERAS_MANUAL.md,
PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md, SENSOR_FLEET_CLASSES.md, `FIXTURE_camera_paths_interior.md`; by section:
`PLANNING_egress_identity_producer.md` (D2b algorithm step 1), `transit_validator.py` 1357-1923 (identity) and
1925-2140 (direction, emit, union feed, notify), `camera_census.py` 4139-4280 (union register/read) and 6270-6340
(census veto), `perimeter_alert.py` 4985-5015 (D10.5 egress read).

**Rev 6, 2026-11-12, ura-planner.** Operator 2026-11-12: (1) guest count = vision AND Frigate/Protect person
counts fused with an explicit deconfliction rule until vision is trusted (§15.7 rewritten, trust criterion §15.7a);
(2) fast sample = 3 detection-timed frames with a blank-frame guard (§15.5 F-stage, §15.5a) and an offline frame-timing
experiment D0-FRAME (§15.4a). Changelog §19.

**Rev 5, 2026-11-12, ura-planner.** Operator direction 2026-11-12: vision is a strong INPUT if latency is decent;
design its timing (fast sample, batch, synthesis), simulate it before building (D0-SIM), and define how every
signal is weighed in the census and sightings (vision does not replace integration face/person counts). Adds §15.5
timing design with a per-day cost envelope from measured crossing rates, §15.6 D0-SIM, §15.7 signal-weighting
model, §15.8 coverage model (camera chains, interior purview); folds the queued points into §15.3 and D0-V (§15.4).
The access invariant, rev 4 fixes, and Tier 3 are unchanged. This cycle still builds nothing in §15. Changelog: §18.

**Rev 4, 2026-11-12, ura-planner.** Applies `docs/reviews/code-review/PLAN_person_sighting_layer_review_rev3.md`
(FIX-PLAN: H1, M1-M6, L1-L7). Design unchanged; fixes are explicit egress face provenance, one canonical physical-camera
key, the Garage A config premise, an egress boot drop, a named census/sighting split, a shared camera-derived source
set for the access gates, and the existing egress arrival notification. Changelog: §17.

**Rev 3, 2026-11-12, ura-planner.** Operator 2026-11-12: "reframe this, rename it and make sure it's really
harmonized with egress arrival/departure and census. And reuse any primitives that make sense. I don't want a cowboy
one off" and "why can't we watch people when we detect an arrival ... AI vision ... We have to get more ambitious",
plus (same day, via coordinator) "It also doesn't have to be live. It could be a time lapse set of snapshots that
happen when a crossing is detected for say the first x minutes". Rev 3 changes the frame, not the safety design:
- The layer is **person sightings**: "person P was seen at place X at time T, by evidence of provenance V, with
  confidence C". Face is the first provenance; egress identity is the second; AI vision of a crossing's snapshot
  sequence is a later one (§15). "Face arrival" is one narrow derived consumer of sightings (§3.3).
- §2A states ONE identity model across the egress producer, the census and sightings: who owns which fact, how a
  sighting, a crossing and a census identity relate, and a no-duplicates checklist. §1.2 is now a full primitive
  reuse table (REUSE / EXTEND / NEW with why).
- Everything rev 2 fixed stays: INV-ACCESS (now worded for any camera-derived identity, face or vision),
  INV-PRODUCER, INV-PROVENANCE, INV-NOOP, all review resolutions. Rev-3 changelog: §16.

Rev 2 history follows. Rev 1 was reviewed twice (framing-disjoint):
`docs/reviews/code-review/PLAN_face_arrival_rebuild_review_buildprediction.md` (H1, H2, M1-M7, L1-L5, hollow
tests) and `docs/reviews/code-review/PLAN_face_arrival_rebuild_review_completeness.md` (F1-F11). Both said
FIX-PLAN. The changelog (§14) marks each finding resolved and where. Status: plan only; operator APPROVE next.
No version in this name; the version is assigned at deploy.

Read before writing rev 2 (completely): `docs/Coordinator/IDENTITY_FUSION_CAMERAS_MANUAL.md`,
`docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`, both plan reviews. Rev 1 also read
`SENSOR_FLEET_CLASSES.md`, `CLAUDE.md` (fire-check corollary), `AUDIT_face_arrival_and_prearrival_fan_rooms.md`,
`AUDIT_face_production_after_nov_fixes.md`, and `PLANNING_egress_identity_producer.md` /
`PLANNING_lock_suspicious_arrival_hold.md` by section. Nothing here re-asserts a §10 ledger claim of the presence
doc. HVAC is touched only at the pre-arrival entry point (`hvac._handle_person_arriving`); see §11.

Paths are relative to `custom_components/universal_room_automation/` unless stated.

---

## 0. Summary, the honest expected value, and the pushback

**What is broken (verified).** The v3.19 path `presence._handle_camera_change` (`presence.py:5444`) ->
`_get_face_for_camera` (`:5487`) -> `_handle_face_arrival` (`:5581`) -> `SIGNAL_PERSON_ARRIVING(source=camera_face)`
(`:5632`) has fired 0 times in every activity-log window read (~90 days). Four independent defects, any one fatal:

1. **Wrong listener source.** It listens to zone-tracker cameras from `_discover_zone_cameras` (`presence.py:5060`),
   which filters by entity-level area; every camera here has its area on the device, so trackers have no cameras.
   The operator's picks (`zone_cameras` on the ZM entry, `config_flow.async_step_zone_cameras` `:11590`) are read
   only by `check_zone_occupancy_confidence` (`presence.py:2389`, called from `hvac.py:3089`).
2. **Edge race / freshness.** The face is read only at the person sensor's `on` edge and must be < 30 s old
   (`presence.py:5567-5574`). The name usually lands after the edge (audit: family_room 22 fresh-at-edge vs 89
   named within 60 s after).
3. **Producer disabled to protect one consumer.** `FACE_SOURCE_PRESENCE_ARRIVAL_DISAMBIGUATED = False`
   (`const.py:3511`) returns None for every `_N` person sensor (`presence.py:5532-5535`), to protect the SC lock
   regime. This is the anti-pattern the fire-check corollary forbids.
4. **No arrival semantics.** No was-away test: an interior face of a resident who is home becomes an "arrival".

**Live picks (`.storage/core.config_entries`, read-only, 2026-11-12):**

| House zone | `zone_cameras` | `zone_persons` |
|---|---|---|
| Back Hallway | `binary_sensor.staircase_person_occupancy`, `binary_sensor.garage_a_camera_person_detected` | none |
| Entertainment | `family_room_person_occupancy`, `foyer_fisheye_person_occupancy`, `master_hallway_person_occupancy` | ezinne, oji_udezue |
| Master Suite | `master_hallway_person_occupancy` | ezinne, oji_udezue |
| Upstairs | `upstairs_hall_person_occupancy_2`, `playroom_person_occupancy_2`, `stairs_top_person_occupancy` | ziri, jaya |

8 distinct picks, one (`master_hallway`) in two zones. **Correction from rev 1 (F1):**
`binary_sensor.garage_a_camera_person_detected` is NOT a UniFi Protect sensor. It is the URA platform's fused
per-room `CameraPersonDetectedSensor` (`binary_sensor.py:1520`) on the "Garage A" URA room device. It fuses that
room's `CONF_ROOM_CAMERAS`. §3.2 defines how such a pick resolves to face sensors. Also read: CM
`face_recognition_enabled = True`, `pre_arrival_sources = [geofence, ble, camera_face]`, `face_name_aliases` absent,
`security_on_arrival_add_expected` absent (default False, `config_flow.py:10403`).

**Correction from rev 1 (F3):** "Oji is unmapped" holds only for the presence mapper
(`presence._find_person_entity_from_face`, `:5644`). The census mapper `camera_census._canonical_person_slug`
(`:3903`) maps "Oji" to `oji_udezue` by unique first token. This plan uses the census mapper (§3.2), so Oji maps
without an alias. The alias is optional hygiene, not a fix.

**Marginal-benefit decomposition.**

| Consumer | What face adds over today | Size |
|---|---|---|
| HVAC pre-arrival (comfort) | geofence + ble supply 337 of 337 pre-arrival triggers in 30 days. A face adds a trigger only when the face comes before the phone (class (i), §7). | Small, possibly zero. D0-P3 decides. |
| SC lock regime (access) | Needs an independent non-face edge anyway (`_face_arrival_corroborated`, `security_lock_regime.py:1374`). | Zero by design. |
| Security expected arrivals (access: alarm suppression) | Off by default; a face must never feed it alone (§2). | Zero. D3 closes a latent leak. |
| Music (`music_following.py:549`) | Logs only. | Zero. |
| Personalization (PERSON-PROFILE-PREFERENCES-1, not built) | Who is in which shared room/hallway, now. Needs BLE for private rooms. | Future. The main reason for this cycle. |
| Presence fusion (census) | Census already reads faces directly (S5/S6/S7 point reads + the MQTT latch) and maps them with `_canonical_person_slug` (orchestrator-verified: thousands of `face_recognized_persons` rows credit `oji_udezue` 11-05..11-08, no alias). The sighting signal adds nothing to census: census does not subscribe to it and keeps its own reads (§8). The only census-side changes are the bridge hook and the trip-wire ring, both read-only for census logic. | Zero this cycle. |

**Honest expected value (rev 2, per review build-prediction "pushback should go further").**

- ~~**Egress produces sightings only, never arrivals (H1).**~~ **SUPERSEDED rev 8 (§2B).** H1 was true of the code
  but the cause was the veto, not egress: `transit_validator.py:1840-1854` drops an egress face identity whenever
  `person.<slug>` reads `not_home`, so every named egress entry was someone already home. That veto was copied from
  the census "who is home now" guard (`camera_census.py:6283-6338`; the egress plan's D2b step 1 says only "veto
  preserved", `PLANNING_egress_identity_producer.md:286-290`) with no direction analysis. For an ENTRY, `not_home` is
  exactly the arrival case. Rev 8 makes the rule direction-aware and restores egress arrivals as a D0-gated source.
- **Rev 10: egress arrivals, sized honestly (Phase 2 only).** Candidates are provisional (§2B.3a), so a
  `camera_egress` arrival can dispatch only when a non-face edge confirms it. Tracker-confirmed: geofence already
  dispatched, rule 5 skips (`home`). BLE-confirmed: PersonCoordinator dispatches `SIGNAL_PERSON_ARRIVING(ble)` on the
  same Bermuda tick (`person_coordinator.py:1083-1134`), so the camera arrival is a duplicate and is skipped
  (`arrival_already_dispatched`, §2B.7). GPS-confirmed: rev 10 requires a fix inside the home zone (§2B.7), which may be
  the very fix that flips the tracker home (UNVERIFIED whether HA's zone test already flips it for every such fix).
  So the HVAC gain from egress arrivals is about zero unless P7 shows GPS-confirmed leads over geofence. The durable
  value of §2B is correct labels, named follow-ups and the persisted outcome log, not HVAC.
- **Interior class (iii) is dropped (M7).** A face after the phone's home edge adds nothing; geofence/ble already
  dispatched.
- What remains as an arrival is interior class (i): a face seen before the phone arrives. D0-P3 gates it. **The
  likely outcome is sightings only and ~0 live `camera_face` arrivals until D0 shows otherwise.** That is a good
  result, not a failure:
  - the durable value is the sighting signal plus its last-sighting accessor, which future consumers read;
  - D3's security gate is worth shipping on its own, because it closes a latent alarm-suppression sink;
  - the dead v3.19 path and its producer-disabling flag go away.

**Parked, with revival triggers:** any presence/census fusion of sightings. **Rev 8: no longer parked:** egress
arrivals (the revival trigger "the egress not_home veto changes" fires: §2B changes it; D0-P7 sizes it) and the
interior/approach track sequence (D7 is now a prerequisite of §2B path corroboration, built from the operator's
fixture).

---

## 0A. Two phases (rev 10)

**What Phase 1 delivers to the operator.**
1. **Person sightings** (D1): "P was seen at place X at T, with provenance and confidence", from every resolved
   interior pick and from egress crossings that carry a real face provenance, plus `get_last_person_sighting`. This
   is the input PERSON-PROFILE-PREFERENCES-1 (personalization) needs.
2. **The security gate** (D3): a camera-derived arrival can no longer add an expected arrival (alarm suppression) on a
   face alone. That closes the latent leak with `security_on_arrival_add_expected` on. Lock regime and security test
   one shared set, `{"camera_face", "camera_egress"}`, before anything can emit `camera_egress`; unknown sources fail
   closed.
3. **The interior path map** (D7): `interior_paths.json` with the operator's corrected door paths, a validated const
   fallback, a reload button and provenance, on a loader helper shared with the shipped seam loader. Phase 1 loads,
   validates and exposes it and ships the pure scorer; no runtime decision reads it yet.
4. **The persisted egress outcome log** (D8a): one memory_episodes row per egress identity resolution, slug included on
   vetoed rows, plus a weekly labelling run. This is what makes Phase 2 decidable.
5. The dead v3.19 face-arrival path and its producer-disabling flag go away (D5); the HVAC face counter compares zones by
   membership (D2); a zero-fire trip-wire guards the new producer (D4); interior class (i) arrivals exist behind
   `FACE_ARRIVAL_INTERIOR_ENABLED` = False until D0-P3 passes.

**What waits for Phase 2:** the direction-aware egress rule (§2B.2), guards G1-G4, provisional candidates, the
confirmation waiter, `SIGNAL_EGRESS_ENTRY_CONFIRMED`, the notify follow-up, `departure_candidate`, path-node
subscriptions and `path_score` on the bus, sighting source (c'), the D2 egress branch, and HVAC `camera_egress`
(default, selector, migration). Phase 1 does not change the face-only veto.

**Phase 2 gate (its own go decision, its own Tier-3 plan reviews before build):** (a) the D8a log covers >= 28 days;
(b) the operator has reviewed the weekly labels (§7 P7); (c) the P7 go rules in §7 pass. Fail = Phase 2 stays parked
with the triggers in §7 P7. Phase 2's design (§2B) is kept and already carries every rev-9 fix (§2B.7) so a later
build starts from a reviewed text.

**Phase 1 build order (each step a ship; every dependency ships before its user).**

| Step | Deliverable | Depends on | Why here |
|---|---|---|---|
| 1 | D0 (P1-P5; P7 baseline replay over 7 days of recorder) | nothing | read-only gate |
| 2 | D8a outcome log + `EgressResolution` channel + pure tier helper + weekly labeller | nothing | starts the 28-day P7 clock |
| 3 | D3 access gates: `CAMERA_DERIVED_ARRIVAL_SOURCES` = {camera_face, camera_egress}, lock `:1017` and security `:2412-2419` by membership, `face_input_corroborated`, unknown fails closed | nothing | before any new arrival emitter (completeness M1) |
| 4 | D1 sightings + `canonical_camera_key` + `resolve_pick_to_fusions` + accessor + `identity_provenance` key + provenance consts; D4 diagnostics and the zero-fire trip-wire in the same ship | D3 (D1 emits nothing access-relevant, but D2 follows) | a new producer ships with its trip-wire |
| 5 | D2 interior arrival rule (flag False) + HVAC face counter fix; D5 retire v3.19 + docs; D6 real-hass test | D1, D3 | replaces the dead producer in one ship |
| 6 | D7 interior path map (shared loader helper, `interior_paths.py` + scorer, reload button, provenance) | D1 (`canonical_camera_key`) | build-prediction M1 |

The orchestrator's labels map as: "D3/D4 security gate + shared set" = plan D3; "D6 zero-fire trip-wire" = plan D4
§3.5 (plan D6 is the real-hass test, also Phase 1).

**Phase 1 falsifiable invariants:** INV-ACCESS, INV-PRODUCER, INV-PROVENANCE, INV-NOOP (Phase 1 form, §2) and INV-LOG
(§2). INV-PROVISIONAL, INV-CANDIDATE and INV-CENSUS-HOME are Phase 2 invariants; in Phase 1 they hold trivially
because no candidate can exist.

---

## 1. Institutional context verified

### 1.1 Config-first check

| Could config fix it? | Finding |
|---|---|
| Add picks so the tracker discovers cameras | No. Discovery ignores device area; the face path does not read picks at all. |
| Flip `FACE_SOURCE_PRESENCE_ARRIVAL_DISAMBIGUATED` | Rung-1 const (code change). It would not fix (1), (2) or (4) and still does nothing while trackers are empty. |
| Add `face_name_aliases` `Oji=oji_udezue` | Not needed by this plan: the census mapper already maps Oji (F3). Optional hygiene; it does help `presence._find_person_entity_from_face`, which this plan stops using. |
| Disable `camera_face` in `pre_arrival_sources` | Hides the symptom. |

Code is required for (1), (2), (4) and the producer/consumer split.

### 1.2 Prior-art scan: REUSE or BUILD (code, plans, analysis)

Greps run (rev 1 and rev 2), under `custom_components/universal_room_automation/`:
`grep -rn SIGNAL_PERSON_ARRIVING`; `grep -rn "zone_cameras\|CONF_ZONE_CAMERAS"`; `grep -n FACE_ const.py`;
`grep -rn "ura_person_egress_event"`; `grep -rn "face_sighting\|FACE_SIGHTING\|SIGNAL_FACE"` (**0 hits**);
`grep -n "def " arrival_edges.py`; `grep -rn fire_stuck_signal`; `grep -rn "add_expected_arrival"`;
`grep -rn "face_arrivals_today\|camera_face_arrivals_today\|_face_arrival_cooldown"`;
rev 2: `grep -n "provenance\|contributor_engines" transit_validator.py`; `grep -rn "_resolver_dirty"`;
`grep -n "self._lock_regime" domain_coordinators/security.py`; `grep -rn "_last_face_recognized\|_last_face_time"`;
`grep -n "class CameraPersonDetectedSensor\|class RoomCameraFusion"`.

| Piece | Verdict | Existing symbol (file:line) | Note |
|---|---|---|---|
| Operator picks | **REUSE** | `hvac_const.CONF_ZONE_CAMERAS` `:348`; ZM `zones.<zone>.zone_cameras`; form `config_flow.async_step_zone_cameras` `:11590` | Read per **house** zone from the ZM entry, not the merged HVAC zone. |
| Face name at recognition time | **REUSE + hook** | `camera_census._on_frigate_face_msg` `:5459`, latch loop `:5591-5593`, `_compute_face_latch_stems` `:5348` | One hook per message (§3.2). Retained messages already skipped (`:5468`). |
| Pick -> physical camera -> per-integration entities | **REUSE** | `CameraResolver.resolve_operator_declaration` `camera_resolver.py:767`, `resolve_capabilities` `:801`, `resolve_entity_to_device_id` `:752`, `RoomCameraFusion` `:189`, `FusionSource` `:131`, `face_name_entities_for_device` `:680`, `face_name_entities_for_stem` `:698` | Registry/device ladder; never string-built (`_2` rule, manual §1.1). Works today for camera-integration picks. |
| URA fused room pick -> its cameras | **BUILD (thin)** | none: the ladder on a URA room device finds no camera; `CameraPersonDetectedSensor` `binary_sensor.py:1520` reads `CONF_ROOM_CAMERAS` itself | `CameraResolver.resolve_pick_to_fusions` (§3.2), the single pick entry point. |
| Re-resolution trigger | **REUSE** | census `_resolver_dirty` (`camera_census.py:454`, flipped on registry update `:502`) | Plus `EVENT_HOMEASSISTANT_STARTED`, ZM options update, periodic retry (§3.2). |
| Face producer suppression | **REUSE** | `census._face_suppressed_now` `:4458` | |
| Name -> person (ONE mapper) | **REUSE** | `camera_census._canonical_person_slug` `:3903` (alias consulted inside it, manual §4.2) | F3. `presence._find_person_entity_from_face` `:5644` is not used and is retired with the v3.19 path. |
| Egress face provenance | **REUSE (expose)** | `census._egress_identity_last_attach["provenance"]` read at `transit_validator.py:2080-2092` (values `ble`, `ble+face`, default `face`); set at `:1667`, `:1716`, `:1776` | F2. One additive bus key (§3.2 (c)). |
| Debounce | **REUSE (re-keyed)** | `presence._face_arrival_cooldown` `:1820`, cleared at midnight `:8740` | Two keys now (§3.2, §3.3). |
| Camera -> area -> room -> zone | **REUSE** | `camera_resolver.resolve_area_id_for_entity` `:427`; `PresenceCoordinator.get_room_zone` / `_room_to_zone` | |
| Egress identity | **REUSE** | `transit_validator` fires `ura_person_egress_event` `:2016` | Producer unchanged except one additive key. |
| Independent arrival edge | **REUSE** | `arrival_edges.nonface_arrival_source` `:168`; lock `_face_arrival_corroborated` `:1374` | Exposed through one public lock-regime method (M3/F4). |
| Lock corroboration for other consumers | **BUILD (thin)** | none public | `SecurityLockRegime.face_input_corroborated(person, at_ts)`: public wrapper, no new logic. |
| Per-person last `-> home` edge | **BUILD (small)** | presence already listens to `person.*` (`_subscribe_geofence` / `_handle_geofence_change`) | M5. One dict `_last_home_edge_ts`, written in that existing listener. |
| Arrival signal + consumers | **REUSE** | `signals.SIGNAL_PERSON_ARRIVING` `:25` | Payload extended additively. |
| Zone/HVAC counters + tracker face fields | **REUSE (fix)** | tracker `_face_arrivals_today` `presence.py:653`; `_last_face_recognized` / `_last_face_time` `:651-652` (read `sensor.py:5979-5981`, `presence.py:1031-1032`); `ZoneState.camera_face_arrivals_today` `hvac_zones.py:176` | F11: fields kept and fed by sightings. HVAC counter compound-name fix. |
| Trip-wire NM | **REUSE** | `_stuck_signal_nm.fire_stuck_signal` `:165` | |
| Trip-wire denominator | **BUILD** | none (`_frigate_face_msg_face_count` counts before the sentinel drop and is global, M2/F6) | New post-sentinel ring at the latch write (§3.5). |
| **Face-sighting signal + payload** | **BUILD** | none | `SIGNAL_PERSON_SIGHTING`, frozen `PersonSighting`. |
| **Sighting producer** | **BUILD (small)** | none | `person_sighting.py` + presence wiring. Replaces v3.19. |
| **Last-sighting accessor** | **BUILD (small)** | none | `PresenceCoordinator.get_last_person_sighting(person_entity)` (§3.2). |
| **Arrival rule** | **BUILD (small)** | none | One function, one call site. |

#### 1.2a Rev 3 primitive-reuse table (the complete list; supersedes the BUILD rows above where they differ)

Rev-3 greps (worktree, `custom_components/universal_room_automation/`): `grep -rn -i sighting` (finds
`transit_validator._camera_sightings` / `get_last_camera_sighting`, below); `grep -n provenance camera_census.py
transit_validator.py`; `grep -rn '"ble+face"\|PROVENANCE_' const.py camera_census.py transit_validator.py` (literals
only, no constant); `grep -n "^CONFIDENCE_" const.py`; `grep -n "def " arrival_edges.py`; `grep -n "snapshot\|RETENTION"
perimeter_alert.py const.py`; llmvision `services.yaml` + `__init__.py:457-468` on the live mount.

| Primitive | Verdict | Where | Why / note |
|---|---|---|---|
| Name -> person slug | **REUSE** | `camera_census._canonical_person_slug` `:3903` (aliases + `known_face_guests` -> `guest:<head>` inside it) | The only mapper. `guest:*` slugs emit no resident sighting (counted `guest_names`), same split as `register_egress_face` (defined `:4139`). **Unmapped (rev 4, L4):** the mapper passes unknown names through lowercased (`:3903-3990`), so "mapped" is an explicit membership test: result in `census._get_tracked_person_slugs()`. A result not in that set and not `guest:*`, or `""` (ambiguous head), is unmapped: no sighting, counted `unmapped_names`. |
| Per-leg face evidence shape | **REUSE (vocabulary)** | `camera_census.FaceLeg` `:349` (`engine`, `base_stem`, `canonical_slug`, `last_changed`, `confidence`, `synthetic`) | `PersonSighting` uses the same field names for the same meanings; no second leg type. Interior evidence is built by the same face sensors `_resolve_face_legs` (`:3312`) reads. |
| Provenance vocabulary | **EXTEND (name the existing values)** | literals `"face"` / `"ble"` / `"ble+face"` at `camera_census.py:4197` (default), `:4270`, `:4772` (`provenance="ble"`), `transit_validator.py:1668, :1716, :1777`, and the reader default `transit_validator.py:2087` | NEW rung-1 constants `IDENTITY_PROVENANCE_FACE/_BLE/_BLE_FACE` (+ reserved `_VISION`, unused) and a frozenset of valid values, with the SAME string values. Census and transit validator switch every literal and default above to the constants in the same build (pure rename, byte-identical values; a test pins the values). **Rev 4 (H1): the face-only attach at `transit_validator.py:1908-1916` today writes NO `provenance` key** (face is implied only by the reader default at `:2086-2087`). The rename adds `"provenance": IDENTITY_PROVENANCE_FACE` to that write explicitly. This is the one non-rename line; the value is the one the reader already assumes. |
| Confidence ladder | **REUSE** | `CONFIDENCE_HIGH/MEDIUM/LOW` `const.py:315-317`; `FACE_MATCH_CORRELATED_BOOST` `:3345`; `BLE_TRANSITION_ONLY_CONFIDENCE` `:3378` | Interior sighting = 0.6 (one recognizer). No new number. Consumer thresholds are manual §5.5(b) unchanged. |
| Physical-camera identity (dedup key) | **EXTEND (rev 4, M1)** | `RoomCameraFusion` / `FusionSource.device_id` from `CameraResolver.resolve_operator_declaration` `camera_resolver.py:767` | `physical_camera_id` alone is NOT canonical: `resolve_capabilities` sets it to `sorted(device_ids)[0]` over its INPUT devices (`:1029`), and `resolve_operator_declaration` passes one input device per call (`:785-797`), so a Protect leg and its Frigate twin give different ids. NEW one helper `camera_resolver.canonical_camera_key(fusion) -> str = min(s.device_id for s in fusion.sources)` (the camera's FULL device set after the ladder walk), used by interior AND egress. The egress side resolves the egress person entity that fired (`transit_validator.py:1272, :1323`, Frigate or Protect leg) through `resolve_operator_declaration([entity])` then the same helper. No caller reads `physical_camera_id` for dedup. Concept split NAMED, not changed: the egress producer's independence predicate uses `base_stem` (manual §5.2); this layer does not touch it. |
| Pick -> camera walk | **REUSE + EXTEND** | resolver ladder `:767/:801/:752`; NEW thin `resolve_pick_to_fusions` for URA fused room picks (§3.2) | Rev 2 unchanged. |
| Face producer suppression | **REUSE** | `census._face_suppressed_now` `:4458` | |
| Fast face path (MQTT latch) | **REUSE + hook** | `_on_frigate_face_msg` `:5459` | No second MQTT subscription, no second latch. |
| Egress identity, provenance, confidence | **REUSE + one additive key** | `ura_person_egress_event` `transit_validator.py:2016`; `_egress_identity_last_attach["provenance"]` | Sightings PROJECT the egress decision; they never re-decide identity. |
| Boot exclusion | **REUSE (constant)** | `PERIMETER_EGRESS_ARRIVAL_BOOT_EXCLUDE_S` `const.py:2679` | Rev 2's separate `FACE_SIGHTING_BOOT_EXCLUDE_S` is withdrawn. Rev 4 (L3): `arrival_edges.edge_in_window` (`:85-87`) is a window helper (`ts >= boot_end and abs(at_ts - ts) <= window_s`), not a boot guard. The producer computes `boot_end = presence_setup_ts + PERIMETER_EGRESS_ARRIVAL_BOOT_EXCLUDE_S` once and drops any sighting with `ts < boot_end`; all three sources (a/b/c) use that one check. |
| Arrival corroboration | **REUSE** | `arrival_edges.nonface_arrival_source` `:168`; lock `_face_arrival_corroborated` `:1374` (public wrapper only) | |
| Debounce | **REUSE (re-keyed)** | `presence._face_arrival_cooldown` | Rev 2 unchanged. No other debounce exists for this fact. |
| Freshness | **none needed** | — | A sighting carries its recognition `ts`; consumers age it. The egress `FACE_MATCH_*` windows belong to the identity JOIN and stay there. |
| Kill switch for door naming | **REUSE** | `switch.ura_name_people_at_doors` via the egress producer | Rev 2 L4 unchanged. |
| **Existing camera "sighting" store** | **KEEP + CARD (do not write into it)** | `TransitValidator._camera_sightings` `transit_validator.py:214`, writer `_on_camera_state_change` `:797` (person from `person_id`/`face_id`/`label` state attributes, else `"unidentified"`), reader `get_last_camera_sighting` `:653`; consumers `PersonPhoneLeftBehindSensor` `binary_sensor.py:2196, :2217` and `sensor.py:3559` | Found in rev 3. Live 2026-11-12: `hours_since_camera_sighting` is `null` on every `*_phone_left_behind` sensor, and their `person_id` attribute is a display name (`"Oji Udezue"`), not a slug. So this store never holds a named sighting today. Phone-left-behind is a HOUSE-STATE trust input (it removes a person from the AWAY-veto denominator, presence state-of-play §3), so feeding it named sightings would change house state. It stays untouched this cycle; card **PHONE-LEFT-BEHIND-CAMERA-LEG-1** (Tier 2-DB minimum, house state) migrates it to `get_last_person_sighting(slug)` and retires the named branch of `_camera_sightings`. Until then two stores exist by design: the old one is unnamed-only in practice. |
| Last-sighting accessor | **NEW (small)** | `PresenceCoordinator.get_last_person_sighting` | NEW because the only existing store (row above) would wake a house-state consumer if written. Long-term single store = this one (card above). |
| Sighting signal + payload | **NEW** | `SIGNAL_PERSON_SIGHTING`, `PersonSighting` | `grep -rn -i sighting` finds no signal or typed record; the transit store is an untyped dict keyed by attribute strings. |
| Snapshot capture + retention (for §15) | **REUSE** | `perimeter_alert._capture_at_detection_snapshot` `:3690`, `_try_capture_live_grab` (`camera.snapshot`), `PERIMETER_SNAPSHOT_DIR` `const.py:3136`, `_prune_snapshot_dir` `:4102` with `PERIMETER_SNAPSHOT_RETENTION_AGE_H` (168) / `_COUNT` (5000) | §15 only; not built this cycle. |
| Vision call | **REUSE** | `perimeter_enrichment.enrich_dispatched_alert` / `enrich_with_verdict` (timeout, never-raise, non-empty rules) | §15 only. Needs a multi-image variant (llmvision `image_file` takes newline-separated paths, `__init__.py:457`). |
| Path cameras after a crossing | **REUSE** | `EXTERIOR_ADJACENCY_GRAPH` via `ExteriorTrackLinker.adjacent_cameras` `exterior_track_linker.py:919`; `transit_validator._get_interior_cameras_near` `:2203` | §15 only. |

**Plans and analysis consulted:** `PLANNING_consol_1_alerting_llmvision.md` (rev 3: adapter contract, cost and
latency in `AUDIT_consol_1_d0_probe.md`), `PLANNING_egress_identity_producer.md` (§0 invariant, confidence ladder,
`base_stem` independence, abstain); `PLANNING_lock_suspicious_arrival_hold.md` (§4.2 unlock sites, held-edge rule);
`PLANNING_exterior_track_linking.md` (adjacency-as-data); the two audits; sibling
`PLANNING_hvac_precool_standdown*.md` on `plan/hvac-precool-standdown` (§11). Memory bodies:
`reference_protect_face_latency_async`, `reference_frigate1_retired_2suffix_permanent`,
`reference_egress_face_coverage_7pct_not_a_ceiling` (+ amendments), `feedback_read_consumers_before_asserting_function`,
`project_house_zones_vs_hvac_zones`, `feedback_portability_imperative`.

#### 1.2b Rev 9 prior-art rows (supersede rev 8 rows where they differ)

Greps run (rev 9, worktree after merging develop 2026-11-12): `grep -rn exterior_seams custom_components docs/planning`
(module `exterior_seams.py` exists, no production importer; loader in build as EXTERIOR-SEAM-FILE-LOADER-1);
`grep -n "DEFAULT_PRE_ARRIVAL_SOURCES\|CONF_PRE_ARRIVAL_SOURCES" hvac_const.py config_flow.py hvac.py`;
`grep -n "def _migrate" __init__.py`; `grep -n "def find_unnamed_exit_crossings\|def backfill_entry_exit_person_id\|def log_memory_episode" database.py`;
`grep -rn SIGNAL_EGRESS_EXIT_BACKFILLED`; `grep -n '"attached"' sensor.py`; `grep -n "^def " arrival_edges.py`;
`grep -rn "_gps_newer_or_equal\|haversine\|util.location"`; `grep -n "_resolve_egress_face_identity(" transit_validator.py`
(one call site, `:2011`); `grep -n "MEMORY_EPISODE_DEDUP_WINDOW_S" const.py`. Live: `.storage/core.config_entries`
(egress cameras, door groups, door neighbours, `pre_arrival_sources`), `.storage/core.entity_registry` (camera entities).

| Piece | Verdict | Existing symbol (file:line) | Note |
|---|---|---|---|
| Path-map file format + validator | **REUSE (patterns)** | `exterior_seams.py`: `SeamSpecError` `:64`, `_pairs` `:68`, whole-file rejection + fail-safe contract `:27-39`, `SEAM_SCHEMA_VERSION` `:49`, known-camera rule `:213-221` | NEW module `interior_paths.py` (HA-free: parse, validate, score) with the same contract. Not a second mechanism: same loader, same reject-wholesale semantics |
| File load, const fallback, reload button, provenance attrs | **REUSE (in build)** | EXTERIOR-SEAM-FILE-LOADER-1 (`PLANNING_exterior_seam_file_injection.md` D4 reload button, D5 provenance attrs, D6 const fallback; TOU loader `energy_tou.py:72`) | D7 registers a second file on that loader. If the loader lands seam-specific, D7's builder extracts the shared helper in the same commit (no copy). D7 is built after the loader merges |
| `door_interior_neighbours` | **NOT TOUCHED** | readers `transit_validator.py:1113-1140` (load), `:2221` (`_get_interior_cameras_near`, direction), `arrival_edges.door_entry_areas` `:223` (lock corroboration via `security_lock_regime.py:1371`), `perimeter_alert._near_areas` `:5112`; validator `config_flow.py:4861` | Build H3 / completeness H2. Entry areas are real since b70e3a2f, so widening this option widens access corroboration and changes direction |
| Exterior / extra path-node events | **EXTEND** | the egress tracker's person-sensor subscription and per-entity event lists (`transit_validator.py:1047-1055`), prune `_prune_event_list` `:2252` | Path nodes not already subscribed get a separate list (`_path_events`) with its own horizon, only while the switch is on and a map is loaded. The existing interior lists and their 75 s prune are unchanged |
| Freshest GPS fix | **REUSE** | `person_coordinator._gps_newer_or_equal` `:93`, axis loop `:300-360` (`device_trackers`, `source_type == "gps"`); HA `homeassistant.util.location.distance` | NEW thin pure helper `arrival_edges.freshest_gps_fix(states_get, person_entity) -> (lat, lon, acc_m, fix_ts) | None` |
| Stale-source edge test | **REUSE** | `arrival_edges.stale_source_arrival` `:48` | a tracker home edge whose `source` did not change never confirms a candidate (same rule as the suspicious-arrival hold) |
| Unnamed entry row + late naming | **REUSE / EXTEND** | `Database.find_unnamed_exit_crossings` `:4685` (gains `direction: str = "exit"`; default byte-identical), `backfill_entry_exit_person_id` `:4723` (`WHERE id = ? AND person_id IS NULL`, writes `person_id` only) | Manual §4.3a pattern, applied to confirmed entries |
| Late-name display refresh | **EXTEND (pattern)** | `SIGNAL_EGRESS_EXIT_BACKFILLED` `signals.py:33`; readers `sensor.py:4891`, `:5045` | NEW `SIGNAL_EGRESS_ENTRY_CONFIRMED`. A new signal, not a widened exit one: the exit readers re-read EXITS only |
| Confirmation waiter shape | **REUSE (pattern)** | perimeter "That was <name>" follow-up (`PERIMETER_IDENTITY_FOLLOWUP_POLL_S` 5 s, `_arm_identity_followup` / `_followup_check`; manual §4.5) | poll, one per key, discharged on expiry, teardown, supersession |
| Outcome persistence | **REUSE** | `Database.log_memory_episode` `:10664` (registry gate `MEMORY_EPISODE_TYPES`; per-(node_id, type) dedup `MEMORY_EPISODE_DEDUP_WINDOW_S` 60, `const.py:5810`) | NEW episode type `egress_identity_outcome`. `node_id` per crossing, so the 60 s dedup cannot merge two crossings |
| CM option migration | **REUSE (pattern)** | `_migrate_hvac_zone_entry_dwell_to_zero` `__init__.py:749` (sentinel key, rewrite only a recognised value) | adds `camera_egress` to the stored `pre_arrival_sources` |
| Attach-label vocabulary | **NEW (const)** | literal `"attached"` at `sensor.py:3950` | `EGRESS_OUTCOMES_ATTACHED = frozenset({"attached", "departure_candidate"})` |
| Resolver role channel | **EXTEND** | `_resolve_egress_face_identity` 3-tuple, one call site `transit_validator.py:2011` | 4-tuple with a frozen `EgressRoleResult` (build L4 / completeness L4: no `self._last_*` stash) |

#### 1.2c Rev 10 prior-art rows (supersede 1.2b where they differ)

Greps run (rev 10, worktree after merging develop at 6ff96aed + the fixture commit):
`grep -n "def async_load_seam_file\|def _install_const_seams\|def _read_seam_file\|seam_file_sha256\|_episode_tasks" exterior_track_linker.py`;
`grep -n "def log_entry_exit_event\|lastrowid" database.py`; `grep -n "camera_face" domain_coordinators/hvac.py`;
`grep -n pre_arrival_sources strings.json translations/en.json`; `grep -n "def stale_source_arrival" arrival_edges.py`;
`grep -n LOCK_ARRIVAL_STALE_SOURCE_S const.py`; `grep -n "person_presence_snapshots" database.py`.

| Piece | Verdict | Existing symbol (file:line) | Note |
|---|---|---|---|
| Seam loader (shipped v5.108.15) | **EXTEND (extract helper, Phase 1 D7)** | `ExteriorTrackLinker.async_load_seam_file` `exterior_track_linker.py:479`, `_read_seam_file` `:468`, `_seam_file_path` `:464`, `_install_const_seams` `:433`, sha `:509`; button `button.ura_reload_exterior_seams` | It is a linker method wired to `validate_seam_spec` / `graph_from_spec` / `set_adjacency`, not a reusable loader (build M2). D7 extracts `json_file_loader.load_validated_json(hass, path, *, parse_validate, install, fallback) -> LoadOutcome` (HA-light module: executor read, sha, JSON parse, validate callback, install callback, outcome string). The linker's method becomes a thin caller; `test_exterior_seam_loader.py` must pass UNCHANGED (completeness L4). Owner of the interior map: `EgressDirectionTracker` (the scorer's future caller), not the linker |
| Seam-loader semantics D7 must NOT copy | **NAMED** | const never validated (`:433`); sha set on a rejected file (`:509`) | D7 states its own four outcomes (D7 Loading); the shared helper takes `validate_fallback: bool` so the seam caller keeps today's behaviour byte-identical and D7 validates its const |
| Entry row id at INSERT (Phase 2) | **EXTEND** | `Database.log_entry_exit_event` `database.py:4600` returns None today; precedent `return cursor.lastrowid` inside `_db()` (`:3010`, `:4081`) | Phase 2 returns `int | None` (additive; every current caller ignores the return). Removes the timestamp bracket (build H1, completeness H2) |
| Tracked background tasks | **REUSE (pattern)** | linker `_episode_tasks` set `exterior_track_linker.py:250`, add/discard `:821-822`, bounded teardown gather `:363-379` | D8a logger tasks (Phase 1) and the confirmation tasks (Phase 2) |
| Stale-source threshold | **REUSE** | `LOCK_ARRIVAL_STALE_SOURCE_S` `const.py:3759` (10 s); `arrival_edges.stale_source_arrival(states_get, person_id, stale_s, *, person_state)` `:48` | Phase 2 leg (a) passes this const (build M5) |
| Pre-arrival source default, third copy | **FIX (Phase 2)** | `hvac.py:881` literal `["geofence", "ble", "camera_face"]` | Phase 2 replaces it with `list(DEFAULT_PRE_ARRIVAL_SOURCES)`; help text `strings.json:1425` / `translations/en.json:1425` gains the new source (completeness L1) |
| Long-lived labels source | **REUSE** | `person_presence_snapshots` table (`database.py:1014`); `ura_activity_log` `pre_arrival` rows | P7 weekly labeller (completeness M6). GPS fixes have no URA-DB copy: the weekly run reads them from the recorder inside its 7 days |

### 1.3 Code surveyed end to end
`presence.py` 5040-5700, 2308-2410, 1350-1375, 640-660, 1025-1035; `hvac.py` 1425-1440, 1507-1514, 7212-7290;
`security.py` 249-330, 660-730, 1580-1600, 2381-2430; `security_lock_regime.py` 996-1060, 1364-1460;
`music_following.py` 549-585; `camera_census.py` 349-372, 450-540, 3265-3290, 3903-3960, 5348-5605;
`transit_validator.py` 1640-1790, 1835-1860, 1990-2095; `arrival_edges.py` 1-245; `binary_sensor.py` 1520-1560;
`camera_resolver.py` 185-210, 690-740; `const.py` 2660-2690, 3320-3380, 3495-3512.
Rev 9: `exterior_seams.py` (all), `transit_validator.py` 2000-2200, `arrival_edges.py` 33-240, `database.py` 4685-4770 and
10664-10715, `person_coordinator.py` 80-110 and 300-360, `hvac.py` 7224-7236, `config_flow.py` 8185-8210,
`__init__.py` 749-800; `HVAC_ARCHITECTURE_STATE_OF_PLAY.md` read completely (rev 9 changes the pre-arrival source set).

---

## 2A. One identity model (rev 3)

Three components already make identity facts. This layer adds one fact and changes none of the others.

| Fact | Owner (single writer) | Read by | Persisted |
|---|---|---|---|
| F1 Is person P home? | HA `person.*` + `PersonCoordinator` (`person_state_for_trust` for trust readers, raw state for edge readers) | everyone | HA recorder |
| F2 Who is in the house now (count + identified set) | `PersonCensus` (union of face ids, BLE ids, egress registrations) | presence inference, guest, displays | census sensors |
| F3 A door crossing (camera, direction, ts) and its identity attach (slug, provenance, confidence) | `TransitValidator` / `EgressDirectionTracker` | census union (`register_egress_face`), four display sensors, perimeter D10.5, **the existing arrival/departure NM `TransitValidator._arrival_departure_notify` (`transit_validator.py:2047`, `:2140`; names the person at `identity_confidence >= ARRIVAL_NAME_CONFIDENCE_THRESHOLD`, live since 2026-09)**, **sightings** | `person_entry_exit_events` + bus `ura_person_egress_event` |
| F4 **P was seen at place X at T** (provenance, confidence, camera, room, house zones) | **NEW: the sighting producer in presence** (one emit function) | last-sighting accessor, D2 arrival rule, tracker display fields, diagnostics; later personalization | RAM only |
| F5 P is arriving (event) | presence geofence (`presence.py:5297`), `person_coordinator` ble (`:1132`), and the one D2 site | HVAC, security, lock regime, music | activity log |

How they relate:
- **A crossing is not a sighting, and a sighting is never a crossing.** A crossing with a face-provenance identity
  is PROJECTED into one egress sighting (place = the crossing's room). The sighting copies the slug, provenance and
  confidence the egress producer decided; it never re-runs the JOIN. Exit backfill (late BLE naming) produces no
  sighting.
- **The census does not read sightings, and sightings do not feed the census.** Both read the SAME face sensors
  and latch through the SAME mapper and suppression primitives. A feed in either direction would count one face
  twice (the census double-count history, CLAUDE.md producer/consumer rule). The census keeps registering egress
  identities itself (`register_egress_face`), as today.
- **Named concept split (rev 4, M4; Bug Class #63): they do NOT agree by construction.** The census face path drops
  a face for a `not_home` person and, under BLE Leads, for an overruled adult (`_get_face_recognized_person_names`,
  `camera_census.py:6205-6240`; manual §5.4). The sighting producer keeps those faces on purpose (the class (i)
  candidate, §3.2 Filters). So a Frigate mislabel of an away resident (the 10-24 Jaya-as-Oji case) is a sighting but
  not a census identity. "Seen" (F4, evidence) and "counted in the house" (F2, belief) are different facts. Each
  sighting carries `person_state_at_emit` (raw tracker state) and `census_would_veto` (bool, computed by calling the
  census's own veto predicate, not a re-derivation), so later consumers can apply the census rule without
  re-deriving it.
- **F5 from F4 only through D2** (interior class (i), D0-gated; rev 8/9 add CONFIRMED egress arrival candidates,
  §2B.3a / §2B.6, also D0-gated, through the same one D2 site).
- **Access never reads F4 alone** (INV-ACCESS). Corroboration comes from F1 edges / Bermuda moves via
  `arrival_edges`.

Shared vocabulary (one name per concept, across FaceLeg, the egress attach, the bus event and `PersonSighting`):

| Concept | FaceLeg | egress `_last_attach` / bus | PersonSighting |
|---|---|---|---|
| person | `canonical_slug` | `person` / `person_id` | `slug` (+ `person_entity`) |
| how known | `engine` (+ `synthetic`) | `provenance` / NEW bus key `identity_provenance` | `provenance` (+ `synthetic`) |
| how sure | `confidence` | `identity_confidence` | `confidence` (same ladder) |
| when | `last_changed` | `timestamp` | `ts` (recognition time) |
| which camera | `base_stem` | `camera` / `egress_camera` | `camera` + `physical_camera` |

**No-duplicates checklist** (reviewer D checks each against the build):

| Must exist once | The one | Rev-3 status |
|---|---|---|
| Person-name mapping | `_canonical_person_slug` | reused; `presence._find_person_entity_from_face` deleted (D5) |
| Provenance enum | `IDENTITY_PROVENANCE_*` (named existing strings) | extend; literals replaced |
| Confidence scale | `CONFIDENCE_*` / `FACE_MATCH_CORRELATED_BOOST` / `BLE_TRANSITION_ONLY_CONFIDENCE` | reused |
| Debounce | `_face_arrival_cooldown` (re-keyed) | reused |
| Latch | census MQTT face latch | reused (hook) |
| Freshness | none (ts carried) | n/a |
| Boot guard | `PERIMETER_EGRESS_ARRIVAL_BOOT_EXCLUDE_S`, one `ts < boot_end` check for sources a/b/c | reused constant |
| Physical camera key | `camera_resolver.canonical_camera_key(fusion)` (min source device id) | new helper (rev 4, M1); interior and egress |
| Camera-derived arrival sources | `CAMERA_DERIVED_ARRIVAL_SOURCES` frozenset | new (rev 4, M5); lock regime + security gate by membership |
| Arrival/departure notification | `TransitValidator._arrival_departure_notify` | existing, one site (rev 4, M6); future consumers extend it, never add a second |
| Last-seen store | `get_last_person_sighting` | new; legacy `_camera_sightings` carded for migration |

---

## 2B. Direction-aware egress identity (rev 8, rewritten rev 9) — card EGRESS-DIRECTION-AWARE-IDENTITY-1 — **PHASE 2**

**Rev 10: everything in §2B is Phase 2 (gated, §0A).** Phase 1 builds none of it except §2B.4's pure scorer and map
(D7) and the outcome log (D8a). Where §2B.1-§2B.6 and §2B.7 disagree, §2B.7 wins.

### 2B.1 What the code does today (verified 2026-11-12)

- `_resolve_egress_face_identity` (`transit_validator.py:1357`) has three outcome families. BLE-leg branches
  (`attached_ble`, `attached_ble_face_corroborated`, `:1600-1790`) return BEFORE the veto, so BLE identity is never
  vetoed. Only the FACE-ONLY single-slug path reaches the veto at `:1840-1854`: raw `person.<slug>.state == "not_home"`
  -> outcome `vetoed`, `(None, None, SINGLE)`. Missing / unknown / unavailable person -> not vetoed (fail-open).
- **Rev 9 correction (completeness M1): the veto tests `== "not_home"` only (`:1846-1847`).** A resident in a named zone
  (`Work`) is NOT vetoed today: the crossing is `attached`, an entry registers the slug in the census union, an exit
  evicts it. Manual §5.4 already says "a mislabelled entry crossing can still register a slug via the egress union".
- The veto ignores `direction`. It runs when the identity is resolved, i.e. inside `_resolve_direction` (`:1925`),
  which is scheduled `ENTRY_WINDOW_SECONDS` = 45 s after the egress edge (`:1256-1275`, `const.py:3296`), so a phone
  whose home edge lands inside those 45 s is `attached` and one that lands later is vetoed.
- Its origin: the census stale-face latch guard (`camera_census.py:6283-6338`). That guard answers "who is in the house
  NOW" and protects against a STALE face sensor. The egress plan copied it ("veto preserved",
  `PLANNING_egress_identity_producer.md:286-290`); a second copy exists as `census.is_face_leg_person_vetoed`
  (`camera_census.py:4497`, unconsumed per `transit_validator.py:1522-1527`).
- Its effect by direction:
  - **Entry:** every face-only arrival of a person whose phone has not yet reached home is erased. That is the arrival
    case itself (why rev 2 H1 found named entries were only ever already-home people).
  - **Exit:** a departing person's tracker usually still reads `home`, so the veto rarely fires; when it fires (tracker
    already `not_home`) the person is away by the tracker: a stale face or a misrecognition. Reasonable there.
- What the veto protected against, on entries: (a) a stale or flapping face sensor re-stamping an old name (FS-2,
  `:1499-1508`; the per-leg wall-clock staleness gate `:1509-1550` and the signed-lag window already cover it); (b) a
  resident's face matched on someone else while that resident is away (10-24, Jaya named as Oji, presence §10 #28).
  (b) needs a replacement, and §2B.3 says honestly how much of (b) can be caught at the crossing.

### 2B.2 The rule (replaces the face-only veto at `:1840-1854`, behind `EGRESS_IDENTITY_DIRECTION_AWARE`)

On the face-only single-slug path, with raw state `S = person.<slug>.state`:

| Direction | `S` | Outcome (switch on) | Bus / DB `person_id` at the crossing | Today (switch off, unchanged) |
|---|---|---|---|---|
| entry | `home` | `attached` | slug | same |
| entry | `not_home` or a named zone | **`arrival_candidate`** (PROVISIONAL, §2B.3a) if the guards in §2B.3 allow, else `vetoed_arrival_unverified` (failed guard recorded) | **None** in both. The slug travels only in the bus key `candidate_person_id` and the waiter | `not_home`: `vetoed`, None. Zone: `attached`, slug, union register |
| entry | missing / unknown / unavailable | `attached` (fail-open) | slug | same |
| exit | `home` | **`departure_candidate`** (tracker has not yet seen the departure) | slug, evict as today | `attached` (label only changes) |
| exit | `not_home` or a named zone | `vetoed` | None, no evict | `not_home`: `vetoed`. Zone: `attached` + evict |
| exit | missing / unknown / unavailable | `attached` | slug | same |
| ambiguous | any | unchanged (`direction_ambiguous`, never reaches the veto, `:1430`) | None | same |

**Switch-on deltas against today, declared (INV-NOOP):** entry + zone (attached -> provisional candidate: no union
register, no name until confirmed); exit + zone (attached -> vetoed: no evict, `person_id` None); the labels for entry +
`not_home` and exit + `home`. BLE branches are unchanged. Nothing else changes at the crossing.

**Bus keys, switch on only:** `identity_role` (`attached` / `arrival_candidate` / `departure_candidate` /
`vetoed_arrival_unverified` / `vetoed`), `candidate_person_id` (candidates only), `identity_guards` (dict guard ->
`pass` / `fail` / `skipped` + reason; candidates and `vetoed_arrival_unverified`), `path_score` (int, or None when the
door has no map). **Switch off: these keys are ABSENT** (not null), no path is computed, no extra subscription exists,
no waiter is created.

**Resolver channel (build L4, completeness L4).** `_resolve_egress_face_identity` returns a 4-tuple
`(person_id, identity_confidence, agreement_class, role)` where `role` is a frozen `EgressRoleResult(role,
candidate_slug, guards, path_score)` built fresh in the call, or None on every early return and whenever the switch is
False. One call site, `transit_validator.py:2011`. No `self._last_*` stash, so a role cannot leak from an earlier
crossing.

### 2B.3 What discriminates a misnamed person, honestly (completeness H3)

Rev 8 sold G1-G3 as a replacement for the veto's protection. The completeness review showed they are not, for the case
they were named for. What each signal can and cannot tell at the moment of resolution:

| Signal | Separates a misnamed person from the real one? |
|---|---|
| G1 face confidence | **No** for a consistent mislabel: two cameras agreeing on the wrong name give 0.9 (`transit_validator.py:1858-1883`). It only removes single-recognizer noise. |
| G2 path | **No.** It proves a body walked outside -> door -> inside (a real entry, not a stale sensor or someone indoors passing the door). Identity-blind. |
| G3 GPS, implied speed | **Yes, when the named person's phone has reported recently enough** that being here is impossible. No when the phone is silent for a day or more. |
| Non-face corroboration AFTER the crossing (phone home edge, Bermuda placing the phone in the house, near-home GPS fix) | **Yes.** A real arrival brings that person's phone; a misnamed person does not. Knowable only minutes later. |

So the design (operator direction 2026-11-12): the guards decide only whether a candidate is opened; **the name is
withheld from every consumer until the after-the-fact corroboration (§2B.3a)**. A phoneless real arrival is never
confirmed and stays "Someone arrived" (graceful-anonymous doctrine, manual §3 rule 6). Access is unchanged (INV-ACCESS).

Guards (all evaluated at the resolution instant; any `fail` -> `vetoed_arrival_unverified`):

| Guard | Rule | Source (REUSE) | Missing input |
|---|---|---|---|
| G1 face confidence | `identity_confidence >= EGRESS_ARRIVAL_CANDIDATE_MIN_CONFIDENCE` (rung 1, 0.75) AND not synthetic-only. **Synthetic-only defined for every tier (completeness L2):** at 0.9 the existing `_last_identity_synthetic_corroborated`; below 0.9, any contributing leg with `FaceLeg.synthetic`. (On this house 0.75 cannot come from a synthetic plus a live leg, because legs dedup by (slug, engine, base_stem), `camera_census.py:3572-3588`; still tested.) | egress confidence ladder (manual §5.3), `FaceLeg.synthetic` | n/a |
| G2 path | `path_score >= EGRESS_ARRIVAL_PATH_MIN` (rung 1, default 2; D0-P7 may move it). **`EGRESS_ARRIVAL_PATH_MIN = 0` means G2 is not evaluated** (`skipped`, reason `disabled`), not "score >= 0" (completeness L3). | D7 map + §2B.4 | door without a map -> `skipped`; the candidate then needs G1 at 0.9 non-synthetic |
| G3 implied speed | Fix = the person's **freshest GPS `device_tracker`**: the trackers in `person.<slug>.attributes.device_trackers` whose state has `source_type == "gps"` and numeric `latitude`/`longitude`, the newest by that tracker's own `last_updated` (comparator `person_coordinator._gps_newer_or_equal`). `d` = max(0, `distance(fix, zone.home)` − the tracker's `gps_accuracy` − `zone.home` radius), km. `age` = resolution time − fix time, floored at `EGRESS_ARRIVAL_GPS_MIN_AGE_S` (60). **FAIL iff d / age > `EGRESS_ARRIVAL_MAX_SPEED_KMH`** (rung 1, 150). `person.*` `last_updated` is never used (it moves on any source change). The lock regime's proximity sensors are NOT used: `CONF_SECURITY_LOCKOUT_DISTANCE_SENSORS` is a flat list not keyed by person (`security_lock_regime.py:351-356`), so mapping one to a person would be name-building (build M3). | person attributes + tracker states; `homeassistant.util.location.distance`; new pure helper `arrival_edges.freshest_gps_fix` | no GPS tracker, no coordinates, or fix older than `EGRESS_ARRIVAL_GPS_MAX_AGE_S` (86400) -> `skipped` |
| G4 no conflicting name | the existing abstain / disagree rules (`:1800-1835`) returned a single slug | unchanged | n/a |

Worked G3 cases: fix 3 h old in Lagos (~9,000 km) -> 3,000 km/h -> FAIL (the 10-24 shape whenever the phone had
reported). Driving home, fix 3 km and 8 min old -> 22 km/h -> pass. 27 km and 5 min -> 324 km/h -> FAIL. Flying home
with no fix since departure 4 h earlier at 2,000 km -> 500 km/h -> FAIL on a TRUE arrival: the cost is a name that
arrives a few minutes later from the phone's own geofence arrival, never a wrong name. D0-P7 reports G3 false-fails on
true arrivals by fix-age bucket (build M3).

Recorded, not guards: `away_for_s`, `gps_fix_age_s`, `gps_implied_kmh`. Parked (no data yet): a "confusable resident is
home" guard; revival trigger: D0-P7 shows misrecognitions concentrated in one resident pair.

### 2B.3a Provisional candidate and confirmation (rev 9)

At the crossing (resolution instant), for an `arrival_candidate`: bus `person_id` None, `candidate_person_id` = slug,
`identity_role` = `arrival_candidate`; DB row `person_id` NULL (INSERT unchanged); notification "Someone arrived" (the
existing anonymous branch, because `person_id` is None); no union register (the existing `if person_id` gate at
`:2086`); no sighting; perimeter D10.5 sees no identity. A `vetoed_arrival_unverified` crossing is the same minus the
waiter.

**Waiter (build M6).** One per slug, owned by the egress tracker (`_arrival_waiters: dict[slug, _CandidateWaiter]`):
- Poll every `EGRESS_ARRIVAL_CONFIRM_POLL_S` (rung 1, 5) with `async_track_time_interval`; the unsub lives in the
  waiter and every waiter is cancelled in the tracker's existing teardown. Not persisted: a restart drops pending
  waiters and their rows stay NULL.
- Expiry at `crossing_ts + EGRESS_ARRIVAL_CONFIRM_WINDOW_S` (rung 1, 600) -> outcome log `arrival_unconfirmed`.
- Supersession: a new candidate for the same slug cancels the older waiter (`arrival_superseded`).
- Cap `EGRESS_ARRIVAL_MAX_PENDING` (rung 1, 8): a candidate beyond the cap gets no waiter (`arrival_not_waited`).
- **Confirmation = the FIRST of these, each with its own timestamp strictly after `crossing_ts` and at most
  `crossing_ts + window`** (an edge before the crossing never confirms; that person would have read `home` at
  resolution and been `attached`):
  - (a) tracker: `person.<slug>` reads `home`, `last_changed > crossing_ts`, and
    `arrival_edges.stale_source_arrival(...)` is False (the suspicious-arrival rule: a stale-source blip never confirms);
  - (b) BLE: PersonCoordinator data for the slug has `method == "bermuda"`, a `location` that is a URA room (not
    away / unknown), and `last_changed > crossing_ts`;
  - (c) GPS home-zone with approach (rev 10, completeness H1): `freshest_gps_fix` with fix time `> crossing_ts`
    and `d == 0` (inside `zone.home` radius plus the fix's accuracy), AND an earlier fix (G3's fix, or the last fix
    before `crossing_ts`) with `d > EGRESS_ARRIVAL_CONFIRM_GPS_KM` (rung 1, 0.5; 0 = leg off). Any near fix is no
    longer enough.
  - **Abstain rules for every leg (rev 10):** outcome `arrival_confirm_ambiguous`, no naming, when (i) any other egress
    crossing (any door, entry or exit, named or not; from the tracker's RAM deque `_recent_crossings`) resolves in
    (`crossing_ts`, edge time], or (ii) the same slug has a later candidate. So a tracker edge after someone else came
    through another watched door never confirms this crossing. Named residual: a door with no egress camera (patio,
    §13.4) is invisible to this rule; P7's operator review measures it.
  - Leg (a) passes `stale_s = LOCK_ARRIVAL_STALE_SOURCE_S` (`const.py:3759`). Leg (b) maps slug -> PersonCoordinator key
    through the tracked-person registry mapping (`person.<slug>` entity -> the tracked person whose `person_entity`
    is that id), never `_find_person_entity` string building (completeness L10).
- **Waiter is created only after the INSERT** (build H2): `_resolve_direction` awaits `log_entry_exit_event`, which
  returns the row id (§1.2c); the waiter stores that id. INSERT failed (None) -> no waiter, outcome
  `arrival_not_waited` reason `no_row`.
- On confirmation, in this order, one tracked task (`_confirm_tasks` set, cancelled and gathered with a bound in
  teardown), each step best-effort and logged; **`switch.ura_name_people_at_doors` is fresh-read before the DB write,
  before the signal and before the sighting** (completeness M2; OFF -> count `arrival_confirm_disabled_skip`, write
  nothing):
  1. DB: `backfill_entry_exit_person_id(row_id, slug, conf)` with the stored row id (no time bracket, no camera
     match, no LIMIT; writes `person_id` only; the `person_id IS NULL` guard makes a double fire a no-op). It returns
     whether a row changed; a False return is logged `arrival_confirm_row_missing` and the waiter retries on the next
     poll until expiry, sending nothing else until the row is named (build H2).
  2. `SIGNAL_EGRESS_ENTRY_CONFIRMED` {`person_id`, `egress_camera`, `timestamp` (crossing), `identity_confidence`,
     `identity_provenance: "face"`, `confirmed_by` (`tracker` / `ble` / `gps`), `confirm_lag_s`}. Readers: Persons
     Entered Today and Last Person Entry re-read (as the exit-backfill readers do), and sighting source (c') (§3.2).
  3. One quiet "That was <Name>" through `_arrival_departure_notify` (a `followup` branch of the ONE notify site), only
     while `switch.ura_name_people_at_doors` is on (fresh-read at send).
  4. Never a census register (INV-CENSUS-HOME): the person enters the census through the BLE/tracker evidence that
     confirmed them.
- `EGRESS_ARRIVAL_CONFIRM_WINDOW_S = 0` = candidates are labels only (never confirmed, never named).

This is the exit-backfill pattern (manual §4.3a) applied to entries, with the perimeter follow-up's poll shape (§4.5).

### 2B.7 Rev 10 fixes to the Phase 2 design (both rev-9 reviews; wins over §2B.1-§2B.6)

- **Wrong-person confirmation (completeness H1):** leg (c) home-zone + approach; abstain on any intervening crossing
  or a later candidate for the slug (§2B.3a). P7 reports wrong confirmations per leg.
- **Row by id, after the INSERT, with retry (build H1/H2, completeness H2):** §2B.3a. Test drives the real scheduled
  path (`_on_egress_state_change` -> `async_call_later` 45 s -> `_resolve_direction` INSERT) with time advanced, and a
  deferred INSERT plus an immediate BLE edge: "That was X" goes out only after the row is named.
- **Display leak (completeness M3):** the `arrival_candidate` and `vetoed_arrival_unverified` branches return before
  any write of `census._egress_identity_last_attach` (writers `transit_validator.py:1657, :1705, :1769, :1908`; display
  `sensor.py:3978-3980`). `egress_identity_last_attach` is added to INV-PROVISIONAL's consumer list. Test
  `test_candidate_does_not_write_last_attach`; drill M35.
- **BLE duplicate (completeness M5):** rule 5 also skips with `arrival_already_dispatched` when presence saw a
  geofence or ble `SIGNAL_PERSON_ARRIVING` for the person after `crossing_ts` (presence records the last such ts per
  slug in its existing listener path). The P7 go rule counts GPS-confirmed leads only.
- **Rule 5 skip label (completeness L5):** a tracker-confirmed candidate reads raw `home`, so the skip reason is
  `home`. Test renamed `test_tracker_confirmed_skips_home`; the D8b Verify says `home`.
- **Waiter lifecycle (build M5):** teardown writes one `arrival_dropped_teardown` outcome row per pending waiter
  (best-effort, bounded by the same gather timeout); the poll unsub lives only in the waiter, never in `self._unsub`
  (confirmation and expiry call it); supersession logs `arrival_superseded` with the slug and both crossing ts, the
  older row stays NULL; confirmation tasks are in `_confirm_tasks`, cancelled and gathered in `async_teardown`
  before the DB worker stops. Test `test_unload_during_confirmation`.
- **Bus keys (build L4):** for `departure_candidate`, `person_id` IS the slug (the evict reads it);
  `candidate_person_id` is set only for `arrival_candidate`.
- **G3 timestamp (build L1):** keep the tracker's `last_updated`. A GPS device_tracker's state is a zone name, so
  `last_changed` moves only on a zone change and would make every fix look hours old (speed too low, fail open).
  `last_updated` also moves on an attribute-only refresh (battery), which makes a fix look younger and the speed
  higher: fail closed. P7 reports G3 verdicts under both timestamps.
- **G2 test constructibility (build L3):** `test_g2_no_map_requires_0_9` uses two live recognizer legs on different
  cameras (the only non-synthetic 0.9).
- **G2 knob semantics (completeness L9):** `EGRESS_ARRIVAL_PATH_MIN = 0` skips G2, and a skipped G2 requires G1 at 0.9;
  so 0 TIGHTENS G1. Stated on the knob (§6).
- **Zone union delta (completeness L11):** "exit + zone -> vetoed, no evict" can leave an entry-registered slug in the
  union for up to `EGRESS_FACE_UNION_TTL_S` (300 s), the same as `not_home` today. Declared with the switch-on deltas.
- **Exit horizon (completeness L7):** P7's replay applies the same per-list horizons as runtime (75 s interior lists,
  180 s `_path_events`), so EGRESS-PATH-OVERRIDES-DIRECTION-1 evidence is not biased.
- **Map re-validation (completeness L8):** the path map is re-validated on a door-group / egress-camera options change
  and on `EVENT_ENTITY_REGISTRY_UPDATED` (debounced), same triggers as picks (§3.2).
- **HVAC `camera_egress` (Phase 2 only):** default, selector, help text, the `hvac.py:881` literal, and the one-shot
  migration move here. The migration reads the MERGED view `{**ce.data, **ce.options}` (the HVAC read,
  `hvac.py:1434-1438`) and writes `options`; it uses the EC-pin pattern (`_bootstrap_pin_ec_defaults_once`
  `__init__.py:825`, listener snapshot reseeded) so the write does not trigger a reload; INV-NOOP names the one-time
  write. Tests `test_migration_reads_key_from_data`, `test_setup_runs_camera_egress_migration` (wiring anchor; drill
  M28 second half points at it). The HVAC_ARCHITECTURE_STATE_OF_PLAY edit ships in the same commit as the HVAC change
  (completeness L2).
- **Departure note:** no `SIGNAL_PERSON_DEPARTING`; unchanged.

Phase 2 is reviewed again (completeness + build-prediction) before its build, against this text.

### 2B.4 Path score: map, event sources, decision time, horizon (build H2, completeness M4/M5)

Today direction = the closest interior-neighbour edge within +45 s (entry) or −30 s (exit) of the egress edge, and
`confidence` = 0.9 / 0.8 by platform count (`transit_validator.py:1953-2000`). One interior hit is the whole evidence.

- **Decision time T** = the existing resolution instant, egress edge `t_E` + `ENTRY_WINDOW_SECONDS` (45 s). Resolution
  timing is unchanged for every crossing (no delay, so notification latency, DB write time and the perimeter match
  window are unchanged).
- **Map (D7):** per door group, a DAG whose nodes are physical cameras (`canonical_camera_key`) and whose directed edges
  are typed `approach` (outside, toward the door) or `inward` (door, deeper inside), each with an optional measured
  window `lag_p90_s` (absent -> `EGRESS_PATH_HOP_DEFAULT_WINDOW_S`, 30) and `same_view` pairs. A camera appears once,
  whatever "stage" the fixture lists it in; the edge type carries the stage.
- **Event sources.** Interior nodes already in `_interior_entities` use the existing interior event lists (subscription
  `:1047-1055`, prune `max(ENTRY, EXIT) + 30` = 75 s, `:2254`, unchanged). Every other map node (exterior approach
  cameras, deeper interior cameras) has its person legs, resolved through `CameraResolver.resolve_operator_declaration`
  (Frigate and Protect legs, never string-built), subscribed by the same mechanism into a separate `_path_events` list,
  pruned at `EGRESS_PATH_BUFFER_S` (rung 1, 180). Subscribed only while `EGRESS_IDENTITY_DIRECTION_AWARE` is True and a
  map is loaded; released in the existing teardown and re-made on a map reload.
- **Horizon.** Only edges with timestamp `<= T` count.
  - Entry: `approach` edges u -> v with `t_E − EGRESS_PATH_BUFFER_S <= t_u < t_v <= t_E` (v may be the egress camera);
    `inward` edges with `t_E <= t_u < t_v <= T` (u may be the egress camera).
  - Exit: `inward` edges observed reversed with `T − 75 <= t < t_E` (what the interior buffer still holds at T, i.e.
    from `t_E − 30`); `approach` edges observed reversed with `t_E <= t <= T`.
- **Score.** +1 per distinct map edge observed in the crossing's direction within its window and the horizon; −1 per
  distinct edge observed against it. Each edge contributes at most +1 and at most −1. Never scored: an edge whose two
  ends are both egress cameras of the crossing's door group (build M5: Entry way and front_door_aerial; Doorbell Lite and
  Garage A under today's groups); `same_view` pairs; two legs of one physical camera.
- **One scorer, two callers.** The scorer is a pure function `interior_paths.score_path(map, door, direction, t_E, T,
  events)` in the HA-free module. D0-P7 runs it by concatenating `interior_paths.py` with the probe body into the
  `ssh ha "python3 -"` stdin, so the probe computes the score the runtime can compute, with the same horizon
  (`test_probe_and_runtime_share_scorer`).
- Golden: garage entry Back PTZ (t_E−20) -> Garage A (t_E) -> Garage hallway/stairs (t_E+8) -> Stair top (t_E+25) = 3;
  the same crossing with Game room at t_E+60 (after T) still scores 3.
- Path scoring never changes the resolved direction this cycle (non-goal). D0-P7 reports how often `path_score <= 0`
  coincides with a resolved direction (evidence for EGRESS-PATH-OVERRIDES-DIRECTION-1).

### 2B.5 Consumers of the vetoed outcome and of egress `person_id` (per consumer, rev 9)

| Consumer | file:line | Effect of §2B (switch on) | Change |
|---|---|---|---|
| Census union (`register_egress_face` on entry, `evict_egress_face` on exit) | `transit_validator.py:2075-2100`; `camera_census.py:4139`, `:4210`, read `_get_egress_face_ids_fresh` `:4236` | A candidate has `person_id` None, so the existing `if person_id` gate (`:2086`) skips the register. Confirmation never registers. `departure_candidate` evicts as today. Exit + zone is now `vetoed`: no evict (declared). | None at the register site; tests + drill M20 pin both paths |
| Census face veto | `camera_census.py:6283-6338` | n/a | None |
| Four display sensors | `sensor.py` `_handle_egress_event` (`:4759`, `:4904`, `:4990`, `:5103`); rehydrate `database.get_entry_exit_events_since` `:4654` | No name at the crossing. Entered Today and Last Entry re-read on `SIGNAL_EGRESS_ENTRY_CONFIRMED` (mirror of the exit-backfill readers `:4891`, `:5045`). Rehydrate shows confirmed names only. | Two listeners |
| Attach-rate diagnostics | `sensor.py:3936-3956` (counts `out == "attached"`, `:3950`) | `departure_candidate` would drop the attach rate with no change in reality (completeness M2) | Count `out in EGRESS_OUTCOMES_ATTACHED`; add `arrival_candidates_24h`, `arrival_confirmed_24h`, `arrival_unconfirmed_24h` |
| `_egress_identity_last_attach` | writers `transit_validator.py:1657, :1705, :1769, :1908`; readers `:2084-2088`, `sensor.py:3978` | A candidate makes no attach, so nothing is written; the readers at `:2084-2088` sit behind `if person_id`, so a stale previous provenance is never read for a candidate (completeness M2). The confirmation carries `identity_provenance: face` in its own payload. | None; test `test_candidate_never_reads_stale_last_attach` |
| DB `person_entry_exit_events.person_id` | `database.py:1090-1103` | Meaning, documented in manual §4.6 / §5.5 (D5): NULL at INSERT for a candidate; set later only by a non-face-corroborated confirmation or by the exit backfill. No role column, no schema change. A future 6.0.0 consumer keyed on DB `person_id` never sees an unconfirmed candidate. | Doc only |
| Notification `_arrival_departure_notify` | `transit_validator.py:2140` (names at `>= ARRIVAL_NAME_CONFIDENCE_THRESHOLD` 0.75) | Candidate and `vetoed_arrival_unverified`: "Someone arrived" now (unchanged code path). Confirmation: one quiet "That was X". `departure_candidate`: "X left" as today. | One `followup` branch in the one site |
| Perimeter D10.5 | `perimeter_alert.py:1006`, `:4985-5015` | Sees `person_id` None for a candidate: no known identity, no de-escalation. Never reads `candidate_person_id`. | None (rev 8's perimeter change is withdrawn); test with a 0.9 non-synthetic candidate (build L1) |
| Phone-left-behind | `binary_sensor.py:2196-2218` | Unaffected (store written from camera attributes) | None (PHONE-LEFT-BEHIND-CAMERA-LEG-1) |
| Exit backfill | `camera_census._backfill_exit_identity` | Unaffected: it queries `direction = 'exit'` (default of the extended DAO) | None |
| Sightings | §3.2 | Candidate: none at the crossing. Confirmation: one `egress_entry` sighting, `identity_role = arrival_confirmed` | Source (c') |
| HVAC | `hvac.py:7231` source filter; `hvac.py:1436` option read; default `hvac_const.py:350` | Without a change HVAC drops every `camera_egress` arrival (build H1, completeness H1) | D8a adds `camera_egress` to the default, the selector and the stored option (migration) |
| Access (lock regime, security, disarm) | §3.4 | Only through D2 -> `SIGNAL_PERSON_ARRIVING(camera_egress)`, which needs `face_input_corroborated` | `camera_egress` in `CAMERA_DERIVED_ARRIVAL_SOURCES` |
| Outcome log (new) | §9 D8a | One memory_episodes row per resolution, switch on or off | New writer |

### 2B.6 Egress arrivals and departures as a source (FACE-EGRESS-ARRIVAL-1, folded into EGRESS-DIRECTION-AWARE-IDENTITY-1)

- **Arrivals.** The one D2 site (§3.3) dispatches `SIGNAL_PERSON_ARRIVING(source="camera_egress")` for an `egress_entry`
  sighting with `identity_role == "arrival_confirmed"` when `FACE_ARRIVAL_EGRESS_ENABLED` (rung 1, default False until
  D0-P7 passes). That sighting exists only at confirmation, so rules 3-6 of §3.3 are evaluated then. Rule 5 is the
  discriminator: a tracker-confirmed candidate reads `home` -> `home` skip (geofence already dispatched); a
  BLE-confirmed one is skipped `arrival_already_dispatched` (§2B.7); only a GPS-confirmed candidate before any
  geofence/ble arrival dispatches.
- **HVAC must accept it (both H1).** D8a adds `camera_egress` to `DEFAULT_PRE_ARRIVAL_SOURCES` (`hvac_const.py:350`),
  to the options selector (`config_flow.py:8192-8201`, label "Camera at a door (confirmed arrival)"), and migrates the
  live CM option (`pre_arrival_sources = ['geofence', 'ble', 'camera_face']`, read 2026-11-12) once: append
  `camera_egress` when the stored list contains `camera_face` and lacks it (an operator who removed `camera_face` keeps
  camera arrivals off), sentinel `pre_arrival_sources_camera_egress_migration_done`, same call site and shape as
  `_migrate_hvac_zone_entry_dwell_to_zero` (`__init__.py:749`). HVAC logic and the filter at `hvac.py:7231` are not
  changed.
- `FACE_ARRIVAL_EGRESS_ENABLED = True` with `EGRESS_IDENTITY_DIRECTION_AWARE = False`: no candidate can exist, nothing
  dispatches (pinned by `test_egress_flag_without_direction_aware_inert`).
- **Reconciling rev 2 H1.** H1 said an egress arrival would duplicate geofence/ble; true while only already-home people
  survived the veto. A confirmed candidate is someone the tracker had NOT seen home; when the phone's own edge follows,
  HVAC's episode guard (`pre_arrival_spent`) and the per-person debounce absorb it.
- **Access invariant.** Face or vision alone never unlocks, releases, disarms or adds an expected arrival:
  `camera_egress` is in `CAMERA_DERIVED_ARRIVAL_SOURCES`; both gates (§3.4) require `face_input_corroborated`.
- **Departures.** No `SIGNAL_PERSON_DEPARTING` exists (grep: 0 hits) and none is added. A `departure_candidate` is a
  labelled exit row + sighting + the existing notification and census evict. Consumers: card DEPARTURE-ACTIONS-1.

---

## 2. Falsifiable invariants (reviewer D breaks these)

**INV-ACCESS (load-bearing; rev 3 widens "face-derived" to "camera-derived identity", so a future `vision`
provenance is covered with no new invariant).** In any reachable path, a camera-derived identity input (any
`PersonSighting`, whatever its provenance, or a `SIGNAL_PERSON_ARRIVING` whose `source` is in
`CAMERA_DERIVED_ARRIVAL_SOURCES`) can never, on its own, cause:
garage-lockout release (`SecurityLockRegime._release`), away-lock unlock (`_away_release`), an expected-arrival entry
(`SanctionChecker.add_expected_arrival`, `security.py:257`, consumed person-agnostically at `:302`), or a security
disarm (`SecurityCoordinator.handle_disarm`, `security.py:2472`).

- "Camera-derived input" = a `PersonSighting`, or a `SIGNAL_PERSON_ARRIVING` whose `source` is a member of
  `CAMERA_DERIVED_ARRIVAL_SOURCES` (rung-1 frozenset in `const.py`; **`{"camera_face", "camera_egress"}` from D8a on**,
  rev 9 M6; a future `camera_vision` / `interior_track` source is added there, once). Rev 4 (M5): the lock regime
  (`security_lock_regime.py:1017`, today a literal `== "camera_face"`) and the security gate (§3.4) both test
  membership in this set. A source string that is in neither the set nor the known non-camera set (`geofence`, `ble`)
  is treated as camera-derived (fail closed): pinned by `test_unknown_arrival_source_requires_corroboration`.
- Such an action needs an independent non-face arrival edge for the SAME person per
  `arrival_edges.nonface_arrival_source`, within `PERIMETER_EGRESS_FACE_NONFACE_WINDOW_S` (120 s), outside the boot
  exclusion, **as judged by the lock regime's `face_input_corroborated`**. No lock regime (None, torn down, setup
  raised) = not corroborated = reject.
- Falsifier: any legal config + state where a face input reaches one of those four sinks without that edge. Configs
  include alias set/unset, `security_on_arrival_add_expected` True, both lock switches ON, window 0, lock regime
  None, egress `identity_confidence` 0.9 with a synthetic leg, an HA restart (restored face sensors), and (rev 9) a
  `camera_egress` arrival confirmed by a GPS-near fix only.
- **Scope:** the pre-existing path "camera body -> census count -> `has_people` -> AWAY -> ARRIVING
  (`presence.py:1367-1369`) -> lock release / auto-follow disarm" is body evidence, not a name. Not widened (no
  sighting feeds census or inference, §8). D confirms "not widened"; a NAMED face changing that path's outcome
  where a nameless body would not is a finding. The path itself is carded (§12).
- **Rev 9 (D7):** the path map never feeds `door_entry_areas` (`arrival_edges.py:223`), so it cannot widen the lock
  regime's Bermuda corroboration areas (pinned by `test_entry_areas_near_areas_direction_identical_with_map`).

**INV-PRODUCER (fire-check).** The sighting producer is never disabled, filtered or narrowed to protect a consumer.
No constant or branch in the producer reads a consumer's identity or action class.
`FACE_SOURCE_PRESENCE_ARRIVAL_DISAMBIGUATED` is retired (KEEP + DOCUMENT, no reader). Producer filters are about
evidence quality only (§3.2). Falsifier: a recognised resident face on any resolved pick, including a `_N` person
sensor and the URA fused Garage A pick, that produces no `SIGNAL_PERSON_SIGHTING` while `face_recognition_enabled`,
`FACE_SIGHTING_ENABLED`, outside the boot exclusion and not `_face_suppressed_now()`.

**INV-PROVENANCE (F2; rev 4 L1; rev 9).** A `PersonSighting` exists only for real face evidence, or for vision
evidence under the sibling plan's rules (§15.3 item 5). An egress identity whose provenance is `ble` never becomes a
sighting. A face-only egress identity that is `attached` or `departure_candidate` becomes a sighting at the crossing;
an `arrival_candidate` becomes one only at confirmation, never before. Falsifier: an egress event with
`identity_provenance == "ble"` that yields a sighting; a face-only egress crossing (real `_resolve_egress_face_identity`
path, no BLE leg) whose bus event lacks `identity_provenance == "face"`; or a sighting for a candidate that was never
confirmed.

**INV-NOOP.** With `FACE_SIGHTING_ENABLED = False`, the four `SIGNAL_PERSON_ARRIVING` consumers see exactly the
dispatches they see on develop today (zero `camera_face`), no new listener or census hook is registered, and the
only producer-side changes outside presence are the additive egress bus key and the explicit face provenance write
(both value-identical for existing readers). Rev 4 (L5): the census post-sentinel ring (§3.5) is gated on
`FACE_SIGHTING_ENABLED`; with it False the ring is not created or appended.
**Rev 9 (build M4), `EGRESS_IDENTITY_DIRECTION_AWARE = False`:** the outcome deque label, every column of the DB row,
the notification title, the census register/evict calls and the bus dict are byte-identical to develop, except two
switch-independent additions: D1's `identity_provenance` bus key, and D8a's outcome-log memory_episodes row (own kill
switch `EGRESS_OUTCOME_LOG_PERSIST`). The keys `identity_role`, `candidate_person_id`, `identity_guards`, `path_score`
are ABSENT; no path-node subscription is registered; no path score is computed; no waiter is created. D8a's other
switch-independent changes are inert on behaviour: the HVAC source option gains `camera_egress` (no producer dispatches
it while the egress branch is off), and the attach-rate set `EGRESS_OUTCOMES_ATTACHED` equals `{"attached"}` in effect
because `departure_candidate` cannot occur. The golden replay (`test_switch_off_golden_replay`) compares the full bus
dict minus `identity_provenance`, the DB row, the outcome label and the notification title, over a fixture that MUST
contain entry x {home, not_home, named zone, unknown} and exit x {home, not_home, named zone}.
**Switch-on deltas (declared, not violations):** entry + zone -> provisional candidate; exit + zone -> vetoed (no evict);
labels for entry + `not_home` and exit + `home`.

**INV-NOOP, Phase 1 form (rev 10, build M4 / completeness M4).** With `EGRESS_OUTCOME_LOG_PERSIST = False` and
`FACE_SIGHTING_ENABLED = False`, the egress bus dict minus `identity_provenance`, the DB row, the outcome deque label,
the notification title, the census register/evict calls, `egress_identity_correlated_boost_count_24h` and the bus
`identity_synthetic_corroborated` are byte-identical to develop. With the log ON, the only additional effect is one
memory_episodes row per resolution. The pure tier helper has no side effects; the existing confidence block calls the
same helper for its arithmetic and keeps its stash and ledger append in place. Golden `test_switch_off_golden_replay`
fixture includes a vetoed 0.75 crossing and a vetoed synthetic 0.9 crossing.

**INV-LOG (rev 10, Phase 1).** Every call of `_resolve_egress_face_identity` yields exactly one outcome record, on
every return path (no legs, abstain, disagree, ambiguous, vetoed, attached), slug None when there is none; no decision
reads the record or the row. Falsifier: a resolution with zero rows or two rows (switch on), or any output above that
changes with the log on vs off.

**INV-CENSUS-HOME (rev 8; rev 9).** An egress `arrival_candidate` never enters the census identified set: under any
config, `register_egress_face` is never called for a candidate's slug, at the crossing or at confirmation. Falsifier: a
face-only entry for a `not_home` resident, all guards passing, after which `_get_egress_face_ids_fresh` contains that
slug through the egress path (it may later contain it through BLE/tracker evidence, which is not this path).

**INV-PROVISIONAL (rev 9, new; operator direction).** Before confirmation, no consumer receives a candidate's slug as an
identity: the bus `person_id`, the DB `person_id`, the notification name, the four displays, the census union,
perimeter D10.5, `SIGNAL_PERSON_SIGHTING` and `SIGNAL_PERSON_ARRIVING` all carry None or nothing for it. Only
`candidate_person_id` (diagnostic, read by no decision) and the waiter hold it. Falsifier: any of those carrying the
slug with no confirming edge (a, b or c of §2B.3a) timestamped after the crossing.

**INV-CANDIDATE (rev 8; rev 9).** An `arrival_candidate` exists only when G1 passes, G3 does not fail, and G2 passes or
is `skipped` with G1 at 0.9 non-synthetic (§2B.3). Falsifier: a candidate with `identity_confidence` 0.6, OR with any
synthetic contributing leg below 0.9, OR whose freshest GPS fix implies a speed above `EGRESS_ARRIVAL_MAX_SPEED_KMH`,
OR with `path_score` below the minimum on a door that has a map, OR (G2 `skipped`) below 0.9.

---

## 3. Design

### 3.1 The one signal

`SIGNAL_PERSON_SIGHTING = "ura_person_sighting"` (`signals.py`). Payload: frozen dataclass `PersonSighting`
(`person_sighting.py`):

| Field | Meaning |
|---|---|
| `person_entity`, `slug`, `face_name` | `person.<slug>` from the census mapper; raw Frigate name. Unmapped names emit nothing and are counted in `unmapped_names`. |
| `camera` | Interior: the pick entity id. Egress: the egress camera id. |
| `physical_camera` | The dedup key, ONE definition (rev 4, M1): `canonical_camera_key(fusion)` = min `device_id` over the matched fusion's full source set. Interior (any pick kind) and egress (the fired egress entity's fusion) use the same helper. |
| `person_state_at_emit` | Rev 4 (M4). Raw `person.<slug>` state when the sighting is emitted (None if missing). |
| `census_would_veto` | Rev 4 (M4). True when the census face path would drop this face (not_home, or BLE-Leads overrule), from the census's own predicate. Display/consumer hint only; the producer does not filter on it. |
| `area_id`, `room` | Via `resolve_area_id_for_entity`, then the URA room whose `CONF_AREA_ID` matches; None if no room. **Egress: where the crossing happened, NOT where the face was seen** (the egress identity may come from an interior face up to 300 s earlier, manual §5.2). |
| `house_zones` | Sorted tuple (L2) of house zones whose picks include this pick. Egress: zone of `room`, else `()`. |
| `ts` | When the face was recognised: latch write time (a), the face sensor's `last_changed` on a real transition (b), the egress event `timestamp` (c). Never dispatch time. |
| `confidence` | **Rev 3: the house's existing identity ladder, not a new scale (§2A).** Interior: `CONFIDENCE_MEDIUM` (0.6, `const.py:316`), the value the egress producer gives one uncorroborated recognizer (manual §5.3). Egress: the producer's `identity_confidence` as stamped (0.9 / 0.75 / 0.72 / 0.6). Never `None`. |
| `provenance` | Rev 3. One of `IDENTITY_PROVENANCE_*` (§2A): interior `face`; egress copied from `identity_provenance` (`face` or `ble+face`; `ble` never becomes a sighting, INV-PROVENANCE). `vision` reserved for §15, unused this cycle. |
| `sighting_source` | `interior_pick`, `egress_entry`, `egress_exit`. |
| `identity_role` | Rev 9. Egress only: `attached`, `departure_candidate`, or `arrival_confirmed` (a provisional candidate yields no sighting until confirmed); None for interior. Plus `confirmed_by` (`tracker` / `ble` / `gps`) on confirmed ones. |
| `synthetic` | Interior: True when the name came only from the MQTT latch (a). Egress: `identity_synthetic_corroborated`. |
| `person_edge_age_s` | Seconds since the pick's person sensor was last `on` (None if unknown; 0 while on). |

Granularity: consumers choose camera, room or zone. Room-level means "seen in a shared room or hallway". **Private
rooms are never inferred from a sighting**; a personalization consumer combines it with BLE.

**Last-sighting accessor (build-prediction review, goals section).** `PresenceCoordinator.get_last_person_sighting(
person_entity) -> PersonSighting | None` and `get_last_person_sightings() -> dict[str, PersonSighting]` (copy). In-memory,
cleared on teardown, not persisted. Updated on every emit; also updated (not re-emitted) when a later copy of the
same recognition inside the debounce window carries better evidence (non-synthetic replaces synthetic). This is the
read side future consumers use instead of each re-subscribing and keeping state.

### 3.2 Producer (D1) — `person_sighting.py` + presence wiring

**Pick resolution (M1, F1; operator direction 2026-11-12). No string-building anywhere.** A `zone_cameras` pick
names a CAMERA, whatever sensor kind the operator picked. URA walks pick -> physical camera -> every integration's
entities for that camera, through `CameraResolver` (device + registry):

1. **Pick -> physical camera(s).**
   - Camera-integration pick (Frigate `_person_occupancy[_2]`, Protect `_person_detected`, Reolink, Amcrest/Dahua):
     `CameraResolver.resolve_operator_declaration([pick])` (`camera_resolver.py:767`). It maps the entity to its
     device (`resolve_entity_to_device_id`, `:752`) and walks the correlation ladder (`resolve_capabilities`,
     `:801`: same-device, MAC, identifiers, name-stem with the F2 cross-host collapse) to one `RoomCameraFusion`
     (`:189`) per physical camera, whose `sources` (`FusionSource`, `:131`) list each integration's device for that
     camera (Frigate AND Protect, etc.). **Today's resolver does this already**; it is what `CONF_ROOM_CAMERAS` uses.
   - URA fused room pick (platform `universal_room_automation`, e.g. `binary_sensor.garage_a_camera_person_detected`):
     its device is the URA room device, which owns no camera, so the ladder alone returns nothing useful. Indirection:
     registry `config_entry_id` -> the room entry -> its `CONF_ROOM_CAMERAS` -> `resolve_operator_declaration(...)`.
     **This step does not exist today and must be added**: one helper `CameraResolver.resolve_pick_to_fusions(
     entity_id, room_cameras_lookup)` that handles both cases (camera-integration entity -> ladder; URA fused room
     sensor -> that room's declared cameras -> ladder). It is the single entry point for picks; no caller re-derives it.
2. **Physical camera -> entities per integration.** For each fusion, for each source: person sensor
   (`FusionSource.person_binary_sensor`), and face-NAME sensors via `face_name_entities_for_device(source.device_id)`
   (`:680`, registry token index; bare before `_N`). Frigate sources yield face-name sensors. Protect sources yield
   none: the HA Protect integration exposes no face NAME (manual §1, §2.3); `FusionSource.face_binary_sensor` is a
   detect event, not a name, so it is recorded in the binding but produces no sighting until the parked
   D1-PROTECT-FACE-BRIDGE-ADDON-1. The fusion's `physical_camera_id` is the dedup key; its stem is what the bridge
   latch keys join to (below).
3. **Binding.** `PickBinding = {pick, fusions, physical_cameras, face_entities: frozenset, person_sensors,
   area_id, room, house_zones}`. Area/room: for a URA fused pick, the owning room; otherwise
   `resolve_area_id_for_entity(pick)` -> room.
- A pick whose fusions carry no face-name entity is reported in `face_sighting_picks_unresolved` with its reason
  (`no_fusion`, `no_face_name_source` e.g. Protect-only, `room_entry_missing`, and rev 4 (M2) `room_cameras_empty`:
  a URA fused room pick whose room's `CONF_ROOM_CAMERAS` is `[]`), never guessed.
- **Live today (rev 4, M2):** Garage A's `room_cameras` is `[]` (live entry, 2026-11-12), so
  `CameraPersonDetectedSensor` is permanently off (`binary_sensor.py:1529`, `:1582-1586`) and the Back Hallway pick
  `binary_sensor.garage_a_camera_person_detected` resolves to `room_cameras_empty`. This is a config premise, not a
  code defect; the fix is operator action §13.3. The fused-pick path stays in scope and tested (it is real for other
  rooms).
- `census._device_derived_face_entity_id` (`camera_census.py:3274`) is NOT used for picks: it joins only the pick's
  own device and would miss Protect-picked cameras whose Frigate twin is a different device.

**Join for the MQTT bridge.** The bridge knows a Frigate `camname` and its latch stems. The producer maps those
stems to face-name entities with `face_name_entities_for_stem` and checks membership in a pick's `face_entities`.
The join key is the face-name **entity id, resolved registry-first on both sides**. A message that joins no pick is
not a sighting (it still counts in the bridge ring, §3.5, if its stems are on a pick).

**Re-resolution triggers (M1).** Bindings are rebuilt (cheap; RAM only) on:
1. census `_resolver_dirty` (registry update), observed by presence on the next bridge message or tick;
2. `EVENT_HOMEASSISTANT_STARTED` (Frigate can load after URA);
3. a ZM entry options update (picks changed);
4. every `FACE_SIGHTING_PICK_RERESOLVE_S` while any pick is unresolved (add-only retry).
Source (b) subscriptions are re-made to match the new bindings (old unsubs dropped first).

**Sources.**

- **(a) MQTT bridge hook.** After the latch loop in `_on_frigate_face_msg` (`camera_census.py:5591-5593`), the
  census calls each registered callback **once per message** with `(camname, frozenset(base_stems), name, now)`
  (M6, F6). Callbacks live in a list at `hass.data[DOMAIN]["face_latch_callbacks"]` (L3): the census reads that
  list at each message, so a census rebuild or reload keeps the registration. Presence appends at setup and removes
  at unload. A raising callback is caught and logged (never raises into the bridge).
- **(b) Face-sensor state change.** For each `face_entities` member, `async_track_state_change_event`. A sighting
  needs: `old_state` not None and `old_state.state` not in (`unavailable`, `unknown`) (H2, same guard as
  `presence._handle_geofence_change`); `new_state.state` a real name (not a sentinel). `ts` = `new_state.last_changed`.
- **(c) Egress.** A `ura_person_egress_event` with non-null `person_id`, direction `entry` or `exit`, and
  `identity_provenance` in (`face`, `ble+face`) gives `egress_entry` / `egress_exit`. `ble`, missing provenance and
  `ambiguous` give nothing (counted `egress_non_face_skipped`). Exit backfills (`SIGNAL_EGRESS_EXIT_BACKFILLED`) are
  not sightings. **Producer change (F2, the only one):** the transit validator adds one additive key,
  `identity_provenance`, to the bus event at `:2016`, taken from `census._egress_identity_last_attach` right after
  `_resolve_egress_face_identity` returns (the same read already done at `:2080-2092`), `None` when `person_id` is
  None. **Rev 4 (H1):** the face-only attach at `:1908-1916` writes `provenance: IDENTITY_PROVENANCE_FACE`
  explicitly (it writes no key today), and the bus key is read as
  `last_attach.get("provenance", IDENTITY_PROVENANCE_FACE)` when `person_id` is not None, so both the write and the
  read agree with the existing reader default at `:2087`. Without this, a plain `["provenance"]` copy puts `None` on
  every face-only crossing and the most common face case never becomes a sighting. Existing bus readers ignore
  unknown keys (the four display sensors, perimeter D10.5, `_arrival_departure_notify`).
- **(c') Confirmed egress arrival (rev 9).** A `SIGNAL_EGRESS_ENTRY_CONFIRMED` yields one `egress_entry` sighting with
  `identity_role = arrival_confirmed`, `ts` = the crossing timestamp, provenance `face`, the producer's
  `identity_confidence`, `confirmed_by`. Same emit function, same boot drop (`ts < boot_end`), same debounce key. An
  egress event carrying only `candidate_person_id` (no `person_id`) yields nothing (counted `egress_candidate_pending`).

**Filters (evidence quality only, never about consumers).**
- face suppression (`_face_suppressed_now`);
- sentinel names (`Unknown`, empty, `unknown`, `none`, case-insensitive);
- boot exclusion: any sighting with `ts < boot_end` (`boot_end` = presence setup +
  `PERIMETER_EGRESS_ARRIVAL_BOOT_EXCLUDE_S`) is dropped, for ALL THREE sources including egress (H2; rev 4 M3: the
  transit validator has NO boot window of its own, grep finds only a comment at `transit_validator.py:271`, so egress
  does not inherit one; the producer applies the same drop to source (c));
- interior: the name must join a pick; egress: a face-provenance identity;
- raw `person.<slug> == not_home` does NOT drop an interior sighting (that is the class (i) candidate).
- `switch.ura_name_people_at_doors` (L4): egress sightings honour it through the egress producer (no `person_id`
  when off). Interior sightings do not; that switch governs door naming, and interior faces are census inputs the
  switch never covered.

**Debounce and dedup (M6, F8).**
- Key = `(slug, physical_camera)` across ALL sources. So a door camera that is both a pick (the fused Garage A
  room) and an egress camera yields one sighting per window, first source wins (F8).
- Window `FACE_SIGHTING_DEBOUNCE_S` (60) is **fixed from the first emit, not sliding**: duplicates inside it do
  not extend it. A person sitting in family_room emits about once a minute while Frigate keeps naming them, which
  is what "who is here now" needs.
- A later copy inside the window never re-emits. It may only upgrade the last-sighting store (non-synthetic
  replaces synthetic; `ts` kept from the first). The rev-1 "clears `synthetic`" clause is deleted.
- **Multi-stem rule:** one bridge message = one Frigate camera. Its stems are aliases of that camera, so the
  producer collapses them: stems -> face entities -> the set of matched picks' `physical_camera`s. One sighting per
  distinct `physical_camera` (normally exactly one). More than one is counted `multi_pick_messages` (diagnostic;
  expected 0).
- `master_hallway` (two zones) is one pick, one sighting, `house_zones = ("Entertainment", "Master Suite")`.

**Dispatch.** Sightings are dispatched regardless of Presence observation mode (M4): they drive no action, only the
D2 adapter (which is gated) and diagnostics. Tracker display fields (F11): for each zone in `house_zones`, set the
tracker's `_last_face_recognized` (slug) and `_last_face_time` (ts), so `sensor.py:5979-5981` and
`presence.py:1031-1032` keep working.

**Removal.** The v3.19 face branch of `_handle_camera_change` (`:5478-5481`), `_get_face_for_camera`,
`_handle_face_arrival` and `_find_person_entity_from_face` are removed. The tracker camera-occupancy routing
(`:5466-5471`) stays byte-identical (ZONE-CAMERA-DISCOVERY-DEVICE-AREA-1 owns it).

**Teardown.** Every unsub in `_unsub_listeners`; the bridge callback removed from the hass.data list; bindings,
debounce dicts and the last-sighting store cleared.

### 3.3 Arrival derivation (D2): one rule, one site

On each sighting, presence dispatches `SIGNAL_PERSON_ARRIVING` with
`{"person_entity", "source": "camera_face", "sighting": PersonSighting, "zone": house_zones[0] if any else ""}` iff
ALL hold:

1. `FACE_SIGHTING_ENABLED`, and by branch (rev 9, build M1 / completeness M3): an `interior_pick` sighting needs
   `FACE_ARRIVAL_INTERIOR_ENABLED`; an `egress_entry` sighting needs `FACE_ARRIVAL_EGRESS_ENABLED`. Each is D0-gated,
   default False, and neither gates the other;
2. `sighting_source == "interior_pick"` (source `camera_face`), **or** `sighting_source == "egress_entry"` with
   `identity_role == "arrival_confirmed"` (source `camera_egress`, §2B.6). Rule 5 applies to both branches; for the
   egress branch it is evaluated at confirmation and skips a tracker-confirmed arrival. Other egress sightings never
   arrive;
3. not `self.observation_mode` (M4/F5; same gate as geofence `:5285` and v3.19 `:5622-5628`);
4. outside `PERIMETER_EGRESS_ARRIVAL_BOOT_EXCLUDE_S` of presence setup (H2);
5. **class (i), "face before phone" (M5, M7):** the person's raw `person.<slug>` state NOW is a real non-home value
   (`not_home` or a named zone; `unknown` / `unavailable` / missing -> not a candidate, fail closed), AND
   `_last_home_edge_ts.get(slug)` is None or earlier than `ts - FACE_ARRIVAL_PRIOR_HOME_GAP_S` (the phone did not
   arrive between the face and now, and not just before it);
6. per-person debounce `FACE_ARRIVAL_DEBOUNCE_S` (600, fixed window).

`_last_home_edge_ts` is an in-memory dict `slug -> epoch s`, written in the existing `person.*` listener
(`_handle_geofence_change`) on a live `not_home|zone -> home` edge (`old_state` not None and real). Not persisted;
empty after a restart, which the boot exclusion covers. This is the RAW, edge-triggered reader convention
(STATE_OF_PLAY §1), deliberately not `person_state_for_trust`.

Skip reasons are counted in `face_arrival_skips_by_reason` (`disabled_interior`, `disabled_egress`,
`not_arrival_role`, `observation_mode`, `boot`, `home`, `phone_already_home`, `unknown_state`, `debounce`). Rev 9: the
rev-2 leftover `egress` is gone.

`zone` (L2): the first of the sorted tuple; music logs it and must not rely on it.

HVAC counters: tracker `_face_arrivals_today` per house zone in `house_zones`. HVAC `camera_face_arrivals_today` by
**zone membership**: the HVAC zone whose `rooms` contain `room`, or whose `zone_name` split on `" + "` contains the
house zone. Never string equality (fixes `presence.py:5617`).

### 3.4 Consumer policy by action class (D3) — enforced in each consumer

**The primitive (M3, F4):** `SecurityLockRegime.face_input_corroborated(person: str, at_ts: float) -> bool`, a public
wrapper over `_face_arrival_corroborated` (`:1374`). It reads the regime's own `_arrival_edges` / `_bermuda_moves`
stamps and boot floor; no second stamping path. Every access-class consumer of a face-derived input calls it.
FACE-SIGHTING-CONSUMERS-1 names it as the required gate.

| Consumer | Class | Policy for `source in CAMERA_DERIVED_ARRIVAL_SOURCES` (rev 4, M5) | Change |
|---|---|---|---|
| `hvac._handle_person_arriving` `:7212` | comfort | Face alone OK, filtered by `pre_arrival_sources` (`hvac.py:7231`). Interior class (i) and confirmed egress arrivals reach it. | Rev 9 (both H1): `camera_egress` added to `DEFAULT_PRE_ARRIVAL_SOURCES`, the selector and the stored option (D8a migration); no logic change. Episode guard `pre_arrival_spent` bounds repeats. |
| `security_lock_regime.on_person_arriving` `:996` | access (unlock / lockout release) | Unchanged rule: `_face_arrival_corroborated` + the held re-check + the suspicious-arrival hold drop in `_apply_arrival`. | Rev 4 (M5): the literal `source == "camera_face"` at `:1017` becomes membership in `CAMERA_DERIVED_ARRIVAL_SOURCES` (byte-identical today, set = `{"camera_face"}`), unknown sources fail closed. Tests. |
| `security._handle_person_arriving_signal` -> `add_expected_arrival` `:2412-2419` | access (alarm suppression) | Accept only if `self._lock_regime is not None and self._lock_regime.face_input_corroborated(person, sighting.ts)`. Lock regime None -> reject (fail closed). **No held re-check:** a face whose edge comes later is rejected for good (asymmetric with the lock regime by design; a late edge produces its own geofence/ble arrival, which security handles normally). Here the non-face edge, not the face, is what suppresses. | **Code change.** Closes the latent leak (toggle on + face-only arrival sanctions every door for 5 min). |
| `music_following._handle_person_arriving` `:549` | personalization | Face OK (logs). | None. |
| Disarm | access | No arrival consumer disarms (`handle_disarm` callers: `security.py:1452` auto-follow on house state; service `__init__.py:6595`). | Test pins no face path reaches it. |

A SIGHTING has no consumer this cycle beyond the D2 adapter, the tracker display fields and diagnostics.

**Existing notification consumer (rev 4, M6).** `TransitValidator._arrival_departure_notify` (`transit_validator.py:2047`,
`:2140`) already sends "X arrived / left" from the egress bus identity. It is a display-class consumer of F3, not of
sightings, and is unchanged this cycle. It is the ONE arrival/departure notification site; any later use of sightings
for notification wording extends it, never adds a second producer.

### 3.5 Diagnostics and trip-wires (D4)

Attributes on the presence diagnostics sensor (or the house-state sensor if the builder finds the diagnostics one
crowded), all in `_unrecorded_attributes`:
- `face_sightings_today`, `face_sightings_by_source`;
- `face_arrivals_derived_today`, `face_arrival_skips_by_reason`;
- `face_sighting_last` (slug, camera, room, ts);
- `face_sighting_unmapped_names`, `egress_non_face_skipped`, `multi_pick_messages`;
- `face_sighting_picks_resolved` / `face_sighting_picks_unresolved` (with reason per pick).

**New denominator (M2, F6; BUILD).** At the latch write in `_on_frigate_face_msg`, AFTER the sentinel drop, the
census (only when `FACE_SIGHTING_ENABLED`, rev 4 L5) appends `(now, camname, frozenset(base_stems), name)` to a bounded RAM ring
`_frigate_face_named_ring` (`deque(maxlen=FACE_SIGHTING_BRIDGE_RING_MAX)`), independent of any presence callback.
Presence's trip-wire computes, over the trailing window: denominator = ring entries whose name maps to a tracked
resident (census mapper) AND whose stems join a resolved pick; numerator = interior sightings emitted. Unknown names,
unmapped names and unpicked cameras do not count.

- **`face_sighting_zero` (HIGH):** one `fire_stuck_signal` NM when denominator ≥ `FACE_SIGHTING_ZERO_MIN_FACES` and
  numerator = 0 over `FACE_SIGHTING_ZERO_WINDOW_H`. RAM latch, re-armed when sightings resume. This is the v3.19
  signature (faces exist, producer emits nothing). Limitation, named: if the bridge itself is dead the denominator
  is 0 and this page is silent; source (b) still produces sightings, and the bridge's own health shows in
  `frigate_face_msg_face_count`.
- **`face_arrival_zero` (LOW):** derived arrivals = 0 for `FACE_ARRIVAL_ZERO_DAYS` while sightings > 0. **Armed only
  when `FACE_ARRIVAL_INTERIOR_ENABLED` is True** (otherwise zero arrivals is the expected outcome, not a fault).

---

## 4. Producer and consumer checks

**Producer health (measured).**
- Named Frigate faces: 855 in 11-05..11-12, 85 % interior.
- Per picked camera, named 11-05..12: family_room_2 419, master_hallway_2 126, upstairs_hall_2 38, staircase_2 28,
  playroom_2 25, stairs_top_2 17; foyer_fisheye not in the top list.
- Bridge live: `frigate_face_msg_face_count` 191 since the last restart (pre-sentinel; the new ring will differ).
- Egress `person_id` attach ~40 %; some of it is BLE-provenance (0.72, `transit_validator.py:1655-1682`). D0-P2
  splits it.
- Rates track who is home (Oji travelling): a quiet day is not a fault, hence the ratio form of the trip-wire.

**Fire counts.** `camera_face` pre_arrival rows: 0 in all windows. geofence 220, ble 117 (10-13..11-12). Lock
camera_face holds: 0. `face_arrivals_today`: 0. Expected after this cycle: sightings ~50-150/day with people home;
derived arrivals ~0 unless D0-P3 passes.

**Forward trace to every action.**

| Path | Actions |
|---|---|
| sighting -> last-sighting store / tracker display fields | display only |
| sighting -> D2 rule (interior class (i), gated) -> `SIGNAL_PERSON_ARRIVING` -> HVAC | `_pre_arrival_zones` -> pre-cool / pre-arrival fans (sibling stand-down may skip, §11) |
| -> lock regime | gated release / unlock |
| -> security | expected arrival (now gated by `face_input_corroborated`) |
| -> music | log |

Subscribers of `SIGNAL_PERSON_ARRIVING`: hvac `:1511`, security `:817` (feeds the lock first), music `:281`.
`person_coordinator.py:1132` and `presence.py:5297` are producers.

---

## 5. Emission / decision-site enumeration

Producers of `SIGNAL_PERSON_ARRIVING`: `presence.py:5297` (geofence), `person_coordinator.py:1132` (ble),
`presence.py:5634` (camera_face; removed, replaced by the single D2 site).

Producers of `SIGNAL_PERSON_SIGHTING`: one site in presence (all three sources funnel through one emit function).

Consumers of `SIGNAL_PERSON_ARRIVING`: `hvac.py:1511`, `security.py:817` (-> `security_lock_regime.on_person_arriving`
`:996`), `music_following.py:281`.

Sinks guarded by INV-ACCESS:

| Sink | Callers |
|---|---|
| `_release` | lock regime: `_apply_arrival`, house-state edges (`:809`), P1 person, approach zone, proximity, backstop, hazard, kill switch |
| `_away_release` | lock regime `:1052, 1066, 1080, 2114, 2150` |
| `add_expected_arrival` | `security.py:2276`, `:2286`, `:2419` (the face-gated one), service `:2511` via `__init__.py:6612-6621` (F10) |
| `handle_disarm` | `security.py:2472`; callers `:1452` (auto-follow), service `__init__.py:6595` (F10) |

Perimeter D10.5 face de-escalation (a suppression sink at >= 0.9) listens to the egress bus event, not to sightings
or arrivals. Rev 9 (completeness M6): its code is unchanged because a provisional candidate carries `person_id` None;
it never reads `candidate_person_id` (pinned with a 0.9 non-synthetic candidate). The additive keys do not change its
reads.

Rev 9 additions:
- `SIGNAL_PERSON_ARRIVING` producers: + the D2 site with `source="camera_egress"` (confirmed candidates only).
- Second writer of an ENTRY row's `person_id`: the confirmation waiter, one site, via
  `backfill_entry_exit_person_id` (`database.py:4723`, `person_id IS NULL` guard). The first remains the INSERT.
- `SIGNAL_EGRESS_ENTRY_CONFIRMED`: one producer (the waiter); readers Persons Entered Today, Last Person Entry, the
  sighting producer.
- `_arrival_departure_notify`: still the one notification site; gains a `followup` branch.
- `door_interior_neighbours` readers (`transit_validator.py:1113-1140`, `:2221`; `arrival_edges.door_entry_areas`
  `:223`; `perimeter_alert._near_areas` `:5112`; `config_flow.py:4861`): untouched by D7.
- New memory_episodes writer: the outcome logger (one site).

Reviewer D re-runs these greps independently. The plan's list is a hypothesis.

---

## 6. Numbers get knobs

All rung 1 (module constants in `const.py`) unless stated: protocol windows or semantics that should change only by
review.

| Knob | Default | Rung | Why / kill semantics |
|---|---|---|---|
| `FACE_SIGHTING_ENABLED` | True | 1 | Kill switch for the whole producer. False = INV-NOOP. |
| `FACE_SIGHTING_DEBOUNCE_S` | 60 | 1 | Fixed window per (slug, physical_camera). 0 = no debounce. |
| Boot exclusion | REUSE `PERIMETER_EGRESS_ARRIVAL_BOOT_EXCLUDE_S` (600, `const.py:2679`), as one `ts < boot_end` check on sources a/b/c (rev 4 L3/M3) | 1 | Rev 3: no second boot constant. Same cause (HA restore stamps `last_changed` at boot) as the arrival-edge rule. The builder adds this module to the coupling comment at `const.py:2675`. 0 = off. |
| `CAMERA_DERIVED_ARRIVAL_SOURCES` | `frozenset({"camera_face", "camera_egress"})` from D8a (was `{"camera_face"}`) | 1 | Rev 4 (M5). The one set the lock regime and the security gate test by membership. Not a kill switch; adding a source here is the only way a new camera-derived source is recognised (unknown sources fail closed regardless). |
| `FACE_SIGHTING_PICK_RERESOLVE_S` | 300 | 1 | Retry period while any pick is unresolved. 0 = only the event triggers. |
| `FACE_SIGHTING_BRIDGE_RING_MAX` | 2000 | 1 | Bound on the trip-wire denominator ring (≈ 2 days at measured rates). |
| `FACE_ARRIVAL_INTERIOR_ENABLED` | False until D0-P3 passes | 1 | Interior class (i) arrivals. False = sightings only. |
| `FACE_ARRIVAL_PRIOR_HOME_GAP_S` | set by D0-P3 (placeholder 60) | 1 | A home edge this long before the face, or any time after it, means the phone already arrived. 0 = only edges after the face. |
| `FACE_ARRIVAL_DEBOUNCE_S` | 600 | 1 | One arrival per person per episode. |
| `FACE_SIGHTING_ZERO_WINDOW_H` | 24 | 1 | Trip-wire window; 0 = off. |
| `FACE_SIGHTING_ZERO_MIN_FACES` | 10 | 1 | Denominator floor before zero sightings is a fault. |
| `FACE_ARRIVAL_ZERO_DAYS` | 14 | 1 | Second trip-wire; 0 = off; armed only with interior arrivals on. |
| Security face gate window | REUSE `PERIMETER_EGRESS_FACE_NONFACE_WINDOW_S` (120) + lock boot floor, via `face_input_corroborated` | 1 | Coupling note at `const.py:2674` applies: widening it widens all three access consumers. |
| `EGRESS_IDENTITY_DIRECTION_AWARE` (rev 8) | False until D0-P7 passes | 1 | §2B rule. False = develop's direction-blind veto, byte-identical (INV-NOOP). |
| `EGRESS_ARRIVAL_CANDIDATE_MIN_CONFIDENCE` (rev 8) | 0.75 | 1 | G1. Below it the tracker wins. 1.0 = no candidates (kill). |
| `EGRESS_ARRIVAL_PATH_MIN` (rev 8; rev 9 semantics; Phase 2) | 2 (D0-P7 may move it) | 1 | G2 floor. 0 = G2 not evaluated (`skipped`, reason `disabled`), and a skipped G2 requires G1 at 0.9, so 0 TIGHTENS G1 rather than relaxing anything. |
| `EGRESS_OUTCOME_LABEL_WINDOWS_S` (rev 10, Phase 1 labeller) | (120, 300, 600, 1800) | 1 | Auto-label windows the weekly labeller reports; offline only. |
| `EGRESS_ARRIVAL_MAX_SPEED_KMH` (rev 9) | 150 | 1 | G3 implied-speed bound. A very large value = G3 never fails. |
| `EGRESS_ARRIVAL_GPS_MAX_AGE_S` (rev 9) | 86400 | 1 | Older fixes -> G3 `skipped`. 0 = G3 off. |
| `EGRESS_ARRIVAL_GPS_MIN_AGE_S` (rev 9) | 60 | 1 | Floor on fix age in the speed division (no divide-by-tiny). |
| `EGRESS_ARRIVAL_CONFIRM_WINDOW_S` (rev 9, replaces rev 8 `_FOLLOWUP_WINDOW_S`) | 600 | 1 | Confirmation window after the crossing. 0 = candidates are labels only, never named. |
| `EGRESS_ARRIVAL_CONFIRM_POLL_S` (rev 9) | 5 | 1 | Waiter poll (perimeter follow-up precedent). |
| `EGRESS_ARRIVAL_CONFIRM_GPS_KM` (rev 9) | 0.5 | 1 | Near-home GPS fix that confirms. 0 = GPS leg off. |
| `EGRESS_ARRIVAL_MAX_PENDING` (rev 9) | 8 | 1 | Waiter cap; beyond it a candidate gets no waiter. |
| `EGRESS_PATH_BUFFER_S` (rev 9) | 180 | 1 | Horizon of the `_path_events` list (exterior and other path nodes). |
| `EGRESS_PATH_HOP_DEFAULT_WINDOW_S` (rev 9) | 30 | 1 | Window for a map edge with no measured `lag_p90_s`. |
| `EGRESS_OUTCOME_LOG_PERSIST` (rev 9) | True | 1 | D8a outcome log. False = no row. |
| `EGRESS_OUTCOMES_ATTACHED` (rev 9) | `{"attached", "departure_candidate"}` | 1 | Vocabulary, not a knob: which outcomes count as attached. |
| `FACE_ARRIVAL_EGRESS_ENABLED` (rev 8) | False until D0-P7 passes | 1 | Confirmed candidate -> `SIGNAL_PERSON_ARRIVING(camera_egress)`. False = labels, notifications, sightings only. |
| `pre_arrival_sources` default (rev 9) | REUSE `DEFAULT_PRE_ARRIVAL_SOURCES` + `"camera_egress"` (`hvac_const.py:350`) | 2 | Operator-owned per install; the live option is migrated once. Unticking it = HVAC ignores egress arrivals. |
| Path map (D7, rev 9) | file `interior_paths.json` primary, const `INTERIOR_PATH_MAP_FALLBACK` fallback; learned map = offline report only | 2 (operator file) / 1 (const) | House-specific data. Invalid source = no map (G2 skipped), never partial. No file and no resolvable const = no map. |
| Picks | REUSE `zone_cameras` | 2 | Operator-owned. |
| Aliases | REUSE `face_name_aliases` | 2 | Optional; the census mapper already handles unique first names. |

**Removed from rev 1:** `FACE_ARRIVAL_RECENT_HOME_S` (class (iii) dropped, M7); `FACE_ARRIVAL_EGRESS_MIN_CONF`
(egress arrivals dropped, H1; it was also a no-op at 0.6, L1).
**Retired:** `FACE_SOURCE_PRESENCE_ARRIVAL_DISAMBIGUATED` (KEEP + DOCUMENT, no reader) and the inline 30 s literal
at `presence.py:5572` (deleted with the function).

---

## 7. Measure before build — D0 (read-only probe, the go/no-go gate)

One script, `scripts/probes/face_sighting_d0.py`, run via `ssh ha "python3 -" <` against the recorder (7.5 days),
the URA DB and the registry. The report goes into this doc as §7.1 before build dispatch.

- **P1, pick resolution.** For each of the 8 picks, through the §3.2 binding rules (device join; URA fused room ->
  `CONF_ROOM_CAMERAS` -> fusions -> `face_name_entities_for_stem`): resolved face entities, named events in window,
  and pick -> area -> room hit (None is reported, not guessed). Garage A (rev 4, M2): expected UNRESOLVED with reason
  `room_cameras_empty` (its `room_cameras` is `[]`); P1 records whether operator action §13.3 has been taken and, if
  so, which face sensor the pick then reaches. Go: ≥ 5 picks resolve (Garage A not counted).
- **P2, volume, timing, egress.**
  - Per pick: named events/day; lag from the person `on` edge to the name; fraction named after the sensor went
    `off` (the case D1's discriminating test uses).
  - Bridge (a) vs sensor (b) double reports (dedup expectation).
  - Egress events with `person_id` per day by direction, split by provenance (`face`, `ble+face`, `ble`), and
    **entries with `person_id` whose person was not_home within 300 s before** (H1; expected ~0 because of the
    veto; rev 8/9: the vetoed ones are P7's population, not proof that egress is sightings only).
  - Double sightings expected from a door pick + the same door's egress (F8 dedup expectation; for Garage A only
    after §13.3, rev 4 M2).
- **P3, arrival rule (critical gate).** For each interior resident face event, the raw person state at `ts` and the
  nearest `-> home` edge:
  - (i) not_home at ts and a home edge follows within 10 min: **face before phone** (the only class that can ship);
  - (ii) not_home, no home edge within 30 min: mislabel or phoneless;
  - (iii) home edge before ts: **context only** (no arrival; reported for the gap distribution);
  - (iv) home otherwise.

  Report per person and per camera. The audit's 292 "not home" interior events (Jaya 220) must be explained here.
  **Go rule:** `FACE_ARRIVAL_INTERIOR_ENABLED = True` only if (i) ≥ 1 per week AND (i) / ((i) + (ii)) ≥ 0.5.
  Otherwise ship sightings only and park interior arrivals with the trigger "a resident's tracker degrades so (i)
  rises". `FACE_ARRIVAL_PRIOR_HOME_GAP_S` = the p90 of the home-edge-to-face lag in (iii), capped at 300.
- **P4, interior track sequence.** Per ordered camera pair, the distribution of person-edge lags (A on -> B on
  within 120 s), and the fraction of UNNAMED interior person edges a named edge on an adjacent camera within 60 s
  could label. **Go rule for D7:** ≥ 25 % more named sightings with ≤ 10 % conflicting-name pairs; else park.
- **P4 rev 9 (D7 input; INTERIOR-PATH-MAP-1).** Resolve every fixture name to its physical camera(s) through the
  registry (`CameraResolver`, `canonical_camera_key`; the likely-mapping table in D7 is a hypothesis to confirm, not an
  input) and measure, per declared edge and for undeclared pairs with co-detections, the hop lag (p50 / p90) and hop
  rate per day, day vs night. Output: (1) a draft `interior_paths.json` with each edge's measured `lag_p90_s`, for the
  operator to ratify; (2) the offline diff report `docs/planning/AUDIT_interior_path_map_learned_vs_operator.md`
  (edges in both; operator edges with zero observed hops; learned-only pairs). The learned pairs are a suggestion
  report, never a runtime map (exterior-seam doctrine, `exterior_seams.py:11-23`: co-firing measures household
  movement, not adjacency; 10 of 27 learned exterior seams were struck). Also compare with the live
  `door_interior_neighbours` and `EXTERIOR_ADJACENCY_GRAPH`; differences are findings, not edits.
- **P7 rev 9, vetoed would-be arrivals (the go/no-go for `EGRESS_IDENTITY_DIRECTION_AWARE` and
  `FACE_ARRIVAL_EGRESS_ENABLED`).** Data (completeness M7): the in-RAM outcome deque is a 24 h ring
  (`camera_census.py:1444`, `:3613-3618`) and vetoed DB rows carry `person_id` NULL, so before D8a there is no durable
  record of WHO was vetoed. Sources: (1) the D8a outcome log (memory_episodes `egress_identity_outcome`, every
  resolution, vetoed slug included), which starts at D8a's deploy; (2) a replay of the face-only rule over recorder face
  history (~7 days) for the window before it. The gate is not judged until the log covers >= 28 days.
  - Count entries whose face-only single slug read `not_home` or a named zone at resolution (would-be candidates); split
    by camera, day/night, confidence tier, synthetic or not.
  - Label each automatically: **true arrival** if that person's live non-face edge (tracker home edge, Bermuda in-house,
    near GPS) follows within 10 min (also report 2 / 5 / 30); **misrecognition or phoneless** if none within 30 min. The
    operator reviews every `mis` label and a sample of 10 `true` ones; the labelled set is committed to
    `quality/tests/fixtures/egress_arrival_d0_labelled.json`.
  - Per guard: true arrivals kept and misrecognitions removed (G1, G2 with the replayed score from the shared scorer,
    G3 with the freshest-GPS rule); G3 false-fails on true arrivals by fix-age bucket (< 10 min, 10-60 min, 1-6 h,
    6-24 h); the guard yield on the 10-24 mislabel episode if its face rows are still retained (URA DB; the recorder keeps
    7 days), else on the nearest labelled mislabel episodes.
  - Confirmation: rate, lag, and source (tracker / ble / gps); and the confirmation lead over the person's first
    geofence/ble `SIGNAL_PERSON_ARRIVING` (the only HVAC value, §0 rev 9).
  - Phone-first share (the phone's home edge before resolution: those are `attached` today) vs after.
  - Exits: departures where the tracker still read `home` at resolution, and the time to `home -> not_home`.
  - `path_score <= 0` on resolved directions (EGRESS-PATH-OVERRIDES-DIRECTION-1 evidence).
  - **Go rule, `EGRESS_IDENTITY_DIRECTION_AWARE = True`:** over >= 28 days, >= 4 would-be candidates (about 1 a week);
    and on the CONFIRMED subset, the Wilson 95 % lower bound of "the confirming edge belongs to the named person AND that
    person is the one the operator's review says came through the door" >= 0.85 with n >= 10. Fewer than 10 confirmed =
    not judged; the log keeps accumulating. (A point estimate on 20 labels cannot support 0.9: one error is 0.95.)
  - **Go rule, `FACE_ARRIVAL_EGRESS_ENABLED = True` (rev 10):** the above, plus >= 10 GPS-confirmed candidates (home
    zone + approach, §2B.3a) whose confirmation precedes the person's first geofence/ble arrival by a median >= 60 s.
    BLE confirmations do not count: they land on the same tick as the ble arrival (completeness M5). Else it adds
    nothing to HVAC.
  - **Weekly labelling (rev 10, completeness M6; Phase 1 D8a ships it).** The recorder keeps 7 days and perimeter
    snapshots 168 h, so labels cannot wait for day 28. `scripts/probes/egress_outcome_label_weekly.py` runs once a week
    (read-only, `ssh ha "python3 -"`), reads that week's outcome-log rows, labels each would-be candidate from tracker
    edges, Bermuda moves and GPS fixes (recorder, still inside retention) plus `person_presence_snapshots` and
    activity-log `pre_arrival` rows (URA DB), replays the Phase 2 confirmation rule INCLUDING the §2B.7 abstain rules,
    and appends to `quality/tests/fixtures/egress_arrival_d0_labelled.json`. The operator reviews that week's `mis` labels
    and every replayed confirmation while the crossing snapshots still exist. The auto-label "a non-face edge follows
    within 10 min" IS the confirmation rule, so it cannot measure the rule's precision; the Wilson n counts only
    operator-reviewed confirmations. A missed week is a gap in n, never back-filled from memory.
  - Before Phase 2 there are no candidates: "confirmed" in these rules means "the replayed rule would have confirmed".
  - Fail = switches stay False, numbers recorded, triggers "door face recognition rate doubles after
    FRIGATE-DOOR-FACE-TUNING-1" and "the outcome log shows >= 1 confirmed candidate a week".
- **P5, consumer reality.** Live `security_on_arrival_add_expected`; lock-regime garage lockout and away-lock
  switch states; HVAC `pre_arrival_enabled`; whether the sibling precool stand-down is deployed.

- **P6 (rev 3), vision feasibility = D0-V, defined in §15.4.** Runs in parallel with P1-P5 but gates only the
  sibling vision plan, never D1-D6. It sends frames to a cloud provider unless a local model is used, so it needs an
  operator yes first (§15.3).

Fixture: P3 output hand-labelled for ~20 events (operator or BLE ground truth), committed as
`quality/tests/fixtures/face_arrival_d0_labelled.json`. That table is the D2 acceptance oracle.

---

## 8. Non-goals

- No change to Frigate config or face training (FRIGATE-DOOR-FACE-TUNING-1).
- No change to `_discover_zone_cameras` / tracker camera occupancy / `CameraInfo.area_id`
  (ZONE-CAMERA-DISCOVERY-DEVICE-AREA-1).
- No sighting feeds census, house-state inference, the guest gate, `check_zone_occupancy_confidence`, or NM.
- No private-room location from cameras; no personalization consumer (PERSON-PROFILE-PREFERENCES-1).
- No new arrival/departure notification producer. One already exists, `TransitValidator._arrival_departure_notify`
  (`transit_validator.py:2047`, `:2140`); rev 9 adds only its quiet `followup` branch for confirmed candidates.
- ~~No egress-derived arrivals~~ (rev 8: restored, D0-gated, §2B.6).
- No change to the egress producer's windows, abstain/disagree rules, BLE branches, `base_stem` predicate or exit
  backfill. **Exceptions:** the additive `identity_provenance` bus key (F2); and (rev 8) the direction-aware rule that
  replaces the face-only veto (§2B.2), the guards (§2B.3), `path_score` (§2B.4), provisional candidates and their
  confirmation (§2B.3a), all behind `EGRESS_IDENTITY_DIRECTION_AWARE`; and (rev 9, switch-independent) the outcome
  log, the HVAC source option and the attach-label set (D8a).
- (rev 9) No change to `door_interior_neighbours`, its validator or its four readers; no runtime-learned path map; no
  change to perimeter D10.5 code; no DB schema change (the outcome log uses memory_episodes; confirmation uses the
  existing backfill UPDATE).
- (rev 8) The path score never changes the resolved direction; no `SIGNAL_PERSON_DEPARTING`; no departure-driven
  actuation; no change to the census face veto.
- No change to the lock regime's corroboration rule or the suspicious-arrival hold; one public wrapper only.
- No held re-check in security (§3.4).
- No Protect face-name bridge (parked D1-PROTECT-FACE-BRIDGE-ADDON-1).
- (rev 3) No write into `TransitValidator._camera_sightings` and no change to phone-left-behind (card PHONE-LEFT-BEHIND-CAMERA-LEG-1).
- (rev 3) No vision build, no snapshot sequence capture, no cloud call. §15 is design + the D0-V probe only.
- (rev 3) No change to the egress producer's `base_stem` independence predicate.
- No DB table or persistence for sightings (RAM + attributes).
- No fix to the pre-existing body-evidence ARRIVING -> unlock path (carded, §12).

---

## 9. Deliverables

### D0: Probe and labelled fixture (§7)
- **Verify:** §7.1 committed with P1-P5. Go/no-go recorded for D2-interior and D7.
- **Test:** none (read-only).
- **Live:** n/a.

### D1: Sighting producer (sources a/b/c), signal, payload, bindings, last-sighting accessor
- **Verify:** a named face on any resolved pick, including `upstairs_hall_person_occupancy_2` and
  `playroom_person_occupancy_2`, emits exactly one `SIGNAL_PERSON_SIGHTING` per (slug, physical_camera, fixed
  window), with the right room and sorted `house_zones`. `master_hallway` gives `("Entertainment", "Master Suite")`.
  The URA fused `garage_a_camera_person_detected` is reported unresolved with reason `room_cameras_empty` (rev 4,
  M2) until operator action §13.3; the fused-pick path is proven in-suite on a room with cameras.
- **Verify (discriminating):**
  - A name arriving 45 s after the person edge, with the person sensor already `off`, emits, with
    `person_edge_age_s ≈ 45`. (Rev 1 compared against the deleted edge-read code, which cannot run.)
  - A restored face sensor (`old_state` None or `unavailable` -> "Jaya") emits nothing (H2).
  - A stale retained MQTT name emits nothing; `Unknown` emits nothing.
  - An egress entry with `identity_provenance == "ble"` emits nothing; with `"face"` it emits `egress_entry` with
    `room` = the crossing's room.
  - The same recognition through a door pick and that door's egress gives one sighting (F8), including when the
    pick is the Protect leg and the egress crossing fires on the Frigate leg (rev 4, M1; under the old
    `physical_camera_id` this gives two).
  - A face-only egress crossing driven through the REAL `_resolve_egress_face_identity` path (no BLE leg, no
    hand-stamped key) fires a bus event with `identity_provenance == "face"` and yields an `egress_entry` sighting
    (rev 4, H1; under a plain `["provenance"]` copy it carries `None` and yields nothing).
  - An egress crossing at `ts < boot_end` yields no sighting (rev 4, M3).
  - A Frigate name for a resident whose tracker reads `not_home` yields a sighting with
    `census_would_veto=True` and `person_state_at_emit="not_home"` (rev 4, M4).
- **Verify:** a non-picked camera's face emits nothing (interior). Bindings resolve after
  `EVENT_HOMEASSISTANT_STARTED` when Frigate loads after URA.
- **Test:** `test_person_sighting.py::test_bridge_only_name_after_edge_emits` (source (b) absent; asserts
  `synthetic=True`, the bridge path), `::test_sensor_change_only_emits` (no bridge; asserts `synthetic=False`),
  `::test_bridge_and_sensor_dedup_single_emit`, `::test_debounce_fixed_window_not_sliding`,
  `::test_multi_stem_message_single_emit`, `::test_n_suffix_pick_resolves_without_flag`,
  `::test_ura_fused_room_pick_resolves_via_room_cameras`, `::test_protect_pick_walks_to_frigate_twin_face`, `::test_unresolvable_pick_reported_not_guessed`,
  `::test_rebind_on_ha_started_and_options_update`, `::test_unpicked_camera_silent`,
  `::test_boot_restore_not_a_sighting`, `::test_egress_face_provenance_sighting`,
  `::test_egress_ble_provenance_silent`, `::test_egress_exit_sighting_never_arrival`,
  `::test_ambiguous_egress_silent`, `::test_backfill_not_a_sighting`, `::test_face_suppressed_silent`,
  `::test_unmapped_name_counted_not_emitted`, `::test_oji_maps_without_alias`, `::test_master_hallway_two_zones`,
  `::test_door_pick_and_egress_dedup`, `::test_last_sighting_accessor_upgrades_not_reemits`,
  `::test_census_reload_keeps_callback`, `::test_tracker_face_fields_updated`, `::test_teardown_unsubscribes_all`,
  (rev 3) `::test_interior_confidence_is_medium`, `::test_guest_slug_not_a_resident_sighting`,
  `::test_boot_exclusion_drops_before_boot_end_keeps_after` (rev 4 L3, behavioural: `ts = boot_end - 1` dropped,
  `boot_end + 1` kept; replaces `test_boot_exclusion_uses_shared_edge_helper`), `::test_egress_provenance_copied_not_recomputed`;
  (rev 4) `::test_egress_boot_window_not_a_sighting` (M3, also an egress case inside `test_boot_restore_not_a_sighting`),
  `::test_protect_pick_and_frigate_egress_one_key` (M1), `::test_canonical_camera_key_same_for_all_legs` (M1),
  `::test_ura_fused_pick_room_cameras_empty_unresolved` (M2), `::test_not_home_face_sighting_carries_census_veto` (M4),
  `::test_unmapped_passthrough_name_not_emitted` (L4: lowercased passthrough and `""` both unmapped);
  (rev 9, Phase 2) `::test_provisional_candidate_yields_no_sighting`, `::test_confirmed_candidate_yields_one_egress_sighting`;
  `test_identity_provenance_consts.py::test_values_unchanged` (constants equal the old literals;
  census/transit read them)
  (real hass); `test_transit_validator_provenance.py::test_bus_event_carries_identity_provenance`,
  `::test_face_only_real_path_provenance_face` (rev 4 H1: drives the real `_resolve_egress_face_identity` face-only
  path, asserts `identity_provenance == "face"` on the fired event; no hand-stamped attach).
- **Live:** `face_sighting_picks_resolved` ≥ the D0-P1 count after a restart. Every `*_last_recognized_face*`
  change to a resident name on a resolved pick (outside the boot window) has a matching sighting ±debounce. No
  sighting in the first 600 s after restart. `ura_person_egress_event` rows carry `identity_provenance`.

### D2: Arrival derivation (one site)
**Rev 10 (Phase 1):** D2 ships the interior branch only. Rule 2's egress branch, `FACE_ARRIVAL_EGRESS_ENABLED` and
the `camera_egress` source are Phase 2 (D8b). In Phase 1 every egress sighting is skipped `not_arrival_role`.
- **Verify:**
  - Egress sightings dispatch `SIGNAL_PERSON_ARRIVING` only as `camera_egress` for an `arrival_confirmed` sighting with
    `FACE_ARRIVAL_EGRESS_ENABLED` (rev 9, D8b), subject to rules 3-6 at confirmation; every other egress sighting never
    dispatches.
  - With `FACE_ARRIVAL_INTERIOR_ENABLED` False (expected default), no `camera_face` arrival at all; skips counted
    `disabled`.
  - When enabled: fixture class (i) dispatches; (ii) is dispatched only if the raw state is a real non-home value
    (comfort accepts it; lock and security reject it by D3); (iii) and (iv) never.
  - Observation mode on: no dispatch (`observation_mode` skip).
  - Inside the boot window: no dispatch.
- **Verify (discriminating):** a resident at home walking past family_room 10 times gives 0 arrivals (v3.19: 10). A
  face at t, then the phone's home edge at t+20 s, then dispatch evaluated: `phone_already_home` skip, not an arrival.
- **Test:** `test_face_arrival_rule.py::test_fixture_classes`, `::test_home_resident_no_arrival`,
  `::test_phone_already_home_skip`, `::test_unknown_state_fails_closed`, `::test_egress_never_arrival`,
  `::test_observation_mode_suppresses_arrival`, `::test_boot_window_suppresses_arrival`,
  `::test_arrival_debounce_per_person`, `::test_hvac_counter_matches_compound_zone`, `::test_kill_switch_noop`.
- **Live:** if interior arrivals ship, `face_arrivals_derived_today` and HVAC `camera_face_arrivals_today` move only
  on events the recorder shows as class (i). If they do not ship, both stay 0 and `face_arrival_skips_by_reason`
  shows `disabled` counts matching sightings.

### D3: Consumer policy (security face gate via the lock primitive; lock and HVAC pinned)
- **Verify:**
  - `security_on_arrival_add_expected=True`, a camera_face arrival with no non-face edge: `_expected_arrivals`
    stays empty.
  - Same with the lock regime None: stays empty (fail closed).
  - With a stamped Bermuda entry-area move or a tracker home edge within 120 s: it adds.
  - A face whose edge arrives after the face: rejected, not re-checked.
  - geofence/ble arrivals unchanged.
- **Verify:** the lock regime, with the person really away and no edge, puts an interior camera_face arrival in
  `_pending_faces` (held path) and does not release; with an entry edge it releases.
- **Test:** `test_security_face_expected_arrival.py::test_face_only_rejected`, `::test_face_with_edge_accepted`,
  `::test_lock_regime_none_rejects`, `::test_late_edge_not_rechecked`, `::test_geofence_unchanged`;
  `test_sc_lock_person_sighting.py::test_interior_face_held_pending_when_really_away`,
  `::test_face_released_with_bermuda_entry_edge`, `::test_face_input_corroborated_matches_private`;
  (rev 4, M5) `test_face_access_invariant.py::test_unknown_arrival_source_requires_corroboration` (dispatch
  `source="camera_vision"` with no edge to both the lock regime and security: no release, no expected arrival),
  `::test_camera_derived_set_used_by_both_gates`, (rev 10, moved from D8a, build M1) `::test_camera_egress_requires_corroboration`
  (the set is `{"camera_face", "camera_egress"}` from this ship, before any emitter of `camera_egress` exists);
  `test_face_access_invariant.py::test_no_face_path_reaches_disarm`; config extremes: window 0 (never), alias
  set/unset, egress 0.9 synthetic (no arrival exists), toggle on with both lock switches on, restart with restored
  face sensors.
- **Live:** lock `lock_regime_*` snapshot and security `expected_arrivals` show no face-only effect. Any
  `Lock regime: camera_face arrival for X held` line is followed by no release unless a matching edge exists in the
  recorder.

### D4: Diagnostics and trip-wires
- **Verify:** the §3.5 attributes exist and are unrecorded; the census ring is post-sentinel.
- **Verify (discriminating):** with the D1 emit mutated off and ≥ 10 mapped resident faces on picked stems, one HIGH
  `face_sighting_zero` NM fires. Sightings > 0: nothing. Only `Unknown` faces, only unmapped names, or only unpicked
  cameras: nothing.
- **Test:** `test_face_sighting_tripwire.py::test_zero_with_faces_pages`, `::test_zero_without_faces_silent`,
  `::test_unknown_name_faces_silent`, `::test_unmapped_only_faces_silent`, `::test_unpicked_only_faces_silent`,
  `::test_rearm_after_recovery`, `::test_window_zero_off`, `::test_arrival_zero_unarmed_when_interior_off`.
- **Live:** no `face_sighting_zero` NM in the first day with residents home.

### D5: Retire the v3.19 path and flag; docs (same commit)
- Remove the `_handle_camera_change` face branch, `_get_face_for_camera`, `_handle_face_arrival`,
  `_find_person_entity_from_face` (salvaged parts move to D1/D2). `FACE_SOURCE_PRESENCE_ARRIVAL_DISAMBIGUATED` ->
  KEEP + DOCUMENT.
- Docs:
  - IDENTITY_FUSION_CAMERAS_MANUAL §1.1 (S8 paragraph), §4.3 (the `identity_provenance` key), §4.5 (lock face
    arrivals now come only from interior class (i)), §5.5 (consumer map: sightings; one-line clarification that the
    security expected-arrival suppression is done by the non-face edge, and that egress identity feeds no
    arrival — this resolves F7 without a doctrine change). **Rev 4 (M6): §5.5's claim "NOTHING reads
    `identity_confidence`" is stale (code wins): `_arrival_departure_notify` (`transit_validator.py:2047`, `:2140`)
    reads it against `ARRIVAL_NAME_CONFIDENCE_THRESHOLD`. Correct §5.5 and add it to the consumer map.** Also note
    the `provenance: face` explicit write (H1) in §4.3;
  - PRESENCE_ARCHITECTURE_STATE_OF_PLAY §1 `SIGNAL_PERSON_ARRIVING` row ("camera_face fires for any zone-camera
    face, no was-away gate" becomes the D2 rule) and a §10 entry: "face arrival worked since v3.19" is false, it
    never fired;
  - HVAC_ARCHITECTURE_STATE_OF_PLAY: pre-arrival source line, and fix the stale `_handle_person_arriving` cites
    (`hvac.py:4186` / `:1196` -> `:7212` / `:1511`, F9).
- **Test:** the authority for D5 is behavioural: `test_person_sighting.py::test_n_suffix_pick_resolves_without_flag`
  (fails if any `_N` skip returns). `::test_retired_flag_unread` stays as a lint only (L5, Bug Class #62), not counted
  as test authority.
- **Live:** n/a.

### D6: Real-HA integration test
One real-hass test, `quality/tests/test_face_sighting_realhass.py`: config entries with picks (incl. a URA fused room
pick), census + presence + security (lock regime on and off) + HVAC up. Fire a face sensor change, a bridge message
and an egress event; restart-shaped restore. Assert the sightings, the (absent or present) arrival, and each
consumer's effect. Guards the v5.8.0 fake-coordinator incident class.

### D7 (rev 9; rev 10 Phase 1, step 6): interior camera path map as a validated file — card INTERIOR-PATH-MAP-1
Prerequisite of §2B.4. EXTERIOR-SEAM-FILE-LOADER-1 shipped (v5.108.15). D7 ships after D1 (it needs
`canonical_camera_key`). Phase 1 scope: helper extraction, module + scorer, loading, reload button, provenance, the
offline diff report. Phase 1 has NO runtime reader of the map; `_path_events` subscriptions and `path_score` on the
bus are Phase 2.

- **Shared loader helper (rev 10, build M2, completeness L4).** Extract `load_validated_json` (§1.2c) from
  `async_load_seam_file`; the linker keeps its outcomes exactly (const unvalidated, `validate_fallback=False`) and
  `test_exterior_seam_loader.py` passes unchanged. D7 calls the same helper with `validate_fallback=True`, owned by
  `EgressDirectionTracker`. **Four outcomes for the interior map:** (1) file valid -> file map; (2) file absent ->
  validated const, or `none` if the const does not validate; (3) file invalid at setup -> validated const or `none`;
  (4) file invalid at reload -> the previous installed map is kept. `path_map_sha256` is the sha of the INSTALLED
  source (None for const / none), never of a rejected file. Tests `test_four_load_outcomes`,
  `test_sha_names_installed_source`, `test_seam_loader_unchanged_after_extraction`; drill M42.
- **Resolver-ready ordering (build L2).** Validator rule 2 (live door groups) and rule 3 (cameras resolve) need a
  populated `CameraResolver` and the tracker's door groups. The first load runs at the resolver-ready point (after
  `EVENT_HOMEASSISTANT_STARTED` / the census's first resolver pass), not inside `EgressDirectionTracker` setup at
  `__init__.py:3471`; until then provenance reads `pending`. Test `test_cold_boot_valid_file_loads_after_resolver_ready`.

- **Storage (build H3, completeness H2).** Its own file `/config/universal_room_automation/interior_paths.json`, its
  own HA-free module `interior_paths.py` (parse, validate, score), same contract as `exterior_seams.py`: schema
  version, whole-file rejection, never a partial map. **`door_interior_neighbours` and its four readers are not
  touched**, and no reader of it reads the path map.
- **Schema v1:**
  ```json
  {"schema_version": 1,
   "doors": {
     "garage_a": {
       "edges": [
         {"from": "camera.rear_ptz_2", "to": "camera.garage_a_2", "kind": "approach", "lag_p90_s": 25},
         {"from": "camera.garage_a_2", "to": "camera.staircase_2", "kind": "inward"}
       ],
       "same_view": []
     }}}
  ```
  Nodes are `camera.*` entity ids (operator-pickable, registry-resolvable); the loader resolves each to its physical
  camera with `CameraResolver.resolve_operator_declaration` + `canonical_camera_key`, so Frigate and Protect legs of one
  camera are one node. Door keys are the live door groups (`CONF_DOOR_GROUPS` values; when unset, each egress stem is
  its own group, build H3).
- **Validator rules (any error rejects the whole source):** (1) schema version; (2) every door key is a live door
  group; (3) every node resolves to a camera with at least one person leg (unknown -> error naming it); (4) `kind` in
  {`approach`, `inward`}, no self edge, no duplicate edge; (5) acyclic per door; (6) each door's edges touch at least one
  live egress camera of that group (else WARN: door unanchored, `skipped`); (7) an `approach` edge's `from` node should
  be a perimeter or exterior-egress camera per the seam file or `perimeter_cameras` (WARN, the operator is the oracle);
  (8) `lag_p90_s` in (0, `EGRESS_PATH_BUFFER_S`]; (9) `same_view` nodes known.
- **Loading.** At setup through the loader (executor read), file primary, const `INTERIOR_PATH_MAP_FALLBACK` (rung 1)
  fallback. The const holds this house's ratified map once D0-P4 resolves the names (same status as
  `EXTERIOR_ADJACENCY_GRAPH`); on another install its entity ids do not resolve, the validator rejects it, and there is
  no map (every door `skipped`), with no error beyond the provenance attribute. Reload: the loader's button (one per
  file, `button.ura_reload_interior_paths`, so provenance stays per file); a failed reload keeps the previous good map.
  Provenance attributes next to the seam ones: `path_map_source` (`interior_paths.json (schema 1, N edges)` /
  `built-in const` / `none`), `path_map_validation`, `path_map_sha256`, `path_map_doors`.
- **Learned map: offline only (build M2).** D0-P4's co-detection method runs as a read-only script and writes the diff
  report; it never writes entry options (no reload storm), never loads at runtime, never changes G2. Nothing to
  schedule, cancel or freeze. A learned edge enters the map only when the operator copies it into the file.
- **Operator answers applied (rev 10; `FIXTURE_camera_paths_interior.md` "Operator answers").** Garage: Back PTZ, G5
  -> {Doorbell Lite, Garage A} (both egress, group garage_a, one crossing; their pair never scores) -> Garage
  hallway/stairs -> Stair top -> Game room (= `playroom`) / Upstairs hallway. Front: Front PTZ, Utilities PTZ, Sonoff
  window (driveway) -> {Front door aerial, G6 Entry} (both egress, group front, simultaneous views of one crossing; the
  aerial counts, the G6 is the face camera; their pair never scores) -> Foyer (interior door witness, inward) -> Family
  room or Master hallway. "Entry way" in the fixture is Front door aerial. Still open: Garage B path, patio egress
  (§13.4); those doors get no map (`skipped`). The table below is the rev-9 reconciliation; rows marked RESOLVED follow
  these answers.
- **Fixture vs live egress config (completeness M5).** Live 2026-11-12: `egress_cameras` = `madrone_g6_entry`,
  `doorbell_lite`, `front_door_aerial`, `garage_a_2`, `garage_b_2`; `door_groups` = doorbell_lite -> garage_a,
  front_door_aerial -> front, garage_a -> garage_a, garage_b -> garage_b, madrone_g6_entry -> front;
  `door_interior_neighbours` = front: foyer x3 legs + family_room x2, garage_a: Protect garage hallway, staircase,
  garage_hallway camera, stairs_top; garage_b: []. Likely mapping (D0-P4 confirms by registry; question marks are §13.4):

  | Fixture name | Likely camera | Live role | Map role |
  |---|---|---|---|
  | Back PTZ | `rear_ptz` (Protect + Frigate `rear_ptz_2`) | perimeter | approach -> Garage A |
  | G5 | `g5_bullet` | perimeter | approach -> Garage A |
  | Doorbell Lite | `doorbell_lite` | egress camera, group garage_a | RESOLVED: egress, second view of the garage crossing (anchor with Garage A); approach edges from Back PTZ / G5 |
  | Garage A | `garage_a_2` / Protect `garage_a` | egress, garage_a | anchor |
  | Garage hallway/stairs | Protect `staircase` (+ garage hallway legs) | garage_a neighbour | inward |
  | Stair top | `stairs_top` | garage_a neighbour | inward |
  | Game room | `playroom` (RESOLVED) | not configured | inward |
  | Upstairs hallway | `upstairs_hall` | not configured | inward |
  | Family room | `family_room` | front neighbour | inward (garage branch and front) |
  | Front PTZ | `front_side_ptz` | perimeter | approach -> Entry way |
  | Utilities PTZ | `utilities_ptz` | perimeter | approach -> Entry way |
  | Sonoff window cam | `sonoffwindow` (Frigate) | perimeter | RESOLVED: approach -> Front door aerial and G6 Entry |
  | Entry way | RESOLVED: = Front door aerial (`front_door_aerial`) | egress, group front | anchor with G6 Entry (`madrone_g6_entry`, the face camera); `entry_way_panel_camera` is not on the path |
  | Foyer | `foyer_fisheye` | front neighbour, NOT an egress camera | RESOLVED: interior door witness, inward from the front anchors |
  | Master hallway | `master_hallway` | not configured | inward from Foyer |
  | Front door aerial | `front_door_aerial` | egress, group front | RESOLVED: = "Entry way" (row above) |
  | (absent) Garage B | `garage_b_2` | egress, group garage_b, neighbours [] | no map, `skipped`. OPEN (§13.4 Q5) |
  | Patio | `reolinkpatio` / `reolink_patio_fluent` / Protect patio PTZ | not an egress camera (Patio room is `door_type` egress with no camera) | `same_view` with Family room recorded; no patio crossings exist today. OPEN (§13.4 Q6) |
- **Consumers this cycle:** `path_score` only. Later: VISION-CROSSING-ANALYSIS-1 chains (§15.8), FACE-SIGHTING-TRACK-PROPAGATION-1.
- **Verify (discriminating):** with a valid file, `path_map_source` names the file; with a file naming an unknown
  camera, the source is the const (or `none` on a foreign house) and the error names the camera (under a partial-apply
  bug the known edges would load instead); `door_entry_areas`, `_near_areas`, `_get_interior_cameras_near` and the
  resolved direction of a replayed crossing are identical with and without a map (under a shared-option bug the
  hallway areas would appear); the garage golden scores 3 and its reverse −3; a hop after T is ignored.
- **Test:** `test_interior_paths.py::test_file_wins_over_const`, `::test_invalid_file_rejected_whole_keeps_previous`,
  `::test_invalid_source_means_no_map_not_partial`, `::test_unknown_camera_named_in_error`, `::test_cycle_rejected`,
  `::test_door_key_must_be_live_group`, `::test_frigate_and_protect_legs_one_node`, `::test_same_view_pair_not_a_hop`,
  `::test_path_score_entry_order`, `::test_path_score_reverse_order_negative`, `::test_path_score_front_door_dag`
  (Entry way as approach end and anchor, Foyer inward), `::test_egress_pair_same_group_not_scored`,
  `::test_path_score_ignores_hops_after_resolution`, `::test_no_map_for_door_is_skipped_not_zero`,
  `::test_reload_button_swaps_map`, `::test_probe_and_runtime_share_scorer`;
  `test_door_neighbours_untouched.py::test_entry_areas_near_areas_direction_identical_with_map`.
- **Live:** L10.

### D8 (rev 9): direction-aware egress identity (§2B) — card EGRESS-DIRECTION-AWARE-IDENTITY-1
Two increments.

**D8a (PHASE 1, step 2; switch-independent; Tier 2-DB minimum inside the Tier-3 arc).**
- **Channel (rev 10, build M4).** `_resolve_egress_face_identity` returns a 4-tuple `(person_id, identity_confidence,
  agreement_class, resolution)`; `resolution` is a frozen `EgressResolution` built fresh per call and returned on
  EVERY path (no legs, abstain, disagree, `direction_ambiguous` at `:1430`, vetoed, BLE branches, attached) with
  {outcome label (the same string the census outcome deque records), slug considered (None when none; the vetoed slug
  on a veto), identity tier and synthetic (from the pure helper below), person raw state, agreement, direction}.
  Phase 2 adds `role`, `candidate_slug`, `guards`, `path_score` with None defaults (this replaces rev 9's separate
  `EgressRoleResult`: one channel). One call site, `transit_validator.py:2011`. No `self._last_*` stash.
- **Pure tier helper (completeness M4).** `egress_identity_tier(in_window_legs) -> (tier, synthetic)` with no stash and
  no ledger append. The existing confidence block (`:1858-1896`) calls it for the arithmetic and keeps its side effects
  (`_last_identity_synthetic_corroborated` `:1880`, `_egress_identity_boost_events` `:1888-1891`) where they are; the veto
  path calls only the helper. One derivation, no side effect on a vetoed crossing.
- **Logger (build M4, completeness L6).** `_resolve_direction` (async) hands the `EgressResolution` plus crossing ts and
  camera to ONE logger right after the resolver returns: one memory_episodes row (`episode_type =
  egress_identity_outcome`, registered in `MEMORY_EPISODE_TYPES`, `node_id` per crossing, `source_ref` per crossing,
  `dedup_source_ref=False`: the per-crossing `node_id` already prevents merging and the source_ref SELECT is unindexed).
  The write is a task in the tracker's `_outcome_log_tasks` set (precedent linker `_episode_tasks`), cancelled and
  gathered with a bound in `async_teardown` before the DB worker stops. About 15 rows a day. No decision reads it. Kill
  switch `EGRESS_OUTCOME_LOG_PERSIST` (rung 1, True).
- **Weekly labeller** `scripts/probes/egress_outcome_label_weekly.py` (§7 P7) and operator action §13.6.
- **Verify:** one row per resolution including a no-legs crossing and an ambiguous one; vetoed rows carry the slug,
  tier and synthetic; log OFF = golden identical including the boost count and the synthetic flag for a vetoed 0.75 and
  a vetoed synthetic 0.9 crossing (a side-effecting tier helper would raise the boost count on the vetoed crossing).
- **Test:** `test_egress_outcome_log.py::test_every_resolution_persists_one_row_switch_off` (includes no-legs and
  ambiguous), `::test_vetoed_row_carries_slug_tier_synthetic`, `::test_two_crossings_10s_apart_both_persist`,
  `::test_persist_kill_switch`, `::test_vetoed_path_no_boost_no_synthetic_stash`,
  `::test_logger_task_gathered_at_teardown`; `test_egress_direction_aware.py::test_switch_off_golden_replay` (Phase 1
  form: no direction-aware code exists yet; asserts the log adds nothing else).
- **Live:** L14 (one row per resolved crossing since restart, vetoed rows with slug).
- Moved OUT of D8a by rev 10: HVAC `camera_egress` (Phase 2, §2B.7); `CAMERA_DERIVED_ARRIVAL_SOURCES` (Phase 1 D3,
  build M1); `EGRESS_OUTCOMES_ATTACHED` and the `direction` DAO parameter (Phase 2: only `departure_candidate` and entry
  confirmation need them; the DAO parameter is superseded by row-id backfill).

**D8b (PHASE 2; behind `EGRESS_IDENTITY_DIRECTION_AWARE`, default False until P7 passes; its own plan reviews and go).**
Rev 10 additions to D8b: HVAC `camera_egress` (default, selector, help text, `hvac.py:881`, migration per §2B.7),
`EGRESS_OUTCOMES_ATTACHED` at `sensor.py:3950`, `log_entry_exit_event` returning the row id, `_recent_crossings`,
`_confirm_tasks`, and the D2 egress branch with its four `test_face_arrival_rule.py` tests (they land in D8b because D2
in Phase 1 has no egress branch). The §2B.2 rule; guards G1-G4;
path-node subscriptions and the scorer; the 4-tuple role channel; the bus keys; the waiter and confirmation;
`SIGNAL_EGRESS_ENTRY_CONFIRMED` and its two display readers; the notify `followup` branch; the attach-rate counters;
sighting source (c'); the D2 egress branch behind `FACE_ARRIVAL_EGRESS_ENABLED`. Docs (same commit): manual §4.3 (veto
now direction-aware), §4.6 and §5.5 (`person_id` meaning, provisional candidates), presence state of play §1
(`SIGNAL_PERSON_ARRIVING` sources gain `camera_egress`), HVAC state of play (pre-arrival source list).

- **Verify (discriminating):**
  - Entry, face 0.75 non-synthetic, person `not_home`, path 2, no GPS: bus `person_id` None, `candidate_person_id` set,
    DB row NULL, "Someone arrived", not in the union (today: `vetoed`, no `candidate_person_id`; a leak would show the
    slug in `person_id`).
  - Then the tracker home edge (live source change) at +4 min: DB row named, Entered Today shows the name, one quiet
    "That was X", D2 skips `home`. Instead a Bermuda in-house read at +40 s: confirmed, and D2 skips
    `arrival_already_dispatched` (the ble arrival came on the same tick). Instead a GPS fix inside the home zone at
    +60 s after a 2 km fix before the crossing, with `FACE_ARRIVAL_EGRESS_ENABLED`: `camera_egress` reaches HVAC (not
    skipped for `pre_arrival_sources`).
  - Rev 10 (build H3): with the tracker reading `not_home` throughout, a Bermuda `last_changed` = t_E − 20 and,
    separately, a GPS fix at t_E − 20 inside the zone each leave the candidate open (an abs-window bug confirms them).
    A tracker home edge before t_E cannot test this: the crossing would be `attached`, no waiter exists.
  - Rev 10 (completeness H1): Oji 300 m away and walking, a 0.9 consistent "Oji" mislabel on Jaya's garage crossing,
    Oji's next fix 200 m out: NOT confirmed (no home-zone fix). Another crossing at the front door before Oji's tracker
    edge: `arrival_confirm_ambiguous`.
  - A stale-source iPad blip after the crossing confirms nothing.
  - Face 0.6 -> `vetoed_arrival_unverified` (G1). Fix 3 h old at 9,000 km -> `vetoed_arrival_unverified` (G3). Fix 8 min
    old at 3 km -> candidate. Path 0 on a mapped door -> `vetoed_arrival_unverified` (G2).
  - Entry + named zone -> candidate; exit + named zone -> `vetoed`, no evict; exit + home -> `departure_candidate`,
    evict, counted attached.
  - Switch False: golden replay identical; no new keys; no path subscriptions; no waiter.
  - Perimeter: a 0.9 non-synthetic candidate leaves a dual-role alert at its severity.
- **Test:** `test_egress_direction_aware.py::test_entry_not_home_provisional_candidate`, `::test_entry_zone_becomes_candidate`,
  `::test_exit_zone_vetoed_no_evict`, `::test_candidate_not_in_census_union`, `::test_confirmation_never_registers_union`,
  `::test_candidate_never_reads_stale_last_attach`, `::test_g1_low_confidence_vetoed`, `::test_g1_synthetic_leg_below_09_vetoed`,
  `::test_g3_implied_speed_fails_stale_far_fix`, `::test_g3_driving_home_passes`, `::test_g3_reads_freshest_gps_tracker_last_updated`,
  `::test_g3_no_gps_skipped_not_failed`, `::test_g3_fix_older_than_max_age_skipped`, `::test_g2_path_below_min_vetoed`,
  `::test_g2_min_zero_means_skipped`, `::test_g2_no_map_requires_0_9`, `::test_exit_home_departure_candidate_counts_attached`,
  `::test_exit_not_home_still_vetoed`, `::test_ble_branches_unchanged`, `::test_switch_off_golden_replay`,
  `::test_switch_off_no_new_keys_no_subscriptions_no_waiter`, `::test_role_not_leaked_across_crossings`,
  `::test_confirm_by_tracker_edge_after_crossing`, `::test_bermuda_read_before_crossing_does_not_confirm`, `::test_gps_fix_before_crossing_does_not_confirm`, `::test_gps_near_without_approach_does_not_confirm`, `::test_gps_outside_home_zone_does_not_confirm`, `::test_intervening_crossing_abstains`, `::test_later_candidate_same_slug_abstains`, `::test_candidate_does_not_write_last_attach`, `::test_confirm_waits_for_insert_row_id`, `::test_deferred_insert_then_ble_names_row_before_followup`, `::test_scheduled_path_45s_confirm_names_row`, `::test_name_switch_off_before_db_write_writes_nothing`, `::test_unload_during_confirmation`, `::test_teardown_logs_dropped_waiters`, `::test_ble_confirmed_skips_already_dispatched`,
  `::test_stale_source_edge_does_not_confirm`, `::test_confirm_by_bermuda_room`, `::test_confirm_by_near_gps_fix`,
  `::test_unconfirmed_expires_logged`, `::test_new_candidate_supersedes_waiter`, `::test_pending_cap`,
  `::test_waiters_cancelled_at_teardown`, `::test_confirmation_backfills_that_entry_row_only`,
  `::test_confirmation_refreshes_entry_displays`, `::test_notify_anonymous_then_quiet_followup`,
  `::test_followup_respects_name_switch`, `::test_perimeter_ignores_candidate` (0.9 non-synthetic candidate, build L1),
  `::test_attach_rate_labels`, `::test_egress_flag_without_direction_aware_inert`;
    `test_hvac_camera_egress.py::test_hvac_accepts_camera_egress_when_listed`, `::test_migration_appends_camera_egress_once`,
  `::test_migration_respects_operator_without_camera_face`, `::test_migration_reads_key_from_data`, `::test_setup_runs_camera_egress_migration`, `::test_ctor_default_uses_const`;
  `test_face_arrival_rule.py::test_confirmed_egress_dispatches_camera_egress`, `::test_tracker_confirmed_skips_home`,
  `::test_egress_non_candidate_never_arrives`, `::test_interior_flag_off_egress_flag_on_dispatches`.
- **Live:** L11-L16.

### Mutation drills (framing C; each must turn a named test RED; restore and check `git status` after each)

| # | Mutation | Expected RED test |
|---|---|---|
| M1 | Drop the bridge hook call | `::test_bridge_only_name_after_edge_emits` (source (b) absent in that test) |
| M2 | Producer drops names whose latch ts > person-edge + 30 s | `::test_bridge_only_name_after_edge_emits` |
| M3 | Remove `physical_camera` from the debounce key | `::test_bridge_and_sensor_dedup_single_emit` |
| M4 | Arrival rule ignores raw home state | `::test_home_resident_no_arrival` |
| M5 | Security face gate bypassed | `::test_face_only_rejected` |
| M6 | Lock `_face_arrival_corroborated` returns True | `::test_interior_face_held_pending_when_really_away` (asserts `_pending_faces`, person really away) |
| M7 | Re-add a `_N` skip in the producer | `::test_n_suffix_pick_resolves_without_flag` |
| M8 | Trip-wire compare inverted | `::test_zero_with_faces_pages` |
| M9 | HVAC counter back to string equality | `::test_hvac_counter_matches_compound_zone` |
| M10 | Remove the (b) restore guard and the boot exclusion | `::test_boot_restore_not_a_sighting` |
| M11 | Drop the observation-mode gate | `::test_observation_mode_suppresses_arrival` |
| M12 | Egress accepts any provenance | `::test_egress_ble_provenance_silent` |
| M13 | Security treats lock regime None as corroborated | `::test_lock_regime_none_rejects` |
| M14 | Debounce refreshed by each duplicate (sliding) | `::test_debounce_fixed_window_not_sliding` |
| M15 | Trip-wire denominator counts pre-sentinel / unmapped | `::test_unknown_name_faces_silent` |
| M16 (rev 4, H1) | Remove the explicit `provenance: face` write at `transit_validator.py:1908` AND the `.get` default on the bus key (each separately) | `test_transit_validator_provenance.py::test_face_only_real_path_provenance_face` |
| M17 (rev 4, M1) | `canonical_camera_key` returns the input leg's device id instead of the min over sources | `::test_protect_pick_and_frigate_egress_one_key` |
| M18 (rev 4, M3) | Skip the boot drop for source (c) | `::test_egress_boot_window_not_a_sighting` |
| M19 (rev 4, M5) | Lock regime or security reverts to literal `== "camera_face"` (each separately) | `::test_unknown_arrival_source_requires_corroboration` |
| M20 (rev 8/9) | Register a candidate in the census union, at the crossing or at confirmation (each separately) | `test_egress_direction_aware.py::test_candidate_not_in_census_union` / `::test_confirmation_never_registers_union` |
| M21 (rev 8) | Drop G1 / G2 / G3 (each separately) | `::test_g1_low_confidence_vetoed` / `::test_g2_path_below_min_vetoed` / `::test_g3_implied_speed_fails_stale_far_fix` |
| M21b (rev 9, build L2) | Treat G2 `skipped` as pass (no 0.9 requirement) | `::test_g2_no_map_requires_0_9` |
| M22 (rev 9) | Put the candidate's slug in bus/DB `person_id` at the crossing | `::test_entry_not_home_provisional_candidate` and `::test_perimeter_ignores_candidate` |
| M23 (rev 8) | Remove `camera_egress` from `CAMERA_DERIVED_ARRIVAL_SOURCES` AND mutate the fail-closed default (together; build L3: the membership alone is not separately load-bearing because unknown sources fail closed; reviewer C records that, not a GREEN row) | `test_face_access_invariant.py::test_camera_egress_requires_corroboration` |
| M24 (rev 8) | Apply the direction-aware rule with the switch False | `::test_switch_off_golden_replay` |
| M25 (rev 8) | `path_score` ignores edge order | `test_interior_paths.py::test_path_score_reverse_order_negative` |
| M26 (rev 9) | Count edges after T | `::test_path_score_ignores_hops_after_resolution` |
| M27 (rev 9) | Confirmation accepts an edge before the crossing (abs window) | `::test_home_edge_before_crossing_does_not_confirm` |
| M28 (rev 9) | Drop `camera_egress` from the HVAC default, or skip the migration (each separately) | `test_hvac_camera_egress.py::test_hvac_accepts_camera_egress_when_listed` / `::test_migration_appends_camera_egress_once` |
| M29 (rev 9) | Attach rate back to `== "attached"` | `::test_attach_rate_labels` |
| M30 (rev 9) | Outcome log with a constant `node_id` | `test_egress_outcome_log.py::test_two_crossings_10s_apart_both_persist` |
| M31 (rev 9) | Path map merged into `door_interior_neighbours` (or a neighbour reader reads the map) | `test_door_neighbours_untouched.py::test_entry_areas_near_areas_direction_identical_with_map` |
| M32 (rev 9) | Validator call bypassed in the load path | `test_interior_paths.py::test_invalid_file_rejected_whole_keeps_previous` |
| M33 (rev 9) | G3 reads `person.*` `last_updated` instead of the tracker's | `::test_g3_reads_freshest_gps_tracker_last_updated` |
| M34 (rev 9) | Stale-source edge allowed to confirm | `::test_stale_source_edge_does_not_confirm` |
| M27 (rev 10 re-point, build H3) | Confirmation accepts an edge before the crossing | `::test_bermuda_read_before_crossing_does_not_confirm` and `::test_gps_fix_before_crossing_does_not_confirm` (replaces the hollow home-edge test) |
| M28b (rev 10, build M6) | Delete the migration call in `__init__.py` | `test_hvac_camera_egress.py::test_setup_runs_camera_egress_migration` |
| M35 (rev 10, P2) | Candidate branch writes `_egress_identity_last_attach` | `::test_candidate_does_not_write_last_attach` |
| M36 (rev 10, P1) | Outcome record skipped on the no-legs / ambiguous return | `test_egress_outcome_log.py::test_every_resolution_persists_one_row_switch_off` |
| M37 (rev 10, P1) | Veto path calls the side-effecting confidence block instead of the pure helper | `::test_vetoed_path_no_boost_no_synthetic_stash` |
| M38 (rev 10, P2) | Waiter created before the INSERT / confirm without a row id | `::test_deferred_insert_then_ble_names_row_before_followup` |
| M39 (rev 10, P2) | GPS leg accepts any near fix (no home zone, no approach) | `::test_gps_near_without_approach_does_not_confirm` |
| M40 (rev 10, P2) | Abstain rule removed | `::test_intervening_crossing_abstains` |
| M41 (rev 10, P2) | Name switch not re-read before the DB write | `::test_name_switch_off_before_db_write_writes_nothing` |
| M42 (rev 10, P1) | D7 const fallback installed without validation | `test_interior_paths.py::test_four_load_outcomes` (foreign-house const -> `none`) |

**Phase column (rev 10).** Phase 1 drills: M1-M19, M25, M26 (scorer is Phase 1), M30 (now `node_id` only), M31, M32,
M36, M37, M42, M23 (D3). Phase 2 drills: M20-M22, M21b, M24, M27, M28, M28b, M29, M33-M35, M38-M41. M27's earlier
row (abs-window home edge) is superseded by the rev-10 row.

### Live validation table (written back into the README after restart)
- L1 picks resolved ≥ D0-P1; the fused Garage A pick reported unresolved with `room_cameras_empty` unless §13.3 was
  done (then resolved).
- L1b (rev 4) `ura_person_egress_event` rows for face-only crossings carry `identity_provenance: "face"` (not null).
- L2 the first sighting outside the boot window matches a recorder face change.
- L3 no sighting (interior or egress) in the first 600 s after restart.
- L4 no arrival from a home resident's interior sighting (pick one from the recorder).
- L5 egress: a named face-provenance entry gives an `egress_entry` sighting and NO `camera_face` arrival; a
  BLE-provenance entry gives no sighting.
- L6 if interior arrivals ship: the first class (i) event gives an HVAC `pre_arrival` row, or a recorded skip
  reason. Expected skip reasons: `pre_arrival_spent`, `pre_arrival_sources`, and the sibling's precool stand-down
  (HVAC-PRECOOL-STANDDOWN-WHEN-COOL-1) when the house is already cool.
- L7 no face-only lock release or expected arrival (snapshot + log scan).
- L8 no trip-wire NM.
- L9 INFO setup line `Face sighting: N/M picks resolved, K egress cameras`.
- L10 (rev 9) `path_map_source` names `interior_paths.json` (or `built-in const`) with `path_map_validation: ok`; the learned-vs-operator diff report is committed; a real garage entry in the recorder gets `path_score >= 2` on its bus event; the lock regime's entry areas are the same before and after the map loaded.
- L11 (rev 9, only if the switch is on) the first `arrival_candidate`: bus `person_id` null, `candidate_person_id` set, DB row NULL, "Someone arrived"; then either a confirmation within 10 min (DB row named, Persons Entered Today shows the name, one quiet "That was X") or an `arrival_unconfirmed` log row. Never in `_get_egress_face_ids_fresh` through the egress path.
- L12 (rev 9) no perimeter D10.5 reason cites a candidate (log scan).
- L13 (rev 9) outcome labels: `vetoed` only on exits (or with the switch off); entry vetoes appear as `vetoed_arrival_unverified` with the failed guard named.
- L14 (rev 9) memory_episodes `egress_identity_outcome` rows = resolved crossings since restart (one each; vetoed rows carry the slug).
- L15 (rev 9) the CM entry's `pre_arrival_sources` contains `camera_egress` and the migration sentinel is set; the first `camera_egress` arrival (if the egress flag is on) gives an HVAC `pre_arrival` row or a skip reason other than `pre_arrival_sources`.
- L16 (rev 9) attach rate unchanged in meaning: `egress_identity_attach_rate_24h` counts departure candidates.

---

## 10. Marginal risk, priced in ingredients

| Ingredient | Assessment |
|---|---|
| New writer to a shared primitive (`SIGNAL_PERSON_ARRIVING`) | Rate rises from 0 to the D2 rate, likely still ~0 (interior class (i), D0-gated, default off). An access consumer is downstream. Containment: D3 + INV-ACCESS. Tier 3. |
| Cross-module callback (census -> presence) | One hook per message, list in `hass.data`, exception-isolated, removed at unload. |
| Producer change in the egress path (rev 9, completeness M6) | No longer "one additive key": the face-only veto becomes direction-aware behind a default-off switch (declared zone deltas), plus additive keys, a new late `person_id` writer for entries (reuses the exit-backfill DAO and its NULL guard), a new signal, a notify branch. Containment: switch off = byte-identical (golden), INV-PROVISIONAL, drills M20-M34. |
| Time-based rare-fire path (rev 9) | The confirmation waiter (poll, window, supersession, cap). Same shape as the perimeter follow-up; teardown cancels; not persisted; outcome log records every end state, so it is observable. |
| New subscriptions (rev 9) | `_path_events` person legs for path nodes, only with the switch on and a map loaded. Torn down with the tracker; re-made on map reload. |
| New DB writes (rev 9) | ~15 memory_episodes rows a day through the write queue (no schema change); confirmation backfills (UPDATE by id). No table, no column. |
| CM options write (rev 9) | One-shot migration with a sentinel at the precedent's call site; it writes once per install. |
| Learned map (rev 9) | None at runtime: offline report only. Rev 8's "learned at setup / weekly" recorder reader (completeness M6) is withdrawn. |
| Rare-fire path | Interior arrivals may never fire. Covered by the arrival skip counters and the conditional LOW trip-wire. |
| Synthetic time | None. Timestamps come from the latch/sensor/egress event, compared to wall clock only for debounce and the boot window. |
| Config combinatorics | Picks × alias × security toggle × lock regime present/absent × window × observation mode. Covered by the D3 extremes. |

---

## 11. Tier classification

**Tier 3.** Triggers: a value threaded into a signal consumed by four sites, one of them an unlock; the failure mode
is one missed site (the expected-arrival sink would have been one); operator-flagged first-principles rebuild.

Process: two plan reviews (done, rev 1) -> this rev 2 -> operator APPROVE; build by `ura-super-builder` in a
worktree; four build reviews (A local, B integration/lifecycle incl. restart and census reload, C per-site mutation
M1-M15, D adversarial completeness against INV-ACCESS / INV-PRODUCER / INV-PROVENANCE incl. pre-existing code);
orchestrator re-greps §5 and re-runs M5, M6, M13; operator checkpoint before deploy.

**Rev 8/9 re-check: still Tier 3, with more reasons.** §2B changes the egress producer's DECISION logic (a shared
identity primitive read by the census union, perimeter de-escalation, notifications, four displays and now the arrival
signal), adds a second camera-derived source into the access-guarded signal, adds a second writer of entry
`person_id`, and sits next to house state (the census union feeds AWAY inference; INV-CENSUS-HOME and INV-PROVISIONAL
keep it out). Reviewer D's surface includes every reader of `ura_person_egress_event`, of `person_entry_exit_events`,
of `_egress_face_ids` and of `door_interior_neighbours` (pre-existing code, not just the diff), and INV-CENSUS-HOME /
INV-PROVISIONAL / INV-CANDIDATE. Orchestrator re-runs M20, M22, M23, M27, M31 before ship.

**Build order (rev 10):** Phase 1 as in §0A (D0 -> D8a -> D3 -> D1+D4 -> D2+D5+D6 -> D7). Phase 2 only after its
gate (§0A), as one Tier-3 cycle with two plan reviews of §2B against code at that time. Switches flip only on P7's
numbers, each in its own reviewed change.

**Phase 1 tier: still Tier 3.** It changes the egress producer's return channel (every return path), the access
gates of the lock regime and security (the expected-arrival sink), and adds a producer into a signal consumed by an
unlock. Reviewer D's Phase 1 surface: INV-ACCESS, INV-PRODUCER, INV-PROVENANCE, INV-NOOP (Phase 1 form), INV-LOG,
including pre-existing readers of `ura_person_egress_event`. Orchestrator re-runs M5, M6, M13, M19, M23, M36, M37
before each Phase 1 ship that touches those sites.

**HVAC touch (rev 10).** Phase 1 touches HVAC only through D2's counter fix (`camera_face_arrivals_today` by zone
membership) and D5's doc cite fix. Phase 2: the pre-arrival input set gains `camera_egress`: `DEFAULT_PRE_ARRIVAL_SOURCES`
(`hvac_const.py:350`), the selector (`config_flow.py:8192-8201`), a one-shot migration of the stored CM option. No HVAC
decision logic changes; the filter at `hvac.py:7231` is untouched. This planner read
`HVAC_ARCHITECTURE_STATE_OF_PLAY.md` completely for rev 9. Contradiction found (code wins): its §2 pre-arrival row
cites `hvac.py:4186` / `:1196`; the code is `_handle_person_arriving` `:7212`, subscribed `:1511` (D5 already fixes the
cite, F9). D8b's commit adds the source to that doc. Builders and reviewers read it completely before touching
`hvac*.py` or `config_flow.py`'s HVAC step.

**Sibling HVAC-PRECOOL-STANDDOWN-WHEN-COOL-1** SHIPPED as v5.108.14 (merged here). No code overlap. Doc contradiction
(code wins, reported): HVAC_ARCHITECTURE_STATE_OF_PLAY's header entry for it still says "built, NOT deployed"; D5's doc
commit corrects it to v5.108.14 unless the HVAC owner fixes it first. Its stand-down is an expected HVAC skip reason in L6.

## 12. Cards to mint (adjacency sweep before minting)
- **LOCK-RELEASE-ON-ARRIVING-BODY-EVIDENCE-1** (investigate): AWAY -> ARRIVING from body evidence alone releases the
  garage lockout and can auto-follow disarm; review against §5.5(a).
- **FACE-SIGHTING-CONSUMERS-1** (backlog, after ship): personalization reads `get_last_person_sighting` / the
  signal, declares an action class, and uses `face_input_corroborated` for any access class. Rev 4 (M6):
  notifications are NOT a new producer here; any sighting-based wording extends the existing
  `_arrival_departure_notify`. ARRIVAL-DEPARTURE-NOTIFY-1 is not a gap (that site exists).
- **FACE-EGRESS-ARRIVAL-1** (rev 8: UN-PARKED; on the board it is folded into **EGRESS-DIRECTION-AWARE-IDENTITY-1**,
  D8 + the D2 egress branch, D0-P7 gated).
- **DEPARTURE-ACTIONS-1** (on the board; rev 8 called it EGRESS-DEPARTURE-ACTIONS-1): consumers of `departure_candidate` (e.g. HVAC setback or
  away-lock hints) with their own action class; no `SIGNAL_PERSON_DEPARTING` until one exists.
- **EGRESS-PATH-OVERRIDES-DIRECTION-1** (rev 8, investigate): let `path_score` override or veto the resolved
  direction, if D0-P7 shows path <= 0 on resolved directions often enough to matter.
- **FACE-SIGHTING-TRACK-PROPAGATION-1** (rev 8, backlog): name propagation along the D7 interior track
  (`synthetic` `interior_track` sightings), the rev 2 D7 idea.
- ~~**EXTERIOR-ADJACENCY-TO-CONFIG-1**~~ (rev 8 suggestion) is superseded on the board by **EXTERIOR-SEAM-FILE-LOADER-1**
  (in build: wires `exterior_seams.json` into the linker with the const fallback, reload button, provenance attrs). D7
  reuses its loader. **INTERIOR-PATH-MAP-1** carries D7.
- **LOCK-ENTRY-AREAS-WRONG-OBJECT-1**: fixed in b70e3a2f (presence doc §1 line 88 SUPERSEDED note). Entry areas are
  now real, which is why D7 must never widen `door_interior_neighbours`.
- **PHONE-LEFT-BEHIND-CAMERA-LEG-1** (rev 3, Tier 2-DB minimum, house state): its camera leg reads
  `TransitValidator._camera_sightings`, which never holds a named sighting live (`hours_since_camera_sighting` null on
  all four sensors 2026-11-12; `person_id` attribute is a display name, not a slug). Migrate to
  `get_last_person_sighting(slug)`; retire the named branch of `_camera_sightings` (KEEP + WIRE).
- **VISION-CROSSING-ANALYSIS-1** (on the board; rev 3 called it CROSSING-VISION-SEQUENCE-1; §15): crossing snapshot sequence + batched vision analysis as a `vision`
  provenance. Gated on D0-V; its own plan `PLANNING_crossing_vision_sequence.md` is written only if D0-V passes.

## 13. Operator actions (no code)
1. Optional: `face_name_aliases` `Oji=oji_udezue` (hygiene; the census mapper already maps Oji while his first name
   is unique among tracked persons).
2. No decision is needed on manual §5.5 (F7): egress identity feeds no arrival, and the face never suppresses on its
   own. Recorded in D5's doc update.
3. **Garage A pick (rev 4, M2; config-first, operator action, no code, not done by this plan).** The Back Hallway
   pick `binary_sensor.garage_a_camera_person_detected` is the URA fused sensor of a room whose `room_cameras` is
   `[]`, so it is permanently off and resolves to nothing. Operator chooses one, in settings:
   (a) Garage A room options: set its room cameras to the Garage A camera; or
   (b) Back Hallway zone cameras: replace that pick with the Garage A camera's own person sensor.
   Either makes the pick resolve with no code change. Until then the plan reports it `room_cameras_empty`.
4. **Path map questions (rev 9, completeness M5).** Answers go into `interior_paths.json` (or into egress config, which
   is a settings change, not code). Until answered the affected door edges are omitted, never guessed.
   - Q1-Q4, Q7, Q8: ANSWERED 2026-11-12 (fixture "Operator answers"; applied in D7).
   - Q5 Garage B: its exterior approach cameras and first interior camera (live neighbours are empty).
   - Q6 Patio: there is a patio camera (Reolink) but no patio egress camera configured. Add one to egress cameras, or
     leave patio crossings unwatched? (Unwatched doors are also the named residual of the Phase 2 abstain rule.)
5. **Pre-arrival sources (rev 9; Phase 2 only).** The Phase 2 migration adds "Camera at a door (confirmed arrival)" to HVAC pre-arrival
   sources because `camera_face` is ticked today. Untick it in the CM options to keep HVAC off egress arrivals.
6. **Weekly P7 label review (rev 10, Phase 1, from the D8a ship on).** Each week, review the labeller's `mis` labels and
   every replayed confirmation within 7 days (crossing snapshots and recorder history expire). This is what makes the
   Phase 2 decision possible; a skipped week shrinks n.

---

## 14. Rev 2 changelog (each review finding, resolved where)

Build-prediction review:

| Finding | Resolution | Where |
|---|---|---|
| H1 egress entry is a post-arrival duplicate | Option (b): egress = sightings only, no arrivals; `room`/`camera` defined as crossing location; D0-P2 measures not-home named entries | §0, §3.1, §3.3 rule 2, §7 P2, §8, L5 |
| H2 restore replay of face sensors | (b) ignores `old_state` None/unavailable/unknown; `PERIMETER_EGRESS_ARRIVAL_BOOT_EXCLUDE_S`; test + M10 | §3.2, §3.3 rule 4, §6, D1, M10, L3 |
| M1 pick -> stem unspecified | `PickBinding`; join on registry-resolved face entity id; four re-resolution triggers | §3.2 |
| M2 trip-wire denominator not a REUSE | BUILD post-sentinel ring at latch; mapped resident + picked stem; new silent tests + M15 | §1.2, §3.5, D4 |
| M3 security has no stamps | Public `face_input_corroborated`; fail closed on None; no held re-check, stated | §3.4, D3, M13 |
| M4 observation mode | Arrivals gated; sightings not gated (no action); test + M11 | §3.2 Dispatch, §3.3 rule 3, M11 |
| M5 "not home at ts" with past ts | Current raw state + in-memory `_last_home_edge_ts`; `phone_already_home` skip | §3.3 rule 5, D2 |
| M6 debounce semantics | Fixed window; "clears synthetic" deleted, replaced by last-sighting store upgrade; hook once per message; multi-stem rule | §3.1, §3.2, M14 |
| M7 class (iii) buys nothing | Dropped; knob removed; reported as context in D0 | §3.3, §6, §7 P3 |
| L1 egress min conf no-op | Knob removed with egress arrivals | §6 |
| L2 zone order | `house_zones` sorted; music must not rely on it | §3.1, §3.3 |
| L3 census reload loses callback | Callback list in `hass.data`, read per message; test | §3.2, D1 |
| L4 door-naming kill switch | Egress honours it via the producer; interior does not, stated | §3.2 Filters |
| L5 source-grep test | Lint only; behavioural authority named | D5 |
| Hollow tests table | All six rows rewritten (D1 discriminator, M1, M2, M6, D4 silent cases, L4->L5) | D1, D4, drills, live table |
| New drills | M10, M11 added (plus M12-M15) | Drills |
| Last-sighting accessor | `get_last_person_sighting` / `get_last_person_sightings` | §3.1 |

Completeness review:

| Finding | Resolution | Where |
|---|---|---|
| F1 Garage A pick is URA fused, not Protect | Claim corrected. Operator direction applied: every pick walks pick -> physical camera (resolver ladder) -> each integration's entities; existing resolver covers camera-integration picks; new thin `resolve_pick_to_fusions` covers URA fused room picks; Protect yields no face name (recorded, parked bridge) | §0, §1.2, §3.2, §7 P1, §13 |
| F2 egress `person_id` may be BLE | Additive `identity_provenance` bus key; only `face`/`ble+face` become sightings; INV-PROVENANCE; M12 | §2, §3.2 (c), §8, D1 |
| F3 Oji mapped by census | One mapper: `_canonical_person_slug`; alias optional; test renamed | §0, §1.1, §1.2, §13 |
| F4 security gate state source, fail-closed | Same as M3 | §3.4 |
| F5 observation mode | Same as M4 | §3.3 |
| F6 denominator + per-stem/per-message hook | Same as M2 + M6 | §3.2, §3.5 |
| F7 §5.5 doctrine vs egress arrivals | Resolved by H1 (no egress arrivals); suppression is by the non-face edge; doc clarification only; no operator question | §13.2, D5 |
| F8 door-camera double sightings | Cross-source dedup on (slug, physical_camera) | §3.2, D1 |
| F9 HVAC doc drift + sibling | D5 fixes cites; sibling named as expected skip and build order set | D5, §11, L6 |
| F10 service sinks | Added to §5; perimeter D10.5 scope note | §5 |
| F11 tracker face fields | Kept, fed per house zone by sightings | §3.2 Dispatch, D1 |

---

## 15. AI vision of a crossing (rev 3): a later provenance, designed now, built only after D0-V

Operator 2026-11-12: watch people at an arrival with a vision model instead of relying on face recognition, and it
"doesn't have to be live ... a time lapse set of snapshots ... for say the first x minutes to characterize in more
detail what is actually happening".

**Decision: a sibling plan, gated on D0-V, with its shape fixed here.** Reasons: (1) it has its own risks (frames
leave the house, per-event cost, a new provider dependency) that the Tier-3 access cycle should not carry; (2) its
value is unmeasured, and a measurement is cheap; (3) the identity model in §2A already has the slot for it
(`IDENTITY_PROVENANCE_VISION`, INV-ACCESS already covers it), so no rework later. This cycle builds nothing in §15.

### 15.1 What is live today (read from config, 2026-11-12, not assumed)

- llmvision **1.7.1** custom integration (`/config/custom_components/llmvision/manifest.json`). Two entries: "LLM
  Vision Settings" (global; `memory_paths` / `memory_strings` empty, `retention_time` 7) and **"OpenAI"**
  (`01KHB0EV5AP8ANWQ7RWT30M2CC`, provider OpenAI, default model `gpt-5-mini`). That is a **cloud** provider.
- URA's integration entry: `perimeter_enrichment_enabled: true`, model pinned `gpt-4o-mini`, `max_tokens` 1500,
  provider id = the OpenAI entry, allowlist = 14 perimeter person sensors (back_yard, utilities_ptz, rear_ptz,
  front_side_ptz, g5_bullet, pool_equipment, hot_tub; Frigate + Protect legs). **No door, garage or interior camera
  is enriched today.**
- An `ollama` HA integration points at `http://192.168.13.62:11434/`. It is NOT an llmvision provider, and whether
  it serves a vision model is UNVERIFIED. A local option is a config action (add an llmvision provider entry), not
  code, if a vision model runs there.
- llmvision services verified in its `services.yaml` / `__init__.py`: `image_analyzer` (`image_file` takes several
  newline-separated paths, `__init__.py:457`; `image_entity` takes camera entities; `response_format: json` +
  `structure` JSON schema), `video_analyzer` (`video_file`, or Frigate `event_id` fetched through HA's Frigate proxy
  `/api/frigate/notifications/<id>/clip.mp4`; `max_frames` 1-10, frames with most movement), `stream_analyzer`, and a
  "memory" feature (reference images with name strings).
- **Model plumbing (rev 5, read from llmvision 1.7.1 `providers.py`, not assumed).** The OpenAI provider passes
  `call.model` straight into the payload (`providers.py:691`), so any model id string works with no llmvision change;
  URA already sends `model` per call (`perimeter_enrichment.py:206`). Images go as `image_url` data URIs with NO
  `detail` field (`providers.py:746-750`), so OpenAI's default (`auto`) applies; resolution is controlled only by
  `target_width` (default 1280, range 512-1920, `services.yaml:69-78`). Two caveats D0-V must check with one dry call
  per model: (a) `temperature`/`top_p` are sent for every model except the exact names `gpt-5`, `gpt-5-mini`,
  `gpt-5-nano` (`providers.py:707`); the OpenAI entry sets 0.5/0.9, and a reasoning model that rejects them would
  fail every call; (b) the reasoning-effort table (`providers.py:616-627`) has no `gpt-6*` prefix, so no
  `reasoning_effort` is sent. Candidate ids from OpenAI's models page (fetched 2026-11-12): `gpt-6-luna` ($0.10 /
  $0.50 per 1M in/out), `gpt-6.1-sol` ($2 / $10), `gpt-6-astra` ($10 / $50); all accept image input. Temperature
  support is not stated there. Live today: the llmvision OpenAI entry default is `gpt-5-mini`; URA pins
  `gpt-4o-mini` per call.
- Measured (`AUDIT_consol_1_d0_probe.md`): gpt-4o-mini, one snapshot, 1.4-2.0 s, 0 errors in 25 calls; estimated
  ~$0.003-0.008 per single-image call (llmvision does not report token usage, so cost is an estimate). Multi-image
  cost and latency are NOT measured; D0-V measures them.

### 15.2 What a general vision model can and cannot do here (honest)

Cannot, or should not be relied on:
- **Name a specific resident from the face.** General hosted models are not face-recognition systems, are
  unreliable at it on 2-4 MP overhead door frames, and providers may decline to identify people. llmvision "memory"
  could hold reference photos of residents, which turns the cloud model into a face matcher and sends biometric
  reference images off-site. **Recommended: do not use memory with resident faces.** D0-V records the refusal rate
  rather than assuming it.
- Be an access input. Never (INV-ACCESS).

Realistic:
- Describe what happened ("two people and a dog came in through the garage; one carried grocery bags").
- Count people; vehicle present / arriving / leaving; carried items; direction of travel across the sequence.
- Non-face cues (clothing, build, gait across frames) used for **re-identification across the cameras of one
  crossing** and for "resident-like vs unknown" when given text profiles, NOT photos.
- Delivery vs visitor vs resident-like (uniform, package, vehicle type, time at door).
- Consistency check against the face/BLE identity: "the named person is one of the people in these frames" is a
  plausibility signal, not a recognition.

### 15.3 Design (for the sibling plan)

1. **Trigger:** an egress crossing with direction `entry` or `exit` (F3; `ura_person_egress_event`). Ambiguous
   crossings are skipped. Display-only, so it is not time-sensitive.
2. **Capture a snapshot sequence** at cadence `CROSSING_VISION_SNAPSHOT_INTERVAL_S` for
   `CROSSING_VISION_SEQUENCE_DURATION_S`, on the door camera plus the next cameras on the path: interior neighbours
   from `transit_validator._get_interior_cameras_near` for entries, exterior neighbours from
   `ExteriorTrackLinker.adjacent_cameras` for exits. Capture reuses the perimeter live-grab path
   (`_try_capture_live_grab`, `camera.snapshot`) into `PERIMETER_SNAPSHOT_DIR/crossings/<crossing_id>/`. Prefer the
   Frigate event snapshot/clip when the crossing camera's Frigate event id is known (fewer grabs; no extra camera
   load). That event id comes from the existing `FrigateEventIngress` (`frigate_ingress.py:147`, consumer
   registration `register_consumer` `:175`; rev 4 L6), not a new MQTT listener.
3. **Clustering:** crossings that start while a sequence is open on the same door extend that sequence (one
   sequence, several crossing ids attached), capped at `CROSSING_VISION_SEQUENCE_MAX_S`. Different doors run
   independent sequences, at most `CROSSING_VISION_MAX_CONCURRENT` at once; extra crossings are counted `skipped_busy`,
   never queued without bound. A daily cap `CROSSING_VISION_DAILY_CALLS` bounds cost; over the cap = skip + counter.
4. **One batched analysis per sequence** after it closes: a multi-image variant of
   `perimeter_enrichment.enrich_dispatched_alert` (same kill switch, timeout, never-raise and non-empty rules), JSON
   structure `{people_count, people: [{description, clothing, carried, resident_like: yes|no|unsure,
   matches_named_person: yes|no|unsure}], vehicle, direction, summary}`. Latency does not matter, so the timeout
   can be long (`CROSSING_VISION_TIMEOUT_S`).
5. **Into the identity model:** attach the result to the crossing as evidence with `provenance = vision`:
   - It never sets or overrides `person_id`. If the egress producer already named someone, `matches_named_person`
     becomes a plausibility flag on that attach (`vision_consistent: true|false|unsure`).
   - It may produce a `PersonSighting` only when it re-identifies the SAME person the face/BLE attach named, and then
     at most `CONFIDENCE_LOW` (0.3) on its own; vision + face on one crossing come from the same frames, so they are
     correlated and never reach 0.9 (same rule as `FACE_MATCH_CORRELATED_BOOST`).
   - `resident_like` / delivery / visitor are attributes for display and notification wording, never identity.
   - Never access-class (INV-ACCESS covers it). Never a census input.
6. **Storage and retention:** frames reuse the perimeter snapshot directory and its prune (`_prune_snapshot_dir`,
   168 h / 5000 files) with the sequence subdirectory counted in the same budget; a sequence is deleted after
   analysis unless `CROSSING_VISION_KEEP_FRAMES` is on. The JSON result is stored as a `memory_episodes` row
   (`episode_type = crossing_vision`, `source_ref = crossing id`, `dedup_source_ref=True`, the linker's pattern at
   `exterior_track_linker.py:694`), batched through the DB write queue, one row per sequence.
7. **Privacy:** frames go to OpenAI while the provider is cloud. Operator choices: cloud with door cameras only; a
   local llmvision provider (if the Ollama host serves a vision model); or off. Interior frames go off-site only on an
   explicit separate toggle (`CROSSING_VISION_INTERIOR_ENABLED`, default False). **Rev 5:** the operator wants the
   interior cameras in the enrichment purview (entry chains end indoors; §15.8 head counts are interior). The toggle
   stays, as the explicit privacy switch, but the sibling plan's intended live setting is ON after D0-V passes.

8. **Progressive analysis (rev 4, operator 2026-11-12).** A fast first call (rev 6: three detection-timed, guarded
   frames, §15.5a) yields a PROVISIONAL hypothesis `{people_count, direction, resident_like}` attached to the crossing
   with `provenance = vision`, `stage = provisional`, confidence capped at `CONFIDENCE_LOW`. The batched sequence call
   (item 4) then records `stage = final`, confirming or revising it; both records are kept (never overwritten), each with
   provenance, confidence and a `revised: bool`, so D0-V can measure how often the first frame was wrong.
9. **Vision count as census evidence (rev 4, operator 2026-11-12).** An entry/exit people-count ledger per watched door
   (`+n` on a final entry, `-n` on a final exit). **Ownership does not move:** the census stays the single owner of F2
   (§2A); the ledger is one more evidence input it reads, like `register_egress_face`, never a second census.
   Why it is NOT error-free, stated plainly:
   - doors and paths with no watched camera (any uncovered door makes in-minus-out wrong forever);
   - tailgating and occlusion (two people in one frame read as one);
   - night IR frames (lower count and direction accuracy);
   - exits are not seen as well as entries (backs to camera, faster, different light), so the ledger drifts one way;
   - provider outage, timeout, refusal, or the daily cap skipping a crossing = a missing term;
   - an in-minus-out ledger accumulates every error above with no natural correction.
   Reconciliation design: the ledger is clamped at 0; it is reset to the BLE/tracker resident floor when the house is
   verifiably empty (all residents away + no body evidence) and at a periodic quiet point; each term decays out after
   the census decay window, so the ledger answers "who came in recently", not "who is in the house since boot"; a
   residual above the BLE-known resident count is the GUEST hypothesis, still subject to the census's guest gate.
   **Gated decision, not a promise:** "census from vision" (the ledger weighed above face/person counts) is decided
   only on D0-V numbers (§15.4); the default outcome is evidence-only.
   **Rev 5 framing (operator):** residents are solved by BLE/trackers; the census problem is NON-residents. The ledger
   therefore answers one question: non-resident count = vision ledger total minus BLE-home residents (clamped ≥ 0).
   Vision counts groups and people walking away well; naming stays with face/BLE. Independent checks on the ledger:
   empty-house reset, periodic interior head count (§15.8), exit-chain matching (an exit cluster of n closes n open
   entry terms). **Rev 6:** the guest count is never the ledger alone; it is the fused value of §15.7 (vision AND
   Frigate/Protect counts, deconflicted), and camera counts stay in it until the §15.7a trust decision.

Knobs (all proposed for the sibling plan; rung and default set there after D0-V): interval (rung 3), duration
(rung 3), max sequence (rung 1), concurrency (rung 1), daily cap (rung 3), timeout (rung 3), keep-frames (rung 2),
interior toggle (rung 2), master enable (rung 2, default off), kill const (rung 1; reuse
`LLMVISION_ENRICHMENT_KILL`).

### 15.4 D0-V: measure before building (read-only, operator-approved)

Sample: 40 past crossings from `person_entry_exit_events` with ground truth from BLE (a resident's
`person.*` / Bermuda edge within ±120 s, the D10.5 rule), plus 10 with no resident edge (likely visitors /
deliveries). For each, fetch what still exists: the Frigate event snapshot/clip for the door camera (Frigate
retention on the homelab is UNVERIFIED; P0 counts how many past crossings still have media) and the perimeter
snapshot if one exists. Run the existing enrichment adapter on 4-8 frames per crossing with the §15.3 JSON schema.

Score:
- **Description quality:** operator labels 20 summaries correct / partly / wrong.
- **People count** vs ground truth (BLE residents + face) — exact-match rate.
- **Resident-like vs unknown** vs ground truth — accuracy, and the false "resident-like" rate on the 10 non-resident
  crossings (the dangerous error).
- **Consistency:** for crossings with a face/BLE name, `matches_named_person` agreement; and for 20 crossing PAIRS
  (same person vs different person by BLE), same-person accuracy from non-face cues.
- **Refusals, latency per call, estimated cost per crossing** (frames x per-image estimate).
- **(rev 4) Provisional vs final:** first-frame hypothesis agreement with the final call (count, direction).
- **(rev 4) Count accuracy, both directions separately:** exact people-count match for entries AND for exits vs BLE/face
  ground truth; day vs night (IR) split.
- **(rev 4) Coverage:** of BLE-known resident crossings (a `person.*` / Bermuda home or away edge) over the window, the
  fraction that pass a WATCHED door (have a `person_entry_exit_events` row on a camera-covered door within ±120 s).
  Uncovered crossings are the ledger's irreducible error.
- **(rev 5) Model comparison.** Step 0: one dry call per candidate (`gpt-4o-mini` baseline, `gpt-6-luna`,
  `gpt-6.1-sol`; `gpt-6-astra` only if Sol fails accuracy) through llmvision to prove it is accepted (§15.1
  temperature caveat). Then each crossing runs both stages per model: FAST (§15.5 F-stage, rev 6: 3 guarded frames, 768 px) and
  BATCH (§15.5 B-stage: up to 12 frames, 1024 px). Recommended pairing to test first: Luna for fast, Sol for batch.
- **(rev 5) Fast vs batch accuracy**, scored separately per model, per stage, for entries and exits: count exact-match,
  direction, group size, refusal rate.
- **(rev 5) Guest-ledger return to zero.** Replay a full day: does vision-ledger minus BLE residents return to 0 at
  the empty-house / all-guests-left points (operator labels when guests were present)? Residual at day end, and the
  number of hours it sat ≠ 0 with no guest present.
- **(rev 5) Tokens and cost per crossing per model, measured.** llmvision does not return usage, so D0-V sends the
  same payload once directly to the OpenAI API (same frames, same `target_width`, `detail` omitted) to read
  `usage.prompt_tokens` / `completion_tokens`; every §15.5 token figure is replaced by the measured one.
- **(rev 5) Latency per stage per model:** p50/p90 of call duration and of frames-ready-to-result, fed to D0-SIM.
- **(rev 5) Agreement with Frigate/Protect counts** on the same crossing (the §15.7 disagreement rate).
- **(rev 6) Per-case deconfliction scoring:** for every crossing, the §15.7 case (A agree / B vision higher / C camera
  higher / D one side missing) and which side matched ground truth in each case. This is the data the §15.7a trust
  criterion is computed from; D0-V reports it per camera and day/night.
- **(rev 6) Frame selection:** F-stage frames come from D0-FRAME's chosen offsets (§15.4a), not fixed seconds.

### 15.4a D0-FRAME: frame timing and blank-frame experiment (rev 6, read-only, offline; runs BEFORE D0-V)

Operator 2026-11-12: "more frames in the initial analysis, maybe 3; well timed so we don't send blanks; a guard and
some experiments." Measure-before-build: the frame offsets are an empirical property of each camera, so they are
measured over recorded events, not guessed.

Inputs (existing only): Frigate event payloads for the egress and chain cameras (the `frigate_events` stream that
`FrigateEventIngress` normalises, `frigate_ingress.py:110` / `:147`; recorder or Frigate's own event API on the
homelab, read-only), the event snapshots and clips Frigate still retains (`/api/frigate/notifications/<id>/snapshot.jpg`
and `clip.mp4`, the paths `perimeter_alert.py:2125` already builds), and `person_entry_exit_events` for t0. Which
per-update fields Frigate's payload carries (object box, score, frame time, has-snapshot) is read from the recorded
payloads in step 0, not assumed; if the box is absent the guard falls back to a person-detection check on the frame
(step 3).

Method (scratchpad script, no HA or URA writes, no cloud call):
0. Dump 50 recorded person events per egress camera; list the `after` keys actually present. Record whether a box,
   score and frame time arrive on each update.
1. For each event, extract frames from the clip at offsets relative to (a) the event start, (b) the first update with
   a person box, (c) the event best snapshot frame time, (d) t0 (crossing emit). Offsets -2 to +8 s, 0.5 s step.
2. **Blank** = no person in the frame. Label automatically with the box-in-frame test at that frame time when the
   payload has boxes; otherwise run Frigate's own detection result for that frame where available; 30 frames per camera
   are hand-labelled by the operator to check the automatic label (agreement ≥ 95 % or the automatic label is not used).
3. Per camera, split day vs night (IR): blank rate at each offset per anchor; the best 3-frame set (the set maximising
   frames-with-person and spread for direction); the latency cost of each set (how long after t0 the 3rd frame exists).

Report: per camera × day/night, blank rate by anchor and offset, chosen 3 offsets, and their latency. Thresholds
(stated now): the chosen set has **≥ 2 of 3 frames with a person on ≥ 95 % of events and 0 all-blank sets on ≥ 99 %**,
and its 3rd frame exists by **t0 + 6 s p90**. A camera that fails at night gets night-only offsets or F = event
snapshot + 2 detection updates only; a camera that fails both = F runs with whatever non-blank frames exist (min 1) and
is marked `fast_frames_short`. Output goes in `docs/planning/AUDIT_crossing_vision_d0_sim.md` (same audit as D0-SIM),
and the chosen offsets become rung-1 knobs in the sibling plan.

Go rule for the sibling plan: description correct-or-partly ≥ 80 %, false resident-like ≤ 5 %, refusals ≤ 10 %,
p90 latency ≤ 60 s, projected cost at the measured crossing rate ≤ the CONSOL-1 single-digit-dollars/month band.
Census-from-vision gate (rev 4, separate and stricter): entry AND exit count exact-match each ≥ 95 %, night ≥ 90 %,
coverage ≥ 95 % of BLE-known crossings, provisional-to-final revision ≤ 10 %. Fail any = vision count stays
evidence-only (or is not built), with trigger "an uncovered door gets a camera" / "a local model removes outage risk".
Re-ID pairs are reported but do not gate (they only matter for the 0.3 sighting). Fail = park with trigger "a local
vision model is available" or "door face recognition stays below 20 % of crossings after FRIGATE-DOOR-FACE-TUNING-1".

**Marginal benefit, priced honestly.** The description of what happened is the real value and is new; the identity
gain is small, because a vision attribution is capped at 0.3 and cannot name anyone the face/BLE path did not. The
ingredients are a cloud dependency, off-site frames and a new batch path; none touches a shared primitive or access.
That is why it is a separate, measured, default-off cycle rather than part of this one.

**Rev 5 go rule additions:** fast-stage count exact-match ≥ 85 % (it is provisional), batch ≥ 95 % entries and ≥ 90 %
exits; ledger returns to 0 within one empty-house reset on ≥ 95 % of labelled days; measured cost within the §15.5
envelope ×1.5; D0-SIM (§15.6) passes. A model that fails step 0 is dropped, not patched around.

### 15.5 Timing design (rev 5): fast sample, batch, synthesis

Every number below is a MODELED starting value. D0-SIM replays them, D0-V replaces the latency and token figures with
measured ones, and the sibling plan puts each on the knob ladder. Token figures use OpenAI's published GPT-4o-family
tile formula (low-detail base 85 tokens + 170 per 512-px tile after scaling; I applied it, I did not measure it).
The GPT-6 models may count image tokens differently; that is exactly what D0-V's direct-API usage read settles.

**Measured inputs (URA DB `person_entry_exit_events`, 14 days to 2026-11-12, via `ssh ha sqlite3 -readonly`):**

| Door (all legs) | Rows / 14 d | Per day | Entry / exit |
|---|---|---|---|
| Front (doorbell_lite + front_door_aerial, Protect + Frigate legs) | 92 | 6.6 | 59 / 33 |
| Garage A | 63 | 4.5 | 23 / 40 |
| Madrone G6 entry | 45 | 3.2 | 22 / 23 |
| **All** | **201** (some are the same crossing seen by two legs) | **14.4 mean, 3-25 range** | 106 / 95 |

Clustering (same door, gap ≤ W): W = 60 s → 11.9 clusters/day; **120 s → 10.5/day (largest 8 rows)**; 300 s → 9.6/day;
600 s → 9.1/day (largest 15). At most 2 doors were active within any 300 s. `peak_person_count`: 1 = 132, 2 = 56,
3 = 4, 6 = 1, 0 = 8. Hours (UTC) cluster 13-01, i.e. 07:00-19:00 CT plus a late-evening block; ~1/3 are after dark.

**Stage timeline (t0 = the egress crossing event, `ura_person_egress_event`):**

| Stage | What | Frames / size | Model | Lands (modeled p50 / p90) |
|---|---|---|---|---|
| Edge | Camera person edge to crossing emit; includes `PERIMETER_EGRESS_XCORR_SETTLE_S` (20 s) where it applies | n/a | n/a | t0 is 0-20 s after the camera edge; D0-SIM measures it |
| F (fast, rev 6) | Three frames timed to DETECTION, not wall clock (§15.5a): frame 1 = Frigate event best snapshot (event id from `FrigateEventIngress`), frames 2-3 = the frames at the next two Frigate updates that carry a person box, spaced ≥ `CROSSING_VISION_FAST_MIN_SPACING_S` (modeled 1 s), at D0-FRAME's per-camera offsets. Blank-frame guard drops any frame with no person and replaces it from the next update; send when 3 guarded frames exist or at `CROSSING_VISION_FAST_MAX_WAIT_S` (modeled 6 s) with ≥ 1. Door camera only. Prompt asks only `{people_count, direction, group, resident_like}` | 3 × 768 px wide (~425 tokens each by the 4o formula), ~400 text tokens in, ≤ 150 out | `gpt-6-luna` | frames ready 2-6 s + call 2-5 s → **t0 + 6 s / t0 + 12 s** |
| B (batch) | Window opens at t0, closes at t0 + 60 s (extended by clustering, cap 180 s). Door camera every 5 s for the first 20 s then every 10 s; up to 2 chain cameras (§15.8: interior for entries, exterior for exits) every 10 s from t0 + 5 s. Frames with no person detection on that camera are dropped before the call | ≤ 12 × 1024 px (~765 tokens each), ~600 text in, ≤ 600 out | `gpt-6.1-sol` | window 60 s + call 5-20 s → **t0 + 70 s / t0 + 90 s** unclustered; clustered worst t0 + 180 s + 30 s |
| S (synthesis) | Join F, B, face (Protect names back-fill ~1-2 min; `FACE_MATCH_WINDOW_S` 60), BLE (home edges; exit backfill `BLE_EGRESS_EXIT_BACKFILL_WINDOW_S` 600) and Frigate/Protect counts into the final crossing record and the ledger term | none | none (local) | entries **t0 + 120 s**; exits wait for BLE backfill, **≤ t0 + 600 s** |

Why these numbers: the person usually reaches the next camera on the chain 5-20 s after the door (assumed; D0-SIM
measures hop times from Frigate events), so a 60 s window covers the door plus 2-3 hops, and a 5 s door cadence gives
4 frames of the door moment, which is where groups split. Three frames for F (rev 6): two give direction, the third
separates a tailgater from one person and survives one bad frame; detection timing keeps all three on the person.
768 px for F because count and direction do not need detail; 1024 px for B because tailgating and occlusion do.

**Against the census windows:** interior hold `DEFAULT_CENSUS_HOLD_INTERIOR_MINUTES` = 3 min, exterior 5 min,
`EGRESS_FACE_UNION_TTL_S` = 300 s, face window `CENSUS_FACE_RECOGNITION_WINDOW_SECONDS` = 1800 s. F lands inside the
first census debounce (`CENSUS_EVENT_DEBOUNCE_SECONDS` = 30); B lands well inside the 3-min interior hold
unclustered; S for entries lands inside the 300 s egress TTL. Exit synthesis can exceed 300 s; that is acceptable
because an exit lowers a count and the existing hold already covers it, and D0-SIM checks it.

**Per-day envelope (calls, tokens, cost) at the measured rates.** Mean = 14.4 crossings, 10.5 clusters; worst = 25
and 25 (no clustering).

| Item | Calls/day mean (worst) | Tokens/call in (out) | Cost/day mean (worst) |
|---|---|---|---|
| F on `gpt-6-luna` (rev 6: 3 frames) | 14.4 (25) | ~1,675 (150) | $0.004 ($0.007) |
| B on `gpt-6.1-sol` | 10.5 (25) | ~9,800 (600) | $0.27 ($0.64) |
| Interior head count (§15.8) on `gpt-6-luna`, 1 call per 30 min while occupied, 12 cameras × 768 px | 48 (48) | ~5,500 (200) | $0.03 ($0.03) |
| **Total** | ~73 (98) | | **~$0.30 ($0.68) → ~$9/month mean, ~$20 worst** (rev 6: the third F frame adds ~$0.03/month) |
| Baseline: same F + B on `gpt-4o-mini` (images priced at ~2,833 base + 5,667/tile tokens at $0.15/1M by the same published formula) | | | ~$0.55/day |

B dominates the bill. If D0-V shows Luna's batch accuracy meets the gate, Luna for both stages cuts the total to about
$1/month. The daily cap (`CROSSING_VISION_DAILY_CALLS`) is set from the worst-case column, not the mean.

### 15.5a Blank-frame guard and detection timing (rev 6)

Reuse, not new capture: the event id and updates come from `FrigateEventIngress.register_consumer`
(`frigate_ingress.py:175`); the best snapshot from the existing Frigate notifications snapshot path
(`perimeter_alert.py:2125`, multi-instance form `:36`); frames stored in the perimeter snapshot directory with its
prune (`_prune_snapshot_dir`). Rules:
1. A frame is eligible only if a Frigate update for that camera at that frame time reports a `person` object (box
   present, score ≥ the camera's existing Frigate threshold; no new score knob). Protect-only door (doorbell leg): its
   smart-detect thumbnail is frame 1, live grabs at the D0-FRAME offsets after a Protect person edge are frames 2-3.
2. A frame failing rule 1 is dropped, never sent; the next qualifying update replaces it.
3. Frames closer than `CROSSING_VISION_FAST_MIN_SPACING_S` to the previous chosen frame are skipped (no near-duplicates).
4. At `CROSSING_VISION_FAST_MAX_WAIT_S` send what exists if ≥ 1; zero guarded frames = no call, record
   `skipped_blank` (counted; a camera whose `skipped_blank` rate exceeds the D0-FRAME threshold trips the anomaly
   detector wired to NM).
5. The same guard applies to B-stage frames (already "frames with no person detection dropped", now via rule 1).

Knobs (sibling plan): `CROSSING_VISION_FAST_FRAMES` (rung 1, 3), `CROSSING_VISION_FAST_MIN_SPACING_S` (rung 1, from
D0-FRAME), `CROSSING_VISION_FAST_MAX_WAIT_S` (rung 1, from D0-FRAME; 0 = F disabled, B only), per-camera offsets
(rung 1 table from D0-FRAME).

**Concurrency:** at most 2 doors active within 300 s measured, so `CROSSING_VISION_MAX_CONCURRENT` = 2 open sequences
covers every observed day; a third is `skipped_busy`.

### 15.6 D0-SIM: simulate before building (read-only, offline)

Purpose: prove the §15.5 timings and sizes are right BEFORE any code, against the house's own crossings.

Inputs (all existing, read-only): `person_entry_exit_events` (14+ days), the HA recorder history of the egress
cameras' person sensors and the chain cameras' person sensors (for camera-edge and hop times), BLE `person.*` /
Bermuda edges, Frigate events and snapshots/clips where retained (P0 of D0-V counts them), Protect face-name
back-fill times from the recorder.

Method: a script in the scratchpad, run once, no HA writes, no URA writes. It replays each crossing on a simulated
clock through four stages:
1. **Modeled run:** §15.5 latencies and token sizes as fixed distributions.
2. **Measured run:** the same replay with D0-V's measured per-model latency and usage distributions substituted.
3. For each crossing it records: when F, B and S land relative to t0; where the person was on the chain at each
   landing (from the camera edges); whether B's window contained every chain camera the person actually hit;
   whether the stage landed inside the census interior hold, the 300 s egress TTL and the 30 s debounce; and
   cluster sizes, concurrency and daily call/token totals under the caps.
4. Sensitivity: rerun with B window 30/60/90 s, door cadence 3/5/10 s, `target_width` 768/1024/1280.

**Pass/fail, stated now:**

| Check | Pass |
|---|---|
| F lands by t0 + 12 s (rev 6, 3 frames) | ≥ 90 % of crossings (measured run) |
| F sends ≥ 2 non-blank frames (rev 6, D0-FRAME offsets) | ≥ 95 % of crossings; 0 blank frames sent |
| B lands inside the census interior hold (t0 + 180 s) | ≥ 95 % of crossings, clustered ones included |
| B window contains every chain camera the person hit in the first 60 s | ≥ 90 % of entries |
| Entry S lands inside `EGRESS_FACE_UNION_TTL_S` (300 s) | ≥ 95 % |
| No day exceeds the daily call cap or 2 concurrent sequences | 100 % of replayed days |
| Measured daily cost | ≤ §15.5 worst × 1.5 |

Fail on a timing row = change the window or cadence and rerun; fail on cost = drop B to Luna or lower width; fail twice
= park the sibling plan with the failing number recorded. The report goes in
`docs/planning/AUDIT_crossing_vision_d0_sim.md`.

### 15.7 Signal weighting for the census and sightings (rev 5)

Vision is one input among several; it does not replace integration face or person counts. Each signal is good for a
different fact: COUNT (how many), IDENTITY (who), LOCATION (where).

| Signal | Good for | Reliability here | Latency | Failure modes |
|---|---|---|---|---|
| BLE / trackers (`person.*`, Bermuda) | identity + home/away of residents; room for private rooms | high for residents carrying phones; blind to non-residents | seconds-minutes; exit backfill ≤ 600 s | phone left behind, BLE budget, scanner gaps |
| Frigate face (`_2` legs) | identity at a camera | sparse (attach 44 % of egress crossings over 14 d to 11-08) | ~1-5 s | night, angle, no-face, mis-name |
| Protect face (webhook / name back-fill) | identity at a camera | front door only | name back-fills ~1-2 min | async name, single camera |
| Frigate / Protect person count | count at a camera, local, always on | good for presence of a body, weak for groups | ~1 s | ghosts (§1.3 cross-corroboration), occlusion, handoff spikes |
| Egress crossing (transit validator) | count + direction at a door; identity when attached | covers the 3 watched doors | 0-20 s settle | ambiguous direction, double legs |
| Vision fast (F) | provisional count, direction, group | unmeasured (D0-V) | t0 + 5-10 s | refusal, outage, night IR |
| Vision batch (B) | count, direction, group, walking away, re-ID across a chain | unmeasured (D0-V) | t0 + 70-90 s | as F, plus cost cap skips |

How they combine (all inside the existing census owner, no second owner):
1. **Who is home stays BLE-led.** `person_state_for_trust` and the BLE-leads rule are unchanged. Face and vision
   never move a resident home or away.
2. **Identity** comes from face and BLE only (the union, manual §3 rule 4). Vision may only confirm a name already
   attached (`vision_consistent`), never supply one.
3. **How many guests (rev 6, operator: "both vision and Frigate/Protect person counts with deconfliction, until we
   trust vision").** Two estimates are always computed: `guest_cam = max(0, camera_total - |known|)` (today's path,
   `camera_census.py:2533`) and `guest_vis = max(0, vision_ledger - BLE_home_residents)`. Camera counts are NEVER
   dropped while vision is untrusted. Deconfliction, per census evaluation:

   | Case | Condition | Guest count used | Flag |
   |---|---|---|---|
   | A agree | `abs(guest_vis - guest_cam) ≤ CROSSING_VISION_DISAGREE_FLAG_MIN - 1` (modeled 0) | the shared value | `agreement=agree` |
   | B vision higher | `guest_vis > guest_cam` | `guest_cam` (camera stays authoritative while untrusted); `guest_vis` recorded | `vision_higher` (likely occlusion/tailgate the cameras merged) |
   | C camera higher | `guest_cam > guest_vis` | `guest_cam` | `camera_higher` (likely ghost / handoff spike, or vision missed an entry) |
   | D one side missing | vision unhealthy, capped, skipped, or no camera count | whichever exists | `camera_only` / `vision_only`; `vision_only` never raises the guest gate by itself while untrusted |

   While untrusted, the camera count is the value the guest gate reads in every case; vision changes nothing that
   acts, only the recorded agreement. Each case is persisted per crossing with ground truth when BLE/face supply it,
   which is the §15.7a trust data.
4. **No signal silently wins.** Both estimates and the case are recorded on the census result; persistent B or C on
   one camera (≥ `CROSSING_VISION_DISAGREE_PERSIST_N`, rung 1, modeled 5 in 24 h) trips the AnomalyDetector → NM.

### 15.7a When vision may lead (rev 6): a measured criterion, then a reviewed decision

Vision leads the guest count (cases B and C resolve to `guest_vis`) only when ALL hold over ≥ 100 crossings with
ground truth and ≥ 7 days (rev 7, operator 2026-11-12: "as long as it includes identified people visual census vs the
BLE signal ... get to trust faster"). The main accuracy stream is RESIDENT crossings: every crossing where BLE/tracker
says which residents moved gives an exact expected head count for vision to match, so at ~14 crossings/day the bar is
reachable in about a week. Because residents-only truth tests counting but not the guest case, the set must also
include ≥ 10 crossings with a non-resident present (deliveries/visitors from Frigate events or operator-labelled
guest days); false-guest rate is scored on the resident-only crossings (vision must report 0 guests). Sources: D0-V
then organic records:
- vision exact guest-count match ≥ 95 % overall, ≥ 90 % at night, per watched door;
- in disagreement cases B and C, vision is the side matching ground truth ≥ 80 % of the time (it must win the
  disagreements, not just the easy agreements);
- false guest (vision says ≥ 1 guest, none present) ≤ 2 %;
- vision healthy (not case D) on ≥ 95 % of crossings.
Meeting the numbers does not flip anything: the switch is `CROSSING_VISION_COUNT_AUTHORITY` (`evidence_only` →
`vision_led`), changed only in a reviewed cycle (Tier 2-DB minimum, house-state rule) with the numbers attached. Under
`vision_led` camera counts stay computed and case flags stay recorded; any criterion falling below its bar over a
rolling 14 days trips NM and recommends reverting the knob.

Reuse, not new structure: `CensusZoneResult` already carries `source_agreement`, `degraded_mode` and
`active_platforms` (`camera_census.py:305-321`). The sibling plan adds `vision` to `active_platforms` when vision
contributed, records a vision-vs-camera agreement value using the existing `CENSUS_AGREEMENT_*` vocabulary, and uses
`degraded_mode` semantics for "camera-only". The persistent-disagreement trip-wire goes to the AnomalyDetector wired
to NM (CLAUDE.md No-Soak), not a calendar. The guest gate keeps reading the census's `unidentified_count`; what
changes, only after the D0-V census gate passes, is which estimate feeds it.

Knob sketch for the sibling plan: `CROSSING_VISION_HEALTH_MAX_AGE_S` (rung 1, how stale the last good vision call
may be before fallback), `CROSSING_VISION_COUNT_AUTHORITY` (rung 2 select: `evidence_only` default / `vision_led`),
`CROSSING_VISION_DISAGREE_FLAG_MIN` (rung 1, persons of disagreement before flagging), rev 6
`CROSSING_VISION_DISAGREE_PERSIST_N` (rung 1). `CROSSING_VISION_COUNT_AUTHORITY` stays rung 2 but rev 6 adds: changing
it to `vision_led` requires the §15.7a numbers and a reviewed cycle.

### 15.8 Coverage model (rev 5)

The operator reports 20+ cameras watching outside to inside on every approach. Coverage is therefore modeled as
CAMERA CHAINS, not single doors: each approach is an ordered list (exterior approach camera(s) → door camera →
interior landing camera(s)). The sibling plan builds chains from existing adjacency, not a new map:
`ExteriorTrackLinker.adjacent_cameras` for the outside legs and `transit_validator._get_interior_cameras_near` (`:2203`, which reads
the operator-set `door_interior_neighbours` option, `config_flow.py:4861`) for the inside legs (`adjacent_cameras` at `exterior_track_linker.py:919`). D0-SIM measures, per approach, whether the person actually hit each
chain camera and how long each hop took; that is the evidence for the B-stage chain choice.

Interior cameras join the enrichment purview (under the §15.3 item 7 toggle) for two reasons: entry chains end
indoors, and the periodic interior head count is the ledger's independent check. Head count = one Luna call every
`CROSSING_VISION_HEADCOUNT_INTERVAL_S` (modeled 1800 s) while the house is occupied, one frame per interior camera,
counting people; it is compared with the ledger and with Frigate/Protect counts per §15.7, never written over them.

D0-V's coverage score (BLE-known crossings that pass a watched door) becomes per-chain under rev 5: a crossing is
covered when it hits at least the door camera of some chain.

---

## 16. Rev 3 changelog

| Change | Why | Where |
|---|---|---|
| Reframed and renamed: person sightings (identity at a place), file `PLANNING_person_sighting_layer.md`, signal `SIGNAL_PERSON_SIGHTING`, payload `PersonSighting`, module `person_sighting.py`; card id suggested PERSON-SIGHTING-LAYER-1 | Operator: not a face-only one-off; face is one provenance | title, header, §3 |
| One identity model: facts F1-F5 with single owners, relations, shared vocabulary, no-duplicates checklist | Operator: harmonize with egress and census | §2A |
| Primitive-reuse table with file:line and REUSE / EXTEND / NEW | Operator: reuse primitives | §1.2a |
| `provenance` field; `IDENTITY_PROVENANCE_*` constants name the existing literals (no value change) | One provenance enum instead of three literal copies | §1.2a, §3.1 |
| Interior confidence `None` -> `CONFIDENCE_MEDIUM` (0.6) | One confidence ladder; a single recognizer is 0.6 in the egress model | §3.1 |
| Boot guard: `FACE_SIGHTING_BOOT_EXCLUDE_S` withdrawn; reuse `edge_in_window` + `PERIMETER_EGRESS_ARRIVAL_BOOT_EXCLUDE_S` | No duplicate boot guard | §6 |
| Dedup key = resolver `physical_camera_id` for interior AND egress; `base_stem` concept split named, unchanged | One physical-camera identity | §1.2a |
| Found `TransitValidator._camera_sightings` / `get_last_camera_sighting` (prior art), its consumer phone-left-behind dead on the camera leg live; not written this cycle; card PHONE-LEFT-BEHIND-CAMERA-LEG-1 | Writing it would change house state | §1.2a, §8, §12 |
| INV-ACCESS reworded to "camera-derived identity" | Covers vision with no new invariant | §2 |
| AI vision: crossing snapshot sequence + batched analysis as `vision` provenance, design + D0-V; sibling plan only if D0-V passes; card CROSSING-VISION-SEQUENCE-1 | Operator: be more ambitious; time-lapse not live | §15, §7 P6, §12 |
| New tests: interior confidence, guest slug, shared boot helper, egress provenance copy, provenance const values | Pin the harmonization | D1 |

Unchanged from rev 2: the arrival rule (D2), consumer policy (D3), trip-wires (D4), retirement (D5), real-HA test (D6),
parked D7, mutation drills M1-M15, live table L1-L9, Tier 3.

---

## 17. Rev 4 changelog (review `PLAN_person_sighting_layer_review_rev3.md`)

| Finding | Resolution | Where |
|---|---|---|
| H1 face-only egress attach writes no `provenance`; plain copy drops every face-only sighting | Explicit `provenance: IDENTITY_PROVENANCE_FACE` at `transit_validator.py:1908`; bus key read with `.get(..., FACE)`; real-path test `test_face_only_real_path_provenance_face`; drill M16 | §1.2a, §2 INV-PROVENANCE, §3.2 (c), D1, drills, L1b |
| M1 `physical_camera_id` depends on the input leg | One helper `canonical_camera_key(fusion)` = min device id over the full source set, interior and egress; Protect-pick + Frigate-egress test; drill M17 | §1.2a, §2A checklist, §3.1, D1, drills |
| M2 Garage A `room_cameras` is `[]` | Unresolved reason `room_cameras_empty`; D1/P1/L1 restated; operator action §13.3 (set room cameras, or pick the camera's own sensor); fused-pick test kept | §3.2, §7 P1/P2, D1, L1, §13.3 |
| M3 egress has no boot guard to inherit | Same `ts < boot_end` drop on source (c); egress boot test; drill M18 | §3.2 Filters, §6, D1, drills, L3 |
| M4 "agree by construction" is false | Named concept split (seen vs counted); `person_state_at_emit` + `census_would_veto` stamped on the sighting | §2A, §3.1, D1 |
| M5 access gates match the literal `camera_face` | `CAMERA_DERIVED_ARRIVAL_SOURCES` (rung 1), membership in lock regime `:1017` and security gate; unknown sources fail closed; test + drill M19 | §2 INV-ACCESS, §3.4, §6, D3, drills |
| M6 `_arrival_departure_notify` missing | Added to F3 readers, no-duplicates checklist, §3.4 note, §8; FACE-SIGHTING-CONSUMERS-1 extends it; D5 corrects manual §5.5 | §2A, §3.4, §8, §12, D5 |
| L1 INV-PROVENANCE vs §15.3 | Reworded: face evidence, or vision under the sibling plan's rules | §2 |
| L2 provenance literal list | Added `camera_census.py:4772` and defaults `transit_validator.py:2087`, `camera_census.py:4197` | §1.2a |
| L3 `edge_in_window` is not a boot guard | Explicit `ts < boot_end` check; behavioural test replaces the call-was-made test | §1.2a, §2A, §6, D1 |
| L4 "unmapped" undefined | Membership in `_get_tracked_person_slugs()`; `""` unmapped; test | §1.2a, D1 |
| L5 census ring vs INV-NOOP | Ring gated on `FACE_SIGHTING_ENABLED`; INV-NOOP lists the provenance write | §2, §3.5 |
| L6 §15 event id source | `FrigateEventIngress` `frigate_ingress.py:147` / `:175` | §15.3 |
| L7 D7 prior art | Extend `door_interior_neighbours` before minting `INTERIOR_CAMERA_ADJACENCY` | D7 |
| Operator addition (vision) | §15.3 items 8-9: progressive provisional/final analysis; door count ledger as census EVIDENCE (census stays owner), error sources and reconciliation named; D0-V scores both-direction count accuracy + coverage; census-from-vision a gated decision | §15.3, §15.4 |
| Cite drift | `register_egress_face` `:4139`, `_prune_snapshot_dir` `:4102` | §1.2a |

Unchanged from rev 3: the arrival rule (D2), the security corroboration rule, trip-wire design (D4), retirement
(D5 scope), real-HA test (D6), §15 vision design, Tier 3. Status: plan only; operator APPROVE next.

---

## 18. Rev 5 changelog (operator direction 2026-11-12)

| Change | Why | Where |
|---|---|---|
| llmvision model plumbing read from source: model string passed through; no `detail` field; `target_width` controls size; temperature/top_p caveat; no `gpt-6*` reasoning entry. Candidate ids and prices from OpenAI's models page | Operator: use OpenAI GPT-6 lineup; verify llmvision accepts it | §15.1 |
| Timing design: F (2 × 768 px, Luna, t0 + 5/10 s), B (≤ 12 × 1024 px over 60 s along the chain, Sol, t0 + 70/90 s), S (t0 + 120 s entries, ≤ 600 s exits); clustering and concurrency from measured data; per-day call/token/cost envelope from 14 days of crossings | Operator: focus on the technical timing | §15.5 |
| D0-SIM: offline replay, modeled then measured, pass/fail table up front | Operator: simulate timings and sizes | §15.6 |
| Signal-weighting model: BLE leads who-is-home; face/BLE give identity; vision leads non-resident count when healthy, Frigate/Protect counts are the fallback marked camera-only; disagreements recorded and flagged; reuses `CensusZoneResult` fields, no second owner | Operator: integration face counts still used; weigh signals | §15.7 |
| Coverage as camera chains; interior cameras in purview; periodic interior head count | Operator: 20+ cameras on every approach | §15.8, §15.3 item 7 |
| Non-resident framing of the ledger; empty-house reset, head count, exit-chain matching as checks | Operator: residents solved, guests are the problem | §15.3 item 9 |
| D0-V: model step 0, fast vs batch accuracy, entries/exits, ledger return to zero, measured tokens via direct API usage, latency per stage, agreement with camera counts; go-rule additions | Queued points folded | §15.4 |

Unchanged: INV-ACCESS (vision is never access-class), all rev 4 fixes, D1-D7, drills, live table, Tier 3. This cycle
still builds nothing in §15; the sibling plan (CROSSING-VISION-SEQUENCE-1) is gated on D0-SIM and D0-V.

---

## 19. Rev 6 changelog (operator 2026-11-12)

| Change | Why | Where |
|---|---|---|
| Guest count fuses vision and Frigate/Protect counts with a 4-case deconfliction table (agree / vision higher / camera higher / one side missing); camera count is what the guest gate reads while vision is untrusted; every case recorded and persistent disagreement trips NM | Operator: "both vision and frigate/protect person counts with deconfliction, until we trust vision" | §15.7 items 3-4, §15.3 item 9 |
| Measurable trust criterion (≥ 14 d, ≥ 100 ground-truth crossings, 95 % / 90 % night exact, wins ≥ 80 % of disagreements, false guest ≤ 2 %, healthy ≥ 95 %); switch is a reviewed change of `CROSSING_VISION_COUNT_AUTHORITY`, auto-revert recommendation via NM | Operator: until we trust vision | §15.7a, §15.4 per-case scoring |
| Fast sample = 3 frames, timed to Frigate detection updates (best snapshot + next two person-box updates), not wall-clock offsets | Operator: more frames, maybe 3, well timed | §15.5 F row, §15.3 item 8 |
| Blank-frame guard reusing `FrigateEventIngress`, the Frigate snapshot path and the perimeter snapshot dir; `skipped_blank` counted and trip-wired | Operator: no blanks, need a guard | §15.5a |
| D0-FRAME offline experiment: blank rate by anchor/offset per camera, day vs night, chosen 3-frame set, thresholds stated | Operator: some experiments | §15.4a |
| Timing F t0 + 6 / 12 s; F tokens ~1,675 in; F cost $0.004/day mean ($0.007 worst), total unchanged at ~$9/month; D0-SIM F row + non-blank row | 3 frames | §15.5, §15.6 |

Unchanged: this cycle builds nothing in §15; D1-D7, invariants, drills, Tier 3. Sibling plan gated on D0-FRAME,
D0-SIM and D0-V.

---

## 20. Portability (rev 8; rev 9)

Rule (memory `feedback_portability_imperative`): everything house-specific is config or learned, and every missing
piece removes a capability without errors. Inventory for this plan:

| House-specific input | Where it comes from | Missing -> capability lost (no error) |
|---|---|---|
| Camera picks per house zone | `zone_cameras` (ZM entry, rung 2), resolved by registry/device (`resolve_pick_to_fusions`) | no picks -> no interior sightings; `face_sighting_picks_resolved = 0`; trip-wire silent (denominator 0) |
| Egress cameras, door groups, interior neighbours | existing integration options (`CONF_DOOR_INTERIOR_NEIGHBOURS`, door groups) | none -> no crossings -> no egress sightings, no candidates |
| Path map (D7) | file `interior_paths.json` (operator), const `INTERIOR_PATH_MAP_FALLBACK` (this house's ratified map; inert elsewhere because its entity ids do not resolve) | no valid source -> `path_map_source: none`, G2 `skipped` per door, candidates need 0.9 non-synthetic |
| Exterior adjacency | `EXTERIOR_ADJACENCY_GRAPH` code constant, with the operator seam file being wired by EXTERIOR-SEAM-FILE-LOADER-1 | D7 never reads the constant; approach nodes come from D7's own file |
| Transit checkpoint areas (completeness L1) | `DEFAULT_TRANSIT_CHECKPOINT_AREAS` (`const.py:3270-3276`: master_hallway, entry_way, garage_hallway, upstairs_hallway, stairs), house area ids as a code default; they feed the interior camera set direction and path scoring read | another house: no matching areas -> empty interior set -> crossings resolve `ambiguous`; no error. Noted, not changed this cycle |
| `CAMERA_COVERED_ROOMS = {"Study A"}` (`const.py:1573`) | outside this surface | noted only |
| Camera integrations | per-integration capability adapters in `CameraResolver` | an integration without face names yields person legs only: crossings and direction work, identity does not |
| Face recognition | Frigate face sensors / MQTT latch (Protect bridge parked) | no face source -> no sightings, no candidates; D4 trip-wire silent; egress identity from BLE only |
| BLE / Bermuda | optional (`person_coordinator`) | no BLE -> no BLE legs; confirmation leg (b) never fires; (a) and (c) still can |
| GPS | the person's own GPS `device_tracker`s (registry/attributes, never names) | none -> G3 `skipped`, confirmation leg (c) never fires |
| Vision provider / model | llmvision entry + model as settings (§15) | none -> §15 off |
| Doors | config only, never names | n/a |

No code path builds a CAMERA entity id from a slug or a name (manual §1.1). Scope note (completeness L1): `person.<slug>`
reads (the existing veto `:1842`, G3, rule 5, confirmation leg (a)) are round-trips of tracked persons from
`_get_tracked_person_slugs()`, not built camera names; they stay. No house name appears in code except the two
fallback constants above, both inert on another install.

**Acceptance tests (D6 extends the real-hass test with these install shapes):**
- `test_portability_shapes.py::test_protect_only_house`: Protect person sensors only (no Frigate, no face names).
  Crossings and direction resolve; zero sightings; zero candidates; `face_sighting_picks_unresolved` reasons are
  `no_face_name_source`; no exception, no ERROR log; trip-wire silent.
- `::test_person_sensor_no_face_house`: Reolink/Amcrest-style person sensors, BLE on. Egress identity from BLE only;
  §2B never reached (no face path); arrivals only from geofence/ble.
- `::test_camera_less_house` (Wigton-like): no cameras, no egress, BLE optional. The sighting producer registers no
  listeners, D7 reports `path_map_source: none`, D8 is inert, every diagnostic reads zero or `skipped`, setup
  completes, no ERROR.
- `::test_no_gps_no_path_map`: face-only house with no GPS and no path map; candidates require 0.9 non-synthetic and
  can be confirmed only by the tracker leg.
- `::test_foreign_house_const_map_inert` (rev 9): the const fallback's entity ids absent from the registry -> no map,
  no ERROR, provenance `none`.

## 21. Rev 8 changelog (operator 2026-11-12)

| Change | Why | Where |
|---|---|---|
| Egress identity rule made direction-aware: entry + `not_home` = arrival candidate (name kept), exit + `home` = departure candidate; exit + `not_home` still vetoed; BLE branches unchanged | Operator: "Who made this rule? ... It should do both". The veto was copied from the census "who is home now" guard without considering direction | §2B.1-2B.2, §0 |
| Misrecognition protection replaced by G1 face confidence (>= 0.75, not synthetic-only), G2 path corroboration, G3 GPS plausibility, G4 existing abstain; access consumers keep the independent-second-signal rule | The veto's one real job (a resident's face on a stranger) needs an explicit guard | §2B.3, INV-CANDIDATE |
| Per-consumer audit: census union does NOT take candidates (census veto stays, INV-CENSUS-HOME); displays name more (right); notification names now only when path-corroborated, else anonymous + named follow-up; perimeter D10.5 treats a candidate like a synthetic hit; phone-left-behind and exit backfill unaffected | Every reader of the vetoed outcome and of egress `person_id` checked | §2B.5 |
| Egress arrivals restored as `camera_egress` through the one D2 site, D0-gated; added to `CAMERA_DERIVED_ARRIVAL_SOURCES`; H1 reconciled (it was the veto's artefact) | FACE-EGRESS-ARRIVAL-1 revival trigger fired | §2B.6, §3.3 rule 2, §12 |
| `path_score` from the operator's ordered camera path; D7 reframed from parked to prerequisite: path map as config, learned default from recorder hop lags, operator fixture as override and validator | Operator: "a direction detector, which the path I outlined should improve" | §2B.4, D7, D0-P4 |
| D8 deliverable with discriminating tests and drills M20-M25; live L10-L13 | Sprint contract | §9 |
| D0-P7: count vetoed would-be arrivals and how often the tracker flips home within N min (true arrival vs misrecognition), guard yield, phone-first share; go rule | Measure-first | §7 |
| Portability section and three install-shape tests | Operator: everything house-specific is config or learned | §20 |
| Knobs for every new number (rung 1 switches and guards, rung 2 path map) | Numbers get knobs | §6 |
| Tier re-checked: Tier 3, wider D surface | Egress decision logic + access-guarded signal + house-state adjacency | §11 |

Unchanged: INV-ACCESS, INV-PRODUCER, INV-PROVENANCE, D1/D3-D6, §15 vision design. Status at rev 8: plan only; plan reviews
(completeness + build-prediction) of rev 8 then operator APPROVE (approved 2026-11-12; rev 9 applies both reviews, §22).

## 22. Rev 9 changelog (both rev-8 plan reviews; operator APPROVED 2026-11-12)

Build-prediction review (`PLAN_person_sighting_layer_review_rev8_buildprediction.md`):

| Finding | Resolution | Where |
|---|---|---|
| H1 HVAC drops every `camera_egress` | D8a: default, selector, one-shot migration of the live CM option (append when `camera_face` is listed); HVAC logic unchanged; tests + drill M28 + L15 | §2B.5, §2B.6, §3.4, D8a, L15 |
| H2 path_score cannot see the path at decision time | Decision time = existing resolution instant (+45 s), unchanged; named sources (existing interior lists + `_path_events` for other nodes, subscribed only when switch on and a map is loaded, torn down); explicit horizon; P7 runs the same pure scorer | §2B.4, §7 P7, D7, drill M26 |
| H3 extending `door_interior_neighbours` breaks it | Separate file `interior_paths.json` + `interior_paths.py`; that option and its four readers untouched; door key = live door group (stem when groups unset) | §1.2b, D7, INV-ACCESS note, drill M31 |
| M1 rule 1 blocks the egress branch | Rule 1 split by branch; egress-on with direction-aware-off is inert and tested | §3.3, §2B.6 |
| M2 learned map storage / timing / partial maps | Learned map is offline only: a diff report, never options, never runtime, never a trust gate | D7, §7 P4 |
| M3 G3 data source | Freshest GPS `device_tracker` by its own `last_updated`; proximity sensors not used; implied-speed rule; P7 reports false-fails by age bucket | §2B.3, §7 P7 |
| M4 kill switch not byte-identical | Switch off: new keys absent, no subscriptions, no scoring, no waiter; golden compares full bus dict minus `identity_provenance`; fixture includes entry/exit x home/not_home/zone (+ entry unknown) | INV-NOOP, D8 tests |
| M5 cameras in two stages | DAG: nodes are cameras, edge type carries the stage; pairs within one door group's egress cameras never score; front-door DAG test | §2B.4, D7 |
| M6 follow-up waiter unspecified | Poll 5 s, one per slug, supersession, cap, teardown cancel, window 600 s, edges strictly after the crossing, stale-source edges excluded | §2B.3a, drill M27 |
| L1 hollow perimeter test | Test uses a 0.9 non-synthetic candidate; with provisional candidates perimeter needs no change | §2B.5, D8 tests |
| L2 G2 `skipped` drill | Drill M21b | drills |
| L3 M23 membership not separately load-bearing | Recorded on M23 | drills |
| L4 role channel | 4-tuple with frozen `EgressRoleResult`, None on every early return | §2B.2 |

Completeness review (`PLAN_person_sighting_layer_review_rev8_completeness.md`):

| Finding | Resolution | Where |
|---|---|---|
| H1 HVAC drops `camera_egress` | Same as build H1 | as above |
| H2 D7 storage widens access corroboration and changes direction | Same as build H3; test pins `door_entry_areas`, `_near_areas`, direction identical with a map loaded | D7, INV-ACCESS |
| H3 guards do not stop the 10-24 case | Honest table of what discriminates; candidates PROVISIONAL (no name anywhere until a non-face edge after the crossing); G3 implied speed (catches stale-far fixes); anonymous-first for every candidate; P7 reports guard yield on 10-24 | §2B.3, §2B.3a, INV-PROVISIONAL |
| M1 named zones misdescribed | 2B.1 corrected (veto is `== "not_home"`); zone deltas declared; zone rows in golden + tests | §2B.1, §2B.2, INV-NOOP |
| M2 attach rate / stale last_attach / role not persisted | `EGRESS_OUTCOMES_ATTACHED`; candidate never reads `last_attach`; DB `person_id` meaning documented (NULL until confirmed), no schema change | §2B.5, D8 |
| M3 rule 1 coupling | Same as build M1 | §3.3 |
| M4 path_score source and time | Same as build H2 | §2B.4 |
| M5 fixture vs live egress config | Reconciliation table; doors without a map `skipped` per door; gaps are operator questions | D7, §13.4 |
| M6 stale sections | §5 perimeter paragraph and producer list, §10 egress row, §6 / INV-ACCESS camera set, learned-map pricing all rewritten | §5, §6, §10, §2 |
| M7 P7 data thin | D8a persists the outcome log (vetoed slug included); gate needs >= 28 days and a Wilson bound with n >= 10 | D8a, §7 P7 |
| L1 portability | Transit checkpoint areas and `CAMERA_COVERED_ROOMS` listed; the "no entity id from a slug" sentence scoped to camera entities | §20 |
| L2 synthetic below 0.9 | Any contributing synthetic leg | §2B.3 |
| L3 PATH_MIN 0 | 0 = G2 not evaluated | §2B.3, §6 |
| L4 role entry reset | Fresh per-call result, no stash | §2B.2 |
| L5 presence doc line 88 | Read; the SUPERSEDED note (b70e3a2f) is why D7 must not touch the neighbour option | header, D7 |

Operator direction applied (2026-11-12): D7 = own validated file + const fallback on the exterior-seam mechanism, a DAG,
reconciled with live egress config, gaps as questions, learned map offline diff only; HVAC accepts `camera_egress` with
migration; honest mislabel guard with provisional candidates and a reachable "Someone arrived" path, GPS freshness from
the tracker's own timestamp, access unchanged; path_score event sources, decision time and identical P7 horizon; every
MEDIUM and LOW; P7 outcome log persisted.

Unchanged: INV-ACCESS rule, INV-PRODUCER, D1-D6 (except source (c') and the `identity_role` payload field), §15 vision
design, Tier 3. Status at rev 9: superseded by rev 10 (§23).

## 23. Rev 10 changelog (both rev-9 plan reviews; orchestrator phase split; operator camera-map answers)

**Structure.** Two phases (§0A). Phase 1 = D0, D8a, D3, D1, D4, D2 (interior), D5, D6, D7, in dependency order. Phase 2
= §2B, D8b, HVAC `camera_egress`, gated on >= 28 days of D8a log + operator label review + the P7 go rules. Phase 2's
design is kept with every finding fixed (§2B.7).

Build-prediction review (`..._rev9_buildprediction.md`):

| Finding | Resolution | Where |
|---|---|---|
| H1 DB timestamp is INSERT time | Row id: `log_entry_exit_event` returns `lastrowid`; backfill by id, no bracket | §1.2c, §2B.3a, §2B.7 (P2) |
| H2 waiter before INSERT | Waiter created after the INSERT returns; retry until the row is named; follow-up only after | §2B.3a, tests, M38 (P2) |
| H3 M27 hollow | Two tests with the tracker `not_home` (Bermuda / GPS before t_E); M27 re-pointed; verify bullet rewritten | D8b, drills (P2) |
| M1 build-order inversions | D7 after D1; D2 egress branch + its tests in D8b; access test in D3 | §0A, D3, D7, D8 |
| M2 loader is a method | Extract `load_validated_json`; four outcomes; sha of installed source; seam tests unchanged | §1.2c, D7, M42 |
| M3 DAO LIMIT / camera | Superseded by row id | §2B.3a |
| M4 log scope / task | One record per call, every path, emitted from `_resolve_direction`; `_outcome_log_tasks` + teardown gather | D8a, INV-LOG, M36 |
| M5 waiter lifecycle | Teardown rows, `_confirm_tasks`, unsub only in waiter, supersession log, `LOCK_ARRIVAL_STALE_SOURCE_S` | §2B.3a, §2B.7 |
| M6 migration wiring / data key | Merged view, write options, setup wiring test, data-only test, M28b | §2B.7 (P2) |
| L1 G3 timestamp | Kept `last_updated` with reason (tracker state is a zone; `last_changed` fails open); P7 reports both | §2B.7 |
| L2 boot ordering | First D7 load at resolver-ready; `pending` provenance; test | D7 |
| L3 G2 fixture | Two live legs | §2B.7 |
| L4 evict key | `person_id` = slug for `departure_candidate` | §2B.7 |

Completeness review (`..._rev9_completeness.md`):

| Finding | Resolution | Where |
|---|---|---|
| H1 wrong-person confirmation | GPS leg = home-zone fix + approach; abstain on any intervening crossing or a later candidate; per-leg P7 errors; tests | §2B.3a, §2B.7, M39, M40 (P2) |
| H2 backfill bracket | Row id (as build H1); test drives the 45 s scheduled path | §2B.7 |
| M1 access gates after emitter | Set + both membership gates in D3, Phase 1 step 3, before any `camera_egress` emitter | §0A, D3 |
| M2 name switch | Fresh-read before DB write, signal and sighting; test; M41 | §2B.3a (P2) |
| M3 `last_attach` display | Candidate branches return before any write; consumer added to INV-PROVISIONAL; test; M35 | §2B.7 (P2) |
| M4 veto-path side effects | Pure tier helper, one derivation; golden incl. vetoed 0.75 and synthetic 0.9 | D8a, INV-NOOP Phase 1, M37 |
| M5 BLE leg no HVAC gain | `arrival_already_dispatched` skip; P7 counts GPS leads only; §0 restated | §0, §2B.6, §2B.7, §7 |
| M6 P7 data retention | Weekly labeller + operator review inside 7 days; URA-DB sources named; Wilson n = reviewed only | §7, D8a, §13.6 |
| L1 `hvac.py:881`, help text | Phase 2 HVAC change | §1.2c, §2B.7 |
| L2 HVAC doc in the HVAC commit | Phase 2 HVAC commit; Phase 1 D5 fixes cites | §2B.7, §11 |
| L3 migration reseed | EC-pin pattern; one-time write named in INV-NOOP | §2B.7 |
| L4 loader shipped | §1.2c, D7 | |
| L5 skip label | `home` | §2B.6, §2B.7 |
| L6 log scope / dedup | Every path; `dedup_source_ref=False` | D8a |
| L7 exit horizons | Same per-list horizons in P7 | §2B.7 |
| L8 map re-validation | Options change + registry update | §2B.7 |
| L9 PATH_MIN 0 | Stated on the knob | §6 |
| L10 slug -> PersonCoordinator key | Registry/tracked-person mapping | §2B.3a |
| L11 zone union delta | Declared | §2B.7 |
| Adjacent `LastPersonEntrySensor` unsub | Card candidate LAST-PERSON-ENTRY-UNSUB-1 (pre-existing; Phase 2 takes the name only when its last entry is the confirmed row) | §12 note |

Operator camera-map answers: Doorbell Lite egress (garage), Foyer interior witness, "Entry way" = Front door aerial
(+ G6 Entry, two views of one crossing), Sonoff window -> aerial + G6, Game room = `playroom`. Applied in D7; §13.4
keeps Q5 (Garage B) and Q6 (patio).

Doc contradictions found (code wins, reported): HVAC state of play header still marks HVAC-PRECOOL-STANDDOWN "NOT
deployed" (shipped v5.108.14); manual §4.5 seam-file paragraph says "NOT deployed" (shipped v5.108.15). Fixed by D5's
doc commit if not fixed first.

Status: rev 10. Phase 1 needs one adversarial plan review of the rev-10 deltas (§0A, D3, D7, D8a, INV-LOG) before
build dispatch; Phase 2 gets its own two reviews at its gate.
