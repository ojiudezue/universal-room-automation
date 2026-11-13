# PLANNING: person sightings — identity at a place, one model with crossings and the census

Card: **FACE-ARRIVAL-REBUILD-1** (tier 3, thread identity); **suggested new id PERSON-SIGHTING-LAYER-1** (the
orchestrator renames the card; this planner did not edit the kanban yaml). Related: ZONE-CAMERA-DISCOVERY-DEVICE-AREA-1,
PERSON-PROFILE-PREFERENCES-1, FRIGATE-DOOR-FACE-TUNING-1, EGRESS-IDENTITY-JOIN-GAP-1 (egress producer, shipped),
HVAC-PRECOOL-STANDDOWN-WHEN-COOL-1 (sibling). File renamed with `git mv` from `PLANNING_face_arrival_rebuild.md`.

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

- **Egress produces sightings only, never arrivals (H1).** `transit_validator.py:1840-1854` vetoes an egress
  identity whenever `person.<slug>` reads `not_home`, so every named egress entry is someone the tracker already
  shows home. An arrival from it would be a post-arrival duplicate.
- **Interior class (iii) is dropped (M7).** A face after the phone's home edge adds nothing; geofence/ble already
  dispatched.
- What remains as an arrival is interior class (i): a face seen before the phone arrives. D0-P3 gates it. **The
  likely outcome is sightings only and ~0 live `camera_face` arrivals until D0 shows otherwise.** That is a good
  result, not a failure:
  - the durable value is the sighting signal plus its last-sighting accessor, which future consumers read;
  - D3's security gate is worth shipping on its own, because it closes a latent alarm-suppression sink;
  - the dead v3.19 path and its producer-disabling flag go away.

**Parked, with revival triggers:** the interior track sequence (§9 D7, D0-P4 decides; default PARK); any
presence/census fusion of sightings; egress-derived arrivals (revival trigger: the egress not_home veto changes,
or D0-P2 shows named egress entries for not-home persons ≥ 1 per week).

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

### 1.3 Code surveyed end to end
`presence.py` 5040-5700, 2308-2410, 1350-1375, 640-660, 1025-1035; `hvac.py` 1425-1440, 1507-1514, 7212-7290;
`security.py` 249-330, 660-730, 1580-1600, 2381-2430; `security_lock_regime.py` 996-1060, 1364-1460;
`music_following.py` 549-585; `camera_census.py` 349-372, 450-540, 3265-3290, 3903-3960, 5348-5605;
`transit_validator.py` 1640-1790, 1835-1860, 1990-2095; `arrival_edges.py` 1-245; `binary_sensor.py` 1520-1560;
`camera_resolver.py` 185-210, 690-740; `const.py` 2660-2690, 3320-3380, 3495-3512.

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
- **F5 from F4 only through D2** (interior class (i), D0-gated). Egress sightings never become arrivals (rev 2 H1).
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

## 2. Falsifiable invariants (reviewer D breaks these)

**INV-ACCESS (load-bearing; rev 3 widens "face-derived" to "camera-derived identity", so a future `vision`
provenance is covered with no new invariant).** In any reachable path, a camera-derived identity input (any
`PersonSighting`, whatever its provenance, or a `SIGNAL_PERSON_ARRIVING` whose `source` is in
`CAMERA_DERIVED_ARRIVAL_SOURCES`) can never,
on its own, cause:
garage-lockout release (`SecurityLockRegime._release`), away-lock unlock (`_away_release`), an expected-arrival entry
(`SanctionChecker.add_expected_arrival`, `security.py:257`, consumed person-agnostically at `:302`), or a security
disarm (`SecurityCoordinator.handle_disarm`, `security.py:2472`).

