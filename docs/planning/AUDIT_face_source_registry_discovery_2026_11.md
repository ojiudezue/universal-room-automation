# AUDIT: face-source discovery via the HA registries (FACE-SOURCE-REGISTRY-DISCOVERY-1)

Probe date: 2026-11-08 (CDT). Read-only. Sources: `/Users/okosisi/ha-config/.storage/core.entity_registry` + `core.device_registry` (Samba), `ssh ha` reads of `/config/custom_components/frigate/`, the unifiprotect core source on GitHub (not on the HA host), and URA source in the repo.
This is an investigation, not a plan. Card is `pre_planning`; no HVAC/presence STATE_OF_PLAY docs apply (identity domain). I read IDENTITY_FUSION_CAMERAS_MANUAL.md §1 and §2.3 only for the Protect face facts, not the whole manual.

## 1. Answer first

1. **Frigate: registry discovery is clean and stable.** Every face sensor is `platform=frigate`, `unique_id = <entry_id>:sensor_recognized_face:<cam_name>`, and sits on the SAME device as that camera's `camera.*` entity and its `binary_sensor.*_person_occupancy*`. All 29 per-camera face sensors have a same-device camera entity and a same-device person-occupancy sensor. I checked all 29; there are zero exceptions.
2. **Protect: there is nothing to discover.** The HA `unifiprotect` integration exposes no recognized-face-name entity. Face is only an event type (`face`) in `event.*_smart_detection`, and the event attributes carry only event id, detected types and source. The `sensor.<stem>_face_recognized[_2]` entity that URA looks for (`camera_census.py:3209-3210`, `camera_resolver.py:247`) has **no registry entry and no restore-state entry anywhere on this install**. It is a speculative name for a "D1 bridge" that does not exist live. The manual says the Protect name path is a dead webhook (IDENTITY_FUSION_CAMERAS_MANUAL.md:39, :154-165).
3. **Face name to person mapping is not a registry or HA person link.** It is name-matching against the integration option `tracked_persons` (first-token match), plus an optional `known_face_guests` list. See §5.
4. **Recommendation:** keep the pattern as a fallback, add a registry-first resolver for Frigate keyed on `(platform=frigate, unique_id segment == "sensor_recognized_face")` and linked by `device_id`. For Protect, do not build a discovery path; there is no source. Protect work belongs in a different card (a producer, not a discoverer).

## 2. Live registry evidence

### 2.1 Frigate per-camera face sensors (29 entities, one config entry `01KM239Z8ZQWQTN1D9CV5JRA7V`)
Sample rows (registry fields verbatim):

| entity_id | platform | unique_id | translation_key | original_name | device name | device identifiers |
|---|---|---|---|---|---|---|
| sensor.doorbell_lite_last_recognized_face_2 | frigate | `01KM239Z8ZQWQTN1D9CV5JRA7V:sensor_recognized_face:doorbell_lite` | None | Last Recognized Face | Doorbell Lite | `[frigate, 01KM239Z8ZQWQTN1D9CV5JRA7V:doorbell_lite]` |
| sensor.armcrest_last_recognized_face_2 | frigate | `...:sensor_recognized_face:ArmCrest` | None | Last Recognized Face | ArmCrest | `[frigate, ...:armcrest]` |
| sensor.madroneptultra_last_recognized_face | frigate | `...:sensor_recognized_face:MadronePTUltra` | None | Last Recognized Face | MadronePTUltra | (lowercased slug) |

