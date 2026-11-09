# PLANNING: face-source registry discovery (FACE-SOURCE-REGISTRY-DISCOVERY-1)

Card: `FACE-SOURCE-REGISTRY-DISCOVERY-1` (`docs/planning/kanban.data.yaml:350`). Input audit:
`docs/planning/AUDIT_face_source_registry_discovery_2026_11.md`. Plan date 2026-11-08. Plan only; nothing built.

**Rev 2 (2026-11-08, plan review 1, `docs/reviews/code-review/face_source_registry_plan_review_1.md`).** D3 now
ships the skip fix LIVE (default True) behind a pre-build one-shot recorder probe (new D0) instead of shadow plus a
14-day measurement card; INV-4 (S7 direction) added; D4 engine fallback pinned; D2 counter semantics pinned;
non-goals list completed (`camera_census.py:626`, `:1134`); FACE-SOURCE-SKIP-FIX-FLIP-1 folded into this cycle.

**Sequencing (hard constraint):** branch `feature/face-source-registry` off `develop` only AFTER
`feature/perimeter-fp-build` (PERIMETER-FP-STREET-NOISE-1, v5.107.0) has merged to develop. See §9.

---

## 0. Institutional context verified

### 0.1 Read in full
- `docs/Coordinator/IDENTITY_FUSION_CAMERAS_MANUAL.md` (all 587 lines; canonical for this domain).
- `docs/planning/AUDIT_face_source_registry_discovery_2026_11.md` (all 102 lines).
- Code read end to end for each site in §4: `camera_census.py` 3134-3420, 3425-3640, 3665-3800, 5017-5090,
  5473-5560; `camera_resolver.py` 240-256, 455-600, 1205-1290, 1395-1435; `domain_coordinators/presence.py`
  5335-5445; `transit_validator.py` 1450-1470, 1695-1720, 1850-1900; `perimeter_alert.py` 485-510,
  1395-1430; `camera_census.py` 620-670, 1125-1150, 1222-1235 (CameraInfo construction).
- The in-flight perimeter build's uncommitted diff (worktree `.claude/worktrees/agent-ae7aefbc986e55f79`,
  branch `feature/perimeter-fp-build`) and its plan `docs/planning/PLANNING_perimeter_fp_build_2026_11.md`.
- HVAC / PRESENCE state-of-play docs: not applicable (identity domain, no presence-sensor change).

### 0.2 Contradictions between code and docs (code wins; the manual fix is in D7)
1. Manual §1.1 and §2.2/§4.2 cite `_resolve_face_entity_id` at `camera_census.py:2615-2648` and
   `_face_lookup_missing_count` at `:2647`. Actual on develop (`4a1d1049`): `camera_census.py:3134-3175`, counter
   increment `:3174`.
2. Manual §1.1 says face reads tolerate `_2` via `_resolve_face_entity_id`. That is true only of the face-sensor
   leg. Four callers derive the base stem from the person sensor with a raw `endswith("_person_occupancy")`
   (`camera_census.py:3578`, `:3612`, `:5533`; `presence.py:5366-5369`), while `CameraInfo.entity_id` keeps the real
   id (`camera_census.py:653-656`, "Real entity_id is stored below"). Live result: 17 of 29 Frigate cameras
   (every `_person_occupancy_2` camera) never reach the face resolver. See §2.1.
3. Manual §1 table: "every survivor carries `_2` on at least SOME entities". The face family is mixed (23 `_2`,
   6 bare). The audit says the same; the manual is not wrong but is incomplete for face sensors.

### 0.3 Prior-art scan, REUSE or NEW per piece

| Piece | Verdict | Evidence |
|---|---|---|
| Registry walk over Frigate entities by `platform` and `unique_id` segment | **REUSED pattern** | `camera_census.py:3428-3500` `_build_frigate_person_last_camera_map` already iterates `registry.entities.values()`, filters `platform == "frigate"`, splits `unique_id` on `:` and tests `parts[1] == "sensor_global_face"`. Same read-not-construct rule (`:3146-3147`). |
| Where the index lives and when it rebuilds | **REUSED** | `CameraResolver.__init__` builds `_frigate_stem_to_device_ids` (`camera_resolver.py:460`, `:533`), `_stem_to_device_ids` (`:470`), `_dstem_to_device_ids`, `_device_platform_hint`. The census marks the resolver dirty on `EVENT_ENTITY_REGISTRY_UPDATED` / device-registry updates (`camera_census.py:462-506`, `:1529`). The new face index is one more dict built in the same pass. |
| Stem → device lookup | **REUSED** | the raw-then-stripped lookup chain at `camera_resolver.py:757` over `_stem_to_device_ids` / `_dstem_to_device_ids`. |
| Engine family from a device | **REUSED** | `CameraResolver._infer_integration(dev)` (`camera_resolver.py:1245-1262`), already used by `_resolve_face_legs` (`camera_census.py:3260-3268`). |
| Face-name → person canonicalizer | **REUSED, extended** | `_canonical_person_slug` (`camera_census.py:3681-3774`) with `tracked_persons` and `known_face_guests` (`CONF_KNOWN_FACE_GUESTS`, `const.py:3258`; options field `config_flow.py:5120-5138`, step `async_step_camera_census` `:5005`). |
| Face-name alias map (`CONF_FACE_NAME_ALIASES`) | **NEW** | grep of `const.py` + `config_flow.py` for `alias|nickname|face_name|FACE_.*MAP|KNOWN_FACE|face_library|person_map|name_map` (case-insensitive) finds only `CONF_KNOWN_FACE_GUESTS` and unrelated aliases (`EXTERIOR_CAMERA_KEY_ALIASES` `const.py:2984` = camera-stem aliases; `stem_aliases` `camera_resolver.py:901` = native-AI stem bridge; deprecated-constant aliases). No `options_flow.py` exists. Repo-wide `*.py` grep for `alias|nickname` finds no person-name alias. `docs/planning` + `docs/Coordinator` grep finds one need statement: `AUDIT_census_subsystem_2026_10_04.md:176` F6 ("`ojini` leaks into `person_entry_exit_events.person_id` ... Decide whether Ojini is a known guest or an alias of Oji"). Memory grep (`face.*alias|nickname|face_name`): no relevant body. |
| Diagnostic surface for face sources | **REUSED** | attributes on `URAPersonsInHouseSensor` (`sensor.py:3719`, unique_id `universal_room_automation_census_persons_in_house`, live `sensor.universal_room_automation_persons_in_house`), which already carries `face_lookup_missing_count` (`sensor.py:3873-3875`) and `unresolved_configured_cameras` (`:3853-3860`). No `diagnostics.py` exists in the integration. No new entity. |
| Frigate MQTT topic prefix | **REUSED, no change** | `_resolve_frigate_topic_prefix` (`camera_census.py:4980-5000`) already reads it from the Frigate entry. Not a portability gap. |
| Face producer health entity | out of scope | `_resolve_face_producer_health_entity` (`camera_census.py:4092-4130`) hard-codes `sensor.frigate_status[_2]`. Same class; see Non-goals. |