- "Camera-derived input" = a `PersonSighting`, or a `SIGNAL_PERSON_ARRIVING` whose `source` is a member of
  `CAMERA_DERIVED_ARRIVAL_SOURCES` (rung-1 frozenset in `const.py`, today `{"camera_face"}`; a future `camera_vision` /
  `interior_track` source is added there, once). Rev 4 (M5): the lock regime (`security_lock_regime.py:1017`, today a
  literal `== "camera_face"`) and the security gate (§3.4) both test membership in this set. A source string that is
  in neither the set nor the known non-camera set (`geofence`, `ble`) is treated as camera-derived (fail closed):
  pinned by `test_unknown_arrival_source_requires_corroboration`.
- Such an action needs an independent non-face arrival edge for the SAME person per
  `arrival_edges.nonface_arrival_source`, within `PERIMETER_EGRESS_FACE_NONFACE_WINDOW_S` (120 s), outside the boot
  exclusion, **as judged by the lock regime's `face_input_corroborated`**. No lock regime (None, torn down, setup
  raised) = not corroborated = reject.
- Falsifier: any legal config + state where a face input reaches one of those four sinks without that edge. Configs
  include alias set/unset, `security_on_arrival_add_expected` True, both lock switches ON, window 0, lock regime
  None, egress `identity_confidence` 0.9 with a synthetic leg, and an HA restart (restored face sensors).
- **Scope:** the pre-existing path "camera body -> census count -> `has_people` -> AWAY -> ARRIVING
  (`presence.py:1367-1369`) -> lock release / auto-follow disarm" is body evidence, not a name. Not widened (no
  sighting feeds census or inference, §8). D confirms "not widened"; a NAMED face changing that path's outcome
  where a nameless body would not is a finding. The path itself is carded (§12).

**INV-PRODUCER (fire-check).** The sighting producer is never disabled, filtered or narrowed to protect a consumer.
No constant or branch in the producer reads a consumer's identity or action class.
`FACE_SOURCE_PRESENCE_ARRIVAL_DISAMBIGUATED` is retired (KEEP + DOCUMENT, no reader). Producer filters are about
evidence quality only (§3.2). Falsifier: a recognised resident face on any resolved pick, including a `_N` person
sensor and the URA fused Garage A pick, that produces no `SIGNAL_PERSON_SIGHTING` while `face_recognition_enabled`,
`FACE_SIGHTING_ENABLED`, outside the boot exclusion and not `_face_suppressed_now()`.

**INV-PROVENANCE (new, F2; rev 4 L1).** A `PersonSighting` exists only for real face evidence, or for vision evidence
under the sibling plan's rules (§15.3 item 5, which amends this invariant only when that plan ships). An egress
identity whose provenance is `ble` never becomes a sighting. A face-only egress identity always does (rev 4, H1: the
face-only attach writes `provenance: face` explicitly). Falsifier: an egress event with `identity_provenance == "ble"`
that yields a sighting, OR a face-only egress crossing (real `_resolve_egress_face_identity` path, no BLE leg) whose
bus event lacks `identity_provenance == "face"`.

**INV-NOOP.** With `FACE_SIGHTING_ENABLED = False`, the four `SIGNAL_PERSON_ARRIVING` consumers see exactly the
dispatches they see on develop today (zero `camera_face`), no new listener or census hook is registered, and the
only producer-side changes outside presence are the additive egress bus key and the explicit face provenance write
(both value-identical for existing readers). Rev 4 (L5): the census post-sentinel ring (§3.5) is gated on
`FACE_SIGHTING_ENABLED`; with it False the ring is not created or appended.

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

1. `FACE_SIGHTING_ENABLED` and `FACE_ARRIVAL_INTERIOR_ENABLED` (D0-gated, default False);
2. `sighting_source == "interior_pick"` (**egress never arrives**, H1);
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

Skip reasons are counted in `face_arrival_skips_by_reason` (`disabled`, `egress`, `observation_mode`, `boot`,
`home`, `phone_already_home`, `unknown_state`, `debounce`).

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
| `hvac._handle_person_arriving` `:7212` | comfort | Face alone OK (existing `pre_arrival_sources`). Interior class (i) only reaches it. | None to logic. Episode guard `pre_arrival_spent` bounds repeats. |
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