- 23 have the `_2` suffix, 6 do not (`madroneptultra`, `reolinkpatio`, `sonoffwindow`, `study_a_panel`, `kitchen_panel`, `up_hallway_panel`). Mixed in one install, so the suffix is not a rule.
- `translation_key` is **None** on all of them; `original_name` is constant "Last Recognized Face". Not usable as a discriminator beyond the name string.
- Device model field is the Frigate version string (`5.15.6/0.18.2-cfa08c5`), not a hardware model. Identifiers are a single `("frigate", "<entry_id>:<slug(cam)>")`, `connections` empty, `via_device_id` = the parent "Frigate" server device (`b06f4308...`, identifiers `[frigate, 01KM239Z...]`).
- Note the identifier uses the **slugified** camera name (`reolinkstudybporchptz`) while the unique_id uses the **raw** Frigate cam name (`ReolinkStudyBPorchPTZ`). Source: `get_frigate_device_identifier` slugifies (`/config/custom_components/frigate/__init__.py:102-108`); `get_frigate_entity_unique_id` does not (`__init__.py:130-134`).
- Per-camera device holds ~45 entities. For `doorbell_lite` (device `bd2dd0c8...`): `camera.doorbell_lite` (unique_id `...:camera:doorbell_lite`), `binary_sensor.doorbell_lite_person_occupancy_2` (`occupancy_sensor:doorbell_lite_person`), `sensor.doorbell_lite_last_recognized_face_2` and `..._plate_2`. Same pattern for `back_yard`. `camera.garage_a_2` has unique_id `...:camera:garage_a`.
- A **different** Frigate entity family also matches the loose word "face": 6 `sensor_global_face` sensors (`sensor.frigate_<person>_last_camera[_2]`, unique_id `...:sensor_global_face:<Name>`), attached to the SERVER device (not a camera). These are per-person "last camera seen" sensors, and the sensor's value is a camera name, not a person name (`/config/custom_components/frigate/sensor.py:1555-1612`, `device_info` identifiers = server). They are not face-name sources for a camera and a name-substring scan could confuse them. A registry discriminator on `sensor_recognized_face` excludes them.

### 2.2 Protect (config entry `01K1SBX7CWG96MAGXTQMFRS5EW`, NVR "Phalanax NVR Pro", model UNVR Pro, identifiers `[unifiprotect, 0CEA1429E700]`)
- No entity with face / recognized in the name, unique_id or translation_key exists. The face-related Protect entities are:
  - `event.<...>_smart_detection`: unique_id `<MAC>_smart_detection` (e.g. `28704E18FC13_smart_detection` for Garage A), `translation_key=smart_detection`, `capabilities.event_types = [person, animal, vehicle, license_plate, package, face, car, pet]`. Present on 19 cameras.
  - `binary_sensor.*_person_detected`: unique_id `<MAC>_smart_obj_person`, `translation_key=person_detected` (19).
  - `event.*_vehicle` (`<MAC>_vehicle`), `event.*_doorbell` etc.
- Protect camera devices: `identifiers=[]`, `connections=[["mac","04:18:d6:a2:92:65"]]` (G5 Bullet), `via_device_id` = the NVR device. MAC is the stable link; the unique_id prefix is the same MAC uppercased without colons.
- Upstream source: `unifiprotect/event.py` `smart_detection` description (`translation_key="smart_detection"`, `event_types=_SMART_OBJECT_EVENT_TYPES`), fired attributes are `event_id`, `smart_detect_types`, optional `event_source`; no name field. Only `license_plate` (vehicle entity) carries a matched name. Source: https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/components/unifiprotect/event.py (read via WebFetch, so summarized, not full text; the core source is not present on the HA host: `/usr/src/homeassistant/...` absent).
- `sensor.*_face_recognized[_2]`: grep of `core.entity_registry` and `core.restore_state` for ids ending `_face_recognized[_2]` returns nothing. A yaml/py grep on the HA host for `face_recognized` outside URA also found nothing in config. Unknown whether any bridge was ever deployed; none is live.

## 3. How Frigate creates the entity (stable contract)
`/config/custom_components/frigate/sensor.py`:
- Created only when Frigate >= 0.16, global `face_recognition.enabled`, and the camera has `face_recognition.enabled` (`sensor.py:205-217`). So "face-capable camera, no face sensor" is a legitimate state (camera not enrolled), not always a discovery failure. Diagnostics must separate those.
- `FrigateRecognizedFaceSensor`: unique_id from `get_frigate_entity_unique_id(entry_id, "sensor_recognized_face", cam_name)` (`sensor.py:1116-1122`); device_info identifiers = camera device plus `get_frigate_via_device` (server); `name` property hard-coded "Last Recognized Face" (`sensor.py` ~1137-1140); state = titlecased recognized name (`native_value`), reset to "None" after 60 s (`sensor.py:1099-1112`). It listens to `<topic_prefix>/tracked_object_update` with `type=="face"` (`sensor.py:1081-1087`).
- Stable across installs: the `sensor_recognized_face` type token in the unique_id (integration-defined, not user-renamable), `platform=frigate`, `device_id` shared with the camera entity. Unstable: entity_id (user/HA rename, `_2`/`_N` disambiguation after re-adding the integration), `original_name` is stable but translation_key is absent, the camera-name casing between unique_id and device identifier.
- `unique_id` format is explicitly noted in the URA code as external ("Does NOT construct Frigate unique_ids", `camera_census.py:3146-3147`). Parsing the second `:` segment from an existing registry row is reading, not constructing, and is acceptable; constructing one is not.