### 0.4 Prior planning and cards consulted
- `D1-PROTECT-FACE-BRIDGE-ADDON-1` (kanban `:27143`, **parked** 2026-08-29): the Protect add-on that would write
  `sensor.<cam>_face_recognized`. It is the only planned producer of the Protect suffixes URA looks up (§6).
- `FRIGATE-SUBLABEL-FACE-BRIDGE-1` (done): the MQTT latch (`_compute_face_latch_stems`, `_on_frigate_face_msg`).
- `EGRESS-IDENTITY-JOIN-GAP-1` / v5.91.4 producer: `_resolve_face_legs`, `FaceLeg`, the 0.6 / 0.75 / 0.9 tiers.
- `PERIMETER-FP-STREET-NOISE-1` plan + uncommitted build (§9).
- `CENSUS-ACCURACY-1` D2 (the `_2`-tolerant face resolver), `CENSUS-SUFFIX-FIX` (strips `_N` when building
  CameraInfo but not in the face callers), `CENSUS-NAME-SPACE-DEDUP-1` (canonicalizer normalisation).
- `AUDIT_census_subsystem_2026_10_04.md` F6 (Ojini).

### 0.5 Memory bodies relevant
`reference_frigate1_retired_2suffix_permanent` (never assume `_2` = live), `feedback_extend_existing_never_rebuild`,
`feedback_config_first_before_code`, `feedback_marginal_benefit_pushback`,
`feedback_coincidental_equality_masks_concept_split` (applies to §2.2 engine tag).

### 0.6 Config-first check
No setting fixes this. Discovery is hard-coded string building; no knob selects face entities. Renaming entities
in HA to match the pattern would work for one house but is the opposite of the card's goal (home-agnostic). The
silent skip (§2.1) has no config workaround short of renaming 17 person sensors, which would break other readers.

---

## 1. Falsifier results (run at plan time, read-only)

Probe: `.../scratchpad/falsify_face_registry.py` over the live `core.entity_registry` / `core.device_registry`
(Samba, mtime 2026-11-08 19:25). D1 commits the probe as `scripts/probe_face_source_registry.py`.

| Check | Result |
|---|---|
| (a) Registry path vs today's pattern path, per Frigate camera person sensor (29 camera devices) | For the **12** cameras the pattern path resolves today, the registry path returns the **same entity_id** (12/12). Zero sources lost. For the other **17** the pattern path returns nothing (person sensor is `*_person_occupancy_2`, rejected by the raw suffix test) and the registry path returns that camera's face sensor. |
| (b) Rename `sensor.doorbell_lite_last_recognized_face_2` → `sensor.front_bell_face_name` | Registry path resolves the renamed id; pattern path cannot. |
| (c) Replace every Frigate `unique_id` entry prefix with a new entry_id | Registry index identical to live (`True`). |
| `sensor_global_face` look-alikes | 6 exist, none enter the registry index. |
| Name-pattern hits that are not `sensor_recognized_face` | none. |
| Frigate camera devices with no face sensor | 0 (all 29 enrolled). |
| Face-entity stem (suffix stripped) vs the same device's `camera.*` stem (`_N` stripped) | equal on 29/29; no device owns two camera entities. |

**Consequence for the invariant the operator asked for.** "This house resolves byte-identical face sources before
and after" holds for discovery. It does **not** hold for "fix the silent skip": that fix by construction adds 17
cameras' face sensors to four consumers (§2.1). The two scope items conflict. ~~Rev 1 resolved it by shipping the
skip fix in shadow with a 14-day measurement card.~~ **Rev 2:** INV-1 is stated for discovery only (S1, S2, S9, S10,
D4, and S5-S8 on the 12 cameras the legacy path already reads). The skip fix goes live this cycle (D3), gated by a
one-shot recorder probe run before build (D0), with its own invariant INV-4. Rationale: plan review 1 §3.

---

## 2. Falsifiable invariants

**INV-1 (discovery equivalence).** With `FACE_SOURCE_REGISTRY_DISCOVERY_ENABLED = True` and
`FACE_SOURCE_INCLUDE_DISAMBIGUATED_PERSON_SENSORS = False` (the test configuration; the shipped default of the second
constant is True, see INV-4), for every call in any reachable path into
`_resolve_face_entity_id(stem)`, `_resolve_face_legs(stem)`, `_compute_face_latch_stems(resolver, camname)`,
`_get_face_recognized_persons()`, `_get_face_recognized_persons_fresh(now)`, `_get_unrecognized_camera_count()` and
`presence._get_face_for_camera(camera_entity)`, given the same registry and the same states, the post-build code
returns the same value as `develop` before the build: same entity_id(s), same order, same `FaceLeg` fields
(`entity_id`, `device_id`, `base_stem`, `canonical_slug`, `last_changed`, `confidence`) and the same
`_face_lookup_missing_count` delta. The one declared exception is `FaceLeg.engine` (INV-2).
*Break it by:* any stem where the registry index picks a different entity than the pattern path, any caller that
now reads a camera it skipped before, or a counter that moves differently.