Out of scope, named (F10): perimeter D10.5 face de-escalation (a suppression sink at ≥ 0.9) listens to the egress bus
event, not to sightings or arrivals; the additive `identity_provenance` key does not change its reads.

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
| `CAMERA_DERIVED_ARRIVAL_SOURCES` | `frozenset({"camera_face"})` | 1 | Rev 4 (M5). The one set the lock regime and the security gate test by membership. Not a kill switch; adding a source here is the only way a new camera-derived source is recognised (unknown sources fail closed regardless). |
| `FACE_SIGHTING_PICK_RERESOLVE_S` | 300 | 1 | Retry period while any pick is unresolved. 0 = only the event triggers. |
| `FACE_SIGHTING_BRIDGE_RING_MAX` | 2000 | 1 | Bound on the trip-wire denominator ring (≈ 2 days at measured rates). |
| `FACE_ARRIVAL_INTERIOR_ENABLED` | False until D0-P3 passes | 1 | Interior class (i) arrivals. False = sightings only. |
| `FACE_ARRIVAL_PRIOR_HOME_GAP_S` | set by D0-P3 (placeholder 60) | 1 | A home edge this long before the face, or any time after it, means the phone already arrived. 0 = only edges after the face. |
| `FACE_ARRIVAL_DEBOUNCE_S` | 600 | 1 | One arrival per person per episode. |
| `FACE_SIGHTING_ZERO_WINDOW_H` | 24 | 1 | Trip-wire window; 0 = off. |
| `FACE_SIGHTING_ZERO_MIN_FACES` | 10 | 1 | Denominator floor before zero sightings is a fault. |
| `FACE_ARRIVAL_ZERO_DAYS` | 14 | 1 | Second trip-wire; 0 = off; armed only with interior arrivals on. |
| Security face gate window | REUSE `PERIMETER_EGRESS_FACE_NONFACE_WINDOW_S` (120) + lock boot floor, via `face_input_corroborated` | 1 | Coupling note at `const.py:2674` applies: widening it widens all three access consumers. |
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
    veto). This confirms egress = sightings only.
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
- No new arrival/departure notification. One already exists, `TransitValidator._arrival_departure_notify`
  (`transit_validator.py:2047`, `:2140`), and is unchanged (rev 4, M6).
- **No egress-derived arrivals** (H1; parked with trigger, §0).
- No change to the egress producer's logic, windows, veto or exit backfill. **One exception:** the additive
  `identity_provenance` bus key (F2), a value it already computes.
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
  `test_identity_provenance_consts.py::test_values_unchanged` (constants equal the old literals;
  census/transit read them)
  (real hass); `test_transit_validator_provenance.py::test_bus_event_carries_identity_provenance`,
  `::test_face_only_real_path_provenance_face` (rev 4 H1: drives the real `_resolve_egress_face_identity` face-only
  path, asserts `identity_provenance == "face"` on the fired event; no hand-stamped attach).
- **Live:** `face_sighting_picks_resolved` ≥ the D0-P1 count after a restart. Every `*_last_recognized_face*`
  change to a resident name on a resolved pick (outside the boot window) has a matching sighting ±debounce. No
  sighting in the first 600 s after restart. `ura_person_egress_event` rows carry `identity_provenance`.

### D2: Arrival derivation (one site)
- **Verify:**
  - Egress sightings never dispatch `SIGNAL_PERSON_ARRIVING`.
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
  `::test_camera_derived_set_used_by_both_gates`;
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

### D7 (PARKED unless D0-P4 passes): interior track sequence
If P4 passes: first extend the live `door_interior_neighbours` option (already encodes door-to-interior adjacency,
e.g. garage_a: garagehallway, staircase, stairs_top; rev 4 L7); mint `INTERIOR_CAMERA_ADJACENCY` (rung 1, modelled on
`EXTERIOR_ADJACENCY_GRAPH`) only for interior-to-interior pairs it cannot hold; propagate a name to an
unnamed person edge on an adjacent camera within the measured lag; emit `synthetic=True`,
`sighting_source="interior_track"`, never an arrival. Revival trigger if parked: door camera recognition below 20 %
of crossings after FRIGATE-DOOR-FACE-TUNING-1 AND a personalization consumer needs hallway continuity.

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