## 4. URA code that string-matches (the full list)
Existing registry use is partial. The camera-to-device link is already registry based (CameraResolver). The face-sensor selection is still by entity_id suffix.

| Site | What it does | Pattern |
|---|---|---|
| `camera_census.py:3135-3178` `_resolve_face_entity_id(base_name)` | builds `sensor.<base>_last_recognized_face` then `..._face_2`, first live state wins | string-built, hard-codes the two Frigate variants |
| `camera_census.py:3180-3210` `_resolve_face_legs(base_name)` | candidate list of four ids: Frigate `_last_recognized_face[_2]`, Protect `_face_recognized[_2]` | string-built; engine hint hard-coded per suffix; `_2` => engine tag via `resolver._engine_tag` |
| `camera_census.py:3339-3351` (inside `_resolve_face_legs`' latch branch) | builds `_last_recognized_face_2` / bare ids again to pick the engine tag | string-built |
| `camera_census.py:3554-3592` `_get_face_recognized_persons` | for each Frigate `CameraInfo` whose person sensor endswith `_person_occupancy`, strips it to get `base_name`, then `_resolve_face_entity_id` | derives the face sensor from the occupancy entity_id |
| `camera_census.py:3595-3640` `_get_face_recognized_persons_fresh` | same derivation | same |
| `camera_census.py:5017-5088` `_compute_face_latch_stems` | registry walk: devices from the resolver's Frigate-stem index, then entity_id endswith `_last_recognized_face_2` / `_last_recognized_face` | half-registry: device link by registry, sensor pick by suffix |
| `camera_resolver.py:245-252` `_FACE_SUFFIXES` and `:1405-1432` | `sensor`/`binary_sensor` endswith any of `_face_recognized`, `_face_detected`, `_smart_detect_face`, `_ai_face`, `_last_recognized_face` sets `face_cap` (USABLE/AMBIGUOUS) | suffix list; note `_2` is stripped by `_has_any_suffix` helpers before matching |
| `camera_census.py:1133-1143`, `:626-665`, `:945-976` | Frigate camera / stem derivation by `_person_occupancy` suffix | pattern |
| `camera_census.py:4092-4130` `_resolve_face_producer_health_entity` | already registry-checked, but candidate ids are hard-coded (`sensor.frigate_status[_2]`) | list of four ids |
| `camera_resolver.py:533` Frigate stem index | `identifiers` second segment after the last `:` | uses the slug in the device identifier, which is the right layer |

Two latent portability bugs found while mapping:
- `_get_face_recognized_persons` / `_fresh` only consider Frigate cameras whose person sensor endswith `_person_occupancy`. If the occupancy entity is renamed, that camera yields no face sensor silently. `_face_lookup_missing_count` is incremented only on the resolve miss, not on a skipped camera.
- The two helper functions each re-derive stem and iterate Frigate cameras instead of consulting one cached index.

## 5. Face name to HA person: today
There is **no HA `person.*` entity mapping and no per-face-name config field**. It is a name canonicalizer:
- `camera_census.py:3681-3779` `_canonical_person_slug(name)`: lowercases, collapses spaces and hyphens to `_` (CENSUS-NAME-SPACE-DEDUP-1, `:3721-3731`), then
  1. direct match against `tracked_persons` slugs (`:3733-3735`);
  2. else first-token (head) match against each tracked slug's first token; unique match wins; if more than one tracked slug shares the head, returns "" and warns once (fail-closed) (`:3736-3752`);
  3. else `guest:<head>` if the head matches an entry in the `known_face_guests` option (`:3753-3774`, `_get_known_face_guests` at `:3770+`, const `CONF_KNOWN_FACE_GUESTS`);
  4. else pass-through lowercased identifier.
- `tracked_persons` source: integration entry data+options key `"tracked_persons"` (`camera_census.py:3672`; list of `person.<slug>`, prefix stripped at `:3675`).
- Hard-coded assumption: Frigate face-library names are first names (or the Protect display name "Oji Udezue"); a library name that is not a first token of any tracked slug yields an unmapped passthrough. This means a face library labelled with nicknames in another home maps nothing silently. An explicit face-name to person map (config field) would remove that assumption; the card already plans that. Nothing currently exists (no `CONF_FACE_*MAP` found in this pass; I did not grep const.py exhaustively for alternates, so treat "none exists" as to be confirmed by the planner's prior-art scan).

## 6. Recommendation

### 6.1 Registry lookup (Frigate)
Build a registry-backed index once per resolver rebuild (CameraResolver already rebuilds on registry updates; reuse `_frigate_stem_to_device_ids`, `camera_resolver.py:533`):
1. Iterate entity registry entries with `platform == "frigate"`, `domain == "sensor"`, `unique_id.split(":")[1] == "sensor_recognized_face"`. Result: `device_id -> face entity_id`. Respect `disabled_by`.
2. Link to a camera: **same `device_id`** as the `camera.*` entity whose unique_id segment 2 == `camera` (verified 29/29). Do not use `via_device` (that points to the Frigate server; useful only to group everything under one install) and there are no zone devices involved for this entity (zone devices would have different identifiers; the 29 face sensors sit on camera devices only. I did not enumerate Frigate zone-device entities, other types of entity, beyond the counts above).
3. Link to the existing census `CameraInfo`: `CameraInfo.entity_id` is the person binary_sensor; look up that entity's `device_id` in the registry and join to step 1 by `device_id`. This removes the dependence on `_person_occupancy` suffix and on `_2`.
4. Fallback only when the registry yields no face sensor for that device: current suffix candidates (`_resolve_face_entity_id` behaviour unchanged).
5. Engine tag: derive from the face entity's device (`resolver._infer_integration`) instead of `entity_id.endswith("_2")` (`camera_census.py:3339-3351` and `:3269-3281` fallbacks).

Falsifiers to run at plan time: (a) disable the name pattern and confirm the registry path alone yields the same 29 stems this house resolves today; (b) rename one face sensor's entity_id in a test registry and confirm resolution still works; (c) a Frigate entry re-added (new `entry_id` prefix) still matches because only the `sensor_recognized_face` token is used, not the prefix.

### 6.2 Diagnostics flag
For each Frigate camera device in the registry: has a `camera` entity but no `sensor_recognized_face` entity => "face-capable? no face source". Caveat from §3: that is expected when the camera is not enrolled for face recognition in Frigate. Suggest reporting counts: cameras with a face sensor, cameras without, and a name-pattern-only match (mismatch with registry). Surface via existing diagnostics rather than a new sensor (a new sensor needs the prior-art scan).

### 6.3 Protect
No face-name entity to discover. Options are outside this card: (i) a Protect face-name producer (not available via HA integration, webhook currently empty per manual §2.3), (ii) the `event.*_smart_detection` `face` event type as a face-**detected** (unnamed) signal; its unique_id `<MAC>_smart_detection` joins to the Protect camera device by device_id. The code already lists `_face_detected` / `_smart_detect_face` / `_ai_face` as detection-only suffixes (`camera_census.py:3189-3192`); the live Protect fleet has none of these, so those are dead patterns here. I recommend dropping the "discover Protect face-name sensors" scope from this card and carding the Protect producer separately if still wanted. Evidence: registry has no such entity; upstream event.py exposes no name.

### 6.4 What stays a config field
Face-name to person mapping: keep explicit config (current first-token inference is fragile for non-first-name libraries; see §5).

## 7. Unknowns and limits
- Did not read `unifiprotect/entity.py` (unique_id construction) or `sensor.py`; unique_id shapes above come from the live registry only. Upstream summary came through a summarizing fetch, so quote-level accuracy is limited to what the fetch returned.
- Did not verify the Protect "D1 bridge" history (which cycle meant to create `sensor.<stem>_face_recognized`); only that nothing exists live now.
- Did not enumerate Frigate zone devices; the registry shows only 30 `frigate` devices with a single identifier each (29 cameras + server), consistent with no separate zone devices for this install, but I did not list them by name.
- No HA state was changed; no repo files edited except this report; not committed.