**INV-2 (engine label change cannot change a decision).** `FaceLeg.engine` changes from suffix-derived
(`frigate2` for 23 cameras) to device-derived (`frigate`). For every pair of an entity leg and a synthetic latch
leg on the same `base_stem`, the dedup at `camera_census.py:3380-3390` merges them after the build exactly when it
did before. Therefore the leg count `n` and `identity_confidence` in
`transit_validator._resolve_egress_face_identity` (`:1855-1878`) are unchanged for every crossing.
*Break it by:* any path where the entity leg and the synthetic leg get engines from different derivations (e.g.
entity leg from the device, synthetic from the `_2` state probe at `:3339-3345`), which makes `n = 2` and
spuriously yields `FACE_MATCH_CORRELATED_BOOST` (0.75).

**INV-4 (skip fix only removes, never adds, unrecognized persons; rev 2).** With
`FACE_SOURCE_INCLUDE_DISAMBIGUATED_PERSON_SENSORS = True`, for every interior Frigate camera on every tick,
the raw contribution computed in `_get_unrecognized_camera_count` (`camera_census.py:5531-5574`) is less than or
equal to the contribution the legacy path computes for the same camera and states, and is exactly equal for every
camera whose person sensor ends in `_person_occupancy`. For those 12-style cameras, S5, S6 and S8 return exactly the
legacy value.
*Break it by:* any camera whose contribution rises (e.g. the device join returns a different camera's face sensor,
or an exception in the new branch falls through to a path that double-appends), or any bare-suffix camera whose
value changes.

**INV-3 (no look-alike admission).** No entity whose `unique_id` segment 1 is not exactly `sensor_recognized_face`
is ever returned as a face-name source by the registry path, on any platform.

---

## 3. Producer and consumer checks

### 3.1 Value: "face-name source entity for camera X"
**Producer today.** String building: `sensor.<base>_last_recognized_face[_2]` (`camera_census.py:3156-3157`,
`:3206-3210`), with `<base>` derived from the person sensor id (`:3578`, `:3612`, `:5533`, `presence.py:5367`) or
supplied by the caller as a camera stem (`transit_validator.py:1459`, `perimeter_alert.py:1401`). Its dependency,
the person sensor id suffix, is unhealthy for 17/29 cameras today (§1).
**Producer after.** Registry index `device_id → [face entity_id]` built in `CameraResolver` from
`(platform == "frigate", domain sensor, unique_id.split(":")[1] == "sensor_recognized_face", disabled_by is None)`.
Camera X is joined by `device_id`: for a person-sensor caller, the person sensor's own `device_id`; for a stem
caller, the stem → device lookup (`camera_resolver.py:757` chain) filtered to devices in the face index. Pattern
candidates are used only when the registry yields nothing for that camera. Dependencies: the entity registry
(always present) and Frigate's `unique_id` type token (integration-defined; audit §3, `frigate/sensor.py:1116-1122`).
Ground truth: falsifier (a) against the live registry.