---

## 10. Marginal risk, priced in ingredients

| Ingredient | Assessment |
|---|---|
| New writer to a shared primitive (`SIGNAL_PERSON_ARRIVING`) | Rate rises from 0 to the D2 rate, likely still ~0 (interior class (i), D0-gated, default off). An access consumer is downstream. Containment: D3 + INV-ACCESS. Tier 3. |
| Cross-module callback (census -> presence) | One hook per message, list in `hass.data`, exception-isolated, removed at unload. |
| Producer change in the egress path | One additive bus key, read from a value already computed. No reader changes behaviour. |
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

**HVAC touch:** only the pre-arrival entry point's input set changes. The builder and reviewers read
`HVAC_ARCHITECTURE_STATE_OF_PLAY.md` completely before touching `hvac.py` (this planner did not; no HVAC logic
change is planned, and D5 only fixes stale cites).

**Sibling HVAC-PRECOOL-STANDDOWN-WHEN-COOL-1** (`plan/hvac-precool-standdown`) changes pre-arrival pre-cool. No code
overlap (it changes HVAC decision logic; this plan changes only the arrival input). Build order: either first; the
second rebases. Its stand-down is an expected HVAC skip reason in L6.

## 12. Cards to mint (adjacency sweep before minting)
- **LOCK-RELEASE-ON-ARRIVING-BODY-EVIDENCE-1** (investigate): AWAY -> ARRIVING from body evidence alone releases the
  garage lockout and can auto-follow disarm; review against §5.5(a).
- **FACE-SIGHTING-CONSUMERS-1** (backlog, after ship): personalization reads `get_last_person_sighting` / the
  signal, declares an action class, and uses `face_input_corroborated` for any access class. Rev 4 (M6):
  notifications are NOT a new producer here; any sighting-based wording extends the existing
  `_arrival_departure_notify`. ARRIVAL-DEPARTURE-NOTIFY-1 is not a gap (that site exists).
- **FACE-EGRESS-ARRIVAL-1** (parked): egress-derived arrivals; trigger in §0.
- **PHONE-LEFT-BEHIND-CAMERA-LEG-1** (rev 3, Tier 2-DB minimum, house state): its camera leg reads
  `TransitValidator._camera_sightings`, which never holds a named sighting live (`hours_since_camera_sighting` null on
  all four sensors 2026-11-12; `person_id` attribute is a display name, not a slug). Migrate to
  `get_last_person_sighting(slug)`; retire the named branch of `_camera_sightings` (KEEP + WIRE).
- **CROSSING-VISION-SEQUENCE-1** (rev 3, §15): crossing snapshot sequence + batched vision analysis as a `vision`
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