**Consumers** (all read the entity's state; none persist the entity_id):

| Consumer | file:line | Trust or display |
|---|---|---|
| Census face union `face_ids` | `camera_census.py:3554-3592` → `_calculate_house_census` | trust (house count, guest inference) |
| Census corroboration bundle | `camera_census.py:3595-3640` | trust (divergence downgrade) |
| Unrecognized-camera (guest) count | `camera_census.py:5473-5560` | trust (guest count) |
| Presence pre-arrival face | `presence.py:5338-5445` | trust (pre-arrival accelerator) |
| Egress identity producer | `transit_validator.py:1459` via `_resolve_face_legs` | advisory `person_id` + confidence, persisted to `person_entry_exit_events` |
| Perimeter alert naming | `perimeter_alert.py:1400-1430` via `_resolve_face_legs` | display (message text) |
| Perimeter D10.5 known-identity demote (perimeter build, post-merge) | `perimeter_alert._known_identity_for` via `_resolve_face_legs` | **trust: security de-escalation** |
| Latch write key | `camera_census.py:5017-5088` | internal key that must equal the read key |
| Enhanced-census recognized set (via the `last_camera` map, not the per-camera face sensor) | `camera_census.py:5825` `_get_face_recognized_person_names` → `_resolve_last_camera_entity_id` → consumed at `:5977-6011` | trust (house identified set); touched only by D6 |

### 3.2 Value: `FaceLeg.engine`
Producer: `_engine_tag(integration, name, device_id)` (`camera_resolver.py:1212-1235`), which reads the `_N` suffix,
or the suffix fallback at `camera_census.py:3273-3281`, and the latch path `:3329-3352`. Consumers: latch dedup
equality (`camera_census.py:3332-3333`, `:3385`), `contributor_engines` attribute (`transit_validator.py:1709`,
`:1890-1893`; display), perimeter build `nvr_family` (prefix `frigate*`; unchanged by `frigate2` → `frigate`).
`perimeter_alert.py:496` / `:850-860` read `DetectionLeg.engine`, not `FaceLeg.engine`; out of scope.

Why the suffix tag is now a concept split hiding behind a name: `frigate` vs `frigate2` once separated two Frigate
hosts. Frigate-1 retired 2026-08-13; one Frigate entry exists. The suffix now tells you when HA minted the entity,
not which host saw the face (6 bare face sensors are on the same host as the 23 `_2` ones).

### 3.3 Value: canonical person slug from a face name
Producer `_canonical_person_slug` (§0.3). Dependency: `tracked_persons` first tokens equal the face-library names.
That holds here except `Ojini` (F6). Consumers: every face path above plus BLE/census union, DB `person_id`,
the perimeter D10.5 `known` set. The alias field (D5) is empty by default, so no consumer sees a change.

---

## 4. Emission / decision-site enumeration (re-grepped on develop `4a1d1049`)

Grep: `last_recognized_face|_face_recognized|sensor_recognized_face|sensor_global_face|_resolve_face_entity_id|
_resolve_face_legs|_compute_face_latch_stems|_FACE_SUFFIXES|_engine_tag(|endswith("_person_occupancy")`
across `custom_components/universal_room_automation/`. Self-check pass (second, wider grep: `recognized_face|
face_recognized|"_person_occupancy"`) added the `_get_face_recognized_person_names` consumer (§3.1), corrected three
line numbers, and moved the person-leg suffix sites to Non-goals.

| # | Site | Pattern today | Disposition |
|---|---|---|---|
| S1 | `camera_census.py:3134-3175` `_resolve_face_entity_id` | builds bare + `_2` ids | D2: registry candidates first, pattern fallback |
| S2 | `camera_census.py:3200-3211` `_resolve_face_legs` candidate list | 4 built ids (2 Frigate, 2 Protect) | D2 (Frigate); Protect ids KEEP+DOCUMENT (§6) |
| S3 | `camera_census.py:3256-3281` `_resolve_face_legs` engine | `_engine_tag` suffix + suffix fallback | D4 |
| S4 | `camera_census.py:3329-3352` latch synthetic engine + sentinel | builds `_2`/bare ids, probes state | D4 (same helper as S3) |
| S5 | `camera_census.py:3578` `_get_face_recognized_persons` | raw `endswith("_person_occupancy")` | D3 |
| S6 | `camera_census.py:3612` `_get_face_recognized_persons_fresh` | same | D3 |
| S7 | `camera_census.py:5533` `_get_unrecognized_camera_count` | same; non-match counts whole camera as unrecognized | D3 |
| S8 | `presence.py:5366-5395` `_get_face_for_camera` | suffix loop + bare-id fallback | D3 |
| S9 | `camera_census.py:5052-5070` `_compute_face_latch_stems` | device by registry, sensor by name suffix | D2 (pick by token; stem from the device's `camera.*` entity) |
| S10 | `camera_resolver.py:246-252`, `:1411`, `:1426` `_FACE_SUFFIXES` → `face_cap` | suffix list | D2 adds the token test (OR); suffixes KEEP+DOCUMENT (§6) |
| S11 | `camera_census.py:3470-3480` `_build_frigate_person_last_camera_map` | entity_id prefix/suffix filter before the `sensor_global_face` token check | D6 |
| S12 | callers passing a stem: `transit_validator.py:1459`, `perimeter_alert.py:1401`, perimeter build `_known_identity_for` | stem string | no edit; covered by S2 through INV-1 |

---

## 5. Deliverables

### D0 (rev 2). One-shot recorder probe: what the 17 skipped face sensors would have fed (go/no-go for D3 live)
Read-only, run before build dispatch (`ssh ha "python3 -" < script.py` over the recorder DB; the face sensors are
not recorder-excluded, `docs/planning/RUNBOOK_recorder_excludes.md`). Over all retained history for the 17
`sensor.*_last_recognized_face_2` ids listed in review 1 §2.2:
1. Named-state count per sensor; each distinct name classified through the same rules as `_canonical_person_slug`
   (tracked resident / `guest:<head>` / passthrough).
2. For `playroom` and `upstairs_hall` only: each named state that coincided (within
   `CENSUS_FACE_RECOGNITION_WINDOW_SECONDS`) with its person count > 0, i.e. the ticks where S7 would have
   subtracted 1. Count by class.
3. Confirm at runtime which Frigate person sensors the configured interior list resolves to
   (`camera_person_entities` holds `camera.upstairs_hall_high_resolution_channel`, not `camera.upstairs_hall_2`;
   whether S7 ever sees the upstairs_hall Frigate sensor is unverified).
**Gate:** live default True if no passthrough name appears on an interior camera and resident names dominate. If a
passthrough or guest name lands on playroom/upstairs_hall at a material rate, ship with the constant False and say
why in the README (no forward soak either way). Report goes into this plan as §1.1.
- **Live:** n/a (pre-build).

### D1. Committed probe + hand-built fixture (measure first, already run)
Commit the falsifier as `scripts/probe_face_source_registry.py` (read-only; reads the registry JSON path given as
an argument) and a minimised fixture `quality/tests/fixtures/face_source_registry_2026_11.json` hand-extracted
from the live registry: the 29 face sensors, 29 `camera.*`, 29 person sensors (registry fields only: `entity_id`,
`platform`, `unique_id`, `device_id`, `disabled_by`), the 6 `sensor_global_face` rows, and the 29 camera devices +
server device (`id`, `identifiers`, `via_device_id`). The fixture is the acceptance oracle for D2-D4. It is extracted
from the registry, not typed by hand from memory.
- **Verify:** the probe prints `agree=12`, 17 SKIP rows, `(c) ... True`, look-alikes not indexed.
- **Test:** none (fixture + script).
- **Live:** n/a.

### D2. Registry-first Frigate face index in `CameraResolver`, pattern fallback
In the same registry pass that builds `_frigate_stem_to_device_ids` (`camera_resolver.py:505-535`), build
`_frigate_face_entities_by_device: dict[str, list[str]]` from the INV-3 predicate. Add two read methods:
`face_name_entities_for_device(device_id) -> list[str]` and `face_name_entities_for_stem(stem) -> list[str]` (stem →
device via the `:757` raw-then-stripped chain, then the face index). Order within a list: bare-named before `_N`, then
lexical, which reproduces today's bare-then-`_2` candidate order.
Rewire S1, S2 (Frigate candidates), S9 and S10:
- S1/S2: candidates = registry list for the stem; if empty, today's built ids. The state gating, sentinels,
  counter increments and Protect candidates stay as they are.
- S9: choose face entities by the token, not by name suffix; derive the latch key from the device's `camera.*`
  entity name with `_N` stripped (29/29 equal to today's key, §1). Keep the single-stem rule.
- S10: a `sensor` entity whose unique_id token is `sensor_recognized_face` sets `face_cap` regardless of name;
  the suffix test stays as an OR.
- Count `face_source_registry_hits`, `face_source_pattern_fallbacks` per tick (reset beside
  `_face_lookup_missing_count`, `camera_census.py:1715`). **Rev 2 semantics:** both count candidate-list
  *lookups* (registry list non-empty vs empty), not live states. They say nothing about whether Frigate is
  producing; `face_lookup_missing_count` stays the producer-side signal.
- Kill switch `FACE_SOURCE_REGISTRY_DISCOVERY_ENABLED` (§7). False = pre-build code path, byte-identical.

**Acceptance**
- **Verify:** over the D1 fixture, for every Frigate camera stem and every person sensor, `_resolve_face_entity_id`
  and `_resolve_face_legs` return the same value with the switch True and False (the 12 resolving cameras), and
  `_compute_face_latch_stems` returns the same key list for all 29 Frigate cam names.
- **Verify (discriminates rename vs broken index):** with the doorbell face sensor renamed in the fixture, the
  registry path returns the renamed id and `face_source_registry_hits` increments. With the index forced empty, the
  result is `None` for the renamed id and `face_source_pattern_fallbacks` increments. Same final output for the two
  failures would not tell you which broke; the counters do.
- **Verify:** a fixture row `<entry>:sensor_global_face:Oji` on a camera device is never returned (INV-3).
- **Verify:** a fixture with a new entry_id prefix yields the same index.
- **Test:** `test_face_source_registry.py::test_registry_equals_pattern_on_live_fixture`,
  `::test_renamed_face_sensor_resolves_by_registry`, `::test_global_face_never_indexed`,
  `::test_new_entry_prefix_same_index`, `::test_empty_index_falls_back_to_pattern`,
  `::test_latch_key_from_camera_entity_equals_legacy_key`, `::test_kill_switch_off_byte_identical`,
  `::test_face_cap_by_token_for_renamed_sensor`.
- **Live:** `sensor.universal_room_automation_persons_in_house` attributes `face_source_registry_hits > 0` and
  `face_source_pattern_fallbacks == 0` within one census tick of a face-reading tick. A broken index shows the
  reverse (hits 0, fallbacks > 0). (Rev 2: a dead Frigate producer does NOT zero the hits, because hits count
  lookups; it shows as `face_lookup_missing_count` rising with hits unchanged.)

### D3. Silent skip for renamed / `_N` person sensors: fixed LIVE (rev 2)
S5-S8 derive the face source from the person sensor's **device** (`face_name_entities_for_device`) instead of
stripping `_person_occupancy` from the entity_id. Ordering per site: legacy suffix test first (unchanged path for
the 12 bare cameras); only when it fails, the device join. Gated by
`FACE_SOURCE_INCLUDE_DISAMBIGUATED_PERSON_SENSORS` (default **True**, subject to the D0 gate):
- True: the device-derived face source is used for cameras the legacy test skips. Each such read is counted in
  `face_source_device_derived_reads` (int, per tick) and the cameras listed in `face_source_device_derived_cameras`
  (sorted entity_ids).
- False (kill switch): legacy skip, counted in `face_source_skipped_person_sensors` and listed in
  `face_source_skipped_cameras`.
- S7 keeps today's fail-CLOSED rule: if the device join yields no face sensor, the camera's whole count stays
  unrecognized (`camera_census.py:5534-5536`). No new branch may append twice for one camera.
- No consumer semantics change: S7 still subtracts 1 for any fresh named face (resident or `guest:*`), exactly as
  it does for the 12 cameras today. The `guest:*`-subtracts question is a pre-existing behavior, carded separately
  (review 1 F-5), not forked here.
For S8 the legacy fallback `f"sensor.{base_name}_last_recognized_face"` (`presence.py:5394-5395`) stays only on the
fallback branch.

What changes live on this house (review 1 §3): S7 for `playroom` (configured interior; `upstairs_hall` per D0.3)
drops from "every person unrecognized" to `count - 1` when a fresh face is present; S5 changes the raw union only,
which `_apply_enhanced_house_census` overwrites when enhanced census is on (live: on); S6 gains exterior faces as
corroboration; S8 gains face pre-arrival on the 17 cameras that sit in a zone tracker.

**Acceptance**
- **Verify (INV-4):** fixture with `binary_sensor.playroom_person_occupancy_2`, count 2, fresh face "Jaya":
  switch False → contribution 2; switch True → contribution 1. Same fixture with the face stale or absent →
  contribution 2 under both. Same fixture with a bare `_person_occupancy` camera → identical under both.
- **Verify:** a person sensor renamed to `binary_sensor.kids_room_motion_person` on a Frigate device resolves when
  True and is counted as skipped when False.
- **Verify:** with enhanced census on, flipping the switch leaves `house.identified_count` and
  `identified_persons` unchanged for a tick where an exterior `_2` camera shows a resident face and BLE holds that
  resident (the overwrite at `_apply_enhanced_house_census`).
- **Test:** `test_face_source_registry.py::test_skip_fix_on_reads_device_face`,
  `::test_skip_fix_off_counts_skipped`, `::test_unrecognized_contribution_never_rises` (parametrised over
  fresh/stale/absent/exception in device join), `::test_bare_cameras_identical_under_flip`,
  `::test_enhanced_overwrites_raw_face_union`, `::test_presence_face_for_camera_reads_device_face`.
  Mutation: make the device-join branch return the legacy `None` → `test_skip_fix_on_reads_device_face` red; make
  it append the count before the face check → `test_unrecognized_contribution_never_rises` red.
- **Live:** `face_source_device_derived_cameras` on `sensor.universal_room_automation_persons_in_house` lists the
  17 ids from §1 (or the subset seen this tick) and `face_source_skipped_person_sensors == 0`. Discrimination:
  flag not wired = derived list empty and skipped 17; device join broken for all cameras = derived list contains
  bare-suffix ids too (it must never, since the legacy path wins for them). Plus one interior observation: when
  playroom shows a person and its face sensor is fresh, `_last_area_raw_max_pre_cancel` for playroom's area is
  `count - 1`, not `count`.
- **Trip-wire:** the kill switch plus the counters; no new NM anomaly. Justification (review 1 §3.4): the only
  direction S7 can move is down, so the failure mode is a missed guest, not a false GUEST flip.

### D4. Engine tag from the device
One helper, `CameraResolver.face_engine_tag(device_id) -> str`: the family from `_infer_integration(device)`
(`frigate`, `unifiprotect` → `protect`, ...), no suffix parsing. S3 and S4 both call it; the suffix fallback at
`camera_census.py:3273-3281` and the `_has_f2` state probe at `:3339-3345` are removed. The synthetic leg's
`entity_sentinel` comes from the registry list for the stem (first entry), falling back to the legacy id.
**Rev 2 pin:** the helper returns the candidate's `integration_hint` (`"frigate"` / `"protect"`) whenever the
device is missing, `_infer_integration` returns empty/unknown, or the resolver is `None`. It never returns
`"unknown"` or `""` for a Frigate candidate. Reason: the synthetic leg copies an entity leg's engine only if it is in
`("frigate", "frigate2")` (`camera_census.py:3332`); an entity leg tagged `"unknown"` would make the synthetic leg
fall to its own branch, tag `"frigate"`, miss the dedup at `:3385`, give `n = 2`, and yield the spurious 0.75 boost.
Update the `:3332` membership test to the helper's output set in the same edit.
`_engine_tag` for `DetectionLeg` (`camera_resolver.py:1038`) is not touched.

Marginal-benefit note: a device-derived tag cannot say "frigate2" for a one-instance house; adding an instance
ordinal per config entry would rebuild the F1/F2 split nobody consumes. The plain family is the simple version and
captures the purpose (no `_2` dependence). Live labels change from `frigate2` to `frigate` in
`contributor_engines`; that is display only (§3.2). Parked alternative: per-entry instance suffix, revival trigger
"a second Frigate config entry appears on any install".

**Acceptance**
- **Verify (INV-2):** on the fixture, with an entity leg and a fresh latch entry for the same stem and the same
  name, `_resolve_face_legs` returns exactly one leg before and after. Mutation: point S4 back at the `_has_f2`
  probe → the test sees two legs and fails.
- **Verify:** egress replay of a single-camera named crossing yields `identity_confidence == 0.6` before and after;
  a two-camera crossing yields `0.9` before and after.
- **Verify (rev 2):** with the face entity's device absent from the device registry (resolver returns no device),
  entity leg + fresh latch on the same stem still give one leg.
- **Test:** `test_face_source_registry.py::test_entity_and_latch_legs_dedup_same_engine`,
  `::test_engine_fallback_is_hint_not_unknown`,
  `::test_engine_tag_from_device_not_suffix`, `::test_egress_confidence_unchanged_single_and_pair`;
  update any existing test asserting `engine == "frigate2"` on a FaceLeg (expected in
  `test_egress_identity_producer_d2b.py` and the sub-label bridge tests; builder lists every edit).
- **Live:** after a named crossing, `_egress_identity_last_attach.contributor_engines` (surfaced on the census
  sensor) contains `frigate`, not `frigate2`; `person_entry_exit_events.confidence` for new rows takes only values
  already seen pre-deploy (0.6 / 0.72 / 0.75 / 0.9). A 0.75 on a single-camera crossing with no Protect leg is the
  INV-2 break.

### D5. Optional face-name alias field
`CONF_FACE_NAME_ALIASES` (options flow, `async_step_camera_census`, next to `CONF_KNOWN_FACE_GUESTS`; same
`SelectSelector(multiple, custom_value)` widget). Entries are `FaceName=target`, where `target` is a tracked person
slug (with or without `person.`) or a `known_face_guests` name. In `_canonical_person_slug`, after the direct
tracked-slug match and before the first-token match: if the normalised name equals a normalised alias key, return
the target slug (or `guest:<head>` for a guest target). An entry whose target is neither is ignored with one
warning per entry. Default `[]`: the function is unchanged.
Use case on this house: F6 `Ojini` (operator decides alias of Oji or known guest; no default set by the build).
- **Verify:** `[]` → existing canonicalizer tests pass unchanged; `["Ojini=oji_udezue"]` → `"Ojini"` →
  `oji_udezue`; `["Boss=person.oji_udezue"]` resolves; an alias wins over a first-token ambiguity fail-closed; an
  alias to an unknown slug is ignored and warns once.
- **Test:** `test_face_source_registry.py::test_alias_empty_is_noop`, `::test_alias_maps_nickname`,
  `::test_alias_beats_ambiguous_head`, `::test_alias_bad_target_ignored`; options round-trip in the existing
  camera-census options test file.
- **Live:** options flow shows the field with an empty default; with no entry set,
  `person_entry_exit_events.person_id` values in the 24h post-deploy are a subset of those seen pre-deploy.

### D6. `last_camera` map: token-only filter
`_build_frigate_person_last_camera_map` (`camera_census.py:3470-3480`) filters `sensor.frigate_` prefix and
`_last_camera[_2]` suffix **before** the `sensor_global_face` token test, so a renamed per-person sensor drops out.
Remove the entity_id filters; keep the token test and the prefer-bare rule. Same 6 entries on this house (probe).
- **Test:** `test_face_source_registry.py::test_last_camera_map_survives_rename`,
  `::test_last_camera_map_same_on_live_fixture`.
- **Live:** INFO log `D2 frigate last_camera map built: 6 entries` at first build after restart.

### D7. Docs
Manual: fix the stale line refs (§0.2.1), state the registry-first rule in §1.1, record the 17-camera skip and its
shadow flag, the device-derived engine tag, the alias field, and the Protect triage (§6). README Validated table per
CLAUDE.md after deploy.

---

## 6. Protect: dropped from scope, three-bucket triage of the dead lookups

The HA `unifiprotect` integration exposes no recognized-face-name entity (audit §2.2; no registry or restore-state
row for `*_face_recognized[_2]`). This card does not discover Protect face sources.

| Item | file:line | Bucket | Reason |
|---|---|---|---|
| `sensor.<base>_face_recognized[_2]` candidates in `_resolve_face_legs` | `camera_census.py:3209-3210` | **KEEP + DOCUMENT** | Dead live, but it is the consumption contract of the parked `D1-PROTECT-FACE-BRIDGE-ADDON-1` (a URA-owned bridge picks its own entity name, so a name lookup is right for it). `test_egress_identity_producer_d2b.py` uses it to prove the 0.75 same-camera path. Add a comment: "dead until D1-PROTECT-FACE-BRIDGE-ADDON-1 revives". |
| `_face_recognized` in `_FACE_SUFFIXES` | `camera_resolver.py:247` | KEEP + DOCUMENT | Same bridge contract, capability side. |
| `_face_detected`, `_smart_detect_face`, `_ai_face` in `_FACE_SUFFIXES` | `camera_resolver.py:248-250` | KEEP + DOCUMENT | No live entity here; generic face-capability names for other integrations on other installs. Harmless when absent. Comment as "no live match on reference install 2026-11". |
| Protect-face docstring lines | `camera_census.py:3185` | KEEP + DOCUMENT | Reword to "Protect (parked bridge, no live source)". |

**DELETE bucket: empty.** Nothing here is both useless and a footgun.

---

## 7. Knobs

| Knob | Rung | Default | Why this rung | Kill-switch semantics |
|---|---|---|---|---|
| `FACE_SOURCE_REGISTRY_DISCOVERY_ENABLED` | 1, module const (`const.py`) | `True` | Changing face-source discovery should need review; no operator reason to turn it live. | `False` = pre-build pattern path everywhere (S1, S2, S9, S10, D4 helper falls back to `_engine_tag`). |
| `FACE_SOURCE_INCLUDE_DISAMBIGUATED_PERSON_SENSORS` | 1, module const | `True` (rev 2; `False` if the D0 gate fails) | Changes census trust inputs; turning it should need review, not a dashboard tap. | `False` = legacy skip, counted + listed. `True` = act, counted + listed. |
| `CONF_FACE_NAME_ALIASES` | 2, options flow | `[]` | Per-install structure, set rarely, like `known_face_guests`. | Empty = no aliasing. |

No other behavioral numbers are introduced. The diagnostic list is bounded by the camera count; no cap.

---

## 8. Non-goals
- Protect face-name discovery or a Protect producer (`D1-PROTECT-FACE-BRIDGE-ADDON-1` stays parked).
- Changing what a fresh face means to S7 (`guest:*` faces subtract like residents today; review 1 F-5 card).
- Separating `guest:*` from the resident set on the RAW fuse site (`_cross_correlate_persons`, `:2496-2505`); the
  enhanced recompute already does it (review 1 F-6, pre-existing, non-enhanced installs only).
- Scoping S6 corroboration to interior cameras (exterior faces already corroborate via the 12 bare cameras).
- `DetectionLeg` engine tags (`camera_resolver.py:1038`) and perimeter engine strings.
- `_resolve_face_producer_health_entity` hard-coded `sensor.frigate_status[_2]` (`camera_census.py:4092-4130`); same
  bug class, separate card if wanted.
- Frigate zone devices (none on this install; audit §7).
- Any change to face freshness windows, confidence tiers, the latch TTL or the not_home veto.
- Any new entity. Diagnostics go on the existing census sensor's attributes.
- Raw `_person_occupancy` suffix tests that derive person-detection legs or engines, not face sources:
  `perimeter_alert.py:487`, `:507`, `:519`, `:553`, `:2032`; `transit_validator.py:2226`;
  `optimization.py:2654`, `:3304` (already `_2`-tolerant); `camera_census.py:626`, `:945`, `:976`, `:1134`
  (626 and 1134 already strip `_N`). Same smell, different
  value; card separately if a portability sweep of person legs is wanted.

---

## 9. Concurrency with the perimeter build (v5.107.0)

`feature/perimeter-fp-build` is in flight, uncommitted in `.claude/worktrees/agent-ae7aefbc986e55f79` (15 files,
+1466/-31). Overlap:

1. **New consumer of the face resolver.** `perimeter_alert._known_identity_for` (D10.5) calls
   `census._resolve_face_legs(cam_key)`, `census._canonical_person_slug` and `census._get_known_face_guests` to
   decide a **security de-escalation** (LOW for a known person). After merge it is consumer S12c, and INV-1 must hold
   for it. The INV-1 equivalence test must include a D10.5 case.
2. **Engine strings.** The build adds `perimeter_fp_gates.nvr_family` (prefix `frigate*` / `protect*`). D4's
   `frigate2` → `frigate` stays inside the `frigate*` family. The builder confirms `nvr_family` is not fed
   `FaceLeg.engine` in a way that compares exact strings.
3. **Same files.** Both touch `const.py`, `config_flow.py` (both add to the camera-census step: the perimeter build
   adds `perimeter_zone_sensors`), `sensor.py` (census attributes), `strings.json` / `translations/en.json`,
   `perimeter_alert.py` and `IDENTITY_FUSION_CAMERAS_MANUAL.md`.
4. **D10.5's alias exposure.** D5 changes what `_canonical_person_slug` returns when an alias is set, which feeds the
   D10.5 `known` set. Default empty keeps it unchanged; the README must say an alias widens D10.5's known set.

**Rule:** do not branch until v5.107.0 is merged to develop. Branch then, re-run the §4 grep and the D1 probe on the
merged tree, and add any new `_resolve_face_legs` / `_resolve_face_entity_id` caller to §4 before the build starts.

---

## 10. Tier, review, cards

**Tier 2-DB (three framing-disjoint code reviews + live validation), one adversarial plan review before build.**
Trigger: change to a shared primitive (the face resolver) read by 8 consumers including census guest inference and,
after the perimeter merge, a security de-escalation. Standing policy elevates regression-prone shared-primitive work.
Not Tier 3: discovery is a no-op on this house (INV-1); the one behavior change (D3) can only lower the interior
unrecognized count (INV-4), is behind a review-gated constant, and nothing on the cost or HVAC/battery path is
touched. If the plan review finds a reachable INV-1 break that the shadow flag
does not contain, re-tier to 3.
Review framings: A = local correctness of the index, ordering and fallback; B = cross-consumer equivalence
(census, egress, perimeter D10.5, presence) + resolver rebuild/registry-event lifecycle; C = per-site mutation
(S1, S2, S4, S5-S8, S9, and the D4 dedup), each site's bypass must turn a named test red.

Cards: this plan moves `FACE-SOURCE-REGISTRY-DISCOVERY-1` to `planned`. ~~FACE-SOURCE-SKIP-FIX-FLIP-1 (14-day
measurement)~~ rev 2: folded into D0 + D3 of this cycle and marked `declined` on the board (a forward 14-day count
is a soak; the same question is answered from recorder history in D0). Review C adds the D3 sites (S5-S8 device-join
branch) and the D4 fallback to its mutation list. Follow-up cards from review 1: F-5 (`guest:*` faces subtract in
S7), F-6 (raw fuse site counts `guest:*` as resident on non-enhanced installs).

## 11. Plan-completion accounting (filled after build, branch `feature/face-source-registry`)

Pre-build re-check on the merged tree (develop `b9c1b3d0`, v5.107.0 in): the §4 grep found two stem callers
in `perimeter_alert.py` (`:1673` alert naming, `:4894` D10.5 `_known_identity_for`); neither reads
`FaceLeg.engine`. The falsifier re-ran on the 2026-11-08 22:58 registry: `agree=12`, 17 SKIP, (c) True. D0 result:
AUDIT §8 (gate PASS, default True).

| Item | Status | Notes |
|---|---|---|
| D0 | done (pre-build) | AUDIT §8. upstairs_hall's Frigate sensor is not in the interior list, so S7 changes for playroom only. |
| D1 | done | `scripts/probe_face_source_registry.py` (+ `--emit-fixture`), fixture `quality/tests/fixtures/face_source_registry_2026_11.json` (188 entities, 64 devices; registry fields only, no MACs; includes the Protect camera / person entities so the stem tests see real cross-integration stems). |
| D2 | done, one deviation | **Deviation:** `face_name_entities_for_stem` uses the RAW stem only and returns a suffixed face sensor only when its base equals the stem. The plan's raw-then-stripped chain broke INV-1 on the live fixture (10 stems, e.g. `garage_a_2`, `foyer`, reached a face sensor the pattern path never names). Renamed sensors still resolve through the device. S9 key: the face entity's own base (legacy-identical by construction), falling back to the camera.* stem for a renamed sensor (plan said camera-derived; same 29/29). |
| D3 | done, one split | S5-S7 live (default True). **S8 split out** behind `FACE_SOURCE_PRESENCE_ARRIVAL_DISAMBIGUATED` = False: S8 dispatches `SIGNAL_PERSON_ARRIVING(camera_face)`, which `security_lock_regime.on_person_arriving` turns into `_release` (garage lockouts) and `_away_release` (unlocks `lock.master_bedroom_lock` for away-lock persons Ezinne / Oji, live config). Review 1 §3.4 missed this consumer. Operator decides. |
| D4 | done | Engine = device family, hint on any miss; S3 + S4 share `_face_leg_engine`. `test_egress_identity_producer_d2b.py::test_face_legs_2_engine_tagging` updated (now asserts `frigate`, and `frigate2` with the kill switch off). |
| D5 | done | Field is Advanced-only (the Simple camera-census step is pinned at 7 fields), fresh-read, added to `INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS` (no parent reload on save). Presence `_find_person_entity_from_face` also consults it (the Oji -> `person.oji_udezue` case). Shipped empty. |
| D6 | done | Token-only filter when discovery is on. |
| D7 | done | Manual §1.1 / §4.1 / §4.2 / §5.4, presence state-of-play status line, README_v5.107.1. |
| F-5 (optional fold) | not folded | Not small in risk terms: subtracting only for resident slugs would RAISE S7 (new direction, opposite of INV-4) and needs its own measurement of known-guest-only interior ticks. Stays a card. |
| F-6 | not in scope | Card. |