8. **Progressive analysis (rev 4, operator 2026-11-12).** A fast first-frame call (one or two frames as soon as the
   crossing fires) yields a PROVISIONAL hypothesis `{people_count, direction, resident_like}` attached to the crossing
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
   entry terms). Weighting against Frigate/Protect counts is §15.7.

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
  temperature caveat). Then each crossing runs both stages per model: FAST (§15.5 F-stage: 2 frames, 768 px) and
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
| F (fast) | Fire at t0. Frame 1 = Frigate event best snapshot if the event id is known (no camera load), else live grab; frame 2 = live grab at t0 + 2 s. Door camera only. Prompt asks only `{people_count, direction, group, resident_like}` | 2 × 768 px wide (~425 tokens each by the 4o formula), ~400 text tokens in, ≤ 150 out | `gpt-6-luna` | capture 1-3 s + call 2-4 s → **t0 + 5 s / t0 + 10 s** |
| B (batch) | Window opens at t0, closes at t0 + 60 s (extended by clustering, cap 180 s). Door camera every 5 s for the first 20 s then every 10 s; up to 2 chain cameras (§15.8: interior for entries, exterior for exits) every 10 s from t0 + 5 s. Frames with no person detection on that camera are dropped before the call | ≤ 12 × 1024 px (~765 tokens each), ~600 text in, ≤ 600 out | `gpt-6.1-sol` | window 60 s + call 5-20 s → **t0 + 70 s / t0 + 90 s** unclustered; clustered worst t0 + 180 s + 30 s |
| S (synthesis) | Join F, B, face (Protect names back-fill ~1-2 min; `FACE_MATCH_WINDOW_S` 60), BLE (home edges; exit backfill `BLE_EGRESS_EXIT_BACKFILL_WINDOW_S` 600) and Frigate/Protect counts into the final crossing record and the ledger term | none | none (local) | entries **t0 + 120 s**; exits wait for BLE backfill, **≤ t0 + 600 s** |

Why these numbers: the person usually reaches the next camera on the chain 5-20 s after the door (assumed; D0-SIM
measures hop times from Frigate events), so a 60 s window covers the door plus 2-3 hops, and a 5 s door cadence gives
4 frames of the door moment, which is where groups split. Two frames for F because one frame cannot give direction.
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
| F on `gpt-6-luna` | 14.4 (25) | ~1,250 (150) | $0.003 ($0.005) |
| B on `gpt-6.1-sol` | 10.5 (25) | ~9,800 (600) | $0.27 ($0.64) |
| Interior head count (§15.8) on `gpt-6-luna`, 1 call per 30 min while occupied, 12 cameras × 768 px | 48 (48) | ~5,500 (200) | $0.03 ($0.03) |
| **Total** | ~73 (98) | | **~$0.30 ($0.68) → ~$9/month mean, ~$20 worst** |
| Baseline: same F + B on `gpt-4o-mini` (images priced at ~2,833 base + 5,667/tile tokens at $0.15/1M by the same published formula) | | | ~$0.55/day |

B dominates the bill. If D0-V shows Luna's batch accuracy meets the gate, Luna for both stages cuts the total to about
$1/month. The daily cap (`CROSSING_VISION_DAILY_CALLS`) is set from the worst-case column, not the mean.

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
| F lands by t0 + 10 s | ≥ 90 % of crossings (measured run) |
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
3. **How many non-residents** = vision ledger minus BLE-home residents, when vision is healthy (provider up, not
   capped, within its D0-V accuracy). When vision is unhealthy or the crossing was skipped, the census falls back to
   today's path: `unidentified_count = max(0, camera_total - |known|)` from Frigate/Protect counts
   (`camera_census.py:2533`), and the result is marked camera-only.
4. **No signal silently wins.** When the vision non-resident estimate and the camera-count estimate differ, both are
   recorded on the census result and the difference is flagged.

Reuse, not new structure: `CensusZoneResult` already carries `source_agreement`, `degraded_mode` and
`active_platforms` (`camera_census.py:305-321`). The sibling plan adds `vision` to `active_platforms` when vision
contributed, records a vision-vs-camera agreement value using the existing `CENSUS_AGREEMENT_*` vocabulary, and uses
`degraded_mode` semantics for "camera-only". The persistent-disagreement trip-wire goes to the AnomalyDetector wired
to NM (CLAUDE.md No-Soak), not a calendar. The guest gate keeps reading the census's `unidentified_count`; what
changes, only after the D0-V census gate passes, is which estimate feeds it.

Knob sketch for the sibling plan: `CROSSING_VISION_HEALTH_MAX_AGE_S` (rung 1, how stale the last good vision call
may be before fallback), `CROSSING_VISION_COUNT_AUTHORITY` (rung 2 select: `evidence_only` default / `vision_led`),
`CROSSING_VISION_DISAGREE_FLAG_MIN` (rung 1, persons of disagreement before flagging).

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
